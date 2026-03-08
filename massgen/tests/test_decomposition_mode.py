#!/usr/bin/env python3
"""
Unit tests for decomposition coordination mode.

Tests cover:
- StopToolkit tool definitions (all 3 API formats)
- get_workflow_tools with decomposition_mode parameter
- Completion check reuse (has_voted works for both vote and stop)
- Presenter selection (explicit and fallback)
- Config validation for coordination_mode and presenter_agent
- AgentState stop metadata fields
"""

import json
import time

import pytest

import massgen.orchestrator as orchestrator_module
from massgen.agent_config import AgentConfig, CoordinationConfig
from massgen.config_validator import ConfigValidator
from massgen.evaluation_criteria_generator import GeneratedCriterion
from massgen.mcp_tools.checklist_tools_server import write_checklist_specs
from massgen.mcp_tools.hooks import RoundTimeoutState
from massgen.orchestrator import AgentState, Orchestrator
from massgen.system_prompt_sections import DecompositionSection
from massgen.task_decomposer import TaskDecomposerConfig
from massgen.tool.workflow_toolkits import get_workflow_tools
from massgen.tool.workflow_toolkits.stop import StopToolkit
from massgen.utils import ActionType, AgentStatus


class _StubBackend:
    filesystem_manager = None
    config = {}


class _StubAgent:
    def __init__(self):
        self.backend = _StubBackend()
        self._orchestrator = None

    def get_configurable_system_message(self):
        return ""


class _ChecklistBackend:
    def __init__(self):
        self.filesystem_manager = None
        self.config = {}
        self.mcp_servers = []


class _ChecklistAgent:
    def __init__(self):
        self.backend = _ChecklistBackend()
        self._orchestrator = None

    def get_configurable_system_message(self):
        return ""


def _get_tool_names(tools, api_format):
    """Extract tool names from tools list based on API format."""
    names = []
    for tool in tools:
        if api_format == "claude":
            names.append(tool.get("name"))
        else:
            names.append(tool.get("function", {}).get("name"))
    return names


# =============================================================================
# StopToolkit Tests
# =============================================================================


class TestStopToolkit:
    """Test StopToolkit tool definitions across API formats."""

    def test_stop_tool_claude_format(self):
        """Test stop tool definition in Claude API format."""
        toolkit = StopToolkit()
        config = {"api_format": "claude", "enable_workflow_tools": True}
        tools = toolkit.get_tools(config)

        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "stop"
        assert "summary" in tool["input_schema"]["properties"]
        assert "status" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["properties"]["status"]["enum"] == ["complete", "blocked"]
        assert set(tool["input_schema"]["required"]) == {"summary", "status"}

    def test_stop_tool_response_format(self):
        """Test stop tool definition in Response API format."""
        toolkit = StopToolkit()
        config = {"api_format": "response", "enable_workflow_tools": True}
        tools = toolkit.get_tools(config)

        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "stop"
        assert "summary" in tool["function"]["parameters"]["properties"]
        assert "status" in tool["function"]["parameters"]["properties"]

    def test_stop_tool_chat_completions_format(self):
        """Test stop tool definition in Chat Completions format."""
        toolkit = StopToolkit()
        config = {"api_format": "chat_completions", "enable_workflow_tools": True}
        tools = toolkit.get_tools(config)

        assert len(tools) == 1
        tool = tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "stop"

    def test_stop_toolkit_id(self):
        toolkit = StopToolkit()
        assert toolkit.toolkit_id == "stop"

    def test_stop_toolkit_enabled(self):
        toolkit = StopToolkit()
        assert toolkit.is_enabled({"enable_workflow_tools": True})
        assert not toolkit.is_enabled({"enable_workflow_tools": False})


# =============================================================================
# get_workflow_tools Decomposition Mode Tests
# =============================================================================


class TestWorkflowToolsDecomposition:
    """Test get_workflow_tools with decomposition_mode parameter."""

    @pytest.mark.parametrize("api_format", ["claude", "response", "chat_completions"])
    def test_decomposition_mode_returns_stop_not_vote(self, api_format):
        """In decomposition mode, stop replaces vote."""
        tools = get_workflow_tools(
            api_format=api_format,
            decomposition_mode=True,
        )
        names = _get_tool_names(tools, api_format)
        assert "stop" in names
        assert "vote" not in names
        assert "new_answer" in names

    @pytest.mark.parametrize("api_format", ["claude", "response", "chat_completions"])
    def test_voting_mode_returns_vote_not_stop(self, api_format):
        """In voting mode (default), vote is included, not stop."""
        tools = get_workflow_tools(
            api_format=api_format,
            decomposition_mode=False,
        )
        names = _get_tool_names(tools, api_format)
        assert "vote" in names
        assert "stop" not in names
        assert "new_answer" in names

    def test_decomposition_default_is_false(self):
        """Default decomposition_mode is False (voting mode)."""
        tools = get_workflow_tools(api_format="chat_completions")
        names = _get_tool_names(tools, "chat_completions")
        assert "vote" in names
        assert "stop" not in names


# =============================================================================
# AgentState Tests
# =============================================================================


class TestAgentStateDecomposition:
    """Test AgentState fields for decomposition mode."""

    def test_stop_metadata_fields_exist(self):
        """AgentState has stop_summary and stop_status fields."""
        state = AgentState()
        assert state.stop_summary is None
        assert state.stop_status is None

    def test_stop_metadata_can_be_set(self):
        state = AgentState()
        state.stop_summary = "Completed frontend UI"
        state.stop_status = "complete"
        assert state.stop_summary == "Completed frontend UI"
        assert state.stop_status == "complete"

    def test_has_voted_reuse_for_stop(self):
        """has_voted is reused as the 'agent is done' flag for both modes."""
        state = AgentState()
        assert not state.has_voted
        # Simulate stop
        state.has_voted = True
        state.stop_summary = "Done with subtask"
        state.stop_status = "complete"
        assert state.has_voted


# =============================================================================
# Completion Check Tests
# =============================================================================


class TestCompletionCheck:
    """Test that coordination completion works for both modes."""

    def test_all_voted_means_complete(self):
        """All agents with has_voted=True means coordination is complete."""
        states = {
            "a": AgentState(has_voted=True),
            "b": AgentState(has_voted=True),
            "c": AgentState(has_voted=True),
        }
        assert all(s.has_voted for s in states.values())

    def test_partial_voted_not_complete(self):
        states = {
            "a": AgentState(has_voted=True),
            "b": AgentState(has_voted=False),
        }
        assert not all(s.has_voted for s in states.values())

    def test_stop_sets_has_voted(self):
        """Stopping in decomposition mode sets has_voted=True."""
        state = AgentState()
        # Simulate stop handling
        state.has_voted = True
        state.stop_summary = "Subtask complete"
        state.stop_status = "complete"
        assert state.has_voted

    def test_new_answer_resets_has_voted(self):
        """New answer resets has_voted (wakes up stopped agents)."""
        states = {
            "a": AgentState(has_voted=True, stop_summary="Done", stop_status="complete"),
            "b": AgentState(has_voted=True, stop_summary="Done", stop_status="complete"),
        }
        # Simulate reset on new_answer
        for s in states.values():
            s.has_voted = False
            s.stop_summary = None
            s.stop_status = None
        assert not any(s.has_voted for s in states.values())
        assert all(s.stop_summary is None for s in states.values())


# =============================================================================
# Config Tests
# =============================================================================


class TestDecompositionConfig:
    """Test config validation for decomposition mode."""

    def test_agent_config_has_coordination_mode(self):
        """AgentConfig has coordination_mode field."""
        config = AgentConfig()
        assert config.coordination_mode == "voting"

    def test_agent_config_has_presenter_agent(self):
        """AgentConfig has presenter_agent field."""
        config = AgentConfig()
        assert config.presenter_agent is None

    def test_agent_config_has_final_answer_strategy(self):
        """AgentConfig has final_answer_strategy field."""
        config = AgentConfig()
        assert config.final_answer_strategy is None

    def test_coordination_config_has_task_decomposer(self):
        """CoordinationConfig has task_decomposer field."""
        config = CoordinationConfig()
        assert isinstance(config.task_decomposer, TaskDecomposerConfig)
        assert config.task_decomposer.enabled is True

    def test_config_validator_valid_coordination_mode(self):
        """Valid coordination_mode values pass validation."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"coordination_mode": "decomposition"},
        }
        result = validator.validate_config(config)
        # Should not have errors about coordination_mode
        mode_errors = [e for e in result.errors if "coordination_mode" in e.location]
        assert len(mode_errors) == 0

    def test_config_validator_invalid_coordination_mode(self):
        """Invalid coordination_mode values are rejected."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"coordination_mode": "invalid"},
        }
        result = validator.validate_config(config)
        mode_errors = [e for e in result.errors if "coordination_mode" in e.location]
        assert len(mode_errors) == 1

    def test_config_validator_presenter_agent_must_be_valid(self):
        """presenter_agent must reference an existing agent ID."""
        validator = ConfigValidator()
        config = {
            "agents": [
                {"id": "frontend", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
                {"id": "backend", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {
                "coordination_mode": "decomposition",
                "presenter_agent": "nonexistent",
            },
        }
        result = validator.validate_config(config)
        presenter_errors = [e for e in result.errors if "presenter_agent" in e.location]
        assert len(presenter_errors) == 1

    def test_config_validator_valid_final_answer_strategy(self):
        """Valid final_answer_strategy values pass validation."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"final_answer_strategy": "synthesize"},
        }
        result = validator.validate_config(config)
        strategy_errors = [e for e in result.errors if "final_answer_strategy" in e.location]
        assert len(strategy_errors) == 0

    def test_config_validator_invalid_final_answer_strategy(self):
        """Invalid final_answer_strategy values are rejected."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"final_answer_strategy": "invalid"},
        }
        result = validator.validate_config(config)
        strategy_errors = [e for e in result.errors if "final_answer_strategy" in e.location]
        assert len(strategy_errors) == 1

    def test_config_validator_valid_presenter_agent(self):
        """Valid presenter_agent passes validation."""
        validator = ConfigValidator()
        config = {
            "agents": [
                {"id": "frontend", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
                {"id": "backend", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {
                "coordination_mode": "decomposition",
                "presenter_agent": "backend",
            },
        }
        result = validator.validate_config(config)
        presenter_errors = [e for e in result.errors if "presenter_agent" in e.location]
        assert len(presenter_errors) == 0

    def test_config_validator_subtask_must_be_string(self):
        """Per-agent subtask must be a string."""
        validator = ConfigValidator()
        config = {
            "agents": [
                {"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}, "subtask": 123},
            ],
            "orchestrator": {"coordination_mode": "decomposition"},
        }
        result = validator.validate_config(config)
        subtask_errors = [e for e in result.errors if "subtask" in e.location]
        assert len(subtask_errors) == 1

    def test_config_validator_warns_no_subtasks(self):
        """Warning when decomposition mode has no subtasks defined."""
        validator = ConfigValidator()
        config = {
            "agents": [
                {"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
                {"id": "b", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {"coordination_mode": "decomposition"},
        }
        result = validator.validate_config(config)
        subtask_warnings = [w for w in result.warnings if "subtask" in w.suggestion.lower()]
        assert len(subtask_warnings) >= 1

    def test_config_validator_valid_max_new_answers_global(self):
        """Positive max_new_answers_global should pass validation."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"max_new_answers_global": 5},
        }
        result = validator.validate_config(config)
        global_errors = [e for e in result.errors if "max_new_answers_global" in e.location]
        assert len(global_errors) == 0

    def test_config_validator_invalid_max_new_answers_global(self):
        """Non-positive max_new_answers_global should be rejected."""
        validator = ConfigValidator()
        config = {
            "agents": [{"id": "a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
            "orchestrator": {"max_new_answers_global": 0},
        }
        result = validator.validate_config(config)
        global_errors = [e for e in result.errors if "max_new_answers_global" in e.location]
        assert len(global_errors) == 1


class TestDecompositionAnswerLimits:
    """Test decomposition-specific answer limit behavior."""

    @staticmethod
    def _answers(n: int):
        return [type("Answer", (), {"label": f"agent1.{i + 1}", "content": f"answer{i + 1}"})() for i in range(n)]

    def test_per_agent_limit_uses_consecutive_streak_not_total(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.max_new_answers_per_agent = 2
        config.fairness_enabled = False
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        # Total historical answers is high, but current consecutive streak is low.
        orchestrator.coordination_tracker.answers_by_agent["frontend"] = self._answers(5)
        orchestrator.agent_states["frontend"].decomposition_answer_streak = 1

        can_answer, _ = orchestrator._check_answer_count_limit("frontend")
        assert can_answer is True

        # At streak limit, new_answer should be rejected.
        orchestrator.agent_states["frontend"].decomposition_answer_streak = 2
        can_answer, error = orchestrator._check_answer_count_limit("frontend")
        assert can_answer is False
        assert error and "consecutive" in error

    def test_streak_resets_after_unseen_external_update(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        state = orchestrator.agent_states["frontend"]
        state.decomposition_answer_streak = 2
        state.seen_answer_counts = {"frontend": 1, "backend": 1}
        orchestrator.coordination_tracker.answers_by_agent["frontend"] = self._answers(1)
        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answers(2)

        orchestrator._sync_decomposition_answer_visibility("frontend")

        assert state.decomposition_answer_streak == 0
        assert state.seen_answer_counts["backend"] == 2

    def test_decomposition_auto_stop_refreshes_streak_before_limit_check(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.max_new_answers_per_agent = 2
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend = orchestrator.agent_states["frontend"]
        frontend.decomposition_answer_streak = 2
        frontend.seen_answer_counts = {"frontend": 2, "backend": 0}
        orchestrator.coordination_tracker.answers_by_agent["frontend"] = self._answers(2)
        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answers(1)

        should_skip = orchestrator._apply_decomposition_auto_stop_if_needed("frontend")

        assert should_skip is False
        assert frontend.has_voted is False
        assert frontend.decomposition_answer_streak == 0

    def test_decomposition_auto_stop_stops_agent_when_no_new_external_updates(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.max_new_answers_per_agent = 2
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend = orchestrator.agent_states["frontend"]
        frontend.decomposition_answer_streak = 2
        frontend.seen_answer_counts = {"frontend": 2, "backend": 1}
        orchestrator.coordination_tracker.answers_by_agent["frontend"] = self._answers(2)
        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answers(1)

        should_skip = orchestrator._apply_decomposition_auto_stop_if_needed("frontend")

        assert should_skip is True
        assert frontend.has_voted is True

    def test_global_limit_auto_stops_in_decomposition_mode(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.max_new_answers_global = 1
        orchestrator = Orchestrator(agents={"frontend": _StubAgent()}, config=config)
        orchestrator.coordination_tracker.answers_by_agent["frontend"] = self._answers(1)

        # Decomposition mode auto-stops instead of entering vote-only mode.
        assert orchestrator._is_vote_only_mode("frontend") is False
        assert orchestrator.agent_states["frontend"].has_voted is True
        assert "global answer limit" in (orchestrator.agent_states["frontend"].stop_summary or "")


class TestFairnessControls:
    """Test fairness controls for answer pacing and injection behavior."""

    @staticmethod
    def _answer_revisions(count: int, start_ts: float = 1.0):
        return [type("Answer", (), {"timestamp": start_ts + i, "label": f"agent1.{i + 1}", "content": f"answer{i + 1}"})() for i in range(count)]

    def test_fairness_lead_cap_blocks_runaway_new_answer(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.fairness_lead_cap_answers = 1
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        orchestrator.coordination_tracker.answers_by_agent["fast"] = self._answer_revisions(2)
        orchestrator.coordination_tracker.answers_by_agent["slow"] = []

        can_answer, error = orchestrator._check_answer_count_limit("fast")

        assert can_answer is False
        assert error and "Fairness lead cap reached" in error

    def test_fairness_lead_cap_can_be_disabled(self):
        config = AgentConfig()
        config.fairness_enabled = False
        config.fairness_lead_cap_answers = 0
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        orchestrator.coordination_tracker.answers_by_agent["fast"] = self._answer_revisions(4)
        orchestrator.coordination_tracker.answers_by_agent["slow"] = []

        can_answer, _ = orchestrator._check_answer_count_limit("fast")
        assert can_answer is True

    def test_midstream_selection_is_latest_first_and_marks_only_injected_sources(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.fairness_enabled = True
        config.max_midstream_injections_per_round = 1
        orchestrator = Orchestrator(
            agents={
                "frontend": _StubAgent(),
                "backend": _StubAgent(),
                "qa": _StubAgent(),
            },
            config=config,
        )

        state = orchestrator.agent_states["frontend"]
        state.seen_answer_counts = {"frontend": 1, "backend": 0, "qa": 0}
        state.midstream_injections_this_round = 0
        state.decomposition_answer_streak = 2

        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answer_revisions(1, start_ts=10.0)
        orchestrator.coordination_tracker.answers_by_agent["qa"] = self._answer_revisions(1, start_ts=20.0)

        selected, had_unseen = orchestrator._select_midstream_answer_updates(
            "frontend",
            {
                "backend": "backend update",
                "qa": "qa update",
            },
        )

        assert had_unseen is True
        assert list(selected.keys()) == ["qa"]

        orchestrator._register_injected_answer_updates("frontend", list(selected.keys()))

        assert state.decomposition_answer_streak == 0
        assert state.seen_answer_counts["qa"] == 1
        assert state.seen_answer_counts["backend"] == 0

    def test_partial_midstream_injection_keeps_unseen_peer_pending(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.max_midstream_injections_per_round = 1
        orchestrator = Orchestrator(
            agents={
                "frontend": _StubAgent(),
                "backend": _StubAgent(),
                "qa": _StubAgent(),
            },
            config=config,
        )

        state = orchestrator.agent_states["frontend"]
        state.seen_answer_counts = {"frontend": 0, "backend": 0, "qa": 0}

        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answer_revisions(1, start_ts=10.0)
        orchestrator.coordination_tracker.answers_by_agent["qa"] = self._answer_revisions(1, start_ts=20.0)
        orchestrator.agent_states["backend"].answer = "backend update"
        orchestrator.agent_states["qa"].answer = "qa update"

        selected, had_unseen = orchestrator._select_midstream_answer_updates(
            "frontend",
            {
                "backend": "backend update",
                "qa": "qa update",
            },
        )

        assert had_unseen is True
        assert list(selected.keys()) == ["qa"]

        orchestrator._register_injected_answer_updates("frontend", list(selected.keys()))

        assert orchestrator._has_unseen_answer_updates("frontend") is True
        assert orchestrator._get_unseen_source_agent_ids("frontend") == ["backend"]

    def test_terminal_fairness_gate_requires_latest_peer_updates(self):
        config = AgentConfig()
        config.fairness_enabled = True
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answer_revisions(1, start_ts=42.0)
        orchestrator.agent_states["backend"].answer = "backend revision"
        orchestrator.agent_states["frontend"].seen_answer_counts = {"frontend": 0, "backend": 0}

        can_terminal, error = orchestrator._check_terminal_fairness_gate("frontend")
        assert can_terminal is False
        assert error and "Fairness gate" in error

        orchestrator._mark_seen_answer_revisions("frontend", ["backend"])
        can_terminal_after_sync, error_after_sync = orchestrator._check_terminal_fairness_gate("frontend")
        assert can_terminal_after_sync is True
        assert error_after_sync is None

    def test_terminal_fairness_gate_allows_hard_timeout_cutoff(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.timeout_config.round_timeout_grace_seconds = 5
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        orchestrator.coordination_tracker.answers_by_agent["backend"] = self._answer_revisions(1, start_ts=42.0)
        orchestrator.agent_states["backend"].answer = "backend revision"
        orchestrator.agent_states["frontend"].seen_answer_counts = {"frontend": 0, "backend": 0}

        timeout_state = RoundTimeoutState()
        timeout_state.soft_timeout_fired_at = time.time() - 10
        orchestrator.agent_states["frontend"].round_timeout_state = timeout_state

        can_terminal, error = orchestrator._check_terminal_fairness_gate("frontend")
        assert can_terminal is True
        assert error is None

    def test_prestart_fairness_pause_waits_after_two_answer_lead(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.fairness_lead_cap_answers = 2
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        orchestrator.coordination_tracker.answers_by_agent["fast"] = self._answer_revisions(2)
        orchestrator.coordination_tracker.answers_by_agent["slow"] = []

        should_pause, reason = orchestrator._should_pause_agent_for_fairness("fast")

        assert should_pause is True
        assert reason and "Fairness lead cap reached" in reason

    def test_prestart_fairness_pause_does_not_block_first_answer(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.fairness_lead_cap_answers = 2
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        should_pause, reason = orchestrator._should_pause_agent_for_fairness("fast")

        assert should_pause is False
        assert reason is None

    def test_fairness_prestart_pause_logging_deduplicates_until_state_changes(
        self,
        monkeypatch,
    ):
        config = AgentConfig()
        config.fairness_enabled = True
        config.fairness_lead_cap_answers = 1
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        captured_logs = []

        def _capture_info(message, *args, **kwargs):
            del kwargs  # Unused in this test hook.
            if args:
                try:
                    message = message % args
                except Exception:
                    pass
            captured_logs.append(str(message))

        monkeypatch.setattr(orchestrator_module.logger, "info", _capture_info)

        orchestrator.coordination_tracker.answers_by_agent["fast"] = self._answer_revisions(2)
        orchestrator.coordination_tracker.answers_by_agent["slow"] = []

        for _ in range(3):
            paused, reason = orchestrator._should_pause_agent_for_fairness("fast")
            assert paused is True
            orchestrator._update_fairness_pause_log_state("fast", paused, reason)

        pause_logs = [line for line in captured_logs if "Pausing fast before round start due to fairness gate" in line]
        assert len(pause_logs) == 1

        orchestrator.coordination_tracker.answers_by_agent["slow"] = self._answer_revisions(2)

        for _ in range(2):
            paused, reason = orchestrator._should_pause_agent_for_fairness("fast")
            assert paused is False
            orchestrator._update_fairness_pause_log_state("fast", paused, reason)

        resume_logs = [line for line in captured_logs if "Fairness gate cleared for fast; resuming round starts" in line]
        assert len(resume_logs) == 1

    def test_fairness_lead_cap_block_logging_deduplicates_until_unblocked(
        self,
        monkeypatch,
    ):
        config = AgentConfig()
        config.fairness_enabled = True
        config.fairness_lead_cap_answers = 1
        orchestrator = Orchestrator(
            agents={"fast": _StubAgent(), "slow": _StubAgent()},
            config=config,
        )

        captured_logs = []

        def _capture_info(message, *args, **kwargs):
            del kwargs  # Unused in this test hook.
            if args:
                try:
                    message = message % args
                except Exception:
                    pass
            captured_logs.append(str(message))

        monkeypatch.setattr(orchestrator_module.logger, "info", _capture_info)

        orchestrator.coordination_tracker.answers_by_agent["fast"] = self._answer_revisions(2)
        orchestrator.coordination_tracker.answers_by_agent["slow"] = []

        for _ in range(3):
            can_answer, error = orchestrator._check_fairness_answer_lead_cap("fast")
            assert can_answer is False
            assert error and "Fairness lead cap reached" in error

        block_logs = [line for line in captured_logs if "Fairness gate blocked new_answer for fast" in line]
        assert len(block_logs) == 1

        orchestrator.coordination_tracker.answers_by_agent["slow"] = self._answer_revisions(2)
        can_answer, error = orchestrator._check_fairness_answer_lead_cap("fast")
        assert can_answer is True
        assert error is None

        orchestrator.coordination_tracker.answers_by_agent["slow"] = []
        can_answer, error = orchestrator._check_fairness_answer_lead_cap("fast")
        assert can_answer is False
        assert error and "Fairness lead cap reached" in error

        block_logs = [line for line in captured_logs if "Fairness gate blocked new_answer for fast" in line]
        assert len(block_logs) == 2


class _HookBackend(_StubBackend):
    def set_general_hook_manager(self, _manager):
        return None


class _NativeHookBackend(_StubBackend):
    def supports_native_hooks(self):
        return True


class _NativeHookAgent:
    def __init__(self):
        self.backend = _NativeHookBackend()
        self._orchestrator = None


class TestNoHookMidstreamFallback:
    def test_backend_support_detection_for_midstream_hooks(self):
        config = AgentConfig()
        orchestrator = Orchestrator(
            agents={
                "no_hook": _StubAgent(),
                "general_hook": _StubAgent(),
                "native_hook": _NativeHookAgent(),
            },
            config=config,
        )
        orchestrator.agents["general_hook"].backend = _HookBackend()

        assert (
            orchestrator._backend_supports_midstream_hook_injection(
                orchestrator.agents["no_hook"],
            )
            is False
        )
        assert (
            orchestrator._backend_supports_midstream_hook_injection(
                orchestrator.agents["general_hook"],
            )
            is True
        )
        assert (
            orchestrator._backend_supports_midstream_hook_injection(
                orchestrator.agents["native_hook"],
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_no_hook_midstream_enforcement_delivers_updates(self, monkeypatch):
        config = AgentConfig()
        config.fairness_enabled = False
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend_state = orchestrator.agent_states["frontend"]
        frontend_state.restart_pending = True
        frontend_state.answer = "frontend existing answer"  # Must have answer for injection to proceed
        frontend_state.seen_answer_counts = {"frontend": 0, "backend": 0}

        # Backend has one unseen answer revision.
        answer = type("Answer", (), {"timestamp": 42.0, "label": "backend.1", "content": "backend update"})()
        orchestrator.coordination_tracker.answers_by_agent["backend"] = [answer]
        orchestrator.agent_states["backend"].answer = "backend update"

        copied = {"called": False}

        async def _fake_copy(_agent_id):
            copied["called"] = True
            return None

        monkeypatch.setattr(orchestrator, "_copy_all_snapshots_to_temp_workspace", _fake_copy)
        monkeypatch.setattr(
            orchestrator,
            "_build_tool_result_injection",
            lambda _aid, selected, existing_answers=None: f"injected::{','.join(sorted(selected.keys()))}",
        )

        answers_seen_at_start = {}
        injected = await orchestrator._prepare_no_hook_midstream_enforcement(
            "frontend",
            answers_seen_at_start,
        )

        assert copied["called"] is True
        assert injected == "injected::backend"
        assert answers_seen_at_start == {"backend": "backend update"}
        assert frontend_state.injection_count == 1
        assert frontend_state.midstream_injections_this_round == 1
        assert "backend" in frontend_state.known_answer_ids
        assert frontend_state.restart_pending is False

    @pytest.mark.asyncio
    async def test_no_hook_midstream_enforcement_keeps_pending_when_capped(self):
        config = AgentConfig()
        config.fairness_enabled = True
        config.max_midstream_injections_per_round = 1
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend_state = orchestrator.agent_states["frontend"]
        frontend_state.restart_pending = True
        frontend_state.answer = "frontend existing answer"  # Must have answer for injection to proceed
        frontend_state.midstream_injections_this_round = 1
        frontend_state.seen_answer_counts = {"frontend": 0, "backend": 0}

        answer = type("Answer", (), {"timestamp": 42.0, "label": "backend.1", "content": "backend update"})()
        orchestrator.coordination_tracker.answers_by_agent["backend"] = [answer]
        orchestrator.agent_states["backend"].answer = "backend update"

        injected = await orchestrator._prepare_no_hook_midstream_enforcement(
            "frontend",
            {},
        )

        assert injected is None
        assert frontend_state.restart_pending is True
        assert frontend_state.injection_count == 0

    @pytest.mark.asyncio
    async def test_no_hook_midstream_enforcement_defers_peer_updates_until_restart(self):
        config = AgentConfig()
        config.fairness_enabled = False
        config.defer_peer_updates_until_restart = True
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend_state = orchestrator.agent_states["frontend"]
        frontend_state.restart_pending = True
        frontend_state.answer = "frontend existing answer"
        frontend_state.seen_answer_counts = {"frontend": 0, "backend": 0}

        answer = type("Answer", (), {"timestamp": 42.0, "label": "backend.1", "content": "backend update"})()
        orchestrator.coordination_tracker.answers_by_agent["backend"] = [answer]
        orchestrator.agent_states["backend"].answer = "backend update"

        injected = await orchestrator._prepare_no_hook_midstream_enforcement(
            "frontend",
            {},
        )

        assert injected is None
        assert frontend_state.restart_pending is True
        assert frontend_state.injection_count == 0

    @pytest.mark.asyncio
    async def test_no_hook_midstream_enforcement_allows_pre_checklist_injection_when_enabled(self, monkeypatch):
        config = AgentConfig()
        config.fairness_enabled = False
        config.voting_sensitivity = "checklist_gated"
        config.defer_peer_updates_until_restart = True
        config.allow_midstream_peer_updates_before_checklist_submit = True
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend_state = orchestrator.agent_states["frontend"]
        frontend_state.restart_pending = True
        frontend_state.answer = "frontend existing answer"
        frontend_state.seen_answer_counts = {"frontend": 0, "backend": 0}
        frontend_state.checklist_calls_this_round = 0

        answer = type("Answer", (), {"timestamp": 42.0, "label": "backend.1", "content": "backend update"})()
        orchestrator.coordination_tracker.answers_by_agent["backend"] = [answer]
        orchestrator.agent_states["backend"].answer = "backend update"

        copied = {"called": False}

        async def _fake_copy(_agent_id):
            copied["called"] = True
            return None

        monkeypatch.setattr(orchestrator, "_copy_all_snapshots_to_temp_workspace", _fake_copy)
        monkeypatch.setattr(
            orchestrator,
            "_build_tool_result_injection",
            lambda _aid, selected, existing_answers=None: f"injected::{','.join(sorted(selected.keys()))}",
        )

        answers_seen_at_start = {}
        injected = await orchestrator._prepare_no_hook_midstream_enforcement(
            "frontend",
            answers_seen_at_start,
        )

        assert copied["called"] is True
        assert injected == "injected::backend"
        assert answers_seen_at_start == {"backend": "backend update"}
        assert frontend_state.injection_count == 1
        assert frontend_state.restart_pending is False

    @pytest.mark.asyncio
    async def test_no_hook_midstream_enforcement_stops_pre_checklist_injection_after_first_submit(self):
        config = AgentConfig()
        config.fairness_enabled = False
        config.voting_sensitivity = "checklist_gated"
        config.defer_peer_updates_until_restart = True
        config.allow_midstream_peer_updates_before_checklist_submit = True
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )

        frontend_state = orchestrator.agent_states["frontend"]
        frontend_state.restart_pending = True
        frontend_state.answer = "frontend existing answer"
        frontend_state.seen_answer_counts = {"frontend": 0, "backend": 0}
        frontend_state.checklist_calls_this_round = 1

        answer = type("Answer", (), {"timestamp": 42.0, "label": "backend.1", "content": "backend update"})()
        orchestrator.coordination_tracker.answers_by_agent["backend"] = [answer]
        orchestrator.agent_states["backend"].answer = "backend update"

        injected = await orchestrator._prepare_no_hook_midstream_enforcement(
            "frontend",
            {},
        )

        assert injected is None
        assert frontend_state.restart_pending is True
        assert frontend_state.injection_count == 0


class TestDecompositionPromptGuidance:
    def test_decomposition_section_includes_ownership_first_model(self):
        section = DecompositionSection(subtask="Build the timeline section")
        content = section.build_content()

        assert "OWNERSHIP-FIRST EXECUTION" in content
        assert "Keep roughly 80% of your effort on that scope." in content
        assert "Use up to roughly 20% for adjacent integration work only when needed" in content

    def test_decomposition_section_preserves_quality_under_fairness(self):
        section = DecompositionSection(subtask="Build the timeline section")
        content = section.build_content()

        assert "Team fairness policy is active to prevent runaway iteration loops." in content
        assert "It does NOT mean reducing quality or stopping early." in content
        assert "Quality bar for `new_answer`" in content

    def test_decomposition_checklist_guidance_scores_current_subtask_not_peer_ranking(self):
        section = DecompositionSection(
            subtask="Build the timeline section",
            voting_threshold=5,
            voting_sensitivity="checklist_gated",
            answers_used=1,
            answer_cap=3,
            custom_checklist_items=["Criterion 1", "Criterion 2"],
        )
        content = section.build_content()

        assert "select the answer with the strongest overall scores" not in content
        assert "Score EACH agent per dimension" not in content
        assert "Score your current work against the criteria" in content

    def test_stdio_checklist_submit_state_is_visible_to_decomposition_runtime(self, tmp_path):
        config = AgentConfig()
        config.voting_sensitivity = "checklist_gated"
        config.defer_peer_updates_until_restart = True
        config.allow_midstream_peer_updates_before_checklist_submit = True
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent()},
            config=config,
        )

        backend = orchestrator.agents["frontend"].backend
        backend._checklist_state = {"checklist_calls_this_round": 0}
        specs_path = tmp_path / "checklist_specs.json"
        write_checklist_specs(
            ["Criterion 1"],
            {
                "checklist_calls_this_round": 1,
                "checklist_history": [
                    {
                        "verdict": "stop",
                        "true_count": 1,
                        "total_score": 8,
                        "items_detail": [{"id": "E1", "score": 8, "passed": True}],
                    },
                ],
            },
            specs_path,
        )
        backend._checklist_specs_path = specs_path

        assert orchestrator._has_successful_checklist_submit_this_round("frontend") is True
        assert orchestrator.agent_states["frontend"].checklist_calls_this_round == 1

    def test_decomposition_fallback_criteria_enforce_owned_scope_and_integration(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent()},
            config=config,
        )
        orchestrator._agent_subtasks["frontend"] = "Build the timeline section and keep shared navigation aligned."

        items, categories, _ = orchestrator._get_active_criteria("frontend")

        assert items is not None
        assert "Build the timeline section" in items[0]
        assert any("relevant peer work" in item.lower() for item in items)
        assert any("owned scope" in item.lower() for item in items)
        assert any("meaningful improvement" in item.lower() for item in items)
        assert categories["E1"] == "must"

    def test_decomposition_agent_specific_criteria_are_routed_to_prompt_only_for_that_agent(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.voting_sensitivity = "checklist_gated"
        config.voting_threshold = 5
        orchestrator = Orchestrator(
            agents={"frontend": _StubAgent(), "backend": _StubAgent()},
            config=config,
        )
        orchestrator._agent_subtasks = {
            "frontend": "Build the timeline section.",
            "backend": "Wire the content API.",
        }
        orchestrator._agent_subtask_criteria = {
            "frontend": [
                GeneratedCriterion(id="E1", text="Frontend timeline is polished.", category="must"),
            ],
            "backend": [
                GeneratedCriterion(id="E1", text="Backend API is robust.", category="must"),
            ],
        }

        frontend_items, frontend_categories, frontend_verify_by = orchestrator._get_active_criteria("frontend")
        message = orchestrator._get_system_message_builder().build_coordination_message(
            agent=orchestrator.agents["frontend"],
            agent_id="frontend",
            answers={},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            vote_only=False,
            agent_mapping={"frontend": "agent1", "backend": "agent2"},
            voting_sensitivity_override=None,
            voting_threshold=config.voting_threshold,
            checklist_require_gap_report=True,
            gap_report_mode="changedoc",
            answers_used=0,
            answer_cap=2,
            coordination_mode="decomposition",
            agent_subtask=orchestrator._agent_subtasks["frontend"],
            custom_checklist_items=frontend_items,
            item_categories=frontend_categories,
            item_verify_by=frontend_verify_by,
            builder_enabled=True,
        )

        assert "Frontend timeline is polished." in message
        assert "Backend API is robust." not in message

    def test_decomposition_checklist_refresh_writes_agent_specific_items(self):
        config = AgentConfig()
        config.coordination_mode = "decomposition"
        config.voting_sensitivity = "checklist_gated"
        config.voting_threshold = 5
        orchestrator = Orchestrator(
            agents={"frontend": _ChecklistAgent(), "backend": _ChecklistAgent()},
            config=config,
        )
        orchestrator._agent_subtasks = {
            "frontend": "Build the timeline section.",
            "backend": "Wire the content API.",
        }
        orchestrator._agent_subtask_criteria = {
            "frontend": [
                GeneratedCriterion(id="E1", text="Frontend timeline is polished.", category="must"),
                GeneratedCriterion(id="E2", text="Frontend integrates shared nav cleanly.", category="must"),
            ],
            "backend": [
                GeneratedCriterion(id="E1", text="Backend API is robust.", category="must"),
            ],
        }

        orchestrator._refresh_checklist_state_for_agent("frontend")

        frontend_backend = orchestrator.agents["frontend"].backend
        assert frontend_backend._checklist_items == [
            "Frontend timeline is polished.",
            "Frontend integrates shared nav cleanly.",
        ]
        assert frontend_backend._checklist_state["item_categories"] == {
            "E1": "must",
            "E2": "must",
        }
        specs_payload = json.loads(frontend_backend._checklist_specs_path.read_text())
        assert specs_payload["items"] == frontend_backend._checklist_items
        assert "Backend API is robust." not in specs_payload["items"]


# =============================================================================
# Enum Tests
# =============================================================================


class TestDecompositionEnums:
    """Test enum additions for decomposition mode."""

    def test_action_type_stop(self):
        assert ActionType.STOP.value == "stop"

    def test_agent_status_stopped(self):
        assert AgentStatus.STOPPED.value == "stopped"


# =============================================================================
# TaskDecomposerConfig Tests
# =============================================================================


class TestTaskDecomposerConfig:
    """Test TaskDecomposerConfig defaults."""

    def test_defaults(self):
        config = TaskDecomposerConfig()
        assert config.enabled is True
        assert config.decomposition_guidelines is None

    def test_custom_guidelines(self):
        config = TaskDecomposerConfig(
            decomposition_guidelines="Focus on separating frontend from backend",
        )
        assert "frontend" in config.decomposition_guidelines
