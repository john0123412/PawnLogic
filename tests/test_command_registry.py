"""Tests for ownership-aware slash command registration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.commands import (
    COMMANDS,
    CommandContext,
    command_owner,
    dispatch,
    register_owned_commands,
    unregister_owned_commands,
)


@pytest.fixture
def owned_commands():
    """Register test commands and remove only those commands on cleanup."""
    owners: list[str] = []

    def register_for_test(owner: str, handlers):
        register_owned_commands(owner, handlers)
        owners.append(owner)

    yield register_for_test

    for owner in reversed(owners):
        unregister_owned_commands(owner)


def _handler(value: str):
    async def handler(_ctx: CommandContext):
        return value

    return handler


def test_registration_is_atomic_for_batch_and_existing_conflicts(owned_commands):
    owner = "test.atomic"
    duplicate_verb = "/test_atomic_duplicate"
    fresh_verb = "/test_atomic_fresh"

    with pytest.raises(ValueError, match="duplicate command verb"):
        register_owned_commands(
            owner,
            [
                (duplicate_verb, _handler("first")),
                (duplicate_verb, _handler("second")),
            ],
        )
    assert duplicate_verb not in COMMANDS
    assert command_owner(duplicate_verb) is None

    with pytest.raises(ValueError, match="already registered"):
        register_owned_commands(
            owner,
            [
                (fresh_verb, _handler("fresh")),
                ("/help", _handler("must not replace builtin")),
            ],
        )
    assert fresh_verb not in COMMANDS
    assert command_owner(fresh_verb) is None
    assert command_owner("/help") == "builtin"


def test_owned_registration_preserves_order_and_dispatch_compatibility(owned_commands):
    owner = "test.dispatch"
    first = "/test_dispatch_first"
    second = "/test_dispatch_second"
    owned_commands(owner, [(first, _handler("first")), (second, _handler("second"))])

    assert list(COMMANDS)[-2:] == [first, second]
    assert command_owner(first) == owner
    assert command_owner(second) == owner

    ctx = CommandContext(
        verb=second,
        arg="",
        arg2="",
        session=SimpleNamespace(runtime_context=None),
        sink=SimpleNamespace(print=lambda _message: None),
    )
    assert asyncio.run(dispatch(ctx)) == "second"


def test_unregister_removes_only_the_requested_owner(owned_commands):
    first_owner = "test.remove.first"
    second_owner = "test.remove.second"
    first_verb = "/test_remove_first"
    second_verb = "/test_remove_second"
    owned_commands(first_owner, [(first_verb, _handler("first"))])
    owned_commands(second_owner, [(second_verb, _handler("second"))])

    unregister_owned_commands(first_owner)

    assert first_verb not in COMMANDS
    assert command_owner(first_verb) is None
    assert COMMANDS[second_verb] is not None
    assert command_owner(second_verb) == second_owner
    assert command_owner("/help") == "builtin"


def test_extensions_cannot_replace_builtin_commands(owned_commands):
    owner = "test.extension"
    new_verb = "/test_extension_new"

    with pytest.raises(ValueError, match="already registered"):
        register_owned_commands(
            owner,
            [
                ("/help", _handler("replacement")),
                (new_verb, _handler("new")),
            ],
        )

    assert COMMANDS["/help"] is not None
    assert command_owner("/help") == "builtin"
    assert new_verb not in COMMANDS


def test_invalid_verbs_are_rejected_before_mutation(owned_commands):
    owner = "test.invalid"
    valid_verb = "/test_invalid_valid"

    with pytest.raises(ValueError, match="must start with '/'"):
        register_owned_commands(owner, [("test_without_slash", _handler("bad"))])

    with pytest.raises(ValueError, match="must start with '/'"):
        register_owned_commands(
            owner,
            [(valid_verb, _handler("must not remain")), ("invalid", _handler("bad"))],
        )

    assert valid_verb not in COMMANDS
    with pytest.raises(ValueError, match="must start with '/'"):
        command_owner("invalid")


def test_builtin_decorator_registrations_have_builtin_owner():
    assert command_owner("/help") == "builtin"
    assert command_owner("/exit") == "builtin"
