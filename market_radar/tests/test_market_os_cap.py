import sys,unittest
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import flow_core as fc

NOW=datetime(2026,9,28,1,30,tzinfo=timezone.utc)


class MarketOSCapValidationTests(unittest.TestCase):
    def test_ka10099_listed_shares_can_validate_cap(self):
        q=fc.quote({
            'stk_cd':'005930_AL','dt':'20260928','cntr_tm':'103000',
            'cur_prc':'80000','low_pric':'79000','high_pric':'81000',
            'trde_qty':'1000000','trde_prica':'80000',
            # Deliberately ambiguous/wrong detail share reference.
            'stkcnt':'5919638','mac':'47357'
        },NOW,listed_shares=59_196_380)
        self.assertEqual(q['cap_krw'],4_735_700_000_000)
        self.assertEqual(q['cap_scale'],100_000_000)
        self.assertNotIn('CAP_REFERENCE_MISMATCH',q['quality_flags'])

    def test_cap_stays_unresolved_without_reconciling_reference(self):
        q=fc.quote({
            'stk_cd':'005930_AL','dt':'20260928','cntr_tm':'103000',
            'cur_prc':'80000','low_pric':'79000','high_pric':'81000',
            'trde_qty':'1000000','trde_prica':'80000',
            'stkcnt':'10','mac':'9999999'
        },NOW,listed_shares=11)
        self.assertIsNone(q['cap_krw'])
        self.assertIn('CAP_REFERENCE_MISMATCH',q['quality_flags'])


if __name__=='__main__':
    unittest.main()
