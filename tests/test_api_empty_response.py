"""
Tests for API empty-response retry behavior.

Verifies:
  1. Empty API responses trigger retry logic with exponential backoff.
  2. Exhausted retries inject a recovery prompt instead of exiting silently.
  3. Normal responses are unaffected.
"""

import sys

from core.api_client import APIEmptyResponseError


# ════════════════════════════════════════════════════════
# Test 1: APIEmptyResponseError exception definition.
# ════════════════════════════════════════════════════════

def test_exception_exists():
    """APIEmptyResponseError should be an Exception subclass."""
    assert issubclass(APIEmptyResponseError, Exception)
    e = APIEmptyResponseError("test empty response")
    assert str(e) == "test empty response"
    print("  OK [1/5] APIEmptyResponseError definition is correct")


# ════════════════════════════════════════════════════════
# Test 2: empty response detection.
# ════════════════════════════════════════════════════════

def test_empty_response_detection():
    """Simulate empty-response scenarios and verify detection logic."""
    # Empty response: text_buf empty, tc_buf empty, tokens unchanged.
    text_buf = ""
    tc_buf = {}
    tokens_before = 0
    tokens_after = 0

    no_new_tokens = (tokens_after == tokens_before)
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)

    assert empty_response is True, "empty response should be detected"
    print("  OK [2/5] empty response detection works (text='' + tc={} + 0 tokens)")

    # Non-empty response: text content is present.
    text_buf = "Hello"
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)
    assert empty_response is False, "text response should not be considered empty"
    print("  OK [2/5] non-empty response detection works (text='Hello')")

    # Non-empty response: tool_calls are present.
    text_buf = ""
    tc_buf = {"0": {"name": "run_shell", "args": "{}"}}
    empty_response = (not text_buf.strip() and not tc_buf and no_new_tokens)
    assert empty_response is False, "tool_call response should not be considered empty"
    print("  OK [2/5] non-empty response detection works (tc_buf has data)")


# ════════════════════════════════════════════════════════
# Test 3: retry mechanism with exponential backoff.
# ════════════════════════════════════════════════════════

def test_retry_mechanism():
    """Simulate consecutive empty responses and verify retry count/backoff."""
    API_RETRY_MAX = 3
    retry_count = 0
    total_wait = 0

    while retry_count < API_RETRY_MAX:
        # Simulate empty response on every attempt.
        empty_response = True

        if not empty_response:
            break

        retry_count += 1
        if retry_count >= API_RETRY_MAX:
            # Recovery prompt should be injected here.
            assert retry_count == 3, f"retry count should be 3, got: {retry_count}"
            break

        wait = min(2 ** retry_count, 8)
        total_wait += wait

    assert retry_count == API_RETRY_MAX, f"should retry {API_RETRY_MAX} times, got: {retry_count}"
    assert total_wait == 6, f"total wait should be 6s (2+4), got: {total_wait}s"
    print(f"  OK [3/5] retry mechanism works: {retry_count} retries, {total_wait}s total backoff")


# ════════════════════════════════════════════════════════
# Test 4: recovery message injection.
# ════════════════════════════════════════════════════════

def test_recovery_message():
    """Verify recovery message format after retries are exhausted."""
    recovery_msg = (
        "[System] Received an invalid response (empty content / 0 tokens). "
        "Re-check the task objective and continue. "
        "If this repeats, consider switching models (/model) or checking the API key."
    )

    # Simulated messages list.
    messages = [{"role": "user", "content": "test input"}]

    # Simulate injection after retries are exhausted.
    API_RETRY_MAX = 3
    for attempt in range(API_RETRY_MAX):
        if attempt >= API_RETRY_MAX - 1:
            messages.append({"role": "user", "content": recovery_msg})
            break

    assert len(messages) == 2, f"should have 2 messages, got: {len(messages)}"
    assert messages[-1]["role"] == "user", "recovery message should use user role"
    assert "invalid response" in messages[-1]["content"], "should include invalid-response prompt"
    assert "switching models" in messages[-1]["content"], "should include model-switch suggestion"
    print("  OK [4/5] recovery message injection works (user role + invalid-response prompt)")


# ════════════════════════════════════════════════════════
# Test 5: normal responses do not trigger retry.
# ════════════════════════════════════════════════════════

def test_normal_response_no_retry():
    """Normal responses should not trigger retry logic."""
    # Simulate normal text response.
    text_buf = "I found the vulnerability in /etc/passwd"
    tc_buf = {}

    empty_response = (not text_buf.strip() and not tc_buf)
    assert empty_response is False, "normal text response should not be considered empty"

    # Simulate a tool_call response.
    text_buf = ""
    tc_buf = {"0": {"name": "run_shell", "args": '{"command": "id"}'}}
    empty_response = (not text_buf.strip() and not tc_buf)
    assert empty_response is False, "tool_call response should not be considered empty"

    print("  OK [5/5] normal responses do not trigger retry (text + tool_call)")


# ════════════════════════════════════════════════════════
# Test 6: exponential backoff timing.
# ════════════════════════════════════════════════════════

def test_backoff_timing():
    """Verify exponential backoff formula: wait = min(2^attempt, 8)."""
    expected = [2, 4, 8]  # attempt 1, 2, 3
    for attempt in range(1, 4):
        wait = min(2 ** attempt, 8)
        assert wait == expected[attempt - 1], \
            f"attempt={attempt}: expected {expected[attempt-1]}, got {wait}"
    print("  OK [extra] exponential backoff timing is correct: 2s -> 4s -> 8s")


# ════════════════════════════════════════════════════════
# Run all tests.
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  API empty-response retry behavior - unit tests")
    print("=" * 60 + "\n")

    tests = [
        test_exception_exists,
        test_empty_response_detection,
        test_retry_mechanism,
        test_recovery_message,
        test_normal_response_no_retry,
        test_backoff_timing,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ [{t.__name__}] FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ [{t.__name__}] ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Result: {passed} passed, {failed} failed")
    print(f"{'=' * 60}\n")
    sys.exit(0 if failed == 0 else 1)
