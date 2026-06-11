from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def fake_stream_response(*events: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Build a one-shot provider stream from event dictionaries."""
    return iter(events)


def fake_stream_request(*events: dict[str, Any]):
    """Build a stream_request replacement that returns one fake stream."""
    return lambda *_args, **_kwargs: fake_stream_response(*events)


def fake_stream_sequence(*responses: tuple[dict[str, Any], ...]):
    """Build a stream_request replacement that returns one response per call."""
    response_iter = iter(responses)

    def _request(*_args, **_kwargs):
        return fake_stream_response(*next(response_iter))

    return _request
