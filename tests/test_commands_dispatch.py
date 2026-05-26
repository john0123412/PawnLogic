"""
Tests for core.commands dispatch registry, routing, and CommandContext.

Three test groups, mirroring the migration-completion checklist:

1. Registry completeness  — pure static assertion that all 56 known
   slash command verbs are present in `COMMANDS`, and that every theme
   submodule (system/session/provider/workspace/tools) imports cleanly.

2. Dispatch routing       — mocks `COMMANDS[verb]` with an `AsyncMock`
   for 1-2 representative verbs from each module, then asserts that
   `dispatch()` invokes the mocked handler with the supplied
   `CommandContext` rather than falling through to the unknown-verb
   path.

3. CommandContext         — straightforward dataclass construction and
   field-access checks.
"""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest


# ════════════════════════════════════════════════════════
# Shared fixtures
# ════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def cmd_pkg():
    """Import core.commands once and return the module object."""
    return importlib.import_module("core.commands")


@pytest.fixture
def fake_session():
    """A bare-bones stand-in for AgentSession.

    Most command handlers touch session.cwd / session.messages / etc.
    For routing tests we don't actually invoke the real handlers (they
    are mocked), so a no-op object is enough.
    """
    class _FakeSession:
        cwd = "/tmp"
        messages: list = []
        model_alias = "ds-v4-flash"
        session_id = "test-session"

        def _reset_system_prompt(self):
            pass

    return _FakeSession()


def _ctx(cmd_pkg, verb: str, arg: str = "", arg2: str = "", session=None):
    """Build a CommandContext with friendly defaults."""
    return cmd_pkg.CommandContext(verb=verb, arg=arg, arg2=arg2, session=session)


# ════════════════════════════════════════════════════════
# 1. Registry completeness
# ════════════════════════════════════════════════════════

# The full set of 56 verbs that must be registered after stage-1 migration.
# Grouped by source module for readability.
EXPECTED_VERBS_BY_MODULE: dict[str, set[str]] = {
    "system": {
        "/help", "/exit", "/quit", "/q",
        "/clear", "/context", "/ctx", "/history",
        "/ping", "/state", "/stats", "/time", "/failures",
        "/low", "/mid", "/deep", "/max", "/normal", "/limits",
        "/tokens", "/iter", "/toolsize", "/fetchsize",
    },
    "session": {
        "/chat", "/save", "/load", "/resume", "/sessions", "/rename", "/del",
        "/forget", "/memo", "/memorize", "/pin", "/unpin", "/undo",
        "/compact", "/think", "/mode",
    },
    "provider": {
        "/setkey", "/keys", "/provider", "/model",
    },
    "workspace": {
        "/cd", "/file", "/init_project", "/workspace",
    },
    "tools": {
        "/docker", "/pwnenv", "/webstatus", "/browserstatus", "/worker",
        "/knowledge", "/skills", "/skillpack", "/sp",
    },
}

EXPECTED_ALL: set[str] = {v for verbs in EXPECTED_VERBS_BY_MODULE.values() for v in verbs}


def test_registry_has_expected_verb_count(cmd_pkg):
    assert len(EXPECTED_ALL) == 56, "Test harness expects 56 distinct verbs"
    assert len(cmd_pkg.COMMANDS) >= 56, (
        f"Expected at least 56 registered commands, got {len(cmd_pkg.COMMANDS)}"
    )


def test_registry_contains_every_expected_verb(cmd_pkg):
    missing = EXPECTED_ALL - set(cmd_pkg.COMMANDS.keys())
    assert not missing, f"Missing registered verbs: {sorted(missing)}"


@pytest.mark.parametrize("verb", sorted(EXPECTED_ALL))
def test_registered_verb_handler_is_callable(cmd_pkg, verb):
    handler = cmd_pkg.COMMANDS.get(verb)
    assert handler is not None, f"Handler for {verb!r} is missing"
    assert asyncio.iscoroutinefunction(handler), (
        f"Handler for {verb!r} must be an async function"
    )


@pytest.mark.parametrize("submodule", sorted(EXPECTED_VERBS_BY_MODULE.keys()))
def test_submodule_imports_cleanly(submodule):
    """Each theme module must import without side-effecting the registry
    (it has already been imported by `core.commands.__init__`).
    """
    mod = importlib.import_module(f"core.commands.{submodule}")
    assert mod is not None


def test_no_legacy_dispatcher_attributes(cmd_pkg):
    """After step 6, the legacy fallback hooks must be gone."""
    assert not hasattr(cmd_pkg, "set_legacy_dispatcher"), (
        "set_legacy_dispatcher should have been removed in step 6"
    )
    assert not hasattr(cmd_pkg, "_LEGACY_DISPATCHER"), (
        "_LEGACY_DISPATCHER global should have been removed in step 6"
    )


# ════════════════════════════════════════════════════════
# 2. Dispatch routing
# ════════════════════════════════════════════════════════

# Representative verbs per module — 2 each, picked to cover both simple
# (no-arg / argument-driven) handlers in each theme.
ROUTING_SAMPLES: list[tuple[str, str]] = [
    # (module, verb)
    ("system",    "/help"),
    ("system",    "/clear"),
    ("session",   "/save"),
    ("session",   "/undo"),
    ("provider",  "/keys"),
    ("provider",  "/model"),
    ("workspace", "/cd"),
    ("workspace", "/file"),
    ("tools",     "/pwnenv"),
    ("tools",     "/knowledge"),
]


@pytest.mark.parametrize("module,verb", ROUTING_SAMPLES)
def test_dispatch_routes_to_registered_handler(cmd_pkg, fake_session, module, verb):
    """Replace the registered handler with an AsyncMock and confirm
    dispatch invokes it with the supplied CommandContext.
    """
    mock_handler = AsyncMock(return_value="OK")
    original = cmd_pkg.COMMANDS[verb]
    cmd_pkg.COMMANDS[verb] = mock_handler
    try:
        ctx = _ctx(cmd_pkg, verb, arg="x", arg2="y", session=fake_session)
        result = asyncio.run(cmd_pkg.dispatch(ctx))
        assert result == "OK"
        mock_handler.assert_awaited_once_with(ctx)
    finally:
        cmd_pkg.COMMANDS[verb] = original


def test_dispatch_unknown_verb_does_not_raise(cmd_pkg, fake_session, capsys):
    """Unknown verbs should print a hint and return None, matching the
    legacy behaviour rather than raising.
    """
    ctx = _ctx(cmd_pkg, "/__definitely_not_a_real_command__", session=fake_session)
    result = asyncio.run(cmd_pkg.dispatch(ctx))
    assert result is None
    captured = capsys.readouterr()
    assert "未知命令" in captured.out


def test_dispatch_aliases_share_handler(cmd_pkg):
    """/skillpack and /sp are registered as aliases of one async function;
    similarly /exit /quit /q. Both should resolve to the same handler obj.
    """
    assert cmd_pkg.COMMANDS["/skillpack"] is cmd_pkg.COMMANDS["/sp"]
    assert cmd_pkg.COMMANDS["/exit"] is cmd_pkg.COMMANDS["/quit"]
    assert cmd_pkg.COMMANDS["/exit"] is cmd_pkg.COMMANDS["/q"]


# ════════════════════════════════════════════════════════
# 3. CommandContext construction
# ════════════════════════════════════════════════════════

def test_command_context_required_fields(cmd_pkg, fake_session):
    ctx = cmd_pkg.CommandContext(
        verb="/help", arg="", arg2="", session=fake_session,
    )
    assert ctx.verb == "/help"
    assert ctx.arg == ""
    assert ctx.arg2 == ""
    assert ctx.session is fake_session


def test_command_context_keeps_arg_payload(cmd_pkg, fake_session):
    ctx = cmd_pkg.CommandContext(
        verb="/load", arg="42", arg2="extra payload", session=fake_session,
    )
    assert ctx.verb == "/load"
    assert ctx.arg == "42"
    assert ctx.arg2 == "extra payload"


def test_command_context_is_dataclass_instance(cmd_pkg, fake_session):
    """CommandContext is declared as @dataclass; verify dataclass behavior."""
    import dataclasses
    ctx = cmd_pkg.CommandContext(verb="/help", arg="", arg2="", session=fake_session)
    assert dataclasses.is_dataclass(ctx)
    fields = {f.name for f in dataclasses.fields(ctx)}
    # `sink` was added in stage-2 step 4 with a None default so existing
    # callers don't have to specify it; dispatch() injects it lazily.
    assert fields == {"verb", "arg", "arg2", "session", "sink"}


def test_command_context_supports_keyword_only_construction(cmd_pkg, fake_session):
    """Positional construction also works, but keyword-style is the
    intended API used throughout main.py and the handlers.
    """
    ctx = cmd_pkg.CommandContext(
        verb="/save",
        arg="my-session",
        arg2="",
        session=fake_session,
    )
    assert ctx.verb == "/save"
    assert ctx.arg == "my-session"


# ════════════════════════════════════════════════════════
# 4. Sink injection (stage-2 step 4)
# ════════════════════════════════════════════════════════

def test_dispatch_injects_active_sink_when_ctx_sink_is_none(cmd_pkg, fake_session):
    """dispatch() should fall back to `get_active_sink()` if ctx.sink is None."""
    from core.commands._common import get_active_sink, set_active_sink
    from core.output import HumanSink, JsonSink

    saved = get_active_sink()
    sentinel = JsonSink()
    set_active_sink(sentinel)
    try:
        captured = {}

        async def _capturing_handler(ctx):
            captured["sink"] = ctx.sink

        original = cmd_pkg.COMMANDS["/help"]
        cmd_pkg.COMMANDS["/help"] = _capturing_handler
        try:
            ctx = _ctx(cmd_pkg, "/help", session=fake_session)
            assert ctx.sink is None  # not pre-set by caller
            asyncio.run(cmd_pkg.dispatch(ctx))
            assert captured["sink"] is sentinel
            assert ctx.sink is sentinel  # dispatch mutated the same ctx
        finally:
            cmd_pkg.COMMANDS["/help"] = original
    finally:
        # Reset to prior sink to avoid bleeding into other tests.
        set_active_sink(saved if not isinstance(saved, HumanSink) else None)


def test_keys_command_emits_json_with_jsonsink(cmd_pkg, fake_session, capsys):
    """/keys with JsonSink should emit one NDJSON line of api_key_env -> bool."""
    import json
    from core.output import JsonSink

    ctx = cmd_pkg.CommandContext(
        verb="/keys", arg="", arg2="", session=fake_session, sink=JsonSink(),
    )
    asyncio.run(cmd_pkg.dispatch(ctx))
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, f"expected exactly one JSON line, got {len(out)}: {out!r}"
    payload = json.loads(out[0])
    assert payload["type"] == "json"
    # The data field is a dict mapping env-var name -> bool.
    assert isinstance(payload["data"], dict)
    for env, status in payload["data"].items():
        assert env.endswith("_API_KEY") or env.endswith("_KEY"), env
        assert isinstance(status, bool)
