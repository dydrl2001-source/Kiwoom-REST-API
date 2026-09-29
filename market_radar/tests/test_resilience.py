import unittest
from pathlib import Path

from ai_brokerage.resilience import (
    RecoveryPolicy,
    audit_incident_timeline,
    default_chaos_scenarios,
    next_recovery_state,
    replay_recovery_sequence,
    run_chaos_suite,
)
from ai_brokerage.risk_control import RiskControlPolicy, evaluate_kill_switch


def healthy_metrics():
    return {
        "daily_shadow_return_pct":-0.2,
        "risk_utilization_pct":60,
        "median_round_trip_is_bps":20,
        "execution_reject_pct":10,
        "book_coverage_pct":90,
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


class ChaosSuiteTests(unittest.TestCase):
    def test_default_chaos_suite_passes_all_expected_states(self):
        policy=RiskControlPolicy()
        out=run_chaos_suite(
            healthy_metrics(),
            lambda m:evaluate_kill_switch(m,policy),
            default_chaos_scenarios(),
        )
        self.assertEqual(out["status"],"PASS")
        self.assertEqual(out["scenario_count"],11)
        self.assertEqual(out["passed"],11)
        self.assertEqual(out["failed"],0)

    def test_chaos_suite_contains_hard_and_degraded_cases(self):
        states={x.expected_state for x in default_chaos_scenarios()}
        self.assertIn("HALT",states)
        self.assertIn("DEGRADED",states)


class RecoveryLatchTests(unittest.TestCase):
    def setUp(self):
        self.policy=RecoveryPolicy(healthy_streak_required=3,require_ack=True)
        self.run={"state":"RUN","allow_new_shadow_entries":True}
        self.halt={"state":"HALT","allow_new_shadow_entries":False,
                   "hard_triggers":[{"code":"DAILY_LOSS_LIMIT"}]}

    def test_halt_latches_and_creates_incident(self):
        out=next_recovery_state(None,self.halt,policy=self.policy)
        self.assertEqual(out["state"],"HALT")
        self.assertEqual(out["recovery_state"],"LATCHED")
        self.assertTrue(out["incident_id"])
        self.assertFalse(out["allow_new_shadow_entries"])

    def test_healthy_streak_without_ack_stays_halted(self):
        seq=replay_recovery_sequence(
            [self.halt,self.run,self.run,self.run],
            acknowledgements=set(),
            policy=self.policy,
        )
        self.assertEqual(seq[-1]["state"],"HALT")
        self.assertEqual(seq[-1]["recovery_state"],"ACK_REQUIRED")
        self.assertEqual(seq[-1]["healthy_streak"],3)

    def test_ack_without_required_streak_stays_halted(self):
        seq=replay_recovery_sequence(
            [self.halt,self.run],
            acknowledgements={1},
            policy=self.policy,
        )
        self.assertEqual(seq[-1]["state"],"HALT")
        self.assertEqual(seq[-1]["healthy_streak"],1)
        self.assertTrue(seq[-1]["acknowledged_at"])

    def test_ack_and_streak_recover(self):
        seq=replay_recovery_sequence(
            [self.halt,self.run,self.run,self.run],
            acknowledgements={3},
            policy=self.policy,
        )
        self.assertEqual(seq[-1]["state"],"RUN")
        self.assertEqual(seq[-1]["recovery_state"],"RECOVERED")
        self.assertTrue(seq[-1]["allow_new_shadow_entries"])

    def test_degraded_does_not_count_as_healthy(self):
        degraded={"state":"DEGRADED","allow_new_shadow_entries":True}
        seq=replay_recovery_sequence(
            [self.halt,self.run,degraded,self.run,self.run,self.run],
            acknowledgements={5},
            policy=self.policy,
        )
        self.assertEqual(seq[2]["healthy_streak"],0)
        self.assertEqual(seq[-1]["state"],"RUN")


class IncidentReplayTests(unittest.TestCase):
    def test_safe_halt_to_run_transition_passes_audit(self):
        rows=[
            {"state":"HALT","raw_state":"HALT","incident_id":"i1","healthy_streak":0,"acknowledged_at":None},
            {"state":"HALT","raw_state":"RUN","incident_id":"i1","healthy_streak":1,"acknowledged_at":None},
            {"state":"HALT","raw_state":"RUN","incident_id":"i1","healthy_streak":2,"acknowledged_at":"2026-01-01T00:01:00+00:00"},
            {"state":"RUN","raw_state":"RUN","incident_id":"i1","healthy_streak":3,"acknowledged_at":"2026-01-01T00:01:00+00:00"},
        ]
        out=audit_incident_timeline(rows,RecoveryPolicy(3,True))
        self.assertEqual(out["status"],"PASS")
        self.assertEqual(out["violations"],[])

    def test_unsafe_halt_to_run_transition_is_detected(self):
        rows=[
            {"state":"HALT","raw_state":"HALT","incident_id":"i1","healthy_streak":0,"acknowledged_at":None},
            {"state":"RUN","raw_state":"RUN","incident_id":"i1","healthy_streak":1,"acknowledged_at":None},
        ]
        out=audit_incident_timeline(rows,RecoveryPolicy(3,True))
        self.assertEqual(out["status"],"FAIL")
        self.assertEqual(out["violations"][0]["code"],"UNSAFE_RECOVERY_TRANSITION")


class ResilienceSourceTests(unittest.TestCase):
    def test_recovery_cli_has_no_force_run_or_broker_order_action(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"risk_recovery_cli.py").read_text(encoding="utf-8")
        self.assertIn("no force-run command",text)
        self.assertNotIn('add_parser("force',text)
        for banned in ("send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)

    def test_audit_worker_is_non_destructive(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"resilience_audit_worker.py").read_text(encoding="utf-8")
        self.assertIn("Non-destructive resilience audit worker",text)
        for banned in ("subprocess","os.system","docker stop","send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)

    def test_risk_worker_uses_raw_kill_to_avoid_recovery_deadlock(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"risk_control_worker.py").read_text(encoding="utf-8")
        self.assertIn('rc.get("kill_switch_raw")',text)
        self.assertIn("next_recovery_state",text)
        self.assertIn("ai_incident_events",text)

    def test_dashboard_exposes_raw_effective_and_recovery_state(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"radar_api.py").read_text(encoding="utf-8")
        self.assertIn('"kill_switch_raw":raw_kill',text)
        self.assertIn('"recovery":recovery',text)
        self.assertIn('"code":"RECOVERY_LATCH"',text)


if __name__=="__main__":
    unittest.main()
