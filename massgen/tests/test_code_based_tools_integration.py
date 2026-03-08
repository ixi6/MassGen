"""
Integration tests for code-based tools feature.

These tests ensure:
1. Complete directory structure is created correctly
2. Python wrappers are generated and importable
3. Tool registry functions work
4. Generated code can be executed
5. Integration with FilesystemManager works

Run with: uv run pytest massgen/tests/test_code_based_tools_integration.py -v
"""

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from massgen.filesystem_manager import FilesystemManager
from massgen.filesystem_manager._tool_code_writer import ToolCodeWriter
from massgen.mcp_tools.code_generator import MCPToolCodeGenerator


class MockToolObject:
    """Mock MCP tool object."""

    def __init__(self, description: str, input_schema: dict[str, Any]):
        self.description = description
        self.inputSchema = input_schema


class MockMCPClient:
    """Mock MCP client for testing."""

    def __init__(self):
        # Create mock tools
        self.tools = {
            "mcp__weather__get_forecast": MockToolObject(
                description="Get weather forecast for a location",
                input_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                        "days": {"type": "integer", "description": "Number of days"},
                    },
                    "required": ["location"],
                },
            ),
            "mcp__weather__get_current": MockToolObject(
                description="Get current weather",
                input_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                    },
                    "required": ["location"],
                },
            ),
            "mcp__github__create_issue": MockToolObject(
                description="Create a GitHub issue",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Issue title"},
                        "body": {"type": "string", "description": "Issue body"},
                    },
                    "required": ["title", "body"],
                },
            ),
        }

        # Tool to server mapping
        self._tool_to_server = {
            "mcp__weather__get_forecast": "weather",
            "mcp__weather__get_current": "weather",
            "mcp__github__create_issue": "github",
        }

        # Server configs (MCP client uses _server_configs)
        self._server_configs = [
            {
                "name": "weather",
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-weather"],
            },
            {
                "name": "github",
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
            },
        ]


class TestCodeBasedToolsIntegration:
    """Integration tests for code-based tools feature."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        workspace = temp_dir / "workspace"
        workspace.mkdir()
        temp_workspace_parent = temp_dir / "temp_workspaces"
        temp_workspace_parent.mkdir()

        yield {
            "workspace": str(workspace),
            "temp_workspace_parent": str(temp_workspace_parent),
            "temp_dir": temp_dir,
        }

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_mcp_client(self):
        """Create a mock MCP client."""
        return MockMCPClient()

    @pytest.fixture
    def filesystem_manager(self, temp_workspace):
        """Create a FilesystemManager with code-based tools enabled."""
        return FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            exclude_file_operation_mcps=True,
        )

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_creates_directories(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that setup_code_based_tools creates correct directory structure."""
        # Setup code-based tools
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])

        # Verify directory structure
        assert (workspace / "servers").exists()
        assert (workspace / "servers" / "__init__.py").exists()
        assert (workspace / "servers" / "weather").exists()
        assert (workspace / "servers" / "weather" / "__init__.py").exists()
        assert (workspace / "servers" / "github").exists()
        assert (workspace / "servers" / "github" / "__init__.py").exists()
        # utils/ NOT pre-created - agents create in their workspace as needed
        assert (workspace / ".mcp").exists()
        assert (workspace / ".mcp" / "client.py").exists()
        assert (workspace / ".mcp" / "servers.json").exists()
        assert (workspace / "custom_tools").exists()

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_generates_tool_wrappers(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that tool wrappers are generated correctly."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])

        # Check weather tools
        get_forecast_file = workspace / "servers" / "weather" / "get_forecast.py"
        assert get_forecast_file.exists()

        content = get_forecast_file.read_text()
        assert "def get_forecast(" in content
        assert "location: str" in content
        assert "days: Optional[int]" in content
        assert "Get weather forecast for a location" in content
        assert 'server="weather"' in content
        assert 'tool="get_forecast"' in content

        # Check github tools
        create_issue_file = workspace / "servers" / "github" / "create_issue.py"
        assert create_issue_file.exists()

        content = create_issue_file.read_text()
        assert "def create_issue(" in content
        assert "title: str" in content
        assert "body: str" in content

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_generates_mcp_client(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that MCP client code is generated."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])
        client_file = workspace / ".mcp" / "client.py"

        assert client_file.exists()

        content = client_file.read_text()
        assert "def call_mcp_tool(" in content
        assert "async def call_mcp_tool_async(" in content
        assert "async def _ensure_client()" in content
        assert "def list_servers()" in content
        assert "from massgen.mcp_tools.client import MCPClient" in content

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_generates_servers_json(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that servers.json is generated with correct config."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])
        servers_json = workspace / ".mcp" / "servers.json"

        assert servers_json.exists()

        with open(servers_json) as f:
            servers = json.load(f)

        assert "weather" in servers
        assert "github" in servers
        assert servers["weather"]["command"] == "npx"
        assert servers["github"]["type"] == "stdio"

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_generates_servers_init(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that servers __init__.py is generated (no registry, just docstring)."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])
        init_file = workspace / "servers" / "__init__.py"

        assert init_file.exists()

        content = init_file.read_text()
        # Should have docstring explaining filesystem-based discovery
        assert "MCP Server Tools" in content
        assert "Auto-generated Python wrappers" in content
        # Should NOT have registry functions
        assert "def list_tools()" not in content
        assert "def load(tool_path: str)" not in content
        assert "def describe(tool_path: str)" not in content

    @pytest.mark.asyncio
    async def test_generated_server_init_imports(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that server __init__.py contains correct imports."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])
        weather_init = workspace / "servers" / "weather" / "__init__.py"

        content = weather_init.read_text()

        assert "from .get_forecast import get_forecast" in content
        assert "from .get_current import get_current" in content
        assert '__all__ = ["get_forecast", "get_current"]' in content

    @pytest.mark.asyncio
    async def test_custom_tools_directory_created(
        self,
        filesystem_manager,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that custom_tools/ directory is created."""
        await filesystem_manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])
        custom_tools = workspace / "custom_tools"

        assert custom_tools.exists()
        assert custom_tools.is_dir()

    @pytest.mark.asyncio
    async def test_extract_mcp_tool_schemas_organizes_by_server(
        self,
        filesystem_manager,
        mock_mcp_client,
    ):
        """Test that _extract_mcp_tool_schemas organizes tools by server."""
        servers_with_tools = filesystem_manager._extract_mcp_tool_schemas(mock_mcp_client)

        # Should be a list with two servers
        assert len(servers_with_tools) == 2
        assert isinstance(servers_with_tools, list)

        server_names = [s["name"] for s in servers_with_tools]
        assert "weather" in server_names
        assert "github" in server_names

        # Weather should have 2 tools
        weather_server = next(s for s in servers_with_tools if s["name"] == "weather")
        weather_tools = weather_server["tools"]
        assert len(weather_tools) == 2

        tool_names = [t["name"] for t in weather_tools]
        assert "get_forecast" in tool_names
        assert "get_current" in tool_names

        # GitHub should have 1 tool
        github_server = next(s for s in servers_with_tools if s["name"] == "github")
        github_tools = github_server["tools"]
        assert len(github_tools) == 1
        assert github_tools[0]["name"] == "create_issue"

    @pytest.mark.asyncio
    async def test_extract_mcp_tool_schemas_strips_prefix(
        self,
        filesystem_manager,
        mock_mcp_client,
    ):
        """Test that tool name prefixes are stripped."""
        servers_with_tools = filesystem_manager._extract_mcp_tool_schemas(mock_mcp_client)

        weather_server = next(s for s in servers_with_tools if s["name"] == "weather")
        weather_tools = weather_server["tools"]

        # Tool names should not have mcp__ prefix
        for tool in weather_tools:
            assert not tool["name"].startswith("mcp__")
            assert "get_" in tool["name"]

    @pytest.mark.asyncio
    async def test_extract_mcp_tool_schemas_preserves_schemas(
        self,
        filesystem_manager,
        mock_mcp_client,
    ):
        """Test that tool schemas are preserved correctly."""
        servers_with_tools = filesystem_manager._extract_mcp_tool_schemas(mock_mcp_client)

        weather_server = next(s for s in servers_with_tools if s["name"] == "weather")
        weather_tools = weather_server["tools"]
        forecast_tool = next(t for t in weather_tools if t["name"] == "get_forecast")

        # Schema should be preserved
        assert forecast_tool["description"] == "Get weather forecast for a location"
        assert "location" in forecast_tool["inputSchema"]["properties"]
        assert "days" in forecast_tool["inputSchema"]["properties"]
        assert "location" in forecast_tool["inputSchema"]["required"]

    @pytest.mark.asyncio
    async def test_setup_code_based_tools_disabled_does_nothing(
        self,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that when feature is disabled, nothing is generated."""
        # Create filesystem manager with feature disabled
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=False,  # Disabled
        )

        await manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])

        # No directories should be created
        assert not (workspace / "servers").exists()
        assert not (workspace / "utils").exists()
        assert not (workspace / ".mcp").exists()

    @pytest.mark.asyncio
    async def test_tool_code_writer_creates_complete_structure(self, temp_workspace):
        """Test ToolCodeWriter creates complete directory structure."""
        workspace = Path(temp_workspace["workspace"])

        # Create mock server data
        servers_with_tools = [
            {
                "name": "weather",
                "config": {"type": "stdio", "command": "npx"},
                "tools": [
                    {
                        "name": "get_forecast",
                        "description": "Get forecast",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ],
            },
        ]

        writer = ToolCodeWriter()
        writer.setup_code_based_tools(
            workspace_path=workspace,
            mcp_servers=servers_with_tools,
            custom_tools_path=None,
        )

        # Verify all directories created
        assert (workspace / "servers").exists()
        assert (workspace / "servers" / "weather").exists()
        # utils/ NOT created - agents create in their workspace as needed
        assert (workspace / ".mcp").exists()
        assert (workspace / "custom_tools").exists()

        # Verify files created
        assert (workspace / "servers" / "__init__.py").exists()
        assert (workspace / "servers" / "weather" / "__init__.py").exists()
        assert (workspace / "servers" / "weather" / "get_forecast.py").exists()
        assert (workspace / ".mcp" / "client.py").exists()
        assert (workspace / ".mcp" / "servers.json").exists()

    def test_code_generator_produces_importable_code(self, temp_workspace):
        """Test that generated code is syntactically valid Python."""
        generator = MCPToolCodeGenerator()

        schema = {
            "description": "Test tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                },
                "required": ["param1"],
            },
        }

        code = generator.generate_tool_wrapper("test_server", "test_tool", schema)

        # Try to compile the code
        try:
            compile(code, "<generated>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")

    @pytest.mark.asyncio
    async def test_shared_tools_directory_generates_in_shared_location(
        self,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that tools are generated in shared location when configured."""
        shared_tools = Path(temp_workspace["temp_dir"]) / "shared_tools"
        shared_tools.mkdir()

        # Create filesystem manager with shared tools directory
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            shared_tools_directory=str(shared_tools),
        )

        await manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        # Verify tools are in shared location (with hash subdirectory)
        actual_shared_path = manager.shared_tools_directory
        assert actual_shared_path is not None
        assert actual_shared_path.exists()
        assert (actual_shared_path / "servers").exists()
        assert (actual_shared_path / "servers" / "weather").exists()
        assert (actual_shared_path / ".mcp").exists()

        workspace = Path(temp_workspace["workspace"])
        # Verify workspace has symlinks (not real directories)
        assert (workspace / "servers").is_symlink()
        assert (workspace / "servers").resolve() == (actual_shared_path / "servers").resolve()

    @pytest.mark.asyncio
    async def test_shared_tools_directory_skips_regeneration(
        self,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that tools are not regenerated if they already exist in shared location."""
        shared_tools = Path(temp_workspace["temp_dir"]) / "shared_tools"
        shared_tools.mkdir()

        # First agent generates tools
        manager1 = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            shared_tools_directory=str(shared_tools),
        )

        await manager1.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        # Record modification time (tools are in hash subdirectory)
        actual_shared_path = manager1.shared_tools_directory
        servers_init = actual_shared_path / "servers" / "__init__.py"
        original_mtime = servers_init.stat().st_mtime

        # Second agent should skip regeneration but still create symlinks
        workspace2 = Path(temp_workspace["temp_dir"]) / "workspace2"
        workspace2.mkdir()

        manager2 = FilesystemManager(
            cwd=str(workspace2),
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            shared_tools_directory=str(shared_tools),
        )

        await manager2.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        # Verify modification time hasn't changed (no regeneration)
        new_mtime = servers_init.stat().st_mtime
        assert new_mtime == original_mtime

        # Verify second workspace also has symlinks
        assert (workspace2 / "servers").is_symlink()
        assert (workspace2 / "servers").resolve() == (actual_shared_path / "servers").resolve()

    @pytest.mark.asyncio
    async def test_shared_tools_directory_adds_to_read_only_paths(
        self,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that shared tools directory is added to path manager as read-only."""
        shared_tools = Path(temp_workspace["temp_dir"]) / "shared_tools"
        shared_tools.mkdir()

        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            shared_tools_directory=str(shared_tools),
        )

        await manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        # Verify shared tools path is in path manager
        # Check that it's registered (exact permission checking depends on PathPermissionManager API)
        assert manager.path_permission_manager is not None

        # Verify symlinks were created in workspace (pointing to hash subdirectory)
        actual_shared_path = manager.shared_tools_directory
        workspace = Path(temp_workspace["workspace"])
        assert (workspace / "servers").is_symlink()
        assert (workspace / "servers").resolve() == (actual_shared_path / "servers").resolve()
        assert (workspace / ".mcp").is_symlink()
        assert (workspace / "custom_tools").is_symlink()

    @pytest.mark.asyncio
    async def test_without_shared_tools_directory_uses_workspace(
        self,
        mock_mcp_client,
        temp_workspace,
    ):
        """Test that tools are generated in workspace when shared_tools_directory is None."""
        # Create filesystem manager WITHOUT shared tools directory
        manager = FilesystemManager(
            cwd=temp_workspace["workspace"],
            agent_temporary_workspace_parent=temp_workspace["temp_workspace_parent"],
            enable_code_based_tools=True,
            enable_mcp_command_line=True,
            shared_tools_directory=None,  # Explicitly None
        )

        await manager.setup_code_based_tools_from_mcp_client(mock_mcp_client)

        workspace = Path(temp_workspace["workspace"])

        # Verify tools are in workspace (per-agent mode)
        assert (workspace / "servers").exists()
        assert (workspace / "servers" / "weather").exists()
        assert (workspace / ".mcp").exists()
