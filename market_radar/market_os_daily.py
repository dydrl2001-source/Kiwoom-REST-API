"""14:30–14:40 KST packet worker, independent of live rules and order systems."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

from market_os_budget import BudgetError, db, ensure_schema as budget_schema, request_openai
from market_os_packet import build_packet, compact, in_window, make_ai_request, parse_advice
from market_os_risk import fresh

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_os_daily_packets (
    budget_day DATE PRIMARY KEY, packet_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
    packet JSONB NOT NULL, status TEXT NOT NULL, advice JSONB, error_code TEXT
);
"""


def ensure_schema():
    budget_schema()
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419062)")
        cur.execute(SCHEMA)


def latest():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT budget_day,created_at,completed_at,packet_id,packet,status,advice,error_code "
                    "FROM market_os_daily_packets ORDER BY budget_day DESC LIMIT 1")
        row = cur.fetchone()
    return dict(row) if row else {"status": "WAITING_FOR_WINDOW_AND_FRESH_DATA"}


def run_once(now=None, payload=None, env=None):
    e = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    if e.get("MARKET_OS_DAILY_ENABLED", "1") != "1":
        return "DISABLED"
    if not in_window(now):
        return "OUTSIDE_DECISION_WINDOW"
    ensure_schema()
    # Do not repeat expensive reads or attempt AI after an interrupted packet.
    with db() as c, c.cursor() as cur:
        from market_os_budget import budget_day
        cur.execute("SELECT 1 FROM market_os_daily_packets WHERE budget_day=%s", (budget_day(now),))
        if cur.fetchone():
            return "DAILY_PACKET_EXISTS"
    if payload is None:
        from flow_store import desk_payload
        payload = desk_payload(include_tracking=False)
        from market_os_readonly import enrich_payload
        payload = enrich_payload(payload)
    packet = build_packet(payload, now)
    if packet["status"] != "READY":
        return "WAITING_FOR_FRESH_RULE_CANDIDATES"
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO market_os_daily_packets
            (budget_day,packet_id,created_at,packet,status)
            VALUES(%s,%s,%s,%s::jsonb,'RULES_ONLY') ON CONFLICT DO NOTHING
            RETURNING packet_id""", (packet["budget_day_kst"], packet["packet_id"], now, compact(packet)))
        if not cur.fetchone():
            return "DAILY_PACKET_EXISTS"
    # Immutable daily snapshot is committed before an optional network operation.
    if e.get("MARKET_OS_DAILY_AI_ENABLED", "0") != "1":
        return "RULES_ONLY"
    if not e.get("OPENAI_API_KEY") or not e.get("MARKET_OS_DAILY_AI_MODEL"):
        return "RULES_ONLY"
    current = datetime.now(timezone.utc)
    if not in_window(current) or not all(fresh(c["price_as_of"], current) for c in packet["candidates"]):
        return "RULES_ONLY"
    with db() as c, c.cursor() as cur:
        cur.execute("UPDATE market_os_daily_packets SET status='AI_ATTEMPT_PENDING' WHERE packet_id=%s",
                    (packet["packet_id"],))
    advice, error = None, None
    try:
        data = request_openai(make_ai_request(packet, e["MARKET_OS_DAILY_AI_MODEL"]),
                              e["OPENAI_API_KEY"], "DAILY_DECISION_PACKET")
        advice = parse_advice(data, packet)
        status = "ADVISORY_READY"
    except BudgetError as exc:
        status, error = "RULES_ONLY", str(exc)
    except (ValueError, TypeError, KeyError):
        status, error = "RULES_ONLY", "INVALID_ADVICE"
    with db() as c, c.cursor() as cur:
        cur.execute("""UPDATE market_os_daily_packets SET status=%s,completed_at=clock_timestamp(),
            advice=%s::jsonb,error_code=%s WHERE packet_id=%s""",
                    (status, json.dumps(advice, ensure_ascii=False), error, packet["packet_id"]))
    return status


def main():
    # Starting/stopping this service never changes any rule/position/account.
    initialized = False
    while True:
        try:
            if not initialized:
                ensure_schema()
                initialized = True
            print("MARKET_OS_DAILY:", run_once(), flush=True)
        except Exception:
            # No credentials/provider bodies in logs. Other services are independent.
            print("MARKET_OS_DAILY: STORE_OR_SOURCE_UNAVAILABLE", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
