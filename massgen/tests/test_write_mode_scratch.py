"""
Tests for write_mode unified workspace with in-worktree scratch.

Covers:
- Scratch directory creation and git exclusion
- Branch lifecycle (one branch per agent, cleanup_round vs cleanup_session)
- move_scratch_to_workspace archive
- ChangeApplier skipping scratch files
- Shadow mode scratch support
- Config validator deprecation warnings
"""

import os
from pathlib import Path

from git import Repo

from massgen.filesystem_manager._change_applier import ChangeApplier
from massgen.filesystem_manager._isolation_context_manager import (
    SCRATCH_DIR_NAME,
    VERIFICATION_DIR_NAME,
    IsolationContextManager,
)


def init_test_repo(path: Path, with_commit: bool = True) -> Repo:
    """Helper to initialize a test git repo with GitPython."""
    repo = Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "email", "test@test.com")
        config.set_value("user", "name", "Test")
    if with_commit:
        (path / "file.txt").write_text("content")
        repo.index.add(["file.txt"])
        repo.index.commit("init")
    return repo


class TestScratchDirectory:
    """Tests for .massgen_scratch/ creation and git exclusion."""

    def test_worktree_creates_scratch_dir(self, tmp_path):
        """Verify .massgen_scratch/ is created inside the worktree."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-scratch",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")
        scratch = os.path.join(isolated, SCRATCH_DIR_NAME)

        assert os.path.isdir(scratch), ".massgen_scratch/ should be created in worktree"
        icm.cleanup_all()

    def test_scratch_is_git_excluded(self, tmp_path):
        """Verify files in .massgen_scratch/ are invisible to git status."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-exclude",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write a file in scratch
        scratch_file = os.path.join(isolated, SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("scratch content")

        # Check git status - scratch file should be invisible
        wt_repo = Repo(isolated)
        untracked = wt_repo.untracked_files
        assert "notes.md" not in str(untracked), "Scratch files should be git-excluded"
        assert SCRATCH_DIR_NAME not in str(untracked), "Scratch dir should be git-excluded"
        icm.cleanup_all()

    def test_diff_excludes_scratch(self, tmp_path):
        """Verify get_diff() only shows non-scratch file changes."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-diff",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write scratch file and tracked file
        scratch_file = os.path.join(isolated, SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("scratch content")
        tracked_file = os.path.join(isolated, "new_feature.py")
        with open(tracked_file, "w") as f:
            f.write("feature code")

        diff = icm.get_diff(str(repo_path))
        assert "new_feature.py" in diff, "Tracked file should appear in diff"
        assert "notes.md" not in diff, "Scratch file should NOT appear in diff"
        icm.cleanup_all()

    def test_get_scratch_path(self, tmp_path):
        """Verify get_scratch_path() returns the correct path."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-path",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        icm.initialize_context(str(repo_path), agent_id="agent1")
        scratch = icm.get_scratch_path(str(repo_path))

        assert scratch is not None
        assert scratch.endswith(SCRATCH_DIR_NAME)
        assert os.path.isdir(scratch)
        icm.cleanup_all()


class TestWorktreeMirrorsSourceState:
    """Tests for mirroring source working-tree state into new worktrees."""

    def test_worktree_mirrors_dirty_source_baseline(self, tmp_path):
        """Worktree should start from source's current dirty state, not clean HEAD."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        # Add a tracked file that we'll delete in dirty state
        repo = Repo(str(repo_path))
        (repo_path / "tracked_delete.txt").write_text("delete me")
        repo.index.add(["tracked_delete.txt"])
        repo.index.commit("add tracked file to delete")

        # Create dirty source state (modified + deleted + untracked)
        (repo_path / "file.txt").write_text("dirty modified")
        (repo_path / "tracked_delete.txt").unlink()
        (repo_path / "new_untracked.txt").write_text("new dirty file")
        assert repo.is_dirty(untracked_files=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-mirror-dirty-source",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Worktree should mirror source working-tree state
        assert (Path(isolated) / "file.txt").read_text() == "dirty modified"
        assert not (Path(isolated) / "tracked_delete.txt").exists()
        assert (Path(isolated) / "new_untracked.txt").read_text() == "new dirty file"

        # Baseline should be captured as a clean commit in isolated worktree
        wt_repo = Repo(isolated)
        assert not wt_repo.is_dirty(untracked_files=True)
        info = icm.get_context_info(str(repo_path))
        assert info is not None
        assert info.get("base_ref"), "base_ref should be captured for baseline-aware apply"

        # Original source remains dirty (we only mirror into isolated worktree)
        assert repo.is_dirty(untracked_files=True)
        icm.cleanup_all()

    def test_subdir_context_only_mirrors_subdir_dirty_state(self, tmp_path):
        """Subdir context should mirror dirty state only within that context prefix."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)
        subdir = repo_path / "inside" / "dir"
        subdir.mkdir(parents=True)
        (subdir / "sub.txt").write_text("sub-base")
        (repo_path / "root.txt").write_text("root-base")
        repo.index.add(["inside/dir/sub.txt", "root.txt"])
        repo.index.commit("add root and sub files")

        # Dirty changes both inside and outside context path
        (subdir / "sub.txt").write_text("sub-dirty")
        (repo_path / "root.txt").write_text("root-dirty")
        assert repo.is_dirty(untracked_files=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-subdir-mirror",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(subdir), agent_id="agent1")

        # Context file should mirror dirty state
        assert (Path(isolated) / "inside" / "dir" / "sub.txt").read_text() == "sub-dirty"
        # Out-of-scope file should remain at HEAD in worktree
        assert (Path(isolated) / "root.txt").read_text() == "root-base"
        icm.cleanup_all()


class TestMoveScatchToWorkspace:
    """Tests for scratch archive functionality."""

    def test_move_scratch_to_workspace(self, tmp_path):
        """Verify scratch is moved to .massgen_scratch/ in workspace (not .scratch_archive/)."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-archive",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write content in scratch
        scratch_file = os.path.join(isolated, SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("important notes")

        archive_dir = icm.move_scratch_to_workspace(str(repo_path))

        assert archive_dir is not None
        assert ".scratch_archive" not in archive_dir
        assert archive_dir == str(workspace / ".massgen_scratch")
        assert os.path.isdir(archive_dir)
        assert os.path.exists(os.path.join(archive_dir, "notes.md"))
        # Original scratch should no longer exist
        assert not os.path.exists(os.path.join(isolated, SCRATCH_DIR_NAME))
        icm.cleanup_all()


class TestScratchArchiveLabel:
    """Tests for archive_label in move_scratch_to_workspace."""

    def test_scratch_archive_uses_label(self, tmp_path):
        """Verify archive always goes to .massgen_scratch/ regardless of archive_label."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-label-archive",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write content in scratch
        scratch_file = os.path.join(isolated, SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("important notes")

        archive_dir = icm.move_scratch_to_workspace(str(repo_path), archive_label="agent1")

        assert archive_dir is not None
        assert archive_dir == str(workspace / ".massgen_scratch")
        assert os.path.isdir(archive_dir)
        assert os.path.exists(os.path.join(archive_dir, "notes.md"))
        icm.cleanup_all()

    def test_scratch_archive_falls_back_without_label(self, tmp_path):
        """Verify archive goes to .massgen_scratch/ even when no archive_label given."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-fallback-archive",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        scratch_file = os.path.join(isolated, SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("notes")

        archive_dir = icm.move_scratch_to_workspace(str(repo_path))

        assert archive_dir is not None
        assert archive_dir == str(workspace / ".massgen_scratch")
        assert ".scratch_archive" not in archive_dir
        icm.cleanup_all()


class TestBranchLifecycle:
    """Tests for one-branch-per-agent branch lifecycle."""

    def test_cleanup_round_keeps_branch(self, tmp_path):
        """Verify cleanup_round() removes worktree but keeps the branch."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-round",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))
        assert branch_name is not None

        # Cleanup round - worktree removed, branch kept
        icm.cleanup_round(str(repo_path))

        # Worktree should be removed
        assert not os.path.exists(isolated), "Worktree should be removed"
        # Branch should still exist
        branches = [b.name for b in repo.branches]
        assert branch_name in branches, f"Branch {branch_name} should be preserved"

    def test_cleanup_session_removes_branches(self, tmp_path):
        """Verify cleanup_session() removes worktrees AND all branches."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-session",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        icm.cleanup_session()

        # Branch should be removed
        branches = [b.name for b in repo.branches]
        assert branch_name not in branches, f"Branch {branch_name} should be deleted"

    def test_branch_names_are_short_random(self, tmp_path):
        """Verify default branch names are short: massgen/{random_hex}."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-random",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        assert branch_name is not None
        # Should use short massgen/{random} format (no session ID)
        assert branch_name.startswith("massgen/")
        parts = branch_name.split("/")
        assert len(parts) == 2, f"Expected massgen/{{hex}}, got {branch_name}"
        # Should NOT contain agent_id or round number
        assert "agent1" not in branch_name, "Branch name should not contain agent ID"
        assert "test-random" not in branch_name, "Branch name should not contain session ID"
        icm.cleanup_all()

    def test_branch_label_overrides_name(self, tmp_path):
        """Verify branch_label produces a readable prefixed branch name with random suffix."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-label",
            write_mode="worktree",
            workspace_path=str(workspace),
            branch_label="presenter",
        )
        icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        assert branch_name.startswith("presenter_"), f"Expected 'presenter_*', got {branch_name}"
        # Should have an 8-char hex suffix after the underscore
        suffix = branch_name.split("presenter_", 1)[1]
        assert len(suffix) == 8, f"Expected 8-char hex suffix, got '{suffix}'"
        int(suffix, 16)  # Validates it's valid hex
        icm.cleanup_all()

    def test_branch_label_uniqueness_across_sessions(self, tmp_path):
        """Two sessions with same branch_label produce different branch names."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace1 = tmp_path / "workspace1"
        workspace1.mkdir()
        workspace2 = tmp_path / "workspace2"
        workspace2.mkdir()

        icm1 = IsolationContextManager(
            session_id="session-1",
            write_mode="worktree",
            workspace_path=str(workspace1),
            branch_label="presenter",
        )
        icm1.initialize_context(str(repo_path), agent_id="agent1")
        branch1 = icm1.get_branch_name(str(repo_path))

        icm2 = IsolationContextManager(
            session_id="session-2",
            write_mode="worktree",
            workspace_path=str(workspace2),
            branch_label="presenter",
        )
        icm2.initialize_context(str(repo_path), agent_id="agent1")
        branch2 = icm2.get_branch_name(str(repo_path))

        assert branch1 != branch2, f"Branch names should differ, both got {branch1}"
        assert branch1.startswith("presenter_")
        assert branch2.startswith("presenter_")
        icm1.cleanup_all()
        icm2.cleanup_all()

    def test_stale_branch_does_not_block_new_session(self, tmp_path):
        """A leftover branch from a crashed session doesn't prevent a new session."""

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        # Simulate a stale branch left by a previous crashed session
        repo.create_head("presenter_deadbeef")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="new-session",
            write_mode="worktree",
            workspace_path=str(workspace),
            branch_label="presenter",
        )
        # Should succeed — new random suffix won't collide with stale branch
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        assert isolated is not None
        assert branch_name.startswith("presenter_")
        assert branch_name != "presenter_deadbeef"
        icm.cleanup_all()

    def test_branches_accumulate_across_rounds(self, tmp_path):
        """Verify old branches are kept when new rounds create new branches."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        workspace1 = tmp_path / "workspace1"
        workspace1.mkdir()
        workspace2 = tmp_path / "workspace2"
        workspace2.mkdir()

        # Round 1
        icm1 = IsolationContextManager(
            session_id="test-round1",
            write_mode="worktree",
            workspace_path=str(workspace1),
        )
        icm1.initialize_context(str(repo_path), agent_id="agent1")
        old_branch = icm1.get_branch_name(str(repo_path))
        icm1.cleanup_round(str(repo_path))

        # Verify old branch exists
        branches = [b.name for b in repo.branches]
        assert old_branch in branches

        # Round 2 — branches now accumulate (no previous_branch deletion)
        icm2 = IsolationContextManager(
            session_id="test-round2",
            write_mode="worktree",
            workspace_path=str(workspace2),
        )
        icm2.initialize_context(str(repo_path), agent_id="agent1")
        new_branch = icm2.get_branch_name(str(repo_path))

        # Both branches should exist (old is kept for cross-agent diffs)
        branches = [b.name for b in repo.branches]
        assert old_branch in branches, f"Old branch {old_branch} should be preserved"
        assert new_branch in branches, f"New branch {new_branch} should exist"
        assert old_branch != new_branch
        icm2.cleanup_all()


class TestChangeApplierSkipsScratch:
    """Tests for ChangeApplier skipping .massgen_scratch files."""

    def test_change_applier_skips_scratch(self, tmp_path):
        """Verify _apply_file_changes() skips .massgen_scratch files."""
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        # Create a normal file and a scratch file in source
        (source / "main.py").write_text("code")
        scratch_dir = source / ".massgen_scratch"
        scratch_dir.mkdir()
        (scratch_dir / "notes.md").write_text("scratch notes")

        applier = ChangeApplier()
        applied = applier._apply_file_changes(source, target, approved_files=None)

        assert "main.py" in applied, "Normal files should be applied"
        scratch_applied = [f for f in applied if ".massgen_scratch" in f]
        assert len(scratch_applied) == 0, "Scratch files should be skipped"


class TestShadowModeCreatesScatch:
    """Tests for shadow repo scratch support."""

    def test_shadow_mode_creates_scratch(self, tmp_path):
        """Verify shadow repos get .massgen_scratch/ too."""
        non_git_dir = tmp_path / "project"
        non_git_dir.mkdir()
        (non_git_dir / "file.txt").write_text("content")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-shadow",
            write_mode="isolated",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(non_git_dir), agent_id="agent1")
        scratch = os.path.join(isolated, SCRATCH_DIR_NAME)

        assert os.path.isdir(scratch), ".massgen_scratch/ should be created in shadow repo"
        icm.cleanup_all()


class TestWorkspaceScratchNoContextPaths:
    """Tests for workspace mode (no context_paths case)."""

    def test_workspace_scratch_creates_git_repo(self, tmp_path):
        """Verify setup_workspace_scratch() git-inits a non-git workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "notes.txt").write_text("some content")

        icm = IsolationContextManager(
            session_id="test-ws",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        scratch = icm.setup_workspace_scratch(str(workspace), agent_id="agent1")

        # Should be a git repo now
        assert (workspace / ".git").exists(), "Workspace should be git-initialized"
        # Scratch should exist
        assert os.path.isdir(scratch), ".massgen_scratch/ should be created"
        assert scratch.endswith(SCRATCH_DIR_NAME)
        icm.cleanup_session()

    def test_workspace_scratch_creates_branch(self, tmp_path):
        """Verify setup_workspace_scratch() creates a short branch."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-ws-branch",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")

        branch = icm.get_branch_name(str(workspace))
        assert branch is not None
        assert branch.startswith("massgen/")
        parts = branch.split("/")
        assert len(parts) == 2, f"Expected massgen/{{hex}}, got {branch}"
        assert "agent1" not in branch, "Branch name should not contain agent ID"

        # Verify the branch exists in the repo
        repo = Repo(str(workspace))
        assert branch in [b.name for b in repo.branches]
        icm.cleanup_session()

    def test_workspace_scratch_git_excluded(self, tmp_path):
        """Verify scratch files are invisible to git status in workspace mode."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-ws-exclude",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")

        # Write a file in scratch
        scratch_file = os.path.join(str(workspace), SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("scratch content")

        # Check git status - scratch file should be invisible
        repo = Repo(str(workspace))
        untracked = repo.untracked_files
        assert SCRATCH_DIR_NAME not in str(untracked), "Scratch dir should be git-excluded"
        icm.cleanup_session()

    def test_workspace_cleanup_round_keeps_branch(self, tmp_path):
        """Verify cleanup_round() switches back to default branch but keeps the workspace branch."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-ws-round",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")
        branch = icm.get_branch_name(str(workspace))
        assert branch is not None

        # Cleanup round
        icm.cleanup_round(str(workspace))

        # Branch should still exist
        repo = Repo(str(workspace))
        branches = [b.name for b in repo.branches]
        assert branch in branches, f"Branch {branch} should be preserved after cleanup_round"
        # Should be back on master/main
        assert repo.active_branch.name in ("main", "master")

    def test_workspace_cleanup_session_removes_branch(self, tmp_path):
        """Verify cleanup_session() deletes the workspace branch."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-ws-session",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")
        branch = icm.get_branch_name(str(workspace))

        icm.cleanup_session()

        # Branch should be deleted
        repo = Repo(str(workspace))
        branches = [b.name for b in repo.branches]
        assert branch not in branches, f"Branch {branch} should be deleted after cleanup_session"

    def test_workspace_branches_accumulate_across_rounds(self, tmp_path):
        """Verify workspace branches accumulate across rounds (not deleted mid-session)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Round 1
        icm1 = IsolationContextManager(
            session_id="test-ws-r1",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm1.setup_workspace_scratch(str(workspace), agent_id="agent1")
        old_branch = icm1.get_branch_name(str(workspace))
        icm1.cleanup_round(str(workspace))

        # Verify old branch exists
        repo = Repo(str(workspace))
        assert old_branch in [b.name for b in repo.branches]

        # Round 2 — branches now accumulate (no previous_branch deletion)
        icm2 = IsolationContextManager(
            session_id="test-ws-r2",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm2.setup_workspace_scratch(str(workspace), agent_id="agent1")
        new_branch = icm2.get_branch_name(str(workspace))

        # Both branches should exist
        repo = Repo(str(workspace))
        branches = [b.name for b in repo.branches]
        assert old_branch in branches, f"Old branch {old_branch} should be preserved"
        assert new_branch in branches, f"New branch {new_branch} should exist"
        icm2.cleanup_session()

    def test_workspace_move_scratch_to_archive(self, tmp_path):
        """Verify move_scratch_to_workspace is a no-op in workspace mode (scratch already at right place)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-ws-archive",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")

        # Write content in scratch
        scratch_file = os.path.join(str(workspace), SCRATCH_DIR_NAME, "notes.md")
        with open(scratch_file, "w") as f:
            f.write("important notes")

        archive_dir = icm.move_scratch_to_workspace(str(workspace))

        # In workspace mode scratch is already at {workspace}/.massgen_scratch/ — no move needed
        assert archive_dir is not None
        assert ".scratch_archive" not in archive_dir
        assert archive_dir == str(workspace / ".massgen_scratch")
        # File still accessible at same path
        assert os.path.exists(os.path.join(archive_dir, "notes.md"))
        icm.cleanup_session()

    def test_workspace_inside_parent_repo_gets_own_git(self, tmp_path):
        """Verify workspace inside a parent git repo gets its own .git/ (not branching the parent)."""
        # Simulate the real scenario: .massgen/workspaces/workspace_xxx inside a project repo
        project = tmp_path / "project"
        project.mkdir()
        init_test_repo(project)

        workspace = project / ".massgen" / "workspaces" / "workspace_abc"
        workspace.mkdir(parents=True)

        icm = IsolationContextManager(
            session_id="test-ws-nested",
            write_mode="auto",
            workspace_path=str(workspace),
        )
        icm.setup_workspace_scratch(str(workspace), agent_id="agent1")

        # Workspace should have its OWN .git/ (not use the parent's)
        assert (workspace / ".git").exists(), "Workspace should have its own .git/"
        branch = icm.get_branch_name(str(workspace))
        assert branch is not None

        # The branch should be on the WORKSPACE repo, not the parent
        ws_repo = Repo(str(workspace))
        assert branch in [b.name for b in ws_repo.branches]

        # The parent repo should NOT have the branch
        parent_repo = Repo(str(project))
        assert branch not in [b.name for b in parent_repo.branches], f"Branch {branch} should NOT exist on the parent project repo"
        icm.cleanup_session()


class TestWriteModeSuppressesTwoTier:
    """Tests that write_mode suppresses the old two-tier workspace."""

    def test_filesystem_manager_suppresses_two_tier_when_write_mode_set(self, tmp_path):
        """Verify use_two_tier_workspace is False on FM when write_mode is active."""
        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        fm = FilesystemManager(
            cwd=str(workspace),
            use_two_tier_workspace=True,
            write_mode="auto",
        )

        assert fm.use_two_tier_workspace is False, "use_two_tier_workspace should be suppressed when write_mode is active"

    def test_filesystem_manager_keeps_two_tier_without_write_mode(self, tmp_path):
        """Verify use_two_tier_workspace is preserved when write_mode is not set."""
        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        fm = FilesystemManager(
            cwd=str(workspace),
            use_two_tier_workspace=True,
            write_mode=None,
        )

        assert fm.use_two_tier_workspace is True

    def test_no_deliverable_scratch_dirs_with_write_mode(self, tmp_path):
        """Verify no deliverable/ or scratch/ dirs are created when write_mode is active."""
        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            use_two_tier_workspace=True,
            write_mode="auto",
        )
        # _setup_workspace is called during init
        assert not (workspace / "deliverable").exists(), "deliverable/ should not be created"
        assert not (workspace / "scratch").exists(), "scratch/ should not be created"


class TestConfigValidatorDeprecation:
    """Tests for use_two_tier_workspace deprecation warnings."""

    def test_config_validator_deprecation_warning_standalone(self):
        """Verify warning when use_two_tier_workspace is set without write_mode."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [{"name": "test", "type": "openai", "model": "gpt-4o-mini"}],
            "orchestrator": {
                "coordination": {
                    "use_two_tier_workspace": True,
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        # Check warnings for deprecation
        warning_texts = [w.message for w in result.warnings]
        has_deprecation = any("deprecated" in w.lower() for w in warning_texts)
        assert has_deprecation, f"Should have deprecation warning, got: {warning_texts}"

    def test_config_validator_deprecation_warning_with_write_mode(self):
        """Verify warning when use_two_tier_workspace is set WITH write_mode."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [{"name": "test", "type": "openai", "model": "gpt-4o-mini"}],
            "orchestrator": {
                "coordination": {
                    "use_two_tier_workspace": True,
                    "write_mode": "auto",
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        warning_texts = [w.message for w in result.warnings]
        has_ignored_warning = any("ignored" in w.lower() for w in warning_texts)
        assert has_ignored_warning, f"Should warn about being ignored, got: {warning_texts}"


class TestDockerMountsWriteMode:
    """Tests for Docker mount filtering when write_mode creates worktrees."""

    def test_docker_mounts_exclude_context_paths_when_write_mode(self, tmp_path):
        """When write_mode active, setup_orchestration_paths() passes empty context_paths
        and .git/ as extra_mount_paths to Docker."""
        from unittest.mock import MagicMock, patch

        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create a git repo to use as context path
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        fm = FilesystemManager(cwd=str(workspace), write_mode="auto")

        # Mock docker_manager and path_permission_manager
        fm.docker_manager = MagicMock()
        fm.docker_manager.create_container.return_value = None
        fm.agent_id = "agent1"
        fm.path_permission_manager = MagicMock()
        fm.path_permission_manager.get_context_paths.return_value = [
            {"path": str(repo_path), "permission": "read"},
        ]

        # Call the Docker container creation block directly by calling setup_orchestration_paths
        # We need to patch to avoid other side effects
        with patch.object(fm, "_setup_workspace", return_value=workspace):
            fm.setup_orchestration_paths(
                agent_id="agent1",
                skills_directory=None,
            )

        # Verify create_container was called with empty context_paths and .git/ extra_mount_paths
        call_kwargs = fm.docker_manager.create_container.call_args
        assert call_kwargs is not None, "create_container should have been called"
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        # Check positional or keyword args
        if "context_paths" in kwargs:
            assert kwargs["context_paths"] == [], "context_paths should be empty when write_mode active"
        if "extra_mount_paths" in kwargs:
            mount_paths = kwargs["extra_mount_paths"]
            assert len(mount_paths) == 1, f"Should have 1 .git/ mount, got {len(mount_paths)}"
            assert mount_paths[0][0] == str(repo_path / ".git"), "Should mount .git/ dir"

    def test_docker_mounts_git_dir_rw_for_worktrees(self, tmp_path):
        """.git/ dir should be mounted as rw, not ro."""
        from unittest.mock import MagicMock, patch

        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        fm = FilesystemManager(cwd=str(workspace), write_mode="worktree")
        fm.docker_manager = MagicMock()
        fm.docker_manager.create_container.return_value = None
        fm.agent_id = "agent1"
        fm.path_permission_manager = MagicMock()
        fm.path_permission_manager.get_context_paths.return_value = [
            {"path": str(repo_path), "permission": "read"},
        ]

        with patch.object(fm, "_setup_workspace", return_value=workspace):
            fm.setup_orchestration_paths(agent_id="agent1", skills_directory=None)

        call_kwargs = fm.docker_manager.create_container.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        if "extra_mount_paths" in kwargs:
            mount_paths = kwargs["extra_mount_paths"]
            assert mount_paths[0][2] == "rw", f"Expected rw mode, got {mount_paths[0][2]}"

    def test_non_git_context_paths_not_mounted(self, tmp_path):
        """Non-git context paths are preserved as regular context_paths (no .git/ mounts needed)."""
        from unittest.mock import MagicMock, patch

        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Non-git directory (no .git/)
        non_git_path = tmp_path / "plain_dir"
        non_git_path.mkdir()
        (non_git_path / "file.txt").write_text("content")

        fm = FilesystemManager(cwd=str(workspace), write_mode="isolated")
        fm.docker_manager = MagicMock()
        fm.docker_manager.create_container.return_value = None
        fm.agent_id = "agent1"
        fm.path_permission_manager = MagicMock()
        fm.path_permission_manager.get_context_paths.return_value = [
            {"path": str(non_git_path), "permission": "read"},
        ]

        with patch.object(fm, "_setup_workspace", return_value=workspace):
            fm.setup_orchestration_paths(agent_id="agent1", skills_directory=None)

        call_kwargs = fm.docker_manager.create_container.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        # Non-git context paths are preserved (not suppressed) so agents
        # can still read external artifacts like log/session directories.
        if "context_paths" in kwargs:
            assert kwargs["context_paths"] == [
                {"path": str(non_git_path), "permission": "read"},
            ], "Non-git context paths should be preserved"
        # extra_mount_paths should be empty (no .git/ to mount)
        if "extra_mount_paths" in kwargs:
            assert kwargs["extra_mount_paths"] == [], f"No .git/ mounts expected, got {kwargs['extra_mount_paths']}"


class TestSystemPromptWriteMode:
    """Tests for system prompt behavior when worktree_paths are set."""

    def test_system_prompt_hides_context_paths_with_worktrees(self):
        """WorkspaceStructureSection omits context paths when worktree_paths set."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=["/projects/myrepo"],
            worktree_paths={"/workspace/.worktree/ctx_0": "/projects/myrepo"},
        )
        content = section.build_content()

        assert "Context paths" not in content, "Context paths should be suppressed when worktree_paths set"
        assert "/projects/myrepo" not in content, "Original context path should not appear"
        assert "Project Workspace" in content, "Worktree section should be present"

    def test_system_prompt_shows_context_paths_without_worktrees(self):
        """WorkspaceStructureSection shows context paths when no worktree_paths."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=["/projects/myrepo"],
        )
        content = section.build_content()

        assert "Context paths" in content, "Context paths should be shown without worktree_paths"
        assert "/projects/myrepo" in content


class TestClaudeMdDiscoveryWorktrees:
    """Tests for CLAUDE.md discovery through worktree paths."""

    def test_claude_md_discovery_uses_worktree_paths(self, tmp_path):
        """ProjectInstructionsSection discovers CLAUDE.md from worktree path."""
        from massgen.system_prompt_sections import ProjectInstructionsSection

        # Create a worktree path with CLAUDE.md
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()
        (worktree_path / "CLAUDE.md").write_text("# Project instructions\nDo the thing.")

        section = ProjectInstructionsSection(
            context_paths=[{"path": str(worktree_path)}],
            workspace_root=str(tmp_path),
        )
        content = section.build_content()

        assert "Do the thing" in content, "Should discover CLAUDE.md from worktree path"

    def test_claude_md_not_found_in_original_when_worktree_used(self, tmp_path):
        """When worktree path is used, CLAUDE.md in original (unmounted) path is irrelevant."""
        from massgen.system_prompt_sections import ProjectInstructionsSection

        # Original context path has CLAUDE.md but worktree doesn't
        original_path = tmp_path / "original"
        original_path.mkdir()
        (original_path / "CLAUDE.md").write_text("# Original instructions")

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()
        # No CLAUDE.md in worktree

        # Discovery uses worktree path, not original
        section = ProjectInstructionsSection(
            context_paths=[{"path": str(worktree_path)}],
            workspace_root=str(tmp_path),
        )
        content = section.build_content()

        assert "Original instructions" not in content, "Should not find CLAUDE.md from original path"


class TestFilesystemOperationsSuppressesContextPaths:
    """Tests that FilesystemOperationsSection hides context paths when write_mode active."""

    def test_filesystem_ops_hides_context_paths_when_write_mode(self):
        """FilesystemOperationsSection should not show Target/Context Path when write_mode active."""
        from massgen.system_prompt_sections import FilesystemOperationsSection

        section = FilesystemOperationsSection(
            main_workspace="/workspace",
            context_paths=[],  # Empty because _build_filesystem_sections clears them
        )
        content = section.build_content()

        assert "Target Path" not in content, "Target Path should not appear when context_paths empty"
        assert "Context Path" not in content, "Context Path should not appear when context_paths empty"

    def test_filesystem_ops_shows_context_paths_without_write_mode(self):
        """FilesystemOperationsSection shows context paths normally when write_mode not active."""
        from massgen.system_prompt_sections import FilesystemOperationsSection

        section = FilesystemOperationsSection(
            main_workspace="/workspace",
            context_paths=[{"path": "/projects/myrepo", "permission": "read"}],
        )
        content = section.build_content()

        assert "Context Path" in content, "Context Path should appear when write_mode not active"
        assert "/projects/myrepo" in content


class TestAutoCommitBeforeCleanup:
    """Tests for auto-commit of worktree changes before cleanup_round()."""

    def test_auto_commit_before_cleanup_round(self, tmp_path):
        """Verify cleanup_round() auto-commits changes so branch has agent's work."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-autocommit",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        # Make changes in the worktree (simulating agent work)
        new_file = os.path.join(isolated, "agent_work.py")
        with open(new_file, "w") as f:
            f.write("print('agent work')")

        # Cleanup round - should auto-commit before removing worktree
        icm.cleanup_round(str(repo_path))

        # Branch should have the commit with agent's work
        commit = repo.commit(branch_name)
        assert "Auto-commit" in commit.message
        # The file should be in the commit tree
        file_names = [item.name for item in commit.tree.traverse()]
        assert "agent_work.py" in file_names, "Agent's file should be committed on the branch"

    def test_auto_commit_no_changes(self, tmp_path):
        """Verify no commit is made when worktree has no changes."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-noop-commit",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        icm.initialize_context(str(repo_path), agent_id="agent1")
        branch_name = icm.get_branch_name(str(repo_path))

        # Don't make any changes - cleanup should not create a commit
        # Get commit count before cleanup
        initial_commit_count = len(list(repo.iter_commits(branch_name)))

        icm.cleanup_round(str(repo_path))

        # Branch should have the same number of commits (no auto-commit)
        commit_count = len(list(repo.iter_commits(branch_name)))
        assert commit_count == initial_commit_count, "No commit should be made when there are no changes"


class TestBaseCommitWorktree:
    """Tests for base_commit parameter in IsolationContextManager."""

    def test_base_commit_creates_worktree_from_branch(self, tmp_path):
        """Verify passing base_commit starts the worktree from that branch's content."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        # Create a feature branch with some content
        default_branch = repo.active_branch.name
        feature_branch = "massgen/test/feature-branch"
        repo.git.checkout("-b", feature_branch)
        feature_file = repo_path / "feature.py"
        feature_file.write_text("feature code")
        repo.index.add(["feature.py"])
        repo.index.commit("Add feature")
        repo.git.checkout(default_branch)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create ICM with base_commit pointing to the feature branch
        icm = IsolationContextManager(
            session_id="test-base-commit",
            write_mode="worktree",
            workspace_path=str(workspace),
            base_commit=feature_branch,
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # The worktree should contain the feature file from the base branch
        assert os.path.exists(os.path.join(isolated, "feature.py")), "Worktree should contain files from the base_commit branch"
        with open(os.path.join(isolated, "feature.py")) as f:
            assert f.read() == "feature code"

        icm.cleanup_all()


class TestWorkspaceStructureBranchInfo:
    """Tests for branch info in WorkspaceStructureSection."""

    def test_workspace_structure_shows_branch_name(self):
        """Verify WorkspaceStructureSection includes agent's own branch name."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
            branch_name="massgen/abc12345",
        )
        content = section.build_content()

        assert "massgen/abc12345" in content
        assert "Your work is on branch" in content
        assert "auto-committed" in content
        assert "Manual commits are optional" in content

    def test_workspace_structure_shows_other_branches_with_labels(self):
        """Verify WorkspaceStructureSection lists other agents' branches with anonymous labels."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
            other_branches={"agent1": "massgen/def456", "agent2": "massgen/ghi789"},
        )
        content = section.build_content()

        assert "agent1" in content
        assert "massgen/def456" in content
        assert "agent2" in content
        assert "massgen/ghi789" in content
        assert "Other agents' branches" in content
        assert "git diff" in content
        assert "git merge" in content

    def test_workspace_structure_no_branch_info_when_none(self):
        """Verify no branch section appears when branch info is not provided."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
        )
        content = section.build_content()

        assert "Your work is on branch" not in content
        assert "Other agents' branches" not in content

    def test_workspace_structure_mentions_scratch_space(self):
        """Verify WorkspaceStructureSection mentions scratch space."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
        )
        content = section.build_content()

        assert ".massgen_scratch/" in content
        assert "git-excluded" in content


class TestRestartContextBranchInfo:
    """Tests for branch info in format_restart_context()."""

    def test_restart_context_includes_branch_info(self):
        """Verify format_restart_context includes branch names when branch_info provided."""
        from massgen.message_templates import MessageTemplates

        mt = MessageTemplates()
        branch_info = {
            "own_branch": "massgen/abc123",
            "other_branches": {"agent1": "massgen/def456", "agent2": "massgen/ghi789"},
        }
        result = mt.format_restart_context(
            reason="Insufficient quality",
            instructions="Improve the solution",
            branch_info=branch_info,
        )

        assert "massgen/abc123" in result
        assert "Your previous work is on branch" in result
        assert "git merge massgen/abc123" in result
        assert "agent1" in result
        assert "massgen/def456" in result
        assert "agent2" in result
        assert "massgen/ghi789" in result
        assert "Other agents' branches" in result

    def test_restart_context_no_branch_info(self):
        """Verify format_restart_context works without branch_info."""
        from massgen.message_templates import MessageTemplates

        mt = MessageTemplates()
        result = mt.format_restart_context(
            reason="Insufficient quality",
            instructions="Improve the solution",
        )

        assert "Your previous work is on branch" not in result
        assert "Other agents' branches" not in result
        assert "PREVIOUS ATTEMPT FEEDBACK" in result


class TestBranchDiffSummary:
    """Tests for get_branch_diff_summary() and generate_branch_summaries()."""

    def test_get_branch_diff_summary_with_changes(self, tmp_path):
        """Verify diff summary returns compact stats and file list."""
        from massgen.utils.git_utils import get_branch_diff_summary

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)
        default_branch = repo.active_branch.name

        # Create a feature branch with changes
        repo.git.checkout("-b", "massgen/test123")
        (repo_path / "new_file.py").write_text("print('hello')")
        (repo_path / "file.txt").write_text("modified content")
        repo.index.add(["new_file.py", "file.txt"])
        repo.index.commit("feature changes")
        repo.git.checkout(default_branch)

        summary = get_branch_diff_summary(str(repo_path), default_branch, "massgen/test123")
        assert summary != ""
        assert "file" in summary
        assert "+" in summary
        assert "new_file.py" in summary

    def test_get_branch_diff_summary_no_changes(self, tmp_path):
        """Verify diff summary is empty when branches are identical."""
        from massgen.utils.git_utils import get_branch_diff_summary

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)
        default_branch = repo.active_branch.name

        # Create a branch at the same commit
        repo.git.branch("massgen/same")

        summary = get_branch_diff_summary(str(repo_path), default_branch, "massgen/same")
        assert summary == ""

    def test_get_branch_diff_summary_invalid_branch(self, tmp_path):
        """Verify diff summary returns empty string for invalid branch."""
        from massgen.utils.git_utils import get_branch_diff_summary

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)
        default_branch = repo.active_branch.name

        summary = get_branch_diff_summary(str(repo_path), default_branch, "massgen/nonexistent")
        assert summary == ""

    def test_generate_branch_summaries_multiple_branches(self, tmp_path):
        """Verify generate_branch_summaries() returns summaries for all branches."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)
        default_branch = repo.active_branch.name

        # Create 3 branches with different changes
        for i, name in enumerate(["massgen/aaa", "massgen/bbb", "massgen/ccc"]):
            repo.git.checkout("-b", name)
            (repo_path / f"feature_{i}.py").write_text(f"code_{i}")
            repo.index.add([f"feature_{i}.py"])
            repo.index.commit(f"feature {i}")
            repo.git.checkout(default_branch)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-summaries",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        # Initialize a context so ICM has a repo path reference
        icm.initialize_context(str(repo_path), agent_id="agent1")

        branches = {
            "agent1": "massgen/aaa",
            "agent2": "massgen/bbb",
            "agent3": "massgen/ccc",
        }
        summaries = icm.generate_branch_summaries(branches, base_ref=default_branch)

        assert len(summaries) == 3, f"Expected 3 summaries, got {len(summaries)}"
        for label in ["agent1", "agent2", "agent3"]:
            assert label in summaries
            assert "file" in summaries[label]
        icm.cleanup_all()

    def test_generate_branch_summaries_empty_branches(self, tmp_path):
        """Verify generate_branch_summaries() handles empty branch dict."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-empty",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        summaries = icm.generate_branch_summaries({})
        assert summaries == {}


class TestCleanupOrphanedBranches:
    """Tests for cleanup_orphaned_branches() static method."""

    def test_cleanup_orphaned_branches_deletes_massgen_branches(self, tmp_path):
        """Verify orphaned massgen/* branches are deleted."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        # Create some massgen/* branches (simulating crashed session leftovers)
        for name in ["massgen/abc123", "massgen/def456", "massgen/ghi789"]:
            repo.git.branch(name)

        branches_before = [b.name for b in repo.branches]
        assert "massgen/abc123" in branches_before

        deleted = IsolationContextManager.cleanup_orphaned_branches(str(repo_path))

        assert deleted == 3
        branches_after = [b.name for b in repo.branches]
        for name in ["massgen/abc123", "massgen/def456", "massgen/ghi789"]:
            assert name not in branches_after

    def test_cleanup_orphaned_branches_no_massgen_branches(self, tmp_path):
        """Verify no-op when there are no massgen/* branches."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        repo = init_test_repo(repo_path)

        # Create a non-massgen branch
        repo.git.branch("feature/unrelated")

        deleted = IsolationContextManager.cleanup_orphaned_branches(str(repo_path))

        assert deleted == 0
        assert "feature/unrelated" in [b.name for b in repo.branches]

    def test_cleanup_orphaned_branches_non_git_path(self, tmp_path):
        """Verify graceful handling of non-git paths."""
        non_git = tmp_path / "not_a_repo"
        non_git.mkdir()

        deleted = IsolationContextManager.cleanup_orphaned_branches(str(non_git))
        assert deleted == 0


class TestDiffSummariesInSystemPrompt:
    """Tests for diff summaries rendering in WorkspaceStructureSection."""

    def test_workspace_structure_shows_diff_summaries(self):
        """Verify diff summaries are rendered with branch info."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
            other_branches={"agent1": "massgen/abc123", "agent2": "massgen/def456"},
            branch_diff_summaries={
                "agent1": "3 files (+45/-12)\n  M src/auth.py | A src/oauth.py | M tests/test_auth.py",
                "agent2": "1 file (+22/-5)\n  M src/auth.py",
            },
        )
        content = section.build_content()

        assert "Other agents' code changes" in content
        assert "3 files (+45/-12)" in content
        assert "M src/auth.py" in content
        assert "1 file (+22/-5)" in content
        assert "git diff" in content
        assert "git merge" in content

    def test_workspace_structure_falls_back_without_summaries(self):
        """Verify branches are shown without summaries when none available."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={"/workspace/.worktree/ctx_1": "/projects/repo"},
            other_branches={"agent1": "massgen/abc123"},
            branch_diff_summaries=None,
        )
        content = section.build_content()

        assert "Other agents' branches" in content
        assert "agent1" in content
        assert "massgen/abc123" in content

    def test_workspace_structure_directive_instructions(self):
        """Verify the improved directive instructions appear in the prompt."""
        from massgen.system_prompt_sections import WorkspaceStructureSection

        wt_path = "/workspace/.worktree/ctx_1"
        section = WorkspaceStructureSection(
            workspace_path="/workspace",
            context_paths=[],
            worktree_paths={wt_path: "/projects/repo"},
        )
        content = section.build_content()

        assert "All code changes must be made here" in content
        assert f"cd {wt_path}" in content
        assert "Project Workspace" in content


class TestVerificationDirectory:
    """Tests for .massgen_scratch/verification/ auto-creation."""

    def test_verification_dir_created_in_worktree(self, tmp_path):
        """Verify verification/ subdir is created inside scratch."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-verification",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")
        verification = os.path.join(isolated, SCRATCH_DIR_NAME, VERIFICATION_DIR_NAME)

        assert os.path.isdir(verification), "verification/ should be created in scratch"
        icm.cleanup_all()

    def test_verification_dir_is_git_excluded(self, tmp_path):
        """Files in verification/ should be invisible to git status."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-verify-exclude",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write a file in verification subdir
        verification_dir = os.path.join(
            isolated,
            SCRATCH_DIR_NAME,
            VERIFICATION_DIR_NAME,
        )
        verification_file = os.path.join(verification_dir, "test_results.txt")
        with open(verification_file, "w") as f:
            f.write("PASS: all tests passed")

        wt_repo = Repo(isolated)
        untracked = wt_repo.untracked_files
        assert "test_results.txt" not in str(untracked)
        assert SCRATCH_DIR_NAME not in str(untracked)
        icm.cleanup_all()

    def test_verification_dir_preserved_in_archive(self, tmp_path):
        """Verify verification/ contents are preserved when scratch is archived."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        init_test_repo(repo_path)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-verify-archive",
            write_mode="worktree",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(repo_path), agent_id="agent1")

        # Write a verification artifact
        verification_dir = os.path.join(
            isolated,
            SCRATCH_DIR_NAME,
            VERIFICATION_DIR_NAME,
        )
        verification_file = os.path.join(verification_dir, "screenshot.png")
        with open(verification_file, "w") as f:
            f.write("fake png data")

        archive_dir = icm.move_scratch_to_workspace(
            str(repo_path),
            archive_label="agent1",
        )
        assert archive_dir is not None
        assert archive_dir == str(workspace / ".massgen_scratch")
        archived_verification = os.path.join(
            archive_dir,
            VERIFICATION_DIR_NAME,
            "screenshot.png",
        )
        assert os.path.exists(archived_verification), "verification/ should be preserved in archive"
        icm.cleanup_all()

    def test_verification_dir_created_in_shadow_mode(self, tmp_path):
        """Verify verification/ subdir is created in shadow mode scratch."""
        non_git_dir = tmp_path / "project"
        non_git_dir.mkdir()
        (non_git_dir / "file.txt").write_text("content")

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        icm = IsolationContextManager(
            session_id="test-shadow-verify",
            write_mode="isolated",
            workspace_path=str(workspace),
        )
        isolated = icm.initialize_context(str(non_git_dir), agent_id="agent1")
        verification = os.path.join(isolated, SCRATCH_DIR_NAME, VERIFICATION_DIR_NAME)

        assert os.path.isdir(verification), "verification/ should be created in shadow mode"
        icm.cleanup_all()
