from __future__ import annotations

from collections import defaultdict
import math
import statistics
from typing import Any


def finite(v: Any) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def _mean(values):
    xs=[finite(x) for x in values];xs=[x for x in xs if x is not None]
    return sum(xs)/len(xs) if xs else None


def _median(values):
    xs=[finite(x) for x in values];xs=[x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _percentile(values,q: float):
    xs=sorted(x for x in (finite(v) for v in values) if x is not None)
    if not xs:return None
    if len(xs)==1:return xs[0]
    pos=max(0.0,min(1.0,q))*(len(xs)-1)
    lo=int(math.floor(pos));hi=int(math.ceil(pos))
    if lo==hi:return xs[lo]
    w=pos-lo
    return xs[lo]*(1-w)+xs[hi]*w


def _positive_pct(values):
    xs=[finite(x) for x in values];xs=[x for x in xs if x is not None]
    return sum(1 for x in xs if x>0)/len(xs)*100 if xs else None


def _profit_factor(values):
    xs=[finite(x) for x in values];xs=[x for x in xs if x is not None]
    if not xs:return None
    gains=sum(x for x in xs if x>0);losses=abs(sum(x for x in xs if x<0))
    if losses==0:return 999.0 if gains>0 else None
    return gains/losses


def liquidity_bucket(capacity_krw: Any) -> str:
    x=finite(capacity_krw)
    if x is None:return "UNKNOWN"
    if x<5_000_000:return "L1 <5M"
    if x<20_000_000:return "L2 5-20M"
    if x<50_000_000:return "L3 20-50M"
    if x<100_000_000:return "L4 50-100M"
    return "L5 100M+"


def spread_bucket(spread_bps: Any) -> str:
    x=finite(spread_bps)
    if x is None:return "UNKNOWN"
    if x<=5:return "S1 <=5bp"
    if x<=15:return "S2 5-15bp"
    if x<=30:return "S3 15-30bp"
    return "S4 >30bp"


_ORDER_BUCKETS=[
    ("O1 <=2.5M",0,2_500_000,2_500_000),
    ("O2 2.5-5M",2_500_000,5_000_000,5_000_000),
    ("O3 5-10M",5_000_000,10_000_000,10_000_000),
    ("O4 10-20M",10_000_000,20_000_000,20_000_000),
    ("O5 20M+",20_000_000,float("inf"),None),
]
_ORDER_RANK={name:i for i,(name,_,__,___) in enumerate(_ORDER_BUCKETS)}


def order_size_bucket(notional_krw: Any) -> str:
    x=finite(notional_krw)
    if x is None:return "UNKNOWN"
    for name,lo,hi,_ in _ORDER_BUCKETS:
        if lo<=x<hi:return name
    return "UNKNOWN"


def bucket_upper(bucket: str) -> float | None:
    for name,_,__,upper in _ORDER_BUCKETS:
        if name==bucket:return upper
    return None


def _closed(rows):
    return [r for r in rows if r.get("status")=="CLOSED" and finite(r.get("net_return_pct")) is not None]


def execution_metrics(rows: list[dict[str,Any]]) -> dict[str,Any]:
    closed=_closed(rows)
    nets=[r.get("net_return_pct") for r in closed]
    papers=[r.get("paper_return_pct") for r in closed]
    drags=[r.get("return_drag_pct") for r in closed]
    is_vals=[r.get("round_trip_is_bps") for r in closed]
    books=[r for r in closed if r.get("entry_model_mode")=="BOOK_V2"]
    return {
        "episodes":len(rows),
        "closed":len(closed),
        "book_closed":len(books),
        "book_coverage_pct":(len(books)/len(closed)*100) if closed else None,
        "positive_pct":_positive_pct(nets),
        "avg_net_return_pct":_mean(nets),
        "median_net_return_pct":_median(nets),
        "profit_factor":_profit_factor(nets),
        "median_paper_return_pct":_median(papers),
        "median_return_drag_pct":_median(drags),
        "median_round_trip_is_bps":_median(is_vals),
        "median_fill_ratio_pct":_median([
            (finite(r.get("entry_fill_ratio")) or 0)*100 for r in closed
            if finite(r.get("entry_fill_ratio")) is not None
        ]),
        "median_requested_notional_krw":_median([r.get("requested_notional_krw") for r in closed]),
        "median_book_capacity_krw":_median([r.get("entry_book_capacity_krw") for r in books]),
        "q25_book_capacity_krw":_percentile([r.get("entry_book_capacity_krw") for r in books],.25),
    }


def execution_adjusted_strategy_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for r in rows:
        sid=r.get("strategy_id")
        if sid:groups[str(sid)].append(r)
    out=[]
    for sid,rs in groups.items():
        m=execution_metrics(rs)
        out.append({
            "strategy_id":sid,
            "strategy_name":next((r.get("strategy_name") for r in rs if r.get("strategy_name")),sid),
            "strategy_family":next((r.get("strategy_family") for r in rs if r.get("strategy_family")),"UNKNOWN"),
            **m,
            "state":"SAMPLE_BUILDING" if m["closed"]<20 else "REVIEWABLE",
        })
    out.sort(key=lambda x:(-x["closed"],x["strategy_id"]))
    return out


def build_capacity_matrix(rows: list[dict[str,Any]], min_cell_samples: int=5) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for r in _closed(rows):
        if r.get("entry_model_mode")!="BOOK_V2" or not r.get("strategy_id"):
            continue
        key=(
            str(r.get("strategy_id")),
            str(r.get("regime_label") or "UNKNOWN"),
            liquidity_bucket(r.get("entry_book_capacity_krw")),
            spread_bucket(r.get("entry_spread_bps")),
            order_size_bucket(r.get("requested_notional_krw")),
        )
        groups[key].append(r)
    out=[]
    for (sid,regime,liq,spread,size),rs in groups.items():
        m=execution_metrics(rs)
        out.append({
            "strategy_id":sid,"regime":regime,"liquidity":liq,"spread":spread,
            "order_size":size,**m,"small_sample":m["closed"]<min_cell_samples,
        })
    out.sort(key=lambda x:(x["small_sample"],-x["closed"],x["strategy_id"],
                           _ORDER_RANK.get(x["order_size"],99)))
    return out


def _size_bucket_metrics(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for r in _closed(rows):
        if r.get("entry_model_mode")!="BOOK_V2":continue
        groups[order_size_bucket(r.get("requested_notional_krw"))].append(r)
    out=[]
    for bucket,rs in groups.items():
        m=execution_metrics(rs)
        upper=bucket_upper(bucket)
        out.append({
            "order_size":bucket,"upper_krw":upper,**m,
            "median_requested_notional_krw":_median([r.get("requested_notional_krw") for r in rs]),
        })
    out.sort(key=lambda x:_ORDER_RANK.get(x["order_size"],99))
    return out


def strategy_capacity_rows(
    rows: list[dict[str,Any]],
    min_total_book_closed: int=20,
    min_bucket_closed: int=5,
    min_positive_pct: float=50.0,
    min_median_net_return_pct: float=0.10,
    min_profit_factor: float=1.10,
    max_median_drag_pct: float=0.50,
    max_median_is_bps: float=40.0,
    min_regimes: int=2,
) -> list[dict[str,Any]]:
    groups=defaultdict(list)
    for r in rows:
        sid=r.get("strategy_id")
        if sid:groups[str(sid)].append(r)
    out=[]
    for sid,rs in groups.items():
        book_closed=[r for r in _closed(rs) if r.get("entry_model_mode")=="BOOK_V2"]
        sizes=_size_bucket_metrics(rs)
        tested=[]
        failed=[]
        for b in sizes:
            eligible=int(b["closed"] or 0)>=min_bucket_closed
            passes=eligible and (finite(b["positive_pct"]) or 0)>=min_positive_pct \
                and (finite(b["median_net_return_pct"]) or -999)>=min_median_net_return_pct \
                and (finite(b["profit_factor"]) or 0)>=min_profit_factor \
                and (finite(b["median_return_drag_pct"]) or 999)<=max_median_drag_pct \
                and (finite(b["median_round_trip_is_bps"]) or 999)<=max_median_is_bps
            b["eligible"]=eligible;b["passes"]=passes
            if passes:tested.append(b)
            elif eligible:failed.append(b)
        regimes={str(r.get("regime_label") or "UNKNOWN") for r in book_closed}
        total=len(book_closed)
        q25=_percentile([r.get("entry_book_capacity_krw") for r in book_closed],.25)
        if tested:
            highest=max(tested,key=lambda x:_ORDER_RANK.get(x["order_size"],-1))
            empirical=highest["upper_krw"] or highest["median_requested_notional_krw"]
        else:
            highest=None;empirical=None
        evidence_cap=min(empirical,q25) if empirical is not None and q25 is not None else None
        lower_fail_before_cap=False
        if highest:
            hr=_ORDER_RANK.get(highest["order_size"],99)
            lower_fail_before_cap=any(_ORDER_RANK.get(x["order_size"],99)<hr for x in failed)
        if total<min_total_book_closed:
            state="SAMPLE_BUILDING";label="BOOK 표본 축적"
        elif len(regimes)<min_regimes:
            state="CONTEXT_LIMITED";label="장세 다양성 부족"
        elif not tested:
            state="NO_SUPPORTED_CAPACITY";label="검증 용량 미확인"
        elif lower_fail_before_cap:
            state="NON_MONOTONIC";label="용량 곡선 불연속"
        else:
            state="EVIDENCE_SUPPORTED";label="검증 용량 후보"
        out.append({
            "strategy_id":sid,
            "strategy_name":next((r.get("strategy_name") for r in rs if r.get("strategy_name")),sid),
            "strategy_family":next((r.get("strategy_family") for r in rs if r.get("strategy_family")),"UNKNOWN"),
            "book_closed":total,"regime_count":len(regimes),
            "size_buckets":sizes,"state":state,"label":label,
            "highest_supported_bucket":highest["order_size"] if highest else None,
            "empirical_tested_capacity_krw":empirical,
            "q25_book_capacity_krw":q25,
            "evidence_capacity_krw":evidence_cap,
            "auto_apply":False,
        })
    rank={"EVIDENCE_SUPPORTED":0,"NON_MONOTONIC":1,"CONTEXT_LIMITED":2,
          "NO_SUPPORTED_CAPACITY":3,"SAMPLE_BUILDING":4}
    out.sort(key=lambda x:(rank.get(x["state"],9),-x["book_closed"],x["strategy_id"]))
    return out


def execution_adjusted_lifecycle(
    paper_reviews: list[dict[str,Any]],
    execution_rows: list[dict[str,Any]],
    capacity_rows: list[dict[str,Any]],
    min_shadow_closed: int=20,
    min_book_coverage_pct: float=60.0,
    min_positive_pct: float=50.0,
    min_median_net_return_pct: float=0.10,
    min_profit_factor: float=1.10,
    max_median_drag_pct: float=0.50,
    max_median_is_bps: float=40.0,
) -> list[dict[str,Any]]:
    exec_map={x["strategy_id"]:x for x in execution_rows}
    cap_map={x["strategy_id"]:x for x in capacity_rows}
    out=[]
    for p in paper_reviews:
        sid=p.get("strategy_id")
        e=exec_map.get(sid) or {}
        c=cap_map.get(sid) or {}
        closed=int(e.get("closed") or 0)
        criteria={
            "shadow_sample":closed>=min_shadow_closed,
            "book_coverage":(finite(e.get("book_coverage_pct")) or 0)>=min_book_coverage_pct,
            "net_positive":(finite(e.get("median_net_return_pct")) or -999)>=min_median_net_return_pct,
            "positive_pct":(finite(e.get("positive_pct")) or 0)>=min_positive_pct,
            "profit_factor":(finite(e.get("profit_factor")) or 0)>=min_profit_factor,
            "execution_drag":(finite(e.get("median_return_drag_pct")) or 999)<=max_median_drag_pct,
            "implementation_shortfall":(finite(e.get("median_round_trip_is_bps")) or 999)<=max_median_is_bps,
            "capacity_evidence":c.get("state")=="EVIDENCE_SUPPORTED",
        }
        weak=closed>=min_shadow_closed and (
            (finite(e.get("median_net_return_pct")) is not None and finite(e.get("median_net_return_pct"))<=0)
            or (finite(e.get("profit_factor")) is not None and finite(e.get("profit_factor"))<1.0)
        )
        paper_action=p.get("action")
        if paper_action=="PROMOTE_CANDIDATE":
            if all(criteria.values()):
                action="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED";label="ACTIVE 최종 승격 검토"
            elif weak:
                action="EXECUTION_BLOCKED";label="실행조정 성과가 승격 차단"
            else:
                action="EXECUTION_GATE_PENDING";label="실행 검증 대기"
        elif paper_action in ("DEMOTE_CANDIDATE","REWORK_CANDIDATE") or weak:
            action="DEMOTE_OR_REWORK";label="강등·수정 검토"
        else:
            action="KEEP";label=p.get("label") or "유지"
        out.append({
            "strategy_id":sid,"name":p.get("name"),"lifecycle":p.get("lifecycle"),
            "paper_action":paper_action,"action":action,"label":label,
            "criteria":criteria,"failed_gates":[k for k,v in criteria.items() if not v],
            "paper":p,"execution":e,"capacity":c,"auto_apply":False,
        })
    rank={"PROMOTE_CANDIDATE_EXECUTION_ADJUSTED":0,"EXECUTION_BLOCKED":1,
          "DEMOTE_OR_REWORK":2,"EXECUTION_GATE_PENDING":3,"KEEP":4}
    out.sort(key=lambda x:(rank.get(x["action"],9),x.get("strategy_id") or ""))
    return out
