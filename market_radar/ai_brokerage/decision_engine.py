from __future__ import annotations

from typing import Any

from .desks import catalyst_desk, flow_desk, market_desk, risk_desk, strategy_desk, technical_desk
from .models import DecisionPacket, DeskVerdict, StrategyMatch
from .strategy_registry import StrategyRegistry


WEIGHTS = {
    "market": 0.16,
    "catalyst": 0.12,
    "flow": 0.20,
    "technical": 0.20,
    "strategy": 0.20,
    "risk": 0.12,
}


class DecisionEngine:
    """Explainable PAPER-first orchestration. This class never places orders."""

    def __init__(self, registry: StrategyRegistry | None = None) -> None:
        self.registry = registry or StrategyRegistry()

    @staticmethod
    def _conviction(desks: list[DeskVerdict]) -> float:
        weighted = 0.0
        total = 0.0
        for d in desks:
            w = WEIGHTS.get(d.desk, 0.0)
            if not w:
                continue
            weighted += (d.score * d.confidence) * w
            total += w
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, 50.0 + (weighted / total) * 50.0))

    @staticmethod
    def _select_strategy(matches: list[StrategyMatch]) -> StrategyMatch | None:
        clean = [m for m in matches if not m.blockers and m.lifecycle in ("PAPER", "ACTIVE")]
        clean.sort(key=lambda m: m.fit_score, reverse=True)
        return clean[0] if clean else None

    def evaluate(self, ctx: dict[str, Any]) -> DecisionPacket:
        md = market_desk(ctx)
        cd = catalyst_desk(ctx)
        fd = flow_desk(ctx)
        td = technical_desk(ctx)
        sd_result = strategy_desk(ctx, self.registry)
        rd = risk_desk(ctx)
        desks = [md, cd, fd, td, sd_result.verdict, rd]

        blockers: list[str] = []
        for d in desks:
            blockers.extend(f"{d.desk}: {b}" for b in d.blockers)

        selected = self._select_strategy(sd_result.matches)
        conviction = self._conviction(desks)

        candidate = ctx.get("candidate") or {}
        try:
            candidate_score = float(candidate.get("score", candidate.get("last_score")) or 0)
        except (TypeError, ValueError):
            candidate_score = 0.0

        reasons = [f"6-desk conviction={conviction:.1f}", f"candidate_score={candidate_score:.0f}"]
        if selected:
            reasons.append(f"strategy={selected.strategy_id} fit={selected.fit_score:.0f}")
        else:
            reasons.append("no fully eligible strategy")

        if blockers:
            state = "BLOCKED"
        elif selected is None:
            state = "WATCH" if conviction >= 45 else "IGNORE"
        elif conviction >= 72 and selected.fit_score >= 72 and candidate_score >= 75:
            state = "PAPER_ENTRY"
        elif conviction >= 62 and selected.fit_score >= 65:
            state = "READY"
        elif conviction >= 45:
            state = "WATCH"
        else:
            state = "IGNORE"

        return DecisionPacket(
            stock_code=str(ctx.get("stock_code") or ""),
            stock_name=ctx.get("stock_name"),
            state=state,
            conviction=conviction,
            selected_strategy=selected,
            desks=desks,
            reasons=reasons,
            blockers=blockers,
            paper_only=True,
        )
