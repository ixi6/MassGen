"""
Tests for structured logging module.

These tests verify:
- TracerProxy graceful degradation when Logfire is disabled
- Configuration options work correctly
- Context managers and decorators function properly
"""

import pytest

from massgen.structured_logging import (
    ObservabilityConfig,
    TracerProxy,
    configure_observability,
    get_tracer,
    is_observability_enabled,
    log_coordination_event,
    log_token_usage,
    log_tool_execution,
    trace_agent_execution,
    trace_orchestrator_operation,
)


class TestTracerProxy:
    """Tests for TracerProxy graceful degradation."""

    def test_tracer_proxy_span_when_disabled(self):
        """TracerProxy.span() should work when Logfire is disabled."""
        tracer = TracerProxy()
        # Should not raise even when Logfire is disabled
        with tracer.span("test_span", attributes={"key": "value"}) as span:
            span.set_attribute("test", "value")
            span.record_exception(ValueError("test"))
            span.add_event("test_event", {"attr": "value"})

    def test_tracer_proxy_info_when_disabled(self):
        """TracerProxy.info() should fall back to loguru when Logfire is disabled."""
        tracer = TracerProxy()
        # Should not raise
        tracer.info("Test message", key="value")

    def test_tracer_proxy_debug_when_disabled(self):
        """TracerProxy.debug() should fall back to loguru when Logfire is disabled."""
        tracer = TracerProxy()
        tracer.debug("Test debug message", key="value")

    def test_tracer_proxy_warning_when_disabled(self):
        """TracerProxy.warning() should fall back to loguru when Logfire is disabled."""
        tracer = TracerProxy()
        tracer.warning("Test warning message", key="value")

    def test_tracer_proxy_error_when_disabled(self):
        """TracerProxy.error() should fall back to loguru when Logfire is disabled."""
        tracer = TracerProxy()
        tracer.error("Test error message", key="value")

    def test_instrument_methods_graceful_when_disabled(self):
        """Instrumentation methods should not raise when Logfire is disabled."""
        tracer = TracerProxy()
        # These should not raise even when Logfire is not configured
        tracer.instrument_openai(None)
        tracer.instrument_anthropic(None)
        tracer.instrument_aiohttp()


class TestConfiguration:
    """Tests for observability configuration."""

    def test_configure_observability_disabled_by_default(self):
        """Observability should be disabled when enabled=False."""
        result = configure_observability(enabled=False)
        assert result is False
        assert is_observability_enabled() is False

    def test_configure_observability_with_env_var(self, monkeypatch):
        """Observability should respect MASSGEN_LOGFIRE_ENABLED env var."""
        # Disabled by default
        monkeypatch.delenv("MASSGEN_LOGFIRE_ENABLED", raising=False)
        result = configure_observability(enabled=None)
        assert result is False

    def test_get_tracer_returns_singleton(self):
        """get_tracer() should return the same instance."""
        tracer1 = get_tracer()
        tracer2 = get_tracer()
        assert tracer1 is tracer2

    def test_observability_config_defaults(self):
        """ObservabilityConfig should have sensible defaults."""
        config = ObservabilityConfig()
        assert config.enabled is False
        assert config.service_name == "massgen"
        assert config.environment == "development"
        assert config.send_to_logfire is True
        assert config.scrub_sensitive_data is True


class TestContextManagers:
    """Tests for tracing context managers."""

    def test_trace_orchestrator_operation(self):
        """trace_orchestrator_operation should work without errors."""
        with trace_orchestrator_operation(
            "test_operation",
            task="Test task",
            num_agents=3,
        ) as span:
            # Should be able to access span
            assert span is not None

    def test_trace_agent_execution(self):
        """trace_agent_execution should work without errors."""
        with trace_agent_execution(
            agent_id="agent_1",
            backend_name="openai",
            model="gpt-4",
            round_number=1,
            round_type="coordination",
        ) as span:
            assert span is not None


class TestEventLoggers:
    """Tests for structured event logging functions."""

    def test_log_token_usage(self):
        """log_token_usage should not raise."""
        # Should not raise
        log_token_usage(
            agent_id="agent_1",
            input_tokens=100,
            output_tokens=50,
            reasoning_tokens=10,
            cached_tokens=5,
            estimated_cost=0.001,
            model="gpt-4",
        )

    def test_log_tool_execution_success(self):
        """log_tool_execution should handle success case."""
        log_tool_execution(
            agent_id="agent_1",
            tool_name="mcp__server__tool",
            tool_type="mcp",
            execution_time_ms=150.5,
            success=True,
            input_chars=100,
            output_chars=200,
        )

    def test_log_tool_execution_failure(self):
        """log_tool_execution should handle failure case."""
        log_tool_execution(
            agent_id="agent_1",
            tool_name="mcp__server__tool",
            tool_type="mcp",
            execution_time_ms=50.0,
            success=False,
            error_message="Tool execution failed",
        )

    def test_log_coordination_event(self):
        """log_coordination_event should not raise."""
        log_coordination_event(
            event_type="winner_selected",
            agent_id="agent_1",
            details={"turn": 1, "vote_count": 3},
        )

    def test_log_coordination_event_minimal(self):
        """log_coordination_event should work with minimal args."""
        log_coordination_event(event_type="coordination_started")


class TestDecorators:
    """Tests for tracing decorators."""

    def test_trace_llm_call_decorator_sync(self):
        """trace_llm_call decorator should work with sync functions."""
        from massgen.structured_logging import trace_llm_call

        @trace_llm_call(backend_name="openai", model="gpt-4")
        def sync_function():
            return "result"

        result = sync_function()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_trace_llm_call_decorator_async(self):
        """trace_llm_call decorator should work with async functions."""
        from massgen.structured_logging import trace_llm_call

        @trace_llm_call(backend_name="anthropic", model="claude-3")
        async def async_function():
            return "async_result"

        result = await async_function()
        assert result == "async_result"

    def test_trace_tool_call_decorator_sync(self):
        """trace_tool_call decorator should work with sync functions."""
        from massgen.structured_logging import trace_tool_call

        @trace_tool_call(tool_name="test_tool", tool_type="custom")
        def sync_tool():
            return {"success": True}

        result = sync_tool()
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_trace_tool_call_decorator_async(self):
        """trace_tool_call decorator should work with async functions."""
        from massgen.structured_logging import trace_tool_call

        @trace_tool_call(tool_name="async_tool", tool_type="mcp")
        async def async_tool():
            return {"success": True}

        result = await async_tool()
        assert result == {"success": True}

    def test_trace_tool_call_handles_exceptions(self):
        """trace_tool_call should record exceptions properly."""
        from massgen.structured_logging import trace_tool_call

        @trace_tool_call(tool_name="failing_tool", tool_type="custom")
        def failing_tool():
            raise ValueError("Tool failed")

        with pytest.raises(ValueError, match="Tool failed"):
            failing_tool()


class TestCoordinationTracing:
    """Tests for coordination-specific tracing functions."""

    def test_trace_coordination_session(self):
        """trace_coordination_session context manager should work."""
        from massgen.structured_logging import trace_coordination_session

        with trace_coordination_session(
            task="Test task",
            num_agents=3,
            agent_ids=["agent_a", "agent_b", "agent_c"],
        ) as span:
            assert span is not None

    def test_trace_coordination_iteration(self):
        """trace_coordination_iteration context manager should work."""
        from massgen.structured_logging import trace_coordination_iteration

        with trace_coordination_iteration(
            iteration=1,
            available_answers=["agent1.1", "agent2.1"],
        ) as span:
            assert span is not None

    def test_trace_agent_round(self):
        """trace_agent_round context manager should work."""
        from massgen.structured_logging import trace_agent_round

        with trace_agent_round(
            agent_id="agent_a",
            iteration=1,
            round_type="coordination",
            context_labels=["agent1.1"],
        ) as span:
            assert span is not None

    def test_log_agent_answer(self):
        """log_agent_answer should not raise."""
        from massgen.structured_logging import log_agent_answer

        log_agent_answer(
            agent_id="agent_a",
            answer_label="agent1.1",
            iteration=1,
            round_number=1,
            answer_preview="This is a test answer...",
        )

    def test_log_agent_vote(self):
        """log_agent_vote should not raise."""
        from massgen.structured_logging import log_agent_vote

        log_agent_vote(
            agent_id="agent_b",
            voted_for_label="agent1.1",
            iteration=1,
            round_number=1,
            reason="Better solution",
            available_answers=["agent1.1", "agent2.1"],
        )

    def test_log_winner_selected(self):
        """log_winner_selected should not raise."""
        from massgen.structured_logging import log_winner_selected

        log_winner_selected(
            winner_agent_id="agent_a",
            winner_label="agent1.1",
            vote_counts={"agent1.1": 2, "agent2.1": 1},
            total_iterations=3,
        )

    def test_log_final_answer(self):
        """log_final_answer should not raise."""
        from massgen.structured_logging import log_final_answer

        log_final_answer(
            agent_id="agent_a",
            iteration=3,
            answer_preview="This is the final answer...",
        )

    def test_log_iteration_end(self):
        """log_iteration_end should not raise."""
        from massgen.structured_logging import log_iteration_end

        log_iteration_end(
            iteration=1,
            end_reason="all_voted",
            votes_cast=3,
            answers_provided=2,
        )

    def test_nested_coordination_spans(self):
        """Nested coordination spans should work correctly."""
        from massgen.structured_logging import (
            log_agent_answer,
            log_agent_vote,
            trace_coordination_iteration,
            trace_coordination_session,
        )

        with trace_coordination_session(
            task="Nested test",
            num_agents=2,
            agent_ids=["agent_a", "agent_b"],
        ):
            with trace_coordination_iteration(iteration=1):
                log_agent_answer(
                    agent_id="agent_a",
                    answer_label="agent1.1",
                    iteration=1,
                    round_number=1,
                )
                log_agent_vote(
                    agent_id="agent_b",
                    voted_for_label="agent1.1",
                    iteration=1,
                    round_number=1,
                )
            with trace_coordination_iteration(iteration=2):
                log_agent_vote(
                    agent_id="agent_a",
                    voted_for_label="agent1.1",
                    iteration=2,
                    round_number=1,
                )


class TestLLMAPICallTracing:
    """Tests for LLM API call tracing with agent attribution."""

    def test_trace_llm_api_call_basic(self):
        """trace_llm_api_call should work as a context manager."""
        from massgen.structured_logging import trace_llm_api_call

        with trace_llm_api_call(
            agent_id="agent_1",
            provider="anthropic",
            model="claude-3-opus",
            operation="stream",
        ):
            # Simulate API call
            pass

    def test_trace_llm_api_call_with_extra_attributes(self):
        """trace_llm_api_call should accept extra attributes."""
        from massgen.structured_logging import trace_llm_api_call

        with trace_llm_api_call(
            agent_id="agent_2",
            provider="openai",
            model="gpt-4o",
            operation="create",
            request_id="test-123",
            max_tokens=1000,
        ):
            pass

    def test_trace_llm_api_call_yields_span(self):
        """trace_llm_api_call should yield a span object."""
        from massgen.structured_logging import trace_llm_api_call

        with trace_llm_api_call(
            agent_id="agent_3",
            provider="gemini",
            model="gemini-pro",
        ) as span:
            # Span should be a valid object (or NoOpSpan)
            assert span is not None

    def test_trace_llm_api_call_handles_exceptions(self):
        """trace_llm_api_call should properly handle exceptions."""
        from massgen.structured_logging import trace_llm_api_call

        try:
            with trace_llm_api_call(
                agent_id="agent_4",
                provider="anthropic",
                model="claude-3-sonnet",
            ):
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected


class TestSubagentTracing:
    """Tests for subagent tracing functions."""

    def test_trace_subagent_execution_basic(self):
        """trace_subagent_execution should work as a context manager."""
        from massgen.structured_logging import trace_subagent_execution

        with trace_subagent_execution(
            subagent_id="sub_1",
            parent_agent_id="agent_a",
            task="Research topic",
            model="gpt-4",
            timeout_seconds=300,
        ) as span:
            # Span should be a valid object (or NoOpSpan)
            assert span is not None

    def test_trace_subagent_execution_yields_span(self):
        """trace_subagent_execution should yield a span for attribute setting."""
        from massgen.structured_logging import trace_subagent_execution

        with trace_subagent_execution(
            subagent_id="sub_2",
            parent_agent_id="agent_b",
            task="Analyze data",
        ) as span:
            # Should be able to set attributes on the span
            span.set_attribute("subagent.success", True)
            span.set_attribute("subagent.execution_time_seconds", 10.5)

    def test_log_subagent_spawn(self):
        """log_subagent_spawn should not raise."""
        from massgen.structured_logging import log_subagent_spawn

        log_subagent_spawn(
            subagent_id="sub_3",
            parent_agent_id="agent_c",
            task="Write a report on market trends",
            model="claude-3-opus",
            timeout_seconds=600,
            context_files=["data.csv", "report_template.md"],
            execution_mode="foreground",
        )

    def test_log_subagent_spawn_minimal(self):
        """log_subagent_spawn should work with minimal args."""
        from massgen.structured_logging import log_subagent_spawn

        log_subagent_spawn(
            subagent_id="sub_4",
            parent_agent_id="agent_d",
            task="Simple task",
        )

    def test_log_subagent_complete_success(self):
        """log_subagent_complete should handle success case."""
        from massgen.structured_logging import log_subagent_complete

        log_subagent_complete(
            subagent_id="sub_5",
            parent_agent_id="agent_e",
            status="completed",
            execution_time_seconds=45.3,
            success=True,
            token_usage={"input_tokens": 1000, "output_tokens": 500},
            answer_preview="This is the beginning of the answer...",
        )

    def test_log_subagent_complete_timeout(self):
        """log_subagent_complete should handle timeout case."""
        from massgen.structured_logging import log_subagent_complete

        log_subagent_complete(
            subagent_id="sub_6",
            parent_agent_id="agent_f",
            status="timeout",
            execution_time_seconds=300.0,
            success=False,
            error_message="Timed out after 300s",
        )

    def test_log_subagent_complete_failure(self):
        """log_subagent_complete should handle failure case."""
        from massgen.structured_logging import log_subagent_complete

        log_subagent_complete(
            subagent_id="sub_7",
            parent_agent_id="agent_g",
            status="failed",
            execution_time_seconds=5.2,
            success=False,
            error_message="Connection refused",
        )


class TestPersonaGenerationTracing:
    """Tests for persona generation tracing functions."""

    def test_trace_persona_generation_basic(self):
        """trace_persona_generation should work as a context manager."""
        from massgen.structured_logging import trace_persona_generation

        with trace_persona_generation(
            num_agents=3,
            strategy="cognitive_diversity",
            diversity_mode="perspective",
        ) as span:
            assert span is not None

    def test_trace_persona_generation_yields_span(self):
        """trace_persona_generation should yield a span for attribute setting."""
        from massgen.structured_logging import trace_persona_generation

        with trace_persona_generation(
            num_agents=5,
            strategy="random",
        ) as span:
            span.set_attribute("persona.success", True)
            span.set_attribute("persona.generation_time_ms", 150.5)

    def test_log_persona_generation_success(self):
        """log_persona_generation should handle success case."""
        from massgen.structured_logging import log_persona_generation

        log_persona_generation(
            agent_ids=["agent_a", "agent_b", "agent_c"],
            strategy="cognitive_diversity",
            success=True,
            generation_time_ms=250.5,
            used_fallback=False,
            diversity_mode="perspective",
        )

    def test_log_persona_generation_fallback(self):
        """log_persona_generation should handle fallback case."""
        from massgen.structured_logging import log_persona_generation

        log_persona_generation(
            agent_ids=["agent_d", "agent_e"],
            strategy="implementation_diversity",
            success=False,
            generation_time_ms=50.0,
            used_fallback=True,
            diversity_mode="implementation",
            error_message="LLM API timeout",
        )

    def test_log_persona_generation_minimal(self):
        """log_persona_generation should work with minimal args."""
        from massgen.structured_logging import log_persona_generation

        log_persona_generation(
            agent_ids=["agent_f"],
            strategy="default",
            success=True,
            generation_time_ms=100.0,
        )
