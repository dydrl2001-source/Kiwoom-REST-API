#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUT="${1:-$ROOT/backups}"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT/market_radar_$STAMP.dump"
TMP="$FILE.tmp"
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  pg_dump -U market -d market_radar -Fc > "$TMP"
test -s "$TMP"
mv "$TMP" "$FILE"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FILE" > "$FILE.sha256"
else
  shasum -a 256 "$FILE" > "$FILE.sha256"
fi
echo "backup=$FILE"
echo "checksum=$FILE.sha256"
