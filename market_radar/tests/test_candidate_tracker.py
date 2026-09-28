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

    def test_prospective_episode_tables_exist(self):
        self.assertIn('radar_candidate_episodes', self.text)
        self.assertIn('radar_candidate_outcomes', self.text)
        self.assertIn('return_5m_pct', self.text)
        self.assertIn('return_15m_pct', self.text)
        self.assertIn('return_30m_pct', self.text)

    def test_journal_uses_observed_flow_quotes(self):
        self.assertIn('FROM radar_flow_quotes', self.text)
        self.assertIn('MAX_HORIZON_DELAY_SECONDS', self.text)

    def test_episode_is_not_fill_simulation(self):
        self.assertIn('not fills', self.text.lower())
        for banned in ('commission', 'slippage_model', 'fill_price_model'):
            self.assertNotIn(banned, self.text)

    def test_history_retention_is_bounded(self):
        self.assertIn("interval '14 days'", self.text)

if __name__=='__main__':
    unittest.main()
