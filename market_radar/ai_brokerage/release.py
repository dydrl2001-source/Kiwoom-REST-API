from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ReleasePolicy:
    require_ci_green: bool = True
    require_backup_restore: bool = True
    require_preflight: bool = True
    require_persistent_staging: bool = True
    require_branch_sync: bool = True


def evaluate_release_candidate(evidence: dict[str,Any], policy: ReleasePolicy | None=None) -> dict[str,Any]:
    p=policy or ReleasePolicy()
    gates=[
        {"id":"SOAK_RC_CANDIDATE",
         "pass":evidence.get("soak_stage")=="RC_CANDIDATE" and evidence.get("soak_rc_candidate") is True,
         "value":evidence.get("soak_stage"),"required":"RC_CANDIDATE"},
        {"id":"RISK_CONTROL_RUN","pass":evidence.get("risk_state")=="RUN",
         "value":evidence.get("risk_state"),"required":"RUN"},
        {"id":"RESILIENCE_PASS","pass":evidence.get("resilience_status")=="PASS",
         "value":evidence.get("resilience_status"),"required":"PASS"},
        {"id":"SCHEMA_CURRENT","pass":evidence.get("schema_ok") is True,
         "value":evidence.get("schema_version"),"required":evidence.get("required_schema_version")},
        {"id":"LIVE_DISABLED","pass":evidence.get("live_enabled") is False,
         "value":evidence.get("live_enabled"),"required":False},
        {"id":"NO_LIVE_ORDER_PATH","pass":evidence.get("live_order_path_present") is False,
         "value":evidence.get("live_order_path_present"),"required":False},
    ]
    optional=[
        ("CI_GREEN","ci_green_confirmed",p.require_ci_green),
        ("BACKUP_RESTORE","backup_restore_confirmed",p.require_backup_restore),
        ("PREFLIGHT_PASS","preflight_confirmed",p.require_preflight),
        ("PERSISTENT_STAGING","persistent_staging_confirmed",p.require_persistent_staging),
        ("BRANCH_SYNC","branch_sync_confirmed",p.require_branch_sync),
    ]
    for gate_id,key,required in optional:
        gates.append({
            "id":gate_id,
            "pass":(evidence.get(key) is True) if required else True,
            "value":evidence.get(key),
            "required":True if required else "optional",
        })
    ready=all(g["pass"] for g in gates)
    return {
        "stage":"RC_READY" if ready else "RC_BLOCKED",
        "rc_ready":ready,
        "gates":gates,
        "failed_gates":[g["id"] for g in gates if not g["pass"]],
        "evidence":evidence,
        "policy":asdict(p),
        "live_enabled":False,
        "note":"RC_READY is a release-review state only; it does not enable broker orders",
    }
