"""Runs against the real CI PostgreSQL service, never a broker."""
import os
import sys
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests import test_market_os_orders as fixture_module

DB = os.getenv('MARKET_OS_TEST_DATABASE_URL')


@unittest.skipUnless(DB, 'MARKET_OS_TEST_DATABASE_URL required')
class OrderDatabaseTests(unittest.TestCase):
    def setUp(self):
        from market_os_order_store import Store
        from market_os_orders import Executor
        from market_os_broker import PaperBroker
        self.store = Store(DB)
        self.store.ensure_schema()
        fixture = fixture_module.OrderPolicyTests(); fixture.setUp()
        self.now = fixture.now
        self.context = fixture.context
        self.context['account_ref'] = 'test-' + uuid.uuid4().hex
        self.context['intent']['intent_id'] = 'oi-' + uuid.uuid4().hex
        class Source:
            @contextmanager
            def guard(inner, connection, intent_id, account_ref, mode, parent, *, request):
                if parent:
                    self.context['facts'].update(parent_order_number=parent['attempt']['broker_order_number'],
                        parent_remaining_quantity=parent['attempt']['remaining_quantity'],parent_as_of=self.now)
                yield self.context
            def history(inner, plan):
                return self.history
        self.history = {'complete':True, 'account_ref':self.context['account_ref'], 'mode':'paper',
                        'observed_at':self.now, 'rows':[]}
        self.source = Source()
        self.executor = Executor(self.store,self.source,PaperBroker(),env={},clock=lambda:self.now)
        self.plan = self.executor.prepare(self.context['intent']['intent_id'],self.context['account_ref'],
                                         'paper',quantity=2,limit_price=70000,stop_price=69000)

    def test_prepare_does_not_submit_and_repeated_execute_never_resends(self):
        from market_os_order_plan import OrderError
        self.assertIsNone(self.store.attempt(self.plan.plan_id))
        out = self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.assertEqual(out['status'],'ACCEPTED')
        self.assertNotIn('account_ref',out)
        self.assertNotIn('broker_order_number',out)
        with self.assertRaisesRegex(OrderError,'ALREADY_ATTEMPTED'):
            self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)

    def test_crash_reservation_survives_restart_and_unknown_blocks_account(self):
        from market_os_order_plan import OrderError
        self.store.claim(self.plan,'crash-'+uuid.uuid4().hex)
        self.executor.reconcile(self.plan.plan_id)
        self.assertEqual(self.store.attempt(self.plan.plan_id)['status'],'UNKNOWN')
        with self.assertRaises(OrderError):
            self.executor.execute(self.plan.plan_id,'new-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        another = replace(self.plan,intent_id='oi-'+uuid.uuid4().hex,stock_code='000660')
        self.store.save(another)
        with self.assertRaisesRegex(OrderError,'UNRESOLVED'):
            self.store.claim(another,'cmd-'+uuid.uuid4().hex)

    def test_duplicate_events_and_monotonic_fill_survive_reopen(self):
        from market_os_order_plan import OrderError
        self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.store.update(self.plan,'PARTIALLY_FILLED',1,'fill1')
        self.store.update(self.plan,'PARTIALLY_FILLED',1,'fill1')
        self.store.update(self.plan,'FILLED',2,'fill2')
        with self.assertRaises(OrderError): self.store.update(self.plan,'ACCEPTED',0,'late')
        from market_os_order_store import Store
        self.assertEqual(Store(DB).attempt(self.plan.plan_id)['filled_quantity'],2)
        with self.store.connect() as c:
            n=c.execute("SELECT count(*) AS n FROM market_os_order_events WHERE plan_id=%s AND event_key='fill1'",
                        (self.plan.plan_id,)).fetchone()['n']
        self.assertEqual(n,1)

    def test_plan_and_audit_are_immutable_in_database(self):
        import psycopg
        with self.assertRaises(psycopg.Error):
            with self.store.connect() as c:
                c.execute("UPDATE market_os_order_plans SET plan='{}'::jsonb WHERE plan_id=%s",(self.plan.plan_id,))
        with self.assertRaises(psycopg.Error):
            with self.store.connect() as c:
                c.execute('DELETE FROM market_os_order_events WHERE plan_id=%s',(self.plan.plan_id,))

    def test_concurrent_account_lock_denies_second_executor(self):
        from market_os_order_plan import OrderError
        with self.store.account_lock(self.plan.account_ref,'paper'):
            with self.assertRaisesRegex(OrderError,'BUSY'):
                self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.assertIsNone(self.store.attempt(self.plan.plan_id))

    def test_post_prepare_control_change_blocks_without_reservation(self):
        from market_os_order_plan import OrderError
        self.context['control']['control_hash']='stale'
        with self.assertRaisesRegex(OrderError,'CONTROL'):
            self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.assertIsNone(self.store.attempt(self.plan.plan_id))

    def test_child_acceptance_does_not_fabricate_parent_cancel(self):
        self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        child = self.executor.prepare(self.plan.intent_id,self.plan.account_ref,'paper',quantity=1,
                                     limit_price=70000,stop_price=69000,operation='CANCEL',
                                     parent_plan_id=self.plan.plan_id)
        self.executor.execute(child.plan_id,'cmd-'+uuid.uuid4().hex,confirm=child.plan_id)
        self.assertEqual(self.store.attempt(self.plan.plan_id)['status'],'ACCEPTED')
        self.assertEqual(child.parent_plan_id,self.plan.plan_id)

    def test_timeout_is_unknown_and_new_command_cannot_resubmit(self):
        from market_os_order_plan import OrderError
        class TimeoutBroker:
            mode='paper'
            def submit(self,*args,**kwargs): raise TimeoutError('private')
        self.executor.broker=TimeoutBroker()
        out=self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.assertEqual(out['status'],'UNKNOWN')
        with self.assertRaises(OrderError):
            self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)

    def test_rejected_plan_is_not_retried(self):
        from market_os_broker import BrokerResult
        from market_os_order_plan import OrderError
        class RejectBroker:
            mode='paper'
            def submit(self,*args,**kwargs): return BrokerResult('REJECTED',reason='BROKER_REJECTED')
        self.executor.broker=RejectBroker()
        out=self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.assertEqual(out['status'],'REJECTED')
        self.assertEqual(out['remaining_quantity'],0)
        with self.assertRaises(OrderError):
            self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)

    def test_approved_intent_cannot_be_replanned_with_other_quantity(self):
        from market_os_order_plan import OrderError
        with self.assertRaisesRegex(OrderError,'IMMUTABLE_PLAN'):
            self.executor.prepare(self.plan.intent_id,self.plan.account_ref,'paper',quantity=3,
                                  limit_price=70000,stop_price=69000)

    def test_paper_fill_then_amend_tracks_child_and_excludes_filled_quantity(self):
        self.executor.execute(self.plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        self.executor.paper_event(self.plan.plan_id,status='PARTIALLY_FILLED',filled_quantity=1,
                                  event_key='partial-'+uuid.uuid4().hex,confirm=self.plan.plan_id)
        from market_os_order_plan import OrderError
        with self.assertRaisesRegex(OrderError,'REMAINING'):
            self.executor.prepare(self.plan.intent_id,self.plan.account_ref,'paper',quantity=2,
                 limit_price=70000,stop_price=69000,operation='AMEND',parent_plan_id=self.plan.plan_id)
        child=self.executor.prepare(self.plan.intent_id,self.plan.account_ref,'paper',quantity=1,
                 limit_price=70000,stop_price=69000,operation='AMEND',parent_plan_id=self.plan.plan_id)
        self.executor.execute(child.plan_id,'cmd-'+uuid.uuid4().hex,confirm=child.plan_id)
        self.assertEqual(self.store.attempt(self.plan.plan_id)['filled_quantity'],1)

    def test_live_off_blocks_before_claim_or_adapter(self):
        from market_os_order_plan import OrderError
        class NoBroker:
            mode='live'
            def submit(self,*args,**kwargs): raise AssertionError('unexpected broker call')
        self.executor.broker=NoBroker()
        plan=self.executor.prepare(self.plan.intent_id,self.plan.account_ref,'live',quantity=2,
                                   limit_price=70000,stop_price=69000)
        with self.assertRaisesRegex(OrderError,'DISABLED'):
            self.executor.execute(plan.plan_id,'cmd-'+uuid.uuid4().hex,confirm=plan.plan_id)
        self.assertIsNone(self.store.attempt(plan.plan_id))


if __name__=='__main__': unittest.main()
