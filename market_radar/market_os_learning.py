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
    axis_reasons        JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_flags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ref        JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_time, stock_code, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_code_time
    ON market_os_assessment_snapshots(stock_code, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_tier_time
    ON market_os_assessment_snapshots(watch_tier, snapshot_time DESC);

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
    avg_return_pct      DOUBLE PRECISION,
    median_return_pct   DOUBLE PRECISION,
    positive_rate       DOUBLE PRECISION,
    avg_mfe_pct         DOUBLE PRECISION,
    avg_mae_pct         DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (segment_type, segment_value, horizon)
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


def capture_assessments():
    payload=desk_payload()
    if not payload.get("recent_trade_count"):
        return 0,None
    sample=parse_dt(payload.get("sample_time"))
    if not sample:
        return 0,None
    age=(datetime.now(timezone.utc)-sample).total_seconds()
    if age < -60 or age > 180:
        return 0,None
    snap=sample.replace(second=0,microsecond=0)
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
            x.get("chart_state"),json.dumps(x.get("axis_reasons") or {},ensure_ascii=False),
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
          chart_state,axis_reasons,risk_flags,evidence_ref)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
          ON CONFLICT(snapshot_time,stock_code,rule_version) DO NOTHING""",items)
        return cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(items),snap


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
    cur.execute("""SELECT bar_time,close_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<=%s
                   ORDER BY bar_time LIMIT 1""",
                (code,target,target+timedelta(minutes=window_minutes)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["close_price"])
    if px is None or px<=0:return None
    return px,r["bar_time"],"KRX_3M_FALLBACK"


def _mfe_mae(cur,code,start,end,reference):
    if not reference or end<=start:
        return None,None,[]
    cur.execute("""SELECT MAX(high_price) AS hi,MIN(low_price) AS lo,COUNT(*) AS n
                   FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<=%s""",(code,start,end))
    r=cur.fetchone()
    if not r or not r["n"]:
        return None,None,["MFE_MAE_NO_3M_BARS"]
    hi=safe_num(r["hi"]);lo=safe_num(r["lo"])
    mfe=(hi/reference-1)*100 if hi else None
    mae=(lo/reference-1)*100 if lo else None
    return mfe,mae,["MFE_MAE_KRX_3M"]


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
    return {
        "samples":len(rets),
        "avg_return_pct":sum(rets)/len(rets),
        "median_return_pct":statistics.median(rets),
        "positive_rate":sum(x>0 for x in rets)/len(rets),
        "avg_mfe_pct":sum(mfes)/len(mfes) if mfes else None,
        "avg_mae_pct":sum(maes)/len(maes) if maes else None
    }


def refresh_segments():
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT a.watch_tier,a.market_stance,a.trigger_state,a.session_bucket,
                              a.catalyst_grade,a.setup_score,o.horizon,o.return_pct,o.mfe_pct,o.mae_pct
                       FROM market_os_assessment_outcomes o
                       JOIN market_os_assessment_snapshots a
                         ON a.snapshot_time=o.assessment_time AND a.stock_code=o.stock_code
                        AND a.rule_version=o.rule_version
                       WHERE a.rule_version=%s
                         AND a.snapshot_time>now()-interval '60 days'""",(RULE_VERSION,))
        rows=cur.fetchall()
        groups=defaultdict(list)
        for r in rows:
            horizon=r["horizon"]
            tier=r["watch_tier"] or "UNKNOWN"
            stance=r["market_stance"] or "UNKNOWN"
            trigger=r["trigger_state"] or "UNKNOWN"
            session=r["session_bucket"] or "UNKNOWN"
            dims={
                "TIER":tier,
                "STANCE":stance,
                "TRIGGER":trigger,
                "SESSION":session,
                "CATALYST":r["catalyst_grade"] or "UNKNOWN",
                "SETUP":_bucket_setup(r["setup_score"]),
                "STANCE_TRIGGER":stance+" | "+trigger,
                "TIER_SESSION":tier+" | "+session,
            }
            for kind,value in dims.items():
                groups[(kind,value,horizon)].append(r)
        cur.execute("DELETE FROM market_os_learning_segments")
        payload=[]
        for (kind,value,horizon),vals in groups.items():
            a=_aggregate(vals)
            if not a:continue
            payload.append((kind,value,horizon,a["samples"],a["avg_return_pct"],a["median_return_pct"],
                            a["positive_rate"],a["avg_mfe_pct"],a["avg_mae_pct"]))
        cur.executemany("""INSERT INTO market_os_learning_segments(
              segment_type,segment_value,horizon,samples,avg_return_pct,median_return_pct,
              positive_rate,avg_mfe_pct,avg_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",payload)
        return len(payload)


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
