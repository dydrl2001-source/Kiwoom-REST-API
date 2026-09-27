import os, sys, time, json, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
LOG_FILE = HERE / "kiwoom_feed.log"

def load_env():
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line=raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,v=line.split("=",1)
            os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))

load_env()

MODE=os.getenv("KIWOOM_MODE","demo").strip().lower()
POLL=max(10,int(os.getenv("KIWOOM_POLL_SECONDS","30")))
TRADE_VALUE_MULT=float(os.getenv("KIWOOM_TRADE_VALUE_MULTIPLIER","1000000"))
MARKET_CAP_MULT=float(os.getenv("KIWOOM_MARKET_CAP_MULTIPLIER","100000000"))
BASE=os.getenv("PRD","https://api.kiwoom.com") if MODE=="real" else os.getenv("MOCK","https://mockapi.kiwoom.com")
APPKEY=os.getenv("APP_KEY","") if MODE=="real" else os.getenv("APP_KEY_MOCK","")
SECRET=os.getenv("APP_SECRET","") if MODE=="real" else os.getenv("APP_SECRET_MOCK","")
INGEST_URL=os.getenv("RADAR_INGEST_URL","").rstrip("/")
INGEST_TOKEN=os.getenv("KIWOOM_INGEST_TOKEN","")
HTTP_TIMEOUT=int(os.getenv("HTTP_TIMEOUT","20"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE,encoding="utf-8"),logging.StreamHandler(sys.stdout)]
)

token=None
token_exp=None
stock_meta={}
last_meta_refresh=None

def n(v):
    try:
        s=str(v).replace(",","").strip()
        return float(s) if s else None
    except Exception:
        return None

def norm_cap(v):
    x=n(v)
    if x is None: return None
    return x*MARKET_CAP_MULT if x < 1_000_000_000 else x

def norm_tv(v):
    x=n(v)
    if x is None: return None
    return x*TRADE_VALUE_MULT if x < 1_000_000_000_000 else x

def code_of(v):
    return str(v or "").replace("_AL","").replace("_NX","").strip()

def issue_token():
    global token,token_exp
    r=requests.post(
        BASE+"/oauth2/token",
        json={"grant_type":"client_credentials","appkey":APPKEY,"secretkey":SECRET},
        headers={"Content-Type":"application/json;charset=UTF-8"},
        timeout=HTTP_TIMEOUT,
    )
    d=r.json()
    if r.status_code>=400 or d.get("return_code") not in (None,0):
        raise RuntimeError("Kiwoom token failed: "+str(d.get("return_msg") or r.status_code))
    token=d["token"]
    exp=d.get("expires_dt")
    token_exp=(datetime.strptime(exp,"%Y%m%d%H%M%S").replace(
        tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
        if exp else datetime.now(timezone.utc)+timedelta(hours=12))

def auth_header():
    global token
    if not token or not token_exp or datetime.now(timezone.utc)>token_exp-timedelta(minutes=10):
        issue_token()
    return "Bearer "+token

def call(api_id,path,body,cont_yn=None,next_key=None,retry=True):
    global token
    h={"Content-Type":"application/json;charset=UTF-8","api-id":api_id,"authorization":auth_header()}
    if cont_yn: h["cont-yn"]=cont_yn
    if next_key: h["next-key"]=next_key
    r=requests.post(BASE+path,json=body,headers=h,timeout=HTTP_TIMEOUT)
    try: d=r.json()
    except Exception: d={"return_msg":r.text[:200]}
    rc=d.get("return_code")
    if retry and (r.status_code==401 or (rc in (8005,3) and "8005" in str(d.get("return_msg","")))):
        token=None
        return call(api_id,path,body,cont_yn,next_key,False)
    if r.status_code>=400 or rc not in (None,0):
        raise RuntimeError(f"{api_id}: {d.get('return_msg') or r.status_code}")
    return d,r.headers

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

def refresh_meta():
    global stock_meta,last_meta_refresh
    meta={}
    for mkt in ("0","10"):
        rows=fetch_all("ka10099","/api/dostk/stkinfo",{"mrkt_tp":mkt},"list",10)
        for r in rows:
            code=code_of(r.get("code"))
            if not code: continue
            meta[code]={
                "stock_code":code,
                "stock_name":r.get("name"),
                "market_name":r.get("marketName"),
                "official_sector":r.get("upName"),
                "size_class":r.get("upSizeName"),
                "nxt_enabled":r.get("nxtEnable"),
            }
    stock_meta=meta
    last_meta_refresh=datetime.now(timezone.utc)
    logging.info("stock master refreshed: %d",len(meta))

def detail_map(codes):
    out={}
    for i in range(0,len(codes),20):
        rows=fetch_all("ka10095","/api/dostk/stkinfo",{"stk_cd":"|".join(codes[i:i+20])},"atn_stk_infr",2)
        for r in rows:
            code=code_of(r.get("stk_cd"))
            out[code]={
                "name":r.get("stk_nm"),"price":n(r.get("cur_prc")),"change":n(r.get("flu_rt")),
                "trade_value":norm_tv(r.get("trde_prica")),"market_cap":norm_cap(r.get("mac"))
            }
    return out

def collect():
    global last_meta_refresh
    if not last_meta_refresh or datetime.now(timezone.utc)-last_meta_refresh>timedelta(hours=12):
        refresh_meta()

    rank=fetch_all("ka00198","/api/dostk/stkinfo",{"qry_tp":"5"},"item_inq_rank",10)[:100]
    trade=fetch_all("ka10032","/api/dostk/rkinfo",{"mrkt_tp":"000","mang_stk_incls":"0","stex_tp":"3"},"trde_prica_upper",10)[:100]

    codes=[]
    for r in rank[:40]+trade[:40]:
        c=code_of(r.get("stk_cd"))
        if c and c not in codes: codes.append(c)
    det=detail_map(codes)

    rank_out=[]
    for r in rank:
        code=code_of(r.get("stk_cd"))
        if not code: continue
        m=stock_meta.get(code,{})
        d=det.get(code,{})
        rank_out.append({
            "stock_code":code,
            "stock_name":r.get("stk_nm") or d.get("name") or m.get("stock_name"),
            "rank_no":int(n(r.get("bigd_rank")) or 0) or None,
            "rank_change":int(n(r.get("rank_chg")) or 0),
            "change_rate":n(r.get("base_comp_chgr")) if n(r.get("base_comp_chgr")) is not None else d.get("change"),
            "market_cap_krw":d.get("market_cap"),
            "official_sector":m.get("official_sector"),
            "market_theme":None,
            "current_price_krw":d.get("price"),
        })

    trade_out=[]
    for r in trade:
        code=code_of(r.get("stk_cd"))
        if not code: continue
        m=stock_meta.get(code,{})
        d=det.get(code,{})
        trade_out.append({
            "stock_code":code,
            "stock_name":r.get("stk_nm") or d.get("name") or m.get("stock_name"),
            "rank_no":int(n(r.get("now_rank")) or 0) or None,
            "trade_value_krw":d.get("trade_value") if d.get("trade_value") is not None else norm_tv(r.get("trde_prica")),
            "change_rate":n(r.get("flu_rt")) if n(r.get("flu_rt")) is not None else d.get("change"),
            "market_cap_krw":d.get("market_cap"),
            "official_sector":m.get("official_sector"),
            "market_theme":None,
            "current_price_krw":n(r.get("cur_prc")) if n(r.get("cur_prc")) is not None else d.get("price"),
        })

    sectors=[]; indices=[]
    for inds,name in (("001","KOSPI"),("101","KOSDAQ")):
        rows=fetch_all("ka20003","/api/dostk/sect",{"inds_cd":inds},"all_inds_idex",10)
        primary=None
        for rr in rows:
            scode=str(rr.get("stk_cd") or rr.get("stk_nm") or "")
            sname=str(rr.get("stk_nm") or rr.get("stk_cd") or "")
            sectors.append({
                "sector_code":scode,
                "sector_name":sname,
                "change_rate":n(rr.get("flu_rt")),
                "trade_value_krw":norm_tv(rr.get("trde_prica")),
                "rising_count":int(n(rr.get("rising")) or 0),
                "flat_count":int(n(rr.get("stdns")) or 0),
                "falling_count":int(n(rr.get("fall")) or 0),
            })
            if str(rr.get("stk_cd") or "")==inds or name.lower() in sname.lower() or "종합" in sname:
                primary=rr
        if not primary and rows: primary=rows[0]
        if primary:
            indices.append({
                "index_code":inds,"index_name":name,
                "current_value":n(primary.get("cur_prc")),"change_rate":n(primary.get("flu_rt")),
                "open_value":None,"high_value":None,"low_value":None,
            })

    return {
        "mode":MODE,
        "source":"windows",
        "snapshot_time":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "rank":rank_out,
        "trade":trade_out,
        "sectors":sectors,
        "indices":indices,
        "stock_meta":list(stock_meta.values()) if last_meta_refresh and datetime.now(timezone.utc)-last_meta_refresh<timedelta(minutes=2) else [],
    }

def push(payload):
    r=requests.post(
        INGEST_URL+"/api/kiwoom/ingest",
        json=payload,
        headers={"x-kiwoom-ingest-token":INGEST_TOKEN,"User-Agent":"telegram-stock-radar-windows-feed/1.0"},
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code>=400:
        raise RuntimeError(f"Radar ingest HTTP {r.status_code}: {r.text[:300]}")
    return r.json()

def validate_config():
    missing=[]
    if MODE not in ("demo","real"): missing.append("KIWOOM_MODE must be demo or real")
    if not APPKEY: missing.append("Kiwoom APP_KEY")
    if not SECRET: missing.append("Kiwoom APP_SECRET")
    if not INGEST_URL.startswith("https://"): missing.append("RADAR_INGEST_URL (https://...)")
    if not INGEST_TOKEN: missing.append("KIWOOM_INGEST_TOKEN")
    if missing:
        raise RuntimeError("Missing config: "+", ".join(missing))

def main():
    validate_config()
    logging.info("Kiwoom Windows Feed started | mode=%s | poll=%ss | endpoint=%s",MODE,POLL,INGEST_URL)
    failures=0
    while True:
        started=time.time()
        try:
            payload=collect()
            ack=push(payload)
            failures=0
            logging.info("OK rank=%s trade=%s sectors=%s snapshot=%s",ack.get("rank"),ack.get("trade"),ack.get("sectors"),ack.get("snapshot_time"))
        except KeyboardInterrupt:
            logging.info("stopped by user")
            return
        except Exception as e:
            failures+=1
            logging.error("cycle failed (%d): %s",failures,str(e))
            # Avoid hammering Kiwoom/Railway during outages.
            if failures>=3: time.sleep(min(300,30*failures))
        elapsed=time.time()-started
        time.sleep(max(1,POLL-elapsed))

if __name__=="__main__":
    main()
