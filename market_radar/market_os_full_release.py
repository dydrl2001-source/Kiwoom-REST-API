"""Full Release Review Gate for Market OS v2.1.

Builds an immutable, human-reviewable release dossier after Canary promotion
eligibility. It never switches the live CONTROL ruleset.
"""
from __future__ import annotations

import hashlib
import json
import math

from market_os_ruleset import canonical_json

REVIEW_SCHEMA_VERSION="full-release-review-v1"


def _num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _index(rows):
    return {(x.get("horizon"),x.get("cohort")):dict(x) for x in (rows or [])}


def _ratio(num,den):
    a=_num(num);b=_num(den)
    if a is None or b is None or b<=0:
        return None
    return a/b


def _distribution(counts):
    counts=dict(counts or {})
    total=sum(int(v or 0) for v in counts.values())
    if total<=0:
        return {}
    return {str(k):int(v or 0)/total for k,v in counts.items() if int(v or 0)>0}


def total_variation(a,b):
    pa=_distribution(a);pb=_distribution(b)
    keys=set(pa)|set(pb)
    if not keys:
        return None
    return .5*sum(abs(pa.get(k,0)-pb.get(k,0)) for k in keys)


def sample_bias_gate(composition):
    c=dict(composition or {})
    eligible=int(c.get("eligible_stock_days") or 0)
    selected=int(c.get("selected_stock_days") or 0)
    expected=_num(c.get("expected_pct"))
    actual=(selected/eligible*100) if eligible else None
    stance_tvd=total_variation(c.get("stance_universe"),c.get("stance_canary"))
    tier_tvd=total_variation(c.get("tier_universe"),c.get("tier_canary"))
    evidence={
        "eligible_stock_days":eligible,
        "selected_stock_days":selected,
        "expected_pct":expected,
        "actual_pct":actual,
        "stance_tvd":stance_tvd,
        "tier_tvd":tier_tvd,
        "stance_universe":dict(c.get("stance_universe") or {}),
        "stance_canary":dict(c.get("stance_canary") or {}),
        "tier_universe":dict(c.get("tier_universe") or {}),
        "tier_canary":dict(c.get("tier_canary") or {}),
    }
    reasons=[]
    if eligible<20 or selected<6:
        reasons.append("CANARY_COMPOSITION_SAMPLE_LOW")
    if expected is None or actual is None or abs(actual-expected)>10:
        reasons.append("CANARY_ALLOCATION_DRIFT")
    if stance_tvd is None or stance_tvd>0.20:
        reasons.append("CANARY_STANCE_BIAS")
    if tier_tvd is None or tier_tvd>0.20:
        reasons.append("CANARY_TIER_BIAS")
    return {"ready":not reasons,"reason_codes":reasons,"evidence":evidence}


def effect_alignment_gate(canary_rows,dry_run_rows,primary_cohort):
    canary=_index(canary_rows);dry=_index(dry_run_rows)
    evidence={}
    reasons=[]
    for h in ("30m","close"):
        c=canary.get((h,primary_cohort)) or {}
        d=dry.get((h,primary_cohort)) or {}
        cavg=_num(c.get("delta_avg_return_pct"))
        davg=_num(d.get("delta_avg_return_pct"))
        cpos=_num(c.get("delta_positive_rate_pp"))
        dpos=_num(d.get("delta_positive_rate_pp"))
        cmae=_num(c.get("delta_mae_pct"))
        dmae=_num(d.get("delta_mae_pct"))
        ratio=_ratio(cavg,davg)
        evidence[h]={
            "canary_delta_avg_return_pct":cavg,
            "dry_run_delta_avg_return_pct":davg,
            "avg_effect_ratio":ratio,
            "canary_delta_positive_rate_pp":cpos,
            "dry_run_delta_positive_rate_pp":dpos,
            "positive_rate_gap_pp":abs(cpos-dpos) if cpos is not None and dpos is not None else None,
            "canary_delta_mae_pct":cmae,
            "dry_run_delta_mae_pct":dmae,
        }
        if cavg is None or davg is None or cavg<=0 or davg<=0:
            reasons.append(h.upper()+"_EFFECT_DIRECTION_MISMATCH")
            continue
        if ratio is None or ratio<0.50:
            reasons.append(h.upper()+"_CANARY_EFFECT_COLLAPSED")
        elif ratio>2.0:
            reasons.append(h.upper()+"_CANARY_EFFECT_DIVERGED")
        if cpos is None or dpos is None or abs(cpos-dpos)>8.0:
            reasons.append(h.upper()+"_POSITIVE_RATE_DIVERGED")
        if cmae is None or dmae is None or cmae<0 or dmae<0:
            reasons.append(h.upper()+"_MAE_NOT_ALIGNED")
    return {"ready":not reasons,"reason_codes":reasons,"evidence":evidence}


def rollback_readiness(release_candidate,ruleset,current_rule_version):
    rc=dict(release_candidate or {});rs=dict(ruleset or {})
    package=rc.get("package") or {}
    safety=package.get("safety") or {}
    candidate_spec=package.get("candidate_ruleset_spec") or {}
    base=candidate_spec.get("base_rule_version") or rs.get("base_rule_version")
    reasons=[]
    if not base or base!=current_rule_version:
        reasons.append("CONTROL_VERSION_MISMATCH")
    if rs.get("ruleset_id")!=rc.get("source_ruleset_id"):
        reasons.append("SOURCE_RULESET_MISMATCH")
    if rs.get("spec_hash")!=package.get("source_ruleset_hash"):
        reasons.append("SOURCE_RULESET_HASH_MISMATCH")
    forbidden={
        "live_activation":False,
        "order_execution":False,
        "position_sizing":False,
        "blocked_override":False,
        "auto_full_promotion":False,
    }
    for key,expected in forbidden.items():
        if safety.get(key)!=expected:
            reasons.append("UNSAFE_"+key.upper())
    if candidate_spec.get("live_activation") not in (False,None):
        reasons.append("CANDIDATE_SPEC_LIVE_ACTIVATION")
    if candidate_spec.get("blocked_override") not in (False,None):
        reasons.append("CANDIDATE_SPEC_BLOCKED_OVERRIDE")

    control_snapshot={
        "role":"CONTROL",
        "rule_version":current_rule_version,
        "expected_base_rule_version":base,
        "primary_market_os_source":"market_os_assessment_snapshots.watch_tier",
    }
    control_hash=hashlib.sha256(canonical_json(control_snapshot).encode("utf-8")).hexdigest()
    rollback_target={
        "target_id":"control-"+control_hash[:20],
        "control_snapshot_hash":control_hash,
        "rule_version":current_rule_version,
        "restore_primary_view":"CONTROL",
        "restore_order_execution":"UNCHANGED_CONTROL",
        "one_click_target_defined":True,
        "one_click_live_command_available":False,
    }
    return {
        "ready":not reasons,
        "reason_codes":reasons,
        "control_snapshot":control_snapshot,
        "rollback_target":rollback_target,
    }


def full_release_gate(release_candidate,canary_decision,canary_rows,dry_run_rows,
                      composition,ruleset,current_rule_version):
    rc=dict(release_candidate or {})
    cd=dict(canary_decision or {})
    reasons=[]
    if cd.get("decision_state")!="CANARY_PROMOTION_CANDIDATE" or not cd.get("review_eligible"):
        reasons.append("CANARY_PROMOTION_CANDIDATE_REQUIRED")
    if rc.get("status")!="CANARY_ACTIVE":
        reasons.append("CANARY_MUST_BE_ACTIVE_FOR_REVIEW")
    primary=cd.get("primary_cohort") or (cd.get("evidence") or {}).get("primary_cohort")
    if primary not in ("FOCUS","REVIEW"):
        reasons.append("PRIMARY_COHORT_MISSING")
        primary="REVIEW"

    alignment=effect_alignment_gate(canary_rows,dry_run_rows,primary)
    bias=sample_bias_gate(composition)
    rollback=rollback_readiness(rc,ruleset,current_rule_version)
    reasons+=alignment["reason_codes"]+bias["reason_codes"]+rollback["reason_codes"]
    return {
        "state":"FULL_RELEASE_REVIEW_READY" if not reasons else "FULL_RELEASE_MORE_DATA",
        "review_eligible":not reasons,
        "reason_codes":reasons,
        "evidence":{
            "primary_cohort":primary,
            "effect_alignment":alignment["evidence"],
            "sample_bias":bias["evidence"],
            "rollback":rollback,
        },
    }


def build_review_package(release_candidate,canary_decision_event_id,gate,
                         canary_rows,dry_run_rows,composition,ruleset,current_rule_version):
    rc=dict(release_candidate or {});rs=dict(ruleset or {})
    if not canary_decision_event_id:
        raise ValueError("CANARY_DECISION_EVENT_REQUIRED")
    package={
        "schema_version":REVIEW_SCHEMA_VERSION,
        "release_candidate":{
            "release_candidate_id":rc.get("release_candidate_id"),
            "release_version_label":rc.get("release_version_label"),
            "package_hash":rc.get("package_hash"),
            "source_ruleset_id":rc.get("source_ruleset_id"),
            "source_canary_decision_event_id":int(canary_decision_event_id),
        },
        "gate":gate,
        "deployment_manifest":{
            "candidate_ruleset_id":rs.get("ruleset_id"),
            "candidate_ruleset_hash":rs.get("spec_hash"),
            "candidate_version_label":rs.get("version_label"),
            "control_rule_version":current_rule_version,
            "deployment_mode":"NOT_AUTHORIZED",
            "primary_view_switch":False,
            "order_execution_change":False,
            "position_sizing_change":False,
            "next_allowed_step":"HUMAN_RELEASE_APPROVAL",
        },
        "rollback_manifest":(gate.get("evidence") or {}).get("rollback",{}).get("rollback_target"),
        "canary_summary":list(canary_rows or []),
        "dry_run_summary":list(dry_run_rows or []),
        "canary_composition":composition,
        "review_questions":[
            "Does Canary preserve the 30m and close effect seen in the full dry run?",
            "Is the deterministic Canary sample acceptably representative by stance and CONTROL tier?",
            "Is the CONTROL rollback identity unambiguous and still current?",
            "Are all safety flags still false for live/order/position mutation?",
            "Are there operational reasons to delay release despite statistical readiness?",
        ],
        "release_constraints":[
            "No live switch is implemented by v2.1.",
            "RELEASE_READY is human approval metadata, not deployment.",
            "Any later switch must preserve the frozen rollback target and candidate hash.",
            "Canary or source evidence invalidation makes a pending review stale.",
        ],
    }
    h=hashlib.sha256(canonical_json(package).encode("utf-8")).hexdigest()
    return {
        "review_id":"fr-"+h[:24],
        "content_hash":h,
        "package":package,
    }
