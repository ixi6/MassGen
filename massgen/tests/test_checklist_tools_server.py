#!/usr/bin/env python3
"""Unit tests for the checklist MCP tools server.

Tests cover:
- _extract_score() from different input types
- submit_checklist verdict logic (iterate vs terminate)
- First-answer forced iterate behavior
- Codex JSON-string normalization for scores
- Improvement analysis inclusion in explanations
- write_checklist_specs() file I/O
- build_server_config() structure
"""

import json
import sys
from pathlib import Path

import pytest

from massgen.mcp_tools.checklist_tools_server import (
    _extract_score,
    _normalize_substantiveness,
    _read_specs,
    build_server_config,
    evaluate_checklist_submission,
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
                improvements="",
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
                improvements="",
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
                improvements="",
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
                improvements="",
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

        result = json.loads(await handler(scores="not valid json", improvements=""))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_improvements_included_in_iterate_explanation(self, tmp_path):
        """Improvement analysis text should appear in iterate explanations."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 7,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"E1": {"score": 3, "reasoning": "bad"}},
                improvements="Add error handling and validation",
            ),
        )
        assert result["verdict"] == "new_answer"
        assert "Add error handling and validation" in result["explanation"]

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
                improvements="",
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
                improvements="",
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
                improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
            report_path="",
            items=items,
            state=state,
            substantiveness=None,
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
            improvements="",
            report_path="",
            items=items,
            state=state,
            substantiveness=None,
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
            improvements="",
            report_path="",
            items=items,
            state=state,
            substantiveness=None,
        )
        assert result["verdict"] == "vote"

        # None-ish report path
        result2 = evaluate_checklist_submission(
            scores={"E1": 9},
            improvements="",
            report_path="nonexistent/path.md",
            items=items,
            state=state,
            substantiveness=None,
        )
        assert result2["verdict"] == "vote"


# ---------------------------------------------------------------------------
# Substantiveness gating and convergence off-ramp
# ---------------------------------------------------------------------------


class TestSubstantivenessGating:
    """Tests for substantiveness-based convergence control."""

    @pytest.mark.asyncio
    async def test_substantiveness_required_forces_iterate_when_missing(self, tmp_path):
        """When substantiveness is required, missing payload should force iterate."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 10, "reasoning": "strong"},
                    "E2": {"score": 10, "reasoning": "strong"},
                    "E3": {"score": 10, "reasoning": "strong"},
                    "E4": {"score": 10, "reasoning": "strong"},
                },
                improvements="No critical gaps",
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["substantiveness_gate_triggered"] is True
        assert "Substantiveness" in result["explanation"]

    @pytest.mark.asyncio
    async def test_convergence_offramp_terminates_incremental_only_tail_failures(self, tmp_path):
        """Allow natural termination when only T4 fails and no substantive plan remains."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 9, "reasoning": "core quality strong"},
                    "E2": {"score": 9, "reasoning": "core quality strong"},
                    "E3": {"score": 9, "reasoning": "core quality strong"},
                    "E4": {"score": 6, "reasoning": "ambition limited"},
                },
                improvements="Only polish-level tweaks remain",
                substantiveness={
                    "transformative": [],
                    "structural": [],
                    "incremental": ["fix spacing", "adjust colors"],
                    "decision_space_exhausted": True,
                    "notes": "No meaningful structural moves left",
                },
            ),
        )
        assert result["verdict"] == "vote"
        assert result["convergence_offramp_triggered"] is True
        assert "Convergence off-ramp activated" in result["explanation"]

    @pytest.mark.asyncio
    async def test_convergence_offramp_does_not_trigger_with_structural_plan(self, tmp_path):
        """Do not terminate early when a structural plan still exists."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 9, "reasoning": "core quality strong"},
                    "E2": {"score": 9, "reasoning": "core quality strong"},
                    "E3": {"score": 9, "reasoning": "core quality strong"},
                    "E4": {"score": 6, "reasoning": "ambition limited"},
                },
                improvements="Need one major architecture revision",
                substantiveness={
                    "transformative": [],
                    "structural": ["redesign navigation architecture"],
                    "incremental": [],
                    "decision_space_exhausted": False,
                    "notes": "A structural redesign remains feasible",
                },
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["convergence_offramp_triggered"] is False

    @pytest.mark.asyncio
    async def test_changedoc_offramp_does_not_treat_t3_as_tail_failure(self, tmp_path):
        """In changedoc mode, failing T3 (traceability) should block off-ramp termination."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_gap_report": False,
            "require_substantiveness": True,
            "changedoc_mode": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 9, "reasoning": "deliverable strong"},
                    "E2": {"score": 9, "reasoning": "gaps addressed"},
                    "E3": {"score": 6, "reasoning": "traceability gaps remain"},
                    "E4": {"score": 6, "reasoning": "ambition limited"},
                },
                improvements="Need to fix traceability mappings",
                substantiveness={
                    "transformative": [],
                    "structural": [],
                    "incremental": ["fix traceability"],
                    "decision_space_exhausted": True,
                    "notes": "No architectural changes left",
                },
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["convergence_offramp_triggered"] is False

    @pytest.mark.asyncio
    async def test_changedoc_offramp_can_trigger_when_only_t4_fails(self, tmp_path):
        """In changedoc mode, off-ramp may trigger when T1-T3 pass and only T4 fails."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_gap_report": False,
            "require_substantiveness": True,
            "changedoc_mode": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 9, "reasoning": "deliverable strong"},
                    "E2": {"score": 9, "reasoning": "gaps addressed"},
                    "E3": {"score": 9, "reasoning": "traceability is complete"},
                    "E4": {"score": 6, "reasoning": "ambition limited"},
                },
                improvements="No substantive ambition paths remain",
                substantiveness={
                    "transformative": [],
                    "structural": [],
                    "incremental": ["minor polish"],
                    "decision_space_exhausted": True,
                    "notes": "Only polish options remain",
                },
            ),
        )
        assert result["verdict"] == "vote"
        assert result["convergence_offramp_triggered"] is True

    @pytest.mark.asyncio
    async def test_stretch_criteria_guidance_when_exhausted(self, tmp_path):
        """When stretch criteria fail and decision space is exhausted, give specific guidance."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 9,
            "require_gap_report": False,
            "require_substantiveness": True,
            "item_categories": {"E1": "core", "E2": "core", "E3": "core", "E4": "stretch"},
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 8, "reasoning": "decent coverage"},
                    "E2": {"score": 8, "reasoning": "decent rationale"},
                    "E3": {"score": 9, "reasoning": "good traceability"},
                    "E4": {"score": 4, "reasoning": "no genuine ambition"},
                },
                improvements="Add attribution and fallback UX",
                substantiveness={
                    "transformative": [],
                    "structural": [],
                    "incremental": ["add attribution", "fallback UX", "polish"],
                    "decision_space_exhausted": True,
                    "notes": "Only incremental polish remains",
                },
            ),
        )
        assert result["verdict"] == "new_answer"
        # Should contain stretch-specific guidance
        assert "E4 (stretch crit" in result["explanation"]
        assert "stretch-quality deficit" in result["explanation"]

    @pytest.mark.asyncio
    async def test_stretch_criteria_guidance_when_substantive_plan_exists(self, tmp_path):
        """When stretch criteria fail but structural work remains, give different guidance."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 9,
            "require_gap_report": False,
            "require_substantiveness": True,
            "item_categories": {"E1": "core", "E2": "core", "E3": "core", "E4": "stretch"},
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "E1": {"score": 8, "reasoning": "decent coverage"},
                    "E2": {"score": 8, "reasoning": "decent rationale"},
                    "E3": {"score": 9, "reasoning": "good traceability"},
                    "E4": {"score": 4, "reasoning": "no genuine ambition"},
                },
                improvements="Add interactive timeline and fallback UX",
                substantiveness={
                    "transformative": [],
                    "structural": ["add interactive timeline"],
                    "incremental": ["fallback UX", "polish"],
                    "decision_space_exhausted": False,
                    "notes": "Interactive timeline would be structural",
                },
            ),
        )
        assert result["verdict"] == "new_answer"
        # Should still get stretch guidance but the non-exhausted variant
        assert "E4 (stretch crit" in result["explanation"]
        assert "care beyond correctness" in result["explanation"]


class TestIterateVerdictBreadth:
    """Tests that iterate verdict encourages implementing ALL identified improvements."""

    def test_iterate_verdict_says_implement_all(self, tmp_path):
        """When iterating, verdict must tell agent to implement ALL improvements, not just one."""
        items = ["Coverage", "Quality", "Polish", "Depth"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "substantiveness_eval": {"required": True, "valid": True, "has_substantive_plan": True},
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps in coverage"},
                "E2": {"score": 5, "reasoning": "weak quality"},
                "E3": {"score": 7, "reasoning": "decent polish"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Add interactive timeline, redesign navigation, add real data sources",
            report_path="",
            items=items,
            state=state,
            substantiveness={
                "transformative": [],
                "structural": ["interactive timeline", "redesign navigation", "real data sources"],
                "incremental": ["minor polish"],
                "decision_space_exhausted": False,
                "notes": "Three structural improvements identified",
            },
        )
        assert result["verdict"] == "new_answer"
        explanation_lower = result["explanation"].lower()
        normalized = " ".join(explanation_lower.split())
        # Must tell agent to implement all improvements, not just pick one
        assert "implement all" in normalized or "address all" in normalized or "all identified" in normalized


# ---------------------------------------------------------------------------
# Substantiveness list format and backward compatibility
# ---------------------------------------------------------------------------


class TestSubstantivenessListFormat:
    """Tests for structured list-based substantiveness format."""

    def test_list_format_derives_counts_from_lengths(self):
        """List format should derive counts from len() of each list."""
        state = {"require_substantiveness": True}
        result = _normalize_substantiveness(
            {
                "transformative": ["rewrite nav as SPA router"],
                "structural": ["add timeline", "add search"],
                "incremental": ["fix typos", "adjust colors", "add alt text"],
                "decision_space_exhausted": False,
                "notes": "test",
            },
            state,
        )
        assert result["transformative_count"] == 1
        assert result["structural_count"] == 2
        assert result["incremental_count"] == 3
        assert result["has_substantive_plan"] is True
        assert result["incremental_only"] is False

    def test_list_format_stores_items(self):
        """List format should store the actual item lists in result."""
        state = {"require_substantiveness": True}
        result = _normalize_substantiveness(
            {
                "transformative": ["rewrite as SPA"],
                "structural": ["add caching layer"],
                "incremental": ["fix typos"],
                "decision_space_exhausted": False,
            },
            state,
        )
        assert result["transformative_items"] == ["rewrite as SPA"]
        assert result["structural_items"] == ["add caching layer"]
        assert result["incremental_items"] == ["fix typos"]

    def test_legacy_count_format_still_works(self):
        """Old count-based format should still be accepted for backward compat."""
        state = {"require_substantiveness": True}
        result = _normalize_substantiveness(
            {
                "transformative_count": 1,
                "structural_count": 2,
                "incremental_count": 3,
                "decision_space_exhausted": False,
                "notes": "legacy",
            },
            state,
        )
        assert result["transformative_count"] == 1
        assert result["structural_count"] == 2
        assert result["incremental_count"] == 3
        assert result["has_substantive_plan"] is True
        # Legacy format should have empty item lists
        assert result["transformative_items"] == []
        assert result["structural_items"] == []
        assert result["incremental_items"] == []

    def test_empty_lists_mean_zero_counts(self):
        """Empty lists should produce zero counts."""
        state = {"require_substantiveness": True}
        result = _normalize_substantiveness(
            {
                "transformative": [],
                "structural": [],
                "incremental": [],
                "decision_space_exhausted": True,
            },
            state,
        )
        assert result["transformative_count"] == 0
        assert result["structural_count"] == 0
        assert result["incremental_count"] == 0
        assert result["has_substantive_plan"] is False


class TestVerdictEchoWithItems:
    """Tests for echoing specific item names in iterate verdict."""

    def test_iterate_verdict_echoes_structural_items(self):
        """When iterating with structural items, echo them by name."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Various improvements needed",
            report_path="",
            items=items,
            state=state,
            substantiveness={
                "transformative": [],
                "structural": ["add interactive timeline", "redesign navigation"],
                "incremental": ["fix typos"],
                "decision_space_exhausted": False,
                "notes": "Two structural changes",
            },
        )
        assert result["verdict"] == "new_answer"
        # Must echo specific structural items by name
        assert "add interactive timeline" in result["explanation"]
        assert "redesign navigation" in result["explanation"]

    def test_iterate_verdict_echoes_transformative_items(self):
        """When iterating with transformative items, echo them by name."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Major rework needed",
            report_path="",
            items=items,
            state=state,
            substantiveness={
                "transformative": ["rewrite as event-driven architecture"],
                "structural": [],
                "incremental": [],
                "decision_space_exhausted": False,
                "notes": "One transformative change",
            },
        )
        assert result["verdict"] == "new_answer"
        assert "rewrite as event-driven architecture" in result["explanation"]


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


class TestTaskPlanCommitmentTracking:
    """Tests for task plan commitment tracking in iterate verdicts."""

    def test_iterate_verdict_instructs_task_plan_logging(self):
        """When iterating with structural items, verdict must instruct agent to log them as tasks."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Various improvements needed",
            report_path="",
            items=items,
            state=state,
            substantiveness={
                "transformative": [],
                "structural": ["add interactive timeline", "redesign navigation"],
                "incremental": ["fix typos"],
                "decision_space_exhausted": False,
            },
        )
        assert result["verdict"] == "new_answer"
        explanation = result["explanation"].lower()
        # Must instruct the agent to log committed items in its task plan
        assert "task plan" in explanation or "task list" in explanation

    def test_iterate_verdict_no_task_plan_when_no_items(self):
        """When iterating with legacy count format (no item lists), no task plan instruction."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Various improvements needed",
            report_path="",
            items=items,
            state=state,
            substantiveness={
                "transformative_count": 0,
                "structural_count": 2,
                "incremental_count": 1,
                "decision_space_exhausted": False,
            },
        )
        assert result["verdict"] == "new_answer"
        # Legacy format has no specific items to track — no task plan instruction
        explanation = result["explanation"].lower()
        assert "task plan" not in explanation and "task list" not in explanation

    def test_system_prompt_iterate_guidance_mentions_task_plan(self):
        """System prompt iterate guidance must mention logging committed items as tasks."""
        from massgen.system_prompt_sections import (
            _CHECKLIST_ITEMS_CHANGEDOC,
            _build_checklist_gated_decision,
        )

        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        lower = decision.lower()
        assert "task plan" in lower or "task list" in lower


class TestNoveltySubagentGuidance:
    """Tests for novelty subagent spawning guidance in iterate verdicts."""

    def _make_t0_state(self, **overrides):
        """Helper: state dict for T=0 iterate scenario."""
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
            "novelty_subagent_enabled": True,
        }
        state.update(overrides)
        return state

    def _t0_substantiveness(self):
        """Helper: substantiveness with T=0."""
        return {
            "transformative": [],
            "structural": [],
            "incremental": ["fix spacing", "adjust colors"],
            "decision_space_exhausted": False,
            "notes": "Only incremental work identified",
        }

    def test_novelty_guidance_when_t0_and_has_existing_answers(self):
        """When T=0, iterate verdict, novelty enabled, and has_existing_answers: explanation contains novelty subagent guidance."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Minor polish and formatting",
            report_path="",
            items=items,
            state=self._make_t0_state(),
            substantiveness=self._t0_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        explanation_lower = result["explanation"].lower()
        assert "novelty" in explanation_lower
        assert "subagent" in explanation_lower
        assert "background" in explanation_lower

    def test_no_novelty_guidance_when_transformative_exists(self):
        """When T>0, no novelty subagent guidance needed (agent already has transformative ideas)."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Major rework needed",
            report_path="",
            items=items,
            state=self._make_t0_state(),
            substantiveness={
                "transformative": ["rewrite as event-driven architecture"],
                "structural": [],
                "incremental": [],
                "decision_space_exhausted": False,
                "notes": "One transformative change",
            },
        )
        assert result["verdict"] == "new_answer"
        explanation_lower = result["explanation"].lower()
        assert "novelty" not in explanation_lower or "subagent" not in explanation_lower

    def test_no_novelty_guidance_on_first_answer(self):
        """When first answer (no existing), no novelty subagent guidance."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 2,
            "cutoff": 7,
            "novelty_subagent_enabled": True,
        }
        result = evaluate_checklist_submission(
            scores={"E1": {"score": 10, "reasoning": "perfect"}, "E2": {"score": 10, "reasoning": "perfect"}},
            improvements="",
            report_path="",
            items=items,
            state=state,
        )
        assert result["verdict"] == "new_answer"
        assert "novelty" not in result["explanation"].lower()

    def test_no_novelty_guidance_when_disabled(self):
        """When novelty_subagent_enabled=False, novelty guidance is suppressed even with T=0."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Minor polish",
            report_path="",
            items=items,
            state=self._make_t0_state(novelty_subagent_enabled=False),
            substantiveness=self._t0_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "novelty" not in result["explanation"].lower()

    def test_no_novelty_guidance_when_key_absent(self):
        """When novelty_subagent_enabled absent from state, default OFF (safe)."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
            # No novelty_subagent_enabled key
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Minor polish",
            report_path="",
            items=items,
            state=state,
            substantiveness=self._t0_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "novelty" not in result["explanation"].lower()


class TestBuilderSubagentGuidance:
    """Builder subagent guidance in verdict text.

    The builder fires when transformative items are present (T>0) AND builder
    is enabled — complementary to novelty/critic which fire when T==0.
    """

    def _make_state(self, **overrides):
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
            "require_substantiveness": True,
            "builder_subagent_enabled": True,
        }
        state.update(overrides)
        return state

    def _transformative_substantiveness(self):
        return {
            "transformative": ["rebuild layout as era-based chapters", "replace card grids with full-bleed sections"],
            "structural": [],
            "incremental": [],
            "decision_space_exhausted": False,
            "notes": "Two transformative changes identified",
        }

    def _incremental_only_substantiveness(self):
        return {
            "transformative": [],
            "structural": ["add timeline connector nodes"],
            "incremental": ["fix contrast", "increase font size"],
            "decision_space_exhausted": False,
            "notes": "Only incremental/structural work",
        }

    def test_builder_guidance_when_transformative_and_enabled(self):
        """Builder guidance appears when transformative items present + builder enabled."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Rebuild layout and replace card grids",
            report_path="",
            items=items,
            state=self._make_state(),
            substantiveness=self._transformative_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        explanation_lower = result["explanation"].lower()
        assert "builder" in explanation_lower
        assert "subagent" in explanation_lower
        assert "background" in explanation_lower

    def test_no_builder_guidance_when_disabled(self):
        """No builder guidance when builder_subagent_enabled=False."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Rebuild layout",
            report_path="",
            items=items,
            state=self._make_state(builder_subagent_enabled=False),
            substantiveness=self._transformative_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "builder" not in result["explanation"].lower()

    def test_no_builder_guidance_when_no_transformative_items(self):
        """No builder guidance when there are no transformative items (only structural/incremental)."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Fix some issues",
            report_path="",
            items=items,
            state=self._make_state(),
            substantiveness=self._incremental_only_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "builder" not in result["explanation"].lower()

    def test_no_builder_guidance_on_first_answer(self):
        """No builder guidance on first answer (has_existing_answers=False)."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Rebuild everything",
            report_path="",
            items=items,
            state=self._make_state(has_existing_answers=False),
            substantiveness=self._transformative_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "builder" not in result["explanation"].lower()

    def test_no_builder_guidance_when_key_absent(self):
        """When builder_subagent_enabled absent from state, default OFF (safe)."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 7,
        }
        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Rebuild layout",
            report_path="",
            items=items,
            state=state,
            substantiveness=self._transformative_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        assert "builder" not in result["explanation"].lower()

    def test_builder_and_novelty_are_mutually_exclusive(self):
        """Builder fires on T>0; novelty fires on T==0 — they don't appear together."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = self._make_state(novelty_subagent_enabled=True)

        result = evaluate_checklist_submission(
            scores={
                "E1": {"score": 6, "reasoning": "gaps"},
                "E2": {"score": 5, "reasoning": "weak"},
                "E3": {"score": 7, "reasoning": "ok"},
                "E4": {"score": 5, "reasoning": "shallow"},
            },
            improvements="Rebuild layout",
            report_path="",
            items=items,
            state=state,
            substantiveness=self._transformative_substantiveness(),
        )
        assert result["verdict"] == "new_answer"
        explanation_lower = result["explanation"].lower()
        # Builder fires (T>0)
        assert "builder" in explanation_lower
        # Novelty does NOT fire (T>0, so no novelty guidance needed)
        assert "novelty" not in explanation_lower


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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="E2 is weak across all agents",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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
            improvements="",
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


def _make_low_score_state(extra=None):
    """State that triggers T=0 plateau (no transformative changes identified)."""
    state = {
        "terminate_action": "vote",
        "iterate_action": "new_answer",
        "has_existing_answers": True,
        "required": 2,
        "cutoff": 90,  # high cutoff so scores fail → iterate verdict
    }
    if extra:
        state.update(extra)
    return state


def _low_scores():
    return {
        "agent1": {"E1": {"score": 40, "reasoning": "poor"}, "E2": {"score": 40, "reasoning": "poor"}},
        "agent2": {"E1": {"score": 35, "reasoning": "poor"}, "E2": {"score": 38, "reasoning": "poor"}},
    }


def _t0_substantiveness():
    """Substantiveness with zero transformative changes to trigger novelty guidance."""
    return {
        "transformative": [],
        "structural": [],
        "incremental": [],
        "decision_space_exhausted": False,
        "notes": "",
    }


class TestNoveltyGuidanceInjection:
    """Novelty guidance: critic removed, adoption language mandatory."""

    def test_critic_not_in_novelty_guidance_when_both_enabled(self):
        """When both critic+novelty enabled, injected guidance mentions novelty only (not critic)."""
        state = _make_low_score_state(
            {
                "novelty_subagent_enabled": True,
                "critic_subagent_enabled": True,
            },
        )
        result = evaluate_checklist_submission(
            scores=_low_scores(),
            improvements="",
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
            substantiveness=_t0_substantiveness(),
        )
        explanation = result["explanation"]
        # Novelty should be mentioned
        assert "novelty" in explanation.lower()
        # Critic must NOT appear as a spawn instruction in the plateau-breaking block
        assert "spawn a `critic`" not in explanation
        assert "spawn two background" not in explanation

    def test_novelty_adoption_language_is_mandatory(self):
        """Injected novelty guidance must contain strong mandatory adoption language."""
        state = _make_low_score_state({"novelty_subagent_enabled": True})
        result = evaluate_checklist_submission(
            scores=_low_scores(),
            improvements="",
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
            substantiveness=_t0_substantiveness(),
        )
        explanation = result["explanation"]
        # Must contain mandatory language (MUST adopt / must adopt)
        assert "must adopt" in explanation.lower()

    def test_no_novelty_guidance_when_novelty_disabled(self):
        """No novelty guidance injected when novelty subagent is disabled."""
        state = _make_low_score_state({"novelty_subagent_enabled": False})
        result = evaluate_checklist_submission(
            scores=_low_scores(),
            improvements="",
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
            substantiveness=_t0_substantiveness(),
        )
        explanation = result["explanation"]
        assert "novelty subagent" not in explanation.lower()

    def test_novelty_not_injected_when_transformative_count_positive(self):
        """Novelty guidance only fires when T=0; skip when transformative items exist."""
        state = _make_low_score_state({"novelty_subagent_enabled": True})
        substantiveness = {
            "transformative": ["Full redesign"],
            "structural": [],
            "incremental": [],
            "decision_space_exhausted": False,
            "notes": "",
        }
        result = evaluate_checklist_submission(
            scores=_low_scores(),
            improvements="",
            report_path="",
            items=["Check 1", "Check 2"],
            state=state,
            substantiveness=substantiveness,
        )
        explanation = result["explanation"]
        # novelty guidance should not mention the "plateau" spawn instruction
        assert "plateau" not in explanation.lower()
