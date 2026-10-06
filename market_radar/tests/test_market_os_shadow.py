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


    def summary_cell(self,horizon='30m',cohort='REVIEW',changes=12,
                     cavg=.20,havg=.55,cpos=.50,hpos=.58,cmae=-1.0,hmae=-.7,
                     n=50,days=7,stocks=10):
        return {
            'horizon':horizon,'cohort':cohort,'membership_changes':changes,
            'control':{'samples':n,'distinct_stocks':stocks,'distinct_days':days,
                       'avg_return_pct':cavg,'median_return_pct':cavg,
                       'positive_rate':cpos,'avg_mfe_pct':1.0,'avg_mae_pct':cmae},
            'challenger':{'samples':n,'distinct_stocks':stocks,'distinct_days':days,
                          'avg_return_pct':havg,'median_return_pct':havg,
                          'positive_rate':hpos,'avg_mfe_pct':1.2,'avg_mae_pct':hmae},
            'delta_avg_return_pct':havg-cavg,
            'delta_positive_rate_pp':(hpos-cpos)*100,
            'delta_mae_pct':hmae-cmae,
        }

    def test_decision_gate_collects_before_30m_is_comparable(self):
        weak=self.summary_cell(n=8,days=1,stocks=2,changes=2)
        d=shadow.shadow_decision(
            {'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST'},
            [weak],[]
        )
        self.assertEqual(d['state'],'COLLECTING')
        self.assertFalse(d['review_eligible'])

    def test_decision_gate_rejects_consistent_harm(self):
        bad30=self.summary_cell(cavg=.5,havg=.1,cpos=.60,hpos=.48,cmae=-.5,hmae=-1.0)
        badc=self.summary_cell(horizon='close',cavg=.6,havg=.1,cpos=.62,hpos=.48,cmae=-.6,hmae=-1.1)
        d=shadow.shadow_decision(
            {'segment_type':'STANCE_TRIGGER','segment_value':'DEFENSIVE | BREAKOUT_TEST'},
            [bad30,badc],[]
        )
        self.assertEqual(d['state'],'REJECT')

    def test_decision_gate_accept_candidate_requires_time_and_stance_replication(self):
        overall=[
            self.summary_cell('30m','REVIEW'),
            self.summary_cell('close','REVIEW',cavg=.10,havg=.45,cpos=.50,hpos=.58,cmae=-1.0,hmae=-.7),
        ]
        slices=[]
        for window in ('EARLY','RECENT'):
            for h in ('30m','close'):
                cell=self.summary_cell(h,'REVIEW',changes=10,n=40,days=6,stocks=8)
                slices.append({'scope_type':'WINDOW','scope_value':window,**cell})
        for stance in ('EXPANDABLE','SELECTIVE'):
            cell=self.summary_cell('30m','REVIEW',changes=7,n=25,days=4,stocks=6)
            slices.append({'scope_type':'STANCE','scope_value':stance,**cell})
        d=shadow.shadow_decision(
            {'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST'},
            overall,slices
        )
        self.assertEqual(d['state'],'ACCEPT_CANDIDATE')
        self.assertTrue(d['review_eligible'])

    def test_decision_gate_nonstance_rule_waits_for_second_stance(self):
        overall=[
            self.summary_cell('30m','REVIEW'),
            self.summary_cell('close','REVIEW'),
        ]
        slices=[]
        for window in ('EARLY','RECENT'):
            for h in ('30m','close'):
                cell=self.summary_cell(h,'REVIEW',changes=10,n=40,days=3,stocks=8)
                slices.append({'scope_type':'WINDOW','scope_value':window,**cell})
        cell=self.summary_cell('30m','REVIEW',changes=7,n=25,days=4,stocks=6)
        slices.append({'scope_type':'STANCE','scope_value':'SELECTIVE',**cell})
        d=shadow.shadow_decision(
            {'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST'},
            overall,slices
        )
        self.assertEqual(d['state'],'MORE_DATA')
        self.assertIn('MULTI_STANCE_REPLICATION_PENDING',d['reason_codes'])

    def test_decision_gate_stance_scoped_rule_needs_target_stance_only(self):
        overall=[
            self.summary_cell('30m','REVIEW'),
            self.summary_cell('close','REVIEW'),
        ]
        slices=[]
        for window in ('EARLY','RECENT'):
            for h in ('30m','close'):
                cell=self.summary_cell(h,'REVIEW',changes=10,n=40,days=3,stocks=8)
                slices.append({'scope_type':'WINDOW','scope_value':window,**cell})
        cell=self.summary_cell('30m','REVIEW',changes=7,n=25,days=4,stocks=6)
        slices.append({'scope_type':'STANCE','scope_value':'DEFENSIVE',**cell})
        d=shadow.shadow_decision(
            {'segment_type':'STANCE_TRIGGER',
             'segment_value':'DEFENSIVE | BREAKOUT_TEST'},
            overall,slices
        )
        self.assertIn(d['state'],('CONSISTENT','ACCEPT_CANDIDATE'))


if __name__=='__main__':
    unittest.main()
