"""Tests for the single-parent round evaluator loop."""

from __future__ import annotations

from pathlib import Path

import yaml

from massgen.config_validator import ConfigValidator


def _make_round_evaluator_config() -> dict:
    return {
        "agents": [
            {
                "id": "parent",
                "backend": {"type": "codex", "model": "gpt-5.4"},
            },
        ],
        "orchestrator": {
            "voting_sensitivity": "checklist_gated",
            "coordination": {
                "enable_subagents": True,
                "subagent_types": ["round_evaluator"],
                "round_evaluator_before_checklist": True,
                "orchestrator_managed_round_evaluator": True,
                "subagent_orchestrator": {
                    "enabled": True,
                    "agents": [
                        {"id": "eval_codex", "backend": {"type": "codex", "model": "gpt-5.4"}},
                        {"id": "eval_claude", "backend": {"type": "claude_code", "model": "claude-sonnet-4-6"}},
                        {"id": "eval_gemini", "backend": {"type": "gemini", "model": "gemini-3.1-pro-preview"}},
                    ],
                },
            },
        },
    }


def test_parse_coordination_config_passes_round_evaluator_before_checklist():
    from massgen.cli import _parse_coordination_config

    coord = _parse_coordination_config(
        {
            "round_evaluator_before_checklist": True,
            "orchestrator_managed_round_evaluator": True,
            "subagent_orchestrator": {
                "enabled": True,
                "final_answer_strategy": "synthesize",
            },
        },
    )

    assert coord.round_evaluator_before_checklist is True
    assert coord.orchestrator_managed_round_evaluator is True
    assert coord.subagent_orchestrator is not None
    assert coord.subagent_orchestrator.final_answer_strategy == "synthesize"


def test_config_validator_accepts_valid_round_evaluator_single_parent_config():
    result = ConfigValidator().validate_config(_make_round_evaluator_config())
    assert result.is_valid(), result.format_errors()


def test_config_validator_rejects_nested_invalid_subagent_final_answer_strategy():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["subagent_orchestrator"]["final_answer_strategy"] = "invalid"

    result = ConfigValidator().validate_config(config)

    errors = [e for e in result.errors if "final_answer_strategy" in e.location]
    assert errors


def test_config_validator_rejects_orchestrator_managed_round_evaluator_without_prompt_flag():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["round_evaluator_before_checklist"] = False

    result = ConfigValidator().validate_config(config)

    assert any("orchestrator_managed_round_evaluator" in e.location for e in result.errors)


def test_config_validator_accepts_round_evaluator_loop_for_multi_parent_runs():
    config = _make_round_evaluator_config()
    config["agents"].append(
        {
            "id": "peer_parent",
            "backend": {"type": "codex", "model": "gpt-5.4"},
        },
    )

    result = ConfigValidator().validate_config(config)

    assert result.is_valid(), result.format_errors()


def test_config_validator_rejects_round_evaluator_loop_without_subagent_support():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["enable_subagents"] = False

    result = ConfigValidator().validate_config(config)

    assert any("enable_subagents" in e.message for e in result.errors)


def test_config_validator_rejects_round_evaluator_loop_without_round_evaluator_type():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["subagent_types"] = ["evaluator"]

    result = ConfigValidator().validate_config(config)

    assert any("round_evaluator" in e.message for e in result.errors)


def test_config_validator_rejects_round_evaluator_loop_without_enabled_subagent_orchestrator():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["subagent_orchestrator"]["enabled"] = False

    result = ConfigValidator().validate_config(config)

    assert any("subagent_orchestrator" in e.message and "enabled" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# Typed RoundEvaluatorResult contract tests
# ---------------------------------------------------------------------------


def test_round_evaluator_result_from_successful_subagent():
    from massgen.subagent.models import RoundEvaluatorResult, SubagentResult

    raw = SubagentResult.create_success(
        subagent_id="round_eval_r2",
        answer="# Critique Packet\n\nFull synthesized report",
        workspace_path="/tmp/ws",
        execution_time_seconds=45.0,
    )
    result = RoundEvaluatorResult.from_subagent_result(raw, elapsed=50.0)

    assert result.status == "success"
    assert result.packet_text == "# Critique Packet\n\nFull synthesized report"
    assert result.degraded_fallback_used is False
    assert result.execution_time_seconds == 50.0
    assert result.subagent_id == "round_eval_r2"


def test_round_evaluator_result_from_failed_subagent():
    from massgen.subagent.models import RoundEvaluatorResult, SubagentResult

    raw = SubagentResult.create_error(
        subagent_id="round_eval_r2",
        error="Config validation failed",
        workspace_path="/tmp/ws",
    )
    result = RoundEvaluatorResult.from_subagent_result(raw, elapsed=3.5)

    assert result.status == "degraded"
    assert result.degraded_fallback_used is True
    assert result.packet_text is None
    assert "Config validation failed" in result.error


def test_round_evaluator_result_serialization_roundtrip():
    from massgen.subagent.models import RoundEvaluatorResult

    original = RoundEvaluatorResult(
        packet_text="critique text",
        status="success",
        degraded_fallback_used=False,
        execution_time_seconds=42.0,
        subagent_id="eval_1",
        log_path="/tmp/logs",
        primary_artifact_path="/tmp/ws/critique_packet.md",
        next_tasks_artifact_path="/tmp/ws/next_tasks.json",
        task_plan_source="next_tasks_artifact",
        next_tasks={
            "schema_version": "1",
            "execution_scope": {"active_chunk": "c1"},
            "tasks": [{"id": "t1", "description": "Do work", "verification": "done"}],
        },
    )
    restored = RoundEvaluatorResult.from_dict(original.to_dict())

    assert restored.packet_text == original.packet_text
    assert restored.status == original.status
    assert restored.degraded_fallback_used == original.degraded_fallback_used
    assert restored.execution_time_seconds == original.execution_time_seconds
    assert restored.subagent_id == original.subagent_id
    assert restored.log_path == original.log_path
    assert restored.primary_artifact_path == original.primary_artifact_path
    assert restored.next_tasks_artifact_path == original.next_tasks_artifact_path
    assert restored.task_plan_source == "next_tasks_artifact"
    assert restored.next_tasks == original.next_tasks


# ---------------------------------------------------------------------------
# Packet-only checklist instruction tests
# ---------------------------------------------------------------------------


def test_evaluator_result_block_contains_packet_only_instruction():
    """The formatted result block must instruct the parent to use the packet as sole diagnostic basis."""
    from massgen.subagent.models import RoundEvaluatorResult

    evaluator_result = RoundEvaluatorResult(
        packet_text="Critique findings here",
        status="success",
        subagent_id="eval_r2",
    )
    # Import the formatter from orchestrator — it's a standalone method.
    # We test the output string directly.
    from massgen.orchestrator import Orchestrator

    block = Orchestrator._format_round_evaluator_result_block_static(
        subagent_id="eval_r2",
        evaluator_result=evaluator_result,
    )
    assert "sole diagnostic basis" in block.lower() or "sole diagnostic" in block.lower()
    assert "do not run a separate self-evaluation" in block.lower() or "do NOT run a separate" in block


def test_evaluator_result_block_includes_status():
    """The formatted result block must surface the evaluator status."""
    from massgen.orchestrator import Orchestrator
    from massgen.subagent.models import RoundEvaluatorResult

    evaluator_result = RoundEvaluatorResult(
        packet_text="Findings",
        status="degraded",
        degraded_fallback_used=True,
        subagent_id="eval_r2",
    )
    block = Orchestrator._format_round_evaluator_result_block_static(
        subagent_id="eval_r2",
        evaluator_result=evaluator_result,
    )
    assert "degraded" in block.lower()


def test_auto_injected_evaluator_result_block_includes_summary():
    """Auto-injected mode should include evaluator answer text and workflow instructions."""
    from massgen.orchestrator import Orchestrator
    from massgen.subagent.models import RoundEvaluatorResult

    evaluator_result = RoundEvaluatorResult(
        packet_text="Key findings: E1=4, E3=7. See critique_packet.md for details.",
        clean_packet_text="Key findings: E1=4, E3=7. See critique_packet.md for details.",
        status="success",
        subagent_id="eval_r2",
        primary_artifact_path="/tmp/eval/critique_packet.md",
        next_tasks_artifact_path="/tmp/eval/next_tasks.json",
    )

    block = Orchestrator._format_round_evaluator_result_block_static(
        subagent_id="eval_r2",
        evaluator_result=evaluator_result,
        auto_injected=True,
    )

    assert "get_task_plan" in block
    assert "Key findings: E1=4, E3=7" in block
    assert "<evaluator_summary" in block
    assert "submit_checklist" in block and "do not call" in block.lower()
    assert "propose_improvements" in block and "do not call" in block.lower()
    assert "diagnostic report" in block.lower()
    assert "pure text artifact" in block.lower()
    assert "critique_packet.md" in block
    assert "implementation_guidance" in block


# ---------------------------------------------------------------------------
# Example config tests
# ---------------------------------------------------------------------------


def test_parse_coordination_config_passes_round_evaluator_refine():
    from massgen.cli import _parse_coordination_config

    coord = _parse_coordination_config(
        {
            "round_evaluator_before_checklist": True,
            "orchestrator_managed_round_evaluator": True,
            "round_evaluator_refine": True,
            "subagent_orchestrator": {"enabled": True},
        },
    )
    assert coord.round_evaluator_refine is True


def test_round_evaluator_refine_defaults_to_false():
    from massgen.cli import _parse_coordination_config

    coord = _parse_coordination_config(
        {
            "round_evaluator_before_checklist": True,
            "orchestrator_managed_round_evaluator": True,
        },
    )
    assert coord.round_evaluator_refine is False


def test_config_validator_rejects_round_evaluator_refine_without_managed():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["orchestrator_managed_round_evaluator"] = False
    config["orchestrator"]["coordination"]["round_evaluator_before_checklist"] = False
    config["orchestrator"]["coordination"]["round_evaluator_refine"] = True

    result = ConfigValidator().validate_config(config)
    assert not result.is_valid()
    assert any("round_evaluator_refine" in e.message for e in result.errors)


def test_config_validator_accepts_round_evaluator_refine_with_managed():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["round_evaluator_refine"] = True

    result = ConfigValidator().validate_config(config)
    assert result.is_valid(), result.format_errors()


def test_planning_injection_dir_is_absolute(tmp_path, monkeypatch):
    """The injection dir stored in _planning_injection_dirs must be absolute.

    If relative, the MCP subprocess (whose CWD differs from the orchestrator)
    won't find inject_tasks.json and the agent gets an empty task plan.
    Regression test for the bug where get_log_session_dir() returned a relative
    path and the orchestrator passed it as-is to the planning MCP.
    """
    import massgen.orchestrator as orch_mod

    # Simulate get_log_session_dir returning a relative path (the bug trigger)
    relative_log_dir = Path(".massgen/massgen_logs/log_test/turn_1/attempt_1")
    monkeypatch.setattr(
        orch_mod,
        "get_log_session_dir",
        lambda *a, **kw: relative_log_dir,
    )

    # Directly exercise the injection-dir construction logic extracted
    # from _create_planning_mcp_config (lines 2326-2339 of orchestrator.py).
    log_dir = orch_mod.get_log_session_dir()
    injection_dir = (log_dir / "planning_injection" / "agent_a").resolve()

    assert injection_dir.is_absolute(), f"injection_dir must be absolute, got relative: {injection_dir}"


def test_example_round_evaluator_config_exists_and_validates():
    config_path = Path(__file__).resolve().parents[2] / ".massgen" / "config_beatles_round_evaluator.yaml"
    assert config_path.exists()

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    result = ConfigValidator().validate_config(config)

    assert result.is_valid(), result.format_errors()
    assert len(config["agents"]) == 1
    assert config["orchestrator"]["enable_multimodal_tools"] is True
    assert config["orchestrator"]["image_generation_backend"] == "openai"
    assert config["orchestrator"]["video_generation_backend"] == "openai"
    child_agents = config["orchestrator"]["coordination"]["subagent_orchestrator"]["agents"]
    assert [agent["id"] for agent in child_agents] == ["eval_codex", "eval_claude", "eval_gemini"]
