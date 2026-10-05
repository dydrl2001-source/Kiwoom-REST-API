"""Official NAVER search for human verification only; no scraping/AI export.

Search response bodies are neither logged nor persisted. Results retain provider
order/content and source links. Daily packet receives only our own query/links.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, date
import os
import re
from urllib.parse import urlencode

from market_os_budget import BudgetError, KST, finish, reserve

KINDS = {"news": "Verification", "webkr": "Context", "blog": "Discovery"}


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    provider: str = "hub"
    client_id: str = ""
    client_secret: str = ""
    daily_limit: int = 100

    @classmethod
    def read(cls):
        try:
            limit = max(1, min(25000, int(os.getenv("NAVER_SEARCH_DAILY_LIMIT", "100"))))
        except ValueError:
            limit = 100
        return cls(os.getenv("NAVER_SEARCH_ENABLED", "0") == "1", os.getenv("NAVER_SEARCH_PROVIDER", "hub"),
                   os.getenv("NAVER_CLIENT_ID", ""), os.getenv("NAVER_CLIENT_SECRET", ""), limit)


def verification_context(code, name):
    if not re.fullmatch(r"[0-9A-Z]{6}", str(code)):
        raise ValueError("INVALID_CODE")
    query = (str(name or code)[:60] + " " + code).strip()
    return {"query": query, "search_url": "https://search.naver.com/search.naver?" + urlencode({"query": query}),
            "finance_url": "https://finance.naver.com/item/main.naver?" + urlencode({"code": code}),
            "result_content_included": False, "status": "HUMAN_VERIFICATION_ONLY",
            "reason": "NAVER_SEARCH_RESULTS_EXCLUDED_FROM_AI"}


def search(kind, query, cfg=None):
    import requests
    cfg = cfg or Config.read()
    if kind not in KINDS or not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
        return {"status": "INVALID_SEARCH"}
    if not cfg.enabled:
        return {"status": "DISABLED"}
    if not cfg.client_id or not cfg.client_secret:
        return {"status": "NAVER_NOT_CONFIGURED"}
    params = {"query": query.strip(), "display": 5, "start": 1}
    if kind != "webkr":
        params["sort"] = "date"
    if cfg.provider == "hub":
        url = "https://naverapihub.apigw.ntruss.com/search/v1/" + kind
        headers = {"X-NCP-APIGW-API-KEY-ID": cfg.client_id, "X-NCP-APIGW-API-KEY": cfg.client_secret}
        params["format"] = "json"
    elif cfg.provider == "legacy":
        if datetime.now(KST).date() >= date(2027, 7, 1):
            return {"status": "LEGACY_SERVICE_ENDED"}
        url = "https://openapi.naver.com/v1/search/" + kind + ".json"
        headers = {"X-Naver-Client-Id": cfg.client_id, "X-Naver-Client-Secret": cfg.client_secret}
    else:
        return {"status": "INVALID_PROVIDER"}
    try:
        # Aggregate quota across API kinds/containers; response content never enters audit.
        ticket = reserve("NAVER", "HUMAN_" + kind.upper(), limit=cfg.daily_limit, min_interval=1)
    except BudgetError as exc:
        return {"status": str(exc)}
    result = None
    status = "NAVER_NETWORK_ERROR"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=(3, 8), allow_redirects=False)
        if r.status_code == 200:
            data = r.json()
            if (isinstance(data, dict) and isinstance(data.get("items"), list)
                    and all(isinstance(x, dict) for x in data["items"])):
                result = data
                status = "OK"
            else:
                status = "NAVER_INVALID_RESPONSE"
        else:
            status = {401: "NAVER_AUTH_FAILED", 403: "NAVER_PERMISSION_DENIED", 429: "NAVER_QUOTA_EXCEEDED"}.get(
                r.status_code, "NAVER_HTTP_ERROR")
    except (requests.RequestException, ValueError, TypeError):
        status = "NAVER_NETWORK_OR_RESPONSE_ERROR"
    try:
        finish(ticket, "COMPLETED" if status == "OK" else "FAILED", error=None if status == "OK" else status)
    except Exception:
        return {"status": "AUDIT_COMPLETION_UNCERTAIN"}
    return {"status": status, "provider": cfg.provider, "role": KINDS[kind],
            "source_label": "네이버 검색결과", "fetched_at": datetime.now(timezone.utc).isoformat(),
            "human_only": True, "ai_export_allowed": False, "results": result}
