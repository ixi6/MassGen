# -*- coding: utf-8 -*-
"""Tests for convergence and ambition/craft mechanisms.

Tests cover:
- Rationale preservation rules in changedoc subsequent round prompt
- T4 ambition/craft definition (depth over breadth, synthesis with improvement counts)
- Substantiveness test in checklist gated evaluation
- Fresh approach enhancements (FEWER decisions restraint)
- Substantiveness classification in changedoc analysis
"""

from massgen.system_prompt_sections import (
    _CHECKLIST_ITEMS_CHANGEDOC,
    ChangedocSection,
    EvaluationSection,
    _build_changedoc_checklist_analysis,
    _build_checklist_analysis,
    _build_checklist_gated_decision,
    _build_checklist_scored_decision,
)

# ---------------------------------------------------------------------------
# Rationale Preservation Rules
# ---------------------------------------------------------------------------


class TestRationalePreservation:
    """Tests for rationale preservation rules in changedoc subsequent round prompt."""

    def test_subsequent_round_has_rationale_preservation_rule(self):
        """Subsequent-round changedoc prompt must contain rationale preservation rules."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "Rationale Preservation Rule" in content

    def test_subsequent_round_mentions_synthesis_note(self):
        """Subsequent-round prompt instructs using Synthesis Note for meta-reasoning."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "Synthesis Note" in content

    def test_subsequent_round_forbids_meta_justification(self):
        """Subsequent-round prompt explicitly forbids replacing Why with meta-justification."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "FORBIDDEN" in content
        assert "this was the best prior answer" in content

    def test_first_round_no_rationale_preservation(self):
        """First-round prompt does not contain rationale preservation rules (not needed)."""
        section = ChangedocSection(has_prior_answers=False)
        content = section.build_content()
        assert "Synthesis Note" not in content
        assert "Rationale Preservation" not in content

    def test_subsequent_round_template_shows_synthesis_note(self):
        """Template example in subsequent round includes Synthesis Note field."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        # Both inherited and modified templates should have Synthesis Note
        assert content.count("**Synthesis Note:**") >= 2


# ---------------------------------------------------------------------------
# T4 Ambition/Craft Definition
# ---------------------------------------------------------------------------


class TestT4AmbitionDefinition:
    """Tests for T4 checklist item covering ambition/craft (replaces old T5 novelty)."""

    def test_t4_mentions_synthesis_with_improvement(self):
        """T4 item must clarify that synthesis with improvement counts."""
        t4_item = _CHECKLIST_ITEMS_CHANGEDOC[3]
        assert "synthesis" in t4_item.lower()

    def test_t4_covers_ambition_or_craft(self):
        """T4 item must address creative ambition or meaningful craft."""
        t4_item = _CHECKLIST_ITEMS_CHANGEDOC[3]
        assert "ambition" in t4_item.lower() or "craft" in t4_item.lower()

    def test_changedoc_checklist_has_4_items(self):
        """Changedoc checklist must have exactly 4 items."""
        assert len(_CHECKLIST_ITEMS_CHANGEDOC) == 4

    def test_t4_values_depth_not_just_novelty(self):
        """T4 rewards depth (richer existing elements) not just novel additions."""
        t4_item = _CHECKLIST_ITEMS_CHANGEDOC[3]
        assert "richer" in t4_item.lower() or "elegant" in t4_item.lower()


# ---------------------------------------------------------------------------
# Substantiveness Test in Checklist Gated Evaluation
# ---------------------------------------------------------------------------


class TestSubstantivenessTest:
    """Tests for substantiveness classification in checklist gated decision."""

    def test_gated_decision_has_substantiveness_test(self):
        """Checklist gated decision must include substantiveness test section."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "Substantiveness Test" in decision

    def test_gated_decision_has_three_classifications(self):
        """Decision text must mention all three classification levels."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "TRANSFORMATIVE" in decision
        assert "STRUCTURAL" in decision
        assert "INCREMENTAL" in decision

    def test_gated_decision_guides_voting_for_incremental(self):
        """Decision text must suggest voting when all improvements are incremental."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        lower = decision.lower()
        assert "voting may be the better choice" in lower

    def test_gated_decision_has_substantiveness_object_instructions(self):
        """Gated decision must instruct agents to provide a substantiveness object."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "substantiveness" in decision.lower()
        # Should use list-based format keys, not count-based
        assert '"transformative"' in decision or "'transformative'" in decision
        assert "decision_space_exhausted" in decision

    def test_gated_decision_has_diverse_examples(self):
        """Decision text must give examples for each classification level."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        # TRANSFORMATIVE examples
        assert "data model" in decision.lower() or "event-driven" in decision.lower()
        # STRUCTURAL examples
        assert "real-time" in decision.lower() or "caching" in decision.lower()
        # INCREMENTAL examples
        assert "aria labels" in decision.lower() or "alt text" in decision.lower()

    def test_gated_decision_classifies_changedoc_only_as_incremental(self):
        """Changedoc-only improvements must be classified as INCREMENTAL."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        lower = decision.lower()
        assert "changedoc" in lower and "incremental" in lower
        # Specifically check the INCREMENTAL section mentions changedoc work
        # (text may wrap across lines, so normalize whitespace)
        normalized = " ".join(lower.split())
        assert "changedoc decisions without corresponding" in normalized

    def test_gated_decision_requires_implementing_all_identified_improvements(self):
        """Iterate verdict guidance must say to implement ALL identified improvements, not just one."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        normalized = " ".join(decision.lower().split())
        # Must instruct agents to implement all structural improvements, not cherry-pick
        assert "all" in normalized and "improvements" in normalized
        # Must discourage picking only one improvement when multiple are identified
        assert "cherry" in normalized or "single easiest" in normalized or "one and stop" in normalized


# ---------------------------------------------------------------------------
# Substantiveness Test in Changedoc Analysis
# ---------------------------------------------------------------------------


class TestChangedocAnalysisSubstantiveness:
    """Tests for substantiveness test in changedoc-anchored analysis."""

    def test_changedoc_analysis_has_substantiveness(self):
        """Changedoc analysis must include substantiveness test section."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Substantiveness Test" in analysis

    def test_changedoc_analysis_has_classification_categories(self):
        """Changedoc analysis must reference the three classification categories."""
        analysis = _build_changedoc_checklist_analysis()
        assert "TRANSFORMATIVE" in analysis
        assert "STRUCTURAL" in analysis
        assert "INCREMENTAL" in analysis

    def test_changedoc_analysis_has_fewer_decisions_principle(self):
        """Changedoc analysis must include the 'FEWER decisions' restraint principle."""
        analysis = _build_changedoc_checklist_analysis()
        assert "FEWER decisions" in analysis

    def test_changedoc_analysis_classifies_changedoc_only_as_incremental(self):
        """Changedoc analysis must classify changedoc-only changes as INCREMENTAL."""
        analysis = _build_changedoc_checklist_analysis()
        lower = analysis.lower()
        assert "changedoc decisions without corresponding" in lower


# ---------------------------------------------------------------------------
# Fresh Approach Enhancement
# ---------------------------------------------------------------------------


class TestFreshApproach:
    """Tests for fresh approach enhancements."""

    def test_checklist_gated_has_fresh_approach(self):
        """Checklist gated evaluation should include fresh approach consideration."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            has_changedoc=True,
        )
        content = section.build_content()
        assert "Fresh Approach" in content or "fresh approach" in content.lower()

    def test_sequential_r2_has_variation_guidance(self):
        """Sequential sensitivity Round 2 (CONVERGENCE phase) should mention variation."""
        section = EvaluationSection(
            voting_sensitivity="sequential",
            round_number=2,
        )
        content = section.build_content()
        lower = content.lower()
        # R2 should encourage fresh approaches or variation
        assert "vari" in lower or "fresh" in lower or "different" in lower or "diverg" in lower


# ---------------------------------------------------------------------------
# Change 1: Adversarial Critique Framing
# ---------------------------------------------------------------------------


class TestAdversarialCritique:
    """Tests for reframing Per-Answer Assessment as adversarial critique."""

    def test_generic_analysis_has_adversarial_reviewer(self):
        """Generic checklist analysis must frame the role as adversarial reviewer."""
        analysis = _build_checklist_analysis()
        assert "adversarial reviewer" in analysis

    def test_generic_analysis_has_find_every_flaw(self):
        """Generic checklist analysis must instruct to find every flaw."""
        analysis = _build_checklist_analysis()
        assert "find every flaw" in analysis

    def test_changedoc_analysis_has_adversarial_reviewer(self):
        """Changedoc analysis must frame the role as adversarial reviewer."""
        analysis = _build_changedoc_checklist_analysis()
        assert "adversarial reviewer" in analysis

    def test_changedoc_analysis_has_find_every_flaw(self):
        """Changedoc analysis must instruct to find every flaw."""
        analysis = _build_changedoc_checklist_analysis()
        assert "find every flaw" in analysis

    def test_generic_analysis_no_assess_quality(self):
        """Generic analysis must not use the old 'assess quality' framing."""
        analysis = _build_checklist_analysis()
        # The old "For each answer, assess:" phrasing should be replaced
        assert "Is it something you would be proud to deliver" not in analysis

    def test_changedoc_analysis_no_assess_quality(self):
        """Changedoc analysis must not use the old 'assess quality' framing."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Is it something you would be proud to deliver" not in analysis


# ---------------------------------------------------------------------------
# Change 2: Score Calibration Anchors
# ---------------------------------------------------------------------------


class TestScoreCalibration:
    """Tests for score calibration anchors in decision sections."""

    def test_gated_decision_has_calibration_anchors(self):
        """Gated decision must include score calibration anchor ranges."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "90-100%" in decision
        assert "70-89%" in decision
        assert "50-69%" in decision
        assert "30-49%" in decision
        assert "Below 30%" in decision

    def test_gated_decision_has_first_attempts_rarely(self):
        """Gated decision must warn that first attempts rarely score above 70%."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "First attempts rarely score above 70%" in decision

    def test_gated_decision_has_critique_score_consistency(self):
        """Gated decision must include critique-vs-score consistency check."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        lower = decision.lower()
        assert "critique" in lower
        assert "one of them is wrong" in lower

    def test_scored_decision_has_calibration_anchors(self):
        """Scored decision must also include calibration anchor text."""
        decision = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=_CHECKLIST_ITEMS_CHANGEDOC,
        )
        assert "90-100%" in decision
        assert "70-89%" in decision


# ---------------------------------------------------------------------------
# Change 3: Hardened Gap Analysis
# ---------------------------------------------------------------------------


class TestHardenedGapAnalysis:
    """Tests for problem-focused gap analysis."""

    def test_generic_gap_analysis_list_only_problems(self):
        """Generic gap analysis must say 'List only problems'."""
        analysis = _build_checklist_analysis()
        assert "List only problems" in analysis

    def test_generic_gap_analysis_no_describe_what_works(self):
        """Generic gap analysis must say 'do not describe what works'."""
        analysis = _build_checklist_analysis()
        assert "do not describe what works" in analysis

    def test_changedoc_gap_analysis_has_cross_check(self):
        """Changedoc gap analysis must include cross-check instruction."""
        analysis = _build_changedoc_checklist_analysis()
        assert "do the flaws from your Per-Answer Critique align" in analysis

    def test_generic_gap_analysis_has_cross_check(self):
        """Generic gap analysis must include cross-check between critique and gap."""
        analysis = _build_checklist_analysis()
        lower = analysis.lower()
        assert "critique" in lower
        # Check for the cross-check instruction
        assert "revisit both" in lower


# ---------------------------------------------------------------------------
# Change 4: Exhaustion Criteria
# ---------------------------------------------------------------------------


class TestExhaustionCriteria:
    """Tests for strengthened decision_space_exhausted criteria."""

    def test_gated_decision_mentions_three_approaches(self):
        """Gated decision must mention '3 fundamentally different approaches'."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "3 fundamentally different approaches" in decision

    def test_gated_decision_mentions_different_directions(self):
        """Gated decision must mention different architectures and creative directions."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "different architectures" in decision
        assert "different creative directions" in decision


# ---------------------------------------------------------------------------
# Change 5: Recalibration Between Ideal and Gap
# ---------------------------------------------------------------------------


class TestRecalibration:
    """Tests for recalibration text between ideal and gap analysis."""

    def test_generic_analysis_has_recalibration(self):
        """Generic analysis must have recalibration text after ideal section."""
        analysis = _build_checklist_analysis()
        assert "Hold this distance in mind when you score" in analysis

    def test_changedoc_analysis_has_recalibration(self):
        """Changedoc analysis must have recalibration text after ideal decision set."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Hold this distance in mind" in analysis

    def test_generic_recalibration_ordering(self):
        """Recalibration must appear between ideal and gap analysis sections."""
        analysis = _build_checklist_analysis()
        ideal_pos = analysis.index("The Ideal Version")
        recal_pos = analysis.index("Hold this distance in mind when you score")
        gap_pos = analysis.index("### Gap Analysis")
        assert ideal_pos < recal_pos < gap_pos

    def test_changedoc_recalibration_ordering(self):
        """Changedoc recalibration must appear between ideal decision set and gap analysis."""
        analysis = _build_changedoc_checklist_analysis()
        ideal_pos = analysis.index("The Ideal Decision Set")
        recal_pos = analysis.index("Hold this distance in mind")
        gap_pos = analysis.index("### Gap Analysis")
        assert ideal_pos < recal_pos < gap_pos
