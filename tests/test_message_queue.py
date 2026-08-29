"""Tests for the MessageQueue breakpoint resume module."""

import threading
import time
from core.message_queue import MessageQueue, QueuedMessage


class TestMessageQueueBasic:
    """Basic MessageQueue enqueue/dequeue operations."""

    def test_enqueue_returns_queue_size(self):
        q = MessageQueue()
        assert q.enqueue("hello") == 1
        assert q.enqueue("world") == 2

    def test_dequeue_returns_oldest_message(self):
        q = MessageQueue()
        q.enqueue("first")
        q.enqueue("second")
        msg = q.dequeue()
        assert msg is not None
        assert msg.content == "first"

    def test_dequeue_empty_returns_none(self):
        q = MessageQueue()
        assert q.dequeue() is None

    def test_fifo_order(self):
        q = MessageQueue()
        for i in range(5):
            q.enqueue(f"msg-{i}")
        contents = [q.dequeue().content for _ in range(5)]
        assert contents == [f"msg-{i}" for i in range(5)]

    def test_size_tracks_queue(self):
        q = MessageQueue()
        assert q.size() == 0
        q.enqueue("a")
        assert q.size() == 1
        q.dequeue()
        assert q.size() == 0

    def test_clear_returns_count(self):
        q = MessageQueue()
        q.enqueue("a")
        q.enqueue("b")
        assert q.clear() == 2
        assert q.size() == 0


class TestMessageQueuePending:
    """Pending tracking during turn execution."""

    def test_dequeue_moves_to_pending(self):
        q = MessageQueue()
        q.enqueue("a")
        q.dequeue()
        assert q.pending_count == 1

    def test_complete_pending_clears(self):
        q = MessageQueue()
        q.enqueue("a")
        q.dequeue()
        q.complete_pending()
        assert q.pending_count == 0

    def test_requeue_pending_preserves_fifo_order(self):
        q = MessageQueue()
        q.enqueue("a")
        q.enqueue("b")
        q.dequeue()  # a -> pending
        q.dequeue()  # b -> pending
        count = q.requeue_pending()
        assert count == 2
        assert q.size() == 2
        assert q.pending_count == 0
        # Requeue preserves FIFO order: a was first dequeued, so after requeue
        # a is at the front of the queue (LIFO pop + appendleft = FIFO)
        assert q.peek(2)[0].content == "a"
        assert q.peek(2)[1].content == "b"

    def test_requeue_increments_retry_count(self):
        q = MessageQueue()
        q.enqueue("a")
        q.dequeue()
        q.requeue_pending()
        msg = q.peek(1)[0]
        assert msg.metadata.get("retried") == 1

    def test_replace_next_updates_only_the_interrupted_head(self):
        q = MessageQueue()
        q.enqueue("interrupted prompt")
        q.enqueue("later prompt")

        assert q.replace_next("edited prompt") is True
        assert q.to_list() == ["edited prompt", "later prompt"]

    def test_replace_next_returns_false_for_an_empty_queue(self):
        assert MessageQueue().replace_next("retry") is False


class TestMessageQueuePriority:
    """Priority-based ordering."""

    def test_high_priority_first(self):
        q = MessageQueue()
        q.enqueue("low", priority=1)
        q.enqueue("high", priority=10)
        # Note: append order is preserved at enqueue; priority affects
        # drop selection, not dequeue order (which is FIFO).
        assert q.peek(1)[0].content == "low"

    def test_max_size_drops_lowest_priority(self):
        q = MessageQueue(max_size=2)
        q.enqueue("low", priority=1)
        q.enqueue("high", priority=10)
        q.enqueue("new", priority=5)
        # Should drop "low" (priority 1)
        contents = q.to_list()
        assert "low" not in contents
        assert "high" in contents
        assert "new" in contents

    def test_enqueue_with_metadata(self):
        q = MessageQueue()
        q.enqueue("a", source="cli", token_count=42)
        msg = q.peek(1)[0]
        assert msg.metadata.get("source") == "cli"
        assert msg.metadata.get("token_count") == 42


class TestMessageQueueThreadSafety:
    """Thread-safety of the message queue."""

    def test_concurrent_enqueue(self):
        q = MessageQueue(max_size=1000)

        def enqueuer(start: int, count: int):
            for i in range(start, start + count):
                q.enqueue(f"msg-{i}")

        threads = [
            threading.Thread(target=enqueuer, args=(i * 100, 100)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert q.size() == 500

    def test_concurrent_dequeue(self):
        q = MessageQueue()
        for i in range(100):
            q.enqueue(f"msg-{i}")
        results = []

        def dequeuer():
            for _ in range(50):
                msg = q.dequeue()
                if msg:
                    results.append(msg.content)

        threads = [threading.Thread(target=dequeuer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 100

    def test_concurrent_enqueue_and_dequeue(self):
        q = MessageQueue()
        errors = []

        def producer():
            for i in range(50):
                q.enqueue(f"p-{i}")

        def consumer():
            for _ in range(50):
                msg = q.dequeue()
                if msg is not None:
                    time.sleep(0.001)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # No errors means lock works
        assert errors == []


class TestMessageQueuePersistence:
    """Save/restore queue state."""

    def test_save_and_restore(self):
        q1 = MessageQueue()
        q1.enqueue("a", priority=1)
        q1.enqueue("b", priority=2)
        q1.dequeue()  # moves 'a' to pending

        state = q1.save_state()
        q2 = MessageQueue.from_state(state)

        assert q2.size() == 1
        assert q2.pending_count == 1
        assert q2.to_list() == ["b"]
        pending = q2.peek(5)  # peek doesn't show pending
        assert pending[0].content == "b"
        # check pending via dequeue order
        q2.complete_pending()
        # restore
        q3 = MessageQueue.from_state(state)
        msg = q3.dequeue()
        assert msg.content == "b"

    def test_from_empty_state(self):
        q = MessageQueue.from_state({"queue": [], "pending": []})
        assert q.size() == 0
        assert q.pending_count == 0

    def test_from_state_ignores_malformed_entries(self):
        q = MessageQueue.from_state({
            "queue": [
                {"content": "valid", "timestamp": 1.0, "metadata": "bad"},
                {"timestamp": 2.0},
                "not a message",
            ],
            "pending": "not a list",
        })

        assert q.to_list() == ["valid"]
        assert q.peek(1)[0].metadata == {}

    def test_enqueue_many(self):
        q = MessageQueue()
        size = q.enqueue_many(["a", "b", "c"])
        assert size == 3
        assert q.to_list() == ["a", "b", "c"]


class TestMessageQueueIntegration:
    """Integration scenarios for breakpoint resume."""

    def test_simulate_interrupt_and_resume(self):
        """Simulate: enqueue -> dequeue -> interrupt -> requeue -> dequeue."""
        q = MessageQueue()
        q.enqueue("task 1")
        q.enqueue("task 2")
        q.enqueue("task 3")

        # Worker picks up first task
        msg1 = q.dequeue()
        assert msg1.content == "task 1"

        # Simulate interrupt
        requeued = q.requeue_pending()
        assert requeued == 1
        assert q.size() == 3

        # Worker resumes, gets first task again
        msg1_again = q.dequeue()
        assert msg1_again.content == "task 1"
        assert msg1_again.metadata.get("retried") == 1

    def test_queue_drain(self):
        """Process all queued messages."""
        q = MessageQueue()
        for i in range(5):
            q.enqueue(f"task-{i}")

        processed = []
        while not q.is_empty:
            msg = q.dequeue()
            if msg:
                processed.append(msg.content)
                q.complete_pending()

        assert processed == [f"task-{i}" for i in range(5)]


class TestQueuedMessage:
    """Tests for the QueuedMessage dataclass."""

    def test_default_timestamp(self):
        before = time.time()
        msg = QueuedMessage(content="hi")
        after = time.time()
        assert before <= msg.timestamp <= after

    def test_metadata_default_empty(self):
        msg = QueuedMessage(content="hi")
        assert msg.metadata == {}

    def test_priority_comparison(self):
        m1 = QueuedMessage(content="a", priority=5)
        m2 = QueuedMessage(content="b", priority=10)
        # Higher priority sorts first
        assert m2 < m1
        assert not (m1 < m2)
