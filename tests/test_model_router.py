"""Contract tests for delegated model routing."""

import core.model_router as model_router
from core.delegation import AgentBudget, AgentTask, DelegationModelPolicy
from core.model_router import ModelRouter


def _task(
    *,
    model_alias=None,
    model_requirement="auto",
    max_tokens=1000,
    max_cost=None,
):
    return AgentTask(
        objective="Route this delegated task",
        model_alias=model_alias,
        model_requirement=model_requirement,
        budget=AgentBudget(max_tokens=max_tokens, max_cost=max_cost),
    )


def _policy(
    *,
    allow=(),
    deny=(),
    default_mode="auto",
    preferred_model=None,
    max_tokens=2000,
    max_cost=None,
):
    return DelegationModelPolicy(
        allowed_models=tuple(allow),
        denied_models=tuple(deny),
        default_mode=default_mode,
        preferred_model=preferred_model,
        max_tokens=max_tokens,
        max_cost=max_cost,
    )


def _router(models, *, active=("alpha", "beta"), configured=None, fast=()):
    configured_aliases = None if configured is None else set(configured)
    return ModelRouter(
        models,
        is_provider_active=lambda provider: provider in set(active),
        validate_api_key=lambda alias: (
            alias in models if configured_aliases is None else alias in configured_aliases,
            ""
            if (alias in models if configured_aliases is None else alias in configured_aliases)
            else "TEST_API_KEY",
        ),
        is_fast_model=lambda alias: alias in set(fast),
    )


def test_router_reads_mutated_model_registry_on_every_selection():
    models = {
        "parent": {"provider": "alpha"},
    }
    router = _router(models, fast={"new-fast"})

    first = router.select(_task(), "parent", _policy())
    models["new-fast"] = {"provider": "alpha"}
    second = router.select(_task(), "parent", _policy())

    assert first.model_alias == "parent"
    assert second.model_alias == "new-fast"
    assert second.reason == "same_provider_fast_peer"
    assert second.eligible_models == ("parent", "new-fast")


def test_default_router_reads_replaced_live_models(monkeypatch):
    models = {"parent": {"provider": "alpha"}}
    monkeypatch.setattr(model_router, "MODELS", models)
    router = ModelRouter(
        is_provider_active=lambda provider: provider == "alpha",
        validate_api_key=lambda alias: alias in models,
        is_fast_model=lambda alias: alias == "new-fast",
    )

    models["new-fast"] = {"provider": "alpha"}
    decision = router.select(_task(), "parent", _policy())

    assert decision.model_alias == "new-fast"
    assert decision.eligible_models == ("parent", "new-fast")


def test_explicit_model_is_rejected_instead_of_bypassing_visibility():
    models = {
        "parent": {"provider": "alpha"},
        "inactive": {"provider": "beta"},
        "unconfigured": {"provider": "alpha"},
    }
    router = _router(models, active={"alpha"}, configured={"parent"})

    inactive = router.select(
        _task(model_alias="inactive"),
        "parent",
        _policy(),
    )
    unconfigured = router.select(
        _task(model_alias="unconfigured"),
        "parent",
        _policy(),
    )

    assert inactive.model_alias is None
    assert inactive.reason == "explicit_model_rejected"
    assert "inactive" in inactive.error
    assert unconfigured.model_alias is None
    assert "not configured" in unconfigured.error
    assert "TEST_API_KEY" in unconfigured.error


def test_allowlist_narrows_models_and_denylist_wins():
    models = {
        "allowed": {"provider": "alpha"},
        "denied": {"provider": "alpha"},
        "outside": {"provider": "alpha"},
    }
    router = _router(models)
    policy = _policy(allow={"allowed", "denied"}, deny={"denied"})

    decision = router.select(_task(), "outside", policy)
    rejected = router.select(_task(model_alias="denied"), "outside", policy)

    assert decision.model_alias == "allowed"
    assert decision.eligible_models == ("allowed",)
    assert rejected.model_alias is None
    assert "denied by model policy" in rejected.error


def test_same_requirement_uses_current_model_only_when_eligible():
    models = {
        "parent": {"provider": "alpha"},
        "other": {"provider": "alpha"},
    }
    router = _router(models)

    selected = router.select(
        _task(model_requirement="same"),
        "parent",
        _policy(),
    )
    rejected = router.select(
        _task(model_requirement="same"),
        "parent",
        _policy(deny={"parent"}),
    )

    assert selected.model_alias == "parent"
    assert selected.eligible_models == ("parent",)
    assert rejected.model_alias is None
    assert rejected.reason == "no_eligible_models"


def test_fast_and_reasoning_requirements_filter_dynamic_eligible_models():
    models = {
        "parent": {"provider": "alpha"},
        "fast-peer": {"provider": "alpha"},
        "reasoner": {
            "provider": "beta",
            "capabilities": ("reasoning",),
        },
    }
    router = _router(models, fast={"fast-peer"})

    fast = router.select(
        _task(model_requirement="fast"),
        "parent",
        _policy(),
    )
    reasoning = router.select(
        _task(model_requirement="reasoning"),
        "parent",
        _policy(),
    )

    assert fast.model_alias == "fast-peer"
    assert fast.eligible_models == ("fast-peer",)
    assert reasoning.model_alias == "reasoner"
    assert reasoning.eligible_models == ("reasoner",)


def test_vision_requirement_uses_flag_or_capability_metadata():
    models = {
        "parent": {"provider": "alpha"},
        "flag-vision": {"provider": "alpha", "vision": True},
        "capability-vision": {
            "provider": "beta",
            "capabilities": ("vision",),
        },
    }
    router = _router(models)

    decision = router.select(
        _task(model_requirement="vision"),
        "parent",
        _policy(),
    )

    assert decision.model_alias == "flag-vision"
    assert decision.eligible_models == ("flag-vision", "capability-vision")


def test_policy_default_mode_and_preferred_model_apply_without_explicit_alias():
    models = {
        "parent": {"provider": "alpha"},
        "fast-a": {"provider": "alpha"},
        "fast-b": {"provider": "beta"},
    }
    router = _router(models, fast={"fast-a", "fast-b"})

    decision = router.select(
        _task(),
        "parent",
        _policy(default_mode="fast", preferred_model="fast-b"),
    )

    assert decision.model_alias == "fast-b"
    assert decision.reason == "preferred_model"
    assert decision.eligible_models == ("fast-a", "fast-b")


def test_policy_and_task_token_budgets_use_the_stricter_limit():
    task = _task(max_tokens=800)
    policy = _policy(max_tokens=500)

    assert ModelRouter.effective_max_tokens(task, policy) == 500


def test_cost_budget_filters_known_cost_and_rejects_unknown_cost():
    models = {
        "parent": {"provider": "alpha", "cost": 2.0},
        "cheap": {"provider": "alpha", "estimated_cost": 0.25},
        "unknown": {"provider": "beta"},
    }
    router = _router(models)
    task = _task(max_cost=0.75)
    policy = _policy(max_cost=0.5)

    decision = router.select(task, "parent", policy)
    rejected = router.select(
        _task(model_alias="unknown", max_cost=0.75),
        "parent",
        policy,
    )

    assert ModelRouter.effective_max_cost(task, policy) == 0.5
    assert decision.model_alias == "cheap"
    assert decision.eligible_models == ("cheap",)
    assert rejected.model_alias is None
    assert "cost cannot be estimated" in rejected.error


def test_unknown_cost_remains_eligible_without_a_cost_budget():
    models = {
        "parent": {"provider": "alpha"},
    }

    decision = _router(models).select(_task(), "parent", _policy())

    assert decision.model_alias == "parent"
    assert decision.error is None


def test_no_eligible_models_returns_an_explicit_error():
    router = _router(
        {"parent": {"provider": "alpha"}},
        configured=set(),
    )

    decision = router.select(_task(), "parent", _policy())

    assert decision.model_alias is None
    assert decision.reason == "no_eligible_models"
    assert decision.eligible_models == ()
    assert decision.error
