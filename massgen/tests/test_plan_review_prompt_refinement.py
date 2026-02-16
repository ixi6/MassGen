# -*- coding: utf-8 -*-
"""Tests for plan-review refinement prompt composition."""

from massgen.cli import build_plan_review_refinement_appendix


def test_refinement_appendix_avoids_duplicate_feedback_block_when_already_in_question():
    question = "Refine `project_plan.json`.\n\n" "Plan review feedback:\n" "add more visual verification"
    appendix = build_plan_review_refinement_appendix(
        question=question,
        planning_feedback="add more visual verification",
        include_quick_edit_hint=True,
    )

    assert "## Plan Review Feedback" not in appendix
    assert "## Quick Edit Planning Turn" in appendix


def test_refinement_appendix_includes_feedback_once_when_missing_from_question():
    appendix = build_plan_review_refinement_appendix(
        question="Refine project plan",
        planning_feedback="add migration rollback steps",
        include_quick_edit_hint=False,
    )

    assert appendix.count("## Plan Review Feedback") == 1
    assert "add migration rollback steps" in appendix


def test_quick_edit_hint_does_not_explicitly_call_out_single_agent():
    appendix = build_plan_review_refinement_appendix(
        question="Refine project plan",
        planning_feedback="",
        include_quick_edit_hint=True,
    )

    assert "## Quick Edit Planning Turn" in appendix
    assert "single-agent" not in appendix.lower()
