"""Kiwoom domestic-stock realtime (0B) observer.

Official source contract:
- WebSocket: /api/dostk/websocket
- REG packet with type 0B
- FID 10 current price, 15 trade volume, 13 cumulative volume,
  228 execution strength, 1032 buy ratio, 1313 instantaneous trade value.

This worker is observation-only. It never submits orders. Exact KRW trade value
is computed from received tick price * absolute tick volume; gaps detected via
cumulative volume are flagged rather than invented.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime,timezone,timedelta
import json
import os
import re
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import requests

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    from websockets import connect as ws_connect

KST=ZoneInfo("Asia/Seoul")
DB=os.getenv("DATABASE_URL","")
MODE=os.getenv("KIWOOM_MODE","demo").strip().lower()
ENABLED=os.getenv("KIWOOM_REALTIME_ENABLED","0").strip()=="1"
TOP_N=max(1,min(100,int(os.getenv("KIWOOM_REALTIME_TOP_N","30"))))
UNIVERSE_SEC=max(10,int(os.getenv("KIWOOM_REALTIME_UNIVERSE_SECONDS","30")))
FLUSH_SEC=max(1,int(os.getenv("KIWOOM_REALTIME_FLUSH_SECONDS","2")))
HTTP_TIMEOUT=max(5,int(os.getenv("KIWOOM_REALTIME_HTTP_TIMEOUT","20")))
BASE=(os.getenv("PRD","https://api.kiwoom.com") if MODE=="real"
      else os.getenv("MOCK","https://mockapi.kiwoom.com")).rstrip("/")
WS_BASE=(os.getenv("W_PRD","wss://api.kiwoom.com:10000") if MODE=="real"
         else os.getenv("W_MOCK","wss://mockapi.kiwoom.com:10000")).rstrip("/")
APPKEY=os.getenv("APP_KEY","") if MODE=="real" else os.getenv("APP_KEY_MOCK","")
SECRET=os.getenv("APP_SECRET","") if MODE=="real" else os.getenv("APP_SECRET_MOCK","")
WS_PATH="/api/dostk/websocket"

SCHEMA=r"""
CREATE TABLE IF NOT EXISTS market_realtime_minute_bars(
  minute_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  open_price NUMERIC,
  high_price NUMERIC,
  low_price NUMERIC,
  close_price NUMERIC,
  volume NUMERIC NOT NULL DEFAULT 0,
  trade_value_krw NUMERIC NOT NULL DEFAULT 0,
  buy_volume NUMERIC NOT NULL DEFAULT 0,
  sell_volume NUMERIC NOT NULL DEFAULT 0,
  tick_count INTEGER NOT NULL DEFAULT 0,
  gap_count INTEGER NOT NULL DEFAULT 0,
  last_strength DOUBLE PRECISION,
  last_buy_ratio DOUBLE PRECISION,
  last_cum_volume NUMERIC,
  last_cum_turnover_raw TEXT,
  last_exchange TEXT,
  source TEXT NOT NULL DEFAULT 'KIWOOM_0B',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(minute_time,stock_code)
);
CREATE INDEX IF NOT EXISTS idx_realtime_bar_code_time
 ON market_realtime_minute_bars(stock_code,minute_time DESC);

CREATE TABLE IF NOT EXISTS market_realtime_5s_bars(
  bucket_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  open_price NUMERIC,
  high_price NUMERIC,
  low_price NUMERIC,
  close_price NUMERIC,
  volume NUMERIC NOT NULL DEFAULT 0,
  trade_value_krw NUMERIC NOT NULL DEFAULT 0,
  buy_volume NUMERIC NOT NULL DEFAULT 0,
  sell_volume NUMERIC NOT NULL DEFAULT 0,
  tick_count INTEGER NOT NULL DEFAULT 0,
  gap_count INTEGER NOT NULL DEFAULT 0,
  last_strength DOUBLE PRECISION,
  last_buy_ratio DOUBLE PRECISION,
  last_cum_volume NUMERIC,
  last_cum_turnover_raw TEXT,
  last_exchange TEXT,
  source TEXT NOT NULL DEFAULT 'KIWOOM_0B',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(bucket_time,stock_code)
);
CREATE INDEX IF NOT EXISTS idx_realtime_5s_code_time
 ON market_realtime_5s_bars(stock_code,bucket_time DESC);

CREATE TABLE IF NOT EXISTS kiwoom_realtime_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  mode TEXT,
  connected BOOLEAN NOT NULL DEFAULT false,
  last_message_at TIMESTAMPTZ,
  subscribed_count INTEGER NOT NULL DEFAULT 0,
  tick_count BIGINT NOT NULL DEFAULT 0,
  gap_count BIGINT NOT NULL DEFAULT 0,
  note TEXT,
  last_error TEXT
);
"""


def db(read_only=False):
    c=psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
                      options="-c statement_timeout=15000 -c lock_timeout=3000")
    if read_only:c.execute("SET TRANSACTION READ ONLY")
    return c


def exists(cur,name):
    cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
    return cur.fetchone()["name"] is not None


def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419079)")
        cur.execute(SCHEMA)


def num(v):
    try:
        s=str(v).replace(",","").strip()
        if not s:return None
        return float(s)
    except (TypeError,ValueError):
        return None


def price(v):
    x=num(v)
    return abs(x) if x is not None else None


def code_of(v):
    return re.sub(r"_(AL|NX)$","",str(v or "").strip())


def issue_token():
    r=requests.post(BASE+"/oauth2/token",
        json={"grant_type":"client_credentials","appkey":APPKEY,"secretkey":SECRET},
        headers={"Content-Type":"application/json;charset=UTF-8"},timeout=HTTP_TIMEOUT)
    try:d=r.json()
    except Exception:d={}
    if r.status_code>=400 or d.get("return_code") not in (None,0) or not d.get("token"):
        raise RuntimeError("KIWOOM_REALTIME_AUTH_FAILED")
    return d["token"]


def status(state,*,connected=False,last_message=None,subscribed=0,ticks=0,gaps=0,note=None,error=None):
    try:
        with db() as c,c.cursor() as cur:
            cur.execute("""INSERT INTO kiwoom_realtime_status(
                id,updated_at,status,mode,connected,last_message_at,subscribed_count,tick_count,gap_count,note,last_error)
                VALUES(1,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,mode=excluded.mode,
                connected=excluded.connected,last_message_at=COALESCE(excluded.last_message_at,kiwoom_realtime_status.last_message_at),
                subscribed_count=excluded.subscribed_count,tick_count=excluded.tick_count,gap_count=excluded.gap_count,
                note=excluded.note,last_error=excluded.last_error""",
                (state,MODE,connected,last_message,subscribed,ticks,gaps,note,error))
    except Exception:
        pass


def universe():
    """Prioritize recent Market OS FOCUS/PREP, then rank/trade leaders."""
    codes=[]
    with db(True) as c,c.cursor() as cur:
        if exists(cur,"market_os_assessment_snapshots"):
            cur.execute("""SELECT DISTINCT ON(stock_code) stock_code,watch_tier,snapshot_time
                           FROM market_os_assessment_snapshots
                           WHERE snapshot_time>now()-interval '10 minutes'
                             AND watch_tier IN('FOCUS','PREP')
                           ORDER BY stock_code,snapshot_time DESC""")
            rows=cur.fetchall()
            rows.sort(key=lambda r:(0 if r["watch_tier"]=="FOCUS" else 1,-r["snapshot_time"].timestamp()))
            for r in rows:
                if r["stock_code"] not in codes:codes.append(r["stock_code"])
        for table in ("market_trade_value_snapshots","market_rank_snapshots"):
            if not exists(cur,table):continue
            cur.execute(f"SELECT MAX(snapshot_time) AS t FROM {table}");t=cur.fetchone()["t"]
            if not t:continue
            cur.execute(f"""SELECT stock_code FROM {table}
                            WHERE snapshot_time=%s ORDER BY rank_no NULLS LAST LIMIT 60""",(t,))
            for r in cur.fetchall():
                if r["stock_code"] and r["stock_code"] not in codes:codes.append(r["stock_code"])
    return [c for c in codes if re.fullmatch(r"[0-9A-Z]{6}",c)][:TOP_N]


def seed_cumulative(codes):
    out={}
    if not codes:return out
    with db(True) as c,c.cursor() as cur:
        if not exists(cur,"market_realtime_minute_bars"):return out
        cur.execute("""SELECT DISTINCT ON(stock_code) stock_code,last_cum_volume,minute_time
                       FROM market_realtime_minute_bars
                       WHERE stock_code=ANY(%s)
                         AND (minute_time AT TIME ZONE 'Asia/Seoul')::date=(now() AT TIME ZONE 'Asia/Seoul')::date
                       ORDER BY stock_code,minute_time DESC""",(codes,))
        for r in cur.fetchall():
            v=num(r["last_cum_volume"])
            if v is not None:out[r["stock_code"]]=v
    return out


class Aggregator:
    def __init__(self):
        self.pending_minute={}
        self.pending_5s={}
        # Backward-compatible alias used by pure tests and simple diagnostics.
        self.pending=self.pending_minute
        self.last_cum={}
        self.total_ticks=0
        self.total_gaps=0
        self.baseline_codes=set()

    def set_codes(self,codes):
        seeded=seed_cumulative(codes)
        for code,v in seeded.items():
            self.last_cum.setdefault(code,v)
        # The first tick after subscribe/reconnect establishes a fresh baseline.
        # Any cumulative-volume jump since the previous process is downtime, not
        # an in-stream packet-loss event. Missing time is handled by bar coverage.
        self.baseline_codes.update(codes)

    @staticmethod
    def _accumulate(store,key,time_key,ts,code,px,vol,signed_vol,gap,vals,cum):
        p=store.get(key)
        if p is None:
            p={time_key:ts,"code":code,"open":px,"high":px,"low":px,"close":px,
               "volume":0.0,"turnover":0.0,"buy_volume":0.0,"sell_volume":0.0,
               "ticks":0,"gaps":0,"strength":None,"buy_ratio":None,"cum":None,
               "cum_turnover_raw":None,"exchange":None}
            store[key]=p
        p["high"]=max(p["high"],px);p["low"]=min(p["low"],px);p["close"]=px
        p["volume"]+=vol;p["turnover"]+=px*vol;p["ticks"]+=1;p["gaps"]+=gap
        # Signed realtime volume is retained as an aggressor-side inference.
        if signed_vol>0:p["buy_volume"]+=vol
        elif signed_vol<0:p["sell_volume"]+=vol
        p["strength"]=num(vals.get("228"));p["buy_ratio"]=num(vals.get("1032"))
        p["cum"]=cum;p["cum_turnover_raw"]=str(vals.get("14") or "")[:48]
        p["exchange"]=str(vals.get("9081") or "")[:20]

    def add(self,entry,received_at):
        if not isinstance(entry,dict) or str(entry.get("type"))!="0B":return
        code=code_of(entry.get("item"))
        vals=entry.get("values") or {}
        if not re.fullmatch(r"[0-9A-Z]{6}",code) or not isinstance(vals,dict):return
        px=price(vals.get("10"));signed_vol=num(vals.get("15"));cum=num(vals.get("13"))
        if px is None or px<=0 or signed_vol is None:return
        vol=abs(signed_vol)
        if vol<=0:return

        prev=self.last_cum.get(code);gap=0
        if cum is not None:
            if code in self.baseline_codes:
                self.baseline_codes.discard(code)
            elif prev is not None:
                delta=cum-prev
                if delta==0:return
                if delta>0 and delta>vol+1e-9:gap=1
            self.last_cum[code]=cum

        local=received_at.astimezone(KST)
        hhmmss=str(vals.get("20") or "").strip().replace(":","")
        if re.fullmatch(r"\d{6}",hhmmss):
            try:
                local=datetime.combine(local.date(),datetime.strptime(hhmmss,"%H%M%S").time(),tzinfo=KST)
            except ValueError:
                pass

        minute=local.replace(second=0,microsecond=0).astimezone(timezone.utc)
        bucket5=local.replace(second=(local.second//5)*5,microsecond=0).astimezone(timezone.utc)
        self._accumulate(self.pending_minute,(code,minute),"minute",minute,code,px,vol,signed_vol,gap,vals,cum)
        self._accumulate(self.pending_5s,(code,bucket5),"bucket",bucket5,code,px,vol,signed_vol,gap,vals,cum)
        self.total_ticks+=1;self.total_gaps+=gap

    def flush(self):
        if not self.pending_minute and not self.pending_5s:return 0
        minute_rows=list(self.pending_minute.values())
        five_rows=list(self.pending_5s.values())
        self.pending_minute={};self.pending_5s={};self.pending=self.pending_minute
        with db() as c,c.cursor() as cur:
            if minute_rows:
                cur.executemany("""INSERT INTO market_realtime_minute_bars(
                  minute_time,stock_code,open_price,high_price,low_price,close_price,volume,trade_value_krw,
                  buy_volume,sell_volume,tick_count,gap_count,last_strength,last_buy_ratio,last_cum_volume,
                  last_cum_turnover_raw,last_exchange,updated_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                  ON CONFLICT(minute_time,stock_code) DO UPDATE SET
                    high_price=GREATEST(market_realtime_minute_bars.high_price,excluded.high_price),
                    low_price=LEAST(market_realtime_minute_bars.low_price,excluded.low_price),
                    close_price=excluded.close_price,
                    volume=market_realtime_minute_bars.volume+excluded.volume,
                    trade_value_krw=market_realtime_minute_bars.trade_value_krw+excluded.trade_value_krw,
                    buy_volume=market_realtime_minute_bars.buy_volume+excluded.buy_volume,
                    sell_volume=market_realtime_minute_bars.sell_volume+excluded.sell_volume,
                    tick_count=market_realtime_minute_bars.tick_count+excluded.tick_count,
                    gap_count=market_realtime_minute_bars.gap_count+excluded.gap_count,
                    last_strength=excluded.last_strength,last_buy_ratio=excluded.last_buy_ratio,
                    last_cum_volume=excluded.last_cum_volume,last_cum_turnover_raw=excluded.last_cum_turnover_raw,
                    last_exchange=excluded.last_exchange,updated_at=now()""",
                    [(r["minute"],r["code"],r["open"],r["high"],r["low"],r["close"],r["volume"],r["turnover"],
                      r["buy_volume"],r["sell_volume"],r["ticks"],r["gaps"],r["strength"],r["buy_ratio"],r["cum"],
                      r["cum_turnover_raw"],r["exchange"]) for r in minute_rows])
            if five_rows:
                cur.executemany("""INSERT INTO market_realtime_5s_bars(
                  bucket_time,stock_code,open_price,high_price,low_price,close_price,volume,trade_value_krw,
                  buy_volume,sell_volume,tick_count,gap_count,last_strength,last_buy_ratio,last_cum_volume,
                  last_cum_turnover_raw,last_exchange,updated_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                  ON CONFLICT(bucket_time,stock_code) DO UPDATE SET
                    high_price=GREATEST(market_realtime_5s_bars.high_price,excluded.high_price),
                    low_price=LEAST(market_realtime_5s_bars.low_price,excluded.low_price),
                    close_price=excluded.close_price,
                    volume=market_realtime_5s_bars.volume+excluded.volume,
                    trade_value_krw=market_realtime_5s_bars.trade_value_krw+excluded.trade_value_krw,
                    buy_volume=market_realtime_5s_bars.buy_volume+excluded.buy_volume,
                    sell_volume=market_realtime_5s_bars.sell_volume+excluded.sell_volume,
                    tick_count=market_realtime_5s_bars.tick_count+excluded.tick_count,
                    gap_count=market_realtime_5s_bars.gap_count+excluded.gap_count,
                    last_strength=excluded.last_strength,last_buy_ratio=excluded.last_buy_ratio,
                    last_cum_volume=excluded.last_cum_volume,last_cum_turnover_raw=excluded.last_cum_turnover_raw,
                    last_exchange=excluded.last_exchange,updated_at=now()""",
                    [(r["bucket"],r["code"],r["open"],r["high"],r["low"],r["close"],r["volume"],r["turnover"],
                      r["buy_volume"],r["sell_volume"],r["ticks"],r["gaps"],r["strength"],r["buy_ratio"],r["cum"],
                      r["cum_turnover_raw"],r["exchange"]) for r in five_rows])
        return len(minute_rows)+len(five_rows)


async def recv_json(ws):
    raw=await ws.recv()
    if isinstance(raw,bytes):raw=raw.decode("utf-8")
    if isinstance(raw,str):
        try:return json.loads(raw)
        except json.JSONDecodeError:return raw
    return raw


async def login(ws,token):
    await ws.send(json.dumps({"trnm":"LOGIN","token":token},ensure_ascii=False))
    while True:
        msg=await recv_json(ws)
        if isinstance(msg,dict) and str(msg.get("trnm","")).upper()=="PING":
            await ws.send(json.dumps(msg,ensure_ascii=False));continue
        if not isinstance(msg,dict) or str(msg.get("trnm","")).upper()!="LOGIN":
            raise RuntimeError("KIWOOM_REALTIME_LOGIN_ACK_MISSING")
        if int(msg.get("return_code") or 0)!=0:
            raise RuntimeError("KIWOOM_REALTIME_LOGIN_FAILED")
        return


async def register(ws,codes):
    await ws.send(json.dumps({
        "trnm":"REG","grp_no":"1","refresh":"0",
        "data":[{"item":codes,"type":["0B"]}]
    },ensure_ascii=False))


async def run_once():
    token=issue_token()
    uri=WS_BASE+WS_PATH
    agg=Aggregator();codes=universe();agg.set_codes(codes)
    if not codes:
        status("WAITING_FOR_UNIVERSE",note="조회/거래대금/Market OS 후보 대기")
        await asyncio.sleep(10);return
    status("CONNECTING",subscribed=len(codes))
    last_msg=None;last_flush=time.monotonic();last_universe=time.monotonic()
    async with ws_connect(uri,open_timeout=HTTP_TIMEOUT,ping_interval=None) as ws:
        await login(ws,token);await register(ws,codes)
        status("OK",connected=True,subscribed=len(codes),note="0B observation-only")
        while True:
            timeout=max(.2,min(2.0,FLUSH_SEC-(time.monotonic()-last_flush)))
            try:
                msg=await asyncio.wait_for(recv_json(ws),timeout=timeout)
            except asyncio.TimeoutError:
                msg=None
            now=datetime.now(timezone.utc)
            if isinstance(msg,dict):
                trnm=str(msg.get("trnm","")).upper()
                if trnm=="PING":
                    await ws.send(json.dumps(msg,ensure_ascii=False))
                elif trnm=="REAL":
                    for entry in msg.get("data") or []:agg.add(entry,now)
                    last_msg=now
                elif trnm=="SYSTEM" and int(msg.get("return_code") or 0)!=0:
                    raise RuntimeError("KIWOOM_REALTIME_SYSTEM_ERROR")

            if time.monotonic()-last_flush>=FLUSH_SEC:
                agg.flush();last_flush=time.monotonic()
                status("OK",connected=True,last_message=last_msg,subscribed=len(codes),
                       ticks=agg.total_ticks,gaps=agg.total_gaps,note="0B observation-only; turnover=price×observed tick volume")

            if time.monotonic()-last_universe>=UNIVERSE_SEC:
                new=universe()
                if new and new!=codes:
                    await register(ws,new);codes=new;agg.set_codes(codes)
                last_universe=time.monotonic()


async def main():
    schema()
    if not ENABLED:
        status("DISABLED",note="KIWOOM_REALTIME_ENABLED=0")
        print("Kiwoom 0B realtime disabled",flush=True)
        while True:await asyncio.sleep(300)
    if not APPKEY or not SECRET:
        status("WAITING_FOR_CREDENTIALS",note="Kiwoom App Key/Secret 대기")
        print("Kiwoom 0B realtime waiting for credentials",flush=True)
        while True:await asyncio.sleep(60)
    delay=3
    while True:
        try:
            await run_once();delay=3
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status("ERROR",connected=False,error=type(exc).__name__,note="0B reconnect pending")
            print("Kiwoom 0B realtime error:",type(exc).__name__,flush=True)
            await asyncio.sleep(delay);delay=min(60,delay*2)


if __name__=="__main__":
    asyncio.run(main())
