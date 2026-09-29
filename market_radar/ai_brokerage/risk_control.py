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


@dataclass(frozen=True)
class RiskControlPolicy:
    max_daily_loss_pct: float = 2.0
    hard_risk_utilization_pct: float = 105.0
    warn_risk_utilization_pct: float = 90.0
    max_critical_feed_age_sec: int = 180
    max_orderbook_age_sec: int = 90
    max_median_round_trip_is_bps: float = 60.0
    warn_median_round_trip_is_bps: float = 40.0
    max_execution_reject_pct: float = 50.0
    warn_execution_reject_pct: float = 30.0
    min_book_coverage_pct: float = 50.0
    max_portfolio_corr: float = 0.92
    warn_portfolio_corr: float = 0.80
    max_unknown_corr_pairs: int = 3
    min_live_paper_closed: int = 100
    min_live_shadow_closed: int = 60
    min_live_book_closed: int = 40
    min_live_operating_days: int = 10
    min_live_book_coverage_pct: float = 80.0
    min_live_supported_strategies: int = 1


def _age_sec(now_epoch: float | None, ts_epoch: float | None) -> float | None:
    if now_epoch is None or ts_epoch is None:return None
    return max(0.0,float(now_epoch)-float(ts_epoch))


def evaluate_kill_switch(metrics: dict[str,Any], policy: RiskControlPolicy | None=None) -> dict[str,Any]:
    p=policy or RiskControlPolicy()
    hard=[]
    warnings=[]
    evidence={}

    daily=finite(metrics.get("daily_shadow_return_pct"))
    risk_util=finite(metrics.get("risk_utilization_pct"))
    is_bps=finite(metrics.get("median_round_trip_is_bps"))
    reject=finite(metrics.get("execution_reject_pct"))
    book_cov=finite(metrics.get("book_coverage_pct"))
    max_corr=finite(metrics.get("max_portfolio_corr"))
    unknown_corr=int(metrics.get("unknown_corr_pairs") or 0)

    evidence.update({
        "daily_shadow_return_pct":daily,
        "risk_utilization_pct":risk_util,
        "median_round_trip_is_bps":is_bps,
        "execution_reject_pct":reject,
        "book_coverage_pct":book_cov,
        "max_portfolio_corr":max_corr,
        "unknown_corr_pairs":unknown_corr,
    })

    if daily is not None and daily<=-abs(p.max_daily_loss_pct):
        hard.append({"code":"DAILY_LOSS_LIMIT","value":daily,"limit":-abs(p.max_daily_loss_pct)})
    if risk_util is not None and risk_util>=p.hard_risk_utilization_pct:
        hard.append({"code":"PORTFOLIO_RISK_BREACH","value":risk_util,"limit":p.hard_risk_utilization_pct})
    elif risk_util is not None and risk_util>=p.warn_risk_utilization_pct:
        warnings.append({"code":"PORTFOLIO_RISK_HIGH","value":risk_util,"limit":p.warn_risk_utilization_pct})

    critical_feeds=metrics.get("critical_feeds") or {}
    for name,feed in critical_feeds.items():
        status=str((feed or {}).get("status") or "UNKNOWN")
        age=finite((feed or {}).get("age_sec"))
        evidence[f"feed_{name}"]={"status":status,"age_sec":age}
        if status in ("ERROR","FAILED","DOWN"):
            hard.append({"code":"CRITICAL_FEED_ERROR","feed":name,"status":status})
        elif age is not None and age>p.max_critical_feed_age_sec:
            hard.append({"code":"CRITICAL_FEED_STALE","feed":name,"age_sec":age,
                         "limit":p.max_critical_feed_age_sec})
        elif status in ("NOT_CONFIGURED","WAITING_FOR_CREDENTIALS"):
            warnings.append({"code":"CRITICAL_FEED_NOT_READY","feed":name,"status":status})

    orderbook=metrics.get("orderbook_feed") or {}
    ob_status=str(orderbook.get("status") or "UNKNOWN")
    ob_age=finite(orderbook.get("age_sec"))
    evidence["orderbook_feed"]={"status":ob_status,"age_sec":ob_age}
    if ob_status=="ERROR":
        warnings.append({"code":"ORDERBOOK_ERROR","status":ob_status})
    elif ob_age is not None and ob_age>p.max_orderbook_age_sec:
        warnings.append({"code":"ORDERBOOK_STALE","age_sec":ob_age,"limit":p.max_orderbook_age_sec})

    if is_bps is not None and is_bps>p.max_median_round_trip_is_bps:
        hard.append({"code":"EXECUTION_IS_DEGRADED","value":is_bps,"limit":p.max_median_round_trip_is_bps})
    elif is_bps is not None and is_bps>p.warn_median_round_trip_is_bps:
        warnings.append({"code":"EXECUTION_IS_HIGH","value":is_bps,"limit":p.warn_median_round_trip_is_bps})

    if reject is not None and reject>=p.max_execution_reject_pct:
        hard.append({"code":"EXECUTION_REJECT_SPIKE","value":reject,"limit":p.max_execution_reject_pct})
    elif reject is not None and reject>=p.warn_execution_reject_pct:
        warnings.append({"code":"EXECUTION_REJECT_HIGH","value":reject,"limit":p.warn_execution_reject_pct})

    if book_cov is not None and book_cov<p.min_book_coverage_pct:
        warnings.append({"code":"BOOK_COVERAGE_LOW","value":book_cov,"limit":p.min_book_coverage_pct})
    if max_corr is not None and max_corr>=p.max_portfolio_corr:
        hard.append({"code":"PORTFOLIO_CORRELATION_SPIKE","value":max_corr,"limit":p.max_portfolio_corr})
    elif max_corr is not None and max_corr>=p.warn_portfolio_corr:
        warnings.append({"code":"PORTFOLIO_CORRELATION_HIGH","value":max_corr,"limit":p.warn_portfolio_corr})
    if unknown_corr>p.max_unknown_corr_pairs:
        warnings.append({"code":"CORRELATION_EVIDENCE_GAP","value":unknown_corr,
                         "limit":p.max_unknown_corr_pairs})

    manual_halt=bool(metrics.get("manual_halt"))
    if manual_halt:
        hard.append({"code":"MANUAL_HALT"})

    state="HALT" if hard else "DEGRADED" if warnings else "RUN"
    return {
        "state":state,
        "allow_new_shadow_entries":state!="HALT",
        "hard_triggers":hard,
        "warnings":warnings,
        "evidence":evidence,
        "manual_halt":manual_halt,
        "policy":asdict(p),
    }


def evaluate_live_readiness(metrics: dict[str,Any], kill_switch: dict[str,Any],
                            policy: RiskControlPolicy | None=None) -> dict[str,Any]:
    p=policy or RiskControlPolicy()
    broker_mode=str(metrics.get("broker_mode") or "unknown").lower()
    paper_closed=int(metrics.get("paper_closed") or 0)
    shadow_closed=int(metrics.get("shadow_closed") or 0)
    book_closed=int(metrics.get("book_closed") or 0)
    operating_days=int(metrics.get("operating_days") or 0)
    book_cov=finite(metrics.get("book_coverage_pct")) or 0.0
    supported=int(metrics.get("supported_strategies") or 0)
    costs_configured=bool(metrics.get("costs_configured"))
    orderbook_ok=bool(metrics.get("orderbook_ok"))
    critical_feeds_ok=bool(metrics.get("critical_feeds_ok"))
    allocation_history=int(metrics.get("allocation_snapshots") or 0)
    live_order_path_present=bool(metrics.get("live_order_path_present"))

    gates=[
        {"id":"KILL_SWITCH_RUN","pass":kill_switch.get("state")=="RUN",
         "value":kill_switch.get("state"),"required":"RUN"},
        {"id":"BROKER_REAL_MODE","pass":broker_mode=="real","value":broker_mode,"required":"real"},
        {"id":"CRITICAL_FEEDS_OK","pass":critical_feeds_ok,"value":critical_feeds_ok,"required":True},
        {"id":"ORDERBOOK_OK","pass":orderbook_ok,"value":orderbook_ok,"required":True},
        {"id":"COSTS_CONFIGURED","pass":costs_configured,"value":costs_configured,"required":True},
        {"id":"PAPER_SAMPLE","pass":paper_closed>=p.min_live_paper_closed,
         "value":paper_closed,"required":p.min_live_paper_closed},
        {"id":"SHADOW_SAMPLE","pass":shadow_closed>=p.min_live_shadow_closed,
         "value":shadow_closed,"required":p.min_live_shadow_closed},
        {"id":"BOOK_SAMPLE","pass":book_closed>=p.min_live_book_closed,
         "value":book_closed,"required":p.min_live_book_closed},
        {"id":"OPERATING_DAYS","pass":operating_days>=p.min_live_operating_days,
         "value":operating_days,"required":p.min_live_operating_days},
        {"id":"BOOK_COVERAGE","pass":book_cov>=p.min_live_book_coverage_pct,
         "value":book_cov,"required":p.min_live_book_coverage_pct},
        {"id":"SUPPORTED_STRATEGIES","pass":supported>=p.min_live_supported_strategies,
         "value":supported,"required":p.min_live_supported_strategies},
        {"id":"ALLOCATION_HISTORY","pass":allocation_history>=p.min_live_operating_days,
         "value":allocation_history,"required":p.min_live_operating_days},
        {"id":"LIVE_ORDER_PATH_DISABLED","pass":not live_order_path_present,
         "value":live_order_path_present,"required":False},
    ]
    failed=[g for g in gates if not g["pass"]]
    research_ready=all(g["pass"] for g in gates if g["id"] not in ("BROKER_REAL_MODE","COSTS_CONFIGURED"))
    readiness="SHADOW_VALIDATED" if not failed else "RESEARCH_ONLY"
    if research_ready and broker_mode=="real" and costs_configured:
        readiness="LIVE_READINESS_REVIEW"
    # Even when all evidence gates pass, this codebase intentionally has no live order path.
    live_enabled=False
    return {
        "stage":readiness,
        "live_enabled":live_enabled,
        "eligible_for_human_live_review":readiness=="LIVE_READINESS_REVIEW",
        "gates":gates,
        "failed_gates":[g["id"] for g in failed],
        "policy":asdict(p),
        "note":"readiness checklist only; passing does not enable or place live orders",
    }


def rebalance_portfolio(
    positions: list[dict[str,Any]],
    new_allocations: list[dict[str,Any]],
    kill_switch: dict[str,Any],
    policy: dict[str,Any] | None=None,
) -> dict[str,Any]:
    cfg={
        "watch_reduce_fraction":0.50,
        "high_corr_reduce_fraction":0.25,
        "high_corr_threshold":0.90,
        "replacement_priority_gap":0.15,
    }
    cfg.update(policy or {})
    actions=[]

    for p in positions:
        code=str(p.get("stock_code") or "")
        current_risk=max(0.0,float(p.get("risk_krw") or 0))
        state=str(p.get("ai_state") or "UNKNOWN")
        final_action=str(p.get("final_action") or "")
        current_return=finite(p.get("current_return_pct"))
        stop=abs(finite(p.get("stop_pct")) or 0.0)
        max_corr=finite(p.get("max_positive_corr"))
        priority=finite(p.get("priority_score")) or 0.0
        reasons=[]
        action="HOLD"
        target=current_risk

        if kill_switch.get("state")=="HALT":
            action="EXIT_SHADOW";target=0.0;reasons.append("KILL_SWITCH_HALT")
        elif final_action in ("EXECUTION_BLOCKED","DEMOTE_OR_REWORK"):
            action="EXIT_SHADOW";target=0.0;reasons.append("STRATEGY_EVIDENCE_BLOCKED")
        elif state in ("BLOCKED","IGNORE"):
            action="EXIT_SHADOW";target=0.0;reasons.append("AI_STATE_INVALID")
        elif current_return is not None and stop>0 and current_return<=-stop:
            action="EXIT_SHADOW";target=0.0;reasons.append("STOP_DISTANCE_BREACH")
        elif state=="WATCH" or final_action=="EXECUTION_GATE_PENDING":
            action="REDUCE";target=current_risk*float(cfg["watch_reduce_fraction"])
            reasons.append("EVIDENCE_OR_SIGNAL_WEAKENED")
        elif max_corr is not None and max_corr>=float(cfg["high_corr_threshold"]):
            action="REDUCE";target=current_risk*(1.0-float(cfg["high_corr_reduce_fraction"]))
            reasons.append("CORRELATION_CONCENTRATION")

        actions.append({
            "stock_code":code,"stock_name":p.get("stock_name"),
            "strategy_id":p.get("strategy_id"),"market_theme":p.get("market_theme"),
            "action":action,"current_risk_krw":current_risk,
            "target_risk_krw":max(0.0,target),
            "risk_delta_krw":max(0.0,target)-current_risk,
            "current_return_pct":current_return,"stop_pct":stop or None,
            "priority_score":priority,"reasons":reasons,
            "paper_only":True,
        })

    if kill_switch.get("state")!="HALT":
        for a in new_allocations:
            actions.append({
                "stock_code":a.get("stock_code"),"stock_name":a.get("stock_name"),
                "strategy_id":a.get("strategy_id"),"market_theme":a.get("market_theme"),
                "action":"ADD_SHADOW_REVIEW",
                "current_risk_krw":0.0,
                "target_risk_krw":float(a.get("allocated_risk_krw") or 0),
                "risk_delta_krw":float(a.get("allocated_risk_krw") or 0),
                "priority_score":finite(a.get("priority_score")) or 0.0,
                "reasons":["ALLOCATION_OPTIMIZER_PROPOSAL"],
                "paper_only":True,
            })

    # Replacement review is advisory only. If a new candidate is materially higher priority
    # than the weakest HOLD/REDUCE position, surface the pair but do not mutate anything.
    open_candidates=[x for x in actions if x["action"] in ("HOLD","REDUCE")]
    add_candidates=[x for x in actions if x["action"]=="ADD_SHADOW_REVIEW"]
    replacements=[]
    if open_candidates and add_candidates:
        weakest=min(open_candidates,key=lambda x:x.get("priority_score") or 0)
        strongest=max(add_candidates,key=lambda x:x.get("priority_score") or 0)
        gap=(strongest.get("priority_score") or 0)-(weakest.get("priority_score") or 0)
        if gap>=float(cfg["replacement_priority_gap"]):
            replacements.append({
                "action":"REPLACE_REVIEW",
                "reduce_code":weakest.get("stock_code"),
                "add_code":strongest.get("stock_code"),
                "priority_gap":gap,
                "reason":"NEW_CANDIDATE_MATERIALLY_HIGHER_PRIORITY",
                "paper_only":True,
            })

    summary={
        "hold":sum(1 for x in actions if x["action"]=="HOLD"),
        "reduce":sum(1 for x in actions if x["action"]=="REDUCE"),
        "exit":sum(1 for x in actions if x["action"]=="EXIT_SHADOW"),
        "add_review":sum(1 for x in actions if x["action"]=="ADD_SHADOW_REVIEW"),
        "replacement_review":len(replacements),
        "released_risk_krw":sum(max(0.0,-float(x.get("risk_delta_krw") or 0)) for x in actions),
        "added_risk_krw":sum(max(0.0,float(x.get("risk_delta_krw") or 0)) for x in actions),
    }
    rank={"EXIT_SHADOW":0,"REDUCE":1,"ADD_SHADOW_REVIEW":2,"HOLD":3}
    actions.sort(key=lambda x:(rank.get(x["action"],9),-(abs(float(x.get("risk_delta_krw") or 0))),x.get("stock_code") or ""))
    return {
        "status":"HALT_PLAN" if kill_switch.get("state")=="HALT" else "OK",
        "paper_only":True,
        "actions":actions,
        "replacements":replacements,
        "summary":summary,
        "policy":cfg,
        "note":"rebalance proposals only; no shadow or broker position is automatically changed",
    }
