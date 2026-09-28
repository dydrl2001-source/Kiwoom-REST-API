from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

DeskName = Literal["market", "catalyst", "flow", "technical", "strategy", "risk"]
DecisionState = Literal["IGNORE", "WATCH", "READY", "PAPER_ENTRY", "BLOCKED"]
Lifecycle = Literal["DESIGN", "PAPER", "ACTIVE", "DISABLED"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(v: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(v)))


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    family: str
    lifecycle: Lifecycle = "DESIGN"
    required_regimes: tuple[str, ...] = ()
    preferred_chart_states: tuple[str, ...] = ()
    blocked_chart_states: tuple[str, ...] = ("TREND_DAMAGE", "BREAKOUT_FAIL")
    min_candidate_score: int = 70
    min_material_strength: int = 0
    min_theme_strength: int = 0
    max_hold_minutes: int = 30
    tags: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("required_regimes", "preferred_chart_states", "blocked_chart_states", "tags"):
            out[key] = list(out[key])
        return out


@dataclass
class DeskVerdict:
    desk: DeskName
    score: float
    confidence: float
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = _clamp(self.score)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyMatch:
    strategy_id: str
    name: str
    family: str
    fit_score: float
    lifecycle: Lifecycle
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.fit_score = max(0.0, min(100.0, float(self.fit_score)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionPacket:
    stock_code: str
    stock_name: str | None
    state: DecisionState
    conviction: float
    selected_strategy: StrategyMatch | None
    desks: list[DeskVerdict]
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    paper_only: bool = True
    generated_at: datetime = field(default_factory=_utc_now)
    version: str = "ai-brokerage-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "state": self.state,
            "conviction": round(max(0.0, min(100.0, float(self.conviction))), 1),
            "selected_strategy": self.selected_strategy.to_dict() if self.selected_strategy else None,
            "desks": [d.to_dict() for d in self.desks],
            "reasons": self.reasons,
            "blockers": self.blockers,
            "paper_only": self.paper_only,
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
        }
