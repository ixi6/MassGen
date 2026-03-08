"""Regression tests for orchestrator workspace snapshot context sharing."""

import shutil
from pathlib import Path

import pytest

from massgen.chat_agent import ChatAgent
from massgen.orchestrator import Orchestrator


class MockFilesystemManager:
    """Minimal filesystem manager used by orchestrator context-sharing tests."""

    def __init__(self, cwd: str):
        self.cwd = Path(cwd)
        self.snapshot_storage: Path | None = None
        self.agent_temporary_workspace: Path | None = None
        self.agent_id: str | None = None
        self.save_snapshot_calls: list[tuple[str | None, bool]] = []
        self.clear_workspace_calls = 0
        self.copy_snapshots_calls: list[tuple[dict, dict]] = []
        self.setup_calls = 0

    def setup_orchestration_paths(self, agent_id, snapshot_storage, agent_temporary_workspace, **kwargs):
        self.setup_calls += 1
        self.agent_id = agent_id
        if snapshot_storage:
            self.snapshot_storage = Path(snapshot_storage)
            (self.snapshot_storage / agent_id).mkdir(parents=True, exist_ok=True)
        if agent_temporary_workspace:
            self.agent_temporary_workspace = Path(agent_temporary_workspace)
            (self.agent_temporary_workspace / agent_id).mkdir(parents=True, exist_ok=True)

    def update_backend_mcp_config(self, config) -> None:
        """No-op for tests."""

    def setup_massgen_skill_directories(self, massgen_skills) -> None:
        """No-op for tests."""

    def setup_memory_directories(self) -> None:
        """No-op for tests."""

    def restore_memories_from_previous_turn(self, prev_workspace: Path) -> None:
        """No-op for tests."""

    def get_current_workspace(self) -> str:
        return str(self.cwd)

    async def save_snapshot(self, timestamp=None, is_final=False, preserve_existing_snapshot=False) -> None:
        self.save_snapshot_calls.append((timestamp, is_final))
        if not self.snapshot_storage or not self.agent_id:
            return

        destination = self.snapshot_storage / self.agent_id
        if timestamp:
            destination = destination / timestamp
        destination.mkdir(parents=True, exist_ok=True)

        if self.cwd.exists():
            for item in self.cwd.iterdir():
                target = destination / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)

    def clear_workspace(self) -> None:
        self.clear_workspace_calls += 1

    def restore_from_snapshot_storage(self) -> None:
        """No-op for tests."""

    async def copy_snapshots_to_temp_workspace(self, all_snapshots, agent_mapping):
        self.copy_snapshots_calls.append((all_snapshots, agent_mapping))
        if not self.agent_temporary_workspace or not self.agent_id:
            return None

        workspace_root = self.agent_temporary_workspace / self.agent_id
        workspace_root.mkdir(parents=True, exist_ok=True)

        for source_agent_id, source_snapshot in all_snapshots.items():
            anon_id = agent_mapping.get(source_agent_id, source_agent_id)
            target = workspace_root / anon_id
            shutil.copytree(source_snapshot, target, dirs_exist_ok=True)

        return workspace_root


class MockClaudeCodeBackend:
    """Mock Claude Code backend for testing orchestrator behavior."""

    def __init__(self, cwd: str | None = None, filesystem_enabled: bool = True):
        self._cwd = cwd or "test_workspace"
        self.config = {}
        self.filesystem_manager = MockFilesystemManager(self._cwd) if filesystem_enabled else None

    def get_provider_name(self) -> str:
        return "claude_code"


class MockClaudeCodeAgent(ChatAgent):
    """Mock Claude Code agent for testing."""

    def __init__(self, agent_id: str, cwd: str | None = None, filesystem_enabled: bool = True):
        super().__init__(session_id=f"session_{agent_id}")
        self.agent_id = agent_id
        self.backend = MockClaudeCodeBackend(cwd, filesystem_enabled=filesystem_enabled)

    async def chat(self, messages, tools=None, reset_chat=False, clear_history=False):
        for _ in range(2):
            yield {"type": "content", "content": f"Working on task from {self.agent_id}"}
        yield {"type": "result", "data": ("answer", f"Solution from {self.agent_id}")}

    def get_status(self) -> dict:
        return {"agent_id": self.agent_id, "status": "mock"}

    async def reset(self) -> None:
        pass

    def get_configurable_system_message(self) -> str | None:
        return None


@pytest.fixture
def test_workspace(tmp_path):
    workspace = tmp_path / "test_context_sharing"
    workspace.mkdir(exist_ok=True)

    snapshot_storage = workspace / "snapshots"
    temp_workspace = workspace / "temp_workspaces"
    snapshot_storage.mkdir(exist_ok=True)
    temp_workspace.mkdir(exist_ok=True)

    return {
        "workspace": workspace,
        "snapshot_storage": str(snapshot_storage),
        "temp_workspace": str(temp_workspace),
    }


@pytest.fixture
def mock_agents(test_workspace):
    agents = {}
    workspace_root = Path(test_workspace["workspace"])
    for i in range(1, 4):
        agent_id = f"claude_code_{i}"
        cwd = workspace_root / f"agent_{i}"
        agents[agent_id] = MockClaudeCodeAgent(agent_id, str(cwd))
    return agents


def test_orchestrator_initialization_with_context_sharing(test_workspace, mock_agents):
    """Test orchestrator initializes snapshot and temp workspace integration."""
    orchestrator = Orchestrator(
        agents=mock_agents,
        snapshot_storage=test_workspace["snapshot_storage"],
        agent_temporary_workspace=test_workspace["temp_workspace"],
    )

    assert orchestrator._snapshot_storage == test_workspace["snapshot_storage"]
    assert orchestrator._agent_temporary_workspace == test_workspace["temp_workspace"]

    reverse_mapping = orchestrator.coordination_tracker.get_reverse_agent_mapping()
    assert reverse_mapping["claude_code_1"] == "agent1"
    assert reverse_mapping["claude_code_2"] == "agent2"
    assert reverse_mapping["claude_code_3"] == "agent3"

    for agent in mock_agents.values():
        assert agent.backend.filesystem_manager.setup_calls == 1


@pytest.mark.asyncio
async def test_snapshot_saving(test_workspace, mock_agents):
    """Test save_snapshot orchestration for a single agent."""
    orchestrator = Orchestrator(
        agents=mock_agents,
        snapshot_storage=test_workspace["snapshot_storage"],
        agent_temporary_workspace=test_workspace["temp_workspace"],
    )

    agent = mock_agents["claude_code_1"]
    workspace = Path(agent.backend._cwd)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "code_claude_code_1.py").write_text("# Code from claude_code_1")
    (workspace / "test_claude_code_1.txt").write_text("Test data from claude_code_1")

    timestamp = await orchestrator._save_agent_snapshot("claude_code_1", answer_content="answer")
    assert timestamp
    assert agent.backend.filesystem_manager.clear_workspace_calls == 1

    snapshot_dir = Path(test_workspace["snapshot_storage"]) / "claude_code_1" / timestamp
    assert (snapshot_dir / "code_claude_code_1.py").exists()
    assert (snapshot_dir / "test_claude_code_1.txt").exists()


@pytest.mark.asyncio
async def test_workspace_restoration_with_anonymization(test_workspace, mock_agents):
    """Test copying snapshots into temp workspace with anonymized agent directories."""
    orchestrator = Orchestrator(
        agents=mock_agents,
        snapshot_storage=test_workspace["snapshot_storage"],
        agent_temporary_workspace=test_workspace["temp_workspace"],
    )

    for agent_id, agent in mock_agents.items():
        workspace = Path(agent.backend._cwd)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / f"work_{agent_id}.txt").write_text(f"Work from {agent_id}")
        await orchestrator._save_agent_snapshot(agent_id, answer_content=f"answer from {agent_id}")

    workspace_path = await orchestrator._copy_all_snapshots_to_temp_workspace("claude_code_2")
    assert workspace_path is not None

    workspace_dir = Path(workspace_path)
    for anon in ("agent1", "agent2", "agent3"):
        assert (workspace_dir / anon).exists()

    agent1_files = list((workspace_dir / "agent1").rglob("work_claude_code_1.txt"))
    assert agent1_files
    assert agent1_files[0].read_text() == "Work from claude_code_1"


@pytest.mark.asyncio
async def test_save_all_snapshots(test_workspace, mock_agents):
    """Test saving snapshots for all agents via _save_agent_snapshot."""
    orchestrator = Orchestrator(
        agents=mock_agents,
        snapshot_storage=test_workspace["snapshot_storage"],
        agent_temporary_workspace=test_workspace["temp_workspace"],
    )

    for agent_id, agent in mock_agents.items():
        workspace = Path(agent.backend._cwd)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "shared.py").write_text(f"# Shared code from {agent_id}")
        await orchestrator._save_agent_snapshot(agent_id, answer_content=f"answer from {agent_id}")

    for agent_id, agent in mock_agents.items():
        assert len(agent.backend.filesystem_manager.save_snapshot_calls) == 1
        snapshot_dir = Path(test_workspace["snapshot_storage"]) / agent_id
        shared_files = list(snapshot_dir.rglob("shared.py"))
        assert shared_files
        assert agent_id in shared_files[0].read_text()


@pytest.mark.asyncio
async def test_non_claude_code_agents_ignored(test_workspace):
    """Agents without filesystem support should be skipped for snapshot copy."""
    agents = {
        "claude_code_1": MockClaudeCodeAgent(
            "claude_code_1",
            str(Path(test_workspace["workspace"]) / "agent_1"),
            filesystem_enabled=True,
        ),
        "regular_agent": MockClaudeCodeAgent(
            "regular_agent",
            str(Path(test_workspace["workspace"]) / "regular_agent"),
            filesystem_enabled=False,
        ),
    }

    orchestrator = Orchestrator(
        agents=agents,
        snapshot_storage=test_workspace["snapshot_storage"],
        agent_temporary_workspace=test_workspace["temp_workspace"],
    )

    reverse_mapping = orchestrator.coordination_tracker.get_reverse_agent_mapping()
    assert "claude_code_1" in reverse_mapping
    assert "regular_agent" in reverse_mapping

    workspace_path = await orchestrator._copy_all_snapshots_to_temp_workspace("regular_agent")
    assert workspace_path is None
