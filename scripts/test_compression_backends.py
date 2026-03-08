#!/usr/bin/env python3
"""
Manual test script for reactive compression across multiple backends.

WARNING: This script makes real API calls and costs money. It is intentionally
placed in scripts/ (not massgen/tests/) to exclude it from the normal pytest suite.

This script pre-fills context with source files to reach a target token count,
then runs a query to trigger compression. Each backend has an optimized default
fill ratio that reliably triggers compression based on testing.

Usage:
    # Test all backends with per-backend optimal fill ratios
    uv run python scripts/test_compression_backends.py

    # Test specific backend
    uv run python scripts/test_compression_backends.py --backend gemini

    # Custom fill ratio (overrides per-backend default)
    uv run python scripts/test_compression_backends.py --backend openai --fill-ratio 1.0

    # List available backends with their default fill ratios
    uv run python scripts/test_compression_backends.py --list-backends

See docs/dev_notes/context_compression_design.md for architecture details.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Add massgen to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from massgen.token_manager import TokenCostCalculator  # noqa: E402

# Backend configurations for testing compression
# Context window is looked up dynamically via TokenCostCalculator
# default_fill_ratio: The fill ratio needed to reliably trigger compression for each backend
# (determined through testing - some backends need higher ratios due to context window differences)
BACKEND_CONFIGS: dict[str, dict[str, Any]] = {
    "openai": {
        "type": "openai",
        "model": "gpt-4o-mini",
        "provider": "OpenAI",
        "description": "OpenAI ResponseBackend with Response API",
        "default_fill_ratio": 0.95,  # 128k context, 95% reliably triggers compression
    },
    "claude": {
        "type": "claude",
        "model": "claude-haiku-4-5-20251001",
        "provider": "Anthropic",
        "description": "Claude Messages API via CustomToolAndMCPBackend",
        "default_fill_ratio": 1.5,  # 200k context, needs 150% to exceed with available files
    },
    "gemini": {
        "type": "gemini",
        "model": "gemini-2.0-flash",
        "provider": "Google",
        "description": "Gemini native SDK (1M context, 4M TPM)",
        "default_fill_ratio": 0.95,  # 1M context, 95% triggers due to tokenizer variance
    },
    "openrouter": {
        "type": "chatcompletion",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "provider": "OpenAI",  # For pricing lookup
        "api_key_env": "OPENROUTER_API_KEY",
        "description": "OpenRouter via ChatCompletionsBackend",
        "default_fill_ratio": 0.95,  # Same as OpenAI (uses gpt-4o-mini)
    },
    "grok": {
        "type": "grok",
        "model": "grok-3-mini",
        "provider": "xAI",
        "description": "Grok via GrokBackend (inherits ChatCompletions)",
        "default_fill_ratio": 3.0,  # 131k context but handles overflow gracefully, needs 3x to trigger
    },
}

# Files to use for filling context (ordered by size, largest first for efficiency)
# Include files from across the entire massgen codebase to reach high token counts
CONTEXT_FILL_FILES = [
    # Backend files (largest)
    "massgen/backend/base_with_custom_tool_and_mcp.py",
    "massgen/backend/gemini.py",
    "massgen/backend/response.py",
    "massgen/backend/claude.py",
    "massgen/backend/chat_completions.py",
    "massgen/backend/base.py",
    "massgen/backend/grok.py",
    "massgen/backend/_compression_utils.py",
    "massgen/backend/_context_errors.py",
    "massgen/backend/_api_params_handler_base.py",
    "massgen/backend/_mcp_handler.py",
    "massgen/backend/_tool_handler.py",
    # Frontend files
    "massgen/frontend/coordination_ui.py",
    "massgen/frontend/rich_terminal_ui.py",
    "massgen/frontend/base_ui.py",
    # Formatter files
    "massgen/formatter/_claude_formatter.py",
    "massgen/formatter/_gemini_formatter.py",
    "massgen/formatter/_response_formatter.py",
    "massgen/formatter/_chat_completions_formatter.py",
    "massgen/formatter/base_formatter.py",
    # Token manager
    "massgen/token_manager/token_manager.py",
    "massgen/token_manager/token_cost_calculator.py",
    # Orchestrator
    "massgen/orchestrator/base_orchestrator.py",
    "massgen/orchestrator/single_agent_orchestrator.py",
    "massgen/orchestrator/multi_agent_orchestrator.py",
    # Config
    "massgen/config/loader.py",
    "massgen/config/schema.py",
    # MCP
    "massgen/mcp/mcp_manager.py",
    "massgen/mcp/mcp_server.py",
    # Tool files
    "massgen/tool/_code_based_example/code_tools.py",
    "massgen/tool/_multimodal_tools/image_tools.py",
    "massgen/tool/_web_tools/web_crawler.py",
    # CLI
    "massgen/cli/main.py",
    "massgen/cli/commands.py",
    # Additional utility files
    "massgen/utils/logging.py",
    "massgen/utils/docker.py",
    "massgen/utils/workspace.py",
]


def get_token_calculator() -> TokenCostCalculator:
    """Get token calculator instance."""
    return TokenCostCalculator()


def estimate_tokens(text: str) -> int:
    """Estimate token count for text."""
    calc = get_token_calculator()
    return calc.estimate_tokens(text)


def get_context_window(provider: str, model: str) -> int:
    """Get context window size for a model using TokenCostCalculator.

    Args:
        provider: Provider name (e.g., "OpenAI", "Anthropic")
        model: Model name

    Returns:
        Context window size in tokens, or default 128000 if not found
    """
    calc = get_token_calculator()
    pricing = calc.get_model_pricing(provider, model)

    if pricing and pricing.context_window:
        return pricing.context_window

    # Fallback defaults
    print(f"  Warning: Could not find context window for {provider}/{model}, using 128000")
    return 128000


def load_files_to_target_tokens(
    target_tokens: int,
    base_path: Path,
) -> tuple[str, int, list[str]]:
    """Load files until we reach target token count.

    If unique files aren't enough, repeats content to reach the target.
    This is necessary for testing large-context models (1M+ tokens).

    Args:
        target_tokens: Target number of tokens to reach
        base_path: Base path for resolving file paths

    Returns:
        Tuple of (combined_content, actual_tokens, files_used)
    """
    content_parts = []
    total_tokens = 0
    files_used = []

    # First pass: load unique files
    for file_path in CONTEXT_FILL_FILES:
        full_path = base_path / file_path
        if not full_path.exists():
            print(f"  Warning: {file_path} not found, skipping")
            continue

        file_content = full_path.read_text()
        file_tokens = estimate_tokens(file_content)

        # Add file with header
        file_section = f"\n\n{'='*80}\n# FILE: {file_path}\n{'='*80}\n\n{file_content}"
        content_parts.append(file_section)
        total_tokens += file_tokens
        files_used.append(file_path)

        print(f"  Added {file_path}: {file_tokens:,} tokens (total: {total_tokens:,})")

        if total_tokens >= target_tokens:
            break

    # If we haven't reached target and have content, repeat it
    MAX_REPEATS = 10  # Allow enough repeats to fill 1M+ context windows
    if total_tokens < target_tokens and content_parts:
        unique_content = "\n".join(content_parts)
        unique_tokens = total_tokens
        repeat_count = 1

        print(f"\n  Unique content: {unique_tokens:,} tokens, target: {target_tokens:,}")
        print(f"  Repeating content to reach target (max {MAX_REPEATS}x)...")

        # Only add repeats if adding one won't exceed target (stay just under)
        while total_tokens + unique_tokens <= target_tokens and repeat_count < MAX_REPEATS:
            repeat_count += 1
            # Add repeated content with a separator
            repeat_section = f"\n\n{'='*80}\n# REPEATED CONTENT (iteration {repeat_count})\n{'='*80}\n{unique_content}"
            content_parts.append(repeat_section)
            total_tokens += unique_tokens
            files_used.append(f"[repeat-{repeat_count}]")

        if total_tokens < target_tokens * 0.8:  # Less than 80% of target
            print(f"  Warning: Could only reach {total_tokens:,} tokens ({total_tokens*100//target_tokens}% of target)")
            print("           Model has very large context window - compression may not trigger")
        else:
            print(f"  Repeated {repeat_count}x to reach {total_tokens:,} tokens")

    return "\n".join(content_parts), total_tokens, files_used


def build_prefilled_messages(
    file_content: str,
    query: str,
) -> list[dict[str, Any]]:
    """Build messages with pre-filled context.

    Structure:
    1. System message with instructions
    2. User message with file contents (simulating tool results)
    3. Assistant acknowledgment
    4. User query to trigger more work (and compression)
    """
    system_message = {
        "role": "system",
        "content": """You are a code analysis assistant. You have been given source code files to analyze.
Your task is to read and understand the code, then answer questions about it.
Be thorough and detailed in your analysis.""",
    }

    # Simulate previous conversation where files were read
    user_files_message = {
        "role": "user",
        "content": f"""I've loaded the following source code files for you to analyze:

{file_content}

Please acknowledge that you've received these files and are ready to analyze them.""",
    }

    assistant_ack = {
        "role": "assistant",
        "content": (
            "I've received and reviewed the source code files you've provided. "
            "I can see multiple Python files from the massgen project, including backend implementations, "
            "compression utilities, and formatters. I'm ready to analyze these files and answer your questions."
        ),
    }

    # The query that should trigger compression when model tries to respond
    user_query = {
        "role": "user",
        "content": query,
    }

    return [system_message, user_files_message, assistant_ack, user_query]


# Default query - general summary request
DEFAULT_QUERY = """Based on all the source code files above, please provide a comprehensive summary:

1. What is the overall purpose of this codebase?
2. What are the main components and how do they interact?
3. What patterns and design decisions do you observe?

Please be thorough and detailed in your analysis."""


async def test_backend_compression(
    backend_name: str,
    config: dict[str, Any],
    fill_ratio: float = 0.8,
    base_path: Path | None = None,
) -> dict[str, Any]:
    """Test compression for a single backend.

    Args:
        backend_name: Name of the backend to test
        config: Backend configuration
        fill_ratio: What fraction of context window to fill (default 0.8 = 80%)
        base_path: Base path for file resolution

    Returns:
        Test results dictionary
    """
    if base_path is None:
        base_path = Path(__file__).parent.parent

    # Look up context window dynamically
    provider = config.get("provider", "OpenAI")
    model = config.get("model")
    context_window = get_context_window(provider, model)

    # Calculate target tokens based on fill_ratio, but cap at max_test_tokens if specified
    target_tokens = int(context_window * fill_ratio)
    max_test_tokens = config.get("max_test_tokens")
    if max_test_tokens and target_tokens > max_test_tokens:
        target_tokens = max_test_tokens

    print(f"\n{'='*60}")
    print(f"Testing: {backend_name}")
    print(f"Description: {config.get('description', 'N/A')}")
    print(f"Model: {model}")
    print(f"Context window: {context_window:,} tokens (from TokenCostCalculator)")
    if max_test_tokens:
        print(f"Target fill: {target_tokens:,} tokens (capped for rate limits)")
    else:
        print(f"Target fill: {target_tokens:,} tokens ({fill_ratio*100:.0f}%)")
    print(f"{'='*60}")

    # Load files to fill context
    print("\nLoading files to fill context...")
    file_content, actual_tokens, files_used = load_files_to_target_tokens(
        target_tokens,
        base_path,
    )

    print(f"\nLoaded {len(files_used)} files with {actual_tokens:,} tokens")

    # Build pre-filled messages with default query
    messages = build_prefilled_messages(file_content, DEFAULT_QUERY)

    # Estimate total message tokens
    total_message_tokens = sum(estimate_tokens(json.dumps(m)) for m in messages)
    print(f"Total message tokens: {total_message_tokens:,}")

    # Create backend and run
    result = {
        "backend": backend_name,
        "model": model,
        "context_window": context_window,
        "target_tokens": target_tokens,
        "actual_tokens": actual_tokens,
        "files_used": len(files_used),
        "compression_triggered": False,
        "error": None,
        "duration_seconds": 0,
    }

    try:
        # Import backend classes
        from massgen.backend import (
            ChatCompletionsBackend,
            ClaudeBackend,
            GeminiBackend,
            GrokBackend,
            ResponseBackend,
        )

        # Map backend type to class
        backend_type = config["type"]
        model = config["model"]

        print(f"\nCreating {backend_name} backend...")

        if backend_type == "openai":
            backend = ResponseBackend(model=model)
        elif backend_type == "claude":
            backend = ClaudeBackend(model=model)
        elif backend_type == "gemini":
            backend = GeminiBackend(model=model)
        elif backend_type == "grok":
            backend = GrokBackend(model=model)
        elif backend_type == "chatcompletion":
            base_url = config.get("base_url")
            # Get API key from environment if specified
            api_key = None
            if api_key_env := config.get("api_key_env"):
                import os

                api_key = os.environ.get(api_key_env)
                if not api_key:
                    raise ValueError(f"Environment variable {api_key_env} not set")
            backend = ChatCompletionsBackend(model=model, base_url=base_url, api_key=api_key)
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")

        # Set compression settings
        backend.set_compression_check(
            threshold=0.5,
            context_window=context_window,
            target_ratio=0.2,
        )

        print("Starting streaming (watching for compression)...")
        start_time = time.time()

        content_chunks = []
        chunk_types_seen = set()
        async for chunk in backend.stream_with_tools(messages, tools=[]):
            # Normalize chunk type to string for comparison
            chunk_type = str(chunk.type.value) if hasattr(chunk.type, "value") else str(chunk.type)
            chunk_types_seen.add(chunk_type)

            if chunk_type == "compression_status":
                print(f"\n  >>> COMPRESSION: {chunk.status} - {chunk.content}")
                result["compression_triggered"] = True
            elif chunk_type in ("content", "text") and chunk.content:
                content_chunks.append(chunk.content)
                # Print progress dots
                if len(content_chunks) % 50 == 0:
                    print(".", end="", flush=True)
            elif chunk_type == "error":
                print(f"\n  >>> ERROR: {chunk.error}")
                result["error"] = chunk.error

        print(f"\n  Chunk types seen: {chunk_types_seen}")

        result["duration_seconds"] = time.time() - start_time
        result["response_length"] = len("".join(content_chunks))

        print(f"\n\nCompleted in {result['duration_seconds']:.1f}s")
        print(f"Response length: {result['response_length']:,} chars")
        print(f"Compression triggered: {result['compression_triggered']}")

    except Exception as e:
        result["error"] = str(e)
        print(f"\n  >>> EXCEPTION: {e}")

    return result


async def run_all_tests(
    backends: list[str] | None = None,
    fill_ratio: float | None = None,
) -> list[dict[str, Any]]:
    """Run compression tests for multiple backends.

    Args:
        backends: List of backend names to test (None = all)
        fill_ratio: What fraction of context to fill (None = use per-backend defaults)

    Returns:
        List of test results
    """
    if backends is None:
        backends = list(BACKEND_CONFIGS.keys())

    results = []
    for backend_name in backends:
        if backend_name not in BACKEND_CONFIGS:
            print(f"Unknown backend: {backend_name}")
            continue

        config = BACKEND_CONFIGS[backend_name]
        # Use per-backend default fill ratio if not specified
        backend_fill_ratio = fill_ratio if fill_ratio is not None else config.get("default_fill_ratio", 0.95)
        result = await test_backend_compression(
            backend_name,
            config,
            fill_ratio=backend_fill_ratio,
        )
        results.append(result)

    return results


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print summary of all test results."""
    print("\n" + "=" * 80)
    print("COMPRESSION TEST SUMMARY")
    print("=" * 80)

    print(f"\n{'Backend':<15} {'Model':<30} {'Compression':<12} {'Duration':<10} {'Error'}")
    print("-" * 80)

    for r in results:
        compression = "YES" if r["compression_triggered"] else "NO"
        duration = f"{r['duration_seconds']:.1f}s" if r["duration_seconds"] > 0 else "N/A"
        error = r["error"][:30] + "..." if r["error"] and len(r["error"]) > 30 else (r["error"] or "")

        print(f"{r['backend']:<15} {r['model']:<30} {compression:<12} {duration:<10} {error}")

    # Overall stats
    triggered = sum(1 for r in results if r["compression_triggered"])
    errors = sum(1 for r in results if r["error"])
    print("-" * 80)
    print(f"Total: {len(results)} backends tested, {triggered} triggered compression, {errors} errors")


def main():
    parser = argparse.ArgumentParser(
        description="Test reactive compression across multiple backends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--backend",
        "-b",
        choices=list(BACKEND_CONFIGS.keys()),
        help="Test specific backend (default: all)",
    )
    parser.add_argument(
        "--fill-ratio",
        "-f",
        type=float,
        default=None,  # None means use per-backend defaults
        help="Fraction of context window to fill (default: use per-backend optimal ratio)",
    )
    parser.add_argument(
        "--list-backends",
        "-l",
        action="store_true",
        help="List available backends and exit",
    )

    args = parser.parse_args()

    if args.list_backends:
        print("Available backends:")
        for name, config in BACKEND_CONFIGS.items():
            provider = config.get("provider", "Unknown")
            model = config.get("model")
            context = get_context_window(provider, model)
            fill_ratio = config.get("default_fill_ratio", 0.95)
            print(f"  {name:<15} - {config['description']}")
            print(f"                  Model: {model}, Context: {context:,}, Default fill: {fill_ratio*100:.0f}%")
        return

    backends = [args.backend] if args.backend else None

    print("=" * 80)
    print("COMPRESSION BACKEND TEST")
    print("=" * 80)
    if args.fill_ratio is not None:
        print(f"Fill ratio: {args.fill_ratio * 100:.0f}% of context window")
    else:
        print("Fill ratio: per-backend defaults (optimized for each backend)")
    print(f"Backends: {', '.join(backends) if backends else 'all'}")

    results = asyncio.run(
        run_all_tests(
            backends=backends,
            fill_ratio=args.fill_ratio,  # None means use per-backend defaults
        ),
    )
    print_summary(results)

    # Save results to file
    results_file = Path(__file__).parent.parent / ".massgen" / "compression_test_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_file}")


if __name__ == "__main__":
    main()
