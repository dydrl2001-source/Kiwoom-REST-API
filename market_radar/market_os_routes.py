"""Authenticated Market OS dashboard routes."""
from pathlib import Path
import re
import threading
import time

from fastapi import Header,HTTPException
from fastapi.responses import FileResponse,HTMLResponse,JSONResponse
from fastapi.encoders import jsonable_encoder

_lock=threading.Lock()
_cache=None
_cache_at=0


def install(app,authorize):
    @app.get("/assets/market-os-readonly.js",include_in_schema=False)
    def readonly_script():
        return FileResponse(Path(__file__).with_name("market_os_readonly.js"),
                            media_type="application/javascript",headers={"Cache-Control":"no-cache"})
    @app.get("/api/market-os/readonly-context")
    def readonly_context(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        from market_os_readonly import latest
        try:
            return JSONResponse(latest(),headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="READONLY_CONTEXT_UNAVAILABLE") from None

    @app.post("/api/market-os/readonly-refresh")
    def readonly_refresh(codes:str="",x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        from market_os_readonly import ReadError,refresh
        selected=[x.strip() for x in codes.split(",") if x.strip()]
        if len(selected)>5 or any(not re.fullmatch(r"[0-9]{6}",x) for x in selected):
            raise HTTPException(400,detail="INVALID_CODES_MAX_FIVE")
        try:
            return JSONResponse(refresh(selected),headers={"Cache-Control":"no-store"})
        except ReadError as exc:
            raise HTTPException(503,detail=str(exc)) from None
        except Exception:
            raise HTTPException(503,detail="READONLY_CONTEXT_UNAVAILABLE") from None

    @app.get("/api/market-os/daily-decision")
    def daily_decision(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        try:
            from market_os_daily import latest
            from market_os_budget import status_today
            return JSONResponse(jsonable_encoder({"daily":latest(),"api_attempts":status_today(),
                "live_auto_execution":False}),headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="DAILY_DECISION_NOT_READY") from None

    @app.get("/api/market-os/decision-preview")
    def decision_preview(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        try:
            from flow_store import desk_payload
            from market_os_packet import build_packet
            from market_os_readonly import enrich_payload
            return JSONResponse(build_packet(enrich_payload(desk_payload(include_tracking=False))),
                                headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="DECISION_SOURCE_NOT_READY") from None

    @app.post("/api/market-os/naver-search")
    def naver_search(query:str,kind:str="news",x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        from market_os_naver import search
        # Explicit human action only; dashboard polling never calls a search API.
        return JSONResponse(search(kind,query),headers={"Cache-Control":"no-store"})

    @app.get("/market-os/decision",include_in_schema=False)
    def decision_page():
        return FileResponse(Path(__file__).with_name("market_os_decision.html"),
                            media_type="text/html",headers={"Cache-Control":"no-store"})

    @app.get("/assets/market-os-decision.js",include_in_schema=False)
    def decision_script():
        return FileResponse(Path(__file__).with_name("market_os_decision.js"),
                            media_type="application/javascript",headers={"Cache-Control":"no-cache"})

    @app.get("/api/market-os")
    def market_os_dashboard(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        try:
            global _cache,_cache_at
            from market_os_store import learning_payload
            with _lock:
                if _cache is None or time.monotonic()-_cache_at>20:
                    _cache=learning_payload();_cache_at=time.monotonic()
                payload=_cache
            return JSONResponse(jsonable_encoder(payload),headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="MARKET_OS_DATA_NOT_READY") from None

    @app.get("/api/market-os/live-health")
    def market_os_live_health(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        try:
            from market_os_live_validation import payload
            return JSONResponse(jsonable_encoder(payload()),headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="MARKET_OS_LIVE_HEALTH_NOT_READY") from None

    @app.get("/api/market-os/history/{code}")
    def market_os_history(code:str,x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        if not re.fullmatch(r"[0-9A-Z]{6}",code):
            raise HTTPException(400,detail="INVALID_CODE")
        try:
            from market_os_store import history_payload
            return JSONResponse(jsonable_encoder(history_payload(code)),headers={"Cache-Control":"no-store"})
        except Exception:
            raise HTTPException(503,detail="MARKET_OS_HISTORY_NOT_READY") from None

    @app.get("/assets/market-os.js",include_in_schema=False)
    def market_os_script():
        return FileResponse(Path(__file__).with_name("market_os_ui.js"),
                            media_type="application/javascript",headers={"Cache-Control":"no-cache"})

    originals=[r for r in app.router.routes if getattr(r,"path",None)=="/" and "GET" in (getattr(r,"methods",None) or ())]
    original=originals[-1].endpoint if originals else None
    if not original:return
    for r in originals:app.router.routes.remove(r)

    @app.get("/",response_class=HTMLResponse)
    def root():
        response=original()
        html=response.body.decode("utf-8")
        return HTMLResponse(html.replace("</body>",'<script src="/assets/market-os.js" defer></script></body>'),
                            headers={"Cache-Control":"no-store"})
