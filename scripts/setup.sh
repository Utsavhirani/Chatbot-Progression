#!/usr/bin/env bash
# One-command setup / health check for the AI Business Assistant (macOS, Linux, Git Bash on Windows).
#
#   ./scripts/setup.sh            first-time setup or update: checks, creates .env, builds, starts, verifies
#   ./scripts/setup.sh --check    only verify the environment and the running app (changes nothing)
#   ./scripts/setup.sh --fake     set up without an API key (simulated AI replies)
#   ./scripts/setup.sh --live     also send one real test message to the AI provider during verification
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
CHECK_ONLY=false; FORCE_FAKE=false; LIVE=""
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=true ;;
    --fake) FORCE_FAKE=true ;;
    --live) LIVE="--live" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✘\033[0m %s\n' "$*"; exit 1; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
env_set() {  # env_set KEY VALUE  (replace or append, portable sed)
  if grep -qE "^$1=" .env; then
    local tmp; tmp="$(mktemp)"; awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k{$0=k"="v} {print}' .env > "$tmp" && mv "$tmp" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

step "1. Prerequisites"
command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Start Docker Desktop and re-run."
ok "Docker $(docker version --format '{{.Server.Version}}') is running"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is missing (needs 'docker compose')."
ok "$(docker compose version)"

step "2. Configuration (.env)"
if [ ! -f .env ]; then
  $CHECK_ONLY && fail ".env not found. Run ./scripts/setup.sh (without --check) to create it."
  cp .env.example .env
  PW="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  env_set POSTGRES_PASSWORD "$PW"
  env_set DATABASE_URL "postgresql+asyncpg://assistant:${PW}@127.0.0.1:5433/assistant"
  env_set TEST_DATABASE_URL "postgresql+asyncpg://assistant:${PW}@127.0.0.1:5433/assistant_test"
  ok "created .env with a random database password"
fi
KEY="$(env_get GROQ_API_KEY)"
if ! $CHECK_ONLY && ! $FORCE_FAKE && { [ -z "$KEY" ] || [ "$KEY" = "replace-me" ]; }; then
  if [ -n "${GROQ_API_KEY:-}" ]; then
    KEY="$GROQ_API_KEY"
  elif [ -t 0 ]; then
    printf '  Enter your GroqCloud API key (free at https://console.groq.com/keys),\n  or press Enter to use simulated replies: '
    read -rs KEY; echo
  fi
  if [ -n "$KEY" ]; then env_set GROQ_API_KEY "$KEY"; env_set PROVIDER groq; ok "API key saved to .env";
  else FORCE_FAKE=true; fi
fi
if $FORCE_FAKE && ! $CHECK_ONLY; then env_set PROVIDER fake; warn "PROVIDER=fake: replies are simulated. Add GROQ_API_KEY to .env and re-run for real AI."; fi
WEB_PORT="${WEB_PORT:-$(env_get WEB_PORT)}"; WEB_PORT="${WEB_PORT:-8080}"
ok "PROVIDER=$(env_get PROVIDER), web port $WEB_PORT"

if ! $CHECK_ONLY; then
  step "3. Build and start containers (first run takes a few minutes)"
  docker compose up -d --build
fi

step "$($CHECK_ONLY && echo 3 || echo 4). Waiting for the app to become healthy"
for i in $(seq 1 90); do
  web_id="$(docker compose ps -q web 2>/dev/null || true)"
  state="$( [ -n "$web_id" ] && docker inspect -f '{{.State.Health.Status}}' "$web_id" 2>/dev/null || echo missing)"
  [ "$state" = healthy ] && break
  [ "$state" = missing ] && $CHECK_ONLY && fail "The app is not running. Start it with: docker compose up -d"
  sleep 2
done
[ "$state" = healthy ] || { docker compose ps; fail "The app did not become healthy. See: docker compose logs api"; }
docker compose ps --format '    {{.Service}}: {{.Status}}'
ok "containers healthy"

step "$($CHECK_ONLY && echo 4 || echo 5). Self-check (configuration, database, AI provider)"
if docker compose exec -T api python -m app.doctor $LIVE; then
  printf '\n\033[1;32mReady!\033[0m Open http://localhost:%s\n' "$WEB_PORT"
  printf 'Others on your network can use http://<this-computer-ip>:%s (see docs/sharing.md).\n' "$WEB_PORT"
else
  fail "Self-check failed. Fix the items marked ✘ above, then re-run: ./scripts/setup.sh --check"
fi
