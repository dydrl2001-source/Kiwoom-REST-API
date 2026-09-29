import sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_execution as ex


class ExecutionFirewallPureTests(unittest.TestCase):
    def candidate(self,**overrides):
        x={
            'code':'005930','name':'삼성전자',
            'watch_tier':'FOCUS','base_watch_tier':'PREP',
            'control_overlay_applied':True,
            'trigger_state':'STRUCTURE_CONFIRMED',
            'market_stance':'SELECTIVE','catalyst_grade':'A',
            'setup_score':90,'radar_score':80,'theme_score':70,
            'risk_flags':[],
        }
        x.update(overrides)
        return x

    def control(self,**overrides):
        x={
            'mode':'RULESET','apply_status':'APPLIED',
            'control_id':'control-rs-1','control_hash':'h1',
            'active_version_label':'market-os-v1+dry-x',
            'switch_transaction_id':'sw-1',
        }
        x.update(overrides)
        return x

    def test_healthy_focus_candidate_is_review_eligible(self):
        d=ex.evaluate(self.candidate(),self.control(),'HEALTHY',15)
        self.assertTrue(d['eligible'])
        self.assertEqual(d['status'],'REVIEW_ELIGIBLE')

    def test_unhealthy_switch_blocks_intent(self):
        d=ex.evaluate(self.candidate(),self.control(),'COMMITTED',15)
        self.assertFalse(d['eligible'])
        self.assertIn('CONTROL_SWITCH_NOT_HEALTHY',d['reason_codes'])

    def test_structural_and_market_risks_block(self):
        d=ex.evaluate(
            self.candidate(
                market_stance='DEFENSIVE',
                risk_flags=['추세 훼손','시장 레짐 방어적']
            ),
            self.control(),'HEALTHY',15
        )
        self.assertFalse(d['eligible'])
        self.assertIn('MARKET_STANCE_BLOCKED',d['reason_codes'])
        self.assertIn('HARD_RISK_FLAG',d['reason_codes'])

    def test_stale_sample_blocks(self):
        d=ex.evaluate(self.candidate(),self.control(),'HEALTHY',120)
        self.assertFalse(d['eligible'])
        self.assertIn('STALE_SAMPLE',d['reason_codes'])

    def test_intent_snapshot_never_creates_order_parameters(self):
        now=datetime.now(timezone.utc)
        s=ex.snapshot(
            self.candidate(),self.control(),70000,now,now+timedelta(seconds=120)
        )
        execution=s['evidence']['execution']
        self.assertFalse(execution['broker_order_created'])
        self.assertIsNone(execution['quantity'])
        self.assertIsNone(execution['limit_price'])
        self.assertFalse(execution['market_order'])
        self.assertFalse(execution['position_change'])

    def test_intent_id_is_deterministic(self):
        t='2026-09-30T00:00:00+00:00'
        self.assertEqual(
            ex.intent_id('h1','005930',t),
            ex.intent_id('h1','005930',t)
        )

    def test_human_approval_invalid_after_control_change(self):
        now=datetime.now(timezone.utc)
        intent={
            'expires_at':now+timedelta(seconds=60),
            'control_hash':'h1','switch_transaction_id':'sw-1'
        }
        d=ex.approval_still_valid(
            intent,self.control(control_hash='h2'),'HEALTHY',now
        )
        self.assertFalse(d['valid'])
        self.assertIn('CONTROL_HASH_CHANGED',d['reason_codes'])

    def test_human_approval_invalid_after_expiry(self):
        now=datetime.now(timezone.utc)
        intent={
            'expires_at':now-timedelta(seconds=1),
            'control_hash':'h1','switch_transaction_id':'sw-1'
        }
        d=ex.approval_still_valid(intent,self.control(),'HEALTHY',now)
        self.assertFalse(d['valid'])
        self.assertIn('INTENT_EXPIRED',d['reason_codes'])


if __name__=='__main__':
    unittest.main()
