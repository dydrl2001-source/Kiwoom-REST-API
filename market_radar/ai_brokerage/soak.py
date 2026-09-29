from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

@dataclass(frozen=True)
class SoakPolicy:
    min_duration_hours: float = 72.0
    min_samples: int = 36
    min_ready_pass_pct: float = 99.0
    min_resilience_pass_pct: float = 99.0
    min_risk_fresh_pct: float = 99.0
    max_unexpected_halts: int = 0
    max_unsafe_recovery_violations: int = 0
    max_preflight_failures: int = 0
    max_schema_drift_events: int = 0
    max_worker_error_samples: int = 0

def pct(num:int,den:int):
    return num/den*100.0 if den else None

def evaluate_soak(snapshots:list[dict[str,Any]],incidents=None,resilience_runs=None,policy=None):
    p=policy or SoakPolicy()
    rows=sorted(snapshots,key=lambda x:str(x.get("sample_time") or ""))
    n=len(rows)
    def parse(v):
        if isinstance(v,datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(v)).astimezone(timezone.utc)
    duration=0.0
    if n:
        try: duration=max(0.0,(parse(rows[-1]["sample_time"])-parse(rows[0]["sample_time"])).total_seconds()/3600.0)
        except Exception: duration=0.0
    ready=pct(sum(r.get("ready_ok") is True for r in rows),n)
    resil=pct(sum(str(r.get("resilience_status") or "").upper()=="PASS" for r in rows),n)
    fresh=pct(sum(r.get("risk_fresh") is True for r in rows),n)
    preflight_fail=sum(r.get("preflight_ok") is False for r in rows)
    schema_fail=sum(r.get("schema_ok") is False for r in rows)
    worker_fail=sum(int(r.get("worker_error_count") or 0)>0 for r in rows)
    inc=incidents or []
    unexpected=sum(
        str(x.get("state") or "").upper()=="HALT"
        and not bool(x.get("planned"))
        and "MANUAL_HALT" not in set(x.get("trigger_codes") or [])
        for x in inc
    )
    rr=resilience_runs or []
    unsafe=sum(int(x.get("unsafe_recovery_violations") or 0) for x in rr)
    resil_fail=sum(str(x.get("status") or "").upper()=="FAIL" for x in rr)
    gates=[
        {"id":"DURATION","pass":duration>=p.min_duration_hours,"value":duration,"required":p.min_duration_hours},
        {"id":"SAMPLES","pass":n>=p.min_samples,"value":n,"required":p.min_samples},
        {"id":"READY","pass":(ready or 0)>=p.min_ready_pass_pct,"value":ready,"required":p.min_ready_pass_pct},
        {"id":"RESILIENCE","pass":(resil or 0)>=p.min_resilience_pass_pct,"value":resil,"required":p.min_resilience_pass_pct},
        {"id":"RISK_FRESH","pass":(fresh or 0)>=p.min_risk_fresh_pct,"value":fresh,"required":p.min_risk_fresh_pct},
        {"id":"UNEXPECTED_HALTS","pass":unexpected<=p.max_unexpected_halts,"value":unexpected,"required":p.max_unexpected_halts},
        {"id":"UNSAFE_RECOVERY","pass":unsafe<=p.max_unsafe_recovery_violations,"value":unsafe,"required":p.max_unsafe_recovery_violations},
        {"id":"PREFLIGHT_FAILURES","pass":preflight_fail<=p.max_preflight_failures,"value":preflight_fail,"required":p.max_preflight_failures},
        {"id":"SCHEMA_DRIFT","pass":schema_fail<=p.max_schema_drift_events,"value":schema_fail,"required":p.max_schema_drift_events},
        {"id":"WORKER_ERRORS","pass":worker_fail<=p.max_worker_error_samples,"value":worker_fail,"required":p.max_worker_error_samples},
        {"id":"RESILIENCE_RUN_FAILURES","pass":resil_fail==0,"value":resil_fail,"required":0},
    ]
    hard_ids={"UNEXPECTED_HALTS","UNSAFE_RECOVERY","PREFLIGHT_FAILURES","SCHEMA_DRIFT","WORKER_ERRORS","RESILIENCE_RUN_FAILURES"}
    hard=any(not g["pass"] for g in gates if g["id"] in hard_ids)
    complete=all(g["pass"] for g in gates)
    stage="RC_CANDIDATE" if complete else "SOAK_FAILED" if hard else "SOAK_IN_PROGRESS"
    return {
        "stage":stage,"rc_candidate":stage=="RC_CANDIDATE","gates":gates,
        "failed_gates":[g["id"] for g in gates if not g["pass"]],
        "metrics":{"samples":n,"duration_hours":duration,"ready_pass_pct":ready,
                   "resilience_pass_pct":resil,"risk_fresh_pct":fresh,
                   "preflight_failures":preflight_fail,"schema_drift_events":schema_fail,
                   "worker_error_samples":worker_fail,"unexpected_halts":unexpected,
                   "unsafe_recovery_violations":unsafe,"resilience_fail_runs":resil_fail},
        "policy":asdict(p),"live_enabled":False
    }
