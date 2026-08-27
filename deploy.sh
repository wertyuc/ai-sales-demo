#!/usr/bin/env bash
#
# One-command deployment for the AI Sales Demo Suite.
#
#   ./deploy.sh              build + start (generates .env on first run)
#   ./deploy.sh --port 8090  publish on a different port
#   ./deploy.sh --reset      wipe the database volume and re-seed
#   ./deploy.sh --logs       follow the logs
#   ./deploy.sh --down       stop everything
#
set -euo pipefail

cd "$(dirname "$0")"

PORT=""
RESET=0
ACTION="up"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --reset) RESET=1; shift ;;
    --logs) ACTION="logs"; shift ;;
    --down) ACTION="down"; shift ;;
    --restart) ACTION="restart"; shift ;;
    -h|--help) sed -n '3,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

case "$ACTION" in
  logs) compose logs -f --tail=120; exit 0 ;;
  down) compose down; echo "stopped"; exit 0 ;;
  restart) compose restart; compose ps; exit 0 ;;
esac

# --- .env -------------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "==> generating .env with fresh secrets"
  ADMIN_PASSWORD="$(random_hex 6)"
  cp .env.example .env
  sed -i.bak \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(random_hex 16)|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$(random_hex 32)|" \
    -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASSWORD}|" \
    .env
  rm -f .env.bak
  echo
  echo "    demo login:    admin"
  echo "    demo password: ${ADMIN_PASSWORD}"
  echo
  echo "    (stored in .env — keep it out of git)"
  echo
fi

if [[ -n "$PORT" ]]; then
  if grep -q '^WEB_PORT=' .env; then
    sed -i.bak "s|^WEB_PORT=.*|WEB_PORT=${PORT}|" .env && rm -f .env.bak
  else
    echo "WEB_PORT=${PORT}" >> .env
  fi
fi

WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2 || echo 8080)"
WEB_PORT="${WEB_PORT:-8080}"

if [[ "$RESET" == "1" ]]; then
  echo "==> removing the database volume (all demo data will be re-seeded)"
  compose down -v
fi

echo "==> building images"
compose build

echo "==> starting services"
compose up -d

echo "==> waiting for the API to become healthy"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${WEB_PORT}/api/system/health" >/dev/null 2>&1; then
    echo "    ready"
    break
  fi
  sleep 2
done

compose ps

IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1)"
echo
echo "  Demo:  http://${IP}:${WEB_PORT}"
echo "  Login: $(grep -E '^ADMIN_USERNAME=' .env | cut -d= -f2)"
echo "  Pass:  $(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2)"
echo
echo "  logs:    ./deploy.sh --logs"
echo "  restart: ./deploy.sh --restart"
echo "  reset:   ./deploy.sh --reset"
