#!/usr/bin/env bash
# Bounded maintainer runner for one non-interactive Codex goal.
set -euo pipefail

GOAL=""
GOAL_FILE=""
EXPECTED_BRANCH=""
MAX_WALL_SECONDS=600
OUTPUT_BASE=".codex_goals"
REAL_API=false
MAX_API_CALLS=0
INSTALL_DEPS=false
ALLOW_REMOTE=false
CODEX_BIN="${CODEX_BIN:-codex}"

usage() {
    cat <<'EOF'
Usage: tools/codex_goal_run.sh --goal TEXT [options]
  --goal TEXT              Goal passed to `codex exec`
  --goal-file PATH         Read the goal from a repository-local file
  --branch NAME            Require the current feature branch to match
  --max-wall-seconds N     Wall-clock limit (default: 600)
  --output-dir DIR         Base under .codex_goals/ or .agent-work/
  --real-api               Permit paid API smoke with a positive call cap
  --max-api-calls N        Maximum paid smoke calls
  --install-deps           Permit the agent to install project dependencies
  --allow-remote           Permit the agent to push or create PRs
  --help                   Show this help
EOF
}

need_value() {
    [[ $# -ge 2 && -n "$2" ]] || { echo "Error: $1 requires a value" >&2; exit 2; }
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --goal) need_value "$@"; GOAL="$2"; shift 2 ;;
        --goal-file) need_value "$@"; GOAL_FILE="$2"; shift 2 ;;
        --branch) need_value "$@"; EXPECTED_BRANCH="$2"; shift 2 ;;
        --max-wall-seconds) need_value "$@"; MAX_WALL_SECONDS="$2"; shift 2 ;;
        --output-dir) need_value "$@"; OUTPUT_BASE="$2"; shift 2 ;;
        --real-api) REAL_API=true; shift ;;
        --max-api-calls) need_value "$@"; MAX_API_CALLS="$2"; shift 2 ;;
        --install-deps) INSTALL_DEPS=true; shift ;;
        --allow-remote) ALLOW_REMOTE=true; shift ;;
        --help) usage; exit 0 ;;
        *) echo "Error: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ "$MAX_WALL_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "Error: --max-wall-seconds must be positive" >&2; exit 2; }
[[ "$MAX_API_CALLS" =~ ^[0-9]+$ ]] || { echo "Error: --max-api-calls must be non-negative" >&2; exit 2; }
[[ -z "$GOAL" || -z "$GOAL_FILE" ]] || { echo "Error: choose --goal or --goal-file" >&2; exit 2; }

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Error: not inside a Git repository" >&2; exit 2; }
cd "$REPO_ROOT"
CURRENT_BRANCH="$(git branch --show-current)"
[[ -n "$CURRENT_BRANCH" && "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "master" ]] || {
    echo "Error: refuse to run on main/master or detached HEAD" >&2; exit 2;
}
[[ -z "$EXPECTED_BRANCH" || "$CURRENT_BRANCH" == "$EXPECTED_BRANCH" ]] || {
    echo "Error: current branch does not match --branch" >&2; exit 2;
}
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || {
    echo "Error: working tree must be clean before an automated goal run" >&2; exit 2;
}

if [[ -n "$GOAL_FILE" ]]; then
    GOAL_PATH="$(realpath -e "$GOAL_FILE" 2>/dev/null)" || { echo "Error: goal file does not exist" >&2; exit 2; }
    [[ "$GOAL_PATH" == "$REPO_ROOT"/* ]] || { echo "Error: goal file must stay inside the repository" >&2; exit 2; }
    GOAL="$(<"$GOAL_PATH")"
fi
[[ -n "$GOAL" ]] || { echo "Error: --goal or --goal-file is required" >&2; exit 2; }
if [[ "$REAL_API" == true && "$MAX_API_CALLS" -le 0 ]]; then
    echo "Error: --real-api requires --max-api-calls > 0" >&2
    exit 2
fi

OUTPUT_BASE="$(python3 - "$OUTPUT_BASE" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"
case "$OUTPUT_BASE" in
    "$REPO_ROOT/.codex_goals"|"$REPO_ROOT/.codex_goals/"*|"$REPO_ROOT/.agent-work"|"$REPO_ROOT/.agent-work/"*) ;;
    *) echo "Error: output must stay under .codex_goals/ or .agent-work/" >&2; exit 2 ;;
esac
mkdir -p "$OUTPUT_BASE"
command -v "$CODEX_BIN" >/dev/null 2>&1 || { echo "Error: Codex executable not found" >&2; exit 127; }

LOCK_DIR="$OUTPUT_BASE/.run-lock"
mkdir "$LOCK_DIR" 2>/dev/null || { echo "Error: another goal run is active" >&2; exit 3; }
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_DIR="$OUTPUT_BASE/$RUN_ID"
mkdir -p "$RUN_DIR"
MANIFEST="$RUN_DIR/manifest.json"
HEARTBEAT="$RUN_DIR/heartbeat.log"
RUN_LOG="$RUN_DIR/codex.log"
START_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMMIT="$(git rev-parse HEAD)"
CHILD_PID=""
HEARTBEAT_PID=""

write_manifest() {
    local end_time="${1:-}" exit_status="${2:-null}"
    START_TIME="$START_TIME" END_TIME="$end_time" EXIT_STATUS="$exit_status" \
    CURRENT_BRANCH="$CURRENT_BRANCH" COMMIT="$COMMIT" RUN_ID="$RUN_ID" \
    MAX_WALL_SECONDS="$MAX_WALL_SECONDS" REAL_API="$REAL_API" \
    MAX_API_CALLS="$MAX_API_CALLS" INSTALL_DEPS="$INSTALL_DEPS" \
    ALLOW_REMOTE="$ALLOW_REMOTE" GOAL="$GOAL" python3 - "$MANIFEST" <<'PY'
import hashlib, json, os, sys
status = os.environ["EXIT_STATUS"]
payload = {
    "schema_version": 1,
    "run_id": os.environ["RUN_ID"],
    "pid": os.getppid(),
    "branch": os.environ["CURRENT_BRANCH"],
    "commit": os.environ["COMMIT"],
    "start_time": os.environ["START_TIME"],
    "end_time": os.environ["END_TIME"] or None,
    "exit_status": None if status == "null" else int(status),
    "max_wall_seconds": int(os.environ["MAX_WALL_SECONDS"]),
    "real_api": os.environ["REAL_API"] == "true",
    "max_api_calls": int(os.environ["MAX_API_CALLS"]),
    "install_deps": os.environ["INSTALL_DEPS"] == "true",
    "allow_remote": os.environ["ALLOW_REMOTE"] == "true",
    "goal_sha256": hashlib.sha256(os.environ["GOAL"].encode()).hexdigest(),
}
with open(sys.argv[1] + ".tmp", "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(sys.argv[1] + ".tmp", sys.argv[1])
PY
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    [[ -z "$HEARTBEAT_PID" ]] || kill "$HEARTBEAT_PID" 2>/dev/null || true
    if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill -INT -- "-$CHILD_PID" 2>/dev/null || kill -INT "$CHILD_PID" 2>/dev/null || true
        sleep 2
        kill -KILL -- "-$CHILD_PID" 2>/dev/null || kill -KILL "$CHILD_PID" 2>/dev/null || true
    fi
    local end_time
    end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    write_manifest "$end_time" "$status"
    printf '[%s] exit_status=%s\n' "$end_time" "$status" >> "$HEARTBEAT"
    rm -rf "$LOCK_DIR"
    exit "$status"
}
trap cleanup EXIT INT TERM

write_manifest
printf '[%s] started branch=%s commit=%s pid=%s\n' "$START_TIME" "$CURRENT_BRANCH" "$COMMIT" "$$" > "$HEARTBEAT"
(
    while true; do
        sleep 30
        printf '[%s] heartbeat\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HEARTBEAT"
    done
) >/dev/null 2>&1 &
HEARTBEAT_PID=$!

export PAWNLOGIC_REAL_API_SMOKE="$REAL_API"
export PAWNLOGIC_EVAL_MAX_API_CALLS="$MAX_API_CALLS"
export PAWNLOGIC_AGENT_INSTALL_DEPS="$INSTALL_DEPS"
export PAWNLOGIC_AGENT_ALLOW_REMOTE="$ALLOW_REMOTE"

set +e
if command -v setsid >/dev/null 2>&1; then
    setsid "$CODEX_BIN" exec "$GOAL" >"$RUN_LOG" 2>&1 &
else
    "$CODEX_BIN" exec "$GOAL" >"$RUN_LOG" 2>&1 &
fi
CHILD_PID=$!
timeout --signal=INT --kill-after=10 "$MAX_WALL_SECONDS" tail --pid="$CHILD_PID" -f /dev/null
TIMEOUT_STATUS=$?
if [[ "$TIMEOUT_STATUS" -eq 124 || "$TIMEOUT_STATUS" -eq 137 ]]; then
    kill -INT -- "-$CHILD_PID" 2>/dev/null || kill -INT "$CHILD_PID" 2>/dev/null || true
    timeout 10 tail --pid="$CHILD_PID" -f /dev/null >/dev/null 2>&1 || true
    kill -KILL -- "-$CHILD_PID" 2>/dev/null || kill -KILL "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
    CHILD_PID=""
    set -e
    echo "Error: goal exceeded ${MAX_WALL_SECONDS}s" >&2
    exit 124
fi
wait "$CHILD_PID"
EXIT_STATUS=$?
set -e
CHILD_PID=""
exit "$EXIT_STATUS"
