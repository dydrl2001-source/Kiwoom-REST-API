"""Market OS Execution Firewall v2.3.

Transforms a HEALTHY active CONTROL observation into a short-lived human review
intent. This module deliberately contains no broker adapter, no order endpoint,
no quantity calculation and no position mutation.
"""
from __future__ import annotations

from datetime import datetime,timezone
import hashlib
import json

POLICY_VERSION="execution-firewall-v1"
ALLOWED_TIER="FOCUS"
ALLOWED_TRIGGER="STRUCTURE_CONFIRMED"
ALLOWED_CATALYST={"A","B"}
BLOCKED_STANCES={"DEFENSIVE","UNKNOWN"}
HARD_RISK_MARKERS=(
    "돌파 실패","추세 훼손","거래속도 과열 확인",
    "당일 급등 20%+","시장 레짐 방어적","시장 레짐 확인 필요",
    "재료 종합 미완료",
)


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)


def intent_id(control_hash,stock_code,snapshot_time):
    raw=f"{POLICY_VERSION}|{control_hash}|{stock_code}|{snapshot_time}".encode("utf-8")
    return "oi-"+hashlib.sha256(raw).hexdigest()[:24]


def hard_risks(risk_flags):
    flags=list(risk_flags or [])
    return [x for x in flags if any(marker in str(x) for marker in HARD_RISK_MARKERS)]


def evaluate(candidate,control,switch_state,sample_age_sec):
    """Return a deterministic allow/block decision for human review only."""
    c=dict(candidate or {});ctrl=dict(control or {})
    reasons=[]
    if ctrl.get("mode")!="RULESET":
        reasons.append("CONTROL_NOT_RULESET")
    if switch_state!="HEALTHY":
        reasons.append("CONTROL_SWITCH_NOT_HEALTHY")
    if ctrl.get("apply_status")!="APPLIED":
        reasons.append("CONTROL_RUNTIME_NOT_APPLIED")
    if not ctrl.get("control_hash") or not ctrl.get("switch_transaction_id"):
        reasons.append("CONTROL_IDENTITY_INCOMPLETE")
    if c.get("watch_tier")!=ALLOWED_TIER:
        reasons.append("NOT_FOCUS")
    if c.get("trigger_state")!=ALLOWED_TRIGGER:
        reasons.append("TRIGGER_NOT_CONFIRMED")
    if c.get("catalyst_grade") not in ALLOWED_CATALYST:
        reasons.append("CATALYST_NOT_VERIFIED")
    if c.get("market_stance") in BLOCKED_STANCES:
        reasons.append("MARKET_STANCE_BLOCKED")
    risks=hard_risks(c.get("risk_flags"))
    if risks:
        reasons.append("HARD_RISK_FLAG")
    try:
        age=float(sample_age_sec)
    except (TypeError,ValueError):
        age=None
    if age is None or age<0 or age>90:
        reasons.append("STALE_SAMPLE")

    return {
        "status":"REVIEW_ELIGIBLE" if not reasons else "FIREWALL_BLOCKED",
        "eligible":not reasons,
        "reason_codes":reasons,
        "hard_risks":risks,
        "policy_version":POLICY_VERSION,
    }


def snapshot(candidate,control,reference_price,snapshot_time,expires_at):
    """Freeze the evidence presented to the human reviewer."""
    c=dict(candidate or {});ctrl=dict(control or {})
    evidence={
        "policy_version":POLICY_VERSION,
        "intent_kind":"LONG_ENTRY_REVIEW",
        "stock_code":c.get("code"),
        "stock_name":c.get("name"),
        "snapshot_time":str(snapshot_time),
        "expires_at":str(expires_at),
        "reference_price_krw":reference_price,
        "control":{
            "control_id":ctrl.get("control_id"),
            "control_hash":ctrl.get("control_hash"),
            "active_version_label":ctrl.get("active_version_label"),
            "switch_transaction_id":ctrl.get("switch_transaction_id"),
        },
        "decision":{
            "watch_tier":c.get("watch_tier"),
            "base_watch_tier":c.get("base_watch_tier"),
            "control_overlay_applied":bool(c.get("control_overlay_applied")),
            "trigger_state":c.get("trigger_state"),
            "market_stance":c.get("market_stance"),
            "catalyst_grade":c.get("catalyst_grade"),
            "setup_score":c.get("setup_score"),
            "radar_score":c.get("radar_score"),
            "theme_score":c.get("theme_score"),
            "risk_flags":list(c.get("risk_flags") or []),
        },
        "execution":{
            "broker_order_created":False,
            "quantity":None,
            "limit_price":None,
            "market_order":False,
            "position_change":False,
            "next_allowed_step":"HUMAN_INTENT_REVIEW",
        },
    }
    evidence_hash=hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
    return {"evidence":evidence,"evidence_hash":evidence_hash}


def approval_still_valid(intent,current_control,switch_state,now=None):
    now=now or datetime.now(timezone.utc)
    reasons=[]
    expires=intent.get("expires_at")
    if expires is not None and now>=expires:
        reasons.append("INTENT_EXPIRED")
    if intent.get("control_hash")!=current_control.get("control_hash"):
        reasons.append("CONTROL_HASH_CHANGED")
    if intent.get("switch_transaction_id")!=current_control.get("switch_transaction_id"):
        reasons.append("CONTROL_TRANSACTION_CHANGED")
    if switch_state!="HEALTHY":
        reasons.append("CONTROL_NOT_HEALTHY")
    return {"valid":not reasons,"reason_codes":reasons}
