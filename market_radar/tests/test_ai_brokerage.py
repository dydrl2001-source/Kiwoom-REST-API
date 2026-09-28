import unittest

from ai_brokerage.analytics import (
    build_context_matrix,
    build_daily_review,
    lifecycle_candidates,
    summarize_strategy_rows,
)
from ai_brokerage.decision_engine import DecisionEngine
from ai_brokerage.strategy_registry import StrategyRegistry


class AIBrokerageTest(unittest.TestCase):
    def test_registry_has_50_unique_strategies(self):
        r=StrategyRegistry()
        rows=r.all()
        self.assertEqual(len(rows),50)
        self.assertEqual(len({x.strategy_id for x in rows}),50)
        self.assertGreater(r.lifecycle_counts()["PAPER"],0)

    def test_decision_engine_produces_six_desks(self):
        ctx={
            "stock_code":"005930","stock_name":"샘플",
            "regime":{"trend":"RISING","flow":"LEADER_CONCENTRATED","sentiment":"STRONG",
                      "data_freshness_sec":20,"confidence":0.8},
            "candidate":{"score":86,"rank":3,"rank_change":4,
                         "trade_value_krw":100_000_000_000,"recent_turnover_krw":10_000_000_000},
            "material":{"material_strength":3,"identity_quality":"VERIFIED","status":"MULTI_CHANNEL"},
            "theme":{"theme_strength":75},
            "chart":{"state":"BREAKOUT_HOLD","minute_trend":"UP"},
            "quote":{"freshness_sec":15},
            "risk":{"open_positions":1,"max_open":5,"daily_realized_pct":0.3,
                    "max_daily_loss_pct":2.0,"already_open":False,"paper_mode":True},
        }
        out=DecisionEngine().evaluate(ctx).to_dict()
        self.assertEqual(len(out["desks"]),6)
        self.assertEqual(out["state"],"PAPER_ENTRY")
        self.assertIsNotNone(out["selected_strategy"])
        self.assertTrue(out["paper_only"])

    def test_strategy_performance_groups_by_strategy(self):
        rows=[
            {"status":"CLOSED","strategy_id":"MR-T01","strategy_name":"A","strategy_family":"TREND",
             "return_pct":1.0,"mfe_pct":2.0,"mae_pct":-0.4},
            {"status":"CLOSED","strategy_id":"MR-T01","strategy_name":"A","strategy_family":"TREND",
             "return_pct":-0.5,"mfe_pct":0.5,"mae_pct":-1.0},
            {"status":"OPEN","strategy_id":"MR-T01","strategy_name":"A","strategy_family":"TREND",
             "return_pct":0.2,"mfe_pct":0.3,"mae_pct":-0.1},
        ]
        out=summarize_strategy_rows(rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["episodes"],3)
        self.assertEqual(out[0]["closed"],2)
        self.assertAlmostEqual(out[0]["positive_pct"],50.0)
        self.assertAlmostEqual(out[0]["avg_return_pct"],0.25)

    def test_context_matrix_and_promotion_need_breadth(self):
        rows=[]
        for i in range(30):
            rows.append({
                "status":"CLOSED","strategy_id":"MR-T01","strategy_name":"A",
                "strategy_family":"TREND","strategy_lifecycle":"PAPER",
                "return_pct":1.0 if i%3 else -0.4,"mfe_pct":1.5,"mae_pct":-0.4,
                "ai_regime_trend":"RISING",
                "ai_catalyst_strength":3 if i<15 else 2,
                "ai_catalyst_identity":"VERIFIED",
                "ai_chart_state":"BREAKOUT_HOLD" if i<15 else "LEADER_TREND",
            })
        summary=summarize_strategy_rows(rows)
        matrix=build_context_matrix(rows)
        review=lifecycle_candidates(summary,matrix)
        self.assertEqual(len(matrix),2)
        self.assertEqual(review[0]["action"],"PROMOTE_CANDIDATE")
        self.assertFalse(review[0]["auto_apply"])

        concentrated=[dict(x,ai_catalyst_strength=3,ai_chart_state="BREAKOUT_HOLD") for x in rows]
        summary2=summarize_strategy_rows(concentrated)
        matrix2=build_context_matrix(concentrated)
        review2=lifecycle_candidates(summary2,matrix2)
        self.assertNotEqual(review2[0]["action"],"PROMOTE_CANDIDATE")
        self.assertIn("context_cells",review2[0]["failed_gates"])

    def test_active_weak_strategy_is_demotion_candidate(self):
        rows=[]
        for i in range(30):
            rows.append({
                "status":"CLOSED","strategy_id":"MR-X01","strategy_name":"Weak",
                "strategy_family":"TEST","strategy_lifecycle":"ACTIVE",
                "return_pct":-0.5 if i%2 else 0.1,"mfe_pct":0.2,"mae_pct":-0.8,
                "ai_regime_trend":"RISING","ai_catalyst_strength":2,
                "ai_catalyst_identity":"VERIFIED","ai_chart_state":"LEADER_TREND",
            })
        summary=summarize_strategy_rows(rows)
        matrix=build_context_matrix(rows)
        review=lifecycle_candidates(summary,matrix)
        self.assertEqual(review[0]["action"],"DEMOTE_CANDIDATE")
        self.assertFalse(review[0]["auto_apply"])

    def test_daily_review_counts_states_and_blockers(self):
        decisions=[
            {"state":"PAPER_ENTRY","strategy_id":"MR-T01","packet":{"blockers":[]}},
            {"state":"BLOCKED","strategy_id":"MR-B01","packet":{"blockers":["risk: quote stale","technical: top warning"]}},
        ]
        trades=[{"status":"CLOSED","return_pct":1.0},{"status":"CLOSED","return_pct":-0.5}]
        out=build_daily_review(decisions,trades,{"payload":{"state":"STABLE","label":"현재 규칙 유지"}})
        self.assertEqual(out["decisions"]["states"]["PAPER_ENTRY"],1)
        self.assertEqual(out["decisions"]["states"]["BLOCKED"],1)
        self.assertEqual(out["paper"]["closed"],2)
        self.assertEqual(out["feedback_state"],"STABLE")


if __name__=="__main__":
    unittest.main()
