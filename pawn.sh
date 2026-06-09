#!/bin/bash
# PawnLogic source-checkout launcher.
# Finds a local virtual environment when available, then runs the package entry
# point. The CLI implementation lives in pawnlogic.cli; this script must not
# call main.py directly.

readlink_f() {
    if readlink -f "$1" >/dev/null 2>&1; then
        readlink -f "$1"
    else
        local target="$1"
        local dir
        while [ -L "$target" ]; do
            dir="$(cd "$(dirname "$target")" && pwd)"
            target="$(readlink "$target")"
            case "$target" in
                /*) ;;
                *) target="$dir/$target" ;;
            esac
        done
        cd "$(dirname "$target")" && printf '%s/%s\n' "$(pwd)" "$(basename "$target")"
    fi
}

# 1. Resolve the real path so symlinked launchers work.
REAL_PATH=$(readlink_f "${BASH_SOURCE[0]}")
SCRIPT_DIR="$(cd "$(dirname "$REAL_PATH")" && pwd)"

# 2. Find a local virtual environment. Keep paths relative for portability.
_PYTHON_CANDIDATES=(
    "$SCRIPT_DIR/venv/bin/python3"
    "$SCRIPT_DIR/venv/bin/python"
    "$SCRIPT_DIR/.venv/bin/python3"
    "$SCRIPT_DIR/.venv/bin/python"
)

_PYTHON=""
for _candidate in "${_PYTHON_CANDIDATES[@]}"; do
    if [ -x "$_candidate" ]; then
        _PYTHON="$_candidate"
        break
    fi
done

# 3. Environment readiness check.
if [ -z "$_PYTHON" ]; then
    if ! command -v python3 &> /dev/null; then
        echo -e "\033[91m  ✗ python3 was not found. Please install Python 3.10+.\033[0m"
        exit 1
    fi
    _PYTHON="$(command -v python3)"
fi

# 4. Runtime check: the source launcher needs the package entrypoint.
if [ ! -d "$SCRIPT_DIR/pawnlogic" ]; then
    echo -e "\033[91m  ✗ Error: package directory not found: $SCRIPT_DIR/pawnlogic\033[0m"
    exit 1
fi

# 5. Start the CLI. exec replaces this process and forwards all arguments.
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$_PYTHON" -m pawnlogic "$@"
