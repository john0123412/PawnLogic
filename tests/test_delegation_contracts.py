"""Offline contract tests for delegation value objects and policy storage."""

from __future__ import annotations

import json
import threading
from dataclasses import FrozenInstanceError

import pytest

import core.delegation as delegation
from core.agent_orchestrator import (
    BudgetExceededError,
    BudgetLedger,
    CancellationToken,
)
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
        task_id="task-auth-review",
        parent_task_id="task-parent",
        objective="Review the authentication flow",
        role="security-reviewer",
        instructions="Focus on redirect handling.",
        model_requirement="reasoning",
        model_alias="claude-sonnet",
        context_mode="selected",
        capability_profile="read_only",
        allowed_tools=["read_file", "search_text"],
        budget=AgentBudget(max_tokens=4096, max_cost=0.25, max_tool_calls=4),
        deadline=1234.5,
    )

    assert task.allowed_tools == ("read_file", "search_text")
    assert task.to_dict() == {
        "task_id": "task-auth-review",
        "parent_task_id": "task-parent",
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
        "deadline": 1234.5,
    }
    with pytest.raises(FrozenInstanceError):
        task.role = "other"


def test_agent_task_generates_unique_ids_and_result_preserves_explicit_lineage():
    first = AgentTask(objective="First task")
    second = AgentTask(objective="Second task")

    assert first.task_id
    assert second.task_id
    assert first.task_id != second.task_id
    assert first.parent_task_id is None
    assert first.deadline is None

    result = AgentResult(
        task_id=first.task_id,
        parent_task_id="root-task",
        status="completed",
        summary="Done.",
    )

    assert result.task_id == first.task_id
    assert result.parent_task_id == "root-task"
    assert result.to_dict()["task_id"] == first.task_id
    assert result.to_dict()["parent_task_id"] == "root-task"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AgentTask(objective=" "), "objective"),
        (lambda: AgentTask(objective="x", task_id=" "), "task_id"),
        (lambda: AgentTask(objective="x", parent_task_id=" "), "parent_task_id"),
        (lambda: AgentTask(objective="x", deadline=True), "deadline"),
        (lambda: AgentTask(objective="x", deadline=-1), "deadline"),
        (lambda: AgentTask(objective="x", deadline=float("inf")), "deadline"),
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
        (lambda: AgentUsage(cost=None), "cost"),
    ],
)
def test_contracts_reject_invalid_input(factory, message):
    with pytest.raises((TypeError, ValueError), match=message):
        factory()


def test_agent_result_serializes_nested_contracts():
    result = AgentResult(
        task_id="task-auth-review",
        parent_task_id="task-parent",
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
        "task_id": "task-auth-review",
        "parent_task_id": "task-parent",
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
            "cost": 0.0,
        },
    }


def test_artifact_paths_must_be_relative():
    with pytest.raises(ValueError, match="path"):
        ArtifactRef(name="report", path="/tmp/report.md")
    with pytest.raises(ValueError, match="path"):
        ArtifactRef(name="report", path="../report.md")


def test_cancellation_token_is_thread_safe_idempotent_and_cooperative():
    token = CancellationToken()
    wait_result = []

    waiter = threading.Thread(target=lambda: wait_result.append(token.wait(timeout=1.0)))
    waiter.start()

    assert token.cancel("parent stopped") is True
    waiter.join(timeout=1.0)

    assert not waiter.is_alive()
    assert wait_result == [True]
    assert token.cancelled is True
    assert token.is_cancelled() is True
    assert token.reason == "parent stopped"
    assert token.cancel("later reason") is False
    assert token.reason == "parent stopped"


def test_cancellation_token_rejects_invalid_wait_timeout_and_reason():
    token = CancellationToken()

    with pytest.raises(ValueError, match="timeout"):
        token.wait(timeout=-1)
    with pytest.raises(ValueError, match="reason"):
        token.cancel(" ")


def test_budget_claim_reservation_and_settlement_are_atomic():
    ledger = BudgetLedger(
        AgentBudget(max_tokens=10, max_tool_calls=2, max_cost=1.0)
    )
    claim = ledger.claim(tokens=6, tool_calls=1, cost=0.6)

    reserved = ledger.snapshot()
    assert reserved.reserved_tokens == 6
    assert reserved.reserved_tool_calls == 1
    assert reserved.reserved_cost == pytest.approx(0.6)
    assert reserved.available_tokens == 4
    assert reserved.available_tool_calls == 1
    assert reserved.available_cost == pytest.approx(0.4)

    assert ledger.try_claim(tokens=5, tool_calls=0, cost=0.0) is None
    assert ledger.snapshot() == reserved

    settled = claim.settle(tokens=4, tool_calls=1, cost=0.4)
    assert claim.settled is True
    assert settled.consumed_tokens == 4
    assert settled.consumed_tool_calls == 1
    assert settled.consumed_cost == pytest.approx(0.4)
    assert settled.reserved_tokens == 0
    assert settled.available_tokens == 6
    assert settled.available_cost == pytest.approx(0.6)


def test_budget_claim_rejects_oversettlement_without_mutating_ledger():
    ledger = BudgetLedger(
        AgentBudget(max_tokens=8, max_tool_calls=2, max_cost=0.5)
    )
    claim = ledger.claim(tokens=3, tool_calls=1, cost=0.2)
    before = ledger.snapshot()

    with pytest.raises(ValueError, match="reserved tokens"):
        claim.settle(tokens=4, tool_calls=1, cost=0.2)

    assert ledger.snapshot() == before
    assert claim.settled is False

    released = claim.release()
    assert claim.settled is True
    assert released.consumed_tokens == 0
    assert released.reserved_tokens == 0
    assert released.available_tokens == 8

    with pytest.raises(RuntimeError, match="already settled"):
        claim.release()


def test_budget_ledger_claim_is_all_or_nothing_across_resources():
    ledger = BudgetLedger(
        AgentBudget(max_tokens=10, max_tool_calls=1, max_cost=0.5)
    )
    tool_claim = ledger.claim(tool_calls=1)
    before = ledger.snapshot()

    assert ledger.try_claim(tokens=5, tool_calls=1, cost=0.1) is None
    assert ledger.snapshot() == before

    with pytest.raises(BudgetExceededError, match="budget"):
        ledger.claim(tokens=5, tool_calls=1, cost=0.1)

    tool_claim.release()


def test_budget_ledger_prevents_concurrent_overbooking():
    ledger = BudgetLedger(AgentBudget(max_tokens=3, max_tool_calls=0))
    barrier = threading.Barrier(8)
    claims = []
    claims_lock = threading.Lock()

    def reserve_one():
        barrier.wait()
        claim = ledger.try_claim(tokens=1)
        if claim is not None:
            with claims_lock:
                claims.append(claim)

    workers = [threading.Thread(target=reserve_one) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=1.0)

    assert all(not worker.is_alive() for worker in workers)
    assert len(claims) == 3
    assert ledger.snapshot().available_tokens == 0

    for claim in claims:
        claim.release()
    assert ledger.snapshot().available_tokens == 3


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
