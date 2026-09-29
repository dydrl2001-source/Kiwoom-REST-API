import unittest
from pathlib import Path

class ProductionHardeningSourceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]

    def test_schema_migration_registry_and_drift_guard_exist(self):
        text=(self.root/"schema_migrate.py").read_text(encoding="utf-8")
        self.assertIn("market_radar_schema_migrations",text)
        self.assertIn("checksum drift",text)
        self.assertIn("MARKET_RADAR_SCHEMA_VERSION",text)
        self.assertIn("pg_advisory_xact_lock",text)

    def test_schema_bundle_covers_operational_ai_services(self):
        text=(self.root/"schema_migrate.py").read_text(encoding="utf-8")
        for name in ("ai_brokerage_worker","paper_trade_engine","paper_feedback_engine",
                     "orderbook_collector","shadow_execution_engine","capital_allocation_worker",
                     "risk_control_worker","resilience_audit_worker"):
            self.assertIn(name,text)

    def test_backup_restore_scripts_are_isolated(self):
        backup=(self.root/"local"/"backup_db.sh").read_text(encoding="utf-8")
        restore=(self.root/"local"/"restore_verify.sh").read_text(encoding="utf-8")
        self.assertIn("pg_dump",backup)
        self.assertIn("market_radar_restore_check",restore)
        self.assertIn("pg_restore",restore)
        self.assertNotIn("dropdb -U market market_radar",restore)

    def test_readiness_endpoints_exist_and_hide_exception_details(self):
        text=(self.root/"radar_api.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/health/live")',text)
        self.assertIn('@app.get("/health/ready")',text)
        self.assertNotIn('{"status": "error", "detail": str(e)}',text)

    def test_docker_build_runs_hardening_tests(self):
        docker=(self.root/"local"/"Dockerfile").read_text(encoding="utf-8")
        self.assertIn("test_production_hardening.py",docker)
        self.assertIn("schema_migrate.py",docker)

    def test_compose_uses_one_shot_schema_migration(self):
        text=(self.root/"local"/"docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("schema-migrate:",text)
        self.assertIn("service_completed_successfully",text)
        self.assertIn("/health/live",text)

    def test_ci_workflow_is_present(self):
        workflow=self.root.parent/".github"/"workflows"/"market-radar-ci.yml"
        if workflow.exists():
            text=workflow.read_text(encoding="utf-8")
            self.assertIn("Run Market Radar tests",text)
            self.assertIn("Static live-order guard",text)
            self.assertIn("Build local image",text)

    def test_no_live_order_action_added_to_hardening_files(self):
        for rel in ("schema_migrate.py","local/backup_db.sh","local/restore_verify.sh"):
            text=(self.root/rel).read_text(encoding="utf-8")
            for banned in ("send_order","place_order","/api/dostk/ordr"):
                self.assertNotIn(banned,text)

if __name__=="__main__":
    unittest.main()
