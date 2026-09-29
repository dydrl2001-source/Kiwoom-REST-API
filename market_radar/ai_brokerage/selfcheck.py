from __future__ import annotations

from .decision_engine import DecisionEngine
from .strategy_registry import StrategyRegistry


def sample_context() -> dict:
    return {
        "stock_code": "005930",
        "stock_name": "샘플",
        "regime": {
            "trend": "RISING",
            "flow": "LEADER_CONCENTRATED",
            "sentiment": "STRONG",
            "data_freshness_sec": 20,
            "confidence": 0.8,
        },
        "candidate": {
            "score": 86,
            "rank": 3,
            "rank_change": 4,
            "trade_value_krw": 100_000_000_000,
            "recent_turnover_krw": 10_000_000_000,
        },
        "material": {
            "material_strength": 3,
            "identity_quality": "VERIFIED",
            "status": "MULTI_CHANNEL",
        },
        "theme": {"theme_strength": 75},
        "chart": {"state": "BREAKOUT_HOLD", "minute_trend": "UP"},
        "quote": {"freshness_sec": 15},
        "risk": {
            "open_positions": 1,
            "max_open": 5,
            "daily_realized_pct": 0.3,
            "max_daily_loss_pct": 2.0,
            "already_open": False,
            "paper_mode": True,
        },
    }


def run() -> dict:
    registry = StrategyRegistry()
    assert len(registry.all()) == 50
    assert registry.lifecycle_counts()["PAPER"] > 0
    packet = DecisionEngine(registry).evaluate(sample_context())
    data = packet.to_dict()
    assert data["paper_only"] is True
    assert len(data["desks"]) == 6
    assert data["state"] in {"WATCH", "READY", "PAPER_ENTRY", "BLOCKED", "IGNORE"}
    assert data["selected_strategy"] is not None
    return data


if __name__ == "__main__":
    print(run())
