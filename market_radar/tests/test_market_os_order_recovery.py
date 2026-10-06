import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RecoveryTests(unittest.TestCase):
    def test_unknown_without_exact_broker_number_never_guesses_match(self):
        from market_os_order_recovery import resolve
        attempt = dict(status='UNKNOWN', broker_order_number=None, quantity=2,
                       filled_quantity=0, operation='BUY', stock_code='005930')
        rows = [dict(ord_no='1234', stk_cd='005930', ord_qty='2', cntr_qty='2',
                     ord_remnq='0', io_tp_nm='매수')]
        self.assertIsNone(resolve(attempt, rows))

    def test_exact_history_partial_full_reject_cancel_and_ambiguity(self):
        from market_os_order_recovery import resolve
        a = dict(status='ACCEPTED', broker_order_number='1234', quantity=10,
                 filled_quantity=0, operation='BUY', stock_code='005930')
        row = dict(ord_no='1234', stk_cd='005930', ord_qty='10', cntr_qty='4',
                   ord_remnq='6', io_tp_nm='매수', acpt_tp='접수', mdfy_cncl='')
        self.assertEqual(resolve(a, [row])['status'], 'PARTIALLY_FILLED')
        self.assertEqual(resolve(a, [{**row, 'cntr_qty':'10', 'ord_remnq':'0'}])['status'], 'FILLED')
        self.assertEqual(resolve(a, [{**row, 'acpt_tp':'거부','cntr_qty':'0','ord_remnq':'0'}])['status'], 'REJECTED')
        self.assertEqual(resolve(a, [{**row, 'mdfy_cncl':'취소', 'ord_remnq':'0'}])['status'], 'CANCELLED')
        self.assertIsNone(resolve(a, [row, row]))
        self.assertIsNone(resolve(a, [{**row, 'stk_cd':'000660'}]))
        self.assertIsNone(resolve(a, [{**row, 'cntr_qty':'-1'}]))

    def test_unknown_child_status_is_not_assumed_filled(self):
        from market_os_order_recovery import resolve
        a = dict(status='UNKNOWN', broker_order_number='1234', quantity=4,
                 filled_quantity=0, operation='CANCEL', stock_code='005930')
        row = dict(ord_no='1234', stk_cd='005930', ord_qty='4', cntr_qty='0', ord_remnq='0')
        self.assertIsNone(resolve(a, [row]))

    def test_partial_cancel_preserves_reduced_remaining_quantity(self):
        from market_os_order_recovery import resolve
        a = dict(status='ACCEPTED',broker_order_number='1234',quantity=10,
                 filled_quantity=0,remaining_quantity=10,operation='BUY',stock_code='005930')
        row = dict(ord_no='1234',stk_cd='005930',ord_qty='10',cntr_qty='0',ord_remnq='6',
                   io_tp_nm='매수',acpt_tp='접수',mdfy_cncl='취소')
        out = resolve(a,[row])
        self.assertEqual(out['status'],'ACCEPTED')
        self.assertEqual(out['remaining_quantity'],6)

    def test_explicit_lost_ack_binding_checks_full_request_and_time(self):
        from market_os_order_recovery import binding_valid
        from tests.test_market_os_orders import OrderPolicyTests
        f=OrderPolicyTests(); f.setUp(); plan=f.build(mode='live')
        row=dict(ord_no='1234',stk_cd='005930',ord_qty='2',ord_uv='70000',
                 io_tp_nm='매수',ord_tm='100002',mdfy_cncl='')
        self.assertTrue(binding_valid(plan,{'submitted_at':f.now},row))
        self.assertFalse(binding_valid(plan,{'submitted_at':f.now},{**row,'ord_uv':'70100'}))
        self.assertFalse(binding_valid(plan,{'submitted_at':f.now},{**row,'ord_tm':'090001'}))


if __name__ == '__main__': unittest.main()
