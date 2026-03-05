"""Tests for background tool lifecycle in custom_tools_server."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

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
        final = await manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::paris" in final["result"]
    assert final["tool_success"] is True


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
        final = await manager.get_result(job_id)
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
        final = await manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert final["tool_type"] == "mcp"
    assert "hello" in final["result"]
    assert "tool_success" not in final


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
        final = await manager.get_result(job_id)
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
async def test_registered_mcp_tool_with_native_background_param_runs_foreground_not_wrapped():
    """When a tool defines background itself, do not auto-wrap as framework background job."""

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

    class _FakeToolManager:
        def __init__(self):
            self.calls: list[dict[str, Any]] = []

        async def execute_tool(self, tool_request, execution_context):  # noqa: ARG002
            self.calls.append(tool_request)

            class _Result:
                @staticmethod
                def model_dump():
                    return {"success": True, "operation": "spawn_subagents"}

            yield _Result()

    manager = _RecordingBackgroundManager()
    fake_tool_manager = _FakeToolManager()
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
        tool_manager=fake_tool_manager,
        execution_context={"agent_id": "agent_x"},
        background_manager=manager,
    )

    handler = None
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "mcp__subagent_agent_a__spawn_subagents":
            handler = tool.fn
            break
    assert handler is not None

    result = json.loads(
        await handler(
            tasks=[{"task": "test task"}],
            background=True,
        ),
    )

    assert result["success"] is True
    assert manager.calls == []
    assert fake_tool_manager.calls
    assert fake_tool_manager.calls[0]["name"] == "mcp__subagent_agent_a__spawn_subagents"
    assert fake_tool_manager.calls[0]["input"]["background"] is True


@pytest.mark.asyncio
async def test_background_tool_manager_start_subagent_target_routes_to_direct_background_spawn(
    monkeypatch,
):
    """start_background_tool should treat subagent spawn targets like direct spawn_subagents(background=true)."""
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
    )

    captured: dict[str, Any] = {}

    class _FakeMCPClient:
        async def call_tool(self, name, arguments):
            captured["tool_name"] = name
            captured["arguments"] = dict(arguments)
            payload = {
                "success": True,
                "operation": "spawn_subagents",
                "mode": "background",
                "subagents": [
                    {
                        "subagent_id": "jazz_researcher",
                        "status": "running",
                    },
                ],
            }
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            )

    async def fake_get_client():
        return _FakeMCPClient()

    monkeypatch.setattr(manager, "_get_mcp_client", fake_get_client)

    started = await manager.start(
        tool_name="mcp__subagent_agent_x__spawn_subagents",
        arguments={
            "tasks": [{"task": "Research jazz history"}],
            "background": False,
        },
    )

    assert started["success"] is True
    assert started["operation"] == "spawn_subagents"
    assert started["mode"] == "background"
    assert started["job_id"] == "jazz_researcher"
    assert started["subagent_id"] == "jazz_researcher"
    assert started["job_ids"] == ["jazz_researcher"]
    assert started["subagents"][0]["job_id"] == "jazz_researcher"
    assert captured["tool_name"] == "mcp__subagent_agent_x__spawn_subagents"
    assert captured["arguments"]["background"] is True


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
    assert waited["tool_success"] is True

    timed_out = await manager.wait_for_next_completion(timeout_seconds=0.02)
    assert timed_out["success"] is True
    assert timed_out["ready"] is False
    assert timed_out["timed_out"] is True


@pytest.mark.asyncio
async def test_background_tool_manager_wait_returns_interrupt_payload_from_signal_file(
    tmp_path,
):
    """Wait API should exit early when an interrupt signal file is written."""
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
        wait_interrupt_file=tmp_path / "wait_interrupt.json",
    )

    async def _write_interrupt_signal() -> None:
        await asyncio.sleep(0.05)
        (tmp_path / "wait_interrupt.json").write_text(
            json.dumps(
                {
                    "interrupt_reason": "runtime_injection_available",
                    "injected_content": "[Human Input]: Please tighten acceptance criteria.",
                },
            ),
            encoding="utf-8",
        )

    asyncio.create_task(_write_interrupt_signal())
    waited = await manager.wait_for_next_completion(timeout_seconds=1.0)

    assert waited["success"] is True
    assert waited["ready"] is False
    assert waited["interrupted"] is True
    assert waited["interrupt_reason"] == "runtime_injection_available"
    assert "acceptance criteria" in waited["injected_content"]


@pytest.mark.asyncio
async def test_background_tool_manager_wait_returns_delegate_subagent_completion(monkeypatch):
    """wait_for_next_completion should return completed subagent delegate jobs immediately."""
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
    )

    class _FakeMCPClient:
        def __init__(self):
            self.tools = {
                "mcp__subagent_agent_x__list_subagents": SimpleNamespace(inputSchema={"type": "object"}),
            }

        async def call_tool(self, name, arguments):
            assert name == "mcp__subagent_agent_x__list_subagents"
            assert arguments == {}
            payload = {
                "success": True,
                "operation": "list_subagents",
                "subagents": [
                    {
                        "subagent_id": "eval_agent1",
                        "status": "completed",
                        "created_at": "2026-03-03T22:58:00",
                        "task": "Evaluate E1-E7",
                        "result": {
                            "status": "completed",
                            "answer": "Evaluation complete with findings.",
                        },
                    },
                ],
                "count": 1,
            }
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    async def fake_get_client():
        return _FakeMCPClient()

    monkeypatch.setattr(manager, "_get_mcp_client", fake_get_client)

    waited = await manager.wait_for_next_completion(timeout_seconds=0.2)
    assert waited["success"] is True
    assert waited["ready"] is True
    assert waited["job_id"] == "eval_agent1"
    assert waited["status"] == "completed"
    assert "Evaluation complete" in waited.get("result", "")

    # Completion should be consumed as "seen" and not re-surface on a second wait.
    second = await manager.wait_for_next_completion(timeout_seconds=0.02)
    assert second["success"] is True
    assert second["ready"] is False
    assert second["timed_out"] is True


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

    running_only = await manager.list_jobs()
    running_ids = {job["job_id"] for job in running_only["jobs"]}
    assert second["job_id"] in running_ids
    assert first["job_id"] not in running_ids

    all_jobs = await manager.list_jobs(include_all=True)
    all_ids = {job["job_id"] for job in all_jobs["jobs"]}
    assert first["job_id"] in all_ids
    assert second["job_id"] in all_ids

    await manager.shutdown()


@pytest.mark.asyncio
async def test_background_tool_manager_list_includes_subagent_delegate_jobs(monkeypatch):
    """list_background_tools should include running subagents via delegate bridge."""
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
    )

    class _FakeMCPClient:
        def __init__(self):
            self.tools = {
                "mcp__subagent_agent_x__list_subagents": SimpleNamespace(inputSchema={"type": "object"}),
            }

        async def call_tool(self, name, arguments):
            assert name == "mcp__subagent_agent_x__list_subagents"
            assert arguments == {}
            payload = {
                "success": True,
                "operation": "list_subagents",
                "subagents": [
                    {
                        "subagent_id": "jazz_research",
                        "status": "running",
                        "task": "Research jazz history",
                    },
                ],
                "count": 1,
            }
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    async def fake_get_client():
        return _FakeMCPClient()

    monkeypatch.setattr(manager, "_get_mcp_client", fake_get_client)

    listed = await manager.list_jobs(include_all=False)
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["jobs"][0]["job_id"] == "jazz_research"
    assert listed["jobs"][0]["subagent_id"] == "jazz_research"
    assert listed["jobs"][0]["tool_type"] == "subagent"


@pytest.mark.asyncio
async def test_background_tool_manager_cancel_routes_to_subagent_delegate(monkeypatch):
    """cancel_background_tool should route to cancel_subagent for subagent IDs."""
    manager = BackgroundToolManager(
        tool_manager=ToolManager(),
        execution_context={"agent_id": "agent_x"},
    )

    class _FakeMCPClient:
        def __init__(self):
            self.tools = {
                "mcp__subagent_agent_x__list_subagents": SimpleNamespace(inputSchema={"type": "object"}),
                "mcp__subagent_agent_x__cancel_subagent": SimpleNamespace(
                    inputSchema={
                        "type": "object",
                        "properties": {"subagent_id": {"type": "string"}},
                    },
                ),
            }

        async def call_tool(self, name, arguments):
            if name == "mcp__subagent_agent_x__list_subagents":
                payload = {
                    "success": True,
                    "operation": "list_subagents",
                    "subagents": [
                        {"subagent_id": "jazz_research", "status": "running"},
                    ],
                    "count": 1,
                }
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])
            if name == "mcp__subagent_agent_x__cancel_subagent":
                assert arguments == {"subagent_id": "jazz_research"}
                payload = {
                    "success": True,
                    "operation": "cancel_subagent",
                    "subagent_id": "jazz_research",
                }
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])
            raise AssertionError(f"Unexpected tool call: {name}")

    async def fake_get_client():
        return _FakeMCPClient()

    monkeypatch.setattr(manager, "_get_mcp_client", fake_get_client)

    cancelled = await manager.cancel("jazz_research")
    assert cancelled["success"] is True
    assert cancelled["operation"] == "cancel_subagent"
    assert cancelled["subagent_id"] == "jazz_research"
    assert cancelled["job_id"] == "jazz_research"


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
    assert (await manager.list_jobs(include_all=True))["count"] == 0


@pytest.mark.asyncio
async def test_background_tool_manager_media_background_run_writes_ledger(tmp_path):
    """Codex custom-tools server path should append read_media calls to media ledger."""
    tool_manager = ToolManager()

    async def custom_tool__read_media(prompt: str = "", inputs: list[dict[str, Any]] | None = None) -> ExecutionResult:
        _ = prompt, inputs
        return ExecutionResult(
            output_blocks=[
                TextContent(
                    data=json.dumps(
                        {
                            "success": True,
                            "operation": "read_media",
                            "response": "Looks solid.",
                        },
                    ),
                ),
            ],
        )

    tool_manager.add_tool_function(func=custom_tool__read_media)
    (tmp_path / "CONTEXT.md").write_text("# Task\nCompare screenshots", encoding="utf-8")

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
        arguments={
            "prompt": "Compare the layout hierarchy",
            "inputs": [{"files": {"hero": ".massgen_scratch/verification/hero.png"}}],
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["status"] == "completed"

    ledger_path = tmp_path / ".massgen_scratch" / "verification" / "media_call_ledger.json"
    assert ledger_path.exists()
    ledger_payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    last_entry = ledger_payload["entries"][-1]
    assert last_entry["tool"] == "read_media"
    assert last_entry["tool_arguments"]["inputs"][0]["files"]["hero"] == ".massgen_scratch/verification/hero.png"
    assert "tool_arguments_raw" not in last_entry
    assert any("input[0].hero ->" in mapping for mapping in last_entry["file_mappings"])
    assert ".massgen_scratch/verification/context_snapshots/" in str(
        last_entry["context_snapshot_path"],
    )

    await manager.shutdown()


@pytest.mark.asyncio
async def test_background_tool_manager_custom_result_surfaces_inner_failure_payload():
    """Terminal custom payload should expose inner tool-level failure explicitly."""
    tool_manager = ToolManager()

    async def custom_tool__returns_failure() -> ExecutionResult:
        return ExecutionResult(
            output_blocks=[
                TextContent(
                    data=json.dumps(
                        {
                            "success": False,
                            "operation": "read_media",
                            "error": "inputs[0] missing required 'files' key",
                        },
                    ),
                ),
            ],
        )

    tool_manager.add_tool_function(func=custom_tool__returns_failure)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    started = await manager.start(
        tool_name="custom_tool__returns_failure",
        arguments={},
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert final["tool_success"] is False
    assert "missing required 'files' key" in final["tool_error"]


@pytest.mark.asyncio
async def test_background_tool_manager_custom_tool_without_output_is_error():
    """A custom tool that yields no final output should fail explicitly."""
    tool_manager = ToolManager()

    async def custom_tool__silent():
        if False:
            yield ExecutionResult(
                output_blocks=[TextContent(data="never")],
            )

    tool_manager.add_tool_function(func=custom_tool__silent)
    manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context={"agent_id": "agent_x"},
    )

    started = await manager.start(
        tool_name="custom_tool__silent",
        arguments={},
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await manager.get_result(job_id)
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "error"
    assert "no final result" in final["error"].lower()
    assert final["tool_success"] is False
