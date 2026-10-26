"""Plan-only recovery: the escalation ladder, tool_choice fallback and cleanup.

Session-level behaviour (what a whole Turn sends and leaves behind) is pinned in
``tests/test_session_utils.py``; this file pins the pieces it is built from.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core import provider_protocol
from core.api_errors import HTTP_STATUS_HINTS, format_http_error, http_status_from_error
from core.plan_guard import MAX_PLAN_ONLY_RECOVERIES
from core.plan_recovery import (
    KIND_PLAN_ONLY,
    KIND_TOOL_MARKUP,
    RECOVERY_STEPS,
    TOOL_CHOICE_AUTO,
    TOOL_CHOICE_NONE,
    TOOL_CHOICE_REQUIRED,
    TOOL_MARKUP_RECOVERY_STEPS,
    ToolChoiceMemory,
    purge_messages,
    recovery_step,
    recovery_stop_message,
    stream_with_tool_choice,
    tool_choice_for_recovery,
    unusable_reply_kind,
)

# ── the ladder ───────────────────────────────────────────────────────


def test_ladder_has_one_step_per_tolerated_plan_only_reply():
    """A new limit without a matching step would repeat the last step silently."""
    assert len(RECOVERY_STEPS) == MAX_PLAN_ONLY_RECOVERIES


@pytest.mark.parametrize(
    ("recoveries", "expected"),
    [
        (0, TOOL_CHOICE_AUTO),
        (1, TOOL_CHOICE_REQUIRED),
        (2, TOOL_CHOICE_NONE),
        (3, TOOL_CHOICE_NONE),  # past the ladder: the last step, never auto
        (-1, TOOL_CHOICE_AUTO),
    ],
)
def test_tool_choice_follows_the_number_of_plan_only_replies(recoveries, expected):
    assert tool_choice_for_recovery(recoveries) == expected


def test_each_step_tells_the_model_and_the_user_what_the_next_attempt_does():
    required, no_tools = recovery_step(1), recovery_step(2)

    assert required.signal.startswith("[SYSTEM: PLAN_ONLY_RECOVERY]")
    assert "must call a tool" in required.signal
    assert "requires a tool call" in required.notice

    assert no_tools.signal.startswith("[SYSTEM: PLAN_ONLY_RECOVERY_NO_TOOLS]")
    assert "tools are switched off" in no_tools.signal
    assert "<plan>" in no_tools.signal  # tells the model not to emit one
    assert "without tools" in no_tools.notice
    assert "clarifying question" in no_tools.notice

    # The required step must not offer the escape the provider is closing off.
    assert "provide a normal final answer" not in required.signal


# ── a tool call written as text takes the same ladder ────────────────


def test_the_text_call_ladder_is_the_plan_only_ladder_in_other_words():
    """One bound, one escalation: only the nudge wording differs per kind."""
    assert len(TOOL_MARKUP_RECOVERY_STEPS) == len(RECOVERY_STEPS) == MAX_PLAN_ONLY_RECOVERIES
    assert [step.tool_choice for step in TOOL_MARKUP_RECOVERY_STEPS] == [
        step.tool_choice for step in RECOVERY_STEPS
    ]
    # tool_choice_for_recovery is kind-independent because the rungs agree.
    for count in range(0, MAX_PLAN_ONLY_RECOVERIES + 2):
        wanted = tool_choice_for_recovery(count)
        if count:
            assert recovery_step(count, KIND_TOOL_MARKUP).tool_choice == wanted


def test_text_call_steps_say_the_call_was_written_as_text():
    required = recovery_step(1, KIND_TOOL_MARKUP)
    no_tools = recovery_step(2, KIND_TOOL_MARKUP)

    assert required.signal.startswith("[SYSTEM: TOOL_CALL_AS_TEXT]")
    assert "plain text" in required.signal and "nothing was executed" in required.signal
    assert "provider's tool interface" in required.signal
    assert "requires a real tool call" in required.notice
    assert no_tools.signal.startswith("[SYSTEM: TOOL_CALL_AS_TEXT_NO_TOOLS]")
    assert "without tools" in no_tools.notice
    # They never talk about plans: the reply that triggered them had none.
    assert "<plan>" not in required.signal and "<plan>" not in no_tools.signal
    assert required.label == no_tools.label == "Tool-Call Recovery"
    assert recovery_step(1).label == "Plan Recovery"  # the plan-only wording is unchanged


def test_text_call_step_index_clamps_like_the_plan_only_ladder():
    last = TOOL_MARKUP_RECOVERY_STEPS[-1]

    assert recovery_step(0, KIND_TOOL_MARKUP) is TOOL_MARKUP_RECOVERY_STEPS[0]
    assert recovery_step(99, KIND_TOOL_MARKUP) is last
    assert recovery_step(1) is RECOVERY_STEPS[0]  # the default kind is plan-only


def test_the_stop_message_names_what_the_model_kept_doing():
    assert "sent a plan without an action" in recovery_stop_message(KIND_PLAN_ONLY)
    assert "sent a plan without an action" in recovery_stop_message()
    assert "wrote tool calls as text" in recovery_stop_message(KIND_TOOL_MARKUP)


TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "parameters": {}}},
    {"type": "function", "function": {"name": "read_file", "parameters": {}}},
]
PLAN = "<plan><intent>Continue.</intent></plan>"
TEXT_CALL = "<iquestcoder_tool_call>list_dir<arg_key>path</arg_key><arg_value>.</arg_value></iquestcoder_tool_call>"
# A reserved token needs no tool name to be recognised, so with no tool offered
# only the explicit rule below keeps it from being "recovered".
TOKEN_CALL = "<|tool_calls_section_begin|><|tool_call_begin|>functions.list_dir:0<|tool_call_end|>"


@pytest.mark.parametrize(
    ("text", "tc_buf", "tools", "expected"),
    [
        (PLAN, {}, TOOLS, KIND_PLAN_ONLY),
        (TEXT_CALL, {}, TOOLS, KIND_TOOL_MARKUP),
        (PLAN + "\n" + TEXT_CALL, {}, TOOLS, KIND_TOOL_MARKUP),
        ("The directory holds three files.", {}, TOOLS, None),
        (PLAN + "\nThe directory holds three files.", {}, TOOLS, None),
        # A parsed tool call is an action whatever else the reply says.
        (TEXT_CALL, {0: {"id": "c", "name": "list_dir", "args": "{}"}}, TOOLS, None),
        (PLAN, {0: {"id": "c", "name": "list_dir", "args": "{}"}}, TOOLS, None),
        # With no tool offered, a text call is not a failed attempt at anything ...
        (TEXT_CALL, {}, None, None),
        (TEXT_CALL, {}, [], None),
        (TOKEN_CALL, {}, TOOLS, KIND_TOOL_MARKUP),
        (TOKEN_CALL, {}, None, None),
        (TOKEN_CALL, {}, [], None),
        # ... but a bare plan is still not an answer.
        (PLAN, {}, None, KIND_PLAN_ONLY),
    ],
)
def test_unusable_reply_kind(text, tc_buf, tools, expected):
    assert unusable_reply_kind(text, tc_buf, tools) == expected


# ── per-session memory ───────────────────────────────────────────────


def test_memory_is_per_alias_and_never_stores_auto():
    memory = ToolChoiceMemory()
    memory.reject("model-a", TOOL_CHOICE_REQUIRED)
    memory.reject("model-a", TOOL_CHOICE_AUTO)

    assert memory.effective("model-a", TOOL_CHOICE_REQUIRED) == TOOL_CHOICE_AUTO
    assert memory.effective("model-a", TOOL_CHOICE_NONE) == TOOL_CHOICE_NONE
    assert memory.effective("model-b", TOOL_CHOICE_REQUIRED) == TOOL_CHOICE_REQUIRED
    assert memory.rejected("model-a") == frozenset({TOOL_CHOICE_REQUIRED})


# ── the stream wrapper ───────────────────────────────────────────────

_TOOLS = [{"type": "function", "function": {"name": "list_dir"}}]
_OK = [
    {"choices": [{"delta": {"content": "done"}}]},
    {"_usage": {"prompt_tokens": 10, "completion_tokens": 2}},
]
_REJECTED = {"_error": format_http_error(400, b'{"error": {"message": "bad tool_choice"}}')}


class FakeProvider:
    """A ``stream_request`` stand-in that records the kwargs of every call."""

    def __init__(self, *responses: list[dict[str, Any]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    def __call__(self, messages, model_alias, **kwargs):
        self.calls.append(kwargs)
        return iter(self._responses.pop(0))


def _run(provider, choice, memory=None, *, tools=_TOOLS, rejected=None):
    memory = memory or ToolChoiceMemory()
    deltas = list(
        stream_with_tool_choice(
            provider, [], "model-a", choice, memory,
            on_rejected=rejected, tools_schema=tools, max_tokens=100,
        )
    )
    return deltas, memory


def test_auto_request_is_the_request_that_was_sent_before_recovery_existed():
    provider = FakeProvider(_OK)

    deltas, _ = _run(provider, TOOL_CHOICE_AUTO)

    assert deltas == _OK
    assert provider.calls == [{"tools_schema": _TOOLS, "max_tokens": 100}]


def test_required_request_carries_tool_choice():
    provider = FakeProvider(_OK)

    _run(provider, TOOL_CHOICE_REQUIRED)

    assert provider.calls[0]["tool_choice"] == TOOL_CHOICE_REQUIRED


def test_request_without_tools_is_always_auto():
    provider = FakeProvider(_OK)

    _run(provider, TOOL_CHOICE_REQUIRED, tools=None)

    assert "tool_choice" not in provider.calls[0]


@pytest.mark.parametrize("status", [400, 422])
def test_rejected_value_is_retried_once_with_auto_and_remembered(status):
    refusal = {"_error": format_http_error(status, b"nope")}
    provider = FakeProvider([refusal], _OK)
    seen: list[str] = []

    deltas, memory = _run(provider, TOOL_CHOICE_REQUIRED, rejected=seen.append)

    # The refusal never reaches the caller; only the retry's stream does.
    assert deltas == _OK
    assert [call.get("tool_choice") for call in provider.calls] == [
        TOOL_CHOICE_REQUIRED,
        None,
    ]
    assert seen == [TOOL_CHOICE_REQUIRED]
    assert memory.rejected("model-a") == frozenset({TOOL_CHOICE_REQUIRED})

    # The same session never asks for it again: one request, sent as auto.
    again = FakeProvider(_OK)
    _run(again, TOOL_CHOICE_REQUIRED, memory)
    assert len(again.calls) == 1
    assert "tool_choice" not in again.calls[0]


def test_usage_is_counted_once_across_a_refused_request():
    provider = FakeProvider([_REJECTED], _OK)

    deltas, _ = _run(provider, TOOL_CHOICE_REQUIRED)

    usage = [delta["_usage"] for delta in deltas if "_usage" in delta]
    assert usage == [{"prompt_tokens": 10, "completion_tokens": 2}]


@pytest.mark.parametrize(
    "error",
    [
        format_http_error(401, b"no"),
        format_http_error(403, b"no"),
        format_http_error(429, b"slow down"),
        format_http_error(500, b"boom"),
        "Connection refused. Check network, proxy settings, and provider Base URL.",
        "Responses stream error: HTTP 400 inside an event",
    ],
)
def test_errors_that_are_not_a_refused_parameter_are_not_retried(error):
    provider = FakeProvider([{"_error": error}])

    deltas, memory = _run(provider, TOOL_CHOICE_REQUIRED)

    assert deltas == [{"_error": error}]
    assert len(provider.calls) == 1
    assert memory.rejected("model-a") == frozenset()


def test_transport_retry_notices_ahead_of_a_refusal_are_passed_through():
    notice = {"_retry": "HTTP 502 Bad Gateway: retrying in 1s (1/3)."}
    provider = FakeProvider([notice, _REJECTED], _OK)

    deltas, _ = _run(provider, TOOL_CHOICE_REQUIRED)

    assert deltas == [notice, *_OK]


def test_a_failure_after_content_began_is_never_replayed():
    content = {"choices": [{"delta": {"content": "partial"}}]}
    provider = FakeProvider([content, _REJECTED])

    deltas, memory = _run(provider, TOOL_CHOICE_REQUIRED)

    assert deltas == [content, _REJECTED]
    assert len(provider.calls) == 1
    assert memory.rejected("model-a") == frozenset()


def test_auto_being_refused_too_is_reported_not_retried_again():
    provider = FakeProvider([_REJECTED], [_REJECTED])

    deltas, memory = _run(provider, TOOL_CHOICE_REQUIRED)

    assert deltas == [_REJECTED]
    assert len(provider.calls) == 2
    # The 400 was not about tool_choice (auto fails the same way), so the
    # escalation must stay available for the rest of the session.
    assert memory.rejected("model-a") == frozenset()


@pytest.mark.parametrize(
    "retry_error",
    [format_http_error(503, b"overloaded"), "Connection refused. Check network."],
)
def test_a_retry_that_errors_for_another_reason_proves_nothing_about_the_value(retry_error):
    provider = FakeProvider([_REJECTED], [{"_error": retry_error}])
    seen: list[str] = []

    deltas, memory = _run(provider, TOOL_CHOICE_REQUIRED, rejected=seen.append)

    assert deltas == [{"_error": retry_error}]
    assert seen == [] and memory.rejected("model-a") == frozenset()


def test_the_value_is_reported_once_after_retry_notices_and_before_content():
    notice = {"_retry": "HTTP 502 Bad Gateway: retrying in 1s (1/3)."}
    provider = FakeProvider([_REJECTED], [notice, *_OK])
    order: list[str] = []

    def rejected(_choice):
        order.append("rejected")

    stream = stream_with_tool_choice(
        provider, [], "model-a", TOOL_CHOICE_REQUIRED, ToolChoiceMemory(),
        on_rejected=rejected, tools_schema=_TOOLS, max_tokens=100,
    )
    for delta in stream:
        order.append("retry" if "_retry" in delta else "content")

    assert order == ["retry", "rejected", "content", "content"]


def test_auto_request_that_is_refused_is_not_a_tool_choice_problem():
    provider = FakeProvider([_REJECTED])

    deltas, memory = _run(provider, TOOL_CHOICE_AUTO)

    assert deltas == [_REJECTED]
    assert len(provider.calls) == 1
    assert memory.rejected("model-a") == frozenset()


def test_http_status_is_recovered_from_every_formatted_status():
    """The parser and ``format_http_error`` must not drift apart."""
    for status in HTTP_STATUS_HINTS:
        assert http_status_from_error(format_http_error(status, b"x")) == status
    assert http_status_from_error("") is None
    assert http_status_from_error("DNS resolution failed: boom") is None
    assert http_status_from_error("see HTTP 400 above") is None  # anchored at the start


# ── purge ────────────────────────────────────────────────────────────


def test_purge_removes_exactly_the_recorded_messages_by_identity():
    prompt = {"role": "user", "content": "do it"}
    plan = {"role": "assistant", "content": "<plan><intent>x</intent></plan>"}
    nudge = {"role": "user", "content": "[SYSTEM: PLAN_ONLY_RECOVERY]"}
    # Byte-identical to ``plan`` but from an earlier turn: must survive.
    earlier = {"role": "assistant", "content": "<plan><intent>x</intent></plan>"}
    messages = [earlier, prompt, plan, nudge]

    removed = purge_messages(messages, [plan, nudge])

    assert removed == 2
    assert messages == [earlier, prompt]
    assert messages[0] is earlier
    assert purge_messages(messages, [plan, nudge]) == 0  # idempotent
    assert purge_messages(messages, []) == 0


# ── serialization per wire format ────────────────────────────────────


def _payload(api_format: str, tool_choice: str, tools=_TOOLS, messages=None):
    return provider_protocol.build_stream_payload(
        api_format,
        messages or [{"role": "user", "content": "hi"}],
        "model-a",
        "model-a-id",
        100,
        tools,
        tool_choice,
        None,
    )


@pytest.mark.parametrize("api_format", ["openai", "responses"])
@pytest.mark.parametrize("choice", ["auto", "required", "none"])
def test_openai_chat_and_responses_send_the_string(api_format, choice):
    assert _payload(api_format, choice)["tool_choice"] == choice


def test_anthropic_maps_required_and_none_and_omits_auto():
    assert _payload("anthropic", "required")["tool_choice"] == {"type": "any"}
    assert _payload("anthropic", "none")["tool_choice"] == {"type": "none"}
    # ``auto`` is the API default; omitting it keeps ordinary requests unchanged.
    assert "tool_choice" not in _payload("anthropic", "auto")


@pytest.mark.parametrize("api_format", ["openai", "responses", "anthropic"])
def test_no_tools_means_no_tool_choice_on_any_format(api_format):
    assert "tool_choice" not in _payload(api_format, "required", tools=None)


def test_anthropic_tool_choice_value_is_not_shared_between_payloads():
    first = _payload("anthropic", "required")
    first["tool_choice"]["type"] = "tool"

    assert _payload("anthropic", "required")["tool_choice"] == {"type": "any"}


# ── a cleaned-up history stays valid on every format ─────────────────


def test_two_consecutive_user_messages_are_valid_on_every_format():
    """After a failed turn is cleaned up the next prompt follows the old one."""
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first prompt, never answered"},
        {"role": "user", "content": "second prompt"},
    ]

    openai = _payload("openai", "auto", messages=history)["messages"]
    assert [m["role"] for m in openai] == ["system", "user", "user"]

    responses = _payload("responses", "auto", messages=history)
    assert [(i["type"], i["role"]) for i in responses["input"]] == [
        ("message", "user"),
        ("message", "user"),
    ]
    assert responses["instructions"] == "sys"

    anthropic = _payload("anthropic", "auto", messages=history)
    # The Messages API requires alternation, so the converter merges the two.
    assert [m["role"] for m in anthropic["messages"]] == ["user"]
    assert "first prompt, never answered" in anthropic["messages"][0]["content"]
    assert "second prompt" in anthropic["messages"][0]["content"]


# ── through the real transport ───────────────────────────────────────


class _WireResponse:
    def __init__(self, status: int, *, body: bytes = b"", sse: tuple[bytes, ...] = ()) -> None:
        self.status = status
        self._body = body
        self._lines = iter(sse)
        self.headers: dict[str, str] = {}

    def read(self, *_args):
        return self._body

    def readline(self):
        return next(self._lines, b"")


class _Wire:
    """Replaces ``_open_connection``: records every request body it is sent."""

    def __init__(self, *responses: _WireResponse) -> None:
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []

    def open(self, _url, _proxy, timeout):
        wire = self

        class Conn:
            sock = None

            def request(self, _method, _path, body=None, headers=None):
                wire.sent.append(json.loads(body))

            def getresponse(self):
                return wire.responses.pop(0)

            def close(self):
                pass

        return Conn(), "/v1/endpoint"


_OPENAI_OK = (
    b'data: {"choices": [{"delta": {"content": "ok"}}]}\n',
    b"data: [DONE]\n",
)
_RESPONSES_OK = (
    b"event: response.output_text.delta\n",
    b'data: {"type": "response.output_text.delta", "delta": "ok"}\n',
    b"event: response.completed\n",
    b'data: {"type": "response.completed", "response": {}}\n',
)


@pytest.mark.parametrize(
    ("api_format", "ok_stream"),
    [("openai", _OPENAI_OK), ("responses", _RESPONSES_OK)],
)
def test_a_refusal_from_the_real_transport_falls_back_and_never_resends(
    monkeypatch, api_format, ok_stream
):
    """HTTP 400 -> ``_error`` string -> one retry as auto -> remembered, end to end."""
    import core.api_client as api_client

    monkeypatch.setattr(
        api_client,
        "get_provider_config",
        lambda _alias: {
            "base_url": "https://relay.example.invalid/v1/endpoint",
            "api_key": "test-key-not-real",
            "api_format": api_format,
            "auth": "auto",
        },
    )
    monkeypatch.setattr(api_client, "_CIRCUIT_BREAKERS", {})
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var, raising=False)
    wire = _Wire(
        _WireResponse(400, body=b'{"error": {"message": "unknown tool_choice"}}'),
        _WireResponse(200, sse=ok_stream),
        _WireResponse(200, sse=ok_stream),
    )
    monkeypatch.setattr(api_client, "_open_connection", wire.open)
    memory = ToolChoiceMemory()

    def ask(choice):
        return list(
            stream_with_tool_choice(
                api_client.stream_request,
                [{"role": "user", "content": "hi"}],
                "model-a",
                choice,
                memory,
                tools_schema=_TOOLS,
                max_tokens=100,
            )
        )

    deltas = ask(TOOL_CHOICE_REQUIRED)

    # The refusal never surfaced; the retry's content did.
    assert not any("_error" in delta for delta in deltas)
    assert any("ok" in json.dumps(delta) for delta in deltas)
    assert [body["tool_choice"] for body in wire.sent] == ["required", "auto"]
    assert memory.rejected("model-a") == frozenset({TOOL_CHOICE_REQUIRED})

    ask(TOOL_CHOICE_REQUIRED)  # the same session: straight to auto
    assert [body["tool_choice"] for body in wire.sent] == ["required", "auto", "auto"]
