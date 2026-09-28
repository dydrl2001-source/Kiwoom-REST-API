"""Shadow execution simulator for AI Brokerage.

Consumes already-created PAPER trades and estimates execution quality. It does not
send broker orders. v1 uses last-trade price, recent observed turnover and short
horizon volatility; it deliberately does not pretend to have bid/ask depth.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
import os
import statistics
import time

import psycopg
from psycopg.rows import dict_row

from ai_brokerage.execution_model import FillPolicy, SizingPolicy, estimate_fill, round_trip_result
from flow_core import delta as flow_delta

DB=os.getenv("DATABASE_URL","")
POLL=max(15,min(300,int(os.getenv("SHADOW_EXECUTION_POLL_SECONDS","30"))))
ACCOUNT_EQUITY=max(1_000_000,float(os.getenv("SHADOW_ACCOUNT_EQUITY_KRW","100000000")))
RISK_PCT=max(.05,min(5.0,float(os.getenv("SHADOW_RISK_PER_TRADE_PCT","0.5"))))
MAX_POSITION_PCT=max(.5,min(50.0,float(os.getenv("SHADOW_MAX_POSITION_PCT","10"))))
MAX_PARTICIPATION_PCT=max(.1,min(10.0,float(os.getenv("SHADOW_MAX_PARTICIPATION_PCT","2"))))
COMMISSION_BPS=max(0.0,float(os.getenv("SHADOW_COMMISSION_BPS","0")))
SELL_TAX_BPS=max(0.0,float(os.getenv("SHADOW_SELL_TAX_BPS","0")))

SIZING=SizingPolicy(account_equity_krw=ACCOUNT_EQUITY,risk_per_trade_pct=RISK_PCT,
                    max_position_pct=MAX_POSITION_PCT)
FILL=FillPolicy(max_participation_pct=MAX_PARTICIPATION_PCT,
                commission_bps=COMMISSION_BPS,sell_tax_bps=SELL_TAX_BPS)

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_shadow_trades(
  id BIGSERIAL PRIMARY KEY,
  paper_trade_id BIGINT UNIQUE NOT NULL REFERENCES radar_paper_trades(id) ON DELETE CASCADE,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  strategy_id TEXT,
  strategy_name TEXT,
  strategy_family TEXT,
  regime_label TEXT,
  status TEXT NOT NULL,
  requested_shares INTEGER NOT NULL DEFAULT 0,
  filled_shares INTEGER NOT NULL DEFAULT 0,
  requested_notional_krw NUMERIC,
  stop_pct DOUBLE PRECISION,
  entry_at TIMESTAMPTZ,
  entry_ref_price_krw NUMERIC,
  entry_fill_price_krw NUMERIC,
  entry_slippage_bps DOUBLE PRECISION,
  entry_fill_ratio DOUBLE PRECISION,
  entry_model_quality TEXT,
  exit_at TIMESTAMPTZ,
  exit_ref_price_krw NUMERIC,
  exit_fill_price_krw NUMERIC,
  exit_slippage_bps DOUBLE PRECISION,
  gross_return_pct DOUBLE PRECISION,
  net_return_pct DOUBLE PRECISION,
  gross_pnl_krw NUMERIC,
  net_pnl_krw NUMERIC,
  costs_krw NUMERIC,
  sizing JSONB NOT NULL DEFAULT '{}'::jsonb,
  entry_model JSONB NOT NULL DEFAULT '{}'::jsonb,
  exit_model JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_shadow_status_time ON ai_shadow_trades(status,entry_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_strategy_time ON ai_shadow_trades(strategy_id,entry_at DESC);

CREATE TABLE IF NOT EXISTS ai_shadow_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  open_count INTEGER NOT NULL DEFAULT 0,
  closed_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
"""

def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000')

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419070,))
        cur.execute(SCHEMA)

def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def quote_pair(cur,code,at):
    cur.execute("""SELECT batch_time,payload FROM radar_flow_quotes
                   WHERE stock_code=%s
                     AND batch_time<=%s+interval '60 seconds'
                     AND batch_time>=%s-interval '180 seconds'
                   ORDER BY batch_time DESC LIMIT 2""",(code,at,at))
    rows=cur.fetchall()
    if not rows:return None,None,None
    current=rows[0]["payload"] or {}
    previous=rows[1]["payload"] if len(rows)>1 else None
    recent=None
    if previous:
        value,state,_=flow_delta(current,previous)
        if state=="OK":recent=value
    price=finite(current.get("price_krw"))
    exchange=current.get("exchange_at")
    try:
        exchange=datetime.fromisoformat(exchange) if exchange else rows[0]["batch_time"]
    except ValueError:
        exchange=rows[0]["batch_time"]
    return price,recent,exchange

def volatility_bps(cur,code,at):
    cur.execute("""SELECT close_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3 AND bar_time<=%s
                   ORDER BY bar_time DESC LIMIT 21""",(code,at))
    raw=[finite(r["close_price"]) for r in reversed(cur.fetchall())]
    xs=[x for x in raw if x and x>0]
    if len(xs)<6:return None
    rets=[abs(b/a-1.0)*10_000.0 for a,b in zip(xs[:-1],xs[1:]) if a>0]
    return statistics.median(rets) if rets else None

def open_new(cur):
    cur.execute("""SELECT p.id,p.stock_code,p.stock_name,p.opened_at,p.entry_price_krw,
                          p.strategy_id,p.strategy_name,p.strategy_family,p.regime_label
                   FROM radar_paper_trades p
                   LEFT JOIN ai_shadow_trades s ON s.paper_trade_id=p.id
                   WHERE s.id IS NULL
                     AND p.strategy_id IS NOT NULL
                     AND p.opened_at>now()-interval '7 days'
                   ORDER BY p.opened_at LIMIT 50""")
    opened=0
    for p in cur.fetchall():
        ref,recent,exchange=quote_pair(cur,p["stock_code"],p["opened_at"])
        ref=ref or finite(p["entry_price_krw"])
        vol=volatility_bps(cur,p["stock_code"],p["opened_at"])
        sizing=SIZING.size(ref,vol) if ref else {"shares":0,"requested_notional_krw":0,"stop_pct":None}
        fill=estimate_fill("BUY",ref or 0,sizing.get("shares") or 0,recent,vol,FILL)
        status="OPEN" if fill.get("filled_shares",0)>0 else "REJECTED"
        cur.execute("""INSERT INTO ai_shadow_trades(
                       paper_trade_id,stock_code,stock_name,strategy_id,strategy_name,strategy_family,
                       regime_label,status,requested_shares,filled_shares,requested_notional_krw,stop_pct,
                       entry_at,entry_ref_price_krw,entry_fill_price_krw,entry_slippage_bps,
                       entry_fill_ratio,entry_model_quality,sizing,entry_model)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (p["id"],p["stock_code"],p["stock_name"],p["strategy_id"],p["strategy_name"],
                     p["strategy_family"],p["regime_label"],status,sizing.get("shares") or 0,
                     fill.get("filled_shares") or 0,sizing.get("requested_notional_krw"),sizing.get("stop_pct"),
                     exchange or p["opened_at"],ref,fill.get("fill_price_krw"),fill.get("slippage_bps"),
                     fill.get("fill_ratio"),fill.get("model_quality"),
                     json.dumps(sizing,ensure_ascii=False),json.dumps(fill,ensure_ascii=False)))
        opened+=1
    return opened

def close_ready(cur):
    cur.execute("""SELECT s.*,p.status AS paper_status,p.closed_at,p.exit_price_krw
                   FROM ai_shadow_trades s
                   JOIN radar_paper_trades p ON p.id=s.paper_trade_id
                   WHERE s.status='OPEN' AND p.status IN('CLOSED','CLOSED_NO_PRICE')
                   ORDER BY p.closed_at LIMIT 50""")
    closed=0
    for s in cur.fetchall():
        if not s["closed_at"]:
            continue
        ref,recent,exchange=quote_pair(cur,s["stock_code"],s["closed_at"])
        ref=ref or finite(s["exit_price_krw"])
        vol=volatility_bps(cur,s["stock_code"],s["closed_at"])
        exit_fill=estimate_fill("SELL",ref or 0,int(s["filled_shares"] or 0),recent,vol,FILL)
        entry_model=s["entry_model"] or {}
        result=round_trip_result(entry_model,exit_fill)
        status="CLOSED" if result.get("status")=="COMPLETE" else "CLOSED_NO_FILL"
        cur.execute("""UPDATE ai_shadow_trades
                       SET status=%s,exit_at=%s,exit_ref_price_krw=%s,exit_fill_price_krw=%s,
                           exit_slippage_bps=%s,gross_return_pct=%s,net_return_pct=%s,
                           gross_pnl_krw=%s,net_pnl_krw=%s,costs_krw=%s,
                           exit_model=%s::jsonb,updated_at=now()
                       WHERE id=%s""",
                    (status,exchange or s["closed_at"],ref,exit_fill.get("fill_price_krw"),
                     exit_fill.get("slippage_bps"),result.get("gross_return_pct"),result.get("net_return_pct"),
                     result.get("gross_pnl_krw"),result.get("net_pnl_krw"),result.get("costs_krw"),
                     json.dumps(exit_fill,ensure_ascii=False),s["id"]))
        closed+=1
    return closed

def update_status(cur):
    cur.execute("""SELECT COUNT(*) FILTER(WHERE status='OPEN') AS open_n,
                          COUNT(*) FILTER(WHERE status LIKE 'CLOSED%%') AS closed_n,
                          COUNT(*) FILTER(WHERE status='REJECTED') AS rejected_n
                   FROM ai_shadow_trades""")
    r=cur.fetchone()
    cur.execute("""INSERT INTO ai_shadow_status(id,updated_at,status,open_count,closed_count,rejected_count,note)
                   VALUES(1,now(),'OK',%s,%s,%s,%s)
                   ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',
                     open_count=excluded.open_count,closed_count=excluded.closed_count,
                     rejected_count=excluded.rejected_count,note=excluded.note""",
                (int(r["open_n"] or 0),int(r["closed_n"] or 0),int(r["rejected_n"] or 0),
                 f"shadow only; no orders; equity={ACCOUNT_EQUITY:.0f}; risk={RISK_PCT:.2f}%%; participation<={MAX_PARTICIPATION_PCT:.2f}%%; fees configurable"))

def cycle():
    with db() as c,c.cursor() as cur:
        open_new(cur)
        close_ready(cur)
        update_status(cur)

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    schema()
    print("Shadow execution simulator started; no broker orders",flush=True)
    while True:
        started=time.monotonic()
        try:cycle()
        except Exception as exc:
            print("Shadow simulator error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
