"""Parity tests for background tool lifecycle exposure across API handlers."""

from __future__ import annotations

import pytest

from massgen.backend import ChatCompletionsBackend, ResponseBackend
from massgen.backend.base_with_custom_tool_and_mcp import (
    BACKGROUND_TOOL_CANCEL_NAME,
    BACKGROUND_TOOL_LIST_NAME,
    BACKGROUND_TOOL_RESULT_NAME,
    BACKGROUND_TOOL_START_NAME,
    BACKGROUND_TOOL_STATUS_NAME,
    BACKGROUND_TOOL_WAIT_NAME,
)
from massgen.tool._result import ExecutionResult, TextContent


def _sample_tool(message: str = "ok") -> ExecutionResult:
    return ExecutionResult(output_blocks=[TextContent(data=message)])


def _extract_function_tool_names(tool_defs: list[dict]) -> set[str]:
    names: set[str] = set()
    for tool_def in tool_defs:
        if tool_def.get("type") != "function":
            continue
        if "function" in tool_def:
            name = tool_def.get("function", {}).get("name")
        else:
            name = tool_def.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _assert_background_lifecycle_names(tool_names: set[str]) -> None:
    assert BACKGROUND_TOOL_START_NAME in tool_names
    assert BACKGROUND_TOOL_STATUS_NAME in tool_names
    assert BACKGROUND_TOOL_RESULT_NAME in tool_names
    assert BACKGROUND_TOOL_CANCEL_NAME in tool_names
    assert BACKGROUND_TOOL_LIST_NAME in tool_names
    assert BACKGROUND_TOOL_WAIT_NAME in tool_names


@pytest.mark.asyncio
async def test_chat_completions_api_params_include_background_lifecycle_tools():
    backend = ChatCompletionsBackend(
        api_key="test-key",
        custom_tools=[{"func": _sample_tool}],
    )

    api_params = await backend.api_params_handler.build_api_params(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        all_params={"model": "gpt-4o-mini"},
    )

    tool_names = _extract_function_tool_names(api_params.get("tools", []))
    _assert_background_lifecycle_names(tool_names)


@pytest.mark.asyncio
async def test_response_api_params_include_background_lifecycle_tools():
    backend = ResponseBackend(
        api_key="test-key",
        custom_tools=[{"func": _sample_tool}],
    )

    api_params = await backend.api_params_handler.build_api_params(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        all_params={"model": "gpt-4.1"},
    )

    tool_names = _extract_function_tool_names(api_params.get("tools", []))
    _assert_background_lifecycle_names(tool_names)
