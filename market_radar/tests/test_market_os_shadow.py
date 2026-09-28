import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_shadow as shadow


class ShadowRulePureTests(unittest.TestCase):
    def snapshot(self,**overrides):
        x={
            'watch_tier':'PREP','market_stance':'DEFENSIVE',
            'trigger_state':'BREAKOUT_TEST','session_bucket':'MORNING',
            'catalyst_grade':'B','setup_score':85,
            'micro_strength':130,'micro_buy_share_15s':.70,
            'micro_tick_count_15s':12,'micro_gap_count_15s':0,
        }
        x.update(overrides)
        return x

    def test_dimensions_match_registered_learning_language(self):
        d=shadow.dimensions(self.snapshot())
        self.assertEqual(d['STANCE_SETUP_TRIGGER'],
                         'DEFENSIVE | 80-100 | BREAKOUT_TEST')
        self.assertEqual(d['STANCE_SETUP_TRIGGER_MICRO'],
                         'DEFENSIVE | 80-100 | BREAKOUT_TEST | STRONG_CONFIRM')

    def test_gap_micro_never_matches_micro_rule(self):
        x=self.snapshot(micro_gap_count_15s=1)
        self.assertFalse(shadow.matches(
            x,'MICRO_STATE','STRONG_CONFIRM'
        ))

    def test_promote_and_suppress_move_only_one_review_tier(self):
        self.assertEqual(shadow.shift_tier('DISCOVER','PROMOTE_ONE_TIER'),'PREP')
        self.assertEqual(shadow.shift_tier('PREP','PROMOTE_ONE_TIER'),'FOCUS')
        self.assertEqual(shadow.shift_tier('FOCUS','PROMOTE_ONE_TIER'),'FOCUS')
        self.assertEqual(shadow.shift_tier('FOCUS','SUPPRESS_ONE_TIER'),'PREP')
        self.assertEqual(shadow.shift_tier('PREP','SUPPRESS_ONE_TIER'),'DISCOVER')

    def test_shadow_never_overrides_structural_block(self):
        self.assertEqual(shadow.shift_tier('BLOCKED','PROMOTE_ONE_TIER'),'BLOCKED')
        self.assertEqual(shadow.shift_tier('BLOCKED','SUPPRESS_ONE_TIER'),'BLOCKED')

    def test_evaluate_changes_only_matching_condition(self):
        rule={
            'segment_type':'STANCE_SETUP_TRIGGER',
            'segment_value':'DEFENSIVE | 80-100 | BREAKOUT_TEST',
            'action':'PROMOTE_ONE_TIER',
        }
        y=shadow.evaluate(self.snapshot(),rule)
        self.assertTrue(y['matched'])
        self.assertEqual(y['control_tier'],'PREP')
        self.assertEqual(y['challenger_tier'],'FOCUS')
        z=shadow.evaluate(self.snapshot(market_stance='EXPANDABLE'),rule)
        self.assertFalse(z['matched'])
        self.assertEqual(z['control_tier'],z['challenger_tier'])

    def test_experiment_summary_compares_cohort_composition_not_prices(self):
        rows=[
            {'horizon':'30m','stock_code':'A','trade_day':'2026-09-28',
             'control_tier':'DISCOVER','challenger_tier':'PREP',
             'return_pct':2.0,'mfe_pct':2.5,'mae_pct':-.2},
            {'horizon':'30m','stock_code':'B','trade_day':'2026-09-28',
             'control_tier':'PREP','challenger_tier':'PREP',
             'return_pct':-1.0,'mfe_pct':.2,'mae_pct':-1.5},
        ]
        s=next(x for x in shadow.experiment_summaries(rows)
               if x['horizon']=='30m' and x['cohort']=='REVIEW')
        self.assertEqual(s['control']['samples'],1)
        self.assertEqual(s['challenger']['samples'],2)
        self.assertAlmostEqual(s['control']['avg_return_pct'],-1.0)
        self.assertAlmostEqual(s['challenger']['avg_return_pct'],.5)
        self.assertAlmostEqual(s['delta_avg_return_pct'],1.5)
        self.assertEqual(s['membership_changes'],1)


if __name__=='__main__':
    unittest.main()
