import sys,unittest
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_learning as learn


class LearningPureTests(unittest.TestCase):
    def test_session_buckets(self):
        # UTC -> KST
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,0,5,tzinfo=timezone.utc)),'OPEN_20')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,0,40,tzinfo=timezone.utc)),'MORNING')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,5,10,tzinfo=timezone.utc)),'AFTERNOON')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,6,5,tzinfo=timezone.utc)),'CLOSE')

    def test_setup_bucket(self):
        self.assertEqual(learn._bucket_setup(85),'80-100')
        self.assertEqual(learn._bucket_setup(70),'65-79')
        self.assertEqual(learn._bucket_setup(55),'50-64')
        self.assertEqual(learn._bucket_setup(30),'0-49')

    def test_aggregate_uses_observed_outcomes_only(self):
        a=learn._aggregate([
            {'return_pct':1.0,'mfe_pct':2.0,'mae_pct':-0.5},
            {'return_pct':-0.5,'mfe_pct':0.7,'mae_pct':-1.2},
            {'return_pct':None,'mfe_pct':99,'mae_pct':-99},
        ])
        self.assertEqual(a['samples'],2)
        self.assertAlmostEqual(a['avg_return_pct'],0.25)
        self.assertAlmostEqual(a['median_return_pct'],0.25)
        self.assertAlmostEqual(a['positive_rate'],0.5)
        self.assertAlmostEqual(a['avg_mfe_pct'],1.35)
        self.assertAlmostEqual(a['avg_mae_pct'],-0.85)

    def test_nonfinite_values_are_rejected(self):
        self.assertIsNone(learn.safe_num('NaN'))
        self.assertIsNone(learn.safe_num('inf'))
        self.assertIsNone(learn.safe_num(None))


if __name__=='__main__':
    unittest.main()
