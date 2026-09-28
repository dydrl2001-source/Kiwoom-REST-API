import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_ruleset as ruleset


class VersionedRulesetPureTests(unittest.TestCase):
    def dossier(self):
        return {
            'shadow_rule':{
                'shadow_rule_id':'sr-abc','rule_version':'market-os-v1'
            },
            'proposed_change':{
                'condition':{
                    'segment_type':'STANCE_SETUP_TRIGGER',
                    'segment_value':'DEFENSIVE | 80-100 | BREAKOUT_TEST',
                },
                'action':'PROMOTE_ONE_TIER',
                'blocked_override':False,
                'live_activation':False,
            }
        }

    def snapshot(self,**overrides):
        x={
            'watch_tier':'PREP','market_stance':'DEFENSIVE',
            'trigger_state':'BREAKOUT_TEST','session_bucket':'MORNING',
            'catalyst_grade':'B','setup_score':85,
            'micro_strength':130,'micro_buy_share_15s':.70,
            'micro_tick_count_15s':10,'micro_gap_count_15s':0,
        }
        x.update(overrides)
        return x

    def test_spec_is_deterministic_and_versioned(self):
        a=ruleset.build_spec('ad-1','hash-1',self.dossier())
        b=ruleset.build_spec('ad-1','hash-1',self.dossier())
        self.assertEqual(a,b)
        self.assertTrue(a['ruleset_id'].startswith('rs-'))
        self.assertIn('+dry-',a['version_label'])
        self.assertFalse(a['spec']['live_activation'])

    def test_spec_hash_changes_with_source_dossier_hash(self):
        a=ruleset.build_spec('ad-1','hash-1',self.dossier())
        b=ruleset.build_spec('ad-1','hash-2',self.dossier())
        self.assertNotEqual(a['content_hash'],b['content_hash'])

    def test_candidate_evaluation_never_mutates_control(self):
        built=ruleset.build_spec('ad-1','hash-1',self.dossier())
        out=ruleset.evaluate(self.snapshot(),built['spec'])
        self.assertEqual(out['control_tier'],'PREP')
        self.assertEqual(out['candidate_tier'],'FOCUS')
        self.assertTrue(out['changed'])
        self.assertEqual(self.snapshot()['watch_tier'],'PREP')

    def test_nonmatching_snapshot_stays_identical(self):
        built=ruleset.build_spec('ad-1','hash-1',self.dossier())
        out=ruleset.evaluate(self.snapshot(market_stance='EXPANDABLE'),built['spec'])
        self.assertFalse(out['changed'])
        self.assertEqual(out['control_tier'],out['candidate_tier'])

    def test_blocked_is_never_unblocked(self):
        built=ruleset.build_spec('ad-1','hash-1',self.dossier())
        out=ruleset.evaluate(self.snapshot(watch_tier='BLOCKED'),built['spec'])
        self.assertEqual(out['candidate_tier'],'BLOCKED')

    def test_live_activation_and_multi_overlay_are_forbidden(self):
        built=ruleset.build_spec('ad-1','hash-1',self.dossier())
        spec=dict(built['spec']);spec['live_activation']=True
        with self.assertRaises(ValueError):
            ruleset.evaluate(self.snapshot(),spec)
        spec=dict(built['spec']);spec['overlays']=built['spec']['overlays']*2
        with self.assertRaises(ValueError):
            ruleset.evaluate(self.snapshot(),spec)

    def test_dry_run_summary_uses_candidate_tier(self):
        rows=[
            {'horizon':'30m','stock_code':'A','trade_day':'2026-09-29',
             'control_tier':'DISCOVER','candidate_tier':'PREP',
             'return_pct':2.0,'mfe_pct':2.4,'mae_pct':-.2},
            {'horizon':'30m','stock_code':'B','trade_day':'2026-09-29',
             'control_tier':'PREP','candidate_tier':'PREP',
             'return_pct':-1.0,'mfe_pct':.3,'mae_pct':-1.3},
        ]
        s=next(x for x in ruleset.dry_run_summaries(rows)
               if x['horizon']=='30m' and x['cohort']=='REVIEW')
        self.assertEqual(s['control']['samples'],1)
        self.assertEqual(s['challenger']['samples'],2)
        self.assertAlmostEqual(s['delta_avg_return_pct'],1.5)


    def summary_cell(self,horizon='30m',cohort='REVIEW',changes=16,
                     cavg=.20,kavg=.55,cpos=.50,kpos=.58,cmae=-1.0,kmae=-.7,
                     n=70,days=9,stocks=12):
        return {
            'horizon':horizon,'cohort':cohort,'membership_changes':changes,
            'control':{'samples':n,'distinct_stocks':stocks,'distinct_days':days,
                       'avg_return_pct':cavg,'median_return_pct':cavg,
                       'positive_rate':cpos,'avg_mfe_pct':1.0,'avg_mae_pct':cmae},
            'challenger':{'samples':n,'distinct_stocks':stocks,'distinct_days':days,
                          'avg_return_pct':kavg,'median_return_pct':kavg,
                          'positive_rate':kpos,'avg_mfe_pct':1.2,'avg_mae_pct':kmae},
            'delta_avg_return_pct':kavg-cavg,
            'delta_positive_rate_pp':(kpos-cpos)*100,
            'delta_mae_pct':kmae-cmae,
        }

    def succession_ruleset(self):
        return {'spec':{'overlays':[{
            'overlay_id':'overlay-001',
            'segment_type':'STANCE_TRIGGER',
            'segment_value':'DEFENSIVE | BREAKOUT_TEST',
            'action':'PROMOTE_ONE_TIER',
        }]}}

    def stable_succession_inputs(self):
        overall=[
            self.summary_cell('30m','REVIEW'),
            self.summary_cell('close','REVIEW',cavg=.10,kavg=.45),
        ]
        slices=[]
        for window in ('EARLY','RECENT'):
            slices.append({'scope_type':'WINDOW','scope_value':window,
                           **self.summary_cell('30m','REVIEW',changes=12,n=60,days=8,stocks=10)})
            slices.append({'scope_type':'WINDOW','scope_value':window,
                           **self.summary_cell('close','REVIEW',changes=12,n=60,days=8,stocks=10,
                                               cavg=.10,kavg=.45)})
        slices.append({'scope_type':'STANCE','scope_value':'DEFENSIVE',
                       **self.summary_cell('30m','REVIEW',changes=10,n=45,days=6,stocks=8)})
        concentration={
            'REVIEW':{'changed_episodes':18,'distinct_stocks':10,'distinct_days':7,
                      'top_stock_share':.20,'top_day_share':.28,
                      'stock_hhi':.12,'day_hhi':.18}
        }
        shadow=[
            self.summary_cell('30m','REVIEW',cavg=.20,kavg=.60),
            self.summary_cell('close','REVIEW',cavg=.10,kavg=.50),
        ]
        return overall,slices,concentration,shadow

    def test_impact_concentration_detects_single_stock_dependency(self):
        rows=[]
        for i in range(12):
            rows.append({
                'horizon':'30m','stock_code':'A' if i<8 else f'S{i}',
                'trade_day':f'2026-09-{20+(i%6):02d}',
                'control_tier':'DISCOVER','candidate_tier':'PREP',
            })
        d=ruleset.impact_concentration(rows,'REVIEW')
        self.assertEqual(d['changed_episodes'],12)
        self.assertGreater(d['top_stock_share'],.35)

    def test_succession_gate_collects_before_comparable_30m(self):
        overall=[self.summary_cell('30m','REVIEW',changes=3,n=12,days=2,stocks=3)]
        d=ruleset.succession_decision(self.succession_ruleset(),overall,[],{},[])
        self.assertEqual(d['state'],'RULESET_COLLECTING')
        self.assertFalse(d['review_eligible'])

    def test_succession_gate_rejects_comparable_d1_harm(self):
        overall,slices,conc,shadow=self.stable_succession_inputs()
        overall.append(self.summary_cell('D+1','REVIEW',changes=10,n=35,days=5,stocks=7,
                                         cavg=.50,kavg=.20,cpos=.60,kpos=.48,
                                         cmae=-.5,kmae=-.9))
        d=ruleset.succession_decision(self.succession_ruleset(),overall,slices,conc,shadow)
        self.assertEqual(d['state'],'RULESET_REJECT')
        self.assertIn('D1_HARMFUL',d['reason_codes'])

    def test_succession_gate_blocks_concentrated_impact(self):
        overall,slices,conc,shadow=self.stable_succession_inputs()
        conc['REVIEW']['top_stock_share']=.60
        d=ruleset.succession_decision(self.succession_ruleset(),overall,slices,conc,shadow)
        self.assertEqual(d['state'],'RULESET_MORE_DATA')
        self.assertIn('IMPACT_CONCENTRATION_HIGH',d['reason_codes'])

    def test_succession_gate_blocks_shadow_effect_collapse(self):
        overall,slices,conc,shadow=self.stable_succession_inputs()
        shadow[0]['delta_avg_return_pct']=1.20
        shadow[1]['delta_avg_return_pct']=1.00
        d=ruleset.succession_decision(self.succession_ruleset(),overall,slices,conc,shadow)
        self.assertEqual(d['state'],'RULESET_MORE_DATA')
        self.assertIn('SHADOW_EFFECT_COLLAPSED',d['reason_codes'])

    def test_succession_gate_marks_strong_replicated_ruleset_candidate(self):
        overall,slices,conc,shadow=self.stable_succession_inputs()
        d=ruleset.succession_decision(self.succession_ruleset(),overall,slices,conc,shadow)
        self.assertEqual(d['state'],'SUCCESSION_CANDIDATE')
        self.assertTrue(d['review_eligible'])
        self.assertIn('STRONG_SAMPLE_GATE_PASSED',d['reason_codes'])


if __name__=='__main__':
    unittest.main()
