"""tests/test_path_policy.py - Tests for core/path_policy.py.

Covers:
  - resolve_within: traversal, symlinks, sibling-prefix, absolute/relative
  - safe_filename_fragment: sanitization, fallback
  - Integration: file_ops write containment, browser screenshot containment,
    MCP binary asset filename sanitization.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.path_policy import resolve_within, safe_filename_fragment

# ---------------------------------------------------------------------------
# resolve_within
# ---------------------------------------------------------------------------


class TestResolveWithin:
    """Unit tests for the resolve_within() containment check."""

    def test_relative_path_inside_root(self, tmp_path: Path) -> None:
        result = resolve_within(tmp_path, "subdir/file.txt")
        assert result == (tmp_path / "subdir" / "file.txt").resolve()

    def test_absolute_path_inside_root(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "file.txt"
        target.parent.mkdir(parents=True)
        target.touch()
        result = resolve_within(tmp_path, target)
        assert result == target.resolve()

    def test_dotdot_traversal_blocked(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="escapes root"):
            resolve_within(tmp_path, "../etc/passwd")

    def test_dotdot_traversal_blocked_absolute(self, tmp_path: Path) -> None:
        """Even an absolute path that resolves outside root is blocked."""
        outside = tmp_path.parent / "outside.txt"
        outside.touch()
        with pytest.raises(ValueError, match="escapes root"):
            resolve_within(tmp_path, outside)

    def test_deep_dotdot_traversal_blocked(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="escapes root"):
            resolve_within(tmp_path, "a/b/../../../etc/passwd")

    def test_sibling_prefix_not_confused(self, tmp_path: Path) -> None:
        """A path under /root-evil must not pass containment for /root."""
        root = tmp_path / "root"
        root.mkdir()
        evil = tmp_path / "root-evil"
        evil.mkdir()
        with pytest.raises(ValueError, match="escapes root"):
            resolve_within(root, evil)

    def test_symlink_inside_root_allowed(self, tmp_path: Path) -> None:
        target = tmp_path / "real.txt"
        target.write_text("ok")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        result = resolve_within(tmp_path, link)
        assert result == target.resolve()

    def test_symlink_escape_blocked(self, tmp_path: Path) -> None:
        """A symlink pointing outside root must be blocked."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = root / "escape.txt"
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes root"):
            resolve_within(root, link)

    def test_root_itself_allowed(self, tmp_path: Path) -> None:
        result = resolve_within(tmp_path, ".")
        assert result == tmp_path.resolve()

    def test_root_as_candidate_allowed(self, tmp_path: Path) -> None:
        result = resolve_within(tmp_path, tmp_path)
        assert result == tmp_path.resolve()


# ---------------------------------------------------------------------------
# safe_filename_fragment
# ---------------------------------------------------------------------------


class TestSafeFilenameFragment:
    """Unit tests for safe_filename_fragment()."""

    def test_clean_name_unchanged(self) -> None:
        assert safe_filename_fragment("report-2026.json") == "report-2026.json"

    def test_path_separators_stripped(self) -> None:
        result = safe_filename_fragment("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_special_characters_replaced(self) -> None:
        result = safe_filename_fragment("file name@#$%.txt")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result
        assert "%" not in result

    def test_empty_returns_fallback(self) -> None:
        assert safe_filename_fragment("") == "unnamed"
        assert safe_filename_fragment("../..") == "unnamed"
        assert safe_filename_fragment("///") == "unnamed"

    def test_custom_fallback(self) -> None:
        assert safe_filename_fragment("", fallback="anon") == "anon"

    def test_server_name_with_slashes(self) -> None:
        """MCP server names like '../../evil' must be sanitized."""
        result = safe_filename_fragment("../../evil")
        assert ".." not in result
        assert "/" not in result


# ---------------------------------------------------------------------------
# Integration: file_ops write containment
# ---------------------------------------------------------------------------


class TestFileOpsWriteContainment:
    """Integration tests verifying file_ops uses canonical containment."""

    def test_write_dotdot_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools import file_ops

        monkeypatch.setattr(file_ops, "_session_workspace_dir", [str(tmp_path)])
        monkeypatch.setattr(file_ops, "WORKSPACE_DIR", str(tmp_path))

        _resolved, err = file_ops._resolve_write_path("../../etc/passwd")
        assert err != "", f"expected security block for ../ traversal, got: {err}"

    def test_write_sibling_prefix_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools import file_ops

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        evil = tmp_path / "workspace-evil"
        evil.mkdir()
        monkeypatch.setattr(file_ops, "_session_workspace_dir", [str(workspace)])
        monkeypatch.setattr(file_ops, "WORKSPACE_DIR", str(workspace))

        _resolved, err = file_ops._resolve_write_path(str(evil / "file.txt"))
        assert err != "", "expected security block for sibling-prefix path"

    def test_write_no_directory_creation_before_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_resolve_write_path must not create directories for invalid paths."""
        from tools import file_ops

        monkeypatch.setattr(file_ops, "_session_workspace_dir", [str(tmp_path)])
        monkeypatch.setattr(file_ops, "WORKSPACE_DIR", str(tmp_path))

        before = set(tmp_path.rglob("*"))
        file_ops._resolve_write_path("../../etc/passwd")
        after = set(tmp_path.rglob("*"))
        assert before == after, "directories were created for an invalid path"


# ---------------------------------------------------------------------------
# Integration: browser screenshot containment
# ---------------------------------------------------------------------------


class TestBrowserScreenshotContainment:
    """Integration tests verifying browser_ops uses canonical containment."""

    def test_safe_path_blocks_dotdot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools import browser_ops

        monkeypatch.setattr(
            browser_ops, "SCREENSHOT_DIR", str(tmp_path / "screenshots")
        )

        with pytest.raises(ValueError, match="escapes"):
            browser_ops._safe_path("../../etc/passwd")

    def test_safe_path_blocks_sibling_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools import browser_ops

        screenshots = tmp_path / "screenshots"
        screenshots.mkdir()
        evil = tmp_path / "screenshots-evil"
        evil.mkdir()
        monkeypatch.setattr(browser_ops, "SCREENSHOT_DIR", str(screenshots))

        with pytest.raises(ValueError, match="escapes"):
            browser_ops._safe_path(str(evil / "file.png"))


# ---------------------------------------------------------------------------
# Integration: MCP binary asset filename sanitization
# ---------------------------------------------------------------------------


class TestMCPBinaryAssetSanitization:
    """Integration tests verifying MCP server names are sanitized in filenames."""

    def test_save_binary_asset_with_hostile_server_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import mcp_client_manager

        monkeypatch.setattr(mcp_client_manager, "WORKSPACE_ASSETS", tmp_path / "assets")

        # A server name with path traversal must not escape the assets dir.
        result = mcp_client_manager._save_binary_asset(
            "iVBORw0KGgo=", "image/png", "../../evil"
        )
        if result.startswith("["):
            # Error is acceptable; what matters is no file outside assets.
            return
        assert str(tmp_path / "assets") in result, f"file escaped assets dir: {result}"
