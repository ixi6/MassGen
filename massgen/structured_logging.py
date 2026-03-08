"""
Structured logging and observability for MassGen using Logfire.

This module provides centralized configuration for Logfire-based observability,
including:
- Automatic LLM client instrumentation (OpenAI, Anthropic)
- Manual span creation for orchestrator operations
- Tool call tracing with timing and input/output metrics
- Integration with existing loguru logging

Usage:
    from massgen.structured_logging import configure_observability, get_tracer

    # Configure at startup (typically in cli.py)
    configure_observability(enabled=True, service_name="massgen")

    # Get tracer for manual spans
    tracer = get_tracer()

    # Create spans
    with tracer.span("my_operation", attributes={"key": "value"}):
        do_work()

Environment Variables:
    LOGFIRE_TOKEN: Write token for Logfire cloud (required for production).
        This is read by the Logfire library directly.
    MASSGEN_LOGFIRE_ENABLED: Set to "true" to enable Logfire (default: false)
"""

import os
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

from loguru import logger

# Type variable for generic function wrapper
F = TypeVar("F", bound=Callable[..., Any])

# Global state for observability configuration
_logfire_enabled: bool = False
_logfire_configured: bool = False
_instrumented_clients: dict[str, bool] = {}

# Context variable for tracking current agent round (for tool call attribution)
# This allows nested tool calls to know which round they belong to
_current_round: ContextVar[int | None] = ContextVar("current_round", default=None)
_current_round_type: ContextVar[str | None] = ContextVar(
    "current_round_type",
    default=None,
)


@dataclass
class ObservabilityConfig:
    """Configuration for structured logging and observability."""

    enabled: bool = False
    service_name: str = "massgen"
    service_version: str | None = None
    environment: str = "development"
    send_to_logfire: bool = True
    console_enabled: bool = True
    console_min_level: str = "info"
    scrub_sensitive_data: bool = True
    additional_processors: list[Any] = field(default_factory=list)


# Global config instance
_config: ObservabilityConfig | None = None


def configure_observability(
    enabled: bool | None = None,
    service_name: str = "massgen",
    service_version: str | None = None,
    environment: str = "development",
    send_to_logfire: bool = True,
    console_enabled: bool = False,
    console_min_level: str = "info",
    scrub_sensitive_data: bool = True,
) -> bool:
    """
    Configure Logfire observability for MassGen.

    This should be called once at application startup, typically in cli.py.
    If Logfire is not available or not configured, logging will fall back
    to standard loguru logging with no impact on functionality.

    Args:
        enabled: Whether to enable Logfire. If None, checks MASSGEN_LOGFIRE_ENABLED env var.
        service_name: Name of the service for tracing.
        service_version: Version of the service (auto-detected from massgen.__version__ if not provided).
        environment: Deployment environment (development, staging, production).
        send_to_logfire: Whether to send data to Logfire cloud (requires LOGFIRE_TOKEN).
        console_enabled: Whether to also log to console via Logfire.
        console_min_level: Minimum log level for console output.
        scrub_sensitive_data: Whether to scrub sensitive data from logs.

    Returns:
        True if Logfire was successfully configured, False otherwise.
    """
    global _logfire_enabled, _logfire_configured, _config

    # Determine if enabled from environment or parameter
    if enabled is None:
        enabled = os.environ.get("MASSGEN_LOGFIRE_ENABLED", "").lower() in (
            "true",
            "1",
            "yes",
        )

    if not enabled:
        logger.debug("Logfire observability is disabled")
        _logfire_enabled = False
        return False

    # Store config
    _config = ObservabilityConfig(
        enabled=enabled,
        service_name=service_name,
        service_version=service_version,
        environment=environment,
        send_to_logfire=send_to_logfire,
        console_enabled=console_enabled,
        console_min_level=console_min_level,
        scrub_sensitive_data=scrub_sensitive_data,
    )

    try:
        import logfire

        # Get version if not provided
        if service_version is None:
            try:
                import massgen

                service_version = getattr(massgen, "__version__", "0.0.0")
            except ImportError:
                service_version = "0.0.0"

        # Configure Logfire
        logfire.configure(
            service_name=service_name,
            service_version=service_version,
            environment=environment,
            send_to_logfire=send_to_logfire,
            console=(
                logfire.ConsoleOptions(
                    min_log_level=console_min_level,
                )
                if console_enabled
                else False
            ),
            scrubbing=(
                logfire.ScrubbingOptions(
                    extra_patterns=[
                        "api_key",
                        "api_secret",
                        "password",
                        "token",
                        "secret",
                    ],
                )
                if scrub_sensitive_data
                else False
            ),
        )

        _logfire_enabled = True
        _logfire_configured = True

        # Suppress noisy OpenTelemetry context detach warnings
        # These occur in async generators when context changes between yield points
        # and are harmless - the spans are still recorded correctly
        import logging

        class ContextDetachFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                # Filter out "Failed to detach context" messages
                return "Failed to detach context" not in str(record.msg)

        otel_context_logger = logging.getLogger("opentelemetry.context")
        otel_context_logger.addFilter(ContextDetachFilter())

        logger.info(
            f"Logfire observability configured: service={service_name}, env={environment}",
        )
        return True

    except ImportError:
        logger.warning(
            "Logfire package not installed. Install with: pip install massgen[observability]",
        )
        _logfire_enabled = False
        return False
    except Exception as e:
        error_msg = str(e)
        if "not logged in" in error_msg.lower():
            logger.warning(
                "Logfire requires authentication. Run 'logfire auth' to authenticate, " "then re-run your command. Continuing without observability...",
            )
        else:
            logger.warning(
                f"Failed to configure Logfire: {e}. Observability features disabled.",
            )
        _logfire_enabled = False
        return False


def is_observability_enabled() -> bool:
    """Check if Logfire observability is currently enabled."""
    return _logfire_enabled


def get_config() -> ObservabilityConfig | None:
    """Get the current observability configuration."""
    return _config


class TracerProxy:
    """
    Proxy object for Logfire tracing that gracefully degrades when Logfire is disabled.

    This allows code to use tracing calls without checking if Logfire is enabled,
    making the instrumentation code cleaner and more maintainable.
    """

    def __init__(self):
        self._logfire = None

    def _get_logfire(self):
        """Lazily import logfire to avoid import errors when not installed."""
        if self._logfire is None and _logfire_enabled:
            try:
                import logfire

                self._logfire = logfire
            except ImportError:
                pass
        return self._logfire

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        record_exception: bool = True,
    ):
        """
        Create a tracing span.

        Args:
            name: Name of the span.
            attributes: Key-value attributes to attach to the span.
            record_exception: Whether to record exceptions in the span.

        Yields:
            Span object if Logfire is enabled, otherwise a no-op context.
        """
        logfire = self._get_logfire()
        if logfire:
            with logfire.span(name, **attributes or {}) as span:
                try:
                    yield span
                except Exception as e:
                    if record_exception:
                        span.record_exception(e)
                    raise
        else:
            yield _NoOpSpan()

    def info(self, message: str, **kwargs):
        """Log an info message with optional attributes."""
        logfire = self._get_logfire()
        if logfire:
            logfire.info(message, **kwargs)
        else:
            logger.info(message)

    def debug(self, message: str, **kwargs):
        """Log a debug message with optional attributes."""
        logfire = self._get_logfire()
        if logfire:
            logfire.debug(message, **kwargs)
        else:
            logger.debug(message)

    def warning(self, message: str, **kwargs):
        """Log a warning message with optional attributes."""
        logfire = self._get_logfire()
        if logfire:
            logfire.warn(message, **kwargs)
        else:
            logger.warning(message)

    def error(self, message: str, **kwargs):
        """Log an error message with optional attributes."""
        logfire = self._get_logfire()
        if logfire:
            logfire.error(message, **kwargs)
        else:
            logger.error(message)

    def instrument_openai(self, client=None):
        """
        Instrument OpenAI client for automatic tracing.

        Args:
            client: Specific OpenAI client to instrument, or None for global instrumentation.

        Note:
            When a specific client is provided, it will always be instrumented
            regardless of whether global instrumentation was already called.
            This is necessary because global instrumentation must happen before
            the openai module is imported, but client-specific instrumentation
            can happen at any time.
        """
        global _instrumented_clients

        logfire = self._get_logfire()
        if not logfire:
            return

        try:
            if client:
                # Always instrument specific clients - they may have been created
                # after global instrumentation or the library was imported before
                # global instrumentation could take effect
                logfire.instrument_openai(client)
                logger.debug("OpenAI client instance instrumented for Logfire tracing")
            elif not _instrumented_clients.get("openai"):
                # Global instrumentation - only do once
                logfire.instrument_openai()
                _instrumented_clients["openai"] = True
                logger.debug("OpenAI globally instrumented for Logfire tracing")
        except Exception as e:
            # Log at warning level since user explicitly enabled observability
            logger.warning(f"Could not instrument OpenAI for observability: {e}")

    def instrument_anthropic(self, client=None):
        """
        Instrument Anthropic client for automatic tracing.

        Args:
            client: Specific Anthropic client to instrument, or None for global instrumentation.

        Note:
            When a specific client is provided, it will always be instrumented
            regardless of whether global instrumentation was already called.
            This is necessary because global instrumentation must happen before
            the anthropic module is imported, but client-specific instrumentation
            can happen at any time.
        """
        global _instrumented_clients

        logfire = self._get_logfire()
        if not logfire:
            return

        try:
            if client:
                # Always instrument specific clients - they may have been created
                # after global instrumentation or the library was imported before
                # global instrumentation could take effect
                logfire.instrument_anthropic(client)
                logger.debug(
                    "Anthropic client instance instrumented for Logfire tracing",
                )
            elif not _instrumented_clients.get("anthropic"):
                # Global instrumentation - only do once
                logfire.instrument_anthropic()
                _instrumented_clients["anthropic"] = True
                logger.debug("Anthropic globally instrumented for Logfire tracing")
        except Exception as e:
            # Log at warning level since user explicitly enabled observability
            logger.warning(f"Could not instrument Anthropic for observability: {e}")

    def instrument_google_genai(self):
        """
        Instrument Google GenAI (Gemini) for automatic tracing.

        Note: Set OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
        to capture prompts and completions in spans.
        """
        global _instrumented_clients

        logfire = self._get_logfire()
        if logfire and not _instrumented_clients.get("google_genai"):
            try:
                logfire.instrument_google_genai()
                _instrumented_clients["google_genai"] = True
                logger.debug("Google GenAI instrumented for Logfire tracing")
            except Exception as e:
                # Log at warning level since user explicitly enabled observability
                logger.warning(
                    f"Could not instrument Google GenAI for observability: {e}",
                )

    def instrument_aiohttp(self):
        """Instrument aiohttp for HTTP client tracing."""
        global _instrumented_clients

        logfire = self._get_logfire()
        if logfire and not _instrumented_clients.get("aiohttp"):
            try:
                logfire.instrument_aiohttp_client()
                _instrumented_clients["aiohttp"] = True
                logger.debug("aiohttp instrumented for Logfire tracing")
            except Exception as e:
                # Log at warning level since user explicitly enabled observability
                logger.warning(f"Could not instrument aiohttp for observability: {e}")


class _NoOpSpan:
    """No-operation span for when Logfire is disabled."""

    def set_attribute(self, key: str, value: Any):
        pass

    def record_exception(self, exception: Exception):
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None):
        pass


# Global tracer instance
_tracer: TracerProxy | None = None


def get_tracer() -> TracerProxy:
    """
    Get the global tracer instance.

    Returns:
        TracerProxy that can be used for creating spans and logging.
    """
    global _tracer
    if _tracer is None:
        _tracer = TracerProxy()
    return _tracer


def set_current_round(round_number: int, round_type: str) -> None:
    """
    Set the current round context for tool call attribution.

    This should be called when entering an agent round span so that
    nested tool calls can be properly attributed to the round.

    Args:
        round_number: The current round number (0, 1, 2, etc.)
        round_type: The type of round ("initial_answer", "voting", "presentation")
    """
    _current_round.set(round_number)
    _current_round_type.set(round_type)


def get_current_round() -> tuple[int | None, str | None]:
    """
    Get the current round context for tool call attribution.

    Returns:
        Tuple of (round_number, round_type) or (None, None) if not in a round.
    """
    return _current_round.get(), _current_round_type.get()


def clear_current_round() -> None:
    """Clear the current round context."""
    _current_round.set(None)
    _current_round_type.set(None)


def trace_llm_call(
    backend_name: str,
    model: str,
    agent_id: str | None = None,
    round_number: int | None = None,
):
    """
    Decorator for tracing LLM API calls.

    Args:
        backend_name: Name of the LLM backend (e.g., "openai", "anthropic").
        model: Model name being called.
        agent_id: Optional agent ID for context.
        round_number: Optional round number for context.

    Returns:
        Decorator function.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            attributes = {
                "llm.backend": backend_name,
                "llm.model": model,
            }
            if agent_id:
                attributes["massgen.agent_id"] = agent_id
            if round_number is not None:
                attributes["massgen.round_number"] = round_number

            with tracer.span(f"llm.call.{backend_name}", attributes=attributes):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            attributes = {
                "llm.backend": backend_name,
                "llm.model": model,
            }
            if agent_id:
                attributes["massgen.agent_id"] = agent_id
            if round_number is not None:
                attributes["massgen.round_number"] = round_number

            with tracer.span(f"llm.call.{backend_name}", attributes=attributes):
                return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def trace_tool_call(
    tool_name: str,
    tool_type: str = "custom",
    agent_id: str | None = None,
):
    """
    Decorator for tracing tool calls.

    Args:
        tool_name: Name of the tool being called.
        tool_type: Type of tool (custom, mcp, builtin).
        agent_id: Optional agent ID for context.

    Returns:
        Decorator function.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            attributes = {
                "tool.name": tool_name,
                "tool.type": tool_type,
            }
            if agent_id:
                attributes["massgen.agent_id"] = agent_id

            with tracer.span(f"tool.{tool_name}", attributes=attributes) as span:
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("tool.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(e))
                    raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            attributes = {
                "tool.name": tool_name,
                "tool.type": tool_type,
            }
            if agent_id:
                attributes["massgen.agent_id"] = agent_id

            with tracer.span(f"tool.{tool_name}", attributes=attributes) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("tool.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(e))
                    raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


@contextmanager
def trace_orchestrator_operation(
    operation: str,
    task: str | None = None,
    num_agents: int | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing orchestrator operations.

    Args:
        operation: Name of the orchestrator operation (e.g., "coordinate", "vote", "present").
        task: The current task/question being processed.
        num_agents: Number of agents involved.
        **extra_attributes: Additional attributes to attach to the span.

    Yields:
        Span object for adding additional attributes.
    """
    tracer = get_tracer()
    attributes = {
        "massgen.operation": operation,
    }
    if task:
        attributes["massgen.task"] = task[:500]  # Truncate long tasks
    if num_agents is not None:
        attributes["massgen.num_agents"] = num_agents

    attributes.update(extra_attributes)

    with tracer.span(f"orchestrator.{operation}", attributes=attributes) as span:
        yield span


@contextmanager
def trace_agent_execution(
    agent_id: str,
    backend_name: str,
    model: str,
    round_number: int,
    round_type: str = "coordination",
    **extra_attributes,
):
    """
    Context manager for tracing agent execution within a round.

    Args:
        agent_id: ID of the agent.
        backend_name: Name of the backend provider.
        model: Model being used.
        round_number: Current round number.
        round_type: Type of round (coordination, voting, presentation).
        **extra_attributes: Additional attributes to attach to the span.

    Yields:
        Span object for adding additional attributes.
    """
    tracer = get_tracer()
    attributes = {
        "massgen.agent_id": agent_id,
        "llm.backend": backend_name,
        "llm.model": model,
        "massgen.round_number": round_number,
        "massgen.round_type": round_type,
    }
    attributes.update(extra_attributes)

    with tracer.span(
        f"agent.{agent_id}.round_{round_number}",
        attributes=attributes,
    ) as span:
        yield span


def log_token_usage(
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    cached_tokens: int = 0,
    estimated_cost: float = 0.0,
    model: str | None = None,
):
    """
    Log token usage as a structured event.

    Args:
        agent_id: ID of the agent.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        reasoning_tokens: Number of reasoning tokens (for models that support it).
        cached_tokens: Number of cached input tokens.
        estimated_cost: Estimated cost in USD.
        model: Model name (optional).
    """
    tracer = get_tracer()
    tracer.info(
        "Token usage recorded",
        agent_id=agent_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached_tokens,
        estimated_cost=round(estimated_cost, 6),
        model=model or "unknown",
    )


def log_tool_execution(
    agent_id: str,
    tool_name: str,
    tool_type: str,
    execution_time_ms: float,
    success: bool,
    input_chars: int = 0,
    output_chars: int = 0,
    error_message: str | None = None,
    # New fields for richer context
    server_name: str | None = None,
    arguments_preview: str | None = None,
    output_preview: str | None = None,
    round_number: int | None = None,
    round_type: str | None = None,
    # New workflow analysis fields (MAS-199)
    error_context: str | None = None,
):
    """
    Log tool execution as a structured event.

    Args:
        agent_id: ID of the agent.
        tool_name: Name of the tool.
        tool_type: Type of tool (custom, mcp, builtin).
        execution_time_ms: Execution time in milliseconds.
        success: Whether the execution was successful.
        input_chars: Number of input characters.
        output_chars: Number of output characters.
        error_message: Error message if execution failed.
        server_name: MCP server name (for MCP tools).
        arguments_preview: First 200 chars of tool arguments.
        output_preview: First 200 chars of tool output.
        round_number: Which round this tool was called in.
        round_type: Type of round (initial_answer, voting, presentation).
        error_context: Additional error context for debugging (MAS-199).
    """
    tracer = get_tracer()
    log_func = tracer.info if success else tracer.warning

    # Auto-fill round context if not provided
    if round_number is None or round_type is None:
        ctx_round, ctx_type = get_current_round()
        if round_number is None:
            round_number = ctx_round
        if round_type is None:
            round_type = ctx_type

    # Prepare error context preview (MAS-199)
    from massgen.structured_logging_utils import PREVIEW_ERROR_CONTEXT

    error_context_preview = None
    if error_context:
        error_context_preview = error_context[:PREVIEW_ERROR_CONTEXT] + "..." if len(error_context) > PREVIEW_ERROR_CONTEXT else error_context

    log_func(
        f"Tool execution: {tool_name}",
        agent_id=agent_id,
        tool_name=tool_name,
        tool_type=tool_type,
        execution_time_ms=round(execution_time_ms, 2),
        success=success,
        input_chars=input_chars,
        output_chars=output_chars,
        error_message=error_message,
        server_name=server_name,
        arguments_preview=arguments_preview[:200] if arguments_preview else None,
        output_preview=output_preview[:200] if output_preview else None,
        round_number=round_number,
        round_type=round_type,
        # Workflow analysis attribute (MAS-199)
        **{"massgen.tool.error_context": error_context_preview} if error_context_preview else {},
    )


def log_context_compression(
    agent_id: str,
    reason: str,
    original_message_count: int,
    compressed_message_count: int,
    original_char_count: int = 0,
    compressed_char_count: int = 0,
    compression_ratio: float = 0.0,
    success: bool = True,
    error_message: str | None = None,
):
    """
    Log context compression event as a structured event.

    Args:
        agent_id: ID of the agent whose context was compressed.
        reason: Reason for compression (e.g., "context_length_exceeded", "proactive").
        original_message_count: Number of messages before compression.
        compressed_message_count: Number of messages after compression.
        original_char_count: Character count before compression.
        compressed_char_count: Character count after compression.
        compression_ratio: Ratio of compression (0.0-1.0, where 0.2 means 20% of original).
        success: Whether compression was successful.
        error_message: Error message if compression failed.
    """
    tracer = get_tracer()
    tracer.info(
        "Context compression performed",
        agent_id=agent_id,
        reason=reason,
        original_message_count=original_message_count,
        compressed_message_count=compressed_message_count,
        original_char_count=original_char_count,
        compressed_char_count=compressed_char_count,
        compression_ratio=round(compression_ratio, 4),
        success=success,
        error_message=error_message,
    )


def log_coordination_event(
    event_type: str,
    agent_id: str | None = None,
    details: dict[str, Any] | None = None,
):
    """
    Log a coordination event.

    Args:
        event_type: Type of coordination event (e.g., "answer_submitted", "vote_cast", "winner_selected").
        agent_id: ID of the agent involved (if applicable).
        details: Additional details about the event.
    """
    tracer = get_tracer()
    tracer.info(
        f"Coordination event: {event_type}",
        event_type=event_type,
        agent_id=agent_id,
        **(details or {}),
    )


def log_agent_restart(
    agent_id: str,
    reason: str,
    triggering_agent: str | None = None,
    restart_count: int = 1,
    affected_agents: list[str] | None = None,
    # New workflow analysis fields (MAS-199)
    restart_trigger: str | None = None,
):
    """
    Log when an agent restart is triggered or completed.

    This is crucial for understanding coordination flow and debugging
    why agents restarted during a session.

    Args:
        agent_id: ID of the agent being restarted.
        reason: Reason for the restart (e.g., "new_answer_available", "api_error", "mcp_disconnect").
        triggering_agent: ID of the agent that triggered this restart (if any).
        restart_count: How many times this agent has restarted in this session.
        affected_agents: List of all agents affected by this restart event.
        restart_trigger: Type of trigger - "new_answer", "vote_change", "manual" (MAS-199).
    """
    tracer = get_tracer()

    from massgen.structured_logging_utils import PREVIEW_RESTART_REASON

    # Truncate reason for logging
    reason_preview = reason[:PREVIEW_RESTART_REASON] + "..." if reason and len(reason) > PREVIEW_RESTART_REASON else reason

    tracer.info(
        "Agent restart: {agent_id} (reason: {reason})",
        event_type="agent_restart",
        agent_id=agent_id,
        reason=reason_preview,
        triggering_agent=triggering_agent,
        restart_count=restart_count,
        affected_agents=",".join(affected_agents) if affected_agents else None,
        # Workflow analysis attributes (MAS-199)
        **{
            "massgen.restart.reason": reason_preview,
            "massgen.restart.trigger": restart_trigger,
            "massgen.restart.triggered_by_agent": triggering_agent,
        },
    )


# Coordination iteration tracking for hierarchical spans
_current_iteration_span: Any | None = None
_current_coordination_span: Any | None = None


@contextmanager
def trace_coordination_session(
    task: str,
    num_agents: int,
    agent_ids: list | None = None,
    # New workflow analysis fields (MAS-199)
    log_path: str | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing an entire coordination session.

    This creates the top-level span that contains all iterations/rounds.
    All iteration spans will be nested under this span.

    Args:
        task: The user's question/task being processed.
        num_agents: Number of agents participating.
        agent_ids: List of agent IDs.
        log_path: Path to the run's log directory (MAS-199).
        **extra_attributes: Additional attributes to attach to the span.

    Yields:
        Span object for adding additional attributes.

    Example:
        with trace_coordination_session(task="What is AI?", num_agents=3) as session_span:
            for i in range(max_iterations):
                with trace_coordination_iteration(iteration=i+1):
                    # Run agents
                    pass
    """
    global _current_coordination_span

    tracer = get_tracer()
    attributes = {
        "massgen.task": task[:500] if task else "",
        "massgen.num_agents": num_agents,
    }
    if agent_ids:
        attributes["massgen.agent_ids"] = ",".join(agent_ids)
    # Workflow analysis attribute (MAS-199)
    if log_path:
        attributes["massgen.log_path"] = log_path
    attributes.update(extra_attributes)

    with tracer.span("coordination.session", attributes=attributes) as span:
        _current_coordination_span = span
        try:
            yield span
        finally:
            _current_coordination_span = None


@contextmanager
def trace_coordination_iteration(
    iteration: int,
    available_answers: list | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing a single coordination iteration (round).

    Each iteration represents one round where agents can submit answers or vote.
    This should be called within a trace_coordination_session context.

    Args:
        iteration: The iteration number (1-based).
        available_answers: List of available answer labels at start of iteration.
        **extra_attributes: Additional attributes to attach to the span.

    Yields:
        Span object for adding additional attributes.

    Example:
        with trace_coordination_iteration(iteration=1, available_answers=["agent1.1"]):
            # Agent executions happen here
            log_agent_answer(agent_id="agent_a", answer_label="agent1.2")
            log_agent_vote(agent_id="agent_b", voted_for_label="agent1.2")
    """
    global _current_iteration_span

    tracer = get_tracer()
    attributes = {
        "massgen.iteration": iteration,
        "massgen.round": iteration,  # Alias for clarity
    }
    if available_answers:
        attributes["massgen.available_answers"] = ",".join(available_answers)
    attributes.update(extra_attributes)

    with tracer.span(
        f"coordination.iteration.{iteration}",
        attributes=attributes,
    ) as span:
        _current_iteration_span = span
        try:
            yield span
        finally:
            _current_iteration_span = None


@contextmanager
def trace_agent_round(
    agent_id: str,
    iteration: int,
    round_type: str = "coordination",
    context_labels: list | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing a single agent's execution within an iteration.

    This creates a child span under the current iteration for agent-specific work.

    Args:
        agent_id: ID of the agent.
        iteration: Current iteration number.
        round_type: Type of round (coordination, voting, presentation, final).
        context_labels: Answer labels visible to this agent.
        **extra_attributes: Additional attributes.

    Yields:
        Span object for adding additional attributes.
    """
    tracer = get_tracer()
    attributes = {
        "massgen.agent_id": agent_id,
        "massgen.iteration": iteration,
        "massgen.round_type": round_type,
    }
    if context_labels:
        attributes["massgen.context_labels"] = ",".join(context_labels)
    attributes.update(extra_attributes)

    with tracer.span(
        f"agent.{agent_id}.iteration_{iteration}",
        attributes=attributes,
    ) as span:
        yield span


def log_agent_round_context(
    agent_id: str,
    round_number: int,
    round_type: str,
    answers_in_context: dict[str, str] | None = None,
    answer_labels: list | None = None,
    # New workflow analysis fields (MAS-199)
    round_intent: str | None = None,
    agent_log_path: str | None = None,
):
    """
    Log the context an agent has when starting a round.

    This is crucial for understanding what information each agent had available
    when making decisions (voting, answering, etc.).

    Args:
        agent_id: ID of the agent.
        round_number: The round number for this agent.
        round_type: Type of round ("initial_answer", "voting", "presentation").
        answers_in_context: Dict of agent_id -> answer content that this agent can see.
        answer_labels: List of answer labels available (e.g., ["agent1.1", "agent2.1"]).
        round_intent: What the agent was asked to do this round (for workflow analysis).
        agent_log_path: Path to agent's log directory (for hybrid local access).
    """
    tracer = get_tracer()

    num_answers = len(answers_in_context) if answers_in_context else 0
    answer_providers = list(answers_in_context.keys()) if answers_in_context else []

    # Create preview of each answer (using PREVIEW_ANSWER_EACH constant)
    from massgen.structured_logging_utils import (
        PREVIEW_ANSWER_EACH,
        PREVIEW_ROUND_INTENT,
    )

    answer_previews = {}
    if answers_in_context:
        for aid, content in answers_in_context.items():
            if content:
                preview_len = PREVIEW_ANSWER_EACH
                answer_previews[aid] = content[:preview_len] + "..." if len(content) > preview_len else content

    # Truncate round intent
    intent_preview = None
    if round_intent:
        intent_preview = round_intent[:PREVIEW_ROUND_INTENT] + "..." if len(round_intent) > PREVIEW_ROUND_INTENT else round_intent

    tracer.info(
        f"Agent round context: {agent_id} round_{round_number}",
        event_type="agent_round_context",
        agent_id=agent_id,
        round_number=round_number,
        round_type=round_type,
        num_answers_in_context=num_answers,
        answer_providers=",".join(answer_providers) if answer_providers else None,
        answer_labels=",".join(answer_labels) if answer_labels else None,
        answer_previews=answer_previews if answer_previews else None,
        # Workflow analysis attributes (MAS-199)
        **{
            "massgen.round.intent": intent_preview,
            "massgen.round.available_answers": answer_labels if answer_labels else None,
            "massgen.round.available_answer_count": num_answers,
            "massgen.round.answer_previews": answer_previews if answer_previews else None,
            "massgen.agent.log_path": agent_log_path,
        },
    )


def log_agent_answer(
    agent_id: str,
    answer_label: str,
    iteration: int,
    round_number: int,
    answer_preview: str | None = None,
    # New workflow analysis fields (MAS-199)
    answer_path: str | None = None,
):
    """
    Log when an agent submits an answer.

    Args:
        agent_id: ID of the agent.
        answer_label: Label of the answer (e.g., "agent1.1", "agent2.3").
        iteration: Current iteration number.
        round_number: Agent's round number.
        answer_preview: First 200 chars of the answer (optional).
        answer_path: Path to the agent's answer file (MAS-199).
    """
    tracer = get_tracer()
    tracer.info(
        f"Agent answer: {answer_label}",
        event_type="new_answer",
        agent_id=agent_id,
        answer_label=answer_label,
        iteration=iteration,
        round=round_number,
        answer_preview=answer_preview[:200] if answer_preview else None,
        # Workflow analysis attribute (MAS-199)
        **{"massgen.agent.answer_path": answer_path} if answer_path else {},
    )

    # Also add as span event if we have a current iteration span
    if _current_iteration_span and hasattr(_current_iteration_span, "add_event"):
        _current_iteration_span.add_event(
            f"answer.{answer_label}",
            {"agent_id": agent_id, "label": answer_label},
        )


def log_agent_workspace_files(
    agent_id: str,
    files_created: list[str] | None = None,
    file_count: int = 0,
    workspace_path: str | None = None,
):
    """
    Log files created by an agent in their workspace (MAS-199).

    This enables detection of repeated work and understanding of agent outputs
    through Logfire queries.

    Args:
        agent_id: ID of the agent.
        files_created: List of filenames created (max MAX_FILES_CREATED).
        file_count: Total number of files in workspace.
        workspace_path: Path to agent's workspace directory.
    """
    tracer = get_tracer()

    from massgen.structured_logging_utils import MAX_FILES_CREATED

    # Limit files list
    files_list = None
    if files_created:
        limited_files = files_created[:MAX_FILES_CREATED]
        files_list = ",".join(limited_files)

    if file_count > 0 or files_created:
        tracer.info(
            f"Agent workspace files: {agent_id} ({file_count} files)",
            event_type="agent_workspace_files",
            agent_id=agent_id,
            **{
                "massgen.agent.files_created": files_list,
                "massgen.agent.file_count": file_count,
                "massgen.agent.workspace_path": workspace_path,
            },
        )


def log_agent_vote(
    agent_id: str,
    voted_for_label: str,
    iteration: int,
    round_number: int,
    reason: str | None = None,
    available_answers: list | None = None,
    # New workflow analysis fields (MAS-199)
    agents_with_answers: int | None = None,
    answer_label_mapping: dict[str, str] | None = None,
):
    """
    Log when an agent casts a vote.

    Args:
        agent_id: ID of the voting agent.
        voted_for_label: Label of the answer being voted for.
        iteration: Current iteration number.
        round_number: Agent's round number.
        reason: Agent's reason for voting (optional).
        available_answers: List of available answer labels when voting.
        agents_with_answers: Count of agents who submitted answers (MAS-199).
        answer_label_mapping: Map of labels to agent IDs (MAS-199).
    """
    tracer = get_tracer()

    # Use extended vote reason length (500 chars instead of 200)
    from massgen.structured_logging_utils import PREVIEW_VOTE_REASON

    reason_preview = None
    if reason:
        reason_preview = reason[:PREVIEW_VOTE_REASON] + "..." if len(reason) > PREVIEW_VOTE_REASON else reason

    tracer.info(
        f"Agent vote: {agent_id} -> {voted_for_label}",
        event_type="vote_cast",
        agent_id=agent_id,
        voted_for_label=voted_for_label,
        iteration=iteration,
        round=round_number,
        reason=reason_preview,
        available_answers=",".join(available_answers) if available_answers else None,
        # Workflow analysis attributes (MAS-199)
        **{
            "massgen.vote.reason": reason_preview,
            "massgen.vote.agents_with_answers": agents_with_answers,
            "massgen.vote.answer_label_mapping": answer_label_mapping,
        },
    )

    # Also add as span event if we have a current iteration span
    if _current_iteration_span and hasattr(_current_iteration_span, "add_event"):
        _current_iteration_span.add_event(
            f"vote.{agent_id}",
            {"agent_id": agent_id, "voted_for": voted_for_label},
        )


def log_winner_selected(
    winner_agent_id: str,
    winner_label: str,
    vote_counts: dict[str, int] | None = None,
    total_iterations: int = 0,
):
    """
    Log when a winner is selected after voting.

    Args:
        winner_agent_id: ID of the winning agent.
        winner_label: Label of the winning answer.
        vote_counts: Dictionary of answer labels to vote counts.
        total_iterations: Total number of iterations completed.
    """
    tracer = get_tracer()
    tracer.info(
        f"Winner selected: {winner_label}",
        event_type="winner_selected",
        winner_agent_id=winner_agent_id,
        winner_label=winner_label,
        vote_counts=vote_counts,
        total_iterations=total_iterations,
    )


def log_final_answer(
    agent_id: str,
    iteration: int,
    answer_preview: str | None = None,
):
    """
    Log when the winning agent provides the final answer.

    Args:
        agent_id: ID of the agent providing the final answer.
        iteration: Final iteration number.
        answer_preview: First 200 chars of the final answer.
    """
    tracer = get_tracer()
    tracer.info(
        f"Final answer from {agent_id}",
        event_type="final_answer",
        agent_id=agent_id,
        iteration=iteration,
        answer_preview=answer_preview[:200] if answer_preview else None,
    )


def log_iteration_end(
    iteration: int,
    end_reason: str,
    votes_cast: int = 0,
    answers_provided: int = 0,
):
    """
    Log when an iteration ends.

    Args:
        iteration: The iteration number that ended.
        end_reason: Reason for ending (e.g., "all_voted", "max_rounds", "consensus").
        votes_cast: Number of votes cast in this iteration.
        answers_provided: Number of new answers provided in this iteration.
    """
    tracer = get_tracer()
    tracer.info(
        f"Iteration {iteration} ended: {end_reason}",
        event_type="iteration_end",
        iteration=iteration,
        end_reason=end_reason,
        votes_cast=votes_cast,
        answers_provided=answers_provided,
    )


@contextmanager
def trace_llm_api_call(
    agent_id: str,
    provider: str,
    model: str,
    operation: str = "create",
    **extra_attributes,
):
    """
    Context manager for tracing LLM API calls with agent attribution.

    This creates an explicit span around LLM API calls to ensure:
    1. Agent ID is attached to the span for debugging
    2. The span is visible even if auto-instrumentation fails
    3. Auto-instrumented child spans inherit the context

    Args:
        agent_id: ID of the agent making the call.
        provider: LLM provider name (e.g., "anthropic", "openai", "gemini").
        model: Model name being used.
        operation: API operation (e.g., "create", "stream").
        **extra_attributes: Additional attributes to attach to the span.

    Yields:
        Span object for adding additional attributes.

    Example:
        with trace_llm_api_call("agent_1", "anthropic", "claude-3-opus"):
            stream = await client.messages.create(**params)
    """
    tracer = get_tracer()
    attributes = {
        "massgen.agent_id": agent_id,
        "llm.provider": provider,
        "llm.model": model,
        "llm.operation": operation,
        "gen_ai.system": provider,  # OpenTelemetry semantic convention
        "gen_ai.request.model": model,  # OpenTelemetry semantic convention
    }
    attributes.update(extra_attributes)

    with tracer.span(f"llm.{provider}.{operation}", attributes=attributes) as span:
        yield span


# ==============================================================================
# Subagent Tracing
# ==============================================================================


@contextmanager
def trace_subagent_execution(
    subagent_id: str,
    parent_agent_id: str,
    task: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    # New workflow analysis fields (MAS-199)
    subagent_log_path: str | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing subagent execution.

    This creates a span that covers the full lifecycle of a subagent,
    from spawn to completion or timeout.

    Args:
        subagent_id: Unique ID of the subagent.
        parent_agent_id: ID of the agent that spawned this subagent.
        task: The task assigned to the subagent.
        model: Model being used by the subagent.
        timeout_seconds: Timeout configured for the subagent.
        subagent_log_path: Path to subagent's log directory (MAS-199).
        **extra_attributes: Additional attributes to attach.

    Yields:
        Span object for adding additional attributes.

    Example:
        with trace_subagent_execution("sub_1", "agent_a", "Research topic"):
            result = await execute_subagent(...)
            span.set_attribute("subagent.success", result.success)
    """
    tracer = get_tracer()

    # Use extended task preview (500 chars instead of 200)
    from massgen.structured_logging_utils import PREVIEW_SUBAGENT_TASK

    task_preview = task[:PREVIEW_SUBAGENT_TASK] if task else ""

    attributes = {
        "massgen.subagent_id": subagent_id,
        "massgen.parent_agent_id": parent_agent_id,
        "subagent.task_preview": task_preview,
        # Extended task for workflow analysis (MAS-199)
        "massgen.subagent.task": task_preview,
    }
    if model:
        attributes["subagent.model"] = model
    if timeout_seconds is not None:
        attributes["subagent.timeout_seconds"] = timeout_seconds
    if subagent_log_path:
        attributes["massgen.subagent.log_path"] = subagent_log_path
    attributes.update(extra_attributes)

    with tracer.span(f"subagent.{subagent_id}", attributes=attributes) as span:
        yield span


def log_subagent_spawn(
    subagent_id: str,
    parent_agent_id: str,
    task: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
    context_files: list[str] | None = None,
    execution_mode: str = "foreground",
    # New workflow analysis fields (MAS-199)
    subagent_log_path: str | None = None,
):
    """
    Log a subagent spawn event.

    Args:
        subagent_id: Unique ID of the subagent.
        parent_agent_id: ID of the agent that spawned this subagent.
        task: The task assigned to the subagent.
        model: Model being used by the subagent.
        timeout_seconds: Timeout configured for the subagent.
        context_files: Files copied to subagent workspace.
        execution_mode: "foreground", "background", or "parallel".
        subagent_log_path: Path to subagent's log directory (MAS-199).
    """
    tracer = get_tracer()

    # Use extended task preview (500 chars instead of 200)
    from massgen.structured_logging_utils import PREVIEW_SUBAGENT_TASK

    task_preview = task[:PREVIEW_SUBAGENT_TASK] if task else ""

    attributes = {
        "massgen.subagent_id": subagent_id,
        "massgen.parent_agent_id": parent_agent_id,
        "subagent.task_preview": task_preview,
        "subagent.execution_mode": execution_mode,
        # Extended task for workflow analysis (MAS-199)
        "massgen.subagent.task": task_preview,
    }
    if model:
        attributes["subagent.model"] = model
    if timeout_seconds is not None:
        attributes["subagent.timeout_seconds"] = timeout_seconds
    if context_files:
        attributes["subagent.context_file_count"] = len(context_files)
    if subagent_log_path:
        attributes["massgen.subagent.log_path"] = subagent_log_path

    tracer.info(
        "Subagent spawned: {subagent_id} by {parent_agent_id}",
        subagent_id=subagent_id,
        parent_agent_id=parent_agent_id,
        **attributes,
    )


def log_subagent_complete(
    subagent_id: str,
    parent_agent_id: str,
    status: str,
    execution_time_seconds: float,
    success: bool,
    token_usage: dict[str, int] | None = None,
    error_message: str | None = None,
    answer_preview: str | None = None,
    # New workflow analysis fields (MAS-199)
    files_created: list[str] | None = None,
    file_count: int = 0,
    workspace_path: str | None = None,
):
    """
    Log a subagent completion event.

    Args:
        subagent_id: Unique ID of the subagent.
        parent_agent_id: ID of the agent that spawned this subagent.
        status: Final status ("completed", "timeout", "failed", "cancelled").
        execution_time_seconds: Total execution time.
        success: Whether the subagent succeeded.
        token_usage: Token usage statistics (input_tokens, output_tokens, etc).
        error_message: Error message if failed.
        answer_preview: First 200 chars of the answer if successful.
        files_created: List of filenames created in workspace (MAS-199).
        file_count: Total number of files in workspace (MAS-199).
        workspace_path: Path to subagent's workspace directory (MAS-199).
    """
    tracer = get_tracer()

    from massgen.structured_logging_utils import MAX_FILES_CREATED

    attributes = {
        "massgen.subagent_id": subagent_id,
        "massgen.parent_agent_id": parent_agent_id,
        "subagent.status": status,
        "subagent.execution_time_seconds": execution_time_seconds,
        "subagent.success": success,
    }

    if token_usage:
        for key, value in token_usage.items():
            attributes[f"subagent.tokens.{key}"] = value

    if error_message:
        attributes["subagent.error"] = error_message[:500]

    if answer_preview:
        attributes["subagent.answer_preview"] = answer_preview[:200]

    # Workflow analysis attributes (MAS-199)
    if files_created:
        limited_files = files_created[:MAX_FILES_CREATED]
        attributes["massgen.subagent.files_created"] = ",".join(limited_files)
    attributes["massgen.subagent.file_count"] = file_count
    if workspace_path:
        attributes["massgen.subagent.workspace_path"] = workspace_path

    log_func = tracer.info if success else tracer.warning
    log_func(
        "Subagent {status}: {subagent_id} in {execution_time_seconds:.2f}s",
        subagent_id=subagent_id,
        status=status,
        execution_time_seconds=execution_time_seconds,
        **attributes,
    )


# ==============================================================================
# Persona Generation Tracing
# ==============================================================================


@contextmanager
def trace_persona_generation(
    num_agents: int,
    strategy: str,
    diversity_mode: str | None = None,
    **extra_attributes,
):
    """
    Context manager for tracing persona generation.

    This creates a span for the persona generation process.

    Args:
        num_agents: Number of agents personas are being generated for.
        strategy: The generation strategy being used.
        diversity_mode: The diversity mode (e.g., "perspective", "implementation").
        **extra_attributes: Additional attributes.

    Yields:
        Span object for adding additional attributes.

    Example:
        with trace_persona_generation(3, "cognitive_diversity"):
            personas = await generate_personas(...)
    """
    tracer = get_tracer()

    attributes = {
        "persona.num_agents": num_agents,
        "persona.strategy": strategy,
    }
    if diversity_mode:
        attributes["persona.diversity_mode"] = diversity_mode
    attributes.update(extra_attributes)

    with tracer.span("persona.generation", attributes=attributes) as span:
        yield span


def log_persona_generation(
    agent_ids: list[str],
    strategy: str,
    success: bool,
    generation_time_ms: float,
    used_fallback: bool = False,
    diversity_mode: str | None = None,
    error_message: str | None = None,
):
    """
    Log a persona generation event.

    Args:
        agent_ids: List of agent IDs personas were generated for.
        strategy: The generation strategy used.
        success: Whether generation succeeded.
        generation_time_ms: Time taken in milliseconds.
        used_fallback: Whether fallback personas were used.
        diversity_mode: The diversity mode used.
        error_message: Error message if failed.
    """
    tracer = get_tracer()

    attributes = {
        "persona.agent_ids": ",".join(agent_ids),
        "persona.num_agents": len(agent_ids),
        "persona.strategy": strategy,
        "persona.success": success,
        "persona.generation_time_ms": generation_time_ms,
        "persona.used_fallback": used_fallback,
    }

    if diversity_mode:
        attributes["persona.diversity_mode"] = diversity_mode

    if error_message:
        attributes["persona.error"] = error_message[:500]

    log_func = tracer.info if success else tracer.warning
    log_func(
        "Persona generation {status} for {num_agents} agents in {time_ms:.0f}ms",
        status="succeeded" if success else "failed",
        num_agents=len(agent_ids),
        time_ms=generation_time_ms,
        **attributes,
    )


# Export all public symbols
__all__ = [
    # Configuration
    "configure_observability",
    "is_observability_enabled",
    "get_config",
    "get_tracer",
    "TracerProxy",
    "ObservabilityConfig",
    # Decorators
    "trace_llm_call",
    "trace_tool_call",
    # Context managers for hierarchical tracing
    "trace_orchestrator_operation",
    "trace_agent_execution",
    "trace_coordination_session",
    "trace_coordination_iteration",
    "trace_agent_round",
    "trace_llm_api_call",
    # Round context (for propagating round info to nested calls)
    "set_current_round",
    "get_current_round",
    "clear_current_round",
    # Event loggers
    "log_token_usage",
    "log_tool_execution",
    "log_coordination_event",
    "log_agent_restart",
    # Coordination-specific loggers
    "log_agent_round_context",
    "log_agent_answer",
    "log_agent_workspace_files",  # MAS-199
    "log_agent_vote",
    "log_winner_selected",
    "log_final_answer",
    "log_iteration_end",
    # Subagent tracing
    "trace_subagent_execution",
    "log_subagent_spawn",
    "log_subagent_complete",
    # Persona generation tracing
    "trace_persona_generation",
    "log_persona_generation",
]
