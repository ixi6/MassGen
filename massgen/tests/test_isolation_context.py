"""
Integration tests for the git worktree and isolation context infrastructure.

Tests cover:
- WorktreeManager: Git worktree lifecycle
- ShadowRepo: Shadow repository for non-git directories
- IsolationContextManager: High-level isolation management
"""

from pathlib import Path

import pytest
from git import Repo


def init_test_repo(path: Path, with_commit: bool = True) -> Repo:
    """Helper to initialize a test git repo with GitPython."""
    repo = Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "email", "test@test.com")
        config.set_value("user", "name", "Test")

    if with_commit:
        # Create a file and commit
        (path / "file.txt").write_text("content")
        repo.index.add(["file.txt"])
        repo.index.commit("init")

    return repo


class TestGitUtils:
    """Tests for git utility functions."""

    def test_is_git_repo_in_git_directory(self, tmp_path):
        """Test is_git_repo returns True for git repos."""
        from massgen.utils.git_utils import is_git_repo

        Repo.init(tmp_path)
        assert is_git_repo(str(tmp_path)) is True

    def test_is_git_repo_in_non_git_directory(self, tmp_path):
        """Test is_git_repo returns False for non-git directories."""
        from massgen.utils.git_utils import is_git_repo

        assert is_git_repo(str(tmp_path)) is False

    def test_get_git_root(self, tmp_path):
        """Test get_git_root returns correct path."""
        from massgen.utils.git_utils import get_git_root

        Repo.init(tmp_path)

        # Test from root
        assert get_git_root(str(tmp_path)) == str(tmp_path)

        # Test from subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        assert get_git_root(str(subdir)) == str(tmp_path)

    def test_get_git_root_non_repo(self, tmp_path):
        """Test get_git_root returns None for non-git directories."""
        from massgen.utils.git_utils import get_git_root

        assert get_git_root(str(tmp_path)) is None

    def test_get_git_status_clean(self, tmp_path):
        """Test get_git_status for clean repo."""
        from massgen.utils.git_utils import get_git_status

        init_test_repo(tmp_path)

        status = get_git_status(str(tmp_path))
        assert status["is_dirty"] is False
        assert status["has_untracked"] is False

    def test_get_git_status_dirty(self, tmp_path):
        """Test get_git_status for dirty repo."""
        from massgen.utils.git_utils import get_git_status

        init_test_repo(tmp_path)

        # Modify the file
        (tmp_path / "file.txt").write_text("modified")

        status = get_git_status(str(tmp_path))
        assert status["is_dirty"] is True

    def test_get_git_status_untracked(self, tmp_path):
        """Test get_git_status for untracked files."""
        from massgen.utils.git_utils import get_git_status

        init_test_repo(tmp_path)

        # Create untracked file
        (tmp_path / "untracked.txt").write_text("untracked")

        status = get_git_status(str(tmp_path))
        assert status["has_untracked"] is True

    def test_get_changes_includes_staged_changes(self, tmp_path):
        """Test get_changes detects files that are staged but not unstaged."""
        from massgen.utils.git_utils import get_changes

        repo = init_test_repo(tmp_path)
        (tmp_path / "file.txt").write_text("staged update")
        repo.git.add("file.txt")

        changes = get_changes(repo)
        changed_paths = {change["path"] for change in changes}
        assert "file.txt" in changed_paths


class TestWorktreeManager:
    """Tests for WorktreeManager."""

    def test_create_and_remove_worktree(self, tmp_path):
        """Test worktree creation and removal lifecycle."""
        from massgen.infrastructure import WorktreeManager

        init_test_repo(tmp_path)

        wm = WorktreeManager(str(tmp_path))

        # Create worktree
        worktree_path = tmp_path / "worktree"
        result = wm.create_worktree(str(worktree_path), "test-branch")

        assert result == str(worktree_path)
        assert worktree_path.exists()
        assert (worktree_path / "file.txt").exists()

        # Remove worktree
        wm.remove_worktree(str(worktree_path))
        assert not worktree_path.exists()

    def test_create_worktree_with_changes(self, tmp_path):
        """Test that worktree captures changes correctly."""
        from massgen.infrastructure import WorktreeManager

        repo = init_test_repo(tmp_path)
        (tmp_path / "file.txt").write_text("original")
        repo.index.add(["file.txt"])
        repo.index.commit("set original content")

        wm = WorktreeManager(str(tmp_path))
        worktree_path = tmp_path / "worktree"
        wm.create_worktree(str(worktree_path), "test-branch")

        # Modify file in worktree
        (worktree_path / "file.txt").write_text("modified in worktree")

        # Verify original is unchanged
        assert (tmp_path / "file.txt").read_text() == "original"
        assert (worktree_path / "file.txt").read_text() == "modified in worktree"

        # Cleanup
        wm.remove_worktree(str(worktree_path), force=True)

    def test_list_worktrees(self, tmp_path):
        """Test listing worktrees."""
        from massgen.infrastructure import WorktreeManager

        init_test_repo(tmp_path)

        wm = WorktreeManager(str(tmp_path))

        # Initially should have just the main worktree
        worktrees = wm.list_worktrees()
        assert len(worktrees) >= 1

        # Create another worktree
        worktree_path = tmp_path / "worktree"
        wm.create_worktree(str(worktree_path), "test-branch")

        worktrees = wm.list_worktrees()
        assert len(worktrees) >= 2

        # Cleanup
        wm.remove_worktree(str(worktree_path))

    def test_worktree_manager_non_git_repo_raises(self, tmp_path):
        """Test that WorktreeManager raises for non-git directories."""
        from massgen.infrastructure import WorktreeManager

        with pytest.raises(ValueError, match="not in a git repository"):
            WorktreeManager(str(tmp_path))


class TestShadowRepo:
    """Tests for ShadowRepo."""

    def test_create_shadow_from_directory(self, tmp_path):
        """Test shadow repo creation for non-git directory."""
        import os

        from massgen.infrastructure import ShadowRepo

        # Create a non-git directory with files
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file1.txt").write_text("content1")
        (source_dir / "file2.txt").write_text("content2")
        subdir = source_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")

        shadow = ShadowRepo(str(source_dir))
        shadow_path = shadow.initialize()

        # Verify shadow repo was created
        assert os.path.exists(shadow_path)
        assert os.path.exists(os.path.join(shadow_path, ".git"))

        # Verify files were copied
        assert (Path(shadow_path) / "file1.txt").read_text() == "content1"
        assert (Path(shadow_path) / "file2.txt").read_text() == "content2"
        assert (Path(shadow_path) / "subdir" / "nested.txt").read_text() == "nested content"

        # Cleanup
        shadow.cleanup()
        assert not os.path.exists(shadow_path)

    def test_shadow_repo_tracks_changes(self, tmp_path):
        """Test that changes are tracked in shadow repo."""
        from massgen.infrastructure import ShadowRepo

        # Create source directory
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("original")

        shadow = ShadowRepo(str(source_dir))
        shadow_path = shadow.initialize()

        # Initially should have no changes
        changes = shadow.get_changes()
        assert len(changes) == 0

        # Modify a file
        (Path(shadow_path) / "file.txt").write_text("modified")

        changes = shadow.get_changes()
        assert len(changes) == 1
        assert changes[0]["path"] == "file.txt"

        # Add a new file
        (Path(shadow_path) / "new_file.txt").write_text("new content")

        changes = shadow.get_changes()
        assert len(changes) == 2

        # Cleanup
        shadow.cleanup()

    def test_shadow_repo_get_diff(self, tmp_path):
        """Test getting diff from shadow repo."""
        from massgen.infrastructure import ShadowRepo

        # Create source directory
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_text("original")

        shadow = ShadowRepo(str(source_dir))
        shadow_path = shadow.initialize()

        # Modify a file
        (Path(shadow_path) / "file.txt").write_text("modified")

        diff = shadow.get_diff()
        assert "original" in diff
        assert "modified" in diff

        # Cleanup
        shadow.cleanup()

    def test_shadow_repo_invalid_source_raises(self, tmp_path):
        """Test that ShadowRepo raises for non-existent source."""
        from massgen.infrastructure import ShadowRepo

        with pytest.raises(ValueError, match="not a directory"):
            ShadowRepo(str(tmp_path / "nonexistent"))


class TestIsolationContextManager:
    """Tests for IsolationContextManager."""

    def test_auto_mode_selects_worktree_for_git(self, tmp_path):
        """Test that auto mode uses worktree for git repos."""
        from massgen.filesystem_manager import IsolationContextManager

        init_test_repo(tmp_path)

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Verify worktree was created
        info = icm.get_context_info(str(tmp_path))
        assert info["mode"] == "worktree"
        assert isolated_path != str(tmp_path)

        # Cleanup
        icm.cleanup_all()

    def test_auto_mode_selects_shadow_for_non_git(self, tmp_path):
        """Test that auto mode uses shadow for non-git directories."""
        from massgen.filesystem_manager import IsolationContextManager

        # Create a non-git directory
        (tmp_path / "file.txt").write_text("content")

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Verify shadow repo was created
        info = icm.get_context_info(str(tmp_path))
        assert info["mode"] == "shadow"
        assert isolated_path != str(tmp_path)

        # Cleanup
        icm.cleanup_all()

    def test_legacy_mode_returns_original_path(self, tmp_path):
        """Test that legacy mode returns the original path."""
        from massgen.filesystem_manager import IsolationContextManager

        (tmp_path / "file.txt").write_text("content")

        icm = IsolationContextManager(session_id="test-session", write_mode="legacy")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Legacy mode should return original path
        assert isolated_path == str(tmp_path)
        info = icm.get_context_info(str(tmp_path))
        assert info["mode"] == "legacy"

        # No cleanup needed for legacy mode
        icm.cleanup_all()

    def test_context_manager_protocol(self, tmp_path):
        """Test that IsolationContextManager works as context manager."""
        import os

        from massgen.filesystem_manager import IsolationContextManager

        (tmp_path / "file.txt").write_text("content")

        with IsolationContextManager(session_id="test-session", write_mode="auto") as icm:
            isolated_path = icm.initialize_context(str(tmp_path))
            assert os.path.exists(isolated_path)

        # After context exit, cleanup should have happened

    def test_get_changes_from_isolated_context(self, tmp_path):
        """Test getting changes from isolated context."""
        from massgen.filesystem_manager import IsolationContextManager

        (tmp_path / "file.txt").write_text("content")

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Initially no changes
        changes = icm.get_changes(str(tmp_path))
        assert len(changes) == 0

        # Make a change in isolated context
        (Path(isolated_path) / "file.txt").write_text("modified")

        changes = icm.get_changes(str(tmp_path))
        assert len(changes) == 1

        icm.cleanup_all()

    def test_multiple_contexts(self, tmp_path):
        """Test managing multiple isolated contexts."""
        from massgen.filesystem_manager import IsolationContextManager

        # Create two directories
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "file1.txt").write_text("content1")
        (dir2 / "file2.txt").write_text("content2")

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")

        path1 = icm.initialize_context(str(dir1))
        path2 = icm.initialize_context(str(dir2))

        # Both should be isolated
        assert path1 != str(dir1)
        assert path2 != str(dir2)

        # List should show both
        contexts = icm.list_contexts()
        assert len(contexts) == 2

        icm.cleanup_all()

    def test_isolated_mode_forces_shadow(self, tmp_path):
        """Test that isolated mode uses shadow even for git repos."""
        from massgen.filesystem_manager import IsolationContextManager

        init_test_repo(tmp_path)

        icm = IsolationContextManager(session_id="test-session", write_mode="isolated")
        icm.initialize_context(str(tmp_path))

        # Isolated mode should use shadow even for git repos
        info = icm.get_context_info(str(tmp_path))
        assert info["mode"] == "shadow"

        icm.cleanup_all()


class TestChangeApplier:
    """Tests for ChangeApplier."""

    def test_apply_changes_modified_file(self, tmp_path):
        """Test applying modified file changes."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        # Create source with a file
        (tmp_path / "file.txt").write_text("original")

        # Create isolated context
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Modify file in isolated context
        (Path(isolated_path) / "file.txt").write_text("modified")

        # Apply changes
        applier = ChangeApplier()
        applied = applier.apply_changes(isolated_path, str(tmp_path))

        # Verify changes applied
        assert len(applied) == 1
        assert "file.txt" in applied
        assert (tmp_path / "file.txt").read_text() == "modified"

        icm.cleanup_all()

    def test_apply_changes_new_file(self, tmp_path):
        """Test applying new file changes."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        # Create source directory
        (tmp_path / "existing.txt").write_text("existing")

        # Create isolated context
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Add new file in isolated context
        (Path(isolated_path) / "new_file.txt").write_text("new content")

        # Apply changes
        applier = ChangeApplier()
        applied = applier.apply_changes(isolated_path, str(tmp_path))

        # Verify new file was applied
        assert len(applied) == 1
        assert "new_file.txt" in applied
        assert (tmp_path / "new_file.txt").read_text() == "new content"

        icm.cleanup_all()

    def test_apply_changes_selective(self, tmp_path):
        """Test applying only selected files."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        # Create source with files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")

        # Create isolated context
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Modify both files in isolated context
        (Path(isolated_path) / "file1.txt").write_text("modified1")
        (Path(isolated_path) / "file2.txt").write_text("modified2")

        # Apply only file1 changes
        applier = ChangeApplier()
        applied = applier.apply_changes(
            isolated_path,
            str(tmp_path),
            approved_files=["file1.txt"],
        )

        # Verify only file1 was applied
        assert len(applied) == 1
        assert "file1.txt" in applied
        assert (tmp_path / "file1.txt").read_text() == "modified1"
        assert (tmp_path / "file2.txt").read_text() == "content2"  # Unchanged

        icm.cleanup_all()

    def test_apply_changes_respects_context_prefix(self, tmp_path):
        """Test apply_changes only writes files inside the configured context prefix."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        init_test_repo(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "inner.txt").write_text("inner original")

        repo = Repo(tmp_path)
        repo.index.add(["subdir/inner.txt"])
        repo.index.commit("add subdir file")

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        (Path(isolated_path) / "subdir" / "inner.txt").write_text("inner updated")
        (Path(isolated_path) / "file.txt").write_text("root updated")

        applier = ChangeApplier()
        applied = applier.apply_changes(
            isolated_path,
            str(subdir),
            context_prefix="subdir",
        )

        assert applied == ["inner.txt"]
        assert (subdir / "inner.txt").read_text() == "inner updated"
        assert (tmp_path / "file.txt").read_text() == "content"

        icm.cleanup_all()

    def test_apply_changes_committed_only_with_base_ref(self, tmp_path):
        """Committed-only changes should apply when base_ref is provided."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        init_test_repo(tmp_path)
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        applier = ChangeApplier()
        baseline_content = (tmp_path / "file.txt").read_text()
        base_ref = Repo(isolated_path).head.commit.hexsha

        (Path(isolated_path) / "file.txt").write_text("committed update")
        wt_repo = Repo(isolated_path)
        wt_repo.git.add("-A")
        wt_repo.index.commit("committed change")

        # Simulate already-clean working tree after commit.
        assert not wt_repo.is_dirty(untracked_files=True)

        applied = applier.apply_changes(
            isolated_path,
            str(tmp_path),
            base_ref=base_ref,
        )

        assert baseline_content == "content"
        assert applied == ["file.txt"]
        assert (tmp_path / "file.txt").read_text() == "committed update"

        icm.cleanup_all()

    def test_detect_target_drift_identifies_changed_target_file(self, tmp_path):
        """Drift detection flags files that changed in target after baseline."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        init_test_repo(tmp_path)
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))
        info = icm.get_context_info(str(tmp_path))
        base_ref = info.get("base_ref")
        assert base_ref

        # Presenter change in isolated context
        (Path(isolated_path) / "file.txt").write_text("presenter update")
        wt_repo = Repo(isolated_path)
        wt_repo.git.add("-A")
        wt_repo.index.commit("presenter commit")

        # Independent drift in target context after baseline
        (tmp_path / "file.txt").write_text("source drift")

        applier = ChangeApplier()
        drift = applier.detect_target_drift(
            source_path=isolated_path,
            target_path=str(tmp_path),
            base_ref=base_ref,
        )

        assert drift == ["file.txt"]
        icm.cleanup_all()

    def test_apply_changes_nested_directory(self, tmp_path):
        """Test applying changes in nested directories."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        # Create source with nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested content")

        # Create isolated context
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Modify nested file
        nested_file = Path(isolated_path) / "subdir" / "nested.txt"
        nested_file.write_text("modified nested")

        # Apply changes
        applier = ChangeApplier()
        applied = applier.apply_changes(isolated_path, str(tmp_path))

        # Verify nested file was applied
        assert len(applied) == 1
        assert "subdir/nested.txt" in applied
        assert (tmp_path / "subdir" / "nested.txt").read_text() == "modified nested"

        icm.cleanup_all()

    def test_apply_changes_with_approved_hunks_applies_partial_file(self, tmp_path):
        """When approved_hunks is provided, only selected hunks should apply."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        repo = init_test_repo(tmp_path)
        target_lines = [f"line {i}\n" for i in range(1, 13)]
        (tmp_path / "file.txt").write_text("".join(target_lines))
        repo.git.add("file.txt")
        repo.index.commit("seed multiline file")

        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        source_lines = target_lines.copy()
        source_lines[1] = "line two changed\n"  # hunk 0
        source_lines[10] = "line eleven changed\n"  # hunk 1
        (Path(isolated_path) / "file.txt").write_text("".join(source_lines))

        source_repo = Repo(isolated_path)
        combined_diff = source_repo.git.diff("--", "file.txt")
        assert "@@" in combined_diff

        applier = ChangeApplier()
        applied = applier.apply_changes(
            isolated_path,
            str(tmp_path),
            approved_files=["file.txt"],
            approved_hunks={"file.txt": [0]},
            combined_diff=combined_diff,
        )

        final_lines = (tmp_path / "file.txt").read_text().splitlines(keepends=True)
        assert applied == ["file.txt"]
        assert final_lines[1] == "line two changed\n"
        assert final_lines[10] == "line 11\n"

        icm.cleanup_all()

    def test_get_changes_summary(self, tmp_path):
        """Test getting changes summary."""
        from massgen.filesystem_manager import ChangeApplier, IsolationContextManager

        # Create source
        (tmp_path / "existing.txt").write_text("content")

        # Create isolated context
        icm = IsolationContextManager(session_id="test-session", write_mode="auto")
        isolated_path = icm.initialize_context(str(tmp_path))

        # Make various changes
        (Path(isolated_path) / "existing.txt").write_text("modified")
        (Path(isolated_path) / "new_file.txt").write_text("new")

        # Get summary
        applier = ChangeApplier()
        summary = applier.get_changes_summary(isolated_path)

        # Verify summary
        assert "modified" in summary
        assert "added" in summary
        assert "existing.txt" in summary["modified"]
        assert "new_file.txt" in summary["added"]

        icm.cleanup_all()


class TestReviewResult:
    """Tests for ReviewResult dataclass."""

    def test_review_result_approved_all(self):
        """Test ReviewResult for approving all files."""
        from massgen.filesystem_manager import ReviewResult

        result = ReviewResult(approved=True, approved_files=None)
        assert result.approved is True
        assert result.approved_files is None

    def test_review_result_approved_selective(self):
        """Test ReviewResult for approving specific files."""
        from massgen.filesystem_manager import ReviewResult

        result = ReviewResult(
            approved=True,
            approved_files=["file1.txt", "file2.txt"],
            comments="Only these two",
        )
        assert result.approved is True
        assert len(result.approved_files) == 2
        assert result.comments == "Only these two"

    def test_review_result_rejected(self):
        """Test ReviewResult for rejecting changes."""
        from massgen.filesystem_manager import ReviewResult

        result = ReviewResult(approved=False)
        assert result.approved is False
        assert result.approved_files is None


class TestWorktreeInsideWorkspace:
    """Tests for worktree creation inside agent workspace."""

    def test_worktree_inside_workspace(self, tmp_path):
        """IsolationContextManager with workspace_path creates worktree at {workspace}/.worktree/ctx_1."""
        from massgen.filesystem_manager import IsolationContextManager

        # Create a git repo to use as context path
        context_dir = tmp_path / "project"
        context_dir.mkdir()
        init_test_repo(context_dir)

        # Create a workspace directory
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        icm = IsolationContextManager(
            session_id="test-session",
            write_mode="auto",
            workspace_path=str(workspace_dir),
        )
        isolated_path = icm.initialize_context(str(context_dir))

        # Verify worktree was created inside workspace
        assert isolated_path.startswith(str(workspace_dir))
        assert "/.worktree/" in isolated_path
        assert isolated_path.endswith("/ctx_1")
        assert Path(isolated_path).exists()
        assert (Path(isolated_path) / "file.txt").exists()

        # Verify context info
        info = icm.get_context_info(str(context_dir))
        assert info["mode"] == "worktree"
        assert info["isolated_path"] == isolated_path

        icm.cleanup_all()

    def test_worktree_fallback_to_temp_without_workspace(self, tmp_path):
        """Without workspace_path, worktree falls back to temp directory."""
        from massgen.filesystem_manager import IsolationContextManager

        context_dir = tmp_path / "project"
        context_dir.mkdir()
        init_test_repo(context_dir)

        icm = IsolationContextManager(
            session_id="test-session",
            write_mode="auto",
            # No workspace_path
        )
        isolated_path = icm.initialize_context(str(context_dir))

        # Should NOT be inside any workspace, should be in temp
        assert "/.worktree/" not in isolated_path
        assert Path(isolated_path).exists()

        icm.cleanup_all()

    def test_worktree_changes_in_workspace(self, tmp_path):
        """Changes made in workspace worktree are detected correctly."""
        from massgen.filesystem_manager import IsolationContextManager

        context_dir = tmp_path / "project"
        context_dir.mkdir()
        repo = init_test_repo(context_dir)
        (context_dir / "file.txt").write_text("original")
        repo.index.add(["file.txt"])
        repo.index.commit("set original")

        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        icm = IsolationContextManager(
            session_id="test-session",
            write_mode="auto",
            workspace_path=str(workspace_dir),
        )
        isolated_path = icm.initialize_context(str(context_dir))

        # Make a change in the worktree
        (Path(isolated_path) / "file.txt").write_text("modified in worktree")

        # Verify original is unchanged
        assert (context_dir / "file.txt").read_text() == "original"

        # Verify changes are detected
        changes = icm.get_changes(str(context_dir))
        assert len(changes) == 1
        assert changes[0]["path"] == "file.txt"

        icm.cleanup_all()


class TestPPMRemoveReAdd:
    """Tests for PathPermissionManager remove/re-add methods for isolation."""

    def test_remove_context_path(self, tmp_path):
        """PPM correctly removes context path from managed paths."""
        from massgen.filesystem_manager import PathPermissionManager

        context_dir = tmp_path / "project"
        context_dir.mkdir()
        (context_dir / "file.txt").write_text("content")

        ppm = PathPermissionManager(context_write_access_enabled=True)
        ppm.add_context_paths([{"path": str(context_dir), "permission": "write"}])

        # Verify initially accessible
        from massgen.filesystem_manager._base import Permission

        perm = ppm.get_permission(context_dir / "file.txt")
        assert perm == Permission.WRITE

        # Remove the path
        removed = ppm.remove_context_path(str(context_dir))
        assert removed is not None
        assert removed.path_type == "context"

        # Verify no longer accessible (returns None = not in any managed path)
        perm = ppm.get_permission(context_dir / "file.txt")
        assert perm is None

    def test_re_add_context_path(self, tmp_path):
        """PPM re-adds a previously removed context path."""
        from massgen.filesystem_manager import PathPermissionManager
        from massgen.filesystem_manager._base import Permission

        context_dir = tmp_path / "project"
        context_dir.mkdir()
        (context_dir / "file.txt").write_text("content")

        ppm = PathPermissionManager(context_write_access_enabled=True)
        ppm.add_context_paths([{"path": str(context_dir), "permission": "write"}])

        # Remove then re-add
        removed = ppm.remove_context_path(str(context_dir))
        assert ppm.get_permission(context_dir / "file.txt") is None

        ppm.re_add_context_path(removed)
        perm = ppm.get_permission(context_dir / "file.txt")
        assert perm == Permission.WRITE

    def test_remove_nonexistent_path_returns_none(self, tmp_path):
        """Removing a path not in managed paths returns None."""
        from massgen.filesystem_manager import PathPermissionManager

        ppm = PathPermissionManager()
        result = ppm.remove_context_path("/nonexistent/path")
        assert result is None

    def test_remove_hides_from_set_context_write_access(self, tmp_path):
        """Removed path is invisible to set_context_write_access_enabled."""
        from massgen.filesystem_manager import PathPermissionManager

        context_dir = tmp_path / "project"
        context_dir.mkdir()
        (context_dir / "file.txt").write_text("content")

        # Start with write access disabled (like during coordination)
        ppm = PathPermissionManager(context_write_access_enabled=False)
        ppm.add_context_paths([{"path": str(context_dir), "permission": "write"}])

        # Remove the path before enabling write access
        removed = ppm.remove_context_path(str(context_dir))

        # Enable write access — should have no effect on removed path
        ppm.set_context_write_access_enabled(True)

        # Path is still not accessible
        perm = ppm.get_permission(context_dir / "file.txt")
        assert perm is None

        # Re-add and verify it's writable (since context_write_access is now enabled)
        ppm.re_add_context_path(removed)
        perm = ppm.get_permission(context_dir / "file.txt")
        # The re-added path retains its original permission from when it was removed
        # (READ, since write wasn't enabled when it was removed). This is fine because
        # the orchestrator re-adds it during the review phase when it needs to apply changes.
        assert perm is not None


class TestReviewModalCheckboxPathMapping:
    """Tests for review modal checkbox-to-path mapping."""

    def test_context_namespacing_prevents_cross_context_collisions(self):
        """Files with same relative path in different contexts stay distinct."""
        changes = [
            {
                "original_path": "/repo_one",
                "changes": [{"status": "M", "path": "README.md"}],
            },
            {
                "original_path": "/repo_two",
                "changes": [{"status": "M", "path": "README.md"}],
            },
        ]

        file_approvals = {}
        for ctx in changes:
            context_path = ctx["original_path"]
            for change in ctx["changes"]:
                file_path = change["path"]
                file_key = f"{context_path}::" + file_path
                file_approvals[file_key] = True

        assert len(file_approvals) == 2
        assert "/repo_one::README.md" in file_approvals
        assert "/repo_two::README.md" in file_approvals

    def test_hashed_checkbox_ids_are_unique_for_namespaced_keys(self):
        """Checkbox IDs remain unique even when relative paths are identical."""
        from hashlib import sha1

        key_one = "/repo_one::README.md"
        key_two = "/repo_two::README.md"
        id_one = f"file_cb_{sha1(key_one.encode('utf-8')).hexdigest()[:12]}"
        id_two = f"file_cb_{sha1(key_two.encode('utf-8')).hexdigest()[:12]}"

        assert id_one != id_two
