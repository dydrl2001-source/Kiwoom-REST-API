#!/bin/zsh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
TOKEN="$(sed -n 's/^DASHBOARD_TOKEN=//p' .env | head -1)"
if [ -z "$TOKEN" ]; then
  echo "DASHBOARD_TOKEN이 .env에 없습니다."
  exit 1
fi
open "http://localhost:8080/#$TOKEN"
