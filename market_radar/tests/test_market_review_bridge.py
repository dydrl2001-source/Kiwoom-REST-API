import unittest
from datetime import datetime, timezone

from market_review_bridge import audit_long_plan, reconstruct_radar_summary, source_family
from market_review_journal import decision_hash


class ReviewBridgeUnitTests(unittest.TestCase):
    def test_geubdeung_family_collapses_siblings(self):
        self.assertEqual(source_family("주식 급등일보"), "급등일보")
        self.assertEqual(source_family("급등일보 미국주식"), "급등일보")

    def test_reconstructed_summary_counts_independent_families(self):
        messages = [
            {"channel_name": "주식 급등일보", "source_family": "급등일보",
             "text": "삼성전자 005930 반도체 HBM"},
            {"channel_name": "급등일보 미국주식", "source_family": "급등일보",
             "text": "삼성전자 005930 반도체 HBM"},
            {"channel_name": "독립채널", "source_family": "독립채널",
             "text": "005930 HBM 반도체"},
        ]
        out = reconstruct_radar_summary(messages)
        hbm = next(x for x in out["themes"] if x["theme"] == "반도체/HBM")
        ticker = next(x for x in out["tickers"] if x["ticker"] == "005930")
        self.assertEqual(hbm["messages"], 3)
        self.assertEqual(hbm["families"], 2)
        self.assertEqual(ticker["families"], 2)
        self.assertEqual(out["status"], "RECONSTRUCTED_FROM_TELEGRAM_MESSAGES")

    def test_long_plan_audit_uses_original_stop_for_r(self):
        d = {
            "trigger_spec": {"kind": "ABOVE", "price": 100},
            "theoretical_entry_krw": 101,
            "invalidation_stop_krw": 96,
            "exit_spec": {"kind": "STOP_OR_CLOSE"},
        }
        bars = [
            {"time": datetime(2026, 10, 6, 0, 20, tzinfo=timezone.utc),
             "open": 99, "high": 100, "low": 98, "close": 100, "volume": 1},
            {"time": datetime(2026, 10, 6, 0, 21, tzinfo=timezone.utc),
             "open": 101, "high": 111, "low": 100, "close": 108, "volume": 1},
            {"time": datetime(2026, 10, 6, 6, 30, tzinfo=timezone.utc),
             "open": 108, "high": 109, "low": 106, "close": 106, "volume": 1},
        ]
        out = audit_long_plan(d, bars)
        self.assertTrue(out["trigger_fired"])
        self.assertAlmostEqual(out["mfe_r"], 2.0)
        self.assertAlmostEqual(out["mae_r"], -0.6)
        self.assertAlmostEqual(out["close_r"], 1.0)
        self.assertAlmostEqual(out["system_r"], 1.0)
        self.assertEqual(out["system_exit_reason"], "SESSION_CLOSE")
        self.assertFalse(out["stop_hit"])

    def test_decision_hash_is_stable(self):
        d = {
            "session_date": "2026-10-06",
            "issued_at": "2026-10-06T09:20:00+09:00",
            "stage": "TRADE_CARD",
            "source_kind": "A_GRADE_ENGINE",
            "stock_code": "005930",
            "grade": "A",
            "watch_tier": "FOCUS",
            "side": "LONG",
            "trigger_spec": {"kind": "ABOVE", "price": 100},
            "exit_spec": {"kind": "STOP_OR_CLOSE"},
            "evidence": {"x": 1},
        }
        self.assertEqual(decision_hash(d), decision_hash(dict(d)))


if __name__ == "__main__":
    unittest.main()
