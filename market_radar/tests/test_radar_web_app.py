"""Route isolation/authentication tests using a stand-in for the original app."""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class WebAppTests(unittest.TestCase):
    def setUp(self):
        base = types.ModuleType("radar_api")
        base.app = FastAPI()
        base.DASHBOARD_HTML_V2 = '<html><body><section id="view-research"></section></body></html>'
        base.DASHBOARD_HTML = base.DASHBOARD_HTML_V2
        base.app.add_api_route("/health", lambda: {"status":"ok","db":"ok"})
        base.app.add_api_route("/", lambda: "old")
        spec = importlib.util.spec_from_file_location("isolated_radar_web_app", ROOT / "radar_web_app.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"radar_api":base}): spec.loader.exec_module(self.module)
        self.client = TestClient(self.module.app)
        self.env = patch.dict(os.environ, {"DASHBOARD_TOKEN":"test-dashboard-token"})
        self.env.start()

    def tearDown(self): self.env.stop()

    def test_base_health_and_root_preserved(self):
        self.assertEqual(self.client.get("/health").json(), {"status":"ok","db":"ok"})
        html = self.client.get("/").text
        self.assertIn('/assets/web-research.js', html)
        self.assertNotIn("test-dashboard-token", html)
        self.assertEqual(self.client.get("/").headers["cache-control"],"no-store")

    def test_authentication_required(self):
        self.assertEqual(self.client.get("/api/web-research").status_code,401)
        self.assertEqual(self.client.post("/api/web-research",json={"job_id":1}).status_code,401)

    def test_module_failure_does_not_break_base_health(self):
        with patch.object(self.module,"status_payload",side_effect=RuntimeError("secret dsn")):
            r=self.client.get("/api/web-research",headers={"x-dashboard-token":"test-dashboard-token"})
        self.assertEqual(r.status_code,503)
        self.assertNotIn("secret dsn",r.text)
        self.assertEqual(self.client.get("/health").status_code,200)

    def test_manual_queue_does_not_directly_call_model(self):
        with patch.object(self.module,"enqueue",return_value=7) as queue:
            r=self.client.post("/api/web-research",json={"job_id":1},headers={"x-dashboard-token":"test-dashboard-token"})
        self.assertEqual(r.json(),{"run_id":7})
        self.assertEqual(queue.call_count,1)


if __name__=="__main__": unittest.main()
