"""
Tests for Subagent Cancellation Recovery.

TDD tests for recovering completed work from cancelled/timed-out subagents.
These tests are written BEFORE implementation to drive the design.

Tests cover:
- New SubagentResult status values (completed_but_timeout, partial)
- Workspace status.json parsing for recovery
- Answer extraction from workspace
- Token usage extraction from status.json costs
- Completion percentage reporting
- Workspace path always available
"""

import json
import tempfile
from pathlib import Path

from massgen.subagent.models import SubagentResult


class TestSubagentResultNewStatuses:
    """Tests for new SubagentResult status values and factory methods."""

    def test_status_literal_includes_new_values(self):
        """Test that status Literal type includes new values."""
        # These should not raise - valid statuses
        result1 = SubagentResult(
            subagent_id="test",
            status="completed_but_timeout",
            success=True,
            answer="Recovered answer",
            workspace_path="/workspace",
        )
        assert result1.status == "completed_but_timeout"
        assert result1.success is True

        result2 = SubagentResult(
            subagent_id="test",
            status="partial",
            success=False,
            answer="Partial answer",
            workspace_path="/workspace",
        )
        assert result2.status == "partial"

    def test_create_timeout_with_recovery_full_completion(self):
        """Test factory method for timeout with fully recovered answer."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test_sub",
            workspace_path="/workspace/test_sub",
            timeout_seconds=300.0,
            recovered_answer="This is the recovered answer from the winner",
            completion_percentage=100,
            token_usage={
                "input_tokens": 204656,
                "output_tokens": 8419,
                "estimated_cost": 0.048142,
            },
        )
        assert result.status == "completed_but_timeout"
        assert result.success is True
        assert result.answer == "This is the recovered answer from the winner"
        assert result.workspace_path == "/workspace/test_sub"
        assert result.execution_time_seconds == 300.0
        assert result.completion_percentage == 100
        assert result.token_usage["input_tokens"] == 204656
        assert result.token_usage["estimated_cost"] == 0.048142
        assert "timeout" in result.error.lower()  # Still notes it was a timeout

    def test_create_timeout_with_recovery_partial_completion(self):
        """Test factory method for timeout with partial answer (no winner)."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test_sub",
            workspace_path="/workspace/test_sub",
            timeout_seconds=300.0,
            recovered_answer="Best available answer from first agent",
            completion_percentage=75,
            token_usage={"input_tokens": 150000, "output_tokens": 5000},
            is_partial=True,
        )
        assert result.status == "partial"
        assert result.success is False  # Partial is not fully successful
        assert result.answer == "Best available answer from first agent"
        assert result.completion_percentage == 75

    def test_create_timeout_with_recovery_no_answer(self):
        """Test factory method for timeout with no recoverable answer."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test_sub",
            workspace_path="/workspace/test_sub",
            timeout_seconds=300.0,
            recovered_answer=None,  # No answer recovered
            completion_percentage=10,
            token_usage={},
        )
        assert result.status == "timeout"  # Falls back to regular timeout
        assert result.success is False
        assert result.answer is None
        assert result.workspace_path == "/workspace/test_sub"  # Still has workspace

    def test_completion_percentage_in_to_dict(self):
        """Test that completion_percentage is included in serialization."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test_sub",
            workspace_path="/workspace",
            timeout_seconds=300.0,
            recovered_answer="Answer",
            completion_percentage=100,
            token_usage={},
        )
        data = result.to_dict()
        assert "completion_percentage" in data
        assert data["completion_percentage"] == 100

    def test_completion_percentage_omitted_when_none(self):
        """Test that completion_percentage is omitted when not set."""
        result = SubagentResult.create_timeout(
            subagent_id="test_sub",
            workspace_path="/workspace",
            timeout_seconds=300.0,
        )
        data = result.to_dict()
        # Should not have completion_percentage key when not set
        assert "completion_percentage" not in data or data.get("completion_percentage") is None

    def test_workspace_path_always_present_on_timeout(self):
        """Test that workspace_path is always set even with no answer."""
        result = SubagentResult.create_timeout(
            subagent_id="test_sub",
            workspace_path="/workspace/test_sub",
            timeout_seconds=300.0,
        )
        assert result.workspace_path == "/workspace/test_sub"
        data = result.to_dict()
        assert data["workspace"] == "/workspace/test_sub"


class TestWorkspaceStatusParsing:
    """Tests for parsing status.json from subagent workspace."""

    def test_extract_status_presentation_phase_with_winner(self):
        """Test extracting status when subagent completed (presentation phase)."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            status_data = {
                "coordination": {
                    "phase": "presentation",
                    "completion_percentage": 100,
                    "is_final_presentation": True,
                },
                "results": {
                    "winner": "agent_1",
                    "votes": {"agent_1": 3, "agent_2": 1},
                },
                "costs": {
                    "total_input_tokens": 204656,
                    "total_output_tokens": 8419,
                    "total_estimated_cost": 0.048142,
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            manager = SubagentManager.__new__(SubagentManager)
            status = manager._extract_status_from_workspace(workspace)

            assert status["phase"] == "presentation"
            assert status["completion_percentage"] == 100
            assert status["winner"] == "agent_1"
            assert status["has_completed_work"] is True

    def test_extract_status_enforcement_phase_with_votes(self):
        """Test extracting status when subagent in voting phase."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            status_data = {
                "coordination": {
                    "phase": "enforcement",
                    "completion_percentage": 75,
                },
                "results": {
                    "votes": {"agent_1": 1, "agent_2": 1},  # Tie, no winner
                },
                "costs": {
                    "total_input_tokens": 150000,
                    "total_output_tokens": 5000,
                    "total_estimated_cost": 0.035,
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            manager = SubagentManager.__new__(SubagentManager)
            status = manager._extract_status_from_workspace(workspace)

            assert status["phase"] == "enforcement"
            assert status["completion_percentage"] == 75
            assert status["winner"] is None
            assert status["has_completed_work"] is True  # Has answers even if no winner

    def test_extract_status_initial_phase_no_work(self):
        """Test extracting status when subagent barely started."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            status_data = {
                "coordination": {
                    "phase": "initial_answer",
                    "completion_percentage": 10,
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            manager = SubagentManager.__new__(SubagentManager)
            status = manager._extract_status_from_workspace(workspace)

            assert status["phase"] == "initial_answer"
            assert status["completion_percentage"] == 10
            assert status["has_completed_work"] is False

    def test_extract_status_no_status_file(self):
        """Test extracting status when no status.json exists."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # No status.json created

            manager = SubagentManager.__new__(SubagentManager)
            status = manager._extract_status_from_workspace(workspace)

            assert status["phase"] is None
            assert status["completion_percentage"] is None
            assert status["has_completed_work"] is False


class TestAnswerExtraction:
    """Tests for extracting answers from subagent workspace."""

    def test_extract_answer_from_answer_txt(self):
        """Test extracting answer from answer.txt file."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            answer_content = "This is the final answer from the subagent orchestrator."
            (workspace / "answer.txt").write_text(answer_content)

            manager = SubagentManager.__new__(SubagentManager)
            answer = manager._extract_answer_from_workspace(workspace, winner_agent_id=None)

            assert answer == answer_content

    def test_extract_answer_from_winner_workspace(self):
        """Test extracting answer from winner agent's workspace."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Create winner's workspace with answer
            winner_workspace = workspace / "workspaces" / "agent_1"
            winner_workspace.mkdir(parents=True)
            winner_answer = "The winning agent's detailed answer."
            (winner_workspace / "answer.md").write_text(winner_answer)

            manager = SubagentManager.__new__(SubagentManager)
            answer = manager._extract_answer_from_workspace(workspace, winner_agent_id="agent_1")

            assert answer == winner_answer

    def test_extract_answer_selects_by_votes(self):
        """Test answer selection uses vote count when no explicit winner."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            # Status with votes but no winner field
            status_data = {
                "coordination.phase": "enforcement",
                "results.votes": {"agent_1": 2, "agent_2": 1},
                "historical_workspaces": {
                    "agent_1": str(workspace / "workspaces" / "agent_1"),
                    "agent_2": str(workspace / "workspaces" / "agent_2"),
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            # Create agent workspaces with answers
            for agent_id in ["agent_1", "agent_2"]:
                agent_ws = workspace / "workspaces" / agent_id
                agent_ws.mkdir(parents=True)
                (agent_ws / "answer.md").write_text(f"Answer from {agent_id}")

            manager = SubagentManager.__new__(SubagentManager)
            # Should select agent_1 (highest votes)
            answer = manager._extract_answer_from_workspace(
                workspace,
                winner_agent_id=None,
                votes={"agent_1": 2, "agent_2": 1},
            )

            assert "agent_1" in answer

    def test_extract_answer_falls_back_to_most_recent_by_timestamp(self):
        """Test answer selection falls back to most recent answer by timestamp."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Create agent workspaces with answers
            for agent_id in ["agent_1", "agent_2"]:
                agent_ws = workspace / "workspaces" / agent_id
                agent_ws.mkdir(parents=True)
                (agent_ws / "answer.md").write_text(f"Answer from {agent_id}")

            # historical_workspaces_raw with timestamps — agent_2 is more recent
            raw = [
                {"agentId": "agent_1", "answerLabel": "agent_1", "timestamp": "20260308_100000_000000"},
                {"agentId": "agent_2", "answerLabel": "agent_2", "timestamp": "20260308_110000_000000"},
            ]

            manager = SubagentManager.__new__(SubagentManager)
            # Should select agent_2 (latest timestamp)
            answer = manager._extract_answer_from_workspace(
                workspace,
                winner_agent_id=None,
                votes={},
                historical_workspaces={
                    "agent_1": str(workspace / "workspaces" / "agent_1"),
                    "agent_2": str(workspace / "workspaces" / "agent_2"),
                },
                historical_workspaces_raw=raw,
            )

            assert "agent_2" in answer

    def test_extract_answer_fallback_picks_latest_not_first(self):
        """When agent_1 is registered first but agent_2 has a later timestamp, pick agent_2."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)

            # Create agent workspaces — agent_1 first in dict order
            for agent_id in ["agent_1", "agent_2"]:
                agent_ws = workspace / "workspaces" / agent_id
                agent_ws.mkdir(parents=True)
                (agent_ws / "answer.md").write_text(f"Answer from {agent_id}")

            # agent_1 answered earlier, agent_2 answered later
            raw = [
                {"agentId": "agent_1", "answerLabel": "agent_1", "timestamp": "20260308_090000_000000"},
                {"agentId": "agent_2", "answerLabel": "agent_2", "timestamp": "20260308_100000_000000"},
            ]

            manager = SubagentManager.__new__(SubagentManager)
            answer = manager._extract_answer_from_workspace(
                workspace,
                winner_agent_id=None,
                votes={},
                historical_workspaces={
                    "agent_1": str(workspace / "workspaces" / "agent_1"),
                    "agent_2": str(workspace / "workspaces" / "agent_2"),
                },
                historical_workspaces_raw=raw,
            )

            assert "agent_2" in answer  # Latest timestamp, NOT first registered

    def test_extract_answer_returns_none_when_no_answers(self):
        """Test answer extraction returns None when no answers available."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Empty workspace, no answer.txt, no agent workspaces

            manager = SubagentManager.__new__(SubagentManager)
            answer = manager._extract_answer_from_workspace(workspace, winner_agent_id=None)

            assert answer is None


class TestTokenUsageExtraction:
    """Tests for extracting token usage from status.json."""

    def test_extract_costs_from_status(self):
        """Test extracting token costs from status.json."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            status_data = {
                "costs": {
                    "total_input_tokens": 204656,
                    "total_output_tokens": 8419,
                    "total_estimated_cost": 0.048142,
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            manager = SubagentManager.__new__(SubagentManager)
            costs = manager._extract_costs_from_status(workspace)

            assert costs["input_tokens"] == 204656
            assert costs["output_tokens"] == 8419
            assert costs["estimated_cost"] == 0.048142

    def test_extract_costs_empty_when_no_status(self):
        """Test that costs are empty dict when no status.json."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # No status.json

            manager = SubagentManager.__new__(SubagentManager)
            costs = manager._extract_costs_from_status(workspace)

            assert costs == {}

    def test_extract_costs_empty_when_no_costs_section(self):
        """Test that costs are empty when status.json has no costs."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            status_data = {
                "coordination.phase": "presentation",
                # No costs fields
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            manager = SubagentManager.__new__(SubagentManager)
            costs = manager._extract_costs_from_status(workspace)

            assert costs == {}


class TestTimeoutRecoveryIntegration:
    """Integration tests for the full timeout recovery flow."""

    def test_timeout_recovery_with_completed_subagent(self):
        """Test full recovery flow when subagent completed work before timeout."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            # Simulate a subagent that completed but parent timed out
            status_data = {
                "coordination": {
                    "phase": "presentation",
                    "completion_percentage": 100,
                },
                "results": {
                    "winner": "agent_1",
                    "votes": {"agent_1": 3},
                },
                "costs": {
                    "total_input_tokens": 204656,
                    "total_output_tokens": 8419,
                    "total_estimated_cost": 0.048142,
                },
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            # Create answer.txt (what orchestrator writes on completion)
            (workspace / "answer.txt").write_text("The complete research findings...")

            manager = SubagentManager.__new__(SubagentManager)
            result = manager._create_timeout_result_with_recovery(
                subagent_id="research_agent",
                workspace=workspace,
                timeout_seconds=300.0,
            )

            assert result.status == "completed_but_timeout"
            assert result.success is True
            assert result.answer == "The complete research findings..."
            assert result.completion_percentage == 100
            assert result.token_usage["input_tokens"] == 204656
            assert result.workspace_path == str(workspace)

    def test_timeout_recovery_with_partial_work(self):
        """Test recovery flow when subagent had partial work."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            logs_dir = workspace / "full_logs"
            logs_dir.mkdir(parents=True)

            # Simulate partial completion (in enforcement phase)
            status_data = {
                "coordination": {
                    "phase": "enforcement",
                    "completion_percentage": 60,
                },
                "results": {
                    "votes": {"agent_1": 1, "agent_2": 1},
                },
                "costs": {
                    "total_input_tokens": 100000,
                    "total_output_tokens": 3000,
                    "total_estimated_cost": 0.025,
                },
                "historical_workspaces": [
                    {"agentId": "agent_1", "workspacePath": str(workspace / "workspaces" / "agent_1")},
                ],
            }
            (logs_dir / "status.json").write_text(json.dumps(status_data))

            # Create agent workspace with answer
            agent_ws = workspace / "workspaces" / "agent_1"
            agent_ws.mkdir(parents=True)
            (agent_ws / "answer.md").write_text("Partial research findings from agent 1")

            manager = SubagentManager.__new__(SubagentManager)
            result = manager._create_timeout_result_with_recovery(
                subagent_id="research_agent",
                workspace=workspace,
                timeout_seconds=300.0,
            )

            assert result.status == "partial"
            assert result.success is False
            assert "agent 1" in result.answer
            assert result.completion_percentage == 60
            assert result.token_usage["input_tokens"] == 100000

    def test_timeout_recovery_with_no_work(self):
        """Test recovery flow when subagent had no recoverable work."""
        from massgen.subagent.manager import SubagentManager

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # Empty workspace - subagent didn't get far

            manager = SubagentManager.__new__(SubagentManager)
            result = manager._create_timeout_result_with_recovery(
                subagent_id="research_agent",
                workspace=workspace,
                timeout_seconds=300.0,
            )

            assert result.status == "timeout"
            assert result.success is False
            assert result.answer is None
            assert result.workspace_path == str(workspace)  # Workspace still available
            assert result.token_usage == {}
