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
