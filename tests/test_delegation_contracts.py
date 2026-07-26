"""Offline contract tests for delegation value objects and policy storage."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

import core.delegation as delegation
from core.delegation import (
    AgentBudget,
    AgentResult,
    AgentTask,
    AgentUsage,
    ArtifactRef,
    DelegationModelPolicy,
    DelegationPolicyStore,
    EvidenceRef,
    FailureRecord,
)


def test_agent_task_is_frozen_normalized_and_serializable():
    task = AgentTask(
        objective="Review the authentication flow",
        role="security-reviewer",
        instructions="Focus on redirect handling.",
        model_requirement="reasoning",
        model_alias="claude-sonnet",
        context_mode="selected",
        capability_profile="read_only",
        allowed_tools=["read_file", "search_text"],
        budget=AgentBudget(max_tokens=4096, max_cost=0.25, max_tool_calls=4),
    )

    assert task.allowed_tools == ("read_file", "search_text")
    assert task.to_dict() == {
        "objective": "Review the authentication flow",
        "role": "security-reviewer",
        "instructions": "Focus on redirect handling.",
        "model_requirement": "reasoning",
        "model_alias": "claude-sonnet",
        "context_mode": "selected",
        "capability_profile": "read_only",
        "allowed_tools": ["read_file", "search_text"],
        "budget": {
            "max_tokens": 4096,
            "max_cost": 0.25,
            "max_tool_calls": 4,
        },
    }
    with pytest.raises(FrozenInstanceError):
        task.role = "other"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AgentTask(objective=" "), "objective"),
        (lambda: AgentTask(objective="x", model_alias=" "), "model_alias"),
        (lambda: AgentTask(objective="x", model_requirement="unknown"), "model_requirement"),
        (lambda: AgentTask(objective="x", context_mode="everything"), "context_mode"),
        (lambda: AgentTask(objective="x", capability_profile="root"), "capability_profile"),
        (lambda: AgentTask(objective="x", allowed_tools=("read_file", "read_file")), "allowed_tools"),
        (lambda: AgentBudget(max_tokens=True), "max_tokens"),
        (lambda: AgentBudget(max_tokens=0), "max_tokens"),
        (lambda: AgentBudget(max_cost=float("inf")), "max_cost"),
        (lambda: AgentBudget(max_tool_calls=-1), "max_tool_calls"),
        (lambda: AgentUsage(prompt_tokens=-1), "prompt_tokens"),
    ],
)
def test_contracts_reject_invalid_input(factory, message):
    with pytest.raises((TypeError, ValueError), match=message):
        factory()


def test_agent_result_serializes_nested_contracts():
    result = AgentResult(
        status="failed",
        summary="The worker could not verify the claim.",
        model_alias="worker-fast",
        routing_reason="preferred_model",
        artifacts=(
            ArtifactRef(
                name="report",
                path="reports/auth-review.md",
                media_type="text/markdown",
            ),
        ),
        evidence=(
            EvidenceRef(
                source="read_file",
                reference="reports/auth-review.md#redirects",
                description="Redirect validation notes",
            ),
        ),
        failures=(
            FailureRecord(
                code="tool_denied",
                message="Network access is not allowed.",
                retryable=False,
            ),
        ),
        usage=AgentUsage(prompt_tokens=120, completion_tokens=35, tool_calls=2),
    )

    assert result.to_dict() == {
        "status": "failed",
        "summary": "The worker could not verify the claim.",
        "model_alias": "worker-fast",
        "routing_reason": "preferred_model",
        "artifacts": [
            {
                "name": "report",
                "path": "reports/auth-review.md",
                "media_type": "text/markdown",
            }
        ],
        "evidence": [
            {
                "source": "read_file",
                "reference": "reports/auth-review.md#redirects",
                "description": "Redirect validation notes",
            }
        ],
        "failures": [
            {
                "code": "tool_denied",
                "message": "Network access is not allowed.",
                "retryable": False,
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 35,
            "tool_calls": 2,
        },
    }


def test_artifact_paths_must_be_relative():
    with pytest.raises(ValueError, match="path"):
        ArtifactRef(name="report", path="/tmp/report.md")
    with pytest.raises(ValueError, match="path"):
        ArtifactRef(name="report", path="../report.md")


def test_model_policy_defaults_and_hard_concurrency_limit():
    assert DelegationModelPolicy().to_dict() == {
        "default_mode": "auto",
        "preferred_model": None,
        "allowed_models": [],
        "denied_models": [],
        "max_cost": None,
        "max_tokens": 8192,
        "max_concurrency": 1,
    }

    with pytest.raises(ValueError, match="max_concurrency"):
        DelegationModelPolicy(max_concurrency=0)
    with pytest.raises(ValueError, match="max_concurrency"):
        DelegationModelPolicy(max_concurrency=3)


def test_policy_store_round_trip_uses_atomic_write(tmp_path, monkeypatch):
    calls = []
    real_atomic_write = delegation.atomic_write_text

    def recording_atomic_write(path, text, *, mode=None):
        calls.append((path, text, mode))
        real_atomic_write(path, text, mode=mode)

    monkeypatch.setattr(delegation, "atomic_write_text", recording_atomic_write)
    store = DelegationPolicyStore(tmp_path)
    policy = DelegationModelPolicy(
        default_mode="fast",
        preferred_model="worker-fast",
        allowed_models=["worker-fast", "worker-reasoning"],
        denied_models=["retired-worker"],
        max_cost=1.5,
        max_tokens=4096,
        max_concurrency=2,
    )

    assert store.save(policy) == policy
    assert store.path == tmp_path / "delegation" / "policy.json"
    assert store.load() == policy
    assert len(calls) == 1
    assert calls[0][0] == store.path
    assert calls[0][2] == 0o600


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        "[]",
        '{"default_mode": "unsupported"}',
        '{"max_concurrency": 99}',
    ],
)
def test_policy_store_load_safely_falls_back_for_corrupt_data(tmp_path, payload):
    store = DelegationPolicyStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(payload, encoding="utf-8")

    assert store.load() == DelegationModelPolicy()


def test_policy_store_update_returns_persisted_policy_and_rejects_secrets(tmp_path):
    store = DelegationPolicyStore(tmp_path)

    updated = store.update(
        preferred_model="worker-fast",
        allowed_models=["worker-fast"],
        max_concurrency=2,
    )

    assert updated == store.load()
    assert updated.preferred_model == "worker-fast"
    assert updated.allowed_models == ("worker-fast",)
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(persisted) == {
        "default_mode",
        "preferred_model",
        "allowed_models",
        "denied_models",
        "max_cost",
        "max_tokens",
        "max_concurrency",
    }

    with pytest.raises(ValueError, match="unknown policy field"):
        store.update(api_key="do-not-store")
    assert "do-not-store" not in store.path.read_text(encoding="utf-8")
