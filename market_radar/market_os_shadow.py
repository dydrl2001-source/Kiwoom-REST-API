"""Pure helpers for prospective Market OS shadow-rule experiments.

Shadow rules never mutate the live Market OS output. They only derive a
challenger review tier beside the frozen control tier from the same assessment.
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics

from market_os_store import _bucket_setup, _bucket_strength, _bucket_buy_share, _micro_state

TIER_ORDER=("FOCUS","PREP","DISCOVER")
ALLOWED_ACTIONS={"PROMOTE_ONE_TIER","SUPPRESS_ONE_TIER"}


def dimensions(snapshot):
    tier=snapshot.get("watch_tier") or "UNKNOWN"
    stance=snapshot.get("market_stance") or "UNKNOWN"
    trigger=snapshot.get("trigger_state") or "UNKNOWN"
    session=snapshot.get("session_bucket") or "UNKNOWN"
    setup=_bucket_setup(snapshot.get("setup_score"))
    out={
        "TIER":tier,
        "STANCE":stance,
        "TRIGGER":trigger,
        "SESSION":session,
        "CATALYST":snapshot.get("catalyst_grade") or "UNKNOWN",
        "SETUP":setup,
        "STANCE_TRIGGER":stance+" | "+trigger,
        "TIER_SESSION":tier+" | "+session,
        "STANCE_SETUP":stance+" | "+setup,
        "SETUP_TRIGGER":setup+" | "+trigger,
        "STANCE_SETUP_TRIGGER":stance+" | "+setup+" | "+trigger,
    }
    clean_micro=(int(snapshot.get("micro_tick_count_15s") or 0)>0
                 and int(snapshot.get("micro_gap_count_15s") or 0)==0)
    if clean_micro:
        strength=_bucket_strength(snapshot.get("micro_strength"))
        buy_share=_bucket_buy_share(snapshot.get("micro_buy_share_15s"))
        micro=_micro_state(snapshot.get("micro_strength"),snapshot.get("micro_buy_share_15s"))
        out.update({
            "MICRO_STRENGTH":strength,
            "MICRO_BUY_SHARE":buy_share,
            "MICRO_STATE":micro,
            "STANCE_TRIGGER_MICRO":stance+" | "+trigger+" | "+micro,
            "SETUP_TRIGGER_MICRO":setup+" | "+trigger+" | "+micro,
            "STANCE_SETUP_TRIGGER_MICRO":stance+" | "+setup+" | "+trigger+" | "+micro,
        })
    return out


def matches(snapshot,segment_type,segment_value):
    return dimensions(snapshot).get(segment_type)==segment_value


def shift_tier(control_tier,action):
    """Apply a one-tier shadow priority move without overriding structural blocks."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError("INVALID_SHADOW_ACTION")
    if control_tier=="BLOCKED":
        return "BLOCKED"
    if control_tier not in TIER_ORDER:
        return control_tier
    i=TIER_ORDER.index(control_tier)
    if action=="PROMOTE_ONE_TIER":
        return TIER_ORDER[max(0,i-1)]
    return TIER_ORDER[min(len(TIER_ORDER)-1,i+1)]


def evaluate(snapshot,rule):
    action=rule.get("action")
    control=snapshot.get("watch_tier") or "UNKNOWN"
    matched=matches(snapshot,rule.get("segment_type"),rule.get("segment_value"))
    challenger=shift_tier(control,action) if matched else control
    return {
        "matched":matched,
        "changed":challenger!=control,
        "control_tier":control,
        "challenger_tier":challenger,
        "action":action,
    }


def _finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _stats(rows):
    vals=[x for x in rows if _finite(x.get("return_pct")) is not None]
    if not vals:
        return {
            "samples":0,"distinct_stocks":0,"distinct_days":0,
            "avg_return_pct":None,"median_return_pct":None,"positive_rate":None,
            "avg_mfe_pct":None,"avg_mae_pct":None,
        }
    rets=[float(x["return_pct"]) for x in vals]
    mfes=[float(x["mfe_pct"]) for x in vals if _finite(x.get("mfe_pct")) is not None]
    maes=[float(x["mae_pct"]) for x in vals if _finite(x.get("mae_pct")) is not None]
    return {
        "samples":len(vals),
        "distinct_stocks":len({x.get("stock_code") for x in vals if x.get("stock_code")}),
        "distinct_days":len({x.get("trade_day") for x in vals if x.get("trade_day")}),
        "avg_return_pct":sum(rets)/len(rets),
        "median_return_pct":statistics.median(rets),
        "positive_rate":sum(x>0 for x in rets)/len(rets),
        "avg_mfe_pct":sum(mfes)/len(mfes) if mfes else None,
        "avg_mae_pct":sum(maes)/len(maes) if maes else None,
    }


def _delta(a,b,key,scale=1.0):
    av=a.get(key);bv=b.get(key)
    return (bv-av)*scale if av is not None and bv is not None else None


def experiment_summaries(anchor_rows):
    """Compare CONTROL vs CHALLENGER cohort composition on identical episode anchors.

    Rows must already be horizon-aware non-overlapping anchors. The same observed
    price outcome is used for both variants; only cohort membership differs.
    """
    out=[]
    by_horizon=defaultdict(list)
    for r in anchor_rows:
        by_horizon[r.get("horizon")].append(r)
    cohorts={
        "FOCUS":lambda tier:tier=="FOCUS",
        "REVIEW":lambda tier:tier in {"FOCUS","PREP"},
    }
    for horizon,rows in by_horizon.items():
        for cohort,pred in cohorts.items():
            control=_stats([r for r in rows if pred(r.get("control_tier"))])
            challenger=_stats([r for r in rows if pred(r.get("challenger_tier"))])
            out.append({
                "horizon":horizon,"cohort":cohort,
                "control":control,"challenger":challenger,
                "delta_avg_return_pct":_delta(control,challenger,"avg_return_pct"),
                "delta_positive_rate_pp":_delta(control,challenger,"positive_rate",100),
                "delta_mae_pct":_delta(control,challenger,"avg_mae_pct"),
                "membership_changes":sum(
                    pred(r.get("control_tier"))!=pred(r.get("challenger_tier")) for r in rows
                ),
            })
    return out
