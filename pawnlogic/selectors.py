"""Selector state machines driven by the live Prompt Toolkit Application.

The 0.3.7 inline-terminal contract (ADR 0010) requires interactive
selectors to render inside the same Prompt Toolkit ``Application`` as
the persistent live terminal.  Running a second ``Application`` while
the first one is alive causes two ``Vt100_Output`` instances to
compete for the same PTY and produces the cursor / escape-sequence
corruption seen in 0.3.7 phase B.

This module owns the **single in-Application** selector framework:

- :class:`SelectorState` is the abstract base.  A concrete selector
  exposes a ``formatted_text`` snapshot for the live ``Float`` to
  render and a ``handle_key`` method that the main ``Application``
  dispatches to when the selector is the active modal.

- :class:`SelectorRegistry` is the controller-side store.  The live
  ``Application`` keeps exactly one ``Float`` whose content reads
  from the registry's active selector.  Open / close transitions
  flip a ``Condition`` that the main ``Application``'s key bindings
  use to decide which handler consumes the key.

- :class:`SelectorHost` is the narrow protocol the registry needs
  from the controller.  It is the same Protocol the
  :class:`~core.commands.CommandContext` ``terminal_controller``
  field already speaks, so no new contract is introduced.

Concrete selectors live next to the command handlers that use them
(``/model``, ``/planguard``, ``/provider``, ``/skills``).  Each
concrete selector subclasses :class:`SelectorState` and is wired
into the registry by the controller when the command is dispatched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from prompt_toolkit.formatted_text import FormattedText


@dataclass
class SelectorStyle:
    """Style tokens used by every in-Application selector Float.

    Keeping the styles in one place lets the four concrete selectors
    share the same look without re-declaring the palette.  The
    defaults mirror the pre-0.3.7 inline selectors so existing users
    do not see a visual change.
    """

    title: str = "class:pawnlogic.selector.title"
    desc: str = "class:pawnlogic.selector.desc"
    desc_hi: str = "class:pawnlogic.selector.desc-hi"
    cursor: str = "class:pawnlogic.selector.cursor"
    selected: str = "class:pawnlogic.selector.selected"
    current: str = "class:pawnlogic.selector.current"
    index: str = "class:pawnlogic.selector.index"
    vision: str = "class:pawnlogic.selector.vision"
    help: str = "class:pawnlogic.selector.help"
    frame: str = "class:pawnlogic.selector.frame"


DEFAULT_SELECTOR_STYLE = SelectorStyle()


class SelectorState:
    """Abstract base for in-Application selector state machines.

    Subclasses are expected to:

    - Override :attr:`formatted_text` to render the current state.
    - Override :meth:`handle_key` to consume keys while the selector
      is active.  Return ``True`` when the key was consumed (in
      which case the registry invalidates the live ``Application``
      so the Float re-renders).  Return ``False`` to let the key
      fall through to other bindings.
    - Set :attr:`result` and call :meth:`close` when the user
      confirms or cancels.  The registry will then resolve the
      selector's future and unblock the awaiting command.
    """

    def __init__(
        self, *, title: str, style: SelectorStyle = DEFAULT_SELECTOR_STYLE
    ) -> None:
        self.title = title
        self.style = style
        self.result: Any = None
        self._closed = False

    @property
    def formatted_text(self) -> FormattedText:
        """Return the FormattedText the Float should render right now."""
        raise NotImplementedError

    def handle_key(self, key: str) -> bool:
        """Dispatch a single key to the selector state machine.

        ``key`` is the PT key name (``"up"``, ``"down"``, ``"enter"``,
        ``"escape"``, ``"c-c"``, ``"1"``-``"9"``, ...).  Return
        ``True`` to indicate the selector consumed the key.
        """
        raise NotImplementedError

    def close(self, result: Any = None) -> None:
        """Mark the selector as closed and record its result."""
        self.result = result
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed


@runtime_checkable
class SelectorHost(Protocol):
    """The narrow surface the registry needs from a host.

    The :class:`~core.commands.CommandContext` ``terminal_controller``
    field is already typed to this protocol via
    :class:`PersistentTerminalController`.  No new runtime contract
    is introduced.
    """

    def open_selector(self, selector: SelectorState) -> asyncio.Future[Any]:
        """Install a selector as the live modal and return its result future."""
        ...

    def close_selector(self) -> None:
        """Close the current selector (if any) and resolve its future."""
        ...


@dataclass
class SelectorRegistry:
    """Owns the active selector state and broadcasts it to the live Application.

    The registry is a single per-session object.  When the live
    ``Application`` builds its layout it consults the registry's
    :attr:`active_selector` to decide whether the selector Float
    should be visible and what its content should be.  When a
    command wants to open a modal it calls :meth:`open_selector` on
    the controller, which delegates here.

    The registry is intentionally tiny: it does not own an
    ``asyncio.Future`` per se.  Instead, the host
    (:class:`PersistentTerminalController`) creates the future and
    hands it to the registry via :meth:`install_active`.  This keeps
    the registry synchronous and easy to reason about in tests.
    """

    _active: SelectorState | None = None
    _future: asyncio.Future[Any] | None = field(default=None)

    @property
    def active_selector(self) -> SelectorState | None:
        return self._active

    @property
    def has_active(self) -> bool:
        return self._active is not None and not self._active.is_closed

    def install_active(
        self,
        selector: SelectorState,
        future: asyncio.Future[Any],
    ) -> None:
        """Make ``selector`` the active modal and resolve ``future`` on close.

        The host creates ``future`` so the awaiting command can be
        resolved by either the selector (when the user confirms or
        cancels) or the host (when the live terminal closes for
        another reason).
        """
        if self._active is not None and not self._active.is_closed:
            # Stale selector; resolve it as cancelled so the prior
            # awaiting command does not hang.
            self._active.close(result=None)
            if self._future is not None and not self._future.done():
                self._future.set_result(None)
        self._active = selector
        self._future = future

    def consume_active(self) -> tuple[SelectorState, asyncio.Future[Any]] | None:
        """Atomically take ownership of the active selector and its future."""
        if self._active is None or self._future is None:
            return None
        selector = self._active
        future = self._future
        self._active = None
        self._future = None
        return selector, future

    def resolve(self, result: Any) -> bool:
        """Resolve the current selector's future with ``result``.

        Returns True when an active selector was resolved, False
        when there was no active selector (a benign no-op).
        """
        if self._active is None or self._future is None:
            return False
        self._active.close(result=result)
        future = self._future
        self._active = None
        self._future = None
        if not future.done():
            future.set_result(result)
        return True

    def formatted_text(self) -> FormattedText:
        """Snapshot the active selector's formatted text, or empty."""
        if self._active is None or self._active.is_closed:
            return FormattedText([])
        return self._active.formatted_text


# Sentinel type used by selectors that have no result.  Returning
# ``None`` from a selector is a legitimate user choice (cancel), so
# a separate sentinel is needed to distinguish "no result yet" from
# "user cancelled".
NO_RESULT: Any = object()


def style_dict() -> dict[str, str]:
    """Return the Prompt Toolkit style dict shared by every selector Float.

    The selector Float is rendered inside the persistent
    ``Application``, so the styles must use the application's style
    class prefix (``class:pawnlogic.selector.*``).  Concrete styles
    are registered by ``live_terminal.py`` so the selector Float can
    blend with the rest of the live terminal palette.
    """
    return {
        "pawnlogic.selector.title": "#00afff bold",
        "pawnlogic.selector.desc": "#888888",
        "pawnlogic.selector.desc-hi": "#aaaaaa",
        "pawnlogic.selector.cursor": "#00ff00 bold",
        "pawnlogic.selector.selected": "#00ff00 bold",
        "pawnlogic.selector.current": "#00d700",
        "pawnlogic.selector.index": "#666666",
        "pawnlogic.selector.vision": "#00afff",
        "pawnlogic.selector.help": "#666666",
        "pawnlogic.selector.frame": "#444444",
    }


__all__ = [
    "DEFAULT_SELECTOR_STYLE",
    "NO_RESULT",
    "ModelSelector",
    "PlanGuardSelector",
    "SelectorHost",
    "SelectorRegistry",
    "SelectorState",
    "SelectorStyle",
    "style_dict",
]


class PlanGuardSelector(SelectorState):
    """Two-mode selector for the ``/planguard`` command.

    The state machine is intentionally tiny: the user is choosing
    between ``advisory`` and ``strict``.  The state is just the
    selected index.  The Float renders a simple numbered list with
    the current option marked.
    """

    OPTIONS: tuple[tuple[str, str, str], ...] = (
        (
            "advisory",
            "Advisory (recommended)",
            "Warn after missing plan blocks; tool calls continue.",
        ),
        (
            "strict",
            "Strict",
            "Stop the third tool-call attempt without a plan before tools run.",
        ),
    )

    def __init__(self, current: str) -> None:
        super().__init__(title="Plan Guard Mode")
        self.current = current
        self.selected_idx = next(
            (index for index, (mode, _, _) in enumerate(self.OPTIONS) if mode == current),
            0,
        )

    @property
    def formatted_text(self) -> FormattedText:
        fragments: list[tuple[str, str]] = []
        fragments.append((self.style.title, "\n  Plan Guard Mode\n"))
        fragments.append((self.style.desc, "  Choose how missing <plan> blocks are handled.\n\n"))
        for index, (mode, label, description) in enumerate(self.OPTIONS):
            cursor = "❯" if index == self.selected_idx else " "
            marker = "●" if index == self.selected_idx else "○"
            style = self.style.selected if index == self.selected_idx else ""
            current_marker = "  current" if mode == self.current else ""
            fragments.append((style, f"  {cursor} {marker} {index + 1}. {label}{current_marker}\n"))
            fragments.append((self.style.desc, f"      {description}\n"))
        fragments.append((self.style.help, "\n  Up/Down or 1/2 select  Enter apply  Esc cancel\n"))
        return FormattedText(fragments)

    def handle_key(self, key: str) -> bool:
        if key == "up":
            self.selected_idx = (self.selected_idx - 1) % len(self.OPTIONS)
            return True
        if key == "down":
            self.selected_idx = (self.selected_idx + 1) % len(self.OPTIONS)
            return True
        if key in {"1", "2"}:
            idx = int(key) - 1
            if 0 <= idx < len(self.OPTIONS):
                self.selected_idx = idx
            return True
        if key == "enter":
            self.close(result=self.OPTIONS[self.selected_idx][0])
            return True
        if key in {"escape", "c-c"}:
            self.close(result=None)
            return True
        return False


class ModelSelector(SelectorState):
    """Claude-Code-style inline model picker for the ``/model`` command.

    The state machine is just the current cursor index.  Up to nine
    entries are reachable by digit; ten or more are reachable by
    Up/Down + Enter.  The Float renders a single-line per entry with
    the same emoji + label + description + vision flag layout the
    pre-0.3.7 inline selector used.
    """

    def __init__(
        self,
        models: dict[str, dict[str, Any]],
        current_alias: str,
    ) -> None:
        super().__init__(title="Select model")
        self.entries: list[tuple[str, dict[str, Any]]] = list(models.items())
        self.current_alias = current_alias
        self.selected_idx = next(
            (
                index
                for index, (alias, _) in enumerate(self.entries)
                if alias == current_alias
            ),
            0,
        )

    @property
    def formatted_text(self) -> FormattedText:
        fragments: list[tuple[str, str]] = []
        fragments.append((self.style.title, "  Select model\n"))
        fragments.append((self.style.desc, "  Choose a model for this session\n"))
        fragments.append(("", "\n"))

        for index, (alias, cfg) in enumerate(self.entries):
            if index == self.selected_idx:
                fragments.append((self.style.cursor, "  ❯ "))
            else:
                fragments.append(("", "    "))
            fragments.append((self.style.index, f"{index + 1}."))
            style = self.style.selected if index == self.selected_idx else ""
            fragments.append((style, f" {alias}"))
            if alias == self.current_alias:
                fragments.append((self.style.current, " ✔"))
            desc = str(cfg.get("desc", ""))[:45]
            if desc:
                desc_style = (
                    self.style.desc_hi if index == self.selected_idx else self.style.desc
                )
                fragments.append((desc_style, f"  {desc}"))
            if cfg.get("vision"):
                fragments.append((self.style.vision, " 📷"))
            fragments.append(("", "\n"))

        fragments.append(("", "\n"))
        fragments.append((self.style.help, "  Enter to confirm · Esc to exit\n"))
        return FormattedText(fragments)

    def handle_key(self, key: str) -> bool:
        if not self.entries:
            if key in {"enter", "escape", "c-c"}:
                self.close(result=None)
                return True
            return False
        if key == "up":
            self.selected_idx = (self.selected_idx - 1) % len(self.entries)
            return True
        if key == "down":
            self.selected_idx = (self.selected_idx + 1) % len(self.entries)
            return True
        if key in {str(d) for d in range(1, 10)}:
            idx = int(key) - 1
            if 0 <= idx < len(self.entries):
                self.selected_idx = idx
            return True
        if key == "enter":
            self.close(result=self.entries[self.selected_idx][0])
            return True
        if key in {"escape", "c-c"}:
            self.close(result=None)
            return True
        return False
