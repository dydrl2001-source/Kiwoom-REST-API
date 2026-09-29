"""Release Candidate and deterministic Canary helpers for Market OS.

This module never changes the live CONTROL ruleset. Canary assignment is stable
per stock-day and independent of observed performance or tier.
"""
from __future__ import annotations

import hashlib
import json

from market_os_ruleset import canonical_json, dry_run_summaries, dry_run_slices

RELEASE_SPEC_VERSION="release-candidate-v1"
DEFAULT_CANARY_PCT=20


def package_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_release_candidate(ruleset, succession_event_id, succession_decision,
                            canary_pct=DEFAULT_CANARY_PCT):
    ruleset=dict(ruleset or {})
    decision=dict(succession_decision or {})
    pct=int(canary_pct)
    if not 1<=pct<=25:
        raise ValueError("CANARY_PCT_OUT_OF_RANGE")
    if decision.get("decision_state")!="SUCCESSION_CANDIDATE" or not decision.get("review_eligible"):
        raise ValueError("SUCCESSION_CANDIDATE_REQUIRED")
    if not succession_event_id:
        raise ValueError("SUCCESSION_EVENT_REQUIRED")
    if not ruleset.get("ruleset_id") or not ruleset.get("spec_hash") or not ruleset.get("spec"):
        raise ValueError("RULESET_IDENTITY_REQUIRED")

    package={
        "release_spec_version":RELEASE_SPEC_VERSION,
        "source_ruleset_id":ruleset["ruleset_id"],
        "source_ruleset_hash":ruleset["spec_hash"],
        "source_version_label":ruleset.get("version_label"),
        "source_succession_event_id":int(succession_event_id),
        "source_succession_state":"SUCCESSION_CANDIDATE",
        "canary":{
            "allocation_pct":pct,
            "assignment_unit":"STOCK_KST_DAY",
            "selection":"SHA256_RELEASE_STOCK_DAY",
            "primary_view_replacement":False,
        },
        "safety":{
            "live_activation":False,
            "order_execution":False,
            "position_sizing":False,
            "blocked_override":False,
            "auto_full_promotion":False,
        },
        "candidate_ruleset_spec":ruleset["spec"],
    }
    h=package_hash(package)
    return {
        "release_candidate_id":"rc-"+h[:24],
        "release_version_label":f"{ruleset.get('version_label') or ruleset['ruleset_id']}+rc-{h[:8]}",
        "package_hash":h,
        "package":package,
    }


def canary_bucket(release_candidate_id,stock_code,trade_day):
    raw=f"{release_candidate_id}|{stock_code}|{trade_day}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8],16)%10000


def is_canary_selected(release_candidate_id,stock_code,trade_day,allocation_pct):
    pct=int(allocation_pct)
    if not release_candidate_id or not stock_code or not trade_day:
        return False
    if not 1<=pct<=25:
        raise ValueError("CANARY_PCT_OUT_OF_RANGE")
    return canary_bucket(release_candidate_id,stock_code,trade_day)<pct*100


def canary_summaries(anchor_rows):
    return dry_run_summaries(anchor_rows)


def canary_slices(anchor_rows):
    return dry_run_slices(anchor_rows)


def _ready(cell,strong=False):
    if not cell:
        return False
    control=cell.get("control") or {}
    candidate=cell.get("challenger") or {}
    if strong:
        min_n,min_days,min_stocks,min_changes=25,4,6,6
    else:
        min_n,min_days,min_stocks,min_changes=12,2,4,3
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


def canary_decision(overall_summaries,slices):
    """Safety-first canary gate.

    CANARY_PROMOTION_CANDIDATE grants human review eligibility only. A harmful
    comparable canary returns CANARY_ROLLBACK_REQUIRED so the worker can stop
    further preview observations while preserving all evidence.
    """
    overall={(x.get("horizon"),x.get("cohort")):x for x in (overall_summaries or [])}
    scoped={(x.get("scope_type"),x.get("scope_value"),x.get("horizon"),x.get("cohort")):x
            for x in (slices or [])}
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
    evidence={
        "primary_cohort":primary,
        "overall_30m":e30,"overall_close":eclose,"overall_d1":ed1,
        "membership_changes_30m":int((c30 or {}).get("membership_changes") or 0),
        "membership_changes_close":int((cclose or {}).get("membership_changes") or 0),
    }

    if e30=="INSUFFICIENT":
        return {"state":"CANARY_COLLECTING","review_eligible":False,
                "reason_codes":["30M_NOT_COMPARABLE"],"evidence":evidence}
    if e30=="HARMFUL":
        return {"state":"CANARY_ROLLBACK_REQUIRED","review_eligible":False,
                "reason_codes":["30M_HARMFUL"],"evidence":evidence}
    if eclose=="HARMFUL" or ed1=="HARMFUL":
        return {"state":"CANARY_ROLLBACK_REQUIRED","review_eligible":False,
                "reason_codes":["CLOSE_OR_D1_HARMFUL"],"evidence":evidence}

    recent30=scoped.get(("WINDOW","RECENT","30m",primary))
    recent_close=scoped.get(("WINDOW","RECENT","close",primary))
    r30=_effect(recent30);rclose=_effect(recent_close)
    evidence["recent_30m"]=r30
    evidence["recent_close"]=rclose
    if r30=="HARMFUL" or rclose=="HARMFUL":
        return {"state":"CANARY_ROLLBACK_REQUIRED","review_eligible":False,
                "reason_codes":["RECENT_HALF_HARMFUL"],"evidence":evidence}

    if e30!="BENEFICIAL":
        return {"state":"CANARY_HEALTHY","review_eligible":False,
                "reason_codes":["NO_HARM_DETECTED","30M_NOT_YET_BENEFICIAL"],"evidence":evidence}
    if eclose=="INSUFFICIENT":
        return {"state":"CANARY_HEALTHY","review_eligible":False,
                "reason_codes":["30M_BENEFICIAL","CLOSE_COLLECTING"],"evidence":evidence}
    if eclose!="BENEFICIAL":
        return {"state":"CANARY_HEALTHY","review_eligible":False,
                "reason_codes":["NO_HARM_DETECTED","CLOSE_MIXED"],"evidence":evidence}

    strong30=_effect(c30,strong=True)
    strongclose=_effect(cclose,strong=True)
    evidence["overall_30m_strong"]=strong30
    evidence["overall_close_strong"]=strongclose
    if r30!="BENEFICIAL" or rclose!="BENEFICIAL":
        return {
            "state":"CANARY_HEALTHY","review_eligible":False,
            "reason_codes":["30M_CLOSE_BENEFICIAL","RECENT_CANARY_EVIDENCE_PENDING"],
            "evidence":evidence,
        }
    if strong30=="BENEFICIAL" and strongclose=="BENEFICIAL":
        return {
            "state":"CANARY_PROMOTION_CANDIDATE","review_eligible":True,
            "reason_codes":[
                "30M_CLOSE_BENEFICIAL","RECENT_30M_CLOSE_BENEFICIAL",
                "STRONG_CANARY_GATE_PASSED","NO_D1_HARM"
            ],
            "evidence":evidence,
        }
    return {
        "state":"CANARY_HEALTHY","review_eligible":False,
        "reason_codes":["30M_CLOSE_BENEFICIAL","STRONG_CANARY_GATE_PENDING"],
        "evidence":evidence,
    }
