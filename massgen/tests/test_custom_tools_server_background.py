# -*- coding: utf-8 -*-
"""Tests for background tool lifecycle in custom_tools_server."""

import asyncio
import json
from types import SimpleNamespace

import fastmcp
import pytest

from massgen.mcp_tools.custom_tools_server import (
    BackgroundToolManager,
    _register_mcp_tool,
    _should_auto_background_execution,
)
from massgen.tool import ToolManager
from massgen.tool._result import ExecutionResult, TextContent


@pytest.mark.asyncio
async def test_background_tool_manager_custom_tool_lifecycle():
    tool_manager = ToolManager()

    async def custom_tool__async_weather_fetcher(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"weather::{city}")],
        )

    tool_manager.add_tool_function(func=custom_tool__async_weather_fetcher)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    started = await manager.start(
        tool_name="custom_tool__async_weather_fetcher",
        arguments={"city": "paris"},
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::paris" in final["result"]


@pytest.mark.asyncio
async def test_background_tool_manager_accepts_double_encoded_arguments():
    """Background manager should normalize double-encoded JSON argument payloads."""
    tool_manager = ToolManager()

    async def custom_tool__async_weather_fetcher(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"weather::{city}")],
        )

    tool_manager.add_tool_function(func=custom_tool__async_weather_fetcher)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    started = await manager.start(
        tool_name="custom_tool__async_weather_fetcher",
        arguments=json.dumps(json.dumps({"city": "paris"})),
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::paris" in final["result"]

    await manager.shutdown()


@pytest.mark.asyncio
async def test_background_tool_manager_mcp_tool_lifecycle(monkeypatch):
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={},
        mcp_servers=[
            {
                "name": "command_line",
                "type": "stdio",
                "command": "fastmcp",
                "args": ["run", "massgen/filesystem_manager/_code_execution_server.py:create_server"],
            },
        ],
    )

    class FakeMCPClient:
        async def call_tool(self, name, arguments):
            assert name == "mcp__command_line__execute_command"
            assert arguments == {"command": "echo hello"}
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="hello")])

    async def fake_get_client():
        return FakeMCPClient()

    monkeypatch.setattr(manager, "_get_mcp_client", fake_get_client)

    started = await manager.start(
        tool_name="mcp__command_line__execute_command",
        arguments={"command": "echo hello"},
    )
    assert started["success"] is True
    assert started["tool_type"] == "mcp"
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert final["tool_type"] == "mcp"
    assert "hello" in final["result"]


@pytest.mark.asyncio
async def test_registered_custom_tool_mode_background_auto_starts_job():
    """Regular custom-tool handlers should support mode=background auto-dispatch."""
    tool_manager = ToolManager()

    async def custom_tool__slow_echo(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"echo::{city}")],
        )

    tool_manager.add_tool_function(func=custom_tool__slow_echo)
    schema = tool_manager.fetch_tool_schemas()[0]["function"]

    execution_context = {"agent_id": "agent_x"}
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context=execution_context,
    )

    mcp = fastmcp.FastMCP("test_custom_tools")
    _register_mcp_tool(
        mcp=mcp,
        tool_name=schema["name"],
        tool_desc=schema.get("description", ""),
        tool_params=schema["parameters"],
        tool_manager=tool_manager,
        execution_context=execution_context,
        background_manager=manager,
    )

    handler = None
    for tool in mcp._tool_manager._tools.values():
        if tool.name == schema["name"]:
            handler = tool.fn
            break
    assert handler is not None

    started = json.loads(await handler(city="rome", mode="background"))
    assert started["success"] is True
    assert started["status"] == "running"
    assert started["tool_name"] == "custom_tool__slow_echo"
    job_id = started.get("job_id")
    assert job_id

    final = None
    for _ in range(40):
        final = manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "echo::rome" in final["result"]

    await manager.shutdown()


@pytest.mark.asyncio
async def test_registered_mcp_tool_preserves_real_background_param_for_auto_background():
    """When a tool defines background itself, wrapper must pass it through."""

    class _RecordingBackgroundManager:
        def __init__(self):
            self.calls = []

        async def start(self, tool_name: str, arguments: dict):
            self.calls.append({"tool_name": tool_name, "arguments": arguments})
            return {
                "success": True,
                "status": "running",
                "job_id": "bgtool_test123",
                "tool_name": tool_name,
            }

    manager = _RecordingBackgroundManager()
    mcp = fastmcp.FastMCP("test_mcp_tools")

    _register_mcp_tool(
        mcp=mcp,
        tool_name="mcp__subagent_agent_a__spawn_subagents",
        tool_desc="spawn subagents",
        tool_params={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "background": {"type": "boolean"},
            },
            "required": ["tasks"],
        },
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
        background_manager=manager,
    )

    handler = None
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "mcp__subagent_agent_a__spawn_subagents":
            handler = tool.fn
            break
    assert handler is not None

    started = json.loads(
        await handler(
            tasks=[{"task": "test task"}],
            background=True,
        ),
    )

    assert started["success"] is True
    assert manager.calls
    assert manager.calls[0]["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
    assert manager.calls[0]["arguments"]["background"] is True


@pytest.mark.asyncio
async def test_background_tool_manager_waits_for_next_completion():
    """Wait API should return the next unseen background job completion."""
    tool_manager = ToolManager()

    async def custom_tool__slow_echo(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.02)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"echo::{city}")],
        )

    tool_manager.add_tool_function(func=custom_tool__slow_echo)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    started = await manager.start(
        tool_name="custom_tool__slow_echo",
        arguments={"city": "oslo"},
    )
    assert started["success"] is True

    waited = await manager.wait_for_next_completion(timeout_seconds=1.0)
    assert waited["success"] is True
    assert waited["ready"] is True
    assert waited["job_id"] == started["job_id"]
    assert waited["status"] == "completed"
    assert "echo::oslo" in waited["result"]

    timed_out = await manager.wait_for_next_completion(timeout_seconds=0.02)
    assert timed_out["success"] is True
    assert timed_out["ready"] is False
    assert timed_out["timed_out"] is True


@pytest.mark.asyncio
async def test_background_tool_manager_list_defaults_to_running_only():
    """list_jobs should return running jobs by default and include_all when requested."""
    tool_manager = ToolManager()

    async def custom_tool__slow_echo(delay: float = 0.01, city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(delay)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"echo::{city}")],
        )

    tool_manager.add_tool_function(func=custom_tool__slow_echo)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    first = await manager.start(
        tool_name="custom_tool__slow_echo",
        arguments={"city": "paris", "delay": 0.01},
    )
    assert first["success"] is True
    await asyncio.sleep(0.05)

    second = await manager.start(
        tool_name="custom_tool__slow_echo",
        arguments={"city": "rome", "delay": 0.3},
    )
    assert second["success"] is True

    running_only = manager.list_jobs()
    running_ids = {job["job_id"] for job in running_only["jobs"]}
    assert second["job_id"] in running_ids
    assert first["job_id"] not in running_ids

    all_jobs = manager.list_jobs(include_all=True)
    all_ids = {job["job_id"] for job in all_jobs["jobs"]}
    assert first["job_id"] in all_ids
    assert second["job_id"] in all_ids

    await manager.shutdown()


def test_custom_tools_server_media_tools_default_to_background():
    """Server-side auto-dispatch should default media tools to background mode."""
    assert _should_auto_background_execution("custom_tool__read_media", {}) is True
    assert _should_auto_background_execution("custom_tool__generate_media", {}) is True

    assert (
        _should_auto_background_execution(
            "custom_tool__read_media",
            {"background": False},
        )
        is False
    )
    assert (
        _should_auto_background_execution(
            "custom_tool__generate_media",
            {"background": False},
        )
        is False
    )
    # Legacy async alias should not enable background dispatch anymore.
    assert (
        _should_auto_background_execution(
            "custom_tool__slow_echo",
            {"async": True},
        )
        is False
    )


@pytest.mark.asyncio
async def test_background_tool_manager_media_start_requires_context_file(tmp_path):
    """Background manager should reject media starts until CONTEXT.md exists."""
    tool_manager = ToolManager()

    async def custom_tool__read_media(file_path: str = "image.png") -> ExecutionResult:
        return ExecutionResult(
            output_blocks=[TextContent(data=f"read::{file_path}")],
        )

    tool_manager.add_tool_function(func=custom_tool__read_media)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={
            "agent_id": "agent_x",
            "agent_cwd": str(tmp_path),
            "allowed_paths": [str(tmp_path)],
        },
    )

    started = await manager.start(
        tool_name="custom_tool__read_media",
        arguments={"file_path": "image.png"},
    )

    assert started["success"] is False
    assert "CONTEXT.md" in started["error"]
    assert manager.list_jobs(include_all=True)["count"] == 0
