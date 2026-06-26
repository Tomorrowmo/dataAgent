#!/usr/bin/env bash
#
# RLab Cortex — one-click deploy to a fresh Linux VM
# Tested on: Alibaba Cloud ECS / Tencent Cloud CVM / any Debian-Ubuntu host.
#
# Usage (on the cloud VM, after `scp -r` or `git clone`):
#   cd RLab Cortex && bash deploy/deploy.sh
#
# Optional env:
#   PUBLIC_PORT=80              # external port to expose (default 8088)
#   PUBLIC_ORIGIN=https://x.com # CORS origin for the API
#   DEEPSEEK_API_KEY=sk-...     # server-side LLM key (optional — users can BYOK)
#
set -euo pipefail

cd "$(dirname "$0")/.."  # project root

YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[1;31m'; NC='\033[0m'
log()   { echo -e "${YEL}==>${NC} $*"; }
ok()    { echo -e "${GRN}✓${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# 1. Install docker engine + compose plugin if missing
if ! command -v docker >/dev/null 2>&1; then
  log "Docker not found — installing"
  if command -v apt-get >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER" || true
  else
    fail "Please install Docker manually before re-running this script."
  fi
fi
docker --version || fail "Docker is not on PATH"

# Some installers ship `docker compose`, some still need the legacy `docker-compose`
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  log "Installing docker compose plugin"
  sudo apt-get install -y docker-compose-plugin || fail "Could not install docker compose"
  DC="docker compose"
fi
ok "Docker + compose ready"

# 2. Write backend/.env from the template if missing — embed any DEEPSEEK_API_KEY passed in
if [[ ! -f backend/.env ]]; then
  log "Creating backend/.env"
  cp backend/.env.example backend/.env
fi
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  log "Embedding DEEPSEEK_API_KEY into backend/.env"
  sed -i.bak "s|^DEEPSEEK_API_KEY=.*$|DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}|g" backend/.env
fi
# Rotate the JWT secret to something machine-specific on first run
if grep -q "dev-only-secret" backend/.env 2>/dev/null; then
  SECRET=$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48)
  sed -i.bak "s|^SECRET_KEY=.*$|SECRET_KEY=${SECRET}|g" backend/.env
  ok "Rotated SECRET_KEY"
fi
rm -f backend/.env.bak

# 3. Pick a Docker Hub mirror if Docker Hub is slow/unreachable (China / restricted networks)
#    Set REGISTRY=docker.m.daocloud.io/  (or registry.cn-hangzhou.aliyuncs.com/) to override.
if [[ -z "${REGISTRY:-}" ]] && ! curl -fsI --max-time 5 https://registry-1.docker.io/v2/ >/dev/null 2>&1; then
  log "Docker Hub is slow — falling back to docker.m.daocloud.io mirror"
  export REGISTRY="docker.m.daocloud.io/"
fi

# 4. Build images
log "Building images (this can take a few minutes the first time; REGISTRY=${REGISTRY:-<default>})"
PUBLIC_PORT="${PUBLIC_PORT:-8088}" PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-http://localhost:${PUBLIC_PORT:-8088}}" REGISTRY="${REGISTRY:-}" \
  $DC -f deploy/docker-compose.yml build --pull

# 5. Bring the stack up
log "Starting the stack"
PUBLIC_PORT="${PUBLIC_PORT:-8088}" PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-http://localhost:${PUBLIC_PORT:-8088}}" REGISTRY="${REGISTRY:-}" \
  $DC -f deploy/docker-compose.yml up -d

# 5. Health check
log "Waiting for the API to come up"
for i in $(seq 1 30); do
  if curl -fs "http://127.0.0.1:${PUBLIC_PORT:-8088}/api/health" >/dev/null 2>&1; then
    ok "API is healthy"
    break
  fi
  sleep 2
done

PUB_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo "<server-ip>")
echo
echo -e "${GRN}====================================================================${NC}"
echo -e "${GRN}  RLab Cortex is live${NC}"
echo -e "  Local URL:    http://127.0.0.1:${PUBLIC_PORT:-8088}"
echo -e "  Public URL:   http://${PUB_IP}:${PUBLIC_PORT:-8088}"
echo -e "${GRN}====================================================================${NC}"
echo
echo "Next steps:"
echo "  1. Open the URL above and create an account."
echo "  2. If you haven't set DEEPSEEK_API_KEY at server level, open Settings"
echo "     in the app and paste your DeepSeek key (BYOK)."
echo "  3. To stop:        $DC -f deploy/docker-compose.yml down"
echo "  4. To view logs:   $DC -f deploy/docker-compose.yml logs -f"
echo "  5. To upgrade:     git pull && bash deploy/deploy.sh"
echo
echo "Cloud-specific notes:"
echo "  Aliyun:  open the security group inbound rule for port ${PUBLIC_PORT:-8088}/tcp."
echo "  Tencent: open the same in 'Network & Security' → 'Security Groups'."
