"""Market Radar flow storage and read-only views. No orders or paid API calls."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone,timedelta
import json
import os
import re
from flow_core import quote, metrics, group_rows, rotation_series, candidate_watchlist, reversal_signals, segment, dt, event_from_report, report_sections, SPEC, VERSION, KST
from market_os_rule_engine import market_os_watchlist, VERSION as MARKET_OS_VERSION

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
        data=quote(raw['response'],raw['received_at'],code,(stock_meta.get(code) or {}).get('listed_shares'))
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


def latest_chart_states(cur,codes):
    out={}
    if not codes or not exists(cur,'chart_states'):return out
    cur.execute("""SELECT DISTINCT ON(stock_code)
                    stock_code,state,state_ko,score,minute_trend,daily_context,snapshot_time
                   FROM chart_states
                   WHERE stock_code=ANY(%s) AND snapshot_time>now()-interval '15 minutes'
                   ORDER BY stock_code,snapshot_time DESC""",(list(codes),))
    for r in cur.fetchall():
        out[r['stock_code']]={'state':r['state'],'state_ko':r['state_ko'],
            'score':r['score'],'minute_trend':r['minute_trend'],
            'daily_context':r['daily_context'],
            'snapshot_time':r['snapshot_time'].isoformat() if r['snapshot_time'] else None}
    return out


def latest_strategy_signals(cur,codes):
    out=defaultdict(dict)
    if not codes or not exists(cur,'mimosa_strategy_signals'):return out
    cur.execute("""SELECT DISTINCT ON(stock_code,strategy)
                    stock_code,strategy,state,state_ko,score,metrics,reasons,source_note,snapshot_time
                   FROM mimosa_strategy_signals
                   WHERE stock_code=ANY(%s) AND snapshot_time>now()-interval '15 minutes'
                   ORDER BY stock_code,strategy,snapshot_time DESC""",(list(codes),))
    for r in cur.fetchall():
        out[r['stock_code']][r['strategy']]={
            'state':r['state'],'state_ko':r['state_ko'],'score':r['score'],
            'metrics':r['metrics'] or {},'reasons':r['reasons'] or [],
            'source_note':r['source_note'],
            'snapshot_time':r['snapshot_time'].isoformat() if r['snapshot_time'] else None
        }
    return out


def theme_memberships(cur,codes):
    out=defaultdict(list)
    if not codes or not exists(cur,'stock_theme_memberships'):return out
    cur.execute("""SELECT stock_code,theme_code,theme_name,theme_change_rate,period_return,stock_count,refreshed_at
                   FROM stock_theme_memberships
                   WHERE stock_code=ANY(%s) AND refreshed_at>now()-interval '3 days'
                   ORDER BY stock_code,ABS(COALESCE(theme_change_rate,0)) DESC,theme_name""",(list(codes),))
    for r in cur.fetchall():
        out[r['stock_code']].append({
            'code':r['theme_code'],'name':r['theme_name'],
            'change_pct':r['theme_change_rate'],'period_return':r['period_return'],
            'stock_count':r['stock_count'],
            'refreshed_at':r['refreshed_at'].isoformat() if r['refreshed_at'] else None
        })
    return out



def latest_market_regime(cur):
    if not exists(cur,'market_regime_snapshots'):
        return None
    cur.execute("""SELECT snapshot_time,candidate_trend_state,candidate_flow_state,candidate_sentiment_state,
                    candidate_label,stable_label,confidence,data_freshness_sec,rank_turnover_5m,
                    top5_trade_share,top10_trade_share,top_sector_share,top3_sector_share,
                    largecap_trade_share,positive_rank_share,avg_rank_change_rate,sector_count_top20
                   FROM market_regime_snapshots ORDER BY snapshot_time DESC LIMIT 1""")
    r=cur.fetchone()
    if not r:return None
    snap=r['snapshot_time'];now=datetime.now(timezone.utc)
    age=max(0,int((now-snap).total_seconds())) if snap else None
    freshness=r['data_freshness_sec']
    stale=bool((freshness is not None and freshness>120) or (age is not None and age>150))
    return {
        'snapshot_time':snap.isoformat() if snap else None,
        'candidate_trend_state':r['candidate_trend_state'],
        'candidate_flow_state':r['candidate_flow_state'],
        'candidate_sentiment_state':r['candidate_sentiment_state'],
        'candidate_label':r['candidate_label'],'stable_label':r['stable_label'],
        'confidence':r['confidence'],'data_freshness_sec':freshness,
        'snapshot_age_sec':age,'stale':stale,
        'rank_turnover_5m':r['rank_turnover_5m'],
        'top5_trade_share':r['top5_trade_share'],'top10_trade_share':r['top10_trade_share'],
        'top_sector_share':r['top_sector_share'],'top3_sector_share':r['top3_sector_share'],
        'largecap_trade_share':r['largecap_trade_share'],
        'positive_rank_share':r['positive_rank_share'],
        'avg_rank_change_rate':r['avg_rank_change_rate'],
        'sector_count_top20':r['sector_count_top20']
    }


def candidate_tracking_payload(current_candidates, now, sample_time):
    """Enrich current candidates with persistence history.

    History contains only prior local observation candidates. It is not a
    backtest, fill simulation, recommendation record or model probability.
    """
    base={'status':'NOT_INITIALIZED','current_count':len(current_candidates),
          'recent_dropouts':[],'theme_persistence':[],'state_counts':{}}
    current_time=dt(sample_time) or now
    current_codes={x.get('code') for x in current_candidates if x.get('code')}
    with db(True) as c,c.cursor() as cur:
        if not exists(cur,'radar_candidate_history'):
            return base
        cur.execute("""SELECT updated_at,status,last_sample_time,candidate_count,rows_written,note
                       FROM radar_candidate_tracker_status WHERE id=1""")
        tracker=cur.fetchone() if exists(cur,'radar_candidate_tracker_status') else None
        base['status']=tracker['status'] if tracker else 'READY_NO_STATUS'
        if tracker:
            base['tracker']={
                'updated_at':tracker['updated_at'].isoformat() if tracker['updated_at'] else None,
                'last_sample_time':tracker['last_sample_time'].isoformat() if tracker['last_sample_time'] else None,
                'candidate_count':tracker['candidate_count'],'rows_written':tracker['rows_written']
            }

        cur.execute("""SELECT snapshot_time,stock_code,stock_name,attention_score,label,primary_type,
                              market_theme,price_krw,change_pct,interval_turnover_krw,
                              burst_multiple,event_type,chart_state
                       FROM radar_candidate_history
                       WHERE snapshot_time >= %s
                       ORDER BY stock_code,snapshot_time""",(now-timedelta(minutes=60),))
        recent=cur.fetchall()

        first_today={}
        if current_codes:
            day_start=now.astimezone(KST).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
            cur.execute("""SELECT DISTINCT ON(stock_code)
                              stock_code,snapshot_time,attention_score,price_krw
                           FROM radar_candidate_history
                           WHERE stock_code=ANY(%s) AND snapshot_time >= %s
                           ORDER BY stock_code,snapshot_time""",(list(current_codes),day_start))
            first_today={r['stock_code']:r for r in cur.fetchall()}

    grouped=defaultdict(list)
    for r in recent:
        grouped[r['stock_code']].append(r)

    state_counts=defaultdict(int)
    for x in current_candidates:
        code=x.get('code')
        h=[r for r in grouped.get(code,[]) if r['snapshot_time'] < current_time-timedelta(seconds=1)]
        h.sort(key=lambda r:r['snapshot_time'])
        chain=1
        chain_start=current_time
        prev=current_time
        for r in reversed(h):
            gap=(prev-r['snapshot_time']).total_seconds()
            if 0 <= gap <= 75:
                chain+=1;chain_start=r['snapshot_time'];prev=r['snapshot_time']
            else:
                break
        prior_gap=(current_time-h[-1]['snapshot_time']).total_seconds() if h else None
        returned=bool(h and prior_gap is not None and prior_gap>120)
        first=first_today.get(code)
        first_seen=first['snapshot_time'] if first else current_time
        # If the tracker has already written this exact market sample, it is still
        # the candidate's first appearance rather than an instant transition to "유지".
        is_new=(not first) or abs((current_time-first['snapshot_time']).total_seconds())<=1

        def hits(minutes):
            cutoff=current_time-timedelta(minutes=minutes)
            return 1+sum(1 for r in h if r['snapshot_time']>=cutoff)

        target=current_time-timedelta(minutes=5)
        near=[r for r in h if 240 <= (current_time-r['snapshot_time']).total_seconds() <= 420]
        prior5=min(near,key=lambda r:abs((r['snapshot_time']-target).total_seconds())) if near else None
        delta5=(x.get('attention_score')-prior5['attention_score']) if prior5 else None

        if is_new:
            state='신규'
        elif returned:
            state='재진입'
        elif chain>=5 and delta5 is not None and delta5>=10:
            state='강화'
        elif chain>=5 and delta5 is not None and delta5<=-10:
            state='약화'
        elif chain>=5:
            state='연속 유지'
        else:
            state='유지'
        state_counts[state]+=1

        series=[{'time':r['snapshot_time'].isoformat(),'value':r['attention_score']} for r in h[-19:]]
        series.append({'time':current_time.isoformat(),'value':x.get('attention_score')})
        x['tracking']={
            'state':state,'first_seen_at':first_seen.isoformat(),
            'consecutive_hits':chain,
            'continuous_minutes':round(max(0,(current_time-chain_start).total_seconds())/60,1),
            'hits_5m':hits(5),'hits_15m':hits(15),'hits_30m':hits(30),
            'score_delta_5m':delta5,
            'max_score_30m':max([x.get('attention_score') or 0]+[
                r['attention_score'] for r in h
                if r['snapshot_time']>=current_time-timedelta(minutes=30)]),
            'score_series':series
        }

    # Candidates that were present recently but do not meet the current top-watch criteria.
    dropouts=[]
    for code,h in grouped.items():
        if code in current_codes or not h:continue
        last=h[-1];age=(current_time-last['snapshot_time']).total_seconds()
        if 0 <= age <= 300:
            dropouts.append({
                'code':code,'name':last['stock_name'],'last_seen_at':last['snapshot_time'].isoformat(),
                'age_sec':round(age),'last_score':last['attention_score'],
                'primary_type':last['primary_type'],'market_theme':last['market_theme'],
                'last_change_pct':last['change_pct'],
                'note':'현재 관찰후보 기준 미충족; 하락·매도 신호를 뜻하지 않음'
            })
    dropouts.sort(key=lambda x:(x['age_sec'],-x['last_score']))
    base['recent_dropouts']=dropouts[:10]

    # Theme persistence is based on the top observation-candidate history, not all market stocks.
    themes=defaultdict(list)
    for r in recent:
        if r['market_theme']:
            themes[r['market_theme']].append(r)
    current_theme_counts=defaultdict(int)
    for x in current_candidates:
        if x.get('market_theme'):current_theme_counts[x['market_theme']]+=1
    theme_rows=[]
    for name,h in themes.items():
        last=max(r['snapshot_time'] for r in h)
        h30=[r for r in h if r['snapshot_time']>=current_time-timedelta(minutes=30)]
        h15=[r for r in h if r['snapshot_time']>=current_time-timedelta(minutes=15)]
        h5=[r for r in h if r['snapshot_time']>=current_time-timedelta(minutes=5)]
        prev5=[r for r in h if current_time-timedelta(minutes=10)<=r['snapshot_time']<current_time-timedelta(minutes=5)]
        avg5=sum(r['attention_score'] for r in h5)/len(h5) if h5 else None
        avgprev=sum(r['attention_score'] for r in prev5)/len(prev5) if prev5 else None
        d=(avg5-avgprev) if avg5 is not None and avgprev is not None else None
        current_count=current_theme_counts.get(name,0)
        if current_count and d is not None and d>=5:st='후보군 강화'
        elif current_count and d is not None and d<=-5:st='후보군 약화'
        elif current_count:st='후보군 지속'
        elif 0 <= (current_time-last).total_seconds() <= 300:st='최근 후보군 이탈'
        else:st='과거 관찰'
        theme_rows.append({
            'theme':name,'state':st,'current_candidates':current_count,
            'distinct_stocks_30m':len({r['stock_code'] for r in h30}),
            'hits_5m':len(h5),'hits_15m':len(h15),'hits_30m':len(h30),
            'avg_score_5m':round(avg5,1) if avg5 is not None else None,
            'score_change_5m':round(d,1) if d is not None else None,
            'last_seen_at':last.isoformat()
        })
    theme_rows.sort(key=lambda x:(-x['current_candidates'],-x['hits_15m'],-(x['avg_score_5m'] or 0)))
    base['theme_persistence']=theme_rows[:10]
    base['state_counts']=dict(state_counts)
    base['meaning']='후보 노출 지속성 기록; 수익확률·매수신호·체결성과가 아님'
    return base


def candidate_journal_payload(now):
    """Read prospective candidate episodes and observed price-path outcomes."""
    base={'status':'NOT_INITIALIZED','episodes':[],'summary':[],
          'completed_5m':0,'completed_15m':0,'completed_30m':0,
          'notice':'관찰 후보 등장시점의 SOR 참조가격 경로. 실제 체결·실현손익·추천 성과가 아님'}
    with db(True) as c,c.cursor() as cur:
        if not exists(cur,'radar_candidate_episodes') or not exists(cur,'radar_candidate_outcomes'):
            return base
        base['status']='READY'
        cur.execute("""SELECT e.id,e.stock_code,e.stock_name,e.started_at,e.last_seen_at,e.ended_at,e.status,
                              e.candidate_version,e.entry_score,e.last_score,e.peak_score,e.entry_price_krw,
                              e.entry_change_pct,e.primary_type,e.watch_types,e.market_theme,e.event_type,
                              e.chart_state,e.query_rank,e.trade_rank,
                              o.h5_state,o.h5_at,o.h5_price_krw,o.return_5m_pct,o.mfe_5m_pct,o.mae_5m_pct,
                              o.h15_state,o.h15_at,o.h15_price_krw,o.return_15m_pct,o.mfe_15m_pct,o.mae_15m_pct,
                              o.h30_state,o.h30_at,o.h30_price_krw,o.return_30m_pct,o.mfe_30m_pct,o.mae_30m_pct,
                              o.exit_at,o.exit_price_krw,o.exit_return_pct
                       FROM radar_candidate_episodes e
                       JOIN radar_candidate_outcomes o ON o.episode_id=e.id
                       WHERE e.started_at >= now()-interval '1 day'
                       ORDER BY e.started_at DESC
                       LIMIT 40""")
        episodes=[]
        for r in cur.fetchall():
            def f(v):
                try:return float(v) if v is not None else None
                except (TypeError,ValueError):return None
            episodes.append({
                'id':r['id'],'code':r['stock_code'],'name':r['stock_name'],
                'started_at':r['started_at'].isoformat(),'last_seen_at':r['last_seen_at'].isoformat(),
                'ended_at':r['ended_at'].isoformat() if r['ended_at'] else None,'status':r['status'],
                'candidate_version':r['candidate_version'],'entry_score':r['entry_score'],
                'last_score':r['last_score'],'peak_score':r['peak_score'],
                'entry_price_krw':f(r['entry_price_krw']),'entry_change_pct':f(r['entry_change_pct']),
                'primary_type':r['primary_type'],'watch_types':r['watch_types'] or [],
                'market_theme':r['market_theme'],'event_type':r['event_type'],
                'chart_state':r['chart_state'],'query_rank':r['query_rank'],'trade_rank':r['trade_rank'],
                'horizons':{
                    '5':{'state':r['h5_state'],'at':r['h5_at'].isoformat() if r['h5_at'] else None,
                         'price_krw':f(r['h5_price_krw']),'return_pct':f(r['return_5m_pct']),
                         'mfe_pct':f(r['mfe_5m_pct']),'mae_pct':f(r['mae_5m_pct'])},
                    '15':{'state':r['h15_state'],'at':r['h15_at'].isoformat() if r['h15_at'] else None,
                          'price_krw':f(r['h15_price_krw']),'return_pct':f(r['return_15m_pct']),
                          'mfe_pct':f(r['mfe_15m_pct']),'mae_pct':f(r['mae_15m_pct'])},
                    '30':{'state':r['h30_state'],'at':r['h30_at'].isoformat() if r['h30_at'] else None,
                          'price_krw':f(r['h30_price_krw']),'return_pct':f(r['return_30m_pct']),
                          'mfe_pct':f(r['mfe_30m_pct']),'mae_pct':f(r['mae_30m_pct'])},
                },
                'exit':{'at':r['exit_at'].isoformat() if r['exit_at'] else None,
                        'price_krw':f(r['exit_price_krw']),'return_pct':f(r['exit_return_pct'])}
            })
        base['episodes']=episodes
        base['completed_5m']=sum(x['horizons']['5']['state']=='READY' for x in episodes)
        base['completed_15m']=sum(x['horizons']['15']['state']=='READY' for x in episodes)
        base['completed_30m']=sum(x['horizons']['30']['state']=='READY' for x in episodes)

        cur.execute("""SELECT e.candidate_version,e.primary_type,
                              COUNT(*) FILTER(WHERE o.h5_state='READY') AS n5,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.return_5m_pct)
                                FILTER(WHERE o.h5_state='READY') AS median_r5,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mfe_5m_pct)
                                FILTER(WHERE o.h5_state='READY') AS median_mfe5,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mae_5m_pct)
                                FILTER(WHERE o.h5_state='READY') AS median_mae5,
                              COUNT(*) FILTER(WHERE o.h15_state='READY') AS n15,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.return_15m_pct)
                                FILTER(WHERE o.h15_state='READY') AS median_r15,
                              AVG(CASE WHEN o.h15_state='READY' THEN CASE WHEN o.return_15m_pct>0 THEN 1.0 ELSE 0.0 END END) AS positive15,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mfe_15m_pct)
                                FILTER(WHERE o.h15_state='READY') AS median_mfe15,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mae_15m_pct)
                                FILTER(WHERE o.h15_state='READY') AS median_mae15,
                              COUNT(*) FILTER(WHERE o.h30_state='READY') AS n30,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.return_30m_pct)
                                FILTER(WHERE o.h30_state='READY') AS median_r30,
                              AVG(CASE WHEN o.h30_state='READY' THEN CASE WHEN o.return_30m_pct>0 THEN 1.0 ELSE 0.0 END END) AS positive30,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mfe_30m_pct)
                                FILTER(WHERE o.h30_state='READY') AS median_mfe30,
                              percentile_cont(0.5) WITHIN GROUP(ORDER BY o.mae_30m_pct)
                                FILTER(WHERE o.h30_state='READY') AS median_mae30
                       FROM radar_candidate_episodes e
                       JOIN radar_candidate_outcomes o ON o.episode_id=e.id
                       WHERE e.started_at >= now()-interval '30 days'
                       GROUP BY e.candidate_version,e.primary_type
                       ORDER BY e.candidate_version,e.primary_type""")
        summary=[]
        for r in cur.fetchall():
            def f(v):
                try:return float(v) if v is not None else None
                except (TypeError,ValueError):return None
            summary.append({
                'candidate_version':r['candidate_version'],'primary_type':r['primary_type'],
                'n5':int(r['n5'] or 0),'median_return_5m_pct':f(r['median_r5']),
                'median_mfe_5m_pct':f(r['median_mfe5']),'median_mae_5m_pct':f(r['median_mae5']),
                'n15':int(r['n15'] or 0),'median_return_15m_pct':f(r['median_r15']),
                'positive_15m_pct':f(r['positive15'])*100 if r['positive15'] is not None else None,
                'median_mfe_15m_pct':f(r['median_mfe15']),'median_mae_15m_pct':f(r['median_mae15']),
                'n30':int(r['n30'] or 0),'median_return_30m_pct':f(r['median_r30']),
                'positive_30m_pct':f(r['positive30'])*100 if r['positive30'] is not None else None,
                'median_mfe_30m_pct':f(r['median_mfe30']),'median_mae_30m_pct':f(r['median_mae30']),
                'small_sample':int(r['n15'] or 0)<10
            })
        base['summary']=summary
    return base

def desk_payload(include_tracking=True):
    now=datetime.now(timezone.utc)
    with db(True) as c,c.cursor() as cur:
        history,newest=latest_history(cur)
        reports=saved_reports(cur,history)
        leads=public_leads(cur,history)
        themes=theme_memberships(cur,history)
        charts=latest_chart_states(cur,history)
        strategies=latest_strategy_signals(cur,history)
        market_regime=latest_market_regime(cur)
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
        tm=themes.get(code,[])
        primary_theme=(tm[0]['name'] if tm else None)
        r.update({'sector':top,'segment':top+' > '+fine,'classification':classification,
                  'themes':tm[:8],'market_theme':primary_theme,
                  'market_group':primary_theme or top+' > '+fine,
                  'chart':charts.get(code),'strategy_signals':strategies.get(code,{})})
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
    by_theme,_=group_rows(rows,history,'theme')
    by_sector,_=group_rows(rows,history,'sector')
    rotation=rotation_series(rows,history,10)
    candidates=candidate_watchlist(rows,rotation,12)
    market_os=market_os_watchlist(rows,rotation,market_regime,12)
    tracking=candidate_tracking_payload(candidates,now,newest) if include_tracking else {
        'status':'SKIPPED_FOR_SNAPSHOT','current_count':len(candidates),
        'recent_dropouts':[],'theme_persistence':[],'state_counts':{}
    }
    journal=candidate_journal_payload(now) if include_tracking else {
        'status':'SKIPPED_FOR_SNAPSHOT','episodes':[],'summary':[],
        'completed_5m':0,'completed_15m':0,'completed_30m':0
    }
    recent=sum(r['recent_trade'] for r in rows)
    theme_mapped=sum(1 for r in rows if r.get('market_theme'))
    return {'generated_at':now.isoformat(),'sample_time':newest.isoformat() if newest else None,
            'refresh_target_seconds':30,'status':'RECENT_TRADES' if recent else 'NO_RECENT_TRADE_OR_WAITING',
            'rows':rows,'catalyst_groups':by_catalyst,'theme_groups':by_theme,'sector_groups':by_sector,
            'theme_rotation':rotation,'watch_candidates':candidates,'candidate_tracking':tracking,
            'candidate_journal':journal,
            'market_os_watchlist':market_os,'market_regime':market_regime,'market_os_version':MARKET_OS_VERSION,
            'automation':automation,'coverage':{**coverage,'theme_mapped_stocks':theme_mapped,'observed_stocks':len(rows)},
            'recent_trade_count':recent,'unit_version':VERSION,'unit_source':SPEC,
            'notice':'누적대금 차이와 거래비중 변화입니다. 순매수·자금 유입/유출을 의미하지 않습니다. '
                     '시장테마는 Kiwoom 테마그룹 소속이며 가격 원인으로 단정하지 않습니다. '
                     '표본 진입·날짜변경·거래소범위변경은 폭증으로 계산하지 않습니다.'}


def chart_payload(code,interval=3):
    if not re.fullmatch(r'[0-9A-Z]{6}',code):raise ValueError('INVALID_CODE')
    if interval not in (1,3,5,10,15,30,60):raise ValueError('INVALID_INTERVAL')
    now=datetime.now(timezone.utc);minute=[];daily=[];state=None;strategies={}
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
        if exists(cur,'mimosa_strategy_signals'):
            cur.execute("""SELECT DISTINCT ON(strategy) strategy,state,state_ko,score,reasons,snapshot_time
                           FROM mimosa_strategy_signals
                           WHERE stock_code=%s AND snapshot_time>now()-interval '15 minutes'
                           ORDER BY strategy,snapshot_time DESC""",(code,))
            for r in cur.fetchall():
                strategies[r['strategy']]={'state':r['state'],'state_ko':r['state_ko'],
                    'score':r['score'],'reasons':r['reasons'] or [],
                    'snapshot_time':r['snapshot_time'].isoformat() if r['snapshot_time'] else None}
    minute_signals=reversal_signals(minute,strategies)
    daily_signals=reversal_signals(daily,{})
    return {'code':code,'minute_interval':interval,'minute':minute,'daily':daily,'mimosa':state,
            'strategies':strategies,'minute_reversal_signals':minute_signals,'daily_reversal_signals':daily_signals,
            'price_source':'기존 chart-feed의 KRX 차트; 통합(SOR) 거래대금과 거래소 범위가 다릅니다.',
            'notice':'저장된 OHLCV만 표시. 고점/바닥 표시는 복합 관찰 신호이며 정확한 고점·바닥 예측이나 매수·매도 지시가 아닙니다. '
                     '조회 버튼은 키움 주문 또는 유료 AI API를 직접 호출하지 않습니다.'}
