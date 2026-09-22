import os,time,json
from datetime import datetime,timezone,timedelta
import psycopg

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("MIMOSA_POLL_SECONDS","30"))
INTERVAL=int(os.getenv("MIMOSA_INTERVAL_MIN","3"))

def db(): return psycopg.connect(DB)

def f(v):
    try:return float(v)
    except:return None

def avg(xs):
    xs=[x for x in xs if x is not None]
    return sum(xs)/len(xs) if xs else None

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS chart_states(
          snapshot_time TIMESTAMPTZ NOT NULL,
          stock_code TEXT NOT NULL,
          state TEXT NOT NULL,
          state_ko TEXT NOT NULL,
          score DOUBLE PRECISION,
          current_price DOUBLE PRECISION,
          prior_high DOUBLE PRECISION,
          minute_trend TEXT,
          daily_context TEXT,
          m_contraction BOOLEAN,
          breakout BOOLEAN,
          reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
          PRIMARY KEY(snapshot_time,stock_code)
        );
        CREATE INDEX IF NOT EXISTS idx_chart_states_stock_time ON chart_states(stock_code,snapshot_time DESC);

        CREATE TABLE IF NOT EXISTS mimosa_strategy_signals(
          snapshot_time TIMESTAMPTZ NOT NULL,
          stock_code TEXT NOT NULL,
          strategy TEXT NOT NULL,
          state TEXT NOT NULL,
          state_ko TEXT NOT NULL,
          score DOUBLE PRECISION,
          metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
          reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
          source_note TEXT,
          PRIMARY KEY(snapshot_time,stock_code,strategy)
        );
        CREATE INDEX IF NOT EXISTS idx_mimosa_strategy_stock_time
          ON mimosa_strategy_signals(stock_code,strategy,snapshot_time DESC);

        CREATE TABLE IF NOT EXISTS mimosa_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO mimosa_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,mimosa_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(timezone.utc) if success else None,note,error));c.commit()

def latest_market_maps():
    q={};t={};meta={}
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.market_rank_snapshots')")
        if cur.fetchone()[0]:
            cur.execute("SELECT MAX(snapshot_time) FROM market_rank_snapshots");qt=cur.fetchone()[0]
            if qt:
                cur.execute("""SELECT stock_code,stock_name,rank_no,rank_change,change_rate,market_cap_krw,official_sector
                               FROM market_rank_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 50""",(qt,))
                for x in cur.fetchall():
                    q[x[0]]={"name":x[1],"rank":x[2],"rank_change":x[3],"change":f(x[4]),
                             "cap":f(x[5]),"sector":x[6]}
        cur.execute("SELECT to_regclass('public.market_trade_value_snapshots')")
        if cur.fetchone()[0]:
            cur.execute("SELECT MAX(snapshot_time) FROM market_trade_value_snapshots");tt=cur.fetchone()[0]
            if tt:
                cur.execute("""SELECT stock_code,stock_name,rank_no,trade_value_krw,change_rate,market_cap_krw,official_sector
                               FROM market_trade_value_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 60""",(tt,))
                for x in cur.fetchall():
                    t[x[0]]={"name":x[1],"rank":x[2],"trade_value":f(x[3]),"change":f(x[4]),
                             "cap":f(x[5]),"sector":x[6]}
        cur.execute("SELECT to_regclass('public.stock_master')")
        if cur.fetchone()[0]:
            cur.execute("SELECT stock_code,stock_name,nxt_enabled FROM stock_master")
            meta={x[0]:{"name":x[1],"nxt":x[2]} for x in cur.fetchall()}
    return q,t,meta

def universe(q,t):
    codes=[]
    for code,_ in sorted(q.items(),key=lambda kv:(kv[1].get("rank") is None,kv[1].get("rank") or 999))[:30]:
        if code not in codes:codes.append(code)
    for code,_ in sorted(t.items(),key=lambda kv:(kv[1].get("rank") is None,kv[1].get("rank") or 999))[:30]:
        if code not in codes:codes.append(code)
    return codes[:30]

def bars(code):
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT bar_time,open_price,high_price,low_price,close_price,volume
                       FROM market_minute_bars WHERE stock_code=%s AND interval_min=%s
                       ORDER BY bar_time DESC LIMIT 160""",(code,INTERVAL))
        mins=list(reversed(cur.fetchall()))
        cur.execute("""SELECT trade_date,open_price,high_price,low_price,close_price,volume,trade_value
                       FROM market_daily_bars WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 160""",(code,))
        days=list(reversed(cur.fetchall()))
    return mins,days

def leader_history(code):
    out={"query_days":0,"trade_days":0}
    with db() as c,c.cursor() as cur:
        try:
            cur.execute("""SELECT COUNT(DISTINCT snapshot_time::date) FROM market_rank_snapshots
                           WHERE stock_code=%s AND snapshot_time>now()-interval '20 days' AND rank_no<=20""",(code,))
            out["query_days"]=int(cur.fetchone()[0] or 0)
        except Exception:c.rollback()
        try:
            cur.execute("""SELECT COUNT(DISTINCT snapshot_time::date) FROM market_trade_value_snapshots
                           WHERE stock_code=%s AND snapshot_time>now()-interval '20 days' AND rank_no<=20""",(code,))
            out["trade_days"]=int(cur.fetchone()[0] or 0)
        except Exception:c.rollback()
    return out

def base_analysis(mins,days):
    if len(mins)<12:
        return {
            "state":"WAITING_FOR_CHART","state_ko":"차트 데이터 대기","score":0,"current":None,"prior_high":None,
            "minute_trend":"미확인","daily_context":"일봉 데이터 대기","contraction":False,"breakout":False,
            "reasons":["분봉 데이터 부족"]
        }
    closes=[f(x[4]) for x in mins]; highs=[f(x[2]) for x in mins]; lows=[f(x[3]) for x in mins]
    current=closes[-1]
    last5=mins[-5:];prev10=mins[-15:-5] if len(mins)>=15 else mins[:-5]
    range5=(max(f(x[2]) for x in last5)-min(f(x[3]) for x in last5)) if last5 else None
    range10=(max(f(x[2]) for x in prev10)-min(f(x[3]) for x in prev10)) if prev10 else None
    vol5=avg([f(x[5]) or 0 for x in last5]);vol10=avg([f(x[5]) or 0 for x in prev10])
    contraction=bool(range5 is not None and range10 and range5/range10<0.65 and (vol10 is None or vol5<=vol10*1.15))
    recent_high=max(highs[-6:-1]) if len(highs)>=6 else max(highs[:-1])
    breakout=bool(current and recent_high and current>recent_high)
    recent_lows=lows[-6:]
    minute_trend="상승 유지" if closes[-1]>closes[-4] and min(recent_lows[-3:])>=min(recent_lows[:3]) else ("추세 약화" if closes[-1]<closes[-4] else "횡보")
    prior_high=None;daily_context="일봉 데이터 부족"
    if len(days)>=20:
        prior=[f(x[2]) for x in days[:-1] if f(x[2]) is not None]
        prior_high=max(prior[-60:]) if prior else None
        if prior_high and current:
            d=(current/prior_high-1)*100
            if current>prior_high*1.005:daily_context="전고점/신고가 상단"
            elif abs(d)<=2:daily_context="전고점 접근"
            elif d<-8:daily_context="전고점 하단"
            else:daily_context="전고점 아래"
    reasons=[];state="LEADER_TREND";ko="주도 추세";score=50
    if minute_trend=="추세 약화":
        state="TREND_DAMAGE";ko="분봉 추세 훼손";score=20;reasons.append("분봉 추세가 아래로 약화")
    elif prior_high and max(highs[-6:])>prior_high and current<prior_high*0.995:
        state="BREAKOUT_FAIL";ko="전고 돌파 실패";score=25;reasons.append("전고점 돌파 후 재이탈")
    elif prior_high and current>prior_high*1.005:
        state="NEW_HIGH";ko="일봉 신고가/전고 돌파";score=85;reasons.append("일봉 전고점 상단")
        if min(lows[-3:])>=prior_high*0.99:
            state="BREAKOUT_HOLD";ko="돌파 후 지지";score=90;reasons.append("최근 저점이 돌파선 부근을 지지")
    elif breakout and contraction:
        state="M_BREAKOUT_TEST";ko="M 수렴 후 돌파 시도";score=82;reasons+=["최근 변동폭 수렴","단기 고점 상향 돌파"]
    elif contraction:
        state="M_CONTRACTION";ko="M 수렴";score=72;reasons.append("최근 변동폭/거래량 수렴")
    elif daily_context=="전고점 접근":
        state="PREV_HIGH_APPROACH";ko="전고점 접근";score=65;reasons.append("일봉 전고점 ±2% 구간")
    elif minute_trend=="상승 유지":
        state="PULLBACK_INTACT";ko="분봉 추세 유지";score=60;reasons.append("최근 저점과 종가 흐름 유지")
    if len(days)>=5:
        recent_dv=[f(x[6]) for x in days[-5:] if f(x[6]) is not None]
        old_dv=[f(x[6]) for x in days[-25:-5] if f(x[6]) is not None]
        if recent_dv and old_dv and avg(recent_dv)>avg(old_dv)*1.8:
            reasons.append("최근 일봉 거래대금 확대");score=min(100,score+5)
    return {"state":state,"state_ko":ko,"score":score,"current":current,"prior_high":prior_high,
            "minute_trend":minute_trend,"daily_context":daily_context,"contraction":contraction,
            "breakout":breakout,"reasons":reasons}

def close_bet_signal(code,base,mins,days,q,t,meta):
    qi=q.get(code,{}) ; ti=t.get(code,{})
    current=base.get("current"); trend=base.get("minute_trend")
    trade_rank=ti.get("rank"); change=qi.get("change") if qi.get("change") is not None else ti.get("change")
    nxt=str(meta.get(code,{}).get("nxt") or "").upper() not in ("","N","0","FALSE","NONE")
    new_high=bool(base.get("daily_context")=="전고점/신고가 상단")
    consecutive=False
    if len(days)>=3:
        cs=[f(x[4]) for x in days[-3:]]
        consecutive=all(x is not None for x in cs) and cs[0]<cs[1]<cs[2]
    close_loc=None
    if days:
        lo,hi,cl=f(days[-1][3]),f(days[-1][2]),f(days[-1][4])
        if None not in (lo,hi,cl) and hi>lo:close_loc=(cl-lo)/(hi-lo)
    reasons=[];score=0;state="CLOSEBET_NO";ko="종가베팅 조건 미충족"
    if trend!="추세 약화":score+=20;reasons.append("분봉 추세 유지/횡보")
    if trade_rank is not None and trade_rank<=30:score+=25;reasons.append(f"거래대금 순위 #{trade_rank}")
    if change is not None and change>=5:score+=10;reasons.append("당일 등락률 강함(운영값 ≥5%)")
    if new_high:score+=25;reasons.append("일봉 신고가/전고 돌파")
    if consecutive:score+=15;reasons.append("일봉 연속 상승")
    if close_loc is not None and close_loc>=.70:score+=5;reasons.append("종가 위치 고가권(운영값 ≥70%)")
    if nxt and trade_rank is not None and trade_rank<=30 and trend!="추세 약화" and change is not None and change>=5:
        state="CLOSEBET_NXT_LEADER";ko="NXT 당일 주도주형"
    if nxt and trade_rank is not None and trade_rank<=30 and new_high and trend!="추세 약화":
        state="CLOSEBET_NXT_BREAKOUT";ko="NXT 거래대금+신고가 돌파형"
    if (not nxt) and consecutive and trade_rank is not None and trade_rank<=30 and trend!="추세 약화":
        state="CLOSEBET_KRX_CONSECUTIVE";ko="KRX 연속 상승 주도주형"
    score=min(100,score)
    return {"strategy":"CLOSE_BET","state":state,"state_ko":ko,"score":score,
            "metrics":{"trade_rank":trade_rank,"change_rate":change,"nxt_enabled":nxt,"new_high":new_high,
                       "consecutive_rise":consecutive,"close_location":close_loc,"minute_trend":trend},
            "reasons":reasons,
            "source_note":"미모사 5강 강사 피드백 기반. 등락률 5%, 종가위치 70%, TVRank 30은 시스템 운영/검증용 값이며 강의의 고정 공식으로 단정하지 않음."}

def oversold_signal(code,base,mins,days,q,t,hist):
    current=base.get("current");peak=None;drawdown=None
    if days and current:
        hs=[f(x[2]) for x in days[-60:] if f(x[2]) is not None]
        peak=max(hs) if hs else None
        if peak:drawdown=(current/peak-1)*100
    qi=q.get(code,{}) ;ti=t.get(code,{})
    qrank=qi.get("rank");trank=ti.get("rank")
    retained=bool((qrank is not None and qrank<=30) or (trank is not None and trank<=30))
    leader_hist=bool(hist.get("query_days",0)>0 or hist.get("trade_days",0)>0)
    short_drop=None
    if len(mins)>=3:
        p=f(mins[-3][4]);c=f(mins[-1][4])
        if p and c:short_drop=(c/p-1)*100
    rebound=bool(len(mins)>=4 and f(mins[-1][4]) and f(mins[-3][4]) and f(mins[-1][4])>f(mins[-3][4]))
    in_band=bool(drawdown is not None and -45<=drawdown<=-25)
    score=0;reasons=[]
    if in_band:score+=45;reasons.append(f"최근 고점 대비 {drawdown:.1f}% 하락(운영구간 25~45%)")
    if leader_hist:score+=25;reasons.append("최근 20일 조회/거래대금 상위 이력")
    if retained:score+=20;reasons.append("현재 관심/거래대금 유지")
    if short_drop is not None and short_drop<=-5:score+=10;reasons.append("단기 급락(운영값 3분×2 구간 -5% 이하)")
    state="OVERSOLD_NO";ko="과대낙폭 조건 미충족"
    if in_band and leader_hist and retained:
        state="OVERSOLD_REBOUND_WATCH" if rebound else "OVERSOLD_WATCH"
        ko="과대낙폭 반등 감시" if rebound else "과대낙폭 감시"
    return {"strategy":"OVERSOLD","state":state,"state_ko":ko,"score":min(100,score),
            "metrics":{"peak_60d":peak,"drawdown_pct":drawdown,"query_rank":qrank,"trade_rank":trank,
                       "leader_query_days":hist.get("query_days"),"leader_trade_days":hist.get("trade_days"),
                       "short_drop_pct":short_drop,"rebound":rebound},
            "reasons":reasons,
            "source_note":"미모사 6강 과대낙폭 구조를 반영한 감시형 분류. 25~45%, 단기 -5%는 이전 조건검색 설계의 운영값이며 즉시 진입 신호가 아님."}

def falling_stock_signal(code,base,mins,days,q,t):
    qi=q.get(code,{}) ;ti=t.get(code,{})
    qrank=qi.get("rank");trank=ti.get("rank")
    current=base.get("current");day_high=None;day_dd=None
    if mins and current:
        latest_day=mins[-1][0].date()
        hs=[f(x[2]) for x in mins if x[0].date()==latest_day and f(x[2]) is not None]
        if hs:
            day_high=max(hs);day_dd=(current/day_high-1)*100
    prior_run=None
    if len(days)>=6:
        a=f(days[-6][4]);b=max(f(x[2]) for x in days[-5:] if f(x[2]) is not None)
        if a and b:prior_run=(b/a-1)*100
    retained=bool((qrank is not None and qrank<=30) and (trank is not None and trank<=20))
    rebound=False
    if len(mins)>=4:
        c1,c2,c3=f(mins[-3][4]),f(mins[-2][4]),f(mins[-1][4])
        rebound=all(x is not None for x in (c1,c2,c3)) and c3>c2>=c1
    fit=bool(day_dd is not None and day_dd<=-8 and retained and prior_run is not None and prior_run>=15)
    score=0;reasons=[]
    if day_dd is not None and day_dd<=-8:score+=40;reasons.append(f"당일 고점 대비 {day_dd:.1f}% 급락(운영값 ≤-8%)")
    if retained:score+=30;reasons.append("조회≤30 · 거래대금≤20 관심 유지")
    if prior_run is not None and prior_run>=15:score+=20;reasons.append(f"선행 상승 {prior_run:.1f}%")
    if rebound:score+=10;reasons.append("최근 3개 분봉 반등/매도속도 둔화")
    state="FALLING_NO";ko="낙주 조건 미충족"
    if fit:
        state="FALLING_REBOUND_WATCH" if rebound else "FALLING_WATCH"
        ko="낙주 반등 감시" if rebound else "낙주 감시"
    return {"strategy":"FALLING_STOCK","state":state,"state_ko":ko,"score":min(100,score),
            "metrics":{"day_high":day_high,"day_drawdown_pct":day_dd,"prior_run_pct":prior_run,
                       "query_rank":qrank,"trade_rank":trank,"rebound":rebound},
            "reasons":reasons,
            "source_note":"미모사 6강의 낙주와 과대낙폭을 분리한 운영 분류. 당일고점 -8%, 선행상승 15%는 시스템 감시용 v1 값."}

def cycle():
    q,t,meta=latest_market_maps();codes=universe(q,t)
    if not codes:
        status("WAITING_FOR_MARKET_DATA","조회/거래대금 데이터 대기");return
    snap=datetime.now(timezone.utc).replace(microsecond=0)
    saved=signals=0
    with db() as c,c.cursor() as cur:
        for code in codes:
            mins,days=bars(code)
            base=base_analysis(mins,days)
            cur.execute("""INSERT INTO chart_states(snapshot_time,stock_code,state,state_ko,score,current_price,prior_high,
            minute_trend,daily_context,m_contraction,breakout,reasons)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (snap,code,base["state"],base["state_ko"],base["score"],base["current"],base["prior_high"],
             base["minute_trend"],base["daily_context"],base["contraction"],base["breakout"],
             json.dumps(base["reasons"],ensure_ascii=False)))
            saved+=1
            hist=leader_history(code)
            for sig in (
                close_bet_signal(code,base,mins,days,q,t,meta),
                oversold_signal(code,base,mins,days,q,t,hist),
                falling_stock_signal(code,base,mins,days,q,t),
            ):
                cur.execute("""INSERT INTO mimosa_strategy_signals(snapshot_time,stock_code,strategy,state,state_ko,score,metrics,reasons,source_note)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (snap,code,sig["strategy"],sig["state"],sig["state_ko"],sig["score"],
                 json.dumps(sig["metrics"],ensure_ascii=False),json.dumps(sig["reasons"],ensure_ascii=False),sig["source_note"]))
                signals+=1
        c.commit()
    status("OK",f"chart_states={saved} strategy_signals={signals}",success=True)

def main():
    schema();print(f"Mimosa engine started: interval={INTERVAL}m, strategies=close_bet/oversold/falling",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            status("ERROR","미모사 상태 계산 오류",str(e)[:500]);print("mimosa error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
