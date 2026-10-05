"""Durable, shared API attempts. A committed reservation is never refunded.

All Market Radar OpenAI generation paths must enter request_openai. PostgreSQL
serializes workers/containers; database failure means NO network request.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SCHEMA = """
CREATE TABLE IF NOT EXISTS market_os_api_attempts (
    provider TEXT NOT NULL, budget_day DATE NOT NULL, slot INTEGER NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
    reason TEXT NOT NULL, model TEXT, request_hash TEXT,
    status TEXT NOT NULL DEFAULT 'RESERVED', error_code TEXT,
    input_tokens BIGINT, output_tokens BIGINT, total_tokens BIGINT,
    response_summary TEXT, response_model TEXT,
    PRIMARY KEY(provider,budget_day,slot)
);
CREATE TABLE IF NOT EXISTS market_os_budget_migrations (name TEXT PRIMARY KEY);
CREATE UNIQUE INDEX IF NOT EXISTS market_os_openai_one_per_day
    ON market_os_api_attempts(budget_day) WHERE provider='OPENAI';
"""


class BudgetError(Exception):
    """Fixed public code only; no provider response or credentials."""


def db():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                           connect_timeout=5,
                           options="-c statement_timeout=12000 -c lock_timeout=5000")


def budget_day(now):
    if now.tzinfo is None:
        raise ValueError("timezone required")
    return now.astimezone(KST).date()


def ensure_schema():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419061)")
        cur.execute(SCHEMA)
        cur.execute("SELECT 1 FROM market_os_budget_migrations WHERE name='legacy-openai-v1'")
        if cur.fetchone():
            return
        cur.execute("SELECT to_regclass('public.web_research_runs') AS name")
        if cur.fetchone()["name"]:
            # Import historical attempts, including timeouts, before worker startup.
            # A rolling upgrade must stop old workers first (see deployment guide).
            cur.execute("""INSERT INTO market_os_api_attempts
                (provider,budget_day,slot,attempted_at,reason,model,status)
                SELECT DISTINCT ON ((attempted_at AT TIME ZONE 'Asia/Seoul')::date)
                    'OPENAI',(attempted_at AT TIME ZONE 'Asia/Seoul')::date,1,
                    attempted_at,'LEGACY_WEB_RESEARCH',model,'LEGACY_CONSUMED'
                FROM web_research_runs WHERE attempted_at IS NOT NULL
                ORDER BY (attempted_at AT TIME ZONE 'Asia/Seoul')::date,attempted_at
                ON CONFLICT DO NOTHING""")
        cur.execute("INSERT INTO market_os_budget_migrations VALUES ('legacy-openai-v1')")


def reserve(provider, reason, model=None, request_hash=None, limit=1, min_interval=0):
    """Commit before I/O. DB wall clock is authoritative, never caller's date."""
    if provider not in {"OPENAI", "NAVER"}:
        raise BudgetError("INVALID_PROVIDER")
    limit = 1 if provider == "OPENAI" else max(1, min(25000, int(limit)))
    try:
        ensure_schema()
        with db() as c, c.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("market-os-budget:" + provider,))
            cur.execute("SELECT clock_timestamp() AS now")
            now = cur.fetchone()["now"]
            day = budget_day(now)
            cur.execute("SELECT COUNT(*) AS n, MAX(attempted_at) AS last FROM market_os_api_attempts "
                        "WHERE provider=%s AND budget_day=%s", (provider, day))
            row = cur.fetchone()
            if row["n"] >= limit:
                raise BudgetError("DAILY_BUDGET_USED")
            if row["last"] and (now - row["last"]).total_seconds() < min_interval:
                raise BudgetError("API_COOLDOWN")
            slot = row["n"] + 1
            cur.execute("""INSERT INTO market_os_api_attempts
                (provider,budget_day,slot,attempted_at,reason,model,request_hash)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                        (provider, day, slot, now, reason[:120], model, request_hash))
        return provider, day, slot
    except BudgetError:
        raise
    except Exception:
        raise BudgetError("BUDGET_STORE_UNAVAILABLE") from None


def finish(ticket, status, data=None, error=None):
    data = data if isinstance(data, dict) else {}
    usage = data.get("usage") or {}
    usage = usage if isinstance(usage, dict) else {}
    def tokens(name):
        v = usage.get(name)
        return v if type(v) is int and 0 <= v < 2**63 else None
    texts = [p.get("text", "") for i in data.get("output", []) if isinstance(i, dict)
             for p in i.get("content", []) if isinstance(p, dict) and p.get("type") == "output_text"]
    summary = "\n".join(t for t in texts if isinstance(t, str))[:1200] or None
    with db() as c, c.cursor() as cur:
        cur.execute("""UPDATE market_os_api_attempts SET completed_at=clock_timestamp(),status=%s,
            error_code=%s,input_tokens=%s,output_tokens=%s,total_tokens=%s,
            response_summary=%s,response_model=%s
            WHERE provider=%s AND budget_day=%s AND slot=%s AND status='RESERVED'""",
                    (status, error, tokens("input_tokens"), tokens("output_tokens"), tokens("total_tokens"),
                     summary, str(data.get("model") or "")[:120] or None, *ticket))


def request_openai(payload, key, reason):
    """One HTTP attempt, no retries/redirects/tools in the daily decision path."""
    import requests
    if not key or not payload.get("model"):
        raise BudgetError("AI_NOT_CONFIGURED")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ticket = reserve("OPENAI", reason, payload["model"], digest)
    data = None
    error = None
    try:
        response = requests.post("https://api.openai.com/v1/responses",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                                 json=payload, timeout=(10, 120), allow_redirects=False)
        if response.status_code != 200:
            error = {401: "AUTH_FAILED", 403: "ACCESS_DENIED", 429: "RATE_OR_CREDIT_LIMIT"}.get(
                response.status_code, "PROVIDER_HTTP_ERROR")
        else:
            data = response.json()
            if not isinstance(data, dict) or data.get("status") != "completed":
                error = "INVALID_OR_INCOMPLETE_RESPONSE"
    except requests.RequestException:
        error = "NETWORK_OR_TIMEOUT_UNCERTAIN"
    except (ValueError, TypeError):
        error = "INVALID_PROVIDER_RESPONSE"
    try:
        finish(ticket, "FAILED" if error else "COMPLETED", data, error)
    except Exception:
        # Reservation remains consumed even when completion logging fails.
        raise BudgetError("AUDIT_COMPLETION_UNCERTAIN") from None
    if error:
        raise BudgetError(error)
    return data


def status_today():
    with db() as c, c.cursor() as cur:
        cur.execute("""SELECT provider,budget_day,attempted_at,completed_at,reason,model,status,
            error_code,input_tokens,output_tokens,total_tokens,response_summary,response_model
            FROM market_os_api_attempts
            WHERE budget_day=(clock_timestamp() AT TIME ZONE 'Asia/Seoul')::date
            ORDER BY attempted_at DESC LIMIT 30""")
        return list(cur.fetchall())
