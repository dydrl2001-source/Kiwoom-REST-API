"""Offline startup regression tests. No database, external API, or paid calls."""
from contextlib import asynccontextmanager, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class WithoutLegacyEvents(FastAPI):
    """Simulate removal of Starlette's legacy app startup registration method."""
    def __getattribute__(self, name):
        if name == "add_event_handler":
            raise AttributeError("'FastAPI' object has no attribute 'add_event_handler'")
        return super().__getattribute__(name)


class WebStartupTests(unittest.TestCase):
    def load(self, lifespan=None):
        base = types.ModuleType("radar_api")
        base.app = WithoutLegacyEvents(lifespan=lifespan)
        base.DASHBOARD_HTML_V2 = '<html><body><section id="view-research"></section></body></html>'
        base.DASHBOARD_HTML = base.DASHBOARD_HTML_V2
        base.app.add_api_route("/health", lambda: {"status": "ok", "db": "ok"})
        base.app.add_api_route("/", lambda: "old")
        engine = types.ModuleType("web_research_engine")
        engine.Config = Mock()
        engine.ResearchError = type("ResearchError", (Exception,), {})
        engine.enqueue = Mock(return_value=7)
        engine.ensure_schema = Mock()
        engine.status_payload = Mock(return_value={"config": {"gate": "READY"}})
        engine.call_model = Mock(side_effect=AssertionError("paid API must never be called"))
        spec = importlib.util.spec_from_file_location("startup_test_app", ROOT / "radar_web_app.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"radar_api": base, "web_research_engine": engine}):
            spec.loader.exec_module(module)
        return module, engine

    def setUp(self):
        env = patch.dict(os.environ, {"DASHBOARD_TOKEN": "local-test-only-token"})
        env.start()
        self.addCleanup(env.stop)
        self.headers = {"x-dashboard-token": "local-test-only-token"}

    def test_import_without_legacy_method_has_no_database_or_paid_side_effect(self):
        module, engine = self.load()
        self.assertFalse(hasattr(module.app, "add_event_handler"))
        engine.ensure_schema.assert_not_called()
        engine.call_model.assert_not_called()

    def test_lifespan_initializes_optional_storage_once(self):
        module, engine = self.load()
        with TestClient(module.app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
        engine.ensure_schema.assert_called_once()
        engine.enqueue.assert_not_called()
        engine.call_model.assert_not_called()

    def test_original_lifespan_is_preserved(self):
        events = []
        @asynccontextmanager
        async def original(app):
            events.append("enter")
            yield {"base_ready": True}
            events.append("exit")
        module, engine = self.load(original)
        with TestClient(module.app) as client:
            self.assertEqual(events, ["enter"])
            self.assertTrue(client.app_state["base_ready"])
            self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(events, ["enter", "exit"])
        engine.ensure_schema.assert_called_once()

    def test_optional_storage_failure_does_not_stop_base_app_or_log_secrets(self):
        module, engine = self.load()
        engine.ensure_schema.side_effect = RuntimeError("secret-connection-string")
        output = io.StringIO()
        with redirect_stdout(output):
            with TestClient(module.app) as client:
                self.assertEqual(client.get("/health").json(), {"status": "ok", "db": "ok"})
                self.assertEqual(client.get("/").status_code, 200)
        self.assertNotIn("secret-connection-string", output.getvalue())
        engine.call_model.assert_not_called()

    def test_root_preserves_html_and_injects_one_script(self):
        module, _ = self.load()
        with TestClient(module.app) as client:
            response = client.get("/")
        self.assertEqual(response.text.count('/assets/web-research.js'), 1)
        self.assertIn('id="view-research"', response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("local-test-only-token", response.text)

    def test_authentication_required(self):
        module, engine = self.load()
        with TestClient(module.app) as client:
            self.assertEqual(client.get("/api/web-research").status_code, 401)
            self.assertEqual(client.post("/api/web-research", json={"job_id": 1}).status_code, 401)
        engine.enqueue.assert_not_called()
        engine.status_payload.assert_not_called()

    def test_invalid_job_id_is_rejected(self):
        module, engine = self.load()
        with TestClient(module.app) as client:
            response = client.post("/api/web-research", json={"job_id": 0}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        engine.enqueue.assert_not_called()

    def test_request_enqueues_only_and_does_not_call_paid_model(self):
        module, engine = self.load()
        with TestClient(module.app) as client:
            response = client.post("/api/web-research", json={"job_id": 1}, headers=self.headers)
        self.assertEqual(response.json(), {"run_id": 7})
        engine.enqueue.assert_called_once()
        engine.call_model.assert_not_called()

    def test_storage_error_is_redacted_and_local_health_remains_available(self):
        module, engine = self.load()
        engine.status_payload.side_effect = RuntimeError("secret-connection-string")
        with TestClient(module.app) as client:
            response = client.get("/api/web-research", headers=self.headers)
            self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-connection-string", response.text)
        self.assertEqual(response.json()["detail"], "WEB_RESEARCH_STORAGE_NOT_READY")


if __name__ == "__main__":
    unittest.main()
