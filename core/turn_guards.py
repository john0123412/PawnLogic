"""Pure guard decisions for the run_turn loop.

Each guard computes a decision from the current turn state and returns a
dataclass describing what should happen. The guards perform no side effects:
they never print, append to message history, write logs, switch models, or
sleep. ``run_turn`` owns those side effects and simply applies the returned
decision. This keeps the control-flow judgments testable in isolation.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Sequence
from dataclasses import dataclass

# ── Urgent mode ──────────────────────────────────────────────────────


@dataclass(slots=True)
class UrgentModeDecision:
    """Whether to activate URGENT_MODE and which fast model to switch to.

    ``activate`` is True only on the transition into urgent mode. ``target_model``
    is the fast model to switch to, or ``None`` when no suitable peer was found
    (in which case the caller still activates urgent mode but keeps the model).
    """

    activate: bool
    target_model: str | None = None


def decide_urgent_mode(
    *,
    remaining: float,
    already_urgent: bool,
    threshold: float,
    model_alias: str,
    is_fast_model: Callable[[str], bool],
    find_fast_peer: Callable[[str], str | None],
    candidates: Sequence[str],
    available_models: Container[str],
    validate_api_key: Callable[[str], tuple[bool, str]],
) -> UrgentModeDecision:
    """Decide whether the time budget warrants switching to a fast model."""
    if already_urgent or remaining >= threshold:
        return UrgentModeDecision(activate=False)

    target: str | None = None
    if not is_fast_model(model_alias):
        target = find_fast_peer(model_alias)
    if target is None:
        for alias in candidates:
            if alias in available_models and alias != model_alias:
                ok, _ = validate_api_key(alias)
                if ok:
                    target = alias
                    break
    return UrgentModeDecision(activate=True, target_model=target)


# ── Empty-response retry ─────────────────────────────────────────────


@dataclass(slots=True)
class EmptyResponseDecision:
    """Next action when a streamed response carried no usable content.

    ``action`` is ``"retry"`` (wait ``wait_seconds`` then re-call the API) or
    ``"giveup"`` (retries exhausted; inject a recovery hint and move on).
    """

    action: str
    wait_seconds: int = 0


def is_empty_response(text_buf: str, tc_buf: dict) -> bool:
    """Return whether a response carried neither text nor tool calls.

    Usage-only and hidden reasoning-only deltas are not user-visible answers,
    even when the provider reports completion tokens.
    """
    return not text_buf.strip() and not tc_buf


def decide_empty_response_retry(
    *,
    api_retry: int,
    max_retries: int,
) -> EmptyResponseDecision:
    """Decide whether to retry after an empty response.

    ``api_retry`` is the post-increment attempt count. Exponential backoff is
    capped at 8 seconds, matching the original inline behaviour.
    """
    if api_retry >= max_retries:
        return EmptyResponseDecision(action="giveup")
    return EmptyResponseDecision(action="retry", wait_seconds=min(2**api_retry, 8))


# ── CoT plan guard ───────────────────────────────────────────────────


@dataclass(slots=True)
class PlanGuardDecision:
    """Coaching-mode decision for a missing required ``<plan>``.

    ``plan_rejected`` is the updated consecutive-miss count to carry forward.
    ``action`` is ``"ok"`` (compliant), ``"soft"`` (intercept; tools still run
    and a correction signal is injected after results), or ``"hard"`` (stop the
    task after soft intercepts are exhausted).
    """

    plan_rejected: int
    action: str


def decide_plan_guard(
    *,
    missing_required_plan: bool,
    plan_rejected: int,
    max_soft: int,
) -> PlanGuardDecision:
    """Advance the plan-guard state machine for one model response."""
    new_count = plan_rejected + 1 if missing_required_plan else 0
    if new_count > max_soft:
        return PlanGuardDecision(plan_rejected=new_count, action="hard")
    if new_count > 0:
        return PlanGuardDecision(plan_rejected=new_count, action="soft")
    return PlanGuardDecision(plan_rejected=new_count, action="ok")


# ── Concurrent tool truncation ───────────────────────────────────────


@dataclass(slots=True)
class ConcurrencyDecision:
    """Whether to truncate a batch of concurrent tool calls.

    ``kept_keys`` is the ordered subset to keep when ``truncated`` is True.
    """

    truncated: bool
    kept_keys: list
    original_count: int


def decide_concurrency_truncation(
    tc_keys: Iterable,
    max_concurrent: int,
) -> ConcurrencyDecision:
    """Cap the number of tool calls executed in one turn."""
    ordered = sorted(tc_keys)
    if len(ordered) <= max_concurrent:
        return ConcurrencyDecision(
            truncated=False, kept_keys=ordered, original_count=len(ordered)
        )
    return ConcurrencyDecision(
        truncated=True,
        kept_keys=ordered[:max_concurrent],
        original_count=len(ordered),
    )


__all__ = [
    "ConcurrencyDecision",
    "EmptyResponseDecision",
    "PlanGuardDecision",
    "UrgentModeDecision",
    "decide_concurrency_truncation",
    "decide_empty_response_retry",
    "decide_plan_guard",
    "decide_urgent_mode",
    "is_empty_response",
]
