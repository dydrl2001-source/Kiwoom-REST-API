"""Non-destructive resilience audit worker.

Runs synthetic Kill Switch scenarios and replays persisted incident transitions.
It never alters market data, service availability, Shadow positions, or broker state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

import psycopg
from psycopg.rows import dict_row

from ai_brokerage.resilience import (
    RecoveryPolicy,
    audit_incident_timeline,
    replay_recovery_sequence,
    run_chaos_suite,
)
from ai_brokerage.risk_control import RiskControlPolicy, evaluate_kill_switch

DB=os.getenv("DATABASE_URL","")
POLL=max(60,min(3600,int(os.getenv("RESILIENCE_AUDIT_SECONDS","300"))))
RECOVERY=RecoveryPolicy(
    healthy_streak_required=max(1,min(20,int(os.getenv("RISK_RECOVERY_HEALTHY_STREAK","3")))),
    require_ack=os.getenv("RISK_RECOVERY_REQUIRE_ACK","1").strip().lower() in ("1","true","yes","on"),
)

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_resilience_audit_runs(
  run_time TIMESTAMPTZ PRIMARY KEY,
  status TEXT NOT NULL,
  scenario_count INTEGER NOT NULL DEFAULT 0,
  passed_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  replay_rows INTEGER NOT NULL DEFAULT 0,
  replay_status TEXT,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_resilience_status_time
  ON ai_resilience_audit_runs(status,run_time DESC);

CREATE TABLE IF NOT EXISTS ai_resilience_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  scenario_count INTEGER NOT NULL DEFAULT 0,
  passed_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  replay_status TEXT,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419074,))
        cur.execute(SCHEMA)

def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s)",("public."+name,))
    r=cur.fetchone()
    return bool(r and r["to_regclass"] is not None)

def baseline():
    return {
        "daily_shadow_return_pct":-0.2,
        "risk_utilization_pct":60,
        "median_round_trip_is_bps":20,
        "execution_reject_pct":10,
        "book_coverage_pct":90,
        "max_portfolio_corr":0.55,
        "unknown_corr_pairs":0,
        "critical_feeds":{
            "kiwoom":{"status":"OK","age_sec":20},
            "regime":{"status":"OK","age_sec":20},
            "chart":{"status":"OK","age_sec":20},
        },
        "orderbook_feed":{"status":"OK","age_sec":15},
        "manual_halt":False,
    }

def synthetic_recovery_audit():
    policy=RiskControlPolicy()
    healthy=evaluate_kill_switch(baseline(),policy)
    bad=dict(baseline());bad["daily_shadow_return_pct"]=-3.0
    halt=evaluate_kill_switch(bad,policy)
    seq=[halt,healthy,healthy,healthy]
    replay=replay_recovery_sequence(seq,{3} if RECOVERY.require_ack else set(),RECOVERY)
    final=replay[-1]
    passed=(final["state"]=="RUN" and final["recovery_state"]=="RECOVERED")
    return {"pass":passed,"sequence":replay}

def persisted_replay(cur):
    if not table_exists(cur,"ai_risk_control_snapshots"):
        return {"status":"NO_HISTORY","rows":0,"incidents":0,"violations":[]}
    cur.execute("""SELECT state,raw_state,incident_id,recovery_state,healthy_streak,acknowledged_at
                   FROM ai_risk_control_snapshots
                   WHERE snapshot_time>now()-interval '30 days'
                   ORDER BY snapshot_time ASC""")
    rows=[dict(r) for r in cur.fetchall()]
    if not rows:return {"status":"NO_HISTORY","rows":0,"incidents":0,"violations":[]}
    return audit_incident_timeline(rows,RECOVERY)

def cycle():
    policy=RiskControlPolicy()
    chaos=run_chaos_suite(baseline(),lambda m:evaluate_kill_switch(m,policy))
    recovery=synthetic_recovery_audit()
    with db() as c,c.cursor() as cur:
        replay=persisted_replay(cur)
        passed=chaos["passed"]+(1 if recovery["pass"] else 0)
        total=chaos["scenario_count"]+1
        failed=total-passed
        overall="PASS" if failed==0 and replay.get("status") in ("PASS","NO_HISTORY") else "FAIL"
        payload={
            "chaos":chaos,"synthetic_recovery":recovery,"incident_replay":replay,
            "non_destructive":True,
        }
        now=datetime.now(timezone.utc)
        cur.execute("""INSERT INTO ai_resilience_audit_runs(
                       run_time,status,scenario_count,passed_count,failed_count,
                       replay_rows,replay_status,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (now,overall,total,passed,failed,int(replay.get("rows") or 0),
                     replay.get("status"),json.dumps(payload,ensure_ascii=False)))
        cur.execute("""INSERT INTO ai_resilience_status(
                       id,updated_at,status,scenario_count,passed_count,failed_count,replay_status,note)
                       VALUES(1,now(),%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
                         scenario_count=excluded.scenario_count,passed_count=excluded.passed_count,
                         failed_count=excluded.failed_count,replay_status=excluded.replay_status,
                         note=excluded.note""",
                    (overall,total,passed,failed,replay.get("status"),
                     "non-destructive synthetic chaos + persisted incident replay"))
    return {"status":overall,"passed":passed,"total":total,"replay":replay.get("status")}

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Resilience audit worker started; non-destructive only",flush=True)
    while True:
        started=time.monotonic()
        try:print("Resilience audit",cycle(),flush=True)
        except Exception as exc:print("Resilience audit error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
