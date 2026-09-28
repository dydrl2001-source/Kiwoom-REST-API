#!/bin/bash
set -eu
cd "$(dirname "$0")"

ip=""
for iface in en0 en1; do
  candidate="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
  if [ -n "$candidate" ]; then ip="$candidate"; break; fi
done

if [ -z "$ip" ]; then
  ip="$(python3 - <<'PY'
import socket
try:
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.connect(("8.8.8.8",80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    pass
PY
)"
fi

if [ -z "$ip" ]; then
  echo "LAN IP를 자동으로 찾지 못했습니다."
  echo "Mac에서: ipconfig getifaddr en0"
  exit 1
fi

echo
echo "Market Radar Mobile"
echo "==================="
echo "같은 Wi-Fi의 iPhone Safari에서 열기:"
echo "http://$ip:8080/mobile"
echo
echo "Safari 공유 버튼 → '홈 화면에 추가'를 누르면 앱처럼 설치됩니다."
echo "집 밖에서도 쓰는 공개/개인 URL은 클라우드 미러 연결 후 제공합니다."
