from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _age_seconds(value: Any) -> float:
    if not value:
        return 9999.0
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return 9999.0


def _today_paper_return(paper_lab: dict[str, Any]) -> float:
    today = datetime.now().astimezone().date()
    total = 0.0
    for trade in paper_lab.get("recent_closed") or []:
        try:
            closed = datetime.fromisoformat(str(trade.get("closed_at")))
            if closed.astimezone().date() != today:
                continue
            value = trade.get("return_pct")
            if value is not None:
                total += float(value)
        except Exception:
            continue
    return total


def context_from_dashboard_row(
    row: dict[str, Any],
    regime: dict[str, Any] | None,
    regime_metrics: dict[str, Any] | None,
    theme_strength: dict[str, float] | None,
    paper_lab: dict[str, Any] | None,
    max_open: int = 5,
) -> dict[str, Any]:
    regime = regime or {}
    metrics = regime_metrics or {}
    paper_lab = paper_lab or {}
    theme_strength = theme_strength or {}

    code = str(row.get("code") or "")
    open_rows = paper_lab.get("open") or []
    open_codes = {str(x.get("code") or "") for x in open_rows}
    market_theme = row.get("market_theme") or row.get("official_sector") or "미분류"
    material = row.get("material_digest") or {}
    chart = row.get("mimosa") or {}
    candidate = row.get("candidate") or {}

    return {
        "stock_code": code,
        "stock_name": row.get("name"),
        "regime": {
            "trend": metrics.get("trend") or metrics.get("candidate_trend_state") or "UNKNOWN",
            "flow": metrics.get("flow") or metrics.get("candidate_flow_state") or "UNKNOWN",
            "sentiment": metrics.get("sentiment") or metrics.get("candidate_sentiment_state") or "UNKNOWN",
            "data_freshness_sec": metrics.get("freshness_sec", metrics.get("data_freshness_sec", 9999)),
            "confidence": metrics.get("confidence"),
            "stable_label": regime.get("stable_label"),
        },
        "candidate": {
            "score": candidate.get("score", candidate.get("last_score", 0)),
            "rank": row.get("rank"),
            "rank_change": row.get("rank_change"),
            "trade_value_krw": row.get("trade_value_krw"),
            "recent_turnover_krw": row.get("recent_turnover_krw"),
            "primary_type": candidate.get("primary_type"),
        },
        "material": {
            "material_strength": material.get("material_strength", 0),
            "identity_quality": material.get("identity_quality") or material.get("best_identity_quality"),
            "status": (row.get("catalyst") or {}).get("status"),
            "summary": material.get("summary") or material.get("assessment"),
        },
        "theme": {
            "name": market_theme,
            "theme_strength": theme_strength.get(market_theme),
        },
        "chart": {
            "state": chart.get("state") or "UNKNOWN",
            "state_ko": chart.get("state_ko"),
            "minute_trend": chart.get("minute_trend"),
            "top_warning": row.get("reversal_signal") or {},
        },
        "top_warning": row.get("reversal_signal") or {},
        "quote": {
            "exchange_at": row.get("quote_exchange_at"),
            "freshness_sec": _age_seconds(row.get("quote_exchange_at")),
        },
        "risk": {
            "open_positions": len(open_rows),
            "max_open": max_open,
            "already_open": code in open_codes,
            "daily_realized_pct": _today_paper_return(paper_lab),
            "max_daily_loss_pct": 2.0,
            "paper_mode": True,
        },
    }
