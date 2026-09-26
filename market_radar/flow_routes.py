"""Isolated, authenticated flow desk routes. Import does not connect to a database."""
from pathlib import Path
import re
import threading
import time
from fastapi import Header,HTTPException
from fastapi.responses import FileResponse,HTMLResponse,JSONResponse
from fastapi.encoders import jsonable_encoder

_lock=threading.Lock()
_cached=None
_cached_at=0


def install(app,authorize):
    @app.get('/api/flow-desk')
    def flow_desk(x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        try:
            global _cached,_cached_at
            from flow_store import desk_payload
            with _lock:
                if _cached is None or time.monotonic()-_cached_at>20:
                    result=desk_payload()
                    _cached=result;_cached_at=time.monotonic()
                payload=_cached
            return JSONResponse(jsonable_encoder(payload),headers={'Cache-Control':'no-store'})
        except Exception:
            raise HTTPException(503,detail='FLOW_DATA_NOT_READY') from None

    @app.get('/api/flow-chart/{code}')
    def flow_chart(code:str,interval:int=3,x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        if not re.fullmatch(r'[0-9A-Z]{6}',code) or interval not in (1,3,5,10,15,30,60):
            raise HTTPException(400,detail='INVALID_CHART_REQUEST')
        try:
            from flow_store import chart_payload
            return JSONResponse(jsonable_encoder(chart_payload(code,interval)),headers={'Cache-Control':'no-store'})
        except Exception:
            raise HTTPException(503,detail='CHART_DATA_NOT_READY') from None

    @app.post('/api/flow-chart-request/{code}')
    def flow_chart_request(code:str,x_dashboard_token:str|None=Header(None)):
        authorize(x_dashboard_token)
        if not re.fullmatch(r'[0-9A-Z]{6}',code):raise HTTPException(400,detail='INVALID_CODE')
        from flow_store import db,exists
        try:
            with db() as c,c.cursor() as cur:
                if not exists(cur,'radar_chart_requests'):raise HTTPException(409,detail='CHART_WORKER_NOT_READY')
                if not exists(cur,'stock_master'):raise HTTPException(409,detail='STOCK_MASTER_NOT_READY')
                cur.execute('SELECT 1 FROM stock_master WHERE stock_code=%s',(code,))
                if not cur.fetchone():raise HTTPException(404,detail='UNKNOWN_STOCK')
                cur.execute('INSERT INTO radar_chart_requests(stock_code,requested_at) VALUES(%s,now()) '
                            'ON CONFLICT(stock_code) DO UPDATE SET requested_at=now()', (code,))
            return {'status':'PRIORITIZED','notice':'차트 수집 대상에 추가. 키움 주문·유료 AI 호출 없음'}
        except HTTPException:raise
        except Exception:raise HTTPException(503,detail='CHART_QUEUE_UNAVAILABLE') from None

    @app.get('/assets/flow-desk.js',include_in_schema=False)
    def flow_script():
        return FileResponse(Path(__file__).with_name('flow_ui.js'),media_type='application/javascript',headers={'Cache-Control':'no-cache'})

    originals=[r for r in app.router.routes if getattr(r,'path',None)=='/' and 'GET' in (getattr(r,'methods',None) or ())]
    original=originals[-1].endpoint if originals else None
    if not original:return
    for r in originals:app.router.routes.remove(r)
    @app.get('/',response_class=HTMLResponse)
    def root():
        response=original()
        html=response.body.decode('utf-8')
        return HTMLResponse(html.replace('</body>','<script src="/assets/flow-desk.js" defer></script></body>'),headers={'Cache-Control':'no-store'})
