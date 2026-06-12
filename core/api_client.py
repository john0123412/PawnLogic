"""
core/api_client.py — low-level streaming API client with native dual-format support.

Natively supports OpenAI Chat Completions and Anthropic Messages API formats.
Each format has an independent request-building and response-parsing path,
without cross-format conversion.

Shared infrastructure: connection management, proxy tunneling, circuit breaker,
and exponential backoff.
"""

import copy
import json, re, os, ssl, socket, time, threading
import http.client
from urllib.parse import urlparse
from config import get_provider_config, MODELS, DEFAULT_MODEL, DYNAMIC_CONFIG
from core.api_errors import (
    _retry_delay,
    format_http_error,
    format_transport_error,
    retry_notice,
)
from core.interrupts import clear_cancel_callback, raise_if_interrupted, set_cancel_callback


# Custom exceptions.
class APIEmptyResponseError(Exception):
    """Model returned an empty response: no text, no tool calls, and 0 tokens."""
    pass


# ════════════════════════════════════════════════════════
# thinking-mode support: reasoning_content field handling.
#
# Reasoning models may return reasoning_content and strictly require the
# corresponding assistant message in the next request to pass it back unchanged.
# Otherwise they can return HTTP 400:
# "The reasoning_content in the thinking mode must be passed back to the API."
#
# Non-reasoning models vary in how they handle unknown fields:
#   · Some APIs ignore unknown fields.
#   · Some APIs return 400 unknown parameter.
# To avoid false failures, strip reasoning_content for non-reasoning models.
# ════════════════════════════════════════════════════════

# Reasoning model heuristic: model_alias or model_id contains one of these terms.
_REASONING_MODEL_PATTERNS = (
    "mimo",        # Xiaomi MiMo family, including legacy aliases.
    "deepseek",    # DeepSeek family: v4-flash / v4-pro / reasoner / r1.
    "qwq",         # Alibaba QwQ reasoning series.
)


def _is_reasoning_model(model_alias: str, model_id: str = "") -> bool:
    """Return whether a model supports the reasoning_content field.

    Prefer explicit MODELS[alias].reasoning; fallback to keyword matching for
    custom providers when it is not declared.
    """
    m = MODELS.get(model_alias)
    if m is not None and "reasoning" in m:
        return bool(m["reasoning"])
    # Fallback keyword matching for custom providers.
    combo = f"{(model_alias or '').lower()}|{(model_id or '').lower()}"
    return any(p in combo for p in _REASONING_MODEL_PATTERNS)


def _sanitize_messages_for_model(
    messages: list,
    model_alias: str,
    model_id: str = "",
) -> list:
    """
    Build a clean OpenAI-format messages list for the target model.

    Signature compatibility:
      · Simple callers can use _sanitize_messages_for_model(messages, model_alias)
      · model_id is optional and improves custom-provider detection

    Handling:
      · First, deepcopy messages so the original session.messages is never mutated.
      · Then detect reasoning models through explicit config or keyword fallback.
      · Finally trim:
          - remove private fields whose keys start with "_"
          - remove empty reasoning_content values to avoid sending null
          - remove reasoning_content for non-reasoning models
          - preserve non-empty reasoning_content for reasoning models
    """
    is_reasoning = _is_reasoning_model(model_alias, model_id)
    # deepcopy breaks references to nested session structures such as tool_calls.
    # Without it, stripping reasoning_content for a non-reasoning model would
    # corrupt the original session when switching back to a reasoning model.
    cloned_msgs = copy.deepcopy(messages)
    out: list[dict] = []
    for m in cloned_msgs:
        clean = {
            k: v for k, v in m.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }
        rc = clean.get("reasoning_content")
        # Remove empty values or remove the field for non-reasoning models.
        if not rc or not is_reasoning:
            clean.pop("reasoning_content", None)
        out.append(clean)
    return out


# Circuit-breaker state storage per provider base_url.
_CB_LOCK      = threading.Lock()
_CIRCUIT_BREAKERS: dict[str, dict] = {}
# Each entry: {"state": "closed"|"open"|"half_open",
#              "failures": int, "opened_at": float}
_CB_TRIP_AT   = 3      # Consecutive failures before opening the circuit.
_CB_RESET_SEC = 30     # Seconds from OPEN to HALF_OPEN.
_RETRY_MAX    = 3      # Maximum request attempts, including the first attempt.
_RETRY_CODES  = {429, 500, 502, 503, 504}  # HTTP status codes that trigger backoff.


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
    """Return True when requests are allowed; False means fast-fail circuit open."""
    with _CB_LOCK:
        cb = _CIRCUIT_BREAKERS.get(provider)
        if not cb or cb["state"] == "closed":
            return True
        if cb["state"] == "open":
            if time.monotonic() - cb["opened_at"] >= _CB_RESET_SEC:
                cb["state"] = "half_open"
                return True          # Allow probe request.
            return False             # Still in the open period.
        # half_open: allow one request.
        return True


def _interruptible_sleep(delay: float) -> None:
    """Sleep in short slices so Ctrl+C during retry backoff is processed promptly."""
    deadline = time.monotonic() + max(0.0, delay)
    while True:
        raise_if_interrupted()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))
    raise_if_interrupted()


def _cancel_connection(
    conn: http.client.HTTPConnection,
    response: http.client.HTTPResponse | None = None,
) -> None:
    """Close the active streaming connection from the SIGINT path."""
    sockets = []
    sock = getattr(conn, "sock", None)
    if sock:
        sockets.append(sock)
    if response is not None:
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        for owner in (raw, fp):
            if owner is None:
                continue
            response_sock = getattr(owner, "_sock", None) or getattr(owner, "sock", None)
            if response_sock:
                sockets.append(response_sock)

    for active_sock in sockets:
        try:
            active_sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            active_sock.close()
        except Exception:
            pass

    try:
        if response is not None:
            response.close()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass


# ── per-read / connect timeout ────────────────────────────

def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


_READ_TIMEOUT = _env_int("PAWNLOGIC_API_READ_TIMEOUT", 60, 5, 300)
_CONN_TIMEOUT = _env_int("PAWNLOGIC_API_CONNECT_TIMEOUT", 20, 3, 120)
_NONSTREAM_TIMEOUT = _env_int("PAWNLOGIC_API_NONSTREAM_TIMEOUT", 60, 5, 300)

# ════════════════════════════════════════════════════════
# Proxy detection.
# ════════════════════════════════════════════════════════

def _detect_proxy() -> str | None:
    return (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
        os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    )

# ════════════════════════════════════════════════════════
# Open connection, including HTTP proxy -> HTTPS CONNECT tunnel.
# ════════════════════════════════════════════════════════

def _open_connection(
    target_url: str,
    proxy_url: str | None,
    timeout: int,
) -> tuple[http.client.HTTPConnection, str]:
    """
    Open an HTTP(S) connection to target_url, optionally through a proxy.
    Returns (conn, request_path). The caller must close conn.

    Proxy flow for HTTP proxy + HTTPS target:
      1. TCP connect to proxy
      2. Send CONNECT target:443
      3. Wait for 200 Connection established
      4. Wrap SSL on the same socket, with SNI = target_host
    """
    parsed      = urlparse(target_url)
    is_https    = parsed.scheme == "https"
    target_host = parsed.hostname
    target_port = parsed.port or (443 if is_https else 80)
    path        = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    if parsed.scheme not in ("http", "https") or not target_host:
        raise ConnectionError(f"Invalid provider Base URL: {target_url!r}")

    if proxy_url:
        prx      = urlparse(proxy_url)
        prx_host = prx.hostname
        prx_port = prx.port or 8080
        if not prx_host:
            raise ConnectionError(f"Invalid proxy URL: {proxy_url!r}")

        # Step 1: TCP connect to proxy.
        raw_sock = socket.create_connection((prx_host, prx_port), timeout=timeout)

        if is_https:
            # Step 2: CONNECT tunnel.
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                f"Proxy-Connection: keep-alive\r\n"
                f"\r\n"
            ).encode()
            raw_sock.sendall(connect_req)

            # Read proxy response headers.
            buf = b""
            raw_sock.settimeout(timeout)
            while b"\r\n\r\n" not in buf:
                chunk = raw_sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Proxy CONNECT response was incomplete")
                buf += chunk
            status_line = buf.split(b"\r\n")[0].decode(errors="replace")
            if "200" not in status_line:
                raise ConnectionError(f"Proxy CONNECT failed: {status_line}")

            # Step 3: SSL wrapping with SNI = real target host.
            ctx      = ssl.create_default_context()
            ssl_sock = ctx.wrap_socket(raw_sock, server_hostname=target_host)

            # Inject SSL socket into HTTPSConnection skeleton and skip internal connect.
            conn      = http.client.HTTPSConnection(target_host, target_port, timeout=timeout)
            conn.sock = ssl_sock
        else:
            # HTTP targets through a proxy require an absolute URL.
            conn      = http.client.HTTPConnection(prx_host, prx_port, timeout=timeout)
            conn.sock = raw_sock
            path      = target_url  # Absolute URI.

    else:
        # Direct connection.
        if is_https:
            ctx  = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                target_host, target_port, timeout=timeout, context=ctx
            )
        else:
            conn = http.client.HTTPConnection(target_host, target_port, timeout=timeout)

    return conn, path

# ════════════════════════════════════════════════════════
# Robust SSE delta parser for non-standard model output.
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

    # Fallback: extract content with regex.
    result: dict = {"choices": [{"delta": {}, "finish_reason": None}]}
    delta = result["choices"][0]["delta"]
    m_content = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned2)
    if m_content:
        try:    delta["content"] = json.loads('"' + m_content.group(1) + '"')
        except Exception: delta["content"] = m_content.group(1)
    m_finish = re.search(r'"finish_reason"\s*:\s*"?(\w+)"?', raw)
    if m_finish:
        result["choices"][0]["finish_reason"] = m_finish.group(1)
    return result if delta else None

# ════════════════════════════════════════════════════════
# tool_call ID completion.
# ════════════════════════════════════════════════════════

_call_counter = [0]

def ensure_tool_call_id(tcd: dict, iteration: int, idx: int) -> str:
    existing = tcd.get("id", "").strip()
    if existing:
        return existing
    _call_counter[0] += 1
    return f"call_{iteration}_{idx}_{_call_counter[0]}"


# ════════════════════════════════════════════════════════
# Anthropic native path: request construction.
# ════════════════════════════════════════════════════════

def _anthropic_convert_tools(tools_schema: list) -> list:
    """Convert OpenAI tool schema to Anthropic input_schema format."""
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
    Convert OpenAI messages to Anthropic messages.
    Returns (converted_messages, system_prompt).
    - system is extracted as a top-level field
    - tool role -> user + tool_result content block
    - assistant tool_calls -> tool_use content block
    - consecutive same-role messages are merged because Anthropic requires alternation
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

    # Anthropic requires user/assistant alternation; merge consecutive same-role messages.
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
    """Build a native Anthropic Messages API request body."""
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
    """Build native Anthropic request headers."""
    return {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
        "Accept":            "text/event-stream",
        "Cache-Control":     "no-cache",
        "Content-Length":    str(body_len),
    }


# ════════════════════════════════════════════════════════
# Anthropic native path: SSE parsing.
# ════════════════════════════════════════════════════════

def _anthropic_parse_sse(event_type: str, data_raw: str, state: dict) -> dict | None:
    """
    Parse one Anthropic SSE event and return a unified delta dict.
    state tracks: {"tool_blocks": {idx: {id, name, args}}}
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
    """Parse a non-streaming Anthropic response. Returns (text, error)."""
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
# Streaming request generator.
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
    Streaming SSE generator with circuit breaker, exponential backoff, and
    partial-stream recovery. Chooses OpenAI or Anthropic native path from
    api_format. Yields parsed delta dicts or {"_error": "..."}.
    """
    cfg       = get_provider_config(model_alias)
    base_url  = cfg["base_url"]
    api_key   = cfg["api_key"]
    api_fmt   = cfg["api_format"]
    model_id  = MODELS.get(model_alias, MODELS[DEFAULT_MODEL])["id"]
    provider  = base_url   # Use base_url as the circuit-breaker key.
    _max_tok  = max_tokens or DYNAMIC_CONFIG["max_tokens"]

    # Build payload and headers by format.
    if api_fmt == "anthropic":
        payload = _anthropic_build_payload(messages, model_id, _max_tok, tools_schema)
    else:
        # thinking-mode: preserve reasoning_content for reasoning models and
        # strip it for non-reasoning models to avoid strict provider HTTP 400s.
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
        raise_if_interrupted()
        # Circuit-breaker check.
        if not _cb_allow(provider):
            yield {"_error": f"circuit open: {provider} (consecutive failures; paused {_CB_RESET_SEC}s)"}
            return

        conn: http.client.HTTPConnection | None = None
        cancel_callback = None
        try:
            conn, path = _open_connection(base_url, proxy, timeout=_CONN_TIMEOUT)
            response_ref: dict[str, http.client.HTTPResponse | None] = {"response": None}
            cancel_callback = lambda conn=conn, response_ref=response_ref: _cancel_connection(
                conn,
                response_ref["response"],
            )
            set_cancel_callback(cancel_callback)

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
            response_ref["response"] = resp

            # HTTP status codes that should be retried.
            if resp.status in _RETRY_CODES:
                _cb_record_failure(provider)
                err_body = resp.read(600)
                err_msg = format_http_error(resp.status, err_body)
                if attempt >= _RETRY_MAX - 1:
                    yield {"_error": err_msg}
                    return
                retry_after = resp.headers.get("Retry-After")
                delay = _retry_delay(attempt, retry_after)
                yield {"_retry": retry_notice(err_msg, attempt, _RETRY_MAX, delay)}
                _interruptible_sleep(delay)
                continue

            if resp.status != 200:
                _cb_record_failure(provider)
                err_body = resp.read(600)
                yield {"_error": format_http_error(resp.status, err_body)}
                return

            # Connection established; reset circuit breaker.
            _cb_record_success(provider)

            # Read SSE line by line.
            partial_text = ""

            if api_fmt == "anthropic":
                # Native Anthropic SSE parsing.
                current_event = ""
                state: dict = {"tool_blocks": {}}
                while True:
                    raise_if_interrupted()
                    try:
                        raw_line = resp.readline()
                        raise_if_interrupted()
                    except socket.timeout:
                        raise_if_interrupted()
                        yield {
                            "_error": (
                                f"Read timeout ({_READ_TIMEOUT}s): provider stopped sending stream data. "
                                "Check network, proxy settings, or switch provider."
                            )
                        }
                        return
                    except OSError as e:
                        raise_if_interrupted()
                        if partial_text:
                            yield {"_partial_end": True,
                                   "_error": f"Stream interrupted after partial content: {e}"}
                        else:
                            _cb_record_failure(provider)
                            if attempt < _RETRY_MAX - 1:
                                err_msg = format_transport_error(
                                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                                )
                                delay = _retry_delay(attempt)
                                yield {"_retry": retry_notice(err_msg, attempt, _RETRY_MAX, delay)}
                                _interruptible_sleep(delay)
                                break
                            yield {
                                "_error": format_transport_error(
                                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                                )
                            }
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
                        raise_if_interrupted()
                        if "_usage" in parsed:
                            yield {"_usage": parsed["_usage"]}
                        if "choices" in parsed:
                            choices = parsed["choices"]
                            if choices:
                                partial_text += choices[0].get("delta", {}).get("content") or ""
                            yield parsed
                continue

            else:
                # Native OpenAI SSE parsing.
                while True:
                    raise_if_interrupted()
                    try:
                        raw_line = resp.readline()
                        raise_if_interrupted()
                    except socket.timeout:
                        raise_if_interrupted()
                        yield {
                            "_error": (
                                f"Read timeout ({_READ_TIMEOUT}s): provider stopped sending stream data. "
                                "Check network, proxy settings, or switch provider."
                            )
                        }
                        return
                    except OSError as e:
                        raise_if_interrupted()
                        if partial_text:
                            yield {"_partial_end": True,
                                   "_error": f"Stream interrupted after partial content: {e}"}
                        else:
                            _cb_record_failure(provider)
                            if attempt < _RETRY_MAX - 1:
                                err_msg = format_transport_error(
                                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                                )
                                delay = _retry_delay(attempt)
                                yield {"_retry": retry_notice(err_msg, attempt, _RETRY_MAX, delay)}
                                _interruptible_sleep(delay)
                                break
                            yield {
                                "_error": format_transport_error(
                                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                                )
                            }
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
                        raise_if_interrupted()
                        choices = parsed.get("choices", [])
                        if choices:
                            partial_text += choices[0].get("delta", {}).get("content") or ""
                        usage = parsed.get("usage")
                        if usage and isinstance(usage, dict):
                            yield {"_usage": usage}
                        yield parsed

                continue

        except socket.timeout:
            raise_if_interrupted()
            _cb_record_failure(provider)
            err_msg = format_transport_error(
                TimeoutError(
                    f"no response within {_CONN_TIMEOUT}s connection/header timeout"
                ),
                proxy=proxy,
                connect_timeout=_CONN_TIMEOUT,
            )
            if attempt < _RETRY_MAX - 1:
                delay = _retry_delay(attempt)
                yield {"_retry": retry_notice(err_msg, attempt, _RETRY_MAX, delay)}
                _interruptible_sleep(delay)
                continue
            yield {"_error": err_msg}
        except ConnectionRefusedError as e:
            raise_if_interrupted()
            _cb_record_failure(provider)
            yield {
                "_error": format_transport_error(
                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                )
            }
        except ssl.SSLError as e:
            raise_if_interrupted()
            yield {"_error": f"SSL error: {e}"}
            return
        except ConnectionError as e:
            raise_if_interrupted()
            _cb_record_failure(provider)
            yield {"_error": str(e)}
            return
        except OSError as e:
            raise_if_interrupted()
            _cb_record_failure(provider)
            err_msg = format_transport_error(e, proxy=proxy, connect_timeout=_CONN_TIMEOUT)
            if attempt < _RETRY_MAX - 1:
                delay = _retry_delay(attempt)
                yield {"_retry": retry_notice(err_msg, attempt, _RETRY_MAX, delay)}
                _interruptible_sleep(delay)
                continue
            yield {"_error": err_msg}
        except KeyboardInterrupt:
            raise  # Propagate cleanly; finally handles conn cleanup.
        except Exception as e:
            raise_if_interrupted()
            yield {
                "_error": format_transport_error(
                    e, proxy=proxy, connect_timeout=_CONN_TIMEOUT
                )
            }
            return
        finally:
            if cancel_callback is not None:
                clear_cancel_callback(cancel_callback)
            if conn:
                try: conn.close()
                except Exception: pass
        return

# ════════════════════════════════════════════════════════
# Single non-streaming call, used by vision tools and memorize.
# ════════════════════════════════════════════════════════

def _parse_openai_nonstream_text(raw_body: bytes) -> tuple[str, str | None]:
    """Parse a non-streaming OpenAI-compatible response defensively."""
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return "", f"Invalid JSON response: {exc}"

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return "", "Response missing choices"

    first = choices[0]
    if not isinstance(first, dict):
        return "", "Response choices[0] is not an object"

    message = first.get("message")
    if not isinstance(message, dict):
        return "", "Response missing message"

    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        content = "".join(parts)

    if not isinstance(content, str):
        return "", "Response missing message.content"

    text = content.strip()
    if not text:
        return "", "Response message.content is empty"
    return text, None

def call_once(
    messages: list,
    model_alias: str,
    max_tokens: int = 1024,
    vision_payload_override: dict | None = None,
) -> tuple[str, str | None]:
    """Non-streaming call. Returns (text, error), with error=None on success."""
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
        # thinking-mode: use the same sanitizer as stream_request.
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
        conn, path = _open_connection(base_url, proxy, timeout=_CONN_TIMEOUT)

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
            conn.sock.settimeout(_NONSTREAM_TIMEOUT)

        resp = conn.getresponse()
        raw  = resp.read()

        if resp.status != 200:
            return "", format_http_error(resp.status, raw[:600])

        if api_fmt == "anthropic":
            return _anthropic_parse_response(raw)
        else:
            return _parse_openai_nonstream_text(raw)

    except socket.timeout:
        return "", (
            f"Request timeout ({_NONSTREAM_TIMEOUT}s): provider did not finish "
            "the non-streaming response. Check network/proxy or switch provider."
        )
    except ssl.SSLError as e:
        return "", f"SSL error: {e}"
    except (ConnectionError, OSError) as e:
        return "", format_transport_error(e, proxy=proxy, connect_timeout=_CONN_TIMEOUT)
    except Exception as e:
        return "", format_transport_error(e, proxy=proxy, connect_timeout=_CONN_TIMEOUT)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
