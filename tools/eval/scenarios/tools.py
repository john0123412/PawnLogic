"""Safe local tool execution through the production Tool Registry interface."""

from __future__ import annotations

from pathlib import Path
import tempfile

from core.runtime_context import RuntimeContext
from core.tool_registry import ToolRegistry, ToolSpec
from core.trust import TrustBoundaryKind
from tools import file_ops


def _schema(name: str) -> dict:
    return next(item for item in file_ops.FILE_SCHEMAS if item["function"]["name"] == name)


def run_registry_tools() -> dict[str, object]:
    """Execute workspace-only handlers using complete ToolSpec registrations."""
    registry = ToolRegistry()
    registry.register_many(
        (
            ToolSpec(
                "write_file",
                file_ops.tool_write_file,
                _schema("write_file"),
                trust=TrustBoundaryKind.LOCAL,
                capabilities=frozenset({"workspace.write"}),
            ),
            ToolSpec(
                "read_file",
                file_ops.tool_read_file,
                _schema("read_file"),
                capabilities=frozenset({"workspace.read"}),
            ),
            ToolSpec(
                "list_dir",
                file_ops.tool_list_dir,
                _schema("list_dir"),
                capabilities=frozenset({"workspace.read"}),
            ),
        )
    )
    with tempfile.TemporaryDirectory(prefix="pawnlogic-registry-eval-") as tmp:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        context = RuntimeContext.for_test(cwd=workspace, workspace_dir=workspace)
        old_cwd = list(file_ops._session_cwd)
        old_workspace = list(file_ops._session_workspace_dir)
        try:
            file_ops.sync_runtime_context(context)
            with context.activate():
                write = registry.get_handler("write_file")
                read = registry.get_handler("read_file")
                listing = registry.get_handler("list_dir")
                assert write is not None and read is not None and listing is not None
                write_result = str(write({"path": "eval.txt", "content": "registry-ok\n"}))
                read_result = str(read({"path": str(workspace / "eval.txt")}))
                list_result = str(listing({"path": str(workspace)}))
        finally:
            file_ops._session_cwd[:] = old_cwd
            file_ops._session_workspace_dir[:] = old_workspace
    passed = (
        write_result.startswith("OK: wrote")
        and "registry-ok" in read_result
        and "eval.txt" in list_result
    )
    return {
        "status": "passed" if passed else "failed",
        "summary": "Executed safe workspace handlers through complete Tool Registry specs.",
        "api_calls": 0,
        "tool_calls": 3,
        "failure_class": "" if passed else "RegistryToolFailure",
    }


__all__ = ["run_registry_tools"]
