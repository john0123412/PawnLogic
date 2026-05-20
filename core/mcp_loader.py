"""
core/mcp_loader.py — MCP 服务加载与子进程管理

读取 mcp_configs.json，将 .env 中的密钥注入 MCP 子进程环境，
通过标准 stdio 协议启动外部 MCP 服务。
"""
import os
import re
import json
import subprocess
from pathlib import Path
from typing import Optional

_PAWNLOGIC_DIR = Path.home() / ".pawnlogic"
_CONFIG_PATH = _PAWNLOGIC_DIR / "mcp_configs.json"
_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "mcp_configs.example.json"

# 运行中的 MCP 子进程注册表 {服务名: Popen 对象}
_running_servers: dict[str, subprocess.Popen] = {}


def _inject_env_vars(value: str) -> str:
    """将字符串中的 ${VAR_NAME} 替换为对应的环境变量值。"""
    def replace(m: re.Match) -> str:
        var_name = m.group(1)
        val = os.getenv(var_name, "")
        if not val:
            print(f"[MCP WARNING] 环境变量 {var_name} 未设置，服务可能无法正常工作")
        return val
    return re.sub(r"\$\{(\w+)\}", replace, value)


def load_mcp_config() -> dict:
    """
    加载 mcp_configs.json。
    文件不存在时返回空字典（MCP 功能降级）。
    """
    if not _CONFIG_PATH.exists():
        if _EXAMPLE_PATH.exists():
            print(f"[MCP] 提示：未找到 mcp_configs.json，"
                  f"可复制 mcp_configs.example.json 并按需修改")
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[MCP ERROR] mcp_configs.json 解析失败：{e}")
        return {}


def get_mcp_servers() -> dict:
    """返回已配置的 MCP 服务字典。"""
    return load_mcp_config().get("mcpServers", {})


def spawn_mcp_process(name: str, cfg: dict) -> Optional[subprocess.Popen]:
    """
    按照标准 stdio 协议启动一个 MCP 子进程。

    Args:
        name: 服务名称（用于日志和注册表）
        cfg:  服务配置字典，包含 command / args / env

    Returns:
        成功返回 Popen 对象，失败返回 None。
    """
    child_env = {**os.environ}
    for k, v in cfg.get("env", {}).items():
        child_env[k] = _inject_env_vars(str(v))

    cmd = [cfg["command"]] + cfg.get("args", [])

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
        )
        _running_servers[name] = proc
        print(f"[MCP] 已启动服务：{name} (PID {proc.pid})")
        return proc
    except FileNotFoundError:
        print(f"[MCP ERROR] 找不到命令：{cfg['command']}，请确认已安装")
        return None
    except Exception as e:
        print(f"[MCP ERROR] 启动 {name} 失败：{e}")
        return None


def start_all_servers() -> dict[str, subprocess.Popen]:
    """启动 mcp_configs.json 中定义的所有 MCP 服务。"""
    servers = get_mcp_servers()
    result = {}
    for name, cfg in servers.items():
        proc = spawn_mcp_process(name, cfg)
        if proc:
            result[name] = proc
    return result


def stop_all_servers() -> None:
    """优雅关闭所有 MCP 子进程。"""
    for name, proc in _running_servers.items():
        try:
            proc.terminate()
            proc.wait(timeout=5)
            print(f"[MCP] 已停止服务：{name}")
        except Exception as e:
            print(f"[MCP WARNING] 停止 {name} 时出错：{e}")
            proc.kill()
    _running_servers.clear()


def get_server_status() -> dict[str, str]:
    """返回各服务运行状态。"""
    status = {}
    for name, proc in _running_servers.items():
        if proc.poll() is None:
            status[name] = f"运行中 (PID {proc.pid})"
        else:
            status[name] = f"已退出 (返回码 {proc.returncode})"
    return status
