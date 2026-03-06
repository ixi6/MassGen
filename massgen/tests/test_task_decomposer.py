"""Unit tests for TaskDecomposer parsing helpers."""

import importlib.util
import json
from pathlib import Path


def _load_task_decomposer_module():
    """Load task_decomposer module directly to avoid package import side effects."""
    module_path = Path(__file__).resolve().parents[1] / "task_decomposer.py"
    spec = importlib.util.spec_from_file_location("task_decomposer_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_subtasks_from_plain_json_text() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    text = '{"subtasks": {"agent_a": "Research data", "agent_b": "Build implementation"}}'
    parsed = decomposer._parse_subtasks_from_text(text, ["agent_a", "agent_b"])

    assert parsed == {
        "agent_a": "Research data",
        "agent_b": "Build implementation",
    }


def test_parse_subtasks_from_markdown_json_block() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    text = "Here is the plan:\n" "```json\n" '{"subtasks": {"agent_a": "Design architecture", "agent_b": "Implement UI"}}\n' "```"
    parsed = decomposer._parse_subtasks_from_text(text, ["agent_a", "agent_b"])

    assert parsed == {
        "agent_a": "Design architecture",
        "agent_b": "Implement UI",
    }


def test_parse_subtask_specs_from_object_json_text_preserves_per_agent_criteria() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    text = """
    {
      "subtasks": {
        "agent_a": {
          "subtask": "Own the API contract and persistence layer.",
          "criteria": [
            {"text": "API contract is complete", "category": "must"},
            {"text": "Peer UI integration is preserved", "category": "should"}
          ]
        },
        "agent_b": {
          "subtask": "Own the UI shell and interaction polish.",
          "criteria": [
            {"text": "UI is polished", "category": "must"}
          ]
        }
      }
    }
    """

    parsed = decomposer._parse_subtask_specs_from_text(text, ["agent_a", "agent_b"])

    assert parsed["agent_a"]["subtask"] == "Own the API contract and persistence layer."
    assert parsed["agent_a"]["criteria"] == [
        {"text": "API contract is complete", "category": "must"},
        {"text": "Peer UI integration is preserved", "category": "should"},
    ]
    assert parsed["agent_b"]["criteria"] == [
        {"text": "UI is polished", "category": "must"},
    ]


def test_parse_subtasks_from_object_json_text_returns_plain_subtask_strings() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    text = """
    {
      "subtasks": {
        "agent_a": {
          "subtask": "Own the API contract and persistence layer.",
          "criteria": [{"text": "API contract is complete", "category": "must"}]
        },
        "agent_b": {
          "subtask": "Own the UI shell and interaction polish."
        }
      }
    }
    """

    parsed = decomposer._parse_subtasks_from_text(text, ["agent_a", "agent_b"])

    assert parsed == {
        "agent_a": "Own the API contract and persistence layer.",
        "agent_b": "Own the UI shell and interaction polish.",
    }


def test_parse_subtask_specs_from_workspace_recovers_snapshot_decomposition_plan(tmp_path: Path) -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    artifact = tmp_path / "task_decomposition" / "workspace" / "snapshots" / "log_20260305_152747_062436" / "agent_a" / "deliverable" / "decomposition_plan.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "subtasks": {
                    "agent_a": {
                        "subtask": "Own the data model and persistence layer.",
                        "criteria": [{"text": "Storage contract is correct", "category": "must"}],
                    },
                    "agent_b": {
                        "subtask": "Own the UI shell and wire it to the stored data.",
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    parsed = decomposer._parse_subtask_specs_from_workspace(
        str(tmp_path / "task_decomposition"),
        ["agent_a", "agent_b"],
    )

    assert parsed["agent_a"]["subtask"] == "Own the data model and persistence layer."
    assert parsed["agent_a"]["criteria"] == [
        {"text": "Storage contract is correct", "category": "must"},
    ]
    assert parsed["agent_b"]["subtask"] == "Own the UI shell and wire it to the stored data."


def test_parse_subtask_specs_from_workspace_recovers_full_logs_subtask_assignment(tmp_path: Path) -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    artifact = tmp_path / "task_decomposition" / "full_logs" / "agent_b" / "20260305_152900" / "workspace" / "deliverable" / "subtask_assignment.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "subtasks": {
                    "agent_a": "Own the backend contract and validation.",
                    "agent_b": "Own the frontend state flow and integration checks.",
                },
            },
        ),
        encoding="utf-8",
    )

    parsed = decomposer._parse_subtasks_from_workspace(
        str(tmp_path / "task_decomposition"),
        ["agent_a", "agent_b"],
    )

    assert parsed == {
        "agent_a": "Own the backend contract and validation.",
        "agent_b": "Own the frontend state flow and integration checks.",
    }


def test_normalize_subtasks_fills_missing_agents() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    parsed = decomposer._normalize_subtasks(
        {
            "agent_a": "Write tests",
        },
        ["agent_a", "agent_b", "agent_c"],
    )

    assert parsed["agent_a"] == "Write tests"
    assert "agent_b" in parsed
    assert "agent_c" in parsed


def test_build_decomposition_prompt_includes_balance_and_bleed_guidance() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    prompt = decomposer._build_decomposition_prompt(
        task="Create a website about Bob Dylan",
        agent_descriptions=[
            "- agent_a: General-purpose agent",
            "- agent_b: General-purpose agent",
        ],
        agent_ids=["agent_a", "agent_b"],
    )

    assert "Balance depth: each subtask should include implementation work plus quality validation." in prompt
    assert "Keep ownership-first boundaries" in prompt
    assert "Keep cross-subtask bleed limited to integration needs" in prompt
    assert "Write each subtask as 2-3 sentences" in prompt
    assert "start at kickoff in parallel" in prompt
    assert "use anonymous aliases (`agent1`, `agent2`, ...)" in prompt


def test_fallback_subtasks_do_not_echo_system_message_snippets() -> None:
    module = _load_task_decomposer_module()
    decomposer = module.TaskDecomposer(module.TaskDecomposerConfig())

    marker = "DO_NOT_LEAK_THIS_PROMPT_SNIPPET"
    subtasks = decomposer._generate_fallback_subtasks(
        task="Build a website",
        agent_ids=["agent_a"],
        system_messages={"agent_a": f"custom prompt with {marker} and extra instructions"},
    )

    assert "agent_a" in subtasks
    assert marker not in subtasks["agent_a"]
    assert "aligned with your specialization" in subtasks["agent_a"]
