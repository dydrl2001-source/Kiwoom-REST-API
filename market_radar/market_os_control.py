"""Runtime CONTROL selector and reversible tier-overlay application.

The base Market OS engine remains immutable. A committed control selector may
apply one previously-reviewed ruleset overlay to the primary observation tier.
This module contains no database writes and no order execution.
"""
from __future__ import annotations

import hashlib
import json

BASE_MODE="BASE"
RULESET_MODE="RULESET"
TIER_ORDER=("FOCUS","PREP","DISCOVER")
ALLOWED_ACTIONS={"PROMOTE_ONE_TIER","SUPPRESS_ONE_TIER"}


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)


def control_hash(control):
    payload={k:v for k,v in dict(control or {}).items() if k!="control_hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def base_control(base_version):
    control={
        "control_id":"control-"+str(base_version),
        "mode":BASE_MODE,
        "active_version_label":str(base_version),
        "base_rule_version":str(base_version),
        "ruleset_id":None,
        "ruleset_hash":None,
        "ruleset_spec":None,
        "source_review_id":None,
        "switch_transaction_id":None,
    }
    return {**control,"control_hash":control_hash(control)}


def candidate_control(base_version,ruleset,review_id,switch_transaction_id):
    rs=dict(ruleset or {})
    spec=rs.get("spec") or {}
    if not rs.get("ruleset_id") or not rs.get("spec_hash") or not rs.get("version_label"):
        raise ValueError("RULESET_IDENTITY_REQUIRED")
    if spec.get("base_rule_version")!=base_version:
        raise ValueError("BASE_RULE_VERSION_MISMATCH")
    if spec.get("live_activation") not in (False,None):
        raise ValueError("UNSAFE_LIVE_ACTIVATION_FLAG")
    if spec.get("blocked_override") not in (False,None):
        raise ValueError("BLOCKED_OVERRIDE_FORBIDDEN")
    overlays=list(spec.get("overlays") or [])
    if len(overlays)!=1:
        raise ValueError("CONTROL_V1_REQUIRES_ONE_OVERLAY")
    overlay=overlays[0]
    if overlay.get("action") not in ALLOWED_ACTIONS:
        raise ValueError("INVALID_CONTROL_ACTION")
    control={
        "control_id":"control-"+rs["ruleset_id"],
        "mode":RULESET_MODE,
        "active_version_label":rs["version_label"],
        "base_rule_version":base_version,
        "ruleset_id":rs["ruleset_id"],
        "ruleset_hash":rs["spec_hash"],
        "ruleset_spec":spec,
        "source_review_id":review_id,
        "switch_transaction_id":switch_transaction_id,
    }
    return {**control,"control_hash":control_hash(control)}


def _bucket_setup(v):
    try:v=int(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=80:return "80-100"
    if v>=65:return "65-79"
    if v>=50:return "50-64"
    return "0-49"


def _bucket_strength(v):
    try:v=float(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=120:return "120+"
    if v>=100:return "100-119"
    if v>=80:return "80-99"
    return "<80"


def _bucket_buy_share(v):
    try:v=float(v)
    except (TypeError,ValueError):return "UNKNOWN"
    if v>=.65:return "65%+"
    if v>=.55:return "55-64%"
    if v>=.45:return "45-54%"
    return "<45%"


def _micro_state(strength,buy_share):
    try:s=float(strength)
    except (TypeError,ValueError):s=None
    try:b=float(buy_share)
    except (TypeError,ValueError):b=None
    if s is None or b is None:return "NO_DATA"
    if s>=120 and b>=.65:return "STRONG_CONFIRM"
    if s<80 and b<.45:return "WEAK_CONFIRM"
    if s>=100 and b>=.55:return "POSITIVE"
    if s<100 and b<.45:return "NEGATIVE"
    return "MIXED"


def dimensions(snapshot):
    tier=snapshot.get("base_watch_tier") or snapshot.get("watch_tier") or "UNKNOWN"
    stance=snapshot.get("market_stance") or "UNKNOWN"
    trigger=snapshot.get("trigger_state") or "UNKNOWN"
    session=snapshot.get("session_bucket") or "UNKNOWN"
    setup=_bucket_setup(snapshot.get("setup_score"))
    out={
        "TIER":tier,"STANCE":stance,"TRIGGER":trigger,"SESSION":session,
        "CATALYST":snapshot.get("catalyst_grade") or "UNKNOWN","SETUP":setup,
        "STANCE_TRIGGER":stance+" | "+trigger,
        "TIER_SESSION":tier+" | "+session,
        "STANCE_SETUP":stance+" | "+setup,
        "SETUP_TRIGGER":setup+" | "+trigger,
        "STANCE_SETUP_TRIGGER":stance+" | "+setup+" | "+trigger,
    }
    clean=(int(snapshot.get("micro_tick_count_15s") or 0)>0
           and int(snapshot.get("micro_gap_count_15s") or 0)==0)
    if clean:
        micro=_micro_state(snapshot.get("micro_strength"),snapshot.get("micro_buy_share_15s"))
        out.update({
            "MICRO_STRENGTH":_bucket_strength(snapshot.get("micro_strength")),
            "MICRO_BUY_SHARE":_bucket_buy_share(snapshot.get("micro_buy_share_15s")),
            "MICRO_STATE":micro,
            "STANCE_TRIGGER_MICRO":stance+" | "+trigger+" | "+micro,
            "SETUP_TRIGGER_MICRO":setup+" | "+trigger+" | "+micro,
            "STANCE_SETUP_TRIGGER_MICRO":stance+" | "+setup+" | "+trigger+" | "+micro,
        })
    return out


def _shift_tier(tier,action):
    if tier=="BLOCKED":return "BLOCKED"
    if tier not in TIER_ORDER:return tier
    i=TIER_ORDER.index(tier)
    if action=="PROMOTE_ONE_TIER":
        return TIER_ORDER[max(0,i-1)]
    if action=="SUPPRESS_ONE_TIER":
        return TIER_ORDER[min(len(TIER_ORDER)-1,i+1)]
    raise ValueError("INVALID_CONTROL_ACTION")


def requires_micro(spec):
    overlays=list((spec or {}).get("overlays") or [])
    return any("MICRO" in str(x.get("segment_type") or "") for x in overlays)


def apply_watchlist(base_watchlist,control,micro_by_code=None):
    """Apply active CONTROL to an already-computed base Market OS watchlist.

    Returns (watchlist, metadata). On BASE mode no tier changes occur.
    """
    control=dict(control or {})
    base=[dict(x) for x in (base_watchlist or [])]
    for x in base:
        x["base_watch_tier"]=x.get("watch_tier")
        x["control_overlay_applied"]=False
        x["version"]=control.get("active_version_label") or x.get("version")

    if control.get("mode",BASE_MODE)==BASE_MODE:
        return base,{
            "apply_status":"BASE",
            "control_id":control.get("control_id"),
            "active_version_label":control.get("active_version_label"),
            "control_hash":control.get("control_hash"),
            "switch_transaction_id":control.get("switch_transaction_id"),
            "changed_count":0,
        }

    spec=control.get("ruleset_spec") or {}
    if spec.get("live_activation") not in (False,None):
        raise ValueError("UNSAFE_LIVE_ACTIVATION_FLAG")
    if spec.get("blocked_override") not in (False,None):
        raise ValueError("BLOCKED_OVERRIDE_FORBIDDEN")
    overlays=list(spec.get("overlays") or [])
    if len(overlays)!=1:
        raise ValueError("CONTROL_V1_REQUIRES_ONE_OVERLAY")
    overlay=overlays[0]
    if overlay.get("action") not in ALLOWED_ACTIONS:
        raise ValueError("INVALID_CONTROL_ACTION")

    micro_by_code=micro_by_code or {}
    changed=0
    for x in base:
        m=micro_by_code.get(x.get("code")) or {}
        snap={**x,**m}
        dims=dimensions(snap)
        if dims.get(overlay.get("segment_type"))==overlay.get("segment_value"):
            before=x.get("watch_tier")
            after=_shift_tier(before,overlay.get("action"))
            x["watch_tier"]=after
            x["control_overlay_applied"]=after!=before
            x["control_overlay_id"]=overlay.get("overlay_id")
            if after!=before:changed+=1

    tier_order={"FOCUS":0,"PREP":1,"DISCOVER":2,"BLOCKED":3}
    trigger_order={"STRUCTURE_CONFIRMED":0,"BREAKOUT_TEST":1,"WAIT_PULLBACK":2,"NO_DATA":3,"BLOCKED":4}
    base.sort(key=lambda x:(
        tier_order.get(x.get("watch_tier"),9),
        trigger_order.get(x.get("trigger_state"),9),
        -(x.get("radar_score") or 0),-(x.get("theme_score") or 0),-(x.get("setup_score") or 0),
        x.get("trade_rank") if x.get("trade_rank") is not None else 999,
    ))
    return base,{
        "apply_status":"APPLIED",
        "control_id":control.get("control_id"),
        "active_version_label":control.get("active_version_label"),
        "control_hash":control.get("control_hash"),
        "ruleset_id":control.get("ruleset_id"),
        "switch_transaction_id":control.get("switch_transaction_id"),
        "changed_count":changed,
        "requires_micro":requires_micro(spec),
    }
