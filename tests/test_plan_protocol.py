"""The plan protocol switch: resolver, persistence, command, and prompt.

A model that treats writing the ``<plan>`` as the action it was asked for
answers a request with a plan and no tool call.  A custom provider can switch
the protocol off, and everything that asks for or enforces a plan follows one
resolver.  Session behaviour (rebuild, guard) is pinned in
``tests/test_session_utils.py``; this file pins the pieces.

Module-identity note: several test modules evict ``config`` from
``sys.modules`` at import, so a name bound here at import time can be a
different object from the one the product reads.  The resolver is patched
through its own handles (``plan_protocol.MODELS`` and
``plan_protocol.provider_config``), and the command, which resolves
``config.providers`` inside the call, through ``sys.modules`` -- the pattern the
``/provider effort`` tests use.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import plan_protocol, prompt_builder
from core.tool_result import build_anti_code_loop_message, build_anti_loop_message

_RELAY_PROVIDER = {
    "base_url": "https://relay.example.invalid/v1",
    "api_key_env": "RELAY_API_KEY",
    "label": "Relay",
    "api_format": "openai",
    "active": True,
}


def _live_provider_config():
    """Return the ``config.providers`` object the command actually reads."""
    import config.providers  # noqa: F401 - ensures the module is in sys.modules

    return sys.modules["config.providers"]


def _write_custom_provider_file(path: Path, **relay_extra) -> None:
    path.write_text(
        json.dumps(
            {
                "providers": {"relay": {**_RELAY_PROVIDER, **relay_extra}},
                "models": {
                    "relay-chat": {"id": "relay-chat", "provider": "relay", "desc": "Relay chat"}
                },
                "provider_states": {"relay": {"active": True}, "openai": {"active": True}},
            }
        ),
        encoding="utf-8",
    )


def _builtin_plus_relay_providers(**relay_extra):
    return {
        "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
        "openai": {"api_key_env": "OPENAI_API_KEY", "active": False},
        "anthropic": {"api_key_env": "ANTHROPIC_API_KEY", "active": False},
        "relay": {**_RELAY_PROVIDER, **relay_extra},
    }


def _reload_in_fresh_process(home: Path) -> dict:
    """Load custom providers in a new interpreter, the way a restart does."""
    script = (
        "import json, config.providers as pc\n"
        "pc.load_custom_providers()\n"
        "print(json.dumps({\n"
        "    'providers': sorted(pc.PROVIDERS),\n"
        "    'models': sorted(pc.MODELS),\n"
        "    'relay_plan': pc.PROVIDERS['relay'].get('plan_protocol', 'absent') if 'relay' in pc.PROVIDERS else 'missing',\n"
        "    'relay_resolves': pc.provider_plan_protocol('relay'),\n"
        "    'relay_active': pc.is_provider_active('relay'),\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PAWNLOGIC_HOME": str(home), "PAWNLOGIC_TEST_MODE": "true"},
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


# ── the resolver ─────────────────────────────────────────────────────


@pytest.fixture()
def resolver_tables(monkeypatch):
    """Provider and model tables behind ``plan_protocol_enabled``."""
    providers = {
        "deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
        "openai": {"api_key_env": "OPENAI_API_KEY"},
        "relay": dict(_RELAY_PROVIDER),
        "quiet": {**_RELAY_PROVIDER, "plan_protocol": False},
        "explicit": {**_RELAY_PROVIDER, "plan_protocol": True},
    }
    models = {
        "ds-v4-flash": {"id": "deepseek-flash", "provider": "deepseek"},
        "gpt-4o": {"id": "gpt-4o", "provider": "openai"},
        "relay-chat": {"id": "relay-chat", "provider": "relay"},
        "quiet-chat": {"id": "quiet-chat", "provider": "quiet"},
        "explicit-chat": {"id": "explicit-chat", "provider": "explicit"},
        "orphan-chat": {"id": "orphan", "provider": "not-registered"},
        "no-provider": {"id": "x"},
    }
    monkeypatch.setattr(plan_protocol, "MODELS", models)
    monkeypatch.setattr(plan_protocol.provider_config, "PROVIDERS", providers)
    return providers, models


def test_only_a_custom_provider_that_says_false_turns_the_protocol_off(resolver_tables):
    assert plan_protocol.plan_protocol_enabled("quiet-chat") is False
    assert plan_protocol.plan_protocol_enabled("relay-chat") is True  # key absent
    assert plan_protocol.plan_protocol_enabled("explicit-chat") is True  # true
    assert plan_protocol.plan_protocol_enabled("ds-v4-flash") is True
    assert plan_protocol.plan_protocol_enabled("gpt-4o") is True


def test_an_unknown_model_or_provider_keeps_todays_behaviour(resolver_tables):
    assert plan_protocol.plan_protocol_enabled("not-a-model") is True
    assert plan_protocol.plan_protocol_enabled("") is True
    assert plan_protocol.plan_protocol_enabled("orphan-chat") is True
    assert plan_protocol.plan_protocol_enabled("no-provider") is True


@pytest.mark.parametrize("stray", ["off", "false", 0, None, "", [], {}])
def test_a_hand_edited_value_that_is_not_false_leaves_the_protocol_on(resolver_tables, stray):
    providers, _models = resolver_tables
    providers["quiet"]["plan_protocol"] = stray

    assert plan_protocol.plan_protocol_enabled("quiet-chat") is True


def test_a_built_in_provider_can_never_be_switched_off(resolver_tables):
    """A stray key on a built-in entry must not change a built-in's prompt."""
    providers, _models = resolver_tables
    for builtin in ("deepseek", "openai"):
        providers[builtin]["plan_protocol"] = False

    assert plan_protocol.plan_protocol_enabled("ds-v4-flash") is True
    assert plan_protocol.plan_protocol_enabled("gpt-4o") is True


class _Session:
    def __init__(self, alias, recorded=None):
        self.model_alias = alias
        if recorded is not None:
            self._prompt_plan_protocol = recorded


def test_the_prompt_flag_is_what_consumers_read_once_a_prompt_exists(resolver_tables):
    built_off = _Session("relay-chat", recorded=False)

    # The live answer for the model is True, but the prompt carries no protocol.
    assert plan_protocol.plan_protocol_enabled("relay-chat") is True
    assert plan_protocol.prompt_plan_protocol(built_off) is False
    assert plan_protocol.plan_prompt_is_stale(built_off) is True


def test_a_session_without_a_prompt_falls_back_to_the_live_answer(resolver_tables):
    assert plan_protocol.prompt_plan_protocol(_Session("quiet-chat")) is False
    assert plan_protocol.prompt_plan_protocol(_Session("relay-chat")) is True
    assert plan_protocol.plan_prompt_is_stale(_Session("quiet-chat")) is False


def test_a_prompt_built_for_the_current_setting_is_not_stale(resolver_tables):
    assert plan_protocol.plan_prompt_is_stale(_Session("quiet-chat", recorded=False)) is False
    assert plan_protocol.plan_prompt_is_stale(_Session("relay-chat", recorded=True)) is False
    assert plan_protocol.plan_prompt_is_stale(_Session("quiet-chat", recorded=True)) is True


# ── persistence: the same two guards as /provider effort ─────────────


def test_set_provider_plan_protocol_refuses_builtins_without_the_command_layer(tmp_path, monkeypatch):
    """Pin the persistence boundary on its own, not through the command.

    The command guard returns before the write is attempted, so deleting the
    guard in ``config/providers.py`` would leave a command-level test green.
    """
    provider_config = _live_provider_config()
    home = tmp_path / "home"
    home.mkdir()
    path = home / "custom_providers.json"
    _write_custom_provider_file(path)
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    for builtin in sorted(provider_config.BUILTIN_PROVIDER_NAMES):
        assert provider_config.set_provider_plan_protocol(builtin, False) is False
    assert path.read_text(encoding="utf-8") == before

    reloaded = _reload_in_fresh_process(home)
    assert reloaded["providers"] == ["anthropic", "deepseek", "openai", "relay"]
    assert "relay-chat" in reloaded["models"]
    assert reloaded["relay_active"] is True


def test_set_provider_plan_protocol_never_mints_a_partial_entry(tmp_path, monkeypatch):
    """A registered name with no complete file entry must not be written."""
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": {"halfwritten": {"base_url": "https://relay.example.invalid/v1"}},
                "models": {},
                "provider_states": {},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "halfwritten": {"api_key_env": "HALFWRITTEN_API_KEY", "active": False},
            "unsaved": {"api_key_env": "UNSAVED_API_KEY", "active": False},
        },
    )

    # An incomplete entry on disk, and a registered provider with no entry at all.
    assert provider_config.set_provider_plan_protocol("halfwritten", False) is False
    assert provider_config.set_provider_plan_protocol("unsaved", False) is False
    assert path.read_text(encoding="utf-8") == before


def test_set_provider_plan_protocol_refuses_a_complete_shadow_entry(tmp_path, monkeypatch):
    """A built-in name stays refused even when a complete entry exists for it.

    The loader skips any provider whose name is a built-in, so writing the flag
    into such an entry would report success and change nothing on the next
    start.
    """
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "base_url": "https://api.openai.com/v1/chat/completions",
                        "api_key_env": "OPENAI_API_KEY",
                        "api_format": "openai",
                    }
                },
                "models": {},
                "provider_states": {},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    assert provider_config.set_provider_plan_protocol("openai", False) is False
    assert path.read_text(encoding="utf-8") == before


def test_plan_protocol_persists_on_a_complete_custom_entry_and_survives_a_restart(
    tmp_path, monkeypatch
):
    provider_config = _live_provider_config()
    home = tmp_path / "home"
    home.mkdir()
    path = home / "custom_providers.json"
    _write_custom_provider_file(path)
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    assert provider_config.set_provider_plan_protocol("relay", False) is True

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["providers"]["relay"]["plan_protocol"] is False
    # The entry stays complete, and nothing else in the file moved.
    for key in ("base_url", "api_key_env", "api_format", "label"):
        assert data["providers"]["relay"][key] == _RELAY_PROVIDER[key]
    assert "openai" not in data["providers"]
    assert data["models"]["relay-chat"]["provider"] == "relay"
    assert data["provider_states"] == {"relay": {"active": True}, "openai": {"active": True}}
    assert provider_config.PROVIDERS["relay"]["plan_protocol"] is False  # live table
    assert provider_config.provider_plan_protocol("relay") is False

    reloaded = _reload_in_fresh_process(home)
    # The file still loads whole -- the key is not what the validator objects to --
    # and the setting is what a restarted process resolves.
    assert reloaded["providers"] == ["anthropic", "deepseek", "openai", "relay"]
    assert "relay-chat" in reloaded["models"]
    assert reloaded["relay_active"] is True
    assert reloaded["relay_plan"] is False
    assert reloaded["relay_resolves"] is False

    assert provider_config.set_provider_plan_protocol("relay", True) is True
    assert json.loads(path.read_text(encoding="utf-8"))["providers"]["relay"]["plan_protocol"] is True
    assert provider_config.provider_plan_protocol("relay") is True
    assert _reload_in_fresh_process(home)["relay_resolves"] is True


def test_the_validator_carries_the_unknown_key_through_instead_of_rejecting_the_file():
    """Why downgrading is safe.

    ``load_custom_providers`` abandons the whole file when the validator raises.
    The validator copies the entry (``**prov``) and has never had a key
    whitelist, so a release that predates ``plan_protocol`` loads a file that
    carries it -- the key is simply unused there, and the protocol stays on.
    """
    provider_config = _live_provider_config()

    providers, _models = provider_config._validated_custom_provider_data(
        {"providers": {"relay": {**_RELAY_PROVIDER, "plan_protocol": False}}, "models": {}}
    )

    assert providers["relay"]["plan_protocol"] is False
    assert providers["relay"]["base_url"] == _RELAY_PROVIDER["base_url"]


def test_the_reasoning_effort_setter_behaves_as_before_the_shared_helper(tmp_path, monkeypatch):
    """Both flags go through one helper; the older one must not have changed."""
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    _write_custom_provider_file(path)
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    assert provider_config.set_provider_reasoning_effort("openai", True) is False
    assert provider_config.set_provider_reasoning_effort("relay", True) is True

    entry = json.loads(path.read_text(encoding="utf-8"))["providers"]["relay"]
    assert entry["reasoning_effort"] is True
    assert "plan_protocol" not in entry  # the two flags are independent
    assert provider_config.set_provider_plan_protocol("relay", False) is True
    entry = json.loads(path.read_text(encoding="utf-8"))["providers"]["relay"]
    assert entry["reasoning_effort"] is True and entry["plan_protocol"] is False


# ── /provider plan, through the real handle_slash split ──────────────


@pytest.fixture()
def provider_file(tmp_path, monkeypatch):
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    _write_custom_provider_file(path)
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())
    return path


def _slash(line: str) -> None:
    from pawnlogic import cli

    asyncio.run(cli.handle_slash(line, None))


def test_provider_plan_off_reaches_the_handler_with_name_and_state_split(provider_file, capsys):
    """``/provider plan relay off`` arrives as arg="plan", arg2="relay off"."""
    _slash("/provider plan relay off")

    out = capsys.readouterr().out
    assert "plan protocol off for provider 'relay'" in out
    assert json.loads(provider_file.read_text(encoding="utf-8"))["providers"]["relay"]["plan_protocol"] is False


def test_provider_plan_on_turns_it_back_on(provider_file, capsys):
    _slash("/provider plan relay off")
    _slash("/provider plan relay on")

    out = capsys.readouterr().out
    assert "plan protocol on for provider 'relay'" in out
    assert json.loads(provider_file.read_text(encoding="utf-8"))["providers"]["relay"]["plan_protocol"] is True


def test_provider_plan_without_a_state_reports_and_does_not_write(provider_file, capsys):
    untouched = provider_file.read_text(encoding="utf-8")

    _slash("/provider plan relay")
    on_report = capsys.readouterr().out
    assert provider_file.read_text(encoding="utf-8") == untouched
    assert "plan protocol for 'relay': " in on_report
    assert "asked for a <plan> before tool calls" in on_report

    _slash("/provider plan relay off")
    capsys.readouterr()
    switched_off = provider_file.read_text(encoding="utf-8")
    assert switched_off != untouched

    _slash("/provider plan relay")
    off_report = capsys.readouterr().out
    assert provider_file.read_text(encoding="utf-8") == switched_off
    assert "plan protocol for 'relay': " in off_report
    assert "are not asked for a <plan>" in off_report and "asked for a <plan> before" not in off_report


def test_provider_plan_on_a_builtin_is_refused_and_preserves_the_config_file(provider_file, capsys):
    before = provider_file.read_text(encoding="utf-8")

    _slash("/provider plan openai off")

    out = capsys.readouterr().out
    assert "built-in provider" in out
    assert "✓" not in out
    assert provider_file.read_text(encoding="utf-8") == before


def test_provider_plan_report_for_a_builtin_is_read_only(provider_file, capsys):
    before = provider_file.read_text(encoding="utf-8")

    _slash("/provider plan deepseek")

    out = capsys.readouterr().out
    assert "plan protocol for 'deepseek'" in out and "always use the plan protocol" in out
    assert provider_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ("/provider plan", "Usage: /provider plan <name> [on|off]"),
        ("/provider plan relay maybe", "Usage: /provider plan <name> [on|off]"),
        ("/provider plan relay off now", "Usage: /provider plan <name> [on|off]"),
        ("/provider plan nosuch off", "Unknown provider 'nosuch'"),
    ],
)
def test_provider_plan_rejects_bad_input_without_writing(provider_file, capsys, line, needle):
    before = provider_file.read_text(encoding="utf-8")

    _slash(line)

    assert needle in capsys.readouterr().out
    assert provider_file.read_text(encoding="utf-8") == before


def test_provider_plan_refuses_an_incomplete_entry_instead_of_creating_one(
    tmp_path, monkeypatch, capsys
):
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    path.write_text(json.dumps({"providers": {"relay": {"base_url": "https://x.invalid"}}}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    _slash("/provider plan relay off")

    out = capsys.readouterr().out
    assert "Could not update the plan protocol for 'relay'" in out
    assert "✓" not in out
    assert path.read_text(encoding="utf-8") == before


def test_the_unknown_subcommand_hint_lists_plan(capsys):
    _slash("/provider nosuchsub")

    assert "effort · plan · remove" in capsys.readouterr().out


# ── the prompt ───────────────────────────────────────────────────────


class _Scanner:
    def match(self, _query, *, top_k):
        return []

    def format_for_prompt(self, _packs):
        return ""


def _prompt(**overrides) -> str:
    args = {
        "cfg": {"max_tokens": 1, "max_iter": 1, "ctx_max_chars": 1_000, "tool_max_chars": 1_000},
        "cwd": "/tmp/fake-project",
        "current_phase": "RECON",
        "model_alias": "fake-model",
        "model": {"id": "fake/model"},
        "urgent_mode": False,
        "knowledge_query": "",
        "version": "0.0.0-test",
        "global_skills_path": Path("/tmp/fake-skills.md"),
        "agent_phases": {"RECON": ["list_dir"], "EXPLOIT": ["run_code"]},
        "load_state_md": lambda _cwd: "",
        "load_skills_toc": lambda: "# Pwn",
        "search_knowledge": lambda _query, *, limit: [],
        "format_knowledge_for_prompt": lambda _rows: "",
        "load_relevant_skills": lambda _query, *, top_k, **_kw: ("", ""),
        "skill_scanner": _Scanner(),
    }
    args.update(overrides)
    return prompt_builder.build_session_prompt(**args).prompt


SECTION_HEADER = "=== Execution Protocol (MANDATORY) ==="
NEXT_SECTION = "=== NEGATIVE CONSTRAINTS"


def test_protocol_on_is_the_default_and_carries_the_section():
    prompt = _prompt()

    assert prompt == _prompt(plan_protocol=True)
    assert prompt.count(SECTION_HEADER) == 1
    assert prompt_builder._EXECUTION_PROTOCOL in prompt
    assert "Tool calls emitted without <plan> are flagged" in prompt
    assert "BEFORE invoking ANY tool, output your thought process" in prompt


def test_protocol_off_differs_by_exactly_the_execution_protocol_section():
    on, off = _prompt(plan_protocol=True), _prompt(plan_protocol=False)

    # Removing the section from the protocol-on prompt gives the off prompt,
    # byte for byte; nothing else in the prompt depends on the switch.
    assert on.replace(prompt_builder._EXECUTION_PROTOCOL, "") == off
    assert prompt_builder._EXECUTION_PROTOCOL not in off
    assert len(on) - len(off) == len(prompt_builder._EXECUTION_PROTOCOL)
    # The section starts at its header and ends where the next section begins.
    assert prompt_builder._EXECUTION_PROTOCOL.startswith(SECTION_HEADER)
    assert prompt_builder._EXECUTION_PROTOCOL.endswith("\n\n")
    assert on.index(SECTION_HEADER) + len(prompt_builder._EXECUTION_PROTOCOL) == on.index(NEXT_SECTION)


def test_protocol_off_carries_no_sentence_that_requires_a_plan_before_tool_calls():
    off = _prompt(plan_protocol=False)

    for demand in (
        SECTION_HEADER,
        "Tool calls emitted without <plan> are flagged",
        "BEFORE invoking ANY tool",
        "MUST come FIRST in your response",
        "output AT MINIMUM: <plan>",
        "NO WAITING RULE",
        "Self-Correction Protocol",
        "PLAN_MISSING",
        "Anti-Drift Anchor",
        "Never respond with the plan by itself",
    ):
        assert demand not in off, demand
    # The one remaining mention of a <plan> tag is the language rule's MAY.
    mentions = [line for line in off.splitlines() if "<plan>" in line]
    assert mentions == [
        "2. Your internal <plan> tags MAY use English for technical precision, "
        "regardless of the user's language."
    ]
    # The rest of the prompt is intact: the sections around the removed one.
    assert "=== NEGATIVE CONSTRAINTS" in off and "=== Workflow Guides ===" in off
    assert "Limits      : effort=medium" in off


def test_protocol_off_prompt_is_stable_for_equal_inputs():
    assert _prompt(plan_protocol=False) == _prompt(plan_protocol=False)


def test_the_turn_context_block_asks_load_relevant_skills_for_a_plan_free_warning_only_when_off():
    seen = []

    def skills(query, *, top_k, **kwargs):
        seen.append(kwargs)
        return "## skill", "<conflict_warning>x</conflict_warning>"

    base = {
        "knowledge_query": "heap",
        "search_knowledge": lambda _q, *, limit: [],
        "format_knowledge_for_prompt": lambda _rows: "",
        "load_relevant_skills": skills,
        "skill_scanner": _Scanner(),
    }
    prompt_builder.build_turn_context_block(**base)
    prompt_builder.build_turn_context_block(**base, plan_protocol=False)

    # A protocol-on call is exactly the call it always was.
    assert seen == [{}, {"plan_protocol": False}]


# ── the other texts that ask for a <plan> ────────────────────────────

# The wording before the switch existed: the protocol-on text must not move.
_OLD_CONFLICT_PLAN_LINE = "MANDATORY Meta-Reasoning required in your <plan> block before proceeding:\n"
_OLD_CONFLICT_SELECT_LINE = "  → SELECT the best-matching one and STATE your choice in <plan><why>.\n"


def _conflict_warning(**kwargs) -> str:
    from core import gsa

    blocks = [
        (0.9, "Stack Pivot", "## Stack Pivot\nbody"),
        (0.8, "Stack Pivot Case 2", "## Stack Pivot Case 2\nbody"),
    ]
    return gsa._detect_conflicts(blocks, **kwargs)


def test_the_gsa_conflict_warning_is_unchanged_with_the_protocol_on():
    warning = _conflict_warning()

    assert _OLD_CONFLICT_PLAN_LINE in warning
    assert _OLD_CONFLICT_SELECT_LINE in warning
    assert warning == _conflict_warning(plan_protocol=True)


def test_the_gsa_conflict_warning_does_not_ask_for_a_plan_with_the_protocol_off():
    warning = _conflict_warning(plan_protocol=False)

    assert "<plan>" not in warning
    assert "MANDATORY Meta-Reasoning required before proceeding:" in warning
    assert "STATE your choice." in warning
    # Same warning otherwise: only the two plan clauses moved.
    assert warning.replace("required before", "required in your <plan> block before").replace(
        "STATE your choice.", "STATE your choice in <plan><why>."
    ) == _conflict_warning()


def test_load_relevant_skills_threads_the_switch_to_the_warning(tmp_path, monkeypatch):
    from core import gsa

    path = tmp_path / "global_skills.md"
    path.write_text(
        "# Pwn\n\n"
        "## Stack Pivot\n<!-- meta: hits=3 last_used=2026-10-01 confidence=0.90 -->\npivot the stack with a leave ret gadget\n\n"
        "## Stack Pivot Case 2\n<!-- meta: hits=2 last_used=2026-10-01 confidence=0.90 -->\npivot the stack with a leave ret gadget again\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gsa, "GLOBAL_SKILLS_PATH", path)

    _skills, on_warning = gsa.load_relevant_skills("stack pivot gadget", top_k=3)
    _skills, off_warning = gsa.load_relevant_skills("stack pivot gadget", top_k=3, plan_protocol=False)

    assert "<plan>" in on_warning
    assert off_warning and "<plan>" not in off_warning


def test_loop_notices_are_unchanged_with_the_protocol_on_and_plan_free_when_off():
    assert build_anti_loop_message(3).endswith("Explain the new approach in <plan> before continuing.")
    assert build_anti_code_loop_message(3).endswith("Explain the new approach in <plan> before continuing.")
    assert build_anti_loop_message(3) == build_anti_loop_message(3, plan_protocol=True)

    for message in (
        build_anti_loop_message(3, plan_protocol=False),
        build_anti_code_loop_message(3, plan_protocol=False),
    ):
        assert "<plan>" not in message
        assert message.endswith("Briefly state the new approach, then continue with the next tool call.")
        # Still a framework message: it must not be counted as a user turn.
        assert message.startswith("[System]")


def test_the_result_processor_hands_its_setting_to_the_loop_notices():
    from core.tool_result import ToolResultProcessor

    def processor(**kwargs):
        return ToolResultProcessor(auto_intuitive_search=lambda _q: "", **kwargs)

    on, off = processor(), processor(plan_protocol=False)
    for p in (on, off):
        p._repeat_error_count = p.repeat_error_threshold

    assert "<plan>" in on.maybe_anti_loop_injection(1).injection
    assert "<plan>" not in off.maybe_anti_loop_injection(1).injection


# ── /planguard says when its mode cannot apply ───────────────────────


def _planguard(arg: str, session) -> None:
    from core.commands import CommandContext, system as system_cmds

    asyncio.run(
        system_cmds.cmd_planguard(CommandContext(verb="/planguard", arg=arg, arg2="", session=session))
    )


def test_planguard_status_names_the_precedence_when_the_protocol_is_off(capsys):
    _planguard("status", _Session("quiet-chat", recorded=False))

    out = capsys.readouterr().out
    assert "Current: plan_guard_mode=" in out
    assert "not enforced: the plan protocol is off for quiet-chat" in out
    assert "/provider plan" in out


def test_planguard_confirmation_carries_the_same_note(monkeypatch, capsys):
    from config import DYNAMIC_CONFIG

    monkeypatch.setitem(DYNAMIC_CONFIG, "plan_guard_mode", "advisory")

    _planguard("strict", _Session("quiet-chat", recorded=False))

    out = capsys.readouterr().out
    assert "plan_guard_mode=strict (was advisory)" in out
    assert "not enforced" in out


def test_planguard_output_is_unchanged_when_the_protocol_is_on_or_there_is_no_session(capsys):
    _planguard("status", _Session("relay-chat", recorded=True))
    _planguard("status", None)

    assert "not enforced" not in capsys.readouterr().out
