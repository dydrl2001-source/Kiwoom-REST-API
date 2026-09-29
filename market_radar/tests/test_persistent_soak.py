import unittest
from pathlib import Path

class PersistentSoakSourceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]

    def test_pulse_is_one_shot_and_no_order(self):
        text=(self.root/"persistent_soak_pulse.py").read_text(encoding="utf-8")
        self.assertIn("snapshot()",text)
        self.assertIn("evaluate()",text)
        self.assertNotIn("while True",text)
        for banned in ("send_order","place_order","/api/dostk/ordr"):
            self.assertNotIn(banned,text)

    def test_pulse_requires_external_staging_db_and_token(self):
        text=(self.root/"persistent_soak_pulse.py").read_text(encoding="utf-8")
        self.assertIn('"DATABASE_URL"',text)
        self.assertIn('"DASHBOARD_TOKEN"',text)

    def test_workflow_uses_only_staging_named_secrets(self):
        path=self.root.parent/".github"/"workflows"/"persistent-staging-soak.yml"
        if path.exists():
            text=path.read_text(encoding="utf-8")
            self.assertIn("STAGING_DATABASE_URL",text)
            self.assertIn("STAGING_DASHBOARD_TOKEN",text)
            self.assertNotIn("PRODUCTION_DATABASE_URL",text)

if __name__=="__main__":
    unittest.main()
