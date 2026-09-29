"""Persist operational risk-control snapshots.

This worker never sends orders. It evaluates the dashboard's deterministic
Kill Switch / Live Readiness / Rebalance output and stores the current state so
other Shadow services can fail-safe on stale or HALT conditions.
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
POLL=max(15,min(300,int(os.getenv("RISK_CONTROL_POLL_SECONDS","30"))))

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_risk_control_snapshots(
  snapshot_time TIMESTAMPTZ PRIMARY KEY,
  state TEXT NOT NULL,
  allow_new_shadow_entries BOOLEAN NOT NULL,
  live_stage TEXT,
  hard_trigger_count INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_risk_control_state_time
  ON ai_risk_control_snapshots(state,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS ai_risk_control_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  state TEXT NOT NULL,
  allow_new_shadow_entries BOOLEAN NOT NULL,
  live_stage TEXT,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419073,))
        cur.execute(SCHEMA)

def floor_time(dt):
    return dt.replace(second=0,microsecond=0)

def cycle():
    if not DASHBOARD_TOKEN:
        raise RuntimeError("DASHBOARD_TOKEN missing")
    payload=dashboard(x_dashboard_token=DASHBOARD_TOKEN)
    rc=payload.get("ai_risk_control") or {}
    kill=rc.get("kill_switch") or {}
    ready=rc.get("live_readiness") or {}
    snap=floor_time(datetime.now(timezone.utc))
    state=str(kill.get("state") or "DEGRADED")
    allow=bool(kill.get("allow_new_shadow_entries",False))
    hard=len(kill.get("hard_triggers") or [])
    warns=len(kill.get("warnings") or [])
    live_stage=str(ready.get("stage") or "RESEARCH_ONLY")
    body=json.dumps(rc,ensure_ascii=False)
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO ai_risk_control_snapshots(
                       snapshot_time,state,allow_new_shadow_entries,live_stage,
                       hard_trigger_count,warning_count,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(snapshot_time) DO UPDATE SET
                         state=excluded.state,
                         allow_new_shadow_entries=excluded.allow_new_shadow_entries,
                         live_stage=excluded.live_stage,
                         hard_trigger_count=excluded.hard_trigger_count,
                         warning_count=excluded.warning_count,
                         payload=excluded.payload""",
                    (snap,state,allow,live_stage,hard,warns,body))
        cur.execute("""INSERT INTO ai_risk_control_status(
                       id,updated_at,state,allow_new_shadow_entries,live_stage,note)
                       VALUES(1,now(),%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),state=excluded.state,
                         allow_new_shadow_entries=excluded.allow_new_shadow_entries,
                         live_stage=excluded.live_stage,note=excluded.note""",
                    (state,allow,live_stage,
                     "operational risk control only; no broker orders"))
    return {"snapshot_time":snap.isoformat(),"state":state,"allow":allow,"live_stage":live_stage}

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Risk control worker started; no broker orders",flush=True)
    while True:
        started=time.monotonic()
        try:
            print("Risk control",cycle(),flush=True)
        except Exception as exc:
            print("Risk control worker error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
