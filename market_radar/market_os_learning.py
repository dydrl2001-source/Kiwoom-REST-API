"""Market OS shadow-learning worker.

Captures live multi-axis assessments and resolves ex-post outcomes from already
stored market data. It NEVER places orders and it never rewrites rule thresholds
automatically. Learning runs in shadow mode until a segment has enough samples
to be statistically worth reviewing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
import json
import math
import os
import statistics
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from flow_store import desk_payload
from flow_core import dt as parse_dt
from market_os_rule_engine import VERSION as RULE_VERSION

DB=os.getenv("DATABASE_URL","")
POLL=max(30,int(os.getenv("MARKET_OS_LEARNING_POLL_SECONDS","60")))
KST=ZoneInfo("Asia/Seoul")

SCHEMA=r"""
CREATE TABLE IF NOT EXISTS market_os_assessment_snapshots (
    snapshot_time       TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    stock_name          TEXT,
    rule_version        TEXT NOT NULL,
    watch_tier          TEXT NOT NULL,
    radar_score         SMALLINT,
    theme_score         SMALLINT,
    setup_score         SMALLINT,
    catalyst_grade      TEXT,
    trigger_state       TEXT,
    market_stance       TEXT,
    session_bucket      TEXT,
    market_theme        TEXT,
    event_type          TEXT,
    current_price_krw   NUMERIC,
    change_pct          DOUBLE PRECISION,
    query_rank          INTEGER,
    trade_rank          INTEGER,
    interval_turnover_krw NUMERIC,
    five_min_turnover_krw NUMERIC,
    burst_multiple      DOUBLE PRECISION,
    theme_share_change_pp DOUBLE PRECISION,
    chart_state         TEXT,
    micro_trade_value_15s_krw NUMERIC,
    micro_buy_share_15s DOUBLE PRECISION,
    micro_tick_count_15s INTEGER,
    micro_gap_count_15s INTEGER,
    micro_strength      DOUBLE PRECISION,
    micro_buy_ratio     DOUBLE PRECISION,
    axis_reasons        JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_flags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ref        JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_time, stock_code, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_code_time
    ON market_os_assessment_snapshots(stock_code, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_tier_time
    ON market_os_assessment_snapshots(watch_tier, snapshot_time DESC);
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_trade_value_15s_krw NUMERIC;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_buy_share_15s DOUBLE PRECISION;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_tick_count_15s INTEGER;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_gap_count_15s INTEGER;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_strength DOUBLE PRECISION;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_buy_ratio DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS market_os_assessment_outcomes (
    assessment_time     TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    reference_price_krw NUMERIC NOT NULL,
    outcome_price_krw   NUMERIC,
    return_pct          DOUBLE PRECISION,
    mfe_pct             DOUBLE PRECISION,
    mae_pct             DOUBLE PRECISION,
    outcome_time        TIMESTAMPTZ,
    outcome_source      TEXT,
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assessment_time, stock_code, rule_version, horizon)
);
CREATE INDEX IF NOT EXISTS idx_market_os_outcome_horizon
    ON market_os_assessment_outcomes(horizon, assessment_time DESC);

CREATE TABLE IF NOT EXISTS market_os_learning_segments (
    segment_type        TEXT NOT NULL,
    segment_value       TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    samples             INTEGER NOT NULL,
    distinct_stocks     INTEGER NOT NULL DEFAULT 0,
    distinct_days       INTEGER NOT NULL DEFAULT 0,
    sample_basis        TEXT NOT NULL DEFAULT 'RAW',
    avg_return_pct      DOUBLE PRECISION,
    median_return_pct   DOUBLE PRECISION,
    positive_rate       DOUBLE PRECISION,
    avg_mfe_pct         DOUBLE PRECISION,
    avg_mae_pct         DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (segment_type, segment_value, horizon)
);

ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS distinct_stocks INTEGER NOT NULL DEFAULT 0;
ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS distinct_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS sample_basis TEXT NOT NULL DEFAULT 'RAW';

CREATE TABLE IF NOT EXISTS market_os_interaction_edges (
    segment_type             TEXT NOT NULL,
    segment_value            TEXT NOT NULL,
    horizon                  TEXT NOT NULL,
    parent_type              TEXT NOT NULL,
    parent_value             TEXT NOT NULL,
    sample_basis             TEXT NOT NULL,
    child_samples            INTEGER NOT NULL,
    child_stocks             INTEGER NOT NULL,
    child_days               INTEGER NOT NULL,
    comparator_samples       INTEGER NOT NULL,
    comparator_stocks        INTEGER NOT NULL,
    comparator_days          INTEGER NOT NULL,
    child_avg_return_pct     DOUBLE PRECISION,
    comparator_avg_return_pct DOUBLE PRECISION,
    delta_avg_return_pct     DOUBLE PRECISION,
    child_positive_rate      DOUBLE PRECISION,
    comparator_positive_rate DOUBLE PRECISION,
    delta_positive_rate_pp   DOUBLE PRECISION,
    child_avg_mfe_pct        DOUBLE PRECISION,
    comparator_avg_mfe_pct   DOUBLE PRECISION,
    delta_mfe_pct            DOUBLE PRECISION,
    child_avg_mae_pct        DOUBLE PRECISION,
    comparator_avg_mae_pct   DOUBLE PRECISION,
    delta_mae_pct            DOUBLE PRECISION,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(segment_type,segment_value,horizon)
);

CREATE TABLE IF NOT EXISTS market_os_walk_forward_windows (
    segment_type             TEXT NOT NULL,
    segment_value            TEXT NOT NULL,
    horizon                  TEXT NOT NULL,
    window_name              TEXT NOT NULL,
    start_day                DATE,
    end_day                  DATE,
    samples                  INTEGER NOT NULL,
    distinct_stocks          INTEGER NOT NULL DEFAULT 0,
    distinct_days            INTEGER NOT NULL DEFAULT 0,
    avg_return_pct           DOUBLE PRECISION,
    median_return_pct        DOUBLE PRECISION,
    positive_rate            DOUBLE PRECISION,
    avg_mfe_pct              DOUBLE PRECISION,
    avg_mae_pct              DOUBLE PRECISION,
    comparator_samples       INTEGER,
    comparator_stocks        INTEGER,
    comparator_days          INTEGER,
    comparator_avg_return_pct DOUBLE PRECISION,
    comparator_positive_rate DOUBLE PRECISION,
    comparator_avg_mae_pct   DOUBLE PRECISION,
    delta_avg_return_pct     DOUBLE PRECISION,
    delta_positive_rate_pp   DOUBLE PRECISION,
    delta_mae_pct            DOUBLE PRECISION,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(segment_type,segment_value,horizon,window_name)
);

CREATE TABLE IF NOT EXISTS market_os_learning_status (
    id                  INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
    updated_at          TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL,
    last_snapshot_at    TIMESTAMPTZ,
    last_outcome_at     TIMESTAMPTZ,
    assessments_total   BIGINT NOT NULL DEFAULT 0,
    outcomes_total      BIGINT NOT NULL DEFAULT 0,
    note                TEXT
);
"""


def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
                           options="-c statement_timeout=20000 -c lock_timeout=3000")


def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
    return cur.fetchone()["name"] is not None


def ensure_schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419071)")
        cur.execute(SCHEMA)


def session_bucket(ts):
    local=ts.astimezone(KST)
    t=local.time()
    if t < dtime(9,0):
        return "PRE"
    if t < dtime(9,20):
        return "OPEN_20"
    if t < dtime(11,30):
        return "MORNING"
    if t < dtime(13,30):
        return "MIDDAY"
    if t < dtime(14,50):
        return "AFTERNOON"
    if t <= dtime(15,30):
        return "CLOSE"
    return "AFTER"


def safe_num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def current_microstructure(codes,sample):
    """Use only fully closed 5-second buckets at/before the assessment."""
    codes=[x for x in codes if x]
    if not codes:return {}
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_realtime_5s_bars"):
            return {}
        end=sample-timedelta(seconds=5)
        start=end-timedelta(seconds=15)
        cur.execute("""SELECT stock_code,
                              SUM(trade_value_krw) AS tv,
                              SUM(buy_volume) AS buy,
                              SUM(sell_volume) AS sell,
                              SUM(tick_count) AS ticks,
                              SUM(gap_count) AS gaps
                       FROM market_realtime_5s_bars
                       WHERE stock_code=ANY(%s) AND bucket_time>=%s AND bucket_time<=%s
                       GROUP BY stock_code""",(codes,start,end))
        out={}
        for r in cur.fetchall():
            buy=safe_num(r["buy"]) or 0;sell=safe_num(r["sell"]) or 0;den=buy+sell
            out[r["stock_code"]]={
                "trade_value_15s_krw":safe_num(r["tv"]),
                "buy_share_15s":buy/den if den else None,
                "tick_count_15s":int(r["ticks"] or 0),
                "gap_count_15s":int(r["gaps"] or 0),
                "strength":None,"buy_ratio":None,
            }
        cur.execute("""SELECT DISTINCT ON(stock_code)
                              stock_code,last_strength,last_buy_ratio,bucket_time
                       FROM market_realtime_5s_bars
                       WHERE stock_code=ANY(%s) AND bucket_time<=%s
                       ORDER BY stock_code,bucket_time DESC""",(codes,end))
        for r in cur.fetchall():
            x=out.setdefault(r["stock_code"],{
                "trade_value_15s_krw":None,"buy_share_15s":None,
                "tick_count_15s":0,"gap_count_15s":0,"strength":None,"buy_ratio":None
            })
            x["strength"]=safe_num(r["last_strength"]);x["buy_ratio"]=safe_num(r["last_buy_ratio"])
        return out


def capture_assessments():
    payload=desk_payload(include_tracking=False)
    if not payload.get("recent_trade_count"):
        return 0,None
    sample=parse_dt(payload.get("sample_time"))
    if not sample:
        return 0,None
    age=(datetime.now(timezone.utc)-sample).total_seconds()
    if age < -60 or age > 180:
        return 0,None
    snap=sample.replace(microsecond=0)
    micro=current_microstructure([x.get("code") for x in payload.get("market_os_watchlist",[])],sample)
    rows={r.get("code"):r for r in payload.get("rows",[])}
    regime=payload.get("market_regime") or {}
    items=[]
    for x in payload.get("market_os_watchlist",[]):
        code=x.get("code")
        r=rows.get(code) or {}
        px=safe_num(r.get("price_krw"))
        if not code or px is None or px<=0:
            continue
        evidence={
            "market_regime_snapshot":regime.get("snapshot_time"),
            "chart_snapshot":(r.get("chart") or {}).get("snapshot_time"),
            "research_id":((r.get("research") or {}).get("id")),
            "research_completed_at":((r.get("research") or {}).get("completed_at")),
            "sample_time":payload.get("sample_time"),
            "source":"flow_desk"
        }
        items.append((
            snap,code,x.get("name"),RULE_VERSION,x.get("watch_tier"),
            x.get("radar_score"),x.get("theme_score"),x.get("setup_score"),
            x.get("catalyst_grade"),x.get("trigger_state"),x.get("market_stance"),
            session_bucket(snap),x.get("market_theme"),x.get("event_type"),px,
            safe_num(x.get("change_pct")),x.get("query_rank"),x.get("trade_rank"),
            x.get("interval_turnover_krw"),x.get("five_min_turnover_krw"),
            safe_num(x.get("burst_multiple")),safe_num(x.get("theme_share_change_pp")),
            x.get("chart_state"),
            (micro.get(code) or {}).get("trade_value_15s_krw"),
            (micro.get(code) or {}).get("buy_share_15s"),
            (micro.get(code) or {}).get("tick_count_15s"),
            (micro.get(code) or {}).get("gap_count_15s"),
            (micro.get(code) or {}).get("strength"),
            (micro.get(code) or {}).get("buy_ratio"),
            json.dumps(x.get("axis_reasons") or {},ensure_ascii=False),
            json.dumps(x.get("risk_flags") or [],ensure_ascii=False),
            json.dumps(evidence,ensure_ascii=False)
        ))
    if not items:
        return 0,snap
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO market_os_assessment_snapshots(
          snapshot_time,stock_code,stock_name,rule_version,watch_tier,
          radar_score,theme_score,setup_score,catalyst_grade,trigger_state,market_stance,
          session_bucket,market_theme,event_type,current_price_krw,change_pct,query_rank,trade_rank,
          interval_turnover_krw,five_min_turnover_krw,burst_multiple,theme_share_change_pp,
          chart_state,micro_trade_value_15s_krw,micro_buy_share_15s,micro_tick_count_15s,
          micro_gap_count_15s,micro_strength,micro_buy_ratio,axis_reasons,risk_flags,evidence_ref)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
          ON CONFLICT(snapshot_time,stock_code,rule_version) DO NOTHING""",items)
        return cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(items),snap


def _realtime_target(cur,code,target,window_seconds=20):
    """First observed 5-second bucket at/after the target time.

    Using the bucket OPEN avoids using prices that occurred after the target.
    """
    if not table_exists(cur,"market_realtime_5s_bars"):
        return None
    cur.execute("""SELECT bucket_time,open_price,gap_count
                   FROM market_realtime_5s_bars
                   WHERE stock_code=%s AND bucket_time>=%s AND bucket_time<=%s
                   ORDER BY bucket_time LIMIT 1""",
                (code,target,target+timedelta(seconds=window_seconds)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["open_price"])
    if px is None or px<=0:return None
    flags=["REALTIME_GAPS"] if int(r["gap_count"] or 0)>0 else []
    return px,r["bucket_time"],"KIWOOM_0B_5S_OPEN",flags


def _sor_target(cur,code,target,window_seconds=150):
    cur.execute("""SELECT batch_time,payload FROM radar_flow_quotes
                   WHERE stock_code=%s AND batch_time>=%s AND batch_time<=%s
                   ORDER BY batch_time LIMIT 1""",
                (code,target,target+timedelta(seconds=window_seconds)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num((r["payload"] or {}).get("price_krw"))
    if px is None or px<=0:return None
    return px,r["batch_time"],"SOR_FLOW"


def _minute_target(cur,code,target,window_minutes=6):
    if not table_exists(cur,"market_minute_bars"):
        return None
    cur.execute("""SELECT bar_time,open_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<=%s
                   ORDER BY bar_time LIMIT 1""",
                (code,target,target+timedelta(minutes=window_minutes)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["open_price"])
    if px is None or px<=0:return None
    return px,r["bar_time"],"KRX_3M_OPEN_FALLBACK"


def _mfe_mae(cur,code,start,end,reference):
    if not reference or end<=start:
        return None,None,[]
    if table_exists(cur,"market_realtime_5s_bars"):
        cur.execute("""SELECT MAX(high_price) AS hi,MIN(low_price) AS lo,COUNT(*) AS n,
                              COALESCE(SUM(gap_count),0) AS gaps
                       FROM market_realtime_5s_bars
                       WHERE stock_code=%s AND bucket_time>=%s AND bucket_time<%s""",(code,start,end))
        rr=cur.fetchone()
        if rr and rr["n"] and int(rr["gaps"] or 0)==0:
            hi=safe_num(rr["hi"]);lo=safe_num(rr["lo"])
            return ((hi/reference-1)*100 if hi else None,
                    (lo/reference-1)*100 if lo else None,
                    ["MFE_MAE_KIWOOM_0B_5S"])
    if not table_exists(cur,"market_minute_bars"):
        return None,None,["MFE_MAE_NO_BARS"]
    # Conservative fallback: only fully post-assessment 3-minute bars are used.
    cur.execute("""SELECT MAX(high_price) AS hi,MIN(low_price) AS lo,COUNT(*) AS n
                   FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<%s""",(code,start,end))
    r=cur.fetchone()
    if not r or not r["n"]:
        return None,None,["MFE_MAE_NO_3M_BARS"]
    hi=safe_num(r["hi"]);lo=safe_num(r["lo"])
    mfe=(hi/reference-1)*100 if hi else None
    mae=(lo/reference-1)*100 if lo else None
    return mfe,mae,["MFE_MAE_KRX_3M_CONSERVATIVE"]


def _daily_close(cur,code,trade_date):
    cur.execute("""SELECT trade_date,close_price FROM market_daily_bars
                   WHERE stock_code=%s AND trade_date=%s
                   ORDER BY trade_date DESC LIMIT 1""",(code,trade_date))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["close_price"])
    return (px,r["trade_date"]) if px and px>0 else None


def _next_daily_close(cur,code,trade_date,now_local):
    cur.execute("""SELECT trade_date,close_price FROM market_daily_bars
                   WHERE stock_code=%s AND trade_date>%s
                   ORDER BY trade_date ASC LIMIT 1""",(code,trade_date))
    r=cur.fetchone()
    if not r:return None
    d=r["trade_date"]
    if d==now_local.date() and now_local.time()<dtime(15,40):
        return None
    px=safe_num(r["close_price"])
    return (px,d) if px and px>0 else None


def _close_time_utc(day):
    return datetime.combine(day,dtime(15,30),tzinfo=KST).astimezone(timezone.utc)


def _resolve_one(cur,a,horizon,now):
    at=a["snapshot_time"];code=a["stock_code"];ref=safe_num(a["current_price_krw"])
    if not ref or ref<=0:return None
    now_local=now.astimezone(KST);local_day=at.astimezone(KST).date()
    flags=[]
    if horizon in ("5m","30m"):
        minutes=5 if horizon=="5m" else 30
        target=at+timedelta(minutes=minutes)
        if now<target+timedelta(seconds=30):return None
        rt=_realtime_target(cur,code,target)
        if rt:
            px,ot,source,q=rt;flags+=q
            resolved=(px,ot,source)
        else:
            resolved=_sor_target(cur,code,target)
            if not resolved:
                resolved=_minute_target(cur,code,target)
                if resolved:flags.append("OUTCOME_KRX_FALLBACK")
        if not resolved:return None
        px,ot,source=resolved
        mfe,mae,q=_mfe_mae(cur,code,at,ot,ref);flags+=q
    elif horizon=="close":
        close_utc=_close_time_utc(local_day)
        if now < close_utc+timedelta(minutes=10):return None
        d=_daily_close(cur,code,local_day)
        if not d:return None
        px,_=d;ot=close_utc;source="KRX_DAILY_CLOSE"
        mfe,mae,q=_mfe_mae(cur,code,at,close_utc,ref);flags+=q
    elif horizon=="D+1":
        d=_next_daily_close(cur,code,local_day,now_local)
        if not d:return None
        px,day=d;ot=_close_time_utc(day);source="KRX_NEXT_DAILY_CLOSE"
        if now<ot+timedelta(minutes=10):return None
        mfe,mae,q=_mfe_mae(cur,code,at,ot,ref);flags+=q
    else:
        return None
    ret=(px/ref-1)*100
    return (a["snapshot_time"],code,a["rule_version"],horizon,ref,px,ret,mfe,mae,ot,source,
            json.dumps(flags,ensure_ascii=False))


def resolve_outcomes(limit=240):
    now=datetime.now(timezone.utc)
    inserted=0
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT a.* FROM market_os_assessment_snapshots a
                       WHERE a.snapshot_time>now()-interval '14 days'
                       ORDER BY a.snapshot_time ASC LIMIT %s""",(limit,))
        assessments=cur.fetchall()
        for a in assessments:
            for horizon in ("5m","30m","close","D+1"):
                cur.execute("""SELECT 1 FROM market_os_assessment_outcomes
                               WHERE assessment_time=%s AND stock_code=%s
                                 AND rule_version=%s AND horizon=%s""",
                            (a["snapshot_time"],a["stock_code"],a["rule_version"],horizon))
                if cur.fetchone():continue
                out=_resolve_one(cur,a,horizon,now)
                if not out:continue
                cur.execute("""INSERT INTO market_os_assessment_outcomes(
                    assessment_time,stock_code,rule_version,horizon,reference_price_krw,
                    outcome_price_krw,return_pct,mfe_pct,mae_pct,outcome_time,outcome_source,quality_flags)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT DO NOTHING""",out)
                inserted+=cur.rowcount if cur.rowcount and cur.rowcount>0 else 0
    return inserted


def _bucket_setup(v):
    if v is None:return "UNKNOWN"
    v=int(v)
    if v>=80:return "80-100"
    if v>=65:return "65-79"
    if v>=50:return "50-64"
    return "0-49"


def _aggregate(values):
    vals=[x for x in values if x.get("return_pct") is not None]
    if not vals:return None
    rets=[float(x["return_pct"]) for x in vals]
    mfes=[float(x["mfe_pct"]) for x in vals if x.get("mfe_pct") is not None]
    maes=[float(x["mae_pct"]) for x in vals if x.get("mae_pct") is not None]
    stocks={x.get("stock_code") for x in vals if x.get("stock_code")}
    days={x.get("trade_day") for x in vals if x.get("trade_day")}
    return {
        "samples":len(rets),
        "distinct_stocks":len(stocks),
        "distinct_days":len(days),
        "avg_return_pct":sum(rets)/len(rets),
        "median_return_pct":statistics.median(rets),
        "positive_rate":sum(x>0 for x in rets)/len(rets),
        "avg_mfe_pct":sum(mfes)/len(mfes) if mfes else None,
        "avg_mae_pct":sum(maes)/len(maes) if maes else None
    }


def _walk_forward_windows(values,comparator=None):
    """Split a segment by complete trade days into early/recent halves.

    Day-level splitting prevents observations from the same trading day leaking
    across both halves. Comparator rows, when supplied, are restricted to the
    exact same day sets so interaction deltas remain time-aligned.
    """
    days=sorted({x.get("trade_day") for x in values if x.get("trade_day")})
    if len(days)<4:
        return []
    cut=len(days)//2
    early_days=set(days[:cut]);recent_days=set(days[cut:])
    out=[]
    for name,dayset in (("EARLY",early_days),("RECENT",recent_days)):
        child_vals=[x for x in values if x.get("trade_day") in dayset]
        child=_aggregate(child_vals)
        if not child:
            continue
        row={
            "window_name":name,
            "start_day":min(dayset),"end_day":max(dayset),
            **child,
            "comparator_samples":None,"comparator_stocks":None,"comparator_days":None,
            "comparator_avg_return_pct":None,"comparator_positive_rate":None,
            "comparator_avg_mae_pct":None,
            "delta_avg_return_pct":None,"delta_positive_rate_pp":None,"delta_mae_pct":None,
        }
        if comparator is not None:
            comp_vals=[x for x in comparator if x.get("trade_day") in dayset]
            comp=_aggregate(comp_vals)
            if comp:
                row.update({
                    "comparator_samples":comp["samples"],
                    "comparator_stocks":comp["distinct_stocks"],
                    "comparator_days":comp["distinct_days"],
                    "comparator_avg_return_pct":comp["avg_return_pct"],
                    "comparator_positive_rate":comp["positive_rate"],
                    "comparator_avg_mae_pct":comp["avg_mae_pct"],
                    "delta_avg_return_pct":child["avg_return_pct"]-comp["avg_return_pct"],
                    "delta_positive_rate_pp":(child["positive_rate"]-comp["positive_rate"])*100,
                    "delta_mae_pct":(
                        child["avg_mae_pct"]-comp["avg_mae_pct"]
                        if child["avg_mae_pct"] is not None and comp["avg_mae_pct"] is not None
                        else None
                    ),
                })
        out.append(row)
    return out


def _sample_basis(horizon):
    if horizon=="5m":return "NON_OVERLAP_5M"
    if horizon=="30m":return "NON_OVERLAP_30M"
    if horizon=="close":return "ONE_PER_STOCK_DAY_CLOSE"
    if horizon=="D+1":return "ONE_PER_STOCK_DAY_D1"
    return "UNKNOWN"


def _episode_anchors(rows):
    """Reduce repeated snapshots to horizon-aware non-overlapping anchors.

    Raw assessments remain stored for audit. Learning segments use these anchors
    so a stock that stays on screen for 20 minutes is not counted as 20
    independent observations.
    """
    ordered=sorted(rows,key=lambda r:(r["horizon"],r["stock_code"],r["snapshot_time"]))
    last_time={}
    last_day={}
    out=[]
    for r in ordered:
        horizon=r["horizon"];code=r["stock_code"];ts=r["snapshot_time"]
        day=ts.astimezone(KST).date().isoformat()
        r=dict(r);r["trade_day"]=day
        key=(horizon,code)
        if horizon in ("close","D+1"):
            if last_day.get(key)==day:
                continue
            last_day[key]=day;out.append(r);continue
        cooldown=300 if horizon=="5m" else 1800 if horizon=="30m" else 300
        prev=last_time.get(key)
        if prev is not None and (ts-prev).total_seconds()<cooldown:
            continue
        last_time[key]=ts;out.append(r)
    return out


def _bucket_strength(v):
    v=safe_num(v)
    if v is None:return "UNKNOWN"
    if v>=120:return "120+"
    if v>=100:return "100-119"
    if v>=80:return "80-99"
    return "<80"


def _bucket_buy_share(v):
    v=safe_num(v)
    if v is None:return "UNKNOWN"
    if v>=.65:return "65%+"
    if v>=.55:return "55-64%"
    if v>=.45:return "45-54%"
    return "<45%"


def _micro_state(strength,buy_share):
    """Pre-registered shadow heuristic; not a live trade signal."""
    s=safe_num(strength);b=safe_num(buy_share)
    if s is None or b is None:return "NO_DATA"
    if s>=120 and b>=.65:return "STRONG_CONFIRM"
    if s<80 and b<.45:return "WEAK_CONFIRM"
    if s>=100 and b>=.55:return "POSITIVE"
    if s<100 and b<.45:return "NEGATIVE"
    return "MIXED"


def _segment_depth(kind):
    return {
        "STANCE_TRIGGER":2,"TIER_SESSION":2,"STANCE_SETUP":2,"SETUP_TRIGGER":2,
        "STANCE_SETUP_TRIGGER":3,
        "STANCE_TRIGGER_MICRO":3,"SETUP_TRIGGER_MICRO":3,
        "STANCE_SETUP_TRIGGER_MICRO":4,
    }.get(kind,1)


def _parent_key(kind,value):
    p=value.split(" | ")
    try:
        if kind=="STANCE_TRIGGER":return ("STANCE",p[0])
        if kind=="TIER_SESSION":return ("TIER",p[0])
        if kind=="STANCE_SETUP":return ("STANCE",p[0])
        if kind=="SETUP_TRIGGER":return ("SETUP",p[0])
        if kind=="STANCE_SETUP_TRIGGER":return ("STANCE_TRIGGER",p[0]+" | "+p[2])
        if kind=="STANCE_TRIGGER_MICRO":return ("STANCE_TRIGGER",p[0]+" | "+p[1])
        if kind=="SETUP_TRIGGER_MICRO":return ("SETUP_TRIGGER",p[0]+" | "+p[1])
        if kind=="STANCE_SETUP_TRIGGER_MICRO":
            return ("STANCE_SETUP_TRIGGER",p[0]+" | "+p[1]+" | "+p[2])
    except IndexError:
        return None
    return None


def _learning_dims(r):
    """Return pre-registered single and interaction dimensions.

    Keeping the interaction list explicit prevents an uncontrolled combinatorial
    search over every possible feature combination.
    """
    tier=r["watch_tier"] or "UNKNOWN"
    stance=r["market_stance"] or "UNKNOWN"
    trigger=r["trigger_state"] or "UNKNOWN"
    session=r["session_bucket"] or "UNKNOWN"
    setup=_bucket_setup(r["setup_score"])
    dims={
        "TIER":tier,
        "STANCE":stance,
        "TRIGGER":trigger,
        "SESSION":session,
        "CATALYST":r["catalyst_grade"] or "UNKNOWN",
        "SETUP":setup,
        "STANCE_TRIGGER":stance+" | "+trigger,
        "TIER_SESSION":tier+" | "+session,
        "STANCE_SETUP":stance+" | "+setup,
        "SETUP_TRIGGER":setup+" | "+trigger,
        "STANCE_SETUP_TRIGGER":stance+" | "+setup+" | "+trigger,
    }
    clean_micro=int(r["micro_tick_count_15s"] or 0)>0 and int(r["micro_gap_count_15s"] or 0)==0
    if clean_micro:
        strength=_bucket_strength(r["micro_strength"])
        buy_share=_bucket_buy_share(r["micro_buy_share_15s"])
        micro=_micro_state(r["micro_strength"],r["micro_buy_share_15s"])
        dims["MICRO_STRENGTH"]=strength
        dims["MICRO_BUY_SHARE"]=buy_share
        dims["MICRO_STATE"]=micro
        dims["STANCE_TRIGGER_MICRO"]=stance+" | "+trigger+" | "+micro
        dims["SETUP_TRIGGER_MICRO"]=setup+" | "+trigger+" | "+micro
        dims["STANCE_SETUP_TRIGGER_MICRO"]=stance+" | "+setup+" | "+trigger+" | "+micro
    return dims


def refresh_segments():
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT a.snapshot_time,a.stock_code,
                              a.watch_tier,a.market_stance,a.trigger_state,a.session_bucket,
                              a.catalyst_grade,a.setup_score,a.micro_strength,a.micro_buy_share_15s,
                              a.micro_tick_count_15s,a.micro_gap_count_15s,
                              o.horizon,o.return_pct,o.mfe_pct,o.mae_pct
                       FROM market_os_assessment_outcomes o
                       JOIN market_os_assessment_snapshots a
                         ON a.snapshot_time=o.assessment_time AND a.stock_code=o.stock_code
                        AND a.rule_version=o.rule_version
                       WHERE a.rule_version=%s
                         AND a.snapshot_time>now()-interval '60 days'""",(RULE_VERSION,))
        raw=cur.fetchall()
        rows=_episode_anchors(raw)
        groups=defaultdict(list)
        for r in rows:
            horizon=r["horizon"]
            dims=_learning_dims(r)
            for kind,value in dims.items():
                groups[(kind,value,horizon)].append(r)

        cur.execute("DELETE FROM market_os_learning_segments")
        segment_payload=[]
        for (kind,value,horizon),vals in groups.items():
            a=_aggregate(vals)
            if not a:continue
            segment_payload.append((kind,value,horizon,a["samples"],a["distinct_stocks"],a["distinct_days"],
                            _sample_basis(horizon),a["avg_return_pct"],a["median_return_pct"],
                            a["positive_rate"],a["avg_mfe_pct"],a["avg_mae_pct"]))
        cur.executemany("""INSERT INTO market_os_learning_segments(
              segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,sample_basis,
              avg_return_pct,median_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",segment_payload)

        # Compare each pre-registered interaction to the complement inside its
        # parent condition. Parent aggregate includes the child, so using the
        # complement avoids mechanically diluting the observed conditional gap.
        cur.execute("DELETE FROM market_os_interaction_edges")
        edge_payload=[]
        for (kind,value,horizon),child_vals in groups.items():
            if _segment_depth(kind)<2:continue
            parent=_parent_key(kind,value)
            if not parent:continue
            parent_vals=groups.get((parent[0],parent[1],horizon)) or []
            if kind.endswith("_MICRO"):
                parent_vals=[
                    r for r in parent_vals
                    if int(r["micro_tick_count_15s"] or 0)>0
                    and int(r["micro_gap_count_15s"] or 0)==0
                    and _micro_state(r["micro_strength"],r["micro_buy_share_15s"])!="NO_DATA"
                ]
            if not parent_vals:continue
            child_ids={(r["stock_code"],r["snapshot_time"]) for r in child_vals}
            comparator=[r for r in parent_vals if (r["stock_code"],r["snapshot_time"]) not in child_ids]
            child=_aggregate(child_vals);comp=_aggregate(comparator)
            if not child or not comp:continue
            d_avg=(child["avg_return_pct"]-comp["avg_return_pct"]
                   if child["avg_return_pct"] is not None and comp["avg_return_pct"] is not None else None)
            d_pos=((child["positive_rate"]-comp["positive_rate"])*100
                   if child["positive_rate"] is not None and comp["positive_rate"] is not None else None)
            d_mfe=(child["avg_mfe_pct"]-comp["avg_mfe_pct"]
                   if child["avg_mfe_pct"] is not None and comp["avg_mfe_pct"] is not None else None)
            d_mae=(child["avg_mae_pct"]-comp["avg_mae_pct"]
                   if child["avg_mae_pct"] is not None and comp["avg_mae_pct"] is not None else None)
            edge_payload.append((
                kind,value,horizon,parent[0],parent[1],_sample_basis(horizon),
                child["samples"],child["distinct_stocks"],child["distinct_days"],
                comp["samples"],comp["distinct_stocks"],comp["distinct_days"],
                child["avg_return_pct"],comp["avg_return_pct"],d_avg,
                child["positive_rate"],comp["positive_rate"],d_pos,
                child["avg_mfe_pct"],comp["avg_mfe_pct"],d_mfe,
                child["avg_mae_pct"],comp["avg_mae_pct"],d_mae
            ))
        cur.executemany("""INSERT INTO market_os_interaction_edges(
              segment_type,segment_value,horizon,parent_type,parent_value,sample_basis,
              child_samples,child_stocks,child_days,comparator_samples,comparator_stocks,comparator_days,
              child_avg_return_pct,comparator_avg_return_pct,delta_avg_return_pct,
              child_positive_rate,comparator_positive_rate,delta_positive_rate_pp,
              child_avg_mfe_pct,comparator_avg_mfe_pct,delta_mfe_pct,
              child_avg_mae_pct,comparator_avg_mae_pct,delta_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
              edge_payload)
        cur.execute("DELETE FROM market_os_walk_forward_windows")
        wf_payload=[]
        for (kind,value,horizon),child_vals in groups.items():
            comparator=None
            if _segment_depth(kind)>=2:
                parent=_parent_key(kind,value)
                parent_vals=groups.get((parent[0],parent[1],horizon)) if parent else None
                if parent_vals:
                    if kind.endswith("_MICRO"):
                        parent_vals=[
                            r for r in parent_vals
                            if int(r["micro_tick_count_15s"] or 0)>0
                            and int(r["micro_gap_count_15s"] or 0)==0
                            and _micro_state(r["micro_strength"],r["micro_buy_share_15s"])!="NO_DATA"
                        ]
                    child_ids={(r["stock_code"],r["snapshot_time"]) for r in child_vals}
                    comparator=[
                        r for r in parent_vals
                        if (r["stock_code"],r["snapshot_time"]) not in child_ids
                    ]
            for w in _walk_forward_windows(child_vals,comparator):
                wf_payload.append((
                    kind,value,horizon,w["window_name"],w["start_day"],w["end_day"],
                    w["samples"],w["distinct_stocks"],w["distinct_days"],
                    w["avg_return_pct"],w["median_return_pct"],w["positive_rate"],
                    w["avg_mfe_pct"],w["avg_mae_pct"],
                    w["comparator_samples"],w["comparator_stocks"],w["comparator_days"],
                    w["comparator_avg_return_pct"],w["comparator_positive_rate"],
                    w["comparator_avg_mae_pct"],w["delta_avg_return_pct"],
                    w["delta_positive_rate_pp"],w["delta_mae_pct"]
                ))
        cur.executemany("""INSERT INTO market_os_walk_forward_windows(
              segment_type,segment_value,horizon,window_name,start_day,end_day,
              samples,distinct_stocks,distinct_days,avg_return_pct,median_return_pct,positive_rate,
              avg_mfe_pct,avg_mae_pct,comparator_samples,comparator_stocks,comparator_days,
              comparator_avg_return_pct,comparator_positive_rate,comparator_avg_mae_pct,
              delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
              wf_payload)
        return len(segment_payload)




def update_status(status,note,last_snapshot=None,last_outcome=False):
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM market_os_assessment_snapshots WHERE rule_version=%s",(RULE_VERSION,))
        assessments=int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n,MAX(calculated_at) AS t FROM market_os_assessment_outcomes WHERE rule_version=%s",(RULE_VERSION,))
        r=cur.fetchone();outcomes=int(r["n"]);out_t=r["t"]
        cur.execute("""INSERT INTO market_os_learning_status(
          id,updated_at,status,last_snapshot_at,last_outcome_at,assessments_total,outcomes_total,note)
          VALUES(1,now(),%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
          last_snapshot_at=COALESCE(excluded.last_snapshot_at,market_os_learning_status.last_snapshot_at),
          last_outcome_at=COALESCE(excluded.last_outcome_at,market_os_learning_status.last_outcome_at),
          assessments_total=excluded.assessments_total,outcomes_total=excluded.outcomes_total,note=excluded.note""",
          (status,last_snapshot,out_t if last_outcome else None,assessments,outcomes,note))


def cycle():
    captured,snap=capture_assessments()
    outcomes=resolve_outcomes()
    segments=refresh_segments()
    update_status("OK",f"captured={captured} outcomes={outcomes} segments={segments}",
                  last_snapshot=snap,last_outcome=bool(outcomes))
    return captured,outcomes,segments


if __name__=="__main__":
    ensure_schema()
    print(f"Market OS learning started · poll={POLL}s · rule={RULE_VERSION}",flush=True)
    while True:
        try:
            a,o,s=cycle()
            if a or o:
                print(f"learning cycle assessments={a} outcomes={o} segments={s}",flush=True)
        except Exception as exc:
            print("market os learning error",type(exc).__name__,str(exc)[:400],flush=True)
            try:update_status("ERROR",type(exc).__name__)
            except Exception:pass
        time.sleep(POLL)
