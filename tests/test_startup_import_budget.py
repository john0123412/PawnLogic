"""Startup import-budget tests.

Heavy optional stacks (browser automation, MCP client SDK) must stay out of
the CLI import path: core.session imports tools.browser_ops and the CLI exit
paths import core.session, so an eager probe there used to pull scrapling,
playwright, patchright, and the whole `mcp` package on every startup.

These tests run the imports in a subprocess so the parent test process's
module cache cannot mask a regression.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PAWNLOGIC_HOME"] = tempfile.mkdtemp(prefix="pawnlogic-import-")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        timeout=120,
    )


def test_cli_import_does_not_load_browser_stack():
    """Importing the CLI must not import the scrapling/patchright stack."""
    result = _run_isolated(
        "import sys\n"
        "import pawnlogic.cli\n"
        "heavy = [m for m in ('scrapling', 'playwright', 'patchright') if m in sys.modules]\n"
        "assert not heavy, f'heavy browser modules imported at startup: {heavy}'\n"
    )
    assert result.returncode == 0, result.stderr


def test_cli_import_does_not_load_mcp_package():
    """Importing the CLI must not import the mcp SDK."""
    result = _run_isolated(
        "import sys\n"
        "import pawnlogic.cli\n"
        "assert 'mcp' not in sys.modules, 'mcp SDK imported at startup'\n"
    )
    assert result.returncode == 0, result.stderr


def test_mcp_detach_without_attach_skips_manager_import():
    """Session teardown without a prior MCP attach must not import
    core.mcp_client_manager (whose module body would probe the mcp SDK)."""
    result = _run_isolated(
        "import sys\n"
        "import core.session\n"
        "assert core.session._EXTERNAL_MCP_ATTACHED is False\n"
        "core.session.detach_external_mcp_tools()\n"
        "assert 'core.mcp_client_manager' not in sys.modules\n"
        "assert 'mcp' not in sys.modules\n"
    )
    assert result.returncode == 0, result.stderr


def test_mcp_attach_gate_matches_manager_semantics():
    """A disabled/absent MCP config keeps the attach flag False."""
    result = _run_isolated(
        "import core.session\n"
        "core.session.attach_external_mcp_tools()\n"
        "assert core.session._EXTERNAL_MCP_ATTACHED is False\n"
    )
    assert result.returncode == 0, result.stderr


def test_browser_probe_is_lazy_and_status_renders():
    """Probes stay None at import, run on demand, and browser_tool_status()
    renders the availability line afterwards."""
    result = _run_isolated(
        "import tools.browser_ops as bo\n"
        "assert bo._scrapling_ok is None and bo._patchright_ok is None\n"
        "status = bo.browser_tool_status()\n"
        "assert 'Scrapling' in status and 'Patchright' in status\n"
        "assert bo._scrapling_ok in (True, False)\n"
        "assert bo._patchright_ok in (True, False)\n"
    )
    assert result.returncode == 0, result.stderr
