import os,time,json,statistics
from datetime import datetime,timezone
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

def universe():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.market_rank_snapshots')")
        if not cur.fetchone()[0]: return []
        cur.execute("SELECT MAX(snapshot_time) FROM market_rank_snapshots");t=cur.fetchone()[0]
        if not t:return []
        cur.execute("SELECT stock_code FROM market_rank_snapshots WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 20",(t,))
        return [x[0] for x in cur.fetchall()]

def bars(code):
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT bar_time,open_price,high_price,low_price,close_price,volume
                       FROM market_minute_bars WHERE stock_code=%s AND interval_min=%s
                       ORDER BY bar_time DESC LIMIT 80""",(code,INTERVAL))
        mins=list(reversed(cur.fetchall()))
        cur.execute("""SELECT trade_date,open_price,high_price,low_price,close_price,volume,trade_value
                       FROM market_daily_bars WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 120""",(code,))
        days=list(reversed(cur.fetchall()))
    return mins,days

def analyze(code,mins,days):
    if len(mins)<12:
        return ("WAITING_FOR_CHART","차트 데이터 대기",0,None,None,"미확인","일봉 데이터 대기",False,False,["분봉 데이터 부족"])
    closes=[f(x[4]) for x in mins]; highs=[f(x[2]) for x in mins]; lows=[f(x[3]) for x in mins]; vols=[f(x[5]) or 0 for x in mins]
    current=closes[-1]
    last5=mins[-5:]; prev10=mins[-15:-5] if len(mins)>=15 else mins[:-5]
    range5=(max(f(x[2]) for x in last5)-min(f(x[3]) for x in last5)) if last5 else None
    range10=(max(f(x[2]) for x in prev10)-min(f(x[3]) for x in prev10)) if prev10 else None
    vol5=avg([f(x[5]) or 0 for x in last5]); vol10=avg([f(x[5]) or 0 for x in prev10])
    contraction=bool(range5 is not None and range10 and range5/range10<0.65 and (vol10 is None or vol5<=vol10*1.15))
    recent_high=max(highs[-6:-1]) if len(highs)>=6 else max(highs[:-1])
    breakout=bool(current and recent_high and current>recent_high)
    recent_lows=lows[-6:]
    minute_trend="상승 유지" if closes[-1]>closes[-4] and min(recent_lows[-3:])>=min(recent_lows[:3]) else ("추세 약화" if closes[-1]<closes[-4] else "횡보")

    prior_high=None; daily_context="일봉 데이터 부족"
    if len(days)>=20:
        prior=[f(x[2]) for x in days[:-1] if f(x[2]) is not None]
        prior_high=max(prior[-60:]) if prior else None
        if prior_high and current:
            d=(current/prior_high-1)*100
            if current>prior_high*1.005: daily_context="전고점/신고가 상단"
            elif abs(d)<=2: daily_context="전고점 접근"
            elif d<-8: daily_context="전고점 하단"
            else: daily_context="전고점 아래"
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
            reasons.append("최근 일봉 거래대금 확대")
            score=min(100,score+5)
    return state,ko,score,current,prior_high,minute_trend,daily_context,contraction,breakout,reasons

def cycle():
    codes=universe()
    if not codes:
        status("WAITING_FOR_MARKET_DATA","조회순위 데이터 대기");return
    snap=datetime.now(timezone.utc).replace(microsecond=0)
    saved=0
    with db() as c,c.cursor() as cur:
        for code in codes:
            mins,days=bars(code)
            out=analyze(code,mins,days)
            cur.execute("""INSERT INTO chart_states(snapshot_time,stock_code,state,state_ko,score,current_price,prior_high,
            minute_trend,daily_context,m_contraction,breakout,reasons)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (snap,code,*out[:-1],json.dumps(out[-1],ensure_ascii=False)))
            saved+=1
        c.commit()
    status("OK",f"states={saved}",success=True)

def main():
    schema();print(f"Mimosa engine started: interval={INTERVAL}m",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            status("ERROR","미모사 상태 계산 오류",str(e)[:500]);print("mimosa error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
