"""
MCP Tool Code Generator

Generates Python wrapper code for MCP tools, converting MCP protocol tools
into importable Python functions that agents can discover via filesystem.

This follows the CodeAct paradigm and Anthropic's code-based MCP approach:
- MCP tools become Python functions in servers/ directory
- Agents import and call tools using standard Python
- Reduces context usage
- Enables async patterns and data filtering in utils/ scripts

References:
- https://machinelearning.apple.com/research/codeact
- https://www.anthropic.com/engineering/code-execution-with-mcp
"""

from textwrap import indent
from typing import Any


class MCPToolCodeGenerator:
    """Generates Python wrapper code for MCP tools.

    Converts MCP tool schemas into Python functions that call the MCP
    protocol under the hood while presenting a clean Python API.
    """

    def __init__(self):
        """Initialize the code generator."""

    @staticmethod
    def sanitize_tool_name(tool_name: str) -> str:
        """Convert MCP tool name to valid Python identifier.

        MCP tool names can contain hyphens (e.g., 'get-library-docs'),
        but Python identifiers cannot. This converts hyphens to underscores.

        Args:
            tool_name: Original MCP tool name (may contain hyphens)

        Returns:
            Valid Python identifier (hyphens replaced with underscores)

        Example:
            >>> MCPToolCodeGenerator.sanitize_tool_name("get-library-docs")
            'get_library_docs'
        """
        return tool_name.replace("-", "_")

    def generate_tool_wrapper(
        self,
        server_name: str,
        tool_name: str,
        tool_schema: dict[str, Any],
    ) -> str:
        """Generate Python wrapper code for a single MCP tool.

        Args:
            server_name: Name of the MCP server (e.g., "weather")
            tool_name: Name of the tool (e.g., "get_forecast")
            tool_schema: MCP tool schema with inputSchema and description

        Returns:
            Complete Python file content as a string

        Example:
            >>> generator = MCPToolCodeGenerator()
            >>> schema = {
            ...     "description": "Get weather forecast",
            ...     "inputSchema": {
            ...         "type": "object",
            ...         "properties": {
            ...             "location": {"type": "string", "description": "City name"},
            ...             "days": {"type": "integer", "description": "Number of days"}
            ...         },
            ...         "required": ["location"]
            ...     }
            ... }
            >>> code = generator.generate_tool_wrapper("weather", "get_forecast", schema)
            >>> "def get_forecast(" in code
            True
        """
        # Sanitize tool name for Python identifiers
        sanitized_name = self.sanitize_tool_name(tool_name)

        description = tool_schema.get("description", f"{tool_name} from {server_name} MCP server")
        input_schema = tool_schema.get("inputSchema", {})

        # Extract parameters from JSON schema
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        # Build function signature
        params = self._build_function_params(properties, required)
        param_list = ", ".join(params)

        # Build docstring
        docstring = self._build_docstring(description, properties, required)

        # Build function body
        args_dict = self._build_args_dict(properties)

        # Generate complete function
        code = f'''\
"""
{sanitized_name} - MCP tool wrapper

Auto-generated wrapper for the '{tool_name}' tool from the '{server_name}' MCP server.
This wrapper handles MCP protocol communication transparently.

Note: Original MCP tool name is '{tool_name}', Python function name is '{sanitized_name}'.
"""

from typing import Any, Dict, Optional
import sys
import os
from pathlib import Path

# Add .mcp to path for MCP client
_mcp_path = Path(__file__).parent.parent.parent / '.mcp'
if str(_mcp_path) not in sys.path:
    sys.path.insert(0, str(_mcp_path))

from client import call_mcp_tool


def {sanitized_name}({param_list}) -> Any:
{docstring}
    return call_mcp_tool(
        server="{server_name}",
        tool="{tool_name}",
        arguments={args_dict}
    )


if __name__ == "__main__":
    # CLI usage for testing
    import json

    # Simple CLI: pass first arg as location (or other primary param)
    if len(sys.argv) > 1:
        # For simple testing - assumes first param is primary argument
        result = {sanitized_name}(sys.argv[1])
    else:
        print("Usage: python {sanitized_name}.py <arguments>")
        print(f"\\nDocumentation:\\n{{{sanitized_name}.__doc__}}")
        sys.exit(1)

    print(json.dumps(result, indent=2))
'''

        return code

    def _build_function_params(
        self,
        properties: dict[str, Any],
        required: list[str],
    ) -> list[str]:
        """Build function parameter list from JSON schema properties.

        Args:
            properties: JSON schema properties dict
            required: List of required parameter names

        Returns:
            List of parameter strings (e.g., ["location: str", "days: int = 5"])
            Required parameters come first, then optional parameters (Python syntax requirement)
        """
        required_params = []
        optional_params = []

        for param_name, param_schema in properties.items():
            param_type = self._json_type_to_python_type(param_schema.get("type", "any"))

            if param_name in required:
                required_params.append(f"{param_name}: {param_type}")
            else:
                # Optional parameter with default
                default = self._get_default_value(param_schema)
                optional_params.append(f"{param_name}: Optional[{param_type}] = {default}")

        # Required parameters must come before optional parameters in Python
        return required_params + optional_params

    def _json_type_to_python_type(self, json_type: str) -> str:
        """Convert JSON schema type to Python type hint.

        Args:
            json_type: JSON schema type string

        Returns:
            Python type hint string
        """
        type_map = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
        }
        return type_map.get(json_type, "Any")

    def _get_default_value(self, param_schema: dict[str, Any]) -> str:
        """Get default value for optional parameter.

        Args:
            param_schema: JSON schema for the parameter

        Returns:
            String representation of default value
        """
        if "default" in param_schema:
            default = param_schema["default"]
            if isinstance(default, str):
                return f'"{default}"'
            return str(default)
        return "None"

    def _build_docstring(
        self,
        description: str,
        properties: dict[str, Any],
        required: list[str],
    ) -> str:
        """Build function docstring from schema.

        Args:
            description: Tool description
            properties: Parameter properties
            required: Required parameter names

        Returns:
            Formatted docstring (indented)
        """
        lines = [f'"""{description}']
        lines.append("")

        if properties:
            lines.append("Args:")
            for param_name, param_schema in properties.items():
                param_desc = param_schema.get("description", "")
                param_type = self._json_type_to_python_type(param_schema.get("type", "any"))
                req_marker = "" if param_name in required else ", optional"
                lines.append(f"    {param_name} ({param_type}{req_marker}): {param_desc}")
            lines.append("")

        lines.append("Returns:")
        lines.append("    Any: Tool execution result from MCP server")
        lines.append('"""')

        return indent("\n".join(lines), "    ")

    def _build_args_dict(self, properties: dict[str, Any]) -> str:
        """Build arguments dictionary for MCP call.

        Args:
            properties: Parameter properties

        Returns:
            String representation of dict construction
        """
        if not properties:
            return "{}"

        items = [f'"{name}": {name}' for name in properties.keys()]
        return "{\n        " + ",\n        ".join(items) + "\n            }"

    def generate_server_init(
        self,
        server_name: str,
        tool_names: list[str],
    ) -> str:
        """Generate __init__.py for a server module.

        Args:
            server_name: Name of the MCP server
            tool_names: List of tool names in this server (original MCP names)

        Returns:
            __init__.py file content
        """
        # Sanitize tool names for Python imports
        sanitized_names = [self.sanitize_tool_name(tool) for tool in tool_names]

        imports = [f"from .{sanitized} import {sanitized}" for sanitized in sanitized_names]
        all_list = ", ".join(f'"{sanitized}"' for sanitized in sanitized_names)

        # Build tool list showing both original and Python names
        tool_list_lines = []
        for original, sanitized in zip(tool_names, sanitized_names):
            if original != sanitized:
                tool_list_lines.append(f"- {sanitized} (MCP: {original})")
            else:
                tool_list_lines.append(f"- {sanitized}")

        code = f'''\
"""
{server_name} MCP Server Tools

Auto-generated module containing Python wrappers for all tools
from the '{server_name}' MCP server.

Available tools:
{chr(10).join(tool_list_lines)}

Usage:
    from servers.{server_name} import {sanitized_names[0] if sanitized_names else "tool_name"}
    result = {sanitized_names[0]}(...) if sanitized_names else "tool_name(...)"
"""

{chr(10).join(imports)}

__all__ = [{all_list}]
'''

        return code

    def generate_mcp_client(self) -> str:
        """Generate the hidden MCP client code.

        Returns:
            Content for .mcp/client.py that handles MCP protocol
        """
        code = '''\
"""
MCP Client for Tool Execution

This module handles MCP protocol communication for tool wrappers.
It's hidden from agents - they only interact with tool wrappers in servers/.

DO NOT MODIFY THIS FILE - it's auto-generated and managed by MassGen.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Import MassGen's MCP client infrastructure
try:
    from massgen.mcp_tools.client import MCPClient
    from massgen.logger_config import logger
    MCP_AVAILABLE = True
except ImportError:
    # Fallback for standalone usage
    print("Warning: MassGen MCP client not available", file=sys.stderr)
    MCPClient = None
    MCP_AVAILABLE = False

    class _FakeLogger:
        def info(self, *args, **kwargs): pass
        def warning(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
    logger = _FakeLogger()


# Load server configurations
_config_path = Path(__file__).parent / 'servers.json'
if _config_path.exists():
    with open(_config_path) as f:
        SERVERS = json.load(f)
else:
    SERVERS = {}


# Global MCP client instance (created on first use)
_mcp_client: Optional[MCPClient] = None
_client_lock = asyncio.Lock()


async def _ensure_client() -> MCPClient:
    """Ensure MCP client is connected and ready.

    Returns:
        Connected MCPClient instance

    Raises:
        RuntimeError: If MCP client unavailable or connection fails
    """
    global _mcp_client

    if not MCP_AVAILABLE:
        raise RuntimeError("MassGen MCP client not available")

    async with _client_lock:
        if _mcp_client is None:
            # Convert server configs to list format expected by MCPClient
            server_configs = [
                {
                    "name": name,
                    "type": config.get("type", "stdio"),
                    "command": config.get("command"),
                    "args": config.get("args", []),
                    "env": config.get("env", {}),
                    "url": config.get("url"),
                }
                for name, config in SERVERS.items()
            ]

            if not server_configs:
                raise RuntimeError("No MCP servers configured in servers.json")

            logger.info(f"[MCP Client] Connecting to {len(server_configs)} server(s)")

            # Create and connect MCP client
            _mcp_client = await MCPClient.create_and_connect(
                server_configs=server_configs,
                timeout_seconds=30
            )

            logger.info(f"[MCP Client] Connected successfully, {len(_mcp_client.tools)} tools available")

        return _mcp_client


def call_mcp_tool(server: str, tool: str, arguments: Dict[str, Any]) -> Any:
    """Execute an MCP tool call (synchronous wrapper).

    This function manages MCP connections and handles protocol details.
    Agents never call this directly - they use the tool wrappers.

    Args:
        server: MCP server name
        tool: Tool name
        arguments: Tool arguments dict

    Returns:
        Tool execution result

    Raises:
        ValueError: If server not configured or tool not found
        RuntimeError: If MCP client unavailable or call fails
    """
    # Run async call safely (handles both sync and nested async contexts)
    from massgen.utils import run_async_safely

    return run_async_safely(call_mcp_tool_async(server, tool, arguments))


async def call_mcp_tool_async(server: str, tool: str, arguments: Dict[str, Any]) -> Any:
    """Execute an MCP tool call (async version).

    Args:
        server: MCP server name
        tool: Tool name
        arguments: Tool arguments dict

    Returns:
        Tool execution result

    Raises:
        ValueError: If server not configured or tool not found
        RuntimeError: If MCP call fails
    """
    if server not in SERVERS:
        raise ValueError(
            f"MCP server '{server}' not configured. "
            f"Available servers: {list(SERVERS.keys())}"
        )

    # Ensure client is connected
    client = await _ensure_client()

    # Build prefixed tool name (as used by MCPClient)
    prefixed_tool_name = f"mcp__{server}__{tool}"

    # Execute tool via MCP protocol
    try:
        logger.info(f"[MCP Client] Calling {server}.{tool}")
        result = await client.call_tool(prefixed_tool_name, arguments)
        return result
    except Exception as e:
        logger.error(f"[MCP Client] Error calling {server}.{tool}: {e}")
        raise RuntimeError(
            f"Error calling {server}.{tool}: {str(e)}"
        ) from e


def list_servers() -> list:
    """List all configured MCP servers."""
    return list(SERVERS.keys())


def get_server_config(server: str) -> Dict[str, Any]:
    """Get configuration for a specific server."""
    return SERVERS.get(server, {})


async def cleanup():
    """Cleanup MCP client connections."""
    global _mcp_client
    if _mcp_client is not None:
        await _mcp_client.cleanup()
        _mcp_client = None
'''

        return code

    def generate_tools_init(self, servers: list[str]) -> str:
        """Generate __init__.py for the tools/ directory.

        Args:
            servers: List of server names

        Returns:
            Content for servers/__init__.py
        """
        code = f'''\
"""
MCP Server Tools

Auto-generated Python wrappers for MCP tools.

Available servers:
{chr(10).join(f"- {server}" for server in servers)}

Usage:
    # Import tools from servers
    from servers.weather import get_weather
    from servers.github import create_issue

    # Use the tools
    weather = get_weather("London")

Discover tools via filesystem:
    ls servers/                          # List available servers
    ls servers/weather/                  # List tools in a server
    cat servers/weather/get_weather.py   # Read tool docstring and code
"""

# This file makes servers/ a Python package.
# Agents discover tools using filesystem commands: ls, cat, grep
'''

        return code
