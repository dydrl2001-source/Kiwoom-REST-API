"""One-shot persistent soak pulse for an external staging deployment.

Designed for cron/systemd/GitHub manual workflows. It does not start services,
change deployment state, or place broker orders. It samples the protected dashboard,
persists a soak snapshot, evaluates the RC gate, then exits.
"""
from __future__ import annotations

import json
import os
import sys

from soak_monitor_worker import schema, snapshot, evaluate

def main():
    required=("DATABASE_URL","DASHBOARD_TOKEN")
    missing=[k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit("missing required env: "+",".join(missing))
    schema()
    row=snapshot()
    result=evaluate()
    out={
        "sample_time":row["sample_time"].isoformat(),
        "ready_ok":row["ready_ok"],
        "risk_fresh":row["risk_fresh"],
        "resilience_status":row["resilience_status"],
        "preflight_ok":row["preflight_ok"],
        "stage":result["stage"],
        "rc_candidate":result["rc_candidate"],
        "samples":result["metrics"]["samples"],
        "duration_hours":result["metrics"]["duration_hours"],
        "failed_gates":result["failed_gates"],
        "live_enabled":result["live_enabled"],
    }
    print(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    if result["stage"]=="SOAK_FAILED":
        raise SystemExit(2)

if __name__=="__main__":
    main()
