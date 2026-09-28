from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any, Literal

Side = Literal["BUY","SELL"]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,float(v)))


def finite(v: Any) -> float | None:
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


@dataclass(frozen=True)
class SizingPolicy:
    account_equity_krw: float = 100_000_000
    risk_per_trade_pct: float = 0.50
    max_position_pct: float = 10.0
    min_stop_pct: float = 1.0
    max_stop_pct: float = 5.0
    volatility_stop_multiple: float = 4.0

    def size(self, price_krw: float, volatility_bps: float | None) -> dict[str,Any]:
        price=finite(price_krw)
        if price is None or price<=0:
            return {"shares":0,"requested_notional_krw":0.0,"stop_pct":None,"risk_budget_krw":0.0}
        vol=finite(volatility_bps)
        stop_pct=self.min_stop_pct if vol is None else clamp((vol/100.0)*self.volatility_stop_multiple,
                                                             self.min_stop_pct,self.max_stop_pct)
        risk_budget=self.account_equity_krw*(self.risk_per_trade_pct/100.0)
        risk_notional=risk_budget/(stop_pct/100.0)
        cap_notional=self.account_equity_krw*(self.max_position_pct/100.0)
        target=min(risk_notional,cap_notional)
        shares=max(0,int(target//price))
        return {
            "shares":shares,
            "requested_notional_krw":shares*price,
            "stop_pct":stop_pct,
            "risk_budget_krw":risk_budget,
            "max_position_notional_krw":cap_notional,
        }


@dataclass(frozen=True)
class FillPolicy:
    max_participation_pct: float = 2.0
    min_slippage_bps: float = 3.0
    max_slippage_bps: float = 120.0
    volatility_weight: float = 0.20
    participation_impact_bps: float = 80.0
    commission_bps: float = 0.0
    sell_tax_bps: float = 0.0


def estimate_fill(
    side: Side,
    reference_price_krw: float,
    requested_shares: int,
    recent_turnover_krw: float | None,
    volatility_bps: float | None,
    policy: FillPolicy | None=None,
) -> dict[str,Any]:
    p=policy or FillPolicy()
    ref=finite(reference_price_krw)
    shares=max(0,int(requested_shares or 0))
    turnover=finite(recent_turnover_krw)
    vol=finite(volatility_bps)
    if ref is None or ref<=0 or shares<=0:
        return {"status":"INVALID_REQUEST","filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                "slippage_bps":None,"model_quality":"INVALID"}

    requested_notional=ref*shares
    if turnover is None or turnover<=0:
        return {
            "status":"NO_LIQUIDITY_EVIDENCE","filled_shares":0,"fill_ratio":0.0,
            "fill_price_krw":None,"slippage_bps":None,
            "requested_shares":shares,"requested_notional_krw":requested_notional,
            "model_quality":"NO_RECENT_TURNOVER",
        }

    participation_cap=max(0.0,p.max_participation_pct/100.0)
    max_fill_notional=turnover*participation_cap
    filled_shares=min(shares,max(0,int(max_fill_notional//ref)))
    if filled_shares<=0:
        return {
            "status":"PARTICIPATION_CAP_REJECT","filled_shares":0,"fill_ratio":0.0,
            "fill_price_krw":None,"slippage_bps":None,
            "requested_shares":shares,"requested_notional_krw":requested_notional,
            "available_notional_krw":max_fill_notional,
            "model_quality":"TURNOVER_CAP",
        }

    filled_notional=ref*filled_shares
    participation=filled_notional/turnover
    vol_used=vol if vol is not None else 20.0
    slip=p.min_slippage_bps + p.volatility_weight*vol_used + p.participation_impact_bps*math.sqrt(max(0.0,participation))
    slip=clamp(slip,p.min_slippage_bps,p.max_slippage_bps)
    direction=1.0 if side=="BUY" else -1.0
    fill_price=ref*(1.0+direction*slip/10_000.0)
    executed_notional=filled_shares*fill_price
    commission=executed_notional*(p.commission_bps/10_000.0)
    tax=executed_notional*(p.sell_tax_bps/10_000.0) if side=="SELL" else 0.0
    return {
        "status":"FILLED" if filled_shares==shares else "PARTIAL",
        "requested_shares":shares,
        "filled_shares":filled_shares,
        "fill_ratio":filled_shares/shares,
        "reference_price_krw":ref,
        "fill_price_krw":fill_price,
        "requested_notional_krw":requested_notional,
        "filled_notional_krw":filled_shares*fill_price,
        "available_notional_krw":max_fill_notional,
        "recent_turnover_krw":turnover,
        "participation_pct":participation*100.0,
        "volatility_bps":vol,
        "volatility_bps_used":vol_used,
        "slippage_bps":slip,
        "commission_krw":commission,
        "tax_krw":tax,
        "model_quality":"OBSERVED_VOL" if vol is not None else "VOL_FALLBACK",
        "policy":asdict(p),
    }


def round_trip_result(entry: dict[str,Any], exit: dict[str,Any]) -> dict[str,Any]:
    ep=finite(entry.get("fill_price_krw")); xp=finite(exit.get("fill_price_krw"))
    entry_shares=max(0,int(entry.get("filled_shares") or 0))
    exit_shares=max(0,int(exit.get("filled_shares") or 0))
    shares=min(entry_shares,exit_shares)
    if ep is None or xp is None or shares<=0:
        return {"status":"INCOMPLETE","shares":shares,"gross_return_pct":None,"net_return_pct":None}
    gross=(xp/ep-1.0)*100.0
    raw_entry_cost=float(entry.get("commission_krw") or 0)+float(entry.get("tax_krw") or 0)
    raw_exit_cost=float(exit.get("commission_krw") or 0)+float(exit.get("tax_krw") or 0)
    entry_cost=raw_entry_cost*(shares/entry_shares) if entry_shares>0 else 0.0
    exit_cost=raw_exit_cost*(shares/exit_shares) if exit_shares>0 else 0.0
    invested=ep*shares
    pnl=(xp-ep)*shares-entry_cost-exit_cost
    net=(pnl/invested*100.0) if invested>0 else None
    return {
        "status":"COMPLETE",
        "shares":shares,
        "entry_filled_shares":entry_shares,
        "exit_filled_shares":exit_shares,
        "gross_return_pct":gross,
        "net_return_pct":net,
        "gross_pnl_krw":(xp-ep)*shares,
        "net_pnl_krw":pnl,
        "costs_krw":entry_cost+exit_cost,
    }


@dataclass(frozen=True)
class BookPolicy:
    displayed_liquidity_haircut: float = 0.50
    max_levels: int = 10
    max_spread_bps: float = 120.0
    commission_bps: float = 0.0
    sell_tax_bps: float = 0.0


def estimate_book_fill(
    side: Side,
    requested_shares: int,
    book: dict[str,Any],
    policy: BookPolicy | None=None,
) -> dict[str,Any]:
    p=policy or BookPolicy()
    shares=max(0,int(requested_shares or 0))
    asks=list(book.get("asks") or [])
    bids=list(book.get("bids") or [])
    levels=asks if side=="BUY" else bids
    levels=levels[:max(1,int(p.max_levels))]
    best_ask=finite(book.get("best_ask_krw"))
    best_bid=finite(book.get("best_bid_krw"))
    if shares<=0:
        return {"status":"INVALID_REQUEST","filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                "implementation_shortfall_bps":None,"model_quality":"BOOK_INVALID"}
    if best_ask is None or best_bid is None or best_ask<=0 or best_bid<=0 or best_ask<best_bid:
        return {"status":"INVALID_BOOK","filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                "implementation_shortfall_bps":None,"model_quality":"BOOK_INVALID"}
    mid=(best_ask+best_bid)/2.0
    spread_bps=(best_ask-best_bid)/mid*10_000.0 if mid>0 else None
    if spread_bps is not None and spread_bps>p.max_spread_bps:
        return {"status":"SPREAD_TOO_WIDE","filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                "arrival_mid_krw":mid,"spread_bps":spread_bps,
                "implementation_shortfall_bps":None,"model_quality":"BOOK_SPREAD_BLOCK"}
    remaining=shares
    fills=[]
    haircut=clamp(p.displayed_liquidity_haircut,0.0,1.0)
    for level in levels:
        price=finite(level.get("price_krw"))
        raw_qty=max(0,int(level.get("qty") or 0))
        available=max(0,int(math.floor(raw_qty*haircut)))
        if price is None or price<=0 or available<=0:
            continue
        take=min(remaining,available)
        if take<=0:
            continue
        fills.append({"level":int(level.get("level") or 0),"price_krw":price,
                      "displayed_qty":raw_qty,"usable_qty":available,"filled_qty":take})
        remaining-=take
        if remaining<=0:
            break
    filled=shares-remaining
    if filled<=0:
        return {"status":"NO_BOOK_LIQUIDITY","requested_shares":shares,"filled_shares":0,
                "fill_ratio":0.0,"fill_price_krw":None,"arrival_mid_krw":mid,
                "spread_bps":spread_bps,"implementation_shortfall_bps":None,
                "model_quality":"BOOK_DEPTH_ZERO","fills":[]}
    notional=sum(x["price_krw"]*x["filled_qty"] for x in fills)
    vwap=notional/filled
    direction=1.0 if side=="BUY" else -1.0
    shortfall=direction*(vwap/mid-1.0)*10_000.0
    best=best_ask if side=="BUY" else best_bid
    depth_slip=direction*(vwap/best-1.0)*10_000.0 if best and best>0 else None
    commission=notional*(p.commission_bps/10_000.0)
    tax=notional*(p.sell_tax_bps/10_000.0) if side=="SELL" else 0.0
    return {
        "status":"FILLED" if filled==shares else "PARTIAL",
        "requested_shares":shares,"filled_shares":filled,"remaining_shares":remaining,
        "fill_ratio":filled/shares,"fill_price_krw":vwap,"filled_notional_krw":notional,
        "arrival_mid_krw":mid,"best_ask_krw":best_ask,"best_bid_krw":best_bid,
        "spread_bps":spread_bps,"implementation_shortfall_bps":shortfall,
        "depth_slippage_bps":depth_slip,"levels_used":len(fills),"fills":fills,
        "commission_krw":commission,"tax_krw":tax,
        "model_quality":"ORDER_BOOK_10L","policy":asdict(p),
    }


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    account_equity_krw: float = 100_000_000
    max_total_risk_pct: float = 2.0
    max_theme_risk_pct: float = 0.8
    max_family_risk_pct: float = 1.2
    max_open_positions: int = 5


def portfolio_risk_budget(
    proposed_risk_krw: float,
    market_theme: str | None,
    strategy_family: str | None,
    open_positions: list[dict[str,Any]],
    policy: PortfolioRiskPolicy | None=None,
) -> dict[str,Any]:
    p=policy or PortfolioRiskPolicy()
    proposed=max(0.0,float(proposed_risk_krw or 0))
    theme=str(market_theme or "UNKNOWN")
    family=str(strategy_family or "UNKNOWN")
    open_count=len(open_positions)
    total=sum(max(0.0,float(x.get("risk_krw") or 0)) for x in open_positions)
    theme_used=sum(max(0.0,float(x.get("risk_krw") or 0)) for x in open_positions
                   if str(x.get("market_theme") or "UNKNOWN")==theme)
    family_used=sum(max(0.0,float(x.get("risk_krw") or 0)) for x in open_positions
                    if str(x.get("strategy_family") or "UNKNOWN")==family)
    total_cap=p.account_equity_krw*p.max_total_risk_pct/100.0
    theme_cap=p.account_equity_krw*p.max_theme_risk_pct/100.0
    family_cap=p.account_equity_krw*p.max_family_risk_pct/100.0
    capacities={
        "total":max(0.0,total_cap-total),
        "theme":max(0.0,theme_cap-theme_used),
        "family":max(0.0,family_cap-family_used),
    }
    allowed=min([proposed,*capacities.values()])
    blockers=[]
    if open_count>=p.max_open_positions:blockers.append("MAX_OPEN_POSITIONS")
    if capacities["total"]<=0:blockers.append("TOTAL_RISK_CAP")
    if capacities["theme"]<=0:blockers.append("THEME_RISK_CAP")
    if capacities["family"]<=0:blockers.append("FAMILY_RISK_CAP")
    if blockers:allowed=0.0
    scale=(allowed/proposed) if proposed>0 else 0.0
    return {
        "allowed":allowed>0 and not blockers,
        "proposed_risk_krw":proposed,"allowed_risk_krw":allowed,
        "risk_scale":clamp(scale,0.0,1.0),
        "open_positions":open_count,"market_theme":theme,"strategy_family":family,
        "used":{"total":total,"theme":theme_used,"family":family_used},
        "caps":{"total":total_cap,"theme":theme_cap,"family":family_cap},
        "remaining":capacities,"blockers":blockers,"policy":asdict(p),
    }


def implementation_shortfall_summary(entry: dict[str,Any], exit: dict[str,Any] | None=None) -> dict[str,Any]:
    entry_is=finite(entry.get("implementation_shortfall_bps"))
    exit_is=finite((exit or {}).get("implementation_shortfall_bps"))
    total=(entry_is or 0)+(exit_is or 0) if entry_is is not None or exit_is is not None else None
    return {
        "entry_is_bps":entry_is,
        "exit_is_bps":exit_is,
        "round_trip_is_bps":total,
        "entry_spread_bps":finite(entry.get("spread_bps")),
        "exit_spread_bps":finite((exit or {}).get("spread_bps")),
        "entry_depth_slippage_bps":finite(entry.get("depth_slippage_bps")),
        "exit_depth_slippage_bps":finite((exit or {}).get("depth_slippage_bps")),
    }
