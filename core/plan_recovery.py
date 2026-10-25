"""Plan-only recovery: change the request, and leave no wreckage behind.

A reply that is only a complete ``<plan>`` is neither an action nor an answer.
Re-sending the identical request plus a sterner user message is the cheapest
recovery and the one that fails: a model that answered a request with a plan
tends to answer the same request with the same plan (in the incident behind this
module recovery worked once in nine tries).  So recovery changes the *request*::

    reply 1 was plan-only -> next request: tool_choice="required"
    reply 2 was plan-only -> next request: tool_choice="none", ask for an answer
    reply 3 was plan-only -> the turn stops
    any other reply       -> tool_choice="auto" again

A provider may not implement a ``tool_choice`` value.  Such a provider rejects
the request (HTTP 400/422) before streaming anything; the request is then sent
once more with ``auto`` and the value is remembered as unsupported for that
model alias, so a session never pays the rejected round trip twice.  A provider
that accepts the value but does not honour it produces another plan-only reply,
which the ladder above already bounds, or an empty one, which the session
retries as ``auto`` -- resending the identical request is the retry that fails
again.

When a turn fails after recovery began -- the limit is reached, the provider
errors, the user interrupts -- the plan-only replies and recovery nudges that
turn collected are removed from the history.  Left in place they are the worst
possible few-shot examples: the next turn's request would show the model its own
plan-only replies as the established pattern of this conversation.  Executed
tool batches are never touched; their side effects happened.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, MutableSequence
from dataclasses import dataclass
from typing import Any

from core.api_errors import http_status_from_error
from core.plan_guard import PLAN_ONLY_NO_TOOLS_SIGNAL, PLAN_ONLY_RECOVERY_SIGNAL

TOOL_CHOICE_AUTO = "auto"
TOOL_CHOICE_REQUIRED = "required"
TOOL_CHOICE_NONE = "none"

#: Statuses with which a provider refuses a parameter value it does not
#: implement.  Anything else (auth, rate limit, 5xx) is not about tool_choice.
REJECTED_PARAMETER_STATUSES = frozenset({400, 422})


@dataclass(frozen=True)
class RecoveryStep:
    """What the request that follows one plan-only reply looks like."""

    tool_choice: str
    signal: str
    notice: str


#: One step per tolerated plan-only reply; ``core.plan_guard.MAX_PLAN_ONLY_RECOVERIES``
#: must equal ``len(RECOVERY_STEPS)`` (``tests/test_plan_recovery.py`` pins it).
RECOVERY_STEPS: tuple[RecoveryStep, ...] = (
    RecoveryStep(
        TOOL_CHOICE_REQUIRED,
        PLAN_ONLY_RECOVERY_SIGNAL,
        "A plan without an action was saved; the next attempt requires a tool call",
    ),
    RecoveryStep(
        TOOL_CHOICE_NONE,
        PLAN_ONLY_NO_TOOLS_SIGNAL,
        "Still no action; the next attempt asks for a direct answer or a "
        "clarifying question, without tools",
    ),
)


def recovery_step(recovery_count: int) -> RecoveryStep:
    """Return the step for the ``recovery_count``-th consecutive plan-only reply."""
    index = min(max(recovery_count, 1), len(RECOVERY_STEPS)) - 1
    return RECOVERY_STEPS[index]


def tool_choice_for_recovery(recoveries: int) -> str:
    """Return the ``tool_choice`` for the request after ``recoveries`` plan-only replies."""
    if recoveries <= 0:
        return TOOL_CHOICE_AUTO
    return recovery_step(recoveries).tool_choice


class ToolChoiceMemory:
    """Remember which ``tool_choice`` values a provider rejected, per model alias."""

    def __init__(self) -> None:
        self._rejected: dict[str, set[str]] = {}

    def effective(self, model_alias: str, wanted: str) -> str:
        """Return ``wanted``, or ``auto`` if this alias already rejected it."""
        if wanted in self._rejected.get(model_alias, ()):
            return TOOL_CHOICE_AUTO
        return wanted

    def reject(self, model_alias: str, value: str) -> None:
        if value != TOOL_CHOICE_AUTO:
            self._rejected.setdefault(model_alias, set()).add(value)

    def rejected(self, model_alias: str) -> frozenset[str]:
        return frozenset(self._rejected.get(model_alias, ()))


def _with_fallback(
    open_stream: Callable[[str], Iterable[dict[str, Any]]],
    tool_choice: str,
    on_rejected: Callable[[str], None],
) -> Iterator[dict[str, Any]]:
    """Yield a provider stream; retry once with ``auto`` if ``tool_choice`` is refused.

    A refusal is an HTTP 400/422 error delta that arrives before any content, so
    nothing has been shown and nothing is repeated.  The refused request carries
    no usage, so the retry cannot double-count it, and it is not a retryable
    status, so the transport's own retry policy never saw it.  The retry is a
    single further request: if ``auto`` is refused too, that error is reported
    as an ordinary provider error.

    The value is reported as unsupported (``on_rejected``) only once the retry
    is flowing.  A 400 for another reason -- an oversized request, say -- fails
    the ``auto`` retry as well, and blaming ``tool_choice`` for it would
    silently switch the escalation off for the rest of the session.
    """
    streamed = False
    for delta in open_stream(tool_choice):
        refused = (
            tool_choice != TOOL_CHOICE_AUTO
            and not streamed
            and http_status_from_error(str(delta.get("_error", "")))
            in REJECTED_PARAMETER_STATUSES
        )
        if refused:
            judged = False
            for retry_delta in open_stream(TOOL_CHOICE_AUTO):
                if not judged and "_retry" not in retry_delta:
                    judged = True
                    if "_error" not in retry_delta:
                        on_rejected(tool_choice)
                yield retry_delta
            return
        if "_retry" not in delta and "_error" not in delta:
            streamed = True
        yield delta


def stream_with_tool_choice(
    stream_request: Callable[..., Iterable[dict[str, Any]]],
    messages: list[dict[str, Any]],
    model_alias: str,
    tool_choice: str,
    memory: ToolChoiceMemory,
    *,
    on_rejected: Callable[[str], None] | None = None,
    **request_kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """Open a provider stream that asks for ``tool_choice`` where the provider allows it.

    ``auto`` is never passed to ``stream_request`` -- it is that function's own
    default -- so an ordinary request is exactly the request that was sent
    before recovery existed.  A request without tools is always ``auto``: there
    is nothing to choose, and a rejection could not be about ``tool_choice``.
    """
    wanted = TOOL_CHOICE_AUTO
    if request_kwargs.get("tools_schema"):
        wanted = memory.effective(model_alias, tool_choice)

    def open_stream(choice: str) -> Iterable[dict[str, Any]]:
        extra: dict[str, Any] = {} if choice == TOOL_CHOICE_AUTO else {"tool_choice": choice}
        return stream_request(messages, model_alias, **request_kwargs, **extra)

    def rejected(choice: str) -> None:
        memory.reject(model_alias, choice)
        if on_rejected is not None:
            on_rejected(choice)

    return _with_fallback(open_stream, wanted, rejected)


def memory_for(session: Any) -> ToolChoiceMemory:
    """Return ``session``'s record of refused values, creating it on first use.

    Created lazily because a session restored from a snapshot, or built without
    ``__init__``, has no attribute yet.
    """
    memory = getattr(session, "_tool_choice_memory_store", None)
    if memory is None:
        memory = ToolChoiceMemory()
        session._tool_choice_memory_store = memory
    return memory


def purge_messages(
    messages: MutableSequence[dict[str, Any]],
    artifacts: Iterable[dict[str, Any]],
) -> int:
    """Remove ``artifacts`` (matched by identity) from ``messages``; return the count.

    Identity, not content: two turns can carry byte-identical plan-only replies
    and only this turn's may go.  Removing a plan-only assistant reply or a
    recovery nudge cannot orphan a tool-call/tool-result pair, because neither
    carries or answers a tool call.
    """
    doomed = {id(message) for message in artifacts}
    if not doomed:
        return 0
    kept = [message for message in messages if id(message) not in doomed]
    removed = len(messages) - len(kept)
    messages[:] = kept
    return removed


def discard_turn_artifacts(session: Any) -> int:
    """Remove the plan-only replies and nudges of a turn that did not succeed.

    ``session._turn_plan_artifacts`` is the turn's ledger (``TurnState`` owns
    it; ``AgentSession._run_turn_active`` exposes it).  It is cleared so a later
    turn that fails before it has a ledger of its own cannot discard this one's
    messages a second time.
    """
    removed = purge_messages(session.messages, getattr(session, "_turn_plan_artifacts", ()))
    session._turn_plan_artifacts = ()
    return removed


__all__ = [
    "RECOVERY_STEPS",
    "REJECTED_PARAMETER_STATUSES",
    "TOOL_CHOICE_AUTO",
    "TOOL_CHOICE_NONE",
    "TOOL_CHOICE_REQUIRED",
    "RecoveryStep",
    "ToolChoiceMemory",
    "discard_turn_artifacts",
    "memory_for",
    "purge_messages",
    "recovery_step",
    "stream_with_tool_choice",
    "tool_choice_for_recovery",
]
