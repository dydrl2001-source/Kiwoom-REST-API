"""Incrementally map observed stocks to Kiwoom's official theme groups.

This is a market-theme membership feed, not a claim about the cause of today's price move.
It reuses the existing Kiwoom credentials and only reads market/theme endpoints.
"""
import os,time
from datetime import datetime,timezone,timedelta
import psycopg
import kiwoom_feed as base

DB=os.getenv("DATABASE_URL","")
POLL=int(os.getenv("THEME_POLL_SECONDS","60"))
BATCH=int(os.getenv("THEME_STOCKS_PER_CYCLE","5"))
REFRESH_H=int(os.getenv("THEME_REFRESH_HOURS","24"))

def db(): return psycopg.connect(DB)

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_theme_memberships(
          stock_code TEXT NOT NULL,
          theme_code TEXT NOT NULL,
          theme_name TEXT NOT NULL,
          theme_change_rate DOUBLE PRECISION,
          period_return DOUBLE PRECISION,
          stock_count INTEGER,
          main_stocks TEXT,
          refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY(stock_code,theme_code)
        );
        CREATE INDEX IF NOT EXISTS idx_theme_stock_refresh
          ON stock_theme_memberships(stock_code,refreshed_at DESC);

        CREATE TABLE IF NOT EXISTS stock_theme_refresh(
          stock_code TEXT PRIMARY KEY,
          refreshed_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL,
          theme_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS theme_feed_status(
          id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
          updated_at TIMESTAMPTZ NOT NULL,status TEXT NOT NULL,
          last_success_at TIMESTAMPTZ,note TEXT,last_error TEXT
        );
        """);c.commit()

def set_status(st,note=None,error=None,success=False):
    with db() as c,c.cursor() as cur:
        cur.execute("""INSERT INTO theme_feed_status(id,updated_at,status,last_success_at,note,last_error)
        VALUES(1,now(),%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,
        last_success_at=COALESCE(excluded.last_success_at,theme_feed_status.last_success_at),
        note=excluded.note,last_error=excluded.last_error""",
        (st,datetime.now(timezone.utc) if success else None,note,error))
        c.commit()

def universe():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.radar_flow_quotes')")
        if not cur.fetchone()[0]: return []
        cur.execute("SELECT MAX(batch_time) FROM radar_flow_quotes");t=cur.fetchone()[0]
        if not t:return []
        cur.execute("""SELECT stock_code,payload->>'name',
                      NULLIF(payload->>'query_rank','')::int,
                      NULLIF(payload->>'trade_rank','')::int
                      FROM radar_flow_quotes WHERE batch_time=%s""",(t,))
        rows=cur.fetchall()
        cur.execute("SELECT stock_code,refreshed_at FROM stock_theme_refresh")
        seen={x[0]:x[1] for x in cur.fetchall()}
    now=datetime.now(timezone.utc)
    candidates=[]
    for code,name,qr,tr in rows:
        last=seen.get(code)
        stale=last is None or now-last>timedelta(hours=REFRESH_H)
        if stale:
            score=min(qr or 999,tr or 999)
            candidates.append((score,code,name))
    candidates.sort()
    return candidates[:BATCH]

def fetch_themes(code):
    body={"qry_tp":"2","date_tp":"1","flu_pl_amt_tp":"3","stex_tp":"3",
          "stk_cd":code,"thema_nm":""}
    return base.fetch_all("ka90001","/api/dostk/thme",body,"thema_grp",10)

def store(code,rows):
    vals=[]
    for r in rows:
        tcode=str(r.get("thema_grp_cd") or "").strip()
        name=str(r.get("thema_nm") or "").strip()
        if not tcode or not name:continue
        vals.append((code,tcode,name,base.n(r.get("flu_rt")),base.n(r.get("dt_prft_rt")),
                     int(base.n(r.get("stk_num")) or 0) or None,str(r.get("main_stk") or "")[:1000]))
    with db() as c,c.cursor() as cur:
        cur.execute("DELETE FROM stock_theme_memberships WHERE stock_code=%s",(code,))
        if vals:
            cur.executemany("""INSERT INTO stock_theme_memberships(
              stock_code,theme_code,theme_name,theme_change_rate,period_return,stock_count,main_stocks,refreshed_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,now())""",vals)
        cur.execute("""INSERT INTO stock_theme_refresh(stock_code,refreshed_at,status,theme_count)
          VALUES(%s,now(),%s,%s)
          ON CONFLICT(stock_code) DO UPDATE SET refreshed_at=now(),status=excluded.status,theme_count=excluded.theme_count""",
          (code,"OK" if vals else "NO_THEME",len(vals)))
        c.commit()
    return len(vals)

def cycle():
    targets=universe()
    if not targets:
        set_status("IDLE","갱신할 관측 종목 없음",success=True);return
    done=themes=errors=0
    for _,code,name in targets:
        try:
            rows=fetch_themes(code)
            themes+=store(code,rows);done+=1
        except Exception as e:
            errors+=1
            with db() as c,c.cursor() as cur:
                cur.execute("""INSERT INTO stock_theme_refresh(stock_code,refreshed_at,status,theme_count)
                  VALUES(%s,now(),'ERROR',0)
                  ON CONFLICT(stock_code) DO UPDATE SET refreshed_at=now(),status='ERROR'""",(code,))
                c.commit()
            print("theme fetch error",code,type(e).__name__,flush=True)
        time.sleep(.25)
    set_status("PARTIAL" if errors else "OK",
               f"stocks={done} memberships={themes} errors={errors}",
               None,success=bool(done))

def main():
    schema()
    print(f"Theme feed started: batch={BATCH}, refresh={REFRESH_H}h",flush=True)
    while True:
        try:cycle()
        except Exception as e:
            set_status("ERROR","테마 매핑 오류",type(e).__name__)
            print("theme feed cycle error",type(e).__name__,flush=True)
        time.sleep(POLL)

if __name__=="__main__":main()
