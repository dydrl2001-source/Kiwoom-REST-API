#!/bin/bash
# Market OS live rollout helper.
# Safe default: validates with Kiwoom 0B disabled. Realtime requires explicit --enable-realtime.
set -eu
cd "$(dirname "$0")"

MODE="${1:-validate}"
case "$MODE" in
  validate|--enable-realtime|--disable-realtime) ;;
  *) echo "Usage: bash launch_market_os_live.sh [validate|--enable-realtime|--disable-realtime]"; exit 1 ;;
esac

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Run ./start_mac.sh once and configure credentials first."
  exit 1
fi

read_env(){
  python3 - "$1" <<'PY'
from pathlib import Path
import re,sys
s=Path(".env").read_text(encoding="utf-8")
key=sys.argv[1]
m=re.findall(r"^"+re.escape(key)+r"=(.*)$",s,re.M)
print(m[-1].strip() if m else "")
PY
}

set_env(){
  python3 - "$1" "$2" <<'PY'
from pathlib import Path
import os,re,sys,tempfile
p=Path(".env");key=sys.argv[1];value=sys.argv[2];s=p.read_text(encoding="utf-8")
if len(re.findall(r"^"+re.escape(key)+r"=",s,re.M))>1:
    raise SystemExit("duplicate env key: "+key)
new=re.sub(r"^"+re.escape(key)+r"=.*$",key+"="+value,s,flags=re.M) if re.search(r"^"+re.escape(key)+r"=",s,re.M) else s.rstrip()+"\n"+key+"="+value+"\n"
if new!=s:
    fd,name=tempfile.mkstemp(prefix=".market-os-env-",dir=".")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(new)
        os.chmod(name,0o600);os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
PY
}

credentials_ok(){
  mode="$(read_env KIWOOM_MODE)"
  if [ "$mode" = "real" ]; then
    [ -n "$(read_env APP_KEY)" ] && [ -n "$(read_env APP_SECRET)" ]
  else
    [ -n "$(read_env APP_KEY_MOCK)" ] && [ -n "$(read_env APP_SECRET_MOCK)" ]
  fi
}

echo "=== Market OS live rollout: $MODE ==="
echo "Branch: $(git -C ../.. branch --show-current 2>/dev/null || true)"

if [ "$MODE" = "--disable-realtime" ]; then
  set_env KIWOOM_REALTIME_ENABLED 0
  docker compose up -d --no-deps --build kiwoom-realtime market-os-learning radar-api
  echo "Kiwoom 0B realtime disabled."
  bash check_market_os_live.sh || true
  exit 0
fi

if [ "$MODE" = "validate" ]; then
  # Validation never turns 0B on.
  set_env KIWOOM_REALTIME_ENABLED 0
  bash update_flow_desk.sh
  echo
  bash check_market_os_live.sh
  echo
  echo "Validation complete. Realtime is still OFF."
  echo "If the feed/regime/flow rows are current, run:"
  echo "  bash launch_market_os_live.sh --enable-realtime"
  exit 0
fi

# Explicit realtime activation.
if ! credentials_ok; then
  echo "ERROR: Kiwoom credentials for the selected mode are not configured."
  exit 1
fi

backup=".env.market-os-backup.$(date +%Y%m%d-%H%M%S)"
cp .env "$backup"
chmod 600 "$backup"
echo "Env backup: $backup"

# Require the existing REST/flow path to be healthy before introducing WebSocket data.
set_env KIWOOM_REALTIME_ENABLED 0
if ! bash check_market_os_live.sh; then
  echo "ERROR: base live preflight is blocked. 0B remains OFF."
  exit 2
fi

set_env KIWOOM_REALTIME_ENABLED 1
docker compose up -d --no-deps --build kiwoom-realtime market-os-learning radar-api

ok=0
for n in $(seq 1 24); do
  sleep 5
  state="$(docker compose exec -T postgres psql -U market -d market_radar -Atc "select coalesce(status,'')||'|'||coalesce(connected::text,'')||'|'||coalesce(subscribed_count::text,'0')||'|'||coalesce(tick_count::text,'0')||'|'||coalesce(gap_count::text,'0') from kiwoom_realtime_status where id=1" 2>/dev/null || true)"
  echo "0B check $n: ${state:-waiting}"
  case "$state" in
    OK"|true|"*)
      ticks="$(printf "%s" "$state" | cut -d'|' -f4)"
      if [ "${ticks:-0}" -gt 0 ] 2>/dev/null; then ok=1; break; fi
      ;;
  esac
done

if [ "$ok" -ne 1 ]; then
  echo "ERROR: 0B did not reach connected + tick state within 120 seconds."
  echo "Realtime will be turned back OFF; the backup remains at $backup."
  set_env KIWOOM_REALTIME_ENABLED 0
  docker compose up -d --force-recreate --no-deps kiwoom-realtime radar-api
  docker compose logs --tail=80 kiwoom-realtime || true
  exit 3
fi

echo
echo "Kiwoom 0B is receiving ticks. Running live preflight..."
bash check_market_os_live.sh
echo
echo "0B stays ON. It is observation-only and is not yet used to alter Radar/Setup scores."
