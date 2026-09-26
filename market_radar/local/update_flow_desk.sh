#!/bin/bash
# Explicit --auto enables automatic selection but NEVER raises call limits or edits keys.
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then echo '기존 .env가 없습니다. 설정을 새로 만들거나 덮어쓰지 않았습니다.'; exit 1; fi
if [ "${1:-}" != '' ] && [ "${1:-}" != '--auto' ]; then echo 'Usage: bash update_flow_desk.sh [--auto]'; exit 1; fi
if [ "${1:-}" = '--auto' ]; then
 python3 - <<'PY'
from pathlib import Path
import re,os,tempfile
p=Path('.env');s=p.read_text(encoding='utf-8')
for key in ['WEB_RESEARCH_DAILY_LIMIT','WEB_RESEARCH_HOURLY_LIMIT']:
    matches=re.findall(r'^'+key+r'=\s*(\d+)\s*$',s,re.M)
    if len(matches)!=1 or int(matches[0])<1:
        raise SystemExit(key+' 명시 설정을 확인하세요. 한도를 새로 정하거나 늘리지 않았습니다.')
key='WEB_RESEARCH_AUTO'
if len(re.findall(r'^'+key+r'=',s,re.M))>1:
    raise SystemExit('WEB_RESEARCH_AUTO 중복 설정. 파일을 변경하지 않았습니다.')
new=re.sub(r'^'+key+r'=.*$',key+'=1',s,flags=re.M) if re.search(r'^'+key+'=',s,re.M) else s.rstrip()+'\n'+key+'=1\n'
if new!=s:
    fd,name=tempfile.mkstemp(prefix='.flow-settings-',dir='.')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(new)
        os.chmod(name,0o600);os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
print('자동 선별 켜짐. API 키·일일/시간당 호출 한도·시도 기록은 변경하지 않았습니다.')
PY
fi

echo '=== Update only market/read-only UI/research workers; keep PostgreSQL and Telegram intact ==='
docker compose up -d --no-deps --build kiwoom-feed market-theme-feed news-feed chart-feed radar-api web-research-worker
ready=0
for n in $(seq 1 30); do
 if curl --fail --silent --max-time 3 http://localhost:8080/health >/dev/null 2>&1; then ready=1;break;fi
 sleep 2
done
if [ "$ready" -ne 1 ]; then echo 'API health not ready. Inspect: docker compose logs --tail=40 radar-api';exit 1;fi
bash check_flow_desk.sh
echo 'Open the existing dashboard, refresh, and select [30초 흐름].'
echo 'First deltas need at least 2 new batches; speed baseline needs at least 5 earlier intervals.'
echo 'Auto research uses existing caps; 1/day still means 1/day, including old failed attempts.'
