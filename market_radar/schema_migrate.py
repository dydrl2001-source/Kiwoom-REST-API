"""Versioned schema bundle for the AI Brokerage overlay."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os

import psycopg
from psycopg.rows import dict_row

DB=os.getenv("DATABASE_URL","")
SCHEMA_VERSION=os.getenv("MARKET_RADAR_SCHEMA_VERSION","2026.09.29.1")
MODULES=(
    "ai_brokerage_worker",
    "paper_trade_engine",
    "paper_feedback_engine",
    "orderbook_collector",
    "shadow_execution_engine",
    "capital_allocation_worker",
    "risk_control_worker",
    "resilience_audit_worker",
    "soak_monitor_worker",
)

REGISTRY_SCHEMA="""
CREATE TABLE IF NOT EXISTS market_radar_schema_migrations(
  version TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  modules JSONB NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def db():
    if not DB: raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=5000')

def load_bundle():
    rows=[]
    for name in MODULES:
        mod=importlib.import_module(name)
        sql=getattr(mod,"SCHEMA",None)
        if not isinstance(sql,str) or not sql.strip():
            raise RuntimeError(f"{name} has no SCHEMA")
        rows.append((name,sql.strip()))
    material="\n--MODULE--\n".join(name+"\n"+sql for name,sql in rows)
    checksum=hashlib.sha256(material.encode("utf-8")).hexdigest()
    return rows,checksum

def apply():
    rows,checksum=load_bundle()
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)",(72419075,))
        cur.execute(REGISTRY_SCHEMA)
        cur.execute("SELECT checksum FROM market_radar_schema_migrations WHERE version=%s",(SCHEMA_VERSION,))
        existing=cur.fetchone()
        if existing:
            if existing["checksum"]!=checksum:
                raise RuntimeError(f"schema version {SCHEMA_VERSION} checksum drift; bump MARKET_RADAR_SCHEMA_VERSION")
            print(f"schema {SCHEMA_VERSION} already applied {checksum[:12]}")
            return {"version":SCHEMA_VERSION,"checksum":checksum,"applied":False}
        for name,sql in rows:
            cur.execute(sql)
            print(f"applied schema module {name}")
        cur.execute("""INSERT INTO market_radar_schema_migrations(version,checksum,modules)
                       VALUES(%s,%s,%s::jsonb)""",
                    (SCHEMA_VERSION,checksum,json.dumps([name for name,_ in rows])))
    print(f"schema {SCHEMA_VERSION} applied {checksum[:12]}")
    return {"version":SCHEMA_VERSION,"checksum":checksum,"applied":True}

def check():
    _,checksum=load_bundle()
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.market_radar_schema_migrations') AS t")
        r=cur.fetchone()
        if not r or not r["t"]: raise RuntimeError("schema migration registry missing")
        cur.execute("""SELECT checksum,applied_at FROM market_radar_schema_migrations
                       WHERE version=%s""",(SCHEMA_VERSION,))
        r=cur.fetchone()
        if not r: raise RuntimeError(f"schema version {SCHEMA_VERSION} not applied")
        if r["checksum"]!=checksum: raise RuntimeError(f"schema checksum drift for {SCHEMA_VERSION}")
        print(f"schema check PASS {SCHEMA_VERSION} {checksum[:12]} {r['applied_at']}")
        return True

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=("apply","check"))
    args=p.parse_args()
    apply() if args.command=="apply" else check()

if __name__=="__main__":
    main()
