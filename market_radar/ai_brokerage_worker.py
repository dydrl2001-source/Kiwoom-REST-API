"""Persist AI Brokerage decision snapshots.

This worker reuses the dashboard's normalized decision path and stores the current
6-Desk decision packet. It never sends broker orders and never calls an AI provider.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

import psycopg
from psycopg.rows import dict_row

from radar_api import DASHBOARD_TOKEN, dashboard

DB=os.getenv("DATABASE_URL","")
POLL=max(15,min(300,int(os.getenv("AI_BROKERAGE_POLL_SECONDS","30"))))

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_brokerage_decisions(
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  state TEXT NOT NULL,
  conviction DOUBLE PRECISION,
  strategy_id TEXT,
  strategy_name TEXT,
  strategy_family TEXT,
  strategy_fit DOUBLE PRECISION,
  strategy_lifecycle TEXT,
  regime_label TEXT,
  market_theme TEXT,
  decision_version TEXT,
  packet JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(snapshot_time,stock_code)
);
CREATE INDEX IF NOT EXISTS idx_ai_brokerage_decisions_code_time
  ON ai_brokerage_decisions(stock_code,snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_ai_brokerage_decisions_strategy_time
  ON ai_brokerage_decisions(strategy_id,snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_ai_brokerage_decisions_state_time
  ON ai_brokerage_decisions(state,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS ai_brokerage_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  snapshot_time TIMESTAMPTZ,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  paper_entry_count INTEGER NOT NULL DEFAULT 0,
  ready_count INTEGER NOT NULL DEFAULT 0,
  blocked_count INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419069,))
        cur.execute(SCHEMA)

def parse_time(value):
    if isinstance(value,datetime):
        dt=value
    else:
        dt=datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def minute_floor(dt):
    return dt.replace(second=0,microsecond=0)

def cycle():
    if not DASHBOARD_TOKEN:
        raise RuntimeError("DASHBOARD_TOKEN missing")
    payload=dashboard(x_dashboard_token=DASHBOARD_TOKEN)
    broker=payload.get("ai_brokerage") or {}
    generated=parse_time(payload.get("generated_at") or datetime.now(timezone.utc))
    snap=minute_floor(generated)
    row_by_code={str(x.get("code") or ""):x for x in (payload.get("query_ranking") or [])}
    candidates=broker.get("candidates") or []
    regime=(payload.get("regime") or {}).get("stable_label") or (payload.get("regime") or {}).get("candidate_label")
    counts={"PAPER_ENTRY":0,"READY":0,"BLOCKED":0}

    with db() as c,c.cursor() as cur:
        for packet in candidates:
            code=str(packet.get("stock_code") or "")
            if not code:continue
            state=str(packet.get("state") or "IGNORE")
            if state in counts:counts[state]+=1
            strategy=packet.get("selected_strategy") or {}
            source=row_by_code.get(code) or {}
            cur.execute("""INSERT INTO ai_brokerage_decisions(
                           snapshot_time,stock_code,stock_name,state,conviction,
                           strategy_id,strategy_name,strategy_family,strategy_fit,strategy_lifecycle,
                           regime_label,market_theme,decision_version,packet)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                           ON CONFLICT(snapshot_time,stock_code) DO UPDATE SET
                             stock_name=excluded.stock_name,state=excluded.state,conviction=excluded.conviction,
                             strategy_id=excluded.strategy_id,strategy_name=excluded.strategy_name,
                             strategy_family=excluded.strategy_family,strategy_fit=excluded.strategy_fit,
                             strategy_lifecycle=excluded.strategy_lifecycle,regime_label=excluded.regime_label,
                             market_theme=excluded.market_theme,decision_version=excluded.decision_version,
                             packet=excluded.packet""",
                        (snap,code,packet.get("stock_name"),state,packet.get("conviction"),
                         strategy.get("strategy_id"),strategy.get("name"),strategy.get("family"),
                         strategy.get("fit_score"),strategy.get("lifecycle"),regime,
                         source.get("market_theme") or source.get("official_sector"),
                         packet.get("version"),json.dumps(packet,ensure_ascii=False)))
        cur.execute("""INSERT INTO ai_brokerage_status(
                       id,updated_at,status,snapshot_time,candidate_count,paper_entry_count,
                       ready_count,blocked_count,note)
                       VALUES(1,now(),%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
                         snapshot_time=excluded.snapshot_time,candidate_count=excluded.candidate_count,
                         paper_entry_count=excluded.paper_entry_count,ready_count=excluded.ready_count,
                         blocked_count=excluded.blocked_count,note=excluded.note""",
                    (broker.get("status") or "OK",snap,len(candidates),counts["PAPER_ENTRY"],
                     counts["READY"],counts["BLOCKED"],
                     "6-Desk decision snapshots; paper-only; no broker orders"))
    return {"snapshot_time":snap.isoformat(),"candidates":len(candidates),**counts}

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("AI Brokerage worker started; decision persistence only; no orders",flush=True)
    while True:
        started=time.monotonic()
        try:
            result=cycle()
            print("AI Brokerage snapshot",result,flush=True)
        except Exception as exc:
            print("AI Brokerage worker error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
