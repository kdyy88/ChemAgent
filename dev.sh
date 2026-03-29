#!/usr/bin/env bash
# dev.sh — ChemAgent one-shot local dev launcher
#
# Usage:
#   ./dev.sh                    # Docker Redis + backend + ARQ worker + frontend
#   ./dev.sh --no-worker        # Docker Redis + backend + frontend (tasks run in-process via fallback)
#   ./dev.sh --native-redis     # Start Redis via redis-server instead of Docker
#   ./dev.sh --no-redis         # Redis already running externally; skip Redis startup
#
# Environment: variables are loaded from .env in the project root.
# REDIS_URL defaults to redis://localhost:6379/0.
set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'
BLU='\033[0;34m'; MGT='\033[0;35m'; CYN='\033[0;36m'
BLD='\033[1m'; RST='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"
mkdir -p "$LOG_DIR"

# ── PID tracking ──────────────────────────────────────────────────────────────
PIDS=()

cleanup() {
  echo -e "\n${YLW}${BLD}⏹  Shutting down all services…${RST}"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  # Give processes a moment to exit gracefully
  sleep 1
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  echo -e "${GRN}✓  All services stopped.${RST}"
}
trap cleanup EXIT INT TERM

# ── helpers ───────────────────────────────────────────────────────────────────
check_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo -e "${RED}✗  '$1' not found — please install it first.${RST}"; exit 1; }
}

# Prefix every line from a background process with a coloured tag, then tee to log
stream() {                           # stream <label> <colour> <log-file>
  local label="$1" colour="$2" logfile="$3"
  stdbuf -oL sed "s/^/${colour}[${label}]${RST} /" | tee -a "$logfile"
}

wait_tcp() {                         # wait_tcp <host> <port> <label> [max_seconds]
  local host="$1" port="$2" label="$3" max="${4:-20}" i=0
  printf "${CYN}⏳  Waiting for %s (%s:%s)${RST}" "$label" "$host" "$port"
  until nc -z "$host" "$port" 2>/dev/null; do
    sleep 0.5; i=$((i+1))
    printf '.'
    if [[ $i -ge $((max*2)) ]]; then
      echo -e "\n${RED}✗  Timed-out waiting for $label${RST}"; exit 1
    fi
  done
  echo -e "  ${GRN}ready${RST}"
}

# ── parse flags ───────────────────────────────────────────────────────────────
START_REDIS="docker"   # docker | native | false
START_WORKER=true

for arg in "$@"; do
  case "$arg" in
    --no-redis)     START_REDIS=false ;;
    --native-redis) START_REDIS=native ;;
    --docker-redis) START_REDIS=docker ;;
    --no-worker)    START_WORKER=false ;;
  esac
done

# ── load unified .env ────────────────────────────────────────────────────────
if [[ ! -f "$ROOT/.env" ]]; then
  echo -e "${RED}✗  Missing $ROOT/.env — copy .env.example and fill in your values.${RST}"
  exit 1
fi
# Export all vars so every subshell (backend, worker, frontend) inherits them.
set -a
# shellcheck source=/dev/null
source "$ROOT/.env"
set +a

# ── prerequisite checks ───────────────────────────────────────────────────────
echo -e "${BLD}${CYN}━━━  ChemAgent dev launcher  ━━━${RST}"
check_cmd uv
check_cmd pnpm
check_cmd nc

if [[ "$START_REDIS" == native ]]; then
  check_cmd redis-server
elif [[ "$START_REDIS" == docker ]]; then
  check_cmd docker
fi

# ── 0. Redis ──────────────────────────────────────────────────────────────────
if [[ "$START_REDIS" == docker ]]; then
  echo -e "\n${MGT}${BLD}[Redis]${RST} Starting Redis via Docker Compose…"
  docker compose up redis -d 2>&1 | stream "redis   " "$MGT" "$LOG_DIR/redis.log" || true
  wait_tcp 127.0.0.1 6379 "Redis (Docker)"
elif [[ "$START_REDIS" == native ]]; then
  echo -e "\n${MGT}${BLD}[Redis]${RST} Starting redis-server on port 6379…"
  redis-server \
      --port 6379 \
      --maxmemory 128mb \
      --maxmemory-policy allkeys-lru \
      --save "" \
      --appendonly no \
      --loglevel notice \
    > >(stream "redis   " "$MGT" "$LOG_DIR/redis.log") \
    2>&1 &
  PIDS+=($!)
  wait_tcp 127.0.0.1 6379 "Redis"
else
  echo -e "${YLW}⚡  Skipping Redis startup (--no-redis).${RST}"
  wait_tcp 127.0.0.1 6379 "Redis (external)"
fi

# ── 1. Backend (FastAPI / uvicorn) ────────────────────────────────────────────
echo -e "\n${BLU}${BLD}[Backend]${RST} Starting uvicorn on port 8000…"
(
  cd "$ROOT/backend"
  exec uv run uvicorn app.main:app \
      --reload \
      --host 0.0.0.0 \
      --port 8000 \
      --log-level info
) > >(stream "backend " "$BLU" "$LOG_DIR/backend.log") 2>&1 &
PIDS+=($!)
wait_tcp 127.0.0.1 8000 "Backend (FastAPI)"

# ── 2. ARQ Worker ─────────────────────────────────────────────────────────────
if [[ "$START_WORKER" == true ]]; then
  echo -e "\n${GRN}${BLD}[Worker]${RST} Starting ARQ worker…"
  (
    cd "$ROOT/backend"
    exec uv run arq app.worker.WorkerSettings
  ) > >(stream "worker  " "$GRN" "$LOG_DIR/worker.log") 2>&1 &
  PIDS+=($!)
  echo -e "${GRN}[Worker]${RST} launched (PID ${PIDS[-1]})"
else
  echo -e "${YLW}⚡  Skipping ARQ worker (--no-worker). RDKit tasks will run in-process via fallback.${RST}"
fi

# ── 3. Frontend (Next.js) ─────────────────────────────────────────────────────
echo -e "\n${YLW}${BLD}[Frontend]${RST} Starting Next.js dev server…"
(
  cd "$ROOT/frontend"
  exec pnpm dev
) > >(stream "frontend" "$YLW" "$LOG_DIR/frontend.log") 2>&1 &
PIDS+=($!)
wait_tcp 127.0.0.1 3000 "Frontend (Next.js)" 60

# ── Ready ─────────────────────────────────────────────────────────────────────
echo -e "\n${GRN}${BLD}━━━  All services ready  ━━━${RST}"
echo -e "  ${BLD}App:${RST}     ${CYN}http://localhost:3000${RST}"
echo -e "  ${BLD}API:${RST}     ${CYN}http://localhost:8000/docs${RST}"
echo -e "  ${BLD}Redis:${RST}   ${CYN}localhost:6379${RST}"
if [[ "$START_WORKER" == true ]]; then
  echo -e "  ${BLD}Worker:${RST}  ${GRN}running${RST}"
else
  echo -e "  ${BLD}Worker:${RST}  ${YLW}off (tasks run in-process)${RST}"
fi
echo -e "  ${BLD}Logs:${RST}    ${LOG_DIR}/"
echo -e "\n${YLW}Press Ctrl+C to stop everything.${RST}\n"

# ── Wait for any child to exit unexpectedly ───────────────────────────────────
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo -e "${RED}✗  Process PID $pid exited unexpectedly — shutting down.${RST}"
      exit 1
    fi
  done
  sleep 2
done
