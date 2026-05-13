"""
core/api_client.py — 底层流式 API 客户端（双格式原生支持）

原生支持 OpenAI Chat Completions 和 Anthropic Messages 两种 API 格式。
每种格式有独立的请求构建和响应解析路径，不做格式转换。

共享基础设施：连接管理、代理隧道、断路器、指数退避。
"""

import copy
import json, re, os, ssl, socket, time, threading
import http.client
from urllib.parse import urlparse
from config import get_api_config, get_api_format, get_provider_config, MODELS, DEFAULT_MODEL, DYNAMIC_CONFIG


# ── 自定义异常 ──────────────────────────────────────────
class APIEmptyResponseError(Exception):
    """模型返回空响应（无文本、无工具调用、0 Token）。"""
    pass


# ════════════════════════════════════════════════════════
# ★ thinking-mode 支持：reasoning_content 字段处理
#
# 推理模型（mimo / ds-r1 / qwq 等）在响应中返回 reasoning_content，
# 并且严格校验下一轮请求里对应 assistant 消息必须原样回传此字段，
# 否则返回 HTTP 400 "The reasoning_content in the thinking mode
# must be passed back to the API."
#
# 非推理模型（gpt-4o-mini / ds-chat 等）对未知字段态度不一：
#   · 部分 API 忽略 unknown field
#   · 部分 API 返回 400 unknown parameter
# 为避免误伤，对非推理模型一律 strip reasoning_content。
# ════════════════════════════════════════════════════════

# 推理模型特征：model_alias 或 model_id 包含任一关键词即视为推理模型
_REASONING_MODEL_PATTERNS = (
    "mimo",        # 小米 MiMo 全系（含 legacy alias）
    "reasoner",    # DeepSeek Reasoner (deepseek-reasoner)
    "qwq",         # 阿里 QwQ 推理系列
    "r1",          # DeepSeek R1 通用别名 (ds-r1 / deepseek-r1)
)


def _is_reasoning_model(model_alias: str, model_id: str = "") -> bool:
    """判断是否为支持 reasoning_content 字段的推理模型。"""
    combo = f"{(model_alias or '').lower()}|{(model_id or '').lower()}"
    return any(p in combo for p in _REASONING_MODEL_PATTERNS)


def _sanitize_messages_for_model(
    messages: list,
    model_alias: str,
    model_id: str = "",
) -> list:
    """
    针对目标模型构造干净的 OpenAI 格式 messages 列表。

    签名兼容性：
      · 简化调用 _sanitize_messages_for_model(messages, model_alias) 即可
      · model_id 可选，仅在识别自定义 provider 时提升判准精度

    处理逻辑：
      · 🔑 第一步（深度拷贝隔离）：copy.deepcopy(messages) —— 绝不在原始
        session.messages 上原地修改，避免跨模型切换时污染嵌套结构。
      · 第二步（识别）：_is_reasoning_model 用 'mimo' / 'r1' / 'qwq' /
        'reasoner' 四个关键词匹配 model_alias 和 model_id 的组合字串。
      · 第三步（裁剪）：
          - 私有字段（键以 '_' 开头，例 _pinned / _args_parsed）一律剥离
          - 空 reasoning_content（"" / None / 0 / 空列表）→ del 键，避免
            发送 null 导致推理模型 400
          - 非推理模型 → 强制 del reasoning_content 键，避免未定义字段 400
          - 推理模型且非空 → 原样保留，满足 mimo-v2.5 回传校验
    """
    is_reasoning = _is_reasoning_model(model_alias, model_id)
    # 🔑 deepcopy：割断对 session 原始消息列表与嵌套结构（tool_calls 列表、
    # dict 值等）的引用。切换模型时非推理模型会 strip reasoning_content，
    # 若无深拷贝会污染原始 session.messages，导致切回推理模型后思考内容丢失。
    cloned_msgs = copy.deepcopy(messages)
    out: list[dict] = []
    for m in cloned_msgs:
        clean = {
            k: v for k, v in m.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }
        rc = clean.get("reasoning_content")
        # 空值（None / "" / 0 / 空列表）或非推理模型 → 移除字段
        if not rc or not is_reasoning:
            clean.pop("reasoning_content", None)
        out.append(clean)
    return out


# ── 断路器状态存储（per provider base_url） ──────────────
_CB_LOCK      = threading.Lock()
_CIRCUIT_BREAKERS: dict[str, dict] = {}
# 每个 entry: {"state": "closed"|"open"|"half_open",
#              "failures": int, "opened_at": float}
_CB_TRIP_AT   = 3      # 连续失败次数触发熔断
_CB_RESET_SEC = 30     # OPEN → HALF_OPEN 等待秒数
_RETRY_MAX    = 3      # 最大重试次数
_RETRY_CODES  = {429, 502, 503}  # 触发退避的 HTTP 状态码


def _cb_get(provider: str) -> dict:
    with _CB_LOCK:
        if provider not in _CIRCUIT_BREAKERS:
            _CIRCUIT_BREAKERS[provider] = {
                "state": "closed", "failures": 0, "opened_at": 0.0
            }
        return _CIRCUIT_BREAKERS[provider]


def _cb_record_success(provider: str) -> None:
    with _CB_LOCK:
        cb = _CIRCUIT_BREAKERS.get(provider)
        if cb:
            cb["state"]    = "closed"
            cb["failures"] = 0


def _cb_record_failure(provider: str) -> None:
    with _CB_LOCK:
        cb = _CIRCUIT_BREAKERS.setdefault(
            provider, {"state": "closed", "failures": 0, "opened_at": 0.0}
        )
        cb["failures"] += 1
        if cb["failures"] >= _CB_TRIP_AT:
            cb["state"]     = "open"
            cb["opened_at"] = time.monotonic()


def _cb_allow(provider: str) -> bool:
    """返回 True 表示允许请求；False 表示熔断器开路，应快速失败。"""
    with _CB_LOCK:
        cb = _CIRCUIT_BREAKERS.get(provider)
        if not cb or cb["state"] == "closed":
            return True
        if cb["state"] == "open":
            if time.monotonic() - cb["opened_at"] >= _CB_RESET_SEC:
                cb["state"] = "half_open"
                return True          # 放行探针
            return False             # 仍在熔断期
        # half_open：放行一次
        return True

# ── per-read / connect timeout ────────────────────────────
_READ_TIMEOUT = 120   # 每次 readline() 等待上限（秒）
_CONN_TIMEOUT = 40   # TCP 握手 + 代理 CONNECT 超时（秒）

# ════════════════════════════════════════════════════════
# 代理探测
# ════════════════════════════════════════════════════════

def _detect_proxy() -> str | None:
    return (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
        os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    )

# ════════════════════════════════════════════════════════
# 建立连接（含 HTTP proxy → HTTPS CONNECT 隧道）
# ════════════════════════════════════════════════════════

def _open_connection(
    target_url: str,
    proxy_url: str | None,
    timeout: int,
) -> tuple[http.client.HTTPConnection, str]:
    """
    建立到 target_url 的 HTTP(S) 连接，可选通过代理。
    返回 (conn, request_path)。调用者负责 conn.close()。

    代理流程（HTTP 代理 + HTTPS 目标）：
      1. TCP 连到代理
      2. 发送 CONNECT target:443
      3. 等待 200 Connection established
      4. 在同一 socket 上包裹 SSL（SNI = target_host）
    """
    parsed      = urlparse(target_url)
    is_https    = parsed.scheme == "https"
    target_host = parsed.hostname
    target_port = parsed.port or (443 if is_https else 80)
    path        = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    if proxy_url:
        prx      = urlparse(proxy_url)
        prx_host = prx.hostname
        prx_port = prx.port or 8080

        # 步骤 1：TCP 连到代理
        raw_sock = socket.create_connection((prx_host, prx_port), timeout=timeout)

        if is_https:
            # 步骤 2：CONNECT 隧道
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"Proxy-Connection: keep-alive\r\n"
                f"\r\n"
            ).encode()
            raw_sock.sendall(connect_req)

            # 读取代理响应头
            buf = b""
            raw_sock.settimeout(timeout)
            while b"\r\n\r\n" not in buf:
                chunk = raw_sock.recv(4096)
                if not chunk:
                    raise ConnectionError("代理 CONNECT 响应不完整")
                buf += chunk
            status_line = buf.split(b"\r\n")[0].decode(errors="replace")
            if "200" not in status_line:
                raise ConnectionError(f"代理 CONNECT 失败: {status_line}")

            # 步骤 3：SSL 包裹（SNI = 真实目标域名）
            ctx      = ssl.create_default_context()
            ssl_sock = ctx.wrap_socket(raw_sock, server_hostname=target_host)

            # 将 SSL socket 注入 HTTPSConnection 骨架（跳过内部 connect）
            conn      = http.client.HTTPSConnection(target_host, target_port, timeout=timeout)
            conn.sock = ssl_sock
        else:
            # HTTP 目标：代理需要完整 URL
            conn      = http.client.HTTPConnection(prx_host, prx_port, timeout=timeout)
            conn.sock = raw_sock
            path      = target_url  # 绝对 URI

    else:
        # 直连
        if is_https:
            ctx  = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                target_host, target_port, timeout=timeout, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(target_host, target_port, timeout=timeout)

    return conn, path

# ════════════════════════════════════════════════════════
# 健壮 SSE delta 解析器（兼容国产模型非标格式）
# ════════════════════════════════════════════════════════

def parse_sse_delta(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    def _escape_inner(s: str) -> str:
        result = []; in_str = False; escaped = False
        for ch in s:
            if escaped:
                result.append(ch); escaped = False; continue
            if ch == '\\':
                result.append(ch); escaped = True; continue
            if ch == '"':
                in_str = not in_str; result.append(ch); continue
            if in_str and ch == '\n':
                result.append('\\n'); continue
            if in_str and ch == '\r':
                result.append('\\r'); continue
            if in_str and ch == '\t':
                result.append('\\t'); continue
            result.append(ch)
        return "".join(result)

    cleaned2 = _escape_inner(cleaned)
    try:
        return json.loads(cleaned2)
    except json.JSONDecodeError:
        pass

    # 降级：正则提取 content
    result: dict = {"choices": [{"delta": {}, "finish_reason": None}]}
    delta = result["choices"][0]["delta"]
    m_content = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned2)
    if m_content:
        try:    delta["content"] = json.loads('"' + m_content.group(1) + '"')
        except: delta["content"] = m_content.group(1)
    m_finish = re.search(r'"finish_reason"\s*:\s*"?(\w+)"?', raw)
    if m_finish:
        result["choices"][0]["finish_reason"] = m_finish.group(1)
    return result if delta else None

# ════════════════════════════════════════════════════════
# tool_call ID 补全
# ════════════════════════════════════════════════════════

_call_counter = [0]

def ensure_tool_call_id(tcd: dict, iteration: int, idx: int) -> str:
    existing = tcd.get("id", "").strip()
    if existing:
        return existing
    _call_counter[0] += 1
    return f"call_{iteration}_{idx}_{_call_counter[0]}"


# ════════════════════════════════════════════════════════
# Anthropic 原生路径 — 请求构建
# ════════════════════════════════════════════════════════

def _anthropic_convert_tools(tools_schema: list) -> list:
    """OpenAI tool schema → Anthropic input_schema 格式。"""
    result = []
    for tool in (tools_schema or []):
        fn = tool.get("function", {})
        result.append({
            "name":        fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def _anthropic_convert_messages(messages: list) -> tuple[list, str | None]:
    """
    OpenAI messages → Anthropic messages。
    返回 (converted_messages, system_prompt)。
    - system 提取为顶层字段
    - tool 角色 → user + tool_result content block
    - assistant tool_calls → tool_use content block
    - 合并连续同角色消息（Anthropic 要求交替）
    """
    system_prompt = None
    converted = []

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            system_prompt = msg.get("content", "")
            continue

        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type":         "tool_result",
                    "tool_use_id":  msg.get("tool_call_id", ""),
                    "content":      msg.get("content", ""),
                }],
            })
            continue

        if role == "assistant":
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                converted.append({"role": "assistant", "content": content or "."})
            else:
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {"_raw": args_str}
                    blocks.append({
                        "type":  "tool_use",
                        "id":    tc.get("id", ""),
                        "name":  fn.get("name", ""),
                        "input": args,
                    })
                converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                converted.append({"role": "user", "content": content})
            else:
                converted.append(msg)
            continue

    # Anthropic 要求 user/assistant 交替，合并连续同角色
    merged = []
    for msg in converted:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            curr = msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n\n" + curr
            elif isinstance(prev, list) and isinstance(curr, list):
                merged[-1]["content"] = prev + curr
            elif isinstance(prev, str) and isinstance(curr, list):
                merged[-1]["content"] = [{"type": "text", "text": prev}] + curr
            elif isinstance(prev, list) and isinstance(curr, str):
                merged[-1]["content"] = prev + [{"type": "text", "text": curr}]
        else:
            merged.append(msg)

    return merged, system_prompt


def _anthropic_build_payload(
    messages: list, model_id: str, max_tokens: int,
    tools_schema: list | None,
) -> dict:
    """构建 Anthropic Messages API 原生请求体。"""
    conv_msgs, system_prompt = _anthropic_convert_messages(messages)
    payload: dict = {
        "model":      model_id,
        "max_tokens": max_tokens or DYNAMIC_CONFIG["max_tokens"],
        "messages":   conv_msgs,
        "stream":     True,
    }
    if system_prompt:
        payload["system"] = system_prompt
    if tools_schema:
        payload["tools"] = _anthropic_convert_tools(tools_schema)
    return payload


def _anthropic_build_headers(api_key: str, body_len: int) -> dict:
    """Anthropic 原生请求头。"""
    return {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
        "Accept":            "text/event-stream",
        "Cache-Control":     "no-cache",
        "Content-Length":    str(body_len),
    }


# ════════════════════════════════════════════════════════
# Anthropic 原生路径 — SSE 解析
# ════════════════════════════════════════════════════════

def _anthropic_parse_sse(event_type: str, data_raw: str, state: dict) -> dict | None:
    """
    解析单个 Anthropic SSE 事件，yield 统一 delta dict。
    state 追踪: {"tool_blocks": {idx: {id, name, args}}}
    """
    try:
        data = json.loads(data_raw)
    except json.JSONDecodeError:
        return None

    etype = data.get("type", event_type)

    if etype == "message_start":
        usage = data.get("message", {}).get("usage", {})
        if usage:
            return {"_usage": usage}
        return None

    if etype == "content_block_start":
        block = data.get("content_block", {})
        idx = data.get("index", 0)
        if block.get("type") == "tool_use":
            state.setdefault("tool_blocks", {})[idx] = {
                "id":   block.get("id", ""),
                "name": block.get("name", ""),
                "args": "",
            }
        return None

    if etype == "content_block_delta":
        delta = data.get("delta", {})
        idx = data.get("index", 0)
        delta_type = delta.get("type", "")

        if delta_type == "text_delta":
            return {
                "choices": [{
                    "delta":          {"content": delta.get("text", "")},
                    "finish_reason":  None,
                }],
            }

        if delta_type == "input_json_delta":
            partial = delta.get("partial_json", "")
            tb = state.get("tool_blocks", {}).get(idx, {})
            tb["args"] = tb.get("args", "") + partial
            return {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": idx,
                            "id":     tb.get("id", ""),
                            "function": {
                                "name":      tb.get("name", ""),
                                "arguments": partial,
                            },
                        }],
                    },
                    "finish_reason": None,
                }],
            }
        return None

    if etype == "content_block_stop":
        return None

    if etype == "message_delta":
        usage = data.get("usage", {})
        result = {}
        if usage:
            result["_usage"] = usage
        stop = data.get("delta", {}).get("stop_reason")
        if stop:
            result["choices"] = [{"delta": {}, "finish_reason": stop}]
        return result if result else None

    if etype == "message_stop":
        return None

    return None


def _anthropic_parse_response(raw_bytes: bytes) -> tuple[str, str | None]:
    """Anthropic 非流式响应解析。返回 (text, error)。"""
    try:
        data = json.loads(raw_bytes)
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts).strip(), None
    except Exception as e:
        return "", str(e)

# ════════════════════════════════════════════════════════
# 流式请求生成器（核心重写）
# ════════════════════════════════════════════════════════

def stream_request(
    messages: list,
    model_alias: str,
    tools_schema: list | None = None,
    max_tokens: int | None = None,
    tool_choice: str = "auto",
    response_format: dict | None = None,
):
    """
    流式 SSE 生成器（含断路器 + 指数退避 + 局部流恢复）。
    根据 api_format 自动选择 OpenAI 或 Anthropic 原生路径。
    yields: 已解析的 delta dict，或 {"_error": "..."}。
    """
    cfg       = get_provider_config(model_alias)
    base_url  = cfg["base_url"]
    api_key   = cfg["api_key"]
    api_fmt   = cfg["api_format"]
    model_id  = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])["id"]
    provider  = base_url   # 用 base_url 作熔断器 key
    _max_tok  = max_tokens or DYNAMIC_CONFIG["max_tokens"]

    # ── 按格式构建 payload 和 headers ────────────────────
    if api_fmt == "anthropic":
        payload = _anthropic_build_payload(messages, model_id, _max_tok, tools_schema)
    else:
        # ★ thinking-mode: 推理模型保留 reasoning_content 回传，
        # 非推理模型 strip 掉，避免 mimo/ds-r1 的 HTTP 400 严格校验。
        clean = _sanitize_messages_for_model(messages, model_alias, model_id)
        payload = {
            "model":      model_id,
            "messages":   clean,
            "max_tokens": _max_tok,
            "stream":     True,
        }
        if tools_schema:
            payload["tools"]       = tools_schema
            payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format
        payload["stream_options"] = {"include_usage": True}

    proxy = _detect_proxy()

    for attempt in range(_RETRY_MAX):
        # ── 断路器检查 ────────────────────────────────────
        if not _cb_allow(provider):
            yield {"_error": f"circuit open: {provider}（连续失败，暂停 {_CB_RESET_SEC}s）"}
            return

        # ── 指数退避等待（首次不等）────────────────────────
        if attempt > 0:
            wait = min(2 ** attempt + (time.monotonic() % 1), 30)
            time.sleep(wait)

        conn: http.client.HTTPConnection | None = None
        try:
            conn, path = _open_connection(base_url, proxy, timeout=_CONN_TIMEOUT)

            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if api_fmt == "anthropic":
                hdrs = _anthropic_build_headers(api_key, len(body))
            else:
                hdrs = {
                    "Authorization":  f"Bearer {api_key}",
                    "Content-Type":   "application/json",
                    "Accept":         "text/event-stream",
                    "Cache-Control":  "no-cache",
                    "Content-Length": str(len(body)),
                }
            conn.request("POST", path, body=body, headers=hdrs)

            if conn.sock:
                conn.sock.settimeout(_READ_TIMEOUT)

            resp = conn.getresponse()

            # ── 需要重试的 HTTP 状态码 ─────────────────────
            if resp.status in _RETRY_CODES:
                _cb_record_failure(provider)
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(min(float(retry_after), 60))
                    except ValueError:
                        pass
                resp.read(200)
                continue

            if resp.status != 200:
                _cb_record_failure(provider)
                err_body = resp.read(600).decode("utf-8", errors="replace")
                yield {"_error": f"HTTP {resp.status}: {err_body}"}
                return

            # ── 成功建立连接，重置断路器 ───────────────────
            _cb_record_success(provider)

            # ── 逐行读取 SSE ─────────────────────────────
            partial_text = ""

            if api_fmt == "anthropic":
                # ── Anthropic 原生 SSE 解析 ──────────────
                current_event = ""
                state: dict = {"tool_blocks": {}}
                while True:
                    try:
                        raw_line = resp.readline()
                    except socket.timeout:
                        yield {"_error": f"读取超时 ({_READ_TIMEOUT}s)，检查代理/网络"}
                        return
                    except (BrokenPipeError, ConnectionResetError) as e:
                        if partial_text:
                            yield {"_partial_end": True,
                                   "_error": f"流中断（已接收部分内容）: {e}"}
                        else:
                            _cb_record_failure(provider)
                            if attempt < _RETRY_MAX - 1:
                                break
                            yield {"_error": f"连接断开: {e}"}
                        return

                    if not raw_line:
                        return

                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue

                    if not line.startswith("data: "):
                        continue

                    data_raw = line[6:].strip()
                    parsed = _anthropic_parse_sse(current_event, data_raw, state)
                    if parsed is not None:
                        if "_usage" in parsed:
                            yield {"_usage": parsed["_usage"]}
                        if "choices" in parsed:
                            choices = parsed["choices"]
                            if choices:
                                partial_text += choices[0].get("delta", {}).get("content") or ""
                            yield parsed
                continue

            else:
                # ── OpenAI 原生 SSE 解析 ──────────────────
                while True:
                    try:
                        raw_line = resp.readline()
                    except socket.timeout:
                        yield {"_error": f"读取超时 ({_READ_TIMEOUT}s)，检查代理/网络"}
                        return
                    except (BrokenPipeError, ConnectionResetError) as e:
                        if partial_text:
                            yield {"_partial_end": True,
                                   "_error": f"流中断（已接收部分内容）: {e}"}
                        else:
                            _cb_record_failure(provider)
                            if attempt < _RETRY_MAX - 1:
                                break
                            yield {"_error": f"连接断开: {e}"}
                        return

                    if not raw_line:
                        return

                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line.startswith("data: "):
                        continue

                    data_raw = line[6:].strip()
                    if data_raw == "[DONE]":
                        return

                    parsed = parse_sse_delta(data_raw)
                    if parsed is not None:
                        choices = parsed.get("choices", [])
                        if choices:
                            partial_text += choices[0].get("delta", {}).get("content") or ""
                        usage = parsed.get("usage")
                        if usage and isinstance(usage, dict):
                            yield {"_usage": usage}
                        yield parsed

                continue

        except socket.timeout:
            _cb_record_failure(provider)
            if attempt < _RETRY_MAX - 1:
                continue
            yield {"_error": f"连接超时 ({_CONN_TIMEOUT}s)，检查代理地址"}
        except ConnectionRefusedError:
            _cb_record_failure(provider)
            if attempt < _RETRY_MAX - 1:
                continue
            hint = f"（代理 {proxy} 是否已启动？）" if proxy else ""
            yield {"_error": f"连接被拒绝 {hint}"}
        except ssl.SSLError as e:
            yield {"_error": f"SSL 错误: {e}"}
            return
        except ConnectionError as e:
            _cb_record_failure(provider)
            if attempt < _RETRY_MAX - 1:
                continue
            yield {"_error": str(e)}
        except KeyboardInterrupt:
            raise  # 干净传播；finally 处理 conn 清理
        except Exception as e:
            yield {"_error": str(e)}
            return
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
        return

# ════════════════════════════════════════════════════════
# 单次非流式调用（视觉工具 / memorize 使用）
# ════════════════════════════════════════════════════════

def call_once(
    messages: list,
    model_alias: str,
    max_tokens: int = 1024,
    vision_payload_override: dict | None = None,
) -> tuple[str, str | None]:
    """非流式调用。返回 (text, error)，error=None 表示成功。"""
    cfg       = get_provider_config(model_alias)
    base_url  = cfg["base_url"]
    api_key   = cfg["api_key"]
    api_fmt   = cfg["api_format"]
    model_id  = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])["id"]

    if vision_payload_override:
        payload = vision_payload_override
        payload.setdefault("model",      model_id)
        payload.setdefault("max_tokens", max_tokens)
        payload.setdefault("stream",     False)
    elif api_fmt == "anthropic":
        payload = _anthropic_build_payload(messages, model_id, max_tokens, None)
        payload["stream"] = False
    else:
        # ★ thinking-mode: 与 stream_request 使用相同的 sanitizer
        clean = _sanitize_messages_for_model(messages, model_alias, model_id)
        payload = {
            "model":      model_id,
            "messages":   clean,
            "max_tokens": max_tokens,
            "stream":     False,
        }

    proxy = _detect_proxy()
    conn: http.client.HTTPConnection | None = None

    try:
        conn, path = _open_connection(base_url, proxy, timeout=60)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if api_fmt == "anthropic":
            hdrs = _anthropic_build_headers(api_key, len(body))
        else:
            hdrs = {
                "Authorization":  f"Bearer {api_key}",
                "Content-Type":   "application/json",
                "Content-Length": str(len(body)),
            }
        conn.request("POST", path, body=body, headers=hdrs)
        if conn.sock:
            conn.sock.settimeout(90)

        resp = conn.getresponse()
        raw  = resp.read()

        if resp.status != 200:
            return "", f"HTTP {resp.status}: {raw[:300].decode('utf-8', errors='replace')}"

        if api_fmt == "anthropic":
            return _anthropic_parse_response(raw)
        else:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"].strip()
            return text, None

    except socket.timeout:
        return "", "非流式调用超时"
    except Exception as e:
        return "", str(e)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
