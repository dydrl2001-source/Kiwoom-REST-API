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


def summarize_strategy_rows(rows: list[dict[str,Any]], registry: dict[str,dict[str,Any]] | None=None) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for row in rows:
        sid=row.get("strategy_id")
        if sid:groups[str(sid)].append(row)
    out=[]
    for sid,rs in groups.items():
        returns=[r.get("return_pct") for r in rs if r.get("status")=="CLOSED" and finite(r.get("return_pct")) is not None]
        closed=len(returns)
        positive=(sum(1 for x in returns if finite(x)>0)/closed*100) if closed else None
        meta=(registry or {}).get(sid) or {}
        if closed<10:state="SAMPLE_BUILDING"
        elif closed<30:state="EARLY"
        else:state="REVIEWABLE"
        out.append({
            "strategy_id":sid,
            "name":meta.get("name") or next((r.get("strategy_name") for r in rs if r.get("strategy_name")),sid),
            "family":meta.get("family") or next((r.get("strategy_family") for r in rs if r.get("strategy_family")),"UNKNOWN"),
            "lifecycle":meta.get("lifecycle") or next((r.get("strategy_lifecycle") for r in rs if r.get("strategy_lifecycle")),"PAPER"),
            "episodes":len(rs),
            "closed":closed,
            "open":sum(1 for r in rs if r.get("status")=="OPEN"),
            "positive_pct":positive,
            "avg_return_pct":_mean(returns),
            "median_return_pct":_median(returns),
            "profit_factor":_profit_factor(returns),
            "median_mfe_pct":_median([r.get("mfe_pct") for r in rs if r.get("status")=="CLOSED"]),
            "median_mae_pct":_median([r.get("mae_pct") for r in rs if r.get("status")=="CLOSED"]),
            "state":state,
        })
    out.sort(key=lambda x:(-x["closed"],-x["episodes"],x["strategy_id"]))
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
            "positive_pct":(sum(1 for x in returns if finite(x)>0)/len(returns)*100) if returns else None,
        },
        "feedback_state":((feedback or {}).get("payload") or {}).get("state") or (feedback or {}).get("status"),
        "feedback_label":((feedback or {}).get("payload") or {}).get("label"),
    }
