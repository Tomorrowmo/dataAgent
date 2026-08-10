#!/usr/bin/env bash
#
# RLab Cortex — stop backend (:8077) + frontend (:3000) on Linux.
#
#   bash tools/stop_linux.sh
#
# Kills the recorded pids first, then sweeps the ports. The sweep matters:
# `npm run dev` spawns a child that outlives the pid we recorded, so killing
# the pidfile alone can leave :3000 held.

set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

BPORT="${BPORT:-8077}"
FPORT="${FPORT:-3000}"

YEL='\033[1;33m'; GRN='\033[1;32m'; NC='\033[0m'
log() { echo -e "${YEL}==>${NC} $*"; }
ok()  { echo -e "${GRN} ✓ ${NC} $*"; }

for name in backend web; do
  pidfile="$ROOT/tmp/${name}.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "   killing ${name} pid ${pid}"
      kill "$pid" 2>/dev/null
    fi
    rm -f "$pidfile"
  fi
done

port_kill() {
  local port="$1" pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnpH "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser -n tcp "${port}" 2>/dev/null)"
  fi
  if [ -n "$pids" ]; then
    echo "   killing $(echo "$pids" | tr '\n' ' ')on :${port}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null
  else
    echo "   nothing on :${port}"
  fi
}

log "sweeping ports"
port_kill "$BPORT"
port_kill "$FPORT"

echo
ok "stopped."
