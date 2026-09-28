from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .models import StrategySpec


# The registry intentionally separates "having a slot" from "being validated".
# Only PAPER/ACTIVE strategies are eligible for the decision engine.
# DESIGN entries are placeholders that must earn promotion through prospective tests.
_STRATEGY_ROWS: list[StrategySpec] = [
    StrategySpec("MR-T01", "상승장 주도주 추세 지속", "REGIME_TREND", "PAPER",
                 ("RISING",), ("LEADER_TREND", "BREAKOUT_HOLD"), min_candidate_score=78,
                 min_theme_strength=55, max_hold_minutes=45, tags=("trend","leader")),
    StrategySpec("MR-T02", "횡보장 강세주 상대강도", "REGIME_TREND", "PAPER",
                 ("RANGE_OR_MIXED",), ("LEADER_TREND", "INTACT_PULLBACK"), min_candidate_score=76,
                 min_theme_strength=50, tags=("relative_strength","leader")),
    StrategySpec("MR-T03", "약세장 방어적 상대강도", "REGIME_TREND", "DESIGN",
                 ("FALLING",), ("INTACT_PULLBACK",), min_candidate_score=82, tags=("defensive",)),
    StrategySpec("MR-T04", "대형주 집중 추세", "REGIME_TREND", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND",), min_candidate_score=76,
                 tags=("large_cap","trend")),
    StrategySpec("MR-T05", "전환장 확인 후 추세", "REGIME_TREND", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("BREAKOUT_HOLD",), min_candidate_score=82,
                 tags=("transition","confirmation")),
    StrategySpec("MR-T06", "장중 추세 재개", "REGIME_TREND", "DESIGN",
                 ("RISING",), ("INTACT_PULLBACK",), min_candidate_score=80, tags=("intraday","resume")),

    StrategySpec("MR-B01", "전고점 돌파 확인", "BREAKOUT", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("PREVIOUS_HIGH_APPROACH", "BREAKOUT_HOLD"),
                 min_candidate_score=80, min_theme_strength=50, tags=("breakout","previous_high")),
    StrategySpec("MR-B02", "신고가 돌파", "BREAKOUT", "PAPER",
                 ("RISING",), ("NEW_HIGH", "BREAKOUT_HOLD"), min_candidate_score=82,
                 min_theme_strength=55, tags=("breakout","new_high")),
    StrategySpec("MR-B03", "M수렴 돌파 테스트", "BREAKOUT", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("M_CONTRACTION", "M_BREAKOUT_TEST"),
                 min_candidate_score=78, tags=("mimosa","contraction")),
    StrategySpec("MR-B04", "매물대 흡수 후 돌파", "BREAKOUT", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("SUPPLY_ABSORPTION", "BREAKOUT_HOLD"),
                 min_candidate_score=80, tags=("supply","absorption")),
    StrategySpec("MR-B05", "갭 돌파 유지", "BREAKOUT", "DESIGN", ("RISING",), ("BREAKOUT_HOLD",),
                 min_candidate_score=82, tags=("gap","breakout")),
    StrategySpec("MR-B06", "장초 고점 돌파", "BREAKOUT", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("BREAKOUT_HOLD",), min_candidate_score=84, tags=("open","breakout")),
    StrategySpec("MR-B07", "오전 박스 상단 돌파", "BREAKOUT", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("BREAKOUT_HOLD",), min_candidate_score=80, tags=("box","breakout")),
    StrategySpec("MR-B08", "거래대금 재가속 돌파", "BREAKOUT", "DESIGN", ("RISING",),
                 ("BREAKOUT_HOLD",), min_candidate_score=80, tags=("turnover","acceleration")),
    StrategySpec("MR-B09", "섹터 동반 돌파", "BREAKOUT", "DESIGN", ("RISING",),
                 ("BREAKOUT_HOLD", "NEW_HIGH"), min_candidate_score=78, min_theme_strength=65,
                 tags=("sector","breadth")),
    StrategySpec("MR-B10", "돌파-재테스트 유지", "BREAKOUT", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("INTACT_PULLBACK", "BREAKOUT_HOLD"), min_candidate_score=80, tags=("retest",)),

    StrategySpec("MR-P01", "주도주 첫 눌림", "PULLBACK", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("INTACT_PULLBACK",), min_candidate_score=76,
                 min_theme_strength=55, tags=("pullback","leader")),
    StrategySpec("MR-P02", "돌파 후 눌림 유지", "PULLBACK", "PAPER",
                 ("RISING",), ("BREAKOUT_HOLD", "INTACT_PULLBACK"), min_candidate_score=78,
                 tags=("pullback","post_breakout")),
    StrategySpec("MR-P03", "거래량 수축 눌림", "PULLBACK", "DESIGN", ("RISING",),
                 ("INTACT_PULLBACK", "M_CONTRACTION"), min_candidate_score=78, tags=("volume","contraction")),
    StrategySpec("MR-P04", "VWAP 회복 눌림", "PULLBACK", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("INTACT_PULLBACK",), min_candidate_score=80, tags=("vwap","reclaim")),
    StrategySpec("MR-P05", "전고점 지지 눌림", "PULLBACK", "DESIGN", ("RISING",),
                 ("INTACT_PULLBACK",), min_candidate_score=80, tags=("previous_high","support")),
    StrategySpec("MR-P06", "섹터 강세 동행 눌림", "PULLBACK", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("INTACT_PULLBACK",), min_candidate_score=76, min_theme_strength=65,
                 tags=("sector","pullback")),
    StrategySpec("MR-P07", "장중 2차 파동 눌림", "PULLBACK", "DESIGN", ("RISING",),
                 ("INTACT_PULLBACK",), min_candidate_score=80, tags=("second_leg",)),
    StrategySpec("MR-P08", "매물대 상단 지지", "PULLBACK", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("SUPPLY_ABSORPTION", "INTACT_PULLBACK"), min_candidate_score=80, tags=("supply","support")),

    StrategySpec("MR-F01", "거래대금 Top 재진입", "FLOW", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND", "BREAKOUT_HOLD", "INTACT_PULLBACK"),
                 min_candidate_score=76, tags=("turnover","rank")),
    StrategySpec("MR-F02", "조회순위 급상승 + 거래대금", "FLOW", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND", "M_BREAKOUT_TEST"),
                 min_candidate_score=78, tags=("query_rank","turnover")),
    StrategySpec("MR-F03", "섹터 거래대금 집중", "FLOW", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("LEADER_TREND",), min_candidate_score=76, min_theme_strength=65, tags=("sector_flow",)),
    StrategySpec("MR-F04", "대형주 수급 집중", "FLOW", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("LEADER_TREND",), min_candidate_score=78, tags=("large_cap","flow")),
    StrategySpec("MR-F05", "외인·기관 동반", "FLOW", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("LEADER_TREND", "INTACT_PULLBACK"), min_candidate_score=78, tags=("institution","foreign")),
    StrategySpec("MR-F06", "순환매 초기 포착", "FLOW", "DESIGN", ("RANGE_OR_MIXED",),
                 ("M_CONTRACTION", "M_BREAKOUT_TEST"), min_candidate_score=78, tags=("rotation",)),
    StrategySpec("MR-F07", "분산장 상위 섹터 교체", "FLOW", "DESIGN", ("RANGE_OR_MIXED",),
                 ("LEADER_TREND",), min_candidate_score=80, tags=("rotation","sector")),
    StrategySpec("MR-F08", "거래대금-가격 괴리 회복", "FLOW", "DESIGN", ("RISING", "RANGE_OR_MIXED"),
                 ("INTACT_PULLBACK",), min_candidate_score=82, tags=("divergence","flow")),

    StrategySpec("MR-S01", "주도 섹터 1등주", "SECTOR_ROTATION", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND", "BREAKOUT_HOLD"),
                 min_candidate_score=78, min_theme_strength=65, tags=("sector","leader")),
    StrategySpec("MR-S02", "주도 섹터 2등주 확산", "SECTOR_ROTATION", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("M_BREAKOUT_TEST", "BREAKOUT_HOLD"),
                 min_candidate_score=80, min_theme_strength=70, tags=("sector","breadth")),
    StrategySpec("MR-S03", "테마 신규 형성", "SECTOR_ROTATION", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("M_CONTRACTION", "M_BREAKOUT_TEST"),
                 min_candidate_score=82, min_theme_strength=70, min_material_strength=2,
                 tags=("new_theme","catalyst")),
    StrategySpec("MR-S04", "테마 재점화", "SECTOR_ROTATION", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("INTACT_PULLBACK", "BREAKOUT_HOLD"),
                 min_candidate_score=80, min_theme_strength=65, tags=("theme","reacceleration")),
    StrategySpec("MR-S05", "낙폭과대 섹터 순환", "SECTOR_ROTATION", "DESIGN",
                 ("RANGE_OR_MIXED",), ("M_CONTRACTION",), min_candidate_score=84, tags=("mean_reversion","sector")),
    StrategySpec("MR-S06", "정책 수혜 섹터 확산", "SECTOR_ROTATION", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND",), min_candidate_score=80,
                 min_material_strength=3, tags=("policy","sector")),

    StrategySpec("MR-E01", "신규 공시 직접재료", "EVENT", "PAPER",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND", "M_BREAKOUT_TEST", "BREAKOUT_HOLD"),
                 min_candidate_score=80, min_material_strength=3, tags=("dart","event")),
    StrategySpec("MR-E02", "실적 서프라이즈", "EVENT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("BREAKOUT_HOLD", "INTACT_PULLBACK"),
                 min_candidate_score=82, min_material_strength=3, tags=("earnings","event")),
    StrategySpec("MR-E03", "계약/수주 공시", "EVENT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND", "BREAKOUT_HOLD"),
                 min_candidate_score=82, min_material_strength=3, tags=("contract","dart")),
    StrategySpec("MR-E04", "규제/허가 이벤트", "EVENT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("BREAKOUT_HOLD",), min_candidate_score=84,
                 min_material_strength=3, tags=("regulatory","event")),
    StrategySpec("MR-E05", "복수채널 신규재료 확산", "EVENT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("M_BREAKOUT_TEST", "LEADER_TREND"),
                 min_candidate_score=80, min_material_strength=2, tags=("telegram","spread")),

    StrategySpec("MR-O01", "종가 강도 유지", "OVERNIGHT", "DESIGN",
                 ("RISING",), ("BREAKOUT_HOLD", "NEW_HIGH"), min_candidate_score=84,
                 min_theme_strength=60, max_hold_minutes=900, tags=("close","overnight")),
    StrategySpec("MR-O02", "종가 신고가", "OVERNIGHT", "DESIGN",
                 ("RISING",), ("NEW_HIGH",), min_candidate_score=86, min_theme_strength=65,
                 max_hold_minutes=900, tags=("close","new_high")),
    StrategySpec("MR-O03", "미국장 연동 선반영", "OVERNIGHT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND",), min_candidate_score=86,
                 max_hold_minutes=900, tags=("us_market","overnight")),
    StrategySpec("MR-O04", "공시 후 종가 유지", "OVERNIGHT", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("BREAKOUT_HOLD",), min_candidate_score=86,
                 min_material_strength=3, max_hold_minutes=900, tags=("event","overnight")),

    StrategySpec("MR-L01", "중기 주도주 추세", "PORTFOLIO", "DESIGN",
                 ("RISING",), ("LEADER_TREND", "BREAKOUT_HOLD"), min_candidate_score=85,
                 min_theme_strength=65, max_hold_minutes=43200, tags=("swing","portfolio")),
    StrategySpec("MR-L02", "섹터 리더 포트폴리오", "PORTFOLIO", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("LEADER_TREND",), min_candidate_score=85,
                 min_theme_strength=70, max_hold_minutes=43200, tags=("sector","portfolio")),
    StrategySpec("MR-L03", "실적·추세 결합", "PORTFOLIO", "DESIGN",
                 ("RISING", "RANGE_OR_MIXED"), ("INTACT_PULLBACK", "LEADER_TREND"),
                 min_candidate_score=88, min_material_strength=3, max_hold_minutes=43200,
                 tags=("earnings","portfolio")),
]

assert len(_STRATEGY_ROWS) == 50, f"expected 50 strategies, got {len(_STRATEGY_ROWS)}"


class StrategyRegistry:
    def __init__(self, specs: Iterable[StrategySpec] | None = None) -> None:
        rows = list(specs or _STRATEGY_ROWS)
        self._by_id = {s.strategy_id: s for s in rows}
        if len(self._by_id) != len(rows):
            raise ValueError("duplicate strategy_id")

    def all(self) -> list[StrategySpec]:
        return list(self._by_id.values())

    def get(self, strategy_id: str) -> StrategySpec | None:
        return self._by_id.get(strategy_id)

    def eligible(self) -> list[StrategySpec]:
        return [s for s in self._by_id.values() if s.lifecycle in ("PAPER", "ACTIVE")]

    def by_family(self, family: str) -> list[StrategySpec]:
        return [s for s in self._by_id.values() if s.family == family]

    def lifecycle_counts(self) -> dict[str, int]:
        out = {"DESIGN": 0, "PAPER": 0, "ACTIVE": 0, "DISABLED": 0}
        for s in self._by_id.values():
            out[s.lifecycle] += 1
        return out

    def with_lifecycle(self, strategy_id: str, lifecycle: str) -> "StrategyRegistry":
        current = self._by_id.get(strategy_id)
        if current is None:
            raise KeyError(strategy_id)
        if lifecycle not in ("DESIGN", "PAPER", "ACTIVE", "DISABLED"):
            raise ValueError(lifecycle)
        rows = [replace(s, lifecycle=lifecycle) if s.strategy_id == strategy_id else s for s in self.all()]
        return StrategyRegistry(rows)
