#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "usage: $0 <backup.dump>" >&2
  exit 2
fi
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FILE="$1"
test -s "$FILE"
DB="market_radar_restore_check"
cleanup() {
  docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
    dropdb -U market --if-exists "$DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
cleanup
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres createdb -U market "$DB"
cat "$FILE" | docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  pg_restore -U market -d "$DB" --no-owner --no-privileges
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  psql -U market -d "$DB" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS tables FROM pg_tables WHERE schemaname='public';"
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  psql -U market -d "$DB" -v ON_ERROR_STOP=1 -c "SELECT version,checksum,applied_at FROM market_radar_schema_migrations ORDER BY applied_at DESC LIMIT 3;"
echo "restore drill PASS: $FILE"
