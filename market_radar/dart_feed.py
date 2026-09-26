import os,time,io,zipfile
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import requests
import psycopg

DB=os.getenv("DATABASE_URL","")
KEY=os.getenv("DART_API_KEY","").strip()
POLL=int(os.getenv("DART_POLL_SECONDS","60"))
MAP_REFRESH_HOURS=int(os.getenv("DART_CORP_MAP_REFRESH_HOURS","24"))
KST=ZoneInfo("Asia/Seoul")
BASE="https://opendart.fss.or.kr/api"

def db(): return psycopg.connect(DB)

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS dart_corp_map(
          corp_code TEXT PRIMARY KEY,
          corp_name TEXT,
          stock_code TEXT,
          modify_date TEXT,
          refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_dart_stock_code ON dart_corp_map(stock_code);

        CREATE TABLE IF NOT EXISTS dart_disclosures(
          rcept_no TEXT PRIMARY KEY,
          corp_code TEXT,
          stock_code TEXT,
          corp_name TEXT,
          corp_cls TEXT,
          report_nm TEXT,
          flr_nm TEXT,
          rcept_dt DATE,
          rm TEXT,
          category TEXT,
          disclosure_url TEXT,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_dart_stock_date ON dart_disclosures(stock_code,rcept_dt DESC);

        CREATE TABLE IF NOT EXISTS dart_feed_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,
          last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def set_status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO dart_feed_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,dart_feed_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(KST) if success else None,note,error));c.commit()

def classify(name):
    t=(name or "").replace(" ","")
    rules=[
      ("SUPPLY_CONTRACT",("단일판매","공급계약","수주")),
      ("EARNINGS",("영업(잠정)실적","매출액또는손익구조","연결재무제표기준영업")),
      ("CAPITAL",("유상증자","무상증자","전환사채","신주인수권","교환사채")),
      ("MNA",("합병","분할","주식교환","영업양수","영업양도","타법인주식")),
      ("SHAREHOLDER",("최대주주","주요주주","자기주식","자사주")),
      ("INVESTMENT",("시설투자","신규시설","투자판단","유형자산취득")),
      ("REGULATORY",("임상","품목허가","특허","소송")),
      ("DIVIDEND",("현금ㆍ현물배당","배당")),
    ]
    for cat,kws in rules:
        if any(k in t for k in kws): return cat
    return "DISCLOSURE"

def map_stale():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT MAX(refreshed_at) FROM dart_corp_map")
        x=cur.fetchone()[0]
    return (not x) or (datetime.now(KST)-x.astimezone(KST)>timedelta(hours=MAP_REFRESH_HOURS))

def refresh_map():
    r=requests.get(BASE+"/corpCode.xml",params={"crtfc_key":KEY},timeout=30)
    r.raise_for_status()
    z=zipfile.ZipFile(io.BytesIO(r.content))
    xml=z.read(z.namelist()[0])
    root=ET.fromstring(xml)
    rows=[]
    for el in root.findall(".//list"):
        corp=(el.findtext("corp_code") or "").strip()
        name=(el.findtext("corp_name") or "").strip()
        stock=(el.findtext("stock_code") or "").strip()
        mod=(el.findtext("modify_date") or "").strip()
        if corp: rows.append((corp,name,stock,mod))
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO dart_corp_map(corp_code,corp_name,stock_code,modify_date,refreshed_at)
        VALUES(%s,%s,%s,%s,now())
        ON CONFLICT(corp_code) DO UPDATE SET corp_name=excluded.corp_name,stock_code=excluded.stock_code,
        modify_date=excluded.modify_date,refreshed_at=now()""",rows)
        c.commit()
    return len(rows)

def corp_to_stock():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT corp_code,stock_code FROM dart_corp_map WHERE stock_code IS NOT NULL AND stock_code<>''")
        return {x[0]:x[1] for x in cur.fetchall()}

def fetch_today():
    today=datetime.now(KST).strftime("%Y%m%d")
    allrows=[];page=1
    while page<=3:
        r=requests.get(BASE+"/list.json",params={
            "crtfc_key":KEY,"bgn_de":today,"end_de":today,"page_no":page,"page_count":100
        },timeout=20)
        d=r.json()
        status=d.get("status")
        if status=="013": return []
        if status not in (None,"000"):
            raise RuntimeError(f"DART list failed: {status} {d.get('message')}")
        rows=d.get("list") or []
        allrows.extend(rows)
        total=int(d.get("total_count") or len(allrows))
        if len(allrows)>=total or not rows: break
        page+=1
        time.sleep(.15)
    return allrows

def store(rows,mapping):
    vals=[]
    for x in rows:
        rno=x.get("rcept_no")
        if not rno: continue
        corp=x.get("corp_code")
        stock=mapping.get(corp)
        dt=x.get("rcept_dt")
        try: dtv=datetime.strptime(dt,"%Y%m%d").date() if dt else None
        except: dtv=None
        report=x.get("report_nm")
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}"
        vals.append((rno,corp,stock,x.get("corp_name"),x.get("corp_cls"),report,x.get("flr_nm"),dtv,x.get("rm"),classify(report),url))
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO dart_disclosures(rcept_no,corp_code,stock_code,corp_name,corp_cls,report_nm,flr_nm,rcept_dt,rm,category,disclosure_url)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(rcept_no) DO UPDATE SET report_nm=excluded.report_nm,rm=excluded.rm,
        category=excluded.category,stock_code=excluded.stock_code,fetched_at=now()""",vals)
        cur.execute("DELETE FROM dart_disclosures WHERE rcept_dt < current_date-interval '30 days'")
        c.commit()
    return len(vals)

def cycle():
    if not KEY:
        set_status("WAITING_FOR_KEY","DART_API_KEY 미설정")
        return
    mapped=0
    if map_stale(): mapped=refresh_map()
    mp=corp_to_stock()
    rows=fetch_today()
    count=store(rows,mp)
    set_status("OK",f"today={count} corp_map_refresh={mapped}",success=True)

def main():
    schema();print("DART feed started",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            set_status("ERROR","DART 수집 오류",str(e)[:500]);print("DART error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
