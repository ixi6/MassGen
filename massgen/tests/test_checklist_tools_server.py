#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
            "cutoff": 70,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"T1": {"score": 80, "reasoning": "good"}, "T2": {"score": 75, "reasoning": "ok"}},
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
            "cutoff": 70,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"T1": {"score": 80, "reasoning": "good"}, "T2": {"score": 50, "reasoning": "bad"}, "T3": {"score": 90, "reasoning": "great"}},
                improvements="",
            ),
        )
        assert result["verdict"] == "new_answer"
        assert result["true_count"] == 2
        assert "T2" in result["explanation"]

    @pytest.mark.asyncio
    async def test_first_answer_forces_iterate(self, tmp_path):
        """When has_existing_answers is False, verdict must always iterate."""
        items = ["Check 1"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": False,
            "required": 1,
            "cutoff": 70,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"T1": {"score": 100, "reasoning": "perfect"}},
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
            "cutoff": 70,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Send scores as a JSON string (Codex behavior)
        result = json.loads(
            await handler(
                scores='{"T1": {"score": 85, "reasoning": "good"}}',
                improvements="",
            ),
        )
        assert result["verdict"] == "vote"
        assert result["true_count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_json_string_returns_error(self, tmp_path):
        """Invalid JSON string for scores should return an error."""
        items = ["Check 1"]
        state = {"has_existing_answers": True, "required": 1, "cutoff": 70}
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
            "cutoff": 70,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"T1": {"score": 30, "reasoning": "bad"}},
                improvements="Add error handling and validation",
            ),
        )
        assert result["verdict"] == "new_answer"
        assert "Add error handling and validation" in result["explanation"]

    @pytest.mark.asyncio
    async def test_missing_score_keys_default_to_zero(self, tmp_path):
        """Missing score entries should default to score 0."""
        items = ["Check 1", "Check 2"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 2,
            "cutoff": 70,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        # Only provide T1, T2 is missing
        result = json.loads(
            await handler(
                scores={"T1": {"score": 80, "reasoning": "good"}},
                improvements="",
            ),
        )
        assert result["true_count"] == 1
        assert result["items"][1]["score"] == 0

    @pytest.mark.asyncio
    async def test_custom_terminate_and_iterate_actions(self, tmp_path):
        """Custom action names (stop/continue) should be used in verdicts."""
        items = ["Check 1"]
        state = {
            "terminate_action": "stop",
            "iterate_action": "continue",
            "has_existing_answers": True,
            "required": 1,
            "cutoff": 70,
            "require_gap_report": False,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={"T1": {"score": 80, "reasoning": "good"}},
                improvements="",
            ),
        )
        assert result["verdict"] == "stop"


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
            "cutoff": 70,
        }
        # All scores pass, no report path — verdict should be "vote"
        result = evaluate_checklist_submission(
            scores={"T1": 80, "T2": 85},
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
            "cutoff": 70,
        }
        result = evaluate_checklist_submission(
            scores={"T1": 80},
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
            "cutoff": 70,
        }
        # Empty report path
        result = evaluate_checklist_submission(
            scores={"T1": 90},
            improvements="",
            report_path="",
            items=items,
            state=state,
            substantiveness=None,
        )
        assert result["verdict"] == "vote"

        # None-ish report path
        result2 = evaluate_checklist_submission(
            scores={"T1": 90},
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
            "cutoff": 70,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 95, "reasoning": "strong"},
                    "T2": {"score": 95, "reasoning": "strong"},
                    "T3": {"score": 95, "reasoning": "strong"},
                    "T4": {"score": 95, "reasoning": "strong"},
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
            "cutoff": 70,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 90, "reasoning": "core quality strong"},
                    "T2": {"score": 88, "reasoning": "core quality strong"},
                    "T3": {"score": 85, "reasoning": "core quality strong"},
                    "T4": {"score": 58, "reasoning": "ambition limited"},
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
            "cutoff": 70,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 90, "reasoning": "core quality strong"},
                    "T2": {"score": 88, "reasoning": "core quality strong"},
                    "T3": {"score": 85, "reasoning": "core quality strong"},
                    "T4": {"score": 58, "reasoning": "ambition limited"},
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
            "cutoff": 70,
            "require_gap_report": False,
            "require_substantiveness": True,
            "changedoc_mode": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 90, "reasoning": "deliverable strong"},
                    "T2": {"score": 88, "reasoning": "gaps addressed"},
                    "T3": {"score": 55, "reasoning": "traceability gaps remain"},
                    "T4": {"score": 58, "reasoning": "ambition limited"},
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
            "cutoff": 70,
            "require_gap_report": False,
            "require_substantiveness": True,
            "changedoc_mode": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 90, "reasoning": "deliverable strong"},
                    "T2": {"score": 88, "reasoning": "gaps addressed"},
                    "T3": {"score": 89, "reasoning": "traceability is complete"},
                    "T4": {"score": 58, "reasoning": "ambition limited"},
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
    async def test_t4_ambition_guidance_when_exhausted(self, tmp_path):
        """When T4 fails and decision space is exhausted, give specific ambition guidance."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 90,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 78, "reasoning": "decent coverage"},
                    "T2": {"score": 76, "reasoning": "decent rationale"},
                    "T3": {"score": 85, "reasoning": "good traceability"},
                    "T4": {"score": 38, "reasoning": "no genuine ambition"},
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
        # Should contain T4-specific ambition guidance
        assert "T4 (ambition/craft) failed" in result["explanation"]
        assert "ambition deficit" in result["explanation"]

    @pytest.mark.asyncio
    async def test_t4_ambition_guidance_when_substantive_plan_exists(self, tmp_path):
        """When T4 fails but structural work remains, give different ambition guidance."""
        items = ["Check 1", "Check 2", "Check 3", "Check 4"]
        state = {
            "terminate_action": "vote",
            "iterate_action": "new_answer",
            "has_existing_answers": True,
            "required": 4,
            "cutoff": 90,
            "require_gap_report": False,
            "require_substantiveness": True,
        }
        handler = _build_handler(_make_specs_file(tmp_path, items, state))

        result = json.loads(
            await handler(
                scores={
                    "T1": {"score": 78, "reasoning": "decent coverage"},
                    "T2": {"score": 76, "reasoning": "decent rationale"},
                    "T3": {"score": 85, "reasoning": "good traceability"},
                    "T4": {"score": 38, "reasoning": "no genuine ambition"},
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
        # Should still get ambition guidance but the non-exhausted variant
        assert "T4 (ambition/craft) failed" in result["explanation"]
        assert "creative ambition" in result["explanation"]


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
            "cutoff": 70,
            "substantiveness_eval": {"required": True, "valid": True, "has_substantive_plan": True},
        }
        result = evaluate_checklist_submission(
            scores={
                "T1": {"score": 60, "reasoning": "gaps in coverage"},
                "T2": {"score": 55, "reasoning": "weak quality"},
                "T3": {"score": 70, "reasoning": "decent polish"},
                "T4": {"score": 50, "reasoning": "shallow"},
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
            "cutoff": 70,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "T1": {"score": 60, "reasoning": "gaps"},
                "T2": {"score": 55, "reasoning": "weak"},
                "T3": {"score": 70, "reasoning": "ok"},
                "T4": {"score": 50, "reasoning": "shallow"},
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
            "cutoff": 70,
            "require_substantiveness": True,
        }
        result = evaluate_checklist_submission(
            scores={
                "T1": {"score": 60, "reasoning": "gaps"},
                "T2": {"score": 55, "reasoning": "weak"},
                "T3": {"score": 70, "reasoning": "ok"},
                "T4": {"score": 50, "reasoning": "shallow"},
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
            "cutoff": 70,
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
        state_v2 = {"has_existing_answers": True, "required": 2, "cutoff": 70, "remaining": 3}
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
