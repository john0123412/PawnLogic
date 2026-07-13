"""Tests for internal runtime metrics snapshots."""

from core.runtime_metrics import RuntimeMetrics, RuntimeMetricsSnapshot


def test_runtime_metrics_defaults_are_empty():
    metrics = RuntimeMetrics()
    snapshot = metrics.snapshot()

    assert snapshot == RuntimeMetricsSnapshot()
    assert snapshot.turn_tokens == 0
    assert snapshot.total_tokens == 0


def test_runtime_metrics_records_usage_retries_tools_and_failures():
    metrics = RuntimeMetrics()

    metrics.record_usage(prompt_tokens=3, completion_tokens=5)
    metrics.record_provider_retries(2)
    metrics.record_tool_call(elapsed_ms=12)
    metrics.record_tool_call(elapsed_ms=-7)
    metrics.record_failure_class("Timeout")
    metrics.record_failure_class("Timeout")
    metrics.record_failure_class("")
    metrics.record_circuit_probe()
    metrics.record_circuit_rejection()
    metrics.record_circuit_success()
    metrics.record_circuit_failure()

    snapshot = metrics.snapshot()
    assert snapshot.turn_tool_calls == 2
    assert snapshot.total_tool_calls == 2
    assert snapshot.turn_tool_latency_ms == 12
    assert snapshot.total_tool_latency_ms == 12
    assert snapshot.turn_provider_retries == 2
    assert snapshot.total_provider_retries == 2
    assert snapshot.turn_tokens == 8
    assert snapshot.total_tokens == 8
    assert snapshot.turn_failure_classes == {"Timeout": 2}
    assert snapshot.total_failure_classes == {"Timeout": 2}
    assert snapshot.total_circuit_probes == 1
    assert snapshot.total_circuit_rejections == 1
    assert snapshot.total_circuit_successes == 1
    assert snapshot.total_circuit_failures == 1


def test_runtime_metrics_reset_turn_keeps_session_totals():
    metrics = RuntimeMetrics()
    metrics.record_turn_completed()
    metrics.record_usage(prompt_tokens=1, completion_tokens=2)
    metrics.record_provider_retries(1)
    metrics.record_tool_call(elapsed_ms=9)
    metrics.record_failure_class("RuntimeError")

    metrics.reset_turn()
    snapshot = metrics.snapshot()

    assert snapshot.turn_count == 1
    assert snapshot.turn_tool_calls == 0
    assert snapshot.turn_tool_latency_ms == 0
    assert snapshot.turn_provider_retries == 0
    assert snapshot.turn_tokens == 0
    assert snapshot.turn_failure_classes == {}
    assert snapshot.total_tool_calls == 1
    assert snapshot.total_tool_latency_ms == 9
    assert snapshot.total_provider_retries == 1
    assert snapshot.total_tokens == 3
    assert snapshot.total_failure_classes == {"RuntimeError": 1}


def test_runtime_metrics_snapshot_returns_copies():
    metrics = RuntimeMetrics()
    metrics.record_failure_class("Timeout")

    snapshot = metrics.snapshot()
    snapshot.turn_failure_classes["Timeout"] = 99
    snapshot.total_failure_classes["RuntimeError"] = 1

    fresh_snapshot = metrics.snapshot()
    assert fresh_snapshot.turn_failure_classes == {"Timeout": 1}
    assert fresh_snapshot.total_failure_classes == {"Timeout": 1}
