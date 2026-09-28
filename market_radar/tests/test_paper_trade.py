import os,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("DATABASE_URL","")

import paper_trade_engine as paper

class PaperTradeMathTests(unittest.TestCase):
    def test_pct(self):
        self.assertAlmostEqual(paper.pct(101,100),1.0)
        self.assertAlmostEqual(paper.pct(97,100),-3.0)
        self.assertIsNone(paper.pct(None,100))
        self.assertIsNone(paper.pct(100,0))

    def test_defaults_are_bounded_observation_rules(self):
        self.assertGreaterEqual(paper.ENTRY_SCORE,40)
        self.assertLessEqual(paper.ENTRY_SCORE,100)
        self.assertGreaterEqual(paper.ENTRY_SURVIVE_SEC,30)
        self.assertGreaterEqual(paper.MAX_HOLD_MIN,5)
        self.assertGreaterEqual(paper.MAX_OPEN,1)
        self.assertEqual(paper.RULE_VERSION,"paper-v1-observation")

class PaperTradeSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(ROOT/"paper_trade_engine.py").read_text(encoding="utf-8")
        cls.ui=(ROOT/"radar_ui_v2.py").read_text(encoding="utf-8")
        cls.api=(ROOT/"radar_api.py").read_text(encoding="utf-8")

    def test_no_real_order_or_ai_provider_calls(self):
        for banned in ("send_order","place_order","/api/dostk/ordr","web_research_engine","api.openai.com","requests."):
            self.assertNotIn(banned,self.text)

    def test_one_normalized_unit_no_position_sizing(self):
        self.assertIn("one normalized unit",self.text)
        for banned in ("quantity INTEGER","notional_krw","allocation_pct","portfolio_weight"):
            self.assertNotIn(banned,self.text)

    def test_entry_and_exit_are_auditable(self):
        self.assertIn("PAPER_ENTRY",self.text)
        self.assertIn("PAPER_EXIT",self.text)
        self.assertIn("후보 이탈",self.text)
        self.assertIn("TREND_DAMAGE",self.text)
        self.assertIn("BREAKOUT_FAIL",self.text)
        self.assertIn("TOP_WARNING",self.text)
        self.assertIn("분 관찰 종료",self.text)

    def test_fresh_quote_required_for_entry(self):
        self.assertIn("if not q or not q[\"fresh\"]:continue",self.text)
        self.assertIn("QUOTE_FRESH_SEC",self.text)

    def test_home_panel_exists(self):
        self.assertIn("Paper Lab · 자동 가상매매",self.ui)
        self.assertIn("homePaperLab",self.ui)
        self.assertIn("renderPaperLab",self.ui)
        self.assertIn("paper_lab",self.api)

    def test_ui_states_no_real_orders(self):
        self.assertIn("실계좌 주문 없음",self.ui)
        self.assertIn("실계좌 미연결",self.ui)

if __name__=="__main__":
    unittest.main()
