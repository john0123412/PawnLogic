"""Regression tests for provider management commands."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from prompt_toolkit.document import Document
from prompt_toolkit.application import Application

import main as pawn_main
import pawnlogic.cli as pawn_cli
from config import providers as provider_config
from core.api_errors import format_http_error
from core import provider_runtime, provider_tui
from core import provider_tui_rows as rows_mod
from core.commands import provider as provider_cmd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _isolate_provider_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(provider_runtime, "PAWNLOGIC_DIR", tmp_path)
    monkeypatch.setattr(provider_runtime, "ENV_PATH", env_path)
    monkeypatch.setattr(provider_cmd, "ENV_PATH", env_path)
    return env_path


def test_write_key_to_shell_stores_key_in_private_dot_env_not_shell_rc(tmp_path, monkeypatch):
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("# shell config\n", encoding="utf-8")
    env_path = _isolate_provider_env(tmp_path, monkeypatch)
    key = "sk-value_with$dollar`tick'quote"
    monkeypatch.delenv("WEIRD_API_KEY", raising=False)

    written_to = provider_cmd._write_key_to_shell("WEIRD_API_KEY", key)

    assert written_to == str(env_path)
    assert bashrc.read_text(encoding="utf-8") == "# shell config\n"
    assert env_path.read_text(encoding="utf-8") == f"WEIRD_API_KEY={key}\n"
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert os.environ["WEIRD_API_KEY"] == key
    os.environ.pop("WEIRD_API_KEY", None)


def test_write_key_to_shell_replaces_existing_dot_env_value_without_touching_shell_rc(
    tmp_path,
    monkeypatch,
):
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("export EXISTING_API_KEY='old value'\n", encoding="utf-8")
    env_path = _isolate_provider_env(tmp_path, monkeypatch)
    env_path.write_text("EXISTING_API_KEY=old-value\n", encoding="utf-8")
    monkeypatch.delenv("EXISTING_API_KEY", raising=False)

    provider_cmd._write_key_to_shell("EXISTING_API_KEY", "new value")

    assert bashrc.read_text(encoding="utf-8") == "export EXISTING_API_KEY='old value'\n"
    assert env_path.read_text(encoding="utf-8") == "EXISTING_API_KEY=new value\n"
    assert os.environ["EXISTING_API_KEY"] == "new value"
    os.environ.pop("EXISTING_API_KEY", None)


def test_provider_tui_add_wizard_api_key_field_accepts_pasted_text():
    tui = provider_tui.ProviderTUI()
    pasted_key = "sk-pasted-key-with-symbols_1234567890"

    tui._wiz_inputs[0].text = "relay"
    tui._wiz_inputs[1].text = "https://api.example.com/v1"
    tui._wiz_fields[rows_mod.ROW_FORMAT] = "openai"
    tui._wiz_inputs[2].text = pasted_key

    tui._sync_wizard_fields_from_inputs()

    # Compared by row, not as a literal list: this list grew from four entries
    # to five when the Auth row was added, and a positional assertion is what
    # silently mis-maps the password field onto the Auth dropdown.
    assert tui._wiz_fields[rows_mod.ROW_NAME] == "relay"
    assert tui._wiz_fields[rows_mod.ROW_URL] == "https://api.example.com/v1"
    assert tui._wiz_fields[rows_mod.ROW_FORMAT] == "openai"
    assert tui._wiz_fields[rows_mod.ROW_AUTH] == "auto"
    assert tui._wiz_fields[rows_mod.ROW_KEY] == pasted_key


def test_provider_tui_add_wizard_navigation_moves_real_input_focus():
    tui = provider_tui.ProviderTUI()
    tui._panel = "wizard"
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    next_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_w_next")

    assert app.layout.current_control is tui._wiz_inputs[0].control

    next_handler(SimpleNamespace(app=app))

    assert tui._wiz_focus == rows_mod.ROW_URL
    assert app.layout.current_control is tui._wiz_inputs[1].control

    next_handler(SimpleNamespace(app=app))
    assert tui._wiz_focus == rows_mod.ROW_FORMAT
    next_handler(SimpleNamespace(app=app))

    # The Auth row has no TextArea -- it is a dropdown -- so keyboard focus
    # stays where it was while the row cursor advances.
    assert tui._wiz_focus == rows_mod.ROW_AUTH
    assert rows_mod.input_slot_for_row(tui._wiz_focus) is None

    next_handler(SimpleNamespace(app=app))

    assert tui._wiz_focus == rows_mod.ROW_KEY
    assert app.layout.current_control is tui._wiz_inputs[2].control


def test_provider_tui_wizard_shows_caret_at_the_real_buffer_position():
    """The Add Provider form is drawn by hand, so nothing else marks the caret."""
    tui = provider_tui.ProviderTUI()
    tui._panel = "wizard"
    tui._wiz_inputs[0].text = "openrouter"
    tui._wiz_inputs[0].buffer.cursor_position = 4
    tui._wiz_focus = 0

    rendered = "".join(text for _style, text in tui._render_wizard())

    assert "open\u258cro" in rendered          # caret sits mid-word, not at the end
    assert rendered.count("\u258c") == 1       # only the focused field shows one
    assert "\u25b6\u2460 Name" in rendered     # the focused row is marked


def test_provider_tui_wizard_marks_exactly_one_row_at_a_time():
    tui = provider_tui.ProviderTUI()
    tui._panel = "wizard"
    tui._wiz_inputs[0].text = "relay"
    tui._wiz_inputs[1].text = "https://api.example.com/v1"
    tui._wiz_inputs[2].text = "sk-secret-1234567890"

    # Driven off the row table, so adding a row updates this test rather than
    # leaving a hardcoded marker count pointing at the wrong field.
    circled = "\u2460\u2461\u2462\u2463\u2464"
    for row in range(rows_mod.ROW_SAVE):
        tui._wiz_focus = row
        rendered = "".join(text for _style, text in tui._render_wizard())
        marked = [f"\u25b6{mark}" for mark in circled if f"\u25b6{mark}" in rendered]
        assert marked == [f"\u25b6{circled[row]}"], (
            f"focus {row} should mark exactly one row, got {marked}"
        )

    tui._wiz_focus = rows_mod.ROW_SAVE
    rendered = "".join(text for _style, text in tui._render_wizard())
    assert "\u25b6 [ Save Provider ]" in rendered

    # The API key stays masked, and the caret rides the masked string.
    tui._wiz_focus = rows_mod.ROW_KEY
    rendered = "".join(text for _style, text in tui._render_wizard())
    assert "sk-secret" not in rendered
    assert "\u2022" in rendered and "\u258c" in rendered


def _dialog_key_handlers(tui, key):
    """Matching handler names for `key`, in prompt_toolkit resolution order."""
    from prompt_toolkit.keys import Keys as _Keys

    mapping = {"enter": _Keys.ControlM, "up": _Keys.Up, "down": _Keys.Down,
               "left": _Keys.Left, "right": _Keys.Right, "tab": _Keys.Tab}
    return [b.handler for b in tui._build_kb().get_bindings_for_keys((mapping[key],))
            if b.filter()]


def _open_delete_modal(tui):
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    tui._dialog = "delete"
    tui._dialog_cursor = 0
    return tui


def test_provider_tui_delete_modal_marks_the_focused_button():
    """The confirm dialog rendered focus with background colour only.

    Colour is the sole indicator, so the focused button is invisible in a
    stripped or piped terminal \u2014 the user cannot tell where Enter will land.
    """
    tui = _open_delete_modal(provider_tui.ProviderTUI())

    tui._dialog_cursor = 0
    on_cancel = "".join(text for _s, text in tui._render_dialog())
    tui._dialog_cursor = 1
    on_delete = "".join(text for _s, text in tui._render_dialog())

    assert "\u25b6 [ Cancel ]" in on_cancel
    assert "\u25b6 [ Delete ]" in on_delete
    assert on_cancel.count("\u25b6") == 1
    assert on_delete.count("\u25b6") == 1


def test_provider_tui_delete_modal_navigates_with_every_arrow_key():
    """Only left/right/tab moved the dialog cursor; up/down were unbound."""
    tui = _open_delete_modal(provider_tui.ProviderTUI())

    for key in ("up", "down", "left", "right"):
        handlers = _dialog_key_handlers(tui, key)
        assert handlers, f"{key} does nothing inside the confirm dialog"
        tui._dialog_cursor = 0
        handlers[-1](None)          # _dlg_move ignores the event
        assert tui._dialog_cursor == 1, f"{key} did not reach [ Delete ]"


def test_provider_tui_delete_modal_deletes_after_moving_to_delete():
    tui = _open_delete_modal(provider_tui.ProviderTUI())
    calls = []
    tui._do_delete_provider = lambda: calls.append("deleted")

    _dialog_key_handlers(tui, "right")[-1](None)
    assert tui._dialog_cursor == 1
    _dialog_key_handlers(tui, "enter")[-1](None)

    assert calls == ["deleted"]
    assert tui._dialog is None


def test_provider_tui_delete_modal_default_enter_still_declines():
    """Denying by default is the safety invariant \u2014 Enter on Cancel deletes nothing."""
    tui = _open_delete_modal(provider_tui.ProviderTUI())
    calls = []
    tui._do_delete_provider = lambda: calls.append("deleted")

    assert tui._dialog_cursor == 0
    _dialog_key_handlers(tui, "enter")[-1](None)

    assert calls == []
    assert tui._dialog is None


def test_provider_tui_model_search_field_accepts_pasted_text():
    tui = provider_tui.ProviderTUI()
    pasted_model_name = "provider-prefix/some-long-model-name-v1"

    tui._ms_search_ta.text = pasted_model_name

    tui._sync_model_search_from_input()
    assert tui._ms_search == pasted_model_name


def test_provider_tui_model_selector_reopens_without_the_previous_search_query():
    """A second Fetch/Sync must not inherit the previous selector's query.

    The search TextArea outlives a selection session, and
    ``begin_model_selection`` only resets the mirrored state field, so the
    selector reopened already filtered by a query the user had forgotten. When
    that leftover query matched nothing the list came up empty, leaving no
    checkbox to tick at all.
    """
    candidates = [
        ("model-a", {"id": "model-a", "provider": "relay"}),
        ("model-b", {"id": "model-b", "provider": "relay"}),
    ]

    def open_session(tui):
        tui._begin_model_selection(
            provider="relay",
            caller="detail",
            candidates=candidates,
            existing_ids=set(),
            notices=[],
        )

    tui = provider_tui.ProviderTUI()
    open_session(tui)

    # Session one: the user searches, then cancels with the box still filled.
    tui._ms_search_ta.text = "model-b"
    tui._ms_search_focus = True
    tui._sync_model_search_from_input()
    tui._ms_search_focus = False
    tui._cancel_model_selector()

    # Session two: a fresh fetch of the same provider.
    open_session(tui)
    rendered = "".join(text for _style, text in tui._render_model_select())

    assert tui._ms_search_ta.text == ""
    assert tui._ms_search == ""
    assert rendered.count("[ ]") == len(candidates)
    assert "🔍 Search: \n" in rendered


def test_provider_tui_model_selector_marks_the_focused_action_button_in_text():
    """Focus must survive a terminal that strips colour.

    The three selector actions are colour-only, unlike the provider detail
    menu and the delete dialog, so the user could not see where Enter would
    land.
    """
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [("model-a", {"id": "model-a", "provider": "relay"})]
    total = len(tui._ms_all)

    for offset, label in ((0, "Load Selected"), (1, "Load & Close"), (2, "Cancel")):
        tui._ms_cursor = total + offset
        rendered = "".join(text for _style, text in tui._render_model_select())
        assert f"▶ [ {label} ]" in rendered, label
        for other, other_label in (
            (0, "Load Selected"),
            (1, "Load & Close"),
            (2, "Cancel"),
        ):
            if other != offset:
                assert f"▶ [ {other_label} ]" not in rendered


def test_provider_tui_model_selector_reaches_the_action_row_without_walking_every_model():
    """Saving must not cost one Down press per model in the list.

    openrouter returns hundreds of models, and the action row sat at cursor
    index N, so loading a ticked model needed 200 presses of Down (or ten of
    PageDown) with no shortcut offered. The buttons are always painted at the
    bottom of the panel, so they have to stay reachable from anywhere in the
    list.
    """
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [
        (f"vendor{i // 10}/model-{i}", {"id": f"vendor{i // 10}/model-{i}"})
        for i in range(200)
    ]
    kb = tui._build_kb()
    handlers = {b.handler.__name__: b.handler for b in kb.bindings}
    total = len(tui._ms_all)

    # One key lands on Load Selected from deep inside the list.
    tui._ms_cursor = 137
    handlers["_ms_to_actions"](None)
    assert tui._ms_cursor == total

    # The three actions remain distinct and reachable from there.
    handlers["_ms_dn"](None)
    assert tui._ms_cursor == total + 1
    handlers["_ms_dn"](None)
    assert tui._ms_cursor == total + 2
    handlers["_ms_dn"](None)
    assert tui._ms_cursor == total + 2

    # ...and Up walks back out through them into the list.
    handlers["_ms_up"](None)
    assert tui._ms_cursor == total + 1
    handlers["_ms_up"](None)
    assert tui._ms_cursor == total
    handlers["_ms_up"](None)
    assert tui._ms_cursor == total - 1

    # The jump is available from anywhere, not only from the last page.
    tui._ms_cursor = 0
    handlers["_ms_to_actions"](None)
    assert tui._ms_cursor == total


def test_provider_tui_model_selector_saves_without_reaching_the_action_row():
    """``L`` then ``Enter`` was the only way to load a ticked model.

    The action row still has to exist, but a selection made in the middle of a
    long list should not require walking to it first. ``s`` loads and stays,
    ``S`` loads and closes, matching the existing ``a``/``A`` and ``l``/``L``
    pairs.
    """
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [
        (f"vendor{i // 10}/model-{i}", {"id": f"vendor{i // 10}/model-{i}"})
        for i in range(200)
    ]
    kb = tui._build_kb()
    handlers = {b.handler.__name__: b.handler for b in kb.bindings}

    saved: list[bool] = []
    tui._do_save_models = lambda: saved.append(tui._ms_save_exit)

    # Ticking works with Enter alone; Space is not required to select.
    handlers["_ms_enter"](None)
    assert tui._ms_selected == {"vendor0/model-0"}
    handlers["_ms_enter"](None)
    assert tui._ms_selected == set()

    handlers["_ms_dn"](None)
    handlers["_ms_space"](None)
    assert tui._ms_selected == {"vendor0/model-1"}

    # Mid-list, with the cursor nowhere near the buttons: save directly.
    assert tui._ms_cursor == 1
    handlers["_ms_save"](None)
    assert saved == [False]
    assert tui._ms_selected == {"vendor0/model-1"}

    # S is the close-after-load variant.
    handlers["_ms_save_close"](None)
    assert saved == [False, True]

    # An empty selection is refused exactly as it is on the action row, so
    # the shortcut cannot silently load nothing.
    tui._ms_selected.clear()
    handlers["_ms_save"](None)
    assert saved == [False, True]
    assert tui._ms_error


def test_provider_tui_model_selector_advertises_its_keys_including_the_jump():
    """The panel never told the user how to reach the buttons."""
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [("model-a", {"id": "model-a", "provider": "relay"})]
    rendered = "".join(text for _style, text in tui._render_model_select())
    assert "Space/Enter toggle" in rendered
    assert "Load Selected" in rendered
    # Saving without walking to the action row.
    assert "s save" in rendered


def test_pawn_completer_includes_live_visible_models_without_rebuild():
    completer = pawn_main.PawnCompleter(
        ["/model", "/model ds-v4-flash"],
        meta_dict={"/model": "switch", "/model ds-v4-flash": "DeepSeek"},
        dynamic_model_provider=lambda: {
            "1:gpt-5.5": {"desc": "Dynamically fetched model"},
        },
    )

    completions = list(completer.get_completions(Document("/model"), None))
    words = [completion.text for completion in completions]
    meta_by_word = {completion.text: completion.display_meta_text for completion in completions}

    assert "/model 1:gpt-5.5" in words
    assert meta_by_word["/model 1:gpt-5.5"] == "Dynamically fetched model"
    assert "/model 1:gpt-5.5" not in completer.meta_dict
    assert "/agent policy model allow 1:gpt-5.5" in words
    assert "/agent policy model deny 1:gpt-5.5" in words


def test_packaged_cli_completer_includes_live_visible_models_without_rebuild():
    completer = pawn_cli.PawnCompleter(
        ["/model", "/model ds-v4-flash"],
        meta_dict={"/model": "switch", "/model ds-v4-flash": "DeepSeek"},
        dynamic_model_provider=lambda: {
            "1:gpt-5.5": {"desc": "Dynamically fetched model"},
        },
    )

    completions = list(completer.get_completions(Document("/model"), None))
    words = [completion.text for completion in completions]
    meta_by_word = {completion.text: completion.display_meta_text for completion in completions}

    assert "/model 1:gpt-5.5" in words
    assert meta_by_word["/model 1:gpt-5.5"] == "Dynamically fetched model"
    assert "/model 1:gpt-5.5" not in completer.meta_dict
    assert "/agent policy model allow 1:gpt-5.5" in words
    assert "/agent policy model deny 1:gpt-5.5" in words


def _assert_fuzzy_command_completion(completer_cls):
    query = "/plg"
    completer = completer_cls(
        ["/plan", "/planguard", "/provider"],
        meta_dict={"/planguard": "Configure plan guard"},
    )

    completions = list(completer.get_completions(Document(query), None))

    assert [completion.text for completion in completions] == ["/planguard"]
    assert completions[0].start_position == -len(query)
    assert completions[0].display_meta_text == "Configure plan guard"


def test_main_pawn_completer_supports_fuzzy_command_completion():
    _assert_fuzzy_command_completion(pawn_main.PawnCompleter)


def test_packaged_cli_completer_supports_fuzzy_command_completion():
    _assert_fuzzy_command_completion(pawn_cli.PawnCompleter)


def test_fallback_completer_returns_compatible_completion_objects(tmp_path):
    script = """
from types import SimpleNamespace

from pawnlogic.cli import PawnCompleter

query = "/plg"
items = list(
    PawnCompleter(
        ["/plan", "/planguard"],
        meta_dict={"/planguard": "Configure plan guard"},
    ).get_completions(SimpleNamespace(text_before_cursor=query), None)
)
assert [item.text for item in items] == ["/planguard"]
assert items[0].start_position == -len(query)
assert items[0].display_meta_text == "Configure plan guard"
"""
    env = os.environ.copy()
    env.update(
        {
            "PAWNLOGIC_HOME": str(tmp_path),
            "PAWNLOGIC_TEST_MODE": "true",
            "MCP_ENABLED": "false",
            "PROMPT_TOOLKIT_ENABLED": "0",
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _assert_ultra_fuzzy_command_completion(completer_cls):
    query = "/ult"
    completer = completer_cls(
        ["/max", "/ultra", "/limits"],
        meta_dict={"/ultra": "Ultra mode"},
    )

    completions = list(completer.get_completions(Document(query), None))

    assert [completion.text for completion in completions] == ["/ultra"]
    assert completions[0].start_position == -len(query)
    assert completions[0].display_meta_text == "Ultra mode"


def test_main_pawn_completer_supports_ultra_fuzzy_completion():
    _assert_ultra_fuzzy_command_completion(pawn_main.PawnCompleter)


def test_packaged_cli_completer_supports_ultra_fuzzy_completion():
    _assert_ultra_fuzzy_command_completion(pawn_cli.PawnCompleter)


def _assert_registered_command_fuzzy_completion(pawn_module):
    from core.commands import COMMANDS

    words = pawn_module._builtin_command_completion_words()
    assert set(COMMANDS).issubset(words)

    completions = list(
        pawn_module.PawnCompleter(words).get_completions(Document("/plg"), None)
    )
    assert "/planguard" in {completion.text for completion in completions}


def test_main_registered_command_catalog_supports_planguard_fuzzy_completion():
    _assert_registered_command_fuzzy_completion(pawn_main)


def test_packaged_registered_command_catalog_supports_planguard_fuzzy_completion():
    _assert_registered_command_fuzzy_completion(pawn_cli)


def test_readline_command_candidates_support_fuzzy_matching():
    assert pawn_cli._matching_command_words(
        "/plg", ["/plan", "/planguard", "/provider"]
    ) == ["/planguard"]


def _assert_runtime_registered_command_completion(pawn_module):
    from core.commands import register_owned_commands, unregister_owned_commands

    async def handler(_ctx):
        return None

    owner = f"test-completion-catalog-{pawn_module.__name__}"
    register_owned_commands(owner, {"/catalogcheck": handler})
    try:
        completer = pawn_module.PawnCompleter(
            ["/help"],
            dynamic_command_provider=pawn_module._builtin_command_completion_words,
        )
        completions = list(completer.get_completions(Document("/ctc"), None))
        assert "/catalogcheck" in {completion.text for completion in completions}
    finally:
        unregister_owned_commands(owner)


def test_main_registered_command_catalog_refreshes_runtime_commands():
    _assert_runtime_registered_command_completion(pawn_main)


def test_packaged_registered_command_catalog_refreshes_runtime_commands():
    _assert_runtime_registered_command_completion(pawn_cli)


def test_readline_command_candidates_include_runtime_registered_commands():
    from core.commands import register_owned_commands, unregister_owned_commands

    async def handler(_ctx):
        return None

    owner = "test-readline-completion-catalog"
    register_owned_commands(owner, {"/catalogcheck": handler})
    try:
        candidates = pawn_cli._readline_command_candidates(["/provider list"])
        assert "/catalogcheck" in candidates
        assert "/provider list" in candidates
    finally:
        unregister_owned_commands(owner)


def test_packaged_cli_completer_refreshes_extension_names_and_subcommands_live():
    visible = {"security": "Extension (disabled)"}
    completer = pawn_cli.PawnCompleter(
        ["/extension", "/extension enable", "/extension disable", "/extension status"],
        meta_dict={"/extension": "Manage installed Extensions"},
        dynamic_extension_provider=lambda: visible,
    )

    first = list(completer.get_completions(Document("/extension enable "), None))
    assert "/extension enable security" in {item.text for item in first}

    visible.clear()
    visible["browser"] = "Extension (enabled)"
    second = list(completer.get_completions(Document("/extension enable "), None))
    second_words = {item.text for item in second}
    assert "/extension enable browser" in second_words
    assert "/extension enable security" not in second_words
    assert all("security" not in item.text for item in second)


def test_provider_completion_covers_every_dispatched_subcommand():
    """Every dispatched ``/provider`` subcommand must also be completable.

    ``/provider effort`` shipped with a handler and README documentation but no
    completion entry, so it was reachable only by typing it exactly. The two
    lists live in different files and are maintained by hand, so this compares
    them instead of trusting either one. Only the first name of a
    ``sub in (...)`` group is canonical; the rest are aliases (``/provider
    active`` for ``activate``) and are deliberately not advertised.
    """
    import re

    source = Path(ROOT, "core", "commands", "provider.py").read_text(encoding="utf-8")
    body = source[source.index("async def _handle_provider_cmd("):]
    canonical = set(re.findall(r'\bsub == "([a-z]+)"', body))
    for group in re.findall(r"\bsub in \(([^)]*)\)", body):
        names = re.findall(r'"([a-z]+)"', group)
        canonical.update(names[:1])

    cli_source = Path(ROOT, "pawnlogic", "cli.py").read_text(encoding="utf-8")
    start = cli_source.index("# Provider subcommands.")
    block = cli_source[start : cli_source.index("]:", start)]
    completed = set(re.findall(r'\("([a-z]+)",', block))

    assert canonical, "extraction failed: no subcommands found to compare"
    assert completed, "extraction failed: no completion entries found"
    assert canonical <= completed, f"not completable: {sorted(canonical - completed)}"
    assert "effort" in completed


def test_provider_model_name_filter_hides_non_chat_and_legacy_models():
    assert provider_tui._model_is_chat_candidate("gpt-4o") is True
    assert provider_tui._model_is_chat_candidate("gpt-4o-mini-vision") is True
    assert provider_tui._model_is_chat_candidate("text-embedding-3-large") is False
    assert provider_tui._model_is_chat_candidate("gpt-3.5-turbo-instruct") is False
    assert provider_tui._model_is_chat_candidate("davinci-002") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-2") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-1") is False
    assert provider_tui._model_is_chat_candidate("gpt-image-1.5") is False
    assert provider_tui._model_is_chat_candidate("gpt-4o-realtime-preview") is False
    assert provider_tui._model_is_chat_candidate("tts-1") is False


def test_provider_active_state_defaults_deepseek_only_for_model_visibility(monkeypatch):
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "relay": {"api_key_env": "RELAY_API_KEY", "active": False},
            "xiaomi": {"api_key_env": "XIAOMI_API_KEY", "active": True},
        },
    )
    monkeypatch.setattr(
        provider_config,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "deepseek"},
            "relay-chat": {"id": "relay-chat", "provider": "relay"},
            "mimo": {"id": "mimo", "provider": "xiaomi"},
        },
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", provider_config.PROVIDERS)
    monkeypatch.setattr(provider_cmd, "MODELS", provider_config.MODELS)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("RELAY_API_KEY", "test-key")
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")
    # Treat providers as already initialized so the lazy init_providers() call
    # inside _visible_models does not reload and clobber the patched PROVIDERS
    # table (keeps this test order-independent).
    monkeypatch.setattr(provider_config, "_providers_initialized", True)

    visible = provider_cmd._visible_models()

    assert sorted(visible) == ["ds-v4-flash", "mimo"]


def test_visible_models_require_active_provider_and_configured_key(monkeypatch):
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "relay": {"api_key_env": "RELAY_API_KEY", "active": True},
            "dormant": {"api_key_env": "DORMANT_API_KEY", "active": False},
        },
    )
    monkeypatch.setattr(
        provider_config,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "deepseek"},
            "relay-chat": {"id": "relay-chat", "provider": "relay"},
            "dormant-chat": {"id": "dormant-chat", "provider": "dormant"},
        },
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", provider_config.PROVIDERS)
    monkeypatch.setattr(provider_cmd, "MODELS", provider_config.MODELS)
    monkeypatch.setattr(provider_config, "_providers_initialized", True)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("RELAY_API_KEY", raising=False)
    monkeypatch.setenv("DORMANT_API_KEY", "test-key")

    visible = provider_cmd._visible_models()

    assert sorted(visible) == ["ds-v4-flash"]


def test_load_custom_providers_defaults_only_deepseek_active_without_config(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
            "openai": {"api_key_env": "OPENAI_API_KEY"},
        },
    )
    monkeypatch.setattr(provider_config, "MODELS", {})

    provider_config.load_custom_providers()

    assert provider_config.PROVIDERS["deepseek"]["active"] is True
    assert provider_config.PROVIDERS["openai"]["active"] is False


def test_load_custom_providers_defaults_missing_model_desc(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
        },
    )
    monkeypatch.setattr(provider_config, "MODELS", {})
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "relay-chat": {"id": "relay-chat", "provider": "relay"},
                    "relay-pro": {
                        "id": "relay-pro",
                        "provider": "relay",
                        "desc": "Existing description",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.load_custom_providers()

    assert provider_config.MODELS["relay-chat"]["desc"] == "Custom model"
    assert provider_config.MODELS["relay-pro"]["desc"] == "Existing description"


def test_get_provider_config_lazily_initializes_custom_providers(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "_providers_initialized", False)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1/chat/completions",
                "api_key_env": "DEEPSEEK_API_KEY",
                "api_format": "openai",
            },
        },
    )
    monkeypatch.setattr(
        provider_config,
        "MODELS",
        {
            "ds-v4-flash": {"id": "deepseek-v4-flash", "provider": "deepseek"},
        },
    )
    monkeypatch.setenv("RELAY_API_KEY", "relay-secret")
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://relay.example/v1",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "relay-chat": {"id": "relay-chat", "provider": "relay"},
                },
            }
        ),
        encoding="utf-8",
    )

    cfg = provider_config.get_provider_config("relay-chat")

    assert provider_config._providers_initialized is True
    assert cfg["base_url"] == "https://relay.example/v1/chat/completions"
    assert cfg["api_key"] == "relay-secret"
    assert provider_config.MODELS["relay-chat"]["desc"] == "Custom model"


def test_provider_set_active_persists_and_deepseek_cannot_deactivate(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "relay": {"api_key_env": "RELAY_API_KEY", "active": False},
        },
    )

    assert provider_config.set_provider_active("relay", True) is True
    assert provider_config.PROVIDERS["relay"]["active"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["provider_states"]["relay"]["active"] is True

    assert provider_config.set_provider_active("deepseek", False) is False
    assert provider_config.PROVIDERS["deepseek"]["active"] is True


_RELAY_PROVIDER = {
    "base_url": "https://relay.example.invalid/v1",
    "api_key_env": "RELAY_API_KEY",
    "label": "Relay",
    "api_format": "openai",
    "active": True,
}


def _live_provider_config():
    """Return the ``config.providers`` object the product actually reads.

    ``set_provider_reasoning_effort`` and ``_effort_flow`` both resolve the
    module inside the call, so they get whatever ``sys.modules`` holds *now*.
    Several test modules evict ``config`` from ``sys.modules`` at import to
    defeat a stale mock, which mints a new module object; a binding taken at
    this file's import time is then a different object from the one under
    test, so patching it silently does nothing. The result is a test that
    passes alone and fails in the full suite, with the product looking broken.
    """
    import config.providers  # noqa: F401 - ensures the module is in sys.modules

    return sys.modules["config.providers"]


def _write_custom_provider_file(path):
    """A valid file: one custom provider, one custom model, two active states."""
    path.write_text(
        json.dumps(
            {
                "providers": {"relay": dict(_RELAY_PROVIDER)},
                "models": {
                    "relay-chat": {
                        "id": "relay-chat",
                        "provider": "relay",
                        "desc": "Relay chat",
                    }
                },
                "provider_states": {"relay": {"active": True}, "openai": {"active": True}},
            }
        ),
        encoding="utf-8",
    )


def _reload_in_fresh_process(home):
    """Load custom providers in a new interpreter, the way a restart does.

    An in-process ``load_custom_providers()`` cannot prove this: the poisoned
    entry and the corrupted table are the same objects either way, so the test
    would pass even when the on-disk file is what actually breaks.
    """
    script = (
        "import json, config.providers as pc\n"
        "pc.load_custom_providers()\n"
        "print(json.dumps({\n"
        "    'providers': sorted(pc.PROVIDERS),\n"
        "    'models': sorted(pc.MODELS),\n"
        "    'relay_active': pc.is_provider_active('relay'),\n"
        "    'openai_active': pc.is_provider_active('openai'),\n"
        "}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PAWNLOGIC_HOME": str(home), "PAWNLOGIC_TEST_MODE": "true"},
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _builtin_plus_relay_providers():
    return {
        "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
        "openai": {"api_key_env": "OPENAI_API_KEY", "active": False},
        "anthropic": {"api_key_env": "ANTHROPIC_API_KEY", "active": False},
        "relay": dict(_RELAY_PROVIDER),
    }


def test_provider_effort_on_builtin_is_refused_and_preserves_the_config_file(
    tmp_path, monkeypatch, capsys
):
    """``/provider effort <built-in> on`` must not write to custom_providers.json.

    The opt-in persists into the custom provider file, where every entry must
    carry ``base_url`` and ``api_key_env``. A bare ``{"reasoning_effort": true}``
    for a built-in therefore fails validation, and ``load_custom_providers``
    abandons the *whole* file on the first failure — so one reported success
    cost the user every custom provider, every custom model, and all
    persisted activation state on the next start.
    """
    provider_config = _live_provider_config()
    home = tmp_path / "home"
    home.mkdir()
    path = home / "custom_providers.json"
    _write_custom_provider_file(path)
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    from core.commands import _effort_flow

    _effort_flow.set_provider_effort_support("openai on")

    out = capsys.readouterr().out
    assert "built-in provider" in out
    assert "✓" not in out
    assert path.read_text(encoding="utf-8") == before

    reloaded = _reload_in_fresh_process(home)
    # The real built-ins are present, so this also shows the custom entry
    # survived next to them rather than being dropped as a shadowing name.
    assert reloaded["providers"] == ["anthropic", "deepseek", "openai", "relay"]
    assert "relay-chat" in reloaded["models"]
    assert reloaded["relay_active"] is True
    assert reloaded["openai_active"] is True


def test_provider_effort_on_custom_provider_still_persists(tmp_path, monkeypatch, capsys):
    """The refusal must be scoped to built-ins, not disable the opt-in.

    A guard that simply always returned False would satisfy the test above,
    so the positive path is pinned here through the same command.
    """
    provider_config = _live_provider_config()
    home = tmp_path / "home"
    home.mkdir()
    path = home / "custom_providers.json"
    _write_custom_provider_file(path)

    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    from core.commands import _effort_flow

    _effort_flow.set_provider_effort_support("relay on")

    assert "reasoning_effort enabled" in capsys.readouterr().out
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["providers"]["relay"]["reasoning_effort"] is True
    # The entry stays complete; the opt-in must not replace what is there.
    assert data["providers"]["relay"]["base_url"] == _RELAY_PROVIDER["base_url"]
    assert data["providers"]["relay"]["api_key_env"] == _RELAY_PROVIDER["api_key_env"]
    assert "openai" not in data["providers"]

    reloaded = _reload_in_fresh_process(home)
    # The real built-ins are present, so this also shows the custom entry
    # survived next to them rather than being dropped as a shadowing name.
    assert reloaded["providers"] == ["anthropic", "deepseek", "openai", "relay"]
    assert "relay-chat" in reloaded["models"]


def test_set_provider_reasoning_effort_refuses_builtins_without_the_command_layer(
    tmp_path, monkeypatch
):
    """Pin the persistence boundary on its own, not through the command.

    The command guard would mask a regression here: it returns before the write
    is attempted, so deleting the guard in ``config/providers.py`` leaves the
    command test green. This one is the reason the config file stays safe if a
    second caller ever reaches the store directly.
    """
    provider_config = _live_provider_config()
    home = tmp_path / "home"
    home.mkdir()
    path = home / "custom_providers.json"
    _write_custom_provider_file(path)
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    for builtin in sorted(provider_config.BUILTIN_PROVIDER_NAMES):
        assert provider_config.set_provider_reasoning_effort(builtin, True) is False
    assert path.read_text(encoding="utf-8") == before

    reloaded = _reload_in_fresh_process(home)
    assert reloaded["providers"] == ["anthropic", "deepseek", "openai", "relay"]
    assert reloaded["relay_active"] is True
    assert reloaded["openai_active"] is True


def test_set_provider_reasoning_effort_never_mints_a_partial_entry(tmp_path, monkeypatch):
    """A registered name with no complete file entry must not be written.

    ``setdefault`` built a bare ``{"reasoning_effort": true}`` here — the same
    incomplete entry the built-in path wrote, and the same shape
    ``_validated_custom_provider_data`` rejects, which discards the whole
    file. A provider can be registered without a saved entry, so the write
    has to check rather than create.
    """
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "halfwritten": {"base_url": "https://relay.example.invalid/v1"}
                },
                "models": {},
                "provider_states": {},
            }
        ),
        encoding="utf-8",
    )
    halfwritten_before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {
            "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "active": True},
            "halfwritten": {"api_key_env": "HALFWRITTEN_API_KEY", "active": False},
            "unsaved": {"api_key_env": "UNSAVED_API_KEY", "active": False},
        },
    )

    # An incomplete entry on disk, and a registered provider with no file at all.
    assert provider_config.set_provider_reasoning_effort("halfwritten", True) is False
    assert provider_config.set_provider_reasoning_effort("unsaved", True) is False
    assert path.read_text(encoding="utf-8") == halfwritten_before


def test_set_provider_reasoning_effort_refuses_a_complete_shadow_entry(tmp_path, monkeypatch):
    """A built-in name stays refused even when a complete entry exists for it.

    ``load_custom_providers`` skips any provider whose name is a built-in, so
    an entry like this — hand-edited, or left behind by an older version — is
    never loaded. Writing the opt-in into it would report success and change
    nothing on the next start. This is what makes the built-in refusal a
    decision of its own rather than a duplicate of the completeness check.
    """
    provider_config = _live_provider_config()
    path = tmp_path / "custom_providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai": {
                        "base_url": "https://api.openai.com/v1/chat/completions",
                        "api_key_env": "OPENAI_API_KEY",
                        "api_format": "openai",
                    }
                },
                "models": {},
                "provider_states": {},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(provider_config, "PROVIDERS", _builtin_plus_relay_providers())

    assert provider_config.set_provider_reasoning_effort("openai", True) is False
    assert path.read_text(encoding="utf-8") == before


def test_provider_model_probe_rejects_explicit_unsupported_response():
    assert (
        provider_tui._model_rejection_reason(
            '{"error":{"message":"The gpt-3.5-turbo model is not supported"}}'
        )
        == "unsupported"
    )


def test_provider_model_probe_accepts_non_model_specific_400():
    assert provider_tui._model_rejection_reason('{"error":{"message":"missing field"}}') == ""


def test_provider_filter_supported_chat_models_hides_non_chat_output():
    """Filtering is metadata-only: no provider call, no inference."""
    supported, removed, _stats = asyncio.run(
        provider_runtime.filter_supported_chat_models(
            "https://api.example.com/v1",
            "test-key",
            [
                ("new-model", {"id": "new-model", "source_item": {
                    "architecture": {"output_modalities": ["text"]}}}),
                ("old-model", {"id": "old-model", "source_item": {
                    "architecture": {"output_modalities": ["video"]}}}),
            ],
        )
    )

    assert [mid for mid, _cfg in supported] == ["new-model"]
    assert removed == 1


def test_provider_sync_notice_reports_hidden_and_alias_changes():
    lines = provider_tui._format_model_sync_notice(
        {"returned": 5, "hidden_by_name": 2, "hidden_by_metadata": 1, "selectable": 2},
        [("gpt-5.4-mini", "relay:gpt-5.4-mini")],
    )

    assert lines[0] == (
        "Sync summary: 5 returned; 2 hidden by type/name; "
        "1 hidden by capability metadata; 2 selectable."
    )
    assert "gpt-5.4-mini -> relay:gpt-5.4-mini" in lines[1]


def test_provider_first_chat_model_prefers_registered_provider_chat_model(monkeypatch):
    monkeypatch.setattr(
        provider_runtime,
        "MODELS",
        {
            "gpt-image-2": {"id": "gpt-image-2", "provider": "relay"},
            "relay-chat": {"id": "relay-chat-id", "provider": "relay"},
            "other-chat": {"id": "other-chat-id", "provider": "other"},
        },
    )

    assert provider_tui._first_provider_chat_model("relay") == "relay-chat-id"


def test_provider_detail_test_uses_registered_provider_model(monkeypatch):
    alias = "pytest_detail_test"
    env_key = "PYTEST_DETAIL_TEST_API_KEY"
    tui = provider_tui.ProviderTUI()
    tui._detail_provider = alias
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": env_key,
                "api_format": "openai",
            }
        },
    )
    monkeypatch.setattr(
        provider_runtime,
        "MODELS",
        {
            "relay-chat": {"id": "relay-chat-id", "provider": alias},
        },
    )
    seen = {}

    async def fake_test_connection(base_url, api_key, api_format, model_id=None, auth="auto"):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        seen["api_format"] = api_format
        seen["model_id"] = model_id
        seen["auth"] = auth
        return True, "Connected", 1

    monkeypatch.setattr(provider_tui, "_test_connection", fake_test_connection)

    asyncio.run(tui._run_test_detail(alias))

    assert seen == {
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key",
        "api_format": "openai",
        "model_id": "relay-chat-id",
        # The stored scheme is forwarded, so a provider configured for Bearer
        # is not re-probed with the format's default scheme -- which is the
        # 401 this whole change exists to stop.
        "auth": "auto",
    }
    assert tui._detail_status == "✅ Connected"


def test_provider_command_test_uses_loaded_model_id(monkeypatch):
    alias = "pytest_loaded_alias"
    provider_name = "pytest_loaded_provider"
    env_key = "PYTEST_LOADED_PROVIDER_API_KEY"
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(
        provider_cmd,
        "PROVIDERS",
        {
            provider_name: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": env_key,
                "api_format": "openai",
            }
        },
    )
    monkeypatch.setattr(
        provider_cmd,
        "MODELS",
        {
            alias: {
                "id": "provider-native-chat-id",
                "provider": provider_name,
            }
        },
    )
    monkeypatch.setattr(provider_cmd, "validate_api_key", lambda _alias: (True, env_key))
    seen: dict[str, str] = {}

    async def fake_test_connection(base_url, api_key, api_format, model_id, auth="auto"):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        seen["api_format"] = api_format
        seen["model_id"] = model_id
        seen["auth"] = auth
        return True, "Connected", 1

    monkeypatch.setattr(provider_cmd, "test_connection", fake_test_connection)

    asyncio.run(provider_cmd._provider_test(SimpleNamespace(), alias))

    assert seen == {
        "base_url": "https://api.example.com/v1",
        "api_key": "test-key",
        "api_format": "openai",
        "model_id": "provider-native-chat-id",
        "auth": "auto",
    }
    assert seen["model_id"] not in {"gpt-3.5-turbo", "ds-chat", "ds-r1"}


def test_provider_detail_test_without_models_does_not_use_fallback_model(monkeypatch):
    alias = "pytest_detail_empty"
    env_key = "PYTEST_DETAIL_EMPTY_API_KEY"
    tui = provider_tui.ProviderTUI()
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": env_key,
                "api_format": "openai",
            }
        },
    )
    monkeypatch.setattr(provider_tui, "MODELS", {})
    monkeypatch.setattr(provider_runtime, "MODELS", {})
    called = False

    async def fake_test_connection(*_args, **_kwargs):
        nonlocal called
        called = True
        return True, "Connected", 1

    monkeypatch.setattr(provider_tui, "_test_connection", fake_test_connection)

    asyncio.run(tui._run_test_detail(alias))

    assert called is False
    assert "Fetch / Sync Models first" in tui._detail_status
    assert tui._detail_status_style == "class:warning"


def test_provider_tui_model_selector_enter_toggles_row_and_confirms_on_button(monkeypatch):
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_all = [
        ("model-a", {"id": "model-a", "provider": "relay"}),
        ("model-b", {"id": "model-b", "provider": "relay"}),
    ]
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")
    saved = {"called": False}

    def fake_save_models():
        saved["called"] = True

    monkeypatch.setattr(tui, "_do_save_models", fake_save_models)

    enter_handler(SimpleNamespace(app=app))

    assert tui._ms_selected == {"model-a"}
    assert saved["called"] is False

    tui._ms_cursor = len(tui._ms_all)
    enter_handler(SimpleNamespace(app=app))

    assert saved["called"] is True


def test_provider_tui_model_selector_cancel_button_returns_to_caller():
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_caller = "detail"
    tui._ms_all = [("model-a", {"id": "model-a", "provider": "relay"})]
    tui._ms_cursor = len(tui._ms_all) + 2
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")

    enter_handler(SimpleNamespace(app=app))

    assert tui._panel == "detail"
    assert tui._detail_status == "Model sync cancelled."


def test_provider_tui_manage_model_delete_reports_json_failure(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    path.write_text("{bad json", encoding="utf-8")
    tui = provider_tui.ProviderTUI()
    tui._panel = "manage"
    tui._mm_provider = "relay"
    tui._mm_models = ["relay-chat"]
    monkeypatch.setattr(provider_tui, "CUSTOM_PROVIDERS_PATH", path)
    monkeypatch.setattr(
        provider_tui,
        "MODELS",
        {"relay-chat": {"id": "relay-chat", "provider": "relay"}},
    )
    monkeypatch.setattr(provider_tui, "remove_model", lambda _alias: None)

    logged: list[str] = []

    class FakeLogger:
        def warning(self, msg, *args):
            logged.append(msg.format(*args))

    monkeypatch.setattr(provider_tui, "logger", FakeLogger())
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    delete_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_mm_del")

    delete_handler(SimpleNamespace(app=app))

    assert path.read_text(encoding="utf-8") == "{bad json"
    assert tui._mm_status == "Failed to update custom_providers.json."
    assert tui._mm_status_style == "class:error"
    assert "Failed to remove model from custom_providers.json" in logged[0]


def test_provider_tui_completer_refresh_logs_unexpected_failure(monkeypatch):
    async def fake_run_provider_tui():
        return None

    class BadCompleter:
        @property
        def words(self):
            return []

        @words.setter
        def words(self, _value):
            raise RuntimeError("refresh failed")

    logged: list[str] = []

    class FakeLogger:
        def warning(self, msg, *args):
            logged.append(msg.format(*args))

        def error(self, *_args, **_kwargs):
            raise AssertionError("TUI should not crash")

    monkeypatch.setattr(provider_tui, "run_provider_tui", fake_run_provider_tui)
    monkeypatch.setattr(provider_cmd, "_HAS_PROMPT_TOOLKIT", True)
    monkeypatch.setattr(provider_cmd, "_all_cmd_words", [], raising=False)
    monkeypatch.setattr(provider_cmd, "_cmd_meta", {}, raising=False)
    monkeypatch.setattr(provider_cmd, "_pawn_completer", BadCompleter(), raising=False)
    monkeypatch.setattr(provider_cmd, "_visible_models", lambda: {}, raising=False)
    monkeypatch.setattr(provider_cmd, "logger", FakeLogger())

    asyncio.run(provider_cmd._handle_provider_cmd("", "", session=None))

    assert "[provider] completer refresh failed" in logged[0]


def test_provider_tui_model_selector_renders_prefixed_alias_hint():
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_provider = "relay"
    tui._ms_all = [("gpt-5.4-mini", {"id": "gpt-5.4-mini", "provider": "relay"})]

    rendered = "".join(text for _style, text in tui._render_model_select())

    assert "gpt-5.4-mini -> relay:gpt-5.4-mini" in rendered


def test_provider_tui_model_selector_load_close_exits_after_save(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._panel = "models"
    tui._ms_provider = alias
    tui._ms_all = [("model-a", {"id": "model-a", "provider": alias})]
    tui._ms_selected = {"model-a"}
    tui._ms_cursor = len(tui._ms_all) + 1
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "api_format": "openai",
            }
        },
    )
    kb = tui._build_kb()
    app = Application(
        layout=tui._build_layout(),
        key_bindings=kb,
        style=provider_tui.TUI_STYLE,
        full_screen=False,
    )
    tui._app = app
    enter_handler = next(binding.handler for binding in kb.bindings if binding.handler.__name__ == "_ms_enter")
    saved = {"called": False}
    exited = {"called": False}

    def fake_save_provider_with_rollback(*_args, **_kwargs):
        saved["called"] = True
        return True, ""

    monkeypatch.setattr("core.provider_runtime.save_provider_with_rollback", fake_save_provider_with_rollback)
    monkeypatch.setattr(provider_tui, "_record_sync_time", lambda _pname: None)
    monkeypatch.setattr(provider_tui, "_sync_models_to_runtime", lambda: None)
    monkeypatch.setattr(app, "exit", lambda *args, **kwargs: exited.__setitem__("called", True))

    enter_handler(SimpleNamespace(app=app))

    assert saved["called"] is True
    assert exited["called"] is True


def test_provider_tui_save_models_prefixes_builtin_alias_collisions(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._ms_provider = alias
    tui._ms_all = [
        ("gpt-5.4-mini", {"id": "gpt-5.4-mini", "provider": alias}),
        ("relay-chat", {"id": "relay-chat", "provider": alias}),
    ]
    tui._ms_selected = {"gpt-5.4-mini", "relay-chat"}
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "api_format": "openai",
            }
        },
    )
    saved = {}

    def fake_save_provider_with_rollback(name, provider_cfg, models_cfg, replace_models=False):
        saved["name"] = name
        saved["models_cfg"] = models_cfg
        saved["replace_models"] = replace_models
        return True, ""

    monkeypatch.setattr("core.provider_runtime.save_provider_with_rollback", fake_save_provider_with_rollback)
    monkeypatch.setattr(provider_tui, "_record_sync_time", lambda _pname: None)
    monkeypatch.setattr(provider_tui, "_sync_models_to_runtime", lambda: None)

    tui._do_save_models()

    assert saved["name"] == alias
    assert sorted(saved["models_cfg"]) == ["relay-chat", "relay:gpt-5.4-mini"]
    assert saved["models_cfg"]["relay:gpt-5.4-mini"]["id"] == "gpt-5.4-mini"
    assert saved["replace_models"] is True


def test_provider_tui_toggle_active_updates_provider_state(monkeypatch):
    alias = "relay"
    tui = provider_tui.ProviderTUI()
    tui._detail_provider = alias
    monkeypatch.setattr(
        provider_tui,
        "PROVIDERS",
        {
            alias: {
                "base_url": "https://api.example.com/v1",
                "api_key_env": "RELAY_API_KEY",
                "active": False,
            }
        },
    )
    seen = {}

    def fake_runtime_set_active(name, active):
        seen["name"] = name
        seen["active"] = active
        provider_tui.PROVIDERS[name]["active"] = active
        return True, "Provider is now active."

    monkeypatch.setattr(provider_tui, "is_provider_active", lambda _name: False)
    monkeypatch.setattr(provider_tui, "_runtime_set_active", fake_runtime_set_active)

    tui._toggle_provider_active(alias)

    assert seen == {"name": alias, "active": True}
    assert tui._detail_status == "✅ Provider is now active."


def test_provider_tui_connection_reports_success_from_the_free_listing():
    response = SimpleNamespace(
        status_code=200,
        text='{"data":[{"id":"one"}]}',
        json=lambda: {"data": [{"id": "one"}]},
    )

    ok, message = provider_tui._connection_result_from_listing(response, 12)

    assert ok is True
    # The message must say nothing was inferred, so a user reading the panel
    # does not assume Test Connection exercised the model.
    assert message == "Connected (12ms; free model listing, no inference sent)"


def test_provider_tui_connection_reports_a_rejected_key():
    response = SimpleNamespace(
        status_code=401,
        text='{"error":{"message":"Invalid API key"}}',
        json=lambda: {"error": {"message": "Invalid API key"}},
    )

    ok, message = provider_tui._connection_result_from_listing(response, 34)

    assert ok is False
    # A rejected key must be named as such, not reported as a bare status.
    assert message == format_http_error(401, response.text)


def test_provider_tui_connection_reports_http_400_body_when_json_invalid():
    response = SimpleNamespace(
        status_code=400,
        text='{"error":"bad request"}{"extra":"chunk"}',
        json=lambda: json.loads('{"error":"bad request"}{"extra":"chunk"}'),
    )

    ok, message = provider_tui._connection_result_from_listing(response, 34)

    assert ok is False
    assert "HTTP 400" in message
    assert "bad request" in message
    assert "Extra data" not in message


def test_provider_tui_and_cli_share_http_error_message(monkeypatch, capsys):
    body = '{"error":{"message":"missing entitlement","type":"auth","code":"forbidden"}}'
    expected = format_http_error(500, body)
    response = SimpleNamespace(
        status_code=500,
        text=body,
        json=lambda: {"error": {"message": "missing entitlement"}},
    )

    ok, tui_message = provider_tui._connection_result_from_listing(response, 41)

    assert ok is False
    assert tui_message == expected

    alias = "pytest_http_error"
    env_key = "PYTEST_HTTP_ERROR_API_KEY"
    provider_cmd.PROVIDERS[alias] = {
        "base_url": "https://api.example.com/v1",
        "api_key_env": env_key,
        "label": "Relay",
        "api_format": "openai",
    }
    monkeypatch.setenv(env_key, "test-key")

    async def fake_fetch_models(_base_url, _api_key, _api_format, auth="auto"):
        return [], expected, {"returned": 0, "hidden_by_name": 0, "hidden_by_metadata": 0, "selectable": 0}

    monkeypatch.setattr(provider_cmd, "fetch_models", fake_fetch_models)

    try:
        asyncio.run(provider_cmd._provider_fetch(alias))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert expected in capsys.readouterr().out


def test_provider_tui_add_wizard_saves_without_testing_connection(monkeypatch):
    alias = "pytest_save_only"
    env_key = "PYTEST_SAVE_ONLY_API_KEY"
    tui = provider_tui.ProviderTUI()
    tui._wiz_inputs[0].text = alias
    tui._wiz_inputs[1].text = "http://127.0.0.1:8080/v1"
    tui._wiz_fields[2] = "openai"
    tui._wiz_inputs[2].text = "test-key"
    provider_tui.PROVIDERS.pop(alias, None)

    saved = {}

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("add wizard should not test connection")

    def fake_save_key_to_env(env_var, key):
        saved["env_var"] = env_var
        saved["key"] = key

    def fake_save_provider_with_rollback(name, provider_cfg, models_cfg):
        saved["name"] = name
        saved["provider_cfg"] = provider_cfg
        saved["models_cfg"] = models_cfg
        return True, ""

    monkeypatch.setattr(provider_tui, "_test_connection", fail_if_called)
    monkeypatch.setattr(provider_tui, "_save_key_to_env", fake_save_key_to_env)
    monkeypatch.setattr("core.provider_runtime.save_provider_with_rollback", fake_save_provider_with_rollback)
    monkeypatch.setattr(provider_tui, "init_providers", lambda force=False: None)

    try:
        asyncio.run(tui._wizard_confirm())
    finally:
        provider_tui.PROVIDERS.pop(alias, None)

    assert saved["name"] == alias
    assert saved["env_var"] == env_key
    assert saved["key"] == "test-key"
    assert saved["provider_cfg"]["base_url"] == "http://127.0.0.1:8080/v1"
    assert tui._panel == "main"


def test_models_url_from_base_url_preserves_proxy_path():
    assert (
        provider_config.models_url_from_base_url(
            "https://relay.example.com/openai/v1/chat/completions"
        )
        == "https://relay.example.com/openai/v1/models"
    )
    assert (
        provider_config.models_url_from_base_url("https://relay.example.com/openai/v1")
        == "https://relay.example.com/openai/v1/models"
    )


def test_save_custom_provider_preserves_models_by_default(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    },
                    "other": {
                        "base_url": "https://other.example.com/v1/chat/completions",
                        "api_key_env": "OTHER_API_KEY",
                        "label": "Other",
                        "api_format": "openai",
                    },
                },
                "models": {
                    "old-relay-model": {"id": "old", "provider": "relay"},
                    "other-model": {"id": "other", "provider": "other"},
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"new-relay-model": {"id": "new", "provider": "relay"}},
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(data["models"]) == ["new-relay-model", "old-relay-model", "other-model"]


def test_save_custom_provider_can_replace_models_for_same_provider(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    },
                    "other": {
                        "base_url": "https://other.example.com/v1/chat/completions",
                        "api_key_env": "OTHER_API_KEY",
                        "label": "Other",
                        "api_format": "openai",
                    },
                },
                "models": {
                    "old-relay-model": {"id": "old", "provider": "relay"},
                    "other-model": {"id": "other", "provider": "other"},
                },
            }
        ),
        encoding="utf-8",
    )

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"new-relay-model": {"id": "new", "provider": "relay"}},
        replace_models=True,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(data["models"]) == ["new-relay-model", "other-model"]


def test_save_custom_provider_prefixes_builtin_model_alias_collision(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)

    provider_config.save_custom_provider(
        "relay",
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key_env": "RELAY_API_KEY",
            "label": "Relay",
            "api_format": "openai",
        },
        {"gpt-5.4-mini": {"id": "gpt-5.4-mini", "provider": "relay"}},
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "gpt-5.4-mini" not in data["models"]
    assert data["models"]["relay:gpt-5.4-mini"]["id"] == "gpt-5.4-mini"


def test_load_custom_providers_ignores_existing_non_chat_models(tmp_path, monkeypatch):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(provider_config, "CUSTOM_PROVIDERS_PATH", path)
    provider_config.MODELS.pop("relay:gpt-5.4-mini", None)
    provider_config.MODELS.pop("gpt-image-2", None)
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "relay": {
                        "base_url": "https://api.example.com/v1/chat/completions",
                        "api_key_env": "RELAY_API_KEY",
                        "label": "Relay",
                        "api_format": "openai",
                    }
                },
                "models": {
                    "gpt-5.4-mini": {"id": "gpt-5.4-mini", "provider": "relay"},
                    "gpt-image-2": {"id": "gpt-image-2", "provider": "relay"},
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        provider_config.load_custom_providers()

        assert "relay:gpt-5.4-mini" in provider_config.MODELS
        assert "gpt-image-2" not in provider_config.MODELS
    finally:
        provider_config.PROVIDERS.pop("relay", None)
        provider_config.MODELS.pop("relay:gpt-5.4-mini", None)
        provider_config.MODELS.pop("gpt-image-2", None)


def test_provider_add_cli_fetches_without_nested_event_loop(monkeypatch):
    alias = "pytest_relay"
    env_key = "PYTEST_RELAY_API_KEY"
    assert provider_cmd.provider_config is provider_config
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    provider_cmd.PROVIDERS.pop(alias, None)

    saved = {}

    def fake_save_provider_with_rollback(name, provider_cfg, models_cfg, **_kw):
        saved["name"] = name
        saved["provider_cfg"] = provider_cfg
        saved["models_cfg"] = models_cfg
        return True, ""

    fetch = AsyncMock()
    monkeypatch.setattr(provider_cmd, "_provider_fetch", fetch)
    monkeypatch.setattr(provider_cmd, "_provider_add", lambda: None)
    monkeypatch.setattr(provider_cmd, "_provider_list", lambda: None)
    monkeypatch.setattr(provider_cmd, "_provider_test", lambda _session, _arg: None)
    monkeypatch.setattr("core.provider_runtime.save_provider_with_rollback", fake_save_provider_with_rollback)
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

    try:
        asyncio.run(
            provider_cmd._handle_provider_cmd(
                "add",
                f"{alias} https://api.example.com/v1 {env_key}",
                SimpleNamespace(),
            )
        )
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert saved["name"] == alias
    assert saved["provider_cfg"]["api_key_env"] == env_key
    # The live-terminal controller is threaded through so the model
    # multi-select runs inside the running Application (ADR 0010).
    # None here is the readline/CLI path, which has no live Application.
    fetch.assert_awaited_once_with(alias, terminal_controller=None)


def test_provider_fetch_prints_filter_and_alias_summary(monkeypatch, capsys):
    alias = "pytest_fetch_summary"
    env_key = "PYTEST_FETCH_SUMMARY_API_KEY"
    assert provider_cmd.provider_config is provider_config
    monkeypatch.setenv(env_key, "test-key")
    provider_cmd.PROVIDERS[alias] = {
        "base_url": "https://api.example.com/v1",
        "api_key_env": env_key,
        "label": "Relay",
        "api_format": "openai",
    }
    saved = {}

    async def fake_selector(entries):
        return [mid for mid, _cfg in entries]

    def fake_save_custom_provider(name, _provider_cfg, models_cfg, replace_models=False):
        saved["name"] = name
        saved["models_cfg"] = models_cfg
        saved["replace_models"] = replace_models

    async def fake_fetch_models(_base_url, _api_key, _api_format, auth="auto"):
        return (
            [
                (
                    "gpt-5.4-mini",
                    {
                        "id": "gpt-5.4-mini",
                        "provider": "",
                        "desc": "Dynamically fetched model",
                    },
                ),
                (
                    "relay-chat",
                    {
                        "id": "relay-chat",
                        "provider": "",
                        "desc": "Dynamically fetched model",
                    },
                ),
            ],
            "",
            {"returned": 4, "hidden_by_name": 1, "hidden_by_metadata": 1, "selectable": 2},
        )

    monkeypatch.setattr(provider_cmd, "fetch_models", fake_fetch_models)
    monkeypatch.setattr(provider_cmd, "_provider_fetch_selector", fake_selector)
    monkeypatch.setattr(provider_config, "save_custom_provider", fake_save_custom_provider)
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

    try:
        asyncio.run(provider_cmd._provider_fetch(alias))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    out = capsys.readouterr().out
    assert "Sync summary: 4 returned" in out
    assert "1 hidden by type/name" in out
    assert "1 hidden by capability metadata" in out
    assert "gpt-5.4-mini -> pytest_fetch_summary:gpt-5.4-mini" in out
    assert saved["name"] == alias
    assert sorted(saved["models_cfg"]) == [
        "pytest_fetch_summary:gpt-5.4-mini",
        "relay-chat",
    ]
    assert saved["replace_models"] is True


def test_provider_activate_command_updates_active_state(monkeypatch, capsys):
    alias = "pytest_active_cmd"
    provider_cmd.PROVIDERS[alias] = {"api_key_env": "PYTEST_ACTIVE_CMD_API_KEY", "active": False}
    seen = {}

    def fake_runtime_set_active(name, active):
        seen["name"] = name
        seen["active"] = active
        provider_cmd.PROVIDERS[name]["active"] = active
        return True, "Provider is now active."

    monkeypatch.setattr(provider_cmd, "runtime_set_active", fake_runtime_set_active)

    try:
        asyncio.run(provider_cmd._handle_provider_cmd("activate", alias, SimpleNamespace()))
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    out = capsys.readouterr().out
    assert seen == {"name": alias, "active": True}
    assert "is now active" in out


def test_model_command_rejects_inactive_provider_model(monkeypatch, capsys):
    alias = "inactive-model"
    provider_name = "inactive-provider"
    session = SimpleNamespace(model_alias="ds-v4-flash")
    monkeypatch.setattr(
        provider_config,
        "PROVIDERS",
        {provider_name: {"api_key_env": "INACTIVE_PROVIDER_API_KEY", "active": False}},
    )
    monkeypatch.setattr(
        provider_config,
        "MODELS",
        {alias: {"id": alias, "provider": provider_name, "color": "\033[37m"}},
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", provider_config.PROVIDERS)
    monkeypatch.setattr(provider_cmd, "MODELS", provider_config.MODELS)
    monkeypatch.setattr(provider_config, "_providers_initialized", True)

    asyncio.run(
        provider_cmd.cmd_model(
            SimpleNamespace(arg=alias, arg2="", session=session, sink=None)
        )
    )

    out = capsys.readouterr().out
    assert "is not active" in out
    assert session.model_alias == "ds-v4-flash"


def test_provider_add_cli_does_not_prompt_for_fetch_on_piped_input(monkeypatch):
    alias = "pytest_piped_relay"
    env_key = "PYTEST_PIPED_RELAY_API_KEY"
    monkeypatch.setenv(env_key, "test-key")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    provider_cmd.PROVIDERS.pop(alias, None)

    input_called = False

    def fake_input(_prompt):
        nonlocal input_called
        input_called = True
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(provider_config, "save_custom_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)

    try:
        should_fetch = provider_cmd._provider_add_cli(
            alias,
            "https://api.example.com/v1",
            env_key,
        )
    finally:
        provider_cmd.PROVIDERS.pop(alias, None)

    assert should_fetch is False
    assert input_called is False


def test_provider_tui_detail_offers_edit_for_endpoint_fields():
    """Editing a provider's Base URL / Format needs its own action.

    Only "Update API Key" existed, so a provider saved with a wrong URL or
    wire format could not be corrected from the UI at all.
    """
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"

    actions = tui._detail_actions()

    assert "Edit Provider" in actions
    assert "Update API Key" in actions          # the key keeps its own flow
    # The rendered menu and the dispatcher must agree, or the cursor selects
    # the wrong action; both now read the same list.
    rendered = "".join(text for _s, text in tui._render_detail())
    for act in actions:
        assert f"[ {act} ]" in rendered


def test_provider_tui_detail_cursor_wraps_over_every_action():
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    total = len(tui._detail_actions())

    kb = tui._build_kb()
    from prompt_toolkit.keys import Keys as _Keys
    down = [b.handler for b in kb.get_bindings_for_keys((_Keys.Down,)) if b.filter()][-1]

    for _ in range(total):
        down(None)
    assert tui._detail_cursor == 0, "down did not wrap over the whole action list"


def test_provider_tui_edit_prefills_endpoint_and_locks_the_name(monkeypatch):
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    monkeypatch.setitem(provider_tui.PROVIDERS, "openrouter",
                        {"base_url": "https://api.openrouter.ai/api/v1",
                         "api_format": "anthropic", "api_key_env": "OPENROUTER_API_KEY"})

    tui._open_edit_provider("openrouter")

    assert tui._wiz_edit == "openrouter"
    assert tui._panel == "wizard"
    assert tui._wiz_inputs[1].text == "https://api.openrouter.ai/api/v1"
    assert tui._wiz_fields[rows_mod.ROW_FORMAT] == "anthropic"
    # Focus starts on the first editable row, not the locked name.
    assert tui._wiz_focus == rows_mod.ROW_URL
    # The key is left to the existing Update API Key action: the form must not
    # offer to write a key, because the stored one is never displayed.
    assert tui._wiz_inputs[2].text == ""


def test_provider_tui_edit_navigation_skips_the_locked_rows():
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    tui._open_edit_provider("openrouter")

    from prompt_toolkit.keys import Keys as _Keys
    kb = tui._build_kb()
    down = [b.handler for b in kb.get_bindings_for_keys((_Keys.Down,)) if b.filter()][-1]

    visited = []
    for _ in range(len(rows_mod.focus_cycle(editing=True))):
        visited.append(tui._wiz_focus)
        down(None)

    # Name and key stay out of the cycle; Auth is in it, because it is exactly
    # the row a user editing a mis-authenticated provider needs to reach.
    assert visited == [
        rows_mod.ROW_URL,
        rows_mod.ROW_FORMAT,
        rows_mod.ROW_AUTH,
        rows_mod.ROW_SAVE,
    ]
    assert tui._wiz_focus == rows_mod.ROW_URL   # and it wraps back


def test_provider_tui_edit_confirm_saves_url_and_format_keeping_name(monkeypatch):
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    tui._open_edit_provider("openrouter")
    tui._wiz_inputs[1].text = "https://relay.example.com/v1"
    tui._wiz_fields[rows_mod.ROW_FORMAT] = "anthropic"
    tui._wiz_fields[rows_mod.ROW_AUTH] = "bearer"

    saved = {}

    def fake_update(name, base_url, api_format, auth="auto"):
        saved["name"] = name
        saved["base_url"] = base_url
        saved["api_format"] = api_format
        saved["auth"] = auth
        return True, ""

    def fail_key_write(*_a, **_k):
        raise AssertionError("editing the endpoint must not rewrite the API key")

    monkeypatch.setattr(provider_tui, "_update_custom_provider", fake_update)
    monkeypatch.setattr(provider_tui, "_save_key_to_env", fail_key_write)
    monkeypatch.setattr(provider_tui, "init_providers", lambda force=False: None)

    asyncio.run(tui._wizard_confirm())

    # ``auth`` is asserted here, not merely accepted: a renderer that shows the
    # row while the save silently drops it is the worst possible failure, since
    # the user watches the field confirm and the setting never takes effect.
    assert saved == {"name": "openrouter", "base_url": "https://relay.example.com/v1",
                     "api_format": "anthropic", "auth": "bearer"}
    assert tui._panel == "detail"
    assert tui._wiz_edit == ""


def test_provider_tui_edit_confirm_reports_failure_without_leaving_edit(monkeypatch):
    tui = provider_tui.ProviderTUI()
    tui._panel = "detail"
    tui._detail_provider = "openrouter"
    tui._open_edit_provider("openrouter")
    tui._wiz_inputs[1].text = "https://relay.example.com/v1"

    monkeypatch.setattr(provider_tui, "_update_custom_provider",
                        lambda *_a, **_k: (False, "Failed to save provider config"))
    monkeypatch.setattr(provider_tui, "init_providers", lambda force=False: None)

    asyncio.run(tui._wizard_confirm())

    assert "Failed to save" in tui._wiz_error
    assert tui._panel == "wizard"


# ── the auth scheme must reach every request path, not just the TUI ──
#
# The reported bug was not "Auth is missing from a config file" but "Auth is
# ignored at the three places a request actually goes out". Each of these
# asserts the value *arrives*, because a fake that merely accepts the keyword
# would let a call site that hardcodes "auto" stay green.


def _provider_with_auth(monkeypatch, alias, env_key, fmt, auth):
    """Install one provider into both registries the two paths read.

    The TUI reads ``core.provider_tui.PROVIDERS`` and the CLI reads
    ``core.commands.provider.PROVIDERS``; patching only one leaves the other
    resolving an empty provider and the assertion silently checks nothing.
    """
    entry = {
        alias: {
            "base_url": "https://api.example.com/v1",
            "api_key_env": env_key,
            "api_format": fmt,
            "auth": auth,
        }
    }
    monkeypatch.setattr(provider_cmd, "PROVIDERS", entry)
    monkeypatch.setattr(provider_tui, "PROVIDERS", entry)
    monkeypatch.setenv(env_key, "test-key")


def test_provider_tui_fetch_forwards_the_configured_auth_scheme(monkeypatch):
    alias = "relay"
    env_key = "RELAY_API_KEY"
    _provider_with_auth(monkeypatch, alias, env_key, "anthropic", "bearer")
    seen: dict[str, str] = {}

    async def fake_fetch_models(base_url, api_key, api_format, auth="auto"):
        seen["api_format"] = api_format
        seen["auth"] = auth
        return [], "", {"returned": 0, "hidden_by_name": 0,
                        "hidden_by_metadata": 0, "selectable": 0}

    monkeypatch.setattr(provider_tui, "_fetch_models", fake_fetch_models)

    tui = provider_tui.ProviderTUI()
    asyncio.run(tui._open_model_selector(alias, "detail"))

    assert seen == {"api_format": "anthropic", "auth": "bearer"}


def test_provider_cli_fetch_forwards_the_configured_auth_scheme(monkeypatch):
    alias = "relay"
    env_key = "RELAY_API_KEY"
    _provider_with_auth(monkeypatch, alias, env_key, "anthropic", "bearer")
    seen: dict[str, str] = {}

    async def fake_fetch_models(base_url, api_key, api_format, auth="auto"):
        seen["api_format"] = api_format
        seen["auth"] = auth
        return [], "", {"returned": 0, "hidden_by_name": 0,
                        "hidden_by_metadata": 0, "selectable": 0}

    monkeypatch.setattr(provider_cmd, "fetch_models", fake_fetch_models)

    asyncio.run(provider_cmd._provider_fetch(alias))

    assert seen == {"api_format": "anthropic", "auth": "bearer"}


def test_provider_add_cli_persists_an_explicit_auth_scheme(monkeypatch):
    saved: dict[str, dict] = {}

    def fake_save(name, prov_cfg, models_cfg, replace_models=True):
        saved[name] = dict(prov_cfg)
        return True, ""

    monkeypatch.setattr(provider_runtime, "save_provider_with_rollback", fake_save)
    monkeypatch.setattr(provider_cmd, "PROVIDERS", {})
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)
    monkeypatch.delenv("RELAY_API_KEY", raising=False)

    ok = provider_cmd._provider_add_cli(
        "relay", "https://api.example.com/v1", "RELAY_API_KEY",
        "anthropic", "bearer",
    )

    # Non-interactive /provider add must be able to express the combination
    # that the TUI can; otherwise anyone scripting a relay setup is stuck.
    assert ok is False           # key unset -> prompts to fetch
    assert saved["relay"]["auth"] == "bearer"
    assert saved["relay"]["api_format"] == "anthropic"


def test_provider_add_cli_defaults_auth_to_auto_for_existing_scripts(monkeypatch):
    saved: dict[str, dict] = {}

    def fake_save(name, prov_cfg, models_cfg, replace_models=True):
        saved[name] = dict(prov_cfg)
        return True, ""

    monkeypatch.setattr(provider_runtime, "save_provider_with_rollback", fake_save)
    monkeypatch.setattr(provider_cmd, "PROVIDERS", {})
    monkeypatch.setattr(provider_config, "init_providers", lambda force=False: None)
    monkeypatch.delenv("RELAY_API_KEY", raising=False)

    provider_cmd._provider_add_cli("relay", "https://api.example.com/v1",
                                   "RELAY_API_KEY", "openai")

    assert saved["relay"]["auth"] == "auto"


def test_provider_add_cli_refuses_an_unknown_auth_scheme(monkeypatch):
    saved: dict[str, dict] = {}
    monkeypatch.setattr(
        provider_runtime, "save_provider_with_rollback",
        lambda name, cfg, models, replace_models=True: saved.setdefault(name, cfg) and (True, ""),
    )
    monkeypatch.setattr(provider_cmd, "PROVIDERS", {})

    ok = provider_cmd._provider_add_cli("relay", "https://api.example.com/v1",
                                        "RELAY_API_KEY", "openai", "oauth")

    assert ok is False
    assert saved == {}
