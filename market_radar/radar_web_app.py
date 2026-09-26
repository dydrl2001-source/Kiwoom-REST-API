"""Add isolated, authenticated external research endpoints to the existing app."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import radar_api as base
from web_research_engine import Config, ResearchError, enqueue, ensure_schema, status_payload

app = base.app


def authorize(value: str | None) -> None:
    expected = os.getenv("DASHBOARD_TOKEN", "")
    if not expected or not value or not secrets.compare_digest(expected.encode(), value.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


def prepare_storage() -> None:
    try:
        ensure_schema()
    except Exception as exc:
        # Keep the original dashboard available even when the optional module fails.
        print("web research storage not ready:", type(exc).__name__, flush=True)


app.add_event_handler("startup", prepare_storage)


@app.get("/api/web-research")
def external_research_status(x_dashboard_token: str | None = Header(None)):
    authorize(x_dashboard_token)
    try:
        return status_payload(Config.read())
    except Exception:
        raise HTTPException(status_code=503, detail="WEB_RESEARCH_STORAGE_NOT_READY") from None


class ResearchRequest(BaseModel):
    job_id: int = Field(gt=0)


@app.post("/api/web-research")
def request_external_research(body: ResearchRequest, x_dashboard_token: str | None = Header(None)):
    authorize(x_dashboard_token)
    try:
        return {"run_id": enqueue(body.job_id, Config.read())}
    except ResearchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=503, detail="WEB_RESEARCH_STORAGE_NOT_READY") from None


@app.get("/assets/web-research.js", include_in_schema=False)
def external_research_script():
    return FileResponse(Path(__file__).with_name("web_research_ui.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


# Replace only the HTML route; all existing market and feedback endpoints remain.
for route in list(app.router.routes):
    if getattr(route, "path", None) == "/" and "GET" in (getattr(route, "methods", None) or set()):
        app.router.routes.remove(route)


@app.get("/", response_class=HTMLResponse)
def root():
    html = getattr(base, "DASHBOARD_HTML_V2", None) or base.DASHBOARD_HTML
    script = '<script src="/assets/web-research.js" defer></script>'
    return HTMLResponse(html.replace("</body>", script + "</body>"), headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
