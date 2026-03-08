#!/usr/bin/env python3
"""
Streaming Buffer Reasoning Test

Tests that reasoning/thinking content is properly captured in the streaming buffer
across all providers that support it.

Providers tested:
1. Claude - Extended thinking (thinking_delta)
2. Gemini - Thinking parts (thought=true)
3. OpenAI - Reasoning summaries (response.reasoning_summary_text.delta)
4. Grok - reasoning_content (xAI)
5. OpenRouter/OpenAI - reasoning_details
6. OpenRouter/Qwen - reasoning_content

Usage:
    uv run python scripts/test_streaming_buffer_reasoning.py
    uv run python scripts/test_streaming_buffer_reasoning.py --provider claude
    uv run python scripts/test_streaming_buffer_reasoning.py --prompt "Explain why the sky is blue"
    uv run python scripts/test_streaming_buffer_reasoning.py --provider gemini --prompt "What is 2+2?"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Default prompt that encourages reasoning -- taken from https://huggingface.co/datasets/lmms-lab/imo-2025/viewer/default/train?views%5B%5D=train&row=2 for a hard math problem to ensure reasoning.
DEFAULT_PROMPT = r"""Let $\mathbb{N}$ denote the set of positive integers. A function $f: \mathbb{N} \to \mathbb{N}$ is said to be *bonza* if

$$f(a) \text{ divides } b^a - f(b)^{f(a)}$$

for all positive integers $a$ and $b$.

Determine the smallest real constant $c$ such that $f(n) \leq cn$ for all bonza functions $f$ and all positive integers $n$."""

# Global to hold the current prompt (set from CLI)
PROMPT: str = DEFAULT_PROMPT


def print_header(title: str) -> None:
    """Print a section header."""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80 + "\n")


def print_buffer(buffer: str | None, provider: str) -> bool:
    """Print buffer content and check for reasoning.

    Returns True if [Reasoning] found in buffer.
    """
    print("\n" + "-" * 40)
    print(f"Buffer Content ({provider}):")
    print("-" * 40)

    if buffer:
        print(buffer)
        has_reasoning = "[Reasoning]" in buffer
        print("-" * 40)
        if has_reasoning:
            print(f"✅ SUCCESS: [Reasoning] block found in {provider} buffer!")
        else:
            print(f"⚠️  WARNING: No [Reasoning] block in {provider} buffer")
            print("   (Model may not have used reasoning for this prompt)")
        return has_reasoning
    else:
        print("(empty)")
        print("-" * 40)
        print(f"❌ FAILED: Buffer is empty for {provider}")
        return False


async def test_claude_reasoning() -> bool:
    """Test Claude extended thinking buffer capture."""
    print_header("Testing Claude Extended Thinking (claude-haiku-4-5-20251001)")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⏭️  Skipping: ANTHROPIC_API_KEY not set")
        return False

    from massgen.backend.claude import ClaudeBackend

    backend = ClaudeBackend(api_key=api_key)

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with extended thinking...")
    print("Model: claude-haiku-4-5-20251001")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="claude-haiku-4-5-20251001",
            # Enable extended thinking
            thinking={"type": "enabled", "budget_tokens": 1024},
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[THINKING] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "Claude")


async def test_gemini_reasoning() -> bool:
    """Test Gemini thinking buffer capture."""
    print_header("Testing Gemini Thinking (gemini-3-flash-preview)")

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("⏭️  Skipping: GEMINI_API_KEY/GOOGLE_API_KEY not set")
        return False

    from massgen.backend.gemini import GeminiBackend

    backend = GeminiBackend(api_key=api_key)

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with thinking...")
    print("Model: gemini-3-flash-preview")
    print("Config: include_thoughts=True (enables thought summaries)")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="gemini-3-flash-preview",
            # Enable thinking summaries in responses
            include_thoughts=True,
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[THINKING] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "Gemini")


async def test_openai_reasoning() -> bool:
    """Test OpenAI reasoning buffer capture."""
    print_header("Testing OpenAI Reasoning (gpt-5-nano)")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⏭️  Skipping: OPENAI_API_KEY not set")
        return False

    from massgen.backend.response import ResponseBackend

    backend = ResponseBackend(api_key=api_key)

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with reasoning...")
    print("Model: gpt-5-nano")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="gpt-5-nano",
            # Enable reasoning summaries for o-series models
            reasoning={"summary": "auto"},
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[REASONING] {chunk.content}", end="", flush=True)
            elif chunk.type == "reasoning_summary":
                print(f"[SUMMARY] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "OpenAI")


async def test_openrouter_openai() -> bool:
    """Test OpenRouter OpenAI reasoning_details buffer capture."""
    print_header("Testing OpenRouter OpenAI (openai/gpt-5-mini)")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⏭️  Skipping: OPENROUTER_API_KEY not set")
        return False

    from massgen.backend.chat_completions import ChatCompletionsBackend

    backend = ChatCompletionsBackend(
        type="openrouter",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with reasoning_details...")
    print("Model: openai/gpt-5-mini (OpenAI reasoning model via OpenRouter)")
    print("Config: reasoning={'effort': 'high'}, include_reasoning=True")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="openai/gpt-5-mini",
            # Enable reasoning for gpt-5-mini via OpenRouter
            # Try both reasoning parameter and include_reasoning
            extra_body={
                "reasoning": {"effort": "high"},
                "include_reasoning": True,
            },
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[REASONING] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "OpenRouter/OpenAI")


async def test_openrouter_qwen() -> bool:
    """Test OpenRouter Qwen reasoning buffer capture."""
    print_header("Testing OpenRouter Qwen (qwen/qwen3-30b-a3b)")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⏭️  Skipping: OPENROUTER_API_KEY not set")
        return False

    from massgen.backend.chat_completions import ChatCompletionsBackend

    backend = ChatCompletionsBackend(
        type="openrouter",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with reasoning_content...")
    print("Model: qwen/qwen3-30b-a3b")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="qwen/qwen3-30b-a3b",
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[REASONING] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "OpenRouter/Qwen")


async def test_grok_reasoning() -> bool:
    """Test Grok reasoning buffer capture."""
    print_header("Testing Grok (grok-3-mini)")

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        print("⏭️  Skipping: XAI_API_KEY not set")
        return False

    from massgen.backend.grok import GrokBackend

    backend = GrokBackend(api_key=api_key)

    messages = [
        {"role": "user", "content": PROMPT},
    ]

    print("Streaming response with reasoning_content...")
    print("Model: grok-3-mini")
    print("Config: reasoning_effort='high'")
    print("-" * 40)

    chunk_count = 0
    chunk_types_seen = set()
    try:
        async for chunk in backend.stream_with_tools(
            messages,
            [],
            model="grok-3-mini",
            # Enable high reasoning effort for Grok 3 Mini
            reasoning_effort="high",
        ):
            chunk_count += 1
            chunk_types_seen.add(chunk.type)
            if chunk.type == "content":
                print(chunk.content, end="", flush=True)
            elif chunk.type == "reasoning":
                print(f"[REASONING] {chunk.content}", end="", flush=True)
            elif chunk.type == "error":
                print(f"\n[ERROR] {getattr(chunk, 'error', chunk)}")
            elif chunk.type == "done":
                break
        print(f"\n(Received {chunk_count} chunks, types: {chunk_types_seen})")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

    buffer = backend._get_streaming_buffer()
    return print_buffer(buffer, "Grok")


async def main():
    """Run reasoning buffer tests."""
    global PROMPT

    parser = argparse.ArgumentParser(description="Test streaming buffer reasoning capture")
    parser.add_argument(
        "--provider",
        choices=["claude", "gemini", "openai", "grok", "openrouter-openai", "openrouter-qwen", "all"],
        default="all",
        help="Which provider to test (default: all)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_PROMPT,
        help=f"Custom prompt to use (default: '{DEFAULT_PROMPT}')",
    )
    args = parser.parse_args()

    # Set global prompt from CLI
    PROMPT = args.prompt

    print_header("Streaming Buffer Reasoning Test")
    print("This test verifies that reasoning/thinking content is captured in the")
    print("streaming buffer for compression recovery.\n")
    print(f"Prompt: {PROMPT}\n")
    print("Looking for [Reasoning] blocks in the buffer output.\n")

    results = {}

    if args.provider in ("claude", "all"):
        results["Claude"] = await test_claude_reasoning()

    if args.provider in ("gemini", "all"):
        results["Gemini"] = await test_gemini_reasoning()

    if args.provider in ("openai", "all"):
        results["OpenAI"] = await test_openai_reasoning()

    if args.provider in ("grok", "all"):
        results["Grok"] = await test_grok_reasoning()

    if args.provider in ("openrouter-openai", "all"):
        results["OpenRouter/OpenAI"] = await test_openrouter_openai()

    if args.provider in ("openrouter-qwen", "all"):
        results["OpenRouter/Qwen"] = await test_openrouter_qwen()

    # Print summary
    print_header("Summary")

    for provider, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL/SKIP"
        print(f"  {provider}: {status}")

    passed = sum(1 for s in results.values() if s)
    total = len(results)
    print(f"\n  Total: {passed}/{total} providers with reasoning in buffer")

    print("\n" + "=" * 80)
    print("Test complete!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
