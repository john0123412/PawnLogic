"""Tests for the unified reasoning-effort knob.

The effort level is one control that drives two things at once: the
``reasoning_effort`` value sent to the provider, and the local runtime
limits.  These tests pin the four invariants that make that a single
control rather than two independent ones that can disagree:

1. The wire value is sent only for models that declare support.  An
   undeclared model is never sent the field, so an OpenAI-compatible
   relay that rejects it cannot turn an effort change into a 400.
2. Changing the level keeps an explicit ``/worker`` lock.  Every tier
   preset pins ``preferred_worker`` to ``"auto"``, so a blanket preset
   write silently undid the lock — and the ``/worker`` menu reads the
   on-disk policy first, so the menu then disagreed with what
   delegation actually used.
3. A delegated worker clamps ``max_tokens``.  Effort is inherited
   deliberately, but a worker selected for speed must not inherit the
   parent's 32k output budget.
4. ``reasoning_content`` is written back onto the assistant message on
   turns that carry tool calls.  DeepSeek rejects a follow-up turn whose
   prior ``tool_calls`` message is missing its reasoning, so this is
   what keeps the default provider working once effort turns reasoning
   on by default.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config.tiers import EFFORT_LEVELS, TIER_DEEP

# ── helpers ──────────────────────────────────────────────
#
# Every read and write below goes through core.state rather than an
# import-time ``from config import DYNAMIC_CONFIG`` binding.  Several test
# modules in this suite evict ``config`` from ``sys.modules`` at import
# time to defeat a stale mock; that re-imports the package and mints a
# *new* DYNAMIC_CONFIG dict, so a binding captured earlier points at an
# object the product no longer reads and the write lands nowhere.
# Resolving through the accessor is also the seam the product uses.


@pytest.fixture
def restore_dynamic_config():
    """Restore the process-wide runtime config after a mutation test."""
    cfg = _cfg()
    previous = dict(cfg)
    yield
    cfg.clear()
    cfg.update(previous)


def _cfg():
    """Return the live runtime config mapping."""
    from core.state import runtime_config

    return runtime_config()


def _set_effort(level: str) -> None:
    from core.state import update_dynamic_config

    update_dynamic_config({"effort_level": level})


# ── 1. Wire value resolution ─────────────────────────────


class TestWireValueResolution:
    def test_declared_model_sends_the_mapped_value(self, restore_dynamic_config):
        from core.api_payloads import resolve_reasoning_effort

        for level in EFFORT_LEVELS:
            _set_effort(level)
            assert resolve_reasoning_effort("ds-v4-flash") is not None, level

    def test_every_level_maps_to_its_own_wire_value(self, restore_dynamic_config):
        from config.tiers import EFFORT_WIRE_VALUES
        from core.api_payloads import model_effort_map, resolve_reasoning_effort

        accepted = model_effort_map("ds-v4-flash")
        for level, wire in EFFORT_WIRE_VALUES.items():
            assert accepted[level] == wire, level
            _set_effort(level)
            assert resolve_reasoning_effort("ds-v4-flash") == wire, level

    def test_undeclared_model_never_sends_the_field(self, restore_dynamic_config):
        """A model with no declaration and no provider opt-in is silent.

        Effort still changes the local limits for such a model; what it
        must never do is put an unrecognised key in the request body.
        """
        import core.api_payloads as payloads

        for alias, model in payloads.MODELS.items():
            if model.get("effort"):
                continue
            assert payloads.model_effort_map(alias) == {}, alias
            for level in EFFORT_LEVELS:
                _set_effort(level)
                assert payloads.resolve_reasoning_effort(alias) is None, (alias, level)

    def test_non_reasoning_models_stay_undeclared(self):
        """Non-reasoning models must not claim a wire value they ignore."""
        import core.api_payloads as payloads

        for alias in ("gpt-4o", "gpt-4.1"):
            model = payloads.MODELS.get(alias)
            if model is None:
                continue
            assert not model.get("effort"), alias

    def test_payload_carries_reasoning_effort_for_declared_model(
        self, restore_dynamic_config
    ):
        from core.api_payloads import _build_openai_payload

        _set_effort("high")
        payload = _build_openai_payload(
            [{"role": "user", "content": "hi"}],
            "ds-v4-flash",
            "deepseek-v4",
            2048,
            None,
            "auto",
            None,
        )
        assert payload["reasoning_effort"] == "high"

    def test_payload_omits_reasoning_effort_for_undeclared_model(
        self, restore_dynamic_config
    ):
        from core.api_payloads import _build_openai_payload

        _set_effort("high")
        payload = _build_openai_payload(
            [{"role": "user", "content": "hi"}],
            "gpt-4o",
            "gpt-4o",
            2048,
            None,
            "auto",
            None,
        )
        assert "reasoning_effort" not in payload

    def test_provider_opt_in_lets_a_custom_model_receive_the_ladder(
        self, monkeypatch, restore_dynamic_config
    ):
        import core.api_payloads as payloads

        # gpt-4o declares nothing, so the ladder reaches it only through an
        # explicit provider opt-in.  Patch the maps api_payloads actually
        # reads: it binds MODELS/PROVIDERS at import time, so a freshly
        # imported config.providers.PROVIDERS may be a different dict.
        monkeypatch.setitem(payloads.PROVIDERS["openai"], "reasoning_effort", True)
        accepted = payloads.model_effort_map("gpt-4o")
        assert accepted, "opt-in must grant the ladder"
        # ``off`` is deliberately excluded: opting in is not a claim that
        # the provider has a ``none`` value.
        assert "off" not in accepted
        _set_effort("xhigh")
        assert payloads.resolve_reasoning_effort("gpt-4o") == "xhigh"
        _set_effort("off")
        assert payloads.resolve_reasoning_effort("gpt-4o") is None

    def test_resolution_uses_the_active_level_not_a_stale_snapshot(
        self, restore_dynamic_config
    ):
        from core.api_payloads import resolve_reasoning_effort

        _set_effort("low")
        assert resolve_reasoning_effort("ds-v4-flash") == "low"
        _set_effort("max")
        assert resolve_reasoning_effort("ds-v4-flash") == "max"

    def test_missing_level_falls_back_to_the_default(self):
        from config.tiers import DEFAULT_EFFORT_LEVEL
        from core.api_payloads import resolve_reasoning_effort

        _cfg().pop("effort_level", None)
        assert resolve_reasoning_effort("ds-v4-flash") == DEFAULT_EFFORT_LEVEL


# ── 2. /worker lock survives an effort change ────────────


class TestWorkerLockPreserved:
    def _apply(self, level: str) -> None:
        from core.commands import CommandContext
        from core.commands.system import apply_effort

        class _Session:
            model_alias = "ds-v4-flash"

            def _reset_system_prompt(self) -> None:
                pass

        assert apply_effort(
            CommandContext(verb="/effort", arg=level, arg2="", session=_Session()),
            level,
        )

    def test_effort_change_keeps_an_explicit_worker(self, restore_dynamic_config):
        _cfg()["preferred_worker"] = "ds-v4-flash"
        self._apply("high")
        assert _cfg()["preferred_worker"] == "ds-v4-flash"

    def test_legacy_tier_alias_also_keeps_an_explicit_worker(
        self, restore_dynamic_config
    ):
        import asyncio

        from core.commands import CommandContext
        from core.commands.system import cmd_deep

        class _Session:
            model_alias = "ds-v4-flash"

            def _reset_system_prompt(self) -> None:
                pass

        _cfg()["preferred_worker"] = "ds-v4-flash"
        asyncio.run(
            cmd_deep(CommandContext(verb="/deep", arg="", arg2="", session=_Session()))
        )
        assert _cfg()["preferred_worker"] == "ds-v4-flash"

    def test_unset_worker_stays_auto(self, restore_dynamic_config):
        _cfg()["preferred_worker"] = "auto"
        self._apply("low")
        assert _cfg()["preferred_worker"] == "auto"

    def test_effort_change_still_applies_the_new_limits(self, restore_dynamic_config):
        self._apply("high")
        assert _cfg()["max_iter"] == TIER_DEEP["max_iter"]


# ── 3. Sub-agent output clamp ────────────────────────────


class TestSubAgentTokenClamp:
    def test_clamp_caps_the_inherited_budget(self):
        """The clamp is only meaningful if the top rung exceeds it."""
        from core.delegation_runtime import SubAgentSession

        assert TIER_DEEP["max_tokens"] > SubAgentSession.MAX_TOKENS

    def _requested_max_tokens(
        self, monkeypatch, *, remaining_tokens: int = 1_000_000
    ) -> int:
        from core import delegation_runtime

        seen: dict = {}

        def _fake_stream(messages, model_alias, **kwargs):
            seen["max_tokens"] = kwargs.get("max_tokens")
            return MagicMock()

        monkeypatch.setattr(delegation_runtime, "stream_request", _fake_stream)
        worker = delegation_runtime.SubAgentSession(
            task="recon", model_alias="ds-v4-flash"
        )
        worker._request_stream(tools_schema=[], remaining_tokens=remaining_tokens)
        return seen["max_tokens"]

    def test_worker_is_clamped_at_the_top_effort_rung(
        self, monkeypatch, restore_dynamic_config
    ):
        """A worker selected for speed must not inherit the parent's 32k."""
        from core.delegation_runtime import SubAgentSession

        _cfg()["max_tokens"] = TIER_DEEP["max_tokens"]
        assert self._requested_max_tokens(monkeypatch) == SubAgentSession.MAX_TOKENS

    def test_clamp_does_not_inflate_a_smaller_budget(
        self, monkeypatch, restore_dynamic_config
    ):
        _cfg()["max_tokens"] = 4_000
        assert self._requested_max_tokens(monkeypatch) == 4_000

    def test_remaining_context_still_wins(self, monkeypatch, restore_dynamic_config):
        """The clamp caps the parent's tuning; it does not override the
        remaining-context budget, which is a correctness bound."""
        _cfg()["max_tokens"] = TIER_DEEP["max_tokens"]
        assert self._requested_max_tokens(monkeypatch, remaining_tokens=512) == 512


# ── 4. reasoning_content read-back ───────────────────────


class TestReasoningContentReadBack:
    """DeepSeek returns 400 when a tool-call turn is replayed without the
    assistant's ``reasoning_content``.  The no-tool-call branch was the
    obvious one to get right; the tool-call branch is the one that runs on
    every real agent turn."""

    def _session(self):
        from core.session import AgentSession

        session = AgentSession.__new__(AgentSession)
        session.messages = []
        session._print_turn_summary = lambda: None
        session._autosave = lambda **kwargs: None
        return session

    def test_tool_call_turn_stores_reasoning_content(self):
        session = self._session()
        session._append_assistant_or_tool_call_message(
            "calling a tool",
            {0: {"id": "call_1", "name": "read_file", "args": "{}"}},
            "step by step",
        )
        message = session.messages[-1]
        assert message["role"] == "assistant"
        assert message["reasoning_content"] == "step by step"
        assert message["tool_calls"][0]["function"]["name"] == "read_file"

    def test_text_only_turn_still_stores_reasoning_content(self):
        session = self._session()
        result = session._append_assistant_or_tool_call_message(
            "done", {}, "thought it through"
        )
        assert result is False
        assert session.messages[-1]["reasoning_content"] == "thought it through"

    def test_absent_reasoning_adds_no_key(self):
        session = self._session()
        session._append_assistant_or_tool_call_message("done", {}, "")
        assert "reasoning_content" not in session.messages[-1]

    def test_sanitizer_preserves_reasoning_content_for_reasoning_models(self):
        """A reasoning model must see the field; a non-reasoning one must not."""
        from core.api_payloads import _sanitize_messages_for_model

        messages = [
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "hidden chain",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
        kept = _sanitize_messages_for_model(messages, "ds-v4-flash", "deepseek-v4")
        assert kept[0]["reasoning_content"] == "hidden chain"
        assert kept[0]["tool_calls"][0]["id"] == "call_1"

    def test_tool_call_turn_round_trips_through_the_payload(
        self, restore_dynamic_config
    ):
        """End-to-end shape: store, sanitize, payload, next request."""
        from core.api_payloads import (
            _build_openai_payload,
            _sanitize_messages_for_model,
        )

        session = self._session()
        session._append_assistant_or_tool_call_message(
            "calling a tool",
            {0: {"id": "call_1", "name": "read_file", "args": '{"path":"a"}'}},
            "the chain of thought",
        )
        _set_effort("high")
        sanitized = _sanitize_messages_for_model(
            session.messages, "ds-v4-flash", "deepseek-v4"
        )
        payload = _build_openai_payload(
            sanitized, "ds-v4-flash", "deepseek-v4", 2048, None, "auto", None
        )
        assert payload["messages"][0]["reasoning_content"] == "the chain of thought"
        assert payload["reasoning_effort"] == "high"


# ── 5. /model chains the effort picker ───────────────────


class _StubController:
    """Records every selector the command mounts, in order."""

    def __init__(self, answers: list[str | None]) -> None:
        self.answers = list(answers)
        self.calls: list = []

    async def run_selector(self, factory):
        self.calls.append(factory())
        return self.answers.pop(0) if self.answers else None


class _StubSession:
    def __init__(self) -> None:
        self.model_alias = "gpt-4o"
        self.messages: list = []

    def _reset_system_prompt(self) -> None:
        pass


def _model_ctx(alias_arg: str, effort_arg: str = "", controller=None, session=None):
    """Build the context the way the CLI does.

    ``handle_slash`` splits the line as ``verb arg arg2``, so
    ``/model <alias> <effort>`` reaches the command with the alias in
    ``arg`` and the level in ``arg2`` -- not as one two-token string.
    """
    from core.commands import CommandContext

    return CommandContext(
        verb="/model",
        arg=alias_arg,
        arg2=effort_arg,
        session=session or _StubSession(),
        terminal_controller=controller,
    )


class TestModelSelectionChainsEffort:
    def test_selecting_a_declared_model_opens_the_effort_picker(
        self, monkeypatch, restore_dynamic_config
    ):
        """Effort is chosen in the same interaction as the model."""
        import asyncio

        from core.commands import provider as provider_commands

        monkeypatch.setattr(
            provider_commands, "validate_api_key", lambda _a: (True, "ENV")
        )
        # Model switching is gated on provider activity.  DeepSeek is the
        # only provider active by default and every one of its aliases
        # declares effort, so an undeclared model only exists behind this.
        monkeypatch.setattr(
            provider_commands, "is_provider_active", lambda _p: True
        )
        session = _StubSession()
        controller = _StubController(["high"])
        asyncio.run(provider_commands.cmd_model(_model_ctx("ds-v4-flash", controller=controller, session=session)))

        assert session.model_alias == "ds-v4-flash"
        assert len(controller.calls) == 1, "the effort picker must follow the model"
        assert controller.calls[0].current == "medium"
        # The applied level, not just the selection: the whole point of
        # chaining is that picking a level takes effect.
        assert _cfg()["effort_level"] == "high"

    def test_picking_a_model_alone_keeps_the_current_effort(
        self, monkeypatch, restore_dynamic_config
    ):
        import asyncio

        from core.commands import provider as provider_commands

        monkeypatch.setattr(
            provider_commands, "validate_api_key", lambda _a: (True, "ENV")
        )
        # Model switching is gated on provider activity.  DeepSeek is the
        # only provider active by default and every one of its aliases
        # declares effort, so an undeclared model only exists behind this.
        monkeypatch.setattr(
            provider_commands, "is_provider_active", lambda _p: True
        )
        _set_effort("xhigh")
        controller = _StubController([None])  # user pressed Esc
        asyncio.run(provider_commands.cmd_model(_model_ctx("ds-v4-flash", controller=controller)))
        assert _cfg()["effort_level"] == "xhigh"

    def test_undeclared_model_skips_the_picker_but_reports_the_level(
        self, monkeypatch, restore_dynamic_config, capsys
    ):
        """Prompting to negotiate effort with a model that ignores it is noise."""
        import asyncio

        from core.commands import provider as provider_commands

        monkeypatch.setattr(
            provider_commands, "validate_api_key", lambda _a: (True, "ENV")
        )
        # Model switching is gated on provider activity.  DeepSeek is the
        # only provider active by default and every one of its aliases
        # declares effort, so an undeclared model only exists behind this.
        monkeypatch.setattr(
            provider_commands, "is_provider_active", lambda _p: True
        )
        controller = _StubController(["high"])
        asyncio.run(provider_commands.cmd_model(_model_ctx("gpt-4o", controller=controller)))
        out = capsys.readouterr().out
        assert controller.calls == [], "no picker for an undeclared model"
        assert "local limits only" in out

    def test_two_token_form_sets_model_and_level_in_one_step(
        self, monkeypatch, restore_dynamic_config
    ):
        import asyncio

        from core.commands import provider as provider_commands

        monkeypatch.setattr(
            provider_commands, "validate_api_key", lambda _a: (True, "ENV")
        )
        # Model switching is gated on provider activity.  DeepSeek is the
        # only provider active by default and every one of its aliases
        # declares effort, so an undeclared model only exists behind this.
        monkeypatch.setattr(
            provider_commands, "is_provider_active", lambda _p: True
        )
        session = _StubSession()
        # A controller is attached on purpose: the scripted form must not
        # re-open the picker, because doing so would ignore the level the
        # caller just typed and block on a modal they did not ask for.
        controller = _StubController(["low"])
        asyncio.run(
            provider_commands.cmd_model(
                _model_ctx("ds-v4-flash", "max", controller=controller, session=session)
            )
        )
        assert session.model_alias == "ds-v4-flash"
        assert _cfg()["effort_level"] == "max"
        assert controller.calls == [], "the scripted form must not re-prompt"

    def test_two_token_form_rejects_an_unknown_level(
        self, monkeypatch, restore_dynamic_config, capsys
    ):
        """A bad level must be refused before the model is switched.

        Asserting only that the level is unchanged would pass either way,
        because ``apply_effort`` rejects unknown levels on its own.  What
        matters is that the command reports the bad level and leaves the
        model alone, instead of half-applying the switch.
        """
        import asyncio

        from core.commands import provider as provider_commands

        monkeypatch.setattr(
            provider_commands, "validate_api_key", lambda _a: (True, "ENV")
        )
        # Model switching is gated on provider activity.  DeepSeek is the
        # only provider active by default and every one of its aliases
        # declares effort, so an undeclared model only exists behind this.
        monkeypatch.setattr(
            provider_commands, "is_provider_active", lambda _p: True
        )
        _set_effort("medium")
        session = _StubSession()
        session.model_alias = "ds-v4-pro"
        asyncio.run(
            provider_commands.cmd_model(
                _model_ctx("ds-v4-flash", "turbo", session=session)
            )
        )
        out = capsys.readouterr().out
        assert "Unknown effort level: turbo" in out
        assert "ds-v4-flash" not in out, "the model must not be switched"
        assert session.model_alias == "ds-v4-pro"
        assert _cfg()["effort_level"] == "medium"


# ── 6. /provider effort opt-in ───────────────────────────


class TestProviderEffortOptIn:
    def test_usage_is_printed_without_arguments(self, capsys):
        from core.commands.provider import cmd_provider

        asyncio_run(cmd_provider(_provider_ctx("effort")))
        assert "Usage: /provider effort <name> on|off" in capsys.readouterr().out

    def test_unknown_provider_is_refused(self, capsys):
        from core.commands.provider import cmd_provider

        asyncio_run(cmd_provider(_provider_ctx("effort", "not-a-provider on")))
        assert "Unknown provider" in capsys.readouterr().out

    def test_bad_state_argument_is_refused(self, capsys):
        from core.commands.provider import cmd_provider

        asyncio_run(cmd_provider(_provider_ctx("effort", "deepseek maybe")))
        assert "Usage:" in capsys.readouterr().out


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def _provider_ctx(sub: str, sub_arg: str = ""):
    from core.commands import CommandContext

    return CommandContext(
        verb="/provider",
        arg=sub,
        arg2=sub_arg,
        session=None,
        terminal_controller=None,
    )
