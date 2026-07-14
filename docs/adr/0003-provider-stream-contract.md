# ADR 0003: Provider Stream Contract

## Status

Accepted

## Context

PawnLogic supports multiple LLM providers (DeepSeek/OpenAI-compatible and
Anthropic) with different SSE streaming formats. Before this contract was
explicit:

- OpenAI and Anthropic SSE line readers had different delta shapes, usage
  reporting, and stop conditions.
- Tool-call deltas arrived in provider-specific structures that callers had to
  normalize.
- Retry, timeout, and interruption behavior was partially duplicated between
  stream and non-stream paths.
- Tests asserted on exact dictionary shapes but the contract was implicit in
  test code, not documented.

## Decision

Define a provider stream contract with these rules:

1. **Format-specific readers:** `core.provider_streams` owns OpenAI and
   Anthropic SSE line readers. Each reader yields typed event dicts.
2. **Delta shape:** Text deltas arrive as `{"type": "text_delta", "text": "..."}`.
   Tool-call deltas arrive as `{"type": "tool_call_delta", ...}`. The exact
   provider-specific fields are normalized by the reader.
3. **Usage reporting:** Usage chunks arrive as `{"type": "usage", ...}` with
   `input_tokens` and `output_tokens` keys.
4. **Stop conditions:** Readers yield `{"type": "done"}` on stream completion
   and raise on transport errors. Partial content is preserved on interruption.
5. **Retry classification:** `core.api_errors` classifies retryable vs
   non-retryable failures. Classification is shared between stream and
   non-stream paths.

## Consequences

Provider-specific SSE parsing is isolated in `core.provider_streams`. The rest
of the codebase consumes normalized event dicts.

Tests in `test_api_stream_helpers.py` contract-test the exact delta shapes for
both providers. Changes to delta shapes require updating the contract tests.

New providers must add a reader to `core.provider_streams` that produces the
same normalized event dict shape.
