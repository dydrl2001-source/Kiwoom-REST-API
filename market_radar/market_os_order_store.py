"""Private PostgreSQL execution journal. No credentials or raw account payloads."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from market_os_order_plan import OrderPlan, OrderError, advance, digest

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_os_order_plans (
 plan_id TEXT PRIMARY KEY, scope_key TEXT UNIQUE NOT NULL,
 intent_id TEXT NOT NULL, account_ref TEXT NOT NULL, mode TEXT NOT NULL,
 operation TEXT NOT NULL, stock_code TEXT NOT NULL, parent_plan_id TEXT
 REFERENCES market_os_order_plans(plan_id), plan JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market_os_order_attempts (
 plan_id TEXT PRIMARY KEY REFERENCES market_os_order_plans(plan_id),
 command_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL CHECK(status IN
 ('SUBMITTING','UNKNOWN','ACCEPTED','PARTIALLY_FILLED','FILLED','CANCELLED','AMENDED','REJECTED','DRY_RUN')),
 quantity BIGINT NOT NULL CHECK(quantity>0), filled_quantity BIGINT NOT NULL DEFAULT 0,
 remaining_quantity BIGINT NOT NULL CHECK(remaining_quantity>=0),
 broker_order_number TEXT, broker_order_key TEXT UNIQUE, submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(filled_quantity>=0 AND filled_quantity+remaining_quantity<=quantity)
);
CREATE TABLE IF NOT EXISTS market_os_order_events (
 event_id BIGSERIAL PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES market_os_order_plans(plan_id),
 event_key TEXT NOT NULL, event_type TEXT NOT NULL, status TEXT NOT NULL,
 evidence JSONB NOT NULL, event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(plan_id,event_key)
);
CREATE OR REPLACE FUNCTION market_os_order_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_EXECUTION_RECORD'; END $$;
DROP TRIGGER IF EXISTS market_os_order_plan_immutable ON market_os_order_plans;
CREATE TRIGGER market_os_order_plan_immutable BEFORE UPDATE OR DELETE ON market_os_order_plans
 FOR EACH ROW EXECUTE FUNCTION market_os_order_immutable();
DROP TRIGGER IF EXISTS market_os_order_event_immutable ON market_os_order_events;
CREATE TRIGGER market_os_order_event_immutable BEFORE UPDATE OR DELETE ON market_os_order_events
 FOR EACH ROW EXECUTE FUNCTION market_os_order_immutable();
"""


class Store:
    def __init__(self, database_url):
        self.url = database_url

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5,
                               options='-c lock_timeout=3000 -c statement_timeout=20000')

    def ensure_schema(self):
        with self.connect() as c:
            c.execute('SELECT pg_advisory_xact_lock(72419074)')
            c.execute(SCHEMA)

    @contextmanager
    def account_lock(self, account_ref, mode):
        # Session lock survives commits; every executor/reconciler uses the same key.
        key = int(digest([account_ref, mode])[:15], 16)
        with self.connect() as c:
            if not c.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (key,)).fetchone()['acquired']:
                raise OrderError('ACCOUNT_EXECUTION_BUSY')
            try:
                c.commit()
                yield c
            finally:
                c.rollback()
                c.execute('SELECT pg_advisory_unlock(%s)', (key,))

    def save(self, plan):
        scope = digest([plan.intent_id,plan.account_ref,plan.mode,plan.operation,plan.parent_plan_id])
        with self.connect() as c:
            existing = c.execute('SELECT plan_id FROM market_os_order_plans WHERE scope_key=%s', (scope,)).fetchone()
            if existing:
                if existing['plan_id'] == plan.plan_id:
                    return plan
                raise OrderError('INTENT_ALREADY_HAS_IMMUTABLE_PLAN')
            c.execute('''INSERT INTO market_os_order_plans
                (plan_id,scope_key,intent_id,account_ref,mode,operation,stock_code,parent_plan_id,plan)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)''',
                (plan.plan_id,scope,plan.intent_id,plan.account_ref,plan.mode,plan.operation,
                 plan.stock_code,plan.parent_plan_id,json.dumps(asdict(plan))))
            self.event(c, plan.plan_id, 'prepare', 'HUMAN_PLAN_PREPARED', 'PREPARED',
                       {'broker_order_created':False})
        return plan

    def load(self, plan_id):
        with self.connect() as c:
            r = c.execute('SELECT plan FROM market_os_order_plans WHERE plan_id=%s', (plan_id,)).fetchone()
        if not r:
            raise OrderError('ORDER_PLAN_NOT_FOUND')
        plan = OrderPlan(**r['plan'])
        if plan.plan_id != plan_id:
            raise OrderError('ORDER_PLAN_HASH_CORRUPT')
        return plan

    def attempt(self, plan_id):
        with self.connect() as c:
            return c.execute('SELECT * FROM market_os_order_attempts WHERE plan_id=%s', (plan_id,)).fetchone()

    def record_block(self, plan, codes):
        with self.connect() as c:
            self.event(c,plan.plan_id,'block-'+uuid.uuid4().hex,'EXECUTION_BLOCKED','BLOCKED',
                       {'reason_codes':codes,'broker_order_created':False})

    def claim(self, plan, command_id):
        """Commit before broker call. Any crash after this point forbids resend."""
        with self.connect() as c:
            c.execute('SELECT plan_id FROM market_os_order_plans WHERE plan_id=%s FOR UPDATE', (plan.plan_id,))
            old = c.execute('SELECT * FROM market_os_order_attempts WHERE plan_id=%s', (plan.plan_id,)).fetchone()
            if old:
                raise OrderError('PLAN_ALREADY_ATTEMPTED_RECONCILE_ONLY')
            if c.execute('SELECT 1 FROM market_os_order_attempts WHERE command_id=%s', (command_id,)).fetchone():
                raise OrderError('COMMAND_ID_ALREADY_USED')
            unresolved = c.execute('''SELECT 1 FROM market_os_order_attempts a JOIN market_os_order_plans p
              USING(plan_id) WHERE p.account_ref=%s AND p.mode=%s AND
              (a.status IN ('SUBMITTING','UNKNOWN') OR (p.stock_code=%s AND
              a.status IN ('ACCEPTED','PARTIALLY_FILLED') AND p.plan_id IS DISTINCT FROM %s)) LIMIT 1''',
              (plan.account_ref,plan.mode,plan.stock_code,plan.parent_plan_id)).fetchone()
            if unresolved:
                raise OrderError('UNRESOLVED_OR_DUPLICATE_ORDER')
            c.execute('''INSERT INTO market_os_order_attempts(plan_id,command_id,status,quantity,remaining_quantity)
                      VALUES(%s,%s,'SUBMITTING',%s,%s)''', (plan.plan_id,command_id,plan.quantity,plan.quantity))
            self.event(c,plan.plan_id,'submit','EXPLICIT_EXECUTION_RESERVED','SUBMITTING',
                       {'risk_revalidated':True, 'control_hash':plan.control_hash})

    def event(self, c, plan_id, key, kind, status, evidence):
        return c.execute('''INSERT INTO market_os_order_events(plan_id,event_key,event_type,status,evidence)
          VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(plan_id,event_key) DO NOTHING RETURNING event_id''',
          (plan_id,key,kind,status,json.dumps(evidence))).fetchone()

    def result(self, plan, result):
        with self.connect() as c:
            r = c.execute('SELECT * FROM market_os_order_attempts WHERE plan_id=%s FOR UPDATE', (plan.plan_id,)).fetchone()
            if not r or r['status'] != 'SUBMITTING':
                raise OrderError('ATTEMPT_RESULT_STATE_CONFLICT')
            day = datetime.fromisoformat(plan.prepared_at).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
            key = digest([plan.account_ref,plan.mode,day,result.order_number]) if result.order_number else None
            remaining = 0 if result.status in {'REJECTED','DRY_RUN'} else plan.quantity
            c.execute('''UPDATE market_os_order_attempts SET status=%s,broker_order_number=%s,
                        broker_order_key=%s,remaining_quantity=%s,updated_at=now() WHERE plan_id=%s''',
                        (result.status,result.order_number,key,remaining,plan.plan_id))
            self.event(c,plan.plan_id,'response','BROKER_RESULT',result.status,
                       {'reason':result.reason,'broker_order_created':result.status=='ACCEPTED',
                        'broker_number_recorded':bool(result.order_number)})

    def update(self, plan, status, filled, event_key, remaining=None):
        with self.connect() as c:
            r = c.execute('SELECT * FROM market_os_order_attempts WHERE plan_id=%s FOR UPDATE', (plan.plan_id,)).fetchone()
            if not r:
                raise OrderError('ATTEMPT_NOT_FOUND')
            if c.execute('SELECT 1 FROM market_os_order_events WHERE plan_id=%s AND event_key=%s',
                         (plan.plan_id,event_key)).fetchone():
                return r
            out = advance(r,status,filled,remaining)
            c.execute('''UPDATE market_os_order_attempts SET status=%s,filled_quantity=%s,
                         remaining_quantity=%s,updated_at=now() WHERE plan_id=%s''',
                      (status,filled,out['remaining_quantity'],plan.plan_id))
            self.event(c,plan.plan_id,event_key,'BROKER_RECONCILIATION',status,
                       {'filled_quantity':filled,'remaining_quantity':out['remaining_quantity']})
            return out

    def mark_unknown(self, plan):
        with self.connect() as c:
            r = c.execute("""UPDATE market_os_order_attempts SET status='UNKNOWN',updated_at=now()
                WHERE plan_id=%s AND status='SUBMITTING' RETURNING plan_id""", (plan.plan_id,)).fetchone()
            if r:
                self.event(c,plan.plan_id,'restart','RESTART_UNCERTAIN','UNKNOWN', {'automatic_retry':False})

    def bind(self, plan, order_number):
        from market_os_order_recovery import trade_day
        key = digest([plan.account_ref,plan.mode,trade_day(plan),order_number])
        with self.connect() as c:
            r = c.execute("""UPDATE market_os_order_attempts SET broker_order_number=%s,
                    broker_order_key=%s,updated_at=now() WHERE plan_id=%s AND status='UNKNOWN'
                    AND broker_order_number IS NULL RETURNING plan_id""",(order_number,key,plan.plan_id)).fetchone()
            if not r:
                raise OrderError('LOST_ACK_BINDING_NOT_ALLOWED')
            self.event(c,plan.plan_id,'bind','HUMAN_VERIFIED_BROKER_LINEAGE','UNKNOWN',
                       {'broker_number_recorded':True,'automatic_retry':False})

    def public(self, plan):
        r = self.attempt(plan.plan_id)
        return {'plan_id':plan.plan_id,'intent_id':plan.intent_id,'parent_plan_id':plan.parent_plan_id,
                'stock_code':plan.stock_code,'mode':plan.mode,'operation':plan.operation,
                'quantity':plan.quantity,'limit_price':plan.limit_price,'expires_at':plan.expires_at,
                'status':r['status'] if r else 'PREPARED',
                'filled_quantity':r['filled_quantity'] if r else 0,
                'remaining_quantity':r['remaining_quantity'] if r else plan.quantity,
                'broker_number_recorded':bool(r and r['broker_order_number'])}
