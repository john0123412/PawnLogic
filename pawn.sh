#!/bin/bash
# ── PawnLogic 启动器 ─────────────────────────────────────
# 自动定位 venv 并激活，然后运行 main.py。
# 用法: ln -sf ~/.local/share/pawnlogic/pawn.sh ~/.local/bin/pawn

# 1. 追踪真实路径（解决软链接调用问题）
REAL_PATH=$(readlink -f "${BASH_SOURCE[0]}")
SCRIPT_DIR="$(cd "$(dirname "$REAL_PATH")" && pwd)"

# 2. 寻找 venv（仅保留相对路径，提高迁移性）
_VENV_CANDIDATES=(
    "$SCRIPT_DIR/venv/bin/activate"
    "$SCRIPT_DIR/.venv/bin/activate"
)

_VENV_FOUND=""
for _candidate in "${_VENV_CANDIDATES[@]}"; do
    if [ -f "$_candidate" ]; then
        _VENV_FOUND="$_candidate"
        break
    fi
done

# 3. 环境准备检查
if [ -n "$_VENV_FOUND" ]; then
    source "$_VENV_FOUND"
else
    # 增加对系统 python3 的检查
    if ! command -v python3 &> /dev/null; then
        echo -e "\033[91m  ✗ 未找到 python3，请先安装 Python。\033[0m"
        exit 1
    fi

    if ! python3 -c "import nest_asyncio" 2>/dev/null; then
        echo -e "\033[91m  ✗ 未找到虚拟环境，且系统环境缺少依赖。\033[0m"
        echo -e "\033[93m  建议在项目目录执行:\033[0m"
        echo -e "    cd $SCRIPT_DIR && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
fi

# 4. 运行检查：确保 main.py 确实存在
if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "\033[91m  ✗ 错误: 找不到入口文件 $SCRIPT_DIR/main.py\033[0m"
    exit 1
fi

# 5. 启动（使用 exec 替换进程，透传所有参数 $@）
exec python3 "$SCRIPT_DIR/main.py" "$@"
