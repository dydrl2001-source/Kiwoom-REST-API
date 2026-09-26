"""Read-only, authenticated-by-caller view of saved external AI reports.

No model import, HTTP request, enqueue, schema write, quota edit or retry.
The report is not a price forecast or a verification of the claimed catalyst.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import os
import re
from urllib.parse import urlsplit

LOOKBACK_DAYS = 7
LIMIT = 50
SQL = """
WITH last_attempt AS (
    SELECT DISTINCT ON (stock_code)
        id,stock_code,stock_name,status,error_code,created_at
    FROM web_research_runs
    WHERE created_at >= now()-interval '7 days'
    ORDER BY stock_code,created_at DESC,id DESC
), selected AS (
    SELECT * FROM last_attempt ORDER BY created_at DESC,id DESC LIMIT 50
)
SELECT a.*, r.id AS report_id,r.completed_at,r.model,r.report,
       r.request_context->>'market_collected_at' AS market_collected_at,
       r.request_context->>'price_bar_at' AS price_bar_at
FROM selected a
LEFT JOIN LATERAL (
    SELECT id,completed_at,model,report,request_context
    FROM web_research_runs
    WHERE stock_code=a.stock_code AND status='CITED_REPORT'
      AND completed_at >= now()-interval '7 days'
    ORDER BY completed_at DESC,id DESC LIMIT 1
) r ON true
ORDER BY a.created_at DESC,a.id DESC
"""
STATES = {'QUEUED','RUNNING','CITED_REPORT','EVIDENCE_INCOMPLETE',
          'ERROR','UNCERTAIN','EXPIRED','CANCELLED'}
ERRORS = {'AUTH_FAILED','ACCESS_DENIED','MODEL_OR_ENDPOINT_UNAVAILABLE',
          'RATE_OR_CREDIT_LIMIT','PROVIDER_HTTP_ERROR','TIMEOUT_UNCERTAIN',
          'NETWORK_UNCERTAIN','INCOMPLETE_RESPONSE','INVALID_PROVIDER_RESPONSE',
          'INVALID_REPORT_TEXT','WORKER_INTERRUPTED'}


def stamp(value):
    try:
        d = datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        if not isinstance(d,datetime) or d.tzinfo is None:
            return None
        return d.astimezone(timezone.utc).isoformat()
    except (ValueError,TypeError):
        return None


def public_link(value):
    if not isinstance(value,str) or len(value)>3000 or re.search(r'[\s\\\x00-\x1f]',value):
        return None
    try:
        u=urlsplit(value); h=(u.hostname or '').lower()
        if u.scheme not in {'http','https'} or u.username or u.password or u.port not in (None,80,443):
            return None
        if '.' not in h or h.endswith(('.local','.localhost','.internal')):
            return None
        try:
            if not ipaddress.ip_address(h).is_global:
                return None
        except ValueError:
            if re.fullmatch(r'[0-9.]+',h):
                return None
        return value
    except ValueError:
        return None


def clean_report(value):
    if not isinstance(value,dict):
        return None
    text=value.get('text')
    calls=value.get('web_tool_calls')
    if not isinstance(text,str) or not 0<len(text)<=40000:
        return None
    if type(calls) is not int or calls<1:
        return None
    citations=[]
    raw=value.get('citations')
    for x in raw[:200] if isinstance(raw,list) else []:
        if not isinstance(x,dict):
            continue
        start,end=x.get('start'),x.get('end'); url=public_link(x.get('url'))
        if url and type(start) is int and type(end) is int and 0<=start<end<=len(text):
            citations.append({'start':start,'end':end,'url':url,'title':str(x.get('title') or url)[:300]})
    if not citations:
        return None
    sources={x['url']:{'url':x['url'],'title':x['title']} for x in citations}
    return {'text':text,'citations':sorted(citations,key=lambda x:x['start']),
            'sources':list(sources.values()),'web_tool_calls':calls}


def present(row, now):
    code=str(row.get('stock_code') or '')
    if not re.fullmatch(r'[0-9A-Z]{6}',code):
        return None
    report=clean_report(row.get('report'))
    completed=stamp(row.get('completed_at')) if report else None
    age=None
    if completed:
        age=int((now-datetime.fromisoformat(completed)).total_seconds())
        if age<0:
            age=None
    state=row.get('status')
    error=row.get('error_code')
    return {
        'code':code,'name':str(row.get('stock_name') or code)[:80],
        'latest_attempt_id':row.get('id'),
        'latest_state':state if state in STATES else 'UNKNOWN',
        'latest_error':(error if error in ERRORS else 'OTHER_ERROR') if error else None,
        'latest_attempt_at':stamp(row.get('created_at')),
        'report_id':row.get('report_id') if report else None,
        'report_completed_at':completed,'report_age_sec':age,
        'older_than_6h':bool(age is not None and age>21600),
        'model':str(row.get('model') or '')[:100] if report else None,
        'market_collected_at':stamp(row.get('market_collected_at')) if report else None,
        'price_bar_at':stamp(row.get('price_bar_at')) if report else None,
        'report':report,
    }


def library_payload():
    import psycopg
    from psycopg.rows import dict_row
    now=datetime.now(timezone.utc)
    payload={'mode':'READ_ONLY','generated_at':now.isoformat(),
             'lookback_days':LOOKBACK_DAYS,'max_stocks':LIMIT,'entries':[],'storage':'READY'}
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=5,
                        options='-c statement_timeout=12000 -c lock_timeout=3000') as c, c.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SELECT to_regclass('public.web_research_runs') AS name")
        if cur.fetchone()['name'] is None:
            payload['storage']='NOT_INITIALIZED'
            return payload
        cur.execute(SQL)
        payload['entries']=[p for r in cur.fetchall() if (p:=present(r,now)) is not None]
    return payload
