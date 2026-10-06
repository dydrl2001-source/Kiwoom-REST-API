"""Fail-closed LONG-entry review gate. Never returns broker authorization.

Account/session/duplicate facts must come from a trusted read-only adapter, not
AI, browser input or a saved daily packet. The read-only account adapter supplies
observation and complete unfilled-order facts; unverified daily loss/session
facts remain UNKNOWN and block review.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
import math
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
POLICY = {
    "version": "execution-risk-v1", "mode": "shadow", "max_age_seconds": 90,
    "max_chase_pct": 1.0, "max_stop_pct": 3.0, "max_daily_loss_pct": 2.0,
    "min_turnover_rate_ratio": 0.5, "min_data_confidence": 0.9,
    "entry_start_kst": "09:05", "entry_end_kst": "15:20",
    "live_auto_execution": False,
}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    try:
        t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def fresh(value, now, age=90):
    t = timestamp(value)
    return bool(t and 0 <= (now - t).total_seconds() <= age)


def evaluate(candidate, facts=None, now=None, mode="shadow"):
    now = now or datetime.now(timezone.utc)
    c, f = candidate or {}, facts or {}
    reasons = []
    if mode not in {"shadow", "manual_confirm"}:
        reasons.append("LIVE_AUTO_FORBIDDEN")
    for field in ("price_as_of", "account_as_of", "session_as_of", "duplicate_as_of", "theme_as_of", "turnover_as_of"):
        if not fresh(f.get(field), now):
            reasons.append("STALE_OR_MISSING_" + field.upper())
    local = now.astimezone(KST)
    if (f.get("is_trading_day") is not True or f.get("session_open") is not True
            or local.weekday() >= 5 or not time(9, 5) <= local.time() < time(15, 20)):
        reasons.append("ORDER_WINDOW_CLOSED_OR_UNKNOWN")
    px, ref, stop = (number(f.get(k)) for k in ("price_krw", "reference_price_krw", "stop_price_krw"))
    if px is None or ref is None or px <= 0 or ref <= 0:
        reasons.append("ENTRY_PRICE_UNKNOWN")
    elif px > ref * (1 + POLICY["max_chase_pct"] / 100):
        reasons.append("CHASE_LIMIT")
    if px is None or px <= 0 or stop is None or not 0 < stop < px:
        reasons.append("STOP_INVALID")
    elif (px - stop) / px * 100 > POLICY["max_stop_pct"]:
        reasons.append("STOP_TOO_WIDE")
    loss = number(f.get("daily_loss_pct"))
    if loss is None or loss < 0:
        reasons.append("DAILY_LOSS_UNKNOWN")
    elif loss >= POLICY["max_daily_loss_pct"]:
        reasons.append("DAILY_LOSS_LIMIT")
    if f.get("theme_intact") is not True:
        reasons.append("THEME_EXIT_OR_UNKNOWN")
    ratio = number(f.get("turnover_rate_ratio"))
    if ratio is None or ratio < POLICY["min_turnover_rate_ratio"]:
        reasons.append("TURNOVER_COLLAPSE_OR_UNKNOWN")
    confidence = number(f.get("data_confidence"))
    if confidence is None or not POLICY["min_data_confidence"] <= confidence <= 1:
        reasons.append("DATA_CONFIDENCE_LOW_OR_UNKNOWN")
    if f.get("duplicate_order") is not False:
        reasons.append("DUPLICATE_ORDER_OR_UNKNOWN")
    if not isinstance(f.get("quality_flags"), list) or f["quality_flags"]:
        reasons.append("SOURCE_QUALITY_UNVERIFIED")
    if c.get("watch_tier") != "FOCUS" or c.get("trigger_state") != "STRUCTURE_CONFIRMED":
        reasons.append("RULE_TRIGGER_NOT_READY")
    if c.get("market_stance") not in {"EXPANDABLE", "SELECTIVE"}:
        reasons.append("MARKET_STANCE_BLOCKED")
    if c.get("catalyst_grade") not in {"A", "B"} or c.get("risk_flags"):
        reasons.append("RULE_RISK_OR_CATALYST_BLOCK")
    return {"policy_version": POLICY["version"], "mode": mode,
            "status": "BLOCKED" if reasons else ("SHADOW_PASS" if mode == "shadow" else "MANUAL_CONFIRM_REQUIRED"),
            "review_eligible": not reasons, "reason_codes": reasons,
            "can_submit_order": False, "ai_can_override": False, "broker_order_created": False}


def observation_facts(row):
    """Only source facts actually present in flow_store. Never invent account data."""
    facts = {"price_krw": row.get("price_krw"), "price_as_of": row.get("exchange_at"),
            "quality_flags": row.get("quality_flags"),
            "turnover_as_of": row.get("exchange_at"),
            "turnover_rate_ratio": row.get("burst_multiple")}
    readonly = row.get("readonly_risk_facts") or {}
    for key in ("account_as_of", "duplicate_as_of", "duplicate_order"):
        facts[key] = readonly.get(key)
    # Current account adapter cannot prove a full-day, cash-flow-adjusted loss.
    facts["daily_loss_pct"] = None
    return facts
