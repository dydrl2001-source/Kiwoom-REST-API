"""Market OS multi-axis rule engine.

This module converts trading-study principles into independent observation axes.
It deliberately does NOT emit a single recommendation/probability score and does
not place orders. Numeric weights are local operational heuristics that require
journal/backtest validation.
"""
from __future__ import annotations
from collections import Counter

VERSION = "market-os-v1"

BLOCKED_STATES = {"TREND_DAMAGE", "BREAKOUT_FAIL"}

SETUP_BASE = {
    "BREAKOUT_HOLD": 90,
    "NEW_HIGH": 80,
    "M_BREAKOUT_TEST": 78,
    "PULLBACK_INTACT": 72,
    "LEADER_TREND": 70,
    "M_CONTRACTION": 65,
    "PREV_HIGH_APPROACH": 60,
    "BREAKOUT_FAIL": 20,
    "TREND_DAMAGE": 10,
}

TRIGGER_MAP = {
    "BREAKOUT_HOLD": ("STRUCTURE_CONFIRMED", "돌파 후 지지 확인"),
    "NEW_HIGH": ("BREAKOUT_TEST", "신고가 상단 확인 중"),
    "M_BREAKOUT_TEST": ("BREAKOUT_TEST", "수렴 돌파 확인 중"),
    "PULLBACK_INTACT": ("WAIT_PULLBACK", "추세 유지 · 다음 눌림/재확인 대기"),
    "M_CONTRACTION": ("WAIT_PULLBACK", "수렴 · 돌파 확인 대기"),
    "PREV_HIGH_APPROACH": ("WAIT_PULLBACK", "전고점 접근 · 돌파/눌림 대기"),
    "LEADER_TREND": ("WAIT_PULLBACK", "주도 추세 · 실행 위치 대기"),
    "BREAKOUT_FAIL": ("BLOCKED", "돌파 실패"),
    "TREND_DAMAGE": ("BLOCKED", "분봉 추세 훼손"),
}


def clamp(value, lo=0, hi=100):
    return max(lo, min(hi, int(round(value))))


def _theme_map(theme_rotation):
    return {x.get("name"): x for x in (theme_rotation or {}).get("series", []) if x.get("name")}


def _eligible(row):
    return bool(
        row.get("sector") != "ETF·ETN"
        and row.get("recent_trade")
        and row.get("delta_state") == "OK"
        and (row.get("interval_turnover_krw") or 0) > 0
        and not any(str(x).startswith("TURNOVER_") for x in (row.get("quality_flags") or []))
    )


def _radar_score(row, money_rank):
    score = 0
    reasons = []
    trade_rank = row.get("trade_rank")
    query_rank = row.get("query_rank")
    burst = row.get("burst_multiple")

    if trade_rank is not None:
        if trade_rank <= 10:
            score += 25; reasons.append("거래대금 Top10")
        elif trade_rank <= 20:
            score += 18; reasons.append("거래대금 Top20")
        elif trade_rank <= 40:
            score += 10; reasons.append("거래대금 Top40")
    if query_rank is not None:
        if query_rank <= 10:
            score += 20; reasons.append("조회 Top10")
        elif query_rank <= 20:
            score += 14; reasons.append("조회 Top20")
        elif query_rank <= 40:
            score += 8; reasons.append("조회 Top40")
    if money_rank is not None:
        if money_rank <= 10:
            score += 15; reasons.append("최근 구간 대금 Top10")
        elif money_rank <= 20:
            score += 10; reasons.append("최근 구간 대금 Top20")
    if burst is not None:
        if burst >= 3:
            score += 25; reasons.append(f"거래속도 {burst:.1f}배")
        elif burst >= 2:
            score += 18; reasons.append(f"거래속도 {burst:.1f}배")
        elif burst >= 1.4:
            score += 10; reasons.append(f"거래속도 {burst:.1f}배")
    return clamp(score), reasons


def _theme_score(row, theme_stat, theme_member_count):
    if not row.get("market_theme"):
        return 0, ["시장테마 미확인"]
    score = 10
    reasons = []
    if theme_member_count >= 4:
        score += 35; reasons.append(f"동일테마 {theme_member_count}종목 관찰")
    elif theme_member_count == 3:
        score += 28; reasons.append("동일테마 3종목 관찰")
    elif theme_member_count == 2:
        score += 18; reasons.append("동일테마 2종목 관찰")
    else:
        score += 5

    change = theme_stat.get("change_pp") if theme_stat else None
    share = theme_stat.get("current_share_pct") if theme_stat else None
    if change is not None:
        if change >= 3:
            score += 35; reasons.append(f"테마 거래비중 +{change:.1f}%p")
        elif change >= 1:
            score += 25; reasons.append(f"테마 거래비중 +{change:.1f}%p")
        elif change > 0:
            score += 12; reasons.append("테마 거래비중 증가")
        elif change <= -3:
            reasons.append(f"테마 거래비중 {change:.1f}%p")
    if share is not None:
        if share >= 20:
            score += 20; reasons.append(f"공통표본 비중 {share:.1f}%")
        elif share >= 10:
            score += 12
        elif share >= 5:
            score += 6
    return clamp(score), reasons


def _setup_score(row):
    chart = row.get("chart") or {}
    state = chart.get("state")
    if not state:
        return 0, ["차트 판독 대기"]
    score = SETUP_BASE.get(state, 45)
    reasons = [chart.get("state_ko") or state]
    trend = chart.get("minute_trend")
    context = chart.get("daily_context") or ""
    if trend == "상승 유지":
        score += 5; reasons.append("분봉 상승 유지")
    elif trend == "추세 약화":
        score -= 12; reasons.append("분봉 추세 약화")
    if "신고가" in context or "전고점/신고가" in context:
        score += 5; reasons.append("일봉 신고가 맥락")
    elif "전고점 접근" in context:
        score += 3; reasons.append("일봉 전고점 접근")
    return clamp(score), reasons


def _catalyst_grade(row):
    fresh_report = bool(row.get("research") and not row.get("research_stale"))
    event_type = row.get("event_type")
    if fresh_report and event_type and event_type != "기타·미확인":
        return "A", "인용 포함 최근 조사 + 명시적 재료 유형"
    if fresh_report:
        return "B", "인용 포함 최근 조사 · 재료 유형 추가 확인"
    if row.get("leads"):
        return "C", "공시·뉴스 원문 후보 있음 · 종합 검증 전"
    return "U", "검증 근거 부족"


def _trigger(row):
    state = (row.get("chart") or {}).get("state")
    return TRIGGER_MAP.get(state, ("NO_DATA", "실행 구조 판독 대기"))


def _market_stance(regime):
    if not regime:
        return "UNKNOWN", "시장 레짐 미확인"
    if regime.get("stale"):
        return "UNKNOWN", "시장 레짐 지연"
    trend = regime.get("candidate_trend_state")
    flow = regime.get("candidate_flow_state")
    sentiment = regime.get("candidate_sentiment_state")
    if trend == "FALLING" or sentiment == "WEAK" or flow in {"ROTATIONAL_DISTRIBUTED", "BROAD_DISTRIBUTED"}:
        return "DEFENSIVE", "축소·관망 우선"
    if flow in {"LEADER_CONCENTRATED", "LARGE_CAP_CONCENTRATED"} and trend != "FALLING":
        return "EXPANDABLE", "주도 확인 시 확대 검토"
    return "SELECTIVE", "선별 대응"


def _risk_flags(row, theme_stat, stance):
    flags = []
    state = (row.get("chart") or {}).get("state")
    if state == "BREAKOUT_FAIL":
        flags.append("돌파 실패")
    elif state == "TREND_DAMAGE":
        flags.append("추세 훼손")
    change = theme_stat.get("change_pp") if theme_stat else None
    if change is not None and change <= -3:
        flags.append(f"테마 거래비중 {change:.1f}%p")
    burst = row.get("burst_multiple")
    if burst is not None and burst >= 5:
        flags.append("거래속도 과열 확인")
    chg = row.get("change_pct")
    if chg is not None:
        if chg >= 20:
            flags.append("당일 급등 20%+")
        elif chg >= 15:
            flags.append("당일 급등 15%+")
        elif chg <= -8:
            flags.append("당일 약세 -8% 이하")
    if not row.get("research") or row.get("research_stale"):
        flags.append("재료 종합 미완료")
    if stance == "DEFENSIVE":
        flags.append("시장 레짐 방어적")
    elif stance == "UNKNOWN":
        flags.append("시장 레짐 확인 필요")
    return flags


def _tier(radar, theme, setup, catalyst, trigger, stance):
    if trigger == "BLOCKED":
        return "BLOCKED", "구조 훼손 · 신규 실행 후보 제외"
    if radar >= 65 and theme >= 50 and setup >= 65 and catalyst in {"A", "B"} and stance != "DEFENSIVE":
        return "FOCUS", "여러 축 동시 확인 · 원문/차트 우선 검토"
    if radar >= 50 and setup >= 55 and (theme >= 35 or catalyst in {"A", "B"}):
        return "PREP", "구조 또는 재료 확인 단계"
    return "DISCOVER", "관심·거래 활동 선행 · 이유와 구조 조사"


def market_os_watchlist(rows, theme_rotation=None, market_regime=None, limit=12):
    """Return a lexicographically sorted, multi-axis observation shortlist.

    Sorting is only for screen triage. There is intentionally no combined
    recommendation score or implied return probability.
    """
    eligible = [r for r in rows if _eligible(r)]
    if not eligible:
        return []
    money_order = {
        r.get("code"): i + 1 for i, r in enumerate(
            sorted(eligible, key=lambda x: -(x.get("interval_turnover_krw") or 0))
        )
    }
    theme_counts = Counter(r.get("market_theme") for r in eligible if r.get("market_theme"))
    theme_stats = _theme_map(theme_rotation)
    stance, stance_label = _market_stance(market_regime)
    out = []
    for row in eligible:
        theme_name = row.get("market_theme")
        tstat = theme_stats.get(theme_name) or {}
        radar, radar_reasons = _radar_score(row, money_order.get(row.get("code")))
        theme, theme_reasons = _theme_score(row, tstat, theme_counts.get(theme_name, 0))
        setup, setup_reasons = _setup_score(row)
        catalyst, catalyst_note = _catalyst_grade(row)
        trigger, trigger_note = _trigger(row)
        risks = _risk_flags(row, tstat, stance)
        tier, tier_note = _tier(radar, theme, setup, catalyst, trigger, stance)
        out.append({
            "code": row.get("code"),
            "name": row.get("name"),
            "version": VERSION,
            "watch_tier": tier,
            "watch_note": tier_note,
            "radar_score": radar,
            "theme_score": theme,
            "setup_score": setup,
            "catalyst_grade": catalyst,
            "catalyst_note": catalyst_note,
            "trigger_state": trigger,
            "trigger_note": trigger_note,
            "market_stance": stance,
            "market_stance_label": stance_label,
            "market_theme": theme_name,
            "event_type": row.get("event_type"),
            "chart_state": (row.get("chart") or {}).get("state_ko") or (row.get("chart") or {}).get("state"),
            "query_rank": row.get("query_rank"),
            "trade_rank": row.get("trade_rank"),
            "interval_turnover_krw": row.get("interval_turnover_krw"),
            "five_min_turnover_krw": row.get("five_min_turnover_krw"),
            "burst_multiple": row.get("burst_multiple"),
            "change_pct": row.get("change_pct"),
            "theme_share_change_pp": tstat.get("change_pp"),
            "axis_reasons": {
                "radar": radar_reasons[:5],
                "theme": theme_reasons[:5],
                "setup": setup_reasons[:5],
            },
            "risk_flags": risks[:6],
            "observed_at": row.get("received_at"),
        })

    tier_order = {"FOCUS": 0, "PREP": 1, "DISCOVER": 2, "BLOCKED": 3}
    trigger_order = {"STRUCTURE_CONFIRMED": 0, "BREAKOUT_TEST": 1, "WAIT_PULLBACK": 2, "NO_DATA": 3, "BLOCKED": 4}
    out.sort(key=lambda x: (
        tier_order.get(x["watch_tier"], 9),
        trigger_order.get(x["trigger_state"], 9),
        -x["radar_score"],
        -x["theme_score"],
        -x["setup_score"],
        x.get("trade_rank") if x.get("trade_rank") is not None else 999,
    ))
    return out[:limit]
