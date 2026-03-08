"""Tests for skills directory path permissions.

Verifies that agents without command-line execution still get the skills
directory added to path permissions for filesystem MCP read access.
"""

from pathlib import Path


def test_skills_dir_added_for_non_command_exec_agents(tmp_path: Path) -> None:
    """Skills directory should be added to path permissions when enable_mcp_command_line=False."""
    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "demo").mkdir()
    (skills_dir / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fm = FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(tmp_path / "temp"),
        enable_mcp_command_line=False,
    )

    fm.setup_orchestration_paths(
        agent_id="test_agent",
        skills_directory=str(skills_dir),
    )

    # Check that the skills path was added to managed paths
    managed_path_types = [mp.path_type for mp in fm.path_permission_manager.managed_paths]
    assert "skills_read" in managed_path_types, f"Expected 'skills_read' in managed path types, got: {managed_path_types}"

    # Check that the local_skills_directory was set
    assert fm.local_skills_directory is not None
    assert fm.local_skills_directory == skills_dir.resolve()


def test_skills_dir_in_mcp_filesystem_paths(tmp_path: Path) -> None:
    """Workspace tools MCP --allowed-paths should include the skills directory."""
    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "demo").mkdir()
    (skills_dir / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fm = FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(tmp_path / "temp"),
        enable_mcp_command_line=False,
    )

    fm.setup_orchestration_paths(
        agent_id="test_agent",
        skills_directory=str(skills_dir),
    )

    mcp_paths = fm.path_permission_manager.get_mcp_filesystem_paths()
    resolved_skills = str(skills_dir.resolve())
    assert resolved_skills in mcp_paths, f"Expected skills dir {resolved_skills} in MCP filesystem paths, got: {mcp_paths}"


def test_skills_dir_not_added_when_command_exec_enabled(tmp_path: Path) -> None:
    """Skills directory should NOT be added via the elif branch when enable_mcp_command_line=True.

    (Command-exec agents get skills through setup_local_skills instead.)
    """
    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "demo").mkdir()
    (skills_dir / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fm = FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(tmp_path / "temp"),
        enable_mcp_command_line=True,
        command_line_execution_mode="local",
    )

    fm.setup_orchestration_paths(
        agent_id="test_agent",
        skills_directory=str(skills_dir),
    )

    # Command-exec agents use setup_local_skills which creates a merged temp dir,
    # so the path type should be "local_skills" not "skills_read"
    managed_path_types = [mp.path_type for mp in fm.path_permission_manager.managed_paths]
    assert "skills_read" not in managed_path_types, f"'skills_read' should not be present for command-exec agents, got: {managed_path_types}"


def test_skills_dir_not_added_when_nonexistent(tmp_path: Path) -> None:
    """Skills directory should not be added if it doesn't exist."""
    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    nonexistent_skills = tmp_path / ".agent" / "skills"  # not created

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fm = FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(tmp_path / "temp"),
        enable_mcp_command_line=False,
    )

    fm.setup_orchestration_paths(
        agent_id="test_agent",
        skills_directory=str(nonexistent_skills),
    )

    managed_path_types = [mp.path_type for mp in fm.path_permission_manager.managed_paths]
    assert "skills_read" not in managed_path_types
    assert fm.local_skills_directory is None
