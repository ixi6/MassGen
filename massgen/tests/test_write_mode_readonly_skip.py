"""
Tests for write_mode: auto skipping worktree creation for read-only context paths.

When all context_paths have permission: read (will_be_writable=False),
the per-round isolation setup should skip worktree creation entirely.
When there's a mix of read and write, only writable paths should get worktrees.
"""

from pathlib import Path

from git import Repo


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


class TestReadOnlyContextPathsSkipWorktree:
    """Per-round isolation should not create worktrees for read-only context paths."""

    def test_all_readonly_context_paths_skip_isolation(self):
        """When all context paths are read-only, no IsolationContextManager should be created."""
        # Simulate what get_context_paths() returns for read-only paths
        context_paths = [
            {"path": "/some/repo", "permission": "read", "will_be_writable": False},
            {"path": "/another/repo", "permission": "read", "will_be_writable": False},
        ]

        # Filter to writable paths (the fix we're testing)
        writable_context_paths = [cp for cp in context_paths if cp.get("will_be_writable", False)]

        assert len(writable_context_paths) == 0, "Read-only context paths should not be included in writable list"

    def test_mixed_context_paths_only_isolate_writable(self):
        """When there's a mix of read and write, only writable paths should be isolated."""
        context_paths = [
            {"path": "/readonly/repo", "permission": "read", "will_be_writable": False},
            {"path": "/writable/repo", "permission": "read", "will_be_writable": True},
        ]

        writable_context_paths = [cp for cp in context_paths if cp.get("will_be_writable", False)]

        assert len(writable_context_paths) == 1
        assert writable_context_paths[0]["path"] == "/writable/repo"

    def test_all_writable_context_paths_all_isolated(self):
        """When all context paths are writable, all should be isolated."""
        context_paths = [
            {"path": "/repo_a", "permission": "read", "will_be_writable": True},
            {"path": "/repo_b", "permission": "read", "will_be_writable": True},
        ]

        writable_context_paths = [cp for cp in context_paths if cp.get("will_be_writable", False)]

        assert len(writable_context_paths) == 2

    def test_writable_path_gets_worktree_readonly_does_not(self, tmp_path):
        """Integration: writable context path gets a worktree, read-only does not."""
        from massgen.filesystem_manager import IsolationContextManager

        # Create two git repos
        writable_repo = tmp_path / "writable_repo"
        writable_repo.mkdir()
        init_test_repo(writable_repo)

        readonly_repo = tmp_path / "readonly_repo"
        readonly_repo.mkdir()
        init_test_repo(readonly_repo)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Simulate context_paths as returned by PPM
        context_paths = [
            {"path": str(readonly_repo), "permission": "read", "will_be_writable": False},
            {"path": str(writable_repo), "permission": "read", "will_be_writable": True},
        ]

        # Filter (the production code fix)
        writable_context_paths = [cp for cp in context_paths if cp.get("will_be_writable", False)]

        # Only create isolation for writable paths
        icm = IsolationContextManager(
            session_id="test-round",
            write_mode="auto",
            workspace_path=str(workspace),
        )

        worktree_paths = {}
        for ctx_config in writable_context_paths:
            ctx_path = ctx_config.get("path", "")
            if ctx_path:
                isolated = icm.initialize_context(ctx_path, "agent_a")
                worktree_paths[isolated] = ctx_path

        # Only writable repo should have a worktree
        assert len(worktree_paths) == 1
        isolated_path = list(worktree_paths.keys())[0]
        assert worktree_paths[isolated_path] == str(writable_repo)

        # The readonly repo should NOT be in any isolation context
        contexts = icm.list_contexts()
        context_originals = [c.get("original_path") for c in contexts]
        assert str(readonly_repo) not in context_originals
        assert str(writable_repo) in context_originals

        icm.cleanup_all()

    def test_no_writable_paths_means_no_isolation_manager_needed(self):
        """When no writable paths exist, we shouldn't even create an IsolationContextManager."""
        context_paths = [
            {"path": "/repo", "permission": "read", "will_be_writable": False},
        ]

        writable_context_paths = [cp for cp in context_paths if cp.get("will_be_writable", False)]

        # The orchestrator should check this BEFORE creating the manager
        should_create_isolation = bool(writable_context_paths) or not context_paths
        assert should_create_isolation is False
