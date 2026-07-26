"""Behavioral baselines for the 0.2.3 delegation runtime.

These tests deliberately patch model availability and the sub-agent session so
that they describe routing and observable tool behavior without contacting a
real provider or executing a real delegated task.
"""

import pytest

import tools.delegate_tool as delegate_tool


@pytest.fixture(autouse=True)
def isolated_runtime_home(tmp_path, monkeypatch):
    """Keep any runtime path resolution made by a test inside pytest storage."""
    monkeypatch.setenv("PAWNLOGIC_HOME", str(tmp_path / ".pawnlogic"))


def _patch_selection(monkeypatch, models, *, preferred="auto", valid=()):
    """Patch provider state used by the pure worker-selection decision."""
    monkeypatch.setattr(delegate_tool, "MODELS", models)
    monkeypatch.setattr(
        delegate_tool,
        "get_dynamic_config_value",
        lambda key, default=None: preferred if key == "preferred_worker" else default,
    )
    monkeypatch.setattr(
        delegate_tool,
        "validate_api_key",
        lambda alias: (alias in set(valid), "" if alias in set(valid) else "MISSING"),
    )


def test_preferred_worker_has_priority_over_current_model(monkeypatch):
    _patch_selection(
        monkeypatch,
        {"preferred-worker": {}, "current-fast": {}},
        preferred="preferred-worker",
        valid={"preferred-worker"},
    )
    monkeypatch.setattr(delegate_tool, "is_fast_model", lambda alias: alias == "current-fast")

    assert delegate_tool._select_worker_model("current-fast") == "preferred-worker"


def test_invalid_preferred_worker_falls_back_to_valid_current_fast_model(monkeypatch):
    _patch_selection(
        monkeypatch,
        {"current-fast": {}},
        preferred="missing-key-worker",
        valid={"current-fast"},
    )
    monkeypatch.setattr(delegate_tool, "is_fast_model", lambda alias: alias == "current-fast")
    monkeypatch.setattr(
        delegate_tool,
        "find_fast_peer",
        lambda _alias: pytest.fail("fast current model should not search for a peer"),
    )

    assert delegate_tool._select_worker_model("current-fast") == "current-fast"


def test_pro_model_prefers_a_valid_fast_peer_in_the_same_provider(monkeypatch):
    _patch_selection(monkeypatch, {"current-pro": {}, "same-provider-fast": {}})
    monkeypatch.setattr(delegate_tool, "is_fast_model", lambda _alias: False)
    monkeypatch.setattr(
        delegate_tool,
        "find_fast_peer",
        lambda alias: "same-provider-fast" if alias == "current-pro" else None,
    )

    assert delegate_tool._select_worker_model("current-pro") == "same-provider-fast"


def test_missing_peer_uses_first_configured_cross_provider_candidate(monkeypatch):
    _patch_selection(
        monkeypatch,
        {"current-pro": {}, "claude-haiku": {}, "gpt-4.1": {}},
        valid={"gpt-4.1"},
    )
    monkeypatch.setattr(delegate_tool, "is_fast_model", lambda _alias: False)
    monkeypatch.setattr(delegate_tool, "find_fast_peer", lambda _alias: None)

    assert delegate_tool._select_worker_model("current-pro") == "gpt-4.1"


def test_no_available_worker_falls_back_to_default_model(monkeypatch):
    _patch_selection(monkeypatch, {"current-pro": {}})
    monkeypatch.setattr(delegate_tool, "is_fast_model", lambda _alias: False)
    monkeypatch.setattr(delegate_tool, "find_fast_peer", lambda _alias: None)

    assert delegate_tool._select_worker_model("current-pro") == delegate_tool.DEFAULT_MODEL


def test_capability_profiles_preserve_current_tool_boundary():
    all_tools = {"read_file", "write_file", "run_shell", "delegate_task"}
    capabilities = {
        "write_file": {"mutating"},
        "run_shell": {"shell"},
    }

    assert delegate_tool.resolve_allowed_tools("inherited", all_tools) == {
        "read_file",
        "write_file",
        "run_shell",
    }
    assert delegate_tool.resolve_allowed_tools(
        "read_only", all_tools, capabilities_by_name=capabilities
    ) == {"read_file"}
    assert delegate_tool.resolve_allowed_tools(
        "no_shell", all_tools, capabilities_by_name=capabilities
    ) == {"read_file", "write_file"}
    assert delegate_tool.resolve_allowed_tools(
        "custom",
        all_tools,
        allowlist=["read_file", "run_shell", "delegate_task"],
        capabilities_by_name=capabilities,
    ) == {"read_file", "run_shell"}


def test_delegate_schema_keeps_current_input_boundary():
    parameters = delegate_tool.DELEGATE_SCHEMA["function"]["parameters"]
    properties = parameters["properties"]

    assert parameters["required"] == ["task_description"]
    assert "model_alias" not in properties
    assert properties["capability"]["enum"] == ["inherited", "read_only", "no_shell"]
    assert properties["verbose"]["type"] == "boolean"


def test_empty_task_is_rejected_before_worker_creation(monkeypatch):
    monkeypatch.setattr(
        delegate_tool,
        "_select_worker_model",
        lambda _alias: pytest.fail("empty task must not select a worker"),
    )

    assert delegate_tool.tool_delegate_task({"task_description": "  "}) == (
        "ERROR: task_description is required"
    )


def test_verbose_result_exposes_tool_log_and_final_result(monkeypatch):
    monkeypatch.setattr(delegate_tool, "_select_worker_model", lambda _alias: "fake-worker")
    monkeypatch.setattr(delegate_tool, "get_dynamic_config_value", lambda *_args: "auto")
    monkeypatch.setattr(delegate_tool, "_user_mode", lambda: False)

    observed = {}

    class FakeSubAgent:
        MAX_ITER = 15
        _tool_log = ("  [1] read_file(['path'])",)

        def __init__(self, task, model_alias, capability="inherited", allowlist=None):
            observed.update(
                task=task,
                model_alias=model_alias,
                capability=capability,
                allowlist=allowlist,
            )

        def run(self):
            return "fake final result"

    monkeypatch.setattr(delegate_tool, "_SubAgentSession", FakeSubAgent)

    result = delegate_tool.tool_delegate_task(
        {
            "task_description": "summarize a local file",
            "capability": "read_only",
            "allowlist": ["read_file"],
            "verbose": True,
        }
    )

    assert observed == {
        "task": "summarize a local file",
        "model_alias": "fake-worker",
        "capability": "read_only",
        "allowlist": ["read_file"],
    }
    assert "read_file(['path'])" in result
    assert "fake final result" in result
