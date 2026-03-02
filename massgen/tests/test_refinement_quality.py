"""Tests for refinement quality improvements (anchoring problem).

Covers:
- Part A: Prompt quality improvements (Changes 1-6)
- Part B: Critic subagent type
- Part C: Evaluation criteria revamp (MUST/SHOULD/COULD tiers)
"""

from pathlib import Path

from massgen.system_prompt_sections import (
    NoveltyPressureSection,
    _build_changedoc_checklist_analysis,
    _build_checklist_analysis,
    _build_checklist_gated_decision,
    _build_checklist_scored_decision,
)

# ===========================================================================
# Part A: Prompt Quality Improvements
# ===========================================================================


class TestScoreCalibration:
    """Change 1: Recalibrated score anchors."""

    def test_scored_decision_has_recalibrated_anchors(self):
        """Score calibration places 'most first drafts' at 5-6 level."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=items,
        )
        assert "Most first drafts belong here" in result

    def test_scored_decision_no_first_attempts_above_7(self):
        """Old 'first attempts almost never deserve above 7' is removed."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=items,
        )
        assert "First attempts almost never deserve above 7" not in result

    def test_scored_decision_has_consistency_rule(self):
        """Score calibration includes soft consistency rule."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=items,
        )
        assert "MUST be consistent with" in result

    def test_gated_decision_has_recalibrated_anchors(self):
        """Gated decision also has recalibrated score anchors."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_gated_decision(checklist_items=items)
        assert "Most first drafts belong here" in result

    def test_gated_decision_no_first_attempts_above_7(self):
        """Old 'first attempts almost never deserve above 7' is removed from gated."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_gated_decision(checklist_items=items)
        assert "First attempts almost never deserve above 7" not in result

    def test_gated_decision_has_consistency_rule(self):
        """Gated decision has consistency rule."""
        items = ["E1 criterion", "E2 criterion"]
        result = _build_checklist_gated_decision(checklist_items=items)
        assert "MUST be consistent with" in result

    def test_publish_as_is_at_9_10(self):
        """9-10 described as 'professional would publish as-is'."""
        items = ["E1 criterion"]
        result = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=items,
        )
        assert "publish this as-is" in result


class TestApproachChallenge:
    """Change 2: Fresh Approach → Approach Challenge."""

    def test_checklist_analysis_has_approach_challenge(self):
        """_build_checklist_analysis contains Approach Challenge section."""
        result = _build_checklist_analysis()
        assert "### Approach Challenge" in result

    def test_checklist_analysis_no_fresh_approach(self):
        """Old 'Fresh Approach Consideration' is replaced."""
        result = _build_checklist_analysis()
        assert "Fresh Approach Consideration" not in result

    def test_approach_challenge_demands_alternative(self):
        """Approach Challenge asks for a fundamentally different way."""
        result = _build_checklist_analysis()
        assert "fundamentally different way to solve this problem" in result

    def test_changedoc_analysis_has_approach_challenge(self):
        """Changedoc analysis also has Approach Challenge."""
        result = _build_changedoc_checklist_analysis()
        assert "### Approach Challenge" in result

    def test_changedoc_analysis_no_fresh_approach(self):
        """Changedoc analysis replaces Fresh Approach."""
        result = _build_changedoc_checklist_analysis()
        assert "Fresh Approach Consideration" not in result


class TestPriorAnswerReframing:
    """Change 3: Reframe prior answers as benchmarks."""

    def test_changedoc_subsequent_has_evaluating_prior_answers(self):
        """Subsequent round prompt analyzes each answer independently."""
        from massgen.system_prompt_sections import ChangedocSection

        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "analyze each existing answer independently" in content
        assert "uniquely well" in content

    def test_no_pick_one_as_base(self):
        """Old 'do not pick one as your base' is replaced."""
        from massgen.system_prompt_sections import ChangedocSection

        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert 'do not pick one as your "base" and refine it' not in content


class TestPreScoreAudit:
    """Change 4: Strengthened Pre-Score Audit."""

    def test_checklist_analysis_has_mandatory_audit(self):
        """Pre-Score Audit is marked MANDATORY."""
        result = _build_checklist_analysis()
        assert "### Pre-Score Audit (MANDATORY)" in result

    def test_checklist_analysis_has_consistency_check(self):
        """Pre-Score Audit has concrete consistency check."""
        result = _build_checklist_analysis()
        assert "contradicts your own Failure Patterns" in result

    def test_changedoc_analysis_has_mandatory_audit(self):
        """Changedoc Pre-Score Audit is also MANDATORY."""
        result = _build_changedoc_checklist_analysis()
        assert "### Pre-Score Audit (MANDATORY)" in result

    def test_changedoc_analysis_has_consistency_check(self):
        """Changedoc Pre-Score Audit has consistency check."""
        result = _build_changedoc_checklist_analysis()
        assert "contradicts your own Failure Patterns" in result

    def test_score_above_5_justification(self):
        """Audit mentions score above 5 needing justification."""
        result = _build_checklist_analysis()
        assert "above 5 needs strong justification" in result


class TestProactiveNovelty:
    """Change 5: NoveltyPressureSection proactive at consecutive=0."""

    def test_novelty_proactive_at_zero_consecutive(self):
        """NoveltyPressureSection produces proactive message at consecutive=0."""
        section = NoveltyPressureSection(
            novelty_level="gentle",
            consecutive_incremental_rounds=0,
            restart_count=0,
        )
        content = section.build_content()
        assert "RIGHT approach" in content or "right approach" in content.lower()
        assert "CURRENT approach" in content or "current approach" in content.lower()

    def test_novelty_gentle_still_works_at_1(self):
        """Gentle level still works at consecutive=1 (existing behavior)."""
        section = NoveltyPressureSection(
            novelty_level="gentle",
            consecutive_incremental_rounds=1,
            restart_count=0,
        )
        content = section.build_content()
        assert "fundamentally different approach" in content


class TestCriticFraming:
    """Change 6: Critic framing in evaluation system message."""

    def test_evaluation_system_message_has_critic_framing(self):
        """evaluation_system_message() contains 'as a critic'."""
        from massgen.message_templates import MessageTemplates

        templates = MessageTemplates()
        msg = templates.evaluation_system_message()
        assert "as a critic" in msg

    def test_critic_framing_mentions_genuinely_good(self):
        """Critic framing asks whether work is genuinely good."""
        from massgen.message_templates import MessageTemplates

        templates = MessageTemplates()
        msg = templates.evaluation_system_message()
        assert "genuinely good" in msg


# ===========================================================================
# Part B: Critic Subagent
# ===========================================================================


class TestCriticSubagent:
    """Tests for critic subagent type."""

    def test_critic_in_default_subagent_types(self):
        """critic is in DEFAULT_SUBAGENT_TYPES."""
        from massgen.subagent.type_scanner import DEFAULT_SUBAGENT_TYPES

        assert "critic" in DEFAULT_SUBAGENT_TYPES

    def test_critic_subagent_md_exists(self):
        """critic SUBAGENT.md file exists."""
        critic_md = Path(__file__).parent.parent / "subagent_types" / "critic" / "SUBAGENT.md"
        assert critic_md.exists(), f"Expected {critic_md} to exist"

    def test_critic_discovered_by_scanner(self):
        """scan_subagent_types discovers critic type."""
        from massgen.subagent.type_scanner import scan_subagent_types

        builtin_dir = Path(__file__).parent.parent / "subagent_types"
        types = scan_subagent_types(
            builtin_dir=builtin_dir,
            project_dir=Path("/nonexistent"),
            allowed_types=["critic"],
        )
        names = [t.name for t in types]
        assert "critic" in names

    def test_default_types_still_excludes_novelty(self):
        """novelty is still excluded from DEFAULT_SUBAGENT_TYPES."""
        from massgen.subagent.type_scanner import DEFAULT_SUBAGENT_TYPES

        assert "novelty" not in DEFAULT_SUBAGENT_TYPES

    def test_default_types_preserves_existing(self):
        """Existing types (evaluator, explorer, researcher) still present."""
        from massgen.subagent.type_scanner import DEFAULT_SUBAGENT_TYPES

        assert "evaluator" in DEFAULT_SUBAGENT_TYPES
        assert "explorer" in DEFAULT_SUBAGENT_TYPES
        assert "researcher" in DEFAULT_SUBAGENT_TYPES


class TestNoveltySubagentQualityRevamp:
    """Tests for novelty subagent quality/craft direction."""

    def test_novelty_subagent_mentions_quality_revamp(self):
        """Novelty SUBAGENT.md should mention quality/craft revamp as a direction."""
        novelty_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        content = novelty_md.read_text()
        assert "Quality/craft revamp" in content or "quality/craft revamp" in content

    def test_novelty_warns_against_feature_accumulation(self):
        """Novelty SUBAGENT.md should warn against adding more features on a weak foundation."""
        novelty_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        content = novelty_md.read_text()
        assert "add more features" in content.lower() or "feature accumulation" in content.lower()

    def test_novelty_not_just_additive(self):
        """Novelty constraints should explicitly warn against 'add more' as a direction."""
        novelty_md = Path(__file__).parent.parent / "subagent_types" / "novelty" / "SUBAGENT.md"
        content = novelty_md.read_text()
        assert "rebuild" in content.lower() or "foundation" in content.lower()


class TestCriticChecklistGuidance:
    """Tests for parallel critic + novelty spawning guidance."""

    def test_checklist_mentions_novelty_not_critic_when_both_available(self):
        """When critic and novelty are both available and criteria have plateaued, guidance mentions novelty only (critic removed from plateau loop)."""
        from massgen.mcp_tools.checklist_tools_server import (
            evaluate_checklist_submission,
        )

        items = ["criterion 1", "criterion 2"]
        # Build a minimal state with both critic and novelty available
        state = {
            "threshold": 5,
            "items": items,
            "remaining_rounds": 3,
            "total_rounds": 5,
            "item_prefix": "E",
            "item_categories": {"E1": "core", "E2": "core"},
            "mode": "checklist_gated",
            "cutoff": 7,
            "required": 2,
            "novelty_subagent_enabled": True,
            "critic_subagent_enabled": True,
            "has_existing_answers": True,
        }
        scores = {
            "E1": {"score": 4, "reasoning": "needs work"},
            "E2": {"score": 4, "reasoning": "needs work"},
        }
        # Build checklist_history with 2 rounds of flat scores to trigger
        # per-criterion plateau detection
        checklist_history = [
            {
                "items_detail": [
                    {"id": "E1", "score": 4, "passed": False},
                    {"id": "E2", "score": 4, "passed": False},
                ],
            },
            {
                "items_detail": [
                    {"id": "E1", "score": 4, "passed": False},
                    {"id": "E2", "score": 4, "passed": False},
                ],
            },
        ]
        result = evaluate_checklist_submission(
            scores=scores,
            report_path="",
            items=items,
            state=state,
            checklist_history=checklist_history,
        )
        # Verdict must be new_answer; guidance should mention novelty (not critic)
        assert result.get("verdict") == "new_answer", f"Expected 'new_answer' but got {result.get('verdict')!r}; full result: {result}"
        explanation = result.get("explanation", "")
        assert "plateaued" in explanation.lower(), f"Expected 'plateaued' in explanation: {explanation}"
        assert "novelty" in explanation.lower()
        assert "spawn a `critic`" not in explanation
        assert "spawn two background" not in explanation


# ===========================================================================
# Part C: Evaluation Criteria Revamp
# ===========================================================================


class TestCriteriaTierSystem:
    """Tests for MUST/SHOULD/COULD tier system."""

    def test_generated_criterion_accepts_must(self):
        """GeneratedCriterion accepts 'must' category."""
        from massgen.evaluation_criteria_generator import GeneratedCriterion

        c = GeneratedCriterion(id="E1", text="test", category="must")
        assert c.category == "must"

    def test_generated_criterion_accepts_should(self):
        """GeneratedCriterion accepts 'should' category."""
        from massgen.evaluation_criteria_generator import GeneratedCriterion

        c = GeneratedCriterion(id="E1", text="test", category="should")
        assert c.category == "should"

    def test_generated_criterion_accepts_could(self):
        """GeneratedCriterion accepts 'could' category."""
        from massgen.evaluation_criteria_generator import GeneratedCriterion

        c = GeneratedCriterion(id="E1", text="test", category="could")
        assert c.category == "could"

    def test_backward_compat_core_maps_to_must(self):
        """Parsing 'core' maps to 'must' for backward compatibility."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = '{"criteria": [' '{"text": "t1", "category": "core"},' '{"text": "t2", "category": "core"},' '{"text": "t3", "category": "core"},' '{"text": "t4", "category": "stretch"}' "]}"
        result = _parse_criteria_response(response)
        assert result is not None
        assert result[0].category == "must"
        assert result[1].category == "must"
        assert result[2].category == "must"
        assert result[3].category == "could"

    def test_new_categories_parsed_directly(self):
        """New must/should/could categories are parsed directly."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = '{"criteria": [' '{"text": "t1", "category": "must"},' '{"text": "t2", "category": "must"},' '{"text": "t3", "category": "should"},' '{"text": "t4", "category": "could"}' "]}"
        result = _parse_criteria_response(response)
        assert result is not None
        assert result[0].category == "must"
        assert result[2].category == "should"
        assert result[3].category == "could"


class TestDefaultCriteriaTiers:
    """Tests for default criteria using new tier names."""

    def test_default_categories_use_new_tiers(self):
        """Default categories use must/should/could."""
        from massgen.evaluation_criteria_generator import _DEFAULT_CATEGORIES

        assert "must" in _DEFAULT_CATEGORIES
        # Should have at least one 'could' (was 'stretch')
        assert "could" in _DEFAULT_CATEGORIES

    def test_default_criteria_have_new_tiers(self):
        """get_default_criteria returns criteria with new tier names."""
        from massgen.evaluation_criteria_generator import get_default_criteria

        criteria = get_default_criteria(has_changedoc=False)
        categories = {c.category for c in criteria}
        # Must use new tier names, not old ones
        assert "core" not in categories
        assert "stretch" not in categories
        assert "must" in categories

    def test_default_criteria_include_quality_craft(self):
        """Default criteria always include a quality/craft criterion."""
        from massgen.evaluation_criteria_generator import get_default_criteria

        criteria = get_default_criteria(has_changedoc=False)
        craft = [c for c in criteria if "intentional" in c.text or "craft" in c.text]
        assert len(craft) == 1
        assert craft[0].category == "should"


class TestPresetsTiers:
    """Tests for presets using new tier names."""

    def test_persona_preset_uses_new_tiers(self):
        """Persona preset uses must/should/could."""
        from massgen.evaluation_criteria_generator import _CRITERIA_PRESETS

        categories = {cat for _, cat in _CRITERIA_PRESETS["persona"]}
        assert "core" not in categories
        assert "stretch" not in categories

    def test_decomposition_preset_uses_new_tiers(self):
        """Decomposition preset uses must/should/could."""
        from massgen.evaluation_criteria_generator import _CRITERIA_PRESETS

        categories = {cat for _, cat in _CRITERIA_PRESETS["decomposition"]}
        assert "core" not in categories

    def test_evaluation_preset_uses_new_tiers(self):
        """Evaluation preset uses must/should/could."""
        from massgen.evaluation_criteria_generator import _CRITERIA_PRESETS

        categories = {cat for _, cat in _CRITERIA_PRESETS["evaluation"]}
        assert "core" not in categories

    def test_prompt_preset_uses_new_tiers(self):
        """Prompt preset uses must/should/could."""
        from massgen.evaluation_criteria_generator import _CRITERIA_PRESETS

        categories = {cat for _, cat in _CRITERIA_PRESETS["prompt"]}
        assert "core" not in categories

    def test_analysis_preset_uses_new_tiers(self):
        """Analysis preset uses must/should/could."""
        from massgen.evaluation_criteria_generator import _CRITERIA_PRESETS

        categories = {cat for _, cat in _CRITERIA_PRESETS["analysis"]}
        assert "core" not in categories


class TestGenerationPromptTiers:
    """Tests for the updated generation prompt."""

    def test_generation_prompt_has_must_should_could(self):
        """Generation prompt mentions MUST/SHOULD/COULD tiers."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt("test task", has_changedoc=False)
        assert "MUST" in prompt
        assert "SHOULD" in prompt
        assert "COULD" in prompt

    def test_generation_prompt_has_concrete_examples(self):
        """Generation prompt includes concrete vs abstract examples."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt("test task", has_changedoc=False)
        assert "BAD" in prompt and "abstract" in prompt.lower()
        assert "GOOD" in prompt and "concrete" in prompt.lower()

    def test_generation_prompt_requires_quality_craft(self):
        """Generation prompt requires a quality/craft criterion."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt("test task", has_changedoc=False)
        assert "quality/craft" in prompt.lower() or "overall quality" in prompt.lower()
        assert "mediocre" in prompt.lower()

    def test_generation_prompt_requires_per_part_quality(self):
        """Generation prompt requires per-part quality evaluation."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt("test task", has_changedoc=False)
        lower = prompt.lower()
        # Must mention per-part or per-section quality concept
        assert "per-part" in lower or "each significant part" in lower
        # Must mention evaluating the weakest component, not the average
        assert "weakest" in lower

    def test_generation_prompt_per_part_bad_good_example(self):
        """Generation prompt has BAD/GOOD example for whole-output vs per-part."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt("test task", has_changedoc=False)
        lower = prompt.lower()
        # Must have a BAD example about whole-output criteria
        assert "whole-output" in lower or "whole output" in lower
        # Must have a GOOD example about per-part/per-section criteria
        assert "per-part" in lower or "per-section" in lower

    def test_propose_improvements_example_not_incremental(self):
        """System prompt propose_improvements example shows substantial improvements."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        # The example should NOT contain trivially incremental fixes
        assert "fix font sizes" not in prompt.lower()
        # The example should show rethinking, not pixel tweaks
        assert "propose_improvements" in prompt

    def test_propose_improvements_example_includes_preserve(self):
        """System prompt propose_improvements example includes preserve parameter."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        # preserve should appear in the example call
        assert "preserve" in prompt

    def test_propose_improvements_example_has_sources(self):
        """System prompt propose_improvements example includes sources."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        # sources should appear in the structured improvement example
        assert "sources" in prompt


# ===========================================================================
# Part D: Per-Answer Analysis Across All Evaluation Modes
# ===========================================================================


class TestPerAnswerAnalysis:
    """Per-answer analysis: agents must analyze each answer before deciding."""

    def test_strict_mode_has_per_answer_step(self):
        """Strict evaluation contains per-answer strengths step."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="strict")
        content = section.build_content()
        # Must reference analyzing each answer, not just "the best answer"
        assert "each existing answer" in content.lower() or "per-answer" in content.lower()

    def test_balanced_mode_has_per_answer_step(self):
        """Balanced evaluation contains per-answer analysis."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="balanced")
        content = section.build_content()
        assert "each existing answer" in content.lower() or "per-answer" in content.lower()

    def test_adversarial_mode_has_per_answer_step(self):
        """Adversarial evaluation references multiple answers."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="adversarial")
        content = section.build_content()
        assert "each answer" in content.lower()

    def test_consistency_mode_has_per_answer_step(self):
        """Consistency evaluation references multiple approaches."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="consistency")
        content = section.build_content()
        assert "each answer" in content.lower() or "different approaches" in content.lower()

    def test_reflective_mode_has_per_answer_step(self):
        """Reflective evaluation has per-answer fit analysis."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="reflective")
        content = section.build_content()
        assert "each answer" in content.lower() or "per-answer" in content.lower()

    def test_improve_vary_replaced_with_synthesis(self):
        """New answer strategies mention analyzing each existing answer."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(voting_sensitivity="strict")
        content = section.build_content()
        # Old "Improve/Vary" replaced with synthesis-focused language
        assert "each existing answer" in content.lower()
        # Should have Synthesize and Rethink strategies
        assert "synthesize" in content.lower()
        assert "rethink" in content.lower()

    def test_decision_block_iterate_not_single_base(self):
        """Iterate action says 'each existing answer', not 'from scratch'."""
        from massgen.system_prompt_sections import (
            _build_checklist_decision,
            _build_checklist_scored_decision,
        )

        # Check checklist decision
        result1 = _build_checklist_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=["E1", "E2"],
        )
        assert "each existing answer" in result1.lower()
        assert "from scratch" not in result1.lower()

        # Check checklist_scored decision
        result2 = _build_checklist_scored_decision(
            threshold=5,
            remaining=3,
            total=5,
            checklist_items=["E1", "E2"],
        )
        assert "each existing answer" in result2.lower()
        assert "from scratch" not in result2.lower()

    def test_checklist_flow_per_answer_before_propose(self):
        """Checklist gated prompt has per-answer review before propose_improvements."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        prompt = _build_checklist_gated_decision(
            checklist_items=["Criterion 1", "Criterion 2"],
        )
        lower = prompt.lower()
        # Must have a dedicated per-answer review instruction
        assert "review each existing answer" in lower, "Must have per-answer review step before propose_improvements"
        # The review instruction should appear BEFORE the propose_improvements
        # call instruction (not just the first mention in verdict description)
        review_pos = lower.find("review each existing answer")
        propose_call_pos = lower.find("must call `propose_improvements`")
        assert review_pos < propose_call_pos, "Per-answer review must appear before propose_improvements call"

    def test_evaluating_prior_answers_per_answer(self):
        """Changedoc section has per-answer independent analysis."""
        from massgen.system_prompt_sections import ChangedocSection

        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        # Must analyze each answer independently
        assert "each existing answer" in content.lower() or "each answer" in content.lower()
        # Must ask about unique strengths per answer
        assert "uniquely well" in content.lower() or "does well" in content.lower()
