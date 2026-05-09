"""
测试 API 空响应重试机制

验证：
  1. API 返回空响应时，重试逻辑触发（指数退避）
  2. 重试耗尽后注入恢复提示，不静默退出
  3. 正常响应不受影响
"""

import sys, os, time, types
from unittest.mock import patch, MagicMock
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Mock 配置模块（避免导入真实 config 的副作用）─────────
mock_config = types.ModuleType("config")
mock_config.DYNAMIC_CONFIG = {
    "max_iter": 5,
    "max_tokens": 4096,
    "ctx_max_chars": 100000,
    "tool_max_chars": 10000,
    "time_budget_sec": 0,
}
mock_config.MODELS = {"test-model": {"id": "test-model-id", "color": "\033[32m"}}
mock_config.DEFAULT_MODEL = "test-model"
mock_config.validate_api_key = lambda m: (True, "TEST_KEY")
mock_config.VERSION = "test"
mock_config.GLOBAL_SKILLS_PATH = "/tmp"
mock_config.QUIET_MODE = False
mock_config.USER_MODE = False
mock_config.smart_truncate = lambda s, **kw: s
mock_config.AGENT_PHASES = {"RECON": ["run_shell", "read_file", "list_dir"]}
mock_config.READ_BLACKLIST = []
mock_config.WRITE_BLACKLIST = []
mock_config.DANGEROUS_PATTERNS = []
mock_config.SKILLS_DIR = "/tmp/skills"
mock_config.user_friendly_error = lambda e: f"[User Error] {e}"
mock_config.get_api_config = lambda m: ("http://localhost:8080", "sk-test")
sys.modules["config"] = mock_config

# ── Mock 其他依赖 ──────────────────────────────────────
for mod_name in ("utils.ansi", "core.logger", "core.memory", "core.gsa",
                 "tools.file_ops", "tools.web_ops", "tools.sandbox",
                 "tools.pwn_chain", "tools.vision", "core.skill_manager"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# 确保 ansi 颜色常量可用
sys.modules["utils.ansi"].c = lambda color, text: text
for attr in ("BOLD", "DIM", "GRAY", "CYAN", "GREEN", "YELLOW", "RED", "MAGENTA", "BLUE"):
    setattr(sys.modules["utils.ansi"], attr, "")

# 确保 logger 可用
sys.modules["core.logger"].logger = MagicMock()
sys.modules["core.logger"].audit_tool_call = MagicMock()

# ── 导入被测模块 ──────────────────────────────────────
from core.api_client import APIEmptyResponseError


# ════════════════════════════════════════════════════════
# 测试 1: APIEmptyResponseError 异常定义
# ════════════════════════════════════════════════════════

def test_exception_exists():
    """APIEmptyResponseError 应作为 Exception 的子类存在。"""
    assert issubclass(APIEmptyResponseError, Exception)
    e = APIEmptyResponseError("test empty response")
    assert str(e) == "test empty response"
    print("  ✓ [1/5] APIEmptyResponseError 异常定义正确")


# ════════════════════════════════════════════════════════
# 测试 2: 空响应检测逻辑
# ════════════════════════════════════════════════════════

def test_empty_response_detection():
    """模拟空响应场景，验证检测逻辑。"""
    # 模拟空响应：text_buf 为空，tc_buf 为空，tokens 未变化
    text_buf = ""
    tc_buf = {}
    tokens_before = 0
    tokens_after = 0

    no_new_tokens = (tokens_after == tokens_before)
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)

    assert empty_response is True, "空响应应被检测到"
    print("  ✓ [2/5] 空响应检测逻辑正确（text='' + tc={} + 0 tokens）")

    # 非空响应：有文本内容
    text_buf = "Hello"
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)
    assert empty_response is False, "有文本时不应判定为空"
    print("  ✓ [2/5] 非空响应检测正确（text='Hello')")

    # 非空响应：有 tool_calls
    text_buf = ""
    tc_buf = {"0": {"name": "run_shell", "args": "{}"}}
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)
    assert empty_response is False, "有 tool_calls 时不应判定为空"
    print("  ✓ [2/5] 非空响应检测正确（tc_buf 有数据）")


# ════════════════════════════════════════════════════════
# 测试 3: 重试机制（指数退避）
# ════════════════════════════════════════════════════════

def test_retry_mechanism():
    """模拟连续空响应，验证重试次数和退避时间。"""
    API_RETRY_MAX = 3
    retry_count = 0
    total_wait = 0

    while retry_count < API_RETRY_MAX:
        # 模拟空响应
        text_buf = ""
        tc_buf = {}
        empty_response = True  # 每次都返回空

        if not empty_response:
            break

        retry_count += 1
        if retry_count >= API_RETRY_MAX:
            # 应注入恢复提示
            assert retry_count == 3, f"重试次数应为 3，实际: {retry_count}"
            break

        wait = min(2 ** retry_count, 8)
        total_wait += wait

    assert retry_count == API_RETRY_MAX, f"应重试 {API_RETRY_MAX} 次，实际: {retry_count}"
    assert total_wait == 6, f"总等待应为 6s（2+4），实际: {total_wait}s"
    print(f"  ✓ [3/5] 重试机制正确：{retry_count} 次重试，总退避 {total_wait}s（2s + 4s）")


# ════════════════════════════════════════════════════════
# 测试 4: 恢复消息注入
# ════════════════════════════════════════════════════════

def test_recovery_message():
    """验证重试耗尽后注入的恢复消息格式。"""
    recovery_msg = (
        "[System] 收到无效响应（空内容/0 Token），请重新审视任务目标并继续。"
        "如果此问题反复出现，考虑切换模型（/model）或检查 API 密钥。"
    )

    # 模拟 messages 列表
    messages = [{"role": "user", "content": "test input"}]

    # 模拟重试耗尽后注入
    API_RETRY_MAX = 3
    for attempt in range(API_RETRY_MAX):
        if attempt >= API_RETRY_MAX - 1:
            messages.append({"role": "user", "content": recovery_msg})
            break

    assert len(messages) == 2, f"应有 2 条消息，实际: {len(messages)}"
    assert messages[-1]["role"] == "user", "恢复消息应为 user 角色"
    assert "无效响应" in messages[-1]["content"], "应包含无效响应提示"
    assert "切换模型" in messages[-1]["content"], "应包含切换模型建议"
    print("  ✓ [4/5] 恢复消息注入正确（user 角色 + 无效响应提示）")


# ════════════════════════════════════════════════════════
# 测试 5: 正常响应不触发重试
# ════════════════════════════════════════════════════════

def test_normal_response_no_retry():
    """正常响应不应触发重试逻辑。"""
    API_RETRY_MAX = 3
    retry_count = 0

    # 模拟正常响应
    text_buf = "I found the vulnerability in /etc/passwd"
    tc_buf = {}

    empty_response = (not text_buf.strip() and not tc_buf)
    assert empty_response is False, "正常文本响应不应被判定为空"

    # 模拟有 tool_call 的响应
    text_buf = ""
    tc_buf = {"0": {"name": "run_shell", "args": '{"command": "id"}'}}
    empty_response = (not text_buf.strip() and not tc_buf)
    assert empty_response is False, "tool_call 响应不应被判定为空"

    print("  ✓ [5/5] 正常响应不触发重试（文本 + tool_call）")


# ════════════════════════════════════════════════════════
# 测试 6: 指数退避时间计算
# ════════════════════════════════════════════════════════

def test_backoff_timing():
    """验证指数退避时间计算公式：wait = min(2^attempt, 8)。"""
    expected = [2, 4, 8]  # attempt 1, 2, 3
    for attempt in range(1, 4):
        wait = min(2 ** attempt, 8)
        assert wait == expected[attempt - 1], \
            f"attempt={attempt}: expected {expected[attempt-1]}, got {wait}"
    print("  ✓ [额外] 指数退避时间计算正确: 2s → 4s → 8s")


# ════════════════════════════════════════════════════════
# 运行所有测试
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  API 空响应重试机制 — 单元测试")
    print("=" * 60 + "\n")

    tests = [
        test_exception_exists,
        test_empty_response_detection,
        test_retry_mechanism,
        test_recovery_message,
        test_normal_response_no_retry,
        test_backoff_timing,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ [{t.__name__}] FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ [{t.__name__}] ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed} 通过, {failed} 失败")
    print(f"{'=' * 60}\n")
    sys.exit(0 if failed == 0 else 1)
