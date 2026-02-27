"""Tests for ChangedocSection system prompt.

Tests cover:
- Section inclusion/exclusion based on config flags
- First-round vs subsequent-round prompt content
- Final presenter consolidation instructions
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from massgen.system_message_builder import SystemMessageBuilder
from massgen.system_prompt_sections import (
    _CHECKLIST_ITEMS_CHANGEDOC,
    ChangedocSection,
    CoreBehaviorsSection,
    EvaluationSection,
    SubagentSection,
    _build_changedoc_checklist_analysis,
    _build_changedoc_subsequent_round_prompt,
    _build_checklist_analysis,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(system_message="You are a helpful assistant."):
    """Minimal agent stub."""
    backend = MagicMock()
    backend.config = {"model": "gpt-4o-mini"}
    backend.filesystem_manager = None
    backend.backend_params = {}
    backend.mcp_servers = []

    agent = MagicMock()
    agent.get_configurable_system_message.return_value = system_message
    agent.backend = backend
    agent.config = None
    return agent


def _make_config(
    planning_mode_instruction="Plan your approach.",
    enable_changedoc=False,
    broadcast=False,
):
    """Minimal config stub."""
    cc = SimpleNamespace(
        skills_directory=".massgen/skills",
        load_previous_session_skills=False,
        enabled_skill_names=None,
        enable_subagents=False,
        planning_mode_instruction=planning_mode_instruction,
        broadcast=broadcast,
        task_planning_filesystem_mode=False,
        enable_changedoc=enable_changedoc,
    )
    return SimpleNamespace(coordination_config=cc)


def _make_message_templates():
    """Minimal message templates stub."""
    mt = MagicMock()
    mt._voting_sensitivity = "medium"
    mt._answer_novelty_requirement = "moderate"
    mt.final_presentation_system_message.return_value = "Present the best answer."
    return mt


def _make_builder(enable_changedoc=False):
    """Create SystemMessageBuilder with stubs."""
    config = _make_config(enable_changedoc=enable_changedoc)
    mt = _make_message_templates()
    agents = {"agent_a": _make_agent()}
    return SystemMessageBuilder(config=config, message_templates=mt, agents=agents)


# ---------------------------------------------------------------------------
# ChangedocSection unit tests
# ---------------------------------------------------------------------------


class TestChangedocSection:
    """Tests for ChangedocSection prompt content."""

    def test_first_round_content(self):
        """First-round prompt instructs creating tasks/changedoc.md."""
        section = ChangedocSection(has_prior_answers=False)
        content = section.build_content()
        assert "tasks/changedoc.md" in content
        assert "create" in content.lower() or "write" in content.lower()

    def test_subsequent_round_content(self):
        """Subsequent-round prompt instructs inheriting and evolving changedoc."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "inherit" in content.lower() or "build on" in content.lower()
        assert "changedoc" in content.lower()

    def test_first_round_has_template(self):
        """First-round prompt includes the changedoc template structure."""
        section = ChangedocSection(has_prior_answers=False)
        content = section.build_content()
        assert "Change Document" in content
        assert "Decision" in content or "DEC-" in content

    def test_section_metadata(self):
        """Section has correct title and XML tag."""
        section = ChangedocSection()
        assert section.title == "Change Document"
        assert section.xml_tag == "changedoc_instructions"


# ---------------------------------------------------------------------------
# SystemMessageBuilder integration tests
# ---------------------------------------------------------------------------


class TestChangedocInBuildCoordinationMessage:
    """Tests for changedoc section appearing in build_coordination_message."""

    def test_included_when_planning_and_changedoc_enabled(self):
        """ChangedocSection appears when planning_mode + enable_changedoc both True."""
        builder = _make_builder(enable_changedoc=True)
        agent = _make_agent()

        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=True,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        assert "changedoc" in msg.lower()

    def test_present_even_when_planning_disabled(self):
        """ChangedocSection appears even when planning mode is off."""
        builder = _make_builder(enable_changedoc=True)
        agent = _make_agent()

        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        assert "changedoc" in msg.lower()

    def test_absent_when_changedoc_disabled(self):
        """ChangedocSection absent when enable_changedoc=False."""
        builder = _make_builder(enable_changedoc=False)
        agent = _make_agent()

        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=True,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        assert "changedoc_instructions" not in msg

    def test_first_round_when_no_answers(self):
        """Uses first-round instructions when no answers exist."""
        builder = _make_builder(enable_changedoc=True)
        agent = _make_agent()

        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=True,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        # First round: should mention creating changedoc
        assert "tasks/changedoc.md" in msg

    def test_subsequent_round_when_answers_exist(self):
        """Uses subsequent-round instructions when answers are present."""
        builder = _make_builder(enable_changedoc=True)
        agent = _make_agent()

        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers={"agent_b": "Some prior answer"},
            planning_mode_enabled=True,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        # Subsequent round: should mention inheriting
        assert "inherit" in msg.lower() or "build on" in msg.lower()


# ---------------------------------------------------------------------------
# Changedoc-anchored evaluation checklist tests
# ---------------------------------------------------------------------------


class TestChangedocChecklist:
    """Tests for changedoc-anchored evaluation checklist items and analysis."""

    def test_changedoc_checklist_items_count(self):
        """_CHECKLIST_ITEMS_CHANGEDOC has exactly 4 items."""
        assert len(_CHECKLIST_ITEMS_CHANGEDOC) == 4

    def test_changedoc_checklist_items_content(self):
        """Changedoc items mention changedoc, rationale, and traceability."""
        joined = " ".join(_CHECKLIST_ITEMS_CHANGEDOC).lower()
        assert "changedoc" in joined
        assert "rationale" in joined
        assert "traceab" in joined  # traceability or traceable

    def test_changedoc_analysis_has_decision_audit(self):
        """_build_changedoc_checklist_analysis() mentions key steps."""
        analysis = _build_changedoc_checklist_analysis()
        assert "Decision Audit" in analysis
        assert "Failure Patterns" in analysis
        assert "Success Patterns" in analysis

    def test_changedoc_analysis_differs_from_generic(self):
        """Changedoc analysis is distinct from the generic analysis."""
        generic = _build_checklist_analysis()
        changedoc = _build_changedoc_checklist_analysis()
        assert generic != changedoc
        # Changedoc has "Decision Audit", generic does not
        assert "Decision Audit" in changedoc
        assert "Decision Audit" not in generic

    def test_evaluation_section_uses_changedoc_items(self):
        """EvaluationSection(has_changedoc=True) produces changedoc-aware text."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            has_changedoc=True,
        )
        content = section.build_content()
        # Should contain changedoc checklist items, not generic ones
        assert "Decision Completeness" in content or "changedoc" in content.lower()
        assert "Decision Audit" in content
        assert "substantiveness" in content.lower()

    def test_evaluation_section_uses_generic_items(self):
        """EvaluationSection(has_changedoc=False) produces original text."""
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            has_changedoc=False,
        )
        content = section.build_content()
        # Should contain generic items, not changedoc-specific analysis
        assert "Diagnostic Analysis" in content
        assert "Decision Audit" not in content

    def test_system_message_builder_passes_changedoc_flag(self):
        """Builder derives changedoc flag from config and produces changedoc-aware eval."""
        config = _make_config(enable_changedoc=True)
        mt = _make_message_templates()
        mt._voting_sensitivity = "checklist_gated"
        agents = {"agent_a": _make_agent()}
        builder = SystemMessageBuilder(config=config, message_templates=mt, agents=agents)
        agent = _make_agent()

        # Pass a prior answer so round-2+ checklist instructions are shown
        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers={"agent_a": "prior answer"},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        # The coordination section should use changedoc analysis
        assert "Decision Audit" in msg

    def test_system_message_builder_generic_when_changedoc_off(self):
        """Builder without changedoc uses generic checklist."""
        config = _make_config(enable_changedoc=False)
        mt = _make_message_templates()
        mt._voting_sensitivity = "checklist_gated"
        agents = {"agent_a": _make_agent()}
        builder = SystemMessageBuilder(config=config, message_templates=mt, agents=agents)
        agent = _make_agent()

        # Pass a prior answer so round-2+ checklist instructions are shown
        msg = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers={"agent_a": "prior answer"},
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
        )

        # The coordination section should use generic analysis (GEPA-style diagnostics)
        assert "Failure Patterns" in msg or "Root Causes" in msg
        assert "Decision Audit" not in msg


# ---------------------------------------------------------------------------
# Changedoc prompt answer label tests
# ---------------------------------------------------------------------------


class TestChangedocAnswerLabels:
    """Tests that changedoc prompt references answer labels from CURRENT ANSWERS."""

    def test_changedoc_prompt_mentions_answer_labels_in_headers(self):
        """Changedoc guidance tells agents labels are visible in CURRENT ANSWERS headers."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        # Should mention that labels appear in <CURRENT ANSWERS> headers
        assert "CURRENT ANSWERS" in content
        assert "agent1." in content  # versioned label example like agent1.2


class TestSelfPlaceholderInPrompts:
    """Tests that changedoc prompts use [SELF] for self-references."""

    def test_first_round_template_uses_self_placeholder(self):
        """First-round changedoc prompt uses [SELF] for the agent's own origin."""
        section = ChangedocSection(has_prior_answers=False)
        content = section.build_content()
        assert "[SELF]" in content
        # Should NOT use [your answer label] anymore
        assert "[your answer label]" not in content

    def test_subsequent_round_template_uses_self_placeholder(self):
        """Subsequent-round changedoc prompt uses [SELF] in template examples."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        assert "[SELF]" in content
        # Should NOT use [your label] anymore
        assert "[your label]" not in content

    def test_subsequent_round_explains_self_placeholder(self):
        """Subsequent-round prompt explains that [SELF] is replaced by the system."""
        section = ChangedocSection(has_prior_answers=True)
        content = section.build_content()
        # Should explain the replacement mechanism
        assert "replace" in content.lower() or "substitut" in content.lower()


# ---------------------------------------------------------------------------
# Changedoc analysis improvement tests (Area 1)
# ---------------------------------------------------------------------------


class TestChangedocAnalysisImprovements:
    """Tests for changedoc analysis prompt improvements."""

    def test_analysis_contains_substantiveness_test(self):
        """Changedoc analysis includes substantiveness classification step."""
        analysis = _build_changedoc_checklist_analysis()
        assert "TRANSFORMATIVE" in analysis
        assert "STRUCTURAL" in analysis
        assert "INCREMENTAL" in analysis

    def test_analysis_contains_convergence_awareness(self):
        """Analysis includes convergence awareness — same approach detection."""
        analysis = _build_changedoc_checklist_analysis()
        assert "converging" in analysis.lower() or "same basic" in analysis.lower()

    def test_analysis_contains_subtractive_improvement(self):
        """Fresh Approach section mentions subtractive improvement possibility."""
        analysis = _build_changedoc_checklist_analysis()
        assert "fewer" in analysis.lower() or "restraint" in analysis.lower()

    def test_subsequent_prompt_contains_dec_inflation_guidance(self):
        """Subsequent round changedoc prompt warns against DEC inflation."""
        from massgen.system_prompt_sections import (
            _build_changedoc_subsequent_round_prompt,
        )

        prompt = _build_changedoc_subsequent_round_prompt()
        # Should mention quality over quantity for decisions
        assert "remove" in prompt.lower() or "merge" in prompt.lower()
        assert "deeply" in prompt.lower() or "depth" in prompt.lower()

    def test_analysis_no_longer_takes_has_prior_answers(self):
        """T5 guidance now lives in the checklist item itself, not the analysis."""
        # The function should work with no arguments
        analysis = _build_changedoc_checklist_analysis()
        # Should still contain substantiveness classification
        assert "TRANSFORMATIVE" in analysis
        assert "STRUCTURAL" in analysis
        assert "INCREMENTAL" in analysis

    def test_subsequent_prompt_checklist_before_implementation(self):
        """Subsequent round workflow must instruct checklist evaluation BEFORE implementation."""
        from massgen.system_prompt_sections import (
            _build_changedoc_subsequent_round_prompt,
        )

        prompt = _build_changedoc_subsequent_round_prompt()
        lower = prompt.lower()
        # Must mention evaluating/checklist before making edits
        assert "submit_checklist" in lower or "checklist" in lower
        # The workflow must make clear: evaluate first, implement only after verdict
        normalized = " ".join(lower.split())
        assert "before making any edits" in normalized or "before implementing" in normalized or "before you start building" in normalized

    def test_subsequent_prompt_requires_output_changes_with_changedoc(self):
        """Subsequent round prompt must state changedoc changes require output changes."""
        from massgen.system_prompt_sections import (
            _build_changedoc_subsequent_round_prompt,
        )

        prompt = _build_changedoc_subsequent_round_prompt()
        lower = prompt.lower()
        assert "changedoc alone" in lower or "changedoc changes must accompany" in lower

    def test_key_changes_section_specifies_output(self):
        """Key Changes section must reference output/deliverable, not just any changes."""
        from massgen.system_prompt_sections import (
            _build_changedoc_subsequent_round_prompt,
        )

        prompt = _build_changedoc_subsequent_round_prompt()
        assert "Key Output Changes" in prompt


# ---------------------------------------------------------------------------
# Quality Assessment in changedoc tests (Area 2d)
# ---------------------------------------------------------------------------


class TestQualityAssessmentInChangedoc:
    """Tests for Quality Assessment section in changedoc subsequent-round prompt."""

    def test_subsequent_prompt_with_changedoc_mode_has_open_gaps(self):
        """gap_report_mode='changedoc' includes Open Gaps in subsequent prompt."""
        prompt = _build_changedoc_subsequent_round_prompt(gap_report_mode="changedoc")
        assert "## Open Gaps" in prompt
        assert "not a todo list" in prompt.lower() or "not directives" in prompt.lower()
        # Quality Assessment was replaced by Open Gaps
        assert "Already Strong" not in prompt
        assert "Worth Another Iteration" not in prompt

    def test_subsequent_prompt_with_separate_mode_no_open_gaps(self):
        """gap_report_mode='separate' omits Open Gaps from subsequent prompt."""
        prompt = _build_changedoc_subsequent_round_prompt(gap_report_mode="separate")
        assert "## Open Gaps" not in prompt

    def test_subsequent_prompt_with_none_mode_no_open_gaps(self):
        """gap_report_mode='none' omits Open Gaps from subsequent prompt."""
        prompt = _build_changedoc_subsequent_round_prompt(gap_report_mode="none")
        assert "## Open Gaps" not in prompt

    def test_changedoc_section_passes_gap_report_mode(self):
        """ChangedocSection uses gap_report_mode parameter for subsequent round."""
        section = ChangedocSection(has_prior_answers=True, gap_report_mode="changedoc")
        content = section.build_content()
        assert "Open Gaps" in content

        section_separate = ChangedocSection(has_prior_answers=True, gap_report_mode="separate")
        content_separate = section_separate.build_content()
        assert "Open Gaps" not in content_separate


# ---------------------------------------------------------------------------
# Gap report mode in decision section tests (Area 2e)
# ---------------------------------------------------------------------------


class TestGapReportModeInDecision:
    """Tests for gap_report_mode in _build_checklist_gated_decision."""

    def test_gated_decision_changedoc_mode_requires_separate_report(self):
        """gap_report_mode='changedoc' still requires separate diagnostic report."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        decision = _build_checklist_gated_decision(
            checklist_items=["Check 1", "Check 2"],
            gap_report_mode="changedoc",
        )
        # Should require a diagnostic report separate from changedoc
        assert "diagnostic report" in decision.lower()
        assert "separate from your changedoc" in decision.lower()
        assert "report_path" in decision

    def test_gated_decision_separate_mode_requires_report(self):
        """gap_report_mode='separate' requires diagnostic report file."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        decision = _build_checklist_gated_decision(
            checklist_items=["Check 1"],
            gap_report_mode="separate",
        )
        assert "diagnostic report" in decision.lower()
        assert "report_path" in decision

    def test_gated_decision_none_mode_no_report(self):
        """gap_report_mode='none' has no report requirement section."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        decision = _build_checklist_gated_decision(
            checklist_items=["Check 1"],
            gap_report_mode="none",
        )
        # Should not have a Gap Report or Quality Assessment section header
        assert "### Gap Report" not in decision
        assert "### Quality Assessment" not in decision


# ---------------------------------------------------------------------------
# Anti-glazing, synthesis, and origin chain tests
# ---------------------------------------------------------------------------


class TestAntiGlazingAndSynthesis:
    """Tests for anti-glazing, multi-source synthesis, and origin chain changes."""

    def test_substantiveness_has_not_structural_examples(self):
        """Substantiveness test includes concrete 'NOT structural' examples."""
        analysis = _build_changedoc_checklist_analysis()
        assert "do not upgrade" in analysis.lower()
        assert "CSS tweaks" in analysis

    def test_analysis_anti_glazing(self):
        """Analysis framework focuses on failures over praise."""
        analysis = _build_changedoc_checklist_analysis()
        # The diagnostic framework discourages overly generous reviews
        assert "too generous" in analysis

    def test_analysis_focuses_on_failures(self):
        """Analysis framework focuses on identifying failures, not praising."""
        analysis = _build_changedoc_checklist_analysis()
        # The GEPA diagnostic framework is failure-focused
        assert "Failure Patterns" in analysis
        assert "too generous" in analysis

    def test_open_gaps_replaces_quality_assessment(self):
        """Open Gaps replaces Quality Assessment — no glazing sections remain."""
        prompt = _build_changedoc_subsequent_round_prompt(gap_report_mode="changedoc")
        assert "## Open Gaps" in prompt
        assert "Already Strong" not in prompt
        assert "Quality Assessment" not in prompt

    def test_open_gaps_not_directives(self):
        """Open Gaps section clarifies gaps are not a todo list for next agent."""
        prompt = _build_changedoc_subsequent_round_prompt(gap_report_mode="changedoc")
        assert "not directives" in prompt.lower() or "not a todo list" in prompt.lower()

    def test_subsequent_prompt_uses_sources_reviewed(self):
        """Subsequent round template uses 'Sources reviewed' not 'Based on'."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "Sources reviewed" in prompt
        # "Based on:" should NOT appear in the template header
        # (it may appear in deliberation trail context, but not as the header field)
        assert "**Based on:**" not in prompt

    def test_origin_chain_arrow_notation(self):
        """Template DEC examples use arrow chain notation for origin tracking."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "\u2192" in prompt  # → character

    def test_evaluating_not_inheriting(self):
        """Section heading says 'Evaluating' not 'Inheriting'."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "Evaluating prior answers" in prompt
        assert "Inheriting from prior answers" not in prompt

    def test_deliberation_trail_multi_source(self):
        """Deliberation trail template shows multi-source synthesis."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "synthesized from" in prompt

    def test_e4_polish_and_craft(self):
        """E4 checklist item covers care beyond correctness."""
        from massgen.system_prompt_sections import _CHECKLIST_ITEMS_CHANGEDOC

        e4_text = _CHECKLIST_ITEMS_CHANGEDOC[3]  # 0-indexed, E4 is the 4th item
        assert "beyond correctness" in e4_text.lower() or "creative" in e4_text.lower()

    def test_subsequent_prompt_has_rationale_preservation_rule(self):
        """Subsequent-round prompt must contain Rationale Preservation Rule."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "Rationale Preservation Rule" in prompt
        assert "Synthesis Note" in prompt
        assert "FORBIDDEN" in prompt

    def test_subsequent_prompt_forbids_meta_justification_in_why(self):
        """Rationale Preservation Rule forbids replacing Why with meta-justification."""
        prompt = _build_changedoc_subsequent_round_prompt()
        assert "this was the best prior answer" in prompt

    def test_changedoc_accuracy_requirement_in_t3(self):
        """T3 checklist item must emphasize accuracy — Implementation fields describe what ACTUALLY EXISTS."""
        from massgen.system_prompt_sections import _CHECKLIST_ITEMS_CHANGEDOC

        t3_text = _CHECKLIST_ITEMS_CHANGEDOC[2]  # 0-indexed, T3 is the 3rd item
        lower = t3_text.lower()
        # Must warn about fabrication or require verification of actual existence
        assert "actually exist" in lower or "fabricat" in lower or "verified" in lower or "must exist" in lower, f"T3 must emphasize that implementation references must actually exist. Got: {t3_text}"

    def test_first_round_changedoc_verification_step(self):
        """First-round changedoc workflow must include a verification step."""
        section = ChangedocSection(has_prior_answers=False)
        content = section.build_content()
        lower = content.lower()
        # Must mention verifying that implementation fields are accurate
        assert "verify" in lower or "confirm" in lower, "First-round changedoc must include verification of implementation accuracy"

    def test_subsequent_round_changedoc_verification_step(self):
        """Subsequent-round changedoc workflow must include a verification step."""
        prompt = _build_changedoc_subsequent_round_prompt()
        lower = prompt.lower()
        # Must mention verifying implementation fields match actual output
        assert "verify" in lower or "confirm" in lower, "Subsequent-round changedoc must include verification of implementation accuracy"

    def test_changedoc_analysis_flags_fabrication(self):
        """Changedoc analysis Implementation accuracy check must flag fabricated claims."""
        analysis = _build_changedoc_checklist_analysis()
        lower = analysis.lower()
        # Must warn about documenting features that don't exist
        assert "fabricat" in lower or "does not exist" in lower or "actually exist" in lower or "not actually" in lower, "Changedoc analysis must flag fabricated implementation claims"

    def test_fewer_decisions_guidance_scoped_to_changedoc(self):
        """'Fewer, stronger decisions' guidance must clarify it refers to changedoc quality, not output scope."""
        prompt = _build_changedoc_subsequent_round_prompt()
        lower = " ".join(prompt.lower().split())
        # Must still have the fewer/stronger guidance
        assert "fewer" in lower and "stronger" in lower
        # The fewer/stronger paragraph must clarify it does NOT limit the scope of output work.
        # Find the paragraph with "fewer" and check it has a clarification
        fewer_idx = lower.index("fewer")
        # Check within a ~300 char window around the "fewer" mention
        context_window = lower[max(0, fewer_idx - 100) : fewer_idx + 300]
        assert "does not limit" in context_window or "not about limiting" in context_window or "scope of output" in context_window


# ---------------------------------------------------------------------------
# Output integrity: working output before adding features (Area 3)
# ---------------------------------------------------------------------------


class TestOutputIntegrityPrinciple:
    """Tests that system prompts emphasize working output over feature accumulation."""

    def test_e1_requires_goal_alignment(self):
        """E1 checklist item must require the output achieves what was asked for."""
        e1_text = _CHECKLIST_ITEMS_CHANGEDOC[0]  # 0-indexed, E1 is the 1st item
        lower = e1_text.lower()
        assert "achieves" in lower or "requirements" in lower or "asked for" in lower, f"E1 must require goal alignment. Got: {e1_text}"

    def test_decision_section_verify_before_extend(self):
        """Decision/improvement section must instruct verifying existing before adding new."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        decision = _build_checklist_gated_decision(
            checklist_items=_CHECKLIST_ITEMS_CHANGEDOC,
            gap_report_mode="changedoc",
        )
        lower = decision.lower()
        assert (
            "verify" in lower or "existing features" in lower or "before adding" in lower or "already works" in lower or "working output" in lower
        ), "Decision section must instruct agents to verify existing functionality before adding features"

    def test_changedoc_analysis_has_output_integrity_check(self):
        """Changedoc analysis gap section must check output integrity (does it actually work)."""
        analysis = _build_changedoc_checklist_analysis()
        lower = analysis.lower()
        assert (
            "broken" in lower or "internally consistent" in lower or "actually work" in lower or "output integrity" in lower or "still function" in lower
        ), "Changedoc analysis must check whether the output actually works, not just has features"


# ---------------------------------------------------------------------------
# E-Criterion Anchoring in Diagnostic Sections
# ---------------------------------------------------------------------------


class TestECriterionAnchoring:
    """Diagnostic analysis sections must instruct agents to anchor findings to E criteria.

    Like GEPA's per-aspect ASI (each VISUAL_ASPECT gets its own diagnostic data),
    MassGen's diagnostic sections should reference E1-EN criteria so identified gaps
    don't get lost between analysis and scoring.
    """

    def test_generic_analysis_references_e_criteria(self):
        """Generic analysis framework must instruct anchoring to E criteria."""
        analysis = _build_checklist_analysis()
        assert "E1" in analysis or "E-criterion" in analysis.lower() or "evaluation criteria" in analysis.lower()

    def test_changedoc_analysis_references_e_criteria(self):
        """Changedoc analysis framework must instruct anchoring to E criteria."""
        analysis = _build_changedoc_checklist_analysis()
        assert "E1" in analysis or "E-criterion" in analysis.lower() or "evaluation criteria" in analysis.lower()

    def test_generic_failure_patterns_anchor_to_criteria(self):
        """Failure Patterns section must instruct mapping failures to E criteria."""
        analysis = _build_checklist_analysis()
        # Find the Failure Patterns section and check it references criteria
        fp_start = analysis.index("Failure Patterns")
        # Next section starts with ###
        next_section = analysis.index("###", fp_start + 1)
        fp_section = analysis[fp_start:next_section]
        lower = fp_section.lower()
        assert "e1" in lower or "criterion" in lower or "evaluation criteria" in lower, "Failure Patterns must instruct agents to map failures to E criteria"

    def test_changedoc_failure_patterns_anchor_to_criteria(self):
        """Changedoc Failure Patterns section must instruct mapping failures to E criteria."""
        analysis = _build_changedoc_checklist_analysis()
        fp_start = analysis.index("Failure Patterns")
        next_section = analysis.index("###", fp_start + 1)
        fp_section = analysis[fp_start:next_section]
        lower = fp_section.lower()
        assert "e1" in lower or "criterion" in lower or "evaluation criteria" in lower, "Changedoc Failure Patterns must instruct agents to map failures to E criteria"

    def test_generic_goal_alignment_anchors_to_criteria(self):
        """Goal Alignment section must reference E criteria for scoring alignment."""
        analysis = _build_checklist_analysis()
        ga_start = analysis.index("Goal Alignment")
        next_section = analysis.index("###", ga_start + 1)
        ga_section = analysis[ga_start:next_section]
        lower = ga_section.lower()
        assert "e1" in lower or "criterion" in lower or "score" in lower, "Goal Alignment must connect findings to criteria for scoring"

    def test_diagnostic_report_section_anchors_to_criteria(self):
        """Diagnostic report instructions must require E-criterion references."""
        from massgen.system_prompt_sections import _build_checklist_gated_decision

        # Use dummy items to get the decision section
        items = ["Requirement A", "Requirement B"]
        result = _build_checklist_gated_decision(
            checklist_items=items,
            iterate_action="new_answer",
            terminate_action="terminate_discussion",
            gap_report_mode="separate",
        )
        lower = result.lower()
        assert "e1" in lower or "criterion" in lower or "evaluation criteria" in lower, "Diagnostic report instructions must reference E criteria"

    def test_analysis_shows_e_criterion_example_format(self):
        """Analysis sections should show example format of E-criterion anchoring."""
        analysis = _build_checklist_analysis()
        # Should have an example like "E1 (..." or "E2 (" showing the pattern
        assert "E1" in analysis and "E2" in analysis, "Analysis must show example E-criterion references (E1, E2, etc.)"


# ---------------------------------------------------------------------------
# Context Window Persistence Guidance
# ---------------------------------------------------------------------------


class TestContextWindowPersistence:
    """Core behaviors must include guidance on persisting through context compaction."""

    def test_core_behaviors_has_context_compaction_guidance(self):
        """CoreBehaviorsSection must tell agents not to stop early due to token budget."""
        section = CoreBehaviorsSection()
        content = section.build_content()
        lower = content.lower()
        assert "compact" in lower or "context window" in lower or "token budget" in lower

    def test_core_behaviors_says_do_not_stop_early(self):
        """CoreBehaviorsSection must instruct agents to not stop tasks early."""
        section = CoreBehaviorsSection()
        content = section.build_content()
        lower = content.lower()
        assert "do not stop" in lower or "never" in lower and "stop" in lower

    def test_core_behaviors_says_save_progress(self):
        """CoreBehaviorsSection must instruct agents to save progress before compaction."""
        section = CoreBehaviorsSection()
        content = section.build_content()
        lower = content.lower()
        assert "save" in lower and ("progress" in lower or "state" in lower or "memory" in lower)


# ---------------------------------------------------------------------------
# Evaluation Delegation via Subagents
# ---------------------------------------------------------------------------


def _subagent_content():
    """Helper: build SubagentSection content with default args."""
    return SubagentSection(workspace_path="/tmp/workspace", max_concurrent=3).build_content()


class TestEvaluationDelegation:
    """SubagentSection must guide agents to delegate procedural evaluation work."""

    def test_subagent_section_has_evaluation_delegation(self):
        """SubagentSection must include evaluation delegation pattern."""
        content = _subagent_content()
        lower = content.lower()
        assert "evaluation" in lower or "testing" in lower and "delegat" in lower

    def test_evaluation_delegation_mentions_async(self):
        """Evaluation delegation pattern must recommend async mode."""
        content = _subagent_content()
        lower = content.lower()
        assert "async" in lower and ("evaluation" in lower or "testing" in lower)

    def test_evaluation_delegation_describes_role_split(self):
        """Must describe what subagent does (procedural) vs main agent (analytical)."""
        content = _subagent_content()
        lower = content.lower()
        # Subagent handles procedural: screenshots, tests, serving
        assert "screenshot" in lower or "procedural" in lower or "read_media" in lower
        # Main agent handles analytical: judgment, decisions
        assert "judgment" in lower or "analyz" in lower or "decision" in lower

    def test_evaluation_delegation_mentions_batch_programmatic_runs(self):
        """Should explicitly call out batch/high-volume execution scenarios for evaluator delegation."""
        content = _subagent_content()
        lower = content.lower()
        assert "batch" in lower or "high-volume" in lower
        assert "playwright" in lower
        assert "screenshot" in lower
        assert "test suite" in lower or "test matrix" in lower

    def test_subagent_returns_descriptive_not_judgments(self):
        """Must clarify subagents return descriptions/observations, not high-level judgments."""
        content = _subagent_content()
        lower = content.lower()
        assert "descri" in lower and ("observ" in lower or "finding" in lower or "report" in lower)

    def test_background_lifecycle_guidance(self):
        """Subagent section must describe the background subagent lifecycle."""
        content = _subagent_content()
        lower = content.lower()
        assert "background subagent lifecycle" in lower
        assert "list_subagents" in lower
        assert "send_message_to_subagent" in lower
        assert "continue_subagent" in lower

    def test_subagent_section_documents_workspace_access(self):
        """Subagent guidance must document workspace access model."""
        content = _subagent_content()
        lower = content.lower()
        # include_parent_workspace is the primary field (auto-mounts parent read-only)
        assert "include_parent_workspace" in lower
        assert "auto-mounted" in lower or "auto-mount" in lower
        assert "read-only" in lower or "read only" in lower
        # context_paths is optional for additional paths
        assert "context_paths" in lower
        assert "parent workspace" in lower
