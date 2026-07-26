"""Non-importing discovery and transactional lifecycle for PawnLogic Extensions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from config.paths import VERSION
from core.extension_contracts import (
    CommandContribution,
    CommandRegister,
    CommandUnregister,
    ExtensionContext,
    ExtensionContributions,
    ExtensionDescriptor,
    ExtensionImplementation,
    ExtensionManifest,
    ExtensionPhaseRegistrar,
    ExtensionPromptRegistrar,
    ExtensionState,
    ExtensionStatus,
    ExtensionToolRegistrar,
    PhaseContribution,
    PromptContribution,
)
from core.tool_registry import ToolRegistry, ToolSpec


ENTRY_POINT_GROUP = "pawnlogic.extensions"
SUPPORTED_API_VERSION = 1
ENABLED_STATE_PATH = Path("extensions") / "enabled.json"
_SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|token|password|passwd|secret|private[_-]?key)"
    r"(\s*[:=]\s*)[^\s,;]+"
)
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)(?:(?:[-+])([0-9A-Za-z.-]+))?$")
_SPEC_RE = re.compile(
    r"^(~=|==|!=|>=|<=|>|<)?\s*"
    r"(v?\d+(?:\.\d+)*(?:\.\*)?(?:[-+][0-9A-Za-z.-]+)?|\*)$"
)


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip()).lower()


def _safe_error(error: BaseException) -> str:
    """Return a short error without common secret-shaped values or tracebacks."""
    message = _SECRET_VALUE_RE.sub(r"\1\2<redacted>", str(error))
    message = re.sub(r"\s+", " ", message).strip()
    if not message:
        message = error.__class__.__name__
    return f"{error.__class__.__name__}: {message[:240]}"


def _version_key(value: str) -> tuple[tuple[int, ...], int, str]:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid version {value!r}")
    release = tuple(int(part) for part in match.group(1).split("."))
    suffix = (match.group(2) or "").lower()
    if not suffix:
        return release, 2, ""
    # This is deliberately small but handles the release/pre-release forms
    # used by the host contract without adding ``packaging`` as a dependency.
    if suffix.startswith(("a", "alpha")):
        rank = 0
    elif suffix.startswith(("b", "beta", "rc", "c")):
        rank = 1
    else:
        rank = 2
    return release, rank, suffix


def _compare_versions(left: str, right: str) -> int:
    left_key = _version_key(left)
    right_key = _version_key(right)
    left_release = left_key[0] + (0,) * max(0, len(right_key[0]) - len(left_key[0]))
    right_release = right_key[0] + (0,) * max(0, len(left_key[0]) - len(right_key[0]))
    left_full = (left_release, left_key[1], left_key[2])
    right_full = (right_release, right_key[1], right_key[2])
    if left_full > right_full:
        return 1
    if left_full < right_full:
        return -1
    return 0


def _matches_version_spec(version: str, spec: str) -> bool:
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("core_version_spec cannot be empty")
    for raw_clause in spec.split(","):
        clause = raw_clause.strip()
        match = _SPEC_RE.fullmatch(clause)
        if not match:
            raise ValueError(f"invalid core version specifier {spec!r}")
        operator, required = match.groups()
        if required == "*":
            continue
        if "*" in required:
            if operator not in (None, "==", "!=") or not required.endswith(".*"):
                raise ValueError(f"invalid wildcard version specifier {clause!r}")
            prefix = required.lstrip("v")[:-2]
            release = version.lstrip("v").split("-", 1)[0].split("+", 1)[0]
            matches = release == prefix or release.startswith(f"{prefix}.")
            effective_operator = operator or "=="
            if (effective_operator == "==" and not matches) or (
                effective_operator == "!=" and matches
            ):
                return False
            continue
        comparison = _compare_versions(version, required)
        operator = operator or "=="
        matched = {
            "==": comparison == 0,
            "!=": comparison != 0,
            ">=": comparison >= 0,
            "<=": comparison <= 0,
            ">": comparison > 0,
            "<": comparison < 0,
        }
        if operator == "~=":
            version_match = _VERSION_RE.fullmatch(required)
            assert version_match is not None
            base_parts = [int(part) for part in version_match.group(1).split(".")]
            if len(base_parts) < 2:
                raise ValueError(
                    f"compatible release specifier requires two version segments: {clause!r}"
                )
            upper_parts = base_parts[:-1]
            upper_parts[-1] += 1
            upper_version = ".".join(str(part) for part in upper_parts)
            if comparison < 0 or _compare_versions(version, upper_version) >= 0:
                return False
        elif not matched[operator]:
            return False
    return True


def _json_compatible(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int, float)):
        return True
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _json_compatible(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_json_compatible(item) for item in value)
    return False


def _value_matches_type(value: object, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _validate_config_value(value: object, schema: Mapping[str, object], path: str = "config") -> None:
    expected = schema.get("type")
    if expected is not None and (
        not isinstance(expected, str) or not _value_matches_type(value, expected)
    ):
        raise ValueError(f"{path} does not match schema type")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or value not in enum):
        raise ValueError(f"{path} is not an allowed value")
    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"{path}.properties must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ValueError(f"{path}.required must be a string list")
        missing = [item for item in required if item not in value]
        if missing:
            raise ValueError(f"missing required config key {missing[0]!r}")
        if schema.get("additionalProperties", True) is False:
            unexpected = [key for key in value if key not in properties]
            if unexpected:
                raise ValueError(f"unknown config key {unexpected[0]!r}")
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, Mapping):
                _validate_config_value(item, child_schema, f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            _validate_config_value(item, schema["items"], f"{path}[{index}]")


class _ContributionBuffer(
    ExtensionToolRegistrar,
    ExtensionPhaseRegistrar,
    ExtensionPromptRegistrar,
):
    """Collect contributions without exposing host registries to Extensions."""

    def __init__(self) -> None:
        self.tools: list[ToolSpec] = []
        self.commands: list[CommandContribution] = []
        self.phases: list[PhaseContribution] = []
        self.prompts: list[PromptContribution] = []

    def register_many(self, contributions: Sequence[Any]) -> None:
        items = tuple(contributions)
        if not items:
            return
        first = items[0]
        if isinstance(first, ToolSpec):
            if not all(isinstance(item, ToolSpec) for item in items):
                raise TypeError("tool contribution batch contains a non-ToolSpec")
            self.tools.extend(items)
        elif isinstance(first, CommandContribution):
            if not all(isinstance(item, CommandContribution) for item in items):
                raise TypeError("command contribution batch contains a non-command")
            self.commands.extend(items)
        elif isinstance(first, PhaseContribution):
            if not all(isinstance(item, PhaseContribution) for item in items):
                raise TypeError("phase contribution batch contains a non-phase")
            self.phases.extend(items)
        elif isinstance(first, PromptContribution):
            if not all(isinstance(item, PromptContribution) for item in items):
                raise TypeError("prompt contribution batch contains a non-prompt")
            self.prompts.extend(items)
        else:
            raise TypeError("unknown Extension contribution type")

    def snapshot(self) -> ExtensionContributions:
        return ExtensionContributions(
            tools=tuple(self.tools),
            commands=tuple(self.commands),
            phases=tuple(self.phases),
            prompts=tuple(self.prompts),
        )


class _EventSink:
    def emit(self, event: Mapping[str, object]) -> None:
        del event


@dataclass
class _Record:
    descriptor: ExtensionDescriptor
    entry_point: Any
    state: ExtensionState = ExtensionState.DISCOVERED
    error: str | None = None
    manifest: ExtensionManifest | None = None
    compatible: bool | None = None
    implementation: ExtensionImplementation | None = None
    contributions: ExtensionContributions = field(default_factory=ExtensionContributions)


class ExtensionManager:
    """Own Extension discovery, lifecycle, contribution ownership, and rollback."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        *,
        runtime_home: Path | str | None = None,
        entry_points: Iterable[Any] | Callable[[], Iterable[Any]] | None = None,
        core_version: str = VERSION,
        api_version: int = SUPPORTED_API_VERSION,
        configs: Mapping[str, Mapping[str, object]] | None = None,
        command_register: CommandRegister | None = None,
        command_unregister: CommandUnregister | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.runtime_home = Path(
            runtime_home
            if runtime_home is not None
            else os.environ.get("PAWNLOGIC_HOME", Path.home() / ".pawnlogic")
        ).expanduser()
        self._entry_points_source = entry_points
        self.core_version = core_version
        self.api_version = api_version
        self._configs = dict(configs or {})
        if (command_register is None) != (command_unregister is None):
            raise ValueError("command_register and command_unregister must be provided together")
        self._command_register = command_register
        self._command_unregister = command_unregister
        self._records: dict[str, _Record] = {}
        self._descriptors: tuple[ExtensionDescriptor, ...] | None = None
        self._duplicate_names: set[str] = set()
        self._persisted_enabled = self._read_enabled_names()
        self._owned_tool_names: dict[str, set[str]] = {}
        self._commands: dict[str, tuple[str, CommandContribution]] = {}
        self._registered_command_owners: set[str] = set()
        self._phases: dict[str, tuple[str, PhaseContribution]] = {}
        self._prompts: dict[str, tuple[str, PromptContribution]] = {}

    @property
    def enabled_state_path(self) -> Path:
        return self.runtime_home / ENABLED_STATE_PATH

    def _read_enabled_names(self) -> set[str]:
        try:
            raw = json.loads(self.enabled_state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return set()
            return {_canonical_name(item) for item in raw if isinstance(item, str) and item.strip()}
        except (OSError, ValueError, TypeError):
            return set()

    def _write_enabled_names(self, names: set[str]) -> None:
        target = self.enabled_state_path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".enabled-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(sorted(names), handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        except Exception:
            with suppress(OSError):
                os.unlink(temporary_name)
            raise

    def _get_entry_points(self) -> tuple[Any, ...]:
        source = self._entry_points_source
        if source is not None:
            values = source() if callable(source) else source
            return tuple(values)
        try:
            values = metadata.entry_points(group=ENTRY_POINT_GROUP)
        except TypeError:
            values = metadata.entry_points().select(group=ENTRY_POINT_GROUP)
        return tuple(values)

    @staticmethod
    def _distribution_name(entry_point: Any) -> str:
        distribution = getattr(entry_point, "dist", None)
        name = getattr(distribution, "name", None)
        if not name and distribution is not None:
            metadata_map = getattr(distribution, "metadata", None)
            if metadata_map is not None:
                name = metadata_map.get("Name")
        return str(name or "unknown-distribution")

    @staticmethod
    def _distribution_version(entry_point: Any) -> str:
        distribution = getattr(entry_point, "dist", None)
        return str(getattr(distribution, "version", None) or "0")

    def discover(self) -> tuple[ExtensionDescriptor, ...]:
        """Enumerate metadata only; no EntryPoint.load call is made here."""
        if self._descriptors is not None:
            return self._descriptors
        discovered: list[tuple[ExtensionDescriptor, Any]] = []
        for entry_point in self._get_entry_points():
            raw_name = str(getattr(entry_point, "name", "")).strip() or "<invalid>"
            name = _canonical_name(raw_name)
            descriptor = ExtensionDescriptor(
                name=name,
                distribution=self._distribution_name(entry_point),
                version=self._distribution_version(entry_point),
                entry_point=str(getattr(entry_point, "value", "<invalid>")),
                enabled=name in self._persisted_enabled,
                compatible=None,
            )
            discovered.append((descriptor, entry_point))
        counts: dict[str, int] = {}
        for descriptor, _entry_point in discovered:
            counts[descriptor.name] = counts.get(descriptor.name, 0) + 1
        self._duplicate_names = {name for name, count in counts.items() if count > 1}
        result: list[ExtensionDescriptor] = []
        for descriptor, entry_point in sorted(discovered, key=lambda item: (item[0].name, item[0].distribution)):
            if descriptor.name in self._duplicate_names:
                descriptor = ExtensionDescriptor(
                    name=descriptor.name,
                    distribution=descriptor.distribution,
                    version=descriptor.version,
                    entry_point=descriptor.entry_point,
                    enabled=descriptor.enabled,
                    compatible=False,
                    error="duplicate extension name",
                )
            result.append(descriptor)
            self._records.setdefault(descriptor.name, _Record(descriptor, entry_point))
        self._descriptors = tuple(result)
        return self._descriptors

    def refresh_discovery(self) -> tuple[ExtensionDescriptor, ...]:
        """Refresh entry-point metadata without loading any Extension code."""
        previous_records = self._records
        self._descriptors = None
        self._duplicate_names = set()
        self._records = {}
        descriptors = self.discover()

        # Keep already-running implementations alive while replacing only
        # their metadata record. An installed distribution may disappear from
        # the next metadata snapshot; retain that active record for shutdown
        # and explicit disablement, but never load code during refresh.
        refreshed_records = self._records
        for name, previous in previous_records.items():
            if previous.implementation is None:
                continue
            current = refreshed_records.get(name)
            if current is None:
                refreshed_records[name] = previous
                continue
            current.state = previous.state
            current.error = previous.error
            current.manifest = previous.manifest
            current.compatible = previous.compatible
            current.implementation = previous.implementation
            current.contributions = previous.contributions
        return descriptors

    @staticmethod
    def _coerce_manifest(value: object) -> ExtensionManifest:
        if isinstance(value, ExtensionManifest):
            return value
        if isinstance(value, Mapping):
            return ExtensionManifest(**dict(value))
        raise TypeError("Extension export must provide an ExtensionManifest")

    @staticmethod
    def _resolve_implementation(export: object) -> tuple[ExtensionManifest, ExtensionImplementation]:
        manifest = getattr(export, "manifest", None)
        candidate: object = export
        factory = getattr(export, "factory", None)
        if callable(factory):
            candidate = factory()
        elif isinstance(export, type) or (
            callable(export) and not callable(getattr(export, "start", None))
        ):
            candidate = export()
        if manifest is None:
            manifest = getattr(candidate, "manifest", None)
        manifest = ExtensionManager._coerce_manifest(manifest)
        if not callable(getattr(candidate, "start", None)):
            raise TypeError("Extension implementation must define start(context)")
        if not callable(getattr(candidate, "stop", None)):
            raise TypeError("Extension implementation must define stop()")
        return manifest, candidate  # type: ignore[return-value]

    @staticmethod
    def _distribution_matches(distribution: str, name: str) -> bool:
        left = _canonical_name(distribution)
        right = _canonical_name(name)
        return left == right or left.endswith(f"-{right}")

    def _validate_manifest(self, record: _Record, manifest: ExtensionManifest) -> None:
        if _canonical_name(manifest.name) != record.descriptor.name:
            raise ValueError("manifest name does not match entry point name")
        if not self._distribution_matches(record.descriptor.distribution, manifest.name):
            raise ValueError("manifest name does not match distribution")
        if _compare_versions(manifest.version, record.descriptor.version) != 0:
            raise ValueError("manifest version does not match distribution version")
        if manifest.api_version != self.api_version:
            raise ValueError(f"unsupported Extension API version {manifest.api_version}")
        if not _matches_version_spec(self.core_version, manifest.core_version_spec):
            raise ValueError("Extension is incompatible with this core version")
        if not isinstance(manifest.config_schema, Mapping) or not _json_compatible(manifest.config_schema):
            raise ValueError("config_schema is not JSON-compatible")

    def _config_for(self, name: str) -> Mapping[str, object]:
        for key, value in self._configs.items():
            if _canonical_name(key) == name:
                return dict(value)
        return {}

    def _validate_config(self, name: str, manifest: ExtensionManifest) -> Mapping[str, object]:
        config = self._config_for(name)
        _validate_config_value(config, manifest.config_schema)
        return config

    def _existing_tool(self, name: str) -> bool:
        if self.tool_registry is None:
            return False
        get_spec = getattr(self.tool_registry, "get_spec", None)
        if callable(get_spec):
            return get_spec(name) is not None
        snapshot = getattr(self.tool_registry, "snapshot_specs", None)
        return any(spec.name == name for spec in snapshot()) if callable(snapshot) else False

    def _validate_contributions(self, owner: str, contributions: ExtensionContributions) -> None:
        for specs in (contributions.tools,):
            names = [spec.name for spec in specs]
            if len(names) != len(set(names)):
                raise ValueError("duplicate Tool name in Extension contributions")
            if self.tool_registry is None and specs:
                raise RuntimeError("ToolRegistry is required for Tool contributions")
            for name in names:
                owner_of = getattr(self.tool_registry, "owner_of", None)
                existing_owner = owner_of(name) if callable(owner_of) else None
                if self._existing_tool(name) or (existing_owner is not None and existing_owner != owner):
                    raise ValueError(f"Tool name conflict: {name}")
        for label, values in (
            ("command", contributions.commands),
            ("phase", contributions.phases),
            ("prompt", contributions.prompts),
        ):
            names = [item.name for item in values]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate {label} name in Extension contributions")
            owned = {name for source, item in getattr(self, f"_{label}s").values() if source != owner for name in (item.name,)}
            conflict = owned.intersection(names)
            if conflict:
                raise ValueError(f"{label} name conflict: {sorted(conflict)[0]}")

    def _register_tools(self, owner: str, specs: tuple[ToolSpec, ...]) -> None:
        if not specs:
            return
        assert self.tool_registry is not None
        register_owned = getattr(self.tool_registry, "register_many_owned", None)
        if callable(register_owned):
            register_owned(owner, specs)
        else:
            self.tool_registry.register_many(specs)
        self._owned_tool_names[owner] = {spec.name for spec in specs}

    def _unregister_tools(self, owner: str) -> None:
        if self.tool_registry is None:
            return
        unregister_owner = getattr(self.tool_registry, "unregister_owner", None)
        if callable(unregister_owner):
            unregister_owner(owner)
        else:
            unregister = getattr(self.tool_registry, "unregister", None)
            if callable(unregister):
                for name in self._owned_tool_names.get(owner, set()):
                    unregister(name)
        self._owned_tool_names.pop(owner, None)

    def _register_commands(
        self,
        owner: str,
        contributions: tuple[CommandContribution, ...],
    ) -> None:
        if self._command_register is None:
            # Compatibility mode keeps contributions in command_snapshot();
            # host dispatch is wired only when both adapters are injected.
            return
        if any(not callable(item.handler) for item in contributions):
            raise ValueError(
                "command handler is required when command registration is configured"
            )
        handlers = tuple((item.name, item.handler) for item in contributions)
        self._registered_command_owners.add(owner)
        try:
            self._command_register(owner, handlers)  # type: ignore[arg-type]
        except Exception:
            with suppress(Exception):
                assert self._command_unregister is not None
                self._command_unregister(owner)
            self._registered_command_owners.discard(owner)
            raise

    def _unregister_commands(self, owner: str) -> None:
        if owner not in self._registered_command_owners:
            return
        assert self._command_unregister is not None
        self._command_unregister(owner)
        self._registered_command_owners.discard(owner)

    def _add_owned_state(self, owner: str, contributions: ExtensionContributions) -> None:
        for item in contributions.commands:
            self._commands[item.name] = (owner, item)
        for item in contributions.phases:
            self._phases[item.name] = (owner, item)
        for item in contributions.prompts:
            self._prompts[item.name] = (owner, item)

    def _remove_owned_state(self, owner: str) -> None:
        for store in (self._commands, self._phases, self._prompts):
            for name, (source, _item) in tuple(store.items()):
                if source == owner:
                    del store[name]

    def _status(self, name: str) -> ExtensionStatus:
        record = self._records.get(name)
        if record is None:
            return ExtensionStatus(name, ExtensionState.UNAVAILABLE, False, False, "extension not discovered")
        return ExtensionStatus(
            name=name,
            state=record.state,
            enabled=record.state is ExtensionState.ENABLED,
            compatible=record.compatible if record.compatible is not None else record.descriptor.compatible,
            error=record.error or record.descriptor.error,
            manifest=record.manifest,
            persisted_enabled=name in self._persisted_enabled,
        )

    def enable(self, name: str) -> ExtensionStatus:
        canonical = _canonical_name(name)
        self.discover()
        record = self._records.get(canonical)
        if record is None:
            return self._status(canonical)
        if record.state is ExtensionState.ENABLED:
            return self._status(canonical)
        if canonical in self._duplicate_names or record.descriptor.error:
            record.state = ExtensionState.FAILED
            record.error = "duplicate extension name"
            return self._status(canonical)
        record.state = ExtensionState.VALIDATING
        record.error = None
        record.manifest = None
        record.compatible = None
        implementation: ExtensionImplementation | None = None
        buffer = _ContributionBuffer()
        try:
            export = record.entry_point.load()
            manifest, implementation = self._resolve_implementation(export)
            record.manifest = manifest
            try:
                record.compatible = _matches_version_spec(self.core_version, manifest.core_version_spec)
            except ValueError:
                record.compatible = False
            self._validate_manifest(record, manifest)
            config = self._validate_config(canonical, manifest)
            context = ExtensionContext(
                name=canonical,
                core_version=self.core_version,
                runtime_home=self.runtime_home,
                config=config,
                tools=buffer,
                commands=buffer,
                prompts=buffer,
                phases=buffer,
                events=_EventSink(),
            )
            record.state = ExtensionState.STARTING
            returned = implementation.start(context)
            if returned is not None and not isinstance(returned, ExtensionContributions):
                raise TypeError("Extension start() must return ExtensionContributions or None")
            returned = returned or ExtensionContributions()
            collected = buffer.snapshot()
            contributions = ExtensionContributions(
                tools=collected.tools + returned.tools,
                commands=collected.commands + returned.commands,
                phases=collected.phases + returned.phases,
                prompts=collected.prompts + returned.prompts,
            )
            self._validate_contributions(canonical, contributions)
            self._register_tools(canonical, contributions.tools)
            self._register_commands(canonical, contributions.commands)
            self._add_owned_state(canonical, contributions)
            next_enabled = set(self._persisted_enabled)
            next_enabled.add(canonical)
            self._write_enabled_names(next_enabled)
            self._persisted_enabled = next_enabled
            record.manifest = manifest
            record.implementation = implementation
            record.contributions = contributions
            record.state = ExtensionState.ENABLED
            return self._status(canonical)
        except Exception as error:
            if implementation is not None:
                with suppress(Exception):
                    implementation.stop()
            with suppress(Exception):
                self._unregister_tools(canonical)
            with suppress(Exception):
                self._unregister_commands(canonical)
            self._remove_owned_state(canonical)
            record.implementation = None
            record.contributions = ExtensionContributions()
            record.state = ExtensionState.FAILED
            record.error = _safe_error(error)
            return self._status(canonical)

    def disable(self, name: str) -> ExtensionStatus:
        canonical = _canonical_name(name)
        self.discover()
        record = self._records.get(canonical)
        if record is None:
            return self._status(canonical)
        stop_error: str | None = None
        if record.implementation is not None:
            record.state = ExtensionState.STOPPING
            try:
                record.implementation.stop()
            except Exception as error:
                stop_error = _safe_error(error)
        try:
            self._unregister_tools(canonical)
        except Exception as error:
            stop_error = stop_error or _safe_error(error)
        try:
            self._unregister_commands(canonical)
        except Exception as error:
            stop_error = stop_error or _safe_error(error)
        self._remove_owned_state(canonical)
        next_enabled = set(self._persisted_enabled)
        next_enabled.discard(canonical)
        try:
            self._write_enabled_names(next_enabled)
            self._persisted_enabled = next_enabled
        except Exception as error:
            stop_error = stop_error or _safe_error(error)
        record.implementation = None
        record.contributions = ExtensionContributions()
        record.state = ExtensionState.DISABLED
        record.error = stop_error
        return self._status(canonical)

    def status(self, name: str | None = None) -> tuple[ExtensionStatus, ...]:
        self.discover()
        if name is not None:
            return (self._status(_canonical_name(name)),)
        return tuple(self._status(item.name) for item in self._descriptors or ())

    def activate_persisted(self) -> tuple[ExtensionStatus, ...]:
        """Attempt persisted enablement in canonical order, isolating failures."""
        self.discover()
        statuses: list[ExtensionStatus] = []
        for name in sorted(self._persisted_enabled):
            try:
                statuses.append(self.enable(name))
            except Exception as error:  # pragma: no cover - defensive adapter boundary
                record = self._records.get(name)
                if record is not None:
                    record.state = ExtensionState.FAILED
                    record.error = _safe_error(error)
                statuses.append(self._status(name))
        return tuple(statuses)

    def command_snapshot(self) -> tuple[CommandContribution, ...]:
        return tuple(item for _owner, item in self._commands.values())

    def phase_snapshot(self) -> tuple[PhaseContribution, ...]:
        return tuple(item for _owner, item in self._phases.values())

    def prompt_snapshot(self) -> tuple[PromptContribution, ...]:
        return tuple(item for _owner, item in self._prompts.values())

    def owner_snapshot(self) -> Mapping[str, tuple[str, ...]]:
        return {
            "tools": tuple(sorted(self._owned_tool_names)),
            "commands": tuple(sorted({owner for owner, _item in self._commands.values()})),
            "phases": tuple(sorted({owner for owner, _item in self._phases.values()})),
            "prompts": tuple(sorted({owner for owner, _item in self._prompts.values()})),
        }

    def shutdown(self) -> None:
        """Stop active Extensions and remove runtime contributions.

        Persisted enablement is intentionally retained so a future startup
        Adapter can attempt explicit reactivation without this method writing
        state during core shutdown.
        """
        for canonical in sorted(self._records):
            record = self._records[canonical]
            if record.implementation is None:
                continue
            try:
                record.implementation.stop()
            except Exception as error:
                record.error = _safe_error(error)
            with suppress(Exception):
                self._unregister_tools(canonical)
            with suppress(Exception):
                self._unregister_commands(canonical)
            self._remove_owned_state(canonical)
            record.implementation = None
            record.contributions = ExtensionContributions()
            record.state = ExtensionState.DISABLED


ExtensionRuntime = ExtensionManager


__all__ = [
    "ENABLED_STATE_PATH",
    "ENTRY_POINT_GROUP",
    "SUPPORTED_API_VERSION",
    "ExtensionManager",
    "ExtensionRuntime",
]
