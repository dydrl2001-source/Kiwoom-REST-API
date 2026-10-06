import dataclasses
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class OrderPolicyTests(unittest.TestCase):
    def setUp(self):
        import market_os_order_plan as p
        from market_os_execution import snapshot
        from market_os_control import control_hash
        self.p = p
        self.now = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
        c = dict(control_id='ctrl', mode='RULESET', switch_transaction_id='switch',
                 active_version_label='v1', ruleset_spec={}, apply_status='APPLIED')
        c['control_hash'] = control_hash(c)
        self.candidate = dict(code='005930', watch_tier='FOCUS', trigger_state='STRUCTURE_CONFIRMED',
                              market_stance='SELECTIVE', catalyst_grade='A', risk_flags=[])
        expiry = self.now + timedelta(seconds=120)
        frozen = snapshot(self.candidate, c, 70000, self.now, expiry)
        self.intent = dict(intent_id='oi-test', status='HUMAN_APPROVED_INTENT', stock_code='005930',
                           expires_at=expiry, reviewed_at=self.now, reviewed_by='MANUAL_SCRIPT',
                           control_hash=c['control_hash'], switch_transaction_id='switch', **frozen)
        f = dict(price_krw=70000, daily_loss_pct=0, theme_intact=True, turnover_rate_ratio=1,
                 data_confidence=1, duplicate_order=False, quality_flags=[], session_open=True,
                 is_trading_day=True, executable=True, orderable_quantity=10, tick_size_krw=100)
        for name in ('price', 'account', 'session', 'duplicate', 'theme', 'turnover'):
            f[name + '_as_of'] = self.now
        self.context = dict(intent=self.intent, control=c, switch_state='HEALTHY',
                            candidate=self.candidate, facts=f, account_ref='account-test',
                            broker_mode='real', observed_at=self.now)

    def build(self, **kwargs):
        return self.p.build(self.context, quantity=2, limit_price=70000, stop_price=69000,
                            mode=kwargs.pop('mode', 'paper'), now=self.now, **kwargs)

    def test_plan_is_frozen_and_hash_covers_quantity_and_mode(self):
        a = self.build()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.quantity = 10
        self.assertNotEqual(a.plan_id, dataclasses.replace(a, quantity=3).plan_id)
        self.assertNotEqual(a.plan_id, self.build(mode='live').plan_id)

    def test_unapproved_and_tampered_evidence_cannot_make_plan(self):
        self.intent['status'] = 'REVIEW_PENDING'
        with self.assertRaisesRegex(self.p.OrderError, 'INTENT_NOT_APPROVED'):
            self.build()
        self.intent['status'] = 'HUMAN_APPROVED_INTENT'
        self.intent['evidence']['stock_code'] = '000660'
        with self.assertRaisesRegex(self.p.OrderError, 'EVIDENCE'):
            self.build()

    def test_extending_approval_ttl_cannot_override_frozen_intent_evidence(self):
        self.intent['expires_at'] += timedelta(seconds=600)
        with self.assertRaisesRegex(self.p.OrderError,'EVIDENCE_TTL'):
            self.build()

    def test_separate_confirmation_live_off_and_wrong_account_block(self):
        a = self.build(mode='live')
        for confirm, env in ((None, {}), (a.plan_id, {}), ('wrong', {'MARKET_OS_LIVE_ORDERS_ENABLED':'1'})):
            with self.assertRaises(self.p.OrderError):
                self.p.validate(a, self.context, now=self.now, confirm=confirm, env=env)
        self.context['account_ref'] = 'different'
        with self.assertRaisesRegex(self.p.OrderError, 'ACCOUNT_BINDING'):
            self.p.validate(a, self.context, now=self.now, confirm=a.plan_id,
                            env={'MARKET_OS_LIVE_ORDERS_ENABLED':'1'})

    def test_control_change_expiry_stale_quote_and_capacity_rechecked(self):
        for mutate, reason in (
            (lambda c: c['control'].update(control_hash='changed'), 'CONTROL'),
            (lambda c: c['intent'].update(expires_at=self.now), 'EXPIRED'),
            (lambda c: c['facts'].update(price_as_of=self.now-timedelta(seconds=6)), 'QUOTE'),
            (lambda c: c['facts'].update(orderable_quantity=1), 'CAPACITY'),
            (lambda c: c['facts'].update(executable=False), 'ACCOUNT'),
            (lambda c: c['facts'].update(daily_loss_pct=None), 'DAILY_LOSS'),
            (lambda c: c['facts'].update(duplicate_order=True), 'DUPLICATE'),
            (lambda c: c['facts'].update(price_krw=68000), 'STOP_INVALID'),
        ):
            with self.subTest(reason=reason):
                self.setUp()
                a = self.build()
                mutate(self.context)
                with self.assertRaisesRegex(self.p.OrderError, reason):
                    self.p.validate(a, self.context, now=self.now, confirm=a.plan_id, env={})

    def test_invalid_numbers_and_price_risk(self):
        for qty in (True, 0, -1, 1.5):
            with self.assertRaises(self.p.OrderError):
                self.p.build(self.context, quantity=qty, limit_price=70000, stop_price=69000,
                             mode='paper', now=self.now)
        for price in (float('nan'), 0, 70123, 72000):
            with self.assertRaises(self.p.OrderError):
                self.p.build(self.context, quantity=1, limit_price=price, stop_price=69000,
                             mode='paper', now=self.now)

    def test_cancel_is_fresh_explicit_risk_reduction_after_entry_expiry(self):
        self.intent['expires_at'] = self.now - timedelta(seconds=1)
        self.context['facts'].update(daily_loss_pct=None, duplicate_order=True,
                                     orderable_quantity=0)
        a = self.p.build(self.context,quantity=1,limit_price=70000,stop_price=69000,
                         mode='paper',now=self.now,operation='CANCEL',parent_plan_id='parent')
        self.p.validate(a,self.context,now=self.now,confirm=a.plan_id,env={})
        with self.assertRaisesRegex(self.p.OrderError,'EXPIRED'):
            self.p.validate(a,self.context,now=self.now+timedelta(seconds=121),confirm=a.plan_id,env={})


class BrokerTests(unittest.TestCase):
    def test_account_binding_is_same_for_same_broker_account_across_app_keys(self):
        from market_os_order_source import credential_account_ref
        class AccountClient:
            token='private'
            def read(self,*a): return {}
            def _post(self,*a,**k): return ({'acctNo':'1234567890'}, {})
        env={'KIWOOM_MODE':'real','APP_KEY':'key1','APP_SECRET':'secret1',
             'MARKET_OS_ACCOUNT_BINDING_SECRET':'a'*32}
        first=credential_account_ref(env,client=AccountClient())
        second=credential_account_ref({**env,'APP_KEY':'key2'},client=AccountClient())
        self.assertEqual(first,second)
        self.assertNotIn('1234567890',first)
        self.assertNotIn('key1',first)

    def test_paper_and_dry_run_do_not_construct_http_client(self):
        from market_os_broker import PaperBroker, DryRunBroker
        for broker in (PaperBroker(), DryRunBroker()):
            self.assertNotEqual(broker.mode, 'live')

    def test_live_adapter_never_retries_or_exposes_broker_message(self):
        from market_os_broker import KiwoomBroker
        policy = OrderPolicyTests(); policy.setUp(); plan = policy.build(mode='live')
        class Transport:
            def __init__(self): self.calls = []
            def post(self, url, **kw):
                self.calls.append((url, kw))
                raise TimeoutError('secret account number')
        transport = Transport()
        broker = KiwoomBroker('private-token', 'account-test', transport=transport,
                              env={'MARKET_OS_LIVE_ORDERS_ENABLED':'1'})
        result = broker.submit(plan, None, execution_confirm=plan.plan_id)
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn('secret', repr(result))
        url, kw = transport.calls[0]
        self.assertEqual(url, 'https://api.kiwoom.com/api/dostk/ordr')
        self.assertFalse(kw['allow_redirects'])
        self.assertEqual(kw['json']['trde_tp'], '0')

    def test_missing_return_code_missing_number_and_http_error_are_unknown(self):
        from market_os_broker import KiwoomBroker
        policy = OrderPolicyTests(); policy.setUp(); plan = policy.build(mode='live')
        for status, body, expected in ((200, {}, 'UNKNOWN'), (200, {'return_code':0}, 'UNKNOWN'),
                                      (503, {'return_code':0,'ord_no':'123'}, 'UNKNOWN'),
                                      (200, {'return_code':1,'return_msg':'private'}, 'REJECTED'),
                                      (200, {'return_code':0,'ord_no':'0001234'}, 'ACCEPTED')):
            class Transport:
                def post(self, *a, **k):
                    class Response:
                        status_code = status
                        def json(self): return body
                    return Response()
            r = KiwoomBroker('token', 'account-test', transport=Transport(),
                            env={'MARKET_OS_LIVE_ORDERS_ENABLED':'1'}).submit(plan, None,execution_confirm=plan.plan_id)
            self.assertEqual(r.status, expected)

    def test_adapter_itself_is_off_without_live_enable_and_explicit_plan(self):
        from market_os_broker import KiwoomBroker
        from market_os_order_plan import OrderError
        policy = OrderPolicyTests(); policy.setUp(); plan = policy.build(mode='live')
        class NeverSend:
            def post(self,*a,**k): raise AssertionError('unexpected broker call')
        for env, confirm in (({},plan.plan_id),({'MARKET_OS_LIVE_ORDERS_ENABLED':'1'},None)):
            broker = KiwoomBroker('token','account-test',transport=NeverSend(),env=env)
            with self.assertRaises(OrderError): broker.submit(plan,None,execution_confirm=confirm)

    def test_lifecycle_monotonic_duplicate_and_terminal_guards(self):
        from market_os_order_plan import advance, OrderError
        state = {'status':'ACCEPTED', 'filled_quantity':0, 'quantity':10}
        state = advance(state, 'PARTIALLY_FILLED', 4)
        self.assertEqual(state['filled_quantity'], 4)
        for status, qty in (('PARTIALLY_FILLED',3), ('FILLED',9), ('FILLED',11)):
            with self.assertRaises(OrderError): advance(state, status, qty)
        state = advance(state, 'FILLED',10)
        with self.assertRaises(OrderError): advance(state, 'ACCEPTED',10)


if __name__ == '__main__': unittest.main()
