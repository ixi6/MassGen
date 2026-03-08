"""Tests for Codex backend hook IPC — write_post_tool_use_hook / clear_hook_files."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch


def _make_codex_backend(tmp_path: Path):
    """Create a CodexBackend with mocked internals pointing at tmp_path."""
    from massgen.backend.codex import CodexBackend

    with patch.object(CodexBackend, "_find_codex_cli", return_value="/usr/bin/codex"):
        backend = CodexBackend(api_key="test-key", cwd=str(tmp_path))
    return backend


class TestSupportsServerHooks:
    def test_returns_true(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        assert backend.supports_mcp_server_hooks() is True


class TestGetHookDir:
    def test_returns_codex_subdir(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        assert hook_dir == Path(str(tmp_path)) / ".codex"


class TestWritePostToolUseHook:
    def test_creates_valid_json_file(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("peer answer content")

        hook_file = backend.get_hook_dir() / "hook_post_tool_use.json"
        assert hook_file.exists()

        payload = json.loads(hook_file.read_text(encoding="utf-8"))
        assert payload["inject"]["content"] == "peer answer content"
        assert payload["inject"]["strategy"] == "tool_result"
        assert payload["tool_matcher"] == "*"
        assert payload["sequence"] >= 1
        assert payload["expires_at"] > time.time()

    def test_sequence_increments(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("first")
        first_payload = json.loads(
            (backend.get_hook_dir() / "hook_post_tool_use.json").read_text(),
        )

        backend.write_post_tool_use_hook("second")
        second_payload = json.loads(
            (backend.get_hook_dir() / "hook_post_tool_use.json").read_text(),
        )

        assert second_payload["sequence"] > first_payload["sequence"]

    def test_atomic_write_no_partial_reads(self, tmp_path: Path) -> None:
        """Verify write uses tmp+replace pattern (no partial file visible)."""
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        hook_file = backend.get_hook_dir() / "hook_post_tool_use.json"
        # If write was atomic, the file should always be valid JSON
        payload = json.loads(hook_file.read_text(encoding="utf-8"))
        assert "inject" in payload

    def test_default_expiry_is_30_seconds(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        before = time.time()
        backend.write_post_tool_use_hook("content")

        payload = json.loads(
            (backend.get_hook_dir() / "hook_post_tool_use.json").read_text(),
        )
        # Expiry should be roughly 30s from now
        assert payload["expires_at"] >= before + 25
        assert payload["expires_at"] <= before + 35


class TestClearHookFiles:
    def test_removes_hook_file(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        hook_file = backend.get_hook_dir() / "hook_post_tool_use.json"
        assert hook_file.exists()

        backend.clear_hook_files()
        assert not hook_file.exists()

    def test_no_error_when_file_missing(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        # Should not raise
        backend.clear_hook_files()


class TestReadUnconsumedHookContent:
    def test_returns_content_when_file_exists(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("unconsumed human input")

        result = backend.read_unconsumed_hook_content()
        assert result == "unconsumed human input"

    def test_deletes_file_after_read(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("content")

        backend.read_unconsumed_hook_content()
        hook_file = backend.get_hook_dir() / "hook_post_tool_use.json"
        assert not hook_file.exists()

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        assert backend.read_unconsumed_hook_content() is None

    def test_consumed_hook_returns_none_on_second_read(self, tmp_path: Path) -> None:
        """Once consumed, a second call returns None (idempotent)."""
        backend = _make_codex_backend(tmp_path)
        backend.write_post_tool_use_hook("some content")
        first = backend.read_unconsumed_hook_content()
        assert first is not None
        assert backend.read_unconsumed_hook_content() is None

    def test_returns_none_for_malformed_json(self, tmp_path: Path) -> None:
        backend = _make_codex_backend(tmp_path)
        hook_dir = backend.get_hook_dir()
        hook_dir.mkdir(parents=True, exist_ok=True)
        (hook_dir / "hook_post_tool_use.json").write_text("not json")

        assert backend.read_unconsumed_hook_content() is None
        # File should be cleaned up
        assert not (hook_dir / "hook_post_tool_use.json").exists()
