#!/usr/bin/env bash
#
# RLab Cortex — start backend (:8077) + frontend (:3000) on Linux.
#
#   bash tools/start_linux.sh              # dev mode: next dev, hot reload
#   MODE=prod bash tools/start_linux.sh    # production: next build && next start
#
# Both processes are detached with nohup and their pids recorded in tmp/, so
# closing the terminal doesn't take them down. Stop with tools/stop_linux.sh.
#
# Env knobs: BPORT (8077), FPORT (3000), MODE (dev|prod)

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

BPORT="${BPORT:-8077}"
FPORT="${FPORT:-3000}"
MODE="${MODE:-dev}"

YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[1;31m'; NC='\033[0m'
log()  { echo -e "${YEL}==>${NC} $*"; }
ok()   { echo -e "${GRN} ✓ ${NC} $*"; }
warn() { echo -e "${YEL} ! ${NC} $*"; }
fail() { echo -e "${RED} ✗ ${NC} $*" >&2; exit 1; }

VENV_PY="$ROOT/backend/.venv/bin/python"
[ -x "$VENV_PY" ]            || fail "venv missing — run: bash tools/setup_linux.sh"
[ -d "$ROOT/web/node_modules" ] || fail "web/node_modules missing — run: bash tools/setup_linux.sh"
mkdir -p "$ROOT/tmp"

# Kill whatever holds a port. Distros vary in which of these is installed, so
# try each — `ss` is on essentially every systemd distro, `lsof` often isn't.
port_kill() {
  local port="$1" pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnpH "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u || true)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser -n tcp "${port}" 2>/dev/null || true)"
  fi
  if [ -n "$pids" ]; then
    echo "   killing $(echo "$pids" | tr '\n' ' ')on :${port}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  else
    echo "   nothing on :${port}"
  fi
}

log "stopping anything on :$BPORT / :$FPORT"
port_kill "$BPORT"
port_kill "$FPORT"
sleep 1

# ── backend ─────────────────────────────────────────────────────────────────
# MUST run with cwd=backend/ — DATABASE_URL and UPLOAD_DIR in .env are relative
# paths (./data/db, ./data/uploads); launching from the repo root silently
# creates a second, empty database one level up.
log "starting backend (:$BPORT)"
(
  cd "$ROOT/backend"
  BACKEND_LOG_FILE="$ROOT/tmp/backend.log" PYTHONUNBUFFERED=1 \
  nohup "$VENV_PY" -u -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$BPORT" --log-level info \
      > "$ROOT/tmp/backend.out" 2>&1 &
  echo $! > "$ROOT/tmp/backend.pid"
)

# ── frontend ────────────────────────────────────────────────────────────────
log "starting frontend (:$FPORT, mode=$MODE)"
if [ "$MODE" = "prod" ]; then
  ( cd "$ROOT/web" && npm run build )
  ( cd "$ROOT/web" && nohup npm start > "$ROOT/tmp/web.out" 2>&1 & echo $! > "$ROOT/tmp/web.pid" )
else
  ( cd "$ROOT/web" && nohup npm run dev > "$ROOT/tmp/web.out" 2>&1 & echo $! > "$ROOT/tmp/web.pid" )
fi

# ── wait ────────────────────────────────────────────────────────────────────
log "waiting for backend health (first import pulls in pandas/sklearn)"
healthy=""
for i in $(seq 1 180); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${BPORT}/api/health" >/dev/null 2>&1; then
    healthy="$i"; break
  fi
  sleep 1
done
if [ -n "$healthy" ]; then
  ok "backend healthy after ${healthy}s"
else
  warn "backend not healthy in 180s — tail -n 50 tmp/backend.log"
fi

log "waiting for frontend (first compile can take ~30s)"
up=""
for i in $(seq 1 180); do
  if curl -fsS --max-time 2 -o /dev/null "http://127.0.0.1:${FPORT}/" 2>/dev/null; then
    up="$i"; break
  fi
  sleep 1
done
if [ -n "$up" ]; then
  ok "frontend up after ${up}s"
else
  warn "frontend not up in 180s — tail -n 50 tmp/web.out"
fi

echo
echo "   Open    : http://localhost:${FPORT}"
echo "   Backend : http://127.0.0.1:${BPORT}/api/health   (log: tmp/backend.log)"
echo "   Stop    : bash tools/stop_linux.sh"
echo
