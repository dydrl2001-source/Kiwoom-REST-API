#!/bin/bash
# Offline Market OS logic tests. Does not connect to Kiwoom, OpenAI, or place orders.
set -eu
cd "$(dirname "$0")"
echo '=== Market OS offline tests ==='
docker compose run --rm --no-deps -T radar-api   python -m unittest discover -s /app/tests -p 'test_market_os*.py' -v
echo 'MARKET_OS_OFFLINE_TESTS: PASS'
