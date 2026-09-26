"""Offline tests: no secrets, paid API calls or running database required."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import web_research_engine as w


class WebResearchTests(unittest.TestCase):
    def ready(self, **extra):
        return w.Config.read({"WEB_RESEARCH_ENABLED":"1", "OPENAI_API_KEY":"test-private-key",
                              "WEB_RESEARCH_MODEL":"test-model", **extra})

    def test_disabled_is_default(self):
        self.assertEqual(w.Config.read({}).gate(), "DISABLED")
        self.assertEqual(w.Config.read({"OPENAI_API_KEY":"x"}).gate(), "DISABLED")

    def test_key_and_model_are_both_required(self):
        self.assertEqual(w.Config.read({"WEB_RESEARCH_ENABLED":"1"}).gate(), "WAITING_FOR_KEY")
        self.assertEqual(w.Config.read({"WEB_RESEARCH_ENABLED":"1", "OPENAI_API_KEY":"x"}).gate(), "WAITING_FOR_MODEL")
        self.assertEqual(self.ready().gate(), "READY")

    def test_public_config_has_no_key(self):
        self.assertNotIn("test-private-key", json.dumps(self.ready().public()))
        self.assertFalse(self.ready().automatic)

    def test_safe_cost_bounds(self):
        c = self.ready(WEB_RESEARCH_DAILY_LIMIT="9000", WEB_RESEARCH_HOURLY_LIMIT="0",
                       WEB_RESEARCH_MAX_TOOL_CALLS="99", WEB_RESEARCH_MAX_OUTPUT_TOKENS="broken")
        self.assertEqual((c.daily_limit,c.hourly_limit,c.tool_calls,c.output_tokens),(50,1,5,3000))

    def test_disabled_request_fails_before_network(self):
        with self.assertRaisesRegex(w.ResearchError, "DISABLED"):
            w.make_request({}, w.Config.read({}))

    def test_outbound_context_strips_private_fields(self):
        payload=w.make_request({"stock_name":"테스트기업", "stock_code":"123456",
                               "TELEGRAM_SESSION":"never-send", "channel":"private", "DATABASE_URL":"dsn",
                               "public_news_leads":[{"title":"보도", "url":"https://example.com/a", "secret":"no"}]}, self.ready())
        encoded=json.dumps(payload,ensure_ascii=False)
        for secret in ("test-private-key", "never-send", "private", "dsn", '"secret"'):
            self.assertNotIn(secret, encoded)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tool_choice"],"required")
        self.assertEqual(payload["tools"][0]["type"],"web_search")

    def test_urls_block_unsafe_targets(self):
        for url in ("javascript:alert(1)","file:///etc/passwd","https://localhost/a","http://127.0.0.1/x",
                    "http://10.0.0.1/", "https://user:secret@example.com/", "https://example.com:22/x",
                    "https://abc.local/a", "https://exa\\mple.com", "https://example.com/\n"):
            with self.subTest(url=url): self.assertIsNone(w.safe_url(url))
        self.assertEqual(w.safe_url("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1"),"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1")

    def test_auto_needs_source_price_time_not_ingestion(self):
        now=datetime.now(timezone.utc)
        self.assertFalse(w.fresh_for_auto({"market_collected_at":now.isoformat()},now))
        self.assertFalse(w.fresh_for_auto({"price_bar_at":(now-timedelta(days=1)).isoformat()},now))
        self.assertFalse(w.fresh_for_auto({"price_bar_at":(now+timedelta(minutes=1)).isoformat()},now))
        self.assertTrue(w.fresh_for_auto({"price_bar_at":(now-timedelta(minutes=3)).isoformat()},now))

    def test_fingerprint_dedupes_within_hour(self):
        a={"stock_code":"123456", "requested_at":"2026-09-27T01:01:00+00:00"}
        b={**a,"requested_at":"2026-09-27T01:55:00+00:00"}
        self.assertEqual(w.fingerprint(a),w.fingerprint(b))
        self.assertNotEqual(w.fingerprint(a),w.fingerprint({**a,"requested_at":"2026-09-27T02:00:00+00:00"}))

    def response(self, annotation=True, search=True):
        output=[]
        if search: output.append({"type":"web_search_call","status":"completed","action":{"type":"search"}})
        part={"type":"output_text","text":"🔎 공급계약 확인 [1]"}
        if annotation: part["annotations"]=[{"type":"url_citation","start_index":10,"end_index":13,
                                             "url":"https://example.com/a","title":"공시"}]
        output.append({"type":"message","content":[part]})
        return {"status":"completed","output":output,"usage":{"output_tokens":20}}

    def test_missing_search_or_citations_is_not_completed_research(self):
        self.assertEqual(w.parse_response(self.response(False))["evidence_status"],"EVIDENCE_INCOMPLETE")
        self.assertEqual(w.parse_response(self.response(search=False))["evidence_status"],"EVIDENCE_INCOMPLETE")

    def test_citations_are_preserved_with_unicode_offsets(self):
        r=w.parse_response(self.response())
        self.assertEqual(r["evidence_status"],"CITED_REPORT")
        self.assertEqual(r["citations"][0]["url"],"https://example.com/a")
        self.assertNotIn("confidence",r)

    def test_invalid_provider_response_rejected(self):
        for obj in ([], {"status":"incomplete"}, {"status":"completed","output":[]}):
            with self.subTest(obj=obj), self.assertRaises(w.ResearchError): w.parse_response(obj)

    def test_multiple_messages_adjust_citation_offsets(self):
        response=self.response()
        response["output"].insert(1,{"type":"message","content":[{"type":"output_text","text":"앞문장"}]})
        parsed=w.parse_response(response)
        self.assertEqual(parsed["citations"][0]["start"],15)

    def test_schema_independent_from_other_worker_tables(self):
        self.assertNotIn("REFERENCES research_jobs", w.SCHEMA)
        self.assertIn("request_key TEXT UNIQUE",w.SCHEMA)

    def test_new_ui_contains_no_inline_handlers(self):
        js=(ROOT/"web_research_ui.js").read_text()
        self.assertNotIn("onclick=",js)
        self.assertNotIn(".innerHTML",js)
        self.assertIn('Array.from(report.text',js)


if __name__=="__main__": unittest.main()
