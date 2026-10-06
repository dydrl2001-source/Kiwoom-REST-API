"""Authenticated HTTP surface for the read-only EOD review bridge."""
import hmac
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from market_review_bridge import build_session_export, ro_db

app = FastAPI(title="Market Review Bridge", docs_url=None, redoc_url=None, openapi_url=None)


def authorize(value):
    expected = os.getenv("REVIEW_BRIDGE_TOKEN", "")
    if not expected or not isinstance(value, str) or not hmac.compare_digest(value, expected):
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")


@app.get("/health")
def health():
    try:
        with ro_db() as c, c.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return {"status": "ok", "mode": "read-only", "orders": False}
    except Exception:
        return JSONResponse({"status": "error", "mode": "read-only"}, status_code=503)


@app.get("/review/session/{session_date}")
def review_session(session_date: str, x_review_token: str | None = Header(None)):
    authorize(x_review_token)
    try:
        day = date.fromisoformat(session_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="INVALID_SESSION_DATE")
    try:
        return build_session_export(day)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/review/latest")
def review_latest(x_review_token: str | None = Header(None)):
    authorize(x_review_token)
    # Never fabricate a prior session as today's data; latest means current KST date.
    return build_session_export(datetime.now(ZoneInfo("Asia/Seoul")).date())
