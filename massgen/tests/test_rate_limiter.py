"""Tests for rate limiter functionality (fast, no real 60s waits)."""

import asyncio

import pytest

from massgen.backend import rate_limiter
from massgen.backend.rate_limiter import GlobalRateLimiter


@pytest.fixture(autouse=True)
def _reset_limiters():
    """Ensure clean limiter registry per test."""
    GlobalRateLimiter.clear_limiters()
    yield
    GlobalRateLimiter.clear_limiters()


@pytest.fixture
def fast_clock(monkeypatch):
    """Provide a virtual clock and fast sleep to avoid wall-clock delays."""

    original_sleep = asyncio.sleep

    class _Clock:
        def __init__(self, start: float = 1_000.0):
            self.now = start

        def time(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.now += seconds
            # Yield control so await points still cooperate with asyncio
            await original_sleep(0)

    clock = _Clock()

    # Patch the module-local time and sleep used by MultiRateLimiter
    monkeypatch.setattr(rate_limiter.time, "time", clock.time)
    monkeypatch.setattr(rate_limiter.asyncio, "sleep", clock.sleep)

    return clock


@pytest.mark.asyncio
async def test_shared_limiter_instances():
    """Multiple requests for same provider share a single limiter instance."""
    limiter1 = GlobalRateLimiter.get_multi_limiter_sync(provider="test-shared", rpm=2)
    limiter2 = GlobalRateLimiter.get_multi_limiter_sync(provider="test-shared", rpm=2)

    assert limiter1 is limiter2


@pytest.mark.asyncio
async def test_rpm_limit_waits_without_real_sleep(fast_clock):
    """Third request waits ~60s (virtual) when RPM=2, without wall time passing."""

    limiter = GlobalRateLimiter.get_multi_limiter_sync(provider="test-gemini-2.5-pro", rpm=2)
    timestamps = []

    async def make_request():
        async with limiter:
            timestamps.append(fast_clock.time())

    await asyncio.gather(*(make_request() for _ in range(3)))

    assert len(timestamps) == 3

    first_gap = timestamps[1] - timestamps[0]
    second_gap = timestamps[2] - timestamps[1]

    # First two should be effectively back-to-back; third should be ~60s later (virtual)
    assert first_gap < 1.0
    assert second_gap >= 59.0
