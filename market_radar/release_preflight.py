"""Release preflight for Market Radar / AI Brokerage.

Checks a running deployment without mutating it. The script can validate public
liveness/readiness and, when DASHBOARD_TOKEN is supplied, the protected dashboard
contract. It never sends broker orders or changes deployment state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def fetch_json(url: str, token: str | None=None, timeout: int=8) -> tuple[int,Any]:
    req=urllib.request.Request(url,method="GET")
    if token:
        req.add_header("x-dashboard-token",token)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            body=r.read().decode("utf-8")
            return r.status,json.loads(body)
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace")
        try:data=json.loads(body)
        except Exception:data={"raw":body[:500]}
        return e.code,data


def check(base_url: str, token: str | None=None) -> dict[str,Any]:
    base=base_url.rstrip("/")
    results=[]
    def add(name,ok,detail):
        results.append({"name":name,"pass":bool(ok),"detail":detail})

    status,live=fetch_json(base+"/health/live")
    add("health_live",status==200 and (live or {}).get("status")=="ok",{"status":status,"body":live})

    status,ready=fetch_json(base+"/health/ready")
    add("health_ready",status==200 and (ready or {}).get("status")=="ready",{"status":status,"body":ready})

    status,openapi=fetch_json(base+"/openapi.json")
    paths=(openapi or {}).get("paths") if isinstance(openapi,dict) else {}
    expected={"/health/live","/health/ready","/api/dashboard"}
    add("openapi_contract",status==200 and expected.issubset(set(paths or {})),
        {"status":status,"missing":sorted(expected-set(paths or {}))})

    if token:
        status,dashboard=fetch_json(base+"/api/dashboard",token=token,timeout=15)
        add("dashboard_auth",status==200,{"status":status})
        if status==200 and isinstance(dashboard,dict):
            broker=dashboard.get("ai_brokerage") or {}
            risk=dashboard.get("ai_risk_control") or {}
            ready_live=risk.get("live_readiness") or {}
            alloc=dashboard.get("ai_allocation") or {}
            shadow=dashboard.get("shadow_execution") or {}
            resilience=dashboard.get("ai_resilience") or {}
            add("ai_brokerage_contract",
                all(k in dashboard for k in ("ai_brokerage","ai_capacity","ai_allocation","ai_risk_control","ai_resilience","shadow_execution")),
                {"broker_status":broker.get("status")})
            add("paper_only",broker.get("paper_only") is True,{"paper_only":broker.get("paper_only")})
            add("live_disabled",ready_live.get("live_enabled") is False,
                {"stage":ready_live.get("stage"),"live_enabled":ready_live.get("live_enabled")})
            states={x.get("state") for x in broker.get("candidates") or []}
            add("no_live_entry_state","LIVE_ENTRY" not in states,{"states":sorted(x for x in states if x)})
            add("risk_control_present",bool(risk.get("kill_switch")),{"status":risk.get("status")})
            add("allocation_present",isinstance(alloc,dict),{"status":alloc.get("status")})
            add("shadow_present",isinstance(shadow,dict),{"status":shadow.get("status")})
            add("resilience_present",isinstance(resilience,dict),{"status":resilience.get("status")})
    else:
        add("dashboard_contract","SKIPPED",{"reason":"DASHBOARD_TOKEN not supplied"})

    passed=sum(1 for x in results if x["pass"] is True)
    failed=sum(1 for x in results if x["pass"] is False)
    skipped=sum(1 for x in results if x["pass"] not in (True,False))
    return {
        "status":"PASS" if failed==0 else "FAIL",
        "base_url":base,
        "passed":passed,"failed":failed,"skipped":skipped,
        "checks":results,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base-url",default=os.getenv("PREFLIGHT_BASE_URL"))
    p.add_argument("--token",default=os.getenv("DASHBOARD_TOKEN"))
    p.add_argument("--json",action="store_true")
    args=p.parse_args()
    if not args.base_url:
        raise SystemExit("PREFLIGHT_BASE_URL or --base-url required")
    result=check(args.base_url,args.token)
    if args.json:
        print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for row in result["checks"]:
            mark="PASS" if row["pass"] is True else "FAIL" if row["pass"] is False else "SKIP"
            print(f"{mark:4} {row['name']}: {row['detail']}")
        print(f"preflight={result['status']} passed={result['passed']} failed={result['failed']} skipped={result['skipped']}")
    raise SystemExit(0 if result["status"]=="PASS" else 1)

if __name__=="__main__":
    main()
