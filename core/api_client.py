"""
core/api_client.py — low-level streaming API client with native dual-format support.

Natively supports OpenAI Chat Completions and Anthropic Messages API formats.
Each format has an independent request-building and response-parsing path,
without cross-format conversion.

Shared infrastructure: connection management, proxy tunneling, circuit breaker,
and exponential backoff.
"""

import json, os, ssl, socket, time, threading
import http.client
from urllib.parse import urlparse
from config import get_provider_config, MODELS, DEFAULT_MODEL, DYNAMIC_CONFIG
from core.api_payloads import (
    _anthropic_build_headers,
    _anthropic_build_payload,
    _anthropic_convert_messages as _anthropic_convert_messages,
    _anthropic_convert_tools as _anthropic_convert_tools,
    _build_openai_headers,
    _build_openai_payload,
    _is_reasoning_model as _is_reasoning_model,
    _sanitize_messages_for_model,
)
from core.api_errors import (
    RETRYABLE_HTTP_STATUS_CODES,
    _retry_delay,
    format_http_error,
    format_transport_error,
    is_retryable_http_status,
    retry_notice,
)
from core.interrupts import clear_cancel_callback, raise_if_interrupted, set_cancel_callback
from core import provider_streams
from core.provider_runtime import maybe_warn_insecure_provider


# Custom exceptions.
class APIEmptyResponseError(Exception):
    """Model returned an empty response: no text, no tool calls, and 0 tokens."""
    pass


# Circuit-breaker state storage per provider base_url.
_CB_LOCK      = threading.Lock()
_CIRCUIT_BREAKERS: dict[str, dict] = {}
# Each entry: {"state": "closed"|"open"|"half_open",
#              "failures": int, "opened_at": float}
_CB_TRIP_AT   = 3      # Consecutive failures before opening the circuit.
_CB_RESET_SEC = 30     # Seconds from OPEN to HALF_OPEN.
_RETRY_CODES  = RETRYABLE_HTTP_STATUS_CODES  # Backward-compatible module alias.


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


_RETRY_MAX = _env_int("PAWNLOGIC_API_RETRY_MAX", 3, 1, 8)


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
    return provider_streams.parse_sse_delta(raw)

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
# Anthropic native path: SSE parsing.
# ════════════════════════════════════════════════════════

def _anthropic_parse_sse(event_type: str, data_raw: str, state: dict) -> dict | None:
    return provider_streams.parse_anthropic_sse_event(event_type, data_raw, state)


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


def _stream_interruption_delta(error: OSError, partial_text: str) -> dict[str, object] | None:
    return provider_streams.stream_interruption_delta(error, partial_text)


def _read_anthropic_sse_lines(resp):
    yield from provider_streams.read_anthropic_sse_lines(
        resp,
        read_timeout=_READ_TIMEOUT,
        raise_if_interrupted=raise_if_interrupted,
    )


def _read_openai_sse_lines(resp):
    yield from provider_streams.read_openai_sse_lines(
        resp,
        read_timeout=_READ_TIMEOUT,
        raise_if_interrupted=raise_if_interrupted,
    )


def _read_sse_lines(resp, api_fmt: str):
    yield from provider_streams.read_sse_lines(
        resp,
        api_fmt,
        read_timeout=_READ_TIMEOUT,
        raise_if_interrupted=raise_if_interrupted,
    )

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
        payload = _build_openai_payload(
            messages,
            model_alias,
            model_id,
            _max_tok,
            tools_schema,
            tool_choice,
            response_format,
        )

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
                hdrs = _build_openai_headers(api_key, len(body))
            conn.request("POST", path, body=body, headers=hdrs)

            if conn.sock:
                conn.sock.settimeout(_READ_TIMEOUT)

            resp = conn.getresponse()
            response_ref["response"] = resp

            # HTTP status codes that should be retried.
            if is_retryable_http_status(resp.status):
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

            yield from _read_sse_lines(resp, api_fmt)
            return

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

    maybe_warn_insecure_provider(base_url)

    for attempt in range(_RETRY_MAX):
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

            if is_retryable_http_status(resp.status) and attempt < _RETRY_MAX - 1:
                _interruptible_sleep(_retry_delay(attempt, resp.headers.get("Retry-After")))
                continue
            if resp.status != 200:
                return "", format_http_error(resp.status, raw[:600])

            if api_fmt == "anthropic":
                return _anthropic_parse_response(raw)
            return _parse_openai_nonstream_text(raw)

        except socket.timeout:
            if attempt < _RETRY_MAX - 1:
                _interruptible_sleep(_retry_delay(attempt))
                continue
            return "", (
                f"Request timeout ({_NONSTREAM_TIMEOUT}s): provider did not finish "
                "the non-streaming response. Check network/proxy or switch provider."
            )
        except ssl.SSLError as e:
            return "", f"SSL error: {e}"
        except (ConnectionError, OSError) as e:
            if attempt < _RETRY_MAX - 1:
                _interruptible_sleep(_retry_delay(attempt))
                continue
            return "", format_transport_error(e, proxy=proxy, connect_timeout=_CONN_TIMEOUT)
        except Exception as e:
            return "", format_transport_error(e, proxy=proxy, connect_timeout=_CONN_TIMEOUT)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    return "", "Request failed after retries."
