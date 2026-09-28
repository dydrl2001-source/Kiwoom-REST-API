import unittest

from ai_brokerage.execution_model import FillPolicy, SizingPolicy, estimate_fill, round_trip_result


class ShadowExecutionModelTests(unittest.TestCase):
    def test_sizing_respects_risk_and_position_caps(self):
        p=SizingPolicy(account_equity_krw=100_000_000,risk_per_trade_pct=0.5,max_position_pct=10.0)
        out=p.size(50_000,25)
        self.assertGreater(out["shares"],0)
        self.assertLessEqual(out["requested_notional_krw"],10_000_000)
        self.assertGreaterEqual(out["stop_pct"],1.0)
        self.assertLessEqual(out["stop_pct"],5.0)

    def test_no_recent_turnover_means_no_fill(self):
        out=estimate_fill("BUY",100_000,10,None,20,FillPolicy())
        self.assertEqual(out["status"],"NO_LIQUIDITY_EVIDENCE")
        self.assertEqual(out["filled_shares"],0)

    def test_participation_cap_can_force_partial_fill(self):
        policy=FillPolicy(max_participation_pct=1.0)
        out=estimate_fill("BUY",100_000,100,10_000_000,20,policy)
        self.assertEqual(out["status"],"PARTIAL")
        self.assertLess(out["filled_shares"],100)
        self.assertGreater(out["filled_shares"],0)

    def test_buy_and_sell_slippage_move_against_trader(self):
        policy=FillPolicy(max_participation_pct=10.0)
        buy=estimate_fill("BUY",100_000,10,100_000_000,20,policy)
        sell=estimate_fill("SELL",100_000,10,100_000_000,20,policy)
        self.assertGreater(buy["fill_price_krw"],100_000)
        self.assertLess(sell["fill_price_krw"],100_000)
        self.assertAlmostEqual(buy["slippage_bps"],sell["slippage_bps"])

    def test_round_trip_net_includes_costs(self):
        policy=FillPolicy(max_participation_pct=10.0,commission_bps=2.0,sell_tax_bps=10.0)
        entry=estimate_fill("BUY",100_000,10,100_000_000,20,policy)
        exit=estimate_fill("SELL",102_000,10,100_000_000,20,policy)
        result=round_trip_result(entry,exit)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertLess(result["net_return_pct"],result["gross_return_pct"])
        self.assertGreater(result["costs_krw"],0)


class ShadowExecutionSourceTests(unittest.TestCase):
    def test_model_never_places_orders(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        text=(root/"shadow_execution_engine.py").read_text(encoding="utf-8")
        for banned in ("send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)
        self.assertIn("no broker orders",text)

    def test_worker_is_forward_only_and_requires_flow_evidence(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        text=(root/"shadow_execution_engine.py").read_text(encoding="utf-8")
        self.assertIn("simulation_cutoff",text)
        self.assertIn("MAX_REPLAY_MINUTES",text)
        self.assertNotIn("interval '7 days'",text)
        self.assertNotIn('ref=ref or finite(p["entry_price_krw"])',text)
        self.assertNotIn('ref=ref or finite(s["exit_price_krw"])',text)


if __name__=="__main__":
    unittest.main()
