#!/usr/bin/env bash
#
# RLab Cortex — one-time Linux dev setup.
#
#   bash tools/setup_linux.sh
#
# Creates backend/.venv, installs the Python + web deps, and writes a
# backend/.env carrying a real random SECRET_KEY. Idempotent — re-running it
# only fills in what's missing.
#
# Prereqs on this machine: Python 3.11/3.12 (3.12 is what the Docker image and
# CI build against), Node 18+ (20 or 22 LTS recommended), and internet.
#
# Env knobs:
#   PYTHON=python3.12   pin a specific interpreter instead of autodetecting
#   NO_MIRROR=1         use the official PyPI / npm registries (default is the
#                       Tsinghua + npmmirror China mirrors, same as setup.bat)
#   SKIP_WEB=1          backend only (handy on a headless API box)

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[1;31m'; NC='\033[0m'
log()  { echo -e "${YEL}==>${NC} $*"; }
ok()   { echo -e "${GRN} ✓ ${NC} $*"; }
warn() { echo -e "${YEL} ! ${NC} $*"; }
fail() { echo -e "${RED} ✗ ${NC} $*" >&2; exit 1; }

if [ -n "${NO_MIRROR:-}" ]; then
  PIP_ARGS=()
  NPM_ARGS=()
else
  PIP_ARGS=(-i https://pypi.tuna.tsinghua.edu.cn/simple)
  NPM_ARGS=(--registry https://registry.npmmirror.com)
fi

# ── 1. pick an interpreter ──────────────────────────────────────────────────
log "[1/4] locating Python"
PY_BIN=""
for cand in "${PYTHON:-}" python3.12 python3.11 python3.13 python3; do
  [ -n "$cand" ] || continue
  command -v "$cand" >/dev/null 2>&1 || continue
  PY_BIN="$(command -v "$cand")"
  break
done
[ -n "$PY_BIN" ] || fail "no python3 on PATH — install Python 3.12 (e.g. sudo apt install python3.12 python3.12-venv)"

PY_MM="$("$PY_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$PY_MM" in
  3.11|3.12) ok "using $PY_BIN (Python $PY_MM)" ;;
  3.13)      warn "using $PY_BIN (Python $PY_MM) — untested here; the Docker image pins 3.12. If a wheel fails to build, install python3.12 and re-run with PYTHON=python3.12" ;;
  *)         fail "Python $PY_MM is out of range — this stack needs 3.11 or 3.12 (numpy/scipy/pyarrow are pinned to versions built for those)" ;;
esac

# venv needs the stdlib module present; Debian/Ubuntu ship it separately.
"$PY_BIN" -c 'import venv' 2>/dev/null \
  || fail "the venv module is missing — sudo apt install python${PY_MM}-venv"

# ── 2. venv + Python deps ───────────────────────────────────────────────────
log "[2/4] creating venv + installing Python deps (a few minutes)"
VENV="$ROOT/backend/.venv"
[ -x "$VENV/bin/python" ] || "$PY_BIN" -m venv "$VENV"
[ -x "$VENV/bin/python" ] || fail "venv creation failed at $VENV"

"$VENV/bin/python" -m pip install --upgrade pip "${PIP_ARGS[@]+"${PIP_ARGS[@]}"}"
"$VENV/bin/python" -m pip install -r "$ROOT/backend/requirements.txt" "${PIP_ARGS[@]+"${PIP_ARGS[@]}"}"

# Fail here rather than at first request: a half-installed sci stack otherwise
# only shows up as an opaque 500 the first time someone uploads a CSV.
"$VENV/bin/python" - <<'PYCHECK'
import importlib, sys
mods = ["fastapi", "uvicorn", "pandas", "numpy", "scipy", "sklearn", "pyarrow",
        "sqlalchemy", "openpyxl", "passlib", "jwt", "httpx", "authlib",
        "itsdangerous", "anthropic", "openai"]
missing = [m for m in mods if not importlib.util.find_spec(m)]
if missing:
    sys.exit("import check failed, missing: " + ", ".join(missing))
print("   import check passed (%d modules)" % len(mods))
PYCHECK
ok "backend deps installed"

# ── 3. .env ─────────────────────────────────────────────────────────────────
log "[3/4] backend/.env"
ENV_FILE="$ROOT/backend/.env"
if [ -f "$ENV_FILE" ]; then
  ok ".env already exists — left untouched"
else
  cp "$ROOT/backend/.env.example" "$ENV_FILE"
  # The shipped placeholder is not a secret. Sessions signed with it would be
  # forgeable by anyone who has read the repo.
  SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "$ENV_FILE"
  ok ".env created from .env.example with a fresh random SECRET_KEY"
  warn "BOOTSTRAP_ADMIN_PASSWORD in .env is still the default (123456) — change it before exposing this box"
fi

# ── 4. web deps ─────────────────────────────────────────────────────────────
if [ -n "${SKIP_WEB:-}" ]; then
  warn "[4/4] SKIP_WEB set — skipping npm install"
else
  log "[4/4] installing web deps"
  command -v npm >/dev/null 2>&1 || fail "npm not found — install Node 20 or 22 LTS"
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$NODE_MAJOR" -ge 18 ] || fail "Node $NODE_MAJOR is too old — Next 15 + React 19 need Node 18.18+ (20/22 LTS recommended)"

  # package-lock.json is in sync with package.json, so `npm ci` gives a
  # reproducible tree and is faster than `npm install`.
  ( cd "$ROOT/web" && npm ci --no-audit --no-fund "${NPM_ARGS[@]+"${NPM_ARGS[@]}"}" )
  ok "web deps installed (node $(node -v))"
fi

mkdir -p "$ROOT/tmp"

echo
ok "setup done."
echo "   start:  bash tools/start_linux.sh          (dev mode, hot reload)"
echo "   start:  MODE=prod bash tools/start_linux.sh   (production build)"
echo "   stop :  bash tools/stop_linux.sh"
