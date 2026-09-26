"""Autonomous selection, not autonomous budget expansion.
Reuses the original paid-call ledger, locks, quotas and no-retry behavior.
Only public market observations leave the machine. No Telegram text is exported.
"""
from datetime import datetime,timezone,timedelta
import json
import math
import web_research_engine as base
from flow_core import EVENTS,dt
from flow_store import desk_payload,db,exists

_original_request=base.make_request
_original_context=base.public_context
_original_fresh=base.fresh_for_auto


def priority(row):
    if not row.get('recent_trade') or row.get('sector')=='ETF·ETN':return 0
    if row.get('interval_turnover_krw') is None or row.get('interval_turnover_krw',0)<=0:return 0
    score=0
    if (row.get('burst_multiple') or 0)>=3:score+=45
    if row.get('query_rank') and row['query_rank']<=10:score+=20
    if row.get('trade_rank') and row['trade_rank']<=20:score+=15
    if abs(row.get('change_pct') or 0)>=10:score+=10
    if not row.get('research'):score+=20
    return min(score,100)


def enrich_context(cur,job_id):
    ctx=_original_context(cur,job_id)
    if base.exists(cur,'radar_flow_quotes'):
        cur.execute('SELECT payload FROM radar_flow_quotes WHERE stock_code=%s AND batch_time<=%s '
                    'ORDER BY batch_time DESC LIMIT 1',(ctx['stock_code'],ctx['market_collected_at']))
        r=cur.fetchone()
        if r:
            q=r['payload'];clean={k:q.get(k) for k in ('trade_date','venue','received_at','exchange_at','unit_version','quality_flags')}
            if not q.get('quality_flags'):
                clean.update({k:q.get(k) for k in ('turnover_krw','cap_krw')})
            ctx['flow_observation']=clean
    return ctx


def request(ctx,cfg):
    out=_original_request(ctx,cfg)
    data=json.loads(out['input'])
    obs=ctx.get('flow_observation')
    if isinstance(obs,dict):
        allowed=('trade_date','venue','received_at','exchange_at','unit_version','quality_flags','turnover_krw','cap_krw')
        data['flow_observation']={k:obs[k] for k in allowed if k in obs}
    out['input']=json.dumps(data,ensure_ascii=False)
    out['instructions']+='\n추가 출력 규칙: 첫 줄에 `재료분류: 종류`를 쓴다. 종류는 '+', '.join(EVENTS)+' 중 하나만 사용한다. '
    out['instructions']+='이는 AI의 재료분류이지 확정 원인이 아니다. 해당 종목의 현재 사건을 원문으로 뒷받침하지 못하면 기타·미확인이다. '
    out['instructions']+='이어 기존 네 제목으로 사건·새로운 변화·시장 동시관측·미확인을 종합한다. 기사 제목을 그대로 핵심 요약으로 쓰지 않는다. '
    out['instructions']+='새 flow_observation 금액은 명시된 SOR 범위와 출처 단위로 변환한 로컬 관측이다. 이전 관측과 혼합하지 않는다. '
    out['instructions']+='이 금액은 순유입·순매수를 나타내지 않는다. 빈 quality_flags도 경제적 의미나 인과관계의 검증 완료가 아니다.'
    return out


def fresh_for_auto(ctx,now=None):
    t=dt((ctx.get('flow_observation') or {}).get('exchange_at'))
    if t:return 0<=((now or datetime.now(timezone.utc))-t).total_seconds()<=120
    return _original_fresh(ctx,now)


def auto_enqueue(cfg):
    if not cfg.automatic or cfg.gate()!='READY':return
    # Never create new automatic jobs when this worker's attempt budget is already spent.
    with base.db() as c,c.cursor() as cur:
        counts=base.usage_count(cur)
        if counts['daily']>=cfg.daily_limit or counts['hourly']>=cfg.hourly_limit:return
        if not base.exists(cur,'research_jobs'):return
    desk=desk_payload();ranked=sorted(desk['rows'],key=priority,reverse=True)
    for row in ranked[:3]:
        score=priority(row)
        if score<55:continue
        # Reuse a recent report unless a genuinely later public lead appeared.
        report=row.get('research');done=dt(report['completed_at']) if report else None
        new_lead=any(dt(x.get('at')) and done and dt(x['at'])>done for x in row.get('leads',[]))
        if done and datetime.now(timezone.utc)-done<timedelta(hours=6) and not new_lead:continue
        with db() as c,c.cursor() as cur:
            cur.execute('SELECT id FROM research_jobs WHERE stock_code=%s AND snapshot_time>now()-interval \'90 seconds\' '
                        'ORDER BY created_at DESC LIMIT 1',(row['code'],))
            prior=cur.fetchone()
            if prior:job_id=prior['id']
            else:
                cur.execute("INSERT INTO research_jobs(snapshot_time,stock_code,stock_name,priority,trigger_types,status,context) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb,'FLOW_AUTO_SELECTED','{}'::jsonb) RETURNING id",
                    (row['batch_time'],row['code'],row['name'],score,json.dumps(['30초 대금 관측','재료 검증 우선'],ensure_ascii=False)))
                job_id=cur.fetchone()['id']
        try:base.enqueue(job_id,cfg,automatic=True)
        except base.ResearchError:pass

if __name__=='__main__':
    base.make_request=request;base.public_context=enrich_context;base.auto_enqueue=auto_enqueue;base.fresh_for_auto=fresh_for_auto
    base.main()
