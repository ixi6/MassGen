"""Integration coverage for per-spawning-agent subagent backend inheritance.

This test verifies that different parent agents in the same run context each
produce subagent YAML configs that inherit the caller's exact backend/model
when `inherit_spawning_agent_backend` is enabled.
"""

from pathlib import Path

import pytest

from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SubagentConfig, SubagentOrchestratorConfig

pytestmark = pytest.mark.integration


def _build_manager(
    *,
    workspace: Path,
    parent_agent_id: str,
    parent_agent_configs: list[dict],
) -> SubagentManager:
    return SubagentManager(
        parent_workspace=str(workspace),
        parent_agent_id=parent_agent_id,
        orchestrator_id="orch-integration",
        parent_agent_configs=parent_agent_configs,
        subagent_orchestrator_config=SubagentOrchestratorConfig(
            enabled=True,
            inherit_spawning_agent_backend=True,
        ),
    )


def test_subagent_inherits_backend_from_spawning_parent_in_multi_parent_run(tmp_path: Path):
    """Each spawning parent should map to its own exact backend/model."""
    run_root = tmp_path / "run_root"
    run_root.mkdir(parents=True, exist_ok=True)

    parent_agent_configs = [
        {
            "id": "agent_a",
            "backend": {
                "type": "gemini",
                "model": "gemini-3-flash-preview",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            },
        },
        {
            "id": "agent_b",
            "backend": {
                "type": "openai",
                "model": "gpt-5-mini",
                "reasoning": {"effort": "medium"},
            },
        },
    ]

    parent_a_workspace = run_root / "agent_a_workspace"
    parent_b_workspace = run_root / "agent_b_workspace"
    parent_a_workspace.mkdir(parents=True, exist_ok=True)
    parent_b_workspace.mkdir(parents=True, exist_ok=True)

    manager_a = _build_manager(
        workspace=parent_a_workspace,
        parent_agent_id="agent_a",
        parent_agent_configs=parent_agent_configs,
    )
    manager_b = _build_manager(
        workspace=parent_b_workspace,
        parent_agent_id="agent_b",
        parent_agent_configs=parent_agent_configs,
    )

    sub_cfg_a = SubagentConfig.create(
        task="Evaluate draft A",
        parent_agent_id="agent_a",
        subagent_id="subagent_from_a",
    )
    sub_cfg_b = SubagentConfig.create(
        task="Evaluate draft B",
        parent_agent_id="agent_b",
        subagent_id="subagent_from_b",
    )

    sub_ws_a = manager_a._create_workspace(sub_cfg_a.id)
    sub_ws_b = manager_b._create_workspace(sub_cfg_b.id)

    yaml_a = manager_a._generate_subagent_yaml_config(sub_cfg_a, sub_ws_a, context_paths=[])
    yaml_b = manager_b._generate_subagent_yaml_config(sub_cfg_b, sub_ws_b, context_paths=[])

    # agent_a spawn -> gemini subagent backend
    assert len(yaml_a["agents"]) == 1
    backend_a = yaml_a["agents"][0]["backend"]
    assert yaml_a["agents"][0]["id"] == "agent_a"
    assert backend_a["type"] == "gemini"
    assert backend_a["model"] == "gemini-3-flash-preview"
    assert backend_a["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"

    # agent_b spawn -> openai subagent backend
    assert len(yaml_b["agents"]) == 1
    backend_b = yaml_b["agents"][0]["backend"]
    assert yaml_b["agents"][0]["id"] == "agent_b"
    assert backend_b["type"] == "openai"
    assert backend_b["model"] == "gpt-5-mini"
    assert backend_b["reasoning"] == {"effort": "medium"}


def test_subagent_effective_child_team_uses_shared_common_and_parent_local_sources(tmp_path: Path):
    """Different parents should resolve shared common agents plus their own local subagent agents."""
    run_root = tmp_path / "run_root"
    run_root.mkdir(parents=True, exist_ok=True)

    parent_agent_configs = [
        {
            "id": "agent_a",
            "backend": {
                "type": "gemini",
                "model": "gemini-3-flash-preview",
            },
            "subagent_agents": [
                {
                    "id": "a_local",
                    "backend": {"type": "openrouter", "model": "minimax/minimax-m2.5"},
                },
            ],
        },
        {
            "id": "agent_b",
            "backend": {
                "type": "openai",
                "model": "gpt-5-mini",
            },
            "subagent_agents": [
                {
                    "id": "b_local",
                    "backend": {"type": "claude", "model": "claude-sonnet-4-20250514"},
                },
            ],
        },
    ]

    common_agents = [
        {
            "id": "shared_eval",
            "backend": {"type": "openai", "model": "gpt-5-mini"},
        },
    ]

    manager_a = SubagentManager(
        parent_workspace=str(run_root / "agent_a_workspace"),
        parent_agent_id="agent_a",
        orchestrator_id="orch-integration",
        parent_agent_configs=parent_agent_configs,
        subagent_orchestrator_config=SubagentOrchestratorConfig(
            enabled=True,
            agents=common_agents,
        ),
    )
    manager_b = SubagentManager(
        parent_workspace=str(run_root / "agent_b_workspace"),
        parent_agent_id="agent_b",
        orchestrator_id="orch-integration",
        parent_agent_configs=parent_agent_configs,
        subagent_orchestrator_config=SubagentOrchestratorConfig(
            enabled=True,
            agents=common_agents,
        ),
    )

    Path(manager_a.parent_workspace).mkdir(parents=True, exist_ok=True)
    Path(manager_b.parent_workspace).mkdir(parents=True, exist_ok=True)

    sub_cfg_a = SubagentConfig.create(task="Evaluate draft A", parent_agent_id="agent_a", subagent_id="subagent_from_a")
    sub_cfg_b = SubagentConfig.create(task="Evaluate draft B", parent_agent_id="agent_b", subagent_id="subagent_from_b")

    yaml_a = manager_a._generate_subagent_yaml_config(sub_cfg_a, manager_a._create_workspace(sub_cfg_a.id), context_paths=[])
    yaml_b = manager_b._generate_subagent_yaml_config(sub_cfg_b, manager_b._create_workspace(sub_cfg_b.id), context_paths=[])

    assert [agent["id"] for agent in yaml_a["agents"]] == ["shared_eval", "a_local"]
    assert [agent["id"] for agent in yaml_b["agents"]] == ["shared_eval", "b_local"]
