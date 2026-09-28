"""Pure versioned-ruleset helpers for Market OS dry runs.

A ruleset is an immutable candidate specification built from an approved
Adoption Review Dossier. Evaluating it never mutates the live Market OS output.
"""
from __future__ import annotations

import hashlib
import json

from market_os_shadow import matches, shift_tier, experiment_summaries

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
