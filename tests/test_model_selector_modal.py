"""Contract tests for the single-Application selector modal.

These tests pin down [ADR 0010](../adr/0010-inline-terminal-modal.md):
opening a selector must NOT tear down the main Prompt Toolkit
``Application`` and must NOT spawn a second ``Application``. The main
task must remain alive, the ``Application`` object identity must be
stable across the round trip, the recovered-draft marker must
survive, and the queue preview callback must keep working.

They are written against the public ``PersistentTerminal`` and
``PersistentTerminalController`` contract, so they keep working as the
implementation is rewritten to honor the ADR.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from pawnlogic.live_terminal import (
    PersistentTerminal,
    PersistentTerminalController,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubSession:
    """Minimal stand-in for the session object the controller holds."""

    def __init__(self) -> None:
        self._live_terminal_active = False
        self.sink_history: list[Any] = []

    def activate_sink(self, sink: Any) -> None:
        self.sink_history.append(sink)
        self._live_terminal_active = True


def _make_terminal() -> PersistentTerminal:
    return PersistentTerminal(
        input=DummyInput(),
        output=DummyOutput(),
    )


def _make_controller(
    terminal: PersistentTerminal,
    session: _StubSession,
) -> PersistentTerminalController:
    return PersistentTerminalController(
        terminal=terminal,
        session=session,
        activate_sink=session.activate_sink,
        fallback_sink=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pause_for_modal_does_not_exit_main_application() -> None:
    """pause_for_modal must not call Application.exit() on the live app.

    Under the exit-rebuild lifecycle this is violated: pause_for_modal
    awaits the main task to completion, which only finishes once the
    Application loop has terminated. The new contract is a single,
    continuously running Application, so this test fails until the
    lifecycle is rewritten.
    """
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()

    exit_calls: list[dict[str, Any]] = []

    async def _drive() -> None:
        await controller.start()
        before_app = terminal.application
        assert (
            before_app is not None
        ), "PersistentTerminal must have a live Application after start()"

        def _spy_exit(*args: Any, **kwargs: Any) -> None:
            # Record the call and DO NOT delegate to the real exit.
            # The contract forbids calling Application.exit() at all
            # while a modal is open.
            exit_calls.append({"args": args, "kwargs": kwargs})
            return None

        before_app.exit = _spy_exit  # type: ignore[method-assign]

        try:
            paused = await controller.pause_for_modal(True)
            assert paused is True, "modal host should report it was entered"
            assert exit_calls == [], (
                f"Application.exit() must not be called while opening a "
                f"selector; saw {exit_calls!r}"
            )
            assert (
                terminal.is_running is True
            ), "terminal must still be running while the modal is open"
            assert terminal.application is before_app, (
                "Application object identity must not change while the " "modal is open"
            )
        finally:
            await controller.resume_after_modal(paused)
            await controller.close()

    asyncio.run(_drive())


def test_resume_after_modal_preserves_recovered_draft_marker() -> None:
    """The recovered-draft marker must survive the modal round trip."""
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()
    terminal.set_recovery_draft("recovered body")

    async def _drive() -> None:
        await controller.start()
        assert (
            terminal.recovery_draft_pending is True
        ), "recovered draft should be marked pre-modal"

        paused = await controller.pause_for_modal(True)
        try:
            assert terminal.recovery_draft_pending is True
        finally:
            await controller.resume_after_modal(paused)
            assert (
                terminal.recovery_draft_pending is True
            ), "recovered-draft marker must survive modal round trip"
            await controller.close()

    asyncio.run(_drive())


def test_resume_after_modal_preserves_application_identity() -> None:
    """Same Application instance must serve before and after the modal."""
    terminal = _make_terminal()
    session = _StubSession()
    controller = _make_controller(terminal, session)
    terminal.prepare_run()

    async def _drive() -> None:
        await controller.start()
        before = terminal.application
        assert before is not None

        paused = await controller.pause_for_modal(True)
        try:
            await controller.resume_after_modal(paused)
            after = terminal.application
            assert (
                after is before
            ), "modal round trip must not rebuild the main Application"
        finally:
            await controller.close()

    asyncio.run(_drive())


def test_run_selector_keeps_main_application_task_alive() -> None:
    """run_selector must not exit the main Application.

    The selector state machine is installed in the live ``Application``'s
    :class:`SelectorRegistry`; the main task stays alive for the entire
    round trip and the ``Application`` identity is stable.
    """
    from prompt_toolkit.input.defaults import create_pipe_input
    from pawnlogic.selectors import PlanGuardSelector

    async def _drive() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            session = _StubSession()
            controller = _make_controller(terminal, session)
            terminal.prepare_run()
            await controller.start()
            before_app = terminal.application
            before_task = controller._task
            assert before_app is not None
            assert before_task is not None

            exit_calls: list[dict[str, Any]] = []

            def _spy_exit(*args: Any, **kwargs: Any) -> None:
                # Record the call and DO NOT delegate to the real exit.
                # The contract forbids calling Application.exit() at
                # all while a selector is open, so swallowing here
                # keeps the Application alive for the rest of the
                # assertions. The test process tears the event loop
                # down at the end, so the spy never needs to release
                # anything.
                exit_calls.append({"args": args, "kwargs": kwargs})
                return None

            before_app.exit = _spy_exit  # type: ignore[method-assign]

            async def _drive_close() -> None:
                # Wait until the selector is installed and the
                # controller is awaiting the future, then close the
                # selector through the registry to resolve the future
                # deterministically without depending on key input
                # dispatch through the pipe.
                for _ in range(50):
                    await asyncio.sleep(0.01)
                    selector = terminal.selector_registry.active_selector
                    if selector is not None and not selector.is_closed:
                        break
                else:  # pragma: no cover - timeout safety
                    return
                # Resolve the future directly. The selector was
                # created with current="advisory" and stays at index
                # 0, so a synthetic Enter press would have returned
                # "advisory" - mirror that here.
                terminal._selector_registry.resolve("advisory")

            try:
                drive_task = asyncio.create_task(_drive_close())

                def _factory() -> Any:
                    return PlanGuardSelector(current="advisory")

                result = await controller.run_selector(_factory)
                await drive_task
                assert result == "advisory", (
                    f"run_selector must surface the selector's result; got {result!r}"
                )
                assert exit_calls == [], (
                    f"Application.exit() must not be called during a selector "
                    f"round trip; saw {exit_calls!r}"
                )
                assert terminal.is_running is True
                assert terminal.application is before_app
                assert controller._task is before_task, (
                    "controller task identity must not change across a selector "
                    "round trip"
                )
            finally:
                # Skip the controller close: the exit spy above makes
                # ``Application.exit()`` a no-op, so the controller
                # close would block on the still-running main task.
                # Cancel the main task directly instead.
                if controller._task is not None and not controller._task.done():
                    controller._task.cancel()
                    with suppress(asyncio.CancelledError, BaseException):
                        await controller._task
                if terminal._proxy_active if hasattr(terminal, "_proxy_active") else False:
                    terminal.restore_output_proxy()
                terminal.restore_output_proxy()
                session._live_terminal_active = False

    asyncio.run(_drive())


def test_replaced_selector_finally_cannot_close_newer_selector() -> None:
    """A stale selector task must not tear down the selector that replaced it."""
    from prompt_toolkit.input.defaults import create_pipe_input
    from pawnlogic.selectors import PlanGuardSelector

    async def _drive() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            session = _StubSession()
            controller = _make_controller(terminal, session)
            terminal.prepare_run()
            await controller.start()
            first = PlanGuardSelector(current="advisory")
            second = PlanGuardSelector(current="strict")
            first_task = asyncio.create_task(controller.run_selector(lambda: first))
            second_future: asyncio.Future[Any] | None = None
            try:
                for _ in range(100):
                    if terminal.selector_registry.active_selector is first:
                        break
                    await asyncio.sleep(0.01)
                else:  # pragma: no cover - timeout safety
                    raise AssertionError("first selector did not mount")

                # Install the replacement in this task before yielding.  The
                # first command's continuation is then scheduled only after
                # this assertion, which makes the stale-finally race
                # deterministic instead of depending on task ordering.
                second_future = terminal.open_selector(second)
                assert terminal.selector_registry.active_selector is second

                # Installing the second selector resolves the first command.
                # Its finally block must use its own future/token, otherwise
                # the generic close call closes the second selector here.
                assert await asyncio.wait_for(first_task, timeout=1) is None
                assert terminal.selector_registry.active_selector is second
                terminal.selector_registry.resolve("strict")
                assert await asyncio.wait_for(second_future, timeout=1) == "strict"
            finally:
                if second_future is not None and not second_future.done():
                    second_future.cancel()
                    with suppress(asyncio.CancelledError):
                        await second_future
                if not first_task.done():
                    first_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await first_task
                await controller.close()

    asyncio.run(_drive())


def test_terminal_close_resolves_active_selector_command() -> None:
    """Closing the host must unblock a command waiting on its selector."""
    from prompt_toolkit.input.defaults import create_pipe_input
    from pawnlogic.selectors import PlanGuardSelector

    async def _drive() -> None:
        with create_pipe_input() as pipe:
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            session = _StubSession()
            controller = _make_controller(terminal, session)
            terminal.prepare_run()
            await controller.start()
            selector_task = asyncio.create_task(
                controller.run_selector(
                    lambda: PlanGuardSelector(current="advisory")
                )
            )
            try:
                for _ in range(100):
                    if terminal.selector_registry.has_active:
                        break
                    await asyncio.sleep(0.01)
                else:  # pragma: no cover - timeout safety
                    raise AssertionError("selector did not mount")

                terminal.close()
                assert await asyncio.wait_for(selector_task, timeout=1) is None
            finally:
                if not selector_task.done():
                    selector_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await selector_task
                await controller.close()

    asyncio.run(_drive())


def test_planguard_dispatch_uses_run_selector_when_controller_is_present() -> None:
    """cmd_planguard must route the selector through controller.run_selector.

    Per [ADR 0010](../adr/0010-inline-terminal-modal.md) the
    ``/planguard`` selector must NOT spawn its own ``Application``; the
    controller's ``run_selector`` schedules it as a background task on
    the main Application so the main ``Application`` object identity is
    preserved. This test stubs the selector entry point and asserts
    the dispatch path uses ``controller.run_selector`` when one is
    provided in the ``CommandContext``.
    """
    from core.commands import CommandContext
    from core.commands import system as system_commands

    class _StubController:
        """Stand-in that records the call to ``run_selector``."""

        def __init__(self) -> None:
            self.calls: list[Any] = []

            async def _await(callable_: Any) -> str:
                self.calls.append(callable_)
                return "strict"

            self.run_selector = _await

    class _StubSession:
        def __init__(self) -> None:
            self.model_alias = "stub-model"

        def runtime_context(self) -> Any:  # pragma: no cover - not exercised
            return None

    async def _drive() -> None:
        controller = _StubController()
        # ``_select_plan_guard_mode`` is imported lazily inside
        # ``cmd_planguard``; patch it on the module to keep this test
        # independent from prompt_toolkit's runtime requirements.
        captured: list[tuple[str, Any]] = []

        async def _fake_select_plan_guard_mode(current: str) -> str:
            captured.append(("direct", current))
            return "strict"

        # cmd_planguard imports ``_select_plan_guard_mode`` via the
        # module's own globals, so monkey-patching the module attribute
        # is the right hook.
        original = getattr(system_commands, "_select_plan_guard_mode", None)
        system_commands._select_plan_guard_mode = _fake_select_plan_guard_mode  # type: ignore[assignment]
        original_available = getattr(
            system_commands, "_plan_guard_tui_available", None
        )
        system_commands._plan_guard_tui_available = lambda: True  # type: ignore[assignment]
        try:
            ctx = CommandContext(
                verb="/planguard",
                arg="",
                arg2="",
                session=_StubSession(),
                terminal_controller=controller,
            )
            await system_commands.cmd_planguard(ctx)
        finally:
            if original is not None:
                system_commands._select_plan_guard_mode = original  # type: ignore[assignment]
            if original_available is not None:
                system_commands._plan_guard_tui_available = original_available  # type: ignore[assignment]
        assert controller.calls, (
            "cmd_planguard must invoke controller.run_selector when a "
            "controller is attached to the CommandContext"
        )
        assert captured == [], (
            f"cmd_planguard must not call _select_plan_guard_mode "
            f"directly when a controller is present; saw {captured!r}"
        )

    asyncio.run(_drive())


def test_model_dispatch_uses_run_selector_when_controller_is_present() -> None:
    """cmd_model must route the selector through controller.run_selector.

    Mirrors the /planguard contract test for the model selector, so the
    ADR-0010 in-Application modal guarantee is pinned for both
    selectors. cmd_model is also the long-running interaction the
    user reaches for most often, so the regression surface is high.
    """
    from core.commands import CommandContext
    from core.commands import provider as provider_commands

    class _StubController:
        def __init__(self) -> None:
            self.calls: list[Any] = []

            async def _await(callable_: Any) -> str | None:
                self.calls.append(callable_)
                return "picked-alias"

            self.run_selector = _await

    class _StubSession:
        def __init__(self) -> None:
            self.model_alias = "stub-model"

    async def _drive() -> None:
        controller = _StubController()
        captured: list[Any] = []

        async def _fake_cc_style_model_selector(_models: Any, _alias: str) -> str | None:
            captured.append("direct")
            return "picked-alias"

        original = getattr(
            provider_commands, "cc_style_model_selector", None
        )
        original_visible_models = getattr(
            provider_commands, "_visible_models", None
        )
        original_models = getattr(provider_commands, "MODELS", None)
        original_validate = getattr(provider_commands, "validate_api_key", None)
        provider_commands.cc_style_model_selector = _fake_cc_style_model_selector  # type: ignore[assignment]
        # `_visible_models` is read inside cmd_model; make it return
        # at least one entry so the selector branch is taken.
        provider_commands._visible_models = lambda: {"stub-model": {"provider": "stub", "desc": ""}}  # type: ignore[assignment]
        # The print path looks up `MODELS[result]['color']` after the
        # selector returns; give the stub a color entry so the print
        # path does not crash on a KeyError.
        provider_commands.MODELS = {  # type: ignore[attr-defined]
            "picked-alias": {"color": "white"},
        }
        provider_commands.validate_api_key = lambda _alias: (True, "ENV")  # type: ignore[assignment]
        try:
            ctx = CommandContext(
                verb="/model",
                arg="",
                arg2="",
                session=_StubSession(),
                terminal_controller=controller,
            )
            await provider_commands.cmd_model(ctx)
        finally:
            if original is not None:
                provider_commands.cc_style_model_selector = original  # type: ignore[assignment]
            if original_visible_models is not None:
                provider_commands._visible_models = original_visible_models  # type: ignore[assignment]
            if original_models is not None:
                provider_commands.MODELS = original_models  # type: ignore[attr-defined]
            if original_validate is not None:
                provider_commands.validate_api_key = original_validate  # type: ignore[assignment]
        assert controller.calls, (
            "cmd_model must invoke controller.run_selector when a "
            "controller is attached to the CommandContext"
        )
        assert captured == [], (
            f"cmd_model must not call cc_style_model_selector "
            f"directly when a controller is present; saw {captured!r}"
        )

    asyncio.run(_drive())


def test_provider_dispatch_uses_run_selector_when_controller_is_present() -> None:
    """cmd_provider must route the TUI through controller.run_selector.

    When /provider is called with no arguments the interactive
    provider TUI panel must be scheduled through
    ``controller.run_selector`` so the main ``Application`` identity
    is preserved (ADR 0010).
    """
    from core.commands import CommandContext
    from core.commands import provider as provider_commands

    class _StubController:
        def __init__(self) -> None:
            self.calls: list[Any] = []

            async def _await(callable_: Any) -> None:
                self.calls.append(callable_)
                return None

            self.run_selector = _await

    class _StubSession:
        pass

    async def _drive() -> None:
        controller = _StubController()
        captured: list[str] = []

        async def _fake_run_provider_tui() -> None:
            captured.append("direct")

        # The provider handler imports ``run_provider_tui`` lazily
        # from ``core.provider_tui``; intercept the import by
        # patching ``core.provider_tui.run_provider_tui`` for the
        # duration of the test.
        from core import provider_tui as provider_tui_module
        original_provider_tui = provider_tui_module.run_provider_tui
        provider_tui_module.run_provider_tui = _fake_run_provider_tui  # type: ignore[assignment]
        try:
            ctx = CommandContext(
                verb="/provider",
                arg="",
                arg2="",
                session=_StubSession(),
                terminal_controller=controller,
            )
            await provider_commands.cmd_provider(ctx)
        finally:
            provider_tui_module.run_provider_tui = original_provider_tui  # type: ignore[assignment]
        assert controller.calls, (
            "cmd_provider must invoke controller.run_selector when a "
            "controller is attached to the CommandContext"
        )
        assert captured == [], (
            f"cmd_provider must not call run_provider_tui directly "
            f"when a controller is present; saw {captured!r}"
        )

    asyncio.run(_drive())


def test_skills_dispatch_uses_run_selector_when_controller_is_present() -> None:
    """cmd_skills must route the TUI through controller.run_selector.

    /skills launches the interactive skill pack selector. Per ADR
    0010 it must go through ``controller.run_selector`` when a
    controller is attached so the main ``Application`` identity is
    preserved.
    """
    from core.commands import CommandContext
    from core.commands import tools as tools_commands

    class _StubController:
        def __init__(self) -> None:
            self.calls: list[Any] = []

            async def _await(callable_: Any) -> bool:
                self.calls.append(callable_)
                return False

            self.run_selector = _await

    class _StubSession:
        pass

    async def _drive() -> None:
        controller = _StubController()
        captured: list[str] = []

        async def _fake_run_skill_tui(_scanner: Any) -> bool:
            captured.append("direct")
            return False

        # cmd_skills imports ``run_skill_tui`` lazily from
        # ``core.skill_tui``; patch the symbol on its origin module so
        # the lazy import sees the stub.
        from core import skill_tui as skill_tui_module
        original_skill_tui = skill_tui_module.run_skill_tui
        skill_tui_module.run_skill_tui = _fake_run_skill_tui  # type: ignore[assignment]
        try:
            ctx = CommandContext(
                verb="/skills",
                arg="",
                arg2="",
                session=_StubSession(),
                terminal_controller=controller,
            )
            await tools_commands.cmd_skills(ctx)
        finally:
            skill_tui_module.run_skill_tui = original_skill_tui  # type: ignore[assignment]
        assert controller.calls, (
            "cmd_skills must invoke controller.run_selector when a "
            "controller is attached to the CommandContext"
        )
        assert captured == [], (
            f"cmd_skills must not call run_skill_tui directly when a "
            f"controller is present; saw {captured!r}"
        )

    asyncio.run(_drive())


def test_skills_tui_exposes_an_embedded_modal_for_the_live_application() -> None:
    """The real skills panel must be mountable without creating an Application.

    This deliberately instantiates the production ``SkillPackTUI`` instead of
    replacing ``run_skill_tui`` with a coroutine.  The embedded contract is
    the seam used by the live controller; a standalone ``run_async`` path
    would not provide a container or key bindings for the host application.
    """
    from core.skill_tui import SkillPackTUI

    class _Scanner:
        def scan_all(self, *, include_disabled: bool) -> list[dict[str, Any]]:
            assert include_disabled is True
            return []

        def _read_enabled(self) -> set[str] | None:
            return set()

    tui = SkillPackTUI(_Scanner())  # type: ignore[arg-type]
    from prompt_toolkit.application import Application

    tui.bind_application(Application())
    spec = tui.build_modal(lambda _result: None, lambda: None)
    assert spec.container is not None
    assert spec.key_bindings is not None
    assert spec.focus is not None


def test_cmd_skills_real_dispatch_keeps_host_application_alive(monkeypatch: Any) -> None:
    """The public /skills path must mount and close on the host Application."""
    from core import session as session_module
    from core import skill_tui as skill_tui_module
    from core.commands import CommandContext
    from core.commands import tools as tools_commands
    from prompt_toolkit.input.defaults import create_pipe_input

    class _Scanner:
        def scan_all(self, *, include_disabled: bool) -> list[dict[str, Any]]:
            assert include_disabled is True
            return []

        def _read_enabled(self) -> set[str] | None:
            return set()

        def invalidate_cache(self) -> None:
            return None

        def _write_enabled(self, _selected: set[str]) -> None:
            return None

    class _Session(_StubSession):
        pass

    async def _drive() -> None:
        with create_pipe_input() as pipe:
            created_apps: list[object] = []
            original_application = skill_tui_module.Application

            def _count_application(*args: Any, **kwargs: Any) -> Any:
                created_apps.append(object())
                return original_application(*args, **kwargs)

            monkeypatch.setattr(skill_tui_module, "Application", _count_application)
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            session = _Session()
            controller = _make_controller(terminal, session)
            monkeypatch.setattr(session_module, "_skill_scanner", _Scanner())
            await controller.start()
            application = terminal.application
            assert application is not None
            exit_calls: list[object] = []

            def _spy_exit(*_args: Any, **_kwargs: Any) -> None:
                exit_calls.append(object())

            application.exit = _spy_exit  # type: ignore[method-assign]
            before_task = controller._task
            command_task = asyncio.create_task(
                tools_commands.cmd_skills(
                    CommandContext(
                        verb="/skills",
                        arg="",
                        arg2="",
                        session=session,
                        terminal_controller=controller,
                    )
                )
            )
            try:
                for _ in range(100):
                    if terminal.selector_registry.has_embedded:
                        break
                    await asyncio.sleep(0.01)
                else:  # pragma: no cover - timeout safety
                    raise AssertionError("/skills did not mount its live modal")
                await asyncio.sleep(0.05)
                assert any(
                    "Skill Pack Manager" in line
                    for line in terminal.rendered_screen_lines()
                )
                pipe.send_text("\x1b")
                await asyncio.wait_for(command_task, timeout=2)
                assert exit_calls == [], "closing /skills must not exit the host app"
                assert created_apps == [], "the /skills path must not create a second Application"
                assert terminal.application is application
                assert controller._task is before_task
            finally:
                if not command_task.done():
                    command_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await command_task
                if controller._task is not None and not controller._task.done():
                    controller._task.cancel()
                    with suppress(asyncio.CancelledError, BaseException):
                        await controller._task
                terminal.restore_output_proxy()
                session._live_terminal_active = False

    asyncio.run(_drive())


def test_cmd_provider_real_dispatch_keeps_host_application_alive(monkeypatch: Any) -> None:
    """The public /provider path must mount and close on the host Application."""
    from core.commands import CommandContext
    from core.commands import provider as provider_commands
    from core import provider_tui as provider_tui_module
    from prompt_toolkit.input.defaults import create_pipe_input

    async def _drive() -> None:
        with create_pipe_input() as pipe:
            created_apps: list[object] = []
            original_application = provider_tui_module.Application

            def _count_application(*args: Any, **kwargs: Any) -> Any:
                created_apps.append(object())
                return original_application(*args, **kwargs)

            monkeypatch.setattr(provider_tui_module, "Application", _count_application)
            terminal = PersistentTerminal(input=pipe, output=DummyOutput())
            session = _StubSession()
            controller = _make_controller(terminal, session)
            await controller.start()
            application = terminal.application
            assert application is not None
            exit_calls: list[object] = []

            def _spy_exit(*_args: Any, **_kwargs: Any) -> None:
                exit_calls.append(object())

            application.exit = _spy_exit  # type: ignore[method-assign]
            before_task = controller._task
            command_task = asyncio.create_task(
                provider_commands.cmd_provider(
                    CommandContext(
                        verb="/provider",
                        arg="",
                        arg2="",
                        session=session,
                        terminal_controller=controller,
                    )
                )
            )
            try:
                for _ in range(100):
                    if terminal.selector_registry.has_embedded:
                        break
                    await asyncio.sleep(0.01)
                else:  # pragma: no cover - timeout safety
                    raise AssertionError("/provider did not mount its live modal")
                await asyncio.sleep(0.05)
                assert any(
                    "Provider Manager" in line
                    for line in terminal.rendered_screen_lines()
                )
                pipe.send_text("\x1b")
                await asyncio.wait_for(command_task, timeout=2)
                assert exit_calls == [], "closing /provider must not exit the host app"
                assert created_apps == [], "the /provider path must not create a second Application"
                assert terminal.application is application
                assert controller._task is before_task
            finally:
                if not command_task.done():
                    command_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await command_task
                if controller._task is not None and not controller._task.done():
                    controller._task.cancel()
                    with suppress(asyncio.CancelledError, BaseException):
                        await controller._task
                terminal.restore_output_proxy()
                session._live_terminal_active = False

    asyncio.run(_drive())
