"""Message queue for breakpoint resume support.

Provides a thread-safe queue that supports:
- Enqueue/dequeue message operations
- Pending tracking during turn execution
- Requeue on interruption
- Priority-based ordering
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class QueuedMessage:
    """A message waiting to be processed in the queue."""

    content: str
    timestamp: float = field(default_factory=time.time)
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QueuedMessage):
            return NotImplemented
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.timestamp < other.timestamp


class MessageQueue:
    """Thread-safe message queue for breakpoint resume support.

    Supports enqueue, dequeue, clear, and requeue operations.
    Tracks pending messages during turn execution so interrupted
    turns can resume from where they left off.
    """

    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max_size
        self._queue: deque[QueuedMessage] = deque(maxlen=max_size)
        self._pending: deque[QueuedMessage] = deque()
        self._lock = Lock()

    def enqueue(self, content: str, priority: int = 0, **metadata: Any) -> int:
        """Enqueue a new message.

        Args:
            content: The message content to queue.
            priority: Higher priority messages are processed first.
            **metadata: Optional metadata attached to the message.

        Returns:
            The new size of the queue after enqueue.
        """
        with self._lock:
            if len(self._queue) >= self._max_size:
                # Drop lowest-priority message to make room
                self._drop_lowest_priority()
            msg = QueuedMessage(
                content=content,
                priority=priority,
                metadata=metadata,
            )
            self._queue.append(msg)
            return len(self._queue)

    def enqueue_many(self, messages: list[str], priority: int = 0) -> int:
        """Enqueue multiple messages at once.

        Args:
            messages: List of message contents to queue.
            priority: Priority for all messages.

        Returns:
            The new size of the queue after enqueueing all messages.
        """
        with self._lock:
            for content in messages:
                if len(self._queue) >= self._max_size:
                    self._drop_lowest_priority()
                self._queue.append(QueuedMessage(content=content, priority=priority))
            return len(self._queue)

    def dequeue(self) -> QueuedMessage | None:
        """Dequeue the next message and move it to pending.

        Returns:
            The next QueuedMessage, or None if the queue is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            msg = self._queue.popleft()
            self._pending.append(msg)
            return msg

    def complete_pending(self) -> None:
        """Mark all pending messages as completed.

        Called when a turn finishes successfully.
        """
        with self._lock:
            self._pending.clear()

    def requeue_pending(self) -> int:
        """Move pending messages back to the queue on interruption.

        Increments the retry count in metadata for each requeued message.

        Returns:
            The number of messages requeued.
        """
        with self._lock:
            count = len(self._pending)
            while self._pending:
                msg = self._pending.pop()
                msg.metadata["retried"] = msg.metadata.get("retried", 0) + 1
                self._queue.appendleft(msg)
            return count

    def clear(self) -> int:
        """Clear all queued and pending messages.

        Returns:
            The total number of messages cleared.
        """
        with self._lock:
            count = len(self._queue) + len(self._pending)
            self._queue.clear()
            self._pending.clear()
            return count

    def peek(self, n: int = 5) -> list[QueuedMessage]:
        """Peek at the next n queued messages without removing them.

        Args:
            n: Number of messages to peek at.

        Returns:
            A list of the next n QueuedMessage objects.
        """
        with self._lock:
            return list(self._queue)[:n]

    def size(self) -> int:
        """Return the current queue depth.

        Returns:
            Number of messages in the queue.
        """
        with self._lock:
            return len(self._queue)

    @property
    def is_empty(self) -> bool:
        return self.size() == 0

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _drop_lowest_priority(self) -> None:
        """Remove the lowest-priority message when the queue is full.

        Must be called while holding the lock.
        """
        if not self._queue:
            return
        # Find message with lowest priority (lowest priority value = lowest priority)
        # We use direct attribute comparison to avoid confusion with __lt__
        min_idx = min(
            range(len(self._queue)),
            key=lambda i: (self._queue[i].priority, self._queue[i].timestamp)
        )
        del self._queue[min_idx]

    def to_list(self) -> list[str]:
        """Return all queued message contents as a list.

        Returns:
            A list of message content strings in queue order.
        """
        with self._lock:
            return [msg.content for msg in self._queue]

    def save_state(self) -> dict[str, Any]:
        """Serialize the queue state for persistence.

        Returns:
            A dict containing queue and pending message data.
        """
        with self._lock:
            return {
                "queue": [
                    {
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "priority": msg.priority,
                        "metadata": msg.metadata,
                    }
                    for msg in self._queue
                ],
                "pending": [
                    {
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "priority": msg.priority,
                        "metadata": msg.metadata,
                    }
                    for msg in self._pending
                ],
            }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> MessageQueue:
        """Restore a MessageQueue from serialized state.

        Args:
            state: A dict from save_state().

        Returns:
            A restored MessageQueue instance.
        """
        queue = cls()
        for msg_data in state.get("queue", []):
            msg = QueuedMessage(
                content=msg_data["content"],
                timestamp=msg_data["timestamp"],
                priority=msg_data.get("priority", 0),
                metadata=msg_data.get("metadata", {}),
            )
            queue._queue.append(msg)
        for msg_data in state.get("pending", []):
            msg = QueuedMessage(
                content=msg_data["content"],
                timestamp=msg_data["timestamp"],
                priority=msg_data.get("priority", 0),
                metadata=msg_data.get("metadata", {}),
            )
            queue._pending.append(msg)
        return queue


# Module-level singleton for convenience.
_queue_singleton: MessageQueue | None = None


def get_message_queue() -> MessageQueue:
    """Return the module-level message queue singleton.

    Returns:
        The global MessageQueue instance.
    """
    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = MessageQueue()
    return _queue_singleton
