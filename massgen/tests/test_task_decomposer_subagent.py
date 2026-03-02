"""Tests for TaskDecomposer subagent wiring."""

import json
from types import SimpleNamespace

import pytest

from massgen.task_decomposer import TaskDecomposer, TaskDecomposerConfig


def test_decomposition_prompt_mentions_planning_context_alignment():
    decomposer = TaskDecomposer(TaskDecomposerConfig())
    prompt = decomposer._build_decomposition_prompt(
        task="Build a feature",
        agent_descriptions=["- agent1 (output key: agent_a): General", "- agent2 (output key: agent_b): General"],
        agent_ids=["agent_a", "agent_b"],
        has_planning_spec_context=True,
    )
    prompt_lower = prompt.lower()
    assert "planning/spec context" in prompt_lower
    assert "align" in prompt_lower


def test_decomposition_prompt_omits_planning_context_guidance_when_flag_false():
    decomposer = TaskDecomposer(TaskDecomposerConfig())
    prompt = decomposer._build_decomposition_prompt(
        task="Build a feature",
        agent_descriptions=["- agent1 (output key: agent_a): General", "- agent2 (output key: agent_b): General"],
        agent_ids=["agent_a", "agent_b"],
        has_planning_spec_context=False,
    )
    assert "planning/spec context" not in prompt.lower()


@pytest.mark.asyncio
async def test_decomposition_subagent_passes_voting_sensitivity(monkeypatch, tmp_path):
    captured = {}

    class _FakeSubagentManager:
        def __init__(self, *args, **kwargs):
            captured["coordination"] = kwargs["subagent_orchestrator_config"].coordination

        async def spawn_subagent(self, **kwargs):
            return SimpleNamespace(
                success=True,
                answer=json.dumps(
                    {
                        "subtasks": {
                            "agent_a": "Own architecture and data contracts.",
                            "agent_b": "Implement UI and integration checks.",
                        },
                    },
                ),
                error=None,
                workspace_path=None,
            )

        def get_subagent_display_data(self, _subagent_id):
            return None

    monkeypatch.setattr("massgen.subagent.manager.SubagentManager", _FakeSubagentManager)

    decomposer = TaskDecomposer(TaskDecomposerConfig())
    subtasks = await decomposer.generate_decomposition_via_subagent(
        task="Build a feature",
        agent_ids=["agent_a", "agent_b"],
        existing_system_messages={},
        parent_agent_configs=[
            {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            {"id": "agent_b", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
        ],
        parent_workspace=str(tmp_path),
        orchestrator_id="orch_test",
        voting_sensitivity="checklist_gated",
    )

    assert set(subtasks.keys()) == {"agent_a", "agent_b"}
    assert captured["coordination"]["voting_sensitivity"] == "checklist_gated"


@pytest.mark.asyncio
async def test_decomposition_subagent_passes_voting_threshold(monkeypatch, tmp_path):
    captured = {}

    class _FakeSubagentManager:
        def __init__(self, *args, **kwargs):
            captured["coordination"] = kwargs["subagent_orchestrator_config"].coordination

        async def spawn_subagent(self, **kwargs):
            return SimpleNamespace(
                success=True,
                answer=json.dumps(
                    {
                        "subtasks": {
                            "agent_a": "Own architecture and data contracts.",
                            "agent_b": "Implement UI and integration checks.",
                        },
                    },
                ),
                error=None,
                workspace_path=None,
            )

        def get_subagent_display_data(self, _subagent_id):
            return None

    monkeypatch.setattr("massgen.subagent.manager.SubagentManager", _FakeSubagentManager)

    decomposer = TaskDecomposer(TaskDecomposerConfig())
    subtasks = await decomposer.generate_decomposition_via_subagent(
        task="Build a feature",
        agent_ids=["agent_a", "agent_b"],
        existing_system_messages={},
        parent_agent_configs=[
            {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            {"id": "agent_b", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
        ],
        parent_workspace=str(tmp_path),
        orchestrator_id="orch_test",
        voting_sensitivity="checklist_gated",
        voting_threshold=14,
    )

    assert set(subtasks.keys()) == {"agent_a", "agent_b"}
    assert captured["coordination"]["voting_threshold"] == 14


@pytest.mark.asyncio
async def test_decomposition_subagent_inherits_parent_context_paths_readonly(monkeypatch, tmp_path):
    captured = {}
    parent_context = tmp_path / "plan_frozen"
    parent_context.mkdir()

    class _FakeSubagentManager:
        def __init__(self, *args, **kwargs):
            captured["parent_context_paths"] = kwargs.get("parent_context_paths")

        async def spawn_subagent(self, **kwargs):
            return SimpleNamespace(
                success=True,
                answer=json.dumps(
                    {
                        "subtasks": {
                            "agent_a": "Own architecture and data contracts.",
                            "agent_b": "Implement UI and integration checks.",
                        },
                    },
                ),
                error=None,
                workspace_path=None,
            )

        def get_subagent_display_data(self, _subagent_id):
            return None

    monkeypatch.setattr("massgen.subagent.manager.SubagentManager", _FakeSubagentManager)

    decomposer = TaskDecomposer(TaskDecomposerConfig())
    subtasks = await decomposer.generate_decomposition_via_subagent(
        task="Build a feature",
        agent_ids=["agent_a", "agent_b"],
        existing_system_messages={},
        parent_agent_configs=[
            {
                "id": "agent_a",
                "backend": {
                    "type": "openai",
                    "model": "gpt-4o-mini",
                    "context_paths": [{"path": str(parent_context), "permission": "write"}],
                },
            },
            {"id": "agent_b", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
        ],
        parent_workspace=str(tmp_path),
        orchestrator_id="orch_test",
    )

    assert set(subtasks.keys()) == {"agent_a", "agent_b"}
    assert captured["parent_context_paths"] is not None
    assert {"path": str(tmp_path.resolve()), "permission": "read"} in captured["parent_context_paths"]
    assert {"path": str(parent_context.resolve()), "permission": "read"} in captured["parent_context_paths"]
