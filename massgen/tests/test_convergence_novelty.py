"""Tests for convergence and ambition/craft mechanisms.

Tests cover:
- Rationale preservation rules in changedoc subsequent round prompt
- T4 ambition/craft definition (depth over breadth, synthesis with improvement counts)
- Substantiveness test in checklist gated evaluation
- Fresh approach enhancements (FEWER decisions restraint)
- Substantiveness classification in changedoc analysis
"""

from massgen.system_prompt_sections import (
    _CHECKLIST_ITEM_CATEGORIES_CHANGEDOC,
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


class TestE4StretchDefinition:
    """Tests for E4 stretch checklist item covering polish/craft."""

    def test_e4_covers_care_beyond_correctness(self):
        """E4 item must address quality beyond mere correctness."""
        e4_item = _CHECKLIST_ITEMS_CHANGEDOC[3]
        assert "beyond correctness" in e4_item.lower() or "care" in e4_item.lower()

    def test_e4_mentions_creative_elements(self):
        """E4 item must mention creative or distinguishing elements."""
        e4_item = _CHECKLIST_ITEMS_CHANGEDOC[3]
        assert "creative" in e4_item.lower() or "distinguish" in e4_item.lower()

    def test_changedoc_checklist_has_4_items(self):
        """Changedoc checklist must have exactly 4 items."""
        assert len(_CHECKLIST_ITEMS_CHANGEDOC) == 4

    def test_e4_is_could_category(self):
        """E4 must be tagged as could (aspirational), not must."""
        assert _CHECKLIST_ITEM_CATEGORIES_CHANGEDOC["E4"] == "could"


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
        # Must instruct agents to implement all improvements, not cherry-pick
        assert "all" in normalized and "improvements" in normalized
        # Must discourage picking only a subset (any of these phrasings suffice)
        assert "cherry" in normalized or "single easiest" in normalized or "one and stop" in normalized or "not just one" in normalized or "not just some" in normalized


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

    def test_changedoc_analysis_has_approach_challenge(self):
        """Changedoc analysis must include the Approach Challenge section."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Approach Challenge" in analysis

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

    def test_checklist_gated_has_approach_challenge(self):
        """Checklist gated evaluation should include approach challenge."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            has_changedoc=True,
        )
        content = section.build_content()
        assert "Approach Challenge" in content

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


class TestDiagnosticAnalysis:
    """Tests for GEPA-style diagnostic analysis framework."""

    def test_generic_analysis_has_failure_patterns(self):
        """Generic checklist analysis must have Failure Patterns section."""
        analysis = _build_checklist_analysis()
        assert "Failure Patterns" in analysis

    def test_generic_analysis_has_success_patterns(self):
        """Generic checklist analysis must have Success Patterns section."""
        analysis = _build_checklist_analysis()
        assert "Success Patterns" in analysis

    def test_generic_analysis_has_root_causes(self):
        """Generic checklist analysis must have Root Causes section."""
        analysis = _build_checklist_analysis()
        assert "Root Causes" in analysis

    def test_changedoc_analysis_has_failure_patterns(self):
        """Changedoc analysis must have Failure Patterns section."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Failure Patterns" in analysis

    def test_changedoc_analysis_has_decision_audit(self):
        """Changedoc analysis must still include Decision Audit."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Decision Audit" in analysis

    def test_generic_analysis_no_assess_quality(self):
        """Generic analysis must not use the old 'assess quality' framing."""
        analysis = _build_checklist_analysis()
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
        assert "9-10" in decision
        assert "7-8" in decision
        assert "5-6" in decision
        assert "3-4" in decision
        assert "1-2" in decision

    def test_gated_decision_has_consistency_rule(self):
        """Gated decision must have calibration consistency rule."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "MUST be consistent with" in decision

    def test_gated_decision_has_analysis_score_consistency(self):
        """Gated decision must include analysis-vs-score consistency check."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        lower = decision.lower()
        assert "diagnostic analysis" in lower
        assert "scores are inflated" in lower

    def test_scored_decision_has_calibration_anchors(self):
        """Scored decision must also include calibration anchor text."""
        decision = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=_CHECKLIST_ITEMS_CHANGEDOC,
        )
        assert "9-10" in decision
        assert "7-8" in decision


# ---------------------------------------------------------------------------
# Change 3: Hardened Gap Analysis
# ---------------------------------------------------------------------------


class TestDiagnosticGoalAlignment:
    """Tests for GEPA-style goal alignment and cross-answer synthesis."""

    def test_generic_has_goal_alignment(self):
        """Generic analysis must have Goal Alignment section."""
        analysis = _build_checklist_analysis()
        assert "Goal Alignment" in analysis

    def test_generic_goal_alignment_references_original_request(self):
        """Goal alignment must score against the original request."""
        analysis = _build_checklist_analysis()
        assert "original request" in analysis or "original message" in analysis

    def test_changedoc_has_goal_alignment(self):
        """Changedoc analysis must have Goal Alignment section."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Goal Alignment" in analysis

    def test_generic_has_cross_answer_synthesis(self):
        """Generic analysis must have Cross-Answer Synthesis section."""
        analysis = _build_checklist_analysis()
        assert "Cross-Answer Synthesis" in analysis


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
    """Tests for recalibration text in goal alignment section."""

    def test_generic_analysis_has_recalibration(self):
        """Generic analysis must have recalibration text in goal alignment."""
        analysis = _build_checklist_analysis()
        assert "score for that criterion must be low" in analysis

    def test_changedoc_analysis_has_recalibration(self):
        """Changedoc analysis must have recalibration text in goal alignment."""
        analysis = _build_changedoc_checklist_analysis()
        assert "distance in mind" in analysis

    def test_generic_recalibration_ordering(self):
        """Recalibration must appear in Goal Alignment, before Approach Challenge."""
        analysis = _build_checklist_analysis()
        goal_pos = analysis.index("Goal Alignment")
        recal_pos = analysis.index("score for that criterion must be low")
        challenge_pos = analysis.index("Approach Challenge")
        assert goal_pos < recal_pos < challenge_pos

    def test_changedoc_recalibration_ordering(self):
        """Changedoc recalibration must appear in Goal Alignment, before Substantiveness."""
        analysis = _build_changedoc_checklist_analysis()
        goal_pos = analysis.index("Goal Alignment")
        recal_pos = analysis.index("distance in mind")
        subst_pos = analysis.index("Substantiveness")
        assert goal_pos < recal_pos < subst_pos


# ---------------------------------------------------------------------------
# Anti-Glazing / Score Calibration
# ---------------------------------------------------------------------------


class TestAntiGlazing:
    """Tests for anti-glazing calibration language in scoring prompts."""

    def test_scored_decision_has_calibrated_anchors(self):
        """Scored decision must use the recalibrated anchors."""
        decision = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=_CHECKLIST_ITEMS_CHANGEDOC,
        )
        assert "publish this as-is" in decision
        assert "Most first drafts belong here" in decision

    def test_gated_decision_has_calibrated_anchors(self):
        """Gated decision must use the recalibrated anchors."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "publish this as-is" in decision
        assert "Most first drafts belong here" in decision

    def test_checklist_analysis_has_too_generous_warning(self):
        """Non-changedoc checklist analysis must include 'too generous' warning."""
        analysis = _build_checklist_analysis()
        assert "too generous" in analysis

    def test_changedoc_analysis_has_too_generous_warning(self):
        """Changedoc analysis must still include 'too generous' warning."""
        analysis = _build_changedoc_checklist_analysis()
        assert "too generous" in analysis

    def test_checklist_analysis_has_pre_score_audit(self):
        """Non-changedoc analysis must include Pre-Score Audit section."""
        analysis = _build_checklist_analysis()
        assert "Pre-Score Audit (MANDATORY)" in analysis
        assert "contradicts your own Failure Patterns" in analysis

    def test_changedoc_analysis_has_pre_score_audit(self):
        """Changedoc analysis must include Pre-Score Audit section."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Pre-Score Audit (MANDATORY)" in analysis
        assert "contradicts your own Failure Patterns" in analysis

    def test_scored_decision_has_inflated_warning(self):
        """Scored decision must warn about inflated scores."""
        decision = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=_CHECKLIST_ITEMS_CHANGEDOC,
        )
        assert "scores are inflated" in decision

    def test_gated_decision_has_inflated_warning(self):
        """Gated decision must warn about inflated scores."""
        decision = _build_checklist_gated_decision(_CHECKLIST_ITEMS_CHANGEDOC)
        assert "scores are inflated" in decision

    def test_pre_score_audit_after_approach_challenge(self):
        """Pre-Score Audit must appear after Approach Challenge in non-changedoc analysis."""
        analysis = _build_checklist_analysis()
        challenge_pos = analysis.index("Approach Challenge")
        audit_pos = analysis.index("Pre-Score Audit")
        assert challenge_pos < audit_pos

    def test_pre_score_audit_after_approach_challenge_changedoc(self):
        """Pre-Score Audit must appear after Approach Challenge in changedoc analysis."""
        analysis = _build_changedoc_checklist_analysis()
        challenge_pos = analysis.index("Approach Challenge")
        audit_pos = analysis.index("Pre-Score Audit")
        assert challenge_pos < audit_pos


# ---------------------------------------------------------------------------
# Novelty Subagent Type
# ---------------------------------------------------------------------------


class TestNoveltySubagentType:
    """Tests for the novelty subagent type definition."""

    def test_novelty_subagent_md_exists(self):
        """massgen/subagent_types/novelty/SUBAGENT.md must exist."""
        from pathlib import Path

        subagent_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        assert subagent_md.exists(), f"Expected {subagent_md} to exist"

    def test_novelty_subagent_has_valid_yaml_frontmatter(self):
        """SUBAGENT.md must have valid YAML frontmatter with required fields."""
        from pathlib import Path

        import yaml

        subagent_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        content = subagent_md.read_text()

        # Must start with YAML frontmatter
        assert content.startswith("---"), "SUBAGENT.md must start with YAML frontmatter"
        end = content.index("---", 3)
        frontmatter = yaml.safe_load(content[3:end])

        assert frontmatter["name"] == "novelty"
        assert "description" in frontmatter
        assert "expected_input" in frontmatter

    def test_novelty_subagent_instructions_contain_key_elements(self):
        """SUBAGENT.md body must contain key instruction elements."""
        from pathlib import Path

        subagent_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        content = subagent_md.read_text().lower()

        # Must instruct transformative alternatives, not incremental
        assert "transformative" in content
        assert "incremental" in content
        # Must mention breaking plateaus or stalling
        assert "plateau" in content or "stall" in content or "anchor" in content
        # Must propose multiple directions
        assert "direction" in content or "alternative" in content
        # Must explain WHY, not just WHAT
        assert "why" in content
