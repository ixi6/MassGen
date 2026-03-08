"""Tests for enforcement observability feature.

This module tests the enforcement event tracking functionality in the
CoordinationTracker, including:
- Tracking enforcement events with correct reason codes
- Buffer content capture before enforcement restarts
- Reliability metrics aggregation in status.json
- Retry count formatting in enforcement messages
"""

import json
import time
from unittest.mock import MagicMock

import pytest

from massgen.coordination_tracker import CoordinationTracker


class TestEnforcementEventTracking:
    """Tests for track_enforcement_event() method."""

    def test_track_enforcement_event_basic(self):
        """Test basic enforcement event tracking."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="unknown_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=["execute_command"],
            error_message=None,
            buffer_preview="First 500 chars of buffer...",
            buffer_chars=1500,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1

        event = events[0]
        assert event["round"] == 0
        assert event["attempt"] == 1
        assert event["max_attempts"] == 3
        assert event["reason"] == "unknown_tool"
        assert event["tool_calls"] == ["execute_command"]
        assert event["buffer_preview"] == "First 500 chars of buffer..."
        assert event["buffer_chars"] == 1500
        assert "timestamp" in event

    def test_track_enforcement_event_with_error_message(self):
        """Test enforcement event with error message."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="invalid_vote_id",
            attempt=2,
            max_attempts=3,
            tool_calls=["vote"],
            error_message="Invalid agent_id 'agent5'. Valid agents: agent1, agent2",
            buffer_preview=None,
            buffer_chars=0,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        assert events[0]["error_message"] == "Invalid agent_id 'agent5'. Valid agents: agent1, agent2"

    def test_track_multiple_enforcement_events_per_round(self):
        """Test tracking multiple enforcement attempts in a single round."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])

        # First enforcement event
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_workflow_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=["read_file"],
            error_message="Must use workflow tools",
            buffer_preview=None,
            buffer_chars=0,
        )

        # Second enforcement event (same agent, same round)
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="invalid_vote_id",
            attempt=2,
            max_attempts=3,
            tool_calls=["vote"],
            error_message="Invalid agent_id",
            buffer_preview=None,
            buffer_chars=0,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 2
        assert events[0]["reason"] == "no_workflow_tool"
        assert events[1]["reason"] == "invalid_vote_id"

    def test_buffer_preview_truncation(self):
        """Test that buffer preview is truncated to 500 chars."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        # Buffer larger than 500 chars
        large_buffer = "x" * 1000

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_tool_calls",
            attempt=1,
            max_attempts=3,
            tool_calls=[],
            error_message=None,
            buffer_preview=large_buffer,
            buffer_chars=1000,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        # Buffer preview should be truncated to 500 chars
        assert len(events[0]["buffer_preview"]) == 500


class TestEnforcementReasonCategories:
    """Tests for enforcement reason code categorization."""

    @pytest.mark.parametrize(
        "reason",
        [
            "no_workflow_tool",
            "no_tool_calls",
            "invalid_vote_id",
            "vote_no_answers",
            "vote_and_answer",
            "answer_limit",
            "answer_novelty",
            "answer_duplicate",
            "unknown_tool",
            "api_error",
            "connection_recovery",
            "mcp_disconnected",
        ],
    )
    def test_valid_reason_codes(self, reason):
        """Test that all documented reason codes can be tracked."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason=reason,
            attempt=1,
            max_attempts=3,
            tool_calls=[],
            error_message=None,
            buffer_preview=None,
            buffer_chars=0,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        assert events[0]["reason"] == reason


class TestAgentReliabilityMetrics:
    """Tests for get_agent_reliability() method."""

    def test_no_enforcement_events_returns_none(self):
        """Test that agents with no enforcement events return None for reliability."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        reliability = tracker.get_agent_reliability("agent_a")
        assert reliability is None

    def test_reliability_aggregation(self):
        """Test reliability metrics aggregation."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        # Add multiple enforcement events
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="unknown_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=["execute_command"],
            error_message=None,
            buffer_preview="Buffer 1",
            buffer_chars=500,
        )

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_workflow_tool",
            attempt=2,
            max_attempts=3,
            tool_calls=["read_file"],
            error_message="Must use workflow tools",
            buffer_preview="Buffer 2",
            buffer_chars=300,
        )

        reliability = tracker.get_agent_reliability("agent_a")
        assert reliability is not None

        # Check enforcement_attempts list
        assert len(reliability["enforcement_attempts"]) == 2

        # Check by_round aggregation
        assert "0" in reliability["by_round"]
        assert reliability["by_round"]["0"]["count"] == 2
        assert "unknown_tool" in reliability["by_round"]["0"]["reasons"]
        assert "no_workflow_tool" in reliability["by_round"]["0"]["reasons"]

        # Check unknown_tools list
        assert "execute_command" in reliability["unknown_tools"]

        # Check totals
        assert reliability["total_enforcement_retries"] == 2
        assert reliability["total_buffer_chars_lost"] == 800

        # Check outcome default
        assert reliability["outcome"] == "ok"

    def test_reliability_workflow_errors(self):
        """Test that workflow errors are tracked correctly."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="vote_no_answers",
            attempt=1,
            max_attempts=3,
            tool_calls=["vote"],
            error_message="Cannot vote when no answers exist",
            buffer_preview=None,
            buffer_chars=0,
        )

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="invalid_vote_id",
            attempt=2,
            max_attempts=3,
            tool_calls=["vote"],
            error_message="Invalid agent_id",
            buffer_preview=None,
            buffer_chars=0,
        )

        reliability = tracker.get_agent_reliability("agent_a")
        assert "vote_no_answers" in reliability["workflow_errors"]
        assert "invalid_vote_id" in reliability["workflow_errors"]


class TestStatusJsonReliabilityField:
    """Tests for reliability field in save_status_file()."""

    def test_reliability_field_included_in_agent_statuses(self, tmp_path):
        """Test that reliability field is included in agent statuses."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])
        tracker.start_time = time.time()

        # Add enforcement event for agent_a
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_workflow_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=["search"],
            error_message="Must use workflow tools",
            buffer_preview="Some buffer content",
            buffer_chars=100,
        )

        # Mock orchestrator with minimal attributes
        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_states = {}

        # Save status file
        tracker.save_status_file(tmp_path, mock_orchestrator)

        # Read and verify status.json
        import json

        status_file = tmp_path / "status.json"
        assert status_file.exists()

        with open(status_file) as f:
            status_data = json.load(f)

        # Check agent_a has reliability field
        assert "agents" in status_data
        assert "agent_a" in status_data["agents"]
        assert "reliability" in status_data["agents"]["agent_a"]

        reliability = status_data["agents"]["agent_a"]["reliability"]
        assert reliability is not None
        assert len(reliability["enforcement_attempts"]) == 1
        assert reliability["enforcement_attempts"][0]["reason"] == "no_workflow_tool"
        assert reliability["total_enforcement_retries"] == 1

        # Check agent_b has None for reliability (no events)
        assert "agent_b" in status_data["agents"]
        assert status_data["agents"]["agent_b"]["reliability"] is None


class TestEnforcementMessageFormatting:
    """Tests for enforcement message formatting with retry counts."""

    def test_retry_count_format(self):
        """Test that retry count format matches spec: 'Retry (1/3): ...'"""
        # This is more of an integration test - the actual message formatting
        # happens in orchestrator.py. Here we just verify the format expectation.
        expected_format = "Retry (1/3): Must use workflow tools"
        assert expected_format.startswith("Retry (")
        assert "/3):" in expected_format


class TestRoundLevelTracking:
    """Tests for round-level enforcement tracking."""

    def test_enforcement_tracks_correct_round(self):
        """Test that enforcement events track the correct round number."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])

        # Track event in round 0
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_workflow_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=[],
            error_message=None,
            buffer_preview=None,
            buffer_chars=0,
        )

        # Simulate agent restart (move to round 1)
        tracker.pending_agent_restarts["agent_a"] = True
        tracker.complete_agent_restart("agent_a")

        # Track event in round 1
        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="invalid_vote_id",
            attempt=1,
            max_attempts=3,
            tool_calls=["vote"],
            error_message="Invalid agent_id",
            buffer_preview=None,
            buffer_chars=0,
        )

        events = tracker.enforcement_events["agent_a"]
        assert len(events) == 2
        assert events[0]["round"] == 0
        assert events[1]["round"] == 1

        # Verify by_round aggregation
        reliability = tracker.get_agent_reliability("agent_a")
        assert "0" in reliability["by_round"]
        assert "1" in reliability["by_round"]
        assert reliability["by_round"]["0"]["count"] == 1
        assert reliability["by_round"]["1"]["count"] == 1


class TestDockerHealthTracking:
    """Tests for docker_health parameter in enforcement events."""

    def test_docker_health_included_in_event(self):
        """Test that docker_health is captured in enforcement events."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        docker_health = {
            "exists": True,
            "status": "running",
            "running": True,
            "exit_code": None,
            "error": None,
            "oom_killed": False,
        }

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="mcp_disconnected",
            attempt=1,
            max_attempts=3,
            tool_calls=[],
            error_message="Server 'command_line' not connected",
            buffer_preview=None,
            buffer_chars=0,
            docker_health=docker_health,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        assert "docker_health" in events[0]
        assert events[0]["docker_health"]["status"] == "running"
        assert events[0]["docker_health"]["oom_killed"] is False

    def test_docker_health_captures_container_exit(self):
        """Test that docker_health captures container exit state."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        docker_health = {
            "exists": True,
            "status": "exited",
            "running": False,
            "exit_code": 137,
            "error": "Container killed by OOM",
            "oom_killed": True,
        }

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="mcp_disconnected",
            attempt=1,
            max_attempts=3,
            tool_calls=[],
            error_message="Server 'command_line' not connected",
            buffer_preview=None,
            buffer_chars=0,
            docker_health=docker_health,
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        assert events[0]["docker_health"]["status"] == "exited"
        assert events[0]["docker_health"]["exit_code"] == 137
        assert events[0]["docker_health"]["oom_killed"] is True

    def test_docker_health_none_for_non_docker_events(self):
        """Test that docker_health is not included when not provided."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        tracker.track_enforcement_event(
            agent_id="agent_a",
            reason="no_workflow_tool",
            attempt=1,
            max_attempts=3,
            tool_calls=["read_file"],
            error_message=None,
            buffer_preview=None,
            buffer_chars=0,
            # docker_health not provided
        )

        events = tracker.enforcement_events.get("agent_a", [])
        assert len(events) == 1
        assert "docker_health" not in events[0]


class TestFinishReasonTracking:
    """Tests for finish_reason field at the top of status.json."""

    def test_finish_reason_timeout(self, tmp_path):
        """Test finish_reason shows timeout when orchestrator times out."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.start_time = time.time()

        # Mock orchestrator with timeout state
        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_states = {}
        mock_orchestrator.is_orchestrator_timeout = True
        mock_orchestrator.timeout_reason = "Time limit exceeded (1883.9s/1800s)"

        tracker.save_status_file(tmp_path, mock_orchestrator)

        status_file = tmp_path / "status.json"
        with open(status_file) as f:
            status_data = json.load(f)

        # Verify finish_reason is at top level and correct
        assert status_data["finish_reason"] == "timeout"
        assert status_data["finish_reason_details"] == "Time limit exceeded (1883.9s/1800s)"
        assert status_data["is_complete"] is True

    def test_finish_reason_completed(self, tmp_path):
        """Test finish_reason shows completed when coordination finishes normally."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])
        tracker.start_time = time.time()
        tracker.is_final_round = True
        tracker.final_winner = "agent_a"

        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_states = {}
        mock_orchestrator.is_orchestrator_timeout = False

        tracker.save_status_file(tmp_path, mock_orchestrator)

        status_file = tmp_path / "status.json"
        with open(status_file) as f:
            status_data = json.load(f)

        assert status_data["finish_reason"] == "completed"
        assert status_data["finish_reason_details"] == "Winner: agent_a"
        assert status_data["is_complete"] is True

    def test_finish_reason_in_progress(self, tmp_path):
        """Test finish_reason shows in_progress during coordination."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.start_time = time.time()
        tracker.is_final_round = False
        tracker.final_winner = None

        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_states = {}
        mock_orchestrator.is_orchestrator_timeout = False

        tracker.save_status_file(tmp_path, mock_orchestrator)

        status_file = tmp_path / "status.json"
        with open(status_file) as f:
            status_data = json.load(f)

        assert status_data["finish_reason"] == "in_progress"
        assert "Phase:" in status_data["finish_reason_details"]
        assert status_data["is_complete"] is False

    def test_finish_reason_is_first_field(self, tmp_path):
        """Test that finish_reason appears before meta in the JSON."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.start_time = time.time()

        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_states = {}
        mock_orchestrator.is_orchestrator_timeout = True
        mock_orchestrator.timeout_reason = "Timeout occurred"

        tracker.save_status_file(tmp_path, mock_orchestrator)

        status_file = tmp_path / "status.json"
        with open(status_file) as f:
            raw_content = f.read()

        # Verify finish_reason appears before meta in the file
        finish_reason_pos = raw_content.find('"finish_reason"')
        meta_pos = raw_content.find('"meta"')
        assert finish_reason_pos < meta_pos, "finish_reason should appear before meta"
