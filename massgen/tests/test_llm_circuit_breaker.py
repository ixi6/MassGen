"""Tests for LLM API circuit breaker with 429 classification.

Covers:
  - CB state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
  - HALF_OPEN probe success/failure
  - 429 WAIT: short Retry-After -> retry, no failure counter increase
  - 429 STOP: long Retry-After -> CB force-opened, no retry
  - 429 CAP: no Retry-After -> backoff retry, failure counter increase
  - 500/502/503/529 -> retryable, failure counter increase
  - max_failures triggers OPEN
  - enabled=False bypasses all logic
  - Concurrent access (threading)
  - Config validation (invalid values, boundary values)
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from massgen.backend.llm_circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    LLMCircuitBreaker,
    LLMCircuitBreakerConfig,
    RateLimitAction,
    classify_429,
    extract_retry_after,
    extract_status_code,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAPIError(Exception):
    """Test double for provider API errors."""


def _make_api_error(status_code: int, retry_after: float | None = None):
    """Create a fake Anthropic-style API error with optional Retry-After."""
    exc = FakeAPIError(f"HTTP {status_code}")
    exc.status_code = status_code
    if retry_after is not None:
        response = MagicMock()
        response.status_code = status_code
        response.headers = {"retry-after": str(retry_after)}
        exc.response = response
    else:
        response = MagicMock()
        response.status_code = status_code
        response.headers = {}
        exc.response = response
    return exc


def _enabled_config(**overrides) -> LLMCircuitBreakerConfig:
    """Return an enabled config with optional overrides."""
    defaults = {"enabled": True, "max_failures": 3, "reset_time_seconds": 1}
    defaults.update(overrides)
    return LLMCircuitBreakerConfig(**defaults)


# ---------------------------------------------------------------------------
# 429 classifier unit tests
# ---------------------------------------------------------------------------


class TestClassify429:
    def test_wait_when_retry_after_below_threshold(self):
        assert classify_429(30.0, 60.0) == RateLimitAction.WAIT

    def test_wait_when_retry_after_equals_threshold(self):
        assert classify_429(60.0, 60.0) == RateLimitAction.WAIT

    def test_stop_when_retry_after_exceeds_threshold(self):
        assert classify_429(600.0, 60.0) == RateLimitAction.STOP

    def test_cap_when_no_retry_after(self):
        assert classify_429(None, 60.0) == RateLimitAction.CAP

    def test_wait_zero_retry_after(self):
        assert classify_429(0.0, 60.0) == RateLimitAction.WAIT

    def test_stop_with_zero_threshold(self):
        # Any positive Retry-After exceeds threshold of 0
        assert classify_429(1.0, 0.0) == RateLimitAction.STOP

    def test_wait_with_zero_threshold_zero_retry(self):
        assert classify_429(0.0, 0.0) == RateLimitAction.WAIT


# ---------------------------------------------------------------------------
# extract_retry_after
# ---------------------------------------------------------------------------


class TestExtractRetryAfter:
    def test_from_response_headers(self):
        exc = _make_api_error(429, retry_after=30.0)
        assert extract_retry_after(exc) == 30.0

    def test_from_capitalized_header(self):
        exc = _make_api_error(429)
        exc.response.headers = {"Retry-After": "45"}
        assert extract_retry_after(exc) == 45.0

    def test_none_when_no_header(self):
        exc = _make_api_error(429)
        assert extract_retry_after(exc) is None

    def test_none_when_no_response(self):
        exc = Exception("no response")
        assert extract_retry_after(exc) is None

    def test_none_when_unparseable(self):
        exc = _make_api_error(429)
        exc.response.headers = {"retry-after": "not-a-number"}
        assert extract_retry_after(exc) is None


# ---------------------------------------------------------------------------
# extract_status_code
# ---------------------------------------------------------------------------


class TestExtractStatusCode:
    def test_from_status_code_attr(self):
        exc = Exception("err")
        exc.status_code = 429
        assert extract_status_code(exc) == 429

    def test_from_response(self):
        exc = Exception("err")
        response = MagicMock()
        response.status_code = 500
        exc.response = response
        assert extract_status_code(exc) == 500

    def test_none_when_absent(self):
        assert extract_status_code(Exception("plain")) is None


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestLLMCircuitBreakerConfig:
    def test_defaults(self):
        cfg = LLMCircuitBreakerConfig()
        assert cfg.enabled is False
        assert cfg.max_failures == 5
        assert cfg.retry_after_threshold_seconds == 60.0

    def test_invalid_max_failures(self):
        with pytest.raises(ValueError, match="max_failures"):
            LLMCircuitBreakerConfig(max_failures=0)

    def test_invalid_reset_time(self):
        with pytest.raises(ValueError, match="reset_time_seconds"):
            LLMCircuitBreakerConfig(reset_time_seconds=0)

    def test_invalid_backoff_multiplier(self):
        with pytest.raises(ValueError, match="backoff_multiplier"):
            LLMCircuitBreakerConfig(backoff_multiplier=0.5)

    def test_invalid_max_backoff(self):
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            LLMCircuitBreakerConfig(max_backoff_seconds=0.0)

    def test_invalid_retry_after_threshold(self):
        with pytest.raises(ValueError, match="retry_after_threshold_seconds"):
            LLMCircuitBreakerConfig(retry_after_threshold_seconds=-1)

    def test_boundary_valid(self):
        cfg = LLMCircuitBreakerConfig(
            max_failures=1,
            reset_time_seconds=1,
            backoff_multiplier=1.0,
            max_backoff_seconds=1.0,
            retry_after_threshold_seconds=0,
        )
        assert cfg.max_failures == 1


# ---------------------------------------------------------------------------
# State transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def test_starts_closed(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_max_failures(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=3))
        for _ in range(3):
            cb.record_failure(error_type="test")
        assert cb.state == CircuitState.OPEN

    def test_stays_closed_below_max_failures(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=3))
        for _ in range(2):
            cb.record_failure(error_type="test")
        assert cb.state == CircuitState.CLOSED

    def test_blocks_when_open(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=1))
        cb.record_failure()
        assert cb.should_block() is True

    def test_transitions_to_half_open_after_reset_time(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(1.1)
        # should_block triggers transition
        assert cb.should_block() is False
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        time.sleep(1.1)
        cb.should_block()  # triggers HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_reopens_on_failure(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        time.sleep(1.1)
        cb.should_block()  # triggers HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_blocks_second_request(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        time.sleep(1.1)
        assert cb.should_block() is False  # first probe allowed
        assert cb.should_block() is True  # second blocked

    def test_force_open(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        cb.force_open("test reason")
        assert cb.state == CircuitState.OPEN
        assert cb.should_block() is True

    def test_reset(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# enabled=False bypass
# ---------------------------------------------------------------------------


class TestDisabledBypass:
    def test_should_block_always_false(self):
        cb = LLMCircuitBreaker(config=LLMCircuitBreakerConfig(enabled=False))
        # Even after many failures, should_block returns False
        for _ in range(100):
            cb.record_failure()
        assert cb.should_block() is False

    def test_record_failure_is_noop(self):
        cb = LLMCircuitBreaker(config=LLMCircuitBreakerConfig(enabled=False))
        cb.record_failure()
        # State never changes from CLOSED
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_with_retry_passes_through(self):
        cb = LLMCircuitBreaker(config=LLMCircuitBreakerConfig(enabled=False))

        async def success():
            return "ok"

        result = await cb.call_with_retry(success)
        assert result == "ok"


# ---------------------------------------------------------------------------
# call_with_retry -- 429 WAIT
# ---------------------------------------------------------------------------


class TestCallWithRetry429Wait:
    @pytest.mark.asyncio
    async def test_retries_after_short_retry_after(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(429, retry_after=0.1)
            return "success"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await cb.call_with_retry(api_call)

        assert result == "success"
        assert call_count == 2
        # Failure counter should NOT have increased for WAIT
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_wait_with_zero_retry_after_sleeps_zero(self):
        """Retry-After: 0 should sleep 0s, not 1s (0.0 is falsy but valid)."""
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(429, retry_after=0.0)
            return "ok"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await cb.call_with_retry(api_call)

        assert result == "ok"
        mock_sleep.assert_called_once_with(0.0)

    @pytest.mark.asyncio
    async def test_wait_uses_retry_after_value(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(429, retry_after=5.0)
            return "ok"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            await cb.call_with_retry(api_call)

        # Should have slept for 5.0 seconds (the Retry-After value)
        mock_sleep.assert_called_once_with(5.0)


# ---------------------------------------------------------------------------
# call_with_retry -- 429 STOP
# ---------------------------------------------------------------------------


class TestCallWithRetry429Stop:
    @pytest.mark.asyncio
    async def test_force_opens_cb_on_long_retry_after(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(retry_after_threshold_seconds=60),
        )

        async def api_call():
            raise _make_api_error(429, retry_after=600.0)

        with pytest.raises(FakeAPIError, match="429"):
            await cb.call_with_retry(api_call)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_no_retry_on_stop(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(retry_after_threshold_seconds=60),
        )
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            raise _make_api_error(429, retry_after=3600.0)

        with pytest.raises(FakeAPIError):
            await cb.call_with_retry(api_call)

        assert call_count == 1  # no retries


# ---------------------------------------------------------------------------
# call_with_retry -- 429 CAP
# ---------------------------------------------------------------------------


class TestCallWithRetry429Cap:
    @pytest.mark.asyncio
    async def test_backoff_retry_on_no_retry_after(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _make_api_error(429)  # no Retry-After
            return "ok"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await cb.call_with_retry(api_call, max_retries=3)

        assert result == "ok"
        assert call_count == 3
        # record_success resets failure_count; verify state is CLOSED
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_cap_increments_failure_counter(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=10))

        async def api_call():
            raise _make_api_error(429)  # always CAP

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError):
                await cb.call_with_retry(api_call, max_retries=3)

        # 3 CAP failures recorded (no success to reset)
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_cap_exhausts_retries(self):
        cb = LLMCircuitBreaker(config=_enabled_config())

        async def api_call():
            raise _make_api_error(429)  # always CAP

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError, match="429"):
                await cb.call_with_retry(api_call, max_retries=2)


# ---------------------------------------------------------------------------
# call_with_retry -- retryable status codes (500, 502, 503, 529)
# ---------------------------------------------------------------------------


class TestCallWithRetryRetryable:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [500, 502, 503, 529])
    async def test_retries_on_server_error(self, status_code):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(status_code)
            return "recovered"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await cb.call_with_retry(api_call, max_retries=3)

        assert result == "recovered"
        assert call_count == 2
        # record_success resets failure_count; verify state is CLOSED
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_retryable_increments_failure_counter_on_exhaust(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=10))

        async def api_call():
            raise _make_api_error(500)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError):
                await cb.call_with_retry(api_call, max_retries=3)

        # 3 failures recorded (no success to reset)
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            raise _make_api_error(400)  # not retryable

        with pytest.raises(FakeAPIError, match="400"):
            await cb.call_with_retry(api_call)

        assert call_count == 1


# ---------------------------------------------------------------------------
# call_with_retry -- CB open blocks
# ---------------------------------------------------------------------------


class TestCallWithRetryCBBlocks:
    @pytest.mark.asyncio
    async def test_raises_when_cb_open(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        async def api_call():
            return "should not reach"

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call_with_retry(api_call)

    @pytest.mark.asyncio
    async def test_opens_cb_after_max_failures_during_retries(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=2))

        async def api_call():
            raise _make_api_error(500)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError):
                await cb.call_with_retry(api_call, max_retries=3)

        assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# Concurrent access (threading)
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_record_failure(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=100))
        threads = []

        def record_many():
            for _ in range(50):
                cb.record_failure()

        for _ in range(10):
            t = threading.Thread(target=record_many)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cb.failure_count == 500

    def test_concurrent_should_block(self):
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        time.sleep(1.1)

        results = []

        def check():
            results.append(cb.should_block())

        threads = [threading.Thread(target=check) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one thread should get False (the probe), rest True
        false_count = results.count(False)
        true_count = results.count(True)
        assert false_count == 1
        assert true_count == 9

    def test_concurrent_record_success(self):
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        threads = []

        def succeed():
            cb.record_success()

        for _ in range(10):
            t = threading.Thread(target=succeed)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Edge cases from Round 1 review
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_negative_retry_after_treated_as_wait(self):
        """Negative Retry-After parses as float; classify_429 returns WAIT."""
        assert classify_429(-30.0, 60.0) == RateLimitAction.WAIT

    @pytest.mark.asyncio
    async def test_negative_retry_after_in_call_with_retry(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(429, retry_after=-5.0)
            return "ok"

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await cb.call_with_retry(api_call)

        assert result == "ok"
        # Negative Retry-After used as sleep value (harmless -- asyncio.sleep(negative) returns immediately)
        mock_sleep.assert_called_once_with(-5.0)

    def test_reset_when_disabled(self):
        """reset() works even when enabled=False (no guard needed)."""
        cb = LLMCircuitBreaker(config=LLMCircuitBreakerConfig(enabled=False))
        # Manually set internal state to verify reset clears it
        cb._state = CircuitState.OPEN
        cb._failure_count = 99
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_mid_retry_cb_opens_blocks_further_retries(self):
        """When CB opens mid-retry (from record_failure), further retries are blocked."""
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=2))
        call_count = 0

        async def api_call():
            nonlocal call_count
            call_count += 1
            raise _make_api_error(500)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError):
                await cb.call_with_retry(api_call, max_retries=5)

        # CB opens after 2 failures; 3rd retry blocked by should_block() before API call
        assert cb.state == CircuitState.OPEN
        # Exactly 2 calls: 2 failures open CB, 3rd attempt blocked by should_block()
        assert call_count == 2


# ---------------------------------------------------------------------------
# Round 3 review findings
# ---------------------------------------------------------------------------


class TestRound3Findings:
    @pytest.mark.asyncio
    async def test_cb_opens_on_last_attempt_raises_original_error(self):
        """CB opens exactly at last attempt -- raises original error, not CircuitBreakerOpenError."""
        cb = LLMCircuitBreaker(config=_enabled_config(max_failures=3))

        async def api_call():
            raise _make_api_error(500)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError, match="500") as exc_info:
                await cb.call_with_retry(api_call, max_retries=3)

        # Should be the original 500 error, not CircuitBreakerOpenError
        assert not isinstance(exc_info.value, CircuitBreakerOpenError)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_429_wait_exhausts_max_retries(self):
        """429 WAIT that never succeeds eventually raises after max_retries."""
        cb = LLMCircuitBreaker(config=_enabled_config())

        async def api_call():
            raise _make_api_error(429, retry_after=0.1)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError, match="429"):
                await cb.call_with_retry(api_call, max_retries=3)

        # WAIT does not increment failure counter
        assert cb.failure_count == 0
        # CB stays CLOSED (WAIT is soft failure)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_429_wait_last_attempt_no_sleep(self):
        """On last attempt, 429 WAIT should raise immediately without sleeping."""
        cb = LLMCircuitBreaker(config=_enabled_config())

        async def api_call():
            raise _make_api_error(429, retry_after=10.0)

        with patch("massgen.backend.llm_circuit_breaker.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(FakeAPIError, match="429"):
                await cb.call_with_retry(api_call, max_retries=1)

        # max_retries=1: single attempt, immediately raises, no sleep
        mock_sleep.assert_not_called()


class TestRepr:
    def test_repr(self):
        cb = LLMCircuitBreaker(config=_enabled_config())
        r = repr(cb)
        assert "LLMCircuitBreaker" in r
        assert "closed" in r
        assert "claude" in r


# ---------------------------------------------------------------------------
# CodeRabbit findings
# ---------------------------------------------------------------------------


class TestHalfOpenProbeCleanup:
    """Verify HALF_OPEN probe flag is cleared on non-retryable errors (#3 Critical)."""

    @pytest.mark.asyncio
    async def test_non_retryable_error_clears_half_open_probe(self):
        """400 during HALF_OPEN probe must not wedge the CB."""
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()  # OPEN
        time.sleep(1.1)
        # Don't call should_block() manually -- let call_with_retry do the transition

        async def api_call():
            raise _make_api_error(400)  # non-retryable

        with pytest.raises(FakeAPIError, match="400"):
            await cb.call_with_retry(api_call)

        # CB must be OPEN, not stuck in HALF_OPEN
        assert cb.state == CircuitState.OPEN
        # Probe flag must be cleared
        assert cb._half_open_probe_active is False

    @pytest.mark.asyncio
    async def test_cancellation_clears_half_open_probe(self):
        """asyncio.CancelledError during probe must not wedge CB."""
        cb = LLMCircuitBreaker(
            config=_enabled_config(max_failures=1, reset_time_seconds=1),
        )
        cb.record_failure()
        time.sleep(1.1)
        # Let call_with_retry handle the OPEN->HALF_OPEN transition

        async def api_call():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await cb.call_with_retry(api_call)

        assert cb.state == CircuitState.OPEN
        assert cb._half_open_probe_active is False


class TestForceOpenRetryAfterWindow:
    """Verify force_open honors Retry-After duration (#2 Major)."""

    def test_force_open_with_long_retry_after(self):
        """force_open with open_for_seconds=3600 keeps CB open beyond reset_time."""
        cb = LLMCircuitBreaker(
            config=_enabled_config(reset_time_seconds=60),
        )
        cb.force_open("quota exhaustion", open_for_seconds=3600)
        assert cb.state == CircuitState.OPEN
        # _open_until should be ~3600s from now, not 60s
        with cb._lock:
            remaining = cb._open_until - time.monotonic()
        assert remaining > 3500  # still well above reset_time_seconds

    @pytest.mark.asyncio
    async def test_429_stop_honors_retry_after_window(self):
        """429 STOP with Retry-After=600 should keep CB open for 600s."""
        cb = LLMCircuitBreaker(
            config=_enabled_config(retry_after_threshold_seconds=60),
        )

        async def api_call():
            raise _make_api_error(429, retry_after=600.0)

        with pytest.raises(FakeAPIError):
            await cb.call_with_retry(api_call)

        assert cb.state == CircuitState.OPEN
        with cb._lock:
            remaining = cb._open_until - time.monotonic()
        assert remaining > 550  # honoring 600s, not defaulting to 60s
