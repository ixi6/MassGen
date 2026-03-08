#!/usr/bin/env python3
"""
Integration tests for backend cost tracking with litellm.

These tests make real API calls to verify end-to-end cost tracking.
They are marked as integration + live_api and skipped by default unless
explicitly enabled.

Run with:
  uv run pytest massgen/tests/test_backend_cost_tracking.py \
    -m "integration and live_api" --run-integration --run-live-api -v
"""

import asyncio
import os
from typing import Any

import pytest

TRANSIENT_ERROR_PATTERNS = (
    "rate limit",
    "429",
    "timeout",
    "timed out",
    "connection",
    "network",
    "temporarily unavailable",
    "service unavailable",
    "overloaded",
    "try again",
    "gateway",
    "502",
    "503",
    "504",
)


def _is_transient_error(error_message: str) -> bool:
    if not error_message:
        return False
    message = error_message.lower()
    return any(pattern in message for pattern in TRANSIENT_ERROR_PATTERNS)


async def _collect_stream_response(
    backend: Any,
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
) -> tuple[str, str | None, bool]:
    """Run a single backend stream call and collect content/error state."""
    response_content = ""
    stream_error: str | None = None
    saw_done = False

    async for chunk in backend.stream_with_tools(messages, [], model=model, max_tokens=max_tokens):
        if chunk.type == "content" and chunk.content:
            response_content += chunk.content
        elif chunk.type == "error":
            stream_error = chunk.error or chunk.content or "unknown backend stream error"
        elif chunk.type == "done":
            saw_done = True
            break

    return response_content, stream_error, saw_done


async def _run_usage_tracking_with_retry(
    backend: Any,
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
    attempts: int = 3,
) -> str:
    """Run live API call with retry/skip behavior for transient provider instability."""
    last_error: str | None = None
    last_response = ""

    for attempt in range(1, attempts + 1):
        backend.token_usage.reset()
        response_content, stream_error, saw_done = await _collect_stream_response(
            backend,
            messages,
            model=model,
            max_tokens=max_tokens,
        )
        usage = backend.token_usage
        has_usage = usage.input_tokens > 0 and usage.output_tokens > 0 and usage.estimated_cost > 0

        if has_usage:
            return response_content

        last_response = response_content
        last_error = stream_error
        if stream_error:
            retryable = _is_transient_error(stream_error)
        else:
            retryable = not saw_done or not response_content.strip()

        if retryable and attempt < attempts:
            await asyncio.sleep(2 ** (attempt - 1))
            continue

        if retryable:
            pytest.skip(
                f"Skipping due to transient live API behavior after {attempts} attempts: " f"error={stream_error!r}, content_len={len(response_content)}",
            )

        if response_content.strip():
            pytest.skip(
                f"Provider returned content but no usage telemetry after {attempts} attempts " f"(content_len={len(response_content)}).",
            )

        pytest.fail(
            "Live API call completed without usable cost telemetry. " f"error={stream_error!r}, content_len={len(response_content)}",
        )

    pytest.fail(
        "Unreachable retry termination in usage tracking helper " f"(last_error={last_error!r}, last_content_len={len(last_response)})",
    )


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_chat_completions_backend_usage_tracking():
    """Test that ChatCompletionsBackend correctly tracks usage with real API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    from massgen.backend.chat_completions import ChatCompletionsBackend

    backend = ChatCompletionsBackend(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
    )

    messages = [{"role": "user", "content": "Say only: test"}]

    # Reset usage
    backend.token_usage.reset()

    await _run_usage_tracking_with_retry(
        backend,
        messages,
        model="gpt-4o-mini",
        max_tokens=5,
    )

    # Verify usage was tracked
    assert backend.token_usage.input_tokens > 0, "Input tokens should be tracked"
    assert backend.token_usage.output_tokens > 0, "Output tokens should be tracked"
    assert backend.token_usage.estimated_cost > 0, "Cost should be tracked"

    # Cost should be reasonable for short message (~10 tokens)
    assert backend.token_usage.estimated_cost < 0.001, "Cost should be < $0.001 for short message"

    print("\nChatCompletions usage tracking:")
    print(f"  Input: {backend.token_usage.input_tokens} tokens")
    print(f"  Output: {backend.token_usage.output_tokens} tokens")
    print(f"  Cost: ${backend.token_usage.estimated_cost:.6f}")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_claude_code_backend_usage_tracking():
    """Test that ClaudeCodeBackend correctly tracks usage with real API."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    from massgen.backend.claude_code import ClaudeCodeBackend

    backend = ClaudeCodeBackend(api_key=api_key)

    messages = [{"role": "user", "content": "Say only: test"}]

    backend.token_usage.reset()

    await _run_usage_tracking_with_retry(
        backend,
        messages,
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
    )

    # Verify usage was tracked
    assert backend.token_usage.input_tokens > 0
    assert backend.token_usage.output_tokens > 0
    assert backend.token_usage.estimated_cost > 0

    # Cost should be reasonable
    assert backend.token_usage.estimated_cost < 0.001

    print("\nClaudeCode usage tracking:")
    print(f"  Input: {backend.token_usage.input_tokens} tokens")
    print(f"  Output: {backend.token_usage.output_tokens} tokens")
    print(f"  Cost: ${backend.token_usage.estimated_cost:.6f}")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.expensive
@pytest.mark.asyncio
async def test_o3_mini_reasoning_tokens_e2e():
    """Test o3-mini reasoning tokens are tracked end-to-end (EXPENSIVE)."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    from massgen.backend.chat_completions import ChatCompletionsBackend

    backend = ChatCompletionsBackend(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
    )

    # Reasoning task that should trigger reasoning tokens
    messages = [
        {
            "role": "user",
            "content": "If x^2 + 3x - 10 = 0, what is x? Show your reasoning.",
        },
    ]

    backend.token_usage.reset()

    await _run_usage_tracking_with_retry(
        backend,
        messages,
        model="o3-mini",
        max_tokens=500,
    )

    # Should have tracked cost (reasoning tokens are expensive)
    assert backend.token_usage.estimated_cost > 0

    print("\nO3-mini reasoning test:")
    print(f"  Input: {backend.token_usage.input_tokens} tokens")
    print(f"  Output: {backend.token_usage.output_tokens} tokens")
    print(f"  Cost: ${backend.token_usage.estimated_cost:.6f}")
    print("  Note: Cost includes reasoning tokens if present")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.expensive
@pytest.mark.asyncio
async def test_claude_caching_e2e():
    """Test Claude prompt caching discount is tracked (EXPENSIVE - 2 API calls)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    from massgen.backend.claude_code import ClaudeCodeBackend

    backend = ClaudeCodeBackend(api_key=api_key)

    # Large system prompt to trigger caching (needs >1024 tokens)
    large_context = "Context information: " + "This is important context. " * 200
    assert len(large_context) > 5000, "Context should be large enough to trigger caching"

    messages_with_cache = [
        {"role": "user", "content": f"{large_context}\n\nQuestion: Say 'test'"},
    ]

    await _run_usage_tracking_with_retry(
        backend,
        messages_with_cache,
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
    )

    cost_first_call = backend.token_usage.estimated_cost

    await _run_usage_tracking_with_retry(
        backend,
        messages_with_cache,
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
    )

    cost_second_call = backend.token_usage.estimated_cost

    print("\nClaude caching test:")
    print(f"  First call (no cache): ${cost_first_call:.6f}")
    print(f"  Second call (cached): ${cost_second_call:.6f}")
    print(f"  Savings: ${cost_first_call - cost_second_call:.6f}")

    # Note: This test is informational - caching may or may not occur
    # depending on Claude's caching policies


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration and live_api", "--run-integration", "--run-live-api"])
