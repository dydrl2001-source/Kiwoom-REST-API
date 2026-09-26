#!/bin/bash
set -e
cd "$(dirname "$0")"
echo '=== Containers ==='
docker compose ps radar-api web-research-worker

echo '=== Existing API/DB health ==='
curl --fail --silent --show-error --max-time 10 http://localhost:8080/health
printf '\n'

echo '=== External research configuration (no keys or report content) ==='
docker compose exec -T radar-api python - <<'PY'
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
key = os.getenv('DASHBOARD_TOKEN', '')
if not key:
    print('DASHBOARD_TOKEN missing in radar-api environment')
    sys.exit(1)
req = Request('http://127.0.0.1:8080/api/web-research', headers={'x-dashboard-token': key})
try:
    with urlopen(req, timeout=15) as response:
        data = json.load(response)
    print(json.dumps({'config': data.get('config'), 'usage': data.get('usage'),
                      'worker': data.get('worker'), 'candidate_count': len(data.get('candidates', [])),
                      'report_count': len(data.get('runs', []))}, ensure_ascii=False, indent=2))
except HTTPError as exc:
    print('Web research HTTP status:', exc.code)
    sys.exit(1)
except (URLError, TimeoutError):
    print('Web research API did not respond')
    sys.exit(1)
PY
