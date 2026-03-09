"""Tests for evaluator-driven iteration: structured verdict block parsing and auto-injection."""

from __future__ import annotations

import json

from massgen.subagent.models import RoundEvaluatorResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CRITIQUE = """\
## criteria_interpretation
E1 demands visually stunning design.

## criterion_findings
E1 fails — generic template aesthetic.

## improvement_spec
Replace the hero orb with a cognitive map.

## verification_plan
Run Playwright screenshot at 1440px.

## evidence_gaps
Mobile testing not performed.
"""

SAMPLE_VERDICT_JSON = {
    "verdict": "iterate",
    "scores": {"E1": 4, "E2": 7, "E3": 8, "E4": 3},
    "improvements": [
        {
            "criterion_id": "E1",
            "plan": "Replace generic orb with product-specific cognitive map",
            "sources": ["agent1.1"],
            "impact": "structural",
            "verification": "Screenshot shows distinct product visualization",
        },
        {
            "criterion_id": "E4",
            "plan": "Remove gradient text from all headers except hero",
            "sources": ["agent1.1"],
            "impact": "incremental",
            "verification": "Visual inspection confirms restrained gradient use",
        },
    ],
    "preserve": [
        {
            "criterion_id": "E1",
            "what": "Three-color brand palette (cyan, purple, gold)",
            "source": "agent1.1",
        },
    ],
}

SAMPLE_MINIMAL_VERDICT_JSON = {
    "verdict": "iterate",
    "scores": {"E1": 4, "E2": 7, "E3": 8, "E4": 3},
}

SAMPLE_VERDICT_WITH_OPPORTUNITIES = {
    **SAMPLE_VERDICT_JSON,
    "opportunities": [
        {
            "idea": "Add a real-time collaborative canvas where visitors draw together",
            "rationale": "No answer attempted social interaction — this would transform the page from passive to participatory",
            "impact": "transformative",
            "relates_to": ["E2", "E8"],
        },
        {
            "idea": "Use WebGPU compute shaders for the neural visualization",
            "rationale": "Would enable genuinely novel visual effects impossible with Canvas2D",
            "impact": "structural",
            "relates_to": ["E5"],
        },
    ],
}

SAMPLE_NEXT_TASKS = {
    "schema_version": "1",
    "objective": "Turn the current California brochure into a route-planning experience",
    "primary_strategy": "interactive_route_map",
    "why_this_strategy": "Best addresses weak architecture and California-specific distinctiveness together",
    "deprioritize_or_remove": ["generic destination grid", "repetitive gallery strip"],
    "execution_scope": {"active_chunk": "c1"},
    "tasks": [
        {
            "id": "reframe_ia",
            "description": "Replace brochure IA with route and region planning structure",
            "priority": "high",
            "depends_on": [],
            "chunk": "c1",
            "execution": {"mode": "delegate", "subagent_type": "builder"},
            "verification": "Page is organized around route and region choices",
            "verification_method": "Review rendered page and confirm route-first navigation",
            "metadata": {
                "impact": "transformative",
                "relates_to": ["E3", "E7", "E8"],
                "sources": ["agent3.1"],
                "contract_first": True,
            },
        },
        {
            "id": "route_map",
            "description": "Add a route map explorer that drives trip selection",
            "priority": "high",
            "depends_on": ["reframe_ia"],
            "chunk": "c1",
            "verification": "Interactive route map works and influences content",
            "verification_method": "Run app and verify map interaction in browser",
            "metadata": {
                "impact": "transformative",
                "relates_to": ["E5", "E8"],
                "sources": ["agent2.1", "agent3.1"],
            },
        },
    ],
}

SAMPLE_VERDICT_WITH_NEXT_TASKS = {
    **SAMPLE_VERDICT_WITH_OPPORTUNITIES,
    "next_tasks": SAMPLE_NEXT_TASKS,
}


def _write_round_evaluator_artifacts(
    workspace,
    *,
    critique: str = SAMPLE_CRITIQUE,
    verdict: dict | None = None,
    next_tasks: dict | None = None,
) -> None:
    """Materialize the canonical round-evaluator artifacts in a workspace."""
    (workspace / "critique_packet.md").write_text(critique, encoding="utf-8")
    if verdict is not None:
        verdict_payload = {"schema_version": "1", **verdict}
        (workspace / "verdict.json").write_text(
            json.dumps(verdict_payload, indent=2),
            encoding="utf-8",
        )
    if next_tasks is not None:
        (workspace / "next_tasks.json").write_text(
            json.dumps(next_tasks, indent=2),
            encoding="utf-8",
        )


def _make_packet_with_verdict(critique: str, verdict: dict) -> str:
    """Build a critique packet with a fenced verdict_block."""
    return f"{critique}\n```json verdict_block\n{json.dumps(verdict, indent=2)}\n```\n"


def _make_packet_with_tilde_fence(critique: str, verdict: dict) -> str:
    """Build a critique packet with ~~~ fence style."""
    return f"{critique}\n~~~json verdict_block\n{json.dumps(verdict, indent=2)}\n~~~\n"


# ---------------------------------------------------------------------------
# Verdict block parsing
# ---------------------------------------------------------------------------


class TestParseVerdictBlock:
    """Tests for RoundEvaluatorResult.parse_verdict_block()."""

    def test_parse_verdict_block_iterate(self):
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, SAMPLE_VERDICT_JSON)
        result = RoundEvaluatorResult.parse_verdict_block(packet)

        assert result is not None
        assert result["verdict"] == "iterate"
        assert result["scores"]["E1"] == 4
        assert len(result["improvements"]) == 2
        assert result["improvements"][0]["criterion_id"] == "E1"
        assert result["improvements"][0]["impact"] == "structural"
        assert len(result["preserve"]) == 1

    def test_parse_verdict_block_converged(self):
        verdict = {"verdict": "converged", "scores": {"E1": 9, "E2": 9}, "improvements": [], "preserve": []}
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, verdict)
        result = RoundEvaluatorResult.parse_verdict_block(packet)

        assert result is not None
        assert result["verdict"] == "converged"
        assert result["improvements"] == []

    def test_parse_verdict_block_tilde_fence(self):
        packet = _make_packet_with_tilde_fence(SAMPLE_CRITIQUE, SAMPLE_VERDICT_JSON)
        result = RoundEvaluatorResult.parse_verdict_block(packet)

        assert result is not None
        assert result["verdict"] == "iterate"

    def test_parse_verdict_block_missing_graceful_fallback(self):
        result = RoundEvaluatorResult.parse_verdict_block(SAMPLE_CRITIQUE)
        assert result is None

    def test_parse_verdict_block_malformed_json_fallback(self):
        packet = f"{SAMPLE_CRITIQUE}\n```json verdict_block\n{{not valid json\n```\n"
        result = RoundEvaluatorResult.parse_verdict_block(packet)
        assert result is None

    def test_parse_verdict_block_missing_required_keys(self):
        """A verdict_block missing 'verdict' key should return None."""
        bad_verdict = {"scores": {"E1": 5}}  # missing "verdict"
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, bad_verdict)
        result = RoundEvaluatorResult.parse_verdict_block(packet)
        assert result is None

    def test_parse_verdict_block_includes_next_tasks(self):
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, SAMPLE_VERDICT_WITH_NEXT_TASKS)
        result = RoundEvaluatorResult.parse_verdict_block(packet)

        assert result is not None
        assert result["next_tasks"]["primary_strategy"] == "interactive_route_map"
        assert result["next_tasks"]["execution_scope"]["active_chunk"] == "c1"
        assert len(result["next_tasks"]["tasks"]) == 2
        assert result["next_tasks"]["tasks"][0]["metadata"]["relates_to"] == ["E3", "E7", "E8"]


class TestCleanPacketText:
    """Tests for stripping the verdict block from critique text."""

    def test_verdict_block_stripped_from_critique_text(self):
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, SAMPLE_VERDICT_JSON)
        clean = RoundEvaluatorResult.strip_verdict_block(packet)

        assert "verdict_block" not in clean
        assert "```json" not in clean or "verdict_block" not in clean
        assert "criteria_interpretation" in clean
        assert "improvement_spec" in clean

    def test_strip_preserves_other_code_blocks(self):
        critique_with_code = SAMPLE_CRITIQUE + "\n```python\nprint('hello')\n```\n"
        packet = _make_packet_with_verdict(critique_with_code, SAMPLE_VERDICT_JSON)
        clean = RoundEvaluatorResult.strip_verdict_block(packet)

        assert "print('hello')" in clean
        assert "verdict_block" not in clean


class TestFromSubagentResultWithVerdict:
    """Tests that from_subagent_result populates verdict fields."""

    def test_from_subagent_result_populates_verdict_fields_from_verdict_artifact(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_VERDICT_JSON,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Minimal summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.status == "success"
        assert result.packet_text == SAMPLE_CRITIQUE
        assert result.verdict == "iterate"
        assert result.scores == {"E1": 4, "E2": 7, "E3": 8, "E4": 3}
        assert len(result.improvements) == 2
        assert len(result.preserve) == 1
        assert result.clean_packet_text == SAMPLE_CRITIQUE

    def test_from_subagent_result_uses_packet_artifact_not_answer_text(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            critique="# Artifact packet\n\nAuthoritative critique.",
            verdict=SAMPLE_MINIMAL_VERDICT_JSON,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="# Wrong packet\n\nThis should be ignored.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.status == "success"
        assert result.packet_text == "# Artifact packet\n\nAuthoritative critique."
        assert result.clean_packet_text == "# Artifact packet\n\nAuthoritative critique."

    def test_from_subagent_result_missing_packet_artifact_degrades_even_with_answer(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        (workspace / "verdict.json").write_text(
            json.dumps({"schema_version": "1", **SAMPLE_MINIMAL_VERDICT_JSON}, indent=2),
            encoding="utf-8",
        )

        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer=SAMPLE_CRITIQUE,
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.status == "degraded"
        assert result.packet_text is None
        assert "critique_packet.md" in (result.error or "")

    def test_from_subagent_result_missing_verdict_artifact_keeps_packet_but_disables_structured_metadata(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=None,
        )

        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Concise summary.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.status == "success"
        assert result.packet_text == SAMPLE_CRITIQUE
        assert result.verdict is None
        assert result.scores is None
        assert result.next_tasks is None
        assert result.task_plan_source is None

    def test_from_subagent_result_loads_next_tasks_from_artifact(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_MINIMAL_VERDICT_JSON,
            next_tasks=SAMPLE_NEXT_TASKS,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Minimal summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.next_tasks is not None
        assert result.next_tasks["objective"].startswith("Turn the current California brochure")
        assert result.next_tasks_objective == SAMPLE_NEXT_TASKS["objective"]
        assert result.next_tasks_primary_strategy == SAMPLE_NEXT_TASKS["primary_strategy"]
        assert result.next_tasks_why_this_strategy == SAMPLE_NEXT_TASKS["why_this_strategy"]
        assert result.next_tasks_deprioritize_or_remove == SAMPLE_NEXT_TASKS["deprioritize_or_remove"]
        assert result.next_tasks_execution_scope == SAMPLE_NEXT_TASKS["execution_scope"]
        assert result.primary_artifact_path == str(workspace / "critique_packet.md")
        assert result.next_tasks_artifact_path == str(workspace / "next_tasks.json")
        assert result.task_plan_source == "next_tasks_artifact"

    def test_from_subagent_result_ignores_inline_next_tasks_in_answer(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_MINIMAL_VERDICT_JSON,
        )
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, SAMPLE_VERDICT_WITH_NEXT_TASKS)
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer=packet,
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.next_tasks is None
        assert result.task_plan_source is None

    def test_from_subagent_result_loads_next_tasks_from_nested_final_artifact(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_MINIMAL_VERDICT_JSON,
        )
        nested_final = workspace / ".massgen" / "massgen_logs" / "log_123" / "turn_1" / "final" / "eval_codex" / "workspace"
        nested_final.mkdir(parents=True)
        (nested_final / "next_tasks.json").write_text(
            json.dumps(SAMPLE_NEXT_TASKS, indent=2),
            encoding="utf-8",
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Minimal summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.next_tasks is not None
        assert result.next_tasks["objective"].startswith("Turn the current California brochure")
        assert result.next_tasks_artifact_path == str(nested_final / "next_tasks.json")
        assert result.task_plan_source == "next_tasks_artifact"

    def test_from_subagent_result_ignores_next_tasks_when_verdict_is_converged(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict={"verdict": "converged", "scores": {"E1": 9, "E2": 9}},
            next_tasks=SAMPLE_NEXT_TASKS,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Minimal summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)

        assert result.verdict == "converged"
        assert result.next_tasks is None
        assert result.next_tasks_primary_strategy is None
        assert result.task_plan_source is None


# ---------------------------------------------------------------------------
# Orchestrator auto-injection
# ---------------------------------------------------------------------------


class TestBuildTaskPlanFromVerdict:
    """Tests for _build_task_plan_from_evaluator_verdict."""

    def test_builds_improve_tasks(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4, "E4": 3},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Replace hero orb",
                    "sources": ["agent1.1"],
                    "impact": "structural",
                    "verification": "Screenshot check",
                },
                {
                    "criterion_id": "E4",
                    "plan": "Remove gradient text",
                    "sources": ["agent1.1"],
                    "impact": "incremental",
                    "verification": "Visual check",
                },
            ],
            preserve=[
                {
                    "criterion_id": "E1",
                    "what": "Color palette",
                    "source": "agent1.1",
                },
            ],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        # Should have 2 improve tasks + 1 verify_preserve task
        improve_tasks = [t for t in task_plan if t["type"] == "improve"]
        preserve_tasks = [t for t in task_plan if t["type"] == "verify_preserve"]

        assert len(improve_tasks) == 2
        assert improve_tasks[0]["criterion_id"] == "E1"
        assert improve_tasks[0]["plan"] == "Replace hero orb"
        assert improve_tasks[0]["impact"] == "structural"

        assert len(preserve_tasks) == 1
        assert len(preserve_tasks[0]["items"]) == 1
        assert preserve_tasks[0]["items"][0]["what"] == "Color palette"

    def test_prefers_structured_next_tasks_over_legacy_improvements(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4, "E4": 3},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Replace hero orb",
                    "sources": ["agent1.1"],
                    "impact": "structural",
                    "verification": "Screenshot check",
                },
            ],
            preserve=[],
            next_tasks=SAMPLE_NEXT_TASKS,
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        assert len(task_plan) == 2
        assert all(task.get("type") not in {"improve", "explore"} for task in task_plan)
        assert task_plan[0]["id"] == "reframe_ia"
        assert task_plan[1]["id"] == "route_map"

    def test_structured_next_tasks_still_append_verify_preserve(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            preserve=[
                {
                    "criterion_id": "E2",
                    "what": "Three-color brand palette",
                    "source": "agent1.1",
                },
            ],
            next_tasks=SAMPLE_NEXT_TASKS,
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        assert [task["id"] for task in task_plan[:-1]] == ["reframe_ia", "route_map"]
        assert task_plan[-1]["type"] == "verify_preserve"
        assert task_plan[-1]["items"][0]["what"] == "Three-color brand palette"
        assert task_plan[0]["id"] == "reframe_ia"
        assert task_plan[0]["description"] == "Replace brochure IA with route and region planning structure"
        assert "type" not in task_plan[0]
        assert task_plan[1]["depends_on"] == ["reframe_ia"]

    def test_invalid_structured_next_tasks_falls_back_to_legacy_improvements(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Replace hero orb",
                    "sources": ["agent1.1"],
                    "impact": "structural",
                    "verification": "Screenshot check",
                },
            ],
            preserve=[],
            next_tasks={"tasks": "not-a-list"},
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        assert len(task_plan) == 1
        assert task_plan[0]["type"] == "improve"
        assert task_plan[0]["criterion_id"] == "E1"

    def test_builds_empty_plan_for_converged(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="converged",
            scores={"E1": 9},
            improvements=[],
            preserve=[],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)
        assert task_plan == []

    def test_auto_inject_writes_to_injection_dir(self, tmp_path):
        """When verdict=iterate, tasks should be written to injection dir."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "plan": "Fix hero",
                "criterion": "Visually stunning",
                "impact": "structural",
                "sources": ["agent1.1"],
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        inject_file = tmp_path / "inject_tasks.json"
        assert inject_file.exists()
        tasks = json.loads(inject_file.read_text())
        assert len(tasks) == 1
        assert tasks[0]["criterion_id"] == "E1"


class TestImplementationGuidancePassthrough:
    """Tests that implementation_guidance flows through normalization and injection."""

    def test_normalize_preserves_implementation_guidance(self):
        """implementation_guidance should survive normalize_next_tasks_payload."""
        payload = {
            "schema_version": "1",
            "objective": "Fix the animation system",
            "primary_strategy": "shared_timebase",
            "tasks": [
                {
                    "id": "rebuild_timebase",
                    "description": "Rebuild panels around a single shared time axis",
                    "implementation_guidance": (
                        "Step 1: Define a single time domain [0, 2T]. "
                        "Step 2: Map to shared pixel range x=100..1300. "
                        "The previous approach used per-row animateTransform — "
                        "replace with requestAnimationFrame and a shared clock."
                    ),
                    "priority": "high",
                    "verification": "Identical x-positions correspond to same time",
                    "verification_method": "Render to PNG and inspect alignment",
                },
            ],
        }

        normalized = RoundEvaluatorResult.normalize_next_tasks_payload(payload)

        assert normalized is not None
        assert normalized["tasks"][0]["implementation_guidance"].startswith("Step 1:")

    def test_inject_file_preserves_implementation_guidance(self, tmp_path):
        """implementation_guidance should survive _write_inject_file and reach Task metadata."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )
        from massgen.mcp_tools.planning.planning_dataclasses import TaskPlan

        task_plan = [
            {
                "id": "fix_animation",
                "description": "Replace SMIL with CSS keyframes",
                "implementation_guidance": (
                    "The current code uses animateTransform type=translate. " "Replace with @keyframes that oscillates translateY. " "Use duration proportional to 1/frequency for each harmonic."
                ),
                "priority": "high",
                "verification": "Animation uses CSS keyframes",
                "verification_method": "Grep source for @keyframes",
                "metadata": {"relates_to": ["E3"]},
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        plan = TaskPlan(agent_id="test_agent", require_verification=False)
        added_ids = _check_and_inject_pending_tasks(plan, injection_dir=tmp_path)

        assert len(added_ids) == 1
        task = plan.tasks[0]
        assert "implementation_guidance" in task.metadata
        assert task.metadata["implementation_guidance"].startswith("The current code uses")


class TestVerdictSerialization:
    """Tests for to_dict/from_dict with verdict fields."""

    def test_to_dict_includes_verdict_fields(self):
        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[{"criterion_id": "E1", "plan": "fix"}],
            preserve=[{"what": "palette"}],
            clean_packet_text="clean test",
        )
        d = result.to_dict()
        assert d["verdict"] == "iterate"
        assert d["scores"] == {"E1": 4}
        assert d["improvements"] == [{"criterion_id": "E1", "plan": "fix"}]
        assert d["preserve"] == [{"what": "palette"}]
        assert d["clean_packet_text"] == "clean test"

    def test_from_dict_restores_verdict_fields(self):
        d = {
            "packet_text": "test",
            "status": "success",
            "verdict": "iterate",
            "scores": {"E1": 4},
            "improvements": [{"criterion_id": "E1", "plan": "fix"}],
            "preserve": [{"what": "palette"}],
            "clean_packet_text": "clean test",
        }
        result = RoundEvaluatorResult.from_dict(d)
        assert result.verdict == "iterate"
        assert result.scores == {"E1": 4}
        assert result.improvements == [{"criterion_id": "E1", "plan": "fix"}]
        assert result.clean_packet_text == "clean test"


class TestSynthesisSpecificityGuidance:
    """Tests that synthesis instructions mandate preserving concrete details."""

    def test_synthesize_strategy_preserves_concrete_details(self):
        """The synthesize strategy instruction must tell the presenter to keep specifics."""
        from massgen.message_templates import MessageTemplates

        templates = MessageTemplates(original_message="test task")
        msg = templates.build_final_presentation_message(
            original_task="test task",
            vote_summary="No voting",
            all_answers={"agent1": "answer1", "agent2": "answer2"},
            selected_agent_id="agent1",
            final_answer_strategy="synthesize",
        )
        # Must instruct preservation of concrete implementation details
        assert "concrete" in msg.lower() or "specific" in msg.lower()
        assert "abstract" in msg.lower() or "generalize" in msg.lower()

    def test_subagent_md_has_synthesis_preservation_section(self):
        """SUBAGENT.md must include synthesis guidance for preserving specifics."""
        import pathlib

        subagent_md = pathlib.Path(__file__).parent.parent / "subagent_types" / "round_evaluator" / "SUBAGENT.md"
        content = subagent_md.read_text()
        # Must have a section about synthesis quality
        assert "synthesis" in content.lower()
        # Must instruct preserving concrete implementation details
        assert "concrete" in content.lower()
        # Must warn against abstracting away specifics
        assert "abstract" in content.lower() or "generalize" in content.lower()
        # Must tell the evaluator to base delegation hints on available capabilities
        assert "implementing agent can delegate" in content.lower()
        assert "not on whether you can spawn subagents inside this evaluator run" in content.lower()

    def test_subagent_md_next_tasks_example_is_not_svg_specific(self):
        """The next_tasks example should stay domain-agnostic instead of teaching a route-map SVG fix."""
        import pathlib

        subagent_md = pathlib.Path(__file__).parent.parent / "subagent_types" / "round_evaluator" / "SUBAGENT.md"
        content = subagent_md.read_text()

        assert "route-planning experience" not in content
        assert "SVG path elements with clickable segments" not in content
        assert "canvas overlay with hit-testing on path geometries" not in content
        assert "primary interaction model" in content


# ---------------------------------------------------------------------------
# Multi-evaluator flow (skip synthesis, pass all critiques to parent)
# ---------------------------------------------------------------------------

EVAL_A_CRITIQUE = """\
## criteria_interpretation
E1 demands visually stunning design.

## criterion_findings
E1 fails — hero section uses generic stock gradient.

## improvement_spec
Replace hero with custom 3D product visualization.

```json verdict_block
{"verdict": "iterate", "scores": {"E1": 3, "E2": 7}, "improvements": [{"criterion_id": "E1", "plan": "Add 3D viz"}], "preserve": []}
```
"""

EVAL_B_CRITIQUE = """\
## criteria_interpretation
E2 demands responsive layout.

## criterion_findings
E2 partially met — breakpoint at 768px causes content overflow.

## improvement_spec
Fix CSS grid at tablet breakpoint.

```json verdict_block
{"verdict": "iterate", "scores": {"E1": 5, "E2": 4}, "improvements": [{"criterion_id": "E2", "plan": "Fix 768px breakpoint"}], "preserve": []}
```
"""

EVAL_C_CRITIQUE = """\
## criteria_interpretation
E3 demands accessibility compliance.

## criterion_findings
E3 good — contrast ratios pass WCAG AA.

```json verdict_block
{"verdict": "converged", "scores": {"E1": 7, "E2": 6, "E3": 9}, "improvements": [], "preserve": [{"criterion_id": "E3", "what": "WCAG AA contrast"}]}
```
"""


class TestMultiEvaluatorFlow:
    """Tests for extracting and formatting multiple evaluator answers."""

    def test_format_multi_evaluator_block(self):
        """3 answer texts → formatted with separate <evaluator_packet> tags."""
        from massgen.orchestrator import Orchestrator

        all_answers = {
            "Evaluator A": EVAL_A_CRITIQUE,
            "Evaluator B": EVAL_B_CRITIQUE,
            "Evaluator C": EVAL_C_CRITIQUE,
        }
        block = Orchestrator.format_multi_evaluator_result_block(all_answers)

        # Must contain all 3 evaluator packets
        assert block.count("<evaluator_packet") == 3
        assert block.count("</evaluator_packet>") == 3
        assert 'evaluator="Evaluator A"' in block
        assert 'evaluator="Evaluator B"' in block
        assert 'evaluator="Evaluator C"' in block

        # Verdict blocks should be stripped from the injected text
        assert "verdict_block" not in block

        # But critique content should remain
        assert "hero section uses generic stock gradient" in block
        assert "768px causes content overflow" in block
        assert "contrast ratios pass WCAG AA" in block

        # Should have header
        assert "ROUND EVALUATOR RESULTS" in block
        assert "independent evaluations" in block.lower()

    def test_format_multi_evaluator_block_strips_verdict_blocks(self):
        """Verdict blocks are stripped from each critique before injection."""
        from massgen.orchestrator import Orchestrator

        all_answers = {"Evaluator A": EVAL_A_CRITIQUE}
        block = Orchestrator.format_multi_evaluator_result_block(all_answers)

        # The JSON verdict block should NOT appear in injected text
        assert "```json verdict_block" not in block
        assert '"verdict": "iterate"' not in block

    def test_extract_all_answers_from_status_json(self, tmp_path):
        """Mock status.json + answer files → dict of all answers."""
        from massgen.orchestrator import Orchestrator

        # Create mock log structure:
        # full_logs/eval_agent1/2026-01-01T00:00:00/answer.txt
        # full_logs/eval_agent2/2026-01-01T00:00:01/answer.txt
        # full_logs/eval_agent3/2026-01-01T00:00:02/answer.txt
        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        agents_data = [
            ("eval_agent1", "2026-01-01T00:00:00", EVAL_A_CRITIQUE),
            ("eval_agent2", "2026-01-01T00:00:01", EVAL_B_CRITIQUE),
            ("eval_agent3", "2026-01-01T00:00:02", EVAL_C_CRITIQUE),
        ]

        status_json = {
            "historical_workspaces": [],
        }

        for agent_id, ts, critique in agents_data:
            agent_dir = full_logs / agent_id / ts
            agent_dir.mkdir(parents=True)
            (agent_dir / "answer.txt").write_text(critique)
            status_json["historical_workspaces"].append(
                {
                    "agentId": agent_id,
                    "timestamp": ts,
                    "workspacePath": str(agent_dir / "workspace"),
                },
            )

        # Write status.json
        (full_logs / "status.json").write_text(json.dumps(status_json))

        # Extract all answers
        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )

        assert answers is not None
        assert len(answers) == 3
        # Keys should be anonymized
        assert "Evaluator A" in answers
        assert "Evaluator B" in answers
        assert "Evaluator C" in answers
        # Content should be the actual critiques
        assert "hero section uses generic stock gradient" in list(answers.values())[0]

    def test_fallback_to_single_answer(self, tmp_path):
        """If only 1 answer found → returns dict with single entry."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        agent_dir = full_logs / "eval_agent1" / "2026-01-01T00:00:00"
        agent_dir.mkdir(parents=True)
        (agent_dir / "answer.txt").write_text(EVAL_A_CRITIQUE)

        status_json = {
            "historical_workspaces": [
                {
                    "agentId": "eval_agent1",
                    "timestamp": "2026-01-01T00:00:00",
                    "workspacePath": str(agent_dir / "workspace"),
                },
            ],
        }
        (full_logs / "status.json").write_text(json.dumps(status_json))

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )

        assert answers is not None
        assert len(answers) == 1

    def test_extract_returns_none_on_missing_log(self):
        """If log_path doesn't exist, returns None."""
        from massgen.orchestrator import Orchestrator

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path="/nonexistent/path",
            workspace_path="/nonexistent/workspace",
        )
        assert answers is None

    def test_extract_returns_none_on_no_status_json(self, tmp_path):
        """If status.json doesn't exist, returns None."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        log_path.mkdir()
        (log_path / "full_logs").mkdir()

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )
        assert answers is None

    def test_extract_from_resolved_events_jsonl_path(self, tmp_path):
        """log_path pointing to full_logs/events.jsonl still finds status.json.

        In production, SubagentResult.to_dict() resolves log_path to
        the events.jsonl file. extract_all_evaluator_answers must walk
        up the path to find full_logs/status.json.
        """
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        agents_data = [
            ("eval_codex", "20260307_020803", EVAL_A_CRITIQUE),
            ("eval_claude", "20260307_021215", EVAL_B_CRITIQUE),
            ("eval_gemini", "20260307_020614", EVAL_C_CRITIQUE),
        ]

        status_json = {"historical_workspaces": []}
        for agent_id, ts, critique in agents_data:
            agent_dir = full_logs / agent_id / ts
            agent_dir.mkdir(parents=True)
            (agent_dir / "answer.txt").write_text(critique)
            status_json["historical_workspaces"].append(
                {
                    "agentId": agent_id,
                    "timestamp": ts,
                    "workspacePath": str(agent_dir / "workspace"),
                },
            )

        (full_logs / "status.json").write_text(json.dumps(status_json))
        # Create the events.jsonl file that log_path resolves to
        events_file = full_logs / "events.jsonl"
        events_file.write_text("")

        # Pass the resolved events.jsonl path — simulates real production path
        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(events_file),
            workspace_path=str(tmp_path / "workspace"),
        )

        assert answers is not None
        assert len(answers) == 3
        # Verify anonymization and content
        values = list(answers.values())
        all_text = "\n".join(values)
        assert "hero section uses generic stock gradient" in all_text
        assert "768px causes content overflow" in all_text
        assert "contrast ratios pass WCAG AA" in all_text

    def test_extract_skips_agents_with_empty_answers(self, tmp_path):
        """Agents that wrote empty answer.txt should be excluded."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        # One agent with real content, one empty, one missing
        agents = [
            ("eval_a", "ts1", EVAL_A_CRITIQUE),
            ("eval_b", "ts2", ""),  # empty
            ("eval_c", "ts3", None),  # missing file
        ]

        status_json = {"historical_workspaces": []}
        for agent_id, ts, critique in agents:
            agent_dir = full_logs / agent_id / ts
            agent_dir.mkdir(parents=True)
            if critique is not None:
                (agent_dir / "answer.txt").write_text(critique)
            status_json["historical_workspaces"].append(
                {
                    "agentId": agent_id,
                    "timestamp": ts,
                    "workspacePath": str(agent_dir / "workspace"),
                },
            )

        (full_logs / "status.json").write_text(json.dumps(status_json))

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )

        # Only the agent with real content should appear
        assert answers is not None
        assert len(answers) == 1

    def test_extract_returns_none_on_malformed_status_json(self, tmp_path):
        """Malformed JSON in status.json should return None gracefully."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"
        full_logs.mkdir(parents=True)
        (full_logs / "status.json").write_text("{not valid json")

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )
        assert answers is None

    def test_extract_returns_none_on_empty_historical_workspaces(self, tmp_path):
        """Empty historical_workspaces list should return None."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"
        full_logs.mkdir(parents=True)
        (full_logs / "status.json").write_text(
            json.dumps(
                {
                    "historical_workspaces": [],
                },
            ),
        )

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )
        assert answers is None

    def test_format_multi_evaluator_block_auto_injected_instructions(self):
        """When auto_injected=True, instructions should mention get_task_plan."""
        from massgen.orchestrator import Orchestrator

        all_answers = {
            "Evaluator A": EVAL_A_CRITIQUE,
            "Evaluator B": EVAL_B_CRITIQUE,
        }
        block = Orchestrator.format_multi_evaluator_result_block(
            all_answers,
            auto_injected=True,
        )

        assert "get_task_plan" in block
        assert "auto-injected" in block.lower()
        # Should NOT have the manual checklist instructions
        assert "submit_checklist" not in block or "Do NOT call" in block

    def test_format_multi_evaluator_block_manual_instructions(self):
        """When auto_injected=False, instructions should mention submit_checklist."""
        from massgen.orchestrator import Orchestrator

        all_answers = {"Evaluator A": EVAL_A_CRITIQUE}
        block = Orchestrator.format_multi_evaluator_result_block(
            all_answers,
            auto_injected=False,
        )

        assert "submit_checklist" in block
        assert "independent critiques from multiple evaluators" in block
        # Must instruct synthesis: harshest score, collect all findings
        assert "HARSHEST score" in block
        assert "unified improvement plan" in block

    def test_anonymization_order_is_deterministic(self, tmp_path):
        """Evaluator labels follow insertion order (A, B, C, ...)."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        # Create 5 agents — labels should be A through E
        status_json = {"historical_workspaces": []}
        for i in range(5):
            agent_id = f"eval_{i}"
            ts = f"2026-01-01T00:00:0{i}"
            agent_dir = full_logs / agent_id / ts
            agent_dir.mkdir(parents=True)
            (agent_dir / "answer.txt").write_text(f"Critique from agent {i}")
            status_json["historical_workspaces"].append(
                {
                    "agentId": agent_id,
                    "timestamp": ts,
                    "workspacePath": str(agent_dir / "workspace"),
                },
            )

        (full_logs / "status.json").write_text(json.dumps(status_json))

        answers = Orchestrator.extract_all_evaluator_answers(
            log_path=str(log_path),
            workspace_path=str(tmp_path / "workspace"),
        )

        assert answers is not None
        assert len(answers) == 5
        labels = list(answers.keys())
        assert labels == [
            "Evaluator A",
            "Evaluator B",
            "Evaluator C",
            "Evaluator D",
            "Evaluator E",
        ]

    def test_extract_workspace_paths(self, tmp_path):
        """Workspace paths are found under full_logs/{agentId}/workspace/."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        for agent_id in ["eval_codex", "eval_claude", "eval_gemini"]:
            (full_logs / agent_id / "workspace").mkdir(parents=True)

        # Also create non-directory items that should be ignored
        (full_logs / "status.json").write_text("{}")
        (full_logs / "events.jsonl").write_text("")

        paths = Orchestrator.extract_evaluator_workspace_paths(str(log_path))

        assert len(paths) == 3
        assert all("workspace" in p for p in paths)
        # Sorted alphabetically by agent dir name
        assert "eval_claude" in paths[0]
        assert "eval_codex" in paths[1]
        assert "eval_gemini" in paths[2]

    def test_extract_workspace_paths_from_resolved_events_path(self, tmp_path):
        """Workspace extraction works when log_path is a resolved events.jsonl."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"
        full_logs.mkdir(parents=True)

        for agent_id in ["eval_a", "eval_b"]:
            (full_logs / agent_id / "workspace").mkdir(parents=True)

        events_file = full_logs / "events.jsonl"
        events_file.write_text("")

        paths = Orchestrator.extract_evaluator_workspace_paths(str(events_file))
        assert len(paths) == 2

    def test_extract_workspace_paths_empty_on_missing_dir(self):
        """Returns empty list when log dir doesn't exist."""
        from massgen.orchestrator import Orchestrator

        paths = Orchestrator.extract_evaluator_workspace_paths("/nonexistent")
        assert paths == []

    def test_extract_workspace_paths_skips_agents_without_workspace(self, tmp_path):
        """Agents that lack a workspace/ subdir are excluded."""
        from massgen.orchestrator import Orchestrator

        log_path = tmp_path / "sub_eval"
        full_logs = log_path / "full_logs"

        # eval_a has workspace, eval_b does not
        (full_logs / "eval_a" / "workspace").mkdir(parents=True)
        (full_logs / "eval_b").mkdir(parents=True)
        # eval_b only has timestamp dir with no workspace
        (full_logs / "eval_b" / "20260101").mkdir()

        paths = Orchestrator.extract_evaluator_workspace_paths(str(log_path))
        assert len(paths) == 1
        assert "eval_a" in paths[0]


# ---------------------------------------------------------------------------
# Opportunities parsing and injection
# ---------------------------------------------------------------------------


class TestOpportunitiesParsing:
    """Tests for parsing opportunities from verdict_block."""

    def test_parse_opportunities_from_verdict_block(self):
        """verdict_block with opportunities array should be parsed."""
        packet = _make_packet_with_verdict(SAMPLE_CRITIQUE, SAMPLE_VERDICT_WITH_OPPORTUNITIES)
        result = RoundEvaluatorResult.parse_verdict_block(packet)

        assert result is not None
        assert "opportunities" in result
        assert len(result["opportunities"]) == 2
        assert result["opportunities"][0]["idea"] == "Add a real-time collaborative canvas where visitors draw together"
        assert result["opportunities"][0]["impact"] == "transformative"
        assert result["opportunities"][1]["relates_to"] == ["E5"]

    def test_opportunities_populated_on_result_object_from_verdict_artifact(self, tmp_path):
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_VERDICT_WITH_OPPORTUNITIES,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Short summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)
        assert result.opportunities is not None
        assert len(result.opportunities) == 2
        assert result.opportunities[0]["impact"] == "transformative"

    def test_no_opportunities_when_verdict_artifact_omits_them(self, tmp_path):
        """verdict.json without opportunities should leave field as None."""
        from massgen.subagent.models import SubagentResult

        workspace = tmp_path / "round-evaluator-workspace"
        workspace.mkdir()
        _write_round_evaluator_artifacts(
            workspace,
            verdict=SAMPLE_VERDICT_JSON,
        )
        sub_result = SubagentResult(
            subagent_id="eval-123",
            success=True,
            status="completed",
            answer="Short summary only.",
            workspace_path=str(workspace),
            execution_time_seconds=60.0,
        )

        result = RoundEvaluatorResult.from_subagent_result(sub_result)
        assert result.opportunities is None


class TestTaskPlanOpportunities:
    """Tests for injecting opportunities into task plan."""

    def test_opportunities_produce_explore_tasks(self):
        """Opportunities should become type='explore' entries in task plan."""
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Fix hero",
                    "impact": "structural",
                    "sources": ["agent1.1"],
                    "verification": "Screenshot check",
                },
            ],
            preserve=[],
            opportunities=[
                {
                    "idea": "Add collaborative canvas",
                    "rationale": "Would transform the page",
                    "impact": "transformative",
                    "relates_to": ["E2", "E8"],
                },
            ],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        explore_tasks = [t for t in task_plan if t["type"] == "explore"]
        improve_tasks = [t for t in task_plan if t["type"] == "improve"]

        assert len(explore_tasks) == 1
        assert explore_tasks[0]["idea"] == "Add collaborative canvas"
        assert explore_tasks[0]["impact"] == "transformative"
        assert explore_tasks[0]["relates_to"] == ["E2", "E8"]
        assert len(improve_tasks) == 1

    def test_structured_next_tasks_ignore_opportunities_for_injection(self):
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            preserve=[],
            opportunities=[
                {
                    "idea": "Add collaborative canvas",
                    "rationale": "Would transform the page",
                    "impact": "transformative",
                    "relates_to": ["E2", "E8"],
                },
            ],
            next_tasks=SAMPLE_NEXT_TASKS,
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        assert all(task.get("type") != "explore" for task in task_plan)
        assert [task["id"] for task in task_plan] == ["reframe_ia", "route_map"]

    def test_no_opportunities_no_explore_tasks(self):
        """When opportunities is None/empty, no explore tasks should appear."""
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Fix hero",
                    "impact": "structural",
                    "sources": [],
                    "verification": "check",
                },
            ],
            preserve=[],
            opportunities=None,
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        explore_tasks = [t for t in task_plan if t["type"] == "explore"]
        assert len(explore_tasks) == 0

    def test_structural_improve_tasks_get_builder_advisory(self):
        """Structural/transformative improve tasks should get subagent_name='builder'."""
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4, "E4": 3},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Replace hero orb",
                    "sources": ["agent1.1"],
                    "impact": "structural",
                    "verification": "Screenshot check",
                },
                {
                    "criterion_id": "E4",
                    "plan": "Remove gradient text",
                    "sources": ["agent1.1"],
                    "impact": "incremental",
                    "verification": "Visual check",
                },
                {
                    "criterion_id": "E3",
                    "plan": "Rebuild navigation from scratch",
                    "sources": ["agent1.2"],
                    "impact": "transformative",
                    "verification": "Nav renders correctly",
                },
            ],
            preserve=[],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        improve_tasks = [t for t in task_plan if t["type"] == "improve"]
        assert len(improve_tasks) == 3

        # structural → delegated builder
        assert improve_tasks[0]["execution"] == {"mode": "delegate", "subagent_type": "builder"}
        # incremental → inline
        assert improve_tasks[1]["execution"] == {"mode": "inline"}
        # transformative → delegated builder
        assert improve_tasks[2]["execution"] == {"mode": "delegate", "subagent_type": "builder"}

    def test_explore_tasks_get_builder_execution_hint(self):
        """Explore tasks (opportunities) should get delegated builder execution hints."""
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Fix hero",
                    "impact": "incremental",
                    "sources": [],
                    "verification": "check",
                },
            ],
            preserve=[],
            opportunities=[
                {
                    "idea": "Try WebGPU shaders",
                    "rationale": "Novel visuals",
                    "impact": "transformative",
                    "relates_to": ["E5"],
                },
            ],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        explore_tasks = [t for t in task_plan if t["type"] == "explore"]
        assert len(explore_tasks) == 1
        assert explore_tasks[0]["execution"] == {"mode": "delegate", "subagent_type": "builder"}

    def test_builder_execution_flows_through_inject_format(self, tmp_path):
        """Delegated builder execution should survive conversion to inject format."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "plan": "Replace hero",
                "criterion": "Visually stunning",
                "impact": "structural",
                "sources": ["agent1.1"],
                "execution": {"mode": "delegate", "subagent_type": "builder"},
            },
            {
                "type": "explore",
                "idea": "Try WebGPU",
                "rationale": "Novel",
                "impact": "transformative",
                "relates_to": ["E5"],
                "execution": {"mode": "delegate", "subagent_type": "builder"},
            },
        ]

        injected = _convert_task_plan_to_inject_format(task_plan)

        # improve task should have delegated builder execution
        assert injected[1]["execution"] == {"mode": "delegate", "subagent_type": "builder"}
        assert injected[1]["metadata"]["execution"] == {"mode": "delegate", "subagent_type": "builder"}

        # explore task should have delegated builder execution
        assert injected[0]["execution"] == {"mode": "delegate", "subagent_type": "builder"}
        assert injected[0]["metadata"]["execution"] == {"mode": "delegate", "subagent_type": "builder"}

    def test_explore_tasks_ordered_before_improve_tasks(self):
        """Explore tasks should come before improve tasks in the plan."""
        from massgen.orchestrator import Orchestrator

        result = RoundEvaluatorResult(
            packet_text="test",
            status="success",
            verdict="iterate",
            scores={"E1": 4},
            improvements=[
                {
                    "criterion_id": "E1",
                    "plan": "Fix hero",
                    "impact": "structural",
                    "sources": [],
                    "verification": "check",
                },
            ],
            preserve=[],
            opportunities=[
                {
                    "idea": "Try WebGPU shaders",
                    "rationale": "Novel visuals",
                    "impact": "transformative",
                    "relates_to": ["E5"],
                },
            ],
        )

        task_plan = Orchestrator.build_task_plan_from_evaluator_verdict(result)

        # Find indices
        types = [t["type"] for t in task_plan]
        explore_indices = [i for i, t in enumerate(types) if t == "explore"]
        improve_indices = [i for i, t in enumerate(types) if t == "improve"]

        assert len(explore_indices) > 0
        assert len(improve_indices) > 0
        assert max(explore_indices) < min(improve_indices), "Explore tasks must come before improve tasks"

    def test_plan_compatible_next_tasks_pass_through_inject_conversion(self):
        """Structured next_tasks should survive inject-file conversion unchanged."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        injected = _convert_task_plan_to_inject_format(SAMPLE_NEXT_TASKS["tasks"])

        assert len(injected) == 2
        assert injected[0]["id"] == "reframe_ia"
        assert injected[0]["depends_on"] == []
        assert injected[0]["execution"] == {"mode": "delegate", "subagent_type": "builder"}
        assert injected[0]["metadata"]["injected"] is True
        assert injected[0]["metadata"]["execution"] == {"mode": "delegate", "subagent_type": "builder"}
        assert injected[0]["metadata"]["impact"] == "transformative"
        assert injected[1]["depends_on"] == ["reframe_ia"]
        assert injected[1]["chunk"] == "c1"
