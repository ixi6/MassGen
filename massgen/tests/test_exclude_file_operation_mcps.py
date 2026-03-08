"""
Tests for exclude_file_operation_mcps parameter.

These tests ensure:
1. When exclude_file_operation_mcps is True, filesystem and workspace file operation MCPs are excluded
2. Command execution, media generation, and planning MCPs are preserved
3. The parameter works correctly with various backend configurations

Run with: uv run pytest massgen/tests/test_exclude_file_operation_mcps.py -v
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from massgen.filesystem_manager import FilesystemManager


class TestExcludeFileOperationMCPs:
    """Test exclude_file_operation_mcps parameter functionality."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        temp_workspace_parent = temp_dir / "temp_workspaces"
        temp_workspace_parent.mkdir()
        workspace = temp_dir / "workspace"
        workspace.mkdir()
        yield {"workspace": str(workspace), "temp_workspace_parent": str(temp_workspace_parent)}
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_filesystem_manager_with_exclude_flag_false(self, temp_workspace):
        """Test FilesystemManager with exclude_file_operation_mcps=False (default)."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=False,
        )

        # Verify the flag is stored correctly
        assert manager.exclude_file_operation_mcps is False

        # Get MCP config and verify filesystem tools are NOT excluded
        workspace_config = manager.get_workspace_tools_mcp_config()
        assert "exclude_tools" not in workspace_config or "copy_file" not in workspace_config.get("exclude_tools", [])

    def test_filesystem_manager_with_exclude_flag_true(self, temp_workspace):
        """Test FilesystemManager with exclude_file_operation_mcps=True."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=True,
            enable_mcp_command_line=True,
        )

        # Verify the flag is stored correctly
        assert manager.exclude_file_operation_mcps is True

        # Get workspace tools config and verify file operations are excluded
        workspace_config = manager.get_workspace_tools_mcp_config()
        assert "exclude_tools" in workspace_config
        excluded_tools = workspace_config["exclude_tools"]

        # Verify all file operation tools are excluded
        expected_excluded = [
            "copy_file",
            "copy_files_batch",
            "delete_file",
            "delete_files_batch",
            "compare_directories",
            "compare_files",
        ]
        for tool in expected_excluded:
            assert tool in excluded_tools, f"{tool} should be excluded"

    def test_inject_filesystem_mcp_excludes_filesystem_server(self, temp_workspace):
        """Test that inject_filesystem_mcp limits filesystem MCP tools when flag is True."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=True,
            enable_mcp_command_line=True,
        )

        # Create a mock backend config
        backend_config = {"mcp_servers": []}

        # Inject MCPs
        result_config = manager.inject_filesystem_mcp(backend_config)

        # Get server names
        server_names = [server["name"] for server in result_config["mcp_servers"]]

        # Verify filesystem MCP IS added (but with limited tools - only write_file and edit_file)
        assert "filesystem" in server_names

        # Verify workspace_tools is NOT added (no media generation enabled)
        assert "workspace_tools" not in server_names

        # Verify command_line IS added
        assert "command_line" in server_names

    def test_inject_filesystem_mcp_keeps_workspace_tools_with_media(self, temp_workspace):
        """Test that workspace_tools MCP is kept when media generation is enabled."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=True,
            enable_mcp_command_line=True,
            enable_image_generation=True,  # Enable media generation
        )

        # Create a mock backend config
        backend_config = {"mcp_servers": []}

        # Inject MCPs
        result_config = manager.inject_filesystem_mcp(backend_config)

        # Get server names
        server_names = [server["name"] for server in result_config["mcp_servers"]]

        # Verify filesystem MCP IS added (with limited tools - only write_file and edit_file)
        assert "filesystem" in server_names

        # Verify workspace_tools IS added (for media generation)
        assert "workspace_tools" in server_names

        # Verify command_line IS added
        assert "command_line" in server_names

        # Find workspace_tools server and verify file ops are excluded
        workspace_tools_server = next(s for s in result_config["mcp_servers"] if s["name"] == "workspace_tools")
        assert "exclude_tools" in workspace_tools_server
        assert "copy_file" in workspace_tools_server["exclude_tools"]

    def test_inject_filesystem_mcp_normal_behavior(self, temp_workspace):
        """Test that inject_filesystem_mcp works normally when flag is False."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=False,  # Normal behavior
            enable_mcp_command_line=True,
        )

        # Create a mock backend config
        backend_config = {"mcp_servers": []}

        # Inject MCPs
        result_config = manager.inject_filesystem_mcp(backend_config)

        # Get server names
        server_names = [server["name"] for server in result_config["mcp_servers"]]

        # Verify all MCPs are added
        assert "filesystem" in server_names
        assert "workspace_tools" in server_names
        assert "command_line" in server_names

    def test_workspace_tools_excludes_media_when_disabled(self, temp_workspace):
        """Test that media tools are also excluded when media generation is disabled."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=True,
            enable_image_generation=False,
            enable_audio_generation=False,
        )

        workspace_config = manager.get_workspace_tools_mcp_config()
        excluded_tools = workspace_config.get("exclude_tools", [])

        # Verify file operation tools are excluded
        assert "copy_file" in excluded_tools

        # Verify media tools are excluded
        assert "generate_and_store_image_with_input_images" in excluded_tools
        assert "generate_and_store_image_no_input_images" in excluded_tools
        assert "generate_and_store_audio_with_input_audios" in excluded_tools
        assert "generate_and_store_audio_no_input_audios" in excluded_tools

    def test_workspace_tools_keeps_media_when_enabled(self, temp_workspace):
        """Test that media tools are kept when media generation is enabled."""
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            exclude_file_operation_mcps=True,
            enable_image_generation=True,
            enable_audio_generation=True,
        )

        workspace_config = manager.get_workspace_tools_mcp_config()
        excluded_tools = workspace_config.get("exclude_tools", [])

        # Verify file operation tools are excluded
        assert "copy_file" in excluded_tools

        # Verify media tools are NOT excluded
        assert "generate_and_store_image_with_input_images" not in excluded_tools
        assert "generate_and_store_audio_with_input_audios" not in excluded_tools

    def test_workspace_tools_no_longer_contains_skills(self, temp_workspace):
        """Skills tool has been extracted to its own MCP server.

        Workspace tools should not reference skills at all — neither
        including nor excluding them.
        """
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_mcp_command_line=True,
        )

        workspace_config = manager.get_workspace_tools_mcp_config()
        excluded_tools = workspace_config.get("exclude_tools", [])
        assert "skills" not in excluded_tools
        assert "MASSGEN_DISABLE_SKILLS_TOOL" not in workspace_config.get("env", {})
