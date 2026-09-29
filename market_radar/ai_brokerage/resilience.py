from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import uuid
from typing import Any, Callable


@dataclass(frozen=True)
class RecoveryPolicy:
    healthy_streak_required: int = 3
    require_ack: bool = True


def next_recovery_state(
    previous: dict[str,Any] | None,
    raw_kill: dict[str,Any],
    acknowledged: bool=False,
    policy: RecoveryPolicy | None=None,
    now: datetime | None=None,
) -> dict[str,Any]:
    """Turn a raw Kill Switch evaluation into a latched operational state.

    A raw HALT always latches. Recovery requires consecutive raw RUN observations
    and, by default, an explicit acknowledgement. DEGRADED never counts as healthy.
    """
    p=policy or RecoveryPolicy()
    now=now or datetime.now(timezone.utc)
    prev=previous or {}
    raw_state=str(raw_kill.get("state") or "DEGRADED").upper()
    prev_state=str(prev.get("state") or "RUN").upper()
    incident_id=prev.get("incident_id")
    halted_at=prev.get("halted_at")
    ack_at=prev.get("acknowledged_at")
    healthy=int(prev.get("healthy_streak") or 0)

    if raw_state=="HALT":
        continuing=prev_state=="HALT" and incident_id
        if not continuing:
            incident_id=str(uuid.uuid4())
            halted_at=now.isoformat()
            ack_at=None
        return {
            "state":"HALT",
            "raw_state":"HALT",
            "incident_id":incident_id,
            "recovery_state":"LATCHED",
            "healthy_streak":0,
            "healthy_streak_required":p.healthy_streak_required,
            "ack_required":p.require_ack,
            "acknowledged_at":ack_at,
            "halted_at":halted_at,
            "recovered_at":None,
            "allow_new_shadow_entries":False,
            "effective_reason":"RAW_HALT",
        }

    if prev_state=="HALT" and incident_id:
        if raw_state=="RUN":
            healthy+=1
        else:
            healthy=0
        ack_ok=(not p.require_ack) or bool(ack_at) or acknowledged
        if acknowledged and not ack_at:
            ack_at=now.isoformat()
        streak_ok=healthy>=max(1,p.healthy_streak_required)
        if ack_ok and streak_ok and raw_state=="RUN":
            return {
                "state":"RUN","raw_state":raw_state,"incident_id":incident_id,
                "recovery_state":"RECOVERED","healthy_streak":healthy,
                "healthy_streak_required":p.healthy_streak_required,
                "ack_required":p.require_ack,"acknowledged_at":ack_at,
                "halted_at":halted_at,"recovered_at":now.isoformat(),
                "allow_new_shadow_entries":True,
                "effective_reason":"RECOVERY_CRITERIA_MET",
            }
        recovery_state="VERIFYING"
        if raw_state!="RUN":
            recovery_state="WAITING_FOR_HEALTH"
        elif p.require_ack and not ack_ok:
            recovery_state="ACK_REQUIRED" if streak_ok else "VERIFYING"
        return {
            "state":"HALT","raw_state":raw_state,"incident_id":incident_id,
            "recovery_state":recovery_state,"healthy_streak":healthy,
            "healthy_streak_required":p.healthy_streak_required,
            "ack_required":p.require_ack,"acknowledged_at":ack_at,
            "halted_at":halted_at,"recovered_at":None,
            "allow_new_shadow_entries":False,
            "effective_reason":"RECOVERY_LATCH",
        }

    return {
        "state":raw_state,"raw_state":raw_state,"incident_id":None,
        "recovery_state":"NORMAL","healthy_streak":0,
        "healthy_streak_required":p.healthy_streak_required,
        "ack_required":p.require_ack,"acknowledged_at":None,
        "halted_at":None,"recovered_at":None,
        "allow_new_shadow_entries":bool(raw_kill.get("allow_new_shadow_entries",raw_state!="HALT")),
        "effective_reason":"RAW_STATE",
    }


@dataclass(frozen=True)
class ChaosScenario:
    scenario_id: str
    description: str
    patch: dict[str,Any]
    expected_state: str
    expected_trigger: str | None=None


def _deepcopy_dict(value: dict[str,Any]) -> dict[str,Any]:
    import copy
    return copy.deepcopy(value)


def apply_patch(base: dict[str,Any], patch: dict[str,Any]) -> dict[str,Any]:
    out=_deepcopy_dict(base)
    for key,value in patch.items():
        if isinstance(value,dict) and isinstance(out.get(key),dict):
            out[key]=apply_patch(out[key],value)
        else:
            out[key]=value
    return out


def default_chaos_scenarios() -> list[ChaosScenario]:
    return [
        ChaosScenario("C01_DAILY_LOSS","daily loss beyond hard limit",
                      {"daily_shadow_return_pct":-2.5},"HALT","DAILY_LOSS_LIMIT"),
        ChaosScenario("C02_KIWOOM_STALE","critical Kiwoom feed stale",
                      {"critical_feeds":{"kiwoom":{"status":"OK","age_sec":999}}},"HALT","CRITICAL_FEED_STALE"),
        ChaosScenario("C03_REGIME_DOWN","regime engine error",
                      {"critical_feeds":{"regime":{"status":"ERROR","age_sec":5}}},"HALT","CRITICAL_FEED_ERROR"),
        ChaosScenario("C04_RISK_BREACH","portfolio risk exceeds hard utilization",
                      {"risk_utilization_pct":110},"HALT","PORTFOLIO_RISK_BREACH"),
        ChaosScenario("C05_IS_SPIKE","execution implementation shortfall spike",
                      {"median_round_trip_is_bps":75},"HALT","EXECUTION_IS_DEGRADED"),
        ChaosScenario("C06_REJECT_SPIKE","execution rejection spike",
                      {"execution_reject_pct":65},"HALT","EXECUTION_REJECT_SPIKE"),
        ChaosScenario("C07_CORR_SPIKE","portfolio correlation spike",
                      {"max_portfolio_corr":0.96},"HALT","PORTFOLIO_CORRELATION_SPIKE"),
        ChaosScenario("C08_BOOK_OUTAGE","order book stale while other feeds healthy",
                      {"orderbook_feed":{"status":"OK","age_sec":600}},"DEGRADED","ORDERBOOK_STALE"),
        ChaosScenario("C09_BOOK_COVERAGE","low BOOK_V2 coverage",
                      {"book_coverage_pct":25},"DEGRADED","BOOK_COVERAGE_LOW"),
        ChaosScenario("C10_UNKNOWN_CORR","too many unknown correlation pairs",
                      {"unknown_corr_pairs":8},"DEGRADED","CORRELATION_EVIDENCE_GAP"),
        ChaosScenario("C11_MANUAL_HALT","manual operator halt",
                      {"manual_halt":True},"HALT","MANUAL_HALT"),
    ]


def run_chaos_suite(
    baseline_metrics: dict[str,Any],
    evaluator: Callable[[dict[str,Any]],dict[str,Any]],
    scenarios: list[ChaosScenario] | None=None,
) -> dict[str,Any]:
    rows=[]
    for sc in scenarios or default_chaos_scenarios():
        metrics=apply_patch(baseline_metrics,sc.patch)
        result=evaluator(metrics)
        codes=[x.get("code") for x in (result.get("hard_triggers") or [])+(result.get("warnings") or [])]
        state_ok=str(result.get("state"))==sc.expected_state
        trigger_ok=sc.expected_trigger is None or sc.expected_trigger in codes
        rows.append({
            "scenario_id":sc.scenario_id,"description":sc.description,
            "expected_state":sc.expected_state,"actual_state":result.get("state"),
            "expected_trigger":sc.expected_trigger,"actual_codes":codes,
            "pass":bool(state_ok and trigger_ok),
        })
    passed=sum(1 for x in rows if x["pass"])
    return {
        "status":"PASS" if passed==len(rows) else "FAIL",
        "scenario_count":len(rows),"passed":passed,"failed":len(rows)-passed,
        "scenarios":rows,
    }


def replay_recovery_sequence(
    raw_states: list[dict[str,Any]],
    acknowledgements: set[int] | None=None,
    policy: RecoveryPolicy | None=None,
) -> list[dict[str,Any]]:
    acknowledgements=acknowledgements or set()
    prev=None
    out=[]
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    from datetime import timedelta
    for i,raw in enumerate(raw_states):
        prev=next_recovery_state(
            prev,raw,acknowledged=i in acknowledgements,policy=policy,
            now=start+timedelta(minutes=i)
        )
        out.append(dict(prev))
    return out


def audit_incident_timeline(rows: list[dict[str,Any]], policy: RecoveryPolicy | None=None) -> dict[str,Any]:
    """Audit persisted snapshots for unsafe HALT->RUN transitions.

    rows must be time ordered and contain effective state, raw_state,
    healthy_streak, acknowledged_at and incident_id when available.
    """
    p=policy or RecoveryPolicy()
    violations=[]
    incidents=set()
    previous=None
    for i,row in enumerate(rows):
        state=str(row.get("state") or "").upper()
        raw=str(row.get("raw_state") or state).upper()
        incident=row.get("incident_id")
        if incident:incidents.add(str(incident))
        if previous and str(previous.get("state") or "").upper()=="HALT" and state=="RUN":
            streak=int(row.get("healthy_streak") or 0)
            ack_ok=(not p.require_ack) or bool(row.get("acknowledged_at"))
            if raw!="RUN" or streak<p.healthy_streak_required or not ack_ok:
                violations.append({
                    "index":i,"code":"UNSAFE_RECOVERY_TRANSITION",
                    "incident_id":incident,"raw_state":raw,
                    "healthy_streak":streak,"ack_ok":ack_ok,
                })
        previous=row
    return {
        "status":"PASS" if not violations else "FAIL",
        "rows":len(rows),"incidents":len(incidents),
        "violations":violations,
    }
