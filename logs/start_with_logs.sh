#!/usr/bin/env bash
# ── ChemAgent: start backend + worker, tee all output to timestamped log files ──
# Usage:
#   ./logs/start_with_logs.sh                           # INFO level (default)
#   LOG_LEVEL=DEBUG ./logs/start_with_logs.sh           # full debug (larger files)
#   UVICORN_LOG_LEVEL=debug ./logs/start_with_logs.sh   # verbose uvicorn access log
#   LOG_DIR=/tmp/mylogs ./logs/start_with_logs.sh       # custom log directory
#
# Output files (tail -f them in separate terminals):
#   $LOG_DIR/backend_YYYYMMDD_HHMMSS.log
#   $LOG_DIR/worker_YYYYMMDD_HHMMSS.log
#   $LOG_DIR/combined_YYYYMMDD_HHMMSS.log   (merged, with [BACKEND]/[WORKER] prefix)
#
# NOTE: LOG_FILE env var is intentionally NOT used — don't set it externally.
# The script uses shell-level tee to capture output; using both LOG_FILE and tee
# would double-write every line to the same file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$REPO_ROOT/logs}"
TS="$(date +%Y%m%d_%H%M%S)"

BACKEND_LOG="$LOG_DIR/backend_${TS}.log"
WORKER_LOG="$LOG_DIR/worker_${TS}.log"
COMBINED_LOG="$LOG_DIR/combined_${TS}.log"

mkdir -p "$LOG_DIR"

echo "[start_with_logs] Logs directory : $LOG_DIR"
echo "[start_with_logs] Backend log    : $BACKEND_LOG"
echo "[start_with_logs] Worker log     : $WORKER_LOG"
echo "[start_with_logs] Combined log   : $COMBINED_LOG"
echo ""

# ── Named pipes for the combined log ─────────────────────────────────────────
BACKEND_PIPE="$LOG_DIR/.pipe_backend_${TS}"
WORKER_PIPE="$LOG_DIR/.pipe_worker_${TS}"
mkfifo "$BACKEND_PIPE" "$WORKER_PIPE"

cleanup() {
    echo "[start_with_logs] Shutting down..."
    kill "$BACKEND_PID" "$WORKER_PID" "$MERGER_PID" 2>/dev/null || true
    rm -f "$BACKEND_PIPE" "$WORKER_PIPE"
}
trap cleanup EXIT INT TERM

# ── Merger: reads both pipes, prefixes lines, writes to combined log ──────────
(
    while IFS= read -r line; do
        printf '[BACKEND] %s\n' "$line"
    done < "$BACKEND_PIPE" &
    while IFS= read -r line; do
        printf '[WORKER]  %s\n' "$line"
    done < "$WORKER_PIPE" &
    wait
) >> "$COMBINED_LOG" &
MERGER_PID=$!

# ── Backend ───────────────────────────────────────────────────────────────────
(
    cd "$REPO_ROOT/backend"
    # LOG_FILE is intentionally NOT set here — the in-process FileHandler and
    # the tee below must NOT write to the same file (double-write bug).
    # All output goes through tee → one clean copy in BACKEND_LOG,
    # one copy forwarded to the combined-log pipe.
    PYTHONUNBUFFERED=1 LOG_LEVEL="${LOG_LEVEL:-INFO}" \
        uv run uvicorn app.main:app \
        --reload \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level "${UVICORN_LOG_LEVEL:-info}" \
        2>&1 | tee "$BACKEND_LOG" > "$BACKEND_PIPE"
) &
BACKEND_PID=$!

# ── Worker ────────────────────────────────────────────────────────────────────
(
    cd "$REPO_ROOT/backend"
    PYTHONUNBUFFERED=1 LOG_LEVEL="${LOG_LEVEL:-INFO}" ARQ_LOG_LEVEL="${ARQ_LOG_LEVEL:-info}" \
        uv run arq app.worker.WorkerSettings \
        2>&1 | tee "$WORKER_LOG" > "$WORKER_PIPE"
) &
WORKER_PID=$!

echo "[start_with_logs] Backend PID: $BACKEND_PID | Worker PID: $WORKER_PID"
echo "[start_with_logs] To follow combined log: tail -f $COMBINED_LOG"
echo ""

# ── Wait (Ctrl-C to stop) ──────────────────────────────────────────────────────
wait "$BACKEND_PID" "$WORKER_PID"
