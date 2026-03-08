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


def test_non_round_evaluator_ignores_shared_common_agents_and_uses_parent_local_sources(tmp_path: Path):
    """Builder-style subagents should ignore the shared evaluator pool and keep per-parent local config."""
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

    sub_cfg_a = SubagentConfig.create(
        task="Evaluate draft A",
        parent_agent_id="agent_a",
        subagent_id="subagent_from_a",
        metadata={"subagent_type": "builder"},
    )
    sub_cfg_b = SubagentConfig.create(
        task="Evaluate draft B",
        parent_agent_id="agent_b",
        subagent_id="subagent_from_b",
        metadata={"subagent_type": "builder"},
    )

    yaml_a = manager_a._generate_subagent_yaml_config(sub_cfg_a, manager_a._create_workspace(sub_cfg_a.id), context_paths=[])
    yaml_b = manager_b._generate_subagent_yaml_config(sub_cfg_b, manager_b._create_workspace(sub_cfg_b.id), context_paths=[])

    assert [agent["id"] for agent in yaml_a["agents"]] == ["a_local"]
    assert [agent["id"] for agent in yaml_b["agents"]] == ["b_local"]


def test_round_evaluator_keeps_shared_common_agents(tmp_path: Path):
    """round_evaluator should keep the shared evaluator pool across parents."""
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
            "id": "shared_eval_a",
            "backend": {"type": "openai", "model": "gpt-5-mini"},
        },
        {
            "id": "shared_eval_b",
            "backend": {"type": "gemini", "model": "gemini-3.1-pro-preview"},
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

    sub_cfg_a = SubagentConfig.create(
        task="Evaluate draft A",
        parent_agent_id="agent_a",
        subagent_id="subagent_from_a",
        metadata={"subagent_type": "round_evaluator"},
    )
    sub_cfg_b = SubagentConfig.create(
        task="Evaluate draft B",
        parent_agent_id="agent_b",
        subagent_id="subagent_from_b",
        metadata={"subagent_type": "round_evaluator"},
    )

    yaml_a = manager_a._generate_subagent_yaml_config(sub_cfg_a, manager_a._create_workspace(sub_cfg_a.id), context_paths=[])
    yaml_b = manager_b._generate_subagent_yaml_config(sub_cfg_b, manager_b._create_workspace(sub_cfg_b.id), context_paths=[])

    assert [agent["id"] for agent in yaml_a["agents"]] == ["shared_eval_a", "shared_eval_b"]
    assert [agent["id"] for agent in yaml_b["agents"]] == ["shared_eval_a", "shared_eval_b"]


def test_shared_child_team_types_can_route_builder_to_shared_common_agents(tmp_path: Path):
    """shared_child_team_types should make opted-in builder subagents use the shared child team."""
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
    ]

    common_agents = [
        {
            "id": "shared_eval_a",
            "backend": {"type": "openai", "model": "gpt-5-mini"},
        },
        {
            "id": "shared_eval_b",
            "backend": {"type": "gemini", "model": "gemini-3.1-pro-preview"},
        },
    ]

    manager = SubagentManager(
        parent_workspace=str(run_root / "agent_a_workspace"),
        parent_agent_id="agent_a",
        orchestrator_id="orch-integration",
        parent_agent_configs=parent_agent_configs,
        subagent_orchestrator_config=SubagentOrchestratorConfig(
            enabled=True,
            shared_child_team_types=["round_evaluator", "builder"],
            agents=common_agents,
        ),
    )

    Path(manager.parent_workspace).mkdir(parents=True, exist_ok=True)

    sub_cfg = SubagentConfig.create(
        task="Build draft A",
        parent_agent_id="agent_a",
        subagent_id="subagent_from_a",
        metadata={"subagent_type": "builder"},
    )

    yaml_config = manager._generate_subagent_yaml_config(sub_cfg, manager._create_workspace(sub_cfg.id), context_paths=[])

    assert [agent["id"] for agent in yaml_config["agents"]] == ["shared_eval_a", "shared_eval_b"]


def test_runtime_injected_keys_excluded_from_inherited_backend(tmp_path: Path):
    """Runtime-injected keys like agent_id must not leak into inherited subagent configs.

    When the CLI injects agent_id, instance_id, etc. into parent backend dicts
    at startup, the passthrough loop in _generate_subagent_yaml_config must
    exclude them.  Otherwise create_backend() receives agent_id twice and raises
    "got multiple values for keyword argument 'agent_id'".
    """
    run_root = tmp_path / "run_root"
    run_root.mkdir(parents=True, exist_ok=True)

    # Simulate a parent backend dict that has runtime-injected keys
    parent_agent_configs = [
        {
            "id": "agent_a",
            "backend": {
                "type": "codex",
                "model": "gpt-5.4",
                "reasoning": {"effort": "medium"},
                # These are injected by the CLI at startup, not user config
                "agent_id": "agent_a",
                "instance_id": "abc12345",
                "filesystem_session_id": "session_20260307_110221",
                "session_storage_base": ".massgen/sessions",
                "agent_temporary_workspace": ".massgen/temp_workspaces/log_123",
                "enable_rate_limit": False,
                "write_mode": "auto",
            },
        },
    ]

    workspace = run_root / "agent_a_workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    manager = _build_manager(
        workspace=workspace,
        parent_agent_id="agent_a",
        parent_agent_configs=parent_agent_configs,
    )

    sub_cfg = SubagentConfig.create(
        task="Evaluate draft",
        parent_agent_id="agent_a",
        subagent_id="round_eval_r2",
    )

    sub_ws = manager._create_workspace(sub_cfg.id)
    yaml_cfg = manager._generate_subagent_yaml_config(sub_cfg, sub_ws, context_paths=[])

    backend = yaml_cfg["agents"][0]["backend"]

    # These runtime keys must NOT appear in the generated subagent backend
    assert "agent_id" not in backend, "agent_id leaked into subagent backend config"
    assert "instance_id" not in backend, "instance_id leaked into subagent backend config"
    assert "filesystem_session_id" not in backend
    assert "session_storage_base" not in backend
    assert "agent_temporary_workspace" not in backend

    # But user-level settings should still pass through
    assert backend["type"] == "codex"
    assert backend["model"] == "gpt-5.4"
    assert backend["reasoning"] == {"effort": "medium"}
    # enable_rate_limit and write_mode are non-excluded passthrough keys
    assert backend.get("enable_rate_limit") is False
    assert backend.get("write_mode") == "auto"
