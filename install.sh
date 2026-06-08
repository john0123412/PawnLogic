#!/usr/bin/env bash
set -euo pipefail

# PawnLogic installer.
# Installs the official Python package into an isolated venv and exposes a
# small ~/.local/bin/pawn launcher. User data stays in ~/.pawnlogic.

APP_HOME="${PAWNLOGIC_INSTALL_DIR:-$HOME/.local/share/pawnlogic}"
BIN_DIR="${PAWNLOGIC_BIN_DIR:-$HOME/.local/bin}"
PACKAGE_SPEC="${PAWNLOGIC_PACKAGE_SPEC:-pawnlogic}"
PYTHON_BIN="${PYTHON:-python3}"

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf '\033[91m  ✗ Missing required command: %s\033[0m\n' "$1" >&2
        exit 1
    fi
}

need_cmd "$PYTHON_BIN"

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
    printf '\033[91m  ✗ PawnLogic requires Python 3.10+.\033[0m\n' >&2
    exit 1
fi

mkdir -p "$APP_HOME" "$BIN_DIR"

"$PYTHON_BIN" -m venv "$APP_HOME/venv"
"$APP_HOME/venv/bin/python" -m pip install --upgrade pip
"$APP_HOME/venv/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

cat > "$BIN_DIR/pawn" <<EOF
#!/usr/bin/env bash
exec "$APP_HOME/venv/bin/pawn" "\$@"
EOF
chmod 755 "$BIN_DIR/pawn"

printf '\033[92m  ✓ PawnLogic installed.\033[0m\n'
printf '  Command: %s/pawn\n' "$BIN_DIR"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        printf '\033[93m  ! Add this to your shell profile if pawn is not found:\033[0m\n'
        printf '    export PATH="%s:$PATH"\n' "$BIN_DIR"
        ;;
esac
