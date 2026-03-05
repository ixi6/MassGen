"""Tests for two-tier workspace (scratch/deliverable) functionality."""

import json
import subprocess

import pytest

from massgen import logger_config
from massgen.filesystem_manager._filesystem_manager import FilesystemManager


class TestTwoTierWorkspaceSetup:
    """Tests for workspace directory structure creation."""

    def test_workspace_creates_tier_directories_when_enabled(self, tmp_path):
        """Verify scratch/ and deliverable/ are created when use_two_tier_workspace=True."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        scratch_dir = workspace / "scratch"
        deliverable_dir = workspace / "deliverable"

        assert scratch_dir.exists(), "scratch/ directory should be created"
        assert deliverable_dir.exists(), "deliverable/ directory should be created"
        assert scratch_dir.is_dir(), "scratch/ should be a directory"
        assert deliverable_dir.is_dir(), "deliverable/ should be a directory"

    def test_workspace_does_not_create_tier_directories_when_disabled(self, tmp_path):
        """Verify no tier directories when use_two_tier_workspace=False (default)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=False,
        )

        scratch_dir = workspace / "scratch"
        deliverable_dir = workspace / "deliverable"

        assert not scratch_dir.exists(), "scratch/ should not be created when disabled"
        assert not deliverable_dir.exists(), "deliverable/ should not be created when disabled"

    def test_workspace_default_is_single_tier(self, tmp_path):
        """Verify default behavior is single-tier (no scratch/deliverable)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        # Default value should be False
        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
        )

        scratch_dir = workspace / "scratch"
        deliverable_dir = workspace / "deliverable"

        assert not scratch_dir.exists(), "scratch/ should not exist by default"
        assert not deliverable_dir.exists(), "deliverable/ should not exist by default"


class TestGitVersioning:
    """Tests for git versioning functionality with two-tier workspace."""

    def test_git_init_with_two_tier_workspace(self, tmp_path):
        """Verify git repo is initialized when two-tier workspace is enabled."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        git_dir = workspace / ".git"
        assert git_dir.exists(), ".git/ directory should be created"
        assert git_dir.is_dir(), ".git/ should be a directory"

    def test_gitignore_created_from_constants(self, tmp_path):
        """Verify .gitignore is created with patterns from PATTERNS_TO_IGNORE_FOR_TRACKING."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        gitignore = workspace / ".gitignore"
        assert gitignore.exists(), ".gitignore should be created"

        content = gitignore.read_text()
        # Check some patterns from PATTERNS_TO_IGNORE_FOR_TRACKING
        assert "node_modules" in content, ".gitignore should include node_modules"
        assert "__pycache__" in content, ".gitignore should include __pycache__"
        assert ".DS_Store" in content, ".gitignore should include .DS_Store"

    def test_initial_commit_created(self, tmp_path):
        """Verify initial commit is created after git init."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        # Check git log has at least one commit
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "git log should succeed"
        assert "[INIT]" in result.stdout, "Initial commit should have [INIT] prefix"

    def test_git_not_initialized_when_disabled(self, tmp_path):
        """Verify git is NOT initialized when two-tier workspace is disabled."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=False,
        )

        git_dir = workspace / ".git"
        assert not git_dir.exists(), ".git/ should not exist when two-tier is disabled"


class TestGitCommitOnSnapshot:
    """Tests for automatic git commits during snapshot operations."""

    @pytest.mark.asyncio
    async def test_git_commit_triggered_on_snapshot(self, tmp_path):
        """Verify git commit is triggered when save_snapshot is called."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        # Set up orchestration paths (needed for snapshots)
        manager.setup_orchestration_paths(
            agent_id="test_agent",
            snapshot_storage=str(snapshot_storage),
        )

        # Create a file to commit
        test_file = workspace / "scratch" / "test.txt"
        test_file.write_text("test content")

        # Save snapshot
        await manager.save_snapshot()

        # Check git log shows the snapshot commit
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        assert "[SNAPSHOT]" in result.stdout, "Snapshot commit should have [SNAPSHOT] prefix"

    @pytest.mark.asyncio
    async def test_no_commit_when_no_changes(self, tmp_path):
        """Verify no commit is made when there are no changes."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        manager.setup_orchestration_paths(
            agent_id="test_agent",
            snapshot_storage=str(snapshot_storage),
        )

        # Get commit count before snapshot
        result_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        count_before = int(result_before.stdout.strip())

        # Save snapshot without making any changes
        await manager.save_snapshot()

        # Get commit count after snapshot
        result_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        count_after = int(result_after.stdout.strip())

        assert count_after == count_before, "No new commit should be made when no changes"


class TestSnapshotWithTwoTier:
    """Tests for snapshot functionality with two-tier workspace."""

    @pytest.mark.asyncio
    async def test_snapshot_captures_both_tiers(self, tmp_path):
        """Verify snapshots include both scratch/ and deliverable/."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        manager.setup_orchestration_paths(
            agent_id="test_agent",
            snapshot_storage=str(snapshot_storage),
        )

        # Create files in both tiers
        scratch_file = workspace / "scratch" / "work.txt"
        scratch_file.write_text("working on it")

        deliverable_file = workspace / "deliverable" / "final.txt"
        deliverable_file.write_text("final output")

        # Save snapshot
        await manager.save_snapshot()

        # Check snapshot contains both
        agent_snapshot = snapshot_storage / "test_agent"
        assert (agent_snapshot / "scratch" / "work.txt").exists(), "scratch/ should be in snapshot"
        assert (agent_snapshot / "deliverable" / "final.txt").exists(), "deliverable/ should be in snapshot"


class TestTempWorkspaceSharing:
    """Tests for temp workspace sharing between agents."""

    @pytest.mark.asyncio
    async def test_temp_workspace_has_both_tiers(self, tmp_path):
        """Verify voters see both scratch/ and deliverable/ from other agents."""
        workspace_a = tmp_path / "workspace_a"
        workspace_a.mkdir()
        workspace_b = tmp_path / "workspace_b"
        workspace_b.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()
        temp_workspaces = tmp_path / "temp_workspaces"
        temp_workspaces.mkdir()

        # Create agent A's manager
        manager_a = FilesystemManager(
            cwd=str(workspace_a),
            agent_temporary_workspace_parent=str(temp_workspaces),
            use_two_tier_workspace=True,
        )
        manager_a.setup_orchestration_paths(
            agent_id="agent_a",
            snapshot_storage=str(snapshot_storage),
            agent_temporary_workspace=str(temp_workspaces),
        )

        # Create files in agent A's workspace
        (workspace_a / "scratch" / "notes.txt").write_text("my notes")
        (workspace_a / "deliverable" / "answer.txt").write_text("my answer")

        # Save agent A's snapshot
        await manager_a.save_snapshot()

        # Create agent B's manager
        manager_b = FilesystemManager(
            cwd=str(workspace_b),
            agent_temporary_workspace_parent=str(temp_workspaces),
            use_two_tier_workspace=True,
        )
        manager_b.setup_orchestration_paths(
            agent_id="agent_b",
            snapshot_storage=str(snapshot_storage),
            agent_temporary_workspace=str(temp_workspaces),
        )

        # Copy snapshots to agent B's temp workspace
        all_snapshots = {"agent_a": snapshot_storage / "agent_a"}
        agent_mapping = {"agent_a": "agent1"}

        await manager_b.copy_snapshots_to_temp_workspace(all_snapshots, agent_mapping)

        # Verify agent B can see agent A's both tiers
        temp_workspace_b = temp_workspaces / "agent_b"
        assert (temp_workspace_b / "agent1" / "scratch" / "notes.txt").exists(), "Should see agent1's scratch/"
        assert (temp_workspace_b / "agent1" / "deliverable" / "answer.txt").exists(), "Should see agent1's deliverable/"

    @pytest.mark.asyncio
    async def test_temp_workspace_rewrites_media_ledger_paths(self, tmp_path):
        """Copied media ledger paths should be normalized to temp workspace references."""
        workspace_b = tmp_path / "workspace_b"
        workspace_b.mkdir()
        temp_workspaces = tmp_path / "temp_workspaces"
        temp_workspaces.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()

        source_snapshot = snapshot_storage / "agent_a"
        verification_dir = source_snapshot / ".massgen_scratch" / "verification"
        verification_dir.mkdir(parents=True)

        (verification_dir / "site_initial.png").write_text("x", encoding="utf-8")
        (verification_dir / "site_interacted.png").write_text("y", encoding="utf-8")

        original_workspace = tmp_path / "workspace_source"
        original_initial = (original_workspace / ".massgen_scratch" / "verification" / "site_initial.png").resolve()
        original_interacted = (original_workspace / ".massgen_scratch" / "verification" / "site_interacted.png").resolve()

        ledger_payload = {
            "version": 1,
            "updated_at": "2026-03-05T00:00:00+00:00",
            "entries": [
                {
                    "timestamp": "2026-03-05T00:00:00+00:00",
                    "tool": "read_media",
                    "tool_arguments": {
                        "prompt": "Evaluate images",
                        "inputs": json.dumps(
                            [
                                {
                                    "files": {
                                        "initial": str(original_initial),
                                        "interacted": str(original_interacted),
                                    },
                                },
                            ],
                        ),
                    },
                    "file_mappings": [
                        f"input[0].initial -> {original_initial}",
                        f"input[0].interacted -> {original_interacted}",
                    ],
                },
            ],
        }
        (verification_dir / "media_call_ledger.json").write_text(
            json.dumps(ledger_payload, indent=2),
            encoding="utf-8",
        )

        manager_b = FilesystemManager(
            cwd=str(workspace_b),
            agent_temporary_workspace_parent=str(temp_workspaces),
            use_two_tier_workspace=True,
        )
        manager_b.setup_orchestration_paths(
            agent_id="agent_b",
            snapshot_storage=str(snapshot_storage),
            agent_temporary_workspace=str(temp_workspaces),
        )

        all_snapshots = {"agent_a": source_snapshot}
        agent_mapping = {"agent_a": "agent1"}
        await manager_b.copy_snapshots_to_temp_workspace(all_snapshots, agent_mapping)

        copied_ledger_path = temp_workspaces / "agent_b" / "agent1" / ".massgen_scratch" / "verification" / "media_call_ledger.json"
        copied_payload = json.loads(copied_ledger_path.read_text(encoding="utf-8"))
        copied_entry = copied_payload["entries"][0]

        expected_initial = (temp_workspaces / "agent_b" / "agent1" / ".massgen_scratch" / "verification" / "site_initial.png").resolve()
        expected_interacted = (temp_workspaces / "agent_b" / "agent1" / ".massgen_scratch" / "verification" / "site_interacted.png").resolve()

        rewritten_inputs = json.loads(copied_entry["tool_arguments"]["inputs"])
        files = rewritten_inputs[0]["files"]
        assert files["initial"] == str(expected_initial)
        assert files["interacted"] == str(expected_interacted)
        assert copied_entry["file_mappings"][0] == f"input[0].initial -> {expected_initial}"
        assert copied_entry["file_mappings"][1] == f"input[0].interacted -> {expected_interacted}"


class TestGitIsolation:
    """Tests for git isolation from parent repositories."""

    def test_git_operations_isolated_from_parent_repo(self, tmp_path):
        """Verify git operations in workspace don't affect parent git repos.

        This test creates a workspace inside a parent git repo (simulating
        .massgen/workspaces/ inside a project repo) and verifies that:
        1. Git commands only affect the workspace's .git, not the parent
        2. Pre-commit hooks from parent are not triggered
        3. GIT_DIR and GIT_WORK_TREE are properly set
        """
        # Create a "parent" git repo (simulating the user's project repo)
        parent_repo = tmp_path / "parent_repo"
        parent_repo.mkdir()

        subprocess.run(["git", "init"], cwd=parent_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.name", "parent"],
            cwd=parent_repo,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "parent@test.com"],
            cwd=parent_repo,
            capture_output=True,
            check=True,
        )

        # Create a file and commit in parent
        parent_file = parent_repo / "parent_file.txt"
        parent_file.write_text("parent content")
        subprocess.run(["git", "add", "-A"], cwd=parent_repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Parent initial commit"],
            cwd=parent_repo,
            capture_output=True,
            check=True,
        )

        # Get parent's initial commit count
        parent_log_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=parent_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        parent_commit_count_before = int(parent_log_before.stdout.strip())

        # Create workspace INSIDE the parent repo (like .massgen/workspaces/)
        workspace = parent_repo / ".massgen" / "workspaces" / "test_workspace"
        workspace.mkdir(parents=True)
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        # Initialize FilesystemManager with two-tier workspace
        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        # Verify workspace has its own .git
        assert (workspace / ".git").exists(), "Workspace should have its own .git"

        # Create and commit a file in the workspace
        workspace_file = workspace / "scratch" / "workspace_file.txt"
        workspace_file.write_text("workspace content")

        # Manually trigger a git commit in workspace (simulating snapshot)
        manager._git_commit_if_changed(workspace, "[TEST] Test commit")

        # Verify workspace has the commit
        workspace_log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "[TEST]" in workspace_log.stdout, "Workspace should have the test commit"

        # CRITICAL: Verify parent repo was NOT affected
        parent_log_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=parent_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        parent_commit_count_after = int(parent_log_after.stdout.strip())

        assert parent_commit_count_after == parent_commit_count_before, f"Parent repo should not have new commits! " f"Before: {parent_commit_count_before}, After: {parent_commit_count_after}"

        # Verify parent's git log doesn't contain workspace commits
        parent_log_content = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=parent_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "[TEST]" not in parent_log_content.stdout, "Parent should not have workspace commits"
        assert "[INIT]" not in parent_log_content.stdout, "Parent should not have workspace init commits"

    def test_git_uses_no_verify_flag(self, tmp_path):
        """Verify git commits use --no-verify to skip hooks."""
        # Create a workspace with a pre-commit hook that would fail
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        # Install a pre-commit hook that always fails
        hooks_dir = workspace / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        pre_commit_hook = hooks_dir / "pre-commit"
        pre_commit_hook.write_text("#!/bin/bash\nexit 1\n")
        pre_commit_hook.chmod(0o755)

        # Create a file to commit
        test_file = workspace / "scratch" / "test.txt"
        test_file.write_text("test content")

        # This should succeed because --no-verify skips the hook
        result = manager._git_commit_if_changed(workspace, "[TEST] Should skip hook")

        assert result is True, "Commit should succeed despite failing hook (--no-verify)"

        # Verify commit was made
        log_result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "[TEST]" in log_result.stdout, "Commit should exist"


class TestLegacyFallback:
    """Tests for backwards compatibility with single-tier workspaces."""

    def test_legacy_workspace_works_without_flag(self, tmp_path):
        """Verify workspaces work normally when two-tier is not enabled."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=False,
        )

        # Create a file directly in workspace root
        test_file = workspace / "test.txt"
        test_file.write_text("test content")

        assert test_file.exists(), "Files should work in workspace root"
        assert manager.use_two_tier_workspace is False, "Flag should be False"


class TestFinalSnapshotSelection:
    """Tests for choosing the correct source when saving final snapshots."""

    @pytest.mark.asyncio
    async def test_final_snapshot_uses_snapshot_storage_when_workspace_cleared(self, tmp_path, monkeypatch):
        """Final snapshot should copy from snapshot_storage if workspace was cleared."""

        # Isolate log output to the test directory
        monkeypatch.setattr(logger_config, "_LOG_BASE_SESSION_DIR", None)
        monkeypatch.setattr(logger_config, "_LOG_SESSION_DIR", None)
        monkeypatch.setattr(logger_config, "_CURRENT_TURN", None)
        monkeypatch.setattr(logger_config, "_CURRENT_ATTEMPT", None)
        logger_config.set_log_base_session_dir_absolute(tmp_path / "logs")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        snapshot_storage = tmp_path / "snapshots"
        snapshot_storage.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
            use_two_tier_workspace=True,
        )

        manager.setup_orchestration_paths(
            agent_id="agent_a",
            snapshot_storage=str(snapshot_storage),
        )

        artifact = workspace / "scratch" / "artifact.txt"
        artifact.write_text("answer file")

        # Populate snapshot_storage with the workspace contents
        await manager.save_snapshot()
        manager.clear_workspace()  # Clears workspace but preserves .git

        # Final snapshot should use snapshot_storage fallback
        await manager.save_snapshot(is_final=True)

        final_workspace = logger_config.get_log_session_dir() / "final" / "agent_a" / "workspace"
        final_artifact = final_workspace / "scratch" / "artifact.txt"
        assert final_artifact.exists(), "Final workspace should include artifacts from snapshot storage"
        assert final_artifact.read_text() == "answer file"


class TestClearWorkspacePreservesMassgen:
    """The .massgen directory must survive clear_workspace calls.

    Regression test: subagent MCP config files live in .massgen/subagent_mcp/
    and are written once at session start. clear_workspace() runs at the start
    of every round and was deleting them, so by the time the MCP server
    launched (potentially many rounds later) the files were gone.
    """

    def test_clear_workspace_preserves_massgen_subagent_mcp_dir(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        temp_parent = tmp_path / "temp_workspaces"
        temp_parent.mkdir()

        manager = FilesystemManager(
            cwd=str(workspace),
            agent_temporary_workspace_parent=str(temp_parent),
        )

        # Simulate orchestrator writing subagent MCP config files
        mcp_dir = workspace / ".massgen" / "subagent_mcp"
        mcp_dir.mkdir(parents=True)
        types_file = mcp_dir / "agent_b_specialized_types.json"
        types_file.write_text('[{"name": "novelty"}]')

        # Also add a regular file that SHOULD be cleared
        regular_file = workspace / "scratch_notes.txt"
        regular_file.write_text("temporary")

        manager.clear_workspace()

        # .massgen/subagent_mcp must survive
        assert types_file.exists(), "clear_workspace deleted .massgen/subagent_mcp config files"
        assert types_file.read_text() == '[{"name": "novelty"}]'

        # Regular files should be cleared
        assert not regular_file.exists(), "clear_workspace should still clear regular files"
