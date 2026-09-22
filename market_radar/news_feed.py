import os, time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
import requests
import psycopg

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("NEWS_POLL_SECONDS","60"))
REFRESH_MIN=int(os.getenv("NEWS_REFRESH_MINUTES","15"))
TOPN=int(os.getenv("NEWS_TOP_STOCKS","20"))

def db():
    return psycopg.connect(DB)

def schema():
    with db() as c, c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_news_cache(
          stock_code TEXT NOT NULL,
          stock_name TEXT,
          title TEXT NOT NULL,
          source TEXT,
          published_at TIMESTAMPTZ,
          link TEXT NOT NULL,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(stock_code,link)
        );
        CREATE INDEX IF NOT EXISTS idx_news_stock_time ON stock_news_cache(stock_code,published_at DESC);
        CREATE TABLE IF NOT EXISTS news_feed_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL,
          last_success_at TIMESTAMPTZ,
          note TEXT,
          last_error TEXT
        );
        """)
        c.commit()

def set_status(status,note=None,error=None,success=False):
    with db() as c, c.cursor() as cur:
        cur.execute("""
        INSERT INTO news_feed_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
          last_success_at=COALESCE(excluded.last_success_at,news_feed_status.last_success_at),
          note=excluded.note,last_error=excluded.last_error
        """,(status,datetime.now(timezone.utc) if success else None,note,error))
        c.commit()

def latest_universe():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.market_rank_snapshots')")
        if not cur.fetchone()[0]:
            return []
        cur.execute("SELECT MAX(snapshot_time) FROM market_rank_snapshots")
        t=cur.fetchone()[0]
        if not t:
            return []
        cur.execute("""SELECT stock_code,stock_name FROM market_rank_snapshots
                       WHERE snapshot_time=%s AND stock_name IS NOT NULL
                       ORDER BY rank_no NULLS LAST LIMIT %s""",(t,TOPN))
        return cur.fetchall()

def needs_refresh(code):
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT MAX(fetched_at) FROM stock_news_cache WHERE stock_code=%s",(code,))
        r=cur.fetchone()[0]
    return (not r) or datetime.now(timezone.utc)-r > timedelta(minutes=REFRESH_MIN)

def parse_dt(v):
    if not v:
        return None
    try:
        d=parsedate_to_datetime(v)
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fetch_news(code,name):
    params={"q":f'"{name}" when:1d',"hl":"ko","gl":"KR","ceid":"KR:ko"}
    url="https://news.google.com/rss/search?"+urlencode(params)
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0 MarketRadar/0.1"},timeout=15)
    r.raise_for_status()
    root=ET.fromstring(r.content)
    items=[]
    for item in root.findall(".//item")[:8]:
        title=(item.findtext("title") or "").strip()
        link=(item.findtext("link") or "").strip()
        source=(item.findtext("source") or "").strip()
        pub=parse_dt(item.findtext("pubDate"))
        if title and link:
            items.append((code,name,title,source,pub,link))
    with db() as c, c.cursor() as cur:
        for row in items:
            cur.execute("""INSERT INTO stock_news_cache(stock_code,stock_name,title,source,published_at,link,fetched_at)
                           VALUES(%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT(stock_code,link) DO UPDATE SET title=excluded.title,source=excluded.source,
                           published_at=excluded.published_at,fetched_at=now()""",row)
        cur.execute("DELETE FROM stock_news_cache WHERE fetched_at < now()-interval '7 days'")
        c.commit()
    return len(items)

def cycle():
    uni=latest_universe()
    if not uni:
        set_status("WAITING_FOR_MARKET_DATA","실시간 조회순위 데이터 대기")
        return
    total=0; checked=0
    for code,name in uni:
        if not needs_refresh(code):
            continue
        try:
            total+=fetch_news(code,name)
            checked+=1
        except Exception as e:
            print("news fetch error",code,name,str(e)[:200],flush=True)
        time.sleep(0.4)
    set_status("OK",f"stocks_checked={checked} news_items={total}",success=True)

def main():
    schema()
    print(f"News feed started: top={TOPN}, refresh={REFRESH_MIN}m",flush=True)
    while True:
        try:
            cycle()
        except Exception as e:
            set_status("ERROR","외부 뉴스 수집 오류",str(e)[:500])
            print("news feed error",str(e)[:500],flush=True)
        time.sleep(POLL)

if __name__=="__main__":
    main()
