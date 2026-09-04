"""Queue rendering and the small interactive menu used by ``/queue``.

The scheduler remains the only owner of queue state.  This module consumes an
immutable :class:`~core.turn_scheduler.SchedulerView`, renders it, and emits a
typed menu choice.  Mutations are applied by the command layer so the TUI
cannot accidentally bypass scheduler checkpointing or active-Turn rules.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import re
from typing import Any

from core.turn_scheduler import SchedulerView, SubmissionKind


@dataclass(frozen=True, slots=True)
class QueueRow:
    """One stable queue row suitable for text or a Prompt Toolkit widget."""

    submission_id: str
    sequence: int
    kind: SubmissionKind
    status: str
    summary: str

    @property
    def short_id(self) -> str:
        """Return a compact stable identifier for the menu."""
        return self.submission_id[:12]


@dataclass(frozen=True, slots=True)
class QueueAction:
    """A menu choice returned without mutating scheduler state."""

    operation: str
    submission_id: str | None = None


@dataclass(frozen=True, slots=True)
class QueueTUIResult:
    """Rendered menu result; ``cancelled`` is explicit for every exit path."""

    output: str
    action: QueueAction | None = None
    cancelled: bool = False


def _summary(content: str, limit: int = 64) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"


def queue_rows(view: SchedulerView) -> tuple[QueueRow, ...]:
    """Build rows from one immutable scheduler snapshot in sequence order."""
    entries: list[Any] = []
    if view.active is not None:
        entries.append(view.active)
    if view.recovered is not None:
        entries.append(view.recovered)
    entries.extend(view.steer)
    entries.extend(view.follow_up)
    return tuple(
        QueueRow(
            submission_id=item.submission_id,
            sequence=item.sequence,
            kind=item.kind,
            status=item.status.value,
            summary=_summary(item.content),
        )
        for item in sorted(entries, key=lambda item: item.sequence)
    )


def toolbar_queue_status(view: SchedulerView) -> str:
    """Return a label-only queue summary used by the live composer.

    0.3.7: the live terminal hides queue counters from the user. The
    status line above the composer carries running-vs-idle state; the
    toolbar only needs a single label so ``/queue`` and any internal
    diagnostics stay distinguishable without leaking ``steer:N``,
    ``follow-up:N``, or ``+N parked`` to the user.
    """
    queued = len(view.steer) + len(view.follow_up)
    if view.active is not None:
        return "Running"
    if view.session_status in {"failed", "aborted"}:
        # 0.3.7: failure is silent on the user UI. The internal gate
        # still parks the queue, but the label collapses to a
        # neutral ``Failed`` so the owner does not see ``+N parked``.
        return "Failed"
    if view.recovered is not None:
        return "Recoverable"
    if queued:
        return "Queued"
    return "Idle"


def render_queue_tui(view: SchedulerView) -> str:
    """Render the complete queue list without reading messages or stdin."""
    lines = [f"Queue · {toolbar_queue_status(view)}"]
    rows = queue_rows(view)
    if not rows:
        lines.append("  (queue empty)")
        return "\n".join(lines)
    lines.append("  Seq  ID           Type       Status       Content")
    for row in rows:
        lines.append(
            f"  {row.sequence:>4} {row.short_id:<12} "
            f"{row.kind.value:<10} {row.status:<12} {row.summary}"
        )
    return "\n".join(lines)


def _parse_choice(raw: str, rows: Iterable[QueueRow]) -> QueueAction | None:
    parts = raw.strip().split(None, 1)
    if not parts:
        return None
    operation = parts[0].lower()
    aliases = {
        "r": "recall",
        "x": "remove",
        "s": "steer",
        "f": "follow-up",
        "c": "clear",
        "q": "cancel",
    }
    operation = aliases.get(operation, operation)
    if operation in {"cancel", "clear"}:
        return QueueAction(operation)
    if operation not in {"recall", "remove", "steer", "follow-up", "followup"}:
        return None
    supplied = parts[1].strip() if len(parts) > 1 else ""
    if not supplied:
        return None
    matches = [row.submission_id for row in rows if row.submission_id.startswith(supplied)]
    if len(matches) != 1:
        return None
    return QueueAction("follow-up" if operation == "followup" else operation, matches[0])


def open_queue_tui(
    view: SchedulerView,
    *,
    input_fn: Callable[[str], str] | None = None,
) -> QueueTUIResult:
    """Show the queue menu and return one action, or an explicit cancellation.

    An active worker never shares its stdin with this menu.  Callers can pass
    ``input_fn`` backed by Prompt Toolkit when the UI is idle; tests and
    non-interactive callers receive a deterministic render without blocking.
    """
    output = render_queue_tui(view)
    if view.active is not None:
        return QueueTUIResult(
            output + "\n  A Turn is running; queue controls remain available as commands.",
        )
    if input_fn is None:
        return QueueTUIResult(output)
    rows = queue_rows(view)
    prompt = "  Action [recall/remove/steer/follow-up/clear, q=cancel]: "
    try:
        raw = input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        return QueueTUIResult(output + "\n  Queue TUI cancelled.", cancelled=True)
    action = _parse_choice(raw, rows)
    if action is None:
        return QueueTUIResult(
            output + "\n  Invalid queue action; no changes made.",
            cancelled=True,
        )
    if action.operation == "cancel":
        return QueueTUIResult(output + "\n  Queue TUI cancelled.", cancelled=True)
    return QueueTUIResult(output, action=action)


__all__ = [
    "QueueAction",
    "QueueRow",
    "QueueTUIResult",
    "open_queue_tui",
    "queue_rows",
    "render_queue_tui",
    "toolbar_queue_status",
]
