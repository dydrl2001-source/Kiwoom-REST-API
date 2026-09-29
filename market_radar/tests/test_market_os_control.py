import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_control as control


class RuntimeControlPureTests(unittest.TestCase):
    def ruleset(self,segment_type='STANCE_SETUP_TRIGGER',
                segment_value='DEFENSIVE | 80-100 | BREAKOUT_TEST'):
        return {
            'ruleset_id':'rs-abc','spec_hash':'hash-rs','version_label':'market-os-v1+dry-abc',
            'spec':{
                'base_rule_version':'market-os-v1',
                'live_activation':False,'blocked_override':False,
                'overlays':[{
                    'overlay_id':'overlay-001','segment_type':segment_type,
                    'segment_value':segment_value,'action':'PROMOTE_ONE_TIER'
                }]
            }
        }

    def watch(self,tier='PREP',stance='DEFENSIVE',setup=85,trigger='BREAKOUT_TEST'):
        return [{
            'code':'005930','name':'삼성전자','watch_tier':tier,
            'market_stance':stance,'setup_score':setup,'trigger_state':trigger,
            'catalyst_grade':'B','radar_score':80,'theme_score':70,
            'trade_rank':1,'version':'market-os-v1'
        }]

    def test_base_control_is_deterministic(self):
        a=control.base_control('market-os-v1')
        b=control.base_control('market-os-v1')
        self.assertEqual(a,b)
        self.assertEqual(a['mode'],'BASE')

    def test_candidate_control_requires_safe_single_overlay(self):
        c=control.candidate_control(
            'market-os-v1',self.ruleset(),'fr-1','sw-1'
        )
        self.assertEqual(c['mode'],'RULESET')
        self.assertEqual(c['ruleset_id'],'rs-abc')
        self.assertEqual(c['switch_transaction_id'],'sw-1')

    def test_live_control_changes_only_watch_tier(self):
        c=control.candidate_control('market-os-v1',self.ruleset(),'fr-1','sw-1')
        out,meta=control.apply_watchlist(self.watch(),c)
        self.assertEqual(out[0]['base_watch_tier'],'PREP')
        self.assertEqual(out[0]['watch_tier'],'FOCUS')
        self.assertTrue(out[0]['control_overlay_applied'])
        self.assertEqual(meta['changed_count'],1)
        self.assertEqual(out[0]['radar_score'],80)

    def test_blocked_never_unblocked(self):
        c=control.candidate_control('market-os-v1',self.ruleset(),'fr-1','sw-1')
        out,_=control.apply_watchlist(self.watch(tier='BLOCKED'),c)
        self.assertEqual(out[0]['watch_tier'],'BLOCKED')

    def test_nonmatching_condition_keeps_control_tier(self):
        c=control.candidate_control('market-os-v1',self.ruleset(),'fr-1','sw-1')
        out,meta=control.apply_watchlist(self.watch(stance='EXPANDABLE'),c)
        self.assertEqual(out[0]['watch_tier'],'PREP')
        self.assertEqual(meta['changed_count'],0)

    def test_micro_control_uses_clean_runtime_micro(self):
        rs=self.ruleset('MICRO_STATE','STRONG_CONFIRM')
        c=control.candidate_control('market-os-v1',rs,'fr-1','sw-1')
        micro={'005930':{
            'micro_tick_count_15s':10,'micro_gap_count_15s':0,
            'micro_strength':130,'micro_buy_share_15s':.70
        }}
        out,meta=control.apply_watchlist(self.watch(stance='SELECTIVE'),c,micro)
        self.assertEqual(out[0]['watch_tier'],'FOCUS')
        self.assertTrue(meta['requires_micro'])

    def test_micro_control_never_matches_gap_data(self):
        rs=self.ruleset('MICRO_STATE','STRONG_CONFIRM')
        c=control.candidate_control('market-os-v1',rs,'fr-1','sw-1')
        micro={'005930':{
            'micro_tick_count_15s':10,'micro_gap_count_15s':1,
            'micro_strength':130,'micro_buy_share_15s':.70
        }}
        out,_=control.apply_watchlist(self.watch(stance='SELECTIVE'),c,micro)
        self.assertEqual(out[0]['watch_tier'],'PREP')

    def test_unsafe_spec_is_rejected(self):
        rs=self.ruleset();rs['spec']['live_activation']=True
        with self.assertRaises(ValueError):
            control.candidate_control('market-os-v1',rs,'fr-1','sw-1')


if __name__=='__main__':
    unittest.main()
