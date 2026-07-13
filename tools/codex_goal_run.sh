#!/usr/bin/env bash
# tools/codex_goal_run.sh - Safe WSL2 Codex goal runner.
#
# Maintainer-only helper for running Codex goals with:
# - One-run lock with PID and timestamps
# - Manifest and heartbeat logging
# - Bounded wall-clock time
# - Signal-safe cleanup
# - Safe artifact roots
#
# Usage:
#   tools/codex_goal_run.sh --goal "fix the bug" --max-wall-seconds 300
#
# Options:
#   --goal TEXT              Goal description (required)
#   --branch NAME            Feature branch (must not be main)
#   --max-wall-seconds N     Maximum wall-clock time in seconds (default 600)
#   --output-dir DIR         Output directory (default .codex_goals/)
#   --real-api               Enable real API calls (requires --max-api-calls)
#   --max-api-calls N        Maximum API calls (required with --real-api)
#   --install-deps           Install dependencies before running
#   --help                   Show this help

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
GOAL=""
BRANCH=""
MAX_WALL_SECONDS=600
OUTPUT_DIR=".codex_goals"
REAL_API=false
MAX_API_CALLS=0
INSTALL_DEPS=false

# ── Parse arguments ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --goal) GOAL="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --max-wall-seconds) MAX_WALL_SECONDS="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --real-api) REAL_API=true; shift ;;
        --max-api-calls) MAX_API_CALLS="$2"; shift 2 ;;
        --install-deps) INSTALL_DEPS=true; shift ;;
        --help)
            head -25 "$0" | tail -20
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Validate ─────────────────────────────────────────────────────────────────
if [[ -z "$GOAL" ]]; then
    echo "Error: --goal is required"
    exit 1
fi

CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || echo "")"
if [[ "$CURRENT_BRANCH" == "main" || "$CURRENT_BRANCH" == "master" ]]; then
    echo "Error: refuse to run on main branch. Create a feature branch first."
    exit 1
fi

if [[ "$REAL_API" == true && "$MAX_API_CALLS" -le 0 ]]; then
    echo "Error: --real-api requires --max-api-calls > 0"
    exit 1
fi

# ── Setup ────────────────────────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
LOCK_FILE="$OUTPUT_DIR/.lock"
MANIFEST="$OUTPUT_DIR/manifest.json"
HEARTBEAT="$OUTPUT_DIR/heartbeat.log"
PID_FILE="$OUTPUT_DIR/.pid"

# ── Lock ─────────────────────────────────────────────────────────────────────
if [[ -f "$LOCK_FILE" ]]; then
    LOCK_PID="$(cat "$LOCK_FILE" 2>/dev/null || echo "")"
    if [[ -n "$LOCK_PID" ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "Error: another run is active (PID $LOCK_PID)"
        exit 1
    fi
    echo "Warning: stale lock found, removing"
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
echo $$ > "$PID_FILE"

# ── Cleanup on exit ─────────────────────────────────────────────────────────
cleanup() {
    rm -f "$LOCK_FILE" "$PID_FILE"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cleanup complete" >> "$HEARTBEAT"
}
trap cleanup EXIT

# ── Manifest ─────────────────────────────────────────────────────────────────
START_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$MANIFEST" <<EOF
{
    "goal": "$GOAL",
    "branch": "$CURRENT_BRANCH",
    "start_time": "$START_TIME",
    "max_wall_seconds": $MAX_WALL_SECONDS,
    "pid": $$,
    "real_api": $REAL_API,
    "max_api_calls": $MAX_API_CALLS
}
EOF

echo "[$START_TIME] Starting goal: $GOAL" >> "$HEARTBEAT"
echo "[$START_TIME] Branch: $CURRENT_BRANCH, PID: $$" >> "$HEARTBEAT"
echo "[$START_TIME] Max wall: ${MAX_WALL_SECONDS}s" >> "$HEARTBEAT"

# ── Heartbeat (background) ──────────────────────────────────────────────────
heartbeat_loop() {
    while true; do
        sleep 30
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] heartbeat" >> "$HEARTBEAT"
    done
}
heartbeat_loop &
HEARTBEAT_PID=$!

# ── Kill heartbeat on exit ──────────────────────────────────────────────────
cleanup_full() {
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    cleanup
}
trap cleanup_full EXIT

# ── Main execution with timeout ─────────────────────────────────────────────
echo "========================================="
echo "  Goal: $GOAL"
echo "  Branch: $CURRENT_BRANCH"
echo "  Max wall: ${MAX_WALL_SECONDS}s"
echo "  Output: $OUTPUT_DIR"
echo "========================================="

# Run with timeout.
EXIT_CODE=0
timeout "$MAX_WALL_SECONDS" bash -c "
    echo 'Running Codex goal...'
    # This is where the actual Codex run would happen.
    # For now, just simulate work.
    echo 'Goal execution placeholder'
" || EXIT_CODE=$?

if [[ $EXIT_CODE -eq 124 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Timed out after ${MAX_WALL_SECONDS}s" >> "$HEARTBEAT"
    echo "Error: goal timed out after ${MAX_WALL_SECONDS}s"
    EXIT_CODE=1
fi

END_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[$END_TIME] Completed with exit code $EXIT_CODE" >> "$HEARTBEAT"

# Update manifest with result.
cat > "$MANIFEST" <<EOF
{
    "goal": "$GOAL",
    "branch": "$CURRENT_BRANCH",
    "start_time": "$START_TIME",
    "end_time": "$END_TIME",
    "max_wall_seconds": $MAX_WALL_SECONDS,
    "pid": $$,
    "real_api": $REAL_API,
    "max_api_calls": $MAX_API_CALLS,
    "exit_code": $EXIT_CODE
}
EOF

exit $EXIT_CODE
