import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class CandidateTrackerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(ROOT/'candidate_tracker.py').read_text(encoding='utf-8')

    def test_tracker_uses_unenriched_snapshot(self):
        self.assertIn('desk_payload(include_tracking=False)', self.text)

    def test_tracker_has_no_paid_model_or_order_calls(self):
        for banned in ('call_model(', 'web_research_engine', 'requests.', 'place_order', 'send_order'):
            self.assertNotIn(banned, self.text)

    def test_tracker_deduplicates_same_market_sample(self):
        self.assertIn('PRIMARY KEY(snapshot_time,stock_code)', self.text)
        self.assertIn('ON CONFLICT(snapshot_time,stock_code) DO NOTHING', self.text)

    def test_history_retention_is_bounded(self):
        self.assertIn("interval '14 days'", self.text)

if __name__=='__main__':
    unittest.main()
