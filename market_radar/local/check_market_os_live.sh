#!/bin/bash
# Read-only live Market OS preflight. No API calls to Kiwoom/OpenAI, no key changes, no orders.
set -eu
cd "$(dirname "$0")"

echo '=== Market OS live preflight ==='
docker compose exec -T radar-api python - <<'PY'
from market_os_live_validation import payload
d=payload()
print('OVERALL:',d.get('overall'))
print('MARKET_SESSION:',d.get('market_session'))
k=d.get('kiwoom') or {}
print('KIWOOM_STATUS:',k.get('status'))
print('KIWOOM_MODE:',k.get('mode'))
print('KIWOOM_LAST_SUCCESS:',k.get('last_success_at'))
print('BLOCKERS:',','.join(d.get('blockers') or []) or '-')
print('WARNINGS:',','.join(d.get('warnings') or []) or '-')
print('FLOW_STOCKS:',(d.get('flow_quality') or {}).get('stocks'))
print('FLOW_UNIT_UNRESOLVED_PCT:',(d.get('flow_quality') or {}).get('unit_unresolved_pct'))
print('COVERAGE:',d.get('coverage'))
for x in d.get('tables') or []:
    print('TABLE',x.get('key'),'LEVEL='+str(x.get('level')),'LATEST='+str(x.get('latest')),'TODAY='+str(x.get('today_rows')))
if d.get('market_session')=='SESSION' and d.get('overall')=='BLOCKED':
    raise SystemExit(2)
PY
echo 'LIVE_PREFLIGHT: PASS_OR_OFF_HOURS'
