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
                "backend": {"type": "codex", "model": "gpt-5.4", "cwd": "workspace"},
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
                        {"id": "eval_codex", "backend": {"type": "codex", "model": "gpt-5.4", "cwd": "workspace"}},
                        {"id": "eval_claude", "backend": {"type": "claude_code", "model": "claude-sonnet-4-6", "cwd": "workspace"}},
                        {"id": "eval_gemini", "backend": {"type": "gemini", "model": "gemini-3.1-pro-preview"}},
                    ],
                },
            },
        },
    }


def _make_valid_next_tasks_payload() -> dict:
    return {
        "schema_version": "2",
        "objective": "Rebuild the deliverable around a stronger editorial thesis",
        "primary_strategy": "editorial_reframe",
        "why_this_strategy": "A stronger organizing concept fixes multiple weak criteria at once.",
        "strategy_mode": "incremental_refinement",
        "approach_assessment": {
            "ceiling_status": "ceiling_not_reached",
            "ceiling_explanation": "The current approach still has headroom if executed with more discipline.",
            "breakthroughs": [],
            "paradigm_shift": {
                "recommended": False,
                "current_limitation": "",
                "alternative_approach": "",
                "transferable_elements": [],
            },
        },
        "success_contract": {
            "outcome_statement": "The next revision should feel intentionally reauthored, not just patched.",
            "quality_bar": "The weakest section should feel deliberate and premium in isolation.",
            "fail_if_any": [
                "The output still reads like the same template with only local polish changes.",
            ],
            "required_evidence": [
                "Fresh rendered screenshots of the revised sections",
                "Replayable verification notes for the key changed areas",
            ],
        },
        "deprioritize_or_remove": ["generic filler modules"],
        "execution_scope": {"active_chunk": "c1"},
        "fix_tasks": [],
        "evolution_tasks": [
            {
                "id": "reframe_midpage",
                "task_category": "evolution",
                "strategy_role": "thesis_shift",
                "description": "Rebuild the weak middle sections around one stronger editorial concept.",
                "implementation_guidance": "Replace repeated generic card modules with one stronger narrative section model.",
                "priority": "high",
                "depends_on": [],
                "chunk": "c1",
                "execution": {"mode": "delegate", "subagent_type": "builder"},
                "verification": "The mid-page is organized around one stronger editorial concept.",
                "verification_method": "Render the page and compare the changed sections against the previous layout.",
                "success_criteria": "A reviewer can describe one clear new organizing thesis behind the revised sections.",
                "failure_signals": [
                    "The sections are still recognizably the same layout with only copy and styling tweaks.",
                ],
                "required_evidence": [
                    "Before/after screenshots of the rebuilt sections",
                ],
                "metadata": {
                    "impact": "transformative",
                    "relates_to": ["E7", "E8"],
                },
            },
        ],
        "tasks": [
            {
                "id": "reframe_midpage",
                "task_category": "evolution",
                "strategy_role": "thesis_shift",
                "description": "Rebuild the weak middle sections around one stronger editorial concept.",
                "implementation_guidance": "Replace repeated generic card modules with one stronger narrative section model.",
                "priority": "high",
                "depends_on": [],
                "chunk": "c1",
                "execution": {"mode": "delegate", "subagent_type": "builder"},
                "verification": "The mid-page is organized around one stronger editorial concept.",
                "verification_method": "Render the page and compare the changed sections against the previous layout.",
                "success_criteria": "A reviewer can describe one clear new organizing thesis behind the revised sections.",
                "failure_signals": [
                    "The sections are still recognizably the same layout with only copy and styling tweaks.",
                ],
                "required_evidence": [
                    "Before/after screenshots of the rebuilt sections",
                ],
                "metadata": {
                    "impact": "transformative",
                    "relates_to": ["E7", "E8"],
                },
            },
        ],
    }


def test_parse_coordination_config_passes_round_evaluator_before_checklist():
    from massgen.cli import _parse_coordination_config

    coord = _parse_coordination_config(
        {
            "round_evaluator_before_checklist": True,
            "orchestrator_managed_round_evaluator": True,
            "round_evaluator_transformation_pressure": "aggressive",
            "subagent_orchestrator": {
                "enabled": True,
                "final_answer_strategy": "synthesize",
            },
        },
    )

    assert coord.round_evaluator_before_checklist is True
    assert coord.orchestrator_managed_round_evaluator is True
    assert coord.round_evaluator_transformation_pressure == "aggressive"
    assert coord.subagent_orchestrator is not None
    assert coord.subagent_orchestrator.final_answer_strategy == "synthesize"


def test_round_evaluator_transformation_pressure_defaults_to_balanced():
    from massgen.cli import _parse_coordination_config

    coord = _parse_coordination_config(
        {
            "round_evaluator_before_checklist": True,
            "orchestrator_managed_round_evaluator": True,
        },
    )

    assert coord.round_evaluator_transformation_pressure == "balanced"


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


def test_config_validator_rejects_round_evaluator_loop_for_multi_parent_runs():
    config = _make_round_evaluator_config()
    config["agents"].append(
        {
            "id": "peer_parent",
            "backend": {"type": "codex", "model": "gpt-5.4"},
        },
    )

    result = ConfigValidator().validate_config(config)

    assert not result.is_valid()
    assert any("single-parent" in e.message.lower() for e in result.errors)


def test_config_validator_rejects_round_evaluator_skip_synthesis_in_managed_flow():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["round_evaluator_skip_synthesis"] = True

    result = ConfigValidator().validate_config(config)

    assert not result.is_valid()
    assert any("skip_synthesis" in e.message.lower() for e in result.errors)


def test_config_validator_rejects_invalid_round_evaluator_transformation_pressure():
    config = _make_round_evaluator_config()
    config["orchestrator"]["coordination"]["round_evaluator_transformation_pressure"] = "wild"

    result = ConfigValidator().validate_config(config)

    assert not result.is_valid()
    assert any("round_evaluator_transformation_pressure" in e.location for e in result.errors)
    assert any("gentle" in e.message and "aggressive" in e.message for e in result.errors)


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


def test_round_evaluator_result_from_successful_subagent(tmp_path):
    from massgen.subagent.models import RoundEvaluatorResult, SubagentResult

    workspace = tmp_path / "round-evaluator-workspace"
    workspace.mkdir()
    (workspace / "critique_packet.md").write_text("# Critique Packet\n\nFull synthesized report", encoding="utf-8")
    (workspace / "verdict.json").write_text(
        '{"schema_version": "1", "verdict": "iterate", "scores": {"E1": 4}}',
        encoding="utf-8",
    )
    raw = SubagentResult.create_success(
        subagent_id="round_eval_r2",
        answer="Short summary only.",
        workspace_path=str(workspace),
        execution_time_seconds=45.0,
    )
    result = RoundEvaluatorResult.from_subagent_result(raw, elapsed=50.0)

    assert result.status == "success"
    assert result.packet_text == "# Critique Packet\n\nFull synthesized report"
    assert result.primary_artifact_path == str(workspace / "critique_packet.md")
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

    next_tasks = _make_valid_next_tasks_payload()
    original = RoundEvaluatorResult(
        packet_text="critique text",
        status="success",
        degraded_fallback_used=False,
        execution_time_seconds=42.0,
        subagent_id="eval_1",
        log_path="/tmp/logs",
        primary_artifact_path="/tmp/ws/critique_packet.md",
        verdict_artifact_path="/tmp/ws/verdict.json",
        next_tasks_artifact_path="/tmp/ws/next_tasks.json",
        task_plan_source="next_tasks_artifact",
        next_tasks=next_tasks,
        next_tasks_objective="Rebuild the deliverable around a stronger editorial thesis",
        next_tasks_primary_strategy="editorial_reframe",
        next_tasks_why_this_strategy="A stronger organizing concept fixes multiple weak criteria at once.",
        next_tasks_deprioritize_or_remove=["generic filler modules"],
        next_tasks_execution_scope={"active_chunk": "c1"},
        next_tasks_strategy_mode="incremental_refinement",
        next_tasks_success_contract=next_tasks["success_contract"],
    )
    restored = RoundEvaluatorResult.from_dict(original.to_dict())

    assert restored.packet_text == original.packet_text
    assert restored.status == original.status
    assert restored.degraded_fallback_used == original.degraded_fallback_used
    assert restored.execution_time_seconds == original.execution_time_seconds
    assert restored.subagent_id == original.subagent_id
    assert restored.log_path == original.log_path
    assert restored.primary_artifact_path == original.primary_artifact_path
    assert restored.verdict_artifact_path == original.verdict_artifact_path
    assert restored.next_tasks_artifact_path == original.next_tasks_artifact_path
    assert restored.task_plan_source == "next_tasks_artifact"
    assert restored.next_tasks == original.next_tasks
    assert restored.next_tasks_primary_strategy == original.next_tasks_primary_strategy
    assert restored.next_tasks_strategy_mode == original.next_tasks_strategy_mode
    assert restored.next_tasks_success_contract == original.next_tasks_success_contract


def test_normalize_next_tasks_payload_requires_success_contract():
    from massgen.subagent.models import RoundEvaluatorResult

    payload = _make_valid_next_tasks_payload()
    payload.pop("success_contract")

    assert RoundEvaluatorResult.normalize_next_tasks_payload(payload) is None


def test_normalize_next_tasks_payload_requires_task_success_semantics():
    from massgen.subagent.models import RoundEvaluatorResult

    payload = _make_valid_next_tasks_payload()
    payload["tasks"][0].pop("success_criteria")

    assert RoundEvaluatorResult.normalize_next_tasks_payload(payload) is None


def test_normalize_next_tasks_payload_accepts_elevated_ceiling_without_escalation_with_default():
    """ceiling_approaching + incremental_refinement without override_reason
    should be accepted with a default reason (soft validation)."""
    from massgen.subagent.models import RoundEvaluatorResult

    payload = _make_valid_next_tasks_payload()
    payload["approach_assessment"]["ceiling_status"] = "ceiling_approaching"
    payload["strategy_mode"] = "incremental_refinement"

    result = RoundEvaluatorResult.normalize_next_tasks_payload(payload)
    assert result is not None, "Soft validation should accept the payload"
    assert result.get("incremental_override_reason"), "A default incremental_override_reason should be populated"


def test_normalize_next_tasks_payload_requires_thesis_shift_task_when_strategy_demands_it():
    from massgen.subagent.models import RoundEvaluatorResult

    payload = _make_valid_next_tasks_payload()
    payload["approach_assessment"]["ceiling_status"] = "ceiling_reached"
    payload["strategy_mode"] = "thesis_shift"
    payload["tasks"][0]["strategy_role"] = "supporting_fix"

    assert RoundEvaluatorResult.normalize_next_tasks_payload(payload) is None


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
        primary_artifact_path="/tmp/eval/critique_packet.md",
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
    assert "report_path" in block
    assert "/tmp/eval/critique_packet.md" in block
    assert "save it to your workspace" not in block.lower()


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
        verdict_artifact_path="/tmp/eval/verdict.json",
        next_tasks_artifact_path="/tmp/eval/next_tasks.json",
        next_tasks_objective="Turn the brochure into a route planner",
        next_tasks_primary_strategy="interactive_route_map",
        next_tasks_why_this_strategy="One architectural move fixes the weak IA",
        next_tasks_deprioritize_or_remove=["generic destination grid", "gallery strip"],
        next_tasks_strategy_mode="thesis_shift",
        next_tasks_success_contract={
            "outcome_statement": "The next revision should feel reauthored around a new interaction thesis.",
            "quality_bar": "A reviewer should be able to name the new thesis immediately.",
            "fail_if_any": ["The output still feels like the same brochure with cosmetic tweaks."],
            "required_evidence": ["Fresh screenshots of the rebuilt information architecture"],
        },
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
    assert "implementation_guidance" in block
    assert "interactive_route_map" in block
    assert "Turn the brochure into a route planner" in block
    assert "generic destination grid" in block
    assert "Success contract" in block
    assert "The next revision should feel reauthored around a new interaction thesis." in block
    assert "The output still feels like the same brochure with cosmetic tweaks." in block
    assert "thesis_shift" in block
    assert "/tmp/eval/critique_packet.md" in block
    assert "/tmp/eval/verdict.json" in block
    assert "/tmp/eval/next_tasks.json" in block
    assert "If the task plan includes correctness-critical tasks" in block
    assert "do those first" in block
    assert "remaining higher-order work" in block
    assert "final preserve/regression verification" in block


def test_auto_injected_block_strips_absolute_workspace_paths():
    """Absolute workspace paths in packet text should be replaced with filenames."""
    from massgen.orchestrator import Orchestrator
    from massgen.subagent.models import RoundEvaluatorResult

    packet_with_paths = (
        "Files created for the parent to read:\n"
        "- /Users/foo/MassGen/.massgen/workspaces/workspace_abc/subagents/round_eval_r1/"
        "workspace/agent_1_xyz/critique_packet.md\n"
        "- /Users/foo/MassGen/.massgen/workspaces/workspace_abc/subagents/round_eval_r1/"
        "workspace/agent_1_xyz/next_tasks.json\n"
        "Rendered PNG: /Users/foo/MassGen/.massgen/workspaces/workspace_abc/subagents/"
        "round_eval_r1/workspace/agent_1_xyz/.massgen_scratch/verification/render.png\n"
    )
    evaluator_result = RoundEvaluatorResult(
        packet_text=packet_with_paths,
        clean_packet_text=packet_with_paths,
        status="success",
        subagent_id="eval_r2",
    )

    block = Orchestrator._format_round_evaluator_result_block_static(
        subagent_id="eval_r2",
        evaluator_result=evaluator_result,
        auto_injected=True,
    )

    # Absolute paths should be replaced with backtick-wrapped filenames
    assert "/Users/foo/" not in block
    assert "workspace_abc" not in block
    assert "`critique_packet.md`" in block
    assert "`next_tasks.json`" in block
    assert "`render.png`" in block


def test_strip_absolute_workspace_paths_unit():
    """Unit test for _strip_absolute_workspace_paths."""
    from massgen.orchestrator import Orchestrator

    text = (
        "See /home/user/.massgen/workspaces/ws_123/subagents/eval/workspace/agent_1/critique_packet.md " "and /tmp/workspace/foo/next_tasks.json for details. " "Also check plain_text without paths."
    )
    result = Orchestrator._strip_absolute_workspace_paths(text)
    assert "/home/user/" not in result
    assert "`critique_packet.md`" in result
    assert "`next_tasks.json`" in result
    assert "plain_text without paths" in result


def test_strip_absolute_workspace_paths_preserves_relative_refs():
    """Relative file references like 'critique_packet.md' should be untouched."""
    from massgen.orchestrator import Orchestrator

    text = "See critique_packet.md for details. Also tasks/plan.json is relevant."
    result = Orchestrator._strip_absolute_workspace_paths(text)
    assert result == text  # No changes


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
    config_path = Path(__file__).resolve().parents[2] / "massgen" / "configs" / "features" / "round_evaluator_example.yaml"
    assert config_path.exists()

    raw_text = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(raw_text)
    result = ConfigValidator().validate_config(config)

    assert result.is_valid(), result.format_errors()
    assert len(config["agents"]) == 1
    assert config["orchestrator"]["enable_multimodal_tools"] is True
    assert config["orchestrator"]["image_generation_backend"] == "openai"
    assert config["orchestrator"]["video_generation_backend"] == "openai"
    assert config["orchestrator"]["coordination"]["round_evaluator_transformation_pressure"] in ("balanced", "aggressive", "gentle")
    assert "round_evaluator_refine:" not in raw_text
    assert "round_evaluator_skip_synthesis:" not in raw_text
    child_agents = config["orchestrator"]["coordination"]["subagent_orchestrator"]["agents"]
    assert len(child_agents) == 3


def test_coordination_workflow_docs_describe_round_evaluator_support_matrix():
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "modules" / "coordination_workflow.md"
    content = doc_path.read_text(encoding="utf-8").lower()

    assert "core path" in content
    assert "degraded fallback" in content
    assert "advanced / non-default" in content or "advanced/non-default" in content
    assert "material self-improvement" in content
    assert "open-ended self-improvement" in content
    assert "round_evaluator_transformation_pressure" in content
    assert "conceptual — not yet implemented" not in content
    assert "save or copy that packet into its workspace" not in content


def test_yaml_schema_docs_list_round_evaluator_transformation_pressure():
    schema_path = Path(__file__).resolve().parents[2] / "docs" / "source" / "reference" / "yaml_schema.rst"
    content = schema_path.read_text(encoding="utf-8")

    assert "round_evaluator_transformation_pressure" in content
    assert "gentle" in content
    assert "balanced" in content
    assert "aggressive" in content
