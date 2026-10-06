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
fq=d.get('flow_quality') or {}
print('FLOW_STOCKS:',fq.get('stocks'))
print('TURNOVER_UNIT_UNRESOLVED_PCT:',fq.get('turnover_unresolved_pct'))
print('TURNOVER_STATES:',fq.get('turnover_states'))
print('CAP_UNIT_UNRESOLVED_PCT:',fq.get('cap_unresolved_pct'))
print('CAP_STATES:',fq.get('cap_states'))
rt=d.get('realtime') or {}
print('REALTIME_ENABLED:',rt.get('enabled'))
print('REALTIME_STATUS:',rt.get('status'))
print('REALTIME_CONNECTED:',rt.get('connected'))
print('REALTIME_LAST_MESSAGE:',rt.get('last_message_at'))
print('REALTIME_SUBSCRIBED:',rt.get('subscribed_count'))
print('REALTIME_TICKS:',rt.get('tick_count'))
print('REALTIME_GAPS:',rt.get('gap_count'))
print('REALTIME_RECENT_GAPS_5M:',rt.get('recent_gap_count_5m'))
print('REALTIME_RECENT_GAP_STOCKS_5M:',rt.get('recent_gap_stocks_5m'))
print('COVERAGE:',d.get('coverage'))
for x in d.get('tables') or []:
    print('TABLE',x.get('key'),'LEVEL='+str(x.get('level')),'LATEST='+str(x.get('latest')),'TODAY='+str(x.get('today_rows')))
if d.get('market_session')=='SESSION' and d.get('overall')=='BLOCKED':
    raise SystemExit(2)
PY
echo 'LIVE_PREFLIGHT: PASS_OR_OFF_HOURS'
