"""Read-only Kiwoom investor/account context. No order endpoint exists here.

Account identifiers and order identifiers are discarded before persistence.
Account data must never be exported to an LLM. Daily loss remains unknown until
an independently verified day-opening equity/cash-flow baseline is available.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
import re
import time
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
READS = {"ka10059": ("/api/dostk/stkinfo", "stk_invsr_orgn"),
         "kt00018": ("/api/dostk/acnt", "acnt_evlt_remn_indv_tot"),
         "ka10074": ("/api/dostk/acnt", "dt_rlzt_pl"),
         "ka10075": ("/api/dostk/acnt", "oso"),
         "kt00017": ("/api/dostk/acnt", None)}


class ReadError(Exception):
    """Fixed error codes; never expose HTTP bodies, credentials or identifiers."""


def numeric(value, multiplier=1):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value).strip().replace(",", "")) * multiplier
        value = float(n) if n.is_finite() else None
        return value if value is not None and math.isfinite(value) else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


class Client:
    def __init__(self, env=None, transport=None):
        self.env = os.environ if env is None else env
        self.http = transport or requests.Session()
        mode = self.env.get("KIWOOM_MODE")
        if mode not in {"real", "mock"}:
            raise ReadError("KIWOOM_MODE_NOT_CONFIGURED")
        self.mode = mode
        self.base = "https://api.kiwoom.com" if mode == "real" else "https://mockapi.kiwoom.com"
        self.key = self.env.get("APP_KEY" if mode == "real" else "APP_KEY_MOCK")
        self.secret = self.env.get("APP_SECRET" if mode == "real" else "APP_SECRET_MOCK")
        if not self.key or not self.secret:
            raise ReadError("KIWOOM_KEYS_MISSING")
        self.token = None
        self.last_call = 0.0

    def _post(self, path, body, headers=None):
        time.sleep(max(0, .3 - (time.monotonic() - self.last_call)))
        self.last_call = time.monotonic()
        try:
            r = self.http.post(self.base + path, json=body, headers=headers or {},
                               timeout=(5, 20), allow_redirects=False)
            if r.status_code != 200:
                raise ReadError("KIWOOM_HTTP_" + str(r.status_code))
            d = r.json()
            if not isinstance(d, dict) or str(d.get("return_code")) != "0":
                raise ReadError("KIWOOM_API_REJECTED")
            return d, r.headers
        except (requests.RequestException, ValueError):
            raise ReadError("KIWOOM_TRANSPORT_OR_JSON_ERROR") from None

    def read(self, api_id, body, max_pages=10):
        # Validate before issuing even an authentication request.
        if api_id not in READS:
            raise ReadError("READ_ONLY_API_REQUIRED")
        if not self.token:
            auth, _ = self._post("/oauth2/token", {"grant_type": "client_credentials",
                               "appkey": self.key, "secretkey": self.secret})
            self.token = auth.get("token")
            if not isinstance(self.token, str) or not self.token:
                raise ReadError("KIWOOM_TOKEN_MISSING")
        path, list_key = READS[api_id]
        headers = {"authorization": "Bearer " + self.token, "api-id": api_id}
        result, rows, seen = None, [], set()
        for _ in range(max_pages):
            d, h = self._post(path, body, headers)
            if result is None:
                result = d.copy()
            if list_key:
                if not isinstance(d.get(list_key), list) or any(not isinstance(x, dict) for x in d[list_key]):
                    raise ReadError("KIWOOM_ROWS_MISSING")
                rows.extend(d[list_key])
            continuation = str(h.get("cont-yn", "")).upper()
            if continuation == "N":
                if list_key:
                    result[list_key] = rows
                return result
            # Investor date context deliberately needs only the newest page.
            if api_id == "ka10059" and continuation == "Y":
                result[list_key] = rows
                return result
            key = h.get("next-key")
            if continuation != "Y" or not key or key in seen:
                raise ReadError("KIWOOM_INCOMPLETE_PAGINATION")
            seen.add(key)
            headers.update({"cont-yn": "Y", "next-key": key})
        raise ReadError("KIWOOM_INCOMPLETE_PAGINATION")


def investor_context(data, requested_day, fetched_at):
    valid = []
    for r in data.get("stk_invsr_orgn", []):
        try:
            day = datetime.strptime(str(r.get("dt")), "%Y%m%d").date()
        except (TypeError, ValueError):
            continue
        if day <= requested_day:
            valid.append((day, r))
    if not valid:
        return {"status": "NO_DATED_INVESTOR_DATA", "foreign": None, "institution": None}
    day, row = max(valid, key=lambda x: x[0])
    def item(key):
        value = numeric(row.get(key), 1_000_000)
        return {"source": "KIWOOM", "api_id": "ka10059", "net_buy_krw": value,
                "as_of": day.isoformat(), "fetched_at": fetched_at,
                "status": ("CURRENT_DATE_CONTEXT" if day == requested_day else "PRIOR_SESSION_CONTEXT")
                          if value is not None else "VALUE_MISSING",
                "source_unit": "million_KRW", "is_intraday_trigger": False}
    return {"status": "CONNECTED", "foreign": item("frgnr_invsr"), "institution": item("orgn")}


def collect(codes, client=None, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone required")
    if len(codes) > 5 or any(not re.fullmatch(r"[0-9]{6}", str(c)) for c in codes):
        raise ReadError("INVALID_CODES_MAX_FIVE")
    client = client or Client()
    day = now.astimezone(KST).date()
    date_arg = day.strftime("%Y%m%d")
    # Timestamp the beginning, never the end, of the multi-request observation.
    at = now.isoformat()
    out = {"schema_version": "kiwoom-readonly-v1", "fetched_at": at,
           "requested_day_kst": day.isoformat(), "investor": {}, "account": {},
           "errors": {}, "live_auto_execution": False, "orders_sent": 0}
    mode = getattr(client, "mode", "unknown")
    out["kiwoom_mode"] = mode if mode in ("real", "mock") else "unknown"
    for code in dict.fromkeys(codes):
        try:
            d = client.read("ka10059", {"dt": date_arg, "stk_cd": code,
                            "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"})
            out["investor"][code] = investor_context(d, day, at)
        except ReadError as exc:
            out["errors"]["investor_" + code] = str(exc)
    a = out["account"]
    try:
        d = client.read("kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        a.update({"as_of": at, "estimated_assets_krw": numeric(d.get("prsm_dpst_aset_amt")),
                  "valuation_krw": numeric(d.get("tot_evlt_amt")),
                  "unrealized_pl_krw": numeric(d.get("tot_evlt_pl")),
                  "loan_krw": numeric(d.get("tot_loan_amt")),
                  "position_count": len(d["acnt_evlt_remn_indv_tot"]), "valuation_scope": "KRX"})
    except ReadError as exc:
        out["errors"]["valuation"] = str(exc)
    try:
        d = client.read("ka10074", {"strt_dt": date_arg, "end_dt": date_arg})
        dated = [r for r in d["dt_rlzt_pl"] if r.get("dt") == date_arg]
        # Do not turn a prior-session response (including holidays) into today's P/L.
        values = [numeric(r.get("tdy_sel_pl")) for r in dated]
        a["realized_pl_day"] = day.isoformat() if dated else None
        a["realized_pl_krw"] = sum(values) if values and all(v is not None for v in values) else None
    except ReadError as exc:
        out["errors"]["realized_pl"] = str(exc)
    try:
        d = client.read("ka10075", {"all_stk_tp": "0", "trde_tp": "0", "stk_cd": "", "stex_tp": "0"})
        codes_with_orders = set()
        count = 0
        for r in d["oso"]:
            qty = numeric(r.get("oso_qty"))
            code = str(r.get("stk_cd", "")).removeprefix("A")
            if qty is None or qty < 0 or not re.fullmatch(r"[0-9]{6}", code):
                raise ReadError("KIWOOM_UNFILLED_ROW_INVALID")
            if qty > 0:
                codes_with_orders.add(code)
                count += 1
        a.update({"unfilled_as_of": at, "unfilled_complete": True,
                  "unfilled_count": count, "unfilled_codes": sorted(codes_with_orders)})
    except ReadError as exc:
        out["errors"]["unfilled"] = str(exc)
    try:
        d = client.read("kt00017", {})
        a["cash_d2_krw"] = numeric(d.get("d2_entra"))
        a["cash_d2_as_of"] = at
    except ReadError as exc:
        out["errors"]["cash"] = str(exc)
    a["daily_loss_pct"] = None
    a["daily_loss_status"] = "VERIFIED_OPENING_EQUITY_AND_CASHFLOWS_REQUIRED"
    return out


SCHEMA = """CREATE TABLE IF NOT EXISTS market_os_readonly_context (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
    updated_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL
)"""


def latest():
    from market_os_budget import db
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.market_os_readonly_context') AS name")
        if not cur.fetchone()["name"]:
            return {}
        cur.execute("SELECT payload FROM market_os_readonly_context WHERE singleton")
        row = cur.fetchone()
        return row["payload"] if row else {}


def refresh(codes):
    from market_os_budget import db
    if os.environ.get("MARKET_OS_READONLY_ENABLED", "0") != "1":
        raise ReadError("READONLY_CONNECTOR_DISABLED")
    with db() as c, c.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("SELECT pg_try_advisory_xact_lock(72419065) AS acquired")
        if not cur.fetchone()["acquired"]:
            raise ReadError("READONLY_REFRESH_BUSY")
        cur.execute("SELECT updated_at FROM market_os_readonly_context WHERE singleton")
        previous = cur.fetchone()
        now = datetime.now(timezone.utc)
        if previous and (now - previous["updated_at"]).total_seconds() < 30:
            raise ReadError("READONLY_REFRESH_COOLDOWN")
        snapshot = collect(codes, now=now)
        cur.execute("""INSERT INTO market_os_readonly_context(singleton,updated_at,payload)
            VALUES(TRUE,%s,%s::jsonb) ON CONFLICT(singleton) DO UPDATE
            SET updated_at=EXCLUDED.updated_at,payload=EXCLUDED.payload""",
                    (now, json.dumps(snapshot, allow_nan=False)))
    return snapshot


def enrich_payload(payload, snapshot=None):
    """Attach only public investor context and minimal risk facts, not account values."""
    from market_os_risk import fresh
    now = datetime.now(timezone.utc)
    if snapshot is None:
        try:
            snapshot = latest()
        except Exception:
            snapshot = {}
    a = snapshot.get("account", {})
    if snapshot.get("kiwoom_mode") != "real":
        snapshot, a = {}, {}
    for row in payload.get("rows", []):
        code = row.get("code")
        context = snapshot.get("investor", {}).get(code, {})
        row["investor_context"] = context
        f = {"account_as_of": a.get("as_of"), "daily_loss_pct": None,
             "duplicate_as_of": a.get("unfilled_as_of"), "duplicate_order": None}
        if a.get("unfilled_complete") is True and fresh(a.get("unfilled_as_of"), now):
            f["duplicate_order"] = code in a.get("unfilled_codes", [])
        row["readonly_risk_facts"] = f
    return payload
