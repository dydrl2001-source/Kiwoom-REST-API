import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import market_os_rule_engine as mos


def row(code='319660', **kw):
    base={
        'code':code,'name':'시험기업','sector':'반도체','recent_trade':True,
        'delta_state':'OK','interval_turnover_krw':8_000_000_000,
        'five_min_turnover_krw':25_000_000_000,'query_rank':5,'trade_rank':7,
        'burst_multiple':3.2,'market_theme':'AI 반도체','change_pct':6.0,
        'quality_flags':[],'event_type':'기술·제품·양산',
        'research':{'id':1},'research_stale':False,'leads':[],
        'chart':{'state':'BREAKOUT_HOLD','state_ko':'돌파 후 지지',
                 'minute_trend':'상승 유지','daily_context':'전고점/신고가 상단'},
        'received_at':'2026-09-28T01:30:00+00:00'
    }
    base.update(kw)
    return base


ROTATION={'series':[{'name':'AI 반도체','change_pp':3.4,'current_share_pct':24.0}]}
REGIME={
    'candidate_trend_state':'RISING',
    'candidate_flow_state':'LEADER_CONCENTRATED',
    'candidate_sentiment_state':'STRONG',
    'stale':False
}


class MarketOSTests(unittest.TestCase):
    def test_axes_are_independent_no_composite_score(self):
        rows=[row(),row('000660',name='두번째',query_rank=9,trade_rank=10)]
        out=mos.market_os_watchlist(rows,ROTATION,REGIME)
        self.assertTrue(out)
        x=out[0]
        for key in ('radar_score','theme_score','setup_score','catalyst_grade','trigger_state','risk_flags'):
            self.assertIn(key,x)
        self.assertNotIn('score',x)
        self.assertNotIn('recommendation_score',x)

    def test_focus_requires_intersection_not_attention_alone(self):
        rows=[row(),row('000660',name='두번째',query_rank=9,trade_rank=10)]
        x=mos.market_os_watchlist(rows,ROTATION,REGIME)[0]
        self.assertEqual(x['watch_tier'],'FOCUS')
        weak=row('123456',market_theme=None,research=None,event_type=None,leads=[],
                 chart={'state':None},query_rank=1,trade_rank=1,burst_multiple=6)
        y=mos.market_os_watchlist([weak],{'series':[]},REGIME)[0]
        self.assertEqual(y['watch_tier'],'DISCOVER')
        self.assertGreaterEqual(y['radar_score'],x['radar_score'])
        self.assertEqual(y['setup_score'],0)

    def test_catalyst_grade_is_evidence_not_direction(self):
        a=mos.market_os_watchlist([row()],ROTATION,REGIME)[0]
        self.assertEqual(a['catalyst_grade'],'A')
        c=mos.market_os_watchlist([row(research=None,event_type=None,leads=[{'kind':'DART_LIST_ONLY'}])],ROTATION,REGIME)[0]
        self.assertEqual(c['catalyst_grade'],'C')
        u=mos.market_os_watchlist([row(research=None,event_type=None,leads=[])],ROTATION,REGIME)[0]
        self.assertEqual(u['catalyst_grade'],'U')

    def test_broken_structure_is_blocked(self):
        x=mos.market_os_watchlist([row(chart={'state':'BREAKOUT_FAIL','state_ko':'돌파 실패','minute_trend':'추세 약화'})],ROTATION,REGIME)[0]
        self.assertEqual(x['trigger_state'],'BLOCKED')
        self.assertEqual(x['watch_tier'],'BLOCKED')
        self.assertIn('돌파 실패',x['risk_flags'])

    def test_distributed_or_weak_market_is_defensive(self):
        regime={**REGIME,'candidate_flow_state':'ROTATIONAL_DISTRIBUTED'}
        x=mos.market_os_watchlist([row()],ROTATION,regime)[0]
        self.assertEqual(x['market_stance'],'DEFENSIVE')
        self.assertIn('시장 레짐 방어적',x['risk_flags'])
        self.assertNotEqual(x['watch_tier'],'FOCUS')

    def test_theme_score_uses_breadth_and_common_cohort_share(self):
        one=mos.market_os_watchlist([row()],ROTATION,REGIME)[0]
        many=mos.market_os_watchlist(
            [row('319660'),row('000660'),row('005930'),row('042700')],
            ROTATION,REGIME
        )[0]
        self.assertGreater(many['theme_score'],one['theme_score'])

    def test_invalid_or_stale_flow_is_not_candidate(self):
        self.assertEqual(mos.market_os_watchlist([row(recent_trade=False)],ROTATION,REGIME),[])
        self.assertEqual(mos.market_os_watchlist([row(delta_state='WINDOW_GAP')],ROTATION,REGIME),[])
        self.assertEqual(mos.market_os_watchlist([row(quality_flags=['TURNOVER_UNIT_UNRESOLVED'])],ROTATION,REGIME),[])


if __name__=='__main__':
    unittest.main()
