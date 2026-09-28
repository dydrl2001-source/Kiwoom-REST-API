import sys,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_learning as learn
import market_os_store as store


class LearningPureTests(unittest.TestCase):
    def test_session_buckets(self):
        # UTC -> KST
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,0,5,tzinfo=timezone.utc)),'OPEN_20')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,0,40,tzinfo=timezone.utc)),'MORNING')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,5,10,tzinfo=timezone.utc)),'AFTERNOON')
        self.assertEqual(learn.session_bucket(datetime(2026,9,28,6,5,tzinfo=timezone.utc)),'CLOSE')

    def test_setup_bucket(self):
        self.assertEqual(learn._bucket_setup(85),'80-100')
        self.assertEqual(learn._bucket_setup(70),'65-79')
        self.assertEqual(learn._bucket_setup(55),'50-64')
        self.assertEqual(learn._bucket_setup(30),'0-49')

    def test_aggregate_uses_observed_outcomes_only(self):
        a=learn._aggregate([
            {'return_pct':1.0,'mfe_pct':2.0,'mae_pct':-0.5},
            {'return_pct':-0.5,'mfe_pct':0.7,'mae_pct':-1.2},
            {'return_pct':None,'mfe_pct':99,'mae_pct':-99},
        ])
        self.assertEqual(a['samples'],2)
        self.assertAlmostEqual(a['avg_return_pct'],0.25)
        self.assertAlmostEqual(a['median_return_pct'],0.25)
        self.assertAlmostEqual(a['positive_rate'],0.5)
        self.assertAlmostEqual(a['avg_mfe_pct'],1.35)
        self.assertAlmostEqual(a['avg_mae_pct'],-0.85)

    def test_episode_anchors_do_not_count_repeated_snapshots_as_independent(self):
        base=datetime(2026,9,28,3,0,tzinfo=timezone.utc)
        rows=[]
        for i in range(10):
            rows.append({'horizon':'5m','stock_code':'005930','snapshot_time':base+timedelta(minutes=i),
                         'return_pct':0.1,'mfe_pct':0.2,'mae_pct':-0.1})
        anchors=learn._episode_anchors(rows)
        self.assertEqual(len(anchors),2)
        self.assertEqual([x['snapshot_time'] for x in anchors],[base,base+timedelta(minutes=5)])

    def test_close_uses_one_anchor_per_stock_day(self):
        base=datetime(2026,9,28,0,0,tzinfo=timezone.utc)
        rows=[
            {'horizon':'close','stock_code':'005930','snapshot_time':base+timedelta(minutes=10),
             'return_pct':0.1,'mfe_pct':0.2,'mae_pct':-0.1},
            {'horizon':'close','stock_code':'005930','snapshot_time':base+timedelta(minutes=40),
             'return_pct':0.2,'mfe_pct':0.3,'mae_pct':-0.1},
            {'horizon':'close','stock_code':'005930','snapshot_time':base+timedelta(days=1,minutes=10),
             'return_pct':0.3,'mfe_pct':0.4,'mae_pct':-0.1},
        ]
        self.assertEqual(len(learn._episode_anchors(rows)),2)

    def test_micro_state_is_explicit_and_conservative(self):
        self.assertEqual(learn._micro_state(130,.70),'STRONG_CONFIRM')
        self.assertEqual(learn._micro_state(70,.40),'WEAK_CONFIRM')
        self.assertEqual(learn._micro_state(110,.60),'POSITIVE')
        self.assertEqual(learn._micro_state(90,.40),'NEGATIVE')
        self.assertEqual(learn._micro_state(105,.48),'MIXED')
        self.assertEqual(learn._micro_state(None,.70),'NO_DATA')

    def test_pre_registered_four_way_interaction_requires_clean_micro(self):
        row={
            'watch_tier':'PREP','market_stance':'DEFENSIVE','trigger_state':'BREAKOUT_TEST',
            'session_bucket':'MIDDAY','catalyst_grade':'C','setup_score':85,
            'micro_strength':130,'micro_buy_share_15s':.70,
            'micro_tick_count_15s':20,'micro_gap_count_15s':0
        }
        d=learn._learning_dims(row)
        self.assertEqual(d['STANCE_SETUP_TRIGGER_MICRO'],
                         'DEFENSIVE | 80-100 | BREAKOUT_TEST | STRONG_CONFIRM')
        row['micro_gap_count_15s']=1
        d=learn._learning_dims(row)
        self.assertNotIn('STANCE_SETUP_TRIGGER_MICRO',d)
        self.assertNotIn('MICRO_STATE',d)

    def test_interaction_quality_gate_is_stricter_by_depth(self):
        self.assertEqual(store._quality(25,5,2,1),'초기')
        self.assertEqual(store._quality(25,5,2,3),'탐색')
        self.assertEqual(store._quality(70,10,4,4),'초기')

    def test_interaction_edge_compares_to_registered_parent(self):
        segs=[
            {'segment_type':'STANCE_TRIGGER','segment_value':'DEFENSIVE | BREAKOUT_TEST',
             'horizon':'30m','samples':100,'distinct_stocks':12,'distinct_days':6,'sample_basis':'NON_OVERLAP_30M',
             'quality':'형성','avg_return_pct':-.40,'median_return_pct':-.30,'positive_rate':.40,
             'avg_mfe_pct':.50,'avg_mae_pct':-1.00},
            {'segment_type':'STANCE_SETUP_TRIGGER','segment_value':'DEFENSIVE | 80-100 | BREAKOUT_TEST',
             'horizon':'30m','samples':120,'distinct_stocks':13,'distinct_days':6,'sample_basis':'NON_OVERLAP_30M',
             'quality':'형성','avg_return_pct':-.10,'median_return_pct':-.05,'positive_rate':.48,
             'avg_mfe_pct':.70,'avg_mae_pct':-.70},
        ]
        edges=[{
            'segment_type':'STANCE_SETUP_TRIGGER',
            'segment_value':'DEFENSIVE | 80-100 | BREAKOUT_TEST','horizon':'30m',
            'parent_type':'STANCE_TRIGGER','parent_value':'DEFENSIVE | BREAKOUT_TEST',
            'sample_basis':'NON_OVERLAP_30M',
            'child_samples':120,'child_stocks':13,'child_days':6,
            'comparator_samples':100,'comparator_stocks':12,'comparator_days':6,
            'child_avg_return_pct':-.10,'comparator_avg_return_pct':-.40,'delta_avg_return_pct':.30,
            'child_positive_rate':.48,'comparator_positive_rate':.40,'delta_positive_rate_pp':8.0,
            'child_avg_mfe_pct':.70,'comparator_avg_mfe_pct':.50,'delta_mfe_pct':.20,
            'child_avg_mae_pct':-.70,'comparator_avg_mae_pct':-1.00,'delta_mae_pct':.30,
        }]
        inter=store._enrich_edges(segs,edges)
        child=next(x for x in inter if x['segment_type']=='STANCE_SETUP_TRIGGER')
        self.assertEqual(child['baseline']['comparison'],'PARENT_COMPLEMENT')
        self.assertAlmostEqual(child['edge_avg_return_pct'],.30)
        self.assertAlmostEqual(child['edge_positive_rate_pp'],8.0)
        self.assertAlmostEqual(child['edge_mae_pct'],.30)
        self.assertTrue(child['edge_ready'])

    def test_parent_complement_key_for_four_way_interaction(self):
        self.assertEqual(
            learn._parent_key('STANCE_SETUP_TRIGGER_MICRO',
                              'DEFENSIVE | 80-100 | BREAKOUT_TEST | STRONG_CONFIRM'),
            ('STANCE_SETUP_TRIGGER','DEFENSIVE | 80-100 | BREAKOUT_TEST')
        )

    def test_nonfinite_values_are_rejected(self):
        self.assertIsNone(learn.safe_num('NaN'))
        self.assertIsNone(learn.safe_num('inf'))
        self.assertIsNone(learn.safe_num(None))


    def test_validation_gate_promotes_only_aligned_formed_evidence(self):
        s={
            'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST','horizon':'30m',
            'samples':170,'distinct_stocks':12,'distinct_days':7,'quality':'충분',
            'avg_return_pct':.80,'median_return_pct':.40,'positive_rate':.64,
            'avg_mfe_pct':1.5,'avg_mae_pct':-.6,
        }
        gate=store._validation_gate(s)
        self.assertEqual(gate['status'],'PROMOTE_REVIEW')
        self.assertEqual(gate['readiness'],'READY')

    def test_validation_gate_holds_interaction_when_parent_edge_disagrees(self):
        s={
            'segment_type':'STANCE_TRIGGER','segment_value':'DEFENSIVE | BREAKOUT_TEST',
            'horizon':'30m','samples':220,'distinct_stocks':18,'distinct_days':9,
            'quality':'충분','interaction_depth':2,
            'avg_return_pct':.80,'median_return_pct':.30,'positive_rate':.62,
            'avg_mfe_pct':1.4,'avg_mae_pct':-.7,'edge_ready':True,
            'edge_avg_return_pct':-.10,'edge_positive_rate_pp':-2.0,'edge_mae_pct':-.1,
            'baseline':{'quality':'충분'}
        }
        gate=store._validation_gate(s)
        self.assertEqual(gate['status'],'HOLD')
        self.assertIn('EDGE_EFFECT_NOT_ALIGNED',gate['reason_codes'])

    def test_validation_gate_can_flag_suppression_review(self):
        s={
            'segment_type':'SETUP','segment_value':'0-49','horizon':'close',
            'samples':160,'distinct_stocks':12,'distinct_days':6,'quality':'충분',
            'avg_return_pct':-.55,'median_return_pct':-.25,'positive_rate':.35,
            'avg_mfe_pct':.4,'avg_mae_pct':-1.2,
        }
        gate=store._validation_gate(s)
        self.assertEqual(gate['status'],'SUPPRESS_REVIEW')
        self.assertEqual(gate['direction'],'WEAKNESS')

    def test_validation_gate_ignores_5m_for_live_rule_review(self):
        s={
            'segment_type':'TRIGGER','segment_value':'BREAKOUT_TEST','horizon':'5m',
            'samples':500,'distinct_stocks':30,'distinct_days':15,'quality':'충분',
            'avg_return_pct':1.0,'median_return_pct':.5,'positive_rate':.70,
        }
        self.assertIsNone(store._validation_gate(s))


if __name__=='__main__':
    unittest.main()
