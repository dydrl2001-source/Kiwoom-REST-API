"""Deterministic Adoption Review Dossier builder for Market OS.

The dossier freezes review evidence for a shadow rule. It does not mutate live
rules, create a ruleset, or place orders.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math


def _num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _compact_summary(rows):
    out=[]
    for r in rows or []:
        out.append({
            "horizon":r.get("horizon"),
            "cohort":r.get("cohort"),
            "evidence_state":r.get("evidence_state"),
            "membership_changes":int(r.get("membership_changes") or 0),
            "control_samples":int(r.get("control_samples") or 0),
            "challenger_samples":int(r.get("challenger_samples") or 0),
            "control_avg_return_pct":_num(r.get("control_avg_return_pct")),
            "challenger_avg_return_pct":_num(r.get("challenger_avg_return_pct")),
            "delta_avg_return_pct":_num(r.get("delta_avg_return_pct")),
            "delta_positive_rate_pp":_num(r.get("delta_positive_rate_pp")),
            "delta_mae_pct":_num(r.get("delta_mae_pct")),
        })
    return sorted(out,key=lambda x:(
        {"30m":0,"close":1,"D+1":2,"5m":3}.get(x["horizon"],9),
        {"REVIEW":0,"FOCUS":1}.get(x["cohort"],9),
    ))


def _case_score(case):
    vals=[_num(case.get("return_30m_pct")),_num(case.get("return_close_pct"))]
    vals=[x for x in vals if x is not None]
    return sum(vals)/len(vals) if vals else 0.0


def _case_view(case):
    return {
        "assessment_time":case.get("assessment_time"),
        "stock_code":case.get("stock_code"),
        "stock_name":case.get("stock_name"),
        "market_stance":case.get("market_stance"),
        "control_tier":case.get("control_tier"),
        "challenger_tier":case.get("challenger_tier"),
        "return_30m_pct":_num(case.get("return_30m_pct")),
        "return_close_pct":_num(case.get("return_close_pct")),
        "return_d1_pct":_num(case.get("return_d1_pct")),
    }


def build_dossier(rule,decision,promotion,summaries,changed_cases):
    """Build a stable, review-oriented evidence snapshot."""
    rule=dict(rule or {});decision=dict(decision or {});promotion=dict(promotion or {})
    cases=[dict(x) for x in (changed_cases or [])]
    action=rule.get("action")
    transition_counts=Counter(
        f"{x.get('control_tier','?')}→{x.get('challenger_tier','?')}" for x in cases
    )
    stance_counts=Counter((x.get("market_stance") or "UNKNOWN") for x in cases)

    ranked=sorted(cases,key=_case_score)
    if action=="PROMOTE_ONE_TIER":
        counter=ranked[:8]
        supporting=list(reversed(ranked[-8:]))
        counter_definition="Promoted episodes with the weakest observed 30m/close outcomes."
    else:
        # For suppression, positive episodes are the risk: the rule would have
        # deprioritized observations that subsequently performed well.
        counter=list(reversed(ranked[-8:]))
        supporting=ranked[:8]
        counter_definition="Suppressed episodes with the strongest observed 30m/close outcomes."

    evidence=decision.get("evidence") or {}
    dossier={
        "schema_version":"adoption-dossier-v1",
        "shadow_rule":{
            "shadow_rule_id":rule.get("shadow_rule_id"),
            "candidate_key":rule.get("candidate_key"),
            "rule_version":rule.get("rule_version"),
            "segment_type":rule.get("segment_type"),
            "segment_value":rule.get("segment_value"),
            "source_horizon":rule.get("source_horizon"),
            "action":action,
            "approved_at":str(rule.get("approved_at")) if rule.get("approved_at") else None,
            "prospective_only":True,
        },
        "decision":{
            "state":decision.get("decision_state"),
            "review_eligible":bool(decision.get("review_eligible")),
            "primary_cohort":decision.get("primary_cohort"),
            "reason_codes":list(decision.get("reason_codes") or []),
            "evidence":evidence,
        },
        "promotion_source":{
            "direction":promotion.get("direction"),
            "review_action":promotion.get("review_action"),
            "quality":promotion.get("quality"),
            "walk_forward_status":promotion.get("walk_forward_status"),
            "samples":int(promotion.get("samples") or 0),
            "distinct_stocks":int(promotion.get("distinct_stocks") or 0),
            "distinct_days":int(promotion.get("distinct_days") or 0),
            "avg_return_pct":_num(promotion.get("avg_return_pct")),
            "early_avg_return_pct":_num(promotion.get("early_avg_return_pct")),
            "recent_avg_return_pct":_num(promotion.get("recent_avg_return_pct")),
        },
        "control_vs_challenger":_compact_summary(summaries),
        "impact_surface":{
            "changed_episode_count":len(cases),
            "tier_transitions":dict(sorted(transition_counts.items())),
            "market_stances":dict(sorted(stance_counts.items())),
            "scope":"CURRENT_ASSESSMENT_UNIVERSE_ONLY",
            "blocked_override":False,
        },
        "counterexamples":{
            "definition":counter_definition,
            "cases":[_case_view(x) for x in counter],
        },
        "supporting_examples":[_case_view(x) for x in supporting],
        "known_limits":[
            "Observational prospective A/B; not a randomized causal experiment.",
            "Challenger changes review tier only inside the existing assessment universe.",
            "D+1 is supporting evidence, not a required v1.6 acceptance gate.",
            "Thresholds are operational heuristics and remain subject to future validation.",
            "Market structure and regime relationships can drift after this dossier is generated.",
        ],
        "proposed_change":{
            "engine":"tier-shift-v1",
            "condition":{
                "segment_type":rule.get("segment_type"),
                "segment_value":rule.get("segment_value"),
            },
            "action":action,
            "max_tier_shift":1,
            "blocked_override":False,
            "live_activation":False,
            "next_allowed_step":"HUMAN_APPROVED_DRY_RUN",
        },
        "rollback_criteria":[
            "Shadow Decision state falls to REJECT.",
            "Recent-half 30m or close effect becomes HARMFUL.",
            "Overall 30m and close no longer remain BENEFICIAL.",
            "A comparable market-stance slice becomes HARMFUL.",
            "Data-quality or look-ahead controls are found invalid for the experiment window.",
        ],
        "review_questions":[
            "Is the challenger improvement large enough to matter operationally, not only statistically?",
            "Do counterexamples reveal a coherent failure mode that the proposed rule would worsen?",
            "Is the effect concentrated in one stock, day, or market stance?",
            "Could the same benefit be obtained with a narrower and safer condition?",
            "Are rollback criteria observable quickly enough in a dry run?",
        ],
    }
    return dossier


def canonical_json(dossier):
    return json.dumps(dossier,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)


def dossier_hash(dossier):
    return hashlib.sha256(canonical_json(dossier).encode("utf-8")).hexdigest()
