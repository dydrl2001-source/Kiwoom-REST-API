#!/bin/bash
# Read saved statuses only; do not start worker or expose reports/credentials.
set -eu
cd "$(dirname "$0")"
curl --fail --silent --show-error --max-time 8 http://localhost:8080/health
printf '\n'
docker compose exec -T radar-api python - <<'PY'
import json, os, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
key=os.getenv('DASHBOARD_TOKEN','')
if not key:
    print('RESULT: DASHBOARD_TOKEN_MISSING');sys.exit(1)
try:
    req=Request('http://127.0.0.1:8080/api/report-library',headers={'x-dashboard-token':key})
    with urlopen(req,timeout=20) as res:data=json.load(res)
    entries=data.get('entries') or []
    print('MODE:',data.get('mode'))
    print('STORAGE:',data.get('storage'))
    print('STOCKS_IN_SCOPE:',len(entries))
    print('SAVED_CITED_REPORTS:',sum(bool(x.get('report')) for x in entries))
    print('LATEST_FAILED_OR_UNCERTAIN:',sum(x.get('latest_state') in ('ERROR','UNCERTAIN') for x in entries))
    print('No research request was sent; no limits or records were changed.')
except HTTPError as e:
    print('RESULT: REPORT_LIBRARY_HTTP_'+str(e.code));sys.exit(1)
except Exception:
    print('RESULT: REPORT_LIBRARY_UNAVAILABLE');sys.exit(1)
PY
