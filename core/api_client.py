"""
core/api_client.py — 底层流式 API 客户端（重构版）

核心改动（修复卡死 + 降低资源消耗）：
  ① 彻底抛弃 read(1024)：改用 http.client 逐行 readline()
      → SSE 每帧只有几十字节，read(1024) 会永久等待凑齐缓冲区
  ② 代理显式处理：HTTP proxy + HTTPS CONNECT 隧道 + SSL 手动包裹
      → 不依赖 urllib 全局 opener，本模块独立可用
  ③ per-read timeout = 30s：每次 readline() 独立计时
      → 避免 300s 全局超时导致连接僵死无法中断
  ④ 连接 finally 确保关闭，防止 fd 泄漏
  ⑤ 健壮 SSE 解析器保留（兼容国产模型非标格式）
"""

import json, re, os, ssl, socket, time, threading
import http.client
from urllib.parse import urlparse
from config import get_api_config, MODELS, DYNAMIC_CONFIG


# ── 自定义异常 ──────────────────────────────────────────
class APIEmptyResponseError(Exception):
    """模型返回空响应（无文本、无工具调用、0 Token）。"""
    pass


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
# 流式请求生成器（核心重写）
# ════════════════════════════════════════════════════════

def stream_request(
    messages: list,
    model_alias: str,
    tools_schema: list | None = None,
    max_tokens: int | None = None,
    tool_choice: str = "auto",
):
    """
    流式 SSE 生成器（含断路器 + 指数退避 + 局部流恢复）。
    yields: 已解析的 delta dict，或 {"_error": "..."}。
    """
    base_url, api_key = get_api_config(model_alias)
    model_id          = MODELS[model_alias]["id"]
    provider          = base_url   # 用 base_url 作熔断器 key
    clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]

    payload: dict = {
        "model":      model_id,
        "messages":   clean,
        "max_tokens": max_tokens or DYNAMIC_CONFIG["max_tokens"],
        "stream":     True,
    }
    if tools_schema:
        payload["tools"]       = tools_schema
        payload["tool_choice"] = tool_choice
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
                # 读空 body 避免连接污染
                resp.read(200)
                continue   # 进入下一次 attempt

            if resp.status != 200:
                _cb_record_failure(provider)
                err_body = resp.read(600).decode("utf-8", errors="replace")
                yield {"_error": f"HTTP {resp.status}: {err_body}"}
                return

            # ── 成功建立连接，重置断路器 ───────────────────
            _cb_record_success(provider)

            # ── 逐行读取 SSE（含流中断局部恢复）─────────────
            partial_text = ""
            while True:
                try:
                    raw_line = resp.readline()
                except socket.timeout:
                    yield {"_error": f"读取超时 ({_READ_TIMEOUT}s)，检查代理/网络"}
                    return
                except (BrokenPipeError, ConnectionResetError) as e:
                    # 流中断：已有部分内容则通知上层
                    if partial_text:
                        yield {"_partial_end": True,
                               "_error": f"流中断（已接收部分内容）: {e}"}
                    else:
                        _cb_record_failure(provider)
                        if attempt < _RETRY_MAX - 1:
                            break   # 进入重试
                        yield {"_error": f"连接断开: {e}"}
                    return

                if not raw_line:
                    return   # EOF 正常结束

                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue

                data_raw = line[6:].strip()
                if data_raw == "[DONE]":
                    return

                parsed = parse_sse_delta(data_raw)
                if parsed is not None:
                    # 追踪已收到的文本内容（用于流中断恢复判断）
                    choices = parsed.get("choices", [])
                    if choices:
                        partial_text += choices[0].get("delta", {}).get("content") or ""
                    usage = parsed.get("usage")
                    if usage and isinstance(usage, dict):
                        yield {"_usage": usage}
                    yield parsed

            # 如果 break 出来是因为连接断开要重试，继续 attempt 循环
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
        except Exception as e:
            yield {"_error": str(e)}
            return
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
        return   # 非 continue 路径到这里说明已 yield error，退出

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
    base_url, api_key = get_api_config(model_alias)
    model_id          = MODELS[model_alias]["id"]

    if vision_payload_override:
        payload = vision_payload_override
        payload.setdefault("model",      model_id)
        payload.setdefault("max_tokens", max_tokens)
        payload.setdefault("stream",     False)
    else:
        clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
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
        hdrs = {
            "Authorization":  f"Bearer {api_key}",
            "Content-Type":   "application/json",
            "Content-Length": str(len(body)),
        }
        conn.request("POST", path, body=body, headers=hdrs)
        if conn.sock:
            conn.sock.settimeout(90)   # 视觉推理较慢

        resp = conn.getresponse()
        raw  = resp.read()

        if resp.status != 200:
            return "", f"HTTP {resp.status}: {raw[:300].decode('utf-8', errors='replace')}"

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
