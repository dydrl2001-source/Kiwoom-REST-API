#!/bin/zsh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
echo "=== Market Radar containers ==="
docker compose ps
echo
echo "=== Kiwoom latest logs ==="
docker compose logs --tail=25 kiwoom-feed
echo
echo "=== Local access ==="
echo "Mac mini: http://localhost:8080"
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
[ -n "$IP" ] && echo "Same LAN: http://$IP:8080"
