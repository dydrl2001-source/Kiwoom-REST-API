"""Offline contracts; provider calls are mocked. Optional isolated PostgreSQL tests."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import market_os_budget as budget
import market_os_daily as daily
import market_os_naver as naver
import market_os_packet as packet
import market_os_risk as risk
import web_research_engine as web

NOW = datetime(2026, 10, 6, 5, 31, tzinfo=timezone.utc)


def fixture(now=NOW):
    c = dict(code='005930', name='테스트기업', watch_tier='FOCUS', trigger_state='STRUCTURE_CONFIRMED',
             market_stance='SELECTIVE', catalyst_grade='A', risk_flags=[], radar_score=90,
             theme_score=80, setup_score=70, market_theme='반도체')
    row = dict(code='005930', name='테스트기업', recent_trade=True, exchange_at=now.isoformat(),
               received_at=now.isoformat(), price_krw=100, quality_flags=[], interval_turnover_krw=3e9,
               interval_seconds=60, burst_multiple=2, leads=[dict(source='DART', kind='DART_LIST_ONLY',
               title='공급계약', at=now.date().isoformat(), url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1')])
    return dict(market_os_watchlist=[c], rows=[row], market_os_version='v1', sample_time=now.isoformat(),
                market_regime=dict(snapshot_time=now.isoformat(), candidate_trend_state='RISING',
                                   candidate_flow_state='SELECTIVE', stale=False),
                theme_rotation={'series':[{'name':'반도체','change_pp':2}]})


def facts():
    f = {k:NOW.isoformat() for k in ('price_as_of','account_as_of','session_as_of','duplicate_as_of','theme_as_of','turnover_as_of')}
    f.update(price_krw=100, reference_price_krw=100, stop_price_krw=98,
             daily_loss_pct=0, is_trading_day=True, session_open=True, theme_intact=True,
             turnover_rate_ratio=1, data_confidence=1, duplicate_order=False, quality_flags=[])
    return f


def response(advice=None):
    obj = advice or {'summary':'관망 검토', 'uncertainties':['수급 미연결'],
                     'candidate_notes':[{'code':'005930','note':'추가 검증 필요'}]}
    return {'status':'completed', 'model':'test-model', 'usage':{'input_tokens':111,'output_tokens':22,'total_tokens':133},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(obj,ensure_ascii=False)}]}]}


class RiskTests(unittest.TestCase):
    def test_pass_still_has_no_order_permission(self):
        for mode in ('shadow','manual_confirm'):
            result=risk.evaluate(fixture()['market_os_watchlist'][0],facts(),NOW,mode)
            self.assertTrue(result['review_eligible']);self.assertFalse(result['can_submit_order'])
            self.assertFalse(result['ai_can_override'])

    def test_live_auto_always_rejected(self):
        r=risk.evaluate(fixture()['market_os_watchlist'][0],facts(),NOW,'live')
        self.assertIn('LIVE_AUTO_FORBIDDEN',r['reason_codes'])

    def test_each_mandatory_gate_independently_blocks(self):
        cases=[('price_as_of',(NOW-timedelta(seconds=91)).isoformat(),'STALE_OR_MISSING_PRICE_AS_OF'),
               ('price_as_of',(NOW+timedelta(seconds=1)).isoformat(),'STALE_OR_MISSING_PRICE_AS_OF'),
               ('price_krw',102,'CHASE_LIMIT'),('stop_price_krw',90,'STOP_TOO_WIDE'),
               ('stop_price_krw',100,'STOP_INVALID'),('daily_loss_pct',2,'DAILY_LOSS_LIMIT'),
               ('theme_intact',False,'THEME_EXIT_OR_UNKNOWN'),('turnover_rate_ratio',.49,'TURNOVER_COLLAPSE_OR_UNKNOWN'),
               ('session_open',False,'ORDER_WINDOW_CLOSED_OR_UNKNOWN'),('is_trading_day',False,'ORDER_WINDOW_CLOSED_OR_UNKNOWN'),
               ('duplicate_order',True,'DUPLICATE_ORDER_OR_UNKNOWN'),('data_confidence',.89,'DATA_CONFIDENCE_LOW_OR_UNKNOWN'),
               ('quality_flags',['GAP'],'SOURCE_QUALITY_UNVERIFIED')]
        for key,value,reason in cases:
            with self.subTest(key=key,value=value):
                f=facts();f[key]=value;r=risk.evaluate(fixture()['market_os_watchlist'][0],f,NOW)
                self.assertFalse(r['review_eligible']);self.assertIn(reason,r['reason_codes'])

    def test_all_missing_facts_fail_closed(self):
        self.assertFalse(risk.evaluate(fixture()['market_os_watchlist'][0],{},NOW)['review_eligible'])
        for key in facts():
            with self.subTest(key=key):
                f=facts();del f[key]
                self.assertFalse(risk.evaluate(fixture()['market_os_watchlist'][0],f,NOW)['review_eligible'])

    def test_nonfinite_and_bool_numbers_fail(self):
        for field in ('price_krw','reference_price_krw','stop_price_krw','daily_loss_pct','turnover_rate_ratio','data_confidence'):
            for bad in (float('nan'),float('inf'),True):
                f=facts();f[field]=bad
                with self.subTest(field=field,bad=bad):
                    self.assertFalse(risk.evaluate(fixture()['market_os_watchlist'][0],f,NOW)['review_eligible'])

    def test_expired_account_state_cannot_be_refreshed_by_new_price(self):
        f=facts();f['account_as_of']=(NOW-timedelta(minutes=3)).isoformat()
        self.assertIn('STALE_OR_MISSING_ACCOUNT_AS_OF',risk.evaluate(fixture()['market_os_watchlist'][0],f,NOW)['reason_codes'])

    def test_boundaries_and_rule_overrides(self):
        c=fixture()['market_os_watchlist'][0]
        for field,value in [('watch_tier','BLOCKED'),('trigger_state','WAIT_PULLBACK'),('market_stance','UNKNOWN'),('catalyst_grade','C')]:
            self.assertFalse(risk.evaluate({**c,field:value},facts(),NOW)['review_eligible'])
        f=facts();f['data_confidence']=1.1
        self.assertFalse(risk.evaluate(c,f,NOW)['review_eligible'])
        for t in (NOW.replace(hour=0,minute=4),NOW.replace(hour=6,minute=20)):
            self.assertIn('ORDER_WINDOW_CLOSED_OR_UNKNOWN',risk.evaluate(c,f,t)['reason_codes'])

    def test_ai_fields_never_affect_gate(self):
        c=fixture()['market_os_watchlist'][0];c['ai_override']=True;c['can_submit_order']=True
        self.assertFalse(risk.evaluate(c,{},NOW)['can_submit_order'])
        self.assertEqual(risk.observation_facts({'execution_risk':facts()})['price_krw'],None)


class PacketTests(unittest.TestCase):
    def test_packet_real_fields_nulls_and_no_ai(self):
        p=packet.build_packet(fixture(),NOW);c=p['candidates'][0]
        self.assertEqual(p['status'],'READY');self.assertEqual(p['market_stance'],'SELECTIVE')
        for key in ('radar','theme','setup','catalyst','trigger','risk','turnover','foreign','institution','catalyst_evidence','naver_search_context'):
            self.assertIn(key,c)
        self.assertIsNone(c['foreign']['net_buy_krw']);self.assertEqual(c['turnover']['interval_seconds'],60)
        self.assertFalse(c['execution_risk_gate']['can_submit_order'])
        self.assertLessEqual(len(packet.compact(p).encode()),packet.MAX_BYTES)

    def test_deterministic_snapshot_and_identity(self):
        self.assertEqual(packet.build_packet(fixture(),NOW),packet.build_packet(fixture(),NOW))
        self.assertNotEqual(packet.build_packet(fixture(),NOW)['packet_id'],packet.build_packet(fixture(),NOW+timedelta(seconds=1))['packet_id'])

    def test_stale_exchange_even_when_ingestion_new(self):
        f=fixture();f['rows'][0]['exchange_at']=(NOW-timedelta(days=1)).isoformat()
        p=packet.build_packet(f,NOW);self.assertEqual(p['status'],'INSUFFICIENT_DATA');self.assertEqual(p['candidates'],[])

    def test_stale_regime_prevents_ready(self):
        f=fixture();f['market_regime']['snapshot_time']=(NOW-timedelta(minutes=10)).isoformat()
        p=packet.build_packet(f,NOW);self.assertEqual(p['market_stance'],'UNKNOWN');self.assertEqual(p['status'],'INSUFFICIENT_DATA')

    def test_private_and_naver_result_content_never_exported(self):
        f=fixture();f['account']='PRIVATE';f['naver_search_context']={'items':['FORBIDDEN']}
        f['rows'][0]['naver_results']={'items':['FORBIDDEN']}
        f['rows'][0]['leads'].append({'source':'NAVER','title':'FORBIDDEN','kind':'NEWS_TITLE_ONLY'})
        f['market_os_watchlist'][0]['api_key']='PRIVATE'
        s=packet.compact(packet.make_ai_request(packet.build_packet(f,NOW),'test'))
        self.assertNotIn('FORBIDDEN',s);self.assertNotIn('PRIVATE',s)
        self.assertNotIn('tools',packet.make_ai_request(packet.build_packet(f,NOW),'test'))

    def test_dart_only_future_evidence_excluded(self):
        f=fixture();f['rows'][0]['leads'][0]['at']='2030-01-01'
        self.assertEqual(packet.build_packet(f,NOW)['candidates'][0]['catalyst_evidence'],[])
        f['rows'][0]['leads'][0]['url']='https://evil.example/';f['rows'][0]['leads'][0]['at']='2026-10-05'
        self.assertEqual(packet.build_packet(f,NOW)['candidates'][0]['catalyst_evidence'],[])

    def test_top_five_unique_rule_order_and_bounded_korean(self):
        f=fixture();c=f['market_os_watchlist'][0];r=f['rows'][0]
        f['market_os_watchlist']=[];f['rows']=[]
        for n in range(12):
            code=f'{n:06d}';f['market_os_watchlist'].append({**c,'code':code,'name':'가'*500})
            f['rows'].append({**r,'code':code})
        f['market_os_watchlist'].insert(1,f['market_os_watchlist'][0])
        p=packet.build_packet(f,NOW,500)
        self.assertEqual([c['code'] for c in p['candidates']],[f'{n:06d}' for n in range(5)])
        self.assertLessEqual(len(packet.compact(p).encode()),packet.MAX_BYTES)

    def test_nonfinite_is_null(self):
        f=fixture();f['rows'][0]['price_krw']=float('nan')
        self.assertIsNone(packet.build_packet(f,NOW)['candidates'][0]['price_krw'])

    def test_kst_window_edges_weekend_and_midnight_budget(self):
        self.assertTrue(packet.in_window(NOW.replace(minute=30)))
        self.assertFalse(packet.in_window(NOW.replace(minute=29)))
        self.assertFalse(packet.in_window(NOW.replace(minute=40)))
        self.assertFalse(packet.in_window(NOW.replace(day=10)))
        a=NOW.replace(hour=14,minute=59);b=NOW.replace(hour=15,minute=0)
        self.assertNotEqual(budget.budget_day(a),budget.budget_day(b))
        with self.assertRaises(ValueError):budget.budget_day(NOW.replace(tzinfo=None))

    def test_advice_strict_schema_code_and_no_authority(self):
        p=packet.build_packet(fixture(),NOW)
        self.assertFalse(packet.parse_advice(response(),p)['can_submit_order'])
        for obj in ({'summary':'BUY','orders':[]}, {'summary':'x','uncertainties':[],'candidate_notes':[{'code':'999999','note':'x'}]},
                    {'summary':'x','uncertainties':[],'candidate_notes':[{'code':'005930','note':'x','quantity':1}]}):
            with self.subTest(obj=obj),self.assertRaises(ValueError):packet.parse_advice(response(obj),p)

    def test_worker_outside_window_no_db_no_network(self):
        with patch.object(daily,'ensure_schema') as db,patch.object(daily,'request_openai') as api:
            self.assertEqual(daily.run_once(NOW.replace(minute=40)), 'OUTSIDE_DECISION_WINDOW')
            db.assert_not_called();api.assert_not_called()


class NaverTests(unittest.TestCase):
    def cfg(self,provider='hub'):return naver.Config(True,provider,'client-id','private-secret',5)

    def test_disabled_or_bad_input_makes_no_network_call(self):
        with patch('requests.get') as get:
            self.assertEqual(naver.search('news','test',naver.Config())['status'],'DISABLED')
            self.assertEqual(naver.search('shopping','test',self.cfg())['status'],'INVALID_SEARCH')
            self.assertEqual(naver.search('news','x'*101,self.cfg())['status'],'INVALID_SEARCH')
            get.assert_not_called()

    def test_official_hosts_headers_webkr_no_sort_and_order_preserved(self):
        results={'items':[{'title':'B','link':'https://example.com/b'},{'title':'A','link':'https://example.com/a'}]}
        for provider in ('hub','legacy'):
            with self.subTest(provider=provider),patch.object(naver,'reserve',return_value=('NAVER',NOW.date(),1)),patch.object(naver,'finish') as done,patch('requests.get',return_value=Mock(status_code=200,json=lambda:results)) as get:
                d=naver.search('webkr','테스트기업',self.cfg(provider))
                self.assertEqual(d['results'],results);self.assertFalse(d['ai_export_allowed'])
                self.assertNotIn('sort',get.call_args.kwargs['params']);self.assertFalse(get.call_args.kwargs['allow_redirects'])
                self.assertIn('naverapihub.apigw.ntruss.com' if provider=='hub' else 'openapi.naver.com',get.call_args.args[0])
                self.assertNotIn('private-secret',json.dumps(d));self.assertNotIn('data',done.call_args.kwargs)

    def test_error_status_and_quota_no_retry(self):
        for code,status in [(403,'NAVER_PERMISSION_DENIED'),(429,'NAVER_QUOTA_EXCEEDED'),(500,'NAVER_HTTP_ERROR')]:
            with patch.object(naver,'reserve',return_value=('NAVER',NOW.date(),1)),patch.object(naver,'finish'),patch('requests.get',return_value=Mock(status_code=code)) as get:
                self.assertEqual(naver.search('news','test',self.cfg())['status'],status);self.assertEqual(get.call_count,1)
        with patch.object(naver,'reserve',side_effect=budget.BudgetError('DAILY_BUDGET_USED')),patch('requests.get') as get:
            self.assertEqual(naver.search('news','test',self.cfg())['status'],'DAILY_BUDGET_USED');get.assert_not_called()

    def test_news_sort_and_bad_response(self):
        with patch.object(naver,'reserve',return_value=('NAVER',NOW.date(),1)),patch.object(naver,'finish'),patch('requests.get',return_value=Mock(status_code=200,json=lambda:[])) as get:
            self.assertEqual(naver.search('news','test',self.cfg())['status'],'NAVER_INVALID_RESPONSE')
            self.assertEqual(get.call_args.kwargs['params']['sort'],'date')

    def test_safe_generated_human_links(self):
        c=naver.verification_context('005930','테스트 &기업')
        self.assertIn('code=005930',c['finance_url']);self.assertFalse(c['result_content_included'])
        with self.assertRaises(ValueError):naver.verification_context('../bad','x')


class BudgetUnitTests(unittest.TestCase):
    def test_fail_closed_no_network_when_store_unavailable(self):
        with patch.object(budget,'ensure_schema',side_effect=RuntimeError('secret')),patch('requests.post') as post:
            with self.assertRaisesRegex(budget.BudgetError,'BUDGET_STORE_UNAVAILABLE'):
                budget.request_openai({'model':'test'},'key','TEST')
            post.assert_not_called()

    def test_request_single_attempt_redirects_disabled_failure_recorded(self):
        import requests
        with patch.object(budget,'reserve',return_value=('OPENAI',NOW.date(),1)),patch.object(budget,'finish') as finish,patch('requests.post',side_effect=requests.Timeout('SECRET')) as post:
            with self.assertRaisesRegex(budget.BudgetError,'NETWORK_OR_TIMEOUT_UNCERTAIN'):
                budget.request_openai({'model':'test'},'key','TEST')
            self.assertEqual(post.call_count,1);self.assertFalse(post.call_args.kwargs['allow_redirects'])
            self.assertEqual(finish.call_args.args[1],'FAILED');self.assertNotIn('SECRET',str(finish.call_args))

    def test_old_research_calls_shared_budget(self):
        cfg=web.Config.read({'WEB_RESEARCH_ENABLED':'1','OPENAI_API_KEY':'test','WEB_RESEARCH_MODEL':'test','WEB_RESEARCH_DAILY_LIMIT':'99'})
        self.assertEqual(cfg.daily_limit,1)
        with patch.object(budget,'request_openai',side_effect=budget.BudgetError('DAILY_BUDGET_USED')) as call:
            with self.assertRaisesRegex(web.ResearchError,'DAILY_BUDGET_USED'):web.call_model({},cfg)
            self.assertEqual(call.call_args.args[2],'WEB_RESEARCH')


# Explicit disposable DB only. Never use DATABASE_URL by itself for test cleanup.
TEST_DB = os.environ.get('MARKET_OS_TEST_DATABASE_URL','')
@unittest.skipUnless(TEST_DB and TEST_DB.rsplit('/',1)[-1]=='market_os_test','isolated PostgreSQL not configured')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'DATABASE_URL':TEST_DB});self.env.start()
        daily.ensure_schema()
        with budget.db() as c:c.execute('TRUNCATE market_os_api_attempts,market_os_daily_packets')
    def tearDown(self):self.env.stop()

    def test_concurrent_separate_connections_only_one_reservation(self):
        def attempt(_):
            try:budget.reserve('OPENAI','RACE',limit=999);return 'RESERVED'
            except budget.BudgetError as e:return str(e)
        with ThreadPoolExecutor(max_workers=10) as pool:out=list(pool.map(attempt,range(10)))
        self.assertEqual(out.count('RESERVED'),1);self.assertEqual(out.count('DAILY_BUDGET_USED'),9)

    def test_database_unique_index_prevents_second_openai_slot(self):
        import psycopg
        budget.reserve('OPENAI','FIRST')
        with self.assertRaises(psycopg.errors.UniqueViolation),budget.db() as c:
            c.execute("INSERT INTO market_os_api_attempts(provider,budget_day,slot,attempted_at,reason) "
                      "SELECT provider,budget_day,2,attempted_at,'SECOND' FROM market_os_api_attempts WHERE provider='OPENAI'")

    def test_old_attempt_migration_consumes_today_before_new_worker(self):
        with budget.db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS web_research_runs (attempted_at TIMESTAMPTZ,model TEXT)")
            c.execute("INSERT INTO web_research_runs VALUES (clock_timestamp(),'old-model')")
            c.execute("DELETE FROM market_os_budget_migrations WHERE name='legacy-openai-v1'")
        try:
            with self.assertRaisesRegex(budget.BudgetError,'DAILY_BUDGET_USED'):
                budget.reserve('OPENAI','NEW_DAILY')
            self.assertEqual(budget.status_today()[0]['status'],'LEGACY_CONSUMED')
        finally:
            with budget.db() as c:c.execute('DROP TABLE web_research_runs')

    def test_successful_ai_is_separate_from_immutable_rules(self):
        env={'MARKET_OS_DAILY_AI_ENABLED':'1','OPENAI_API_KEY':'test','MARKET_OS_DAILY_AI_MODEL':'test'}
        with patch.object(daily,'datetime') as clock,patch.object(daily,'request_openai',return_value=response()):
            clock.now.return_value=NOW
            self.assertEqual(daily.run_once(NOW,fixture(),env),'ADVISORY_READY')
        saved=daily.latest()
        self.assertEqual(saved['packet'],packet.build_packet(fixture(),NOW))
        self.assertFalse(saved['advice']['can_submit_order'])

    def test_non_json_advice_falls_back_without_touching_rules(self):
        data=response();data['output'][0]['content'][0]['text']='not json'
        env={'MARKET_OS_DAILY_AI_ENABLED':'1','OPENAI_API_KEY':'test','MARKET_OS_DAILY_AI_MODEL':'test'}
        with patch.object(daily,'datetime') as clock,patch.object(daily,'request_openai',return_value=data):
            clock.now.return_value=NOW
            self.assertEqual(daily.run_once(NOW,fixture(),env),'RULES_ONLY')
        self.assertEqual(daily.latest()['error_code'],'INVALID_ADVICE')

    def test_timeout_consumes_quota_across_clients(self):
        import requests
        with patch('requests.post',side_effect=requests.Timeout) as post:
            with self.assertRaises(budget.BudgetError):budget.request_openai({'model':'test'},'test','DAILY_DECISION_PACKET')
            with self.assertRaisesRegex(budget.BudgetError,'DAILY_BUDGET_USED'):budget.request_openai({'model':'other'},'test','WEB_RESEARCH')
            self.assertEqual(post.call_count,1)
        rows=budget.status_today();self.assertEqual(rows[0]['status'],'FAILED');self.assertIsNone(rows[0]['total_tokens'])

    def test_success_audit_tokens_model_reason_summary(self):
        with patch('requests.post',return_value=Mock(status_code=200,json=lambda:response())):
            budget.request_openai({'model':'test-request-model'},'test','DAILY_DECISION_PACKET')
        r=budget.status_today()[0]
        self.assertEqual(r['total_tokens'],133);self.assertEqual(r['input_tokens'],111)
        self.assertEqual(r['model'],'test-request-model');self.assertEqual(r['response_model'],'test-model')
        self.assertEqual(r['reason'],'DAILY_DECISION_PACKET');self.assertIn('관망',r['response_summary'])
        self.assertIsNotNone(r['attempted_at']);self.assertIsNotNone(r['completed_at'])

    def test_reserved_process_crash_never_refunded_and_prior_day_not_blocking(self):
        ticket=budget.reserve('OPENAI','CRASH')
        with self.assertRaisesRegex(budget.BudgetError,'DAILY_BUDGET_USED'):budget.reserve('OPENAI','RESTART')
        with budget.db() as c:c.execute("UPDATE market_os_api_attempts SET budget_day=budget_day-1")
        next_ticket=budget.reserve('OPENAI','NEXT_DAY')
        self.assertEqual(next_ticket,ticket)
        with budget.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) AS n FROM market_os_api_attempts').fetchone()['n'],2)

    def test_naver_quota_aggregate_separate_from_openai(self):
        budget.reserve('NAVER','NEWS',limit=2);budget.reserve('NAVER','BLOG',limit=2)
        with self.assertRaisesRegex(budget.BudgetError,'DAILY_BUDGET_USED'):budget.reserve('NAVER','WEBKR',limit=2)
        budget.reserve('OPENAI','DAILY')
        self.assertEqual(len(budget.status_today()),3)

    def test_naver_cooldown(self):
        budget.reserve('NAVER','NEWS',limit=100,min_interval=1)
        with self.assertRaisesRegex(budget.BudgetError,'API_COOLDOWN'):budget.reserve('NAVER','BLOG',limit=100,min_interval=1)

    def test_packet_created_once_even_with_ai_disabled(self):
        with patch.object(daily,'request_openai') as call:
            self.assertEqual(daily.run_once(NOW,fixture(),{}),'RULES_ONLY')
            self.assertEqual(daily.run_once(NOW,fixture(),{}),'DAILY_PACKET_EXISTS');call.assert_not_called()
        self.assertEqual(daily.latest()['packet']['candidates'][0]['code'],'005930')

    def test_packet_race_only_one_winner(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            out=list(pool.map(lambda _:daily.run_once(NOW,fixture(),{}),range(4)))
        self.assertEqual(out.count('RULES_ONLY'),1)
        self.assertEqual(out.count('DAILY_PACKET_EXISTS'),3)

    def test_invalid_or_failed_ai_keeps_rules_and_never_retries(self):
        env={'MARKET_OS_DAILY_AI_ENABLED':'1','OPENAI_API_KEY':'test','MARKET_OS_DAILY_AI_MODEL':'test'}
        with patch.object(daily,'datetime') as clock,patch.object(daily,'request_openai',side_effect=budget.BudgetError('TIMEOUT_UNCERTAIN')) as api:
            clock.now.return_value=NOW
            self.assertEqual(daily.run_once(NOW,fixture(),env),'RULES_ONLY')
            self.assertEqual(daily.run_once(NOW,fixture(),env),'DAILY_PACKET_EXISTS');self.assertEqual(api.call_count,1)
        saved=daily.latest();self.assertEqual(saved['error_code'],'TIMEOUT_UNCERTAIN');self.assertTrue(saved['packet']['candidates'])

    def test_stale_holiday_feed_no_packet_no_ai(self):
        f=fixture();f['rows'][0]['exchange_at']=(NOW-timedelta(days=3)).isoformat()
        with patch.object(daily,'request_openai') as api:
            self.assertEqual(daily.run_once(NOW,f,{}),'WAITING_FOR_FRESH_RULE_CANDIDATES');api.assert_not_called()
        self.assertNotIn('packet',daily.latest())



class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from market_os_routes import install
        app=FastAPI()
        def authorize(token):
            if token!='test-token':raise HTTPException(401,'UNAUTHORIZED')
        install(app,authorize)
        self.client=TestClient(app)
        self.headers={'X-Dashboard-Token':'test-token'}

    def test_protected_routes_reject_before_db_or_network(self):
        with patch.object(naver,'search') as search,patch.object(daily,'latest') as latest:
            for url in ('/api/market-os/daily-decision','/api/market-os/decision-preview'):
                self.assertEqual(self.client.get(url).status_code,401)
            self.assertEqual(self.client.post('/api/market-os/naver-search?query=test').status_code,401)
            search.assert_not_called();latest.assert_not_called()

    def test_read_only_views_do_not_call_ai(self):
        with patch.object(daily,'latest',return_value={'status':'RULES_ONLY','packet':packet.build_packet(fixture(),NOW)}),patch.object(budget,'status_today',return_value=[]),patch.object(budget,'request_openai') as ai:
            r=self.client.get('/api/market-os/daily-decision',headers=self.headers)
            self.assertEqual(r.status_code,200);self.assertEqual(r.headers['cache-control'],'no-store')
            self.assertFalse(r.json()['live_auto_execution']);ai.assert_not_called()

    def test_search_requires_explicit_post_and_no_cache(self):
        self.assertEqual(self.client.get('/api/market-os/naver-search?query=test',headers=self.headers).status_code,405)
        with patch.object(naver,'search',return_value={'status':'DISABLED'}) as search:
            r=self.client.post('/api/market-os/naver-search?query=test&kind=blog',headers=self.headers)
            self.assertEqual(r.headers['cache-control'],'no-store');search.assert_called_once_with('blog','test')

    def test_no_order_or_ai_trigger_routes_and_static_view(self):
        self.assertEqual(self.client.post('/api/market-os/order',headers=self.headers).status_code,404)
        self.assertEqual(self.client.post('/api/market-os/daily-decision',headers=self.headers).status_code,405)
        self.assertEqual(self.client.get('/market-os/decision').status_code,200)
        js=self.client.get('/assets/market-os-decision.js').text
        self.assertNotIn('innerHTML',js);self.assertNotIn('localStorage.setItem',js)

class PolicySyncTests(unittest.TestCase):
    def test_rulebook_risk_defaults_match_code(self):
        rules=json.loads((ROOT/'rulebook/market_os_rules.json').read_text())
        for key,value in risk.POLICY.items():self.assertEqual(rules['execution_risk_gate'][key],value)

    def test_legacy_firewall_nonfinite_sample_age_blocked(self):
        import market_os_execution as ex
        for age in (float('nan'),float('inf')):
            self.assertIn('STALE_SAMPLE',ex.evaluate({}, {}, 'HEALTHY',age)['reason_codes'])


if __name__=='__main__':unittest.main()
