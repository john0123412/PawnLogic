"""What the model is shown of a tool result, independent of how the UI renders.

The incident: in the default user-friendly mode every tool result was
head/tail-trimmed to 30+30 lines, and ``list_dir`` sorted dot-directories ahead
of ordinary ones, so a 90-entry home directory reached the model with all
sixteen ordinary directories (including the project) cut from the middle. The
model concluded there was no project.
"""

from __future__ import annotations

from types import SimpleNamespace

from core import delegation_runtime
from core.tool_registry import ToolRegistry, ToolSpec
from core.tool_result import ANSI_PRESERVING_TOOLS, ToolResultProcessor, model_facing_text
from tools import file_ops
from utils.ansi import BLUE, GRAY, c, strip_ansi

ESC = "\x1b"


def _crowded_home(root):
    """36 dot-dirs + 16 ordinary dirs + 10 dot-files + 30 files = 92 entries."""
    for index in range(36):
        (root / f".cache{index:02d}").mkdir()
    for index in range(16):
        (root / f"projdir{index:02d}").mkdir()
    for index in range(10):
        (root / f".dotfile{index:02d}").write_text("x", encoding="utf-8")
    for index in range(30):
        (root / f"notes{index:02d}.txt").write_text("x", encoding="utf-8")
    return root


def _process(tool_name: str, result: str, max_chars: int = 6000) -> str:
    processor = ToolResultProcessor(auto_intuitive_search=lambda _query: "")
    return processor.process(
        result=result,
        tool_name=tool_name,
        fn_args={},
        args_preview="",
        audit_ok=True,
        elapsed_ms=1,
        failure_warning="",
        iteration=0,
        max_chars=max_chars,
    ).content


def test_list_dir_puts_ordinary_entries_before_hidden_ones(tmp_path):
    home = _crowded_home(tmp_path)

    lines = strip_ansi(file_ops.tool_list_dir({"path": str(home)})).splitlines()
    names = [line.split()[1] for line in lines]  # "  📁 name/" or "  📄 name  1B"

    assert len(names) == 92
    hidden = [index for index, name in enumerate(names) if name.startswith(".")]
    ordinary = [index for index in range(92) if index not in hidden]
    assert (len(ordinary), len(hidden)) == (46, 46)
    # Every ordinary entry precedes every hidden one, directories first.
    assert max(ordinary) < min(hidden)
    ordinary_names = [names[index] for index in ordinary]
    assert ordinary_names[:16] == [f"projdir{i:02d}/" for i in range(16)]


def test_ninety_two_entry_listing_reaches_the_model_with_every_ordinary_directory(tmp_path):
    home = _crowded_home(tmp_path)
    listing = file_ops.tool_list_dir({"path": str(home)})

    seen = _process("list_dir", listing)

    for index in range(16):
        assert f"projdir{index:02d}/" in seen
    assert "lines truncated for token efficiency" not in seen
    assert ESC not in seen


def test_listing_longer_than_the_budget_loses_hidden_entries_first(tmp_path):
    home = _crowded_home(tmp_path)
    listing = file_ops.tool_list_dir({"path": str(home)})

    # A budget well under the listing's size: the cut must fall on the tail.
    seen = _process("list_dir", listing, max_chars=1000)

    assert "[truncated to 1000 chars]" in seen
    assert ".cache00" not in seen  # hidden entries are what the cut removed
    for index in range(16):
        assert f"projdir{index:02d}/" in seen


def test_model_facing_text_never_contains_terminal_escapes():
    colored = (
        c(BLUE, "  📁 src/") + "\n"
        + "  📄 main.py  " + c(GRAY, "12B") + "\n"
        + "\x1b]0;window title\x07"  # an OSC sequence a tool might echo back
    )

    # run_shell is the one exemption and has its own test below; run_code is
    # deliberately not exempt (see ANSI_PRESERVING_TOOLS).
    for tool in ("list_dir", "read_file_lines", "run_code"):  # budget and head/tail paths
        seen = _process(tool, colored)
        assert ESC not in seen
        assert "src/" in seen and "main.py" in seen and "12B" in seen


def test_escapes_do_not_eat_the_character_budget():
    colored = "".join(c(BLUE, "x") for _ in range(400))  # 400 visible, ~3000 raw chars

    seen = _process("list_dir", colored, max_chars=1000)

    assert seen == "x" * 400


# A CTF challenge can hide data in the escape sequences themselves: a cursor
# move that overwrites what a terminal shows, an OSC title, an SGR run that
# paints text invisible.  Stripping them before the model sees run_shell output
# would delete the evidence.
HIDDEN_IN_ESCAPES = (
    "visible line\n"
    "\x1b[8mflag{hidden_by_sgr_conceal}\x1b[0m\n"            # concealed text
    "decoy\x1b[5D\x1b[Kreal\n"                                   # cursor move + erase
    "\x1b]0;flag{in_the_window_title}\x07\n"                    # OSC title
)


def test_run_shell_keeps_its_escape_sequences_byte_for_byte():
    seen = _process("run_shell", HIDDEN_IN_ESCAPES)

    assert seen == HIDDEN_IN_ESCAPES
    assert "flag{hidden_by_sgr_conceal}" in seen
    assert "\x1b]0;flag{in_the_window_title}\x07" in seen


def test_only_run_shell_is_exempt_from_stripping():
    # run_code is an open question for the owner, so its stripping is pinned
    # here: widening the exemption has to change this assertion on purpose.
    assert frozenset({"run_shell"}) == ANSI_PRESERVING_TOOLS
    for tool in ("list_dir", "read_file", "read_file_lines", "run_code", "web_search", "fetch_url"):
        assert model_facing_text(tool, HIDDEN_IN_ESCAPES) == strip_ansi(HIDDEN_IN_ESCAPES)
        assert ESC not in _process(tool, HIDDEN_IN_ESCAPES)
    assert model_facing_text("run_shell", HIDDEN_IN_ESCAPES) == HIDDEN_IN_ESCAPES


def test_run_shell_escapes_still_count_against_the_head_tail_trim():
    # The exemption keeps the bytes; it does not lift the 30+30 line trim that
    # run_shell output already had, and an escape in the kept head survives it.
    lines = [f"\x1b[31mline{index:03d}\x1b[0m" for index in range(200)]

    seen = _process("run_shell", "\n".join(lines))

    assert "\x1b[31mline000\x1b[0m" in seen and "\x1b[31mline199\x1b[0m" in seen
    assert "line100" not in seen
    assert "lines truncated for token efficiency" in seen


def _delegated_tool_message(monkeypatch, tool_name: str, output: str) -> str:
    """Run a delegated worker through one tool call and return the tool message."""
    handler = lambda _args: output
    registry = ToolRegistry()
    registry.register_many_owned(
        "builtin",
        [
            ToolSpec(
                name=tool_name,
                handler=handler,
                schema={
                    "type": "function",
                    "function": {"name": tool_name, "parameters": {"type": "object"}},
                },
            )
        ],
    )
    responses = iter(
        [
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                tool_calls={0: {"id": "call-1", "name": tool_name, "args": "{}"}},
                text="",
            ),
            SimpleNamespace(
                error=None,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                tool_calls={},
                text="done",
            ),
        ]
    )
    monkeypatch.setattr(delegation_runtime, "_tool_map", lambda: {tool_name: handler})
    monkeypatch.setattr(
        delegation_runtime,
        "_tools_schema",
        lambda: [{"type": "function", "function": {"name": tool_name}}],
    )
    monkeypatch.setattr(delegation_runtime, "_tool_capabilities", lambda: {})
    monkeypatch.setattr(
        delegation_runtime, "_tool_execution_resolver", lambda: registry.resolve_for_execution
    )
    monkeypatch.setattr(
        delegation_runtime,
        "runtime_config",
        lambda: {"max_tokens": 100, "tool_max_chars": 6000},
    )
    monkeypatch.setattr(delegation_runtime, "stream_request", lambda *_a, **_k: object())
    monkeypatch.setattr(
        delegation_runtime, "consume_model_stream", lambda *_a, **_k: next(responses)
    )

    worker = delegation_runtime.SubAgentSession("run it", "worker", context_mode="none")

    assert worker.run() == "done"
    tool_messages = [m for m in worker.messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    return tool_messages[0]["content"]


def test_delegated_worker_tool_results_are_escape_free_too(monkeypatch):
    content = _delegated_tool_message(
        monkeypatch, "list_dir", c(BLUE, "  📁 src/") + "\n" + c(GRAY, "12B")
    )

    assert ESC not in content
    assert "src/" in content


def test_delegated_worker_run_shell_keeps_its_escape_sequences(monkeypatch):
    content = _delegated_tool_message(monkeypatch, "run_shell", HIDDEN_IN_ESCAPES)

    # The same rule as the main loop, from the same helper: a worker investigating
    # a CTF challenge must see the bytes the challenge hides data in.
    assert content == HIDDEN_IN_ESCAPES
