"""Tests for snapshot preservation during interrupted saves.

During interrupted/restart saves, existing snapshot_storage containing a
submitted answer must never be overwritten with incomplete workspace content.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.filesystem_manager._filesystem_manager import FilesystemManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_file(path: Path, name: str, content: str = "data") -> Path:
    """Create a file inside *path* with *name* and *content*."""
    path.mkdir(parents=True, exist_ok=True)
    f = path / name
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# TestSaveSnapshotPreserveExisting
# ---------------------------------------------------------------------------


class TestSaveSnapshotPreserveExisting:
    """Tests for `save_snapshot(preserve_existing_snapshot=…)`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path):
        """Create a minimal FilesystemManager with workspace + snapshot dirs."""
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()

        self.snapshot = tmp_path / "snapshot_storage"
        self.snapshot.mkdir()

        self.fm = FilesystemManager.__new__(FilesystemManager)
        self.fm.cwd = str(self.workspace)
        self.fm.snapshot_storage = self.snapshot
        self.fm.agent_id = "agent_a"
        self.fm.use_two_tier_workspace = False
        self.fm.is_shared_workspace = False

    # -- Test 1 --
    @pytest.mark.asyncio
    async def test_preserve_flag_skips_overwrite_when_snapshot_has_content(self):
        """preserve=True + snapshot has content → snapshot unchanged."""
        _create_file(self.snapshot, "deliverable.pptx", "real_content_282kb")
        _create_file(self.workspace, "scaffolding.txt", "partial")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await self.fm.save_snapshot(preserve_existing_snapshot=True)

        assert (self.snapshot / "deliverable.pptx").read_text() == "real_content_282kb"
        assert not (self.snapshot / "scaffolding.txt").exists()

    # -- Test 2 --
    @pytest.mark.asyncio
    async def test_preserve_flag_still_copies_to_empty_snapshot(self):
        """preserve=True + snapshot empty → workspace copied to snapshot."""
        _create_file(self.workspace, "partial_work.txt", "in_progress")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await self.fm.save_snapshot(preserve_existing_snapshot=True)

        assert (self.snapshot / "partial_work.txt").read_text() == "in_progress"

    # -- Test 3 --
    @pytest.mark.asyncio
    async def test_preserve_flag_still_saves_to_log_dirs(self, tmp_path: Path):
        """preserve=True + snapshot has content → log dir still gets workspace."""
        _create_file(self.snapshot, "deliverable.pptx", "real_content")
        _create_file(self.workspace, "scaffolding.txt", "partial")

        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=log_dir):
            await self.fm.save_snapshot(
                timestamp="20260228_120000_000000",
                preserve_existing_snapshot=True,
            )

        # snapshot_storage should be preserved (not overwritten)
        assert (self.snapshot / "deliverable.pptx").read_text() == "real_content"
        assert not (self.snapshot / "scaffolding.txt").exists()

        # Log dir should still get content (from snapshot_storage since workspace
        # may or may not be meaningful, but either way logs should capture state)
        log_workspace = log_dir / "agent_a" / "20260228_120000_000000" / "workspace"
        assert log_workspace.exists()

    # -- Test 4 --
    @pytest.mark.asyncio
    async def test_default_behavior_still_overwrites(self):
        """Default (preserve=False) overwrites snapshot with workspace."""
        _create_file(self.snapshot, "old.txt", "old_content")
        _create_file(self.workspace, "new.txt", "new_content")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await self.fm.save_snapshot()

        assert (self.snapshot / "new.txt").read_text() == "new_content"
        assert not (self.snapshot / "old.txt").exists()

    # -- Test 5 --
    @pytest.mark.asyncio
    async def test_empty_workspace_empty_snapshot_returns_early(self):
        """Both empty → early return, no errors."""
        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await self.fm.save_snapshot(preserve_existing_snapshot=True)

        # snapshot dir should still be empty (just the dir itself)
        assert not list(self.snapshot.iterdir())

    # -- Test 6 --
    @pytest.mark.asyncio
    async def test_empty_workspace_preserves_existing_snapshot(self):
        """workspace empty, snapshot has content → snapshot unchanged (existing behavior)."""
        _create_file(self.snapshot, "deliverable.pptx", "good_content")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await self.fm.save_snapshot()

        assert (self.snapshot / "deliverable.pptx").read_text() == "good_content"


# ---------------------------------------------------------------------------
# TestInterruptedTurnSnapshotPreservation
# ---------------------------------------------------------------------------


class TestInterruptedTurnSnapshotPreservation:
    """Tests for orchestrator's `_save_partial_workspace_snapshots_for_interrupted_turn`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.snapshot = tmp_path / "snapshot_storage"
        self.snapshot.mkdir()
        self.log_dir = tmp_path / "logs"
        self.log_dir.mkdir()

        # Minimal mock backend/filesystem_manager
        self.fm_mock = MagicMock()
        self.fm_mock.get_current_workspace.return_value = str(self.workspace)
        self.fm_mock.snapshot_storage = self.snapshot

        self.backend_mock = MagicMock()
        self.backend_mock.filesystem_manager = self.fm_mock

        self.agent_mock = MagicMock()
        self.agent_mock.backend = self.backend_mock

    def _make_orchestrator(self):
        """Create a minimal Orchestrator with mocked internals."""
        from massgen.orchestrator import Orchestrator

        orch = Orchestrator.__new__(Orchestrator)
        orch.agents = {"agent_a": self.agent_mock}
        return orch

    # -- Test 7 --
    def test_interrupted_turn_preserves_existing_snapshot(self):
        """snapshot has deliverable + workspace has content → snapshot unchanged."""
        _create_file(self.snapshot, "deliverable.pptx", "real_content_282kb")
        _create_file(self.workspace, "scaffolding.txt", "partial")

        orch = self._make_orchestrator()
        orch._save_partial_workspace_snapshots_for_interrupted_turn(
            agent_id="agent_a",
            backend=self.backend_mock,
            timestamp="20260228_120000_000000",
            log_session_dir=None,
        )

        assert (self.snapshot / "deliverable.pptx").read_text() == "real_content_282kb"
        assert not (self.snapshot / "scaffolding.txt").exists()

    # -- Test 8 --
    def test_interrupted_turn_copies_to_empty_snapshot(self):
        """snapshot empty + workspace has content → workspace copied."""
        _create_file(self.workspace, "partial_work.txt", "in_progress")

        orch = self._make_orchestrator()
        orch._save_partial_workspace_snapshots_for_interrupted_turn(
            agent_id="agent_a",
            backend=self.backend_mock,
            timestamp="20260228_120000_000000",
            log_session_dir=None,
        )

        assert (self.snapshot / "partial_work.txt").read_text() == "in_progress"

    # -- Test 9 --
    def test_interrupted_turn_still_saves_to_log_dir(self):
        """snapshot has content + workspace has content → log dir gets content."""
        _create_file(self.snapshot, "deliverable.pptx", "real_content")
        _create_file(self.workspace, "scaffolding.txt", "partial")

        orch = self._make_orchestrator()
        orch._save_partial_workspace_snapshots_for_interrupted_turn(
            agent_id="agent_a",
            backend=self.backend_mock,
            timestamp="20260228_120000_000000",
            log_session_dir=self.log_dir,
        )

        # snapshot preserved
        assert (self.snapshot / "deliverable.pptx").read_text() == "real_content"

        # log dir should still get content
        log_workspace = self.log_dir / "agent_a" / "20260228_120000_000000" / "workspace"
        assert log_workspace.exists()
        assert any(log_workspace.iterdir())


# ---------------------------------------------------------------------------
# TestSaveAgentSnapshotPassesPreserveFlag
# ---------------------------------------------------------------------------


class TestSaveAgentSnapshotPassesPreserveFlag:
    """Tests that _save_agent_snapshot wires preserve_existing_snapshot correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from massgen.orchestrator import Orchestrator

        self.orch = Orchestrator.__new__(Orchestrator)
        self.orch.agents = {}
        self.orch.coordination_tracker = MagicMock()

        # Mock filesystem_manager with async save_snapshot
        self.fm_mock = MagicMock()
        self.fm_mock.save_snapshot = AsyncMock()
        self.fm_mock.get_current_workspace.return_value = "/tmp/workspace"
        self.fm_mock.clear_workspace = MagicMock()
        self.fm_mock.restore_from_snapshot_storage = MagicMock()

        self.backend_mock = MagicMock()
        self.backend_mock.filesystem_manager = self.fm_mock

        self.agent_mock = MagicMock()
        self.agent_mock.backend = self.backend_mock

        self.orch.agents = {"agent_a": self.agent_mock}

    # -- Test 10 --
    @pytest.mark.asyncio
    async def test_answer_submission_does_not_preserve(self):
        """When answer_content is provided, preserve_existing_snapshot=False."""
        with (
            patch("massgen.orchestrator.get_log_session_dir", return_value=None),
            patch.object(self.orch, "_archive_agent_memories"),
        ):
            await self.orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content="My answer",
            )

        self.fm_mock.save_snapshot.assert_called_once()
        call_kwargs = self.fm_mock.save_snapshot.call_args
        assert call_kwargs.kwargs.get("preserve_existing_snapshot", call_kwargs[1].get("preserve_existing_snapshot")) is False

    # -- Test 11 --
    @pytest.mark.asyncio
    async def test_interrupted_save_preserves(self):
        """When answer_content is None and not final, preserve_existing_snapshot=True."""
        with (
            patch("massgen.orchestrator.get_log_session_dir", return_value=None),
            patch.object(self.orch, "_archive_agent_memories"),
        ):
            await self.orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content=None,
            )

        self.fm_mock.save_snapshot.assert_called_once()
        call_kwargs = self.fm_mock.save_snapshot.call_args
        assert call_kwargs.kwargs.get("preserve_existing_snapshot", call_kwargs[1].get("preserve_existing_snapshot")) is True

    # -- Test 12 --
    @pytest.mark.asyncio
    async def test_final_save_does_not_preserve(self):
        """When is_final=True, preserve_existing_snapshot=False."""
        with (
            patch("massgen.orchestrator.get_log_session_dir", return_value=None),
            patch.object(self.orch, "_archive_agent_memories"),
        ):
            await self.orch._save_agent_snapshot(
                agent_id="agent_a",
                is_final=True,
            )

        self.fm_mock.save_snapshot.assert_called_once()
        call_kwargs = self.fm_mock.save_snapshot.call_args
        assert call_kwargs.kwargs.get("preserve_existing_snapshot", call_kwargs[1].get("preserve_existing_snapshot")) is False


# ---------------------------------------------------------------------------
# TestFinalSnapshotFallsBackToSnapshotStorage
# ---------------------------------------------------------------------------


class TestFinalSnapshotFallsBackToSnapshotStorage:
    """Regression: final snapshot must use snapshot_storage when workspace only has metadata.

    After workspace clear, backend metadata dirs like .codex survive or get
    re-created. These should NOT count as "meaningful content" — otherwise the
    final snapshot copies a near-empty workspace instead of snapshot_storage
    which holds the real deliverables.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path):
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        self.snapshot = tmp_path / "snapshot_storage"
        self.snapshot.mkdir()
        self.log_dir = tmp_path / "logs"
        self.log_dir.mkdir()

        self.fm = FilesystemManager.__new__(FilesystemManager)
        self.fm.cwd = str(self.workspace)
        self.fm.snapshot_storage = self.snapshot
        self.fm.agent_id = "agent_a"
        self.fm.use_two_tier_workspace = False
        self.fm.is_shared_workspace = False

    # -- Test 13 --
    @pytest.mark.asyncio
    async def test_codex_metadata_only_falls_back_to_snapshot_storage(self):
        """Workspace with only .codex/.git/memory → final snapshot uses snapshot_storage."""
        # Workspace has only backend metadata (post-clear + codex re-init)
        (self.workspace / ".codex").mkdir()
        _create_file(self.workspace / ".codex", "config.toml", "[model]\nprovider='openai'")
        (self.workspace / ".git").mkdir()
        (self.workspace / "memory").mkdir()

        # Snapshot storage has the real deliverables
        _create_file(self.snapshot, "deliverable.mp3", "audio-bytes")
        (self.snapshot / "tasks").mkdir()
        _create_file(self.snapshot / "tasks", "changedoc.md", "# Changes")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=self.log_dir):
            await self.fm.save_snapshot(is_final=True)

        final_workspace = self.log_dir / "final" / "agent_a" / "workspace"
        assert final_workspace.exists()
        # Must have the real deliverable from snapshot_storage
        assert (final_workspace / "deliverable.mp3").exists()
        assert (final_workspace / "tasks" / "changedoc.md").exists()

    # -- Test 14 --
    @pytest.mark.asyncio
    async def test_massgen_metadata_only_falls_back_to_snapshot_storage(self):
        """Workspace with only .massgen/.git → final snapshot uses snapshot_storage."""
        (self.workspace / ".massgen").mkdir()
        (self.workspace / ".git").mkdir()

        _create_file(self.snapshot, "result.txt", "real content")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=self.log_dir):
            await self.fm.save_snapshot(is_final=True)

        final_workspace = self.log_dir / "final" / "agent_a" / "workspace"
        assert (final_workspace / "result.txt").exists()

    # -- Test 15 --
    @pytest.mark.asyncio
    async def test_real_content_in_workspace_uses_workspace(self):
        """Workspace with actual deliverables → final snapshot uses workspace, not snapshot_storage."""
        _create_file(self.workspace, "deliverable.mp3", "fresh-audio")
        (self.workspace / ".codex").mkdir()
        (self.workspace / ".git").mkdir()

        _create_file(self.snapshot, "old_deliverable.mp3", "stale-audio")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=self.log_dir):
            await self.fm.save_snapshot(is_final=True)

        final_workspace = self.log_dir / "final" / "agent_a" / "workspace"
        # Must use workspace (fresh), not snapshot_storage (stale)
        assert (final_workspace / "deliverable.mp3").read_text() == "fresh-audio"


# ---------------------------------------------------------------------------
# TestHasMeaningfulContent
# ---------------------------------------------------------------------------


class TestHasMeaningfulContent:
    """Direct unit tests for the consolidated has_meaningful_content helper."""

    def test_none_path_returns_false(self):
        from massgen.filesystem_manager import has_meaningful_content

        assert has_meaningful_content(None) is False

    def test_nonexistent_path_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        assert has_meaningful_content(tmp_path / "nope") is False

    def test_empty_directory_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        empty = tmp_path / "empty"
        empty.mkdir()
        assert has_meaningful_content(empty) is False

    def test_git_only_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / ".git").mkdir()
        assert has_meaningful_content(d) is False

    def test_codex_only_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / ".codex").mkdir()
        assert has_meaningful_content(d) is False

    def test_massgen_only_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / ".massgen").mkdir()
        assert has_meaningful_content(d) is False

    def test_memory_only_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / "memory").mkdir()
        assert has_meaningful_content(d) is False

    def test_all_metadata_dirs_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        for name in (".git", ".codex", ".massgen", "memory"):
            (d / name).mkdir()
        assert has_meaningful_content(d) is False

    def test_real_file_returns_true(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / "deliverable.txt").write_text("content")
        assert has_meaningful_content(d) is True

    def test_real_file_alongside_metadata_returns_true(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        (d / ".git").mkdir()
        (d / ".codex").mkdir()
        (d / "deliverable.txt").write_text("content")
        assert has_meaningful_content(d) is True

    def test_symlink_only_returns_false(self, tmp_path: Path):
        from massgen.filesystem_manager import has_meaningful_content

        d = tmp_path / "ws"
        d.mkdir()
        target = tmp_path / "target"
        target.write_text("data")
        (d / "link").symlink_to(target)
        assert has_meaningful_content(d) is False
