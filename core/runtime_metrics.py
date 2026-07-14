"""Internal runtime metrics snapshots.

Metrics here are process-local bookkeeping for tests, debug tooling, and future
maintenance work. They are not telemetry, are not persisted in chat messages,
and do not change terminal output by default.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RuntimeMetricsSnapshot:
    """Immutable copy of internal session runtime metrics."""

    turn_count: int = 0
    turn_tool_calls: int = 0
    total_tool_calls: int = 0
    turn_tool_latency_ms: int = 0
    total_tool_latency_ms: int = 0
    turn_provider_retries: int = 0
    total_provider_retries: int = 0
    total_circuit_probes: int = 0
    total_circuit_rejections: int = 0
    total_circuit_successes: int = 0
    total_circuit_failures: int = 0
    turn_prompt_tokens: int = 0
    turn_completion_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    turn_failure_classes: dict[str, int] = field(default_factory=dict)
    total_failure_classes: dict[str, int] = field(default_factory=dict)

    @property
    def turn_tokens(self) -> int:
        """Return prompt plus completion tokens for the current turn."""
        return self.turn_prompt_tokens + self.turn_completion_tokens

    @property
    def total_tokens(self) -> int:
        """Return prompt plus completion tokens for the session."""
        return self.total_prompt_tokens + self.total_completion_tokens


@dataclass(slots=True)
class RuntimeMetrics:
    """Mutable internal counters for an agent session."""

    turn_count: int = 0
    turn_tool_calls: int = 0
    total_tool_calls: int = 0
    turn_tool_latency_ms: int = 0
    total_tool_latency_ms: int = 0
    turn_provider_retries: int = 0
    total_provider_retries: int = 0
    total_circuit_probes: int = 0
    total_circuit_rejections: int = 0
    total_circuit_successes: int = 0
    total_circuit_failures: int = 0
    turn_prompt_tokens: int = 0
    turn_completion_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    turn_failure_classes: Counter[str] = field(default_factory=Counter)
    total_failure_classes: Counter[str] = field(default_factory=Counter)

    def reset_turn(self) -> None:
        """Clear per-turn counters while keeping session totals."""
        self.turn_tool_calls = 0
        self.turn_tool_latency_ms = 0
        self.turn_provider_retries = 0
        self.turn_prompt_tokens = 0
        self.turn_completion_tokens = 0
        self.turn_failure_classes.clear()

    def record_turn_completed(self) -> None:
        """Record that a run_turn lifecycle reached autosave."""
        self.turn_count += 1

    def record_usage(self, *, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Record provider token usage for the current turn and session."""
        self.turn_prompt_tokens += prompt_tokens
        self.turn_completion_tokens += completion_tokens
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

    def record_provider_retries(self, count: int) -> None:
        """Record provider retry events observed while consuming a stream."""
        if count <= 0:
            return
        self.turn_provider_retries += count
        self.total_provider_retries += count

    def record_circuit_probe(self) -> None:
        self.total_circuit_probes += 1

    def record_circuit_rejection(self) -> None:
        self.total_circuit_rejections += 1

    def record_circuit_success(self) -> None:
        self.total_circuit_successes += 1

    def record_circuit_failure(self) -> None:
        self.total_circuit_failures += 1

    def record_tool_call(self, *, elapsed_ms: int = 0) -> None:
        """Record one executed tool call and its elapsed time."""
        self.turn_tool_calls += 1
        self.total_tool_calls += 1
        latency = max(0, elapsed_ms)
        self.turn_tool_latency_ms += latency
        self.total_tool_latency_ms += latency

    def record_failure_class(self, failure_class: str) -> None:
        """Record a classified tool failure."""
        if not failure_class:
            return
        self.turn_failure_classes[failure_class] += 1
        self.total_failure_classes[failure_class] += 1

    def snapshot(self) -> RuntimeMetricsSnapshot:
        """Return an immutable copy of current counters."""
        return RuntimeMetricsSnapshot(
            turn_count=self.turn_count,
            turn_tool_calls=self.turn_tool_calls,
            total_tool_calls=self.total_tool_calls,
            turn_tool_latency_ms=self.turn_tool_latency_ms,
            total_tool_latency_ms=self.total_tool_latency_ms,
            turn_provider_retries=self.turn_provider_retries,
            total_provider_retries=self.total_provider_retries,
            total_circuit_probes=self.total_circuit_probes,
            total_circuit_rejections=self.total_circuit_rejections,
            total_circuit_successes=self.total_circuit_successes,
            total_circuit_failures=self.total_circuit_failures,
            turn_prompt_tokens=self.turn_prompt_tokens,
            turn_completion_tokens=self.turn_completion_tokens,
            total_prompt_tokens=self.total_prompt_tokens,
            total_completion_tokens=self.total_completion_tokens,
            turn_failure_classes=dict(self.turn_failure_classes),
            total_failure_classes=dict(self.total_failure_classes),
        )


__all__ = ["RuntimeMetrics", "RuntimeMetricsSnapshot"]
