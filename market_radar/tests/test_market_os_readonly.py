import copy
from datetime import datetime, timezone
import json
import os
import unittest
from unittest.mock import patch, Mock

from market_os_readonly import Client, ReadError, collect, enrich_payload, investor_context, numeric
from market_os_packet import investor_fact
from market_os_risk import observation_facts, evaluate

NOW = datetime(2026, 10, 5, 5, 35, tzinfo=timezone.utc)
ENV = {'KIWOOM_MODE':'real', 'APP_KEY':'test-key', 'APP_SECRET':'test-secret'}


def response(data, continuation='N', key=''):
    return Mock(status_code=200, json=lambda:data, headers={'cont-yn':continuation,'next-key':key})


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch('market_os_readonly.time.sleep').start()
        self.http = Mock()
        self.client = Client(ENV, self.http)
    def tearDown(self):
        patch.stopall()
    def test_orders_rejected_before_auth(self):
        for api in ['kt10000','kt10001','kt10002','kt10003','anything']:
            with self.assertRaisesRegex(ReadError,'READ_ONLY_API_REQUIRED'):
                self.client.read(api,{})
        self.http.post.assert_not_called()
    def test_redirect_denied(self):
        self.http.post.return_value = Mock(status_code=302)
        with self.assertRaisesRegex(ReadError,'HTTP_302'):
            self.client.read('ka10075',{})
        self.assertFalse(self.http.post.call_args.kwargs['allow_redirects'])
    def test_fixed_origin(self):
        c=Client({**ENV,'KIWOOM_BASE_URL':'https://evil.invalid'},self.http)
        self.assertEqual(c.base,'https://api.kiwoom.com')
    def test_mock_requires_separate_keys(self):
        with self.assertRaisesRegex(ReadError,'KEYS_MISSING'):
            Client({**ENV,'KIWOOM_MODE':'mock'})
    def test_complete_pagination(self):
        self.http.post.side_effect=[response({'return_code':0,'token':'test'}),
            response({'return_code':0,'oso':[{'x':1}]},'Y','next'),
            response({'return_code':0,'oso':[{'x':2}]})]
        d=self.client.read('ka10075',{})
        self.assertEqual(len(d['oso']),2)
    def test_missing_list_not_empty(self):
        self.client.token='test'
        self.http.post.return_value=response({'return_code':0})
        with self.assertRaisesRegex(ReadError,'ROWS_MISSING'):
            self.client.read('ka10075',{})
    def test_missing_continuation_is_unknown(self):
        self.client.token='test'
        self.http.post.return_value=Mock(status_code=200,json=lambda:{'return_code':0,'oso':[]},headers={})
        with self.assertRaisesRegex(ReadError,'INCOMPLETE_PAGINATION'):
            self.client.read('ka10075',{})
    def test_repeated_cursor_blocks(self):
        self.client.token='test'
        self.http.post.return_value=response({'return_code':0,'oso':[]},'Y','same')
        with self.assertRaisesRegex(ReadError,'INCOMPLETE_PAGINATION'):
            self.client.read('ka10075',{})
    def test_exhausted_pages_blocks(self):
        self.client.token='test'
        self.http.post.return_value=response({'return_code':0,'oso':[]},'Y','next')
        with self.assertRaisesRegex(ReadError,'INCOMPLETE_PAGINATION'):
            self.client.read('ka10075',{},max_pages=1)
    def test_error_body_not_exposed(self):
        self.client.token='test'
        self.http.post.return_value=response({'return_code':1,'return_msg':'secret-account'})
        with self.assertRaisesRegex(ReadError,'^KIWOOM_API_REJECTED$'):
            self.client.read('ka10075',{})


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.data={
            'ka10059':{'stk_invsr_orgn':[{'dt':'20261002','frgnr_invsr':'-123','orgn':'+45'}]},
            'kt00018':{'prsm_dpst_aset_amt':'1000000','tot_evlt_amt':'500000','tot_evlt_pl':'-10000',
                       'tot_loan_amt':'0','acnt_evlt_remn_indv_tot':[{'acnt_no':'SECRET_ACCOUNT'}]},
            'ka10074':{'dt_rlzt_pl':[{'dt':'20261002','tdy_sel_pl':'9999'}]},
            'ka10075':{'oso':[{'stk_cd':'A005930','oso_qty':'1','ord_no':'SECRET_ORDER','acnt_no':'SECRET_ACCOUNT'}]},
            'kt00017':{'d2_entra':'100000'}}
        self.client=Mock(read=lambda aid,body:copy.deepcopy(self.data[aid]))
        self.client.mode='real'
    def test_amount_units_date_preserved(self):
        out=collect(['005930'],self.client,NOW)
        f=out['investor']['005930']['foreign']
        self.assertEqual(f['net_buy_krw'],-123000000)
        self.assertEqual(f['as_of'],'2026-10-02')
        self.assertEqual(f['status'],'PRIOR_SESSION_CONTEXT')
    def test_future_ignored(self):
        self.data['ka10059']['stk_invsr_orgn'].insert(0,{'dt':'20261006','frgnr_invsr':'500'})
        f=collect(['005930'],self.client,NOW)['investor']['005930']['foreign']
        self.assertEqual(f['as_of'],'2026-10-02')
    def test_sensitive_identifiers_removed(self):
        out=collect(['005930'],self.client,NOW)
        self.assertNotIn('SECRET',json.dumps(out))
        self.assertEqual(out['account']['unfilled_codes'],['005930'])
    def test_prior_day_realized_not_today(self):
        a=collect([],self.client,NOW)['account']
        self.assertIsNone(a['realized_pl_krw'])
        self.assertIsNone(a['daily_loss_pct'])
    def test_invalid_unfilled_does_not_assert_clear(self):
        self.data['ka10075']['oso'][0]['oso_qty']=''
        out=collect([],self.client,NOW)
        self.assertNotIn('unfilled_complete',out['account'])
        self.assertIn('unfilled',out['errors'])
    def test_request_limit(self):
        with self.assertRaisesRegex(ReadError,'INVALID_CODES'):
            collect(['005930']*6,self.client,NOW)
    def test_null_is_not_zero(self):
        for value in ['',None,True,'NaN','Infinity','bad','1e99999']:
            self.assertIsNone(numeric(value))
    def test_enrichment_never_includes_account_values(self):
        snap=collect(['005930'],self.client,NOW)
        p=enrich_payload({'rows':[{'code':'005930'}]},snap)
        txt=json.dumps(p)
        self.assertNotIn('estimated_assets_krw',txt)
        self.assertNotIn('unrealized_pl_krw',txt)
        self.assertIsNone(p['rows'][0]['readonly_risk_facts']['duplicate_order'])
    def test_complete_empty_unfilled_can_be_clear(self):
        self.data['ka10075']['oso']=[]
        now=datetime.now(timezone.utc)
        snap=collect([],self.client,now)
        row=enrich_payload({'rows':[{'code':'005930'}]},snap)['rows'][0]
        self.assertIs(row['readonly_risk_facts']['duplicate_order'],False)
        self.assertIsNone(observation_facts(row)['daily_loss_pct'])
        self.assertFalse(evaluate({},observation_facts(row))['can_submit_order'])
    def test_mock_facts_not_imported_as_real(self):
        self.client.mode='mock'
        snap=collect(['005930'],self.client,datetime.now(timezone.utc))
        row=enrich_payload({'rows':[{'code':'005930'}]},snap)['rows'][0]
        self.assertEqual(row['investor_context'],{})
        self.assertIsNone(row['readonly_risk_facts']['account_as_of'])
    def test_packet_whitelist(self):
        snap=collect(['005930'],self.client,NOW)
        f=snap['investor']['005930']['foreign']
        f['account']='DO_NOT_EXPORT'
        out=investor_fact({'investor_context':snap['investor']['005930']},'foreign',NOW)
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(out))
        self.assertFalse(out['is_intraday_trigger'])


class RouteTests(unittest.TestCase):
    def test_readonly_routes_require_auth(self):
        from fastapi.testclient import TestClient
        from market_os_readonly_app import app
        with patch.dict(os.environ,{'DASHBOARD_TOKEN':'private'}):
            c=TestClient(app)
            self.assertEqual(c.get('/api/market-os/readonly-context').status_code,401)
            self.assertEqual(c.post('/api/market-os/readonly-refresh').status_code,401)
            self.assertEqual(c.post('/api/market-os/readonly-refresh?codes=bad',headers={'X-Dashboard-Token':'private'}).status_code,400)
    def test_authenticated_response_is_not_cached(self):
        from fastapi.testclient import TestClient
        from market_os_readonly_app import app
        with patch.dict(os.environ,{'DASHBOARD_TOKEN':'private'}),patch('market_os_readonly.latest',return_value={'orders_sent':0}):
            r=TestClient(app).get('/api/market-os/readonly-context',headers={'X-Dashboard-Token':'private'})
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.headers['cache-control'],'no-store')

if __name__=='__main__':unittest.main()
