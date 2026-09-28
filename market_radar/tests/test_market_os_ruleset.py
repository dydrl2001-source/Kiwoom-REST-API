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


if __name__=='__main__':
    unittest.main()
