#!/bin/bash
# Read-only diagnostics, not another model call. No keys/report text are printed.
set -eu
cd "$(dirname "$0")"
docker compose ps radar-api kiwoom-feed market-theme-feed chart-feed web-research-worker
curl --fail --silent --show-error --max-time 8 http://localhost:8080/health
printf '\n'
docker compose exec -T radar-api python - <<'PY'
import os,json,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
try:
    req=Request('http://127.0.0.1:8080/api/flow-desk',headers={'x-dashboard-token':os.getenv('DASHBOARD_TOKEN','')})
    with urlopen(req,timeout=25) as r:d=json.load(r)
    print('FLOW_STATUS:',d.get('status'))
    print('SAMPLE_TIME:',d.get('sample_time'))
    print('OBSERVED_STOCKS:',len(d.get('rows',[])))
    print('COMMON_COHORT:',d.get('coverage',{}).get('common_stocks'))
    print('MONEY_UNITS:',d.get('unit_version'))
    print('THEME_GROUPS:',len(d.get('theme_groups',[])))
    print('CATALYST_GROUPS:',len(d.get('catalyst_groups',[])))
    print('WATCH_CANDIDATES:',len(d.get('watch_candidates',[])))
    print('TOP_ATTENTION_SCORE:',(d.get('watch_candidates') or [{}])[0].get('attention_score'))
    from collections import Counter
    counts=Counter(x.get('primary_type') for x in d.get('watch_candidates',[]) if x.get('primary_type'))
    print('WATCH_TYPE_COUNTS:',dict(counts))
    a=d.get('automation',{})
    print('AUTO_SELECTION:',a.get('automatic'))
    print('DAILY_LIMIT_UNCHANGED:',a.get('daily_limit'))
    print('DAILY_ATTEMPTS:',a.get('usage',{}).get('daily'))
    print('No orders, model calls or data deletion were performed by this diagnostic.')
except HTTPError as e:
    print('FLOW_HTTP_STATUS:',e.code);sys.exit(1)
except Exception:
    print('FLOW_CHECK_FAILED');sys.exit(1)
PY
