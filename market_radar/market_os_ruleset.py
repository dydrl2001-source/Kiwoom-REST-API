"""Pure versioned-ruleset helpers for Market OS dry runs.

A ruleset is an immutable candidate specification built from an approved
Adoption Review Dossier. Evaluating it never mutates the live Market OS output.
"""
from __future__ import annotations

import hashlib
import json

from market_os_shadow import matches, shift_tier, experiment_summaries, experiment_slices

SPEC_VERSION="versioned-ruleset-v1"


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)


def spec_hash(spec):
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def build_spec(dossier_id,dossier_hash,dossier):
    """Create a one-overlay immutable candidate ruleset from a reviewed dossier."""
    doc=dict(dossier or {})
    shadow=doc.get("shadow_rule") or {}
    proposed=doc.get("proposed_change") or {}
    condition=proposed.get("condition") or {}
    action=proposed.get("action")
    if not dossier_id or not dossier_hash:
        raise ValueError("DOSSIER_IDENTITY_REQUIRED")
    if not shadow.get("rule_version"):
        raise ValueError("BASE_RULE_VERSION_REQUIRED")
    if not condition.get("segment_type") or condition.get("segment_value") is None:
        raise ValueError("CONDITION_REQUIRED")
    if action not in {"PROMOTE_ONE_TIER","SUPPRESS_ONE_TIER"}:
        raise ValueError("INVALID_RULESET_ACTION")
    if proposed.get("blocked_override") not in (False,None):
        raise ValueError("BLOCKED_OVERRIDE_FORBIDDEN")

    spec={
        "spec_version":SPEC_VERSION,
        "base_rule_version":shadow.get("rule_version"),
        "source_dossier_id":dossier_id,
        "source_dossier_hash":dossier_hash,
        "source_shadow_rule_id":shadow.get("shadow_rule_id"),
        "prospective_only":True,
        "live_activation":False,
        "max_tier_shift":1,
        "blocked_override":False,
        "overlays":[{
            "overlay_id":"overlay-001",
            "segment_type":condition.get("segment_type"),
            "segment_value":condition.get("segment_value"),
            "action":action,
            "source":"ADOPTION_DOSSIER",
        }],
    }
    h=spec_hash(spec)
    return {
        "ruleset_id":"rs-"+h[:24],
        "version_label":f"{shadow.get('rule_version')}+dry-{h[:10]}",
        "content_hash":h,
        "spec":spec,
    }


def evaluate(snapshot,spec):
    """Evaluate candidate ruleset beside the frozen control assessment."""
    spec=dict(spec or {})
    control=snapshot.get("watch_tier") or "UNKNOWN"
    candidate=control
    matched=[]
    if spec.get("live_activation") not in (False,None):
        raise ValueError("LIVE_ACTIVATION_FORBIDDEN")
    if spec.get("blocked_override") not in (False,None):
        raise ValueError("BLOCKED_OVERRIDE_FORBIDDEN")

    overlays=list(spec.get("overlays") or [])
    if len(overlays)>1:
        raise ValueError("RULESET_V1_SUPPORTS_ONE_OVERLAY")
    for overlay in overlays:
        if matches(snapshot,overlay.get("segment_type"),overlay.get("segment_value")):
            matched.append(overlay.get("overlay_id"))
            candidate=shift_tier(candidate,overlay.get("action"))
    return {
        "control_tier":control,
        "candidate_tier":candidate,
        "changed":candidate!=control,
        "matched_overlays":matched,
    }


def dry_run_summaries(anchor_rows):
    """Reuse the same cohort comparison semantics as Shadow Rule Lab."""
    rows=[]
    for r in anchor_rows:
        x=dict(r)
        x["challenger_tier"]=x.get("candidate_tier")
        rows.append(x)
    return experiment_summaries(rows)

def dry_run_slices(anchor_rows):
    """Reuse pre-registered time/stance slices with candidate tier semantics."""
    rows=[]
    for r in anchor_rows:
        x=dict(r)
        x["challenger_tier"]=x.get("candidate_tier")
        rows.append(x)
    return experiment_slices(rows)


def _cohort_pred(cohort,tier):
    if cohort=="FOCUS":
        return tier=="FOCUS"
    if cohort=="REVIEW":
        return tier in {"FOCUS","PREP"}
    return False


def impact_concentration(anchor_rows,cohort):
    """Measure whether dry-run impact is dominated by one stock or one day.

    Concentration uses 30m episode anchors only to avoid double-counting the
    same stock-day through close/D+1 horizons.
    """
    changed=[]
    for r in anchor_rows:
        if r.get("horizon")!="30m":
            continue
        before=_cohort_pred(cohort,r.get("control_tier"))
        after=_cohort_pred(cohort,r.get("candidate_tier"))
        if before!=after:
            changed.append(r)
    total=len(changed)
    if not total:
        return {
            "changed_episodes":0,"distinct_stocks":0,"distinct_days":0,
            "top_stock_share":None,"top_day_share":None,
            "stock_hhi":None,"day_hhi":None,
        }
    stock_counts={}
    day_counts={}
    for r in changed:
        stock=r.get("stock_code") or "UNKNOWN"
        day=r.get("trade_day") or "UNKNOWN"
        stock_counts[stock]=stock_counts.get(stock,0)+1
        day_counts[day]=day_counts.get(day,0)+1
    stock_shares=[n/total for n in stock_counts.values()]
    day_shares=[n/total for n in day_counts.values()]
    return {
        "changed_episodes":total,
        "distinct_stocks":len(stock_counts),
        "distinct_days":len(day_counts),
        "top_stock_share":max(stock_shares),
        "top_day_share":max(day_shares),
        "stock_hhi":sum(x*x for x in stock_shares),
        "day_hhi":sum(x*x for x in day_shares),
    }


def _ready(cell,strong=False):
    if not cell:
        return False
    control=cell.get("control") or {}
    candidate=cell.get("challenger") or cell.get("candidate") or {}
    if strong:
        min_n,min_days,min_stocks,min_changes=60,8,10,12
    else:
        min_n,min_days,min_stocks,min_changes=30,4,6,6
    return (
        int(cell.get("membership_changes") or 0)>=min_changes
        and min(int(control.get("samples") or 0),int(candidate.get("samples") or 0))>=min_n
        and min(int(control.get("distinct_days") or 0),int(candidate.get("distinct_days") or 0))>=min_days
        and min(int(control.get("distinct_stocks") or 0),int(candidate.get("distinct_stocks") or 0))>=min_stocks
    )


def _effect(cell,strong=False):
    if not _ready(cell,strong=strong):
        return "INSUFFICIENT"
    d_avg=cell.get("delta_avg_return_pct")
    d_pos=cell.get("delta_positive_rate_pp")
    d_mae=cell.get("delta_mae_pct")
    if d_avg is None or d_pos is None or d_mae is None:
        return "INCOMPLETE"
    avg_cut=.20 if strong else .10
    pos_cut=3.0 if strong else 1.0
    if d_avg>=avg_cut and d_pos>=pos_cut and d_mae>=0:
        return "BENEFICIAL"
    if d_avg<=-avg_cut and d_pos<=-pos_cut and d_mae<=0:
        return "HARMFUL"
    return "MIXED"


def _retention(current,reference):
    cur=current.get("delta_avg_return_pct") if current else None
    ref=reference.get("delta_avg_return_pct") if reference else None
    if cur is None or ref is None or ref<=0:
        return None
    return cur/ref


def succession_decision(ruleset,overall_summaries,slices,concentration_by_cohort,
                        shadow_reference):
    """Gate a versioned dry run before any release-candidate discussion.

    SUCCESSION_CANDIDATE grants human release-review eligibility only. It never
    activates the candidate ruleset or changes the live CONTROL.
    """
    overall={(x.get("horizon"),x.get("cohort")):x for x in (overall_summaries or [])}
    scoped={(x.get("scope_type"),x.get("scope_value"),x.get("horizon"),x.get("cohort")):x
            for x in (slices or [])}
    shadow={(x.get("horizon"),x.get("cohort")):x for x in (shadow_reference or [])}

    changes={
        cohort:sum(int((overall.get((h,cohort)) or {}).get("membership_changes") or 0)
                   for h in ("30m","close"))
        for cohort in ("REVIEW","FOCUS")
    }
    primary="REVIEW" if changes["REVIEW"]>=changes["FOCUS"] else "FOCUS"
    c30=overall.get(("30m",primary))
    cclose=overall.get(("close",primary))
    cd1=overall.get(("D+1",primary))
    e30=_effect(c30);eclose=_effect(cclose);ed1=_effect(cd1)
    s30=_effect(c30,strong=True);sclose=_effect(cclose,strong=True)

    evidence={
        "primary_cohort":primary,
        "overall_30m":e30,"overall_close":eclose,"overall_d1":ed1,
        "overall_30m_strong":s30,"overall_close_strong":sclose,
        "membership_changes_30m":int((c30 or {}).get("membership_changes") or 0),
        "membership_changes_close":int((cclose or {}).get("membership_changes") or 0),
    }

    if e30=="INSUFFICIENT":
        return {"state":"RULESET_COLLECTING","review_eligible":False,
                "reason_codes":["30M_NOT_COMPARABLE"],"evidence":evidence}
    if eclose=="INSUFFICIENT":
        return {"state":"RULESET_COMPARABLE","review_eligible":False,
                "reason_codes":["30M_COMPARABLE","CLOSE_NOT_COMPARABLE"],"evidence":evidence}
    if e30=="HARMFUL" and eclose=="HARMFUL":
        return {"state":"RULESET_REJECT","review_eligible":False,
                "reason_codes":["30M_AND_CLOSE_HARMFUL"],"evidence":evidence}
    if ed1=="HARMFUL":
        return {"state":"RULESET_REJECT","review_eligible":False,
                "reason_codes":["D1_HARMFUL"],"evidence":evidence}
    if e30!="BENEFICIAL" or eclose!="BENEFICIAL":
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["OVERALL_EFFECT_NOT_ALIGNED"],"evidence":evidence}

    temporal={}
    for name in ("EARLY","RECENT"):
        temporal[name.lower()]={
            "30m":_effect(scoped.get(("WINDOW",name,"30m",primary))),
            "close":_effect(scoped.get(("WINDOW",name,"close",primary))),
        }
    evidence["temporal"]=temporal
    if temporal["recent"]["30m"]=="HARMFUL" or temporal["recent"]["close"]=="HARMFUL":
        return {"state":"RULESET_REJECT","review_eligible":False,
                "reason_codes":["RECENT_HALF_HARMFUL"],"evidence":evidence}
    if any(temporal[w][h]!="BENEFICIAL" for w in ("early","recent") for h in ("30m","close")):
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["TIME_SPLIT_NOT_STABLE"],"evidence":evidence}

    conc=(concentration_by_cohort or {}).get(primary) or {}
    evidence["concentration"]=conc
    if (int(conc.get("changed_episodes") or 0)<12
            or int(conc.get("distinct_stocks") or 0)<8
            or int(conc.get("distinct_days") or 0)<6):
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["IMPACT_DIVERSITY_LOW"],"evidence":evidence}
    if ((conc.get("top_stock_share") is not None and conc["top_stock_share"]>0.35)
            or (conc.get("top_day_share") is not None and conc["top_day_share"]>0.45)):
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["IMPACT_CONCENTRATION_HIGH"],"evidence":evidence}

    overlays=list((ruleset.get("spec") or ruleset or {}).get("overlays") or [])
    segment_type=(overlays[0].get("segment_type") if overlays else "") or ""
    segment_value=(overlays[0].get("segment_value") if overlays else "") or ""
    stance_scoped="STANCE" in segment_type
    stance_rows=[]
    for stance in ("EXPANDABLE","SELECTIVE","DEFENSIVE"):
        cell=scoped.get(("STANCE",stance,"30m",primary))
        if cell and int(cell.get("membership_changes") or 0)>0:
            stance_rows.append({
                "stance":stance,"state":_effect(cell),
                "membership_changes":int(cell.get("membership_changes") or 0),
            })
    evidence["stance"]=stance_rows
    evidence["stance_scoped"]=stance_scoped
    if stance_scoped:
        target=segment_value.split(" | ")[0]
        target_row=next((x for x in stance_rows if x["stance"]==target),None)
        if not target_row or target_row["state"]!="BENEFICIAL":
            return {"state":"RULESET_MORE_DATA","review_eligible":False,
                    "reason_codes":["TARGET_STANCE_NOT_REPRODUCED"],"evidence":evidence}
    else:
        comparable=[x for x in stance_rows if x["state"]!="INSUFFICIENT"]
        if any(x["state"]=="HARMFUL" for x in comparable):
            return {"state":"RULESET_MORE_DATA","review_eligible":False,
                    "reason_codes":["STANCE_CONTRADICTION"],"evidence":evidence}
        if sum(x["state"]=="BENEFICIAL" for x in comparable)<2:
            return {"state":"RULESET_MORE_DATA","review_eligible":False,
                    "reason_codes":["MULTI_STANCE_REPLICATION_PENDING"],"evidence":evidence}

    retention={}
    for h in ("30m","close"):
        cur=overall.get((h,primary));ref=shadow.get((h,primary))
        retention[h]=_retention(cur,ref)
    evidence["shadow_effect_retention"]=retention
    if retention["30m"] is None or retention["close"] is None:
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["SHADOW_REFERENCE_MISSING"],"evidence":evidence}
    if retention["30m"]<0.40 or retention["close"]<0.40:
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["SHADOW_EFFECT_COLLAPSED"],"evidence":evidence}
    if retention["30m"]>3.0 or retention["close"]>3.0:
        return {"state":"RULESET_MORE_DATA","review_eligible":False,
                "reason_codes":["SHADOW_EFFECT_SIZE_DIVERGED"],"evidence":evidence}

    stable={
        "state":"RULESET_STABLE","review_eligible":False,
        "reason_codes":[
            "30M_CLOSE_BENEFICIAL","TIME_SPLIT_STABLE","IMPACT_DIVERSE",
            "STANCE_REPRODUCED","SHADOW_EFFECT_RETAINED",
        ],
        "evidence":evidence,
    }
    if s30!="BENEFICIAL" or sclose!="BENEFICIAL":
        return stable

    recent30=scoped.get(("WINDOW","RECENT","30m",primary))
    recent_close=scoped.get(("WINDOW","RECENT","close",primary))
    if _effect(recent30,strong=True)!="BENEFICIAL" or _effect(recent_close,strong=True)!="BENEFICIAL":
        return stable

    return {
        "state":"SUCCESSION_CANDIDATE","review_eligible":True,
        "reason_codes":stable["reason_codes"]+[
            "STRONG_SAMPLE_GATE_PASSED","RECENT_STRONG_EFFECT",
            "D1_NOT_HARMFUL",
        ],
        "evidence":evidence,
    }

