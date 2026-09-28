"""Book-aware shadow execution simulator for AI Brokerage.

Consumes PAPER trades and estimates execution quality without sending broker orders.
v2 prefers official Kiwoom ka10004 10-level order books. If a fresh book is absent,
an explicitly-labelled turnover/volatility proxy may be used when enabled.
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

from ai_brokerage.execution_model import (
    BookPolicy,
    FillPolicy,
    PortfolioRiskPolicy,
    SizingPolicy,
    estimate_book_fill,
    estimate_fill,
    implementation_shortfall_summary,
    portfolio_risk_budget,
    round_trip_result,
)
from flow_core import delta as flow_delta

DB=os.getenv("DATABASE_URL","")
POLL=max(15,min(300,int(os.getenv("SHADOW_EXECUTION_POLL_SECONDS","30"))))
ACCOUNT_EQUITY=max(1_000_000,float(os.getenv("SHADOW_ACCOUNT_EQUITY_KRW","100000000")))
RISK_PCT=max(.05,min(5.0,float(os.getenv("SHADOW_RISK_PER_TRADE_PCT","0.5"))))
MAX_POSITION_PCT=max(.5,min(50.0,float(os.getenv("SHADOW_MAX_POSITION_PCT","10"))))
MAX_PARTICIPATION_PCT=max(.1,min(10.0,float(os.getenv("SHADOW_MAX_PARTICIPATION_PCT","2"))))
COMMISSION_BPS=max(0.0,float(os.getenv("SHADOW_COMMISSION_BPS","0")))
SELL_TAX_BPS=max(0.0,float(os.getenv("SHADOW_SELL_TAX_BPS","0")))
MAX_REPLAY_MINUTES=max(0,min(60,int(os.getenv("SHADOW_MAX_REPLAY_MINUTES","5"))))
ALLOW_PROXY_FALLBACK=os.getenv("SHADOW_ALLOW_PROXY_FALLBACK","1").strip().lower() in ("1","true","yes","on")
BOOK_MAX_AGE_SEC=max(5,min(120,int(os.getenv("SHADOW_BOOK_MAX_AGE_SECONDS","30"))))
BOOK_HAIRCUT=max(.05,min(1.0,float(os.getenv("SHADOW_BOOK_LIQUIDITY_HAIRCUT","0.5"))))
BOOK_MAX_SPREAD_BPS=max(5.0,min(500.0,float(os.getenv("SHADOW_BOOK_MAX_SPREAD_BPS","120"))))
PORT_MAX_TOTAL_RISK_PCT=max(.1,min(20.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_TOTAL_RISK_PCT","2.0"))))
PORT_MAX_THEME_RISK_PCT=max(.05,min(10.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_THEME_RISK_PCT","0.8"))))
PORT_MAX_FAMILY_RISK_PCT=max(.05,min(10.0,float(os.getenv("SHADOW_PORTFOLIO_MAX_FAMILY_RISK_PCT","1.2"))))
PORT_MAX_OPEN=max(1,min(50,int(os.getenv("SHADOW_PORTFOLIO_MAX_OPEN","5"))))

SIZING=SizingPolicy(
    account_equity_krw=ACCOUNT_EQUITY,
    risk_per_trade_pct=RISK_PCT,
    max_position_pct=MAX_POSITION_PCT,
)
PROXY_FILL=FillPolicy(
    max_participation_pct=MAX_PARTICIPATION_PCT,
    commission_bps=COMMISSION_BPS,
    sell_tax_bps=SELL_TAX_BPS,
)
BOOK_FILL=BookPolicy(
    displayed_liquidity_haircut=BOOK_HAIRCUT,
    max_levels=10,
    max_spread_bps=BOOK_MAX_SPREAD_BPS,
    commission_bps=COMMISSION_BPS,
    sell_tax_bps=SELL_TAX_BPS,
)
PORTFOLIO=PortfolioRiskPolicy(
    account_equity_krw=ACCOUNT_EQUITY,
    max_total_risk_pct=PORT_MAX_TOTAL_RISK_PCT,
    max_theme_risk_pct=PORT_MAX_THEME_RISK_PCT,
    max_family_risk_pct=PORT_MAX_FAMILY_RISK_PCT,
    max_open_positions=PORT_MAX_OPEN,
)

SCHEMA="""
CREATE TABLE IF NOT EXISTS ai_shadow_trades(
  id BIGSERIAL PRIMARY KEY,
  paper_trade_id BIGINT UNIQUE NOT NULL REFERENCES radar_paper_trades(id) ON DELETE CASCADE,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  market_theme TEXT,
  strategy_id TEXT,
  strategy_name TEXT,
  strategy_family TEXT,
  regime_label TEXT,
  status TEXT NOT NULL,
  requested_shares INTEGER NOT NULL DEFAULT 0,
  filled_shares INTEGER NOT NULL DEFAULT 0,
  requested_notional_krw NUMERIC,
  stop_pct DOUBLE PRECISION,
  risk_at_entry_krw NUMERIC,
  entry_at TIMESTAMPTZ,
  entry_ref_price_krw NUMERIC,
  entry_arrival_mid_krw NUMERIC,
  entry_fill_price_krw NUMERIC,
  entry_slippage_bps DOUBLE PRECISION,
  entry_implementation_shortfall_bps DOUBLE PRECISION,
  entry_fill_ratio DOUBLE PRECISION,
  entry_model_quality TEXT,
  entry_model_mode TEXT,
  exit_at TIMESTAMPTZ,
  exit_ref_price_krw NUMERIC,
  exit_arrival_mid_krw NUMERIC,
  exit_fill_price_krw NUMERIC,
  exit_slippage_bps DOUBLE PRECISION,
  exit_implementation_shortfall_bps DOUBLE PRECISION,
  exit_filled_shares INTEGER NOT NULL DEFAULT 0,
  exit_fill_ratio DOUBLE PRECISION,
  remaining_shares INTEGER NOT NULL DEFAULT 0,
  round_trip_is_bps DOUBLE PRECISION,
  paper_return_pct DOUBLE PRECISION,
  gross_return_pct DOUBLE PRECISION,
  net_return_pct DOUBLE PRECISION,
  return_drag_pct DOUBLE PRECISION,
  gross_pnl_krw NUMERIC,
  net_pnl_krw NUMERIC,
  costs_krw NUMERIC,
  sizing JSONB NOT NULL DEFAULT '{}'::jsonb,
  risk_gate JSONB NOT NULL DEFAULT '{}'::jsonb,
  entry_model JSONB NOT NULL DEFAULT '{}'::jsonb,
  exit_model JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS market_theme TEXT;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS risk_at_entry_krw NUMERIC;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS entry_arrival_mid_krw NUMERIC;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS entry_implementation_shortfall_bps DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS entry_model_mode TEXT;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS exit_arrival_mid_krw NUMERIC;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS exit_implementation_shortfall_bps DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS round_trip_is_bps DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS paper_return_pct DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS return_drag_pct DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS risk_gate JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS exit_filled_shares INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS exit_fill_ratio DOUBLE PRECISION;
ALTER TABLE ai_shadow_trades ADD COLUMN IF NOT EXISTS remaining_shares INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_shadow_status_time ON ai_shadow_trades(status,entry_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_strategy_time ON ai_shadow_trades(strategy_id,entry_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_theme_time ON ai_shadow_trades(market_theme,entry_at DESC);

CREATE TABLE IF NOT EXISTS ai_shadow_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  open_count INTEGER NOT NULL DEFAULT 0,
  closed_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
ALTER TABLE ai_shadow_status ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NOT NULL DEFAULT now();
"""

def db():
    return psycopg.connect(
        DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=15000 -c lock_timeout=3000'
    )

def schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419070,))
        cur.execute(SCHEMA)
        cur.execute("""INSERT INTO ai_shadow_status(
                       id,started_at,updated_at,status,open_count,closed_count,rejected_count,note)
                       VALUES(1,now(),now(),'STARTING',0,0,0,%s)
                       ON CONFLICT(id) DO NOTHING""",
                    ("shadow start boundary; no historical backfill",))

def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s)",("public."+name,))
    r=cur.fetchone()
    return bool(r and r["to_regclass"] is not None)

def column_exists(cur,table,column):
    cur.execute("""SELECT EXISTS(
                   SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s AND column_name=%s) AS ok""",
                (table,column))
    r=cur.fetchone()
    return bool(r and r["ok"])

def finite(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None

def _aware(dt):
    if not dt:return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def quote_pair(cur,code,at):
    if not table_exists(cur,"radar_flow_quotes"):
        return None,None,None
    cur.execute("""SELECT batch_time,payload FROM radar_flow_quotes
                   WHERE stock_code=%s
                     AND batch_time<=%s+interval '60 seconds'
                     AND batch_time>=%s-interval '180 seconds'
                   ORDER BY batch_time ASC LIMIT 12""",(code,at,at))
    rows=cur.fetchall()
    if not rows:return None,None,None
    idx=next((i for i,r in enumerate(rows) if r["batch_time"]>=at),len(rows)-1)
    current_row=rows[idx]
    current=current_row["payload"] or {}
    previous=(rows[idx-1]["payload"] or {}) if idx>0 else None
    recent=None
    if previous:
        value,state,_=flow_delta(current,previous)
        if state=="OK":recent=value
    price=finite(current.get("price_krw"))
    exchange=current.get("exchange_at")
    try:
        exchange=datetime.fromisoformat(exchange) if exchange else current_row["batch_time"]
    except ValueError:
        exchange=current_row["batch_time"]
    exchange=_aware(exchange)
    event_at=_aware(at)
    if exchange and event_at and abs((exchange-event_at).total_seconds())>120:
        return None,recent,exchange
    return price,recent,exchange

def latest_book(cur,code,at):
    if not table_exists(cur,"market_orderbook_snapshots"):
        return None
    cur.execute("""SELECT snapshot_time,venue,best_ask_krw,best_bid_krw,spread_bps,
                          total_ask_qty,total_bid_qty,asks,bids,quality_flags
                   FROM market_orderbook_snapshots
                   WHERE stock_code=%s
                     AND snapshot_time>=%s-interval '10 seconds'
                     AND snapshot_time<=%s+(%s || ' seconds')::interval
                   ORDER BY ABS(EXTRACT(EPOCH FROM(snapshot_time-%s))) ASC
                   LIMIT 1""",(code,at,at,BOOK_MAX_AGE_SEC,at))
    r=cur.fetchone()
    if not r:return None
    snap=_aware(r["snapshot_time"]); event_at=_aware(at)
    age=abs((snap-event_at).total_seconds()) if snap and event_at else 9999
    if age>BOOK_MAX_AGE_SEC:return None
    flags=list(r["quality_flags"] or [])
    if "CROSSED_BOOK" in flags:return None
    return {
        "snapshot_time":snap.isoformat() if snap else None,
        "age_sec":age,
        "venue":r["venue"],
        "best_ask_krw":finite(r["best_ask_krw"]),
        "best_bid_krw":finite(r["best_bid_krw"]),
        "spread_bps":finite(r["spread_bps"]),
        "total_ask_qty":int(r["total_ask_qty"] or 0),
        "total_bid_qty":int(r["total_bid_qty"] or 0),
        "asks":list(r["asks"] or []),
        "bids":list(r["bids"] or []),
        "quality_flags":flags,
    }

def volatility_bps(cur,code,at):
    if not table_exists(cur,"market_minute_bars"):
        return None
    cur.execute("""SELECT close_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3 AND bar_time<=%s
                   ORDER BY bar_time DESC LIMIT 21""",(code,at))
    raw=[finite(r["close_price"]) for r in reversed(cur.fetchall())]
    xs=[x for x in raw if x and x>0]
    if len(xs)<6:return None
    rets=[abs(b/a-1.0)*10_000.0 for a,b in zip(xs[:-1],xs[1:]) if a>0]
    return statistics.median(rets) if rets else None

def simulation_cutoff(cur,now=None):
    now=now or datetime.now(timezone.utc)
    cur.execute("SELECT started_at FROM ai_shadow_status WHERE id=1")
    r=cur.fetchone()
    started=(r["started_at"] if r and r["started_at"] else now)
    replay=now-timedelta(minutes=MAX_REPLAY_MINUTES)
    return max(started,replay)

def open_portfolio(cur):
    cur.execute("""SELECT market_theme,strategy_family,risk_at_entry_krw
                   FROM ai_shadow_trades WHERE status='OPEN'""")
    return [{
        "market_theme":r["market_theme"],
        "strategy_family":r["strategy_family"],
        "risk_krw":finite(r["risk_at_entry_krw"]) or 0.0,
    } for r in cur.fetchall()]

def execution_fill(cur,side,code,at,shares):
    book=latest_book(cur,code,at)
    if book:
        fill=estimate_book_fill(side,shares,book,BOOK_FILL)
        fill["book_snapshot_time"]=book.get("snapshot_time")
        fill["book_age_sec"]=book.get("age_sec")
        return fill,"BOOK_V2",book
    if not ALLOW_PROXY_FALLBACK:
        return {
            "status":"NO_FRESH_BOOK","filled_shares":0,"fill_ratio":0.0,
            "fill_price_krw":None,"model_quality":"NO_FRESH_BOOK"
        },"NO_FILL",None
    ref,recent,exchange=quote_pair(cur,code,at)
    vol=volatility_bps(cur,code,at)
    fill=estimate_fill(side,ref or 0,shares,recent,vol,PROXY_FILL)
    fill["proxy_exchange_at"]=exchange.isoformat() if exchange else None
    return fill,"PROXY_V1",{"reference_price_krw":ref,"exchange_at":exchange}

def _arrival_ref(fill,context):
    mid=finite(fill.get("arrival_mid_krw"))
    if mid is not None:return mid
    return finite((context or {}).get("reference_price_krw"))

def open_new(cur):
    if not table_exists(cur,"radar_paper_trades") or not column_exists(cur,"radar_paper_trades","strategy_id"):
        return 0
    cutoff=simulation_cutoff(cur)
    cur.execute("""SELECT p.id,p.stock_code,p.stock_name,p.opened_at,p.entry_price_krw,
                          p.strategy_id,p.strategy_name,p.strategy_family,p.regime_label,p.market_theme
                   FROM radar_paper_trades p
                   LEFT JOIN ai_shadow_trades s ON s.paper_trade_id=p.id
                   WHERE s.id IS NULL
                     AND p.strategy_id IS NOT NULL
                     AND p.opened_at>=%s
                   ORDER BY p.opened_at LIMIT 50""",(cutoff,))
    opened=0
    for p in cur.fetchall():
        vol=volatility_bps(cur,p["stock_code"],p["opened_at"])
        book=latest_book(cur,p["stock_code"],p["opened_at"])
        if book:
            sizing_ref=(finite(book.get("best_ask_krw")) or finite(book.get("best_bid_krw")))
        else:
            sizing_ref,_,_=quote_pair(cur,p["stock_code"],p["opened_at"])
        sizing=SIZING.size(sizing_ref,vol) if sizing_ref else {
            "shares":0,"requested_notional_krw":0,"stop_pct":None,"risk_budget_krw":0
        }
        proposed_risk=(float(sizing.get("requested_notional_krw") or 0)
                       *float(sizing.get("stop_pct") or 0)/100.0)
        requested=int(sizing.get("shares") or 0)
        if not sizing_ref:
            risk_gate={
                "allowed":False,"proposed_risk_krw":0.0,"allowed_risk_krw":0.0,
                "risk_scale":0.0,"blockers":["NO_MARKET_REFERENCE"]
            }
            fill={
                "status":"NO_MARKET_REFERENCE","requested_shares":0,
                "filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                "model_quality":"NO_MARKET_REFERENCE","risk_gate":risk_gate,
            }
            mode="NO_FILL"
            context=None
        else:
            risk_gate=portfolio_risk_budget(
                proposed_risk,p["market_theme"],p["strategy_family"],open_portfolio(cur),PORTFOLIO
            )
            if requested>0 and risk_gate.get("risk_scale",0)<1:
                requested=max(0,int(math.floor(requested*float(risk_gate.get("risk_scale") or 0))))
            if not risk_gate.get("allowed") or requested<=0:
                fill={
                    "status":"PORTFOLIO_RISK_REJECT","requested_shares":requested,
                    "filled_shares":0,"fill_ratio":0.0,"fill_price_krw":None,
                    "model_quality":"PORTFOLIO_RISK_GATE","risk_gate":risk_gate,
                }
                mode="RISK_GATE"
                context=None
            else:
                fill,mode,context=execution_fill(cur,"BUY",p["stock_code"],p["opened_at"],requested)
        filled=int(fill.get("filled_shares") or 0)
        entry_price=finite(fill.get("fill_price_krw"))
        stop_pct=finite(sizing.get("stop_pct"))
        risk_at_entry=(entry_price*filled*(stop_pct or 0)/100.0) if entry_price and filled else 0.0
        status="OPEN" if filled>0 else "REJECTED"
        arrival=_arrival_ref(fill,context)
        slippage=(finite(fill.get("implementation_shortfall_bps"))
                  if mode=="BOOK_V2" else finite(fill.get("slippage_bps")))
        cur.execute("""INSERT INTO ai_shadow_trades(
                       paper_trade_id,stock_code,stock_name,market_theme,strategy_id,strategy_name,
                       strategy_family,regime_label,status,requested_shares,filled_shares,
                       requested_notional_krw,stop_pct,risk_at_entry_krw,
                       entry_at,entry_ref_price_krw,entry_arrival_mid_krw,entry_fill_price_krw,
                       entry_slippage_bps,entry_implementation_shortfall_bps,
                       entry_fill_ratio,entry_model_quality,entry_model_mode,
                       sizing,risk_gate,entry_model)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                              %s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)""",
                    (p["id"],p["stock_code"],p["stock_name"],p["market_theme"],p["strategy_id"],
                     p["strategy_name"],p["strategy_family"],p["regime_label"],status,requested,filled,
                     float(sizing_ref*requested) if sizing_ref and requested else 0.0,stop_pct,risk_at_entry,
                     p["opened_at"],arrival,finite(fill.get("arrival_mid_krw")),entry_price,slippage,
                     finite(fill.get("implementation_shortfall_bps")),finite(fill.get("fill_ratio")),
                     fill.get("model_quality"),mode,json.dumps(sizing,ensure_ascii=False),
                     json.dumps(risk_gate,ensure_ascii=False),json.dumps(fill,ensure_ascii=False)))
        opened+=1
    return opened

def close_ready(cur):
    if not table_exists(cur,"radar_paper_trades"):
        return 0
    cur.execute("""SELECT s.*,p.status AS paper_status,p.closed_at,p.exit_price_krw,
                          p.return_pct AS paper_return
                   FROM ai_shadow_trades s
                   JOIN radar_paper_trades p ON p.id=s.paper_trade_id
                   WHERE s.status='OPEN' AND p.status IN('CLOSED','CLOSED_NO_PRICE')
                   ORDER BY p.closed_at LIMIT 50""")
    closed=0
    for s in cur.fetchall():
        if not s["closed_at"]:continue
        exit_fill,mode,context=execution_fill(
            cur,"SELL",s["stock_code"],s["closed_at"],int(s["filled_shares"] or 0)
        )
        entry_model=s["entry_model"] or {}
        result=round_trip_result(entry_model,exit_fill)
        entry_shares=int(s["filled_shares"] or 0)
        exit_shares=int(exit_fill.get("filled_shares") or 0)
        remaining=max(0,entry_shares-exit_shares)
        if result.get("status")!="COMPLETE":
            status="CLOSED_NO_FILL"
        elif remaining>0:
            status="CLOSED_PARTIAL_LIQUIDITY"
        else:
            status="CLOSED"
        arrival=_arrival_ref(exit_fill,context)
        slippage=(finite(exit_fill.get("implementation_shortfall_bps"))
                  if mode=="BOOK_V2" else finite(exit_fill.get("slippage_bps")))
        tca=implementation_shortfall_summary(entry_model,exit_fill)
        paper_ret=finite(s["paper_return"])
        net_ret=finite(result.get("net_return_pct"))
        drag=(paper_ret-net_ret) if paper_ret is not None and net_ret is not None else None
        cur.execute("""UPDATE ai_shadow_trades
                       SET status=%s,exit_at=%s,exit_ref_price_krw=%s,exit_arrival_mid_krw=%s,
                           exit_fill_price_krw=%s,exit_slippage_bps=%s,
                           exit_implementation_shortfall_bps=%s,exit_filled_shares=%s,
                           exit_fill_ratio=%s,remaining_shares=%s,round_trip_is_bps=%s,
                           paper_return_pct=%s,gross_return_pct=%s,net_return_pct=%s,
                           return_drag_pct=%s,gross_pnl_krw=%s,net_pnl_krw=%s,costs_krw=%s,
                           exit_model=%s::jsonb,updated_at=now()
                       WHERE id=%s""",
                    (status,s["closed_at"],arrival,finite(exit_fill.get("arrival_mid_krw")),
                     finite(exit_fill.get("fill_price_krw")),slippage,
                     finite(exit_fill.get("implementation_shortfall_bps")),exit_shares,
                     finite(exit_fill.get("fill_ratio")),remaining,finite(tca.get("round_trip_is_bps")),
                     paper_ret,finite(result.get("gross_return_pct")),net_ret,drag,
                     result.get("gross_pnl_krw"),result.get("net_pnl_krw"),result.get("costs_krw"),
                     json.dumps(exit_fill,ensure_ascii=False),s["id"]))
        closed+=1
    return closed

def update_status(cur):
    cur.execute("""SELECT COUNT(*) FILTER(WHERE status='OPEN') AS open_n,
                          COUNT(*) FILTER(WHERE status='CLOSED') AS closed_n,
                          COUNT(*) FILTER(WHERE status='REJECTED') AS rejected_n
                   FROM ai_shadow_trades""")
    r=cur.fetchone()
    cur.execute("""INSERT INTO ai_shadow_status(
                   id,started_at,updated_at,status,open_count,closed_count,rejected_count,note)
                   VALUES(1,now(),now(),'OK',%s,%s,%s,%s)
                   ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',
                     open_count=excluded.open_count,closed_count=excluded.closed_count,
                     rejected_count=excluded.rejected_count,note=excluded.note""",
                (int(r["open_n"] or 0),int(r["closed_n"] or 0),int(r["rejected_n"] or 0),
                 f"book-aware shadow; no orders; equity={ACCOUNT_EQUITY:.0f}; "
                 f"risk={RISK_PCT:.2f}%; totalRisk<={PORT_MAX_TOTAL_RISK_PCT:.2f}%; "
                 f"themeRisk<={PORT_MAX_THEME_RISK_PCT:.2f}%; familyRisk<={PORT_MAX_FAMILY_RISK_PCT:.2f}%; "
                 f"bookHaircut={BOOK_HAIRCUT:.2f}; fallback={ALLOW_PROXY_FALLBACK}"))

def cycle():
    with db() as c,c.cursor() as cur:
        open_new(cur)
        close_ready(cur)
        update_status(cur)

def main():
    if not DB:raise RuntimeError("DATABASE_URL missing")
    while True:
        try:
            schema()
            break
        except Exception as exc:
            print("Shadow schema waiting:",type(exc).__name__,flush=True)
            time.sleep(5)
    print("Book-aware shadow execution simulator started; no broker orders",flush=True)
    while True:
        started=time.monotonic()
        try:cycle()
        except Exception as exc:
            print("Shadow simulator error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))

if __name__=="__main__":
    main()
