"""Market Radar flow storage and read-only views. No orders or paid API calls."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone,timedelta
import json
import os
import re
from flow_core import quote, metrics, group_rows, segment, dt, event_from_report, report_sections, SPEC, VERSION

SCHEMA='''
CREATE TABLE IF NOT EXISTS radar_flow_quotes (
 batch_time TIMESTAMPTZ NOT NULL, stock_code TEXT NOT NULL, payload JSONB NOT NULL,
 PRIMARY KEY(batch_time,stock_code)
);
CREATE INDEX IF NOT EXISTS radar_flow_code_time ON radar_flow_quotes(stock_code,batch_time DESC);
CREATE TABLE IF NOT EXISTS radar_flow_status (
 id INTEGER PRIMARY KEY CHECK(id=1), updated_at TIMESTAMPTZ NOT NULL,
 status TEXT NOT NULL, note TEXT
);
'''


def db(read_only=False):
    import psycopg
    from psycopg.rows import dict_row
    c=psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,connect_timeout=5,
       options='-c statement_timeout=15000 -c lock_timeout=3000')
    if read_only:c.execute('SET TRANSACTION READ ONLY')
    return c


def exists(cur,name):
    cur.execute('SELECT to_regclass(%s) AS name',('public.'+name,))
    return cur.fetchone()['name'] is not None


def schema():
    with db() as c,c.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(72419065)')
        cur.execute(SCHEMA)


def save_batch(batch_time,raw_records,rank_map,trade_rank_map,stock_meta):
    batch_time=dt(batch_time)
    rows=[]
    for code,raw in raw_records.items():
        data=quote(raw['response'],raw['received_at'],code)
        if not data:continue
        data.update({'batch_time':batch_time.isoformat(),'query_rank':rank_map.get(code),
                     'trade_rank':trade_rank_map.get(code),
                     'official_sector':(stock_meta.get(code) or {}).get('sector')})
        rows.append((batch_time,code,json.dumps(data,ensure_ascii=False)))
    with db() as c,c.cursor() as cur:
        cur.executemany('INSERT INTO radar_flow_quotes(batch_time,stock_code,payload) VALUES(%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',rows)
        cur.execute("INSERT INTO radar_flow_status(id,updated_at,status,note) VALUES(1,now(),%s,%s) "
                    "ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,note=excluded.note",
                    ('OK' if rows else 'EMPTY','SOR quotes='+str(len(rows))))
    return len(rows)


def latest_history(cur):
    if not exists(cur,'radar_flow_quotes'):return {},None
    cur.execute('SELECT MAX(batch_time) AS t FROM radar_flow_quotes')
    newest=cur.fetchone()['t']
    if newest is None:return {},None
    cur.execute('SELECT stock_code,payload FROM radar_flow_quotes WHERE batch_time>=%s AND batch_time<=%s ORDER BY batch_time,stock_code',
                (newest-timedelta(minutes=12),newest))
    histories=defaultdict(list)
    for r in cur.fetchall():histories[r['stock_code']].append(r['payload'])
    # Rows that vanished from the selected sample are not current observations.
    histories={code:h for code,h in histories.items() if dt(h[-1].get('batch_time'))==newest}
    return histories,newest


def saved_reports(cur,codes):
    if not codes or not exists(cur,'web_research_runs'):return {}
    from report_library import clean_report
    cur.execute("SELECT DISTINCT ON(stock_code) stock_code,id,completed_at,model,report,request_context "
                "FROM web_research_runs WHERE stock_code=ANY(%s) AND status='CITED_REPORT' "
                "AND completed_at>now()-interval '7 days' ORDER BY stock_code,completed_at DESC,id DESC",(list(codes),))
    out={}
    for r in cur.fetchall():
        report=clean_report(r['report'])
        if report:
            ctx=r['request_context'] or {}
            out[r['stock_code']]={'id':r['id'],'completed_at':r['completed_at'].isoformat(),
                'model':r['model'],'report':report,'sections':report_sections(report),
                'market_collected_at':ctx.get('market_collected_at'),'price_bar_at':ctx.get('price_bar_at')}
    return out


def public_leads(cur,codes):
    """Leads for coverage and links, NOT explanations of price movement."""
    out=defaultdict(list)
    if not codes:return out
    if exists(cur,'stock_news_cache'):
        cur.execute("SELECT stock_code,title,source,published_at,link FROM (SELECT *,row_number() OVER "
                    "(PARTITION BY stock_code ORDER BY published_at DESC NULLS LAST) AS n FROM stock_news_cache "
                    "WHERE stock_code=ANY(%s) AND published_at>now()-interval '3 days') a WHERE n<=4",(list(codes),))
        for r in cur.fetchall():
            out[r['stock_code']].append({'kind':'NEWS_TITLE_ONLY','title':r['title'],'source':r['source'],
                'at':r['published_at'].isoformat() if r['published_at'] else None,'url':r['link']})
    if exists(cur,'dart_disclosures'):
        cur.execute("SELECT stock_code,report_nm,rcept_dt,disclosure_url FROM (SELECT *,row_number() OVER "
                    "(PARTITION BY stock_code ORDER BY rcept_dt DESC,rcept_no DESC) n FROM dart_disclosures "
                    "WHERE stock_code=ANY(%s) AND rcept_dt>=current_date-7) a WHERE n<=3",(list(codes),))
        for r in cur.fetchall():
            out[r['stock_code']].append({'kind':'DART_LIST_ONLY','title':r['report_nm'],'source':'DART',
                'at':r['rcept_dt'].isoformat() if r['rcept_dt'] else None,'url':r['disclosure_url']})
    return out


def desk_payload():
    now=datetime.now(timezone.utc)
    with db(True) as c,c.cursor() as cur:
        history,newest=latest_history(cur)
        reports=saved_reports(cur,history)
        leads=public_leads(cur,history)
        automation={'enabled':False,'notice':'설정 미확인'}
        try:
            from web_research_engine import Config, usage_count
            cfg=Config.read()
            automation={**cfg.public(),'notice':'설정 상태이며 인증 성공 보증이 아닙니다.'}
            if exists(cur,'web_research_runs'):
                automation['usage']=usage_count(cur)
        except (ImportError,KeyError):
            pass
    rows=[]
    for code,h in history.items():
        r=metrics(h,now);top,fine,classification=segment(code,r['name'],r.get('official_sector'))
        r.update({'sector':top,'segment':top+' > '+fine,'classification':classification})
        report=reports.get(code)
        # The report's age must never be hidden behind a current price refresh.
        fresh_report=bool(report and 0<=(now-dt(report['completed_at'])).total_seconds()<=21600)
        r['event_type']=event_from_report(report['report']) if fresh_report else None
        r['research']=report
        r['research_state']='CITED_SAVED' if report else 'ANALYSIS_PENDING'
        r['research_stale']=bool(report and not fresh_report)
        r['leads']=leads.get(code,[])
        r.pop('comparison_prior',None)
        rows.append(r)
    rows.sort(key=lambda x:(x.get('interval_turnover_krw') is None,-(x.get('interval_turnover_krw') or 0)))
    by_catalyst,coverage=group_rows(rows,history,'catalyst')
    by_sector,_=group_rows(rows,history,'sector')
    recent=sum(r['recent_trade'] for r in rows)
    return {'generated_at':now.isoformat(),'sample_time':newest.isoformat() if newest else None,
            'refresh_target_seconds':30,'status':'RECENT_TRADES' if recent else 'NO_RECENT_TRADE_OR_WAITING',
            'rows':rows,'catalyst_groups':by_catalyst,'sector_groups':by_sector,
            'automation':automation,'coverage':coverage,'recent_trade_count':recent,'unit_version':VERSION,'unit_source':SPEC,
            'notice':'누적대금 차이와 거래비중 변화입니다. 순매수·자금 유입/유출을 의미하지 않습니다. '
                     '표본 진입·날짜변경·거래소범위변경은 폭증으로 계산하지 않습니다.'}


def chart_payload(code,interval=3):
    if not re.fullmatch(r'[0-9A-Z]{6}',code):raise ValueError('INVALID_CODE')
    if interval not in (1,3,5,10,15,30,60):raise ValueError('INVALID_INTERVAL')
    now=datetime.now(timezone.utc);minute=[];daily=[];state=None
    with db(True) as c, c.cursor() as cur:
        if exists(cur,'market_minute_bars'):
            cur.execute('SELECT bar_time,open_price,high_price,low_price,close_price,volume FROM market_minute_bars '
                        'WHERE stock_code=%s AND interval_min=%s ORDER BY bar_time DESC LIMIT 160',(code,interval))
            for r in reversed(cur.fetchall()):
                minute.append({'time':r['bar_time'].isoformat(),
                    'open':float(r['open_price']) if r['open_price'] is not None else None,
                    'high':float(r['high_price']) if r['high_price'] is not None else None,
                    'low':float(r['low_price']) if r['low_price'] is not None else None,
                    'close':float(r['close_price']) if r['close_price'] is not None else None,
                    'volume':float(r['volume']) if r['volume'] is not None else None,
                    'provisional':r['bar_time']+timedelta(minutes=interval)>now})
        if exists(cur,'market_daily_bars'):
            cur.execute('SELECT trade_date,open_price,high_price,low_price,close_price,volume FROM market_daily_bars '
                        'WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 160',(code,))
            for r in reversed(cur.fetchall()):
                daily.append({'time':r['trade_date'].isoformat(),
                    'open':float(r['open_price']) if r['open_price'] is not None else None,
                    'high':float(r['high_price']) if r['high_price'] is not None else None,
                    'low':float(r['low_price']) if r['low_price'] is not None else None,
                    'close':float(r['close_price']) if r['close_price'] is not None else None,
                    'volume':float(r['volume']) if r['volume'] is not None else None,
                    'provisional':r['trade_date']>=now.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).date()})
        if exists(cur,'chart_states'):
            cur.execute('SELECT state_ko,minute_trend,daily_context,snapshot_time FROM chart_states '
                        'WHERE stock_code=%s ORDER BY snapshot_time DESC LIMIT 1',(code,))
            r=cur.fetchone()
            if r:state={**r,'snapshot_time':r['snapshot_time'].isoformat()}
    return {'code':code,'minute_interval':interval,'minute':minute,'daily':daily,'mimosa':state,
            'price_source':'기존 chart-feed의 KRX 차트; 통합(SOR) 거래대금과 거래소 범위가 다릅니다.',
            'notice':'저장된 OHLCV만 표시. 조회 버튼은 키움 또는 유료 AI API를 직접 호출하지 않습니다. '
                     '차트 대상 수집범위 밖이면 빈 상태로 표시하며 데이터가 없는 가격을 만들어내지 않습니다.'}
