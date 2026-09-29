import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from release_preflight import check


class _Handler(BaseHTTPRequestHandler):
    mode="good"
    def log_message(self,*args):
        pass
    def do_GET(self):
        if self.path=="/health/live":
            if self.mode=="legacy":
                self.send_response(404);self.end_headers();return
            body={"status":"ok","service":"market-radar"}
        elif self.path=="/health/ready":
            if self.mode=="legacy":
                self.send_response(404);self.end_headers();return
            body={"status":"ready","checks":{"db":True,"schema":True,"risk_control":True}}
        elif self.path=="/openapi.json":
            paths={"/health":{},"/stats":{}} if self.mode=="legacy" else {
                "/health/live":{},"/health/ready":{},"/api/dashboard":{}
            }
            body={"openapi":"3.1.0","paths":paths}
        elif self.path=="/api/dashboard":
            if self.headers.get("x-dashboard-token")!="test":
                self.send_response(401);self.end_headers();return
            body={
                "ai_brokerage":{"status":"OK","paper_only":True,"candidates":[{"state":"PAPER_ENTRY"}]},
                "ai_capacity":{},"ai_allocation":{"status":"OK"},
                "ai_risk_control":{"status":"OK","kill_switch":{"state":"RUN"},
                                   "live_readiness":{"stage":"RESEARCH_ONLY","live_enabled":False}},
                "ai_resilience":{"status":"PASS"},
                "shadow_execution":{"status":"OK"},
            }
        else:
            self.send_response(404);self.end_headers();return
        raw=json.dumps(body).encode()
        self.send_response(200);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)


class ReleasePreflightTests(unittest.TestCase):
    def server(self,mode):
        _Handler.mode=mode
        srv=HTTPServer(("127.0.0.1",0),_Handler)
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        self.addCleanup(srv.shutdown);self.addCleanup(srv.server_close)
        return f"http://127.0.0.1:{srv.server_port}"

    def test_current_contract_passes_with_token(self):
        out=check(self.server("good"),"test")
        self.assertEqual(out["status"],"PASS")
        self.assertEqual(out["failed"],0)
        names={x["name"]:x for x in out["checks"]}
        self.assertTrue(names["paper_only"]["pass"])
        self.assertTrue(names["live_disabled"]["pass"])
        self.assertTrue(names["no_live_entry_state"]["pass"])

    def test_legacy_health_only_deployment_fails(self):
        out=check(self.server("legacy"),None)
        self.assertEqual(out["status"],"FAIL")
        names={x["name"]:x for x in out["checks"]}
        self.assertFalse(names["health_live"]["pass"])
        self.assertFalse(names["health_ready"]["pass"])
        self.assertFalse(names["openapi_contract"]["pass"])

    def test_live_entry_state_fails_guard(self):
        base=self.server("good")
        original=_Handler.do_GET
        def patched(handler):
            if handler.path=="/api/dashboard":
                body={
                    "ai_brokerage":{"status":"OK","paper_only":True,"candidates":[{"state":"LIVE_ENTRY"}]},
                    "ai_capacity":{},"ai_allocation":{},"ai_risk_control":{
                        "kill_switch":{"state":"RUN"},"live_readiness":{"live_enabled":False}},
                    "ai_resilience":{},"shadow_execution":{}
                }
                raw=json.dumps(body).encode();handler.send_response(200)
                handler.send_header("Content-Type","application/json")
                handler.send_header("Content-Length",str(len(raw)));handler.end_headers()
                handler.wfile.write(raw);return
            return original(handler)
        _Handler.do_GET=patched
        self.addCleanup(setattr,_Handler,"do_GET",original)
        out=check(base,"test")
        names={x["name"]:x for x in out["checks"]}
        self.assertFalse(names["no_live_entry_state"]["pass"])
        self.assertEqual(out["status"],"FAIL")


if __name__=="__main__":
    unittest.main()
