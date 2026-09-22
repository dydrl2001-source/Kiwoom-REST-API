import os,time
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg

DB=os.getenv("DATABASE_URL","")
MODE=os.getenv("KIWOOM_MODE","real").strip().lower()
BASE=os.getenv("PRD","https://api.kiwoom.com") if MODE=="real" else os.getenv("MOCK","https://mockapi.kiwoom.com")
APPKEY=os.getenv("APP_KEY","") if MODE=="real" else os.getenv("APP_KEY_MOCK","")
SECRET=os.getenv("APP_SECRET","") if MODE=="real" else os.getenv("APP_SECRET_MOCK","")
POLL=int(os.getenv("INDEX_CHART_POLL_SECONDS","60"))
INTERVAL=os.getenv("INDEX_CHART_INTERVAL_MIN","5")
DAILY_REFRESH=int(os.getenv("INDEX_DAILY_REFRESH_SECONDS","1800"))
KST=ZoneInfo("Asia/Seoul")
INDICES={"001":"KOSPI","101":"KOSDAQ"}

token=None
token_exp=None

def db(): return psycopg.connect(DB)

def n(v):
    try:
        s=str(v).replace(",","").strip()
        if not s:return None
        return float(s)
    except:return None

def px(v):
    x=n(v)
    return abs(x) if x is not None else None

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS index_minute_bars(
          index_code TEXT NOT NULL,index_name TEXT NOT NULL,interval_min INTEGER NOT NULL,
          bar_time TIMESTAMPTZ NOT NULL,open_value DOUBLE PRECISION,high_value DOUBLE PRECISION,
          low_value DOUBLE PRECISION,close_value DOUBLE PRECISION,volume NUMERIC,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(index_code,interval_min,bar_time)
        );
        CREATE INDEX IF NOT EXISTS idx_index_minute_code_time ON index_minute_bars(index_code,interval_min,bar_time DESC);
        CREATE TABLE IF NOT EXISTS index_daily_bars(
          index_code TEXT NOT NULL,index_name TEXT NOT NULL,trade_date DATE NOT NULL,
          open_value DOUBLE PRECISION,high_value DOUBLE PRECISION,low_value DOUBLE PRECISION,
          close_value DOUBLE PRECISION,volume NUMERIC,trade_value NUMERIC,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(index_code,trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_index_daily_code_date ON index_daily_bars(index_code,trade_date DESC);
        CREATE TABLE IF NOT EXISTS index_chart_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),updated_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL,last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def set_status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO index_chart_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,index_chart_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(timezone.utc) if success else None,note,error));c.commit()

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

def call(api_id,body,cy=None,nk=None):
    h={"Content-Type":"application/json;charset=UTF-8","api-id":api_id,"authorization":auth()}
    if cy:h["cont-yn"]=cy
    if nk:h["next-key"]=nk
    r=requests.post(BASE+"/api/dostk/chart",json=body,headers=h,timeout=20)
    d=r.json()
    if r.status_code>=400 or d.get("return_code") not in (None,0):
        raise RuntimeError(f"{api_id}: {d.get('return_msg') or r.status_code}")
    return d,r.headers

def fetch(api_id,body,key,max_pages=2):
    out=[];cy=None;nk=None
    for _ in range(max_pages):
        d,h=call(api_id,body,cy,nk)
        rows=d.get(key,[])
        if isinstance(rows,list):out.extend(x for x in rows if isinstance(x,dict))
        cy=h.get("cont-yn") or h.get("Cont-Yn")
        nk=h.get("next-key") or h.get("Next-Key")
        if cy!="Y":break
        time.sleep(.2)
    return out

def parse_time(v):
    s=str(v or "").strip()
    if len(s)>=14:return datetime.strptime(s[:14],"%Y%m%d%H%M%S").replace(tzinfo=KST).astimezone(timezone.utc)
    return None

def parse_date(v):
    s=str(v or "").strip()
    if len(s)>=8:return datetime.strptime(s[:8],"%Y%m%d").date()
    return None

def daily_stale(code):
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT MAX(fetched_at) FROM index_daily_bars WHERE index_code=%s",(code,))
        x=cur.fetchone()[0]
    return (not x) or datetime.now(timezone.utc)-x>timedelta(seconds=DAILY_REFRESH)

def store_minute(code,name,rows):
    vals=[]
    for r in rows[:600]:
        bt=parse_time(r.get("cntr_tm"))
        if not bt:continue
        vals.append((code,name,int(INTERVAL),bt,px(r.get("open_pric")),px(r.get("high_pric")),
                     px(r.get("low_pric")),px(r.get("cur_prc")),n(r.get("trde_qty"))))
    if not vals:return 0
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO index_minute_bars(index_code,index_name,interval_min,bar_time,open_value,high_value,low_value,close_value,volume)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(index_code,interval_min,bar_time) DO UPDATE SET
        open_value=excluded.open_value,high_value=excluded.high_value,low_value=excluded.low_value,
        close_value=excluded.close_value,volume=excluded.volume,fetched_at=now()""",vals);c.commit()
    return len(vals)

def store_daily(code,name,rows):
    vals=[]
    for r in rows[:260]:
        dt=parse_date(r.get("dt"))
        if not dt:continue
        vals.append((code,name,dt,px(r.get("open_pric")),px(r.get("high_pric")),px(r.get("low_pric")),
                     px(r.get("cur_prc")),n(r.get("trde_qty")),n(r.get("trde_prica"))))
    if not vals:return 0
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO index_daily_bars(index_code,index_name,trade_date,open_value,high_value,low_value,close_value,volume,trade_value)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(index_code,trade_date) DO UPDATE SET open_value=excluded.open_value,high_value=excluded.high_value,
        low_value=excluded.low_value,close_value=excluded.close_value,volume=excluded.volume,
        trade_value=excluded.trade_value,fetched_at=now()""",vals);c.commit()
    return len(vals)

def cycle():
    today=datetime.now(KST).strftime("%Y%m%d");mc=dc=0
    for code,name in INDICES.items():
        rows=fetch("ka20005",{"inds_cd":code,"tic_scope":INTERVAL,"base_dt":today},"inds_min_pole_qry",2)
        mc+=store_minute(code,name,rows)
        if daily_stale(code):
            days=fetch("ka20006",{"inds_cd":code,"base_dt":today},"inds_dt_pole_qry",2)
            dc+=store_daily(code,name,days)
        time.sleep(.2)
    set_status("OK",f"minute_rows={mc} daily_rows={dc}",success=True)

def main():
    schema();print(f"Index chart feed started: {INTERVAL}m",flush=True)
    if not APPKEY or not SECRET:set_status("WAITING_FOR_CREDENTIALS","Kiwoom 실전키 확인")
    while True:
        try:
            if APPKEY and SECRET:cycle()
        except Exception as e:
            set_status("ERROR","지수 차트 수집 오류",str(e)[:500]);print("index chart error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
