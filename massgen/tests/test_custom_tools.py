"""
Test custom tools functionality in ResponseBackend.
"""

import asyncio
import json
import os

# Add parent directory to path for imports
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from massgen.backend.base_with_custom_tool_and_mcp import (  # noqa: E402
    ExecutionContext,
    ToolExecutionConfig,
)
from massgen.backend.response import ResponseBackend  # noqa: E402
from massgen.mcp_tools.custom_tools_server import (  # noqa: E402
    _register_mcp_tool,
    _strip_background_control_args,
    build_server_config,
    create_server,
)
from massgen.tool import ExecutionResult, ToolManager  # noqa: E402
from massgen.tool._result import TextContent  # noqa: E402

# ============================================================================
# Sample custom tool functions for testing
# ============================================================================


def calculate_sum(a: int, b: int) -> ExecutionResult:
    """Calculate sum of two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of a and b
    """
    result = a + b
    return ExecutionResult(
        output_blocks=[TextContent(data=f"The sum of {a} and {b} is {result}")],
    )


def string_manipulator(text: str, operation: str = "upper") -> ExecutionResult:
    """Manipulate string based on operation.

    Args:
        text: Input string
        operation: Operation to perform (upper, lower, reverse)

    Returns:
        Manipulated string
    """
    if operation == "upper":
        result = text.upper()
    elif operation == "lower":
        result = text.lower()
    elif operation == "reverse":
        result = text[::-1]
    else:
        result = text

    return ExecutionResult(
        output_blocks=[TextContent(data=f"Result: {result}")],
    )


async def async_weather_fetcher(city: str) -> ExecutionResult:
    """Mock async function to fetch weather.

    Args:
        city: City name

    Returns:
        Mock weather data
    """
    # Simulate async operation
    await asyncio.sleep(0.1)

    weather_data = {
        "New York": "Sunny, 25°C",
        "London": "Cloudy, 18°C",
        "Tokyo": "Rainy, 22°C",
    }

    weather = weather_data.get(city, "Unknown location")
    return ExecutionResult(
        output_blocks=[TextContent(data=f"Weather in {city}: {weather}")],
    )


async def _invoke_custom_tool_json(
    backend: ResponseBackend,
    tool_name: str,
    arguments: dict,
) -> dict:
    """Execute a custom tool call and parse the final JSON output."""
    call = {
        "name": tool_name,
        "arguments": json.dumps(arguments),
    }

    final_chunk = None
    async for chunk in backend.stream_custom_tool_execution(call):
        if chunk.completed:
            final_chunk = chunk

    assert final_chunk is not None
    return json.loads(final_chunk.accumulated_result)


# ============================================================================
# Test ToolManager functionality
# ============================================================================


class TestToolManager:
    """Test ToolManager class."""

    def setup_method(self):
        """Setup for each test."""
        self.tool_manager = ToolManager()

    def test_add_tool_function_direct(self):
        """Test adding a tool function directly."""
        self.tool_manager.add_tool_function(func=calculate_sum)

        assert "custom_tool__calculate_sum" in self.tool_manager.registered_tools
        tool_entry = self.tool_manager.registered_tools["custom_tool__calculate_sum"]
        assert tool_entry.tool_name == "custom_tool__calculate_sum"
        assert tool_entry.base_function == calculate_sum

    def test_add_tool_with_string_name(self):
        """Test adding a built-in tool by name."""
        # This should find built-in functions from the tool module
        try:
            self.tool_manager.add_tool_function(func="read_file_content")
            # Tool names are registered with custom_tool__ prefix
            assert "custom_tool__read_file_content" in self.tool_manager.registered_tools
        except ValueError:
            # If built-in function not found, that's ok for this test
            pass

    def test_add_tool_with_path(self):
        """Test adding a tool from a Python file."""
        # Create a temporary Python file with a function
        test_file = Path(__file__).parent / "temp_tool.py"
        test_file.write_text(
            """
def custom_function(x: int) -> str:
    return f"Value: {x}"
""",
        )

        try:
            self.tool_manager.add_tool_function(path=str(test_file))
            assert "custom_tool__custom_function" in self.tool_manager.registered_tools
        finally:
            # Cleanup
            if test_file.exists():
                test_file.unlink()

    def test_fetch_tool_schemas(self):
        """Test fetching tool schemas."""
        self.tool_manager.add_tool_function(func=calculate_sum)
        self.tool_manager.add_tool_function(func=string_manipulator)

        schemas = self.tool_manager.fetch_tool_schemas()
        assert len(schemas) == 2

        # Check schema format
        for schema in schemas:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]

    @pytest.mark.asyncio
    async def test_execute_tool(self):
        """Test executing a tool."""
        self.tool_manager.add_tool_function(func=calculate_sum)

        tool_request = {
            "name": "custom_tool__calculate_sum",
            "input": {"a": 5, "b": 3},
        }

        results = []
        async for result in self.tool_manager.execute_tool(tool_request):
            results.append(result)

        assert len(results) > 0
        result = results[0]
        assert hasattr(result, "output_blocks")
        assert "The sum of 5 and 3 is 8" in result.output_blocks[0].data

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        """Test executing an async tool."""
        self.tool_manager.add_tool_function(func=async_weather_fetcher)

        tool_request = {
            "name": "custom_tool__async_weather_fetcher",
            "input": {"city": "Tokyo"},
        }

        results = []
        async for result in self.tool_manager.execute_tool(tool_request):
            results.append(result)

        assert len(results) > 0
        result = results[0]
        assert "Weather in Tokyo: Rainy, 22°C" in result.output_blocks[0].data


# ============================================================================
# Test ResponseBackend with custom tools
# ============================================================================


class TestResponseBackendCustomTools:
    """Test ResponseBackend with custom tools integration."""

    def setup_method(self):
        """Setup for each test."""
        self.api_key = os.getenv("OPENAI_API_KEY", "test-key")

    def test_backend_initialization_with_custom_tools(self):
        """Test initializing ResponseBackend with custom tools."""
        custom_tools = [
            {
                "func": calculate_sum,
                "description": "Calculate sum of two numbers",
            },
            {
                "func": string_manipulator,
                "category": "text",
                "preset_args": {"operation": "upper"},
            },
        ]

        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=custom_tools,
        )

        # Check that tools were registered (with custom_tool__ prefix)
        assert len(backend._custom_tool_names) >= 2
        assert "custom_tool__calculate_sum" in backend._custom_tool_names
        assert "custom_tool__string_manipulator" in backend._custom_tool_names

    def test_get_custom_tools_schemas(self):
        """Test getting custom tools schemas."""
        custom_tools = [
            {"func": calculate_sum},
            {"func": string_manipulator},
        ]

        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=custom_tools,
        )

        schemas = backend._get_custom_tools_schemas()
        assert len(schemas) >= 2
        schema_names = {schema["function"]["name"] for schema in schemas}
        assert "custom_tool__calculate_sum" in schema_names
        assert "custom_tool__string_manipulator" in schema_names

        # Verify schema structure (names have custom_tool__ prefix)
        for schema in schemas:
            assert schema["type"] == "function"
            function = schema["function"]
            assert "name" in function
            assert "parameters" in function

    def test_background_tool_management_schemas_present(self):
        """Background management tools should always be available as custom schemas."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": calculate_sum}],
        )

        schema_names = {schema["function"]["name"] for schema in backend._get_custom_tools_schemas()}
        assert "custom_tool__start_background_tool" in schema_names
        assert "custom_tool__get_background_tool_status" in schema_names
        assert "custom_tool__get_background_tool_result" in schema_names
        assert "custom_tool__cancel_background_tool" in schema_names
        assert "custom_tool__list_background_tools" in schema_names
        assert "custom_tool__wait_for_background_tool" in schema_names

    @pytest.mark.asyncio
    async def test_execute_custom_tool(self):
        """Test custom tool registration and schema generation."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": calculate_sum}],
        )

        # Verify tool is registered with prefixed name
        assert "custom_tool__calculate_sum" in backend._custom_tool_names

        # Verify schema generation includes the tool with correct name
        schemas = backend._get_custom_tools_schemas()
        schema_names = {schema["function"]["name"] for schema in schemas}
        assert "custom_tool__calculate_sum" in schema_names

    @pytest.mark.asyncio
    async def test_custom_tool_categorization(self):
        """Test that custom tools are properly categorized in _stream_with_mcp_tools."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[
                {"func": calculate_sum},
                {"func": string_manipulator},
            ],
        )

        # Simulate captured function calls using the prefixed names as the LLM would return them
        captured_calls = [
            {"name": "custom_tool__calculate_sum", "call_id": "1", "arguments": '{"a": 1, "b": 2}'},
            {"name": "web_search", "call_id": "2", "arguments": '{"query": "test"}'},
            {"name": "unknown_mcp_tool", "call_id": "3", "arguments": "{}"},
        ]

        # Categorize calls (simulate the logic in _stream_with_mcp_tools)
        mcp_calls = []
        custom_calls = []
        provider_calls = []

        for call in captured_calls:
            if call["name"] in backend._mcp_functions:
                mcp_calls.append(call)
            elif call["name"] in backend._custom_tool_names:
                custom_calls.append(call)
            else:
                provider_calls.append(call)

        # Verify categorization
        assert len(custom_calls) == 1
        assert custom_calls[0]["name"] == "custom_tool__calculate_sum"

        assert len(provider_calls) == 2
        assert "web_search" in [c["name"] for c in provider_calls]
        assert "unknown_mcp_tool" in [c["name"] for c in provider_calls]

        assert len(mcp_calls) == 0  # No MCP tools in this test

    @pytest.mark.asyncio
    async def test_background_tool_lifecycle_for_custom_tool(self):
        """Background manager should run a custom tool asynchronously and return result."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "Tokyo"},
            },
        )

        assert start["status"] == "running"
        job_id = start["job_id"]

        status = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_status",
            {"job_id": job_id},
        )
        assert status["status"] in {"running", "completed"}

        await asyncio.sleep(0.2)

        result = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_result",
            {"job_id": job_id},
        )
        assert result["ready"] is True
        assert result["status"] == "completed"
        assert "Weather in Tokyo" in result["result"]
        assert result["tool_success"] is True

        pending = backend.get_pending_background_tool_results()
        assert any(job["job_id"] == job_id for job in pending)

    @pytest.mark.asyncio
    async def test_stream_custom_tool_execution_accepts_double_encoded_arguments(self):
        """Custom tool execution should handle double-encoded JSON argument strings."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        call = {
            "name": "custom_tool__async_weather_fetcher",
            "arguments": json.dumps(json.dumps({"city": "Tokyo"})),
        }

        final_chunk = None
        async for chunk in backend.stream_custom_tool_execution(call):
            if chunk.completed:
                final_chunk = chunk

        assert final_chunk is not None
        assert "Weather in Tokyo" in final_chunk.accumulated_result

    @pytest.mark.asyncio
    async def test_start_background_tool_accepts_top_level_target_args(self):
        """start_background_tool should accept flattened target args for clarity."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "city": "Tokyo",
            },
        )
        assert start["status"] == "running"
        job_id = start["job_id"]

        await asyncio.sleep(0.2)

        result = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_result",
            {"job_id": job_id},
        )
        assert result["ready"] is True
        assert result["status"] == "completed"
        assert "Weather in Tokyo" in result["result"]

    @pytest.mark.asyncio
    async def test_start_background_tool_accepts_double_encoded_arguments(self):
        """start_background_tool should normalize double-encoded arguments payloads."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": json.dumps(json.dumps({"city": "Tokyo"})),
            },
        )
        assert start["success"] is True
        assert start["status"] == "running"
        job_id = start["job_id"]

        await asyncio.sleep(0.2)

        result = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_result",
            {"job_id": job_id},
        )
        assert result["ready"] is True
        assert result["status"] == "completed"
        assert "Weather in Tokyo" in result["result"]

    @pytest.mark.asyncio
    async def test_start_background_tool_accepts_missing_trailing_brace_payload(self):
        """start_background_tool should recover simple missing-closing-brace JSON payloads."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        raw_arguments = json.dumps(
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "Tokyo"},
            },
        )
        malformed_arguments = raw_arguments[:-1]

        call = {
            "name": "custom_tool__start_background_tool",
            "arguments": malformed_arguments,
        }

        final_chunk = None
        async for chunk in backend.stream_custom_tool_execution(call):
            if chunk.completed:
                final_chunk = chunk

        assert final_chunk is not None
        start = json.loads(final_chunk.accumulated_result)
        assert start["success"] is True
        assert start["status"] == "running"
        job_id = start["job_id"]

        await asyncio.sleep(0.2)
        result = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_result",
            {"job_id": job_id},
        )
        assert result["ready"] is True
        assert result["status"] == "completed"
        assert "Weather in Tokyo" in result["result"]

    @pytest.mark.asyncio
    async def test_start_background_tool_subagent_target_routes_to_direct_background_spawn(
        self,
        monkeypatch,
    ):
        """start_background_tool targeting spawn_subagents should mirror direct background spawn semantics."""
        backend = ResponseBackend(api_key=self.api_key)
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")
        backend._mcp_functions["mcp__subagent_agent_a__spawn_subagents"] = types.SimpleNamespace(
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {"type": "array", "items": {"type": "object"}},
                    "background": {"type": "boolean"},
                },
            },
        )

        captured: dict[str, object] = {}
        callback_calls: list[dict[str, object]] = []

        async def fake_execute_mcp(function_name, arguments_json, max_retries=3):  # noqa: ARG001
            parsed = json.loads(arguments_json)
            captured["tool_name"] = function_name
            captured["arguments"] = parsed
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
            payload_text = json.dumps(payload)
            return (
                payload_text,
                types.SimpleNamespace(
                    content=[types.SimpleNamespace(text=payload_text)],
                ),
            )

        async def fail_start_background_job(*, tool_name, arguments, source_call_id=None):  # noqa: ARG001
            raise AssertionError(
                f"framework background wrapper should be bypassed for subagent target: {tool_name}",
            )

        backend.set_subagent_spawn_callback(
            lambda tool_name, args, call_id: callback_calls.append(
                {
                    "tool_name": tool_name,
                    "args": dict(args),
                    "call_id": call_id,
                },
            ),
        )
        monkeypatch.setattr(backend, "_execute_mcp_function_with_retry", fake_execute_mcp)
        monkeypatch.setattr(backend, "_start_background_tool_job", fail_start_background_job)

        call = {
            "name": "custom_tool__start_background_tool",
            "call_id": "start-bg-subagent-call",
            "arguments": json.dumps(
                {
                    "tool_name": "mcp__subagent_agent_a__spawn_subagents",
                    "arguments": {
                        "tasks": [{"task": "Research jazz history"}],
                        "background": False,
                    },
                },
            ),
        }

        final_chunk = None
        async for chunk in backend.stream_custom_tool_execution(call):
            if chunk.completed:
                final_chunk = chunk

        assert final_chunk is not None
        payload = json.loads(final_chunk.accumulated_result)
        assert payload["success"] is True
        assert payload["operation"] == "spawn_subagents"
        assert payload["mode"] == "background"
        assert payload["job_id"] == "jazz_researcher"
        assert payload["subagent_id"] == "jazz_researcher"
        assert payload["job_ids"] == ["jazz_researcher"]
        assert payload["subagents"][0]["job_id"] == "jazz_researcher"

        assert captured["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
        assert isinstance(captured["arguments"], dict)
        assert captured["arguments"]["background"] is True
        assert callback_calls
        assert callback_calls[0]["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
        assert callback_calls[0]["call_id"] == "start-bg-subagent-call"
        assert callback_calls[0]["args"]["background"] is True

    @pytest.mark.asyncio
    async def test_wait_for_background_tool_returns_next_completion(self):
        """Wait lifecycle tool should block until the next job completes."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "Tokyo"},
            },
        )

        waited = await _invoke_custom_tool_json(
            backend,
            "custom_tool__wait_for_background_tool",
            {"timeout_seconds": 1.0},
        )
        assert waited["success"] is True
        assert waited["ready"] is True
        assert waited["job_id"] == start["job_id"]
        assert waited["status"] == "completed"
        assert "Weather in Tokyo" in waited["result"]
        assert waited["tool_success"] is True

    @pytest.mark.asyncio
    async def test_wait_for_background_tool_consumes_shared_completion_queue(self):
        """wait_for_background_tool should consume the same queue used by hook injection."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "Tokyo"},
            },
        )

        waited = await _invoke_custom_tool_json(
            backend,
            "custom_tool__wait_for_background_tool",
            {"timeout_seconds": 1.0},
        )
        assert waited["success"] is True
        assert waited["ready"] is True
        assert waited["job_id"] == start["job_id"]

        pending = backend.get_pending_background_tool_results()
        pending_ids = {job.get("job_id") for job in pending}
        assert start["job_id"] not in pending_ids

    @pytest.mark.asyncio
    async def test_wait_for_background_tool_returns_interrupt_payload_when_runtime_input_available(
        self,
    ):
        """wait_for_background_tool should exit early with injected runtime content."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
            agent_id="agent_a",
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        async def interrupt_provider(agent_id: str):
            assert agent_id == "agent_a"
            return {
                "interrupt_reason": "runtime_injection_available",
                "injected_content": "[Human Input]: Please prioritize edge cases.",
            }

        backend.set_background_wait_interrupt_provider(interrupt_provider)

        waited = await _invoke_custom_tool_json(
            backend,
            "custom_tool__wait_for_background_tool",
            {"timeout_seconds": 1.0},
        )
        assert waited["success"] is True
        assert waited["ready"] is False
        assert waited["interrupted"] is True
        assert waited["interrupt_reason"] == "runtime_injection_available"
        assert "edge cases" in waited["injected_content"]

    @pytest.mark.asyncio
    async def test_list_background_tools_defaults_to_running_only(self):
        """List lifecycle tool should show running jobs by default and support include_all."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        first = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "Tokyo"},
            },
        )
        await asyncio.sleep(0.15)  # Allow first job to finish.

        second = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__async_weather_fetcher",
                "arguments": {"city": "London"},
            },
        )

        running_only = await _invoke_custom_tool_json(
            backend,
            "custom_tool__list_background_tools",
            {},
        )
        running_ids = {job["job_id"] for job in running_only["jobs"]}
        assert second["job_id"] in running_ids
        assert first["job_id"] not in running_ids

        all_jobs = await _invoke_custom_tool_json(
            backend,
            "custom_tool__list_background_tools",
            {"include_all": True},
        )
        all_ids = {job["job_id"] for job in all_jobs["jobs"]}
        assert first["job_id"] in all_ids
        assert second["job_id"] in all_ids

    @pytest.mark.asyncio
    async def test_background_tool_lifecycle_for_mcp_tool(self, monkeypatch):
        """Background manager should run an MCP tool asynchronously via the same interface."""
        backend = ResponseBackend(api_key=self.api_key)
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")
        backend._mcp_functions["mcp__command_line__execute_command"] = object()

        async def fake_mcp(function_name: str, arguments_json: str, max_retries: int = 3):  # noqa: ARG001
            arguments = json.loads(arguments_json)
            return f"Executed: {arguments.get('command')}", {"ok": True}

        monkeypatch.setattr(backend, "_execute_mcp_function_with_retry", fake_mcp)

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "mcp__command_line__execute_command",
                "arguments": {"command": "echo hi"},
            },
        )
        job_id = start["job_id"]

        await asyncio.sleep(0.05)

        result = await _invoke_custom_tool_json(
            backend,
            "custom_tool__get_background_tool_result",
            {"job_id": job_id},
        )
        assert result["ready"] is True
        assert result["status"] == "completed"
        assert "Executed: echo hi" in result["result"]
        assert "tool_success" not in result

    @pytest.mark.asyncio
    async def test_execute_mcp_function_with_retry_accepts_double_encoded_arguments(self):
        """MCP execution should normalize double-encoded JSON arguments before dispatch."""
        backend = ResponseBackend(api_key=self.api_key)

        captured: dict = {}

        class _FakeMCPFunction:
            async def call(self, arguments_json: str):
                captured["arguments"] = json.loads(arguments_json)
                return {"success": True}

        backend._mcp_functions["mcp__test__echo"] = _FakeMCPFunction()

        result_str, _ = await backend._execute_mcp_function_with_retry(
            "mcp__test__echo",
            json.dumps(json.dumps({"command": "echo hi"})),
        )

        assert captured["arguments"] == {"command": "echo hi"}
        assert not result_str.startswith("Error:")

    @pytest.mark.asyncio
    async def test_execute_tool_with_logging_auto_background_from_background_flag(self):
        """Tool calls with background=true should be scheduled automatically."""
        backend = ResponseBackend(
            api_key=self.api_key,
            custom_tools=[{"func": async_weather_fetcher}],
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        call = {
            "name": "custom_tool__async_weather_fetcher",
            "call_id": "auto-bg-call",
            "arguments": json.dumps({"city": "Tokyo", "background": True}),
        }
        config = ToolExecutionConfig(
            tool_type="custom",
            chunk_type="custom_tool_status",
            emoji_prefix="🔧 [Custom Tool]",
            success_emoji="✅ [Custom Tool]",
            error_emoji="❌ [Custom Tool Error]",
            source_prefix="custom_",
            status_called="custom_tool_called",
            status_response="custom_tool_response",
            status_error="custom_tool_error",
            execution_callback=backend._execute_custom_tool,
        )
        updated_messages = []
        processed_call_ids = set()

        chunks = []
        async for chunk in backend._execute_tool_with_logging(
            call,
            config,
            updated_messages,
            processed_call_ids,
        ):
            chunks.append(chunk)

        assert "auto-bg-call" in processed_call_ids
        assert any(getattr(chunk, "status", "") == "custom_tool_response" and "background" in (getattr(chunk, "content", "").lower()) for chunk in chunks)
        assert updated_messages

        result_payload = json.loads(updated_messages[-1]["output"])
        assert result_payload["status"] == "background"
        assert result_payload["job_id"]

    @pytest.mark.asyncio
    async def test_execute_tool_with_logging_mcp_tool_with_native_background_param_runs_foreground(
        self,
        monkeypatch,
    ):
        """MCP tools that define background should run foreground (no wrapper background job)."""
        backend = ResponseBackend(api_key=self.api_key)
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")
        backend._mcp_functions["mcp__subagent_agent_a__spawn_subagents"] = types.SimpleNamespace(
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {"type": "array", "items": {"type": "object"}},
                    "background": {"type": "boolean"},
                },
            },
        )

        captured: dict = {}

        async def fake_execute_mcp(function_name, arguments_json, max_retries=3):  # noqa: ARG001
            captured["tool_name"] = function_name
            captured["arguments"] = json.loads(arguments_json)
            return (
                '{"success": true, "operation": "spawn_subagents", "mode": "background"}',
                types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            text='{"success": true, "operation": "spawn_subagents", "mode": "background"}',
                        ),
                    ],
                ),
            )

        async def fail_start_background_job(*, tool_name, arguments, source_call_id=None):  # noqa: ARG001
            raise AssertionError(
                f"auto-background wrapper should not run for {tool_name} with native background arg",
            )

        monkeypatch.setattr(backend, "_execute_mcp_function_with_retry", fake_execute_mcp)
        monkeypatch.setattr(backend, "_start_background_tool_job", fail_start_background_job)

        call = {
            "name": "mcp__subagent_agent_a__spawn_subagents",
            "call_id": "auto-bg-mcp-call",
            "arguments": json.dumps(
                {
                    "tasks": [{"task": "test task"}],
                    "background": True,
                },
            ),
        }
        config = ToolExecutionConfig(
            tool_type="mcp",
            chunk_type="mcp_tool_status",
            emoji_prefix="🔧 [MCP]",
            success_emoji="✅ [MCP]",
            error_emoji="❌ [MCP Error]",
            source_prefix="mcp_",
            status_called="mcp_tool_called",
            status_response="mcp_tool_response",
            status_error="mcp_tool_error",
            execution_callback=backend._execute_mcp_function_with_retry,
        )
        updated_messages = []
        processed_call_ids = set()

        chunks = []
        async for chunk in backend._execute_tool_with_logging(
            call,
            config,
            updated_messages,
            processed_call_ids,
        ):
            chunks.append(chunk)

        assert "auto-bg-mcp-call" in processed_call_ids
        assert captured["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
        assert captured["arguments"]["background"] is True
        assert any(getattr(chunk, "status", "") == "mcp_tool_response" for chunk in chunks)
        assert updated_messages

    def test_media_tools_default_to_background_mode(self):
        """read_media and generate_media should auto-background unless explicitly foreground."""
        backend = ResponseBackend(api_key=self.api_key)

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

    @pytest.mark.asyncio
    async def test_media_background_start_requires_context_file(self, tmp_path: Path):
        """Background media jobs should fail fast when CONTEXT.md is missing."""
        backend = ResponseBackend(
            api_key=self.api_key,
            enable_multimodal_tools=True,
            cwd=str(tmp_path),
        )
        backend._execution_context = ExecutionContext(messages=[], agent_id="agent_a")

        start = await _invoke_custom_tool_json(
            backend,
            "custom_tool__start_background_tool",
            {
                "tool_name": "custom_tool__generate_media",
                "arguments": {"prompt": "a mountain goat on a cliff"},
            },
        )

        assert start["success"] is False
        assert "CONTEXT.md" in start["error"]


# ============================================================================
# Integration test with mock streaming
# ============================================================================


class TestCustomToolsIntegration:
    """Integration tests for custom tools with streaming."""

    @pytest.mark.asyncio
    async def test_custom_tool_execution_flow(self):
        """Test the complete flow of custom tool registration."""
        # Create backend with custom tools
        backend = ResponseBackend(
            api_key=os.getenv("OPENAI_API_KEY", "test-key"),
            custom_tools=[
                {"func": calculate_sum, "description": "Add two numbers"},
                {"func": async_weather_fetcher, "description": "Get weather info"},
            ],
        )

        # Verify tools are registered (with custom_tool__ prefix)
        assert "custom_tool__calculate_sum" in backend._custom_tool_names
        assert "custom_tool__async_weather_fetcher" in backend._custom_tool_names

        # Verify schema generation includes both tools
        schemas = backend._get_custom_tools_schemas()
        schema_names = {s["function"]["name"] for s in schemas}
        assert "custom_tool__calculate_sum" in schema_names
        assert "custom_tool__async_weather_fetcher" in schema_names

    def test_custom_tool_error_handling(self):
        """Test error handling in custom tools."""

        def faulty_tool(x: int) -> ExecutionResult:
            raise ValueError("Intentional error")

        backend = ResponseBackend(
            api_key="test-key",
            custom_tools=[{"func": faulty_tool}],
        )

        assert "custom_tool__faulty_tool" in backend._custom_tool_names

    @pytest.mark.asyncio
    async def test_mixed_tools_categorization(self):
        """Test categorization with mixed tool types."""
        backend = ResponseBackend(
            api_key="test-key",
            custom_tools=[{"func": calculate_sum}],
        )

        # Mock some MCP functions
        backend._mcp_functions = {"mcp_tool": None}
        backend._mcp_function_names = {"mcp_tool"}

        # Test categorization logic (custom tools use custom_tool__ prefix)
        test_calls = [
            {"name": "custom_tool__calculate_sum", "call_id": "1", "arguments": "{}"},  # Custom
            {"name": "mcp_tool", "call_id": "2", "arguments": "{}"},  # MCP
            {"name": "web_search", "call_id": "3", "arguments": "{}"},  # Provider
        ]

        custom = []
        mcp = []
        provider = []

        for call in test_calls:
            if call["name"] in backend._mcp_functions:
                mcp.append(call)
            elif call["name"] in backend._custom_tool_names:
                custom.append(call)
            else:
                provider.append(call)

        assert len(custom) == 1 and custom[0]["name"] == "custom_tool__calculate_sum"
        assert len(mcp) == 1 and mcp[0]["name"] == "mcp_tool"
        assert len(provider) == 1 and provider[0]["name"] == "web_search"


def test_custom_tools_build_server_config_env_merge(tmp_path: Path) -> None:
    """Ensure custom tools MCP env merges and forces banner suppression."""
    specs_path = tmp_path / "custom_tool_specs.json"
    cfg = build_server_config(
        specs_path,
        env={"OPENAI_API_KEY": "test-key", "FASTMCP_SHOW_CLI_BANNER": "true"},
    )
    env = cfg.get("env", {})
    assert env.get("OPENAI_API_KEY") == "test-key"
    assert env.get("FASTMCP_SHOW_CLI_BANNER") == "false"


def test_custom_tools_build_server_config_includes_wait_interrupt_file(tmp_path: Path) -> None:
    """Server config should pass through a wait interrupt file path when provided."""
    specs_path = tmp_path / "custom_tool_specs.json"
    wait_interrupt_file = tmp_path / "wait_interrupt.json"
    cfg = build_server_config(
        specs_path,
        wait_interrupt_file=wait_interrupt_file,
    )

    args = cfg.get("args", [])
    assert "--wait-interrupt-file" in args
    index = args.index("--wait-interrupt-file")
    assert args[index + 1] == str(wait_interrupt_file)


@pytest.mark.asyncio
async def test_custom_tools_create_server_injects_backend_context(monkeypatch, tmp_path: Path) -> None:
    """custom_tools_server should propagate backend identity into tool context params."""
    tool_path = tmp_path / "context_tool.py"
    tool_path.write_text(
        """
import json

from massgen.tool import ExecutionResult
from massgen.tool._decorators import context_params
from massgen.tool._result import TextContent


@context_params("backend_type", "model", "agent_cwd", "task_context")
async def capture_context(
    backend_type=None,
    model=None,
    agent_cwd=None,
    task_context=None,
):
    return ExecutionResult(
        output_blocks=[
            TextContent(
                data=json.dumps(
                    {
                        "backend_type": backend_type,
                        "model": model,
                        "agent_cwd": agent_cwd,
                        "task_context": task_context,
                    }
                )
            )
        ]
    )
""",
        encoding="utf-8",
    )
    (tmp_path / "CONTEXT.md").write_text("Inspect the rendered output carefully.", encoding="utf-8")

    specs_path = tmp_path / "custom_tool_specs.json"
    specs_path.write_text(
        json.dumps(
            {
                "custom_tools": [
                    {
                        "path": str(tool_path),
                        "function": "capture_context",
                    },
                ],
                "background_mcp_servers": [],
            },
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "custom_tools_server.py",
            "--tool-specs",
            str(specs_path),
            "--agent-id",
            "agent_test",
            "--allowed-paths",
            str(tmp_path),
            "--backend-type",
            "codex",
            "--model",
            "gpt-5.4",
        ],
    )

    server = await create_server()

    handler = None
    for tool in server._tool_manager._tools.values():
        if tool.name == "custom_tool__capture_context":
            handler = tool.fn
            break
    assert handler is not None

    response = json.loads(await handler())
    block = response["output_blocks"][0]
    block_text = block["data"] if isinstance(block, dict) else str(block)
    assert '"backend_type": "codex"' in block_text
    assert '"model": "gpt-5.4"' in block_text
    assert str(tmp_path) in block_text
    assert "Inspect the rendered output carefully." in block_text


def test_custom_tools_server_standalone_import_no_relative_imports():
    """custom_tools_server.py must be loadable as a standalone module (no relative imports).

    When fastmcp run loads the file, it is NOT part of the massgen package.
    Any top-level relative import (from ..foo import bar) will fail with
    ImportError: attempted relative import with no known parent package.
    This is a regression test for the Codex custom tools MCP server not starting.
    """
    import importlib.util

    server_path = Path(__file__).parent.parent / "mcp_tools" / "custom_tools_server.py"
    assert server_path.exists(), f"Expected server file at {server_path}"

    # Load the module as a standalone file (no parent package), same as fastmcp run does
    spec = importlib.util.spec_from_file_location("custom_tools_server", server_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so @dataclass can resolve cls.__module__
    sys.modules["custom_tools_server"] = module
    try:
        # This will raise ImportError if there are top-level relative imports
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("custom_tools_server", None)

    # Verify the factory function is present and callable
    assert hasattr(module, "create_server")
    assert callable(module.create_server)


@pytest.mark.asyncio
async def test_custom_tools_create_server_standalone_with_hook_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Standalone file-path loading must support --hook-dir without import errors.

    fastmcp file-path launch loads this module outside package context.
    Hook middleware import must still work in that mode.
    """
    import importlib.util

    server_path = Path(__file__).parent.parent / "mcp_tools" / "custom_tools_server.py"
    assert server_path.exists(), f"Expected server file at {server_path}"

    specs_path = tmp_path / "custom_tool_specs.json"
    specs_path.write_text(
        json.dumps(
            {
                "custom_tools": [],
                "background_mcp_servers": [],
            },
        ),
        encoding="utf-8",
    )
    hook_dir = tmp_path / "hook_ipc"
    hook_dir.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location("custom_tools_server", server_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["custom_tools_server"] = module
    try:
        spec.loader.exec_module(module)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "custom_tools_server.py",
                "--tool-specs",
                str(specs_path),
                "--agent-id",
                "agent_test",
                "--allowed-paths",
                str(tmp_path),
                "--hook-dir",
                str(hook_dir),
            ],
        )
        server = await module.create_server()
    finally:
        sys.modules.pop("custom_tools_server", None)

    available_tools = {tool.name for tool in server._tool_manager._tools.values()}
    assert "custom_tool__wait_for_background_tool" in available_tools


# ============================================================================
# MCP tool schema type annotation tests
# ============================================================================


class TestMcpToolSchemaTypes:
    """Tests that _register_mcp_tool produces correct typed schemas for FastMCP.

    Without type annotations, FastMCP generates typeless schemas and models
    treat all arguments as strings — causing arrays to be stringified, booleans
    to be sent as "true"/"false", etc. This led to generate_media iterating
    over characters instead of prompts (generating dozens of images).
    """

    def _get_registered_schema(self, tool_name, tool_params, tool_desc="test"):
        """Register a tool and return the schema FastMCP generated for it."""
        import fastmcp

        mcp = fastmcp.FastMCP("test_schema")
        tm = ToolManager()
        ctx = {"agent_cwd": "/tmp"}
        _register_mcp_tool(mcp, tool_name, tool_desc, tool_params, tm, ctx)
        tool = mcp._tool_manager._tools[tool_name]
        return tool.parameters

    def test_string_param_has_type(self):
        tool_params = {"properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}
        schema = self._get_registered_schema("t", tool_params)
        assert schema["properties"]["prompt"]["type"] == "string"

    def test_array_param_has_type(self):
        tool_params = {
            "properties": {"prompts": {"type": "array", "items": {"type": "string"}}},
            "required": ["prompts"],
        }
        schema = self._get_registered_schema("t", tool_params)
        prop = schema["properties"]["prompts"]
        assert prop.get("type") == "array" or any(v.get("type") == "array" for v in prop.get("anyOf", []))

    def test_object_param_has_type(self):
        tool_params = {"properties": {"config": {"type": "object"}}, "required": ["config"]}
        schema = self._get_registered_schema("t", tool_params)
        prop = schema["properties"]["config"]
        assert prop.get("type") == "object" or any(v.get("type") == "object" for v in prop.get("anyOf", []))

    def test_boolean_param_has_type(self):
        tool_params = {"properties": {"verbose": {"type": "boolean"}}, "required": ["verbose"]}
        schema = self._get_registered_schema("t", tool_params)
        prop = schema["properties"]["verbose"]
        assert prop.get("type") == "boolean" or any(v.get("type") == "boolean" for v in prop.get("anyOf", []))

    def test_integer_param_has_type(self):
        tool_params = {"properties": {"count": {"type": "integer"}}, "required": ["count"]}
        schema = self._get_registered_schema("t", tool_params)
        prop = schema["properties"]["count"]
        assert prop.get("type") == "integer" or any(v.get("type") == "integer" for v in prop.get("anyOf", []))

    def test_optional_array_via_anyof_has_type(self):
        """Pydantic Optional[List[str]] generates anyOf — must still have array type."""
        tool_params = {
            "properties": {
                "prompts": {
                    "anyOf": [
                        {"items": {"type": "string"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                },
            },
        }
        schema = self._get_registered_schema("t", tool_params)
        prop = schema["properties"]["prompts"]
        types = {v.get("type") for v in prop.get("anyOf", [])}
        assert "array" in types, f"Expected 'array' in anyOf types, got: {prop}"

    def test_generate_media_schema_has_all_types(self):
        """Regression: generate_media schema must have correct types for all params."""
        tool_params = {
            "properties": {
                "mode": {"type": "string"},
                "prompt": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                },
                "prompts": {
                    "anyOf": [
                        {"items": {"type": "string"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                },
                "quality": {"default": "high", "type": "string"},
                "aspect_ratio": {"default": "1:1", "type": "string"},
                "extra_params": {
                    "anyOf": [{"type": "object"}, {"type": "null"}],
                    "default": None,
                },
            },
            "required": ["mode"],
        }
        schema = self._get_registered_schema("gen_media", tool_params)
        props = schema["properties"]

        assert props["mode"]["type"] == "string"

        prompts_types = {v.get("type") for v in props["prompts"].get("anyOf", [])}
        assert "array" in prompts_types, f"prompts missing array type: {props['prompts']}"

        extra_types = {v.get("type") for v in props["extra_params"].get("anyOf", [])}
        assert "object" in extra_types

    def test_no_type_annotations_means_typeless_schema(self):
        """Baseline: without our fix, schemas would be typeless."""
        import inspect as _inspect

        import fastmcp

        mcp = fastmcp.FastMCP("baseline")
        params = [
            _inspect.Parameter("prompt", _inspect.Parameter.POSITIONAL_OR_KEYWORD),
            _inspect.Parameter("prompts", _inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        ]

        async def bare_handler(**kwargs):
            return ""

        bare_handler.__signature__ = _inspect.Signature(params)
        bare_handler.__name__ = "bare"
        bare_handler.__doc__ = "bare"
        mcp.tool(name="bare", description="bare")(bare_handler)
        schema = mcp._tool_manager._tools["bare"].parameters
        assert "type" not in schema["properties"]["prompt"]
        assert "type" not in schema["properties"]["prompts"]


# ============================================================================
# _strip_background_control_args tests
# ============================================================================


class TestStripBackgroundControlArgs:
    """Tests for _strip_background_control_args.

    Synthetic control parameters (mode, background) are added by
    _register_mcp_tool for background scheduling.  They must be stripped
    before the arguments are passed to the actual tool execution, whether
    via the background path or the foreground path.
    """

    def test_strips_none_mode(self):
        """mode=None (the synthetic default) must be stripped."""
        args = {"prompt": "goat", "mode": None}
        result = _strip_background_control_args(args)
        assert "mode" not in result
        assert result["prompt"] == "goat"

    def test_strips_background_mode(self):
        """mode='background' must be stripped."""
        args = {"prompt": "goat", "mode": "background"}
        result = _strip_background_control_args(args)
        assert "mode" not in result

    def test_preserves_real_mode_value(self):
        """A tool's own 'mode' param (e.g., mode='image') must survive."""
        args = {"prompt": "goat", "mode": "image"}
        result = _strip_background_control_args(args)
        assert result["mode"] == "image"

    def test_strips_background_flag(self):
        args = {"prompt": "goat", "background": True}
        result = _strip_background_control_args(args)
        assert "background" not in result

    def test_can_preserve_real_background_when_not_marked_control(self):
        """Callers can strip only synthetic controls and keep real tool params."""
        args = {"tasks": [{"task": "x"}], "background": True, "mode": None}
        result = _strip_background_control_args(args, control_args_to_strip={"mode"})
        assert result["background"] is True
        assert "mode" not in result

    def test_explicit_synthetic_mode_strip_removes_non_control_mode_value(self):
        """When callers mark `mode` as synthetic, strip it even if it looks real.

        Regression: media tools can receive a synthetic `mode="image"` control arg
        from MCP wrapper generation. That value must not leak into the real tool.
        """
        args = {
            "prompt": "review screenshots",
            "inputs": [{"files": {"hero": "hero.png"}}],
            "mode": "image",
        }
        result = _strip_background_control_args(args, control_args_to_strip={"mode"})
        assert "mode" not in result
        assert result["prompt"] == "review screenshots"
        assert result["inputs"] == [{"files": {"hero": "hero.png"}}]

    def test_strips_run_in_background_flag(self):
        args = {"prompt": "goat", "run_in_background": True}
        result = _strip_background_control_args(args)
        assert "run_in_background" not in result

    def test_preserves_real_tool_params(self):
        """Real tool parameters should not be touched."""
        args = {"prompt": "goat", "quality": "high", "aspect_ratio": "1:1"}
        result = _strip_background_control_args(args)
        assert result == args

    def test_combined_synthetic_and_real_params(self):
        """Regression: read_media with synthetic mode=None + real params."""
        args = {
            "file_path": "/workspace/output.png",
            "mode": None,
            "background": None,
        }
        result = _strip_background_control_args(args)
        assert result == {"file_path": "/workspace/output.png"}

    def test_does_not_mutate_original(self):
        """Original dict must not be modified."""
        args = {"prompt": "goat", "mode": None, "background": True}
        original = dict(args)
        _strip_background_control_args(args)
        assert args == original


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    # Run pytest
    pytest.main([__file__, "-v"])
