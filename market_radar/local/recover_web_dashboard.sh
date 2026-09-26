#!/bin/bash
# Restore the dashboard without enabling AI, resetting Git, or deleting data.
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo 'Existing local/.env not found; nothing was changed.'
  exit 1
fi

echo '=== Pause external AI worker; leave credentials and data unchanged ==='
docker compose stop web-research-worker

echo '=== Rebuild and restart ONLY radar-api ==='
docker compose build radar-api
docker compose up -d --no-deps --force-recreate radar-api

echo '=== Wait for API/DB health (not just container Started) ==='
ready=0
for attempt in $(seq 1 24); do
  if curl --fail --silent --max-time 3 http://localhost:8080/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

docker compose ps --all radar-api web-research-worker
if [ "$ready" -ne 1 ]; then
  echo 'Dashboard health did not recover. External AI worker remains stopped.'
  echo 'Inspect: docker compose logs --tail=60 radar-api'
  echo 'Do not paste .env or any key values into chat.'
  exit 1
fi

curl --fail --silent --show-error --max-time 5 http://localhost:8080/health
printf '\n'
echo 'Dashboard API/DB health responded successfully.'
echo 'External AI worker is intentionally STOPPED; do not submit a research request yet.'
echo 'After checking the dashboard: docker compose up -d --no-deps web-research-worker'
