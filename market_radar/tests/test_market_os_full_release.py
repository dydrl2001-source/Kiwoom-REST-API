import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_full_release as full


class FullReleaseReviewPureTests(unittest.TestCase):
    def release_candidate(self):
        return {
            'release_candidate_id':'rc-1','release_version_label':'rv1',
            'source_ruleset_id':'rs-1','package_hash':'ph',
            'status':'CANARY_ACTIVE',
            'package':{
                'source_ruleset_hash':'rh',
                'safety':{
                    'live_activation':False,'order_execution':False,
                    'position_sizing':False,'blocked_override':False,
                    'auto_full_promotion':False,
                },
                'candidate_ruleset_spec':{
                    'base_rule_version':'market-os-v1',
                    'live_activation':False,'blocked_override':False,
                }
            }
        }

    def ruleset(self):
        return {'ruleset_id':'rs-1','spec_hash':'rh','version_label':'dry-v1',
                'base_rule_version':'market-os-v1'}

    def decision(self):
        return {'decision_state':'CANARY_PROMOTION_CANDIDATE',
                'review_eligible':True,'primary_cohort':'REVIEW'}

    def row(self,h='30m',cohort='REVIEW',davg=.30,dpos=5.0,dmae=.2):
        return {'horizon':h,'cohort':cohort,'delta_avg_return_pct':davg,
                'delta_positive_rate_pp':dpos,'delta_mae_pct':dmae}

    def composition(self):
        return {
            'expected_pct':20,'eligible_stock_days':50,'selected_stock_days':10,
            'stance_universe':{'SELECTIVE':25,'EXPANDABLE':15,'DEFENSIVE':10},
            'stance_canary':{'SELECTIVE':5,'EXPANDABLE':3,'DEFENSIVE':2},
            'tier_universe':{'FOCUS':10,'PREP':25,'DISCOVER':15},
            'tier_canary':{'FOCUS':2,'PREP':5,'DISCOVER':3},
        }

    def test_bias_gate_accepts_balanced_sample(self):
        g=full.sample_bias_gate(self.composition())
        self.assertTrue(g['ready'])
        self.assertAlmostEqual(g['evidence']['actual_pct'],20.0)

    def test_bias_gate_blocks_allocation_and_stance_skew(self):
        c=self.composition()
        c['selected_stock_days']=3
        c['stance_canary']={'DEFENSIVE':3}
        g=full.sample_bias_gate(c)
        self.assertFalse(g['ready'])
        self.assertIn('CANARY_ALLOCATION_DRIFT',g['reason_codes'])
        self.assertIn('CANARY_STANCE_BIAS',g['reason_codes'])

    def test_effect_alignment_requires_canary_to_track_dry_run(self):
        can=[self.row('30m',davg=.30),self.row('close',davg=.25)]
        dry=[self.row('30m',davg=.40),self.row('close',davg=.35)]
        g=full.effect_alignment_gate(can,dry,'REVIEW')
        self.assertTrue(g['ready'])
        self.assertGreater(g['evidence']['30m']['avg_effect_ratio'],.5)

    def test_effect_alignment_blocks_effect_collapse(self):
        can=[self.row('30m',davg=.10),self.row('close',davg=.10)]
        dry=[self.row('30m',davg=.50),self.row('close',davg=.50)]
        g=full.effect_alignment_gate(can,dry,'REVIEW')
        self.assertFalse(g['ready'])
        self.assertIn('30M_CANARY_EFFECT_COLLAPSED',g['reason_codes'])

    def test_rollback_manifest_points_to_current_control(self):
        g=full.rollback_readiness(
            self.release_candidate(),self.ruleset(),'market-os-v1'
        )
        self.assertTrue(g['ready'])
        self.assertEqual(g['rollback_target']['rule_version'],'market-os-v1')
        self.assertTrue(g['rollback_target']['one_click_target_defined'])
        self.assertFalse(g['rollback_target']['one_click_live_command_available'])

    def test_full_release_gate_ready_only_when_all_axes_pass(self):
        can=[self.row('30m',davg=.30),self.row('close',davg=.25)]
        dry=[self.row('30m',davg=.40),self.row('close',davg=.35)]
        g=full.full_release_gate(
            self.release_candidate(),self.decision(),can,dry,
            self.composition(),self.ruleset(),'market-os-v1'
        )
        self.assertEqual(g['state'],'FULL_RELEASE_REVIEW_READY')
        self.assertTrue(g['review_eligible'])

    def test_full_release_gate_blocks_control_version_mismatch(self):
        can=[self.row('30m',davg=.30),self.row('close',davg=.25)]
        dry=[self.row('30m',davg=.40),self.row('close',davg=.35)]
        g=full.full_release_gate(
            self.release_candidate(),self.decision(),can,dry,
            self.composition(),self.ruleset(),'market-os-v2'
        )
        self.assertEqual(g['state'],'FULL_RELEASE_MORE_DATA')
        self.assertIn('CONTROL_VERSION_MISMATCH',g['reason_codes'])

    def test_review_package_never_authorizes_deployment(self):
        can=[self.row('30m',davg=.30),self.row('close',davg=.25)]
        dry=[self.row('30m',davg=.40),self.row('close',davg=.35)]
        gate=full.full_release_gate(
            self.release_candidate(),self.decision(),can,dry,
            self.composition(),self.ruleset(),'market-os-v1'
        )
        pkg=full.build_review_package(
            self.release_candidate(),99,gate,can,dry,
            self.composition(),self.ruleset(),'market-os-v1'
        )
        self.assertEqual(pkg['package']['deployment_manifest']['deployment_mode'],'NOT_AUTHORIZED')
        self.assertFalse(pkg['package']['deployment_manifest']['primary_view_switch'])


if __name__=='__main__':
    unittest.main()
