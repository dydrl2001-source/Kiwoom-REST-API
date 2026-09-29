import unittest
from pathlib import Path

from ai_brokerage.risk_control import (
    RiskControlPolicy,
    evaluate_kill_switch,
    evaluate_live_readiness,
    rebalance_portfolio,
)


def healthy_metrics():
    return {
        "daily_shadow_return_pct":-0.2,
        "risk_utilization_pct":60,
        "median_round_trip_is_bps":20,
        "execution_reject_pct":10,
        "book_coverage_pct":85,
        "max_portfolio_corr":0.55,
        "unknown_corr_pairs":0,
        "critical_feeds":{
            "kiwoom":{"status":"OK","age_sec":20},
            "regime":{"status":"OK","age_sec":20},
            "chart":{"status":"OK","age_sec":20},
        },
        "orderbook_feed":{"status":"OK","age_sec":15},
        "manual_halt":False,
    }


class KillSwitchTests(unittest.TestCase):
    def test_healthy_state_runs(self):
        out=evaluate_kill_switch(healthy_metrics())
        self.assertEqual(out["state"],"RUN")
        self.assertTrue(out["allow_new_shadow_entries"])
        self.assertEqual(out["hard_triggers"],[])

    def test_daily_loss_limit_halts(self):
        m=healthy_metrics();m["daily_shadow_return_pct"]=-2.1
        out=evaluate_kill_switch(m,RiskControlPolicy(max_daily_loss_pct=2.0))
        self.assertEqual(out["state"],"HALT")
        self.assertFalse(out["allow_new_shadow_entries"])
        self.assertIn("DAILY_LOSS_LIMIT",[x["code"] for x in out["hard_triggers"]])

    def test_stale_critical_feed_halts(self):
        m=healthy_metrics();m["critical_feeds"]["kiwoom"]["age_sec"]=181
        out=evaluate_kill_switch(m,RiskControlPolicy(max_critical_feed_age_sec=180))
        self.assertEqual(out["state"],"HALT")
        self.assertIn("CRITICAL_FEED_STALE",[x["code"] for x in out["hard_triggers"]])

    def test_execution_degradation_halts(self):
        m=healthy_metrics();m["median_round_trip_is_bps"]=65
        out=evaluate_kill_switch(m,RiskControlPolicy(max_median_round_trip_is_bps=60))
        self.assertEqual(out["state"],"HALT")
        self.assertIn("EXECUTION_IS_DEGRADED",[x["code"] for x in out["hard_triggers"]])

    def test_low_book_coverage_only_degrades(self):
        m=healthy_metrics();m["book_coverage_pct"]=35
        out=evaluate_kill_switch(m,RiskControlPolicy(min_book_coverage_pct=50))
        self.assertEqual(out["state"],"DEGRADED")
        self.assertTrue(out["allow_new_shadow_entries"])
        self.assertIn("BOOK_COVERAGE_LOW",[x["code"] for x in out["warnings"]])

    def test_manual_halt_is_hard_stop(self):
        m=healthy_metrics();m["manual_halt"]=True
        out=evaluate_kill_switch(m)
        self.assertEqual(out["state"],"HALT")
        self.assertIn("MANUAL_HALT",[x["code"] for x in out["hard_triggers"]])


class LiveReadinessTests(unittest.TestCase):
    def test_all_readiness_gates_can_reach_review_but_never_enable_live(self):
        policy=RiskControlPolicy(
            min_live_paper_closed=100,min_live_shadow_closed=60,min_live_book_closed=40,
            min_live_operating_days=10,min_live_book_coverage_pct=80,min_live_supported_strategies=1
        )
        kill=evaluate_kill_switch(healthy_metrics(),policy)
        metrics={
            "broker_mode":"real","paper_closed":120,"shadow_closed":70,"book_closed":50,
            "operating_days":12,"book_coverage_pct":90,"supported_strategies":2,
            "costs_configured":True,"orderbook_ok":True,"critical_feeds_ok":True,
            "allocation_snapshots":12,"live_order_path_present":False,
        }
        out=evaluate_live_readiness(metrics,kill,policy)
        self.assertEqual(out["stage"],"LIVE_READINESS_REVIEW")
        self.assertTrue(out["eligible_for_human_live_review"])
        self.assertFalse(out["live_enabled"])
        self.assertEqual(out["failed_gates"],[])

    def test_demo_mode_and_small_samples_stay_research_only(self):
        kill=evaluate_kill_switch(healthy_metrics())
        metrics={
            "broker_mode":"demo","paper_closed":10,"shadow_closed":5,"book_closed":3,
            "operating_days":2,"book_coverage_pct":30,"supported_strategies":0,
            "costs_configured":False,"orderbook_ok":False,"critical_feeds_ok":True,
            "allocation_snapshots":1,"live_order_path_present":False,
        }
        out=evaluate_live_readiness(metrics,kill)
        self.assertEqual(out["stage"],"RESEARCH_ONLY")
        self.assertFalse(out["eligible_for_human_live_review"])
        self.assertIn("BROKER_REAL_MODE",out["failed_gates"])
        self.assertIn("SHADOW_SAMPLE",out["failed_gates"])


class RebalanceTests(unittest.TestCase):
    def test_halt_proposes_exit_for_all_open_positions_and_no_adds(self):
        positions=[
            {"stock_code":"A","stock_name":"A","risk_krw":300000,"ai_state":"PAPER_ENTRY",
             "final_action":"PROMOTE_CANDIDATE_EXECUTION_ADJUSTED","priority_score":0.7},
            {"stock_code":"B","stock_name":"B","risk_krw":200000,"ai_state":"READY",
             "final_action":"EXECUTION_GATE_PENDING","priority_score":0.4},
        ]
        new=[{"stock_code":"C","allocated_risk_krw":100000,"priority_score":0.8}]
        out=rebalance_portfolio(positions,new,{"state":"HALT"})
        self.assertTrue(all(x["action"]=="EXIT_SHADOW" for x in out["actions"]))
        self.assertEqual(out["summary"]["add_review"],0)
        self.assertEqual(out["status"],"HALT_PLAN")

    def test_blocked_exits_watch_reduces_and_new_candidate_is_reviewed(self):
        positions=[
            {"stock_code":"A","risk_krw":400000,"ai_state":"BLOCKED",
             "final_action":"EXECUTION_BLOCKED","priority_score":0.2},
            {"stock_code":"B","risk_krw":300000,"ai_state":"WATCH",
             "final_action":"EXECUTION_GATE_PENDING","priority_score":0.3},
        ]
        new=[{"stock_code":"C","stock_name":"C","allocated_risk_krw":250000,
              "priority_score":0.8,"strategy_id":"MR-C","market_theme":"금융"}]
        out=rebalance_portfolio(positions,new,{"state":"RUN"})
        by={x["stock_code"]:x for x in out["actions"]}
        self.assertEqual(by["A"]["action"],"EXIT_SHADOW")
        self.assertEqual(by["B"]["action"],"REDUCE")
        self.assertAlmostEqual(by["B"]["target_risk_krw"],150000)
        self.assertEqual(by["C"]["action"],"ADD_SHADOW_REVIEW")

    def test_replacement_review_surfaces_material_priority_gap(self):
        positions=[
            {"stock_code":"A","risk_krw":300000,"ai_state":"READY",
             "final_action":"EXECUTION_GATE_PENDING","priority_score":0.2},
        ]
        new=[{"stock_code":"C","allocated_risk_krw":250000,"priority_score":0.7}]
        out=rebalance_portfolio(
            positions,new,{"state":"RUN"},
            {"replacement_priority_gap":0.15}
        )
        self.assertEqual(len(out["replacements"]),1)
        self.assertEqual(out["replacements"][0]["reduce_code"],"A")
        self.assertEqual(out["replacements"][0]["add_code"],"C")


class RiskControlSourceTests(unittest.TestCase):
    def test_workers_and_control_layer_never_place_orders(self):
        root=Path(__file__).resolve().parents[1]
        files=[
            root/"risk_control_worker.py",
            root/"capital_allocation_worker.py",
            root/"ai_brokerage"/"risk_control.py",
        ]
        for path in files:
            text=path.read_text(encoding="utf-8")
            for banned in ("send_order","place_order","/api/dostk/ordr"):
                self.assertNotIn(banned,text)

    def test_shadow_engine_requires_fresh_risk_control_by_default(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"shadow_execution_engine.py").read_text(encoding="utf-8")
        self.assertIn('RISK_CONTROL_REQUIRED=os.getenv("RISK_CONTROL_REQUIRED","1")',text)
        self.assertIn("risk_control_allows_new",text)
        self.assertIn("ai_risk_control_status",text)


if __name__=="__main__":
    unittest.main()
