"""Regression coverage for ChatCompletionsBackend provider wiring."""

import pytest

from massgen.backend import ChatCompletionsBackend
from massgen.backend.base_with_custom_tool_and_mcp import (
    BACKGROUND_TOOL_CANCEL_NAME,
    BACKGROUND_TOOL_LIST_NAME,
    BACKGROUND_TOOL_RESULT_NAME,
    BACKGROUND_TOOL_START_NAME,
    BACKGROUND_TOOL_STATUS_NAME,
    BACKGROUND_TOOL_WAIT_NAME,
)


def test_openai_backend_defaults():
    """Default backend should use generic provider settings."""
    backend = ChatCompletionsBackend()
    assert backend.get_provider_name() == "ChatCompletion"
    assert "base_url" not in backend.config
    assert backend.estimate_tokens("Hello world, how are you doing today?") > 0
    assert backend.calculate_cost(1000, 500, "gpt-4o-mini") >= 0


def test_together_ai_backend():
    """Provider should be inferred from Together base URL."""
    backend = ChatCompletionsBackend(
        base_url="https://api.together.xyz/v1",
        api_key="test-key",
    )
    assert backend.get_provider_name() == "Together AI"
    assert backend.config["base_url"] == "https://api.together.xyz/v1"
    assert backend.calculate_cost(1000, 500, "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo") >= 0


def test_cerebras_backend():
    """Provider should be inferred from Cerebras base URL."""
    backend = ChatCompletionsBackend(
        base_url="https://api.cerebras.ai/v1",
        api_key="test-key",
    )
    assert backend.get_provider_name() == "Cerebras AI"
    assert backend.config["base_url"] == "https://api.cerebras.ai/v1"


@pytest.mark.asyncio
async def test_tool_conversion_via_api_params_handler():
    """Response-style function tools are converted via ChatCompletionsAPIParamsHandler."""
    backend = ChatCompletionsBackend(api_key="test-key")
    tools = [
        {
            "type": "function",
            "name": "calculate_area",
            "description": "Calculate area of rectangle",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
                "required": ["width", "height"],
            },
        },
    ]

    api_params = await backend.api_params_handler.build_api_params(
        messages=[{"role": "user", "content": "Calculate area for width 5 and height 3"}],
        tools=tools,
        all_params={"model": "gpt-4o-mini"},
    )

    assert "tools" in api_params
    tool_names = {tool["function"]["name"] for tool in api_params["tools"] if tool.get("type") == "function" and "function" in tool}
    assert "calculate_area" in tool_names
    assert BACKGROUND_TOOL_START_NAME in tool_names
    assert BACKGROUND_TOOL_STATUS_NAME in tool_names
    assert BACKGROUND_TOOL_RESULT_NAME in tool_names
    assert BACKGROUND_TOOL_CANCEL_NAME in tool_names
    assert BACKGROUND_TOOL_LIST_NAME in tool_names
    assert BACKGROUND_TOOL_WAIT_NAME in tool_names
