"""Standalone MCP server that exposes MassGen workflow tools as real MCP tools.

This allows CLI-based backends (Codex, Claude Code) to use workflow tools
(vote, new_answer, submit, restart_orchestration, ask_others) as native
MCP tool calls instead of text-based JSON parsing.

The server is stateless — tool handlers return structured JSON results that the
backend interprets and maps to StreamChunk(type="tool_calls") for the orchestrator.
No IPC or callback mechanism is needed.

Usage (launched by backend):
    fastmcp run massgen/mcp_tools/workflow_tools_server.py:create_server -- \
        --tool-specs /path/to/workflow_specs.json

The workflow_specs.json contains the tool definitions (schemas with valid agent
IDs, available tools for the current phase, etc.) written by the backend before
launch.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import fastmcp

logger = logging.getLogger(__name__)

# Server name used by backends to identify workflow tool calls in MCP results
SERVER_NAME = "massgen_workflow_tools"


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from workflow tool specs.

    Reads tool specifications from a JSON file (passed via --tool-specs)
    and registers each workflow tool as an MCP tool.
    """
    parser = argparse.ArgumentParser(description="MassGen Workflow Tools MCP Server")
    parser.add_argument(
        "--tool-specs",
        type=str,
        required=True,
        help="Path to JSON file containing workflow tool specifications",
    )
    args = parser.parse_args()

    mcp = fastmcp.FastMCP(SERVER_NAME)

    # Load tool specs
    specs_path = Path(args.tool_specs)
    if not specs_path.exists():
        logger.error(f"Workflow tool specs file not found: {specs_path}")
        return mcp

    with open(specs_path) as f:
        tool_specs = json.load(f)

    # Register each workflow tool
    tools = tool_specs.get("tools", [])
    for tool_def in tools:
        _register_workflow_tool(mcp, tool_def)

    logger.info(f"Workflow tools MCP server ready with {len(tools)} tools")
    return mcp


def _register_workflow_tool(
    mcp: fastmcp.FastMCP,
    tool_def: dict[str, Any],
) -> None:
    """Register a single workflow tool as an MCP tool on the server.

    The handler simply returns the tool name and arguments as structured JSON.
    The backend detects results from this server and maps them to
    StreamChunk(type="tool_calls") for the orchestrator.
    """
    import inspect

    # Extract tool info from chat_completions format
    func_info = tool_def.get("function", tool_def)
    tool_name = func_info.get("name", "")
    tool_desc = func_info.get("description", "")
    tool_params = func_info.get("parameters", func_info.get("input_schema", {}))

    if not tool_name:
        return

    # Build parameter list from schema properties
    properties = tool_params.get("properties", {})
    required = set(tool_params.get("required", []))

    params = []
    for param_name, param_info in properties.items():
        if param_name in required:
            params.append(
                inspect.Parameter(param_name, inspect.Parameter.POSITIONAL_OR_KEYWORD),
            )
        else:
            params.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=None,
                ),
            )

    # Create handler that returns structured passthrough result
    async def _handler(**kwargs) -> str:
        # Filter out None defaults for optional params not provided
        filtered_args = {k: v for k, v in kwargs.items() if v is not None}
        result = {
            "status": "ok",
            "server": SERVER_NAME,
            "tool_name": tool_name,
            "arguments": filtered_args,
        }
        return json.dumps(result)

    # Apply correct signature so FastMCP sees named params
    sig = inspect.Signature(params)
    _handler.__signature__ = sig
    _handler.__name__ = tool_name
    _handler.__doc__ = tool_desc

    mcp.tool(name=tool_name, description=tool_desc)(_handler)
    logger.info(f"Registered workflow MCP tool: {tool_name}")


def write_workflow_specs(
    tools: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Write workflow tool specifications to a JSON file for the server to load.

    Called by the backend before launching the MCP server process.

    Args:
        tools: List of workflow tool definitions (chat_completions format).
        output_path: Path to write the specs file.

    Returns:
        Path to the written specs file.
    """
    specs = {"tools": tools}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(specs, f, indent=2)
    return output_path


def build_server_config(
    tool_specs_path: Path,
    tool_timeout_sec: int = 120,
) -> dict[str, Any]:
    """Build an MCP server config dict for use in .codex/config.toml or mcp_servers list.

    Args:
        tool_specs_path: Path to the workflow tool specs JSON file.
        tool_timeout_sec: Timeout in seconds for tool execution (default 120).

    Returns:
        MCP server configuration dict (stdio type).
    """
    # Use absolute file path - works in Docker because massgen is bind-mounted at same host path
    script_path = Path(__file__).resolve()

    return {
        "name": SERVER_NAME,
        "type": "stdio",
        "command": "fastmcp",
        "args": [
            "run",
            f"{script_path}:create_server",
            "--",
            "--tool-specs",
            str(tool_specs_path),
        ],
        "env": {"FASTMCP_SHOW_CLI_BANNER": "false"},
        "tool_timeout_sec": tool_timeout_sec,
    }


def is_workflow_tool_result(mcp_result: dict[str, Any]) -> bool:
    """Check if an MCP tool result is from the workflow tools server.

    Args:
        mcp_result: Parsed MCP tool result dict.

    Returns:
        True if the result is from the workflow tools server.
    """
    return isinstance(mcp_result, dict) and mcp_result.get("server") == SERVER_NAME and mcp_result.get("status") == "ok"


def extract_workflow_tool_call(mcp_result: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a standard workflow tool call from an MCP result.

    Converts the MCP passthrough result into the format expected by the
    orchestrator::

        {"id": "call_...", "type": "function",
         "function": {"name": "vote", "arguments": {...}}}

    Args:
        mcp_result: Parsed MCP tool result from the workflow server.

    Returns:
        Tool call dict in orchestrator format, or None if not a workflow result.
    """
    if not is_workflow_tool_result(mcp_result):
        return None

    import uuid

    tool_name = mcp_result.get("tool_name", "")
    arguments = mcp_result.get("arguments", {})

    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": tool_name, "arguments": arguments},
    }
