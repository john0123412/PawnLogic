#!/usr/bin/env bash
# PawnLogic pre-commit gate.
#
# Runs the same checks the CI runs on the files staged for commit. Hooked
# by .git/hooks/pre-commit (see "make install-hooks" below) and by CI.
# Exit code 0 = pass, non-zero = block the commit.
#
# Phases:
#   1. Python: `ruff check` on staged .py files (only if any are
#      staged; otherwise skip). Uses the venv at venv/bin/ruff if
#      present, otherwise the system `ruff` binary. Matches what CI's
#      🦀 Lint (ruff) job runs (`ruff check .`).
#   2. Rust: `cargo fmt --check` in frontends/ratatui, only if a Rust
#      file there is staged. Matches CI's 🦀 Rust Frontend gate.
#   3. Sanity: no absolute local paths, no provider API keys in the
#      staged diff (mirrors the AGENT.md "Before every commit" leak
#      scan, scoped to the staged set).
#
# This script never modifies files. If a stage fails, fix the
# formatting with `ruff check --fix <file>` or `cargo fmt` and re-stage.
#
# To install as a real git hook:
#   ln -s ../../tools/precommit.sh .git/hooks/pre-commit
# Or copy .git/hooks/pre-commit.sample over the symlink and edit.

set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STAGED_PY="$(git diff --cached --name-only --diff-filter=ACMR -- '*.py' || true)"
STAGED_RS="$(git diff --cached --name-only --diff-filter=ACMR -- 'frontends/ratatui/**/*.rs' || true)"
STAGED_ANY="$(git diff --cached --name-only --diff-filter=ACMR || true)"

run_ruff() {
    # Mirrors CI: only `ruff check` is run there, not `ruff format`.
    # `format --check` is strictly stronger than what CI enforces and
    # would block commits for style-only diffs on legacy files. Keep
    # parity with CI so local hooks never say "fail" when CI says "ok".
    if [ -x venv/bin/ruff ]; then
        venv/bin/ruff check "$@"
    elif command -v ruff >/dev/null 2>&1; then
        ruff check "$@"
    else
        echo "  ✗ ruff not found (install with: pip install ruff)"
        return 1
    fi
}

run_cargo_fmt() {
    (cd frontends/ratatui && cargo fmt --check)
}

count_lines() {
    if [ -z "$1" ]; then
        echo 0
    else
        echo "$1" | wc -l
    fi
}

echo "[pre-commit] staged files: $(count_lines "$STAGED_ANY")"

if [ -n "$STAGED_PY" ]; then
    echo "[pre-commit] ruff check on $(count_lines "$STAGED_PY") Python file(s)"
    # shellcheck disable=SC2086
    run_ruff $STAGED_PY || exit 1
else
    echo "[pre-commit] no Python files staged; skipping ruff"
fi

if [ -n "$STAGED_RS" ]; then
    echo "[pre-commit] cargo fmt --check on $(count_lines "$STAGED_RS") Rust file(s)"
    run_cargo_fmt || exit 1
else
    echo "[pre-commit] no Rust files staged; skipping cargo fmt"
fi

if [ -n "$STAGED_ANY" ]; then
    echo "[pre-commit] leak scan on staged diff"
    # Only scan the *added* lines of the staged diff (those that begin
    # with `+` but not `+++` which is the file header). Source code
    # legitimately contains the patterns as string literals (regex,
    # test fixtures, test paths) so we additionally skip the staged
    # diff hunks of `tools/precommit.sh` itself, which embeds the
    # patterns as the very thing we are matching against.
    ADDED_LINES="$(git diff --cached | grep -E '^\+' | grep -vE '^\+{3}' || true)"
    SELF_DIFF=""
    if echo "$STAGED_ANY" | grep -qE '^tools/precommit\.sh$'; then
        SELF_DIFF="$(git diff --cached -- tools/precommit.sh | grep -E '^\+' | grep -vE '^\+{3}' || true)"
        # `sort -u | grep -vF` may exit 1 when SELF_DIFF is empty, so wrap in
        # `|| true` to keep `set -e` from killing the script during the
        # self-exclude case.
        ADDED_LINES="$(printf '%s\n%s\n' "$ADDED_LINES" "$SELF_DIFF" | sort -u | { grep -vF "$SELF_DIFF" || true; })"
    fi
    if echo "$ADDED_LINES" | grep -nE "/home/[^/ ]+/|/Users/[^/ ]+/|C:\\\\Users\\\\" >/dev/null; then
        echo "  ✗ staged diff (added lines) contains an absolute local path"
        echo "$ADDED_LINES" | grep -nE "/home/[^/ ]+/|/Users/[^/ ]+/|C:\\\\Users\\\\" | head -3
        exit 1
    fi
    if echo "$ADDED_LINES" | grep -nE "sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}|tp-[a-z0-9]{30,}|AIza[A-Za-z0-9_-]{35}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}" >/dev/null; then
        echo "  ✗ staged diff (added lines) contains a provider API key"
        echo "$ADDED_LINES" | grep -nE "sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-|svcacct-|live-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}" | head -3
        exit 1
    fi
else
    echo "[pre-commit] no files staged; skipping leak scan"
fi

echo "[pre-commit] all checks passed"
