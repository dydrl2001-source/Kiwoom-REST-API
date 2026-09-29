"""Persist Capital Allocation Optimizer snapshots.

Read-only with respect to brokerage systems. The worker calls the local dashboard
builder, stores the shadow allocation proposal and never sends an order.
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
POLL=max(30,min(600,int(os.getenv("ALLOCATION_SNAPSHOT_SECONDS","60"))))

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_allocation_snapshots(
  snapshot_time TIMESTAMPTZ PRIMARY KEY,
  status TEXT NOT NULL,
  new_positions INTEGER NOT NULL DEFAULT 0,
  existing_risk_krw NUMERIC,
  new_allocated_risk_krw NUMERIC,
  actual_total_risk_krw NUMERIC,
  total_risk_cap_krw NUMERIC,
  risk_utilization_pct DOUBLE PRECISION,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_allocation_created
  ON ai_allocation_snapshots(created_at DESC);

CREATE TABLE IF NOT EXISTS ai_allocation_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  snapshot_time TIMESTAMPTZ,
  new_positions INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419072,))
        cur.execute(SCHEMA)

def minute_floor(dt):
    return dt.replace(second=0,microsecond=0)

def cycle():
    if not DASHBOARD_TOKEN:
        raise RuntimeError("DASHBOARD_TOKEN missing")
    payload=dashboard(x_dashboard_token=DASHBOARD_TOKEN)
    alloc=payload.get("ai_allocation") or {}
    summary=alloc.get("summary") or {}
    snap=minute_floor(datetime.now(timezone.utc))
    body=json.dumps(alloc,ensure_ascii=False)
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO ai_allocation_snapshots(
                       snapshot_time,status,new_positions,existing_risk_krw,new_allocated_risk_krw,
                       actual_total_risk_krw,total_risk_cap_krw,risk_utilization_pct,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(snapshot_time) DO UPDATE SET
                         status=excluded.status,new_positions=excluded.new_positions,
                         existing_risk_krw=excluded.existing_risk_krw,
                         new_allocated_risk_krw=excluded.new_allocated_risk_krw,
                         actual_total_risk_krw=excluded.actual_total_risk_krw,
                         total_risk_cap_krw=excluded.total_risk_cap_krw,
                         risk_utilization_pct=excluded.risk_utilization_pct,payload=excluded.payload""",
                    (snap,alloc.get("status") or "WAITING",int(summary.get("new_positions") or 0),
                     summary.get("existing_risk_krw"),summary.get("new_allocated_risk_krw"),
                     summary.get("actual_total_risk_krw"),summary.get("total_risk_cap_krw"),
                     summary.get("risk_utilization_pct"),body))
        cur.execute("""INSERT INTO ai_allocation_status(id,updated_at,status,snapshot_time,new_positions,note)
                       VALUES(1,now(),%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
                         snapshot_time=excluded.snapshot_time,new_positions=excluded.new_positions,
                         note=excluded.note""",
                    (alloc.get("status") or "WAITING",snap,int(summary.get("new_positions") or 0),
                     "shadow allocation snapshots only; no broker orders"))
    return {"snapshot_time":snap.isoformat(),"status":alloc.get("status"),
            "new_positions":summary.get("new_positions")}

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Capital allocation snapshot worker started; no broker orders",flush=True)
    while True:
        started=time.monotonic()
        try:
            result=cycle()
            print("Allocation snapshot",result,flush=True)
        except Exception as exc:
            print("Allocation snapshot error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
