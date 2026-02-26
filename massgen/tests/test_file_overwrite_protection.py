"""
Unit tests for file overwrite protection.

Tests that write_file is blocked when trying to overwrite existing files,
while edit_file is allowed on existing files.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from massgen.filesystem_manager import PathPermissionManager, Permission


class OverwriteTestHelper:
    """Helper class for setting up test environment."""

    def __init__(self):
        self.temp_dir = None
        self.workspace_dir = None

    def setup(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace_dir = self.temp_dir / "workspace"
        self.workspace_dir.mkdir(parents=True)

    def teardown(self):
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def create_permission_manager(self):
        manager = PathPermissionManager(context_write_access_enabled=False)
        manager.add_path(self.workspace_dir, Permission.WRITE, "workspace")
        return manager


class TestIsPureWriteTool:
    """Test _is_pure_write_tool helper method."""

    @pytest.fixture(autouse=True)
    def setup_helper(self):
        self.helper = OverwriteTestHelper()
        self.helper.setup()
        yield
        self.helper.teardown()

    def test_write_is_pure_write(self):
        """Test that 'Write' (Claude Code) is identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("Write") is True

    def test_write_file_is_pure_write(self):
        """Test that 'write_file' (MCP) is identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("write_file") is True

    def test_mcp_prefixed_write_file_is_pure_write(self):
        """Test that prefixed MCP write_file is identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("mcp__filesystem__write_file") is True
        assert manager._is_pure_write_tool("mcp__custom_server__write_file") is True

    def test_edit_is_not_pure_write(self):
        """Test that 'Edit' (Claude Code) is NOT identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("Edit") is False

    def test_edit_file_is_not_pure_write(self):
        """Test that 'edit_file' (MCP) is NOT identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("edit_file") is False

    def test_multi_edit_is_not_pure_write(self):
        """Test that 'MultiEdit' is NOT identified as pure write."""
        manager = self.helper.create_permission_manager()
        assert manager._is_pure_write_tool("MultiEdit") is False


class TestFileOverwriteProtection:
    """Test file overwrite protection in _validate_write_tool."""

    @pytest.fixture(autouse=True)
    def setup_helper(self):
        self.helper = OverwriteTestHelper()
        self.helper.setup()
        yield
        self.helper.teardown()

    def test_write_to_nonexistent_file_allowed(self):
        """Test that write_file to a new file is allowed."""
        manager = self.helper.create_permission_manager()
        new_file = self.helper.workspace_dir / "new_file.txt"

        # File doesn't exist
        assert not new_file.exists()

        # write_file should be allowed
        tool_args = {"file_path": str(new_file)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        assert allowed is True
        assert reason is None

    def test_write_to_existing_file_blocked(self):
        """Test that write_file to existing file is blocked."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "existing.txt"
        existing_file.write_text("original content")

        # File exists
        assert existing_file.exists()

        # write_file should be blocked
        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        assert allowed is False
        assert "Cannot overwrite existing file" in reason
        assert "existing.txt" in reason
        assert "edit_file" in reason

    def test_write_tool_claude_code_blocked(self):
        """Test that Claude Code 'Write' to existing file is blocked."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "test.py"
        existing_file.write_text("# original")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("Write", tool_args)

        assert allowed is False
        assert "Cannot overwrite" in reason

    def test_mcp_prefixed_write_file_blocked(self):
        """Test that prefixed MCP write_file to existing file is blocked."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "config.json"
        existing_file.write_text("{}")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("mcp__filesystem__write_file", tool_args)

        assert allowed is False
        assert "Cannot overwrite" in reason

    def test_write_overwrite_of_agent_created_file_allowed(self):
        """Test that pure Write can overwrite files created earlier in this run."""
        manager = self.helper.create_permission_manager()
        created_file = self.helper.workspace_dir / "generated.txt"
        created_file.write_text("initial content")

        # Simulate a file created earlier in this run.
        manager.file_operation_tracker.mark_as_created(created_file)

        tool_args = {"file_path": str(created_file)}
        allowed, reason = manager._validate_write_tool("Write", tool_args)

        assert allowed is True
        assert reason is None

    def test_edit_existing_file_allowed(self):
        """Test that edit_file on existing file is allowed."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "editable.txt"
        existing_file.write_text("editable content")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("edit_file", tool_args)

        assert allowed is True
        assert reason is None

    def test_edit_tool_claude_code_allowed(self):
        """Test that Claude Code 'Edit' on existing file is allowed."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "code.py"
        existing_file.write_text("# code")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("Edit", tool_args)

        assert allowed is True

    def test_write_to_directory_not_blocked(self):
        """Test that write_file to a path that's a directory is not blocked by overwrite check.

        The overwrite protection only applies to files, not directories.
        (Directory handling may have other validations.)
        """
        manager = self.helper.create_permission_manager()
        subdir = self.helper.workspace_dir / "subdir"
        subdir.mkdir()

        # Path exists but is a directory, not a file
        assert subdir.exists()
        assert subdir.is_dir()

        # Should not be blocked by overwrite protection
        # (might fail for other reasons, but not overwrite)
        tool_args = {"file_path": str(subdir)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        # If blocked, should NOT be for overwrite reasons
        if not allowed:
            assert "Cannot overwrite" not in reason


class TestErrorMessageQuality:
    """Test that error messages are helpful."""

    @pytest.fixture(autouse=True)
    def setup_helper(self):
        self.helper = OverwriteTestHelper()
        self.helper.setup()
        yield
        self.helper.teardown()

    def test_error_suggests_edit_file(self):
        """Test that error message suggests using edit_file."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "readme.md"
        existing_file.write_text("# README")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        assert allowed is False
        assert "edit_file" in reason.lower()

    def test_error_suggests_delete_alternative(self):
        """Test that error message mentions delete as alternative."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "data.json"
        existing_file.write_text("{}")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        assert allowed is False
        assert "delete" in reason.lower()

    def test_error_includes_filename(self):
        """Test that error message includes the filename."""
        manager = self.helper.create_permission_manager()
        existing_file = self.helper.workspace_dir / "important_config.yaml"
        existing_file.write_text("key: value")

        tool_args = {"file_path": str(existing_file)}
        allowed, reason = manager._validate_write_tool("write_file", tool_args)

        assert allowed is False
        assert "important_config.yaml" in reason
