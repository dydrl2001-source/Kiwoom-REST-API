import unittest

from ai_brokerage.release import evaluate_release_candidate


def evidence(**overrides):
    base={
        "soak_stage":"RC_CANDIDATE",
        "soak_rc_candidate":True,
        "risk_state":"RUN",
        "resilience_status":"PASS",
        "schema_ok":True,
        "schema_version":"2026.09.29.2",
        "required_schema_version":"2026.09.29.2",
        "live_enabled":False,
        "live_order_path_present":False,
        "ci_green_confirmed":True,
        "backup_restore_confirmed":True,
        "preflight_confirmed":True,
        "persistent_staging_confirmed":True,
        "branch_sync_confirmed":True,
    }
    base.update(overrides)
    return base


class ReleaseGateTests(unittest.TestCase):
    def test_all_evidence_can_reach_rc_ready(self):
        out=evaluate_release_candidate(evidence())
        self.assertEqual(out["stage"],"RC_READY")
        self.assertTrue(out["rc_ready"])
        self.assertFalse(out["live_enabled"])
        self.assertEqual(out["failed_gates"],[])

    def test_soak_in_progress_blocks_release(self):
        out=evaluate_release_candidate(evidence(soak_stage="SOAK_IN_PROGRESS",soak_rc_candidate=False))
        self.assertEqual(out["stage"],"RC_BLOCKED")
        self.assertIn("SOAK_RC_CANDIDATE",out["failed_gates"])

    def test_persistent_staging_is_required(self):
        out=evaluate_release_candidate(evidence(persistent_staging_confirmed=False))
        self.assertIn("PERSISTENT_STAGING",out["failed_gates"])
        self.assertFalse(out["rc_ready"])

    def test_live_enabled_can_never_pass_release_gate(self):
        out=evaluate_release_candidate(evidence(live_enabled=True))
        self.assertIn("LIVE_DISABLED",out["failed_gates"])
        self.assertEqual(out["stage"],"RC_BLOCKED")

    def test_live_order_path_presence_blocks_release(self):
        out=evaluate_release_candidate(evidence(live_order_path_present=True))
        self.assertIn("NO_LIVE_ORDER_PATH",out["failed_gates"])

    def test_risk_or_resilience_failure_blocks_release(self):
        out=evaluate_release_candidate(evidence(risk_state="DEGRADED",resilience_status="FAIL"))
        self.assertIn("RISK_CONTROL_RUN",out["failed_gates"])
        self.assertIn("RESILIENCE_PASS",out["failed_gates"])


if __name__=="__main__":
    unittest.main()
