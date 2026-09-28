"""Confirmation modal for high-risk host operations (0.3.12).

This is the one selector that is a **trust boundary** rather than a
convenience picker, so it does not follow the generic selector
conventions:

- **Deny by default.** ``selected_idx`` starts on "Deny" and a bare
  ``Enter`` resolves to Deny. Approving a high-risk command requires
  the explicit ``y`` key. The live terminal routes ``enter``/``c-j``/
  ``c-m``/digits/arrows to the active selector with ``eager=True``
  bindings, so a user who types a follow-up message while a tool waits
  for approval would otherwise approve the command with a keystroke
  they meant for the composer.

- **No keys before paint.** The selector swallows every key until the
  host has read :attr:`formatted_text` at least once. Until the Float
  has actually been rendered the user has not seen the prompt, so no
  keystroke may resolve it.

It lives in the ``pawnlogic`` layer rather than in ``core`` so that
``core.operation_policy`` can keep its "no ``pawnlogic.*`` import"
discipline: that module imports this one lazily, from inside
:func:`~core.operation_policy.run_confirmation_modal`.
"""

from __future__ import annotations

from typing import Any

from pawnlogic.selectors import SelectorState

#: Key that approves the operation. Deliberately not ``enter``.
APPROVE_KEY = "y"

_DENY_KEYS = frozenset({"n", "escape", "c-c"})


class ConfirmOperationSelector(SelectorState):
    """Two-entry yes/no selector guarding one high-risk operation.

    The live terminal's eager key bindings make this selector own the
    keyboard for as long as it is mounted, so the two guarantees above
    are the only thing standing between an incidental keystroke and an
    approved high-risk command.
    """

    #: Lets the status line distinguish this from a convenience picker.
    kind = "confirmation"

    def __init__(self, decision: Any, *, timeout_seconds: float | None = None) -> None:
        super().__init__(title="Confirm high-risk operation")
        self._decision = decision
        # 0 = "Approve and run", 1 = "Deny". Start on Deny.
        self._selected_idx = 1
        self._rendered = False
        self._timeout_seconds = timeout_seconds

    @property
    def decision(self) -> Any:
        return self._decision

    @property
    def timeout_seconds(self) -> float | None:
        return self._timeout_seconds

    @property
    def has_rendered(self) -> bool:
        """Whether the host has painted this modal at least once."""
        return self._rendered

    @property
    def selected_idx(self) -> int:
        return self._selected_idx

    @property
    def formatted_text(self) -> Any:
        from prompt_toolkit.formatted_text import FormattedText

        decision = self._decision
        style = self.style
        fragments: list[tuple[str, str]] = [
            (style.title, "\n  High-risk host shell operation\n"),
            (style.desc, f"\n  Risk: {getattr(decision, 'risk', None)}\n"),
            (style.desc, f"  Reason: {getattr(decision, 'reason', '')}\n"),
            (style.desc, f"  Rule: {getattr(decision, 'matched_rule', '')}\n"),
            (style.desc, f"  Command: {getattr(decision, 'redacted_command', '')}\n"),
        ]
        if self._timeout_seconds is not None:
            fragments.append(
                (
                    style.help,
                    f"\n  No answer within {self._timeout_seconds:g}s denies it.\n",
                )
            )
        fragments.append(
            (
                style.help,
                f"\n  Up/Down or 1/2 select   {APPROVE_KEY} approve"
                f"   n/Esc deny   Enter confirms the selection\n\n",
            )
        )
        for index, (label, _keyword) in enumerate(
            (("Approve and run", "yes"), ("Deny", "no"))
        ):
            cursor = ">" if index == self._selected_idx else " "
            style_token = style.selected if index == self._selected_idx else ""
            fragments.append((style_token, f"  {cursor} {index + 1}. {label}\n"))
        # Reading this property is the host telling us the Float wants
        # content: the user can see the prompt from now on.
        self._rendered = True
        return FormattedText(fragments)

    def handle_key(self, key: str) -> bool:
        """Consume one key. Unpainted modals resolve nothing."""
        if not self._rendered:
            # Swallow, but report consumption so the host redraws and the
            # Float finally gets painted.
            return True
        if key == APPROVE_KEY:
            self.close(result=True)
            return True
        if key in _DENY_KEYS:
            self.close(result=False)
            return True
        if key == "up":
            self._selected_idx = (self._selected_idx - 1) % 2
            return True
        if key == "down":
            self._selected_idx = (self._selected_idx + 1) % 2
            return True
        if key in {"1", "2"}:
            self._selected_idx = int(key) - 1
            return True
        if key in {"enter", "c-j", "c-m"}:
            # Deny is the default, so a bare Enter denies.
            self.close(result=self._selected_idx == 0)
            return True
        return True


__all__ = ["APPROVE_KEY", "ConfirmOperationSelector"]
