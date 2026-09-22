import os, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg

DB=os.getenv("DATABASE_URL","")
MODE=os.getenv("KIWOOM_MODE","real").strip().lower()
BASE=os.getenv("PRD","https://api.kiwoom.com") if MODE=="real" else os.getenv("MOCK","https://mockapi.kiwoom.com")
APPKEY=os.getenv("APP_KEY","") if MODE=="real" else os.getenv("APP_KEY_MOCK","")
SECRET=os.getenv("APP_SECRET","") if MODE=="real" else os.getenv("APP_SECRET_MOCK","")
POLL=int(os.getenv("CHART_POLL_SECONDS","60"))
TOPN=int(os.getenv("CHART_TOP_STOCKS","20"))
MIN_INTERVAL=os.getenv("CHART_MINUTE_INTERVAL","3")
DAILY_REFRESH=int(os.getenv("CHART_DAILY_REFRESH_SECONDS","1800"))
KST=ZoneInfo("Asia/Seoul")

token=None
token_exp=None

def db(): return psycopg.connect(DB)

def n(v):
    try:
        s=str(v).replace(",","").strip()
        return float(s) if s else None
    except: return None

def px(v):
    x=n(v)
    return abs(x) if x is not None else None

def qty(v):
    x=n(v)
    return abs(x) if x is not None else None

def schema():
    with db() as c, c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS market_minute_bars(
          stock_code TEXT NOT NULL,
          interval_min INTEGER NOT NULL,
          bar_time TIMESTAMPTZ NOT NULL,
          open_price NUMERIC,high_price NUMERIC,low_price NUMERIC,close_price NUMERIC,
          volume NUMERIC,fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(stock_code,interval_min,bar_time)
        );
        CREATE INDEX IF NOT EXISTS idx_minute_bars_stock_time
          ON market_minute_bars(stock_code,interval_min,bar_time DESC);

        CREATE TABLE IF NOT EXISTS market_daily_bars(
          stock_code TEXT NOT NULL,
          trade_date DATE NOT NULL,
          open_price NUMERIC,high_price NUMERIC,low_price NUMERIC,close_price NUMERIC,
          volume NUMERIC,trade_value NUMERIC,fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(stock_code,trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_bars_stock_date
          ON market_daily_bars(stock_code,trade_date DESC);

        CREATE TABLE IF NOT EXISTS chart_feed_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,mode TEXT,
          last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """)
        c.commit()

def set_status(status,note=None,error=None,success=False):
    with db() as c, c.cursor() as cur:
        cur.execute("""
        INSERT INTO chart_feed_status(id,updated_at,status,mode,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,mode=excluded.mode,
        last_success_at=COALESCE(excluded.last_success_at,chart_feed_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error
        """,(status,MODE,datetime.now(timezone.utc) if success else None,note,error))
        c.commit()

def issue_token():
    global token,token_exp
    r=requests.post(BASE+"/oauth2/token",json={"grant_type":"client_credentials","appkey":APPKEY,"secretkey":SECRET},
                    headers={"Content-Type":"application/json;charset=UTF-8"},timeout=20)
    d=r.json()
    if r.status_code>=400 or d.get("return_code") not in (None,0):
        raise RuntimeError(f"token failed: {d.get('return_msg') or r.status_code}")
    token=d["token"]
    exp=d.get("expires_dt")
    token_exp=datetime.strptime(exp,"%Y%m%d%H%M%S").replace(tzinfo=KST).astimezone(timezone.utc) if exp else datetime.now(timezone.utc)+timedelta(hours=12)

def auth():
    if not token or not token_exp or datetime.now(timezone.utc)>token_exp-timedelta(minutes=10):
        issue_token()
    return f"Bearer {token}"

def call(api_id,body,cont_yn=None,next_key=None):
    headers={"Content-Type":"application/json;charset=UTF-8","api-id":api_id,"authorization":auth()}
    if cont_yn: headers["cont-yn"]=cont_yn
    if next_key: headers["next-key"]=next_key
    r=requests.post(BASE+"/api/dostk/chart",json=body,headers=headers,timeout=20)
    d=r.json()
    if r.status_code>=400 or d.get("return_code") not in (None,0):
        raise RuntimeError(f"{api_id}: {d.get('return_msg') or r.status_code}")
    return d,r.headers

def fetch_rows(api_id,body,key,max_pages=2):
    rows=[]; cy=None; nk=None
    for _ in range(max_pages):
        d,h=call(api_id,body,cy,nk)
        got=d.get(key,[])
        if isinstance(got,list):
            rows.extend(x for x in got if isinstance(x,dict))
        cy=h.get("cont-yn") or h.get("Cont-Yn")
        nk=h.get("next-key") or h.get("Next-Key")
        if cy!="Y": break
        time.sleep(.2)
    return rows

def universe():
    with db() as c, c.cursor() as cur:
        codes=[]
        for table in ("market_rank_snapshots","market_trade_value_snapshots"):
            cur.execute("SELECT to_regclass(%s)",(f"public.{table}",))
            if not cur.fetchone()[0]: continue
            cur.execute(f"SELECT MAX(snapshot_time) FROM {table}")
            t=cur.fetchone()[0]
            if not t: continue
            cur.execute(f"SELECT stock_code FROM {table} WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT %s",(t,TOPN))
            for (code,) in cur.fetchall():
                if code and code not in codes: codes.append(code)
        return codes[:TOPN]

def parse_minute_time(v):
    s=str(v or "").strip()
    if len(s)>=14:
        return datetime.strptime(s[:14],"%Y%m%d%H%M%S").replace(tzinfo=KST).astimezone(timezone.utc)
    return None

def parse_date(v):
    s=str(v or "").strip()
    if len(s)>=8:
        return datetime.strptime(s[:8],"%Y%m%d").date()
    return None

def store_minute(code,rows):
    vals=[]
    for r in rows[:600]:
        bt=parse_minute_time(r.get("cntr_tm"))
        if not bt: continue
        vals.append((code,int(MIN_INTERVAL),bt,px(r.get("open_pric")),px(r.get("high_pric")),px(r.get("low_pric")),
                     px(r.get("cur_prc")),qty(r.get("trde_qty"))))
    if not vals: return 0
    with db() as c, c.cursor() as cur:
        cur.executemany("""
        INSERT INTO market_minute_bars(stock_code,interval_min,bar_time,open_price,high_price,low_price,close_price,volume)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(stock_code,interval_min,bar_time) DO UPDATE SET
          open_price=excluded.open_price,high_price=excluded.high_price,low_price=excluded.low_price,
          close_price=excluded.close_price,volume=excluded.volume,fetched_at=now()
        """,vals)
        c.commit()
    return len(vals)

def daily_stale(code):
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT MAX(fetched_at) FROM market_daily_bars WHERE stock_code=%s",(code,))
        x=cur.fetchone()[0]
    return (not x) or datetime.now(timezone.utc)-x>timedelta(seconds=DAILY_REFRESH)

def store_daily(code,rows):
    vals=[]
    for r in rows[:260]:
        dt=parse_date(r.get("dt"))
        if not dt: continue
        vals.append((code,dt,px(r.get("open_pric")),px(r.get("high_pric")),px(r.get("low_pric")),px(r.get("cur_prc")),
                     qty(r.get("trde_qty")),qty(r.get("trde_prica"))))
    if not vals: return 0
    with db() as c, c.cursor() as cur:
        cur.executemany("""
        INSERT INTO market_daily_bars(stock_code,trade_date,open_price,high_price,low_price,close_price,volume,trade_value)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(stock_code,trade_date) DO UPDATE SET
          open_price=excluded.open_price,high_price=excluded.high_price,low_price=excluded.low_price,
          close_price=excluded.close_price,volume=excluded.volume,trade_value=excluded.trade_value,fetched_at=now()
        """,vals)
        c.commit()
    return len(vals)

def cycle():
    codes=universe()
    if not codes:
        set_status("WAITING_FOR_MARKET_DATA","조회/거래대금 상위 종목 대기")
        return
    today=datetime.now(KST).strftime("%Y%m%d")
    mcount=dcount=0
    for code in codes:
        try:
            mins=fetch_rows("ka10080",{"stk_cd":code,"tic_scope":MIN_INTERVAL,"upd_stkpc_tp":"1","base_dt":today},
                            "stk_min_pole_chart_qry",2)
            mcount+=store_minute(code,mins)
            if daily_stale(code):
                days=fetch_rows("ka10081",{"stk_cd":code,"base_dt":today,"upd_stkpc_tp":"1"},
                                "stk_dt_pole_chart_qry",2)
                dcount+=store_daily(code,days)
            time.sleep(.15)
        except Exception as e:
            print("chart fetch error",code,str(e)[:300],flush=True)
    set_status("OK",f"stocks={len(codes)} minute_rows={mcount} daily_rows={dcount}",success=True)

def main():
    schema()
    print(f"Chart feed started: mode={MODE}, top={TOPN}, interval={MIN_INTERVAL}m",flush=True)
    if not APPKEY or not SECRET:
        set_status("WAITING_FOR_CREDENTIALS","로컬 .env의 Kiwoom 실전 App Key/Secret 확인")
    while True:
        try:
            if APPKEY and SECRET: cycle()
        except Exception as e:
            set_status("ERROR","차트 데이터 수집 오류",str(e)[:500])
            print("chart feed error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":
    main()
