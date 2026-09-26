"""Offline tests for the shell diagnostic's embedded Python; no live API calls."""
import io
import os
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import requests

SHELL = (Path(__file__).resolve().parents[1] / 'local/check_openai_auth.sh').read_text()
CODE = SHELL.split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
SECRET = 'sk-testing-DO-NOT-PRINT-1234567890'

class Reply:
    def __init__(self, status, data):
        self.status_code, self.data = status, data
    def json(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *args): pass

class AuthCheck(unittest.TestCase):
    def run_check(self, status=200, data=None, key=SECRET, error=None):
        data = data if data is not None else {'object':'list', 'data':[{'id':'test-model'}]}
        out = io.StringIO()
        with patch.dict(os.environ, {'OPENAI_API_KEY':key, 'WEB_RESEARCH_MODEL':'test-model'}, clear=True), \
             patch.object(requests, 'get', return_value=Reply(status, data), side_effect=error) as get, \
             patch.object(requests, 'post', side_effect=AssertionError('No inference allowed')) as post, \
             redirect_stdout(out):
            try:
                exec(compile(CODE, '<auth-check>', 'exec'), {})
            except SystemExit as exc:
                rc = exc.code
        text = out.getvalue()
        self.assertNotIn(SECRET, text)
        self.assertNotIn('leak-message', text)
        self.assertEqual(post.call_count, 0)
        if get.called:
            self.assertEqual(get.call_args.args, ('https://api.openai.com/v1/models',))
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(get.call_count, 1)
        return rc, text, get.call_count
    def test_ok(self):
        rc,t,_ = self.run_check(); self.assertEqual(rc,0); self.assertIn('MODELS_AUTH_OK',t)
    def test_wrong_key(self):
        _,t,_ = self.run_check(401,{'error':{'code':'invalid_api_key','message':'leak-message '+SECRET}})
        self.assertIn('API_KEY_REJECTED',t)
    def test_ip(self):
        _,t,_ = self.run_check(401,{'error':{'type':'ip_not_authorized','message':SECRET}})
        self.assertIn('IP_NOT_AUTHORIZED',t)
    def test_permission_is_not_wrong_key(self):
        _,t,_ = self.run_check(403,{'error':{'message':SECRET}})
        self.assertIn('MODELS_ACCESS_DENIED',t); self.assertNotIn('API_KEY_REJECTED',t)
    def test_no_key_no_network(self):
        _,t,n = self.run_check(key=''); self.assertEqual(n,0); self.assertIn('KEY_MISSING',t)
    def test_placeholder_no_network(self):
        _,t,n = self.run_check(key='여기에_키'); self.assertEqual(n,0); self.assertIn('KEY_FORMAT_PROBLEM',t)
    def test_embedded_space_no_network(self):
        _,_,n = self.run_check(key=SECRET+' space'); self.assertEqual(n,0)
    def test_timeout_not_retried(self):
        _,t,n = self.run_check(error=requests.Timeout('leak-message '+SECRET))
        self.assertEqual(n,1); self.assertIn('AUTH_CHECK_TIMEOUT',t)
    def test_network_error_not_echoed(self):
        _,t,_ = self.run_check(error=requests.ConnectionError('leak-message '+SECRET))
        self.assertIn('AUTH_CHECK_NETWORK_ERROR',t)
    def test_model_missing(self):
        rc,t,_ = self.run_check(data={'object':'list','data':[]})
        self.assertEqual(rc,0); self.assertIn('CONFIGURED_MODEL_VISIBLE: False',t)
    def test_malformed_success(self):
        rc,t,_ = self.run_check(data={'object':'other'})
        self.assertNotEqual(rc,0); self.assertIn('UNEXPECTED_MODELS_RESPONSE',t)
    def test_redirect_not_followed(self):
        _,t,_ = self.run_check(302,{'error':{'message':SECRET}})
        self.assertIn('AUTH_CHECK_HTTP_ERROR',t)

if __name__ == '__main__': unittest.main()
