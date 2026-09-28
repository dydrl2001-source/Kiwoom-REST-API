#!/bin/bash
# Read-only diagnostics, not another model call. No keys/report text are printed.
set -eu
cd "$(dirname "$0")"
docker compose ps radar-api kiwoom-feed market-theme-feed chart-feed web-research-worker candidate-tracker paper-trade-engine paper-feedback-engine
curl --fail --silent --show-error --max-time 8 http://localhost:8080/health
printf '\n'
docker compose exec -T radar-api python - <<'PY'
import os,json,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
try:
    key=os.getenv('DASHBOARD_TOKEN','')
    req=Request('http://127.0.0.1:8080/api/flow-desk',headers={'x-dashboard-token':key})
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
    tr=d.get('candidate_tracking',{})
    print('CANDIDATE_TRACKER_STATUS:',tr.get('status'))
    print('CANDIDATE_STATE_COUNTS:',tr.get('state_counts'))
    print('RECENT_DROPOUTS:',len(tr.get('recent_dropouts',[])))
    print('PERSISTENT_THEMES:',len(tr.get('theme_persistence',[])))
    j=d.get('candidate_journal',{})
    print('JOURNAL_STATUS:',j.get('status'))
    print('JOURNAL_EPISODES:',len(j.get('episodes',[])))
    print('JOURNAL_5M_READY:',j.get('completed_5m'))
    print('JOURNAL_15M_READY:',j.get('completed_15m'))
    print('JOURNAL_30M_READY:',j.get('completed_30m'))
    print('JOURNAL_TYPE_SUMMARIES:',len(j.get('summary',[])))
    a=d.get('automation',{})
    print('AUTO_SELECTION:',a.get('automatic'))
    print('DAILY_LIMIT_UNCHANGED:',a.get('daily_limit'))
    print('DAILY_ATTEMPTS:',a.get('usage',{}).get('daily'))
    req2=Request('http://127.0.0.1:8080/api/dashboard',headers={'x-dashboard-token':key})
    with urlopen(req2,timeout=25) as r2:dash=json.load(r2)
    p=dash.get('paper_lab',{})
    print('PAPER_LAB_STATUS:',p.get('status'))
    print('PAPER_OPEN:',len(p.get('open',[])))
    print('PAPER_CLOSED_30D:',p.get('summary',{}).get('closed'))
    print('PAPER_MEDIAN_RETURN:',p.get('summary',{}).get('median_return_pct'))
    pf=dash.get('paper_feedback',{})
    pp=pf.get('payload',{})
    print('PAPER_FEEDBACK_STATUS:',pf.get('status'))
    print('PAPER_FEEDBACK_LABEL:',pp.get('label'))
    print('PAPER_FEEDBACK_SAMPLE:',pp.get('overall',{}).get('n'))
    print('PAPER_FEEDBACK_CHECKS:',len(pp.get('checks',[])))
    print('No orders, model calls, threshold changes or data deletion were performed by this diagnostic.')
except HTTPError as e:
    print('FLOW_HTTP_STATUS:',e.code);sys.exit(1)
except Exception:
    print('FLOW_CHECK_FAILED');sys.exit(1)
PY
