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
    shares=min(int(entry.get("filled_shares") or 0),int(exit.get("filled_shares") or 0))
    if ep is None or xp is None or shares<=0:
        return {"status":"INCOMPLETE","shares":shares,"gross_return_pct":None,"net_return_pct":None}
    gross=(xp/ep-1.0)*100.0
    entry_cost=float(entry.get("commission_krw") or 0)+float(entry.get("tax_krw") or 0)
    exit_cost=float(exit.get("commission_krw") or 0)+float(exit.get("tax_krw") or 0)
    invested=ep*shares
    pnl=(xp-ep)*shares-entry_cost-exit_cost
    net=(pnl/invested*100.0) if invested>0 else None
    return {
        "status":"COMPLETE",
        "shares":shares,
        "gross_return_pct":gross,
        "net_return_pct":net,
        "gross_pnl_krw":(xp-ep)*shares,
        "net_pnl_krw":pnl,
        "costs_krw":entry_cost+exit_cost,
    }
