import sys,types,os,unittest,json,importlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import flow_core as fc
NOW=datetime(2026,9,24,1,30,tzinfo=timezone.utc)


def sample(t=0,tv=100000000,code='319660',day='2026-09-24',**kw):
 d={'code':code,'name':'시험기업','received_at':(NOW+timedelta(seconds=t)).isoformat(),
    'batch_time':(NOW+timedelta(seconds=t)).isoformat(),'exchange_at':(NOW+timedelta(seconds=t-1)).isoformat(),
    'turnover_krw':tv,'trade_date':day,'venue':'SOR','source':'ka10095','unit_version':fc.VERSION,
    'cap_krw':10_000_000_000,'quality_flags':[],'price_krw':30000,'change_pct':1.5,'sector':'반도체','segment':'반도체 > 전공정 장비'}
 d.update(kw);return d

class CoreTests(unittest.TestCase):
 def test_validated_units(self):
  q=fc.quote({'stk_cd':'319660_AL','dt':'20260924','cntr_tm':'103000','cur_prc':'-10000',
              'low_pric':'9000','high_pric':'11000','trde_qty':'10000','trde_prica':'100',
              'stkcnt':'12340000','mac':'1234'},NOW)
  self.assertEqual(q['turnover_krw'],100_000_000);self.assertEqual(q['turnover_scale'],1_000_000)
  self.assertEqual(q['cap_krw'],123400000000);self.assertEqual(q['cap_scale'],100_000_000)
  self.assertEqual(q['price_krw'],10000)
 def test_no_magnitude_unit_guess(self):self.assertEqual(fc.amount('1000000000000',1000000),1000000000000000000)
 def test_nonfinite(self):
  for n in ('NaN','inf','bad',None):self.assertIsNone(fc.amount(n))
 def test_zero_not_missing(self):self.assertEqual(fc.amount('0',1000000),0)
 def test_negative_turnover_rejected(self):self.assertIsNone(fc.amount('-1',1000000))
 def test_quote_date_missing(self):self.assertIn('TRADE_DATE_MISSING',fc.quote({'stk_cd':'319660'},NOW)['quality_flags'])
 def test_volume_reference_rejects_wrong_scale(self):
  q=fc.quote({'stk_cd':'319660','trde_prica':'1000','trde_qty':'10','low_pric':'10000','high_pric':'11000'},NOW)
  self.assertIsNone(q['turnover_krw']);self.assertIn('TURNOVER_REFERENCE_MISMATCH',q['quality_flags'])
 def test_missing_reference_never_guesses_money_scale(self):
  q=fc.quote({'stk_cd':'319660','trde_prica':'100','mac':'1234'},NOW)
  self.assertIsNone(q['turnover_krw']);self.assertIsNone(q['cap_krw'])
  self.assertIn('TURNOVER_UNIT_UNRESOLVED',q['quality_flags']);self.assertIn('CAP_UNIT_UNRESOLVED',q['quality_flags'])
 def test_first_observation_not_burst(self):self.assertEqual(fc.delta(sample(),None)[1],'NO_BASELINE')
 def test_actual_interval(self):
  v,s,t=fc.delta(sample(32,130000000),sample(0,100000000));self.assertEqual((v,s,t),(30000000,'OK',32))
 def test_reset_not_negative_flow(self):self.assertEqual(fc.delta(sample(30,90),sample(0,100))[1],'COUNTER_RESET_OR_CORRECTION')
 def test_new_day(self):self.assertEqual(fc.delta(sample(30,150,day='2026-09-25'),sample())[1],'SESSION_OR_SOURCE_CHANGED')
 def test_scope_mismatch(self):self.assertEqual(fc.delta(sample(30,150000000,venue='KRX'),sample())[1],'SESSION_OR_SOURCE_CHANGED')
 def test_gap(self):self.assertEqual(fc.delta(sample(500),sample())[1],'WINDOW_GAP')
 def test_stale_market_not_live(self):self.assertFalse(fc.metrics([sample()],NOW+timedelta(days=3))['recent_trade'])
 def test_sample_is_not_exchange_freshness(self):self.assertFalse(fc.metrics([sample(exchange_at=(NOW-timedelta(days=1)).isoformat())],NOW)['recent_trade'])
 def test_burst_normalizes_seconds(self):
  h=[sample(i*30,100000000+i*30_000_000) for i in range(8)]
  h.append(sample(270,100000000+7*30_000_000+60_000_000))
  self.assertAlmostEqual(fc.metrics(h,NOW+timedelta(seconds=270))['burst_multiple'],1)
 def test_sparse_baseline_no_score(self):self.assertIsNone(fc.metrics([sample(),sample(30,120000000)],NOW)['burst_multiple'])
 def test_sector_does_not_use_news_keywords(self):self.assertEqual(fc.segment('003490','대한항공','운송')[1],'항공')
 def test_unknown_is_unknown(self):self.assertEqual(fc.segment('123456','다른기업','금속')[1],'세부 분류 대기')
 def test_market_theme_is_separate_from_business_segment(self):
  h={'319660':[sample(0,0),sample(30,100),sample(60,200)]}
  rows=[{**fc.metrics(h['319660'],NOW+timedelta(seconds=60)),'sector':'반도체','segment':'반도체 > 전공정 장비','market_theme':'AI 반도체','event_type':'기술·제품·양산'}]
  groups,_=fc.group_rows(rows,h,'catalyst')
  self.assertEqual(groups[0]['name'],'AI 반도체 / 기술·제품·양산')
 def test_common_cohort_share(self):
  h={'319660':[sample(0,0),sample(30,100),sample(60,300)],'222800':[sample(0,0,code='222800'),sample(30,100,code='222800'),sample(60,100,code='222800')]}
  rows=[{**fc.metrics(v,NOW+timedelta(seconds=60)),'sector':'반도체','segment':c} for c,v in h.items()]
  groups,scope=fc.group_rows(rows,h);g=next(x for x in groups if x['segment']=='319660')
  self.assertAlmostEqual(g['share_change_pp'],50);self.assertEqual(scope['common_stocks'],2)
 def test_new_entry_excluded_from_shifts(self):
  h={'319660':[sample(0,0),sample(30,100),sample(60,200)],'123456':[sample(60,99999999999,code='123456')]}
  rows=[{**fc.metrics(v,NOW+timedelta(seconds=60)),'sector':'반도체','segment':c} for c,v in h.items()]
  groups,scope=fc.group_rows(rows,h);self.assertEqual(scope['common_stocks'],1)
  new=next(x for x in groups if x['segment']=='123456');self.assertIsNone(new['interval_turnover_krw']);self.assertIsNone(new['share_pct'])
 def test_missed_batch_not_common(self):
  h={'319660':[sample(0,0),sample(30,100),sample(60,200)],'123456':[sample(-30,0,code='123456'),sample(30,100,code='123456'),sample(60,200,code='123456')]}
  rows=[{**fc.metrics(v,NOW+timedelta(seconds=60)),'sector':'반도체','segment':c} for c,v in h.items()]
  self.assertEqual(fc.group_rows(rows,h)[1]['common_stocks'],1)
 def test_candidate_requires_recent_valid_delta(self):
  rows=[{**sample(60,300),'recent_trade':False,'delta_state':'OK','interval_turnover_krw':200,
         'query_rank':1,'trade_rank':1,'burst_multiple':5,'market_theme':'AI','chart':{'state':'NEW_HIGH'}}]
  self.assertEqual(fc.candidate_watchlist(rows,{'series':[]}),[])
 def test_candidate_score_is_observation_not_trade_action(self):
  rows=[{**sample(60,300),'recent_trade':True,'delta_state':'OK','interval_turnover_krw':200,
         'five_min_turnover_krw':500,'query_rank':5,'trade_rank':7,'burst_multiple':3.5,
         'market_theme':'AI 반도체','chart':{'state':'BREAKOUT_HOLD','state_ko':'돌파 후 지지','minute_trend':'상승 유지'},
         'research':None,'research_stale':False,'event_type':None,'research_state':'ANALYSIS_PENDING'}]
  rotation={'series':[{'name':'AI 반도체','change_pp':2.0}]}
  out=fc.candidate_watchlist(rows,rotation)
  self.assertTrue(out);self.assertIn(out[0]['label'],('관찰 우선','조건 확인','추적'))
  self.assertNotIn('buy',json.dumps(out).lower());self.assertNotIn('매수',json.dumps(out))
 def test_damaged_chart_penalizes_candidate(self):
  base={**sample(60,300),'recent_trade':True,'delta_state':'OK','interval_turnover_krw':200,
        'query_rank':5,'trade_rank':7,'burst_multiple':3.5,'market_theme':'AI 반도체',
        'research':None,'research_stale':False,'event_type':None,'research_state':'ANALYSIS_PENDING'}
  good=fc.candidate_watchlist([{**base,'chart':{'state':'BREAKOUT_HOLD'}}],{'series':[]})
  bad=fc.candidate_watchlist([{**base,'chart':{'state':'BREAKOUT_FAIL'}}],{'series':[]})
  self.assertTrue(good)
  self.assertTrue((not bad) or good[0]['attention_score']>bad[0]['attention_score'])
 def test_report_not_headline_classifier(self):
  r={'text':'대한항공 기사에 HBM이 나옵니다.','citations':[{}]}
  self.assertIsNone(fc.event_from_report(r))
 def test_explicit_event_class(self):self.assertEqual(fc.event_from_report({'text':'재료분류: 수주·공급계약\n...','citations':[{}]}),'수주·공급계약')
 def test_report_section_citations(self):
  text='재료분류: 기술·제품·양산\n## 핵심 재료\n새 제품 설명 [1]\n## 새로움과 반복\n신규 여부 미확인'
  r={'text':text,'citations':[{'url':'https://example.org','start':text.index('[1]'),'end':text.index('[1]')+3}]}
  out=fc.report_sections(r);s=out['핵심 재료'];self.assertEqual(s['text'][s['citations'][0]['start']:s['citations'][0]['end']],'[1]')

class RouteTests(unittest.TestCase):
 def setUp(self):
  from fastapi import FastAPI,HTTPException
  from fastapi.responses import HTMLResponse
  from fastapi.testclient import TestClient
  import flow_routes as fr
  fr._cached=None;self.fr=fr;self.app=FastAPI()
  @self.app.get('/')
  def root():return HTMLResponse('<html><body>BASE</body></html>')
  def auth(token):
   if token!='test':raise HTTPException(401)
  fr.install(self.app,auth);self.client=TestClient(self.app)
 def test_auth_before_read(self):
  with patch('flow_store.desk_payload') as p:
   self.assertEqual(self.client.get('/api/flow-desk').status_code,401);p.assert_not_called()
 def test_failure_isolated(self):
  with patch('flow_store.desk_payload',side_effect=RuntimeError('SECRET')):
   r=self.client.get('/api/flow-desk',headers={'x-dashboard-token':'test'});self.assertEqual(r.status_code,503);self.assertNotIn('SECRET',r.text)
  self.assertEqual(self.client.get('/').status_code,200)
 def test_html_preserved(self):
  s=self.client.get('/').text;self.assertIn('BASE',s);self.assertIn('/assets/flow-desk.js',s)
 def test_cache_and_no_secret(self):
  with patch('flow_store.desk_payload',return_value={'rows':[]}) as p:
   for _ in range(2):self.assertEqual(self.client.get('/api/flow-desk',headers={'x-dashboard-token':'test'}).status_code,200)
   self.assertEqual(p.call_count,1)
 def test_invalid_chart_code(self):self.assertEqual(self.client.get('/api/flow-chart/bad',headers={'x-dashboard-token':'test'}).status_code,400)
 def test_interval_not_mixed(self):
  with patch('flow_store.chart_payload',return_value={'code':'319660'}) as p:
   self.client.get('/api/flow-chart/319660?interval=5',headers={'x-dashboard-token':'test'});p.assert_called_once_with('319660',5)

class ResearchTests(unittest.TestCase):
 def setUp(self):
  self.base=types.ModuleType('web_research_engine');self.base.make_request=lambda ctx,cfg:{'input':json.dumps({'stock_code':ctx['stock_code']}),'instructions':'BASE'}
  self.base.public_context=MagicMock();self.base.fresh_for_auto=lambda ctx,now=None:False
  self.patch=patch.dict(sys.modules,{'web_research_engine':self.base});self.patch.start()
  sys.modules.pop('flow_research_worker',None);self.m=importlib.import_module('flow_research_worker')
 def tearDown(self):self.patch.stop();sys.modules.pop('flow_research_worker',None)
 def test_auto_false_no_db_no_call(self):
  cfg=types.SimpleNamespace(automatic=False)
  with patch.object(self.m,'desk_payload') as p:self.m.auto_enqueue(cfg);p.assert_not_called()
 def test_stale_not_prioritized(self):self.assertEqual(self.m.priority({'recent_trade':False,'burst_multiple':50}),0)
 def test_no_delta_not_prioritized(self):self.assertEqual(self.m.priority({'recent_trade':True,'interval_turnover_krw':None}),0)
 def test_private_fields_not_exported(self):
  p=self.m.request({'stock_code':'319660','TELEGRAM_API_HASH':'SECRET','flow_observation':{'turnover_krw':10,'secret':'SECRET'}},None)
  self.assertNotIn('SECRET',json.dumps(p));self.assertIn('재료분류',p['instructions'])
 def test_units_not_known_are_not_added(self):
  p=self.m.request({'stock_code':'319660'},None);self.assertNotIn('flow_observation',json.loads(p['input']))
 def test_disabled_budget_no_enqueues(self):
  cfg=types.SimpleNamespace(automatic=True,gate=lambda:'READY',daily_limit=1,hourly_limit=1)
  c=MagicMock();c.__enter__.return_value=c;cur=MagicMock();cur.__enter__.return_value=cur;c.cursor.return_value=cur
  self.base.db=lambda:c;self.base.usage_count=lambda cur:{'daily':1,'hourly':0}
  with patch.object(self.m,'desk_payload') as p:self.m.auto_enqueue(cfg);p.assert_not_called()

if __name__=='__main__':unittest.main()
