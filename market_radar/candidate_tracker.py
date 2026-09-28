"""Persist observation candidates and prospectively measure their price paths.

No orders are placed and no OpenAI call is made here. A candidate episode starts
when a stock enters the local top-watch list and ends when it leaves that list.
The recorded +5m/+15m/+30m returns, MFE and MAE use observed SOR reference
prices; they are not fills, realized P&L, recommendations or backtest trades.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import math
import os
import time

from flow_core import dt
from flow_store import db, desk_payload

POLL = max(15, int(os.getenv("CANDIDATE_TRACK_POLL_SECONDS", "30")))
HORIZONS = ((5, "h5", "return_5m_pct", "mfe_5m_pct", "mae_5m_pct"),
            (15, "h15", "return_15m_pct", "mfe_15m_pct", "mae_15m_pct"),
            (30, "h30", "return_30m_pct", "mfe_30m_pct", "mae_30m_pct"))
MAX_HORIZON_DELAY_SECONDS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS radar_candidate_history(
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  attention_score INTEGER NOT NULL,
  candidate_version TEXT,
  label TEXT,
  primary_type TEXT,
  watch_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  market_theme TEXT,
  price_krw NUMERIC,
  change_pct DOUBLE PRECISION,
  interval_turnover_krw NUMERIC,
  five_min_turnover_krw NUMERIC,
  burst_multiple DOUBLE PRECISION,
  event_type TEXT,
  chart_state TEXT,
  query_rank INTEGER,
  trade_rank INTEGER,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY(snapshot_time,stock_code)
);
ALTER TABLE radar_candidate_history ADD COLUMN IF NOT EXISTS candidate_version TEXT;
CREATE INDEX IF NOT EXISTS idx_candidate_history_code_time
  ON radar_candidate_history(stock_code,snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_history_time
  ON radar_candidate_history(snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_history_theme_time
  ON radar_candidate_history(market_theme,snapshot_time DESC);

CREATE TABLE IF NOT EXISTS radar_candidate_episodes(
  id BIGSERIAL PRIMARY KEY,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  candidate_version TEXT,
  entry_score INTEGER NOT NULL,
  last_score INTEGER NOT NULL,
  peak_score INTEGER NOT NULL,
  entry_price_krw NUMERIC,
  entry_change_pct DOUBLE PRECISION,
  primary_type TEXT,
  watch_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  market_theme TEXT,
  event_type TEXT,
  chart_state TEXT,
  query_rank INTEGER,
  trade_rank INTEGER,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  UNIQUE(stock_code,started_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_episode_active
  ON radar_candidate_episodes(stock_code) WHERE status='ACTIVE';
CREATE INDEX IF NOT EXISTS idx_candidate_episode_start
  ON radar_candidate_episodes(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_episode_type
  ON radar_candidate_episodes(candidate_version,primary_type,started_at DESC);

CREATE TABLE IF NOT EXISTS radar_candidate_outcomes(
  episode_id BIGINT PRIMARY KEY REFERENCES radar_candidate_episodes(id) ON DELETE CASCADE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  h5_state TEXT NOT NULL DEFAULT 'WAITING',
  h5_at TIMESTAMPTZ,
  h5_price_krw NUMERIC,
  return_5m_pct DOUBLE PRECISION,
  mfe_5m_pct DOUBLE PRECISION,
  mae_5m_pct DOUBLE PRECISION,
  h15_state TEXT NOT NULL DEFAULT 'WAITING',
  h15_at TIMESTAMPTZ,
  h15_price_krw NUMERIC,
  return_15m_pct DOUBLE PRECISION,
  mfe_15m_pct DOUBLE PRECISION,
  mae_15m_pct DOUBLE PRECISION,
  h30_state TEXT NOT NULL DEFAULT 'WAITING',
  h30_at TIMESTAMPTZ,
  h30_price_krw NUMERIC,
  return_30m_pct DOUBLE PRECISION,
  mfe_30m_pct DOUBLE PRECISION,
  mae_30m_pct DOUBLE PRECISION,
  exit_at TIMESTAMPTZ,
  exit_price_krw NUMERIC,
  exit_return_pct DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS radar_candidate_tracker_status(
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  last_sample_time TIMESTAMPTZ,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  rows_written INTEGER NOT NULL DEFAULT 0,
  active_episodes INTEGER NOT NULL DEFAULT 0,
  completed_30m INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
ALTER TABLE radar_candidate_tracker_status ADD COLUMN IF NOT EXISTS active_episodes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE radar_candidate_tracker_status ADD COLUMN IF NOT EXISTS completed_30m INTEGER NOT NULL DEFAULT 0;
"""


def schema():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (72419066,))
        cur.execute(SCHEMA)


def safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_float(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def pct(value, reference):
    value=safe_float(value); reference=safe_float(reference)
    if value is None or reference is None or reference <= 0:
        return None
    return (value/reference-1.0)*100.0


def set_status(status, sample_time=None, candidate_count=0, rows_written=0,
               active_episodes=0, completed_30m=0, note=None):
    with db() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO radar_candidate_tracker_status(
                 id,updated_at,status,last_sample_time,candidate_count,rows_written,
                 active_episodes,completed_30m,note)
               VALUES(1,now(),%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET
                 updated_at=now(),status=excluded.status,
                 last_sample_time=COALESCE(excluded.last_sample_time,radar_candidate_tracker_status.last_sample_time),
                 candidate_count=excluded.candidate_count,
                 rows_written=excluded.rows_written,
                 active_episodes=excluded.active_episodes,
                 completed_30m=excluded.completed_30m,
                 note=excluded.note""",
            (status, sample_time, candidate_count, rows_written,
             active_episodes, completed_30m, note),
        )


def valid_price(value):
    x=safe_float(value)
    return x if x is not None and x > 0 else None


def quote_at_or_after(cur, code, target):
    cur.execute(
        """SELECT batch_time,NULLIF(payload->>'price_krw','')::double precision AS price
           FROM radar_flow_quotes
           WHERE stock_code=%s
             AND batch_time >= %s
             AND batch_time <= %s
             AND payload->>'price_krw' IS NOT NULL
             AND NULLIF(payload->>'price_krw','')::double precision > 0
           ORDER BY batch_time
           LIMIT 1""",
        (code, target, target+timedelta(seconds=MAX_HORIZON_DELAY_SECONDS)),
    )
    return cur.fetchone()


def path_metrics(cur, code, started_at, end_at, entry_price):
    cur.execute(
        """SELECT batch_time,NULLIF(payload->>'price_krw','')::double precision AS price
           FROM radar_flow_quotes
           WHERE stock_code=%s
             AND batch_time >= %s
             AND batch_time <= %s
             AND payload->>'price_krw' IS NOT NULL
             AND NULLIF(payload->>'price_krw','')::double precision > 0
           ORDER BY batch_time""",
        (code, started_at, end_at),
    )
    prices=[safe_float(r["price"]) for r in cur.fetchall()]
    prices=[x for x in prices if x is not None and x > 0]
    entry=valid_price(entry_price)
    if not prices or entry is None:
        return None,None
    excursions=[pct(x,entry) for x in prices]
    excursions=[x for x in excursions if x is not None]
    return (max(excursions),min(excursions)) if excursions else (None,None)


def active_episode_map(cur):
    cur.execute("""SELECT id,stock_code,started_at,last_seen_at,entry_price_krw
                   FROM radar_candidate_episodes WHERE status='ACTIVE'""")
    return {r["stock_code"]:r for r in cur.fetchall()}


def sync_episodes(cur, sample_time, candidates, source_rows):
    """Open/refresh/close prospective candidate episodes."""
    current={str(x.get("code")):x for x in candidates if len(str(x.get("code") or ""))==6}
    source={str(r.get("code")):r for r in source_rows if len(str(r.get("code") or ""))==6}
    active=active_episode_map(cur)

    # Close an episode when it is absent from the current top-watch list.
    for code,episode in active.items():
        if code in current:
            continue
        cur.execute(
            """SELECT snapshot_time,price_krw FROM radar_candidate_history
               WHERE stock_code=%s AND snapshot_time<=%s
               ORDER BY snapshot_time DESC LIMIT 1""",
            (code,sample_time),
        )
        last=cur.fetchone()
        ended=(last["snapshot_time"] if last else episode["last_seen_at"]) or sample_time
        exit_price=valid_price(last["price_krw"] if last else None)
        cur.execute("""UPDATE radar_candidate_episodes
                       SET status='CLOSED',ended_at=%s,last_seen_at=LEAST(last_seen_at,%s)
                       WHERE id=%s""",(ended,ended,episode["id"]))
        if exit_price is not None:
            cur.execute(
                """UPDATE radar_candidate_outcomes
                   SET exit_at=%s,exit_price_krw=%s,exit_return_pct=%s,updated_at=now()
                   WHERE episode_id=%s""",
                (ended,exit_price,pct(exit_price,episode["entry_price_krw"]),episode["id"]),
            )

    # Refresh active episodes or open a new episode.
    for code,x in current.items():
        score=safe_int(x.get("attention_score"))
        if score is None:
            continue
        existing=active.get(code)
        if existing:
            cur.execute(
                """UPDATE radar_candidate_episodes
                   SET last_seen_at=%s,last_score=%s,peak_score=GREATEST(peak_score,%s)
                   WHERE id=%s""",
                (sample_time,score,score,existing["id"]),
            )
            continue

        src=source.get(code,{})
        entry_price=valid_price(src.get("price_krw"))
        cur.execute(
            """INSERT INTO radar_candidate_episodes(
                 stock_code,stock_name,started_at,last_seen_at,status,candidate_version,
                 entry_score,last_score,peak_score,entry_price_krw,entry_change_pct,
                 primary_type,watch_types,market_theme,event_type,chart_state,
                 query_rank,trade_rank,reasons,risk_flags)
               VALUES(%s,%s,%s,%s,'ACTIVE',%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
               ON CONFLICT(stock_code,started_at) DO NOTHING
               RETURNING id""",
            (code,str(x.get("name") or code)[:80],sample_time,sample_time,
             str(x.get("candidate_version") or "unknown")[:80],
             score,score,score,entry_price,safe_float(x.get("change_pct")),
             str(x.get("primary_type") or "")[:80],
             json.dumps(x.get("watch_types") or [],ensure_ascii=False),
             str(x.get("market_theme") or "")[:160] or None,
             str(x.get("event_type") or "")[:80] or None,
             str(x.get("chart_state") or "")[:120] or None,
             safe_int(x.get("query_rank")),safe_int(x.get("trade_rank")),
             json.dumps(x.get("reasons") or [],ensure_ascii=False),
             json.dumps(x.get("risk_flags") or [],ensure_ascii=False)),
        )
        row=cur.fetchone()
        if row:
            cur.execute("""INSERT INTO radar_candidate_outcomes(episode_id)
                           VALUES(%s) ON CONFLICT DO NOTHING""",(row["id"],))


def update_horizon_outcomes(cur, sample_time):
    """Lock the first available observed quote after each horizon target."""
    cur.execute(
        """SELECT e.id,e.stock_code,e.started_at,e.entry_price_krw,
                  o.h5_state,o.h15_state,o.h30_state
           FROM radar_candidate_episodes e
           JOIN radar_candidate_outcomes o ON o.episode_id=e.id
           WHERE e.started_at >= %s""",
        (sample_time-timedelta(minutes=45),),
    )
    episodes=cur.fetchall()
    for e in episodes:
        entry=valid_price(e["entry_price_krw"])
        if entry is None:
            continue
        for minutes,prefix,ret_col,mfe_col,mae_col in HORIZONS:
            state=e[prefix+"_state"]
            if state != "WAITING":
                continue
            target=e["started_at"]+timedelta(minutes=minutes)
            if sample_time < target:
                continue
            q=quote_at_or_after(cur,e["stock_code"],target)
            if q:
                mfe,mae=path_metrics(cur,e["stock_code"],e["started_at"],q["batch_time"],entry)
                cur.execute(
                    f"""UPDATE radar_candidate_outcomes
                        SET {prefix}_state='READY',{prefix}_at=%s,{prefix}_price_krw=%s,
                            {ret_col}=%s,{mfe_col}=%s,{mae_col}=%s,updated_at=now()
                        WHERE episode_id=%s""",
                    (q["batch_time"],q["price"],pct(q["price"],entry),mfe,mae,e["id"]),
                )
            elif sample_time >= target+timedelta(seconds=MAX_HORIZON_DELAY_SECONDS):
                cur.execute(
                    f"""UPDATE radar_candidate_outcomes
                        SET {prefix}_state='NO_SAMPLE',updated_at=now()
                        WHERE episode_id=%s""",
                    (e["id"],),
                )


def tracker_counts(cur):
    cur.execute("SELECT COUNT(*) AS n FROM radar_candidate_episodes WHERE status='ACTIVE'")
    active=int(cur.fetchone()["n"] or 0)
    cur.execute("SELECT COUNT(*) AS n FROM radar_candidate_outcomes WHERE h30_state='READY'")
    done=int(cur.fetchone()["n"] or 0)
    return active,done


def snapshot():
    payload=desk_payload(include_tracking=False)
    sample_time=dt(payload.get("sample_time"))
    if not sample_time:
        set_status("WAITING_FOR_SAMPLE",note="flow sample not ready")
        return "WAITING_FOR_SAMPLE"

    candidates=payload.get("watch_candidates") or []
    if payload.get("status")!="RECENT_TRADES":
        set_status("NO_RECENT_TRADE",sample_time,len(candidates),0,
                   note="market sample exists but recent exchange trade is not confirmed")
        return "NO_RECENT_TRADE"

    source_rows=payload.get("rows") or []
    source_by_code={r.get("code"):r for r in source_rows}
    rows=[]
    for x in candidates:
        code=str(x.get("code") or "")
        score=safe_int(x.get("attention_score"))
        if len(code)!=6 or score is None:
            continue
        source=source_by_code.get(code,{})
        rows.append((
            sample_time,code,str(x.get("name") or code)[:80],score,
            str(x.get("candidate_version") or "unknown")[:80],
            str(x.get("label") or "")[:40],str(x.get("primary_type") or "")[:80],
            json.dumps(x.get("watch_types") or [],ensure_ascii=False),
            str(x.get("market_theme") or "")[:160] or None,
            source.get("price_krw"),safe_float(x.get("change_pct")),
            x.get("interval_turnover_krw"),x.get("five_min_turnover_krw"),
            safe_float(x.get("burst_multiple")),str(x.get("event_type") or "")[:80] or None,
            str(x.get("chart_state") or "")[:120] or None,
            safe_int(x.get("query_rank")),safe_int(x.get("trade_rank")),
            json.dumps(x.get("reasons") or [],ensure_ascii=False),
            json.dumps(x.get("risk_flags") or [],ensure_ascii=False),
        ))

    with db() as c,c.cursor() as cur:
        if rows:
            cur.executemany(
                """INSERT INTO radar_candidate_history(
                     snapshot_time,stock_code,stock_name,attention_score,candidate_version,
                     label,primary_type,watch_types,market_theme,price_krw,change_pct,
                     interval_turnover_krw,five_min_turnover_krw,burst_multiple,event_type,
                     chart_state,query_rank,trade_rank,reasons,risk_flags)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                   ON CONFLICT(snapshot_time,stock_code) DO NOTHING""",
                rows,
            )
        written=max(0,cur.rowcount) if rows else 0
        sync_episodes(cur,sample_time,candidates,source_rows)
        update_horizon_outcomes(cur,sample_time)
        cur.execute("DELETE FROM radar_candidate_history WHERE snapshot_time < now()-interval '14 days'")
        cur.execute("""DELETE FROM radar_candidate_episodes
                       WHERE started_at < now()-interval '60 days'""")
        active,done=tracker_counts(cur)
        cur.execute(
            """INSERT INTO radar_candidate_tracker_status(
                 id,updated_at,status,last_sample_time,candidate_count,rows_written,
                 active_episodes,completed_30m,note)
               VALUES(1,now(),'OK',%s,%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET updated_at=now(),status='OK',
                 last_sample_time=excluded.last_sample_time,
                 candidate_count=excluded.candidate_count,
                 rows_written=excluded.rows_written,
                 active_episodes=excluded.active_episodes,
                 completed_30m=excluded.completed_30m,
                 note=excluded.note""",
            (sample_time,len(candidates),written,active,done,
             "prospective local observation journal; no orders, fills or model calls"),
        )
    return "OK"


def main():
    schema()
    print(f"Candidate tracker started: target={POLL}s; survival + prospective 5/15/30m journal",flush=True)
    while True:
        started=time.monotonic()
        try:
            result=snapshot()
            if result not in ("OK","WAITING_FOR_SAMPLE","NO_RECENT_TRADE"):
                print("Candidate tracker:",result,flush=True)
        except Exception as exc:
            try:set_status("ERROR",note=type(exc).__name__)
            except Exception:pass
            print("Candidate tracker error:",type(exc).__name__,flush=True)
        time.sleep(max(1,POLL-(time.monotonic()-started)))


if __name__=="__main__":
    main()
