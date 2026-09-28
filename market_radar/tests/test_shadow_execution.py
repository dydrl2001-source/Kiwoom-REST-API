import unittest

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

    def test_book_fill_walks_depth_and_computes_shortfall(self):
        book={
            "best_ask_krw":101.0,"best_bid_krw":99.0,
            "asks":[{"level":1,"price_krw":101.0,"qty":10},{"level":2,"price_krw":102.0,"qty":20}],
            "bids":[{"level":1,"price_krw":99.0,"qty":12},{"level":2,"price_krw":98.0,"qty":20}],
        }
        out=estimate_book_fill("BUY",15,book,BookPolicy(displayed_liquidity_haircut=1.0,max_spread_bps=500))
        self.assertEqual(out["status"],"FILLED")
        self.assertEqual(out["filled_shares"],15)
        self.assertEqual(out["levels_used"],2)
        self.assertAlmostEqual(out["fill_price_krw"],(1010+510)/15)
        self.assertGreater(out["implementation_shortfall_bps"],0)
        self.assertGreater(out["depth_slippage_bps"],0)

    def test_book_depth_can_force_partial_fill(self):
        book={
            "best_ask_krw":101.0,"best_bid_krw":100.0,
            "asks":[{"level":1,"price_krw":101.0,"qty":10}],
            "bids":[{"level":1,"price_krw":100.0,"qty":10}],
        }
        out=estimate_book_fill("BUY",10,book,BookPolicy(displayed_liquidity_haircut=0.5,max_spread_bps=500))
        self.assertEqual(out["status"],"PARTIAL")
        self.assertEqual(out["filled_shares"],5)
        self.assertEqual(out["remaining_shares"],5)

    def test_portfolio_risk_budget_scales_theme_concentration(self):
        policy=PortfolioRiskPolicy(
            account_equity_krw=100_000_000,
            max_total_risk_pct=2.0,
            max_theme_risk_pct=0.8,
            max_family_risk_pct=1.2,
            max_open_positions=5,
        )
        open_positions=[
            {"market_theme":"반도체","strategy_family":"BREAKOUT","risk_krw":700_000}
        ]
        out=portfolio_risk_budget(500_000,"반도체","BREAKOUT",open_positions,policy)
        self.assertTrue(out["allowed"])
        self.assertAlmostEqual(out["allowed_risk_krw"],100_000)
        self.assertAlmostEqual(out["risk_scale"],0.2)

    def test_portfolio_max_open_is_hard_block(self):
        policy=PortfolioRiskPolicy(account_equity_krw=100_000_000,max_open_positions=1)
        out=portfolio_risk_budget(
            100_000,"반도체","BREAKOUT",
            [{"market_theme":"금융","strategy_family":"FLOW","risk_krw":100_000}],
            policy
        )
        self.assertFalse(out["allowed"])
        self.assertIn("MAX_OPEN_POSITIONS",out["blockers"])

    def test_tca_round_trip_sums_entry_and_exit_shortfall(self):
        entry={"implementation_shortfall_bps":8.0,"spread_bps":10.0,"depth_slippage_bps":3.0}
        exit={"implementation_shortfall_bps":7.0,"spread_bps":12.0,"depth_slippage_bps":2.0}
        out=implementation_shortfall_summary(entry,exit)
        self.assertEqual(out["round_trip_is_bps"],15.0)
        self.assertEqual(out["entry_is_bps"],8.0)
        self.assertEqual(out["exit_is_bps"],7.0)

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
        self.assertIn("BOOK_V2",text)
        self.assertIn("portfolio_risk_budget",text)
        self.assertIn("latest_book",text)


if __name__=="__main__":
    unittest.main()
