#!/bin/bash
set -eu
cd "$(dirname "$0")"

TS=""
if command -v tailscale >/dev/null 2>&1; then
  TS="$(command -v tailscale)"
elif [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
  TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
fi

if [ -z "$TS" ]; then
  echo "Tailscale이 설치되어 있지 않습니다."
  echo "1) Mac에 Tailscale 설치 후 같은 계정으로 로그인"
  echo "2) iPhone에도 Tailscale 설치 후 같은 계정으로 로그인"
  echo "3) 이 스크립트를 다시 실행"
  exit 2
fi

if ! curl --fail --silent --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  echo "Market Radar가 8080에서 응답하지 않습니다."
  echo "먼저: docker compose up -d radar-api"
  exit 1
fi

echo "Market Radar를 Tailscale HTTPS로 공유합니다..."
"$TS" serve --bg 8080

echo
echo "=== Tailscale Serve 상태 ==="
"$TS" serve status || true

echo
echo "표시된 https://<Mac이름>.<tailnet>.ts.net/mobile 주소를 iPhone Safari에서 여세요."
echo "iPhone과 Mac 모두 같은 Tailscale 계정/tailnet에 연결되어 있어야 합니다."
echo "사이트는 공개 인터넷에 노출하지 않고 tailnet 내부에만 공유됩니다."
