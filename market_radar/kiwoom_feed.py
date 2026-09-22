import os, time, json, traceback
from datetime import datetime, timezone, timedelta
import requests
import psycopg

DB = os.getenv("DATABASE_URL", "")
MODE = os.getenv("KIWOOM_MODE", "demo").strip().lower()
POLL = int(os.getenv("KIWOOM_POLL_SECONDS", "30"))
TRADE_VALUE_MULT = float(os.getenv("KIWOOM_TRADE_VALUE_MULTIPLIER", "1000000"))
MARKET_CAP_MULT = float(os.getenv("KIWOOM_MARKET_CAP_MULTIPLIER", "100000000"))
BASE = os.getenv("PRD", "https://api.kiwoom.com") if MODE=="real" else os.getenv("MOCK", "https://mockapi.kiwoom.com")
APPKEY = os.getenv("APP_KEY", "") if MODE=="real" else os.getenv("APP_KEY_MOCK", "")
SECRET = os.getenv("APP_SECRET", "") if MODE=="real" else os.getenv("APP_SECRET_MOCK", "")

token=None
token_exp=None
stock_meta={}
last_meta_refresh=None

def db():
    return psycopg.connect(DB)

def schema():
    with db() as c, c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS kiwoom_feed_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL,
          mode TEXT,
          last_success_at TIMESTAMPTZ,
          note TEXT,
          last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS stock_master(
          stock_code TEXT PRIMARY KEY,
          stock_name TEXT,
          market_name TEXT,
          official_sector TEXT,
          size_class TEXT,
          nxt_enabled TEXT,
          updated_at TIMESTAMPTZ NOT NULL
        );
        ALTER TABLE market_rank_snapshots ADD COLUMN IF NOT EXISTS current_price_krw NUMERIC;
        ALTER TABLE market_trade_value_snapshots ADD COLUMN IF NOT EXISTS current_price_krw NUMERIC;
        """)
        c.commit()

def set_status(status,note=None,error=None,success=False):
    with db() as c, c.cursor() as cur:
        cur.execute("""
        INSERT INTO kiwoom_feed_status(id,updated_at,status,mode,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,mode=excluded.mode,
          last_success_at=COALESCE(excluded.last_success_at,kiwoom_feed_status.last_success_at),
          note=excluded.note,last_error=excluded.last_error
        """,(status,MODE,datetime.now(timezone.utc) if success else None,note,error))
        c.commit()

def issue_token():
    global token, token_exp
    r=requests.post(BASE+"/oauth2/token",json={"grant_type":"client_credentials","appkey":APPKEY,"secretkey":SECRET},
                    headers={"Content-Type":"application/json;charset=UTF-8"},timeout=20)
    d=r.json()
    if r.status_code>=400 or d.get("return_code") not in (None,0):
        raise RuntimeError(f"token failed: {d.get('return_msg') or r.status_code}")
    token=d["token"]
    exp=d.get("expires_dt")
    token_exp=datetime.strptime(exp,"%Y%m%d%H%M%S").replace(tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc) if exp else datetime.now(timezone.utc)+timedelta(hours=12)

def auth_header():
    if not token or not token_exp or datetime.now(timezone.utc) > token_exp-timedelta(minutes=10):
        issue_token()
    return f"Bearer {token}"

def call(api_id,path,body,cont_yn=None,next_key=None,retry=True):
    headers={"Content-Type":"application/json;charset=UTF-8","api-id":api_id,"authorization":auth_header()}
    if cont_yn: headers["cont-yn"]=cont_yn
    if next_key: headers["next-key"]=next_key
    r=requests.post(BASE+path,json=body,headers=headers,timeout=20)
    try: d=r.json()
    except: d={"return_msg":r.text[:200]}
    rc=d.get("return_code")
    if retry and (r.status_code==401 or rc in (8005,3) and "8005" in str(d.get("return_msg",""))):
        global token
        token=None
        return call(api_id,path,body,cont_yn,next_key,False)
    if r.status_code>=400 or rc not in (None,0):
        raise RuntimeError(f"{api_id}: {d.get('return_msg') or r.status_code}")
    return d, r.headers

def fetch_all(api_id,path,body,key,max_pages=10):
    out=[]; cy=None; nk=None
    for _ in range(max_pages):
        d,h=call(api_id,path,body,cy,nk)
        rows=d.get(key,[])
        if isinstance(rows,list): out.extend([x for x in rows if isinstance(x,dict)])
        cy=h.get("cont-yn") or h.get("Cont-Yn")
        nk=h.get("next-key") or h.get("Next-Key")
        if cy!="Y": break
        time.sleep(0.2)
    return out

def n(v):
    try:
        s=str(v).replace(",","").strip()
        if not s: return None
        return float(s)
    except: return None

def norm_cap(v):
    x=n(v)
    if x is None: return None
    return x*MARKET_CAP_MULT if x < 1_000_000_000 else x

def norm_tv(v):
    x=n(v)
    if x is None: return None
    return x*TRADE_VALUE_MULT if x < 1_000_000_000_000 else x

def refresh_meta():
    global stock_meta,last_meta_refresh
    meta={}
    for mkt in ("0","10"):
        rows=fetch_all("ka10099","/api/dostk/stkinfo",{"mrkt_tp":mkt},"list",10)
        for r in rows:
            code=str(r.get("code") or "").replace("_AL","").replace("_NX","")
            if not code: continue
            meta[code]={"name":r.get("name"),"market":r.get("marketName"),"sector":r.get("upName"),"size":r.get("upSizeName"),"nxt":r.get("nxtEnable")}
    with db() as c, c.cursor() as cur:
        for code,m in meta.items():
            cur.execute("""INSERT INTO stock_master(stock_code,stock_name,market_name,official_sector,size_class,nxt_enabled,updated_at)
                           VALUES(%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT(stock_code) DO UPDATE SET stock_name=excluded.stock_name,market_name=excluded.market_name,
                           official_sector=excluded.official_sector,size_class=excluded.size_class,nxt_enabled=excluded.nxt_enabled,updated_at=now()""",
                        (code,m["name"],m["market"],m["sector"],m["size"],m["nxt"]))
        c.commit()
    stock_meta=meta
    last_meta_refresh=datetime.now(timezone.utc)

def detail_map(codes):
    out={}
    codes=[c for c in codes if c]
    for i in range(0,len(codes),20):
        batch=codes[i:i+20]
        rows=fetch_all("ka10095","/api/dostk/stkinfo",{"stk_cd":"|".join(batch)},"atn_stk_infr",2)
        for r in rows:
            code=str(r.get("stk_cd") or "").replace("_AL","").replace("_NX","")
            out[code]={
                "name":r.get("stk_nm"),"price":n(r.get("cur_prc")),"change":n(r.get("flu_rt")),
                "trade_value":norm_tv(r.get("trde_prica")),"market_cap":norm_cap(r.get("mac"))
            }
    return out

def one_cycle():
    global last_meta_refresh
    if not last_meta_refresh or datetime.now(timezone.utc)-last_meta_refresh>timedelta(hours=12):
        refresh_meta()

    rank=fetch_all("ka00198","/api/dostk/stkinfo",{"qry_tp":"5"},"item_inq_rank",10)[:100]
    trade=fetch_all("ka10032","/api/dostk/rkinfo",{"mrkt_tp":"000","mang_stk_incls":"0","stex_tp":"3"},"trde_prica_upper",10)[:100]
    codes=[]
    for r in rank[:40]+trade[:40]:
        code=str(r.get("stk_cd") or "").replace("_AL","").replace("_NX","")
        if code and code not in codes: codes.append(code)
    det=detail_map(codes)
    snap=datetime.now(timezone.utc).replace(microsecond=0)

    with db() as c, c.cursor() as cur:
        for r in rank[:100]:
            code=str(r.get("stk_cd") or "").replace("_AL","").replace("_NX","")
            if not code: continue
            m=stock_meta.get(code,{})
            d=det.get(code,{})
            cur.execute("""INSERT INTO market_rank_snapshots(snapshot_time,stock_code,stock_name,rank_no,rank_change,change_rate,
                           market_cap_krw,official_sector,market_theme,current_price_krw)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s) ON CONFLICT DO NOTHING""",
                        (snap,code,r.get("stk_nm") or d.get("name") or m.get("name"),int(n(r.get("bigd_rank")) or 0) or None,
                         int(n(r.get("rank_chg")) or 0),n(r.get("base_comp_chgr")) or d.get("change"),
                         d.get("market_cap"),m.get("sector"),d.get("price")))
        for r in trade[:100]:
            code=str(r.get("stk_cd") or "").replace("_AL","").replace("_NX","")
            if not code: continue
            m=stock_meta.get(code,{})
            d=det.get(code,{})
            cur.execute("""INSERT INTO market_trade_value_snapshots(snapshot_time,stock_code,stock_name,rank_no,trade_value_krw,
                           change_rate,market_cap_krw,official_sector,market_theme,current_price_krw)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s) ON CONFLICT DO NOTHING""",
                        (snap,code,r.get("stk_nm") or d.get("name") or m.get("name"),int(n(r.get("now_rank")) or 0) or None,
                         norm_tv(r.get("trde_prica")) or d.get("trade_value"),n(r.get("flu_rt")) or d.get("change"),
                         d.get("market_cap"),m.get("sector"),n(r.get("cur_prc")) or d.get("price")))

        # sectors + main indices
        for inds,name in (("001","KOSPI"),("101","KOSDAQ")):
            rows=fetch_all("ka20003","/api/dostk/sect",{"inds_cd":inds},"all_inds_idex",10)
            primary=None
            for rr in rows:
                code=str(rr.get("stk_cd") or "")
                sname=str(rr.get("stk_nm") or "")
                tv=norm_tv(rr.get("trde_prica"))
                cur.execute("""INSERT INTO market_sector_snapshots(snapshot_time,sector_code,sector_name,change_rate,trade_value_krw,
                               rising_count,flat_count,falling_count)
                               VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            (snap,code or sname,sname or code,n(rr.get("flu_rt")),tv,
                             int(n(rr.get("rising")) or 0),int(n(rr.get("stdns")) or 0),int(n(rr.get("fall")) or 0)))
                if code==inds or name.lower() in sname.lower() or "종합" in sname:
                    primary=rr
            if not primary and rows: primary=rows[0]
            if primary:
                cur.execute("""INSERT INTO market_index_snapshots(snapshot_time,index_code,index_name,current_value,change_rate,
                               open_value,high_value,low_value) VALUES(%s,%s,%s,%s,%s,NULL,NULL,NULL) ON CONFLICT DO NOTHING""",
                            (snap,inds,name,n(primary.get("cur_prc")),n(primary.get("flu_rt"))))
        c.commit()
    set_status("OK",f"rank={len(rank)} trade={len(trade)}",success=True)

def main():
    schema()
    if not APPKEY or not SECRET:
        set_status("WAITING_FOR_CREDENTIALS","Railway에 Kiwoom App Key/Secret을 입력하세요.")
    while True:
        try:
            if not APPKEY or not SECRET:
                time.sleep(30); continue
            one_cycle()
        except Exception as e:
            set_status("ERROR","Kiwoom 호출 오류",str(e)[:500])
            print("kiwoom feed error:",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":
    main()
