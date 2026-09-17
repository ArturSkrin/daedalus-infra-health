#!/usr/bin/env bash
# Re-create every PNG in design/ from the running prototype.
# Needs Docker and the stack up:  TRACKER_PORT=8088 docker compose up -d
set -e
PORT="${TRACKER_PORT:-8088}"
# pwd -W gives a Windows path under Git Bash, which is what Docker Desktop needs for -v
OUT="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"
BASE="http://host.docker.internal:$PORT"

shot() { # name url width height
  MSYS_NO_PATHCONV=1 docker run --rm -v "$OUT:/out" --add-host=host.docker.internal:host-gateway zenika/alpine-chrome:latest \
    --no-sandbox --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --window-size="$3,$4" --virtual-time-budget=6000 --screenshot="/out/$1.png" "$2" >/dev/null 2>&1
  echo "$1.png"
}

for s in s01_calm s02_release_settled s03_release_regressed s04_memory_pressure s05_agent_disconnected \
         s06_log_spike s07_outage s08_dark_services s09_precursor_imminent s10_low_precision; do
  shot "phone_$s" "$BASE/?scenario=$s" 390 844
done

for s in s01_calm s07_outage s09_precursor_imminent; do
  shot "desktop_$s" "$BASE/?scenario=$s" 1280 1010
done

shot "drill_users_s07"    "$BASE/?scenario=s07_outage&drill=users"                390 844
shot "drill_forecast_s09" "$BASE/?scenario=s09_precursor_imminent&drill=forecast" 390 844
shot "drill_trust_s08"    "$BASE/?scenario=s08_dark_services&drill=trust"         390 844
shot "drill_day_s03"      "$BASE/?scenario=s03_release_regressed&drill=day"       390 844
shot "drill_verdict_s07"  "$BASE/?scenario=s07_outage&drill=verdict"              390 844
