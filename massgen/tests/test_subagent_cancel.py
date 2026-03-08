"""Tests for SubagentManager.cancel_subagent() internal method."""

from __future__ import annotations

import asyncio
import json
import signal as sig
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.subagent.models import SubagentConfig, SubagentState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path):
    """Create a SubagentManager with minimal dependencies."""
    from massgen.subagent.manager import SubagentManager

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = SubagentManager(
        parent_workspace=str(workspace),
        parent_agent_id="parent-1",
        orchestrator_id="orch-1",
        parent_agent_configs=[{"id": "agent-1", "backend": "mock"}],
    )
    return manager


def _make_state(
    subagent_id: str,
    status: str = "running",
    task: str = "test task",
) -> SubagentState:
    """Create a SubagentState for testing."""
    config = SubagentConfig(
        id=subagent_id,
        task=task,
        parent_agent_id="parent-1",
    )
    return SubagentState(
        config=config,
        status=status,
        workspace_path="/tmp/test",
        started_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# cancel_subagent tests
# ---------------------------------------------------------------------------


class TestCancelSubagent:
    @pytest.mark.asyncio
    async def test_cancel_unknown_id_returns_error(self, tmp_path):
        manager = _make_manager(tmp_path)

        result = await manager.cancel_subagent("nonexistent-id")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_terminal_state_returns_error(self, tmp_path):
        """Cannot cancel a subagent that's already completed/failed."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="completed")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is False
        assert "already" in result["error"].lower() or "terminal" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_cancels_asyncio_task(self, tmp_path):
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = True
        manager._background_tasks["sub-1"] = mock_task

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_sends_sigint_to_process(self, tmp_path):
        """Cancel sends SIGINT first (not SIGTERM) for graceful shutdown."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = None  # Still running
        mock_process.send_signal = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_process.send_signal.assert_called_once_with(sig.SIGINT)
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_kills_on_timeout(self, tmp_path):
        """If SIGINT and SIGTERM don't work within timeout, SIGKILL should be used."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.send_signal = MagicMock()
        mock_process.terminate = MagicMock()
        # SIGINT wait times out, SIGTERM wait times out, kill wait succeeds
        mock_process.wait = AsyncMock(
            side_effect=[asyncio.TimeoutError(), asyncio.TimeoutError(), None],
        )
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        mock_process.kill.assert_called_once()
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_sets_status_to_cancelled(self, tmp_path):
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_already_finished_process(self, tmp_path):
        """Process already exited but state still says running."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = 0  # Already exited
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_pending_state(self, tmp_path):
        """Can cancel a pending subagent."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="pending")
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_freezes_elapsed_seconds(self, tmp_path):
        """Cancelled subagents should report a stable elapsed time in display data."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.started_at = datetime.now() - timedelta(seconds=5)
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.finished_at is not None

        first_elapsed = manager.get_subagent_display_data("sub-1").elapsed_seconds
        await asyncio.sleep(0.01)
        second_elapsed = manager.get_subagent_display_data("sub-1").elapsed_seconds

        assert second_elapsed == first_elapsed

    @pytest.mark.asyncio
    async def test_cancel_sets_result_error_for_display_reason(self, tmp_path):
        """Cancelled subagents should carry a displayable terminal reason."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.started_at = datetime.now() - timedelta(seconds=3)
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True
        assert state.result is not None
        assert state.result.error == "Subagent cancelled"

    @pytest.mark.asyncio
    async def test_list_subagents_reports_cancelled_after_cancel(self, tmp_path):
        """list_subagents should preserve cancelled status instead of downgrading to error."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        manager._subagents["sub-1"] = state

        cancelled = await manager.cancel_subagent("sub-1")
        assert cancelled["success"] is True

        listed = manager.list_subagents()
        assert listed
        assert listed[0]["subagent_id"] == "sub-1"
        assert listed[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_sends_sigint_before_sigterm(self, tmp_path):
        """Verify process.send_signal(SIGINT) is called first, then terminate() only after timeout."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.workspace_path = str(tmp_path / "ws")
        Path(state.workspace_path).mkdir(parents=True, exist_ok=True)
        manager._subagents["sub-1"] = state

        call_order = []

        mock_process = AsyncMock()
        mock_process.returncode = None

        def _track_send_signal(signum):
            call_order.append(("send_signal", signum))

        mock_process.send_signal = MagicMock(side_effect=_track_send_signal)

        def _track_terminate():
            call_order.append(("terminate",))

        mock_process.terminate = MagicMock(side_effect=_track_terminate)

        # First wait (after SIGINT) times out, second wait (after SIGTERM) succeeds
        mock_process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), 0])
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        # SIGINT should be sent first
        assert call_order[0] == ("send_signal", sig.SIGINT)
        # SIGTERM should come after SIGINT timeout
        assert ("terminate",) in call_order

    @pytest.mark.asyncio
    async def test_cancel_reads_session_id_from_sentinel(self, tmp_path):
        """Cancel reads .massgen/.session_id sentinel and saves to registry."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        state.workspace_path = str(ws)
        manager._subagents["sub-1"] = state

        # Write sentinel file
        sentinel_dir = ws / ".massgen"
        sentinel_dir.mkdir(parents=True)
        session_id = "session_20260223_120000"
        (sentinel_dir / ".session_id").write_text(session_id)
        # Mark session as continuable by creating at least one saved turn.
        (sentinel_dir / "sessions" / session_id / "turn_1").mkdir(parents=True, exist_ok=True)

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        # Check registry was saved with session_id from sentinel
        registry_file = manager.subagents_base / "_registry.json"
        assert registry_file.exists()
        registry = json.loads(registry_file.read_text())
        sub_entry = registry["subagents"][0]
        assert sub_entry["session_id"] == session_id
        assert sub_entry["continuable_via"] == "session"

    @pytest.mark.asyncio
    async def test_cancel_empty_session_from_sentinel_uses_context_recovery(self, tmp_path):
        """Sentinel-only sessions with no saved turns should not be treated as continuable."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        state.workspace_path = str(ws)
        manager._subagents["sub-1"] = state

        sentinel_dir = ws / ".massgen"
        sentinel_dir.mkdir(parents=True)
        session_id = "session_20260223_empty"
        (sentinel_dir / ".session_id").write_text(session_id)
        (sentinel_dir / "sessions" / session_id).mkdir(parents=True, exist_ok=True)

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        registry = json.loads((manager.subagents_base / "_registry.json").read_text())
        sub_entry = registry["subagents"][0]
        assert sub_entry["session_id"] is None
        assert sub_entry["continuable_via"] == "context_recovery"

    @pytest.mark.asyncio
    async def test_cancel_always_saves_registry(self, tmp_path):
        """Cancelled subagent always gets a registry entry, even without session_id."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        state.workspace_path = str(ws)
        manager._subagents["sub-1"] = state

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        registry_file = manager.subagents_base / "_registry.json"
        assert registry_file.exists()
        registry = json.loads(registry_file.read_text())
        assert len(registry["subagents"]) == 1
        sub_entry = registry["subagents"][0]
        assert sub_entry["subagent_id"] == "sub-1"
        assert sub_entry["session_id"] is None
        assert sub_entry["continuable_via"] == "context_recovery"

    @pytest.mark.asyncio
    async def test_cancel_sigint_graceful_shutdown(self, tmp_path):
        """SIGINT leads to graceful shutdown without SIGTERM when process exits in time."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.workspace_path = str(tmp_path / "ws")
        Path(state.workspace_path).mkdir(parents=True, exist_ok=True)
        manager._subagents["sub-1"] = state

        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.send_signal = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)  # Exits promptly after SIGINT
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        mock_process.send_signal.assert_called_once_with(sig.SIGINT)
        mock_process.terminate.assert_not_called()
        mock_process.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_sigint_before_bg_task_cancel(self, tmp_path):
        """SIGINT is sent to process BEFORE bg_task is cancelled, preventing race."""
        manager = _make_manager(tmp_path)
        state = _make_state("sub-1", status="running")
        state.workspace_path = str(tmp_path / "ws")
        Path(state.workspace_path).mkdir(parents=True, exist_ok=True)
        manager._subagents["sub-1"] = state

        call_order = []

        mock_process = AsyncMock()
        mock_process.returncode = None

        def _track_send_signal(signum):
            call_order.append("sigint")

        mock_process.send_signal = MagicMock(side_effect=_track_send_signal)
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        manager._active_processes["sub-1"] = mock_process

        # Create a bg_task that tracks when cancel() is called
        mock_bg_task = MagicMock()
        mock_bg_task.done.return_value = False

        def _track_bg_cancel():
            call_order.append("bg_cancel")

        mock_bg_task.cancel = MagicMock(side_effect=_track_bg_cancel)
        manager._background_tasks["sub-1"] = mock_bg_task

        result = await manager.cancel_subagent("sub-1")
        assert result["success"] is True

        # SIGINT must come before bg_task.cancel()
        assert call_order == ["sigint", "bg_cancel"]

    @pytest.mark.asyncio
    async def test_background_cancel_not_overwritten_by_timeout_result(self, tmp_path, monkeypatch):
        """Background runner must preserve cancelled state/result when cancellation races timeout handling."""
        manager = _make_manager(tmp_path)
        (Path(manager.parent_workspace) / "CONTEXT.md").write_text("# Context\ncancel test\n")

        started = asyncio.Event()

        async def _fake_execute_subagent(config, workspace):  # noqa: ANN001 - monkeypatch target signature
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Mirror real _execute_subagent behavior that converts cancellation
                # into a timeout-style result payload.
                return manager._create_timeout_result_with_recovery(
                    subagent_id=config.id,
                    workspace=workspace,
                    timeout_seconds=10.0,
                )

        monkeypatch.setattr(manager, "_execute_subagent", _fake_execute_subagent)

        spawned = manager.spawn_subagent_background(
            task="long running task",
            subagent_id="sub-1",
            timeout_seconds=10.0,
        )
        assert spawned["status"] == "running"

        await asyncio.wait_for(started.wait(), timeout=1.0)
        cancelled = await manager.cancel_subagent("sub-1")
        assert cancelled["success"] is True
        assert cancelled["status"] == "cancelled"

        await manager.wait_for_subagent("sub-1", timeout=2.0)

        state = manager._subagents["sub-1"]
        assert state.status == "cancelled"
        assert state.result is not None
        assert state.result.error == "Subagent cancelled"

        listed = manager.list_subagents()
        assert listed
        assert listed[0]["subagent_id"] == "sub-1"
        assert listed[0]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Per-agent writable workspace pre-population test
# ---------------------------------------------------------------------------


class _DummyFilesystemManager:
    def __init__(self, cwd: Path) -> None:
        self.cwd = str(cwd)
        self.path_permission_manager = None
        self.agent_temporary_workspace = None
        self.enable_code_based_tools = False

    def get_current_workspace(self) -> str:
        return self.cwd

    def setup_orchestration_paths(self, **kwargs) -> None:
        return None

    def setup_massgen_skill_directories(self, **kwargs) -> None:
        return None

    def setup_memory_directories(self) -> None:
        return None

    def update_backend_mcp_config(self, _backend_config) -> None:
        return None


class _DummyBackend:
    def __init__(self, cwd: Path) -> None:
        self.filesystem_manager = _DummyFilesystemManager(cwd)
        self.config = {}


class _DummyAgent:
    def __init__(self, agent_id: str, cwd: Path) -> None:
        self.agent_id = agent_id
        self.backend = _DummyBackend(cwd)


def test_pre_populated_workspaces_copied_writable_per_agent(tmp_path):
    """Orchestrator with _pre_populated_workspaces copies per-agent matched workspaces as writable."""
    from massgen.agent_config import AgentConfig
    from massgen.orchestrator import Orchestrator

    # Create agent workspaces
    ws_a = tmp_path / "ws_a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws_b"
    ws_b.mkdir()

    agents = {
        "agent_a": _DummyAgent("agent_a", ws_a),
        "agent_b": _DummyAgent("agent_b", ws_b),
    }

    orchestrator = Orchestrator(agents=agents, config=AgentConfig())

    # Create source workspaces (simulating saved cancelled turn workspaces)
    src_a = tmp_path / "saved_ws" / "agent_a"
    src_a.mkdir(parents=True)
    (src_a / "research.md").write_text("# Agent A research")
    (src_a / "notes").mkdir()
    (src_a / "notes" / "detail.txt").write_text("details from agent A")

    src_b = tmp_path / "saved_ws" / "agent_b"
    src_b.mkdir(parents=True)
    (src_b / "analysis.md").write_text("# Agent B analysis")

    # Set pre-populated workspaces
    orchestrator._pre_populated_workspaces = {
        "agent_a": src_a,
        "agent_b": src_b,
    }

    orchestrator._clear_agent_workspaces()

    # Verify agent_a got its files (writable copy)
    assert (ws_a / "research.md").exists()
    assert (ws_a / "research.md").read_text() == "# Agent A research"
    assert (ws_a / "notes" / "detail.txt").read_text() == "details from agent A"

    # Verify agent_b got its files
    assert (ws_b / "analysis.md").exists()
    assert (ws_b / "analysis.md").read_text() == "# Agent B analysis"

    # Verify files are writable (not symlinks)
    assert not (ws_a / "research.md").is_symlink()
    assert not (ws_b / "analysis.md").is_symlink()

    # Pre-populated should be cleared after use
    assert orchestrator._pre_populated_workspaces is None


def test_pre_populated_workspaces_unmatched_agents_get_empty(tmp_path):
    """Agents without matching pre-populated workspace get empty workspace."""
    from massgen.agent_config import AgentConfig
    from massgen.orchestrator import Orchestrator

    ws_a = tmp_path / "ws_a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws_b"
    ws_b.mkdir()
    # Put some pre-existing content to verify it gets cleared
    (ws_b / "old_file.txt").write_text("should be cleared")

    agents = {
        "agent_a": _DummyAgent("agent_a", ws_a),
        "agent_b": _DummyAgent("agent_b", ws_b),
    }

    orchestrator = Orchestrator(agents=agents, config=AgentConfig())

    src_a = tmp_path / "saved_ws" / "agent_a"
    src_a.mkdir(parents=True)
    (src_a / "research.md").write_text("# Agent A research")

    # Only agent_a has pre-populated workspace
    orchestrator._pre_populated_workspaces = {
        "agent_a": src_a,
    }

    orchestrator._clear_agent_workspaces()

    assert (ws_a / "research.md").exists()
    # agent_b's old content should be cleared, but no new content
    assert not (ws_b / "old_file.txt").exists()
    assert list(ws_b.iterdir()) == []


def test_clear_agent_workspaces_preserves_massgen_subagent_mcp_with_previous_turn_copy(tmp_path):
    """Workspace clear should keep .massgen/subagent_mcp files while restoring turn n-1 files."""
    from massgen.agent_config import AgentConfig
    from massgen.orchestrator import Orchestrator

    ws = tmp_path / "ws"
    ws.mkdir()
    mcp_dir = ws / ".massgen" / "subagent_mcp"
    mcp_dir.mkdir(parents=True)
    specialized_types = mcp_dir / "agent_a_specialized_types.json"
    specialized_types.write_text('[{"name":"critic"}]')
    (ws / "old_file.txt").write_text("stale")

    prev = tmp_path / "prev_turn"
    prev.mkdir()
    (prev / "restored.txt").write_text("from previous turn")

    agents = {"agent_a": _DummyAgent("agent_a", ws)}
    orchestrator = Orchestrator(
        agents=agents,
        config=AgentConfig(),
        previous_turns=[{"path": str(prev)}],
    )

    orchestrator._clear_agent_workspaces()

    assert not (ws / "old_file.txt").exists()
    assert (ws / "restored.txt").read_text() == "from previous turn"
    assert specialized_types.exists()
    assert specialized_types.read_text() == '[{"name":"critic"}]'
