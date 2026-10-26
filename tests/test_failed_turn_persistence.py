"""A failed turn's cleanup must survive SQLite and keep undo exact.

``save_messages`` writes incrementally and rewrites in full only when the
history shrinks, so removing messages from the middle of a history that was
already checkpointed is the case worth pinning: stale rows must not outlive the
cleanup, and the retrieval-block flag must still pair the block with its prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import MethodType, SimpleNamespace

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.plan_guard import PLAN_ONLY_NO_TOOLS_SIGNAL, PLAN_ONLY_RECOVERY_SIGNAL
from core.plan_recovery import purge_messages
from tests.test_memory_reliability import isolated_memory  # noqa: F401

PLAN = "<plan><intent>Continue the pending action.</intent></plan>"


def _failed_turn_history():
    """System, an executed batch, then a turn whose recovery hit the limit."""
    context = {"role": "assistant", "content": "[Retrieved Context]", "_turn_context": True}
    prompt = {"role": "user", "content": "write the file"}
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "write_file", "arguments": "{}"}}
        ],
    }
    result = {"role": "tool", "tool_call_id": "call_1", "content": "OK: wrote x"}
    artifacts = [
        {"role": "assistant", "content": PLAN},
        {"role": "user", "content": PLAN_ONLY_RECOVERY_SIGNAL},
        {"role": "assistant", "content": PLAN},
        {"role": "user", "content": PLAN_ONLY_NO_TOOLS_SIGNAL},
        {"role": "assistant", "content": PLAN},
    ]
    history = [{"role": "system", "content": "sys"}, context, prompt, call, result, *artifacts]
    return history, artifacts


def _sid(memory, name):
    memory.upsert_session(
        session_id=name, name="", model="ds-v4-flash", cwd="/tmp",
        config_dict={}, workspace_dir="/tmp/ws",
    )
    return name


def test_cleanup_after_a_checkpoint_leaves_no_stale_rows(isolated_memory):
    memory = isolated_memory
    sid = _sid(memory, "sess_failed_turn_checkpointed")
    history, artifacts = _failed_turn_history()

    # A mid-recovery checkpoint (iteration autosave, scheduler transition)
    # already wrote the plan-only replies and nudges.
    memory.save_messages(sid, history)
    assert len(memory.load_messages(sid)) == len(history) - 1  # system is not stored

    assert purge_messages(history, artifacts) == len(artifacts)
    memory.save_messages(sid, history)  # the failed-turn autosave

    loaded = memory.load_messages(sid)
    assert [(m["role"], m["content"]) for m in loaded] == [
        (m["role"], m["content"] or "") for m in history[1:]
    ]
    assert not any("PLAN_ONLY" in m["content"] for m in loaded)
    assert not any(m["content"] == PLAN for m in loaded)
    # The flag that pairs the retrieval block with its prompt round-trips ...
    assert loaded[0]["_turn_context"] is True
    # ... and so does the executed tool batch.
    assert loaded[2]["tool_calls"][0]["id"] == "call_1"
    assert loaded[3]["tool_call_id"] == "call_1"


def test_undo_after_reload_takes_the_failed_prompt_and_its_block_together(isolated_memory):
    memory = isolated_memory
    from core.session import AgentSession

    sid = _sid(memory, "sess_failed_turn_undo")
    prompt_only = [
        {"role": "assistant", "content": "[Retrieved Context]", "_turn_context": True},
        {"role": "user", "content": "list the files"},
    ]
    artifacts = [
        {"role": "assistant", "content": PLAN},
        {"role": "user", "content": PLAN_ONLY_RECOVERY_SIGNAL},
    ]
    history = [{"role": "system", "content": "sys"}, *prompt_only, *artifacts]
    memory.save_messages(sid, history)
    purge_messages(history, artifacts)
    memory.save_messages(sid, history)

    stub = SimpleNamespace(messages=memory.load_messages(sid))
    stub._pop_orphan_turn_context_block = MethodType(
        AgentSession._pop_orphan_turn_context_block, stub
    )
    removed, last_user_text = AgentSession.undo(stub, 1)

    # Before the cleanup existed the tail was a recovery nudge: undo returned
    # the nudge's text as "the prompt" and left the real prompt behind.
    assert removed == 2
    assert last_user_text == "list the files"
    assert stub.messages == []
