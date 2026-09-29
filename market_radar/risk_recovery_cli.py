"""Acknowledge a latched Risk Control incident.

This CLI only records human acknowledgement. It cannot force RUN, clear a HALT,
or place an order. Recovery still requires the configured consecutive healthy streak.
"""
from __future__ import annotations

import argparse
import os

import psycopg
from psycopg.rows import dict_row

DB=os.getenv("DATABASE_URL","")

def db():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5)

def status():
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT updated_at,state,raw_state,incident_id,recovery_state,
                              healthy_streak,healthy_streak_required,ack_required,
                              acknowledged_at,halted_at,recovered_at
                       FROM ai_risk_control_status WHERE id=1""")
        r=cur.fetchone()
        if not r:
            print("risk-control status: missing")
            return 2
        print(f"state={r['state']} raw={r['raw_state']} recovery={r['recovery_state']}")
        print(f"incident_id={r['incident_id'] or '-'}")
        print(f"healthy_streak={r['healthy_streak']}/{r['healthy_streak_required']}")
        print(f"ack_required={r['ack_required']} acknowledged_at={r['acknowledged_at'] or '-'}")
        print(f"halted_at={r['halted_at'] or '-'} recovered_at={r['recovered_at'] or '-'}")
        return 0

def acknowledge(incident_id: str):
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT state,incident_id,ack_required,acknowledged_at
                       FROM ai_risk_control_status WHERE id=1 FOR UPDATE""")
        r=cur.fetchone()
        if not r:
            raise RuntimeError("risk-control status missing")
        current=r["incident_id"]
        if str(r["state"]).upper()!="HALT":
            raise RuntimeError("current effective state is not HALT")
        if not current:
            raise RuntimeError("current HALT has no incident_id")
        if str(current)!=str(incident_id):
            raise RuntimeError(f"incident mismatch: current={current}")
        if r["acknowledged_at"]:
            print(f"already acknowledged: {r['acknowledged_at']}")
            return 0
        cur.execute("""UPDATE ai_risk_control_status
                       SET acknowledged_at=now(),updated_at=now()
                       WHERE id=1 AND incident_id=%s""",(incident_id,))
        cur.execute("""UPDATE ai_incident_events
                       SET acknowledged_at=COALESCE(acknowledged_at,now()),
                           last_seen_at=now()
                       WHERE incident_id=%s""",(incident_id,))
        print(f"acknowledged incident {incident_id}")
        print("HALT remains latched until healthy-streak criteria are met.")
        return 0

def main():
    p=argparse.ArgumentParser(description="Risk Control recovery acknowledgement; no force-run command")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("status")
    ack=sub.add_parser("ack")
    ack.add_argument("--incident",required=True)
    args=p.parse_args()
    if args.command=="status":raise SystemExit(status())
    if args.command=="ack":raise SystemExit(acknowledge(args.incident))

if __name__=="__main__":
    main()
