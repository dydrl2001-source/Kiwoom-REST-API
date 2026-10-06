"""Append-only review decision journal.

This module stores *issued decisions*, not end-of-day analysis.  It never places
orders and does not expose a write HTTP endpoint.  The EOD review bridge reads
these rows later so hindsight cannot rewrite the original plan.

Market OS FOCUS snapshots captured at 08:20/09:20 are explicitly labelled as
MARKET_OS_FOCUS_SNAPSHOT and are NOT silently renamed to A-grade.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timezone
import hashlib
import json
import os
import re
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from flow_store import desk_payload

DB = os.getenv("DATABASE_URL", "")
POLL = max(10, min(60, int(os.getenv("MARKET_REVIEW_JOURNAL_POLL_SECONDS", "15"))))
KST = ZoneInfo("Asia/Seoul")

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS market_review_decisions (
    id                  BIGSERIAL PRIMARY KEY,
    session_date        DATE NOT NULL,
    issued_at           TIMESTAMPTZ NOT NULL,
    stage               TEXT NOT NULL,
    source_kind         TEXT NOT NULL,
    stock_code          TEXT NOT NULL,
    stock_name          TEXT,
    grade               TEXT,
    watch_tier          TEXT,
    setup_type          TEXT,
    side                TEXT NOT NULL DEFAULT 'LONG',
    trigger_spec        JSONB NOT NULL DEFAULT '{}'::jsonb,
    theoretical_entry_krw NUMERIC,
    invalidation_stop_krw NUMERIC,
    expiry_at           TIMESTAMPTZ,
    market_stance       TEXT,
    catalyst_grade      TEXT,
    rule_version        TEXT,
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision_hash       TEXT NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_review_decisions_session
  ON market_review_decisions(session_date, issued_at, stock_code);
CREATE INDEX IF NOT EXISTS idx_market_review_decisions_stage
  ON market_review_decisions(session_date, stage, issued_at);
"""


def db():
    if not DB:
        raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(
        DB,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c statement_timeout=15000 -c lock_timeout=3000",
    )


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def decision_hash(decision):
    stable = {
        "session_date": str(decision.get("session_date") or ""),
        "issued_at": str(decision.get("issued_at") or ""),
        "stage": str(decision.get("stage") or ""),
        "source_kind": str(decision.get("source_kind") or ""),
        "stock_code": str(decision.get("stock_code") or ""),
        "grade": decision.get("grade"),
        "watch_tier": decision.get("watch_tier"),
        "setup_type": decision.get("setup_type"),
        "side": decision.get("side") or "LONG",
        "trigger_spec": decision.get("trigger_spec") or {},
        "theoretical_entry_krw": decision.get("theoretical_entry_krw"),
        "invalidation_stop_krw": decision.get("invalidation_stop_krw"),
        "expiry_at": str(decision.get("expiry_at") or ""),
        "rule_version": decision.get("rule_version"),
        "evidence": decision.get("evidence") or {},
    }
    return hashlib.sha256(canonical(stable).encode("utf-8")).hexdigest()


def ensure_schema():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419093)")
        cur.execute(SCHEMA)


def _valid_code(value):
    s = str(value or "")
    return s if re.fullmatch(r"[0-9A-Z]{6}", s) else None


def append_decision(decision, connection=None):
    """Append one immutable decision. Existing hashes are never updated."""
    issued_at = decision.get("issued_at")
    if not isinstance(issued_at, datetime) or issued_at.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware datetime")
    code = _valid_code(decision.get("stock_code"))
    if not code:
        raise ValueError("invalid stock_code")
    stage = str(decision.get("stage") or "").strip()
    source = str(decision.get("source_kind") or "").strip()
    if not stage or not source:
        raise ValueError("stage/source_kind required")
    side = str(decision.get("side") or "LONG").upper()
    if side not in {"LONG", "OBSERVE"}:
        raise ValueError("side must be LONG or OBSERVE")

    session_date = decision.get("session_date") or issued_at.astimezone(KST).date()
    row = dict(decision)
    row["session_date"] = session_date
    row["stock_code"] = code
    row["stage"] = stage
    row["source_kind"] = source
    row["side"] = side
    row["decision_hash"] = decision_hash(row)

    owns = connection is None
    c = connection or db()
    try:
        with c.cursor() as cur:
            cur.execute(
                """INSERT INTO market_review_decisions(
                    session_date,issued_at,stage,source_kind,stock_code,stock_name,
                    grade,watch_tier,setup_type,side,trigger_spec,theoretical_entry_krw,
                    invalidation_stop_krw,expiry_at,market_stance,catalyst_grade,
                    rule_version,evidence,decision_hash)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT(decision_hash) DO NOTHING
                   RETURNING id""",
                (
                    row["session_date"], issued_at, stage, source, code, row.get("stock_name"),
                    row.get("grade"), row.get("watch_tier"), row.get("setup_type"), side,
                    canonical(row.get("trigger_spec") or {}), row.get("theoretical_entry_krw"),
                    row.get("invalidation_stop_krw"), row.get("expiry_at"),
                    row.get("market_stance"), row.get("catalyst_grade"), row.get("rule_version"),
                    canonical(row.get("evidence") or {}), row["decision_hash"],
                ),
            )
            inserted = cur.fetchone()
        if owns:
            c.commit()
        return inserted["id"] if inserted else None
    finally:
        if owns:
            c.close()


def _focus_decision(stage, item, issued_at, payload):
    """Preserve FOCUS as FOCUS. Do not fabricate A-grade/entry/stop."""
    return {
        "session_date": issued_at.astimezone(KST).date(),
        "issued_at": issued_at,
        "stage": stage,
        "source_kind": "MARKET_OS_FOCUS_SNAPSHOT",
        "stock_code": item.get("code"),
        "stock_name": item.get("name"),
        "grade": None,
        "watch_tier": item.get("watch_tier"),
        "setup_type": None,
        "side": "OBSERVE",
        "trigger_spec": {"state": item.get("trigger_state")},
        "theoretical_entry_krw": None,
        "invalidation_stop_krw": None,
        "expiry_at": None,
        "market_stance": item.get("market_stance"),
        "catalyst_grade": item.get("catalyst_grade"),
        "rule_version": payload.get("market_os_version"),
        "evidence": {
            "generated_at": payload.get("generated_at"),
            "sample_time": payload.get("sample_time"),
            "market_theme": item.get("market_theme"),
            "event_type": item.get("event_type"),
            "radar_score": item.get("radar_score"),
            "theme_score": item.get("theme_score"),
            "setup_score": item.get("setup_score"),
            "trigger_state": item.get("trigger_state"),
            "risk_flags": item.get("risk_flags") or [],
            "trade_rank": item.get("trade_rank"),
            "change_pct": item.get("change_pct"),
            "note": "FOCUS snapshot only; not native A-grade and not an executable trade card.",
        },
    }


def capture_focus_snapshot(stage, now=None, payload=None):
    """Capture the current FOCUS set once per stage/stock without changing semantics."""
    now = now or datetime.now(timezone.utc)
    payload = payload or desk_payload(include_tracking=False)
    sample = payload.get("sample_time")
    if not sample or not payload.get("recent_trade_count"):
        return 0
    try:
        sample_dt = datetime.fromisoformat(str(sample).replace("Z", "+00:00"))
        if sample_dt.tzinfo is None:
            sample_dt = sample_dt.replace(tzinfo=timezone.utc)
        age = (now.astimezone(timezone.utc) - sample_dt.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return 0
    # Never turn a holiday/prior-session/stale sample into a fresh decision snapshot.
    if age < -60 or age > 180:
        return 0
    items = [x for x in (payload.get("market_os_watchlist") or []) if x.get("watch_tier") == "FOCUS"]
    if not items:
        return 0
    inserted = 0
    with db() as c:
        for item in items:
            d = _focus_decision(stage, item, now, payload)
            # One immutable FOCUS record per session/stage/stock. Keep the first observation.
            d["issued_at"] = now.replace(second=0, microsecond=0)
            d["decision_hash"] = hashlib.sha256(
                f"{d['session_date']}|{stage}|{d['stock_code']}|MARKET_OS_FOCUS_SNAPSHOT".encode()
            ).hexdigest()
            with c.cursor() as cur:
                cur.execute(
                    """INSERT INTO market_review_decisions(
                        session_date,issued_at,stage,source_kind,stock_code,stock_name,
                        grade,watch_tier,setup_type,side,trigger_spec,theoretical_entry_krw,
                        invalidation_stop_krw,expiry_at,market_stance,catalyst_grade,
                        rule_version,evidence,decision_hash)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                       ON CONFLICT(decision_hash) DO NOTHING""",
                    (
                        d["session_date"], d["issued_at"], d["stage"], d["source_kind"],
                        d["stock_code"], d.get("stock_name"), d.get("grade"), d.get("watch_tier"),
                        d.get("setup_type"), d["side"], canonical(d.get("trigger_spec") or {}),
                        None, None, None, d.get("market_stance"), d.get("catalyst_grade"),
                        d.get("rule_version"), canonical(d.get("evidence") or {}), d["decision_hash"],
                    ),
                )
                if cur.rowcount and cur.rowcount > 0:
                    inserted += cur.rowcount
        c.commit()
    return inserted


WINDOWS = (
    ("PREMARKET_0820", dtime(8, 20), dtime(8, 22)),
    ("CHECKPOINT_0920", dtime(9, 20), dtime(9, 22)),
)


def run_once(now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(KST)
    if local.weekday() >= 5:
        return "NON_SESSION_WEEKEND"
    for stage, start, end in WINDOWS:
        if start <= local.time() < end:
            n = capture_focus_snapshot(stage, now)
            return f"{stage}:{n}"
    return "OUTSIDE_CAPTURE_WINDOWS"


def main():
    ensure_schema()
    while True:
        try:
            print("MARKET_REVIEW_JOURNAL:", run_once(), flush=True)
        except Exception as exc:
            # Do not print DB bodies, credentials or payloads.
            print("MARKET_REVIEW_JOURNAL: ERROR", type(exc).__name__, flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
