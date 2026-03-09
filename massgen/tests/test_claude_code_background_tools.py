"""Tests for Claude Code background tool management parity."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from massgen.backend.base_with_custom_tool_and_mcp import (
    BACKGROUND_TOOL_CANCEL_NAME,
    BACKGROUND_TOOL_LIST_NAME,
    BACKGROUND_TOOL_RESULT_NAME,
    BACKGROUND_TOOL_START_NAME,
    BACKGROUND_TOOL_STATUS_NAME,
    BACKGROUND_TOOL_WAIT_NAME,
)
from massgen.backend.claude_code import ClaudeCodeBackend
from massgen.tool import ToolManager
from massgen.tool._decorators import context_params
from massgen.tool._result import ExecutionResult, TextContent


def test_claude_code_exposes_background_management_schemas_without_custom_tools(tmp_path):
    """Background lifecycle tools should be available even without user custom tools."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    schema_names = {schema["function"]["name"] for schema in backend._get_massgen_custom_tool_schemas()}

    assert BACKGROUND_TOOL_START_NAME in schema_names
    assert BACKGROUND_TOOL_STATUS_NAME in schema_names
    assert BACKGROUND_TOOL_RESULT_NAME in schema_names
    assert BACKGROUND_TOOL_CANCEL_NAME in schema_names
    assert BACKGROUND_TOOL_LIST_NAME in schema_names
    assert BACKGROUND_TOOL_WAIT_NAME in schema_names


@pytest.mark.asyncio
async def test_claude_code_background_lifecycle_for_custom_tool(tmp_path):
    """Claude Code backend should execute custom tools via background lifecycle APIs."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__async_weather_fetcher(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"weather::{city}")],
        )

    backend._custom_tool_manager.add_tool_function(func=custom_tool__async_weather_fetcher)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__async_weather_fetcher",
            "arguments": {"city": "paris"},
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::paris" in final["result"]
    assert final["tool_success"] is True

    pending = backend.get_pending_background_tool_results()
    assert pending
    assert pending[0]["job_id"] == job_id
    assert pending[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_claude_code_background_lifecycle_for_mcp_tool(tmp_path, monkeypatch):
    """Claude Code backend should support MCP targets via background lifecycle APIs."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    class FakeMCPClient:
        async def call_tool(self, name, arguments):
            assert name == "mcp__command_line__execute_command"
            assert arguments == {"command": "echo hello"}
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="hello"),
                ],
            )

    async def fake_get_client():
        return FakeMCPClient()

    monkeypatch.setattr(backend, "_get_background_mcp_client", fake_get_client)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "mcp__command_line__execute_command",
            "arguments": {"command": "echo hello"},
        },
    )
    assert started["success"] is True
    assert started["tool_type"] == "mcp"
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
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
async def test_claude_code_custom_tool_background_flag_auto_background(tmp_path):
    """Custom tool calls with background=true should auto-start a background job."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__slow_echo(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(output_blocks=[TextContent(data=f"echo::{city}")])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__slow_echo)

    response = await backend._execute_massgen_custom_tool(
        "custom_tool__slow_echo",
        {"city": "rome", "background": True},
    )

    payload = json.loads(response["content"][0]["text"])
    assert payload["success"] is True
    assert payload["status"] == "background"
    assert payload["tool_name"] == "custom_tool__slow_echo"
    assert payload.get("job_id")

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": payload["job_id"]},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "echo::rome" in final["result"]


@pytest.mark.asyncio
async def test_claude_code_does_not_auto_background_mcp_tools_with_native_background_param(
    tmp_path,
):
    """MCP tools that define background should not be wrapped as framework background jobs."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._mcp_client = SimpleNamespace(
        tools={
            "mcp__subagent_agent_a__spawn_subagents": SimpleNamespace(
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array", "items": {"type": "object"}},
                        "background": {"type": "boolean"},
                    },
                },
            ),
        },
    )

    assert (
        backend._should_auto_background_execution(
            "mcp__subagent_agent_a__spawn_subagents",
            {
                "tasks": [{"task": "test task"}],
                "background": True,
            },
        )
        is False
    )

    # Strip logic should still preserve the real background argument.
    stripped = backend._strip_background_control_args(
        {
            "tasks": [{"task": "test task"}],
            "background": True,
        },
        tool_name="mcp__subagent_agent_a__spawn_subagents",
    )
    assert stripped["background"] is True
    assert stripped["tasks"] == [{"task": "test task"}]


def test_claude_code_media_tools_default_to_background(tmp_path):
    """Claude Code policy should default media tools to background mode."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    assert backend._should_auto_background_execution("custom_tool__read_media", {}) is True
    assert backend._should_auto_background_execution("custom_tool__generate_media", {}) is True

    # Explicit opt-out for immediate blocking result.
    assert (
        backend._should_auto_background_execution(
            "custom_tool__read_media",
            {"background": False},
        )
        is False
    )
    assert (
        backend._should_auto_background_execution(
            "custom_tool__generate_media",
            {"background": False},
        )
        is False
    )
    assert (
        backend._should_auto_background_execution(
            "custom_tool__slow_echo",
            {"async": True},
        )
        is False
    )


@pytest.mark.asyncio
async def test_claude_code_background_media_job_executes_tool_in_foreground_once(tmp_path):
    """Background-managed media tools should not recursively schedule nested background jobs."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()
    (tmp_path / "CONTEXT.md").write_text("Generate goat images.", encoding="utf-8")

    calls = []

    async def custom_tool__generate_media(prompt: str = "", mode: str = "image") -> ExecutionResult:
        calls.append({"prompt": prompt, "mode": mode})
        return ExecutionResult(
            output_blocks=[TextContent(data=f"media::{prompt}::{mode}")],
        )

    backend._custom_tool_manager.add_tool_function(func=custom_tool__generate_media)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__generate_media",
            "arguments": {"prompt": "goat", "mode": "image"},
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "media::goat::image" in final["result"]
    assert calls == [{"prompt": "goat", "mode": "image"}]


@pytest.mark.asyncio
async def test_claude_code_custom_tool_execution_injects_multimodal_context(tmp_path):
    """Claude Code custom tools should receive backend/model/task context even without prior stream state."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path), model="claude-sonnet-4-6")
    backend._custom_tool_manager = ToolManager()
    (tmp_path / "CONTEXT.md").write_text("Review the current UI output.", encoding="utf-8")

    @context_params("backend_type", "model", "agent_cwd", "task_context")
    async def custom_tool__capture_context(
        backend_type: str | None = None,
        model: str | None = None,
        agent_cwd: str | None = None,
        task_context: str | None = None,
    ) -> ExecutionResult:
        payload = json.dumps(
            {
                "backend_type": backend_type,
                "model": model,
                "agent_cwd": agent_cwd,
                "task_context": task_context,
            },
        )
        return ExecutionResult(output_blocks=[TextContent(data=payload)])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__capture_context)

    response = await backend._execute_massgen_custom_tool(
        "custom_tool__capture_context",
        {},
    )

    payload = json.loads(response["content"][0]["text"])
    assert payload["backend_type"] == "claude_code"
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["agent_cwd"] == str(tmp_path)
    assert payload["task_context"] == "Review the current UI output."


@pytest.mark.asyncio
async def test_claude_code_background_custom_tool_injects_multimodal_context(tmp_path):
    """Background-managed Claude Code tools should preserve multimodal context injection."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path), model="claude-sonnet-4-6")
    backend._custom_tool_manager = ToolManager()
    (tmp_path / "CONTEXT.md").write_text("Review the current UI output.", encoding="utf-8")

    @context_params("backend_type", "model", "agent_cwd", "task_context")
    async def custom_tool__capture_context(
        backend_type: str | None = None,
        model: str | None = None,
        agent_cwd: str | None = None,
        task_context: str | None = None,
    ) -> ExecutionResult:
        payload = json.dumps(
            {
                "backend_type": backend_type,
                "model": model,
                "agent_cwd": agent_cwd,
                "task_context": task_context,
            },
        )
        return ExecutionResult(output_blocks=[TextContent(data=payload)])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__capture_context)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__capture_context",
            "arguments": {},
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    payload = json.loads(final["result"])
    assert payload["backend_type"] == "claude_code"
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["agent_cwd"] == str(tmp_path)
    assert payload["task_context"] == "Review the current UI output."


@pytest.mark.asyncio
async def test_claude_code_wait_for_next_background_tool(tmp_path):
    """Wait lifecycle API should block until the next background job completes."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__slow_echo(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.02)
        return ExecutionResult(output_blocks=[TextContent(data=f"echo::{city}")])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__slow_echo)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__slow_echo",
            "arguments": {"city": "berlin"},
        },
    )
    assert started["success"] is True

    waited = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_WAIT_NAME,
        {"timeout_seconds": 1.0},
    )
    assert waited["success"] is True
    assert waited["ready"] is True
    assert waited["job_id"] == started["job_id"]
    assert waited["status"] == "completed"
    assert "echo::berlin" in waited["result"]
    assert waited["tool_success"] is True


@pytest.mark.asyncio
async def test_claude_code_wait_consumes_shared_completion_queue(tmp_path):
    """wait_for_background_tool should consume the same queue used by hook injection."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__slow_echo(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.02)
        return ExecutionResult(output_blocks=[TextContent(data=f"echo::{city}")])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__slow_echo)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__slow_echo",
            "arguments": {"city": "berlin"},
        },
    )
    assert started["success"] is True

    waited = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_WAIT_NAME,
        {"timeout_seconds": 1.0},
    )
    assert waited["success"] is True
    assert waited["ready"] is True
    assert waited["job_id"] == started["job_id"]

    pending = backend.get_pending_background_tool_results()
    pending_ids = {job.get("job_id") for job in pending}
    assert started["job_id"] not in pending_ids


@pytest.mark.asyncio
async def test_claude_code_wait_returns_interrupt_payload_when_runtime_input_available(
    tmp_path,
):
    """wait_for_background_tool should return early when runtime injection content is available."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    async def interrupt_provider(agent_id: str):
        assert agent_id
        return {
            "interrupt_reason": "runtime_injection_available",
            "injected_content": "[Human Input]: Please continue with stricter validation.",
        }

    backend.set_background_wait_interrupt_provider(interrupt_provider)

    waited = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_WAIT_NAME,
        {"timeout_seconds": 1.0},
    )
    assert waited["success"] is True
    assert waited["ready"] is False
    assert waited["interrupted"] is True
    assert waited["interrupt_reason"] == "runtime_injection_available"
    assert "stricter validation" in waited["injected_content"]


@pytest.mark.asyncio
async def test_claude_code_media_background_start_requires_context_file(tmp_path):
    """Claude Code should reject background media start when CONTEXT.md is missing."""
    backend = ClaudeCodeBackend(
        cwd=str(tmp_path),
        enable_multimodal_tools=True,
    )

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__read_media",
            "arguments": {"file_path": "image.png"},
        },
    )

    assert started["success"] is False
    assert "CONTEXT.md" in started["error"]


@pytest.mark.asyncio
async def test_claude_code_list_background_tools_defaults_to_running_only(tmp_path):
    """Claude Code list lifecycle should default to running jobs and allow include_all."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__slow_echo(delay: float = 0.01, city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(delay)
        return ExecutionResult(output_blocks=[TextContent(data=f"echo::{city}")])

    backend._custom_tool_manager.add_tool_function(func=custom_tool__slow_echo)

    first = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__slow_echo",
            "arguments": {"city": "berlin", "delay": 0.01},
        },
    )
    assert first["success"] is True
    await asyncio.sleep(0.05)

    second = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__slow_echo",
            "arguments": {"city": "rome", "delay": 0.3},
        },
    )
    assert second["success"] is True

    running_only = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_LIST_NAME,
        {},
    )
    running_ids = {job["job_id"] for job in running_only["jobs"]}
    assert second["job_id"] in running_ids
    assert first["job_id"] not in running_ids

    all_jobs = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_LIST_NAME,
        {"include_all": True},
    )
    all_ids = {job["job_id"] for job in all_jobs["jobs"]}
    assert first["job_id"] in all_ids
    assert second["job_id"] in all_ids


@pytest.mark.asyncio
async def test_claude_code_list_background_tools_includes_delegate_jobs(tmp_path):
    """Delegate-managed jobs (for example subagents) should be merged into list results."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    class _Delegate:
        async def list_jobs(self, include_all: bool):  # noqa: ARG002
            return [
                {
                    "job_id": "jazz_research",
                    "tool_name": "subagent",
                    "tool_type": "subagent",
                    "status": "running",
                    "created_at": "2026-02-22T00:00:00",
                },
            ]

        async def owns(self, job_id: str):  # noqa: ARG002
            return False

    backend.register_background_delegate(_Delegate())

    listed = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_LIST_NAME,
        {},
    )

    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["jobs"][0]["job_id"] == "jazz_research"
    assert listed["jobs"][0]["tool_type"] == "subagent"


@pytest.mark.asyncio
async def test_claude_code_cancel_background_tool_routes_to_delegate(tmp_path):
    """cancel_background_tool should route to delegate-owned IDs when native job is absent."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    class _Delegate:
        async def owns(self, job_id: str):
            return job_id == "jazz_research"

        async def cancel(self, job_id: str):
            return {
                "success": True,
                "operation": "cancel_subagent",
                "subagent_id": job_id,
            }

        async def list_jobs(self, include_all: bool):  # noqa: ARG002
            return []

    backend.register_background_delegate(_Delegate())

    cancelled = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_CANCEL_NAME,
        {"job_id": "jazz_research"},
    )

    assert cancelled["success"] is True
    assert cancelled["operation"] == "cancel_subagent"
    assert cancelled["subagent_id"] == "jazz_research"


@pytest.mark.asyncio
async def test_claude_code_start_background_tool_accepts_top_level_target_args(tmp_path):
    """Claude Code start_background_tool should accept flattened target args."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__async_weather_fetcher(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"weather::{city}")],
        )

    backend._custom_tool_manager.add_tool_function(func=custom_tool__async_weather_fetcher)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__async_weather_fetcher",
            "city": "tokyo",
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::tokyo" in final["result"]


@pytest.mark.asyncio
async def test_claude_code_start_background_tool_accepts_double_encoded_arguments(tmp_path):
    """Claude Code background start should normalize double-encoded argument payloads."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    backend._custom_tool_manager = ToolManager()

    async def custom_tool__async_weather_fetcher(city: str = "sf") -> ExecutionResult:
        await asyncio.sleep(0.01)
        return ExecutionResult(
            output_blocks=[TextContent(data=f"weather::{city}")],
        )

    backend._custom_tool_manager.add_tool_function(func=custom_tool__async_weather_fetcher)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "custom_tool__async_weather_fetcher",
            "arguments": json.dumps(json.dumps({"city": "tokyo"})),
        },
    )
    assert started["success"] is True
    job_id = started["job_id"]

    final = None
    for _ in range(40):
        final = await backend._execute_background_management_tool(
            BACKGROUND_TOOL_RESULT_NAME,
            {"job_id": job_id},
        )
        if final["ready"]:
            break
        await asyncio.sleep(0.01)

    assert final is not None
    assert final["success"] is True
    assert final["ready"] is True
    assert final["status"] == "completed"
    assert "weather::tokyo" in final["result"]


@pytest.mark.asyncio
async def test_claude_code_start_background_tool_subagent_target_routes_to_direct_background_spawn(
    tmp_path,
    monkeypatch,
):
    """Subagent targets through start_background_tool should behave like direct spawn_subagents(background=true)."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    captured: dict[str, object] = {}

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
                content=[
                    SimpleNamespace(type="text", text=json.dumps(payload)),
                ],
            )

    async def fake_get_background_mcp_client():
        return _FakeMCPClient()

    async def fail_start_background_job(*, tool_name, arguments, source_call_id=None):  # noqa: ARG001
        raise AssertionError(
            f"framework background wrapper should be bypassed for subagent target: {tool_name}",
        )

    monkeypatch.setattr(backend, "_get_background_mcp_client", fake_get_background_mcp_client)
    monkeypatch.setattr(backend, "_start_background_tool_job", fail_start_background_job)

    started = await backend._execute_background_management_tool(
        BACKGROUND_TOOL_START_NAME,
        {
            "tool_name": "mcp__subagent_agent_a__spawn_subagents",
            "arguments": {
                "tasks": [{"task": "Research jazz history"}],
                "background": False,
            },
        },
    )

    assert started["success"] is True
    assert started["operation"] == "spawn_subagents"
    assert started["mode"] == "background"
    assert started["job_id"] == "jazz_researcher"
    assert started["subagent_id"] == "jazz_researcher"
    assert started["job_ids"] == ["jazz_researcher"]
    assert started["subagents"][0]["job_id"] == "jazz_researcher"
    assert captured["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
    assert isinstance(captured["arguments"], dict)
    assert captured["arguments"]["background"] is True


@pytest.mark.asyncio
async def test_background_mcp_client_timeout_derived_from_server_configs(tmp_path, monkeypatch):
    """Background MCP client timeout should derive from tool_timeout_sec in server configs, not be hardcoded."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    # Simulate subagent MCP server configs with a custom tool_timeout_sec
    # (e.g. subagent_default_timeout=2000 + 60 = 2060)
    backend.config["mcp_servers"] = [
        {
            "name": "subagent_agent_a",
            "type": "stdio",
            "command": "fastmcp",
            "args": ["run", "server.py"],
            "tool_timeout_sec": 2060,
        },
        {
            "name": "command_line",
            "type": "stdio",
            "command": "fastmcp",
            "args": ["run", "cmd.py"],
            "tool_timeout_sec": 120,
        },
    ]

    captured_timeout = {}

    async def capture_setup_mcp_client(*, servers, timeout_seconds, **kwargs):
        captured_timeout["timeout_seconds"] = timeout_seconds
        # Return None to short-circuit (we only care about the timeout value passed)
        raise RuntimeError("intercepted")

    from massgen.mcp_tools import backend_utils

    monkeypatch.setattr(backend_utils.MCPResourceManager, "setup_mcp_client", staticmethod(capture_setup_mcp_client))

    # Should fail because we raise RuntimeError, but the timeout should have been captured
    result = await backend._get_background_mcp_client()
    assert result is None  # Failed init returns None

    # The timeout should be at least the max tool_timeout_sec from server configs
    assert "timeout_seconds" in captured_timeout
    assert captured_timeout["timeout_seconds"] >= 2060


@pytest.mark.asyncio
async def test_background_mcp_client_timeout_fallback_when_no_tool_timeout_sec(tmp_path, monkeypatch):
    """When server configs lack tool_timeout_sec, should use a sensible default."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    backend.config["mcp_servers"] = [
        {
            "name": "command_line",
            "type": "stdio",
            "command": "fastmcp",
            "args": ["run", "cmd.py"],
            # No tool_timeout_sec
        },
    ]

    captured_timeout = {}

    async def capture_setup_mcp_client(*, servers, timeout_seconds, **kwargs):
        captured_timeout["timeout_seconds"] = timeout_seconds
        raise RuntimeError("intercepted")

    from massgen.mcp_tools import backend_utils

    monkeypatch.setattr(backend_utils.MCPResourceManager, "setup_mcp_client", staticmethod(capture_setup_mcp_client))

    await backend._get_background_mcp_client()

    # Should still have a reasonable default (at least 300s)
    assert "timeout_seconds" in captured_timeout
    assert captured_timeout["timeout_seconds"] >= 300
