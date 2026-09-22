#!/bin/zsh
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$HOME/Library/Logs/market-radar-autostart.log"
mkdir -p "$HOME/Library/Logs"
{
  echo "[$(date)] Market Radar autostart check"
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker CLI not found"
    exit 1
  fi
  open -ga Docker 2>/dev/null || true
  for i in {1..90}; do
    if docker info >/dev/null 2>&1; then
      cd "$SCRIPT_DIR"
      docker compose up -d
      echo "[$(date)] Market Radar is up"
      exit 0
    fi
    sleep 2
  done
  echo "[$(date)] Docker did not become ready"
  exit 1
} >>"$LOG" 2>&1
