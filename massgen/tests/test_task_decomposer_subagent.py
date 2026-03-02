"""Tests for TaskDecomposer subagent wiring."""

import json
from types import SimpleNamespace

import pytest

from massgen.task_decomposer import TaskDecomposer, TaskDecomposerConfig


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
