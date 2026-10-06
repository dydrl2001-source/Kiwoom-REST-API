"""Explicit prepare/execute/reconcile service. Never imported by auto workers."""
from datetime import datetime, timezone
import re

from market_os_order_plan import build, validate, OrderError, digest
from market_os_broker import BrokerResult
from market_os_order_recovery import resolve, trade_day, binding_valid
from market_os_risk import fresh


class Executor:
    def __init__(self, store, source, broker, *, env=None, clock=None):
        self.store, self.source, self.broker = store, source, broker
        self.env = {} if env is None else env
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def parent(self, parent_id, account_ref, mode, stock_code=None, quantity=None):
        if parent_id is None:
            return None
        p = self.store.load(parent_id)
        a = self.store.attempt(parent_id)
        if (p.account_ref != account_ref or p.mode != mode or p.operation == 'CANCEL'
                or (stock_code is not None and p.stock_code != stock_code)
                or not a or a['status'] not in {'ACCEPTED','PARTIALLY_FILLED'}
                or not a['broker_order_number']):
            raise OrderError('PARENT_ORDER_NOT_AMENDABLE_OR_CANCELLABLE')
        if quantity is not None and quantity > a['remaining_quantity']:
            raise OrderError('CHILD_QUANTITY_EXCEEDS_PARENT_REMAINING')
        return {'plan':p, 'attempt':a}

    def prepare(self, intent_id, account_ref, mode, *, quantity, limit_price, stop_price,
                operation='BUY', parent_plan_id=None):
        if mode != self.broker.mode:
            raise OrderError('EXECUTOR_BROKER_MODE_MISMATCH')
        with self.store.account_lock(account_ref,mode) as connection:
            parent = self.parent(parent_plan_id,account_ref,mode,quantity=quantity)
            request = {'quantity':quantity,'limit_price':limit_price,'stop_price':stop_price,'operation':operation}
            with self.source.guard(connection,intent_id,account_ref,mode,parent,request=request) as context:
                plan = build(context,quantity=quantity,limit_price=limit_price,stop_price=stop_price,
                             mode=mode,now=self.clock(),operation=operation,parent_plan_id=parent_plan_id)
                self.parent(parent_plan_id,account_ref,mode,stock_code=plan.stock_code,quantity=quantity)
                self.validate_parent_facts(plan,parent,context)
                return self.store.save(plan)

    def execute(self, plan_id, command_id, *, confirm):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', str(command_id)):
            raise OrderError('EXECUTION_COMMAND_ID_REQUIRED')
        plan = self.store.load(plan_id)
        if self.broker.mode != plan.mode:
            raise OrderError('EXECUTOR_BROKER_MODE_MISMATCH')
        with self.store.account_lock(plan.account_ref,plan.mode) as connection:
            # Check previous reservation before source/network calls or a new command ID.
            if self.store.attempt(plan_id):
                raise OrderError('PLAN_ALREADY_ATTEMPTED_RECONCILE_ONLY')
            parent = self.parent(plan.parent_plan_id,plan.account_ref,plan.mode,plan.stock_code,plan.quantity)
            request = {'quantity':plan.quantity,'limit_price':plan.limit_price,
                       'stop_price':plan.stop_price,'operation':plan.operation}
            with self.source.guard(connection,plan.intent_id,plan.account_ref,plan.mode,parent,request=request) as context:
                try:
                    validate(plan,context,now=self.clock(),confirm=confirm,env=self.env)
                    self.validate_parent_facts(plan,parent,context)
                except OrderError as exc:
                    self.store.record_block(plan,str(exc).split(','))
                    raise
                self.store.claim(plan,command_id)
                # Reservation is durable. CONTROL/intent locks remain held on guard connection.
                # Revalidate time after committing the reservation (TTL/quote may have elapsed).
                try:
                    validate(plan,context,now=self.clock(),confirm=confirm,env=self.env)
                    self.validate_parent_facts(plan,parent,context)
                except OrderError:
                    self.store.result(plan,BrokerResult('REJECTED',reason='PRE_SEND_REVALIDATION_BLOCKED'))
                    raise
                try:
                    result = self.broker.submit(plan,parent['attempt']['broker_order_number'] if parent else None,
                                               execution_confirm=confirm)
                except Exception:
                    result = BrokerResult('UNKNOWN',reason='EXECUTOR_BROKER_UNCERTAIN')
                self.store.result(plan,result)
        return self.store.public(plan)

    def reconcile(self, plan_id, *, broker_order_number=None, confirm=None):
        plan = self.store.load(plan_id)
        with self.store.account_lock(plan.account_ref,plan.mode):
            self.store.mark_unknown(plan)  # Any abandoned SUBMITTING is now a recovery-only attempt.
            a = self.store.attempt(plan_id)
            if not a:
                raise OrderError('ATTEMPT_NOT_FOUND')
            if plan.mode != 'live':
                return self.store.public(plan)  # Paper fills require explicit simulated events, never real history.
            history = self.source.history(plan)
            if (history.get('complete') is not True or history.get('account_ref') != plan.account_ref
                    or history.get('mode') != 'live' or history.get('trade_day_kst') != trade_day(plan)
                    or not fresh(history.get('observed_at'),self.clock(),30)):
                raise OrderError('RECOVERY_HISTORY_INCOMPLETE_STALE_OR_WRONG_ACCOUNT')
            if broker_order_number is not None:
                if confirm != plan_id or not re.fullmatch(r'[0-9]{1,20}',str(broker_order_number)):
                    raise OrderError('EXPLICIT_RECOVERY_BINDING_CONFIRMATION_REQUIRED')
                rows=[r for r in history.get('rows',[]) if r.get('ord_no')==broker_order_number]
                parent = self.store.attempt(plan.parent_plan_id) if plan.parent_plan_id else None
                if (len(rows)!=1 or not binding_valid(plan,a,rows[0],
                        parent['broker_order_number'] if parent else None)):
                    raise OrderError('BROKER_REQUEST_LINEAGE_NOT_VERIFIED')
                self.store.bind(plan,broker_order_number)
                a=self.store.attempt(plan_id)
            result = resolve({**a,'operation':plan.operation,'stock_code':plan.stock_code},history.get('rows',[]))
            if result:
                self.store.update(plan,result['status'],result['filled_quantity'],
                                  'history-'+digest([a['broker_order_number'],result['status'],result['filled_quantity'],result['remaining_quantity']]),
                                  remaining=result['remaining_quantity'])
        return self.store.public(plan)

    def validate_parent_facts(self, plan, parent, context):
        if not parent:
            return
        facts = context.get('facts') or {}
        qty = facts.get('parent_remaining_quantity')
        if (facts.get('parent_order_number') != parent['attempt']['broker_order_number']
                or not fresh(facts.get('parent_as_of'),self.clock(),5)
                or type(qty) is not int or not plan.quantity <= qty <= parent['attempt']['remaining_quantity']):
            raise OrderError('PARENT_REMAINING_UNVERIFIED_STALE_OR_EXCEEDED')

    def paper_event(self, plan_id, *, status, filled_quantity, event_key, confirm):
        plan = self.store.load(plan_id)
        if plan.mode != 'paper' or self.broker.mode != 'paper' or confirm != plan_id:
            raise OrderError('EXPLICIT_PAPER_EVENT_ONLY')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',str(event_key)):
            raise OrderError('PAPER_EVENT_KEY_INVALID')
        with self.store.account_lock(plan.account_ref,'paper'):
            self.store.update(plan,status,filled_quantity,'paper-'+event_key)
        return self.store.public(plan)
