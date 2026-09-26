"""Pure observations for Market Radar flow desk; never net capital flow.

Money fields are normalized by internal consistency checks against price, volume and listed shares.
The raw Kiwoom values and chosen scales are retained so the first live session can be reconciled with HTS.
Observation windows use actual sample receipt times; first appearances are not bursts.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
SPEC = 'https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/kiwoom/_data/kiwoom_api_spec.json'
VERSION = 'sor-money-v2-validated'
# Editable business segments, not assertions about today's price catalyst.
# Initial operational registry; unknowns retain official sector, never guessed from other companies.
SEGMENTS = {
 '005930':('반도체','메모리·종합반도체'), '000660':('반도체','메모리·HBM'),
 '005935':('반도체','메모리·종합반도체'), '042700':('반도체','후공정 장비'),
 '319660':('반도체','전공정 장비'), '240810':('반도체','전공정 장비'),
 '036930':('반도체','전공정 장비'), '039030':('반도체','전공정 장비'),
 '089030':('반도체','후공정 장비'), '058470':('반도체','검사·소모품'),
 '222800':('전자부품','반도체 패키지기판'), '007810':('전자부품','PCB·패키지기판'),
 '353200':('전자부품','PCB·패키지기판'), '356860':('전자부품','메모리 모듈 PCB'),
 '007660':('전자부품','고다층 PCB'), '009150':('전자부품','MLCC·패키지기판'),
 '001440':('전력','전선·케이블'), '000500':('전력','전선·케이블'),
 '010120':('전력','전력기기'), '267260':('전력','변압기·전력기기'),
 '298040':('전력','변압기·전력기기'), '034020':('에너지설비','원전·가스터빈'),
 '052690':('에너지설비','발전 설계'), '003490':('운송','항공'),
 '005380':('자동차','완성차'), '000270':('자동차','완성차'),
 '066570':('전자','가전·냉난방'), '035420':('인터넷','플랫폼'),
 '035720':('인터넷','플랫폼'), '006400':('배터리','배터리·전자재료'),
 '373220':('배터리','이차전지'), '247540':('배터리','양극재'),
 '196170':('바이오','신약·기술이전'), '086520':('배터리','지주·소재'),
}
EVENTS = ('수주·공급계약','실적·가이던스','기술·제품·양산','정책·규제',
          '승인·임상','자본·주주환원','업황·가격','인수·사업재편','기타·미확인')
ETF_PREFIX = ('KODEX ','TIGER ','RISE ','ACE ','SOL ','HANARO ','KOSEF ',
              'TIMEFOLIO ','PLUS ','ARIRANG ','KIWOOM ','KBSTAR ','1Q ')


def dt(value):
    try:
        value = datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        return value.astimezone(timezone.utc) if isinstance(value,datetime) and value.tzinfo else None
    except (TypeError,ValueError):
        return None


def num(value):
    try:
        x=Decimal(str(value).replace(',','').strip())
        return x if x.is_finite() else None
    except (InvalidOperation,ValueError,TypeError):
        return None


def amount(value, multiplier=1):
    n=num(value)
    return int(n*multiplier) if n is not None and n>=0 else None


def resolve_turnover(raw_value, volume, low, high, current):
    """Resolve raw turnover without trusting a magnitude threshold.

    Candidate scales are tested against cumulative volume × the day's price range.
    If the response lacks enough reference fields or no candidate is plausible,
    the normalized value is withheld rather than guessed.
    """
    raw=num(raw_value)
    if raw is None or raw < 0:
        return None,None,'TURNOVER_MISSING'
    if raw == 0:
        return 0,1,'OK'
    if not volume:
        return None,None,'TURNOVER_UNIT_UNRESOLVED'
    prices=[abs(float(x)) for x in (low,high,current) if x is not None and float(x)!=0]
    if not prices:
        return None,None,'TURNOVER_UNIT_UNRESOLVED'
    lo=min(prices)*volume
    hi=max(prices)*volume
    # Cumulative trade value should live near price*volume. Wide tolerance handles
    # asynchronous response fields and auction/after-hours prints without inventing a unit.
    lower=max(0,lo*.72-5_000_000)
    upper=hi*1.28+5_000_000
    midpoint=(lo+hi)/2 if hi else lo
    candidates=[]
    for scale in (1,1_000,10_000,1_000_000,100_000_000):
        value=float(raw)*scale
        if lower <= value <= upper:
            score=abs(value-midpoint)/(midpoint or 1)
            candidates.append((score,scale,int(value)))
    if not candidates:
        return None,None,'TURNOVER_REFERENCE_MISMATCH'
    _,scale,value=min(candidates)
    return value,scale,'OK'


def resolve_cap(raw_value, shares, current):
    """Resolve market-cap units by reconciling with current price × listed shares."""
    raw=num(raw_value)
    if raw is None or raw < 0:
        return None,None,'CAP_MISSING'
    if raw == 0:
        return 0,1,'OK'
    if not shares or current is None or float(current)==0:
        return None,None,'CAP_UNIT_UNRESOLVED'
    expected=abs(float(current))*shares
    candidates=[]
    for scale in (1,1_000,10_000,1_000_000,100_000_000):
        value=float(raw)*scale
        rel=abs(value/expected-1) if expected else 99
        if rel <= .20:
            candidates.append((rel,scale,int(value)))
    if not candidates:
        return None,None,'CAP_REFERENCE_MISMATCH'
    _,scale,value=min(candidates)
    return value,scale,'OK'


def quote(raw, received_at, code=None):
    """Only non-secret response fields are retained. No magnitude-based unit guesses."""
    received_at=dt(received_at)
    code=code or re.sub(r'_(AL|NX)$','',str(raw.get('stk_cd','')))
    if not re.fullmatch(r'[0-9A-Z]{6}',code) or not received_at:
        return None
    day=str(raw.get('dt') or '')
    trade_date=None; exchange=None
    try:
        trade_date=datetime.strptime(day,'%Y%m%d').date()
        clock=str(raw.get('cntr_tm') or '')
        if re.fullmatch(r'\d{6}',clock):
            exchange=datetime.strptime(day+clock,'%Y%m%d%H%M%S').replace(tzinfo=KST).astimezone(timezone.utc)
    except ValueError:
        trade_date=None
    px=num(raw.get('cur_prc')); vol=amount(raw.get('trde_qty'))
    low=num(raw.get('low_pric')); high=num(raw.get('high_pric')); shares=amount(raw.get('stkcnt'))
    tv,tv_scale,tv_state=resolve_turnover(raw.get('trde_prica'),vol,low,high,px)
    cap,cap_scale,cap_state=resolve_cap(raw.get('mac'),shares,px)
    flags=[]
    if not trade_date: flags.append('TRADE_DATE_MISSING')
    if exchange and exchange>received_at+timedelta(seconds=60): flags.append('EXCHANGE_CLOCK_FUTURE')
    if tv_state!='OK': flags.append(tv_state)
    if cap_state!='OK': flags.append(cap_state)
    return {'code':code,'name':str(raw.get('stk_nm') or code)[:80],
            'received_at':received_at.isoformat(),'trade_date':trade_date.isoformat() if trade_date else None,
            'exchange_at':exchange.isoformat() if exchange else None,'venue':'SOR','source':'ka10095',
            'unit_version':VERSION,'turnover_krw':tv,'cap_krw':cap,
            'turnover_scale':tv_scale,'cap_scale':cap_scale,
            'price_krw':float(abs(px)) if px is not None else None,
            'change_pct':float(num(raw.get('flu_rt'))) if num(raw.get('flu_rt')) is not None else None,
            'volume':vol,'raw_turnover':str(raw.get('trde_prica',''))[:40],
            'raw_cap':str(raw.get('mac',''))[:40],'quality_flags':flags}


def segment(code,name='',official=None):
    if name.upper().startswith(ETF_PREFIX) or ' ETN' in name.upper():
        return 'ETF·ETN','상장지수상품','NAME_HEURISTIC'
    if code in SEGMENTS:
        top,fine=SEGMENTS[code];return top,fine,'CURATED_V1'
    return official or '업종 미확인', '세부 분류 대기', 'OFFICIAL_FALLBACK'


def delta(new,old,min_seconds=15,max_seconds=90):
    if not old:return None,'NO_BASELINE',None
    a,b=dt(new.get('received_at')),dt(old.get('received_at'))
    if not a or not b:return None,'MISSING_TIME',None
    sec=(a-b).total_seconds()
    if not min_seconds<=sec<=max_seconds:return None,'WINDOW_GAP',sec
    keys=('trade_date','venue','source','unit_version')
    if any(not new.get(k) or new.get(k)!=old.get(k) for k in keys):
        return None,'SESSION_OR_SOURCE_CHANGED',sec
    nv,ov=new.get('turnover_krw'),old.get('turnover_krw')
    if nv is None or ov is None:return None,'MISSING_VALUE',sec
    if any(str(x).startswith('TURNOVER_') for x in (new.get('quality_flags') or [])):
        return None,'VALUE_CHECK_FAILED',sec
    if nv<ov:return None,'COUNTER_RESET_OR_CORRECTION',sec
    # Stale exchange time alone is not an outage (illiquid instruments may not trade).
    na,oa=dt(new.get('exchange_at')),dt(old.get('exchange_at'))
    if na and oa and na<oa:return None,'EXCHANGE_CLOCK_REVERSED',sec
    return nv-ov,'OK',sec


def metrics(history, now=None):
    now=dt(now) or datetime.now(timezone.utc)
    h=sorted(history,key=lambda x:dt(x.get('received_at')) or datetime.min.replace(tzinfo=timezone.utc))
    if not h:return {}
    current=h[-1];previous=h[-2] if len(h)>1 else None
    value,state,sec=delta(current,previous)
    rates=[]
    for a,b in zip(h[1:-1],h[:-2]):
        v,s,t=delta(a,b)
        if s=='OK':rates.append(v/t)
    base=median(rates[-10:]) if len(rates)>=5 else None
    burst=(value/sec/base) if value is not None and sec and base and base>0 else None
    fivemin=None;five_seconds=None
    target=dt(current['received_at'])-timedelta(minutes=5)
    candidates=[x for x in h[:-1] if dt(x['received_at'])<=target]
    if candidates:
        fivemin,_,five_seconds=delta(current,candidates[-1],min_seconds=285,max_seconds=390)
    exchange=dt(current.get('exchange_at'))
    sampled=dt(current.get('received_at'))
    fresh=bool(sampled and 0<=(now-sampled).total_seconds()<=120)
    # Market freshness is based on exchange time, not a newly written database row.
    active=bool(fresh and exchange and 0<=(now-exchange).total_seconds()<=120)
    cap=current.get('cap_krw');ratio=None
    if cap and current.get('turnover_krw') is not None and not any(str(s).startswith(('TURNOVER_','CAP_')) for s in current.get('quality_flags',[])):
        ratio=current['turnover_krw']/cap*100
    return {**current,'interval_turnover_krw':value,'interval_seconds':sec,'delta_state':state,
            'five_min_turnover_krw':fivemin,'five_min_seconds':five_seconds,
            'burst_multiple':burst,'baseline_intervals':len(rates[-10:]),
            'trade_to_cap_pct':ratio,'recent_trade':active,'sample_recent':fresh,
            'comparison_prior':previous,
            'spark':[{ 'time':x['received_at'],'value':x.get('price_krw')} for x in h[-20:]]}


def group_rows(rows,history_by_code,mode='catalyst'):
    """No double counting: one primary bucket per stock; deltas use common cohorts."""
    def key(r):
        event=r.get('event_type') or '재료 분석 대기'
        if mode=='catalyst':
            base=r.get('market_theme') or r.get('segment') or '테마 미확인'
            return base+' / '+event
        if mode=='theme':
            return r.get('market_theme') or '시장테마 미확인'
        return r.get('segment') or '세부업종 미확인'
    stock_rows=[r for r in rows if r.get('sector')!='ETF·ETN']
    comparable={}
    batches=sorted({x.get('batch_time') for h in history_by_code.values() for x in h if x.get('batch_time')})[-3:]
    for r in stock_rows:
        h=history_by_code.get(r['code'],[])
        if len(h)<3:continue
        if batches and [x.get('batch_time') for x in h[-3:]]!=batches:continue
        d0,s0,t0=delta(h[-1],h[-2]);d1,s1,t1=delta(h[-2],h[-3])
        if s0=='OK' and s1=='OK':comparable[r['code']]=(d0,d1,t0,t1)
    total0=sum(x[0] for x in comparable.values());total1=sum(x[1] for x in comparable.values())
    groups={}
    for r in stock_rows:
        g=groups.setdefault(key(r),{'name':key(r),'segment':r['segment'],'event_type':r.get('event_type'),
            'stocks':[],'cum':0,'cum_known':0,'delta':0,'delta_known':0,'common0':0,'common1':0,'common_n':0})
        g['stocks'].append(r)
        if r.get('turnover_krw') is not None:g['cum']+=r['turnover_krw'];g['cum_known']+=1
        if r.get('interval_turnover_krw') is not None:g['delta']+=r['interval_turnover_krw'];g['delta_known']+=1
        if r['code'] in comparable:
            a,b,_,_=comparable[r['code']];g['common0']+=a;g['common1']+=b;g['common_n']+=1
    result=[]
    for g in groups.values():
        changes=[r['change_pct'] for r in g['stocks'] if r.get('change_pct') is not None]
        sh0=g['common0']/total0*100 if total0 and g['common_n'] else None
        sh1=g['common1']/total1*100 if total1 and g['common_n'] else None
        result.append({'name':g['name'],'segment':g['segment'],'event_type':g['event_type'],
            'stock_count':len(g['stocks']),'turnover_krw':g['cum'] if g['cum_known'] else None,
            'known_cumulative':g['cum_known'],
            'interval_turnover_krw':g['delta'] if g['delta_known'] else None,
            'known_deltas':g['delta_known'],'common_stock_count':g['common_n'],
            'share_pct':sh0,'share_change_pp':sh0-sh1 if sh0 is not None and sh1 is not None else None,
            'mean_change_pct':sum(changes)/len(changes) if changes else None,
            'stock_codes':[r['code'] for r in sorted(g['stocks'],key=lambda x:(x.get('interval_turnover_krw') is None,-(x.get('interval_turnover_krw') or 0)))]})
    result.sort(key=lambda g:(g['interval_turnover_krw'] is None,-(g['interval_turnover_krw'] or 0),-(g['turnover_krw'] or 0)))
    return result,{'common_stocks':len(comparable),'current_common_turnover':total0,'prior_common_turnover':total1,
                   'scope':'조회상위와 거래대금상위의 수집 표본; 전체 시장 아님',
                   'meaning':'거래 집중도 변화; 순매수 자금 이동이 아님'}


def rotation_series(rows,history_by_code,max_intervals=10):
    """Fixed-cohort market-theme turnover-share series.

    A stock must be present and have a valid cumulative-turnover delta in every
    displayed interval. This avoids making sample entry/exit look like rotation.
    """
    batches=sorted({x.get('batch_time') for h in history_by_code.values() for x in h if x.get('batch_time')})
    batches=batches[-(max_intervals+1):]
    if len(batches)<2:return {'times':[],'series':[],'common_stocks':0}
    rowmap={r['code']:r for r in rows if r.get('sector')!='ETF·ETN'}
    cohort={}
    for code,r in rowmap.items():
        bytime={x.get('batch_time'):x for x in history_by_code.get(code,[])}
        if any(t not in bytime for t in batches):continue
        vals=[];ok=True
        for a,b in zip(batches[1:],batches[:-1]):
            v,state,_=delta(bytime[a],bytime[b])
            if state!='OK':ok=False;break
            vals.append(v)
        if ok:cohort[code]=vals
    if not cohort:return {'times':batches[1:],'series':[],'common_stocks':0}
    totals=[sum(v[i] for v in cohort.values()) for i in range(len(batches)-1)]
    groups={}
    for code,vals in cohort.items():
        r=rowmap[code];name=r.get('market_theme') or r.get('segment') or '테마 미확인'
        arr=groups.setdefault(name,[0]*len(vals))
        for i,v in enumerate(vals):arr[i]+=v
    series=[]
    for name,vals in groups.items():
        shares=[(v/totals[i]*100 if totals[i]>0 else None) for i,v in enumerate(vals)]
        valid=[x for x in shares if x is not None]
        series.append({'name':name,'turnover':vals,'share_pct':shares,
                       'current_share_pct':shares[-1] if shares else None,
                       'change_pp':(valid[-1]-valid[0]) if len(valid)>=2 else None,
                       'current_turnover_krw':vals[-1] if vals else None})
    series.sort(key=lambda x:-(x.get('current_turnover_krw') or 0))
    return {'times':batches[1:],'series':series,'common_stocks':len(cohort),
            'meaning':'고정 공통표본의 구간 거래대금 비중 변화; 순매수 자금이동이 아님'}


def report_sections(report):
    """Slice report sections without destroying citation offsets. No new AI calls."""
    if not isinstance(report,dict) or not report.get('citations'):return {}
    text=report.get('text','')
    marks=list(re.finditer(r'(?m)^\s*(?:#{1,4}\s*)?(?:\*\*)?(핵심 재료|새로움과 반복|시장 연결|반대 근거·미확인)(?:\*\*)?\s*[:：]?\s*$',text))
    out={}
    for i,m in enumerate(marks):
        start=m.end();end=marks[i+1].start() if i+1<len(marks) else len(text)
        while start<end and text[start].isspace():start+=1
        body=text[start:end].strip()
        citations=[{**x,'start':x['start']-start,'end':x['end']-start} for x in report.get('citations',[]) if start<=x.get('start',-1)<x.get('end',-1)<=end]
        out[m.group(1)]={'text':body,'citations':citations}
    return out


def event_from_report(report):
    """Explicit model category only. No headline keywords pretending to be analysis."""
    if not isinstance(report,dict) or not report.get('citations'):return None
    match=re.search(r'(?m)^\s*재료분류\s*[:：]\s*([^\n]+)',report.get('text',''))
    value=match.group(1).strip().strip('*') if match else None
    return value if value in EVENTS else None
