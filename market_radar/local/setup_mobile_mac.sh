#!/bin/bash
set -eu
cd "$(dirname "$0")"

echo "=== Market Radar Mobile setup ==="
docker compose up -d --no-deps --build radar-api

echo "Waiting for dashboard..."
ready=0
for i in $(seq 1 20); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "radar-api health check failed"
  docker compose logs --tail=50 radar-api
  exit 1
fi

chmod +x mobile_url_mac.sh enable_mobile_remote_mac.sh

echo
./mobile_url_mac.sh

if command -v tailscale >/dev/null 2>&1 || [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
  echo
  echo "Tailscale이 감지되었습니다."
  echo "집 밖 원격 HTTPS도 켜려면:"
  echo "./enable_mobile_remote_mac.sh"
else
  echo
  echo "집 밖에서도 접속하려면 Mac/iPhone에 Tailscale 설치 후 ./enable_mobile_remote_mac.sh 실행"
fi
