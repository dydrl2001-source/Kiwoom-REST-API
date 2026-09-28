import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_dossier as dossier


class AdoptionDossierPureTests(unittest.TestCase):
    def base(self,action='PROMOTE_ONE_TIER'):
        rule={
            'shadow_rule_id':'sr-abc','candidate_key':'abc','rule_version':'market-os-v1',
            'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST',
            'source_horizon':'30m','action':action,'approved_at':'2026-09-29T01:00:00+09:00'
        }
        decision={
            'decision_state':'ACCEPT_CANDIDATE','review_eligible':True,'primary_cohort':'REVIEW',
            'reason_codes':['30M_CLOSE_BENEFICIAL'],
            'evidence':{'overall_30m':'BENEFICIAL','overall_close':'BENEFICIAL'}
        }
        promotion={
            'direction':'STRENGTH','review_action':'PROMOTE','quality':'충분',
            'walk_forward_status':'STABLE','samples':180,'distinct_stocks':15,'distinct_days':10,
            'avg_return_pct':.8,'early_avg_return_pct':.7,'recent_avg_return_pct':.9
        }
        summaries=[
            {'horizon':'30m','cohort':'REVIEW','evidence_state':'COMPARABLE',
             'membership_changes':14,'control_samples':60,'challenger_samples':62,
             'control_avg_return_pct':.20,'challenger_avg_return_pct':.55,
             'delta_avg_return_pct':.35,'delta_positive_rate_pp':5.0,'delta_mae_pct':.2}
        ]
        cases=[
            {'assessment_time':'2026-09-29T01:01:00Z','stock_code':'A','stock_name':'A',
             'market_stance':'SELECTIVE','control_tier':'DISCOVER','challenger_tier':'PREP',
             'return_30m_pct':-1.0,'return_close_pct':-.5,'return_d1_pct':.2},
            {'assessment_time':'2026-09-29T01:02:00Z','stock_code':'B','stock_name':'B',
             'market_stance':'EXPANDABLE','control_tier':'PREP','challenger_tier':'FOCUS',
             'return_30m_pct':2.0,'return_close_pct':1.0,'return_d1_pct':1.2},
        ]
        return rule,decision,promotion,summaries,cases

    def test_dossier_is_deterministic_and_hash_stable(self):
        args=self.base()
        a=dossier.build_dossier(*args)
        b=dossier.build_dossier(*args)
        self.assertEqual(dossier.dossier_hash(a),dossier.dossier_hash(b))
        self.assertEqual(a,b)

    def test_promote_counterexample_is_weak_outcome(self):
        d=dossier.build_dossier(*self.base())
        self.assertEqual(d['counterexamples']['cases'][0]['stock_code'],'A')
        self.assertEqual(d['supporting_examples'][0]['stock_code'],'B')

    def test_suppress_counterexample_is_strong_outcome(self):
        args=list(self.base(action='SUPPRESS_ONE_TIER'))
        d=dossier.build_dossier(*args)
        self.assertEqual(d['counterexamples']['cases'][0]['stock_code'],'B')

    def test_dossier_never_authorizes_live_activation(self):
        d=dossier.build_dossier(*self.base())
        self.assertFalse(d['proposed_change']['live_activation'])
        self.assertEqual(d['proposed_change']['next_allowed_step'],'HUMAN_APPROVED_DRY_RUN')
        self.assertFalse(d['impact_surface']['blocked_override'])

    def test_dossier_records_transition_and_stance_surface(self):
        d=dossier.build_dossier(*self.base())
        self.assertEqual(d['impact_surface']['changed_episode_count'],2)
        self.assertEqual(d['impact_surface']['tier_transitions']['DISCOVER→PREP'],1)
        self.assertEqual(d['impact_surface']['market_stances']['SELECTIVE'],1)


if __name__=='__main__':
    unittest.main()
