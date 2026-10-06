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

def experiment_slices(anchor_rows):
    """Return pre-registered temporal and market-stance slices for A/B validation."""
    out=[]
    days=sorted({r.get("trade_day") for r in anchor_rows if r.get("trade_day")})
    if len(days)>=4:
        cut=len(days)//2
        for name,dayset in (
            ("EARLY",set(days[:cut])),
            ("RECENT",set(days[cut:])),
        ):
            rows=[r for r in anchor_rows if r.get("trade_day") in dayset]
            for s in experiment_summaries(rows):
                out.append({"scope_type":"WINDOW","scope_value":name,**s})
    stance_groups=defaultdict(list)
    for r in anchor_rows:
        stance_groups[r.get("market_stance") or "UNKNOWN"].append(r)
    for stance,rows in stance_groups.items():
        for s in experiment_summaries(rows):
            out.append({"scope_type":"STANCE","scope_value":stance,**s})
    return out


def _cell_ready(cell,strong=False):
    if not cell:
        return False
    control=cell.get("control") or {}
    challenger=cell.get("challenger") or {}
    min_n=40 if strong else 20
    min_days=6 if strong else 3
    min_stocks=8 if strong else 5
    min_changes=10 if strong else 5
    return (
        int(cell.get("membership_changes") or 0)>=min_changes
        and min(int(control.get("samples") or 0),int(challenger.get("samples") or 0))>=min_n
        and min(int(control.get("distinct_days") or 0),int(challenger.get("distinct_days") or 0))>=min_days
        and min(int(control.get("distinct_stocks") or 0),int(challenger.get("distinct_stocks") or 0))>=min_stocks
    )


def _effect_state(cell,strong=False):
    """Classify challenger minus control without selecting a winner from noise."""
    if not _cell_ready(cell,strong=strong):
        return "INSUFFICIENT"
    d_avg=_finite(cell.get("delta_avg_return_pct"))
    d_pos=_finite(cell.get("delta_positive_rate_pp"))
    d_mae=_finite(cell.get("delta_mae_pct"))
    if d_avg is None or d_pos is None or d_mae is None:
        return "INCOMPLETE"
    avg_cut=.20 if strong else .10
    pos_cut=3.0 if strong else 1.0
    if d_avg>=avg_cut and d_pos>=pos_cut and d_mae>=0:
        return "BENEFICIAL"
    if d_avg<=-avg_cut and d_pos<=-pos_cut and d_mae<=0:
        return "HARMFUL"
    return "MIXED"


def shadow_decision(rule,overall_summaries,slices):
    """Conservative prospective decision gate for an already-approved shadow rule.

    ACCEPT_CANDIDATE means only that the challenger deserves human replacement
    review. It never mutates live Market OS rules or disables/enables anything.
    """
    overall={(x.get("horizon"),x.get("cohort")):x for x in overall_summaries}
    scoped={(x.get("scope_type"),x.get("scope_value"),x.get("horizon"),x.get("cohort")):x
            for x in slices}

    # Select the cohort where the challenger actually changes more membership.
    # This selects the impact surface only; it does not inspect performance.
    change_totals={}
    for cohort in ("REVIEW","FOCUS"):
        change_totals[cohort]=sum(
            int((overall.get((h,cohort)) or {}).get("membership_changes") or 0)
            for h in ("30m","close")
        )
    primary="REVIEW" if change_totals["REVIEW"]>=change_totals["FOCUS"] else "FOCUS"

    c30=overall.get(("30m",primary))
    cclose=overall.get(("close",primary))
    state30=_effect_state(c30)
    state_close=_effect_state(cclose)
    strong30=_effect_state(c30,strong=True)
    strong_close=_effect_state(cclose,strong=True)

    evidence={
        "primary_cohort":primary,
        "membership_changes_30m":int((c30 or {}).get("membership_changes") or 0),
        "membership_changes_close":int((cclose or {}).get("membership_changes") or 0),
        "overall_30m":state30,
        "overall_close":state_close,
        "overall_30m_strong":strong30,
        "overall_close_strong":strong_close,
    }
    reasons=[]

    if state30=="INSUFFICIENT":
        return {"state":"COLLECTING","review_eligible":False,
                "reason_codes":["30M_NOT_COMPARABLE"],"evidence":evidence}
    if state_close=="INSUFFICIENT":
        return {"state":"COMPARABLE","review_eligible":False,
                "reason_codes":["30M_COMPARABLE","CLOSE_NOT_COMPARABLE"],"evidence":evidence}

    if state30=="HARMFUL" and state_close=="HARMFUL":
        return {"state":"REJECT","review_eligible":False,
                "reason_codes":["30M_AND_CLOSE_HARMFUL"],"evidence":evidence}

    early30=scoped.get(("WINDOW","EARLY","30m",primary))
    recent30=scoped.get(("WINDOW","RECENT","30m",primary))
    early_close=scoped.get(("WINDOW","EARLY","close",primary))
    recent_close=scoped.get(("WINDOW","RECENT","close",primary))
    temporal={
        "early_30m":_effect_state(early30),
        "recent_30m":_effect_state(recent30),
        "early_close":_effect_state(early_close),
        "recent_close":_effect_state(recent_close),
    }
    evidence["temporal"]=temporal

    if state30!="BENEFICIAL" or state_close!="BENEFICIAL":
        reasons.append("OVERALL_EFFECT_MIXED")
        return {"state":"MORE_DATA","review_eligible":False,
                "reason_codes":reasons,"evidence":evidence}

    if temporal["recent_30m"]=="HARMFUL" or temporal["recent_close"]=="HARMFUL":
        return {"state":"REJECT","review_eligible":False,
                "reason_codes":["RECENT_HALF_HARMFUL"],"evidence":evidence}
    if temporal["early_30m"]!="BENEFICIAL" or temporal["recent_30m"]!="BENEFICIAL":
        return {"state":"MORE_DATA","review_eligible":False,
                "reason_codes":["30M_TIME_SPLIT_NOT_STABLE"],"evidence":evidence}
    if temporal["early_close"] not in ("BENEFICIAL","INSUFFICIENT") or temporal["recent_close"] not in ("BENEFICIAL","INSUFFICIENT"):
        return {"state":"MORE_DATA","review_eligible":False,
                "reason_codes":["CLOSE_TIME_SPLIT_NOT_STABLE"],"evidence":evidence}

    segment_type=rule.get("segment_type") or ""
    stance_scoped="STANCE" in segment_type
    stance_evidence=[]
    for stance in ("EXPANDABLE","SELECTIVE","DEFENSIVE"):
        cell=scoped.get(("STANCE",stance,"30m",primary))
        if cell and int(cell.get("membership_changes") or 0)>0:
            stance_evidence.append({
                "stance":stance,
                "state":_effect_state(cell),
                "strong_state":_effect_state(cell,strong=True),
                "membership_changes":int(cell.get("membership_changes") or 0),
            })
    evidence["stance"]=stance_evidence
    evidence["stance_scoped"]=stance_scoped

    if stance_scoped:
        target=(rule.get("segment_value") or "").split(" | ")[0]
        target_rows=[x for x in stance_evidence if x["stance"]==target]
        if not target_rows or target_rows[0]["state"]!="BENEFICIAL":
            return {"state":"MORE_DATA","review_eligible":False,
                    "reason_codes":["TARGET_STANCE_NOT_REPLICATED"],"evidence":evidence}
        stance_ok=True
    else:
        comparable=[x for x in stance_evidence if x["state"]!="INSUFFICIENT"]
        if any(x["state"]=="HARMFUL" for x in comparable):
            return {"state":"MORE_DATA","review_eligible":False,
                    "reason_codes":["STANCE_CONTRADICTION"],"evidence":evidence}
        stance_ok=sum(x["state"]=="BENEFICIAL" for x in comparable)>=2
        if not stance_ok:
            return {"state":"MORE_DATA","review_eligible":False,
                    "reason_codes":["MULTI_STANCE_REPLICATION_PENDING"],"evidence":evidence}

    reasons=["30M_CLOSE_BENEFICIAL","30M_TIME_SPLIT_STABLE","STANCE_REPRODUCED"]
    consistent={"state":"CONSISTENT","review_eligible":False,
                "reason_codes":reasons,"evidence":evidence}

    recent_close_ready=_cell_ready(recent_close,strong=False)
    early_close_ready=_cell_ready(early_close,strong=False)
    recent30_strong=_effect_state(recent30,strong=True)=="BENEFICIAL"
    # Strong acceptance requires larger full-period evidence and both close windows
    # to be genuinely comparable, not merely non-contradictory.
    if (strong30=="BENEFICIAL" and strong_close=="BENEFICIAL"
            and recent30_strong
            and early_close_ready and recent_close_ready
            and temporal["early_close"]=="BENEFICIAL"
            and temporal["recent_close"]=="BENEFICIAL"):
        return {
            "state":"ACCEPT_CANDIDATE","review_eligible":True,
            "reason_codes":reasons+["STRONG_SAMPLE_GATE_PASSED","CLOSE_TIME_SPLIT_STABLE"],
            "evidence":evidence,
        }
    return consistent

