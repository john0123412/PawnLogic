"""Streaming renderer for the XML ``<plan>`` block emitted during a Turn.

The model emits its plan as an XML tag stream (``<plan>`` with
``<action>``/``<verify>``/``<intent>``/... sub-tags). ``_PlanRenderer.feed``
consumes that stream chunk by chunk, stripping the tags, writing the coloured
human-readable form straight to stdout, and returning any non-plan text (the
actual answer) to the caller.

Not every ``<plan>`` in the stream opens a plan.  An answer that explains the
plan protocol quotes the tag, and treating that as a plan printed the rest of
the answer dim gray as plan text, indistinguishable from the thinking stream,
because no ``</plan>`` followed.  A ``<plan>`` opens a plan only outside code
(a fenced block or an inline code span) and only at the start of a line or
directly followed by a plan sub-tag; that rule classifies all 421 stored
replies that contain the tag.  The renderer tracks just enough of the answer's
current line to apply it, and waits for more of the stream when the sub-tag
check cannot be decided yet.

Split out of ``core/session.py`` so the tag-scanning state machine does not
consume that module's architecture budget. It is imported by ``core.session``
and re-exported there under its original private name for compatibility.
"""

import sys

from utils.ansi import c, strip_ansi, GRAY, CYAN, MAGENTA, YELLOW, DIM

_TAG_PAIRS = [
    ("<plan>", "</plan>"),
    ("<action>", "</action>"),
    ("<verify>", "</verify>"),
    # Additional subtags.
    ("<intent>", "</intent>"),
    ("<tool>", "</tool>"),
    ("<why>", "</why>"),
    ("<next>", "</next>"),
    ("<anchor>", "</anchor>"),
    ("<correction>", "</correction>"),
]
_ALL_TAGS = [t for pair in _TAG_PAIRS for t in pair]
_TAG_MAX = max(len(t) for t in _ALL_TAGS) + 2
_PLAN_OPEN = "<plan>"
_FENCES = ("```", "~~~")

# Subtag prefix labels and color mapping.
_SUBTAG_OPEN: dict = {
    "<action>": (GRAY, "  📋 "),
    "<verify>": (CYAN, "  🔬 Verify: "),
    "<intent>": (MAGENTA, "  🎯 Intent: "),
    "<tool>": (CYAN, "  🔧 Tool: "),
    "<why>": (GRAY, "  💡 Why: "),
    "<next>": (GRAY + DIM, "  ⏭  Next: "),
    "<anchor>": (YELLOW, "  ⚓ Anchor:\n"),
    "<correction>": (YELLOW, ""),  # silent flag, no display
}
_PLAN_SUBTAGS = tuple(_SUBTAG_OPEN)


class _PlanRenderer:
    def __init__(self):
        self.in_plan = False
        self.in_action = False
        self.in_verify = False
        self.in_intent = False
        self.in_tool_tag = False
        self.in_why = False
        self.in_next = False
        self.in_anchor = False
        self.in_correction = False
        self.tail = ""
        self._reset_line_state()

    def _reset_line_state(self) -> None:
        # Answer text only (plan text is not tracked): the first non-blank
        # characters of the current line, its backtick count, and whether a
        # fenced code block is open.
        self._line_head = ""
        self._line_ticks = 0
        self._in_fence = False

    def _note(self, text: str) -> str:
        """Record answer text for the line and code-fence state; return ``text``."""
        for index, part in enumerate(text.split("\n")):
            if index:  # a newline ended the previous line
                if self._line_head.startswith(_FENCES):
                    self._in_fence = not self._in_fence
                self._line_head, self._line_ticks = "", 0
            if part:
                if len(self._line_head) < 3:
                    head = part if self._line_head else part.lstrip()
                    self._line_head += head[: 3 - len(self._line_head)]
                self._line_ticks += part.count("`")
        return text

    def _opens_plan(self, after: str) -> bool | None:
        """Decide whether a ``<plan>`` the answer text reached opens a plan block.

        ``after`` is the buffered text that follows the tag; ``None`` means the
        stream has not yet said whether a plan sub-tag follows it.
        """
        if self._in_fence or self._line_ticks % 2:
            return False
        if not self._line_head:  # only whitespace precedes it on its line
            return True
        rest = after.lstrip()
        if rest.startswith(_PLAN_SUBTAGS):
            return True
        if not rest or any(tag.startswith(rest) for tag in _PLAN_SUBTAGS):
            return None
        return False

    def _in_subtag(self) -> bool:
        return (
            self.in_action
            or self.in_verify
            or self.in_intent
            or self.in_tool_tag
            or self.in_why
            or self.in_next
            or self.in_anchor
            or self.in_correction
        )

    def _color(self, text: str) -> str:
        if self.in_verify:
            return c(CYAN, text)
        if self.in_intent:
            return c(MAGENTA, text)
        if self.in_tool_tag:
            return c(CYAN, text)
        if self.in_why:
            return c(GRAY, text)
        if self.in_next:
            return c(GRAY + DIM, text)
        if self.in_anchor:
            return c(YELLOW, text)
        if self.in_correction:
            return ""  # never display <correction> value
        if self.in_action:
            return c(GRAY, text)
        return c(GRAY + DIM, text)

    def _set_subtag(self, tag: str, val: bool):
        if tag in ("<action>", "</action>"):
            self.in_action = val
        elif tag in ("<verify>", "</verify>"):
            self.in_verify = val
        elif tag in ("<intent>", "</intent>"):
            self.in_intent = val
        elif tag in ("<tool>", "</tool>"):
            self.in_tool_tag = val
        elif tag in ("<why>", "</why>"):
            self.in_why = val
        elif tag in ("<next>", "</next>"):
            self.in_next = val
        elif tag in ("<anchor>", "</anchor>"):
            self.in_anchor = val
        elif tag in ("<correction>", "</correction>"):
            self.in_correction = val

    def feed(self, chunk: str) -> str:
        self.tail += chunk
        output = ""
        while self.tail:
            if "<" not in self.tail:
                if not self.in_plan:
                    output += self._note(self.tail)
                else:
                    col = self._color(strip_ansi(self.tail))
                    if col:
                        sys.stdout.write(col)
                        sys.stdout.flush()
                self.tail = ""
                break

            lt = self.tail.find("<")
            if lt > 0:
                safe = self.tail[:lt]
                if not self.in_plan:
                    output += self._note(safe)
                else:
                    col = self._color(strip_ansi(safe))
                    if col:
                        sys.stdout.write(col)
                        sys.stdout.flush()
                self.tail = self.tail[lt:]
                continue

            ep = len(self.tail)
            et = None
            for tag in _ALL_TAGS:
                pos = self.tail.find(tag)
                if pos != -1 and pos < ep:
                    ep = pos
                    et = tag

            if not et:
                if len(self.tail) > _TAG_MAX:
                    if not self.in_plan:
                        output += self._note(self.tail[0])
                    else:
                        sys.stdout.write(self._color(strip_ansi(self.tail[0])))
                        sys.stdout.flush()
                    self.tail = self.tail[1:]
                else:
                    break
            elif not self.in_plan:
                output += self._note(self.tail[:ep])
                self.tail = self.tail[ep:]
                if et == _PLAN_OPEN:
                    opens = self._opens_plan(self.tail[len(_PLAN_OPEN) :])
                    if opens is None:
                        break  # wait for the text that decides it
                    if opens:
                        sys.stdout.write(c(GRAY + DIM, "\n  💭 [plan start]\n"))
                        sys.stdout.flush()
                        self.in_plan = True
                    else:
                        output += self._note(_PLAN_OPEN)
                    self.tail = self.tail[len(_PLAN_OPEN) :]
                else:
                    output += self._note(self.tail[: len(et)])
                    self.tail = self.tail[len(et) :]
            else:
                # inside <plan> — handle open and close subtags
                col = self._color(strip_ansi(self.tail[:ep]))
                if col:
                    sys.stdout.write(col)
                    sys.stdout.flush()
                self.tail = self.tail[ep:]
                if et == "</plan>":
                    sys.stdout.write(c(GRAY, "\n  [plan end]\n"))
                    sys.stdout.flush()
                    self.in_plan = self.in_action = self.in_verify = False
                    self.in_intent = self.in_tool_tag = self.in_why = False
                    self.in_next = self.in_anchor = self.in_correction = False
                    self.tail = self.tail[len("</plan>") :]
                    self._line_head, self._line_ticks = "", 0  # answer resumes on a new line
                elif et in _SUBTAG_OPEN:
                    # opening subtag
                    color, prefix = _SUBTAG_OPEN[et]
                    if prefix:
                        sys.stdout.write(c(color, prefix))
                        sys.stdout.flush()
                    self._set_subtag(et, True)
                    self.tail = self.tail[len(et) :]
                elif et.startswith("</"):
                    # closing subtag
                    self._set_subtag(et, False)
                    self.tail = self.tail[len(et) :]
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                else:
                    self.tail = self.tail[len(et) :]
        return output

    def flush(self) -> str:
        leftover = ""
        if self.in_plan:
            sys.stdout.write(c(GRAY + DIM, strip_ansi(self.tail)))
            sys.stdout.flush()
        else:
            leftover = self.tail
        self.tail = ""
        self.in_plan = self.in_action = self.in_verify = False
        self.in_intent = self.in_tool_tag = self.in_why = False
        self.in_next = self.in_anchor = self.in_correction = False
        self._reset_line_state()
        return leftover
