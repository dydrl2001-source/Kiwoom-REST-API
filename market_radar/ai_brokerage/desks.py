from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import DeskVerdict, StrategyMatch, StrategySpec
from .strategy_registry import StrategyRegistry


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _present_count(*values: Any) -> int:
    return sum(v not in (None, "", "UNKNOWN") for v in values)


def market_desk(ctx: dict[str, Any]) -> DeskVerdict:
    r = ctx.get("regime") or {}
    trend = r.get("trend") or r.get("candidate_trend_state") or "UNKNOWN"
    flow = r.get("flow") or r.get("candidate_flow_state") or "UNKNOWN"
    sentiment = r.get("sentiment") or r.get("candidate_sentiment_state") or "UNKNOWN"
    freshness = _num(r.get("data_freshness_sec"), 9999)
    reasons: list[str] = []
    blockers: list[str] = []

    score = {
        "RISING": 0.35, "RANGE_OR_MIXED": 0.08, "FALLING": -0.35, "UNKNOWN": -0.08,
    }.get(trend, 0.0)
    score += {
        "LEADER_CONCENTRATED": 0.22, "LARGE_CAP_CONCENTRATED": 0.12,
        "BROAD_DISTRIBUTED": 0.04, "ROTATIONAL_DISTRIBUTED": 0.02,
        "TRANSITION_OR_MIXED": -0.05, "UNKNOWN": -0.05,
    }.get(flow, 0.0)
    score += {
        "STRONG": 0.22, "NORMAL": 0.06, "WEAK": -0.28, "UNKNOWN": -0.06,
    }.get(sentiment, 0.0)

    reasons += [f"trend={trend}", f"flow={flow}", f"sentiment={sentiment}"]
    if freshness > 180:
        blockers.append(f"market data stale: {int(freshness)}s")
        score -= 0.35
    elif freshness > 120:
        reasons.append(f"market data aging: {int(freshness)}s")
        score -= 0.12
    else:
        reasons.append(f"market data fresh: {int(freshness)}s")

    observed = _present_count(trend, flow, sentiment)
    confidence = max(0.2, min(1.0, observed / 3.0))
    upstream_conf = r.get("confidence")
    if upstream_conf is not None:
        confidence = (confidence + max(0.0, min(1.0, _num(upstream_conf)))) / 2

    return DeskVerdict("market", score, confidence, reasons, blockers, {
        "trend": trend, "flow": flow, "sentiment": sentiment, "freshness_sec": freshness,
    })


def catalyst_desk(ctx: dict[str, Any]) -> DeskVerdict:
    m = ctx.get("material") or ctx.get("catalyst") or {}
    strength = int(_num(m.get("material_strength"), 0))
    identity = m.get("identity_quality") or m.get("best_identity_quality") or "UNVERIFIED"
    status = m.get("status") or "UNKNOWN"
    score = {0: -0.04, 1: 0.04, 2: 0.22, 3: 0.46, 4: 0.58}.get(strength, 0.58 if strength > 4 else -0.04)
    reasons = [f"material_strength={strength}", f"identity={identity}", f"status={status}"]
    blockers: list[str] = []

    if identity in ("ENTITY_CONFLICT", "MISSING_NAME"):
        blockers.append(f"unusable catalyst identity: {identity}")
        score = min(score, -0.35)
    elif identity in ("VERIFIED", "CONTEXT_VERIFIED"):
        score += 0.12
    elif identity == "NAME_MATCH":
        score -= 0.05

    if status in ("SPREADING", "MULTI_CHANNEL"):
        score += 0.08
    confidence = min(1.0, 0.25 + strength * 0.16 + (0.2 if identity in ("VERIFIED", "CONTEXT_VERIFIED") else 0.0))
    return DeskVerdict("catalyst", score, confidence, reasons, blockers, {
        "material_strength": strength, "identity_quality": identity, "status": status,
        "summary": m.get("summary") or m.get("assessment"),
    })


def flow_desk(ctx: dict[str, Any]) -> DeskVerdict:
    c = ctx.get("candidate") or {}
    theme = ctx.get("theme") or {}
    candidate_score = _num(c.get("score", c.get("last_score")), 0)
    rank = c.get("rank")
    rank_change = _num(c.get("rank_change"), 0)
    theme_strength = _num(theme.get("strength", theme.get("theme_strength")), 0)
    recent_turnover = c.get("recent_turnover_krw")
    trade_value = c.get("trade_value_krw")

    score = 0.0
    reasons: list[str] = []
    if candidate_score:
        score += max(-0.3, min(0.55, (candidate_score - 55.0) / 70.0))
        reasons.append(f"candidate_score={candidate_score:.0f}")
    else:
        reasons.append("candidate score missing")
        score -= 0.12

    if rank is not None:
        r = int(_num(rank, 99))
        score += 0.18 if r <= 5 else 0.10 if r <= 12 else 0.03 if r <= 20 else -0.04
        reasons.append(f"query_rank={r}")
    if rank_change > 0:
        score += min(0.12, rank_change / 100.0)
        reasons.append(f"rank improving +{rank_change:g}")
    elif rank_change < 0:
        score -= min(0.10, abs(rank_change) / 100.0)
        reasons.append(f"rank weakening {rank_change:g}")

    if theme_strength:
        score += max(-0.08, min(0.20, (theme_strength - 45.0) / 180.0))
        reasons.append(f"theme_strength={theme_strength:.0f}")

    if recent_turnover is not None:
        score += 0.08
        reasons.append("recent SOR turnover observed")
    elif trade_value is not None:
        score += 0.03
        reasons.append("cumulative trading value observed")
    else:
        score -= 0.08
        reasons.append("money-flow value missing")

    available = _present_count(candidate_score if candidate_score else None, rank, theme_strength if theme_strength else None,
                               recent_turnover if recent_turnover is not None else trade_value)
    confidence = max(0.2, min(1.0, available / 4.0))
    return DeskVerdict("flow", score, confidence, reasons, [], {
        "candidate_score": candidate_score or None, "rank": rank, "rank_change": rank_change,
        "theme_strength": theme_strength or None, "recent_turnover_krw": recent_turnover,
        "trade_value_krw": trade_value,
    })


def technical_desk(ctx: dict[str, Any]) -> DeskVerdict:
    chart = ctx.get("chart") or {}
    state = chart.get("state") or chart.get("chart_state") or "UNKNOWN"
    minute_trend = chart.get("minute_trend") or "UNKNOWN"
    top_warning = ctx.get("top_warning") or chart.get("top_warning") or {}
    warning_kind = top_warning.get("kind")
    warning_score = int(_num(top_warning.get("score"), 0))

    state_scores = {
        "LEADER_TREND": 0.34, "INTACT_PULLBACK": 0.30, "M_CONTRACTION": 0.20,
        "M_BREAKOUT_TEST": 0.30, "PREVIOUS_HIGH_APPROACH": 0.20, "SUPPLY_ZONE_TEST": 0.04,
        "SUPPLY_ABSORPTION": 0.30, "NEW_HIGH": 0.34, "BREAKOUT_HOLD": 0.38,
        "BREAKOUT_FAIL": -0.62, "TREND_DAMAGE": -0.70, "UNKNOWN": -0.08,
    }
    score = state_scores.get(state, 0.0)
    reasons = [f"chart_state={state}", f"minute_trend={minute_trend}"]
    blockers: list[str] = []

    if state in ("BREAKOUT_FAIL", "TREND_DAMAGE"):
        blockers.append(f"blocked chart state: {state}")
    if warning_kind == "TOP_WARNING" and warning_score >= 70:
        blockers.append(f"top warning score={warning_score}")
        score -= 0.25
    elif warning_kind:
        reasons.append(f"{warning_kind}={warning_score}")

    if minute_trend in ("UP", "RISING", "ASCENDING"):
        score += 0.08
    elif minute_trend in ("DOWN", "FALLING", "DESCENDING"):
        score -= 0.12

    confidence = 0.82 if state != "UNKNOWN" else 0.35
    return DeskVerdict("technical", score, confidence, reasons, blockers, {
        "state": state, "minute_trend": minute_trend, "top_warning": top_warning,
    })


def _fit_strategy(spec: StrategySpec, ctx: dict[str, Any]) -> StrategyMatch:
    r = ctx.get("regime") or {}
    c = ctx.get("candidate") or {}
    m = ctx.get("material") or ctx.get("catalyst") or {}
    theme = ctx.get("theme") or {}
    chart = ctx.get("chart") or {}

    trend = r.get("trend") or r.get("candidate_trend_state") or "UNKNOWN"
    chart_state = chart.get("state") or chart.get("chart_state") or "UNKNOWN"
    candidate_score = int(_num(c.get("score", c.get("last_score")), 0))
    material_strength = int(_num(m.get("material_strength"), 0))
    theme_strength = int(_num(theme.get("strength", theme.get("theme_strength")), 0))

    score = 50.0
    reasons: list[str] = []
    blockers: list[str] = []

    if spec.required_regimes:
        if trend in spec.required_regimes:
            score += 12
            reasons.append(f"regime match {trend}")
        else:
            score -= 22
            blockers.append(f"regime {trend} not in {','.join(spec.required_regimes)}")

    if chart_state in spec.blocked_chart_states:
        score -= 50
        blockers.append(f"chart blocked {chart_state}")
    elif spec.preferred_chart_states:
        if chart_state in spec.preferred_chart_states:
            score += 18
            reasons.append(f"chart match {chart_state}")
        elif chart_state != "UNKNOWN":
            score -= 8
            reasons.append(f"chart not preferred {chart_state}")

    if candidate_score >= spec.min_candidate_score:
        score += min(12, (candidate_score - spec.min_candidate_score) * 0.6 + 4)
        reasons.append(f"candidate {candidate_score}>={spec.min_candidate_score}")
    else:
        score -= min(30, (spec.min_candidate_score - candidate_score) * 1.5)
        blockers.append(f"candidate {candidate_score}<{spec.min_candidate_score}")

    if spec.min_material_strength:
        if material_strength >= spec.min_material_strength:
            score += 8
            reasons.append(f"material {material_strength}>={spec.min_material_strength}")
        else:
            score -= 18
            blockers.append(f"material {material_strength}<{spec.min_material_strength}")

    if spec.min_theme_strength:
        if theme_strength >= spec.min_theme_strength:
            score += 8
            reasons.append(f"theme {theme_strength}>={spec.min_theme_strength}")
        else:
            score -= 14
            blockers.append(f"theme {theme_strength}<{spec.min_theme_strength}")

    return StrategyMatch(spec.strategy_id, spec.name, spec.family,
                         max(0.0, min(100.0, score)), spec.lifecycle, reasons, blockers)


@dataclass
class StrategyDeskResult:
    verdict: DeskVerdict
    matches: list[StrategyMatch]


def strategy_desk(ctx: dict[str, Any], registry: StrategyRegistry) -> StrategyDeskResult:
    matches = [_fit_strategy(s, ctx) for s in registry.eligible()]
    matches.sort(key=lambda m: (len(m.blockers) == 0, m.fit_score), reverse=True)
    best = matches[0] if matches else None
    reasons: list[str] = []
    blockers: list[str] = []

    if best:
        reasons.append(f"best={best.strategy_id} {best.name} fit={best.fit_score:.0f}")
    else:
        blockers.append("no PAPER/ACTIVE strategies registered")

    clean = [m for m in matches if not m.blockers]
    if clean:
        best_clean = clean[0]
        score = (best_clean.fit_score - 50.0) / 50.0
        confidence = min(1.0, 0.45 + best_clean.fit_score / 200.0)
        reasons.insert(0, f"eligible={best_clean.strategy_id} fit={best_clean.fit_score:.0f}")
    else:
        score = -0.25
        confidence = 0.55 if matches else 0.25
        blockers.append("no strategy satisfies all current gates")

    return StrategyDeskResult(
        DeskVerdict("strategy", score, confidence, reasons, blockers,
                    {"matches": [m.to_dict() for m in matches[:5]]}),
        matches,
    )


def risk_desk(ctx: dict[str, Any]) -> DeskVerdict:
    risk = ctx.get("risk") or {}
    quote = ctx.get("quote") or {}
    blockers: list[str] = []
    reasons: list[str] = []
    score = 0.15

    open_positions = int(_num(risk.get("open_positions"), 0))
    max_open = int(_num(risk.get("max_open"), 5))
    if open_positions >= max_open:
        blockers.append(f"open positions {open_positions}/{max_open}")
        score -= 0.65
    else:
        reasons.append(f"open positions {open_positions}/{max_open}")

    if bool(risk.get("already_open")):
        blockers.append("position already open")
        score -= 0.70

    daily_return = _num(risk.get("daily_realized_pct"), 0.0)
    max_daily_loss = abs(_num(risk.get("max_daily_loss_pct"), 2.0))
    if daily_return <= -max_daily_loss:
        blockers.append(f"daily loss guard {daily_return:.2f}% <= -{max_daily_loss:.2f}%")
        score -= 0.85
    else:
        reasons.append(f"daily realized={daily_return:.2f}%")

    quote_freshness = _num(quote.get("freshness_sec"), 9999)
    if quote_freshness > 120:
        blockers.append(f"quote stale: {int(quote_freshness)}s")
        score -= 0.55
    else:
        reasons.append(f"quote fresh: {int(quote_freshness)}s")

    if risk.get("paper_mode", True) is not True:
        blockers.append("v1 requires paper_mode=true")
        score -= 1.0
    else:
        reasons.append("paper mode enforced")

    confidence = 0.95 if risk else 0.55
    return DeskVerdict("risk", score, confidence, reasons, blockers, {
        "open_positions": open_positions, "max_open": max_open,
        "daily_realized_pct": daily_return, "max_daily_loss_pct": max_daily_loss,
        "quote_freshness_sec": quote_freshness, "paper_mode": risk.get("paper_mode", True),
    })
