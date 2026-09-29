"""Persist operational risk-control snapshots with recovery latch.

This worker never sends orders. Raw Kill Switch output is latched on HALT.
Recovery requires consecutive healthy observations and, by default, an explicit
incident acknowledgement.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

import psycopg
from psycopg.rows import dict_row

from ai_brokerage.resilience import RecoveryPolicy, next_recovery_state
from radar_api import DASHBOARD_TOKEN, dashboard

DB=os.getenv("DATABASE_URL","")
POLL=max(15,min(300,int(os.getenv("RISK_CONTROL_POLL_SECONDS","30"))))
RECOVERY_POLICY=RecoveryPolicy(
    healthy_streak_required=max(1,min(20,int(os.getenv("RISK_RECOVERY_HEALTHY_STREAK","3")))),
    require_ack=os.getenv("RISK_RECOVERY_REQUIRE_ACK","1").strip().lower() in ("1","true","yes","on"),
)

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_risk_control_snapshots(
  snapshot_time TIMESTAMPTZ PRIMARY KEY,
  state TEXT NOT NULL,
  raw_state TEXT,
  allow_new_shadow_entries BOOLEAN NOT NULL,
  live_stage TEXT,
  incident_id TEXT,
  recovery_state TEXT,
  healthy_streak INTEGER NOT NULL DEFAULT 0,
  acknowledged_at TIMESTAMPTZ,
  hard_trigger_count INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_risk_control_snapshots ADD COLUMN IF NOT EXISTS raw_state TEXT;
ALTER TABLE ai_risk_control_snapshots ADD COLUMN IF NOT EXISTS incident_id TEXT;
ALTER TABLE ai_risk_control_snapshots ADD COLUMN IF NOT EXISTS recovery_state TEXT;
ALTER TABLE ai_risk_control_snapshots ADD COLUMN IF NOT EXISTS healthy_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_risk_control_snapshots ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_risk_control_state_time
  ON ai_risk_control_snapshots(state,snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_risk_incident_time
  ON ai_risk_control_snapshots(incident_id,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS ai_risk_control_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  state TEXT NOT NULL,
  raw_state TEXT,
  allow_new_shadow_entries BOOLEAN NOT NULL,
  live_stage TEXT,
  incident_id TEXT,
  recovery_state TEXT,
  healthy_streak INTEGER NOT NULL DEFAULT 0,
  healthy_streak_required INTEGER NOT NULL DEFAULT 3,
  ack_required BOOLEAN NOT NULL DEFAULT TRUE,
  acknowledged_at TIMESTAMPTZ,
  halted_at TIMESTAMPTZ,
  recovered_at TIMESTAMPTZ,
  note TEXT
);
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS raw_state TEXT;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS incident_id TEXT;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS recovery_state TEXT;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS healthy_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS healthy_streak_required INTEGER NOT NULL DEFAULT 3;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS ack_required BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS halted_at TIMESTAMPTZ;
ALTER TABLE ai_risk_control_status ADD COLUMN IF NOT EXISTS recovered_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS ai_incident_events(
  incident_id TEXT PRIMARY KEY,
  opened_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ,
  state TEXT NOT NULL,
  raw_state TEXT,
  recovery_state TEXT,
  healthy_streak INTEGER NOT NULL DEFAULT 0,
  ack_required BOOLEAN NOT NULL DEFAULT TRUE,
  acknowledged_at TIMESTAMPTZ,
  hard_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
  warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
  last_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_incident_opened
  ON ai_incident_events(opened_at DESC);
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

def _dt(value):
    if not value:return None
    if isinstance(value,datetime):return value
    try:return datetime.fromisoformat(str(value))
    except Exception:return None

def previous_state(cur):
    cur.execute("""SELECT state,raw_state,incident_id,recovery_state,healthy_streak,
                          healthy_streak_required,ack_required,acknowledged_at,
                          halted_at,recovered_at
                   FROM ai_risk_control_status WHERE id=1""")
    r=cur.fetchone()
    if not r:return None
    return {
        "state":r["state"],"raw_state":r["raw_state"],"incident_id":r["incident_id"],
        "recovery_state":r["recovery_state"],"healthy_streak":r["healthy_streak"],
        "healthy_streak_required":r["healthy_streak_required"],"ack_required":r["ack_required"],
        "acknowledged_at":r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
        "halted_at":r["halted_at"].isoformat() if r["halted_at"] else None,
        "recovered_at":r["recovered_at"].isoformat() if r["recovered_at"] else None,
    }

def cycle():
    if not DASHBOARD_TOKEN:
        raise RuntimeError("DASHBOARD_TOKEN missing")
    payload=dashboard(x_dashboard_token=DASHBOARD_TOKEN)
    rc=payload.get("ai_risk_control") or {}
    raw=rc.get("kill_switch_raw") or rc.get("kill_switch") or {}
    ready=rc.get("live_readiness") or {}
    snap=floor_time(datetime.now(timezone.utc))
    live_stage=str(ready.get("stage") or "RESEARCH_ONLY")

    with db() as c,c.cursor() as cur:
        prev=previous_state(cur)
        effective=next_recovery_state(prev,raw,False,RECOVERY_POLICY,datetime.now(timezone.utc))
        state=str(effective["state"])
        raw_state=str(effective["raw_state"])
        allow=bool(effective["allow_new_shadow_entries"])
        incident_id=effective.get("incident_id")
        recovery_state=str(effective.get("recovery_state") or "NORMAL")
        healthy=int(effective.get("healthy_streak") or 0)
        ack_at=_dt(effective.get("acknowledged_at"))
        halted_at=_dt(effective.get("halted_at"))
        recovered_at=_dt(effective.get("recovered_at"))
        hard=len(raw.get("hard_triggers") or [])
        warns=len(raw.get("warnings") or [])

        persisted={
            **rc,
            "kill_switch_raw":raw,
            "kill_switch_effective":{
                **raw,
                "state":state,
                "allow_new_shadow_entries":allow,
                "incident_id":incident_id,
                "recovery_state":recovery_state,
                "healthy_streak":healthy,
                "healthy_streak_required":RECOVERY_POLICY.healthy_streak_required,
                "ack_required":RECOVERY_POLICY.require_ack,
                "acknowledged_at":effective.get("acknowledged_at"),
                "halted_at":effective.get("halted_at"),
                "recovered_at":effective.get("recovered_at"),
                "effective_reason":effective.get("effective_reason"),
            }
        }
        body=json.dumps(persisted,ensure_ascii=False)

        cur.execute("""INSERT INTO ai_risk_control_snapshots(
                       snapshot_time,state,raw_state,allow_new_shadow_entries,live_stage,
                       incident_id,recovery_state,healthy_streak,acknowledged_at,
                       hard_trigger_count,warning_count,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(snapshot_time) DO UPDATE SET
                         state=excluded.state,raw_state=excluded.raw_state,
                         allow_new_shadow_entries=excluded.allow_new_shadow_entries,
                         live_stage=excluded.live_stage,incident_id=excluded.incident_id,
                         recovery_state=excluded.recovery_state,healthy_streak=excluded.healthy_streak,
                         acknowledged_at=excluded.acknowledged_at,
                         hard_trigger_count=excluded.hard_trigger_count,
                         warning_count=excluded.warning_count,payload=excluded.payload""",
                    (snap,state,raw_state,allow,live_stage,incident_id,recovery_state,
                     healthy,ack_at,hard,warns,body))

        cur.execute("""INSERT INTO ai_risk_control_status(
                       id,updated_at,state,raw_state,allow_new_shadow_entries,live_stage,
                       incident_id,recovery_state,healthy_streak,healthy_streak_required,
                       ack_required,acknowledged_at,halted_at,recovered_at,note)
                       VALUES(1,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET
                         updated_at=now(),state=excluded.state,raw_state=excluded.raw_state,
                         allow_new_shadow_entries=excluded.allow_new_shadow_entries,
                         live_stage=excluded.live_stage,incident_id=excluded.incident_id,
                         recovery_state=excluded.recovery_state,healthy_streak=excluded.healthy_streak,
                         healthy_streak_required=excluded.healthy_streak_required,
                         ack_required=excluded.ack_required,
                         acknowledged_at=excluded.acknowledged_at,
                         halted_at=excluded.halted_at,recovered_at=excluded.recovered_at,
                         note=excluded.note""",
                    (state,raw_state,allow,live_stage,incident_id,recovery_state,healthy,
                     RECOVERY_POLICY.healthy_streak_required,RECOVERY_POLICY.require_ack,
                     ack_at,halted_at,recovered_at,
                     "latched operational risk control; no broker orders"))

        if incident_id:
            cur.execute("""INSERT INTO ai_incident_events(
                           incident_id,opened_at,last_seen_at,closed_at,state,raw_state,
                           recovery_state,healthy_streak,ack_required,acknowledged_at,
                           hard_triggers,warnings,last_payload)
                           VALUES(%s,COALESCE(%s,now()),now(),%s,%s,%s,%s,%s,%s,%s,
                                  %s::jsonb,%s::jsonb,%s::jsonb)
                           ON CONFLICT(incident_id) DO UPDATE SET
                             last_seen_at=now(),closed_at=excluded.closed_at,state=excluded.state,
                             raw_state=excluded.raw_state,recovery_state=excluded.recovery_state,
                             healthy_streak=excluded.healthy_streak,ack_required=excluded.ack_required,
                             acknowledged_at=COALESCE(ai_incident_events.acknowledged_at,excluded.acknowledged_at),
                             hard_triggers=excluded.hard_triggers,warnings=excluded.warnings,
                             last_payload=excluded.last_payload""",
                        (incident_id,halted_at,recovered_at,state,raw_state,recovery_state,
                         healthy,RECOVERY_POLICY.require_ack,ack_at,
                         json.dumps(raw.get("hard_triggers") or [],ensure_ascii=False),
                         json.dumps(raw.get("warnings") or [],ensure_ascii=False),body))

    return {
        "snapshot_time":snap.isoformat(),"state":state,"raw_state":raw_state,
        "allow":allow,"live_stage":live_stage,"incident_id":incident_id,
        "recovery_state":recovery_state,"healthy_streak":healthy,
    }

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Risk control worker started with recovery latch; no broker orders",flush=True)
    while True:
        started=time.monotonic()
        try:
            print("Risk control",cycle(),flush=True)
        except Exception as exc:
            print("Risk control worker error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
