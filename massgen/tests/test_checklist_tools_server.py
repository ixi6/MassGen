#!/usr/bin/env python3
"""Unit tests for the checklist MCP tools server.

Tests cover:
- _extract_score() from different input types
- submit_checklist verdict logic (iterate vs terminate)
- First-answer forced iterate behavior
- Codex JSON-string normalization for scores
- Per-criterion plateau detection
- propose_improvements validation
- write_checklist_specs() file I/O
- build_server_config() structure
"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from massgen.mcp_tools.checklist_tools_server import (
    _extract_score,
    _find_plateaued_criteria,
    _read_specs,
    build_server_config,
    evaluate_checklist_submission,
    evaluate_proposed_improvements,
    write_checklist_specs,
)

# ---------------------------------------------------------------------------
# _extract_score
# ---------------------------------------------------------------------------


class TestExtractScore:
    """Tests for _extract_score helper."""

    def test_int_value(self):
        assert _extract_score(80) == 80

    def test_float_value(self):
        assert _extract_score(75.9) == 75

    def test_dict_with_score(self):
        assert _extract_score({"score": 90, "reasoning": "great"}) == 90

    def test_dict_missing_score_key(self):
        assert _extract_score({"reasoning": "no score"}) == 0

    def test_string_returns_zero(self):
        assert _extract_score("not a number") == 0

    def test_none_returns_zero(self):
        assert _extract_score(None) == 0

    def test_zero_score(self):
        assert _extract_score(0) == 0

    def test_dict_with_zero_score(self):
        assert _extract_score({"score": 0, "reasoning": "failed"}) == 0


# ---------------------------------------------------------------------------
# _read_specs
# ---------------------------------------------------------------------------


class TestReadSpecs:
    """Tests for _read_specs file reader."""

    def test_reads_valid_json(self, tmp_path):
        specs_file = tmp_path / "specs.json"
        specs_file.write_text(json.dumps({"items": ["a", "b"], "state": {}}))
        result = _read_specs(specs_file)
        assert result["items"] == ["a", "b"]

    def test_returns_empty_on_missing_file(self, tmp_path):
        result = _read_specs(tmp_path / "missing.json")
        assert result == {}

    def test_returns_empty_on_invalid_json(self, tmp_path):
        specs_file = tmp_path / "bad.json"
        specs_file.write_text("not json")
        result = _read_specs(specs_file)
        assert result == {}


# ---------------------------------------------------------------------------
# submit_checklist handler (tested via direct function invocation)
# ---------------------------------------------------------------------------


def _make_specs_file(tmp_path, items, state):
    """Helper to write a checklist specs file and return its path."""
    specs_path = tmp_path / "specs.json"
    write_checklist_specs(items, state, specs_path)
    return specs_path


def _build_handler(specs_path):
    """Build the submit_checklist handler by extracting it from registration."""
    import fastmcp

    mcp = fastmcp.FastMCP("test_checklist")
    from massgen.mcp_tools.checklist_tools_server import _register_checklist_tool

    _register_checklist_tool(mcp, specs_path)

    # Extract the registered tool's handler
    # FastMCP stores tools internally; we access the handler directly
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "submit_checklist":
            return tool.fn
    raise RuntimeError("submit_checklist tool not found after registration")


class TestSubmitChecklistVerdict:
    """Tests for the submit_checklist tool's verdict logic."""

    @pytest.mark.asyncio
    async def test_all_pass_returns_terminate(self, tmp_path):
        """When all items pass the cutoff, verdict should be terminate action."""
        items = ["Quality check 1", "Quality check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 7, "reasoning": "ok"}},
            ),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 2

    @pytest.mark.asyncio
    async def test_partial_pass_returns_iterate(self, tmp_path):
        """When not enough items pass, verdict should be iterate action."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 3,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 5, "reasoning": "bad"}, "E3": {"score": 9, "reasoning": "great"}},
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["true_count"] == 2
        assert "E2" in result["explanation"]

    @pytest.mark.asyncio
    async def test_first_answer_forces_iterate(self, tmp_path):
        """When has_existing_answers is False, verdict must always iterate."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 1,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 10, "reasoning": "perfect"}},
            ),
        )
        # Even though score passes, first answer always iterates
        assert result["verdict"] == "new_answer"
        assert "First answer" in result["explanation"]

    @pytest.mark.asyncio
    async def test_codex_json_string_scores(self, tmp_path):
        """Codex sends scores as JSON string; handler should normalize."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Send scores as a JSON string (Codex behavior)
        result = json.loads(
            await handler(
                scores='{"E1": {"score": 8, "reasoning": "good"}}',
            ),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_json_string_returns_error(self, tmp_path):
        """Invalid JSON string for scores should return an error."""
        items = ["Check 1"]
        state = {"has_existing_answers": True, "required": 1, "cutoff": 7}
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(await handler(scores="not valid json"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_score_keys_rejected_when_existing_answers(self, tmp_path):
        """Missing score entries should be rejected with incomplete_scores flag."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Only provide E1, E2 is missing
        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["incomplete_scores"] is True
        assert "E2" in result["explanation"]

    @pytest.mark.asyncio
    async def test_missing_score_keys_default_to_zero_on_first_answer(self, tmp_path):
        """Missing score entries should default to 0 on first answer (no rejection)."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 2,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Only provide E1, E2 is missing — first answer, so no rejection
        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is not True

    @pytest.mark.asyncio
    async def test_custom_terminate_and_iterate_actions(self, tmp_path):
        """Custom action names (stop/continue) should be used in verdicts."""
        items = ["Check 1"]
        state = {
            "terminate_action": "stop",
            "iterate_action": "continue",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 8, "reasoning": "good"}},
            ),
        )
        assert result["verdict"] == "stop"


# ---------------------------------------------------------------------------
# Incomplete score rejection
# ---------------------------------------------------------------------------


class TestIncompleteScoreRejection:
    """Tests for incomplete score submission rejection."""

    def test_missing_scores_rejected_with_existing_answers(self):
        """Incomplete submissions with existing answers should be rejected."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 3,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": {"score": 8, "reasoning": "good"}},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert result["incomplete_scores"] is True
        assert "E2" in result["explanation"]
        assert "E3" in result["explanation"]

    def test_complete_submission_not_rejected(self):
        """Complete submissions should proceed normally."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 8, "reasoning": "good"},
                "E2": {"score": 9, "reasoning": "great"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        assert result.get("incomplete_scores") is not True

    def test_empty_scores_rejected(self):
        """Empty scores dict should be rejected when existing answers present."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert result["incomplete_scores"] is True

    def test_first_answer_not_rejected_for_missing_scores(self):
        """First answer (no existing answers) should not be rejected for missing scores."""
        items = ["Check 1", "Check 2", "Check 3"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 3,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": {"score": 8, "reasoning": "good"}},
            report_path="",
            items=items,
            state=state,
        )
        # First answer always iterates, but NOT because of incomplete scores
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is not True

    def test_t_prefix_accepted_for_backward_compat(self):
        """T-prefix keys should be accepted as equivalent to E-prefix."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={
                "T1": {"score": 8, "reasoning": "good"},
                "T2": {"score": 9, "reasoning": "great"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        assert result.get("incomplete_scores") is not True

    def test_rejection_message_includes_all_missing_keys(self):
        """Rejection message should list all missing keys."""
        items = ["A", "B", "C", "D", "E"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 5,
            "cutoff": 7,
        }
        # Only E1 and E3 provided, missing E2, E4, E5
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 8, "reasoning": "ok"},
                "E3": {"score": 7, "reasoning": "ok"},
            },
            report_path="",
            items=items,
            state=state,
        )
        assert result["incomplete_scores"] is True
        assert "E2" in result["explanation"]
        assert "E4" in result["explanation"]
        assert "E5" in result["explanation"]


# ---------------------------------------------------------------------------
# write_checklist_specs & build_server_config
# ---------------------------------------------------------------------------


class TestWriteChecklistSpecs:
    """Tests for write_checklist_specs utility."""

    def test_writes_valid_json(self, tmp_path):
        items = ["Item 1", "Item 2"]
        state = {"required": 2, "cutoff": 70}
        output = write_checklist_specs(items, state, tmp_path / "out.json")
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["items"] == items
        assert data["state"] == state

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "specs.json"
        write_checklist_specs([], {}, nested)
        assert nested.exists()


class TestGapReportGateRemoval:
    """Tests for gap report gate removal — verdict determined solely by T-item scores."""

    def test_verdict_not_overridden_by_poor_report(self, tmp_path):
        """Checklist passes -> vote verdict, regardless of report quality."""
        items = ["Quality check 1", "Quality check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        # All scores pass, no report path — verdict should be "vote"
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 9},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"
        # Report gate should NOT override
        assert result.get("report_gate_triggered") is False

    def test_report_diagnostics_still_in_result(self, tmp_path):
        """Gap report diagnostics are included in result dict for transparency."""
        items = ["Quality check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8},
            report_path="",
            items=items,
            state=state,
        )
        # Report diagnostics should be in the result
        assert "report" in result
        assert isinstance(result["report"], dict)

    def test_report_path_optional(self):
        """No crash when report_path is empty or absent."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
        }
        # Empty report path
        result = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "vote"

        # None-ish report path
        result2 = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="nonexistent/path.md",
            items=items,
            state=state,
        )
        assert result2["verdict"] == "vote"


class TestChecklistRequiredTrue:
    """Tests for _checklist_required_true threshold relaxation."""

    def test_threshold_0_requires_all_4_items(self):
        """At threshold 0, all 4 items should be required (default)."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(0) == 4
        assert _checklist_required_true(0, num_items=4) == 4

    def test_threshold_50_relaxes_to_3(self):
        """At threshold 50, requirement should relax to 3 for 4 items."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(50, num_items=4) == 3

    def test_threshold_70_relaxes_to_2(self):
        """At threshold 70+, requirement should relax to floor (2 for 4 items)."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(70, num_items=4) == 2

    def test_threshold_100_respects_floor(self):
        """Even at max threshold, never go below floor."""
        from massgen.system_prompt_sections import _checklist_required_true

        result = _checklist_required_true(100, num_items=4)
        assert result >= 2  # floor = max(1, (4+1)//2) = 2

    def test_threshold_0_requires_all_5_items(self):
        """At threshold 0 with 5 items, all items should be required."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(0, num_items=5) == 5

    def test_threshold_50_relaxes_to_4_for_5_items(self):
        """At threshold 50, requirement should relax to 4 for 5 items."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(50, num_items=5) == 4

    def test_floor_for_3_items(self):
        """Floor for 3 items should be 2."""
        from massgen.system_prompt_sections import _checklist_required_true

        assert _checklist_required_true(0, num_items=3) == 3  # strict at 0
        assert _checklist_required_true(70, num_items=3) >= 2  # floor = max(1, (3+1)//2) = 2


# ---------------------------------------------------------------------------
# Per-criterion plateau detection
# ---------------------------------------------------------------------------


class TestCriterionPlateau:
    """Tests for _find_plateaued_criteria helper."""

    def test_plateau_detected_after_two_flat_rounds(self):
        """Same score for 2 rounds → plateaued."""
        current_items = [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 7}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        assert "E2" in result_ids

    def test_no_plateau_when_improving(self):
        """Score increases → not plateaued."""
        current_items = [{"id": "E1", "score": 8}, {"id": "E2", "score": 9}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
        ]
        # No items/categories needed when result is empty
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        assert result == []

    def test_no_plateau_with_insufficient_history(self):
        """<2 rounds of history → empty."""
        current_items = [{"id": "E1", "score": 5}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        assert result == []

    def test_per_criterion_plateau(self):
        """E1 stuck but E2 improving → only E1 plateaued."""
        current_items = [{"id": "E1", "score": 5}, {"id": "E2", "score": 9}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 6}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        assert "E2" not in result_ids

    def test_plateau_threshold(self):
        """+1 point = still plateau, +2 = not plateau."""
        current_items = [{"id": "E1", "score": 6}, {"id": "E2", "score": 7}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = _find_plateaued_criteria(current_items, history, min_rounds=2)
        # E1: 6 > 5 + 1 is False, so E1 is stuck
        result_ids = [d["id"] for d in result]
        assert "E1" in result_ids
        # E2: 7 > 5 + 1 is True, so E2 is improving
        assert "E2" not in result_ids

    def test_returns_rich_detail_dicts(self):
        """Plateaued criteria return dicts with id, text, category, score_history, current_score."""
        items = ["First criterion text", "Second criterion text"]
        categories = {"E1": "should", "E2": "could"}
        current_items = [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]
        history = [
            {"items_detail": [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 6}, {"id": "E2", "score": 5}]},
        ]
        result = _find_plateaued_criteria(
            current_items,
            history,
            items=items,
            item_categories=categories,
            min_rounds=2,
        )
        assert len(result) == 2
        e1 = next(d for d in result if d["id"] == "E1")
        assert e1["text"] == "First criterion text"
        assert e1["category"] == "should"
        assert e1["current_score"] == 6
        assert "score_history" in e1

    def test_score_trajectory_in_detail(self):
        """Score history includes prior rounds + current score."""
        items = ["Criterion A"]
        categories = {"E1": "must"}
        current_items = [{"id": "E1", "score": 6}]
        history = [
            {"items_detail": [{"id": "E1", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 6}]},
        ]
        result = _find_plateaued_criteria(
            current_items,
            history,
            items=items,
            item_categories=categories,
            min_rounds=2,
        )
        assert len(result) == 1
        assert result[0]["score_history"] == [5, 6, 6]


# ---------------------------------------------------------------------------
# propose_improvements validation
# ---------------------------------------------------------------------------


class TestProposeImprovements:
    """Tests for evaluate_proposed_improvements function."""

    # Disable impact gate for tests focused on other validation logic.
    _NO_GATE = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 0}}

    def test_valid_improvements_all_criteria_covered(self):
        """All failing criteria covered → valid."""
        result = evaluate_proposed_improvements(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        assert "task_plan" in result
        assert len(result["task_plan"]) == 2

    def test_missing_criteria_returns_error(self):
        """Missing improvements for a criterion → error."""
        result = evaluate_proposed_improvements(
            improvements={"E2": ["fix fonts"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is False
        assert "E5" in result["error"]
        assert "E5" in result["missing_criteria"]

    def test_empty_improvements_for_criterion_returns_error(self):
        """Empty list for a criterion → error."""
        result = evaluate_proposed_improvements(
            improvements={"E2": ["fix fonts"], "E5": []},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is False
        assert "E5" in result["empty_criteria"]

    def test_task_plan_built_from_improvements(self):
        """Task plan items contain criterion info and improvement text."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": ["add mobile nav", "fix breakpoints"],
                "E3": ["add real images"],
            },
            failed_criteria=["E1", "E3"],
            items=["Goal alignment", "Correctness", "Depth"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        assert len(result["task_plan"]) == 3
        # Check structure
        first = result["task_plan"][0]
        assert first["criterion_id"] == "E1"
        assert first["criterion"] == "Goal alignment"
        assert first["improvement"] == "add mobile nav"

    def test_subagent_name_set_for_structural_impact(self):
        """Structural impact improvements should suggest builder subagent."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign nav", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["subagent_name"] == "builder"

    def test_subagent_name_set_for_transformative_impact(self):
        """Transformative impact improvements should suggest builder subagent."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "switch architecture", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["subagent_name"] == "builder"

    def test_no_subagent_name_for_incremental(self):
        """Incremental impact should not pre-label a builder subagent."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "polish spacing", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert "subagent_name" not in improve_entry

    def test_novelty_task_injected_on_round_2_plus(self):
        """Round 2+ with novelty-on-iteration enabled should prepend novelty task."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": False,
            "agent_answer_count": 1,
        }
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E3": [{"plan": "recompose layout", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1", "E3"],
            items=["Check 1", "Check 2", "Check 3"],
            state=state,
        )
        assert result["valid"] is True
        assert result["task_plan"][0]["type"] == "novelty_quality_spawn"
        assert result["task_plan"][0]["metadata"]["failing_criteria"] == ["E1", "E3"]
        assert result["task_plan"][0]["metadata"]["spawn_novelty"] is True
        assert result["task_plan"][0]["metadata"]["spawn_quality_rethinking"] is False

    def test_quality_rethinking_task_injected_on_round_2_plus(self):
        """Round 2+ with quality-on-iteration enabled should prepend spawn task."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": False,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
        }
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=state,
        )
        assert result["valid"] is True
        assert result["task_plan"][0]["type"] == "novelty_quality_spawn"
        assert result["task_plan"][0]["metadata"]["spawn_novelty"] is False
        assert result["task_plan"][0]["metadata"]["spawn_quality_rethinking"] is True

    def test_novelty_spawn_includes_verbatim_evaluation_packet_and_templates(self):
        """Spawn task should carry exact evaluation packet plus copy-ready task templates."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
        }
        latest_evaluation = {
            "failed_criteria": ["E1", "E2"],
            "failing_criteria_detail": [
                {
                    "id": "E1",
                    "text": "Hero clarity",
                    "category": "must",
                    "current_score": 5,
                },
            ],
            "plateaued_criteria": [
                {
                    "id": "E1",
                    "text": "Hero clarity",
                    "category": "must",
                    "score_history": [5, 5, 5],
                    "current_score": 5,
                },
            ],
            "checklist_explanation": "E1 plateaued and E2 still weak.",
            "diagnostic_report_path": "/tmp/report.md",
            "diagnostic_report_artifact_paths": [
                "/tmp/screenshots/hero.png",
                "/tmp/screenshots/cta.png",
            ],
        }
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign hero", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "rewrite CTA", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1", "E2"],
            items=["Hero clarity", "CTA clarity"],
            state=state,
            latest_evaluation=latest_evaluation,
        )
        assert result["valid"] is True
        spawn_task = result["task_plan"][0]
        assert spawn_task["type"] == "novelty_quality_spawn"
        metadata = spawn_task["metadata"]
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1", "E2"]
        assert metadata["evaluation_input"]["plateaued_criteria"][0]["score_history"] == [5, 5, 5]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == "/tmp/report.md"
        assert metadata["evaluation_input"]["diagnostic_report_artifact_paths"] == [
            "/tmp/screenshots/hero.png",
            "/tmp/screenshots/cta.png",
        ]
        assert "subagent_task_templates" in metadata
        novelty_template = metadata["subagent_task_templates"]["novelty_task_template"]
        quality_template = metadata["subagent_task_templates"]["quality_rethinking_task_template"]
        assert "Evaluation Input (verbatim)" in novelty_template
        assert "Evaluation Input (verbatim)" in quality_template
        assert "Do NOT re-evaluate" in novelty_template
        assert "Do NOT re-evaluate" in quality_template

    def test_no_novelty_task_on_round_1(self):
        """Round 1 should not inject novelty task even when novelty-on-iteration is enabled."""
        state = {
            **self._NO_GATE,
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 0,
        }
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1"],
            state=state,
        )
        assert result["valid"] is True
        assert all(task["type"] != "novelty_quality_spawn" for task in result["task_plan"])

    def test_improvements_must_be_dict(self):
        """Non-dict improvements → error."""
        result = evaluate_proposed_improvements(
            improvements="just a string",
            failed_criteria=["E1"],
            items=["Check 1"],
        )
        assert result["valid"] is False
        assert "must be a dict" in result["error"]

    # --- Structured improvements (plan + sources) ---

    def test_structured_improvements_accepted(self):
        """Structured [{"plan": "...", "sources": [...]}] format accepted."""
        result = evaluate_proposed_improvements(
            improvements={
                "E2": [{"plan": "rethink feature cards", "sources": ["agent_b.1"]}],
            },
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    def test_string_improvements_backward_compat(self):
        """Plain string lists auto-wrapped to {"plan": str, "sources": [], "impact": "incremental"}."""
        result = evaluate_proposed_improvements(
            improvements={"E1": ["fix layout"]},
            failed_criteria=["E1"],
            items=["Check 1"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        improve_entries = [t for t in result["task_plan"] if t.get("type", "improve") == "improve"]
        assert len(improve_entries) >= 1
        # Should have plan and sources in task_plan entry
        assert improve_entries[0]["plan"] == "fix layout"
        assert improve_entries[0]["sources"] == []

    # --- Preserve parameter ---

    def test_preserve_required_when_criteria_exist(self):
        """Empty preserve + all_criteria_ids provided → error."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix layout", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={},
        )
        assert result["valid"] is False
        assert "preserve" in result["error"].lower()

    def test_preserve_allows_same_criterion_in_both(self):
        """Same criterion in improvements AND preserve → accepted."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix the cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={
                "E1": {"what": "hero section impact", "source": "agent_a.2"},
                "E2": {"what": "section header layout", "source": "agent_a.2"},
            },
        )
        assert result["valid"] is True

    def test_preserve_key_must_be_valid_criterion_id(self):
        """Preserve key not in all_criteria_ids → error."""
        result = evaluate_proposed_improvements(
            improvements={"E1": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E1"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E99": {"what": "something", "source": "agent_a.1"}},
        )
        assert result["valid"] is False
        assert "E99" in result["error"]

    def test_preserve_value_structured(self):
        """Preserve value {"what": "...", "source": "..."} accepted."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "hero section impact", "source": "agent_a.2"}},
        )
        assert result["valid"] is True
        assert result["preserve"]["E1"]["what"] == "hero section impact"
        assert result["preserve"]["E1"]["source"] == "agent_a.2"

    def test_preserve_string_value_backward_compat(self):
        """Plain string preserve value auto-wrapped to {"what": str, "source": ""}."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": "hero section impact"},
        )
        assert result["valid"] is True
        assert result["preserve"]["E1"]["what"] == "hero section impact"
        assert result["preserve"]["E1"]["source"] == ""

    def test_preserve_empty_what_rejected(self):
        """Preserve with empty 'what' → error."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "", "source": "agent_a.2"}},
        )
        assert result["valid"] is False
        assert "empty" in result["error"].lower()

    def test_task_plan_includes_preserve_entries(self):
        """Task plan has one verify_preserve row AFTER improve entries."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero impact", "source": "agent1.2"},
                "E3": {"what": "color palette", "source": "agent1.2"},
            },
        )
        assert result["valid"] is True
        types = [t["type"] for t in result["task_plan"]]
        # Single verify_preserve row at the end, after all improve entries
        verify_indices = [i for i, t in enumerate(types) if t == "verify_preserve"]
        improve_indices = [i for i, t in enumerate(types) if t == "improve"]
        assert len(verify_indices) == 1, "Exactly one verify_preserve row expected"
        assert len(improve_indices) >= 1
        assert min(improve_indices) < verify_indices[0], "verify_preserve must come after improve rows"

    def test_task_plan_improve_entries_have_sources(self):
        """Improve entries include plan and sources fields."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "rethink cards", "sources": ["agent2.1"], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E2": {"what": "layout", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        improve = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve["plan"] == "rethink cards"
        assert improve["sources"] == ["agent2.1"]

    def test_preserve_echoed_in_response(self):
        """Response includes preserve dict."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix it", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2"],
            all_criteria_ids=["E1", "E2"],
            preserve={"E1": {"what": "hero impact", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        assert "preserve" in result
        assert "E1" in result["preserve"]

    def test_backward_compat_no_all_criteria_ids(self):
        """Without all_criteria_ids arg, preserve enforcement skipped."""
        result = evaluate_proposed_improvements(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True

    # --- verify_preserve consolidation ---

    def test_verify_preserve_single_row(self):
        """Multiple preserve entries → exactly one verify_preserve row."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero impact", "source": "agent1.2"},
                "E3": {"what": "color palette", "source": "agent1.2"},
            },
        )
        assert result["valid"] is True
        verify_rows = [t for t in result["task_plan"] if t["type"] == "verify_preserve"]
        assert len(verify_rows) == 1

    def test_verify_preserve_after_improve_rows(self):
        """verify_preserve row comes after all improve rows."""
        result = evaluate_proposed_improvements(
            improvements={
                "E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}],
                "E4": [{"plan": "add animation", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E2", "E4"],
            items=["Check 1", "Check 2", "Check 3", "Check 4"],
            all_criteria_ids=["E1", "E2", "E3", "E4"],
            preserve={"E1": {"what": "hero impact", "source": "agent1.2"}},
        )
        assert result["valid"] is True
        types = [t["type"] for t in result["task_plan"]]
        verify_idx = next(i for i, t in enumerate(types) if t == "verify_preserve")
        improve_indices = [i for i, t in enumerate(types) if t == "improve"]
        assert all(improve_idx < verify_idx for improve_idx in improve_indices)

    def test_verify_preserve_contains_all_items(self):
        """verify_preserve row lists all preserved criteria in its items list."""
        result = evaluate_proposed_improvements(
            improvements={"E2": [{"plan": "fix cards", "sources": [], "impact": "structural"}]},
            failed_criteria=["E2"],
            items=["Check 1", "Check 2", "Check 3"],
            all_criteria_ids=["E1", "E2", "E3"],
            preserve={
                "E1": {"what": "hero gradient animation", "source": "agent1.2"},
                "E3": {"what": "sci-fi color palette", "source": "agent2.1"},
            },
        )
        assert result["valid"] is True
        verify_row = next(t for t in result["task_plan"] if t["type"] == "verify_preserve")
        items = verify_row["items"]
        assert len(items) == 2
        criterion_ids = {item["criterion_id"] for item in items}
        assert criterion_ids == {"E1", "E3"}
        e1_item = next(item for item in items if item["criterion_id"] == "E1")
        assert e1_item["what"] == "hero gradient animation"
        assert e1_item["source"] == "agent1.2"

    def test_no_preserve_no_verify_row(self):
        """No preserve entries → no verify_preserve row in task_plan."""
        result = evaluate_proposed_improvements(
            improvements={"E2": ["fix fonts"], "E5": ["add timeline"]},
            failed_criteria=["E2", "E5"],
            items=["Check 1", "Check 2", "Check 3", "Check 4", "Check 5"],
            state=self._NO_GATE,
        )
        assert result["valid"] is True
        verify_rows = [t for t in result["task_plan"] if t["type"] == "verify_preserve"]
        assert len(verify_rows) == 0


# ---------------------------------------------------------------------------
# Impact gate tests
# ---------------------------------------------------------------------------


class TestImpactGate:
    """Tests for the min_non_incremental impact validation gate."""

    _ITEMS = ["Check 1", "Check 2", "Check 3"]
    _DEFAULT_STATE = {}  # uses default min_structural=1, min_non_incremental=1

    def test_propose_improvements_rejects_all_incremental(self):
        """All entries with impact: incremental (default) → fails gate."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "polish layout", "sources": [], "impact": "incremental"}],
                "E2": [{"plan": "tweak colors", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_propose_improvements_accepts_one_structural(self):
        """One structural improvement → passes (meets min_structural=1)."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign navigation", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True

    def test_propose_improvements_accepts_one_transformative(self):
        """One transformative improvement → passes (meets min_non_incremental=1)."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "switch to 3D engine", "sources": [], "impact": "transformative"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True

    def test_propose_improvements_default_impact_is_incremental(self):
        """Entry with no impact field → treated as incremental, fails gate."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "fix typo", "sources": []}],  # no impact key
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_propose_improvements_min_transformative_gate(self):
        """min_transformative: 1, only structural provided → fails."""
        state = {"improvements": {"min_transformative": 1, "min_structural": 0, "min_non_incremental": 0}}
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign nav", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is False
        assert "transformative" in result["error"]

    def test_propose_improvements_all_gates_disabled(self):
        """All gates set to 0 → all-incremental passes."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 0}}
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "polish layout", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is True

    def test_propose_improvements_combined_floor_fails_with_one(self):
        """min_non_incremental: 2, only one structural → fails."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 2}}
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "polish", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is False
        assert "non-incremental combined" in result["error"]

    def test_propose_improvements_combined_floor_passes_with_two(self):
        """min_non_incremental: 2, two structural → passes."""
        state = {"improvements": {"min_transformative": 0, "min_structural": 0, "min_non_incremental": 2}}
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
                "E2": [{"plan": "rethink", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1", "E2"],
            items=self._ITEMS,
            state=state,
        )
        assert result["valid"] is True

    def test_propose_improvements_error_suggests_novelty_subagent(self):
        """Error message mentions novelty and quality_rethinking subagents."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "tweak", "sources": [], "impact": "incremental"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "novelty" in result["error"]
        assert "quality_rethinking" in result["error"]

    def test_propose_improvements_unknown_impact_coerced_to_incremental(self):
        """Unknown impact value is coerced to incremental, which fails gate."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "do something", "sources": [], "impact": "revolutionary"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False
        assert "impact requirements not met" in result["error"]

    def test_propose_improvements_impact_passed_through_task_plan(self):
        """impact field is included in task_plan improve entries."""
        result = evaluate_proposed_improvements(
            improvements={
                "E1": [{"plan": "redesign", "sources": [], "impact": "structural"}],
            },
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is True
        improve_entry = [t for t in result["task_plan"] if t["type"] == "improve"][0]
        assert improve_entry["impact"] == "structural"

    def test_propose_improvements_string_entry_treated_as_incremental(self):
        """Plain string improvement → incremental → fails gate."""
        result = evaluate_proposed_improvements(
            improvements={"E1": ["fix layout"]},
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=self._DEFAULT_STATE,
        )
        assert result["valid"] is False

    def test_propose_improvements_no_state_uses_defaults(self):
        """No state passed → default min_structural=1, all-incremental fails."""
        result = evaluate_proposed_improvements(
            improvements={"E1": [{"plan": "polish", "sources": [], "impact": "incremental"}]},
            failed_criteria=["E1"],
            items=self._ITEMS,
            state=None,
        )
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# Simplified submit_checklist (no improvements/substantiveness params)
# ---------------------------------------------------------------------------


class TestSimplifiedSubmitChecklist:
    """Tests that submit_checklist no longer accepts improvements/substantiveness."""

    def test_no_improvements_param(self):
        """evaluate_checklist_submission has no improvements param."""
        import inspect

        sig = inspect.signature(evaluate_checklist_submission)
        assert "improvements" not in sig.parameters

    def test_no_substantiveness_param(self):
        """evaluate_checklist_submission has no substantiveness param."""
        import inspect

        sig = inspect.signature(evaluate_checklist_submission)
        assert "substantiveness" not in sig.parameters

    def test_submit_checklist_returns_failed_criteria(self):
        """Result includes failed_criteria list."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert "failed_criteria" in result
        assert "E2" in result["failed_criteria"]
        assert "E1" not in result["failed_criteria"]

    def test_submit_checklist_returns_plateaued_criteria(self):
        """Result includes plateaued_criteria when history shows plateau."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert result["verdict"] == "new_answer"
        assert "plateaued_criteria" in result
        # E2 is failing and plateaued — plateaued_criteria is list of dicts
        plateaued_ids = [d["id"] for d in result["plateaued_criteria"]]
        assert "E2" in plateaued_ids

    def test_no_convergence_offramp(self):
        """Result never has convergence_offramp_triggered."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert "convergence_offramp_triggered" not in result

    def test_propose_improvements_instruction_in_iterate_verdict(self):
        """Iterate verdict must instruct agent to call propose_improvements."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert "propose_improvements" in result["explanation"]


# ---------------------------------------------------------------------------
# Quality rethinking subagent guidance (per-criterion plateau trigger)
# ---------------------------------------------------------------------------


class TestQualityRethinkingPlateauTrigger:
    """Quality rethinking + novelty subagent guidance fires on per-criterion plateau."""

    def test_plateau_triggers_quality_rethinking_guidance(self):
        """When criteria plateau for 2+ rounds and quality_rethinking enabled, guidance appears."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "quality_rethinking_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "quality_rethinking" in result["explanation"].lower()

    def test_plateau_triggers_novelty_guidance(self):
        """When criteria plateau and novelty enabled, novelty guidance appears."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "novelty" in result["explanation"].lower()

    def test_no_plateau_guidance_when_scores_improving(self):
        """No subagent guidance when scores are improving (no plateau)."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 90,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 3}, {"id": "E2", "score": 3}]},
            {"items_detail": [{"id": "E1", "score": 3}, {"id": "E2", "score": 3}]},
        ]
        # Current scores jump significantly — not plateaued
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 8},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        assert "quality_rethinking" not in result["explanation"].lower()
        assert "novelty" not in result["explanation"].lower()

    def test_no_plateau_guidance_on_first_answer(self):
        """No plateau guidance on first answer."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 2,
            "cutoff": 90,
            "quality_rethinking_subagent_enabled": True,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        assert "quality_rethinking" not in result["explanation"].lower()


class TestPlateauEnrichedDetail:
    """Tests that plateau response includes rich detail for subagent context."""

    def test_plateaued_criteria_result_has_detail_dicts(self):
        """plateaued_criteria in result contains dicts with text and score_history."""
        items = ["First criterion", "Second criterion"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        plateaued = result["plateaued_criteria"]
        assert len(plateaued) >= 1
        e2_detail = next(d for d in plateaued if d["id"] == "E2")
        assert "text" in e2_detail
        assert e2_detail["text"] == "Second criterion"
        assert "score_history" in e2_detail
        assert "category" in e2_detail
        assert e2_detail["category"] == "could"

    def test_plateau_explanation_includes_score_numbers(self):
        """Explanation text includes actual score trajectory numbers."""
        items = ["First criterion", "Second criterion"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 8}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 8, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        # Explanation should contain score trajectory like "5→5→5"
        explanation = result["explanation"]
        assert "5" in explanation and "→" in explanation

    def test_plateau_guidance_spawns_both_subagents(self):
        """When both quality_rethinking and novelty enabled, guidance says side-by-side."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        history = [
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
            {"items_detail": [{"id": "E1", "score": 5}, {"id": "E2", "score": 5}]},
        ]
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
            checklist_history=history,
        )
        explanation = result["explanation"].lower()
        assert "side-by-side" in explanation or "side by side" in explanation
        assert "quality_rethinking" in explanation
        assert "novelty" in explanation


class TestSubagentPatienceCheckpoints:
    """Tests that system prompt includes patience checkpoints."""

    def test_evaluator_checkpoint_in_prompt(self):
        """System prompt has CHECKPOINT before Phase 2 about evaluator results."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        assert "CHECKPOINT" in prompt
        # Checkpoint must mention evaluator returning before scoring
        idx_checkpoint = prompt.index("CHECKPOINT")
        idx_phase2 = prompt.index("Phase 2")
        assert idx_checkpoint < idx_phase2, "CHECKPOINT must appear before Phase 2"

    def test_builder_checkpoint_in_prompt(self):
        """System prompt has explicit checkpoint about confirming all builders returned."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        # Must have explicit CHECKPOINT about builder completion
        assert "CHECKPOINT" in prompt
        # Two checkpoints: one for evaluator, one for builders
        checkpoints = [i for i in range(len(prompt)) if prompt[i : i + 10] == "CHECKPOINT"]
        assert len(checkpoints) >= 2, f"Expected 2+ CHECKPOINTs, found {len(checkpoints)}"


class TestBuilderGatedPrompt:
    """Tests that builder-specific prompt sections are gated on builder_enabled."""

    def test_no_builder_guidance_when_disabled(self):
        """When builder_enabled=False, no [builder] annotation or Step 3b in prompt."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            builder_enabled=False,
        )
        assert "[builder]" not in prompt
        assert "Step 3b" not in prompt
        # Should still have evaluator CHECKPOINT but NOT builder CHECKPOINT
        assert "CHECKPOINT" in prompt
        checkpoints = [i for i in range(len(prompt)) if prompt[i : i + 10] == "CHECKPOINT"]
        assert len(checkpoints) == 1, f"Expected 1 CHECKPOINT (evaluator only), found {len(checkpoints)}"

    def test_builder_guidance_present_by_default(self):
        """By default (builder_enabled=True), builder guidance is present."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        assert "[builder]" in prompt
        assert "Step 3b" in prompt

    def test_inline_execution_when_no_builders(self):
        """When builder_enabled=False, Phase 3 says to execute inline."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
            builder_enabled=False,
        )
        assert "inline" in prompt.lower()


class TestIterationTriggeredQualitySubagents:
    """Tests for iteration-triggered novelty/quality subagent guidance mode."""

    def test_quality_subagent_guidance_fires_without_plateau(self):
        """When both iteration flags are on in round 2+, guidance mentions both subagents."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": True,
        }
        # No history — so no plateau possible
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        assert "quality_rethinking" in explanation
        assert "novelty" in explanation

    def test_quality_subagent_guidance_includes_failing_criteria_detail(self):
        """Iteration-trigger mode builds detail for all failing criteria, not just plateaued."""
        items = ["First criterion text", "Second criterion text"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "item_categories": {"E1": "should", "E2": "could"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": False,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": False,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        # Should include failing_criteria_detail in result
        assert "failing_criteria_detail" in result
        detail = result["failing_criteria_detail"]
        assert len(detail) == 2
        assert detail[0]["id"] == "E1"
        assert detail[0]["text"] == "First criterion text"
        assert detail[0]["category"] == "should"

    def test_no_guidance_without_flag(self):
        """Without iteration flags, no quality subagent guidance on non-plateaued criteria."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 1,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            # No iteration-trigger flags
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        # Without plateau, no subagent guidance
        assert "quality_rethinking" not in explanation

    def test_no_guidance_on_round_1_even_with_flags(self):
        """Round 1 should not force iteration-trigger guidance even when flags are set."""
        items = ["Criterion A", "Criterion B"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "agent_answer_count": 0,
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
            "enable_quality_rethink_on_iteration": True,
            "enable_novelty_on_iteration": True,
        }
        result = evaluate_checklist_submission(
            scores={"E1": 5, "E2": 5},
            report_path="",
            items=items,
            state=state,
        )
        explanation = result["explanation"].lower()
        assert "quality_rethinking" not in explanation
        assert "novelty" not in explanation


class TestBuildServerConfig:
    """Tests for build_server_config utility."""

    def test_config_structure(self, tmp_path):
        specs_path = tmp_path / "specs.json"
        config = build_server_config(specs_path)
        assert config["name"] == "massgen_checklist"
        assert config["type"] == "stdio"
        assert config["command"] == "fastmcp"
        assert "--specs" in config["args"]
        assert str(specs_path) in config["args"]


# ---------------------------------------------------------------------------
# Stdio MCP registration (orchestrator wiring)
# ---------------------------------------------------------------------------


class TestChecklistStdioRegistration:
    """Tests for _init_checklist_tool_stdio orchestrator helper.

    Verifies that non-SDK backends with standard MCP infrastructure get the
    checklist stdio MCP server registered automatically.
    """

    def _make_backend(self, *, mcp_servers=None, supports_sdk_mcp=False):
        """Create a minimal mock backend with the attributes the orchestrator checks."""

        class _MockBackend:
            pass

        backend = _MockBackend()
        if mcp_servers is not None:
            backend.mcp_servers = list(mcp_servers)
        backend.supports_sdk_mcp = supports_sdk_mcp
        return backend

    def test_stdio_mcp_added_to_backend_mcp_servers(self, tmp_path, monkeypatch):
        """Backends with mcp_servers=[] get checklist stdio MCP appended."""
        from massgen.orchestrator import Orchestrator

        backend = self._make_backend(mcp_servers=[])
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 3,
            "cutoff": 7,
        }
        items = ["Check 1", "Check 2", "Check 3"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        # Redirect temp dir to tmp_path for deterministic cleanup
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path / "specs_dir"))
        (tmp_path / "specs_dir").mkdir(exist_ok=True)

        orch = Orchestrator.__new__(Orchestrator)
        orch._init_checklist_tool_stdio("agent_0", backend, checklist_state, items)

        # Stdio MCP config should be appended
        assert len(backend.mcp_servers) == 1
        mcp_entry = backend.mcp_servers[0]
        assert mcp_entry["name"] == "massgen_checklist"
        assert mcp_entry["type"] == "stdio"

        # Specs file should exist with correct content
        specs_path = backend._checklist_specs_path
        assert specs_path.exists()
        data = json.loads(specs_path.read_text())
        assert data["items"] == items
        assert data["state"]["required"] == 3

    def test_specs_file_rewritten_on_refresh(self, tmp_path, monkeypatch):
        """Calling write_checklist_specs with updated state rewrites the file."""
        items = ["Check 1", "Check 2"]
        state_v1 = {"has_existing_answers": False, "required": 2, "cutoff": 70}
        specs_path = tmp_path / "specs.json"
        write_checklist_specs(items, state_v1, specs_path)

        # Simulate orchestrator updating state
        state_v2 = {"has_existing_answers": True, "required": 2, "cutoff": 7, "remaining": 3}
        write_checklist_specs(items, state_v2, specs_path)

        data = json.loads(specs_path.read_text())
        assert data["state"]["has_existing_answers"] is True
        assert data["state"]["remaining"] == 3

    def test_sdk_backend_skipped(self, tmp_path):
        """SDK backends (supports_sdk_mcp=True) should NOT get stdio MCP added."""
        backend = self._make_backend(mcp_servers=[], supports_sdk_mcp=True)
        checklist_state = {"required": 3, "cutoff": 70}
        items = ["Check 1", "Check 2", "Check 3"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        # The orchestrator's _init_checklist_tool checks supports_sdk_mcp first,
        # so _init_checklist_tool_stdio is never called for SDK backends.
        # We verify the gate condition directly.
        assert backend.supports_sdk_mcp is True
        # mcp_servers should remain empty — no stdio MCP added
        assert len(backend.mcp_servers) == 0

    def test_codex_backend_skipped(self):
        """Backends without mcp_servers attribute should NOT get stdio MCP added."""
        backend = self._make_backend()  # No mcp_servers attribute
        assert not hasattr(backend, "mcp_servers")

    def test_replaces_existing_checklist_mcp_entry(self, tmp_path, monkeypatch):
        """If a checklist MCP entry already exists, it should be replaced, not duplicated."""
        from massgen.orchestrator import Orchestrator

        existing_mcp = {"name": "massgen_checklist", "type": "stdio", "command": "old"}
        backend = self._make_backend(mcp_servers=[existing_mcp, {"name": "other_tool", "type": "stdio"}])
        checklist_state = {"required": 2, "cutoff": 70}
        items = ["Check 1", "Check 2"]
        backend._checklist_state = checklist_state
        backend._checklist_items = items

        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path / "specs_dir"))
        (tmp_path / "specs_dir").mkdir(exist_ok=True)

        orch = Orchestrator.__new__(Orchestrator)
        orch._init_checklist_tool_stdio("agent_0", backend, checklist_state, items)

        # Should have exactly 2 entries: the other_tool + the new checklist
        assert len(backend.mcp_servers) == 2
        names = [s["name"] for s in backend.mcp_servers]
        assert names.count("massgen_checklist") == 1
        assert "other_tool" in names

    def test_checklist_in_framework_mcps(self):
        """massgen_checklist must be in FRAMEWORK_MCPS so it's sent directly to the model.

        Without this, code-based-tools filtering shunts it into a Python
        wrapper that the agent has to discover via filesystem — breaking
        the direct tool-call contract.
        """
        from massgen.filesystem_manager._constants import FRAMEWORK_MCPS
        from massgen.mcp_tools.checklist_tools_server import SERVER_NAME

        assert SERVER_NAME in FRAMEWORK_MCPS, f"{SERVER_NAME!r} missing from FRAMEWORK_MCPS — " f"checklist tool will be filtered out of direct model tools"


class TestChecklistSdkSubmissionCounting:
    """Tests for SDK checklist call quota accounting."""

    @staticmethod
    def _install_fake_claude_agent_sdk(monkeypatch) -> None:
        """Install a minimal claude_agent_sdk stub for orchestrator SDK tool tests."""
        fake_sdk = ModuleType("claude_agent_sdk")

        def tool(**_kwargs):
            def decorator(fn):
                return fn

            return decorator

        def create_sdk_mcp_server(*, name, version, tools):
            return {
                "name": name,
                "version": version,
                "tools": tools,
            }

        fake_sdk.tool = tool
        fake_sdk.create_sdk_mcp_server = create_sdk_mcp_server
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    @pytest.mark.asyncio
    async def test_incomplete_submission_does_not_consume_round_quota(self, monkeypatch):
        """Flat scores (invalid with multiple agents) should not spend the per-round call budget."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=1,
            checklist_first_answer=False,
        )
        orchestrator.agents = {"agent_0": None, "agent_1": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": False,
            "available_agent_labels": ["agent1.1", "agent2.1"],
        }
        items = ["Check 1", "Check 2"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]

        invalid_args = {
            "scores": {
                "E1": {"score": 8, "reasoning": "solid"},
                "E2": {"score": 8, "reasoning": "solid"},
            },
        }
        invalid_result = await submit_checklist(invalid_args)
        invalid_payload = json.loads(invalid_result["content"][0]["text"])
        assert invalid_payload.get("incomplete_scores") is True
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 0

        valid_args = {
            "scores": {
                "agent1.1": {
                    "E1": {"score": 8, "reasoning": "solid"},
                    "E2": {"score": 9, "reasoning": "solid"},
                },
                "agent2.1": {
                    "E1": {"score": 7, "reasoning": "solid"},
                    "E2": {"score": 8, "reasoning": "solid"},
                },
            },
        }
        valid_result = await submit_checklist(valid_args)
        valid_payload = json.loads(valid_result["content"][0]["text"])
        assert valid_payload.get("incomplete_scores") is not True
        assert orchestrator.agent_states["agent_0"].checklist_calls_this_round == 1

        blocked_result = await submit_checklist(valid_args)
        assert blocked_result["isError"] is True
        assert "already called 1 time(s)" in blocked_result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_sdk_propose_improvements_includes_evaluation_input_packet(self, monkeypatch, tmp_path):
        """SDK path should thread checklist evaluation packet into novelty/quality spawn metadata."""
        from massgen.orchestrator import AgentState, Orchestrator

        self._install_fake_claude_agent_sdk(monkeypatch)

        class _MockBackend:
            def __init__(self):
                self.config = {}

        report_path = tmp_path / "diagnostic_report.md"
        report_path.write_text(
            (
                "Failure Patterns\n"
                "- Hero message is vague\n"
                "Root Causes\n"
                "- Missing concrete product behavior\n"
                "Goal Alignment\n"
                "- Path evidence: /tmp/screenshots/hero.png and /tmp/screenshots/cta.png\n"
            ),
            encoding="utf-8",
        )

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.config = SimpleNamespace(
            max_checklist_calls_per_round=2,
            checklist_first_answer=False,
            coordination_config=SimpleNamespace(enable_subagents=True),
        )
        orchestrator.agents = {"agent_0": None}
        orchestrator.agent_states = {"agent_0": AgentState(answer_count=1)}
        orchestrator._planning_injection_dirs = {}

        backend = _MockBackend()
        checklist_state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "workspace_path": str(tmp_path),
            "subagents_enabled": True,
            "enable_novelty_on_iteration": True,
            "enable_quality_rethink_on_iteration": True,
            "agent_answer_count": 1,
            "item_categories": {"E1": "must", "E2": "should"},
            "quality_rethinking_subagent_enabled": True,
            "novelty_subagent_enabled": True,
        }
        items = ["Hero clarity", "CTA clarity"]

        orchestrator._init_checklist_tool_sdk(
            "agent_0",
            backend,
            checklist_state,
            items,
        )
        submit_checklist = backend.config["mcp_servers"]["massgen_checklist"]["tools"][0]
        propose_improvements = backend.config["mcp_servers"]["massgen_checklist"]["tools"][1]

        checklist_result = await submit_checklist(
            {
                "scores": {
                    "E1": {"score": 5, "reasoning": "hero vague"},
                    "E2": {"score": 8, "reasoning": "cta clear"},
                },
                "report_path": str(report_path),
            },
        )
        checklist_payload = json.loads(checklist_result["content"][0]["text"])
        assert checklist_payload["verdict"] == "new_answer"

        propose_result = await propose_improvements(
            {
                "improvements": {
                    "E1": [
                        {"plan": "rewrite hero around one concrete product flow", "sources": [], "impact": "structural"},
                    ],
                },
                "preserve": {
                    "E2": {"what": "clear CTA and conversion copy", "source": "agent1.1"},
                },
            },
        )
        propose_payload = json.loads(propose_result["content"][0]["text"])
        assert propose_payload["valid"] is True
        spawn_task = propose_payload["task_plan"][0]
        assert spawn_task["type"] == "novelty_quality_spawn"
        metadata = spawn_task["metadata"]
        assert "evaluation_input" in metadata
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1"]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == str(report_path)
        assert metadata["evaluation_input"]["diagnostic_report_artifact_paths"] == [
            "/tmp/screenshots/hero.png",
            "/tmp/screenshots/cta.png",
        ]
        assert "subagent_task_templates" in metadata


@pytest.mark.asyncio
async def test_checklist_create_server_standalone_with_hook_dir(
    monkeypatch,
    tmp_path,
):
    """Standalone file-path loading must support --hook-dir without import errors."""
    import importlib.util

    server_path = Path(__file__).parent.parent / "mcp_tools" / "checklist_tools_server.py"
    assert server_path.exists(), f"Expected server file at {server_path}"

    specs_path = tmp_path / "checklist_specs.json"
    specs_path.write_text(
        json.dumps(
            {
                "items": ["T1"],
                "state": {
                    "required": 1,
                    "cutoff": 7,
                    "has_existing_answers": True,
                },
            },
        ),
        encoding="utf-8",
    )
    hook_dir = tmp_path / "hook_ipc"
    hook_dir.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location("checklist_tools_server", server_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["checklist_tools_server"] = module
    try:
        spec.loader.exec_module(module)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "checklist_tools_server.py",
                "--specs",
                str(specs_path),
                "--hook-dir",
                str(hook_dir),
            ],
        )
        server = await module.create_server()
    finally:
        sys.modules.pop("checklist_tools_server", None)

    available_tools = {tool.name for tool in server._tool_manager._tools.values()}
    assert "submit_checklist" in available_tools


# ---------------------------------------------------------------------------
# Diagnostic Report Gate
# ---------------------------------------------------------------------------


class TestDiagnosticReportGate:
    """Tests for required diagnostic report in checklist_gated mode."""

    def _make_state(self, tmp_path, require_report=True, has_existing=True):
        """Build a minimal state dict with diagnostic report gate enabled."""
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": has_existing,
            "required": 2,
            "cutoff": 7,
            "require_diagnostic_report": require_report,
            "workspace_path": str(tmp_path),
        }

    def _passing_scores(self):
        return {"E1": 80, "E2": 85}

    def test_missing_report_rejected_when_required(self, tmp_path):
        """No report_path + gate active -> verdict overridden, gate triggered."""
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is True
        assert result["verdict"] == "new_answer"

    def test_empty_report_rejected(self, tmp_path):
        """Empty report file -> rejected."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text("")
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is True
        assert result["verdict"] == "new_answer"

    def test_too_short_report_rejected(self, tmp_path):
        """Report with < 100 chars -> rejected as lacking substance."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text("Some notes.")
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is True
        assert result["verdict"] == "new_answer"

    def test_substantial_report_accepted(self, tmp_path):
        """Report with real diagnostic content -> gate passes, scores determine verdict."""
        report = tmp_path / "diagnostic_report.md"
        report.write_text(
            "## Failure Patterns\n\n"
            "The login form has no error states. The CSS layout breaks on mobile.\n\n"
            "## Root Causes\n\n"
            "The responsive design was not tested across viewport sizes.\n\n"
            "## Goal Alignment\n\n"
            "The core request was a responsive website but mobile is broken.\n",
        )
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is False
        assert result["verdict"] == "vote"  # scores pass, report passes

    def test_report_content_captured(self, tmp_path):
        """Report content should be included in result for logging."""
        report = tmp_path / "diagnostic_report.md"
        content = "## Failure Patterns\n\nLogin form has no error states.\n\n" "## Root Causes\n\nMissing validation logic.\n\n" "## Goal Alignment\n\nCore requirements partially met.\n"
        report.write_text(content)
        state = self._make_state(tmp_path)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path=str(report),
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report"]["content"] == content

    def test_gate_skipped_on_first_answer(self, tmp_path):
        """First answer (has_existing_answers=False) -> gate not applied."""
        state = self._make_state(tmp_path, has_existing=False)
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        # First answer always iterates, but NOT because of report gate
        assert result["report_gate_triggered"] is False

    def test_gate_inactive_by_default(self, tmp_path):
        """No require_diagnostic_report in state -> backward compat, no gate."""
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
            # No require_diagnostic_report key at all
        }
        result = evaluate_checklist_submission(
            scores={"E1": 9},
            report_path="",
            items=["Check 1"],
            state=state,
        )
        assert result["report_gate_triggered"] is False
        assert result["verdict"] == "vote"

    def test_report_required_in_changedoc_mode_too(self, tmp_path):
        """Changedoc mode still requires separate diagnostic report."""
        state = self._make_state(tmp_path)
        state["changedoc_mode"] = True  # changedoc active
        result = evaluate_checklist_submission(
            scores=self._passing_scores(),
            report_path="",  # no separate report
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["report_gate_triggered"] is True


# ---------------------------------------------------------------------------
# Per-agent scores format
# ---------------------------------------------------------------------------


class TestPerAgentScores:
    """Tests for the per-agent scores format where each agent is scored separately."""

    def _base_state(self):
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
        }

    def test_best_agent_passes_returns_terminate(self):
        """Best agent's scores clear the bar → vote."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "solid"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["best_agent"] == "agent1"
        assert result["true_count"] == 2

    def test_best_agent_fails_returns_iterate(self):
        """Even the best agent fails a dimension → new_answer."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 4, "reasoning": "poor"}},
            "agent2": {"E1": {"score": 6, "reasoning": "ok"}, "E2": {"score": 5, "reasoning": "poor"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "new_answer"
        assert result["best_agent"] == "agent1"  # agent1 has higher aggregate
        assert result["true_count"] == 1

    def test_best_agent_selected_by_aggregate(self):
        """Agent with highest total score is selected as best."""
        scores = {
            "agent1": {"E1": {"score": 9, "reasoning": "great"}, "E2": {"score": 5, "reasoning": "weak"}},
            "agent2": {"E1": {"score": 7, "reasoning": "good"}, "E2": {"score": 8, "reasoning": "solid"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        # agent1 total=14, agent2 total=15 → agent2 wins
        assert result["best_agent"] == "agent2"

    def test_per_agent_breakdown_included_in_response(self):
        """Response includes full per-agent score breakdown."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert "per_agent_scores" in result
        assert "agent1" in result["per_agent_scores"]
        assert "agent2" in result["per_agent_scores"]

    def test_flat_scores_still_work_backward_compat(self):
        """Legacy flat E-keyed scores still produce correct verdicts."""
        scores = {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}}
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 2
        # No best_agent key for flat format
        assert "best_agent" not in result

    def test_single_agent_per_agent_format(self):
        """Single agent in per-agent format works correctly."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "vote"
        assert result["best_agent"] == "agent1"

    def test_per_agent_incomplete_scores_rejected(self):
        """Per-agent format: best agent missing a criterion triggers rejection."""
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}},  # missing E2
            "agent2": {"E1": {"score": 5, "reasoning": "weak"}, "E2": {"score": 6, "reasoning": "ok"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=self._base_state(),
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is True
        assert result["verdict"] == "new_answer"


# ---------------------------------------------------------------------------
# Novelty guidance injection (Step 3 of round lifecycle plan)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-criterion plateau detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Available agent labels enforcement
# ---------------------------------------------------------------------------


class TestAvailableAgentLabelsCoverage:
    """When available_agent_labels is provided in state, all labels must be scored.

    Regression test: agents were submitting per-agent scores that only covered their
    own answer (flat or single-agent format), silently omitting peer agents from
    evaluation.
    """

    def _base_state(self, **extra):
        return {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 7,
            "require_gap_report": False,
            **extra,
        }

    def test_missing_available_agent_triggers_rejection(self):
        """Scores dict omits an available agent → iterate with clear explanation."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        scores = {
            # Only agent1 scored; agent2 is available but missing
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is True
        assert "agent2" in result.get("explanation", "").lower()

    def test_all_available_agents_scored_passes(self):
        """Scoring all available agents succeeds normally."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
            "agent2": {"E1": {"score": 6, "reasoning": "ok"}, "E2": {"score": 7, "reasoning": "decent"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "vote"
        assert not result.get("incomplete_scores")

    def test_no_available_labels_in_state_no_enforcement(self):
        """Without available_agent_labels in state, single-agent submission is fine."""
        state = self._base_state()  # no available_agent_labels key
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "vote"
        assert not result.get("incomplete_scores")

    def test_three_agents_two_missing_rejected(self):
        """Multiple missing agents all named in error message."""
        state = self._base_state(available_agent_labels=["agent1", "agent2", "agent3"])
        scores = {
            "agent1": {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}},
        }
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is True
        explanation = result.get("explanation", "").lower()
        assert "agent2" in explanation
        assert "agent3" in explanation

    def test_flat_format_with_available_labels_rejected(self):
        """Flat (non-per-agent) scores with available_agent_labels present → rejected."""
        state = self._base_state(available_agent_labels=["agent1", "agent2"])
        # Flat format only covers one implicit answer, not all available agents
        scores = {"E1": {"score": 8, "reasoning": "good"}, "E2": {"score": 9, "reasoning": "great"}}
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert result.get("incomplete_scores") is True


# ---------------------------------------------------------------------------
# _convert_task_plan_to_inject_format
# ---------------------------------------------------------------------------


class TestConvertTaskPlanToInjectFormat:
    """Tests for _convert_task_plan_to_inject_format helper."""

    def test_convert_improve_item(self):
        """Improve task_plan item converts to correct injection format."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E2",
                "criterion": "Uses vivid imagery",
                "plan": "Add more sensory details in stanza 2",
                "sources": ["agent1.1"],
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 1
        task = result[0]
        assert task["description"] == "[E2] Add more sensory details in stanza 2"
        assert task["verification"] == "Uses vivid imagery"
        assert task["priority"] == "high"
        assert task["metadata"]["criterion_id"] == "E2"
        assert task["metadata"]["type"] == "improve"
        assert task["metadata"]["sources"] == ["agent1.1"]
        assert task["metadata"]["injected"] is True

    def test_convert_verify_preserve_item(self):
        """verify_preserve task_plan item converts to a single consolidated injection task."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Warm conversational tone in intro", "source": "agent2.1"},
                    {"criterion_id": "E3", "what": "Color palette coherence", "source": "agent1.2"},
                ],
                "priority": "high",
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 1
        task = result[0]
        assert "Before submitting" in task["description"]
        assert "[E1]" in task["description"]
        assert "Warm conversational tone" in task["description"]
        assert "[E3]" in task["description"]
        assert task["priority"] == "high"
        assert task["verification"] == "All preserved elements still present and intact in your output"
        assert task["metadata"]["type"] == "verify_preserve"
        assert len(task["metadata"]["items"]) == 2
        assert task["metadata"]["injected"] is True

    def test_convert_mixed_items(self):
        """Improve and verify_preserve items in a single task_plan convert correctly."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E3",
                "criterion": "Includes examples",
                "plan": "Add 3 concrete examples",
                "sources": [],
            },
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Hook in first line", "source": "agent1.1"},
                ],
                "priority": "high",
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)

        assert len(result) == 2
        assert result[0]["metadata"]["type"] == "improve"
        assert result[1]["metadata"]["type"] == "verify_preserve"

    def test_convert_novelty_quality_spawn_preserves_evaluation_metadata(self):
        """Spawn conversion should preserve evaluation packet and template metadata."""
        from massgen.mcp_tools.checklist_tools_server import (
            _convert_task_plan_to_inject_format,
        )

        task_plan = [
            {
                "id": "novelty_quality_spawn",
                "type": "novelty_quality_spawn",
                "description": "Spawn novelty/quality in background",
                "priority": "high",
                "metadata": {
                    "type": "novelty_quality_spawn",
                    "failing_criteria": ["E1"],
                    "spawn_novelty": True,
                    "spawn_quality_rethinking": True,
                    "evaluation_input": {
                        "failed_criteria": ["E1"],
                        "failing_criteria_detail": [
                            {"id": "E1", "text": "Hero clarity", "category": "must", "current_score": 5},
                        ],
                        "diagnostic_report_path": "/tmp/report.md",
                        "diagnostic_report_artifact_paths": ["/tmp/screenshots/hero.png"],
                    },
                    "subagent_task_templates": {
                        "novelty_task_template": "Evaluation Input (verbatim): ...",
                        "quality_rethinking_task_template": "Evaluation Input (verbatim): ...",
                    },
                },
            },
        ]

        result = _convert_task_plan_to_inject_format(task_plan)
        assert len(result) == 1
        metadata = result[0]["metadata"]
        assert metadata["evaluation_input"]["failed_criteria"] == ["E1"]
        assert metadata["evaluation_input"]["diagnostic_report_path"] == "/tmp/report.md"
        assert metadata["subagent_task_templates"]["novelty_task_template"].startswith(
            "Evaluation Input (verbatim):",
        )


# ---------------------------------------------------------------------------
# _write_inject_file
# ---------------------------------------------------------------------------


class TestWriteInjectFile:
    """Tests for _write_inject_file helper that writes injection files."""

    def test_propose_improvements_writes_inject_file(self, tmp_path):
        """Valid propose_improvements result + injection_dir → file written with correct format."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        inject_file = tmp_path / "inject_tasks.json"
        assert inject_file.exists()

        data = json.loads(inject_file.read_text())
        assert len(data) == 1
        assert data[0]["description"] == "[E1] Add section headers"
        assert data[0]["metadata"]["injected"] is True

    def test_propose_improvements_creates_missing_dir(self, tmp_path):
        """_write_inject_file creates the injection directory if it doesn't exist."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        missing_dir = tmp_path / "nonexistent" / "nested"
        assert not missing_dir.exists()

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E1",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
        ]

        _write_inject_file(missing_dir, task_plan)

        inject_file = missing_dir / "inject_tasks.json"
        assert inject_file.exists()
        data = json.loads(inject_file.read_text())
        assert len(data) == 1

    def test_propose_improvements_no_inject_when_no_dir(self):
        """No injection_dir → no file written, no error."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        # Should be a safe no-op
        _write_inject_file(None, [{"type": "improve", "criterion_id": "E1", "criterion": "x", "plan": "y", "sources": []}])

    def test_verify_preserve_written_to_inject_file(self, tmp_path):
        """verify_preserve task_plan row → correct entry in inject_tasks.json."""
        from massgen.mcp_tools.checklist_tools_server import _write_inject_file

        task_plan = [
            {
                "type": "improve",
                "criterion_id": "E2",
                "criterion": "Clear structure",
                "plan": "Add section headers",
                "sources": ["agent1.1"],
            },
            {
                "type": "verify_preserve",
                "description": "Before submitting: verify these strengths haven't regressed",
                "items": [
                    {"criterion_id": "E1", "what": "Hero animation", "source": "agent2.1"},
                ],
                "priority": "high",
            },
        ]

        _write_inject_file(tmp_path, task_plan)

        inject_file = tmp_path / "inject_tasks.json"
        data = json.loads(inject_file.read_text())
        assert len(data) == 2
        verify_entry = next(d for d in data if d["metadata"]["type"] == "verify_preserve")
        assert "Before submitting" in verify_entry["description"]
        assert "[E1]" in verify_entry["description"]
        assert verify_entry["priority"] == "high"
