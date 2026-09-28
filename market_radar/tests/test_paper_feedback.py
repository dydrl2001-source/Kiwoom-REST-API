import os,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("DATABASE_URL","")

import paper_feedback_engine as fb

def row(ret=0.5,mfe=1.2,mae=-0.4,score=75,ptype="추세·돌파",reason="후보 이탈"):
    return {
        "status":"CLOSED","return_pct":ret,"mfe_pct":mfe,"mae_pct":mae,
        "entry_score":score,"primary_type":ptype,"exit_reason":reason
    }

class FeedbackMathTests(unittest.TestCase):
    def test_small_sample_never_changes_rule(self):
        out=fb.analyze([row() for _ in range(5)])
        self.assertEqual(out["state"],"SAMPLE_BUILDING")
        self.assertEqual(out["checks"][0]["status"],"SAMPLE_BUILDING")
        self.assertIn("변경하지 않음",out["checks"][0]["message"])

    def test_type_groups_preserve_sample_gate(self):
        rows=[row(ptype="추세·돌파") for _ in range(12)]
        out=fb.analyze(rows)
        g=next(x for x in out["types"] if x["key"]=="추세·돌파")
        self.assertTrue(g["small_sample"])
        self.assertEqual(g["verdict"],"SAMPLE_BUILDING")

    def test_low_score_weakness_can_be_review_candidate(self):
        rows=[]
        for _ in range(15):
            rows.append(row(ret=-0.3,mfe=0.4,mae=-0.8,score=72))
        for _ in range(20):
            rows.append(row(ret=0.8,mfe=1.5,mae=-0.3,score=78))
        out=fb.analyze(rows)
        check=next(x for x in out["checks"] if x["rule"]=="진입 관찰도")
        self.assertEqual(check["status"],"REVIEW_CANDIDATE")
        self.assertIn("70→75",check["message"])

    def test_giveback_rate_is_detected(self):
        rows=[row(ret=-0.1,mfe=1.5,mae=-0.4,score=80) for _ in range(30)]
        out=fb.analyze(rows)
        self.assertGreaterEqual(out["overall"]["giveback_pct"],30)
        self.assertTrue(any(x["rule"]=="되돌림 관리" for x in out["checks"]))

    def test_exit_reason_buckets(self):
        rows=[
            row(reason="후보 이탈"),
            row(reason="관찰도 44<55"),
            row(reason="전고 돌파 실패"),
            row(reason="고점 경계 강화 76"),
            row(reason="30분 관찰 종료"),
        ]
        out=fb.analyze(rows)
        names={x["reason"] for x in out["exit_reasons"]}
        self.assertTrue({"후보 이탈","관찰도 하락","차트 훼손","고점 경계","시간 종료"}.issubset(names))

class FeedbackSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(ROOT/"paper_feedback_engine.py").read_text(encoding="utf-8")
        cls.ui=(ROOT/"radar_ui_v2.py").read_text(encoding="utf-8")
        cls.api=(ROOT/"radar_api.py").read_text(encoding="utf-8")

    def test_feedback_never_auto_applies_settings_or_orders(self):
        for banned in ("os.environ[","set_variables","send_order","place_order","/api/dostk/ordr",
                       "api.openai.com","web_research_engine","requests."):
            self.assertNotIn(banned,self.text)
        self.assertIn("auto-change disabled",self.text)

    def test_feedback_home_panel_exists(self):
        self.assertIn("homePaperFeedback",self.ui)
        self.assertIn("renderPaperFeedback",self.ui)
        self.assertIn("paper_feedback",self.api)

    def test_explicit_sample_gates_exist(self):
        self.assertIn("MIN_TYPE_SAMPLES",self.text)
        self.assertIn("MIN_RULE_SAMPLES",self.text)

if __name__=="__main__":
    unittest.main()
