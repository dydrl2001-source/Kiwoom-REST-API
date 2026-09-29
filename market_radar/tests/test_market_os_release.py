import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_release as release


class ReleaseCanaryPureTests(unittest.TestCase):
    def ruleset(self):
        return {
            'ruleset_id':'rs-abc','spec_hash':'hash-rs','version_label':'market-os-v1+dry-abc',
            'spec':{
                'spec_version':'versioned-ruleset-v1',
                'base_rule_version':'market-os-v1',
                'source_dossier_id':'ad-1',
                'source_dossier_hash':'dh',
                'source_shadow_rule_id':'sr-1',
                'prospective_only':True,'live_activation':False,
                'max_tier_shift':1,'blocked_override':False,
                'overlays':[{
                    'overlay_id':'overlay-001','segment_type':'TRIGGER',
                    'segment_value':'BREAKOUT_TEST','action':'PROMOTE_ONE_TIER',
                    'source':'ADOPTION_DOSSIER'
                }]
            }
        }

    def succession(self):
        return {'decision_state':'SUCCESSION_CANDIDATE','review_eligible':True}

    def cell(self,horizon='30m',cohort='REVIEW',changes=7,
             cavg=.2,kavg=.45,cpos=.50,kpos=.56,cmae=-1.0,kmae=-.7,
             n=30,days=5,stocks=7):
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

    def test_release_package_is_deterministic_and_safe(self):
        a=release.build_release_candidate(self.ruleset(),11,self.succession(),20)
        b=release.build_release_candidate(self.ruleset(),11,self.succession(),20)
        self.assertEqual(a,b)
        self.assertTrue(a['release_candidate_id'].startswith('rc-'))
        self.assertFalse(a['package']['safety']['live_activation'])
        self.assertFalse(a['package']['canary']['primary_view_replacement'])

    def test_release_requires_succession_candidate(self):
        with self.assertRaises(ValueError):
            release.build_release_candidate(
                self.ruleset(),11,
                {'decision_state':'RULESET_STABLE','review_eligible':False},20
            )

    def test_canary_assignment_is_stable_per_stock_day(self):
        a=release.canary_bucket('rc-1','005930','2026-09-29')
        b=release.canary_bucket('rc-1','005930','2026-09-29')
        self.assertEqual(a,b)
        self.assertEqual(
            release.is_canary_selected('rc-1','005930','2026-09-29',20),
            release.is_canary_selected('rc-1','005930','2026-09-29',20)
        )

    def test_canary_allocation_is_capped(self):
        with self.assertRaises(ValueError):
            release.build_release_candidate(self.ruleset(),11,self.succession(),50)
        with self.assertRaises(ValueError):
            release.is_canary_selected('rc','A','2026-09-29',50)

    def test_canary_rolls_back_on_comparable_30m_harm(self):
        bad=self.cell(cavg=.5,kavg=.2,cpos=.62,kpos=.48,cmae=-.5,kmae=-.9)
        d=release.canary_decision([bad],[])
        self.assertEqual(d['state'],'CANARY_ROLLBACK_REQUIRED')
        self.assertFalse(d['review_eligible'])

    def test_canary_healthy_when_30m_good_close_still_collecting(self):
        good=self.cell()
        close=self.cell('close',changes=2,n=8,days=1,stocks=3)
        d=release.canary_decision([good,close],[])
        self.assertEqual(d['state'],'CANARY_HEALTHY')
        self.assertFalse(d['review_eligible'])

    def test_canary_promotion_requires_strong_30m_and_close(self):
        good30=self.cell(changes=8,n=32,days=5,stocks=7)
        goodclose=self.cell('close',changes=8,n=32,days=5,stocks=7,cavg=.1,kavg=.4)
        d=release.canary_decision([good30,goodclose],[])
        self.assertEqual(d['state'],'CANARY_PROMOTION_CANDIDATE')
        self.assertTrue(d['review_eligible'])


if __name__=='__main__':
    unittest.main()
