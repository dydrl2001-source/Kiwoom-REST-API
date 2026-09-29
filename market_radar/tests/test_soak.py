import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ai_brokerage.soak import SoakPolicy, evaluate_soak


def snapshots(hours=72,count=37,ready=True,resilience="PASS",risk_fresh=True):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    step=hours/(count-1) if count>1 else 0
    return [{
        "sample_time":start+timedelta(hours=step*i),
        "ready_ok":ready,
        "schema_ok":True,
        "risk_fresh":risk_fresh,
        "resilience_status":resilience,
        "preflight_ok":True,
        "worker_error_count":0,
    } for i in range(count)]


class SoakGateTests(unittest.TestCase):
    def test_healthy_72h_window_becomes_rc_candidate(self):
        out=evaluate_soak(snapshots(),[],[{"status":"PASS","unsafe_recovery_violations":0}],
                          SoakPolicy(min_duration_hours=72,min_samples=36))
        self.assertEqual(out["stage"],"RC_CANDIDATE")
        self.assertTrue(out["rc_candidate"])
        self.assertFalse(out["live_enabled"])
        self.assertEqual(out["failed_gates"],[])

    def test_short_window_never_becomes_rc(self):
        out=evaluate_soak(snapshots(hours=24,count=37),[],[{"status":"PASS","unsafe_recovery_violations":0}])
        self.assertEqual(out["stage"],"SOAK_IN_PROGRESS")
        self.assertIn("DURATION",out["failed_gates"])

    def test_missing_samples_never_becomes_rc(self):
        out=evaluate_soak(snapshots(hours=72,count=10),[],[{"status":"PASS","unsafe_recovery_violations":0}])
        self.assertEqual(out["stage"],"SOAK_IN_PROGRESS")
        self.assertIn("SAMPLES",out["failed_gates"])

    def test_unexpected_halt_is_hard_failure(self):
        inc=[{"state":"HALT","planned":False,"trigger_codes":["DAILY_LOSS_LIMIT"]}]
        out=evaluate_soak(snapshots(),inc,[{"status":"PASS","unsafe_recovery_violations":0}])
        self.assertEqual(out["stage"],"SOAK_FAILED")
        self.assertIn("UNEXPECTED_HALTS",out["failed_gates"])

    def test_planned_manual_halt_does_not_fail_soak(self):
        inc=[{"state":"HALT","planned":True,"trigger_codes":["MANUAL_HALT"]}]
        out=evaluate_soak(snapshots(),inc,[{"status":"PASS","unsafe_recovery_violations":0}])
        self.assertEqual(out["stage"],"RC_CANDIDATE")

    def test_preflight_failure_is_hard_failure(self):
        rows=snapshots()
        rows[5]["preflight_ok"]=False
        out=evaluate_soak(rows,[],[{"status":"PASS","unsafe_recovery_violations":0}])
        self.assertEqual(out["stage"],"SOAK_FAILED")
        self.assertIn("PREFLIGHT_FAILURES",out["failed_gates"])

    def test_unsafe_recovery_is_hard_failure(self):
        out=evaluate_soak(snapshots(),[],[{"status":"PASS","unsafe_recovery_violations":1}])
        self.assertEqual(out["stage"],"SOAK_FAILED")
        self.assertIn("UNSAFE_RECOVERY",out["failed_gates"])


class SoakSourceTests(unittest.TestCase):
    def test_soak_worker_has_no_broker_order_action(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/"soak_monitor_worker.py").read_text(encoding="utf-8")
        for banned in ("send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)
        self.assertIn("RC candidate does not enable live orders",text)


if __name__=="__main__":
    unittest.main()
