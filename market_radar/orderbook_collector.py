"""Kiwoom 10-level order-book collector for AI Brokerage execution research.

Read-only. Uses official ka10004 (국내주식 > 시세 > 주식호가요청).
No order endpoints are called. Targets only currently relevant AI/Paper/Shadow names.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
import os
import time

import psycopg
from psycopg.rows import dict_row

import kiwoom_feed as kw

DB=os.getenv("DATABASE_URL","")
POLL=max(5,min(120,int(os.getenv("ORDERBOOK_POLL_SECONDS","15"))))
MAX_CODES=max(1,min(50,int(os.getenv("ORDERBOOK_MAX_CODES","15"))))
TARGET_LOOKBACK_MIN=max(1,min(120,int(os.getenv("ORDERBOOK_TARGET_LOOKBACK_MINUTES","20"))))
VENUE_SUFFIX=os.getenv("ORDERBOOK_VENUE_SUFFIX","_AL").strip()

SCHEMA="""
CREATE TABLE IF NOT EXISTS market_orderbook_snapshots(
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  request_code TEXT NOT NULL,
  venue TEXT NOT NULL,
  book_time_raw TEXT,
  best_ask_krw NUMERIC,
  best_bid_krw NUMERIC,
  spread_krw NUMERIC,
  spread_bps DOUBLE PRECISION,
  total_ask_qty BIGINT,
  total_bid_qty BIGINT,
  asks JSONB NOT NULL,
  bids JSONB NOT NULL,
  source_api TEXT NOT NULL DEFAULT 'ka10004',
  quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY(snapshot_time,stock_code,venue)
);
CREATE INDEX IF NOT EXISTS idx_orderbook_code_time
  ON market_orderbook_snapshots(stock_code,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS orderbook_feed_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  mode TEXT,
  target_count INTEGER NOT NULL DEFAULT 0,
  saved_count INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419071,))
        cur.execute(SCHEMA)

def finite(v):
    try:
        s=str(v).replace(",","").strip()
        if not s:return None
        x=float(s)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def positive_price(v):
    x=finite(v)
    return abs(x) if x not in (None,0) else None

def qty(v):
    x=finite(v)
    return max(0,int(abs(x))) if x is not None else None

def normalize_book(raw,code,request_code,received_at):
    asks=[]
    bids=[]
    ask1=positive_price(raw.get("sel_fpr_bid")); askq1=qty(raw.get("sel_fpr_req"))
    bid1=positive_price(raw.get("buy_fpr_bid")); bidq1=qty(raw.get("buy_fpr_req"))
    if ask1 is not None:asks.append({"level":1,"price_krw":ask1,"qty":askq1 or 0})
    if bid1 is not None:bids.append({"level":1,"price_krw":bid1,"qty":bidq1 or 0})
    for level in range(2,11):
        ap=positive_price(raw.get(f"sel_{level}th_pre_bid")); aq=qty(raw.get(f"sel_{level}th_pre_req"))
        bp=positive_price(raw.get(f"buy_{level}th_pre_bid")); bq=qty(raw.get(f"buy_{level}th_pre_req"))
        if ap is not None:asks.append({"level":level,"price_krw":ap,"qty":aq or 0})
        if bp is not None:bids.append({"level":level,"price_krw":bp,"qty":bq or 0})
    asks.sort(key=lambda x:(x["price_krw"],x["level"]))
    bids.sort(key=lambda x:(-x["price_krw"],x["level"]))
    best_ask=asks[0]["price_krw"] if asks else None
    best_bid=bids[0]["price_krw"] if bids else None
    spread=(best_ask-best_bid) if best_ask is not None and best_bid is not None else None
    mid=((best_ask+best_bid)/2) if best_ask is not None and best_bid is not None else None
    spread_bps=(spread/mid*10_000) if spread is not None and mid and mid>0 else None
    flags=[]
    if not asks:flags.append("ASKS_MISSING")
    if not bids:flags.append("BIDS_MISSING")
    if best_ask is not None and best_bid is not None and best_ask<best_bid:flags.append("CROSSED_BOOK")
    if len(asks)<5:flags.append("ASK_DEPTH_THIN")
    if len(bids)<5:flags.append("BID_DEPTH_THIN")
    return {
        "snapshot_time":received_at,
        "stock_code":code,
        "request_code":request_code,
        "venue":"SOR" if request_code.endswith("_AL") else "NXT" if request_code.endswith("_NX") else "KRX",
        "book_time_raw":str(raw.get("bid_req_base_tm") or "")[:20] or None,
        "best_ask_krw":best_ask,"best_bid_krw":best_bid,
        "spread_krw":spread,"spread_bps":spread_bps,
        "total_ask_qty":qty(raw.get("tot_sel_req")),
        "total_bid_qty":qty(raw.get("tot_buy_req")),
        "asks":asks,"bids":bids,"quality_flags":flags,
    }

def target_codes(cur):
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=TARGET_LOOKBACK_MIN)
    scored={}
    if table_exists(cur,"ai_brokerage_decisions"):
        cur.execute("""SELECT stock_code,MAX(conviction) AS score
                       FROM ai_brokerage_decisions
                       WHERE snapshot_time>=%s AND state IN('PAPER_ENTRY','READY','WATCH')
                       GROUP BY stock_code""",(cutoff,))
        for r in cur.fetchall():
            scored[str(r["stock_code"])]=max(scored.get(str(r["stock_code"]),0),float(r["score"] or 0)+100)
    if table_exists(cur,"radar_paper_trades"):
        cur.execute("""SELECT stock_code FROM radar_paper_trades
                       WHERE status='OPEN' OR opened_at>=%s""",(cutoff,))
        for r in cur.fetchall():scored[str(r["stock_code"])]=max(scored.get(str(r["stock_code"]),0),250)
    if table_exists(cur,"ai_shadow_trades"):
        cur.execute("""SELECT stock_code FROM ai_shadow_trades
                       WHERE status='OPEN' OR entry_at>=%s""",(cutoff,))
        for r in cur.fetchall():scored[str(r["stock_code"])]=max(scored.get(str(r["stock_code"]),0),300)
    return [code for code,_ in sorted(scored.items(),key=lambda kv:(-kv[1],kv[0]))[:MAX_CODES]]

def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s)",("public."+name,))
    r=cur.fetchone()
    return bool(r and r["to_regclass"] is not None)

def save(cur,book):
    cur.execute("""INSERT INTO market_orderbook_snapshots(
                   snapshot_time,stock_code,request_code,venue,book_time_raw,best_ask_krw,best_bid_krw,
                   spread_krw,spread_bps,total_ask_qty,total_bid_qty,asks,bids,quality_flags)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
                   ON CONFLICT DO NOTHING""",
                (book["snapshot_time"],book["stock_code"],book["request_code"],book["venue"],
                 book["book_time_raw"],book["best_ask_krw"],book["best_bid_krw"],book["spread_krw"],
                 book["spread_bps"],book["total_ask_qty"],book["total_bid_qty"],
                 json.dumps(book["asks"],ensure_ascii=False),json.dumps(book["bids"],ensure_ascii=False),
                 json.dumps(book["quality_flags"],ensure_ascii=False)))

def cycle():
    now=datetime.now(timezone.utc)
    with db() as c,c.cursor() as cur:
        codes=target_codes(cur)
    saved=0
    errors=0
    for code in codes:
        request_code=code+VENUE_SUFFIX if VENUE_SUFFIX and not code.endswith(("_AL","_NX")) else code
        try:
            raw,_=kw.call("ka10004","/api/dostk/mrkcond",{"stk_cd":request_code})
            received=datetime.now(timezone.utc)
            book=normalize_book(raw,code,request_code,received)
            with db() as c,c.cursor() as cur:
                save(cur,book)
            saved+=1
        except Exception:
            errors+=1
        time.sleep(.08)
    with db() as c,c.cursor() as cur:
        status="OK" if saved else "WAITING_FOR_TARGETS" if not codes else "ERROR"
        cur.execute("""INSERT INTO orderbook_feed_status(id,updated_at,status,mode,target_count,saved_count,note)
                       VALUES(1,now(),%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,mode=excluded.mode,
                         target_count=excluded.target_count,saved_count=excluded.saved_count,note=excluded.note""",
                    (status,kw.MODE,len(codes),saved,
                     f"ka10004 read-only; venue_suffix={VENUE_SUFFIX or 'KRX'}; errors={errors}"))
    return {"targets":len(codes),"saved":saved,"errors":errors}

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Order-book collector started: ka10004 read-only; no orders",flush=True)
    while True:
        started=time.monotonic()
        try:cycle()
        except Exception as exc:print("Order-book collector error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
