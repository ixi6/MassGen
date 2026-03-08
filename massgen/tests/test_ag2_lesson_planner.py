"""Tests for the AG2 lesson planner tool wrapper."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from massgen.tool._extraframework_agents.ag2_lesson_planner_tool import (
    ag2_lesson_planner,
)
from massgen.tool._result import ExecutionResult, TextContent


def _build_prompt(topic: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"Create a fourth grade lesson plan for {topic}."}]


class _FakeEvent:
    def __init__(self, event_type: str, *, summary: str | None = None, line: str = ""):
        self.type = event_type
        self.content = SimpleNamespace(summary=summary) if summary is not None else None
        self._line = line

    def print(self, f) -> None:
        f(self._line)


class _FakeResponse:
    def __init__(self, topic: str):
        self.events = [
            _FakeEvent("run_started", line=f"Starting AG2 flow for: {topic}"),
            _FakeEvent("run_completion", summary=f"Lesson plan for {topic}"),
        ]


def _fake_response_from_messages(messages, api_key):
    topic = messages[0]["content"] if messages else "unknown topic"
    return _FakeResponse(topic)


async def _collect_outputs(generator):
    outputs = []
    logs = []
    async for result in generator:
        if getattr(result, "is_log", False):
            logs.append(result)
        else:
            outputs.append(result)
    return outputs, logs


class TestAG2LessonPlannerTool:
    """Test AG2 Lesson Planner Tool functionality."""

    @pytest.mark.asyncio
    async def test_basic_lesson_plan_creation(self):
        """Test basic lesson plan creation with a simple topic."""
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.ag2_lesson_planner_tool.run_ag2_lesson_planner_agent",
                side_effect=_fake_response_from_messages,
            ),
        ):
            outputs, logs = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt("photosynthesis")))

        assert len(outputs) >= 1
        assert len(logs) >= 1
        result = outputs[-1]
        assert isinstance(result, ExecutionResult)
        assert len(result.output_blocks) > 0
        assert not result.output_blocks[0].data.startswith("Error:")
        assert "photosynthesis" in result.output_blocks[0].data.lower()

    @pytest.mark.asyncio
    async def test_lesson_plan_with_env_api_key(self):
        """Test lesson plan creation using environment variable for API key."""
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.ag2_lesson_planner_tool.run_ag2_lesson_planner_agent",
                side_effect=_fake_response_from_messages,
            ),
        ):
            outputs, _ = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt("fractions")))

        result = outputs[-1]
        assert isinstance(result, ExecutionResult)
        assert len(result.output_blocks) > 0
        assert not result.output_blocks[0].data.startswith("Error:")

    @pytest.mark.asyncio
    async def test_missing_api_key_error(self):
        """Test error handling when API key is missing."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            outputs, _ = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt("test topic")))

        assert len(outputs) == 1
        result = outputs[0]
        assert isinstance(result, ExecutionResult)
        assert result.output_blocks[0].data.startswith("Error:")
        assert "OPENAI_API_KEY not found" in result.output_blocks[0].data

    @pytest.mark.asyncio
    async def test_different_topics(self):
        """Test lesson plan creation with different topics."""
        topics = ["addition", "animals", "water cycle"]

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.ag2_lesson_planner_tool.run_ag2_lesson_planner_agent",
                side_effect=_fake_response_from_messages,
            ),
        ):
            for topic in topics:
                outputs, _ = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt(topic)))
                result = outputs[-1]
                assert isinstance(result, ExecutionResult)
                assert len(result.output_blocks) > 0
                assert not result.output_blocks[0].data.startswith("Error:")
                assert topic.lower() in result.output_blocks[0].data.lower()

    @pytest.mark.asyncio
    async def test_concurrent_lesson_plan_creation(self):
        """Test creating multiple lesson plans concurrently."""
        topics = ["math", "science", "reading"]

        async def _run_topic(topic: str):
            outputs, _ = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt(topic)))
            return outputs[-1]

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.ag2_lesson_planner_tool.run_ag2_lesson_planner_agent",
                side_effect=_fake_response_from_messages,
            ),
        ):
            results = await asyncio.gather(*[_run_topic(topic) for topic in topics])

        assert len(results) == len(topics)
        for topic, result in zip(topics, results):
            assert isinstance(result, ExecutionResult)
            assert len(result.output_blocks) > 0
            assert not result.output_blocks[0].data.startswith("Error:")
            assert topic.lower() in result.output_blocks[0].data.lower()


class TestAG2ToolIntegration:
    """Test AG2 tool integration with MassGen tool system."""

    def test_tool_function_signature(self):
        """Test that the tool has the correct async generator signature."""
        import collections.abc
        import inspect
        from typing import get_origin

        # The function is an async generator (uses yield), not a coroutine
        assert inspect.isasyncgenfunction(ag2_lesson_planner)

        # Get function signature
        sig = inspect.signature(ag2_lesson_planner)
        params = sig.parameters

        # Verify the prompt parameter exists (injected via context_params decorator)
        assert "prompt" in params

        # Verify return annotation is AsyncGenerator[ExecutionResult, None]
        assert get_origin(sig.return_annotation) is collections.abc.AsyncGenerator

    @pytest.mark.asyncio
    async def test_execution_result_structure(self):
        """Test that the returned ExecutionResult has the correct structure."""
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.ag2_lesson_planner_tool.run_ag2_lesson_planner_agent",
                side_effect=_fake_response_from_messages,
            ),
        ):
            outputs, _ = await _collect_outputs(ag2_lesson_planner(prompt=_build_prompt("test")))

        result = outputs[-1]
        assert hasattr(result, "output_blocks")
        assert isinstance(result.output_blocks, list)
        assert len(result.output_blocks) > 0
        assert not result.output_blocks[0].data.startswith("Error:")

        assert isinstance(result.output_blocks[0], TextContent)
        assert hasattr(result.output_blocks[0], "data")
        assert isinstance(result.output_blocks[0].data, str)


class TestAG2ToolWithBackend:
    """Test AG2 tool with ResponseBackend."""

    @pytest.mark.asyncio
    async def test_backend_registration(self):
        """Test registering AG2 tool with ResponseBackend."""
        from massgen.backend.response import ResponseBackend

        api_key = os.getenv("OPENAI_API_KEY", "test-key")

        # Import the tool
        from massgen.tool._extraframework_agents.ag2_lesson_planner_tool import (
            ag2_lesson_planner,
        )

        # Register with backend
        backend = ResponseBackend(
            api_key=api_key,
            custom_tools=[
                {
                    "func": ag2_lesson_planner,
                    "description": "Create a comprehensive lesson plan using AG2 nested chat",
                },
            ],
        )

        # Verify tool is registered (with custom_tool__ prefix)
        assert "custom_tool__ag2_lesson_planner" in backend._custom_tool_names

        # Verify schema generation
        schemas = backend._get_custom_tools_schemas()
        assert len(schemas) >= 1

        # Find our tool's schema
        ag2_schema = None
        for schema in schemas:
            if schema["function"]["name"] == "custom_tool__ag2_lesson_planner":
                ag2_schema = schema
                break

        assert ag2_schema is not None
        assert ag2_schema["type"] == "function"
        assert "parameters" in ag2_schema["function"]
