"""Local paper-trading experiment for Market Radar.

This service never sends an order and never calls an AI provider.
It uses one normalized unit per experiment and records percentage paths only.
The purpose is to test Radar rules prospectively, not to recommend real trades.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
import os
import time

import psycopg
from psycopg.rows import dict_row

from flow_core import reversal_signals

DB=os.getenv("DATABASE_URL","")
POLL=max(15,int(os.getenv("PAPER_TRADE_POLL_SECONDS","30")))
ENTRY_SCORE=max(40,min(100,int(os.getenv("PAPER_ENTRY_SCORE","70"))))
ENTRY_SURVIVE_SEC=max(30,min(900,int(os.getenv("PAPER_ENTRY_SURVIVE_SECONDS","120"))))
EXIT_SCORE=max(0,min(100,int(os.getenv("PAPER_EXIT_SCORE","55"))))
MAX_HOLD_MIN=max(5,min(180,int(os.getenv("PAPER_MAX_HOLD_MINUTES","30"))))
MAX_OPEN=max(1,min(20,int(os.getenv("PAPER_MAX_OPEN","5"))))
QUOTE_FRESH_SEC=max(30,min(300,int(os.getenv("PAPER_QUOTE_FRESH_SECONDS","120"))))
AI_DECISION_FRESH_SEC=max(30,min(600,int(os.getenv("PAPER_AI_DECISION_FRESH_SECONDS","180"))))
REQUIRE_AI_BROKERAGE=os.getenv("PAPER_REQUIRE_AI_BROKERAGE","0").strip().lower() in ("1","true","yes","on")
RULE_VERSION="paper-v1-observation"

SCHEMA="""
CREATE TABLE IF NOT EXISTS radar_paper_trades(
  id BIGSERIAL PRIMARY KEY,
  episode_id BIGINT UNIQUE,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  rule_version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  opened_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ,
  entry_price_krw NUMERIC NOT NULL,
  exit_price_krw NUMERIC,
  last_mark_at TIMESTAMPTZ,
  last_mark_price_krw NUMERIC,
  return_pct DOUBLE PRECISION,
  mfe_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
  mae_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
  entry_score INTEGER,
  exit_score INTEGER,
  primary_type TEXT,
  market_theme TEXT,
  event_type TEXT,
  chart_state_entry TEXT,
  chart_state_exit TEXT,
  entry_reason JSONB NOT NULL DEFAULT '[]'::jsonb,
  exit_reason TEXT,
  exit_price_basis TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_open_code
  ON radar_paper_trades(stock_code) WHERE status='OPEN';
CREATE INDEX IF NOT EXISTS idx_paper_opened ON radar_paper_trades(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_rule_type ON radar_paper_trades(rule_version,primary_type,opened_at DESC);
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS strategy_id TEXT;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS strategy_name TEXT;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS strategy_family TEXT;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS strategy_lifecycle TEXT;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS strategy_fit DOUBLE PRECISION;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS ai_conviction DOUBLE PRECISION;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS ai_decision_time TIMESTAMPTZ;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS ai_decision_version TEXT;
ALTER TABLE radar_paper_trades ADD COLUMN IF NOT EXISTS regime_label TEXT;
CREATE INDEX IF NOT EXISTS idx_paper_strategy_time ON radar_paper_trades(strategy_id,opened_at DESC);

CREATE TABLE IF NOT EXISTS radar_paper_events(
  id BIGSERIAL PRIMARY KEY,
  trade_id BIGINT REFERENCES radar_paper_trades(id) ON DELETE CASCADE,
  event_time TIMESTAMPTZ NOT NULL,
  event_type TEXT NOT NULL,
  price_krw NUMERIC,
  score INTEGER,
  reason TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_paper_events_trade_time
  ON radar_paper_events(trade_id,event_time DESC);

CREATE TABLE IF NOT EXISTS radar_paper_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  open_count INTEGER NOT NULL DEFAULT 0,
  closed_today INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

def db(read_only=False):
    c=psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=12000 -c lock_timeout=3000')
    if read_only:c.execute("SET TRANSACTION READ ONLY")
    return c

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419067,))
        cur.execute(SCHEMA)

def f(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def pct(price,entry):
    p=f(price);e=f(entry)
    return ((p/e)-1)*100 if p is not None and e and e>0 else None

def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s)",("public."+name,))
    return cur.fetchone()["to_regclass"] is not None

def latest_ai_decision(cur,code,now):
    if not table_exists(cur,"ai_brokerage_decisions"):return None
    cur.execute("""SELECT snapshot_time,state,conviction,strategy_id,strategy_name,strategy_family,
                          strategy_fit,strategy_lifecycle,regime_label,decision_version,packet
                   FROM ai_brokerage_decisions
                   WHERE stock_code=%s AND snapshot_time>=%s
                   ORDER BY snapshot_time DESC LIMIT 1""",
                (code,now-timedelta(seconds=AI_DECISION_FRESH_SEC)))
    r=cur.fetchone()
    return dict(r) if r else None

def latest_quote(cur,code,now):
    if not table_exists(cur,"radar_flow_quotes"):return None
    cur.execute("""SELECT batch_time,
                          NULLIF(payload->>'exchange_at','')::timestamptz AS exchange_at,
                          NULLIF(payload->>'price_krw','')::double precision AS price
                   FROM radar_flow_quotes
                   WHERE stock_code=%s
                     AND payload->>'exchange_at' IS NOT NULL
                     AND payload->>'price_krw' IS NOT NULL
                   ORDER BY batch_time DESC
                   LIMIT 1""",(code,))
    r=cur.fetchone()
    if not r or f(r["price"]) is None:return None
    exchange=r["exchange_at"]
    fresh=bool(exchange and 0<=(now-exchange).total_seconds()<=QUOTE_FRESH_SEC)
    return {"batch_time":r["batch_time"],"exchange_at":exchange,"price":f(r["price"]),"fresh":fresh}

def recent_exit_quote(cur,code,now):
    if not table_exists(cur,"radar_flow_quotes"):return None
    cur.execute("""SELECT batch_time,
                          NULLIF(payload->>'exchange_at','')::timestamptz AS exchange_at,
                          NULLIF(payload->>'price_krw','')::double precision AS price
                   FROM radar_flow_quotes
                   WHERE stock_code=%s
                     AND payload->>'exchange_at' IS NOT NULL
                     AND NULLIF(payload->>'exchange_at','')::timestamptz<=%s
                     AND NULLIF(payload->>'exchange_at','')::timestamptz>=%s
                     AND payload->>'price_krw' IS NOT NULL
                   ORDER BY NULLIF(payload->>'exchange_at','')::timestamptz DESC,batch_time DESC
                   LIMIT 1""",(code,now,now-timedelta(seconds=QUOTE_FRESH_SEC)))
    r=cur.fetchone()
    if not r or f(r["price"]) is None:return None
    return {"exchange_at":r["exchange_at"],"price":f(r["price"])}

def latest_chart(cur,code):
    out={"state":None,"state_ko":None,"minute_trend":None}
    if not table_exists(cur,"chart_states"):return out
    cur.execute("""SELECT state,state_ko,minute_trend,snapshot_time
                   FROM chart_states WHERE stock_code=%s
                   ORDER BY snapshot_time DESC LIMIT 1""",(code,))
    r=cur.fetchone()
    if r:
        out={"state":r["state"],"state_ko":r["state_ko"],
             "minute_trend":r["minute_trend"],"snapshot_time":r["snapshot_time"]}
    return out

def top_warning(cur,code):
    if not table_exists(cur,"market_minute_bars"):return None
    cur.execute("""SELECT bar_time,open_price,high_price,low_price,close_price,volume
                   FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                   ORDER BY bar_time DESC LIMIT 60""",(code,))
    raw=list(reversed(cur.fetchall()))
    bars=[]
    for r in raw:
        vals=[f(r[k]) for k in ("open_price","high_price","low_price","close_price")]
        if None in vals:continue
        bars.append({"time":r["bar_time"].isoformat(),"open":vals[0],"high":vals[1],
                     "low":vals[2],"close":vals[3],"volume":f(r["volume"]) or 0})
    if len(bars)<22:return None
    return (reversal_signals(bars,{}).get("latest"))

def active_candidates(cur,now):
    if not table_exists(cur,"radar_candidate_episodes") or not table_exists(cur,"radar_candidate_history"):
        return []
    cutoff=now-timedelta(seconds=ENTRY_SURVIVE_SEC)
    cur.execute("""SELECT e.id,e.stock_code,e.stock_name,e.started_at,e.last_seen_at,e.candidate_version,
                          e.last_score,e.peak_score,e.primary_type,e.market_theme,e.event_type,e.chart_state,
                          h.n_obs,h.min_score
                   FROM radar_candidate_episodes e
                   JOIN LATERAL (
                     SELECT COUNT(*) AS n_obs,MIN(attention_score) AS min_score
                     FROM radar_candidate_history h
                     WHERE h.stock_code=e.stock_code
                       AND h.snapshot_time>=%s
                       AND h.snapshot_time<=%s
                   ) h ON true
                   WHERE e.status='ACTIVE'
                     AND e.last_seen_at>=%s
                     AND e.started_at<=%s
                     AND e.last_score>=%s
                     AND h.n_obs>=3
                     AND h.min_score>=%s
                     AND COALESCE(e.primary_type,'')<>'조건 미완성'
                   ORDER BY e.last_score DESC,e.peak_score DESC,e.last_seen_at DESC
                   LIMIT 20""",
                (cutoff,now,now-timedelta(seconds=90),cutoff,ENTRY_SCORE,ENTRY_SCORE))
    return cur.fetchall()

def open_trades(cur):
    cur.execute("""SELECT * FROM radar_paper_trades
                   WHERE status='OPEN' ORDER BY opened_at""")
    return cur.fetchall()

def event(cur,trade_id,when,kind,price=None,score=None,reason=None,payload=None):
    cur.execute("""INSERT INTO radar_paper_events(
                     trade_id,event_time,event_type,price_krw,score,reason,payload)
                   VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (trade_id,when,kind,price,score,reason,
                 json.dumps(payload or {},ensure_ascii=False)))

def mark_trade(cur,t,quote):
    r=pct(quote["price"],t["entry_price_krw"])
    if r is None:return
    mfe=max(float(t["mfe_pct"] or 0),r)
    mae=min(float(t["mae_pct"] or 0),r)
    cur.execute("""UPDATE radar_paper_trades
                   SET last_mark_at=%s,last_mark_price_krw=%s,return_pct=%s,
                       mfe_pct=%s,mae_pct=%s,updated_at=now()
                   WHERE id=%s""",
                (quote["exchange_at"],quote["price"],r,mfe,mae,t["id"]))

def close_trade(cur,t,now,reason,exit_score=None,chart=None):
    q=recent_exit_quote(cur,t["stock_code"],now)
    if q:
        ret=pct(q["price"],t["entry_price_krw"])
        status="CLOSED"
        basis="OBSERVED_SOR"
        close_at=q["exchange_at"]
        exit_price=q["price"]
    else:
        ret=None
        status="CLOSED_NO_PRICE"
        basis="NO_RECENT_QUOTE"
        close_at=now
        exit_price=None
    cur.execute("""UPDATE radar_paper_trades
                   SET status=%s,closed_at=%s,exit_price_krw=%s,return_pct=%s,
                       exit_score=%s,chart_state_exit=%s,exit_reason=%s,
                       exit_price_basis=%s,updated_at=now()
                   WHERE id=%s""",
                (status,close_at,exit_price,ret,exit_score,
                 (chart or {}).get("state_ko"),reason,basis,t["id"]))
    event(cur,t["id"],close_at,"PAPER_EXIT",exit_price,exit_score,reason,
          {"basis":basis,"chart_state":(chart or {}).get("state")})

def entry_reason(c,chart):
    return [
        f"관찰도 {c['last_score']}≥{ENTRY_SCORE}",
        f"최근 {ENTRY_SURVIVE_SEC}초 최저 관찰도도 {ENTRY_SCORE} 이상",
        "최근 SOR 체결 확인",
        "차트 훼손 상태 아님",
        f"유형 {c.get('primary_type') or '미확인'}",
    ]

def maybe_open(cur,now):
    open_now=open_trades(cur)
    if len(open_now)>=MAX_OPEN:return 0
    open_codes={x["stock_code"] for x in open_now}
    opened=0
    for c in active_candidates(cur,now):
        if len(open_now)+opened>=MAX_OPEN:break
        if c["stock_code"] in open_codes:continue
        cur.execute("SELECT 1 FROM radar_paper_trades WHERE episode_id=%s",(c["id"],))
        if cur.fetchone():continue
        ai=latest_ai_decision(cur,c["stock_code"],now)
        if REQUIRE_AI_BROKERAGE and (not ai or ai.get("state")!="PAPER_ENTRY"):
            continue
        if ai and ai.get("state") not in ("PAPER_ENTRY","READY"):
            continue
        q=latest_quote(cur,c["stock_code"],now)
        if not q or not q["fresh"]:continue
        chart=latest_chart(cur,c["stock_code"])
        if chart.get("state") in ("TREND_DAMAGE","BREAKOUT_FAIL"):continue
        warn=top_warning(cur,c["stock_code"])
        if warn and warn.get("kind")=="TOP_WARNING" and int(warn.get("score") or 0)>=70:
            continue
        reasons=entry_reason(c,chart)
        if ai:
            if ai.get("strategy_id"):
                reasons.append(f"AI 전략 {ai.get('strategy_id')} · fit {float(ai.get('strategy_fit') or 0):.0f}")
            reasons.append(f"6-Desk conviction {float(ai.get('conviction') or 0):.0f}")
        cur.execute("""INSERT INTO radar_paper_trades(
                       episode_id,stock_code,stock_name,rule_version,status,opened_at,
                       entry_price_krw,last_mark_at,last_mark_price_krw,return_pct,mfe_pct,mae_pct,
                       entry_score,primary_type,market_theme,event_type,chart_state_entry,entry_reason,
                       strategy_id,strategy_name,strategy_family,strategy_lifecycle,strategy_fit,
                       ai_conviction,ai_decision_time,ai_decision_version,regime_label)
                       VALUES(%s,%s,%s,%s,'OPEN',%s,%s,%s,%s,0,0,0,%s,%s,%s,%s,%s,%s::jsonb,
                              %s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id""",
                    (c["id"],c["stock_code"],c["stock_name"],RULE_VERSION,
                     q["exchange_at"],q["price"],q["exchange_at"],q["price"],
                     c["last_score"],c["primary_type"],c["market_theme"],c["event_type"],
                     chart.get("state_ko"),json.dumps(reasons,ensure_ascii=False),
                     (ai or {}).get("strategy_id"),(ai or {}).get("strategy_name"),
                     (ai or {}).get("strategy_family"),(ai or {}).get("strategy_lifecycle"),
                     (ai or {}).get("strategy_fit"),(ai or {}).get("conviction"),
                     (ai or {}).get("snapshot_time"),(ai or {}).get("decision_version"),
                     (ai or {}).get("regime_label")))
        trade_id=cur.fetchone()["id"]
        event(cur,trade_id,q["exchange_at"],"PAPER_ENTRY",q["price"],c["last_score"],
              " | ".join(reasons),
              {"candidate_version":c["candidate_version"],"chart_state":chart.get("state"),
               "top_warning":warn,"ai_decision":ai})
        opened+=1
    return opened

def maybe_close_and_mark(cur,now):
    if not table_exists(cur,"radar_candidate_episodes"):return 0
    closed=0
    for t in open_trades(cur):
        q=latest_quote(cur,t["stock_code"],now)
        if q and q["fresh"]:
            mark_trade(cur,t,q)
            # Refresh row after mark not necessary for exit-rule inputs.
        cur.execute("""SELECT status,last_seen_at,last_score
                       FROM radar_candidate_episodes WHERE id=%s""",(t["episode_id"],))
        episode=cur.fetchone()
        chart=latest_chart(cur,t["stock_code"])
        reason=None
        score=episode["last_score"] if episode else None
        if not episode or episode["status"]!="ACTIVE" or episode["last_seen_at"]<now-timedelta(seconds=90):
            reason="후보 이탈"
        elif int(score or 0)<EXIT_SCORE:
            reason=f"관찰도 {score}<{EXIT_SCORE}"
        elif chart.get("state") in ("TREND_DAMAGE","BREAKOUT_FAIL"):
            reason=chart.get("state_ko") or "차트 훼손"
        else:
            warn=top_warning(cur,t["stock_code"])
            if warn and warn.get("kind")=="TOP_WARNING" and int(warn.get("score") or 0)>=70:
                reason=f"고점 경계 강화 {warn.get('score')}"
            elif now-t["opened_at"]>=timedelta(minutes=MAX_HOLD_MIN):
                reason=f"{MAX_HOLD_MIN}분 관찰 종료"
        if reason:
            close_trade(cur,t,now,reason,score,chart)
            closed+=1
    return closed

def update_status():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM radar_paper_trades WHERE status='OPEN'")
        open_count=int(cur.fetchone()["n"] or 0)
        cur.execute("""SELECT COUNT(*) AS n FROM radar_paper_trades
                       WHERE closed_at IS NOT NULL
                         AND (closed_at AT TIME ZONE 'Asia/Seoul')::date
                             =(now() AT TIME ZONE 'Asia/Seoul')::date""")
        closed_today=int(cur.fetchone()["n"] or 0)
        cur.execute("""INSERT INTO radar_paper_status(id,updated_at,status,open_count,closed_today,note)
                       VALUES(1,now(),'OK',%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',
                         open_count=excluded.open_count,closed_today=excluded.closed_today,note=excluded.note""",
                    (open_count,closed_today,
                     f"{RULE_VERSION}; 1 normalized unit; no orders; score {ENTRY_SCORE}/{EXIT_SCORE}; max {MAX_HOLD_MIN}m; ai_gate={REQUIRE_AI_BROKERAGE}"))

def cycle():
    now=datetime.now(timezone.utc)
    with db() as c,c.cursor() as cur:
        maybe_close_and_mark(cur,now)
        maybe_open(cur,now)
    update_status()

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print(f"Paper Lab started: {RULE_VERSION}; no orders; score>={ENTRY_SCORE}; hold<={MAX_HOLD_MIN}m; ai_gate={REQUIRE_AI_BROKERAGE}",flush=True)
    while True:
        started=time.monotonic()
        try:cycle()
        except Exception as exc:
            print("Paper Lab error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
