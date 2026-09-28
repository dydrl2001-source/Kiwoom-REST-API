"""Persist real-time observation-candidate history.

This worker never places orders and never calls OpenAI. It snapshots the local
candidate list once per latest market sample so persistence can be measured
without treating one 30-second spike as durable interest.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

from flow_core import dt
from flow_store import db, desk_payload

POLL = max(15, int(os.getenv("CANDIDATE_TRACK_POLL_SECONDS", "30")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS radar_candidate_history(
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  attention_score INTEGER NOT NULL,
  label TEXT,
  primary_type TEXT,
  watch_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  market_theme TEXT,
  price_krw NUMERIC,
  change_pct DOUBLE PRECISION,
  interval_turnover_krw NUMERIC,
  five_min_turnover_krw NUMERIC,
  burst_multiple DOUBLE PRECISION,
  event_type TEXT,
  chart_state TEXT,
  query_rank INTEGER,
  trade_rank INTEGER,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY(snapshot_time,stock_code)
);
CREATE INDEX IF NOT EXISTS idx_candidate_history_code_time
  ON radar_candidate_history(stock_code,snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_history_time
  ON radar_candidate_history(snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_history_theme_time
  ON radar_candidate_history(market_theme,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS radar_candidate_tracker_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  last_sample_time TIMESTAMPTZ,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  rows_written INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""


def schema():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (72419066,))
        cur.execute(SCHEMA)


def set_status(status, sample_time=None, candidate_count=0, rows_written=0, note=None):
    with db() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO radar_candidate_tracker_status(
                 id,updated_at,status,last_sample_time,candidate_count,rows_written,note)
               VALUES(1,now(),%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET
                 updated_at=now(),status=excluded.status,
                 last_sample_time=COALESCE(excluded.last_sample_time,radar_candidate_tracker_status.last_sample_time),
                 candidate_count=excluded.candidate_count,
                 rows_written=excluded.rows_written,note=excluded.note""",
            (status, sample_time, candidate_count, rows_written, note),
        )


def safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_float(value):
    try:
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def snapshot():
    payload = desk_payload(include_tracking=False)
    sample_time = dt(payload.get("sample_time"))
    if not sample_time:
        set_status("WAITING_FOR_SAMPLE", note="flow sample not ready")
        return "WAITING_FOR_SAMPLE"

    candidates = payload.get("watch_candidates") or []
    if payload.get("status") != "RECENT_TRADES":
        set_status("NO_RECENT_TRADE", sample_time, len(candidates), 0,
                   "market sample exists but recent exchange trade is not confirmed")
        return "NO_RECENT_TRADE"

    rows = []
    for x in candidates:
        code = str(x.get("code") or "")
        score = safe_int(x.get("attention_score"))
        if len(code) != 6 or score is None:
            continue
        source = next((r for r in payload.get("rows", []) if r.get("code") == code), {})
        rows.append((
            sample_time, code, str(x.get("name") or code)[:80], score,
            str(x.get("label") or "")[:40], str(x.get("primary_type") or "")[:80],
            json.dumps(x.get("watch_types") or [], ensure_ascii=False),
            str(x.get("market_theme") or "")[:160] or None,
            source.get("price_krw"), safe_float(x.get("change_pct")),
            x.get("interval_turnover_krw"), x.get("five_min_turnover_krw"),
            safe_float(x.get("burst_multiple")), str(x.get("event_type") or "")[:80] or None,
            str(x.get("chart_state") or "")[:120] or None,
            safe_int(x.get("query_rank")), safe_int(x.get("trade_rank")),
            json.dumps(x.get("reasons") or [], ensure_ascii=False),
            json.dumps(x.get("risk_flags") or [], ensure_ascii=False),
        ))

    with db() as c, c.cursor() as cur:
        if rows:
            cur.executemany(
                """INSERT INTO radar_candidate_history(
                     snapshot_time,stock_code,stock_name,attention_score,label,primary_type,
                     watch_types,market_theme,price_krw,change_pct,interval_turnover_krw,
                     five_min_turnover_krw,burst_multiple,event_type,chart_state,query_rank,
                     trade_rank,reasons,risk_flags)
                   VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                   ON CONFLICT(snapshot_time,stock_code) DO NOTHING""",
                rows,
            )
        written = cur.rowcount if rows else 0
        # Long enough for intraday review and calibration, bounded so this stays lightweight.
        cur.execute("DELETE FROM radar_candidate_history WHERE snapshot_time < now()-interval '14 days'")
        cur.execute(
            """INSERT INTO radar_candidate_tracker_status(
                 id,updated_at,status,last_sample_time,candidate_count,rows_written,note)
               VALUES(1,now(),'OK',%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',
                 last_sample_time=excluded.last_sample_time,
                 candidate_count=excluded.candidate_count,rows_written=excluded.rows_written,
                 note=excluded.note""",
            (sample_time, len(candidates), written,
             "local observation history only; no orders or model calls"),
        )
    return "OK"


def main():
    schema()
    print(f"Candidate tracker started: target={POLL}s; local history only", flush=True)
    while True:
        started = time.monotonic()
        try:
            result = snapshot()
            if result not in ("OK", "WAITING_FOR_SAMPLE", "NO_RECENT_TRADE"):
                print("Candidate tracker:", result, flush=True)
        except Exception as exc:
            try:
                set_status("ERROR", note=type(exc).__name__)
            except Exception:
                pass
            print("Candidate tracker error:", type(exc).__name__, flush=True)
        time.sleep(max(1, POLL - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
