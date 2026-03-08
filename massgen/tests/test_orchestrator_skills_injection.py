"""Tests for skills validation in the orchestrator.

Verifies:
1. _validate_skills_config no longer requires command execution
2. _validate_skills_config does NOT inject any skills MCP server
3. Agent mcp_servers remain unchanged after validation
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


def _make_mock_agent(
    agent_id: str,
    enable_mcp_command_line: bool = False,
    backend_type: str = "chat_completions",
) -> Any:
    """Create a mock agent with the minimum attributes needed for skills testing."""
    backend = MagicMock()
    backend.config = {
        "model": "mock-model",
        "type": backend_type,
        "enable_mcp_command_line": enable_mcp_command_line,
        "mcp_servers": [],
    }
    agent = MagicMock()
    agent.backend = backend
    agent.config = backend.config
    return agent


def _make_orchestrator(agents: dict[str, Any], skills_dir: str = ".agent/skills") -> Any:
    """Create a minimal orchestrator for testing _validate_skills_config."""
    from massgen.orchestrator import Orchestrator

    config = SimpleNamespace(
        coordination_config=SimpleNamespace(
            skills_directory=skills_dir,
            use_skills=True,
            load_previous_session_skills=False,
        ),
    )

    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = agents
    orch.config = config
    orch.orchestrator_id = "test-orch"
    return orch


def test_orchestrator_no_longer_requires_command_exec_for_skills(tmp_path: Path) -> None:
    """use_skills=True + no command execution = no error.

    Previously _validate_skills_config raised RuntimeError when no agent
    had enable_mcp_command_line=True. This restriction is now removed.
    """
    # Create a skills directory with at least one skill
    skills_dir = tmp_path / ".agent" / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\nname: demo\ndescription: test\n---\n", encoding="utf-8")

    agent_a = _make_mock_agent("agent_a", enable_mcp_command_line=False)
    orch = _make_orchestrator(
        agents={"agent_a": agent_a},
        skills_dir=str(tmp_path / ".agent" / "skills"),
    )

    # Should NOT raise RuntimeError
    orch._validate_skills_config()


def test_validate_skills_config_does_not_inject_mcp(tmp_path: Path) -> None:
    """_validate_skills_config should NOT modify agent mcp_servers.

    The skills MCP server has been removed. Agents access skills directly
    from the filesystem via workspace tools MCP.
    """
    skills_dir = tmp_path / ".agent" / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\nname: demo\ndescription: test\n---\n", encoding="utf-8")

    agent_a = _make_mock_agent("agent_a", enable_mcp_command_line=False)
    agent_b = _make_mock_agent("agent_b", enable_mcp_command_line=True)
    agent_c = _make_mock_agent("agent_c", enable_mcp_command_line=False, backend_type="codex")

    orch = _make_orchestrator(
        agents={"agent_a": agent_a, "agent_b": agent_b, "agent_c": agent_c},
        skills_dir=str(tmp_path / ".agent" / "skills"),
    )

    orch._validate_skills_config()

    # No agent should have any skills MCP server injected
    for agent_id, agent in orch.agents.items():
        mcp_servers = agent.backend.config.get("mcp_servers", [])
        assert mcp_servers == [], f"Agent {agent_id} should have no MCP servers injected, got: {mcp_servers}"


def test_validate_skills_config_raises_when_no_skills(tmp_path: Path) -> None:
    """_validate_skills_config should raise RuntimeError when no skills exist."""
    from unittest.mock import patch

    empty_skills_dir = tmp_path / ".agent" / "skills"
    empty_skills_dir.mkdir(parents=True)

    # Also create an empty builtin skills dir so the check fails
    empty_builtin = tmp_path / "builtin_skills"
    empty_builtin.mkdir()

    agent_a = _make_mock_agent("agent_a")
    orch = _make_orchestrator(
        agents={"agent_a": agent_a},
        skills_dir=str(empty_skills_dir),
    )

    # Patch __file__ so Path(__file__).parent / "skills" points to the empty builtin dir
    with patch("massgen.orchestrator.__file__", str(tmp_path / "orchestrator.py")):
        with pytest.raises(RuntimeError, match="No skills found"):
            orch._validate_skills_config()
