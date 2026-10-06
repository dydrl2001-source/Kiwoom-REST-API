#!/bin/bash
# Operator commands only; intentionally absent from compose workers and schedulers.
set -eu
cd "$(dirname "$0")"
exec docker compose exec -T radar-api python /app/market_os_order_admin.py "$@"
