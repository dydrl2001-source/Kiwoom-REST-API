"""Offline tests: no real Postgres, model calls, or user credentials."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import report_library as lib
NOW=datetime(2026,9,27,0,0,tzinfo=timezone.utc)
TEXT='핵심 재료\n시험 회사의 공개 자료입니다. [출처]'
REPORT={'text':TEXT,'web_tool_calls':1,'citations':[{'start':TEXT.index('[출처]'),'end':len(TEXT),'url':'https://example.org/report','title':'시험 출처'}]}

def record(**kw):
    r={'id':2,'stock_code':'123456','stock_name':'시험기업','status':'ERROR','error_code':'AUTH_FAILED','created_at':NOW,
       'report_id':1,'completed_at':NOW-timedelta(hours=7),'model':'test-model','report':REPORT,
       'market_collected_at':NOW.isoformat(),'price_bar_at':None,'OPENAI_API_KEY':'NEVER-PRINT'}
    r.update(kw);return r

class ShapeTests(unittest.TestCase):
    def test_saved_success_survives_later_failure(self):
        x=lib.present(record(),NOW);self.assertEqual(x['latest_state'],'ERROR');self.assertTrue(x['report']);self.assertEqual(x['report_id'],1)
    def test_no_private_fields(self):
        self.assertNotIn('NEVER-PRINT',json.dumps(lib.present(record(),NOW)))
    def test_unknown_error_redacted(self):
        self.assertEqual(lib.present(record(error_code='sk-secret'),NOW)['latest_error'],'OTHER_ERROR')
    def test_missing_report_is_not_success(self):
        self.assertIsNone(lib.present(record(report=None),NOW)['report'])
    def test_invalid_stock(self):
        self.assertIsNone(lib.present(record(stock_code='<script>'),NOW))
    def test_historical(self):
        self.assertTrue(lib.present(record(),NOW)['older_than_6h'])
    def test_future_time_not_fresh(self):
        self.assertIsNone(lib.present(record(completed_at=NOW+timedelta(days=1)),NOW)['report_age_sec'])
    def test_no_citation_no_report(self):
        self.assertIsNone(lib.clean_report(dict(REPORT,citations=[])))
    def test_no_search_no_report(self):
        self.assertIsNone(lib.clean_report(dict(REPORT,web_tool_calls=0)))
    def test_bad_offsets(self):
        self.assertIsNone(lib.clean_report(dict(REPORT,citations=[dict(REPORT['citations'][0],end=99999)])))
    def test_unsafe_link(self):
        for u in ['javascript:alert(1)','http://127.0.0.1/','https://user:pass@example.org/','http://169.254.169.254/','http://internal.local/']:
            self.assertIsNone(lib.public_link(u))
    def test_body_preserved_not_interpreted(self):
        text=TEXT+'<img src=x onerror=alert(1)>'
        self.assertEqual(lib.clean_report(dict(REPORT,text=text))['text'],text)
    def test_timestamp_unknown(self):
        for x in ['x','2026-09-27',datetime(2026,9,27),None]:self.assertIsNone(lib.stamp(x))
    def test_usage_and_extra_fields_omitted(self):
        r=lib.clean_report(dict(REPORT,usage={'secret':'bad'},secret='bad'))
        self.assertNotIn('bad',json.dumps(r))

class DatabaseTests(unittest.TestCase):
    def test_read_only_query_no_schema_or_update(self):
        cursor=MagicMock();cursor.__enter__.return_value=cursor
        cursor.fetchone.return_value={'name':'web_research_runs'};cursor.fetchall.return_value=[record()]
        conn=MagicMock();conn.__enter__.return_value=conn;conn.cursor.return_value=cursor
        pg=types.ModuleType('psycopg');pg.connect=MagicMock(return_value=conn)
        rows=types.ModuleType('psycopg.rows');rows.dict_row=object()
        with patch.dict(sys.modules,{'psycopg':pg,'psycopg.rows':rows}),patch.dict(os.environ,{'DATABASE_URL':'test'}):
            d=lib.library_payload()
        sql=[x.args[0] for x in cursor.execute.call_args_list]
        self.assertEqual(sql[0],'SET TRANSACTION READ ONLY')
        self.assertEqual(len(sql),3)
        self.assertEqual(d['mode'],'READ_ONLY')
        for s in sql:
            for banned in ['INSERT INTO','DELETE FROM','UPDATE web_','CREATE TABLE']:
                self.assertNotIn(banned,s)
    def test_missing_storage_returns_empty(self):
        cur=MagicMock();cur.__enter__.return_value=cur;cur.fetchone.return_value={'name':None}
        conn=MagicMock();conn.__enter__.return_value=conn;conn.cursor.return_value=cur
        pg=types.ModuleType('psycopg');pg.connect=MagicMock(return_value=conn)
        rows=types.ModuleType('psycopg.rows');rows.dict_row=object()
        with patch.dict(sys.modules,{'psycopg':pg,'psycopg.rows':rows}),patch.dict(os.environ,{'DATABASE_URL':'test'}):
            d=lib.library_payload()
        self.assertEqual(d['storage'],'NOT_INITIALIZED');self.assertEqual(d['entries'],[])
        self.assertEqual(cur.execute.call_count,2)

class RouteTests(unittest.TestCase):
    def setUp(self):
        base=types.ModuleType('radar_api');base.app=FastAPI();base.DASHBOARD_HTML_V2='<html><body></body></html>';base.DASHBOARD_HTML=base.DASHBOARD_HTML_V2
        base.app.add_api_route('/health',lambda:{'status':'ok'});base.app.add_api_route('/',lambda:'old')
        wr=types.ModuleType('web_research_engine');wr.Config=MagicMock();wr.ResearchError=type('ResearchError',(Exception,),{});wr.enqueue=MagicMock();wr.ensure_schema=MagicMock();wr.status_payload=MagicMock()
        spec=importlib.util.spec_from_file_location('report_test_app',ROOT/'radar_web_app.py');self.app=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'radar_api':base,'web_research_engine':wr}):spec.loader.exec_module(self.app)
        self.client=TestClient(self.app.app);self.wr=wr
        self.env=patch.dict(os.environ,{'DASHBOARD_TOKEN':'TEST-ONLY'});self.env.start()
    def tearDown(self):self.env.stop()
    def test_auth_before_data_read(self):
        with patch.object(lib,'library_payload') as read:
            self.assertEqual(self.client.get('/api/report-library').status_code,401);read.assert_not_called()
    def test_authenticated_read_never_enqueues(self):
        with patch.object(lib,'library_payload',return_value={'mode':'READ_ONLY','entries':[]}):
            r=self.client.get('/api/report-library',headers={'x-dashboard-token':'TEST-ONLY'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.headers['cache-control'],'no-store')
        self.wr.enqueue.assert_not_called();self.wr.ensure_schema.assert_not_called()
    def test_post_disallowed(self):
        self.assertEqual(self.client.post('/api/report-library').status_code,405)
    def test_reader_failure_isolated(self):
        with patch.object(lib,'library_payload',side_effect=ValueError('SECRET-DSN')):
            r=self.client.get('/api/report-library',headers={'x-dashboard-token':'TEST-ONLY'})
        self.assertEqual(r.status_code,503);self.assertNotIn('SECRET-DSN',r.text);self.assertEqual(self.client.get('/health').status_code,200)
    def test_scripts_and_original_routes(self):
        html=self.client.get('/').text
        self.assertIn('/assets/report-library.js',html);self.assertIn('/assets/web-research.js',html)
        self.assertEqual(self.client.get('/assets/report-library.js').status_code,200)
        self.assertEqual(len([r for r in self.app.app.routes if getattr(r,'path',None)=='/']),1)
    def test_source_has_no_paid_model_or_network(self):
        text=(ROOT/'report_library.py').read_text()
        for p in ['call_model(','enqueue(','requests.','DELETE FROM','INSERT INTO']:
            self.assertNotIn(p,text)

if __name__=='__main__':unittest.main()
