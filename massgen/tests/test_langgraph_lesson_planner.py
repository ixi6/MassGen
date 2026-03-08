"""Tests for the LangGraph lesson planner tool wrapper."""

import asyncio
import os
from unittest.mock import patch

import pytest

from massgen.tool._extraframework_agents.langgraph_lesson_planner_tool import (
    langgraph_lesson_planner,
)
from massgen.tool._result import ExecutionResult, TextContent


def _build_prompt(topic: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"Create a fourth grade lesson plan for {topic}."}]


async def _fake_langgraph_runner(messages, api_key):
    topic = messages[0]["content"] if messages else "unknown topic"
    yield {"type": "log", "content": f"Generating lesson plan for {topic}"}
    yield {"type": "output", "content": f"Lesson plan for {topic}"}


async def _collect_outputs(generator):
    outputs = []
    logs = []
    async for result in generator:
        if getattr(result, "is_log", False):
            logs.append(result)
        else:
            outputs.append(result)
    return outputs, logs


class TestLangGraphLessonPlannerTool:
    """Test LangGraph Lesson Planner Tool functionality."""

    @pytest.mark.asyncio
    async def test_basic_lesson_plan_creation(self):
        """Test basic lesson plan creation with a simple topic."""
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.langgraph_lesson_planner_tool.run_langgraph_lesson_planner_agent",
                new=_fake_langgraph_runner,
            ),
        ):
            outputs, logs = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt("photosynthesis")))

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
                "massgen.tool._extraframework_agents.langgraph_lesson_planner_tool.run_langgraph_lesson_planner_agent",
                new=_fake_langgraph_runner,
            ),
        ):
            outputs, _ = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt("fractions")))

        result = outputs[-1]
        assert isinstance(result, ExecutionResult)
        assert len(result.output_blocks) > 0
        assert not result.output_blocks[0].data.startswith("Error:")

    @pytest.mark.asyncio
    async def test_missing_api_key_error(self):
        """Test error handling when API key is missing."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            outputs, _ = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt("test topic")))

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
                "massgen.tool._extraframework_agents.langgraph_lesson_planner_tool.run_langgraph_lesson_planner_agent",
                new=_fake_langgraph_runner,
            ),
        ):
            for topic in topics:
                outputs, _ = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt(topic)))
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
            outputs, _ = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt(topic)))
            return outputs[-1]

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch(
                "massgen.tool._extraframework_agents.langgraph_lesson_planner_tool.run_langgraph_lesson_planner_agent",
                new=_fake_langgraph_runner,
            ),
        ):
            results = await asyncio.gather(*[_run_topic(topic) for topic in topics])

        assert len(results) == len(topics)
        for topic, result in zip(topics, results):
            assert isinstance(result, ExecutionResult)
            assert len(result.output_blocks) > 0
            assert not result.output_blocks[0].data.startswith("Error:")
            assert topic.lower() in result.output_blocks[0].data.lower()


class TestLangGraphToolIntegration:
    """Test LangGraph tool integration with MassGen tool system."""

    def test_tool_function_signature(self):
        """Test that the tool has the correct async generator signature."""
        import collections.abc
        import inspect
        from typing import get_origin

        # The function is an async generator (uses yield), not a coroutine
        assert inspect.isasyncgenfunction(langgraph_lesson_planner)

        # Get function signature
        sig = inspect.signature(langgraph_lesson_planner)
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
                "massgen.tool._extraframework_agents.langgraph_lesson_planner_tool.run_langgraph_lesson_planner_agent",
                new=_fake_langgraph_runner,
            ),
        ):
            outputs, _ = await _collect_outputs(langgraph_lesson_planner(prompt=_build_prompt("test")))

        result = outputs[-1]
        assert hasattr(result, "output_blocks")
        assert isinstance(result.output_blocks, list)
        assert len(result.output_blocks) > 0
        assert not result.output_blocks[0].data.startswith("Error:")

        assert isinstance(result.output_blocks[0], TextContent)
        assert hasattr(result.output_blocks[0], "data")
        assert isinstance(result.output_blocks[0].data, str)


class TestLangGraphToolWithBackend:
    """Test LangGraph tool with ResponseBackend."""

    @pytest.mark.asyncio
    async def test_backend_registration(self):
        """Test registering LangGraph tool with ResponseBackend."""
        from massgen.backend.response import ResponseBackend

        api_key = os.getenv("OPENAI_API_KEY", "test-key")

        # Import the tool
        from massgen.tool._extraframework_agents.langgraph_lesson_planner_tool import (
            langgraph_lesson_planner,
        )

        # Register with backend
        backend = ResponseBackend(
            api_key=api_key,
            custom_tools=[
                {
                    "func": langgraph_lesson_planner,
                    "description": "Create a comprehensive lesson plan using LangGraph state graph",
                },
            ],
        )

        # Verify tool is registered (with custom_tool__ prefix)
        assert "custom_tool__langgraph_lesson_planner" in backend._custom_tool_names

        # Verify schema generation
        schemas = backend._get_custom_tools_schemas()
        assert len(schemas) >= 1

        # Find our tool's schema (with custom_tool__ prefix)
        langgraph_schema = None
        for schema in schemas:
            if schema["function"]["name"] == "custom_tool__langgraph_lesson_planner":
                langgraph_schema = schema
                break

        assert langgraph_schema is not None
        assert langgraph_schema["type"] == "function"
        assert "parameters" in langgraph_schema["function"]
