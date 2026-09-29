from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any


def finite(v: Any) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def clamp(v: float, lo: float=0.0, hi: float=1.0) -> float:
    return max(lo,min(hi,float(v)))


@dataclass(frozen=True)
class AllocationPolicy:
    account_equity_krw: float = 100_000_000
    max_total_risk_pct: float = 2.0
    max_single_risk_pct: float = 0.50
    max_theme_risk_pct: float = 0.80
    max_family_risk_pct: float = 1.20
    max_position_pct: float = 10.0
    max_positions: int = 5
    risk_chunk_pct: float = 0.05
    correlation_penalty_weight: float = 0.65
    unknown_correlation_penalty: float = 0.15
    high_correlation_threshold: float = 0.80
    pending_evidence_scale: float = 0.35
    sample_building_scale: float = 0.20


def pearson(x: list[float], y: list[float], min_obs: int=20) -> float | None:
    n=min(len(x),len(y))
    if n<min_obs:return None
    a=x[-n:];b=y[-n:]
    ma=sum(a)/n;mb=sum(b)/n
    va=sum((v-ma)**2 for v in a);vb=sum((v-mb)**2 for v in b)
    if va<=0 or vb<=0:return None
    cov=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    return max(-1.0,min(1.0,cov/math.sqrt(va*vb)))


def aligned_return_correlation(
    series_a: dict[Any,float],
    series_b: dict[Any,float],
    min_obs: int=20,
) -> float | None:
    common=sorted(set(series_a).intersection(series_b))
    if len(common)<min_obs+1:return None
    ra=[];rb=[]
    for p0,p1 in zip(common[:-1],common[1:]):
        a0=finite(series_a.get(p0));a1=finite(series_a.get(p1))
        b0=finite(series_b.get(p0));b1=finite(series_b.get(p1))
        if None in (a0,a1,b0,b1) or a0<=0 or b0<=0:continue
        ra.append(a1/a0-1.0);rb.append(b1/b0-1.0)
    return pearson(ra,rb,min_obs=min_obs)


def correlation_matrix(
    price_series: dict[str,dict[Any,float]],
    min_obs: int=20,
) -> dict[str,dict[str,float | None]]:
    codes=sorted(price_series)
    out={c:{} for c in codes}
    for i,a in enumerate(codes):
        for b in codes[i:]:
            value=1.0 if a==b else aligned_return_correlation(price_series[a],price_series[b],min_obs)
            out[a][b]=value;out[b][a]=value
    return out


def evidence_scale(final_action: str | None, capacity_state: str | None, policy: AllocationPolicy) -> float:
    action=str(final_action or "")
    cap=str(capacity_state or "")
    if action in ("EXECUTION_BLOCKED","DEMOTE_OR_REWORK"):
        return 0.0
    if action=="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED" and cap=="EVIDENCE_SUPPORTED":
        return 1.0
    if action=="EXECUTION_GATE_PENDING":
        return policy.pending_evidence_scale
    if cap in ("SAMPLE_BUILDING","CONTEXT_LIMITED") or not action:
        return policy.sample_building_scale
    return policy.sample_building_scale


def candidate_priority(candidate: dict[str,Any], scale: float) -> dict[str,Any]:
    conviction=finite(candidate.get("conviction"))
    fit=finite(candidate.get("strategy_fit"))
    net=finite(candidate.get("median_net_return_pct"))
    pf=finite(candidate.get("profit_factor"))
    positive=finite(candidate.get("positive_pct"))
    is_bps=finite(candidate.get("median_round_trip_is_bps"))
    drag=finite(candidate.get("median_return_drag_pct"))

    signal=clamp(((conviction or 50)-50)/50,0,1)
    strategy_fit=clamp(((fit or 50)-50)/50,0,1)
    edge=clamp((net or 0)/1.0,0,1)
    pf_score=clamp(((pf or 1)-1)/1.0,0,1)
    hit=clamp(((positive or 50)-50)/30,0,1)
    execution_penalty=clamp((is_bps or 0)/100,0,1)*0.12 + clamp((drag or 0)/1.0,0,1)*0.12
    raw=(0.28*edge + 0.17*pf_score + 0.10*hit + 0.27*signal + 0.18*strategy_fit - execution_penalty)
    score=max(0.0,raw)*scale
    return {
        "priority_score":score,
        "evidence_scale":scale,
        "components":{
            "edge":edge,"profit_factor":pf_score,"positive":hit,
            "signal":signal,"strategy_fit":strategy_fit,
            "execution_penalty":execution_penalty,
        },
        "meaning":"research priority score; not expected return",
    }


def _positive_corr(
    code: str,
    allocated: dict[str,float],
    correlations: dict[str,dict[str,float | None]],
) -> tuple[float,list[dict[str,Any]],int]:
    vals=[];unknown=0
    for other,risk in allocated.items():
        if risk<=0 or other==code:continue
        corr=(correlations.get(code) or {}).get(other)
        if corr is None:
            unknown+=1
            continue
        vals.append({"code":other,"corr":float(corr),"risk_krw":risk})
    if not vals:return 0.0,[],unknown
    positives=[x for x in vals if x["corr"]>0]
    return (max((x["corr"] for x in positives),default=0.0),
            sorted(vals,key=lambda x:-abs(x["corr"]))[:5],unknown)


def optimize_allocations(
    candidates: list[dict[str,Any]],
    correlations: dict[str,dict[str,float | None]] | None=None,
    open_positions: list[dict[str,Any]] | None=None,
    policy: AllocationPolicy | None=None,
) -> dict[str,Any]:
    p=policy or AllocationPolicy()
    corr=correlations or {}
    open_positions=open_positions or []
    equity=float(p.account_equity_krw)

    total_cap=equity*p.max_total_risk_pct/100.0
    single_cap=equity*p.max_single_risk_pct/100.0
    theme_cap=equity*p.max_theme_risk_pct/100.0
    family_cap=equity*p.max_family_risk_pct/100.0
    position_notional_cap=equity*p.max_position_pct/100.0
    chunk=max(1.0,equity*p.risk_chunk_pct/100.0)

    used_total=sum(max(0.0,float(x.get("risk_krw") or 0)) for x in open_positions)
    used_theme={}
    used_family={}
    for x in open_positions:
        risk=max(0.0,float(x.get("risk_krw") or 0))
        theme=str(x.get("market_theme") or "UNKNOWN")
        family=str(x.get("strategy_family") or "UNKNOWN")
        used_theme[theme]=used_theme.get(theme,0.0)+risk
        used_family[family]=used_family.get(family,0.0)+risk

    prepared=[]
    rejected=[]
    for raw in candidates:
        c=dict(raw)
        code=str(c.get("stock_code") or c.get("code") or "")
        state=str(c.get("state") or "")
        price=finite(c.get("price_krw"))
        stop=finite(c.get("stop_pct"))
        capacity=finite(c.get("evidence_capacity_krw"))
        theme=str(c.get("market_theme") or "UNKNOWN")
        family=str(c.get("strategy_family") or "UNKNOWN")
        action=c.get("final_action")
        cap_state=c.get("capacity_state")
        scale=evidence_scale(action,cap_state,p)
        priority=candidate_priority(c,scale)
        reasons=[]
        if state!="PAPER_ENTRY":reasons.append("NOT_PAPER_ENTRY")
        if not code:reasons.append("MISSING_CODE")
        if price is None or price<=0:reasons.append("MISSING_PRICE")
        if stop is None or stop<=0:reasons.append("MISSING_STOP")
        if scale<=0:reasons.append("EVIDENCE_BLOCKED")
        if capacity is None or capacity<=0:
            # research candidates may use a point-in-time capacity if explicitly supplied.
            capacity=finite(c.get("point_in_time_capacity_krw"))
        if capacity is None or capacity<=0:reasons.append("NO_CAPACITY_EVIDENCE")
        if reasons:
            rejected.append({**c,"stock_code":code,"reasons":reasons,**priority})
            continue
        max_notional=min(capacity,position_notional_cap)
        capacity_risk=max_notional*(stop/100.0)
        evidence_risk=single_cap*scale
        max_risk=min(single_cap,capacity_risk,evidence_risk)
        if max_risk<chunk*.5:
            rejected.append({**c,"stock_code":code,"reasons":["RISK_BUDGET_TOO_SMALL"],**priority})
            continue
        prepared.append({
            **c,"stock_code":code,"price_krw":price,"stop_pct":stop,
            "market_theme":theme,"strategy_family":family,
            "capacity_krw":capacity,"max_notional_krw":max_notional,
            "max_risk_krw":max_risk,**priority,
        })

    allocations={x["stock_code"]:0.0 for x in prepared}
    details={x["stock_code"]:x for x in prepared}
    active_allocated=set()
    max_new=max(0,p.max_positions-len(open_positions))
    iterations=0

    while prepared and used_total+1e-9<total_cap and iterations<1000:
        iterations+=1
        choices=[]
        for c in prepared:
            code=c["stock_code"];current=allocations[code]
            if current+1e-9>=c["max_risk_krw"]:continue
            if code not in active_allocated and len(active_allocated)>=max_new:continue
            theme=c["market_theme"];family=c["strategy_family"]
            theme_now=used_theme.get(theme,0.0)
            family_now=used_family.get(family,0.0)
            room=min(
                c["max_risk_krw"]-current,
                total_cap-used_total,
                theme_cap-theme_now,
                family_cap-family_now,
            )
            if room<=0:continue
            max_corr,corr_peers,unknown_corr=_positive_corr(code,allocations,corr)
            corr_penalty=clamp(max_corr,0,1)*p.correlation_penalty_weight
            if unknown_corr>0:
                corr_penalty=max(corr_penalty,min(.50,p.unknown_correlation_penalty*unknown_corr))
            if max_corr>=p.high_correlation_threshold and current>=c["max_risk_krw"]*.5:
                corr_penalty=max(corr_penalty,.75)
            saturation=math.sqrt(max(0.0,1.0-current/max(c["max_risk_krw"],1.0)))
            marginal=c["priority_score"]*(1.0-corr_penalty)*saturation
            choices.append((marginal,room,max_corr,corr_peers,unknown_corr,c))
        if not choices:break
        choices.sort(key=lambda x:(-x[0],-x[1],x[5]["stock_code"]))
        marginal,room,max_corr,corr_peers,unknown_corr,c=choices[0]
        if marginal<=0:break
        add=min(chunk,room)
        code=c["stock_code"];theme=c["market_theme"];family=c["strategy_family"]
        allocations[code]+=add;used_total+=add
        used_theme[theme]=used_theme.get(theme,0.0)+add
        used_family[family]=used_family.get(family,0.0)+add
        active_allocated.add(code)

    rows=[]
    for code,risk in allocations.items():
        c=details[code]
        if risk<=0:
            rejected.append({**c,"reasons":["PORTFOLIO_CONSTRAINT_NO_ROOM"]})
            continue
        notional=min(c["max_notional_krw"],risk/(c["stop_pct"]/100.0))
        shares=max(0,int(notional//c["price_krw"]))
        notional=shares*c["price_krw"]
        actual_risk=notional*c["stop_pct"]/100.0
        max_corr,corr_peers,unknown_corr=_positive_corr(
            code,{k:v for k,v in allocations.items() if k!=code},corr
        )
        rows.append({
            "stock_code":code,"stock_name":c.get("stock_name") or c.get("name"),
            "strategy_id":c.get("strategy_id"),"strategy_name":c.get("strategy_name"),
            "strategy_family":c["strategy_family"],"market_theme":c["market_theme"],
            "state":c.get("state"),"final_action":c.get("final_action"),
            "priority_score":c["priority_score"],"priority_components":c["components"],
            "evidence_scale":c["evidence_scale"],
            "allocated_risk_krw":actual_risk,"allocated_notional_krw":notional,
            "shares":shares,"price_krw":c["price_krw"],"stop_pct":c["stop_pct"],
            "capacity_krw":c["capacity_krw"],"capacity_utilization_pct":notional/c["capacity_krw"]*100,
            "max_positive_corr":max_corr,"correlation_peers":corr_peers,
            "unknown_correlation_peers":unknown_corr,
            "paper_only":True,
        })
    rows.sort(key=lambda x:(-x["allocated_risk_krw"],-x["priority_score"],x["stock_code"]))

    final_risk=sum(x["allocated_risk_krw"] for x in rows)
    existing_risk=sum(max(0.0,float(x.get("risk_krw") or 0)) for x in open_positions)
    actual_total_risk=existing_risk+final_risk
    return {
        "status":"OK" if rows else "NO_ALLOCATION",
        "paper_only":True,
        "allocations":rows,
        "rejected":rejected,
        "summary":{
            "account_equity_krw":equity,
            "existing_risk_krw":existing_risk,
            "new_allocated_risk_krw":final_risk,
            "total_risk_cap_krw":total_cap,
            "actual_total_risk_krw":actual_total_risk,
            "risk_utilization_pct":(actual_total_risk/total_cap*100) if total_cap>0 else None,
            "new_positions":len(rows),
            "max_positions":p.max_positions,
            "iterations":iterations,
        },
        "constraints":{
            "single_risk_cap_krw":single_cap,
            "theme_risk_cap_krw":theme_cap,
            "family_risk_cap_krw":family_cap,
            "position_notional_cap_krw":position_notional_cap,
            "risk_chunk_krw":chunk,
        },
        "policy":asdict(p),
        "note":"shadow capital allocation only; deterministic constrained allocator; priority score is not expected return",
    }
