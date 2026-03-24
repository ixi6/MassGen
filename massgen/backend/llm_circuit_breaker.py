"""
LLM API Circuit Breaker with 429 classification.

Provides circuit breaker protection for LLM API calls with intelligent
handling of HTTP 429 responses based on Retry-After header analysis.

429 classification:
  WAIT -- Retry-After present and <= threshold: wait and retry (soft failure)
  STOP -- Retry-After present and > threshold: open CB immediately (quota exhaustion)
  CAP  -- No Retry-After: concurrency limit signal, backoff + retry (hard failure)

Public interface: should_block(), record_failure(), record_success() (single-endpoint).
"""

from __future__ import annotations

import asyncio
import enum
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..logger_config import log_backend_activity

# ---------------------------------------------------------------------------
# 429 classification
# ---------------------------------------------------------------------------


class RateLimitAction(enum.Enum):
    """Classification of a 429 response."""

    WAIT = "wait"  # Retry-After <= threshold -- wait then retry
    STOP = "stop"  # Retry-After > threshold -- open CB, no retry
    CAP = "cap"  # No Retry-After -- backoff retry, record failure


# ---------------------------------------------------------------------------
# Circuit breaker states
# ---------------------------------------------------------------------------


class CircuitState(enum.Enum):
    """Standard three-state circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LLMCircuitBreakerConfig:
    """Configuration for the LLM circuit breaker."""

    enabled: bool = False  # opt-in, default preserves existing behavior
    max_failures: int = 5
    reset_time_seconds: int = 60
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 300.0
    retry_after_threshold_seconds: float = 60.0
    retryable_status_codes: list[int] = field(
        default_factory=lambda: [500, 502, 503, 529],
    )

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_failures < 1:
            raise ValueError(f"max_failures must be >= 1, got {self.max_failures}")
        if self.reset_time_seconds < 1:
            raise ValueError(
                f"reset_time_seconds must be >= 1, got {self.reset_time_seconds}",
            )
        if self.backoff_multiplier < 1.0:
            raise ValueError(
                f"backoff_multiplier must be >= 1.0, got {self.backoff_multiplier}",
            )
        if self.max_backoff_seconds < 1.0:
            raise ValueError(
                f"max_backoff_seconds must be >= 1.0, got {self.max_backoff_seconds}",
            )
        if self.retry_after_threshold_seconds < 0:
            raise ValueError(
                f"retry_after_threshold_seconds must be >= 0, " f"got {self.retry_after_threshold_seconds}",
            )


# ---------------------------------------------------------------------------
# 429 classifier
# ---------------------------------------------------------------------------


def classify_429(
    retry_after_value: float | None,
    threshold: float,
) -> RateLimitAction:
    """Classify a 429 response based on Retry-After header.

    Args:
        retry_after_value: Parsed Retry-After in seconds, or None if absent.
        threshold: Maximum Retry-After to treat as WAIT (seconds).

    Returns:
        RateLimitAction indicating how to handle the 429.
    """
    if retry_after_value is None:
        return RateLimitAction.CAP
    if retry_after_value <= threshold:
        return RateLimitAction.WAIT
    return RateLimitAction.STOP


def extract_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After seconds from an Anthropic API exception.

    Checks response headers for 'retry-after' (case-insensitive).

    Returns:
        Seconds to wait, or None if header is absent or unparseable.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None

    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    # Case-insensitive lookup: SDK may return "Retry-After" or "retry-after"
    raw = None
    if hasattr(headers, "get"):
        for key in ("retry-after", "Retry-After"):
            raw = headers.get(key)
            if raw is not None:
                break
    if raw is None:
        return None

    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def extract_status_code(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception.

    Checks exc.status_code (anthropic SDK pattern) and exc.response.status_code.
    """
    status = getattr(exc, "status_code", None)
    if status is not None:
        return int(status)

    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if status is not None:
            return int(status)

    return None


# ---------------------------------------------------------------------------
# LLM Circuit Breaker
# ---------------------------------------------------------------------------


class LLMCircuitBreaker:
    """Circuit breaker for LLM API calls with 429 classification.

    Thread-safe via a lock. State machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    Public interface (similar to MCPCircuitBreaker but single-endpoint):
      - should_block()    -- check if requests should be blocked
      - record_failure()  -- record a failed API call
      - record_success()  -- record a successful API call

    Unlike MCPCircuitBreaker, this class tracks a single endpoint (no server_name key).
    """

    def __init__(
        self,
        config: LLMCircuitBreakerConfig | None = None,
        backend_name: str = "claude",
    ) -> None:
        self.config = config or LLMCircuitBreakerConfig()
        self.backend_name = backend_name
        self._lock = threading.Lock()

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._open_until = 0.0  # monotonic deadline for OPEN state
        self._half_open_probe_active = False

    # -- Public interface ---------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state (read-only snapshot)."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Current failure count (read-only snapshot)."""
        with self._lock:
            return self._failure_count

    def should_block(self) -> bool:
        """Check whether new requests should be blocked.

        Returns:
            True if the circuit is OPEN and reset time has not elapsed.
            In HALF_OPEN, allows exactly one probe request.
        """
        if not self.config.enabled:
            return False

        with self._lock:
            if self._state == CircuitState.CLOSED:
                return False

            if self._state == CircuitState.OPEN:
                now = time.monotonic()
                if now >= self._open_until:
                    # Transition to HALF_OPEN -- allow one probe
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_probe_active = True
                    self._log("Circuit breaker half-open, allowing probe request")
                    return False
                return True

            # HALF_OPEN
            if self._half_open_probe_active:
                # Probe already dispatched; block additional requests
                return True
            # No probe active -- allow one
            self._half_open_probe_active = True
            return False

    def record_failure(
        self,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record a failed API call. Increments failure counter.

        If max_failures is reached, transitions to OPEN.
        In HALF_OPEN, any failure transitions back to OPEN.
        """
        if not self.config.enabled:
            return

        with self._lock:
            self._failure_count += 1
            now = time.monotonic()
            self._last_failure_time = now

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._open_until = now + self.config.reset_time_seconds
                self._half_open_probe_active = False
                self._log(
                    "Probe failed, circuit breaker re-opened",
                    failure_count=self._failure_count,
                    error_type=error_type,
                )
                return

            if self._failure_count >= self.config.max_failures:
                self._state = CircuitState.OPEN
                self._open_until = now + self.config.reset_time_seconds
                self._log(
                    "Circuit breaker opened",
                    failure_count=self._failure_count,
                    error_type=error_type,
                )
            else:
                self._log(
                    "Failure recorded",
                    failure_count=self._failure_count,
                    max_failures=self.config.max_failures,
                    error_type=error_type,
                )

    def record_success(self) -> None:
        """Record a successful API call. Resets failure counter and closes circuit."""
        if not self.config.enabled:
            return

        with self._lock:
            prev_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_probe_active = False

            if prev_state != CircuitState.CLOSED:
                self._log(
                    "Circuit breaker closed after success",
                    previous_state=prev_state.value,
                )

    def force_open(self, reason: str = "", open_for_seconds: float = 0) -> None:
        """Force the circuit to OPEN state (e.g. on 429 STOP).

        Args:
            reason: Human-readable reason for logging.
            open_for_seconds: Minimum seconds to keep OPEN. If > reset_time_seconds,
                overrides the default. Used to honor Retry-After from 429 STOP.
        """
        if not self.config.enabled:
            return

        with self._lock:
            now = time.monotonic()
            self._state = CircuitState.OPEN
            self._last_failure_time = now
            duration = max(self.config.reset_time_seconds, open_for_seconds)
            self._open_until = now + duration
            self._half_open_probe_active = False
            self._log(f"Circuit breaker force-opened: {reason}", open_for_seconds=duration)

    def reset(self) -> None:
        """Reset circuit breaker to initial CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            self._open_until = 0.0
            self._half_open_probe_active = False

    # -- 429-aware retry wrapper --------------------------------------------

    async def call_with_retry(
        self,
        coro_factory: Any,  # Callable[[], Awaitable[T]]
        *,
        max_retries: int = 3,
        agent_id: str | None = None,
    ) -> Any:
        """Execute an async API call with circuit breaker protection and 429 handling.

        Args:
            coro_factory: Zero-arg callable that returns an awaitable for the API call.
            max_retries: Maximum number of retry attempts for retryable errors.
            agent_id: Optional agent ID for logging.

        Returns:
            The result of the API call.

        Raises:
            The original exception if not retryable, CB is open, or retries exhausted.
        """
        if not self.config.enabled:
            return await coro_factory()

        if self.should_block():
            with self._lock:
                state_label = self._state.value
            raise CircuitBreakerOpenError(
                f"Circuit breaker is {state_label} for {self.backend_name}",
            )

        last_exc: Exception | None = None
        delay = 1.0  # initial backoff for CAP / retryable errors
        _probe_was_half_open = self.state == CircuitState.HALF_OPEN

        try:
            for attempt in range(1, max_retries + 1):
                # Re-check CB state at start of each attempt
                if attempt > 1 and self.should_block():
                    with self._lock:
                        state_label = self._state.value
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker became {state_label} during retries for {self.backend_name}",
                    )

                try:
                    result = await coro_factory()
                    self.record_success()
                    return result

                except Exception as exc:
                    last_exc = exc
                    status_code = extract_status_code(exc)

                    # --- 429 handling with classification ---
                    if status_code == 429:
                        retry_after = extract_retry_after(exc)
                        action = classify_429(
                            retry_after,
                            self.config.retry_after_threshold_seconds,
                        )

                        if action == RateLimitAction.STOP:
                            # Quota exhaustion -- open CB for full Retry-After window
                            self.force_open(
                                f"429 STOP: Retry-After={retry_after}s > " f"threshold={self.config.retry_after_threshold_seconds}s",
                                open_for_seconds=retry_after or 0,
                            )
                            raise

                        if action == RateLimitAction.WAIT:
                            # Short wait -- retry without counting as failure
                            if attempt >= max_retries:
                                raise
                            wait_seconds = retry_after if retry_after is not None else 1.0
                            self._log(
                                "429 WAIT: retrying after Retry-After",
                                retry_after=wait_seconds,
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            await asyncio.sleep(wait_seconds)
                            continue

                        # CAP -- no Retry-After, backoff + record failure
                        self.record_failure(
                            error_type="429_cap",
                            error_message=str(exc)[:200],
                        )
                        if attempt < max_retries:
                            jittered = delay * random.uniform(0.8, 1.2)  # noqa: S311
                            self._log(
                                "429 CAP: backoff retry",
                                delay=round(jittered, 2),
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            await asyncio.sleep(jittered)
                            delay = min(
                                delay * self.config.backoff_multiplier,
                                self.config.max_backoff_seconds,
                            )
                            continue
                        raise

                    # --- Other retryable status codes ---
                    if status_code in self.config.retryable_status_codes:
                        self.record_failure(
                            error_type=f"http_{status_code}",
                            error_message=str(exc)[:200],
                        )
                        if attempt < max_retries and not self.should_block():
                            jittered = delay * random.uniform(0.8, 1.2)  # noqa: S311
                            self._log(
                                f"Retryable error (HTTP {status_code}), backing off",
                                delay=round(jittered, 2),
                                attempt=attempt,
                                agent_id=agent_id,
                            )
                            await asyncio.sleep(jittered)
                            delay = min(
                                delay * self.config.backoff_multiplier,
                                self.config.max_backoff_seconds,
                            )
                            continue
                        raise

                    # --- Non-retryable error ---
                    raise

            # Defensive fallback
            if last_exc:
                raise last_exc
            raise RuntimeError("call_with_retry ended without result or exception")

        except BaseException:
            # Ensure HALF_OPEN probe flag is cleared on any terminal exit
            # to prevent wedging the CB in a permanently blocked state.
            if _probe_was_half_open:
                with self._lock:
                    if self._state == CircuitState.HALF_OPEN and self._half_open_probe_active:
                        self._state = CircuitState.OPEN
                        self._open_until = time.monotonic() + self.config.reset_time_seconds
                        self._half_open_probe_active = False
                        self._log("Probe terminated abnormally, circuit breaker re-opened")
            raise

    # -- Internal helpers ---------------------------------------------------

    def _log(self, message: str, **details: Any) -> None:
        """Log via structured backend activity logger."""
        log_details: dict[str, Any] = {k: v for k, v in details.items() if v is not None}
        log_backend_activity(
            self.backend_name,
            message,
            log_details if log_details else None,
            agent_id=details.get("agent_id"),
        )

    def __repr__(self) -> str:
        with self._lock:
            state = self._state.value
            failures = self._failure_count
        return f"LLMCircuitBreaker(state={state}, " f"failures={failures}/{self.config.max_failures}, " f"backend={self.backend_name!r})"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and blocking requests."""
