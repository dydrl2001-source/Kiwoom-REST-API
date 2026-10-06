"""Optional local-only context dashboard; independent of existing collectors."""
import hmac
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from market_os_routes import install

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def authorize(value):
    token = os.environ.get("DASHBOARD_TOKEN", "")
    if not token or not isinstance(value, str) or not hmac.compare_digest(value, token):
        raise HTTPException(401, detail="UNAUTHORIZED")


install(app, authorize)


@app.get("/")
def root():
    return RedirectResponse("/market-os/decision")
