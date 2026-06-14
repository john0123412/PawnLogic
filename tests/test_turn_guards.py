"""Tests for pure run_turn guard decisions."""

from core.turn_guards import (
    ConcurrencyDecision,
    EmptyResponseDecision,
    PlanGuardDecision,
    UrgentModeDecision,
    decide_concurrency_truncation,
    decide_empty_response_retry,
    decide_plan_guard,
    decide_urgent_mode,
    is_empty_response,
)

# ── decide_urgent_mode ───────────────────────────────────────────────


def _urgent(**overrides):
    params = dict(
        remaining=10.0,
        already_urgent=False,
        threshold=30,
        model_alias="slow",
        is_fast_model=lambda a: False,
        find_fast_peer=lambda a: None,
        candidates=[],
        available_models={"slow", "fast1", "fast2"},
        validate_api_key=lambda a: (True, ""),
    )
    params.update(overrides)
    return decide_urgent_mode(**params)


def test_urgent_not_activated_when_already_urgent():
    assert _urgent(already_urgent=True).activate is False


def test_urgent_not_activated_above_threshold():
    assert _urgent(remaining=45.0).activate is False


def test_urgent_prefers_fast_peer_for_slow_model():
    decision = _urgent(
        model_alias="slow",
        is_fast_model=lambda a: False,
        find_fast_peer=lambda a: "peer-fast",
    )
    assert decision.activate is True
    assert decision.target_model == "peer-fast"


def test_urgent_falls_back_to_candidates_when_no_peer():
    decision = _urgent(
        find_fast_peer=lambda a: None,
        candidates=["missing", "fast2"],
    )
    assert decision.activate is True
    assert decision.target_model == "fast2"


def test_urgent_candidate_search_skips_current_and_unkeyed():
    decision = _urgent(
        model_alias="fast1",
        is_fast_model=lambda a: True,  # peer lookup skipped; candidates still searched
        candidates=["fast1", "fast2"],
        validate_api_key=lambda a: (a == "fast2", ""),
    )
    assert decision.activate is True
    assert decision.target_model == "fast2"


def test_urgent_activates_without_target_when_none_valid():
    decision = _urgent(
        is_fast_model=lambda a: True,
        candidates=["fast2"],
        validate_api_key=lambda a: (False, "NO_KEY"),
    )
    assert decision.activate is True
    assert decision.target_model is None


# ── is_empty_response ────────────────────────────────────────────────


def test_empty_response_true_when_no_text_and_no_tools():
    assert is_empty_response("   ", {}) is True


def test_empty_response_false_with_text():
    assert is_empty_response("hello", {}) is False


def test_empty_response_false_with_tool_calls():
    assert is_empty_response("", {0: {"id": "x"}}) is False


# ── decide_empty_response_retry ──────────────────────────────────────


def test_retry_backoff_is_exponential_and_capped():
    assert decide_empty_response_retry(api_retry=1, max_retries=3).wait_seconds == 2
    assert decide_empty_response_retry(api_retry=2, max_retries=5).wait_seconds == 4
    assert decide_empty_response_retry(api_retry=3, max_retries=5).wait_seconds == 8
    assert decide_empty_response_retry(api_retry=4, max_retries=5).wait_seconds == 8


def test_retry_action_is_retry_below_max():
    decision = decide_empty_response_retry(api_retry=1, max_retries=3)
    assert decision.action == "retry"


def test_retry_gives_up_at_max():
    decision = decide_empty_response_retry(api_retry=3, max_retries=3)
    assert decision.action == "giveup"
    assert decision.wait_seconds == 0


# ── decide_plan_guard ────────────────────────────────────────────────


def test_plan_guard_resets_when_compliant():
    decision = decide_plan_guard(
        missing_required_plan=False, plan_rejected=2, max_soft=2
    )
    assert decision == PlanGuardDecision(plan_rejected=0, action="ok")


def test_plan_guard_first_miss_is_soft():
    decision = decide_plan_guard(
        missing_required_plan=True, plan_rejected=0, max_soft=2
    )
    assert decision.plan_rejected == 1
    assert decision.action == "soft"


def test_plan_guard_stays_soft_up_to_threshold():
    decision = decide_plan_guard(
        missing_required_plan=True, plan_rejected=1, max_soft=2
    )
    assert decision.plan_rejected == 2
    assert decision.action == "soft"


def test_plan_guard_hard_kills_past_threshold():
    decision = decide_plan_guard(
        missing_required_plan=True, plan_rejected=2, max_soft=2
    )
    assert decision.plan_rejected == 3
    assert decision.action == "hard"


# ── decide_concurrency_truncation ────────────────────────────────────


def test_concurrency_no_truncation_within_limit():
    decision = decide_concurrency_truncation([0, 1, 2], 3)
    assert decision == ConcurrencyDecision(
        truncated=False, kept_keys=[0, 1, 2], original_count=3
    )


def test_concurrency_truncates_to_first_n_sorted():
    decision = decide_concurrency_truncation([3, 1, 0, 2], 2)
    assert decision.truncated is True
    assert decision.kept_keys == [0, 1]
    assert decision.original_count == 4


def test_concurrency_handles_unsorted_keys():
    decision = decide_concurrency_truncation([2, 0, 1], 5)
    assert decision.kept_keys == [0, 1, 2]
    assert decision.truncated is False


def test_decision_dataclass_shapes():
    assert UrgentModeDecision(activate=False).target_model is None
    assert EmptyResponseDecision(action="retry").wait_seconds == 0
