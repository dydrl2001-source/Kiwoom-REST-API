#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p data
docker compose --profile tools run --rm telegram-login
docker compose up -d telegram-collector
echo "Telegram collector started."
