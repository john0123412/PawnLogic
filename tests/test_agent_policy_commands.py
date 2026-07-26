"""Offline command tests for delegated-agent model policy controls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from core.commands import CommandContext


@dataclass(frozen=True)
class FakePolicy:
    allowed_models: tuple[str, ...] = ()
    denied_models: tuple[str, ...] = ()
    default_mode: str = "auto"
    preferred_model: str | None = None
    max_cost: float | None = None
    max_concurrency: int = 1


class FakePolicyStore:
    def __init__(self, policy: FakePolicy | None = None) -> None:
        self.policy = policy or FakePolicy()
        self.saved: list[FakePolicy] = []

    def load(self) -> FakePolicy:
        return self.policy

    def save(self, policy: FakePolicy) -> None:
        self.policy = policy
        self.saved.append(policy)


class FakeSession:
    def __init__(self) -> None:
        self.reset_calls = 0

    def _reset_system_prompt(self) -> None:
        self.reset_calls += 1


@pytest.fixture(scope="module")
def isolated_tools_commands():
    """Load tools commands through a local decorator without changing COMMANDS."""
    commands = importlib.import_module("core.commands")
    registry_before = dict(commands.COMMANDS)
    captured: dict[str, object] = {}

    def fake_register(*verbs: str):
        def decorator(handler):
            for verb in verbs:
                captured[verb] = handler
            return handler

        return decorator

    original_register = commands.register
    previous_module = sys.modules.pop("core.commands.tools", None)
    commands.register = fake_register
    try:
        module = importlib.import_module("core.commands.tools")
    finally:
        commands.register = original_register
        sys.modules.pop("core.commands.tools", None)
        if previous_module is not None:
            sys.modules["core.commands.tools"] = previous_module

    assert registry_before == commands.COMMANDS
    return SimpleNamespace(
        module=module,
        agent=captured["/agent"],
        worker=captured["/worker"],
    )


@pytest.fixture
def command_env(isolated_tools_commands, monkeypatch):
    module = isolated_tools_commands.module
    output: list[str] = []
    runtime_config = {"preferred_worker": "auto"}
    store = FakePolicyStore()

    monkeypatch.setattr(module, "_print", lambda text="": output.append(str(text)))
    monkeypatch.setattr(module, "_delegation_policy_store", lambda: store)
    monkeypatch.setattr(
        module,
        "get_dynamic_config_value",
        lambda key, default=None: runtime_config.get(key, default),
    )
    monkeypatch.setattr(
        module,
        "set_dynamic_config_value",
        lambda key, value: runtime_config.__setitem__(key, value),
    )
    monkeypatch.setattr(
        module,
        "MODELS",
        {
            "fast-visible": {"desc": "Fast visible model"},
            "reasoning-visible": {"desc": "Reasoning visible model"},
            "known-hidden": {"desc": "Inactive provider model"},
        },
    )
    monkeypatch.setattr(
        module,
        "_visible_worker_models",
        lambda: {
            "fast-visible": {"desc": "Fast visible model"},
            "reasoning-visible": {"desc": "Reasoning visible model"},
        },
    )
    return SimpleNamespace(
        module=module,
        output=output,
        runtime_config=runtime_config,
        store=store,
        session=FakeSession(),
    )


def run_agent(isolated_tools_commands, env, arg: str, arg2: str) -> None:
    context = CommandContext("/agent", arg, arg2, env.session)
    asyncio.run(isolated_tools_commands.agent(context))


def run_worker(isolated_tools_commands, env, arg: str = "") -> None:
    context = CommandContext("/worker", arg, "", env.session)
    asyncio.run(isolated_tools_commands.worker(context))


def test_policy_store_uses_live_runtime_home(
    isolated_tools_commands,
    monkeypatch,
    tmp_path: Path,
):
    module = isolated_tools_commands.module
    runtime_home = tmp_path / "runtime-home"
    seen: list[Path] = []

    class CapturingStore:
        def __init__(self, home: Path) -> None:
            seen.append(home)

    fake_delegation = ModuleType("core.delegation")
    fake_delegation.DelegationPolicyStore = CapturingStore
    monkeypatch.setitem(sys.modules, "core.delegation", fake_delegation)

    import config.paths as path_config

    monkeypatch.setattr(path_config, "PAWNLOGIC_HOME", runtime_home)
    store = module._delegation_policy_store()

    assert isinstance(store, CapturingStore)
    assert seen == [runtime_home]


def test_agent_policy_and_worker_persist_under_current_runtime_home(
    isolated_tools_commands,
    monkeypatch,
    tmp_path: Path,
):
    from core.delegation import DelegationPolicyStore

    module = isolated_tools_commands.module
    runtime_home = tmp_path / "runtime-home"
    output: list[str] = []
    runtime_config = {"preferred_worker": "auto"}
    session = FakeSession()

    import config.paths as path_config

    monkeypatch.setattr(path_config, "PAWNLOGIC_HOME", runtime_home)
    monkeypatch.setattr(module, "_print", lambda text="": output.append(str(text)))
    monkeypatch.setattr(
        module,
        "MODELS",
        {"fast-visible": {"desc": "Fast visible model"}},
    )
    monkeypatch.setattr(
        module,
        "_visible_worker_models",
        lambda: {"fast-visible": {"desc": "Fast visible model"}},
    )
    monkeypatch.setattr(
        module,
        "get_dynamic_config_value",
        lambda key, default=None: runtime_config.get(key, default),
    )
    monkeypatch.setattr(
        module,
        "set_dynamic_config_value",
        lambda key, value: runtime_config.__setitem__(key, value),
    )

    run_agent(
        isolated_tools_commands,
        SimpleNamespace(session=session),
        "policy",
        "model allow fast-visible",
    )
    store = DelegationPolicyStore(runtime_home)
    assert store.load().allowed_models == ("fast-visible",)
    assert store.path.is_file()
    assert list(store.path.parent.glob("*.tmp")) == []

    run_worker(
        isolated_tools_commands,
        SimpleNamespace(session=session),
        "fast-visible",
    )
    assert store.load().preferred_model == "fast-visible"
    assert runtime_config["preferred_worker"] == "fast-visible"

    run_worker(isolated_tools_commands, SimpleNamespace(session=session), "auto")
    assert store.load().preferred_model is None
    assert runtime_config["preferred_worker"] == "auto"


def test_agent_policy_show_renders_complete_policy(
    isolated_tools_commands,
    command_env,
):
    command_env.store.policy = FakePolicy(
        allowed_models=("fast-visible", "reasoning-visible"),
        denied_models=("known-hidden",),
        default_mode="reasoning",
        preferred_model="fast-visible",
        max_cost=1.5,
        max_concurrency=2,
    )

    run_agent(isolated_tools_commands, command_env, "policy", "show")

    rendered = "\n".join(command_env.output)
    assert "default mode    : reasoning" in rendered
    assert "preferred model : fast-visible" in rendered
    assert "allowed models  : fast-visible, reasoning-visible" in rendered
    assert "denied models   : known-hidden" in rendered
    assert "max cost        : 1.5" in rendered
    assert "max concurrency : 2" in rendered
    assert command_env.store.saved == []


def test_agent_policy_allow_and_deny_use_visible_dynamic_models(
    isolated_tools_commands,
    command_env,
):
    command_env.store.policy = FakePolicy(
        denied_models=("fast-visible",),
    )

    run_agent(
        isolated_tools_commands,
        command_env,
        "policy",
        "model allow fast-visible",
    )
    assert command_env.store.policy.allowed_models == ("fast-visible",)
    assert command_env.store.policy.denied_models == ()

    run_agent(
        isolated_tools_commands,
        command_env,
        "policy",
        "model deny fast-visible",
    )
    assert command_env.store.policy.allowed_models == ()
    assert command_env.store.policy.denied_models == ("fast-visible",)


def test_agent_policy_deny_clears_matching_preferred_model(
    isolated_tools_commands,
    command_env,
):
    command_env.store.policy = FakePolicy(
        preferred_model="fast-visible",
    )

    run_agent(
        isolated_tools_commands,
        command_env,
        "policy",
        "model deny fast-visible",
    )

    assert command_env.store.policy.preferred_model is None
    assert command_env.store.policy.denied_models == ("fast-visible",)


@pytest.mark.parametrize(
    ("alias", "message"),
    [
        ("missing-alias", "Unknown model alias"),
        ("known-hidden", "unavailable in /model"),
    ],
)
def test_agent_policy_rejects_unknown_or_hidden_aliases(
    isolated_tools_commands,
    command_env,
    alias: str,
    message: str,
):
    run_agent(
        isolated_tools_commands,
        command_env,
        "policy",
        f"model allow {alias}",
    )

    assert command_env.store.saved == []
    assert message in "\n".join(command_env.output)


def test_agent_policy_updates_modes_cost_and_concurrency(
    isolated_tools_commands,
    command_env,
):
    run_agent(isolated_tools_commands, command_env, "policy", "default same")
    assert command_env.store.policy.default_mode == "same"

    run_agent(isolated_tools_commands, command_env, "policy", "max-cost 0")
    assert command_env.store.policy.max_cost == 0

    run_agent(isolated_tools_commands, command_env, "policy", "max-cost off")
    assert command_env.store.policy.max_cost is None

    run_agent(isolated_tools_commands, command_env, "policy", "max-concurrency 2")
    assert command_env.store.policy.max_concurrency == 2


@pytest.mark.parametrize(
    "arguments",
    [
        "default vision",
        "max-cost -0.01",
        "max-cost nan",
        "max-concurrency 0",
        "max-concurrency 3",
    ],
)
def test_agent_policy_invalid_values_do_not_persist(
    isolated_tools_commands,
    command_env,
    arguments: str,
):
    original = command_env.store.policy

    run_agent(isolated_tools_commands, command_env, "policy", arguments)

    assert command_env.store.policy == original
    assert command_env.store.saved == []


def test_agent_run_only_prints_delegate_task_structure(
    isolated_tools_commands,
    command_env,
    monkeypatch,
):
    monkeypatch.setattr(
        command_env.module,
        "_delegation_policy_store",
        lambda: pytest.fail("/agent run must not load policy or call a provider"),
    )

    run_agent(
        isolated_tools_commands,
        command_env,
        "run",
        "security-reviewer Review redirect handling",
    )

    rendered = "\n".join(command_env.output)
    assert "delegate_task" in rendered
    assert '"role": "security-reviewer"' in rendered
    assert '"task_description": "Review redirect handling"' in rendered
    assert "does not call a provider" in rendered


def test_worker_lists_only_live_visible_models(
    isolated_tools_commands,
    command_env,
):
    run_worker(isolated_tools_commands, command_env)

    rendered = "\n".join(command_env.output)
    assert "fast-visible" in rendered
    assert "reasoning-visible" in rendered
    assert "known-hidden" not in rendered


def test_worker_alias_and_numeric_selection_sync_preferred_policy(
    isolated_tools_commands,
    command_env,
):
    run_worker(isolated_tools_commands, command_env, "reasoning-visible")

    assert command_env.store.policy.preferred_model == "reasoning-visible"
    assert command_env.runtime_config["preferred_worker"] == "reasoning-visible"
    assert command_env.session.reset_calls == 1

    run_worker(isolated_tools_commands, command_env, "1")

    assert command_env.store.policy.preferred_model == "fast-visible"
    assert command_env.runtime_config["preferred_worker"] == "fast-visible"
    assert command_env.session.reset_calls == 2


def test_worker_auto_clears_preferred_policy(
    isolated_tools_commands,
    command_env,
):
    command_env.store.policy = replace(
        command_env.store.policy,
        preferred_model="fast-visible",
    )
    command_env.runtime_config["preferred_worker"] = "fast-visible"

    run_worker(isolated_tools_commands, command_env, "auto")

    assert command_env.store.policy.preferred_model is None
    assert command_env.runtime_config["preferred_worker"] == "auto"
    assert command_env.session.reset_calls == 1


def test_worker_rejects_known_but_hidden_model(
    isolated_tools_commands,
    command_env,
):
    run_worker(isolated_tools_commands, command_env, "known-hidden")

    assert command_env.store.saved == []
    assert command_env.runtime_config["preferred_worker"] == "auto"
    assert command_env.session.reset_calls == 0
    assert "unavailable in /model" in "\n".join(command_env.output)


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (
            FakePolicy(denied_models=("fast-visible",)),
            "denied by delegated-agent policy",
        ),
        (
            FakePolicy(allowed_models=("reasoning-visible",)),
            "not in the delegated-agent allowlist",
        ),
    ],
)
def test_worker_cannot_override_explicit_model_policy(
    isolated_tools_commands,
    command_env,
    policy,
    message,
):
    command_env.store.policy = policy

    run_worker(isolated_tools_commands, command_env, "fast-visible")

    assert command_env.store.saved == []
    assert command_env.runtime_config["preferred_worker"] == "auto"
    assert command_env.session.reset_calls == 0
    assert message in "\n".join(command_env.output)
