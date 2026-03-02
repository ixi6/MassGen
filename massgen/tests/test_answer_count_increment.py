"""
Tests for answer_count increment correctness.

Bug: answer_count was only incremented inside _archive_agent_memories(),
which early-returns when no memory/ directory exists in the agent's
workspace.  This caused submit_checklist to be blocked with
"not available before your first answer" in round > 0 for agents
that never create a memory/ directory.

The fix moves answer_count increment (and checklist_calls_this_round
reset) into _save_agent_snapshot so it always fires when an answer
snapshot is saved, regardless of whether memory archiving occurs.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.orchestrator import AgentState, Orchestrator


def _build_orchestrator_with_agent(tmp_path: Path, agent_id: str = "agent_a"):
    """Build a minimal Orchestrator with one agent for answer_count tests."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.session_id = "test-session"
    orch.current_task = "test task"
    orch.agent_states = {agent_id: AgentState()}

    # Set up a mock agent with filesystem_manager
    fm = MagicMock()
    fm.get_current_workspace.return_value = str(tmp_path / "workspace" / agent_id)
    fm.save_snapshot = AsyncMock()
    fm.clear_workspace = MagicMock()
    fm.restore_from_snapshot_storage = MagicMock()

    backend = MagicMock()
    backend.filesystem_manager = fm

    agent = MagicMock()
    agent.backend = backend

    orch.agents = {agent_id: agent}

    # Create the workspace directory (but no memory/ subdirectory)
    ws = tmp_path / "workspace" / agent_id
    ws.mkdir(parents=True, exist_ok=True)

    return orch


class TestAnswerCountIncrementWithoutMemoryDir:
    """answer_count must increment even when workspace has no memory/ dir."""

    def test_archive_memories_without_memory_dir_does_not_increment(self, tmp_path):
        """Verify the bug: _archive_agent_memories early-returns without memory/ dir."""
        orch = _build_orchestrator_with_agent(tmp_path)
        ws = tmp_path / "workspace" / "agent_a"
        # No memory/ dir exists

        assert orch.agent_states["agent_a"].answer_count == 0
        orch._archive_agent_memories("agent_a", ws)
        # _archive_agent_memories should NOT increment answer_count
        # (after the fix, it no longer does — the caller does)
        assert orch.agent_states["agent_a"].answer_count == 0

    @pytest.mark.asyncio
    async def test_save_agent_snapshot_increments_answer_count_without_memory_dir(
        self,
        tmp_path,
    ):
        """answer_count must increment when saving an answer snapshot,
        even if the agent has no memory/ directory."""
        orch = _build_orchestrator_with_agent(tmp_path)

        assert orch.agent_states["agent_a"].answer_count == 0

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            await orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content="My first answer",
            )

        assert orch.agent_states["agent_a"].answer_count == 1

    @pytest.mark.asyncio
    async def test_save_agent_snapshot_increments_answer_count_with_memory_dir(
        self,
        tmp_path,
    ):
        """answer_count must also increment when memory/ dir exists."""
        orch = _build_orchestrator_with_agent(tmp_path)
        ws = tmp_path / "workspace" / "agent_a"
        (ws / "memory").mkdir()
        (ws / "memory" / "notes.md").write_text("some memory")

        assert orch.agent_states["agent_a"].answer_count == 0

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            await orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content="My first answer",
            )

        assert orch.agent_states["agent_a"].answer_count == 1

    @pytest.mark.asyncio
    async def test_save_agent_snapshot_resets_checklist_calls_this_round(
        self,
        tmp_path,
    ):
        """checklist_calls_this_round must reset on answer snapshot."""
        orch = _build_orchestrator_with_agent(tmp_path)
        orch.agent_states["agent_a"].checklist_calls_this_round = 3

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            await orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content="My answer",
            )

        assert orch.agent_states["agent_a"].checklist_calls_this_round == 0

    @pytest.mark.asyncio
    async def test_vote_only_snapshot_does_not_increment_answer_count(self, tmp_path):
        """Vote-only snapshots should NOT increment answer_count."""
        orch = _build_orchestrator_with_agent(tmp_path)
        orch.coordination_tracker = MagicMock()
        orch.coordination_tracker.get_anonymous_agent_mapping.return_value = {}
        orch.coordination_tracker.get_agent_context_labels.return_value = []
        orch.coordination_tracker.current_iteration = 1
        orch.coordination_tracker.max_round = 1

        assert orch.agent_states["agent_a"].answer_count == 0

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            await orch._save_agent_snapshot(
                agent_id="agent_a",
                vote_data={"agent_id": "agent_b", "reason": "better"},
            )

        # Vote-only should not change answer_count
        assert orch.agent_states["agent_a"].answer_count == 0

    @pytest.mark.asyncio
    async def test_interrupted_save_without_answer_does_not_increment(self, tmp_path):
        """Interrupted saves (no answer_content, not final) should not
        increment answer_count — only real answer submissions should."""
        orch = _build_orchestrator_with_agent(tmp_path)

        assert orch.agent_states["agent_a"].answer_count == 0

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            await orch._save_agent_snapshot(
                agent_id="agent_a",
                answer_content=None,
            )

        assert orch.agent_states["agent_a"].answer_count == 0

    @pytest.mark.asyncio
    async def test_multiple_answers_increment_correctly(self, tmp_path):
        """Multiple answer submissions should increment answer_count each time."""
        orch = _build_orchestrator_with_agent(tmp_path)

        with patch("massgen.orchestrator.get_log_session_dir", return_value=None):
            for i in range(3):
                await orch._save_agent_snapshot(
                    agent_id="agent_a",
                    answer_content=f"Answer {i + 1}",
                )

        assert orch.agent_states["agent_a"].answer_count == 3
