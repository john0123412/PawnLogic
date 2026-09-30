"""The standalone (no-controller) model picker.

``/model`` has two very different front ends.  When a terminal controller owns
the screen, ``pawnlogic/selectors.py`` renders a ``ModelSelector`` as real
layout inside the one persistent Prompt Toolkit ``Application`` (ADR 0010).
This module is the other path: a self-contained ``Application`` built on the
spot, for the headless and readline cases where nothing else owns the PTY.

It is separate from ``core/commands/provider.py`` because that file sits on
its architecture budget, and because a nested ``Application`` has its own
preconditions — it may only run where no controller exists.  Keeping it here
makes that precondition obvious instead of hiding it in a command body.
"""

from __future__ import annotations

from typing import Any

try:
    from prompt_toolkit.styles import Style as _PTStyle
except ImportError:  # pragma: no cover - mirrors provider.py's detection
    _PTStyle = None  # type: ignore


async def cc_style_model_selector(
    models: dict[str, Any],
    current_alias: str,
) -> str | None:
    """Claude Code style inline model selector. Returns the alias or None."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window

    entries = list(models.items())
    selected_idx = 0

    def get_menu_fragments():
        fragments = []
        fragments.append(("class:title", "  Select model\n"))
        fragments.append(("class:desc", "  Choose a model for this session\n"))
        fragments.append(("", "\n"))

        for i, (alias, cfg_m) in enumerate(entries):
            if i == selected_idx:
                fragments.append(("class:cursor", "  ❯ "))
            else:
                fragments.append(("", "    "))

            fragments.append(("class:index", f"{i+1}."))

            is_current = alias == current_alias
            if i == selected_idx:
                fragments.append(("class:selected", f" {alias}"))
            else:
                fragments.append(("", f" {alias}"))

            if is_current:
                fragments.append(("class:current", " ✔"))

            desc = cfg_m.get("desc", "")[:45]
            if desc:
                if i == selected_idx:
                    fragments.append(("class:desc-hi", f"  {desc}"))
                else:
                    fragments.append(("class:desc", f"  {desc}"))

            if cfg_m.get("vision"):
                fragments.append(("class:vision", " 📷"))

            fragments.append(("", "\n"))

        fragments.append(("", "\n"))
        fragments.append(("class:help", "  Enter to confirm · Esc to exit\n"))

        return fragments

    control = FormattedTextControl(get_menu_fragments)
    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx - 1) % len(entries)

    @kb.add("down")
    def _(event):
        nonlocal selected_idx
        selected_idx = (selected_idx + 1) % len(entries)

    @kb.add("enter")
    def _(event):
        event.app.exit(result=entries[selected_idx][0])

    @kb.add("escape")
    def _(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _(event):
        event.app.exit(result=None)

    for _n in range(1, min(10, len(entries) + 1)):

        @kb.add(str(_n))
        def _(event, _idx=_n - 1):
            nonlocal selected_idx
            if _idx < len(entries):
                selected_idx = _idx

    body = Window(content=control, always_hide_cursor=True)

    style = _PTStyle.from_dict(
        {
            "title": "#00afff bold",
            "desc": "#888888",
            "desc-hi": "#aaaaaa",
            "cursor": "#00ff00 bold",
            "selected": "#00ff00 bold",
            "current": "#00d700",
            "index": "#666666",
            "vision": "#00afff",
            "help": "#555555",
        }
    )

    app = Application(
        layout=Layout(body),
        key_bindings=kb,
        style=style,
        mouse_support=False,
        full_screen=False,
    )

    return await app.run_async()


__all__ = ["cc_style_model_selector"]
