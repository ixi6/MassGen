"""Async utility functions for MassGen."""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run_async_safely(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """
    Run async code safely from sync context, handling nested event loops.

    This is needed when sync code needs to call async functions, but we don't
    know if we're already inside an event loop (e.g., called from async code
    via a sync adapter).

    The problem with naive asyncio.run():
    - If we're already in an event loop, asyncio.run() raises RuntimeError
    - If we force a new loop, httpcore connections get confused about which loop owns them
    - This causes "async generator ignored GeneratorExit" and lifecycle errors

    Solution:
    - Detect if we're in an async context (running event loop exists)
    - If YES: Run the coroutine in a separate thread with its own event loop
    - If NO: Use asyncio.run() normally

    Args:
        coro: Coroutine to execute
        timeout: Optional timeout in seconds for thread pool execution

    Returns:
        Result of the coroutine

    Raises:
        TimeoutError: If timeout is specified and exceeded
        Any exception raised by the coroutine
    """
    try:
        asyncio.get_running_loop()
        # We are in an async context - run in thread pool to avoid conflicts
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=timeout)
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)
