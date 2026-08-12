"""Bounded FIFO orchestration for delegated Agent tasks and shared budgets."""

from __future__ import annotations

import contextvars
import math
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Protocol

from core.delegation import (
    AgentBudget,
    AgentResult,
    AgentTask,
    AgentUsage,
    FailureRecord,
)


_DEADLINE_CANCEL_REASON = "deadline exceeded"
_HOST_INTERRUPT_REASON = "parent turn interrupted"
_INTERRUPT_POLL_SECONDS = 0.05


def _host_interrupt_requested() -> bool:
    """Read the host interrupt signal without adding a runtime import edge."""
    try:
        from core.interrupts import interrupted

        return bool(interrupted())
    except Exception:
        return False


def _amount(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _cost(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("cost must be a number")
    result = float(value)
    if result < 0 or not math.isfinite(result):
        raise ValueError("cost must be finite and non-negative")
    return result


class CancellationToken:
    """Thread-safe cooperative cancellation signal with one-way child links."""

    def __init__(self, parent: CancellationToken | None = None) -> None:
        if parent is not None and not isinstance(parent, CancellationToken):
            raise TypeError("parent must be a CancellationToken or None")
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None
        self._children: set[CancellationToken] = set()
        self._parent = parent
        self._abort_callbacks: dict[int, Callable[[], object]] = {}
        self._next_abort_callback = 0
        if parent is not None:
            parent._register_child(self)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def is_cancelled(self) -> bool:
        return self.cancelled

    def cancel(self, reason: str = "cancelled") -> bool:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must not be empty")
        normalized = reason.strip()
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized
            self._event.set()
            children = tuple(self._children)
            callbacks = tuple(self._abort_callbacks.values())
            self._abort_callbacks.clear()
        for callback in callbacks:
            self._invoke_abort(callback)
        for child in children:
            child.cancel(normalized)
        return True

    def child(self) -> CancellationToken:
        """Create a token cancelled by this token but isolated from siblings."""
        return CancellationToken(parent=self)

    def detach(self) -> None:
        """Remove this completed child token from its parent fan-out set."""
        parent = self._parent
        if parent is not None:
            parent._unregister_child(self)
            self._parent = None

    def register_abort(self, callback: Callable[[], object]) -> Callable[[], None]:
        """Register a best-effort abort callback and return an idempotent remover."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            cancelled = self._event.is_set()
            if cancelled:
                callback_id: int | None = None
            else:
                callback_id = self._next_abort_callback
                self._next_abort_callback += 1
                self._abort_callbacks[callback_id] = callback
        if cancelled:
            self._invoke_abort(callback)

        def unregister() -> None:
            if callback_id is None:
                return
            with self._lock:
                self._abort_callbacks.pop(callback_id, None)

        return unregister

    def _register_child(self, child: CancellationToken) -> None:
        with self._lock:
            cancelled = self._event.is_set()
            reason = self._reason
            if not cancelled:
                self._children.add(child)
        if cancelled:
            child.cancel(reason or "cancelled")

    def _unregister_child(self, child: CancellationToken) -> None:
        with self._lock:
            self._children.discard(child)

    @staticmethod
    def _invoke_abort(callback: Callable[[], object]) -> None:
        try:
            callback()
        except Exception:
            return

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise TypeError("timeout must be a number or None")
            if timeout < 0 or not math.isfinite(float(timeout)):
                raise ValueError("timeout must be finite and non-negative")
        return self._event.wait(timeout)


class BudgetExceededError(RuntimeError):
    """Raised when an atomic budget reservation cannot be satisfied."""


@dataclass(frozen=True)
class BudgetSnapshot:
    max_tokens: int
    max_tool_calls: int
    max_cost: float | None
    consumed_tokens: int
    consumed_tool_calls: int
    consumed_cost: float
    reserved_tokens: int
    reserved_tool_calls: int
    reserved_cost: float

    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.consumed_tokens - self.reserved_tokens

    @property
    def available_tool_calls(self) -> int:
        return (
            self.max_tool_calls
            - self.consumed_tool_calls
            - self.reserved_tool_calls
        )

    @property
    def available_cost(self) -> float | None:
        if self.max_cost is None:
            return None
        return self.max_cost - self.consumed_cost - self.reserved_cost


class BudgetClaim:
    """Single-settlement reservation owned by a :class:`BudgetLedger`."""

    def __init__(
        self,
        ledger: BudgetLedger,
        *,
        tokens: int,
        tool_calls: int,
        cost: float | None,
        reserved_cost: float,
    ) -> None:
        self._ledger = ledger
        self.tokens = tokens
        self.tool_calls = tool_calls
        self.cost = cost
        self._reserved_cost = reserved_cost
        self._settled = False

    @property
    def settled(self) -> bool:
        with self._ledger._lock:
            return self._settled

    def settle(
        self,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        cost: float = 0.0,
    ) -> BudgetSnapshot:
        return self._ledger._settle(
            self,
            tokens=_amount(tokens, "tokens"),
            tool_calls=_amount(tool_calls, "tool_calls"),
            cost=_cost(cost),
        )

    def release(self) -> BudgetSnapshot:
        return self.settle()


class BudgetLedger:
    """Atomically reserve and settle token, Tool Call, and cost budgets."""

    def __init__(self, budget: AgentBudget) -> None:
        if not isinstance(budget, AgentBudget):
            raise TypeError("budget must be an AgentBudget")
        self._budget = budget
        self._lock = threading.Lock()
        self._consumed_tokens = 0
        self._consumed_tool_calls = 0
        self._consumed_cost = 0.0
        self._reserved_tokens = 0
        self._reserved_tool_calls = 0
        self._reserved_cost = 0.0

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def try_claim(
        self,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        cost: float | None = 0.0,
    ) -> BudgetClaim | None:
        tokens = _amount(tokens, "tokens")
        tool_calls = _amount(tool_calls, "tool_calls")
        normalized_cost = None if cost is None else _cost(cost)
        with self._lock:
            current = self._snapshot_unlocked()
            if tokens > current.available_tokens:
                return None
            if tool_calls > current.available_tool_calls:
                return None
            available_cost = current.available_cost
            if normalized_cost is None:
                reserved_cost = available_cost or 0.0
            else:
                reserved_cost = normalized_cost
                if available_cost is not None and reserved_cost > available_cost:
                    return None
            self._reserved_tokens += tokens
            self._reserved_tool_calls += tool_calls
            self._reserved_cost += reserved_cost
            return BudgetClaim(
                self,
                tokens=tokens,
                tool_calls=tool_calls,
                cost=(
                    available_cost
                    if normalized_cost is None and available_cost is not None
                    else normalized_cost
                ),
                reserved_cost=reserved_cost,
            )

    def claim(
        self,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        cost: float = 0.0,
    ) -> BudgetClaim:
        claim = self.try_claim(tokens=tokens, tool_calls=tool_calls, cost=cost)
        if claim is None:
            raise BudgetExceededError("requested budget is unavailable")
        return claim

    def _settle(
        self,
        claim: BudgetClaim,
        *,
        tokens: int,
        tool_calls: int,
        cost: float,
    ) -> BudgetSnapshot:
        with self._lock:
            if claim._settled:
                raise RuntimeError("budget claim is already settled")
            if tokens > claim.tokens:
                raise ValueError("actual usage exceeds reserved tokens")
            if tool_calls > claim.tool_calls:
                raise ValueError("actual usage exceeds reserved tool calls")
            if claim.cost is not None and cost > claim.cost:
                raise ValueError("actual usage exceeds reserved cost")
            self._reserved_tokens -= claim.tokens
            self._reserved_tool_calls -= claim.tool_calls
            self._reserved_cost -= claim._reserved_cost
            self._consumed_tokens += tokens
            self._consumed_tool_calls += tool_calls
            self._consumed_cost += cost
            claim._settled = True
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            max_tokens=self._budget.max_tokens,
            max_tool_calls=self._budget.max_tool_calls,
            max_cost=self._budget.max_cost,
            consumed_tokens=self._consumed_tokens,
            consumed_tool_calls=self._consumed_tool_calls,
            consumed_cost=self._consumed_cost,
            reserved_tokens=self._reserved_tokens,
            reserved_tool_calls=self._reserved_tool_calls,
            reserved_cost=self._reserved_cost,
        )


class AgentTaskExecutor(Protocol):
    """Delegation Runtime seam consumed by the bounded orchestrator.

    Executors used with ``max_concurrency=2`` must support concurrent calls;
    each call receives an independent child cancellation token.
    """

    def execute(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult: ...


@dataclass(frozen=True)
class OrchestrationResult:
    status: str
    results: tuple[AgentResult, ...]
    budget: BudgetSnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "results": [result.to_dict() for result in self.results],
            "budget": {
                "consumed_tokens": self.budget.consumed_tokens,
                "consumed_tool_calls": self.budget.consumed_tool_calls,
                "consumed_cost": self.budget.consumed_cost,
                "available_tokens": self.budget.available_tokens,
                "available_tool_calls": self.budget.available_tool_calls,
                "available_cost": self.budget.available_cost,
            },
        }


@dataclass
class _InFlightTask:
    index: int
    task: AgentTask
    claim: BudgetClaim
    cancellation: CancellationToken
    deadline_processed: bool = False
    deadline_cancelled: bool = False


class SerialAgentOrchestrator:
    """Execute tasks with FIFO admission and one or two synchronous workers.

    The legacy public name remains for compatibility. Results preserve input
    order even when up to two independently cancellable executor calls run.
    """

    def __init__(
        self,
        executor: AgentTaskExecutor,
        *,
        max_concurrency: int = 1,
        clock=time.monotonic,
    ) -> None:
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an integer")
        if max_concurrency not in (1, 2):
            raise ValueError("max_concurrency must be 1 or 2")
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must implement execute(task, cancellation)")
        configure_concurrency = getattr(executor, "configure_concurrency", None)
        if callable(configure_concurrency):
            configure_concurrency(max_concurrency)
        self._executor = executor
        self._max_concurrency = max_concurrency
        self._clock = clock

    def run(
        self,
        tasks: Sequence[AgentTask],
        *,
        budget: AgentBudget,
        cancellation: CancellationToken | None = None,
    ) -> OrchestrationResult:
        normalized = tuple(tasks)
        if not all(isinstance(task, AgentTask) for task in normalized):
            raise TypeError("tasks must contain only AgentTask values")
        task_ids = [task.task_id for task in normalized]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("task IDs must be unique")
        token = cancellation or CancellationToken()
        ledger = BudgetLedger(budget)
        results: list[AgentResult | None] = [None] * len(normalized)
        inflight: dict[Future[AgentResult], _InFlightTask] = {}
        next_index = 0

        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            while next_index < len(normalized) or inflight:
                self._propagate_host_interrupt(token)
                while (
                    next_index < len(normalized)
                    and len(inflight) < self._max_concurrency
                ):
                    self._propagate_host_interrupt(token)
                    task = normalized[next_index]
                    terminal = self._preflight(task, token)
                    if terminal is not None:
                        results[next_index] = terminal
                        next_index += 1
                        continue
                    claim = ledger.try_claim(
                        tokens=task.budget.max_tokens,
                        tool_calls=task.budget.max_tool_calls,
                        cost=task.budget.max_cost,
                    )
                    if claim is None:
                        if inflight:
                            break
                        results[next_index] = self._terminal(
                            task,
                            "budget_exhausted",
                            "shared_budget_exhausted",
                            "Shared orchestration budget could not admit this task.",
                        )
                        next_index += 1
                        continue

                    child = token.child()
                    try:
                        # Each worker receives a snapshot of the caller's
                        # ContextVars.  A concurrent executor must still fork
                        # mutable RuntimeContext state before changing it.
                        context = contextvars.copy_context()
                        future = pool.submit(
                            context.run,
                            self._execute_admitted,
                            task,
                            child,
                        )
                    except Exception:
                        self._release_claim(claim)
                        child.detach()
                        results[next_index] = self._terminal(
                            task,
                            "failed",
                            "executor_submit_error",
                            "Delegation Runtime could not start the task.",
                        )
                    else:
                        inflight[future] = _InFlightTask(
                            index=next_index,
                            task=task,
                            claim=claim,
                            cancellation=child,
                        )
                    next_index += 1

                if not inflight:
                    continue
                completed = {future for future in inflight if future.done()}
                if not completed:
                    timeout = self._wait_timeout(inflight.values())
                    completed, _ = wait(
                        inflight,
                        timeout=timeout,
                        return_when=FIRST_COMPLETED,
                    )
                self._propagate_host_interrupt(token)
                if not completed:
                    self._cancel_expired_tasks(inflight.values())
                    continue
                for future in completed:
                    scheduled = inflight.pop(future)
                    results[scheduled.index] = self._collect_result(
                        future,
                        scheduled,
                    )

        ordered_results = tuple(result for result in results if result is not None)
        return OrchestrationResult(
            status=self._status(ordered_results),
            results=ordered_results,
            budget=ledger.snapshot(),
        )

    def _execute_admitted(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult:
        terminal = self._preflight(task, cancellation)
        if terminal is not None:
            return terminal
        return self._execute(task, cancellation)

    def _collect_result(
        self,
        future: Future[AgentResult],
        scheduled: _InFlightTask,
    ) -> AgentResult:
        task = scheduled.task
        try:
            result = future.result()
        except Exception:
            result = self._terminal(
                task,
                "failed",
                "executor_error",
                "Delegation Runtime failed while executing the task.",
            )
        if not isinstance(result, AgentResult):
            result = self._terminal(
                task,
                "failed",
                "invalid_executor_result",
                "Delegation Runtime returned an invalid result.",
            )

        try:
            usage = result.usage
            scheduled.claim.settle(
                tokens=usage.prompt_tokens + usage.completion_tokens,
                tool_calls=usage.tool_calls,
                cost=usage.cost,
            )
        except ValueError:
            result = self._terminal(
                task,
                "budget_exhausted",
                "reported_usage_exceeded_reservation",
                "Delegation Runtime reported usage above its reservation.",
            )
        except Exception:
            result = self._terminal(
                task,
                "failed",
                "budget_settlement_error",
                "Delegation Runtime usage could not be settled safely.",
            )
        finally:
            self._release_claim(scheduled.claim)
            scheduled.cancellation.detach()
        return self._postflight(
            task,
            scheduled.cancellation,
            result,
            deadline_cancelled=scheduled.deadline_cancelled,
        )

    @staticmethod
    def _release_claim(claim: BudgetClaim) -> None:
        if not claim.settled:
            claim.release()

    def _wait_timeout(
        self,
        scheduled_tasks: Iterable[_InFlightTask],
    ) -> float:
        deadlines = [
            scheduled.task.deadline
            for scheduled in scheduled_tasks
            if (
                scheduled.task.deadline is not None
                and not scheduled.deadline_processed
            )
        ]
        if not deadlines:
            return _INTERRUPT_POLL_SECONDS
        return min(
            _INTERRUPT_POLL_SECONDS,
            max(0.0, min(deadlines) - self._clock()),
        )

    def _cancel_expired_tasks(
        self,
        scheduled_tasks: Iterable[_InFlightTask],
    ) -> None:
        now = self._clock()
        for scheduled in scheduled_tasks:
            deadline = scheduled.task.deadline
            if (
                deadline is not None
                and now >= deadline
                and not scheduled.deadline_processed
            ):
                scheduled.deadline_processed = True
                scheduled.deadline_cancelled = scheduled.cancellation.cancel(
                    _DEADLINE_CANCEL_REASON
                )

    @staticmethod
    def _propagate_host_interrupt(cancellation: CancellationToken) -> None:
        if _host_interrupt_requested():
            cancellation.cancel(_HOST_INTERRUPT_REASON)

    def _preflight(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult | None:
        if cancellation.cancelled:
            return self._terminal(
                task,
                "cancelled",
                "cancelled",
                cancellation.reason or "Task was cancelled.",
            )
        if task.deadline is not None and self._clock() >= task.deadline:
            return self._terminal(
                task,
                "timed_out",
                "deadline_exceeded",
                "Task deadline elapsed before execution.",
            )
        return None

    def _postflight(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
        result: AgentResult,
        *,
        deadline_cancelled: bool = False,
    ) -> AgentResult:
        if deadline_cancelled and result.status in {"completed", "cancelled"}:
            return self._terminal(
                task,
                "timed_out",
                "deadline_exceeded",
                "Task deadline elapsed during execution.",
                usage=result.usage,
            )
        if cancellation.cancelled and result.status == "completed":
            return self._terminal(
                task,
                "cancelled",
                "cancelled",
                cancellation.reason or "Task was cancelled.",
                usage=result.usage,
            )
        if (
            task.deadline is not None
            and self._clock() >= task.deadline
            and result.status == "completed"
        ):
            return self._terminal(
                task,
                "timed_out",
                "deadline_exceeded",
                "Task deadline elapsed during execution.",
                usage=result.usage,
            )
        return replace(
            result,
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
        )

    def _execute(
        self,
        task: AgentTask,
        cancellation: CancellationToken,
    ) -> AgentResult:
        try:
            result = self._executor.execute(task, cancellation)
        except Exception:
            return self._terminal(
                task,
                "failed",
                "executor_error",
                "Delegation Runtime failed while executing the task.",
            )
        if not isinstance(result, AgentResult):
            return self._terminal(
                task,
                "failed",
                "invalid_executor_result",
                "Delegation Runtime returned an invalid result.",
            )
        return replace(
            result,
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
        )

    @staticmethod
    def _terminal(
        task: AgentTask,
        status: str,
        code: str,
        message: str,
        *,
        usage: AgentUsage | None = None,
    ) -> AgentResult:
        return AgentResult(
            status=status,
            summary=message,
            failures=(FailureRecord(code=code, message=message),),
            usage=usage or AgentUsage(),
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
        )

    @staticmethod
    def _status(results: Sequence[AgentResult]) -> str:
        if not results:
            return "completed"
        statuses = {result.status for result in results}
        if len(statuses) == 1:
            return results[0].status
        return "partial"


__all__ = [
    "AgentTaskExecutor",
    "BudgetClaim",
    "BudgetExceededError",
    "BudgetLedger",
    "BudgetSnapshot",
    "CancellationToken",
    "OrchestrationResult",
    "SerialAgentOrchestrator",
]
