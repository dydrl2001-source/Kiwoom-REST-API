"""Persist multi-day staging soak snapshots and RC-candidate evidence."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
import time

import psycopg
from psycopg.rows import dict_row

from ai_brokerage.soak import SoakPolicy, evaluate_soak
from radar_api import DASHBOARD_TOKEN, dashboard

DB=os.getenv("DATABASE_URL","")
POLL=max(60,min(3600,int(os.getenv("SOAK_SAMPLE_SECONDS","600"))))
SCHEMA_VERSION=os.getenv("MARKET_RADAR_SCHEMA_VERSION","2026.09.29.1")

POLICY=SoakPolicy(
    min_duration_hours=max(1.0,float(os.getenv("SOAK_MIN_DURATION_HOURS","72"))),
    min_samples=max(3,int(os.getenv("SOAK_MIN_SAMPLES","36"))),
    min_ready_pass_pct=max(50.0,min(100.0,float(os.getenv("SOAK_MIN_READY_PASS_PCT","99")))),
    min_resilience_pass_pct=max(50.0,min(100.0,float(os.getenv("SOAK_MIN_RESILIENCE_PASS_PCT","99")))),
    min_risk_fresh_pct=max(50.0,min(100.0,float(os.getenv("SOAK_MIN_RISK_FRESH_PCT","99")))),
    max_unexpected_halts=max(0,int(os.getenv("SOAK_MAX_UNEXPECTED_HALTS","0"))),
    max_unsafe_recovery_violations=max(0,int(os.getenv("SOAK_MAX_UNSAFE_RECOVERY","0"))),
    max_preflight_failures=max(0,int(os.getenv("SOAK_MAX_PREFLIGHT_FAILURES","0"))),
    max_schema_drift_events=max(0,int(os.getenv("SOAK_MAX_SCHEMA_DRIFT","0"))),
    max_worker_error_samples=max(0,int(os.getenv("SOAK_MAX_WORKER_ERROR_SAMPLES","0"))),
)

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_soak_snapshots(
  sample_time TIMESTAMPTZ PRIMARY KEY,
  ready_ok BOOLEAN NOT NULL,
  schema_ok BOOLEAN NOT NULL,
  risk_fresh BOOLEAN NOT NULL,
  risk_state TEXT,
  resilience_status TEXT,
  preflight_ok BOOLEAN NOT NULL,
  worker_error_count INTEGER NOT NULL DEFAULT 0,
  shadow_closed INTEGER NOT NULL DEFAULT 0,
  book_coverage_pct DOUBLE PRECISION,
  risk_utilization_pct DOUBLE PRECISION,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_soak_time ON ai_soak_snapshots(sample_time DESC);

CREATE TABLE IF NOT EXISTS ai_soak_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  stage TEXT NOT NULL,
  rc_candidate BOOLEAN NOT NULL DEFAULT FALSE,
  sample_count INTEGER NOT NULL DEFAULT 0,
  duration_hours DOUBLE PRECISION NOT NULL DEFAULT 0,
  failed_gates JSONB NOT NULL DEFAULT '[]'::jsonb,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  note TEXT
);
"""

def db():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=20000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419076,))
        cur.execute(SCHEMA)

def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s)",("public."+name,))
    r=cur.fetchone()
    return bool(r and r["to_regclass"] is not None)

def status_value(cur,table):
    if not table_exists(cur,table):return None
    cur.execute(f"SELECT status FROM {table} WHERE id=1")
    r=cur.fetchone()
    return str(r["status"]) if r and r.get("status") is not None else None

def snapshot():
    if not DASHBOARD_TOKEN:raise RuntimeError("DASHBOARD_TOKEN missing")
    payload=dashboard(x_dashboard_token=DASHBOARD_TOKEN)
    risk=payload.get("ai_risk_control") or {}
    kill=risk.get("kill_switch") or {}
    resilience=payload.get("ai_resilience") or {}
    shadow=payload.get("shadow_execution") or {}
    alloc=payload.get("ai_allocation") or {}
    broker=payload.get("ai_brokerage") or {}

    now=datetime.now(timezone.utc)
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT EXISTS(
                       SELECT 1 FROM market_radar_schema_migrations
                       WHERE version=%s) AS ok""",(SCHEMA_VERSION,))
        schema_ok=bool(cur.fetchone()["ok"]) if table_exists(cur,"market_radar_schema_migrations") else False

        risk_fresh=False
        if table_exists(cur,"ai_risk_control_status"):
            cur.execute("SELECT updated_at FROM ai_risk_control_status WHERE id=1")
            r=cur.fetchone()
            if r and r["updated_at"]:
                age=(now-r["updated_at"].astimezone(timezone.utc)).total_seconds()
                risk_fresh=age<=max(30,min(600,int(os.getenv("RISK_CONTROL_STATUS_MAX_AGE_SECONDS","120"))))

        ready_ok=bool(schema_ok and risk_fresh)
        live=((risk.get("live_readiness") or {}).get("live_enabled"))
        states={x.get("state") for x in broker.get("candidates") or []}
        preflight_ok=(
            broker.get("paper_only") is True
            and live is False
            and "LIVE_ENTRY" not in states
            and isinstance(payload.get("ai_capacity"),dict)
            and isinstance(payload.get("ai_allocation"),dict)
            and isinstance(payload.get("ai_resilience"),dict)
            and isinstance(payload.get("shadow_execution"),dict)
        )

        status_tables=(
            "kiwoom_feed_status","chart_feed_status","market_regime_status",
            "orderbook_feed_status","ai_risk_control_status","ai_resilience_status",
        )
        worker_errors=0
        for name in status_tables:
            st=status_value(cur,name)
            if st and st.upper() in ("ERROR","FAILED","DOWN"):
                worker_errors+=1

        summary=shadow.get("summary") or {}
        row={
            "sample_time":now,
            "ready_ok":ready_ok,"schema_ok":schema_ok,"risk_fresh":risk_fresh,
            "risk_state":kill.get("state"),
            "resilience_status":resilience.get("status"),
            "preflight_ok":preflight_ok,
            "worker_error_count":worker_errors,
            "shadow_closed":int(summary.get("closed") or 0),
            "book_coverage_pct":summary.get("book_coverage_pct"),
            "risk_utilization_pct":(alloc.get("summary") or {}).get("risk_utilization_pct"),
        }
        cur.execute("""INSERT INTO ai_soak_snapshots(
                       sample_time,ready_ok,schema_ok,risk_fresh,risk_state,resilience_status,
                       preflight_ok,worker_error_count,shadow_closed,book_coverage_pct,
                       risk_utilization_pct,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(sample_time) DO NOTHING""",
                    (row["sample_time"],row["ready_ok"],row["schema_ok"],row["risk_fresh"],
                     row["risk_state"],row["resilience_status"],row["preflight_ok"],
                     row["worker_error_count"],row["shadow_closed"],row["book_coverage_pct"],
                     row["risk_utilization_pct"],json.dumps(row,default=str,ensure_ascii=False)))
    return row

def evaluate():
    lookback=max(POLICY.min_duration_hours+24,96)
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT sample_time,ready_ok,schema_ok,risk_fresh,risk_state,
                              resilience_status,preflight_ok,worker_error_count
                       FROM ai_soak_snapshots
                       WHERE sample_time>=now()-(%s || ' hours')::interval
                       ORDER BY sample_time""",(lookback,))
        snapshots=[dict(r) for r in cur.fetchall()]

        incidents=[]
        if table_exists(cur,"ai_incident_events"):
            cur.execute("""SELECT state,hard_triggers
                           FROM ai_incident_events
                           WHERE opened_at>=now()-(%s || ' hours')::interval""",(lookback,))
            for r in cur.fetchall():
                codes=[x.get("code") for x in (r["hard_triggers"] or []) if isinstance(x,dict)]
                incidents.append({"state":r["state"],"trigger_codes":codes,"planned":"MANUAL_HALT" in codes})

        resilience_runs=[]
        if table_exists(cur,"ai_resilience_audit_runs"):
            cur.execute("""SELECT status,payload FROM ai_resilience_audit_runs
                           WHERE run_time>=now()-(%s || ' hours')::interval""",(lookback,))
            for r in cur.fetchall():
                replay=((r["payload"] or {}).get("incident_replay") or {})
                resilience_runs.append({
                    "status":r["status"],
                    "unsafe_recovery_violations":len(replay.get("violations") or []),
                })

        result=evaluate_soak(snapshots,incidents,resilience_runs,POLICY)
        cur.execute("""INSERT INTO ai_soak_status(
                       id,updated_at,stage,rc_candidate,sample_count,duration_hours,
                       failed_gates,payload,note)
                       VALUES(1,now(),%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                       ON CONFLICT(id) DO UPDATE SET
                         updated_at=now(),stage=excluded.stage,rc_candidate=excluded.rc_candidate,
                         sample_count=excluded.sample_count,duration_hours=excluded.duration_hours,
                         failed_gates=excluded.failed_gates,payload=excluded.payload,note=excluded.note""",
                    (result["stage"],result["rc_candidate"],result["metrics"]["samples"],
                     result["metrics"]["duration_hours"],json.dumps(result["failed_gates"]),
                     json.dumps(result,ensure_ascii=False),
                     "multi-day staging soak gate; RC candidate does not enable live orders"))
    return result

def cycle():
    row=snapshot()
    result=evaluate()
    return {"sample_time":row["sample_time"].isoformat(),"stage":result["stage"],
            "samples":result["metrics"]["samples"],"hours":result["metrics"]["duration_hours"]}

def main():
    schema()
    print("Soak monitor started; staging evidence only",flush=True)
    while True:
        started=time.monotonic()
        try:print("Soak",cycle(),flush=True)
        except Exception as exc:print("Soak monitor error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
