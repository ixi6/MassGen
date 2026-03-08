"""
Tests for MCP tool code generator.

These tests ensure:
1. Tool wrappers are generated correctly from MCP schemas
2. Function signatures match schema parameters
3. Docstrings are properly formatted
4. MCP client code is functional
5. Tool registry is correctly generated

Run with: uv run pytest massgen/tests/test_code_generator.py -v
"""

import pytest

from massgen.mcp_tools.code_generator import MCPToolCodeGenerator


class TestMCPToolCodeGenerator:
    """Test MCPToolCodeGenerator functionality."""

    @pytest.fixture
    def generator(self):
        """Create a code generator instance."""
        return MCPToolCodeGenerator()

    @pytest.fixture
    def simple_tool_schema(self):
        """Simple tool schema with required parameters."""
        return {
            "description": "Get weather forecast for a location",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name or coordinates",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to forecast",
                    },
                },
                "required": ["location"],
            },
        }

    @pytest.fixture
    def complex_tool_schema(self):
        """Complex tool schema with various parameter types."""
        return {
            "description": "Create a GitHub issue with details",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Issue title",
                    },
                    "body": {
                        "type": "string",
                        "description": "Issue description",
                    },
                    "labels": {
                        "type": "array",
                        "description": "Issue labels",
                    },
                    "assignees": {
                        "type": "array",
                        "description": "User logins to assign",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority level",
                        "default": 1,
                    },
                },
                "required": ["title", "body"],
            },
        }

    def test_generate_tool_wrapper_basic_structure(self, generator, simple_tool_schema):
        """Test basic structure of generated tool wrapper."""
        code = generator.generate_tool_wrapper(
            server_name="weather",
            tool_name="get_forecast",
            tool_schema=simple_tool_schema,
        )

        # Verify essential imports
        assert "from typing import Any, Dict, Optional" in code
        assert "import sys" in code
        assert "from pathlib import Path" in code
        assert "from client import call_mcp_tool" in code

        # Verify function definition
        assert "def get_forecast(" in code

        # Verify MCP call
        assert 'server="weather"' in code
        assert 'tool="get_forecast"' in code

        # Verify CLI usage section
        assert 'if __name__ == "__main__"' in code

    def test_generate_tool_wrapper_function_signature(self, generator, simple_tool_schema):
        """Test function signature generation with required and optional parameters."""
        code = generator.generate_tool_wrapper(
            server_name="weather",
            tool_name="get_forecast",
            tool_schema=simple_tool_schema,
        )

        # Required parameter should not have default
        assert "location: str" in code

        # Optional parameter should have default
        assert "days: Optional[int] = None" in code

    def test_generate_tool_wrapper_docstring(self, generator, simple_tool_schema):
        """Test docstring generation from schema."""
        code = generator.generate_tool_wrapper(
            server_name="weather",
            tool_name="get_forecast",
            tool_schema=simple_tool_schema,
        )

        # Verify docstring contains description
        assert "Get weather forecast for a location" in code

        # Verify Args section
        assert "Args:" in code
        assert "location (str):" in code
        assert "City name or coordinates" in code
        assert "days (int, optional):" in code
        assert "Number of days to forecast" in code

        # Verify Returns section
        assert "Returns:" in code
        assert "Any: Tool execution result from MCP server" in code

    def test_generate_tool_wrapper_complex_params(self, generator, complex_tool_schema):
        """Test parameter handling for complex schemas."""
        code = generator.generate_tool_wrapper(
            server_name="github",
            tool_name="create_issue",
            tool_schema=complex_tool_schema,
        )

        # Required string parameters
        assert "title: str" in code
        assert "body: str" in code

        # Optional array parameters
        assert "labels: Optional[list] = None" in code
        assert "assignees: Optional[list] = None" in code

        # Optional parameter with default value
        assert "priority: Optional[int] = 1" in code

    def test_build_function_params_required_only(self, generator):
        """Test function parameter building with only required params."""
        properties = {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        }
        required = ["name", "age"]

        params = generator._build_function_params(properties, required)

        assert "name: str" in params
        assert "age: int" in params
        assert len(params) == 2

    def test_build_function_params_optional_only(self, generator):
        """Test function parameter building with only optional params."""
        properties = {
            "name": {"type": "string"},
            "count": {"type": "integer", "default": 10},
        }
        required = []

        params = generator._build_function_params(properties, required)

        assert "name: Optional[str] = None" in params
        assert "count: Optional[int] = 10" in params

    def test_build_function_params_mixed(self, generator):
        """Test function parameter building with mixed required/optional."""
        properties = {
            "required_str": {"type": "string"},
            "optional_int": {"type": "integer"},
            "optional_with_default": {"type": "boolean", "default": True},
        }
        required = ["required_str"]

        params = generator._build_function_params(properties, required)

        assert "required_str: str" in params
        assert "optional_int: Optional[int] = None" in params
        assert "optional_with_default: Optional[bool] = True" in params

    def test_json_type_to_python_type(self, generator):
        """Test JSON type to Python type conversion."""
        assert generator._json_type_to_python_type("string") == "str"
        assert generator._json_type_to_python_type("integer") == "int"
        assert generator._json_type_to_python_type("number") == "float"
        assert generator._json_type_to_python_type("boolean") == "bool"
        assert generator._json_type_to_python_type("array") == "list"
        assert generator._json_type_to_python_type("object") == "dict"
        assert generator._json_type_to_python_type("unknown") == "Any"

    def test_get_default_value_string(self, generator):
        """Test default value extraction for strings."""
        param_schema = {"type": "string", "default": "hello"}
        assert generator._get_default_value(param_schema) == '"hello"'

    def test_get_default_value_number(self, generator):
        """Test default value extraction for numbers."""
        param_schema = {"type": "integer", "default": 42}
        assert generator._get_default_value(param_schema) == "42"

    def test_get_default_value_boolean(self, generator):
        """Test default value extraction for booleans."""
        param_schema = {"type": "boolean", "default": True}
        assert generator._get_default_value(param_schema) == "True"

    def test_get_default_value_none(self, generator):
        """Test default value when no default specified."""
        param_schema = {"type": "string"}
        assert generator._get_default_value(param_schema) == "None"

    def test_build_docstring(self, generator):
        """Test docstring building."""
        description = "Test function"
        properties = {
            "name": {"type": "string", "description": "User name"},
            "age": {"type": "integer", "description": "User age"},
        }
        required = ["name"]

        docstring = generator._build_docstring(description, properties, required)

        # Should be indented
        assert docstring.startswith("    ")

        # Should contain description
        assert "Test function" in docstring

        # Should contain Args section
        assert "Args:" in docstring
        assert "name (str):" in docstring
        assert "User name" in docstring
        assert "age (int, optional):" in docstring
        assert "User age" in docstring

        # Should contain Returns section
        assert "Returns:" in docstring
        assert "Any: Tool execution result from MCP server" in docstring

    def test_build_args_dict_empty(self, generator):
        """Test argument dict building with no parameters."""
        args_dict = generator._build_args_dict({})
        assert args_dict == "{}"

    def test_build_args_dict_single_param(self, generator):
        """Test argument dict building with single parameter."""
        properties = {"location": {"type": "string"}}
        args_dict = generator._build_args_dict(properties)

        assert '"location": location' in args_dict

    def test_build_args_dict_multiple_params(self, generator):
        """Test argument dict building with multiple parameters."""
        properties = {
            "location": {"type": "string"},
            "days": {"type": "integer"},
            "units": {"type": "string"},
        }
        args_dict = generator._build_args_dict(properties)

        assert '"location": location' in args_dict
        assert '"days": days' in args_dict
        assert '"units": units' in args_dict

    def test_generate_server_init(self, generator):
        """Test server __init__.py generation."""
        server_name = "weather"
        tool_names = ["get_forecast", "get_current", "get_alerts"]

        code = generator.generate_server_init(server_name, tool_names)

        # Verify imports
        assert "from .get_forecast import get_forecast" in code
        assert "from .get_current import get_current" in code
        assert "from .get_alerts import get_alerts" in code

        # Verify __all__
        assert '__all__ = ["get_forecast", "get_current", "get_alerts"]' in code

        # Verify docstring
        assert "weather MCP Server Tools" in code
        assert "- get_forecast" in code
        assert "- get_current" in code
        assert "- get_alerts" in code

    def test_generate_server_init_single_tool(self, generator):
        """Test server __init__.py generation with single tool."""
        code = generator.generate_server_init("github", ["create_issue"])

        assert "from .create_issue import create_issue" in code
        assert '__all__ = ["create_issue"]' in code

    def test_generate_mcp_client(self, generator):
        """Test MCP client code generation."""
        code = generator.generate_mcp_client()

        # Verify imports
        assert "import asyncio" in code
        assert "import json" in code
        assert "from massgen.mcp_tools.client import MCPClient" in code

        # Verify server config loading
        assert "servers.json" in code
        assert "SERVERS = json.load(f)" in code

        # Verify client functions
        assert "async def _ensure_client()" in code
        assert "def call_mcp_tool(server: str, tool: str, arguments: Dict[str, Any])" in code
        assert "async def call_mcp_tool_async(server: str, tool: str, arguments: Dict[str, Any])" in code

        # Verify utility functions
        assert "def list_servers()" in code
        assert "def get_server_config(server: str)" in code
        assert "async def cleanup()" in code

        # Verify async handling (modernized to use run_async_safely)
        assert "run_async_safely" in code

        # Verify prefixed tool name handling
        assert 'prefixed_tool_name = f"mcp__{server}__{tool}"' in code

    def test_generate_tools_init(self, generator):
        """Test tools directory __init__.py generation (filesystem-based discovery)."""
        servers = ["weather", "github", "salesforce"]

        code = generator.generate_tools_init(servers)

        # Verify docstring mentions servers
        assert "- weather" in code
        assert "- github" in code
        assert "- salesforce" in code

        # Verify filesystem-based discovery guidance (not registry functions)
        assert "ls servers/" in code
        assert "cat servers/" in code

        # Verify usage examples show imports (not registry calls)
        assert "from servers.weather import" in code or "from servers.github import" in code

        # Should NOT contain old registry functions
        assert "def list_tools()" not in code
        assert "def load(" not in code
        assert "def describe(" not in code
        assert "servers.list_tools()" not in code

    def test_generate_tool_wrapper_no_parameters(self, generator):
        """Test tool wrapper generation with no parameters."""
        schema = {
            "description": "Get server status",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }

        code = generator.generate_tool_wrapper(
            server_name="monitoring",
            tool_name="get_status",
            tool_schema=schema,
        )

        # Function should have no parameters (except self signature is empty)
        assert "def get_status()" in code

        # Arguments should be empty dict
        assert "arguments={}" in code

    def test_generate_tool_wrapper_all_optional_params(self, generator):
        """Test tool wrapper with all optional parameters."""
        schema = {
            "description": "Search with filters",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        }

        code = generator.generate_tool_wrapper(
            server_name="search",
            tool_name="search",
            tool_schema=schema,
        )

        # All params should be optional with defaults
        assert 'query: Optional[str] = ""' in code
        assert "limit: Optional[int] = 10" in code

    def test_generate_tool_wrapper_array_and_object_types(self, generator):
        """Test tool wrapper with array and object type parameters."""
        schema = {
            "description": "Complex data operation",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "description": "List of items"},
                    "config": {"type": "object", "description": "Configuration object"},
                },
                "required": ["items"],
            },
        }

        code = generator.generate_tool_wrapper(
            server_name="data",
            tool_name="process",
            tool_schema=schema,
        )

        # Array and object types should map correctly
        assert "items: list" in code
        assert "config: Optional[dict] = None" in code

    def test_generate_tool_wrapper_preserves_description(self, generator):
        """Test that tool and parameter descriptions are preserved."""
        schema = {
            "description": "This is a very specific tool description",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "This is a very specific parameter description",
                    },
                },
                "required": ["param1"],
            },
        }

        code = generator.generate_tool_wrapper(
            server_name="test",
            tool_name="test_tool",
            tool_schema=schema,
        )

        # Descriptions should appear in docstring
        assert "This is a very specific tool description" in code
        assert "This is a very specific parameter description" in code

    def test_generate_tool_wrapper_cli_usage(self, generator, simple_tool_schema):
        """Test that CLI usage section is generated."""
        code = generator.generate_tool_wrapper(
            server_name="weather",
            tool_name="get_forecast",
            tool_schema=simple_tool_schema,
        )

        # Verify CLI usage section
        assert 'if __name__ == "__main__"' in code
        assert "import json" in code
        assert "sys.argv" in code
        assert "result = get_forecast(" in code
        assert "print(json.dumps(result, indent=2))" in code
        assert "Usage: python get_forecast.py" in code
