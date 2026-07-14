"""Tests for the ToolRegistry class (the single tool registration interface)."""

import pytest

from core.tool_registry import ToolRegistry, ToolSpec
from core.trust import TrustBoundaryKind


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def test_register_adds_handler_and_schema():
    reg = ToolRegistry()
    reg.register("alpha", lambda a: "ok", _schema("alpha"))
    assert reg.get_handler("alpha")({}) == "ok"
    assert reg.snapshot_schemas() == [_schema("alpha")]


def test_register_ignores_empty_name():
    reg = ToolRegistry()
    reg.register("", lambda a: "bad", _schema(""))
    assert reg.snapshot_map() == {}
    assert reg.snapshot_schemas() == []


def test_register_schema_only_handler_is_not_advertised():
    reg = ToolRegistry()
    reg.register("schema_only", None, _schema("schema_only"))
    assert "schema_only" not in reg.snapshot_map()
    assert reg.snapshot_schemas() == []


def test_register_none_schema_leaves_existing_schema():
    reg = ToolRegistry()
    reg.register("alpha", lambda a: 1, _schema("alpha"))
    reg.register("alpha", lambda a: 2)  # update handler only
    assert reg.get_handler("alpha")({}) == 2
    assert reg.snapshot_schemas() == [_schema("alpha")]


def test_unregister_removes_handler_and_schema():
    reg = ToolRegistry()
    reg.register("alpha", lambda a: 1, _schema("alpha"))
    reg.unregister("alpha")
    assert reg.get_handler("alpha") is None
    assert reg.snapshot_schemas() == []
    # Unregistering an unknown name is a no-op.
    reg.unregister("ghost")


def test_get_handler_unknown_returns_none():
    assert ToolRegistry().get_handler("nope") is None


def test_snapshot_map_is_a_copy():
    reg = ToolRegistry()
    reg.register("alpha", lambda a: 1)
    snap = reg.snapshot_map()
    snap["beta"] = lambda a: 2
    assert "beta" not in reg.snapshot_map()


def test_live_map_reflects_later_registrations_by_reference():
    reg = ToolRegistry()
    live = reg.live_map()
    reg.register("alpha", lambda a: 1)
    # Same dict object: a dynamic registration appears without re-fetching.
    assert "alpha" in live


def test_snapshot_schemas_is_fresh_list():
    reg = ToolRegistry()
    reg.register("alpha", lambda a: 1, _schema("alpha"))
    first = reg.snapshot_schemas()
    first.append("junk")
    assert reg.snapshot_schemas() == [_schema("alpha")]


def test_set_schemas_bulk_registers_by_function_name():
    reg = ToolRegistry()
    reg.register("a", lambda _a: "a")
    reg.register("b", lambda _a: "b")
    reg.set_schemas(
        [_schema("a"), _schema("b"), {"type": "function", "function": {"name": ""}}]
    )
    names = {s["function"]["name"] for s in reg.snapshot_schemas()}
    assert names == {"a", "b"}


def test_tool_spec_registers_metadata_atomically():
    reg = ToolRegistry()
    spec = ToolSpec(
        name="alpha",
        handler=lambda _args: "ok",
        schema=_schema("alpha"),
        phases=frozenset({"RECON"}),
        trust=TrustBoundaryKind.LOCAL,
        capabilities=frozenset({"read"}),
    )
    reg.register(spec)

    assert reg.get_spec("alpha") is spec
    assert reg.visible_specs("RECON") == (spec,)
    assert reg.visible_specs("GENERAL") == ()
    assert reg.get_capabilities("alpha") == frozenset({"read"})


def test_tool_spec_rejects_mismatched_schema_name_without_mutation():
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="does not match"):
        ToolSpec("alpha", lambda _args: "ok", _schema("beta"))
    assert reg.snapshot_map() == {}


def test_register_many_validates_duplicates_before_mutation():
    reg = ToolRegistry()
    specs = [
        ToolSpec("alpha", lambda _args: "one", _schema("alpha")),
        ToolSpec("alpha", lambda _args: "two", _schema("alpha")),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        reg.register_many(specs)
    assert reg.snapshot_map() == {}
