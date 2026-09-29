from __future__ import annotations

from collections import Counter, defaultdict
import math
import statistics
from typing import Any


def finite(v: Any) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _median(values):
    xs=[finite(x) for x in values]
    xs=[x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _mean(values):
    xs=[finite(x) for x in values]
    xs=[x for x in xs if x is not None]
    return (sum(xs)/len(xs)) if xs else None


def _profit_factor(values):
    xs=[finite(x) for x in values]
    xs=[x for x in xs if x is not None]
    gains=sum(x for x in xs if x>0)
    losses=abs(sum(x for x in xs if x<0))
    if not xs:return None
    if losses==0:return None if gains==0 else 999.0
    return gains/losses


def _positive_pct(values):
    xs=[finite(x) for x in values]
    xs=[x for x in xs if x is not None]
    return (sum(1 for x in xs if x>0)/len(xs)*100) if xs else None


def _metrics(rows: list[dict[str,Any]]) -> dict[str,Any]:
    closed=[r for r in rows if r.get("status")=="CLOSED" and finite(r.get("return_pct")) is not None]
    returns=[r.get("return_pct") for r in closed]
    return {
        "episodes":len(rows),
        "closed":len(closed),
        "open":sum(1 for r in rows if r.get("status")=="OPEN"),
        "positive_pct":_positive_pct(returns),
        "avg_return_pct":_mean(returns),
        "median_return_pct":_median(returns),
        "profit_factor":_profit_factor(returns),
        "median_mfe_pct":_median([r.get("mfe_pct") for r in closed]),
        "median_mae_pct":_median([r.get("mae_pct") for r in closed]),
    }


def summarize_strategy_rows(rows: list[dict[str,Any]], registry: dict[str,dict[str,Any]] | None=None) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for row in rows:
        sid=row.get("strategy_id")
        if sid:groups[str(sid)].append(row)
    out=[]
    for sid,rs in groups.items():
        m=_metrics(rs)
        meta=(registry or {}).get(sid) or {}
        if m["closed"]<10:state="SAMPLE_BUILDING"
        elif m["closed"]<30:state="EARLY"
        else:state="REVIEWABLE"
        out.append({
            "strategy_id":sid,
            "name":meta.get("name") or next((r.get("strategy_name") for r in rs if r.get("strategy_name")),sid),
            "family":meta.get("family") or next((r.get("strategy_family") for r in rs if r.get("strategy_family")),"UNKNOWN"),
            "lifecycle":meta.get("lifecycle") or next((r.get("strategy_lifecycle") for r in rs if r.get("strategy_lifecycle")),"PAPER"),
            **m,
            "state":state,
        })
    out.sort(key=lambda x:(-x["closed"],-x["episodes"],x["strategy_id"]))
    return out


def catalyst_bucket(strength: Any, identity: Any=None) -> str:
    try:s=int(strength or 0)
    except (TypeError,ValueError):s=0
    ident=str(identity or "UNVERIFIED")
    if ident in ("ENTITY_CONFLICT","MISSING_NAME"):
        return "INVALID"
    if s>=3:return "DIRECT"
    if s==2:return "THEME"
    if s==1:return "MENTION"
    return "NONE"


def context_key(row: dict[str,Any]) -> tuple[str,str,str,str]:
    return (
        str(row.get("strategy_id") or "UNASSIGNED"),
        str(row.get("ai_regime_trend") or row.get("regime_label") or "UNKNOWN"),
        catalyst_bucket(row.get("ai_catalyst_strength"),row.get("ai_catalyst_identity")),
        str(row.get("ai_chart_state") or row.get("chart_state_entry") or "UNKNOWN"),
    )


def build_context_matrix(rows: list[dict[str,Any]], min_cell_samples: int=5) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for row in rows:
        if not row.get("strategy_id"):continue
        groups[context_key(row)].append(row)
    out=[]
    for (sid,regime,catalyst,chart),rs in groups.items():
        m=_metrics(rs)
        out.append({
            "strategy_id":sid,
            "regime":regime,
            "catalyst":catalyst,
            "chart_state":chart,
            **m,
            "small_sample":m["closed"]<min_cell_samples,
        })
    out.sort(key=lambda x:(x["small_sample"],-x["closed"],-(x["median_return_pct"] or -999),x["strategy_id"]))
    return out


def lifecycle_candidates(
    strategy_rows: list[dict[str,Any]],
    context_rows: list[dict[str,Any]],
    min_closed: int=30,
    min_positive_pct: float=55.0,
    min_median_return_pct: float=0.20,
    min_profit_factor: float=1.20,
    min_context_cells: int=2,
    min_cell_samples: int=5,
    max_context_concentration: float=0.70,
) -> list[dict[str,Any]]:
    cells_by_strategy=defaultdict(list)
    for c in context_rows:
        cells_by_strategy[c.get("strategy_id")].append(c)

    out=[]
    for s in strategy_rows:
        sid=s["strategy_id"]; lifecycle=str(s.get("lifecycle") or "PAPER")
        closed=int(s.get("closed") or 0)
        pos=finite(s.get("positive_pct")); med=finite(s.get("median_return_pct")); pf=finite(s.get("profit_factor"))
        eligible_cells=[c for c in cells_by_strategy.get(sid,[]) if int(c.get("closed") or 0)>=min_cell_samples]
        max_cell=max([int(c.get("closed") or 0) for c in eligible_cells] or [0])
        concentration=(max_cell/closed) if closed else None
        robust_cells=sum(
            1 for c in eligible_cells
            if (finite(c.get("median_return_pct")) or -999)>0 and (finite(c.get("positive_pct")) or 0)>=50
        )
        criteria={
            "sample":closed>=min_closed,
            "positive":pos is not None and pos>=min_positive_pct,
            "median":med is not None and med>=min_median_return_pct,
            "profit_factor":pf is not None and pf>=min_profit_factor,
            "context_cells":len(eligible_cells)>=min_context_cells,
            "context_concentration":concentration is not None and concentration<=max_context_concentration,
            "robust_cells":robust_cells>=min_context_cells,
        }
        strong=all(criteria.values())
        clearly_weak=closed>=min_closed and (
            (med is not None and med<=0) or
            (pf is not None and pf<1.0) or
            (pos is not None and pos<45)
        )

        if lifecycle=="PAPER":
            if strong:
                action="PROMOTE_CANDIDATE"; label="ACTIVE 승격 검토"
            elif clearly_weak:
                action="REWORK_CANDIDATE"; label="전략 수정·중지 검토"
            elif closed<min_closed:
                action="SAMPLE_BUILDING"; label="표본 축적"
            else:
                action="KEEP_PAPER"; label="PAPER 유지"
        elif lifecycle=="ACTIVE":
            if clearly_weak:
                action="DEMOTE_CANDIDATE"; label="PAPER 강등 검토"
            else:
                action="KEEP_ACTIVE"; label="ACTIVE 유지"
        elif lifecycle=="DISABLED":
            action="KEEP_DISABLED"; label="중지 유지"
        else:
            action="DESIGN_ONLY"; label="설계 단계"

        failed=[k for k,v in criteria.items() if not v]
        out.append({
            "strategy_id":sid,"name":s.get("name"),"family":s.get("family"),
            "lifecycle":lifecycle,"action":action,"label":label,
            "closed":closed,"positive_pct":pos,"median_return_pct":med,"profit_factor":pf,
            "eligible_context_cells":len(eligible_cells),"robust_context_cells":robust_cells,
            "max_context_concentration":concentration,
            "criteria":criteria,"failed_gates":failed,
            "auto_apply":False,
        })

    rank={"PROMOTE_CANDIDATE":0,"DEMOTE_CANDIDATE":1,"REWORK_CANDIDATE":2,"KEEP_PAPER":3,
          "KEEP_ACTIVE":4,"SAMPLE_BUILDING":5,"DESIGN_ONLY":6,"KEEP_DISABLED":7}
    out.sort(key=lambda x:(rank.get(x["action"],9),-x["closed"],x["strategy_id"]))
    return out


def summarize_decisions(rows: list[dict[str,Any]]) -> dict[str,Any]:
    state_counts=Counter(str(r.get("state") or "UNKNOWN") for r in rows)
    strategy_counts=Counter(str(r.get("strategy_id")) for r in rows if r.get("strategy_id"))
    blockers=Counter()
    for r in rows:
        packet=r.get("packet") or {}
        for b in packet.get("blockers") or []:
            blockers[str(b).split(":",1)[0]]+=1
    return {
        "decisions":len(rows),
        "states":dict(state_counts),
        "top_strategies":[{"strategy_id":k,"count":v} for k,v in strategy_counts.most_common(5)],
        "top_blockers":[{"desk":k,"count":v} for k,v in blockers.most_common(5)],
    }


def build_daily_review(decision_rows: list[dict[str,Any]], trade_rows: list[dict[str,Any]], feedback: dict[str,Any] | None=None) -> dict[str,Any]:
    decisions=summarize_decisions(decision_rows)
    closed=[r for r in trade_rows if r.get("status")=="CLOSED" and finite(r.get("return_pct")) is not None]
    returns=[r.get("return_pct") for r in closed]
    return {
        "decisions":decisions,
        "paper":{
            "opened":len(trade_rows),
            "closed":len(closed),
            "avg_return_pct":_mean(returns),
            "median_return_pct":_median(returns),
            "positive_pct":_positive_pct(returns),
        },
        "feedback_state":((feedback or {}).get("payload") or {}).get("state") or (feedback or {}).get("status"),
        "feedback_label":((feedback or {}).get("payload") or {}).get("label"),
    }
