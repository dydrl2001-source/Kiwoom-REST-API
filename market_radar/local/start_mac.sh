#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker가 없습니다. Docker Desktop을 먼저 설치하세요."
  exit 1
fi
mkdir -p data
if [ ! -f .env ]; then
  cp .env.example .env
  PASS=$(openssl rand -hex 16)
  TOKEN=$(openssl rand -hex 24)
  python3 - <<PY
from pathlib import Path
p=Path(".env")
s=p.read_text()
s=s.replace("POSTGRES_PASSWORD=change-this-password","POSTGRES_PASSWORD=$PASS")
s=s.replace("DASHBOARD_TOKEN=change-this-long-random-token","DASHBOARD_TOKEN=$TOKEN")
p.write_text(s)
PY
  echo ".env 파일을 만들었습니다. Kiwoom/Telegram 키를 입력한 뒤 다시 실행하세요."
  open -e .env
  exit 0
fi
docker compose build
docker compose up -d postgres radar-api kiwoom-feed market-regime news-feed chart-feed mimosa-engine index-chart-feed research-engine research-engine
if [ -f data/marketcollector.session ]; then
  docker compose up -d telegram-collector
else
  echo
  echo "Telegram 로그인이 아직 없습니다."
  echo "먼저 ./telegram_login_mac.sh 를 실행하세요."
fi
echo
echo "Market Radar: http://localhost:8080"
