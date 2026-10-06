"""Read-only EOD review bridge.

Purpose:
- provide one authenticated, minimal endpoint for end-of-day review;
- read existing Postgres facts only;
- collapse Telegram sibling channels into source families;
- expose immutable decision journal rows and available market observations;
- never place orders and never mutate Postgres.

The bridge intentionally distinguishes an original event-engine RADAR_SUMMARY from
its own reconstructed fallback.  If the original summary is not persisted in a
known table, it reports that fact instead of pretending the fallback is original.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
import json
import math
import os
import re
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

DB = os.getenv("DATABASE_URL", "")
KST = ZoneInfo("Asia/Seoul")

THEME_KEYWORDS = {
    "반도체/HBM": ["HBM", "반도체", "패키징", "테스트", "파운드리", "D램", "DRAM", "낸드"],
    "PCB/반도체기판": ["PCB", "기판", "FC-BGA", "CCL", "회로", "패키지기판"],
    "2차전지/배터리": ["2차전지", "배터리", "양극재", "음극재", "전고체"],
    "전력/변압기/케이블": ["전력", "변압기", "케이블", "데이터센터 전력"],
    "원전/SMR": ["원전", "SMR", "원자력"],
    "방산": ["방산", "군수", "미사일", "무기"],
    "조선/LNG": ["조선", "LNG", "해운"],
    "바이오/제약": ["바이오", "제약", "임상", "FDA"],
    "로봇": ["로봇", "휴머노이드", "자동화"],
    "자동차/EV": ["자동차", "전기차", "EV", "자율주행"],
    "AI/데이터센터": ["AI 데이터센터", "데이터센터", "AI 팩토리", "NPU", "GPU", "AI 서버"],
    "정유/유가": ["정유", "유가", "WTI", "브렌트", "석유"],
    "화장품": ["화장품", "뷰티"],
    "태양광/에너지": ["태양광", "솔라", "태양광 모듈", "폴리실리콘"],
    "금융": ["은행", "금융", "증권", "보험"],
}
TICKER_RE = re.compile(r"(?<![0-9])([0-9]{6})(?![0-9])")


def ro_db():
    if not DB:
        raise RuntimeError("DATABASE_URL missing")
    # The server enforces a read-only default transaction for this connection.
    return psycopg.connect(
        DB,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=20000 -c lock_timeout=2000",
    )


def table_exists(cur, name):
    cur.execute("SELECT to_regclass(%s) AS t", ("public." + name,))
    return cur.fetchone()["t"] is not None


def iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def session_bounds(day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    start = datetime.combine(day, dtime(0, 0), KST).astimezone(timezone.utc)
    end = (datetime.combine(day, dtime(23, 59, 59, 999999), KST)).astimezone(timezone.utc)
    market_close = datetime.combine(day, dtime(15, 30), KST).astimezone(timezone.utc)
    return start, end, market_close


def source_family(channel):
    """Collapse known sibling channels; exact channel is fallback family."""
    name = re.sub(r"\s+", " ", str(channel or "")).strip()
    lowered = name.lower()
    if "급등일보" in name:
        return "급등일보"
    # Optional operator-managed aliases without code changes.
    raw = os.getenv("REVIEW_SOURCE_FAMILY_ALIASES_JSON", "")
    if raw:
        try:
            mapping = json.loads(raw)
            if isinstance(mapping, dict):
                for family, aliases in mapping.items():
                    if not isinstance(aliases, list):
                        continue
                    for alias in aliases:
                        a = str(alias or "").strip().lower()
                        if a and a in lowered:
                            return str(family)
        except (ValueError, TypeError):
            pass
    return name or "UNKNOWN"


def infer_themes(text):
    body = str(text or "").lower()
    out = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(k.lower() in body for k in keywords):
            out.append(theme)
    return out


def reconstruct_radar_summary(messages):
    theme_messages = Counter()
    theme_families = defaultdict(set)
    ticker_messages = Counter()
    ticker_families = defaultdict(set)
    for row in messages:
        family = row.get("source_family") or source_family(row.get("channel_name"))
        text = row.get("text") or ""
        for theme in infer_themes(text):
            theme_messages[theme] += 1
            theme_families[theme].add(family)
        for ticker in set(TICKER_RE.findall(text)):
            ticker_messages[ticker] += 1
            ticker_families[ticker].add(family)
    themes = [
        {"theme": t, "messages": n, "families": len(theme_families[t])}
        for t, n in theme_messages.most_common()
    ]
    tickers = [
        {"ticker": t, "messages": n, "families": len(ticker_families[t])}
        for t, n in ticker_messages.most_common()
    ]
    tickers.sort(key=lambda x: (-x["families"], -x["messages"], x["ticker"]))
    return {
        "status": "RECONSTRUCTED_FROM_TELEGRAM_MESSAGES",
        "warning": "This is not the event-engine [RADAR_SUMMARY]. Use only as fallback.",
        "themes": themes,
        "tickers": tickers[:100],
    }


def _original_radar_summary(cur, start, end):
    """Read a persisted event-engine summary only when a supported sink exists."""
    candidates = (
        ("event_engine_radar_summaries", "summary_time", "payload"),
        ("radar_summary_snapshots", "summary_time", "payload"),
        ("telegram_radar_summaries", "summary_time", "payload"),
    )
    for table, time_col, payload_col in candidates:
        if not table_exists(cur, table):
            continue
        try:
            cur.execute(
                f"SELECT {time_col} AS summary_time,{payload_col} AS payload "
                f"FROM {table} WHERE {time_col}>=%s AND {time_col}<=%s "
                f"ORDER BY {time_col} DESC LIMIT 1",
                (start, end),
            )
            row = cur.fetchone()
            if row:
                return {
                    "status": "ORIGINAL_PERSISTED",
                    "table": table,
                    "summary_time": iso(row["summary_time"]),
                    "payload": row["payload"],
                }
        except Exception:
            # A differently shaped optional table is not trusted.
            continue
    return {
        "status": "UNAVAILABLE",
        "reason": "event-engine [RADAR_SUMMARY] is not persisted in a supported read-only sink",
    }


def telegram_section(cur, day):
    start, end, _ = session_bounds(day)
    if not table_exists(cur, "telegram_messages"):
        return {
            "status": "UNAVAILABLE",
            "latest_message_at": None,
            "messages": [],
            "original_radar_summary": _original_radar_summary(cur, start, end),
            "reconstructed_summary": None,
        }
    cur.execute(
        """SELECT collected_at,message_date,channel_name,text,message_url
           FROM telegram_messages
           WHERE COALESCE(message_date,collected_at)>=%s
             AND COALESCE(message_date,collected_at)<=%s
           ORDER BY COALESCE(message_date,collected_at),collected_at
           LIMIT 5000""",
        (start, end),
    )
    messages = []
    for r in cur.fetchall():
        at = r["message_date"] or r["collected_at"]
        messages.append(
            {
                "message_date": iso(at),
                "collected_at": iso(r["collected_at"]),
                "channel_name": r["channel_name"],
                "source_family": source_family(r["channel_name"]),
                "text": r["text"],
                "message_url": r["message_url"],
            }
        )
    return {
        "status": "OK",
        "latest_message_at": messages[-1]["message_date"] if messages else None,
        "message_count": len(messages),
        "source_family_count": len({x["source_family"] for x in messages}),
        "original_radar_summary": _original_radar_summary(cur, start, end),
        "reconstructed_summary": reconstruct_radar_summary(messages),
        "messages": messages,
    }


def _latest_snapshot_time(cur, table, day, column="snapshot_time"):
    if not table_exists(cur, table):
        return None
    start, end, _ = session_bounds(day)
    cur.execute(
        f"SELECT MAX({column}) AS t FROM {table} WHERE {column}>=%s AND {column}<=%s",
        (start, end),
    )
    row = cur.fetchone()
    return row["t"] if row else None


def market_section(cur, day):
    out = {
        "regime": None,
        "regime_metrics": None,
        "trade_value": {"as_of": None, "top": []},
        "rank": {"as_of": None, "top": []},
        "breadth": None,
        "foreign_flow": None,
        "institution_flow": None,
        "limitations": [],
    }
    regime_time = _latest_snapshot_time(cur, "market_regime_snapshots", day)
    if regime_time:
        cur.execute(
            """SELECT snapshot_time,stable_label,candidate_label,confidence,data_freshness_sec,
                      rank_turnover_5m,top5_trade_share,top10_trade_share,top_sector_share,
                      top3_sector_share,largecap_trade_share,positive_rank_share,
                      avg_rank_change_rate,sector_count_top20,explanation
               FROM market_regime_snapshots WHERE snapshot_time=%s LIMIT 1""",
            (regime_time,),
        )
        r = cur.fetchone()
        if r:
            out["regime_metrics"] = {k: iso(v) for k, v in dict(r).items()}
            out["regime"] = r.get("stable_label") or r.get("candidate_label")

    trade_time = _latest_snapshot_time(cur, "market_trade_value_snapshots", day)
    if trade_time:
        cur.execute(
            """SELECT stock_code,stock_name,rank_no,trade_value_krw,change_rate,
                      market_cap_krw,official_sector,market_theme,current_price_krw
               FROM market_trade_value_snapshots
               WHERE snapshot_time=%s
               ORDER BY rank_no NULLS LAST LIMIT 100""",
            (trade_time,),
        )
        out["trade_value"] = {
            "as_of": iso(trade_time),
            "top": [{k: iso(v) for k, v in dict(r).items()} for r in cur.fetchall()],
        }

    rank_time = _latest_snapshot_time(cur, "market_rank_snapshots", day)
    if rank_time:
        cur.execute(
            """SELECT stock_code,stock_name,rank_no,rank_change,change_rate,
                      market_cap_krw,official_sector,market_theme
               FROM market_rank_snapshots
               WHERE snapshot_time=%s
               ORDER BY rank_no NULLS LAST LIMIT 100""",
            (rank_time,),
        )
        out["rank"] = {
            "as_of": iso(rank_time),
            "top": [{k: iso(v) for k, v in dict(r).items()} for r in cur.fetchall()],
        }

    # The radar tables are ranked subsets, not full-exchange breadth. Do not invent it.
    out["limitations"].append("full KRX breadth is not derived from ranked subsets")
    out["limitations"].append("foreign/institutional whole-market flow requires a connected authoritative feed")
    return out


def _bars(cur, code, issued_at, day):
    if not table_exists(cur, "market_minute_bars"):
        return []
    _, _, close_at = session_bounds(day)
    cur.execute(
        """SELECT bar_time,open_price,high_price,low_price,close_price,volume
           FROM market_minute_bars
           WHERE stock_code=%s AND interval_min=1
             AND bar_time>=%s AND bar_time<=%s
           ORDER BY bar_time""",
        (code, issued_at, close_at),
    )
    return [
        {
            "time": r["bar_time"],
            "open": num(r["open_price"]),
            "high": num(r["high_price"]),
            "low": num(r["low_price"]),
            "close": num(r["close_price"]),
            "volume": num(r["volume"]),
        }
        for r in cur.fetchall()
    ]


def _first_exit(path, entry, stop, exit_spec):
    """Resolve a stated LONG exit rule without inventing missing semantics."""
    kind = str((exit_spec or {}).get("kind") or "").upper()
    if kind not in {"STOP_OR_CLOSE", "TARGET_STOP_CLOSE"}:
        return {
            "status": "EXIT_RULE_NOT_AUDITABLE",
            "system_r": None,
            "system_exit_reason": None,
            "system_exit_time": None,
            "system_exit_price_krw": None,
        }
    risk = entry - stop
    target_price = None
    if kind == "TARGET_STOP_CLOSE":
        target_price = num((exit_spec or {}).get("target_price"))
        target_r = num((exit_spec or {}).get("target_r"))
        if target_price is None and target_r is not None:
            target_price = entry + target_r * risk
        if target_price is None or target_price <= entry:
            return {
                "status": "EXIT_RULE_NOT_AUDITABLE",
                "system_r": None,
                "system_exit_reason": None,
                "system_exit_time": None,
                "system_exit_price_krw": None,
            }

    for i, bar in enumerate(path):
        high, low = bar.get("high"), bar.get("low")
        if high is None or low is None:
            continue
        stop_hit = low <= stop
        target_hit = bool(target_price is not None and high >= target_price)
        # With OHLC only, order inside one bar is unknowable. Do not guess.
        if i == 0 and stop_hit:
            return {
                "status": "INTRABAR_ENTRY_STOP_AMBIGUOUS",
                "system_r": None,
                "system_exit_reason": None,
                "system_exit_time": iso(bar.get("time")),
                "system_exit_price_krw": None,
            }
        if stop_hit and target_hit:
            return {
                "status": "INTRABAR_STOP_TARGET_AMBIGUOUS",
                "system_r": None,
                "system_exit_reason": None,
                "system_exit_time": iso(bar.get("time")),
                "system_exit_price_krw": None,
            }
        if stop_hit:
            return {
                "status": "SYSTEM_RESULT_READY",
                "system_r": -1.0,
                "system_exit_reason": "STOP",
                "system_exit_time": iso(bar.get("time")),
                "system_exit_price_krw": stop,
            }
        if target_hit:
            return {
                "status": "SYSTEM_RESULT_READY",
                "system_r": (target_price - entry) / risk,
                "system_exit_reason": "TARGET",
                "system_exit_time": iso(bar.get("time")),
                "system_exit_price_krw": target_price,
            }

    closes = [x for x in path if x.get("close") is not None]
    if not closes:
        return {
            "status": "EXIT_PRICE_UNAVAILABLE",
            "system_r": None,
            "system_exit_reason": None,
            "system_exit_time": None,
            "system_exit_price_krw": None,
        }
    last = closes[-1]
    return {
        "status": "SYSTEM_RESULT_READY",
        "system_r": (last["close"] - entry) / risk,
        "system_exit_reason": "SESSION_CLOSE",
        "system_exit_time": iso(last.get("time")),
        "system_exit_price_krw": last["close"],
    }


def audit_long_plan(decision, bars):
    """Audit a LONG plan only from the original numeric trigger/entry/stop/exit rule."""
    trigger = decision.get("trigger_spec") or {}
    kind = str(trigger.get("kind") or "").upper()
    trigger_price = num(trigger.get("price"))
    entry = num(decision.get("theoretical_entry_krw"))
    stop = num(decision.get("invalidation_stop_krw"))
    if kind not in {"ABOVE", "BELOW", "TOUCH"} or trigger_price is None:
        return {"status": "TRIGGER_SPEC_NOT_AUDITABLE", "trigger_fired": None, "system_r": None}
    if not bars:
        return {"status": "INTRADAY_BARS_UNAVAILABLE", "trigger_fired": None, "system_r": None}

    trigger_index = None
    for i, bar in enumerate(bars):
        high, low = bar.get("high"), bar.get("low")
        if high is None or low is None:
            continue
        fired = (
            (kind == "ABOVE" and high >= trigger_price)
            or (kind == "BELOW" and low <= trigger_price)
            or (kind == "TOUCH" and low <= trigger_price <= high)
        )
        if fired:
            trigger_index = i
            break
    if trigger_index is None:
        return {
            "status": "TRIGGER_NOT_FIRED",
            "trigger_fired": False,
            "system_r": None,
            "hindsight_state": "CANCEL",
        }

    actual_entry = entry if entry is not None else trigger_price
    path = bars[trigger_index:]
    highs = [x["high"] for x in path if x.get("high") is not None]
    lows = [x["low"] for x in path if x.get("low") is not None]
    closes = [x["close"] for x in path if x.get("close") is not None]
    result = {
        "status": "TRIGGER_FIRED",
        "trigger_fired": True,
        "hindsight_state": "ENTER",
        "trigger_time": iso(path[0]["time"]),
        "theoretical_entry_krw": actual_entry,
        "max_high_krw": max(highs) if highs else None,
        "min_low_krw": min(lows) if lows else None,
        "close_krw": closes[-1] if closes else None,
        "stop_hit": None,
        "mfe_r": None,
        "mae_r": None,
        "close_r": None,
        "system_r": None,
        "system_exit_reason": None,
        "system_exit_time": None,
        "system_exit_price_krw": None,
    }
    if stop is None or actual_entry is None or actual_entry <= stop:
        result["status"] = "TRIGGER_FIRED_STOP_NOT_AUDITABLE"
        return result

    risk = actual_entry - stop
    result["stop_hit"] = bool(lows and min(lows) <= stop)
    if highs:
        result["mfe_r"] = (max(highs) - actual_entry) / risk
    if lows:
        result["mae_r"] = (min(lows) - actual_entry) / risk
    if closes:
        result["close_r"] = (closes[-1] - actual_entry) / risk

    exit_result = _first_exit(path, actual_entry, stop, decision.get("exit_spec") or {})
    result.update(exit_result)
    return result

def decisions_section(cur, day):
    if not table_exists(cur, "market_review_decisions"):
        return {
            "status": "JOURNAL_NOT_CONNECTED",
            "native_a_grade": [],
            "focus_snapshots": [],
            "trade_cards": [],
        }
    cur.execute(
        """SELECT id,session_date,issued_at,stage,source_kind,stock_code,stock_name,
                  grade,watch_tier,setup_type,side,trigger_spec,exit_spec,theoretical_entry_krw,
                  invalidation_stop_krw,expiry_at,market_stance,catalyst_grade,
                  rule_version,evidence,decision_hash
           FROM market_review_decisions
           WHERE session_date=%s
           ORDER BY issued_at,id""",
        (day,),
    )
    rows = []
    for r in cur.fetchall():
        item = {k: iso(v) for k, v in dict(r).items()}
        if r["side"] == "LONG":
            item["audit"] = audit_long_plan(item, _bars(cur, r["stock_code"], r["issued_at"], day))
        else:
            item["audit"] = {"status": "OBSERVATION_ONLY", "trigger_fired": None}
        rows.append(item)
    native = [x for x in rows if str(x.get("grade") or "").upper() == "A"]
    focus = [x for x in rows if x.get("source_kind") == "MARKET_OS_FOCUS_SNAPSHOT"]
    cards = [x for x in rows if x.get("stage") == "TRADE_CARD"]
    return {
        "status": "OK",
        "native_a_grade": native,
        "focus_snapshots": focus,
        "trade_cards": cards,
        "all": rows,
    }


def assessment_outcomes_section(cur, day):
    if not table_exists(cur, "market_os_assessment_outcomes"):
        return {"status": "UNAVAILABLE", "rows": []}
    start, end, _ = session_bounds(day)
    cur.execute(
        """SELECT assessment_time,stock_code,rule_version,horizon,reference_price_krw,
                  outcome_price_krw,return_pct,mfe_pct,mae_pct,outcome_time,
                  outcome_source,quality_flags
           FROM market_os_assessment_outcomes
           WHERE assessment_time>=%s AND assessment_time<=%s
           ORDER BY assessment_time,stock_code,horizon""",
        (start, end),
    )
    return {
        "status": "OK",
        "rows": [{k: iso(v) for k, v in dict(r).items()} for r in cur.fetchall()],
    }


def build_session_export(day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    generated = datetime.now(timezone.utc)
    with ro_db() as c, c.cursor() as cur:
        telegram = telegram_section(cur, day)
        market = market_section(cur, day)
        decisions = decisions_section(cur, day)
        outcomes = assessment_outcomes_section(cur, day)
    latest = telegram.get("latest_message_at")
    stale_minutes = None
    if latest:
        try:
            latest_dt = datetime.fromisoformat(latest)
            close = datetime.combine(day, dtime(15, 30), KST)
            stale_minutes = max(0.0, (close - latest_dt.astimezone(KST)).total_seconds() / 60)
        except (ValueError, TypeError):
            pass
    return {
        "schema_version": "market-review-bridge-v1",
        "session_date": day.isoformat(),
        "generated_at": generated.isoformat(),
        "permissions": {
            "database": "READ_ONLY",
            "orders": False,
            "postgres_writes": False,
            "account_identifiers_exported": False,
        },
        "freshness": {
            "telegram_latest_message_at": latest,
            "telegram_gap_to_1530_minutes": stale_minutes,
        },
        "telegram": telegram,
        "market": market,
        "decisions": decisions,
        "market_os_outcomes": outcomes,
        "review_notes": [
            "Original event-engine RADAR_SUMMARY is authoritative when status=ORIGINAL_PERSISTED.",
            "RECONSTRUCTED_FROM_TELEGRAM_MESSAGES is fallback only and must not be presented as original RADAR_SUMMARY.",
            "MARKET_OS_FOCUS_SNAPSHOT is observation evidence, not native A-grade.",
            "User realized result is absent unless a separately approved sanitized execution source is connected.",
        ],
    }
