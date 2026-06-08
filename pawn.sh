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

# 1. 追踪真实路径（解决软链接调用问题）
REAL_PATH=$(readlink_f "${BASH_SOURCE[0]}")
SCRIPT_DIR="$(cd "$(dirname "$REAL_PATH")" && pwd)"

# 2. 寻找 venv（仅保留相对路径，提高迁移性）
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

# 3. 环境准备检查
if [ -z "$_PYTHON" ]; then
    if ! command -v python3 &> /dev/null; then
        echo -e "\033[91m  ✗ 未找到 python3，请先安装 Python 3.10+。\033[0m"
        exit 1
    fi
    _PYTHON="$(command -v python3)"
fi

# 4. 运行检查：源码安装器需要包入口存在
if [ ! -d "$SCRIPT_DIR/pawnlogic" ]; then
    echo -e "\033[91m  ✗ 错误: 找不到包目录 $SCRIPT_DIR/pawnlogic\033[0m"
    exit 1
fi

# 5. 启动（使用 exec 替换进程，透传所有参数 $@）
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$_PYTHON" -m pawnlogic "$@"
