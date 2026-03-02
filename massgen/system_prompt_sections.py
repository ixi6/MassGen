"""
System Prompt Section Architecture

This module implements a class-based architecture for building structured,
prioritized system prompts. Each section encapsulates specific instructions
with explicit priority levels, enabling better attention management and
maintainability.

Design Document: docs/dev_notes/system_prompt_architecture_redesign.md
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# ---------------------------------------------------------------------------
# ROI evaluation shared helpers
#
# Design principles:
#   1. Threshold changes the EVALUATION LENS, not just a gate on a fixed score.
#      Low threshold -> high quality bar -> agent is more critical -> iterates more.
#      High threshold -> low quality bar -> agent is more lenient -> iterates less.
#   2. Remaining budget (answer slots) scales willingness to iterate.
#      More slots left -> slightly lower bar -> more willing to spend a slot.
# ---------------------------------------------------------------------------

_ROI_RUBRIC = """\
- Correctness & completeness — requirements met, edge cases handled?
- Depth & insight — thorough or surface-level?
- Robustness — error handling, validation, defensive coding (if code)?
- Polish & style — clarity, readability, documentation, formatting?
- Testing & verification — claims verified, code tested?

Be a tough grader. A first draft that merely works is a 6. A polished, production-ready answer is a 9."""


def _threshold_to_quality_bar(threshold: int) -> float:
    """Map a voting threshold (0-100) to a quality bar (1-10 scale).

    Low threshold  -> high bar -> iterate more.
    High threshold -> low bar  -> iterate less.

    Examples:
        threshold  5 -> bar 9.8  (perfectionist)
        threshold 15 -> bar 9.2  (high standard)
        threshold 30 -> bar 8.5  (solid)
        threshold 60 -> bar 7.0  (good enough)
        threshold 90 -> bar 5.5  (only fix obvious problems)
    """
    return round(max(5.0, min(10.0, 10.0 - (threshold / 20))), 1)


def _build_budget_line(
    quality_bar: float,
    answers_used: int,
    answer_cap: int | None,
) -> tuple[float, str]:
    """Compute effective quality bar + budget text given remaining answer slots.

    Returns (effective_bar, budget_text).  budget_text is empty when cap is None.
    """
    if answer_cap is None:
        return quality_bar, ""
    remaining = max(0, answer_cap - answers_used)
    budget_fraction = remaining / answer_cap if answer_cap > 0 else 0
    budget_bonus = round(budget_fraction * 0.5, 1)  # up to 0.5 bar reduction
    effective_bar = round(quality_bar - budget_bonus, 1)
    text = (
        f"\n\n**Budget:** You have used {answers_used} of "
        f"{answer_cap} answer slots ({remaining} remaining). "
        f"With {remaining} slots left, your effective quality bar is "
        f"**{effective_bar}/10** (base {quality_bar} adjusted for remaining budget)."
    )
    return effective_bar, text


def build_roi_decision_block(
    threshold: int,
    answers_used: int = 0,
    answer_cap: int | None = None,
    *,
    iterate_action: str = "new_answer",
    satisfied_action: str = "vote",
    satisfied_detail: str = "for the answer with the strongest overall scores",
) -> str:
    """Build the complete ROI rubric + decision rule block.

    Used by both EvaluationSection (vote/new_answer) and
    DecompositionSection (stop/new_answer).
    """
    quality_bar = _threshold_to_quality_bar(threshold)
    quality_bar, budget_line = _build_budget_line(quality_bar, answers_used, answer_cap)

    return f"""**Step 1: Rate EACH answer on ALL dimensions (1-10 each):**
{_ROI_RUBRIC}

Score every answer separately. Note which answer handles each dimension best —
this tells you what already exists and is worth keeping vs. what needs to be built.

**Step 2: Check against the quality bar.**
Your quality bar is **{quality_bar}/10**. For each dimension, look at the
**best score across all answers**. If any dimension's best score is still below
the bar, no existing answer has solved that gap yet — you SHOULD iterate.

**Decision Rule:**
- Any dimension's best score < {quality_bar} -> `{iterate_action}` (a real gap exists that no answer fills)
- All dimensions have at least one answer >= {quality_bar} -> `{satisfied_action}` {satisfied_detail}

A good first draft is rarely perfect. Look for what can be *better*, not just what is *wrong*.{budget_line}"""


# ---------------------------------------------------------------------------
# Checklist evaluation shared helpers
#
# Design principles:
#   1. Threshold changes propensity to iterate (P1).
#   2. Remaining budget scales willingness to iterate (P2).
#   3. Good unique content triggers synthesis (P3).
#
# Two modes share this infrastructure:
#   - checklist:        binary TRUE/FALSE, visible required_true
#   - checklist_scored: 0-100% confidence, visible cutoff + required_true
# ---------------------------------------------------------------------------

_CHECKLIST_ITEMS = [
    ("The output directly achieves what was asked for — requirements are met," " not just approximated. Missing or partially implemented requirements" " count as failures."),
    ("No broken functionality, errors, or obvious defects. Everything that's" " present works correctly. A working output with fewer features beats a" " broken one with more."),
    ("The output is thorough — no significant gaps, thin sections, or" " placeholder content. Each component has enough depth to be genuinely" " useful, not just present."),
    ("The output shows care beyond correctness — thoughtful choices," " consistent style, attention to edge cases, or creative elements that" " distinguish it from adequate work."),
    (
        "The output reflects intentional, thoughtful choices — not just"
        " minimum viable execution. A knowledgeable person in this domain"
        " would recognize craft, not just correctness. The whole feels"
        " cohesive and considered, not assembled from adequate parts."
    ),
]

# Category tags for default checklist items: "must", "should", or "could"
_CHECKLIST_ITEM_CATEGORIES = {
    "E1": "must",
    "E2": "must",
    "E3": "should",
    "E4": "could",
    "E5": "should",  # quality/craft — always present
}

_CHECKLIST_ITEMS_CHANGEDOC = [
    ("The output directly achieves what was asked for — requirements are met," " not just approximated. Missing or partially implemented requirements" " count as failures."),
    ("No broken functionality, errors, or obvious defects. Everything that's" " present works correctly. A working output with fewer features beats a" " broken one with more."),
    (
        "Changedoc is honest, complete, and traceable. Every significant"
        " decision is documented with genuine rationale. Implementation"
        " references point to code that actually exists. No fabricated claims."
        " Gaps from all sources — this answer's own changedoc, other agents'"
        " answers, and other agents' changedocs — are addressed or explicitly"
        " justified. Critical gaps that persist unaddressed are a failure."
    ),
    ("The output shows care beyond correctness — thoughtful choices," " consistent style, attention to edge cases, or creative elements that" " distinguish it from adequate work."),
]

# Category tags for changedoc checklist items
_CHECKLIST_ITEM_CATEGORIES_CHANGEDOC = {
    "E1": "must",
    "E2": "must",
    "E3": "must",
    "E4": "could",
}


def _checklist_budget_context(remaining: int, total: int) -> str:
    """Generate budget context string for checklist modes."""
    if total <= 0:
        return "Budget is exhausted."
    ratio = remaining / total
    if remaining <= 1:
        return "This is your last answer slot. Only use new_answer if the improvement would be substantial."
    elif remaining <= 2:
        return f"Budget is very tight ({remaining}/{total} slots remain). Set a high bar for new_answer."
    elif ratio <= 0.4:
        return f"Budget is limited ({remaining}/{total} slots remain). Be judicious about using new_answer."
    elif ratio >= 0.7:
        return f"Budget is ample ({remaining}/{total} slots remain). Don't hesitate to use new_answer if warranted."
    else:
        return f"Budget is moderate ({remaining}/{total} slots remain)."


def _checklist_effective_threshold(T: int, remaining: int, total: int) -> int:
    """Compute budget-adjusted effective threshold (0-10)."""
    et = T
    if total > 0:
        ratio = remaining / total
        if remaining <= 2:
            et += 2
        elif ratio <= 0.4:
            et += 1
        if ratio >= 0.7:
            et -= 1
    return max(0, min(10, et))


def _checklist_required_true(effective_threshold: int, num_items: int = 4) -> int:
    """How many TRUE items needed to justify vote/stop.

    Relaxes with higher thresholds so agents can pass via quality
    instead of only stopping when hitting max_new_answers_per_agent.

    - Floor: max(1, (num_items + 1) // 2) — e.g. 2 for 4 items
    - Formula: max(floor, num_items - effective_threshold // 30)
    - At threshold 0:  max(2, 4-0) = 4 (strict)
    - At threshold 50: max(2, 4-1) = 3
    - At threshold 70+: max(2, 4-2) = 2 (lenient)
    """
    floor = max(1, (num_items + 1) // 2)
    relaxation = effective_threshold // 30
    return max(floor, num_items - relaxation)


def _checklist_confidence_cutoff(effective_threshold: int) -> int:
    """Minimum confidence score (0-10) for a score to count as TRUE."""
    return max(4, int(10 - effective_threshold * 0.5))


def _build_criteria_failure_bullets(
    custom_checklist_items: list[str] | None = None,
    item_verify_by: dict[str, str] | None = None,
) -> str:
    """Build failure-pattern bullets from criteria list.

    When custom items are provided, generates E1/E2/... bullets with short
    labels derived from the first ~60 chars of each criterion text.
    If item_verify_by is provided, appends a verification hint for criteria
    that require non-textual evidence.
    Otherwise returns the hardcoded generic labels.
    """
    if custom_checklist_items:
        lines = []
        for i, text in enumerate(custom_checklist_items):
            label = text[:60].rstrip(" .,—-")
            eid = f"E{i + 1}"
            vb = (item_verify_by or {}).get(eid)
            vb_hint = f" [verify: {vb}]" if vb else ""
            lines.append(f"- **{eid} ({label}{vb_hint})**: Gaps or failures against this criterion?")
        return "\n".join(lines)
    return (
        "- **E1 (goal alignment)**: Requirements missing or only partially met?\n"
        "- **E2 (correctness)**: Broken behavior, wrong results, regressions?\n"
        "- **E3+ (remaining criteria)**: Quality gaps against each remaining criterion?"
    )


def _build_changedoc_failure_bullets(
    custom_checklist_items: list[str] | None = None,
    item_verify_by: dict[str, str] | None = None,
) -> str:
    """Build changedoc-specific failure-pattern bullets.

    When custom items are provided, uses dynamic labels. Otherwise uses the
    default changedoc labels (goal alignment, correctness, changedoc quality,
    alignment, remaining criteria).
    """
    if custom_checklist_items:
        return _build_criteria_failure_bullets(custom_checklist_items, item_verify_by)
    return (
        "- **E1 (goal alignment)**: Output failures — what doesn't work? What produces wrong\n"
        "  results? What would a demanding user be disappointed by?\n"
        "- **E2 (correctness)**: Regression failures — does the deliverable actually work\n"
        "  end-to-end? Are features from earlier rounds still functioning? A working output\n"
        "  with fewer features beats a broken output with more.\n"
        "- **E3 (changedoc quality)**: Which decisions have thin rationale? Which alternatives\n"
        "  are strawmen? Which Implementation fields are vague, incorrect, or fabricated?\n"
        "- **E3 (alignment)**: Where did the code drift from documented decisions? What was\n"
        "  built but never decided? What was decided but poorly implemented?\n"
        "- **E4+ (remaining criteria)**: Quality gaps against each remaining criterion?"
    )


def _build_checklist_analysis(
    custom_checklist_items: list[str] | None = None,
    item_verify_by: dict[str, str] | None = None,
) -> str:
    """Build GEPA-style diagnostic analysis section for checklist modes.

    Uses structured diagnostic feedback (failure patterns, success patterns,
    root causes, goal alignment) instead of abstract critique. This produces
    more actionable evaluation that tells agents *why* something failed, not
    just *that* it failed.

    The analysis handles both N=1 and N>1 in a single template.
    """
    failure_bullets = _build_criteria_failure_bullets(custom_checklist_items, item_verify_by)
    return f"""## Diagnostic Analysis

Complete your full analysis before reading the Decision section below. Do not let
the decision criteria influence your assessment.

**Anchor every finding to evaluation criteria.** For each failure, success, or root
cause, reference the specific E-criterion it affects (E1, E2, E3, etc.). This
prevents gaps from getting lost between analysis and scoring.

### Failure Patterns

What specific errors, gaps, or broken functionality exist in each answer?
Be concrete — "login form has no error states" not "could be better."

For each answer, map failures to the evaluation criteria they violate:
{failure_bullets}

Example format:
- E1: Missing mobile navigation = core requirement unmet
- E2: Search returns stale results after filter change = broken behavior
- E3: No real images, placeholder text in hero section = depth gap

If an answer has no meaningful failures, say so explicitly — but this should be
rare. First attempts almost always have significant gaps.
If you cannot find meaningful failures, your review is probably too generous.

**Evidence-Based Findings:** If you used read_media to evaluate the output,
include its key findings here. If read_media flagged fundamental issues with
the approach, these belong in root causes — not just surface notes.

### Success Patterns

What works well and MUST be preserved in any revision? Regression on these is
worse than not improving.

For each answer, identify strengths by criterion:
- Which E-criteria are well-satisfied? What makes them strong?
- **Unique contributions**: What does this answer do well that others don't?
- **Preservation priority**: What would be most damaging to lose in a revision?

This section exists to prevent the round-2-worse-than-round-1 problem. Any new
answer must retain these strengths.

### Root Causes

What underlying issues explain the failures you identified? Are you treating
symptoms or causes?

- Are failures connected by a common root (e.g., misunderstanding the requirements,
  wrong architectural choice, insufficient depth in a key area)?
- Which E-criteria are affected by each root cause? A single root cause often
  drags down multiple criteria.
- Would fixing surface-level symptoms actually improve the result, or does the
  fundamental approach need to change?
- What would prevent the same failures from recurring in the next iteration?

### Goal Alignment

Step back — does the output actually achieve what the user asked for? Map your
assessment to E-criteria and hold it in mind when you score.

- Re-read the original message. What did the user actually want?
- Does the best answer deliver that, or has it drifted toward what was easier
  to build or more interesting to work on?
- For each E-criterion, how far is the current best from genuinely fulfilling it?
  If the gap is large on any criterion, your score for that criterion must be low.
- What would make the person who asked say "this is exactly what I needed" vs
  "this is impressive but not what I asked for"?

### Cross-Answer Synthesis

*If there is only one answer, evaluate it on its own merits — consider whether a
different approach or additional depth would meaningfully improve it.*

For multiple answers: which specific elements from other answers would directly
fix the failures you identified? Be targeted:
- "Agent 2's retry logic fixes failure #1"
- "Agent 1's data model is stronger but Agent 3's UI handles edge cases better"
- Don't just say "combine the best of both" — specify exactly what to take and why.

### Approach Challenge

Before scoring, answer honestly: **Is the current approach the right approach,
or just the first approach that was tried?**

Name one fundamentally different way to solve this problem — not a variation,
a genuinely different strategy. If you can name one that would plausibly produce
a better result, seriously consider pursuing it. Polishing a mediocre approach
will never produce an excellent result.

If all current answers share the same basic approach, that is a warning sign,
not validation. If the output has accumulated features across rounds but still
feels unpolished, the problem is the foundation, not the feature count.

### Pre-Score Audit (MANDATORY)

For EACH E-criterion:
1. Copy your single biggest finding from Failure Patterns for this criterion.
2. Ask: does my planned score honestly reflect this finding's severity?
3. If your finding describes a missing requirement or broken behavior, a score
   above 5 needs strong justification.
4. If your finding describes a significant gap, a score above 7 is suspect.
5. If you wrote "no meaningful failures": what would a harsh critic say?

A score that contradicts your own Failure Patterns section is dishonest — fix
either the analysis or the score.\""""


def _build_changedoc_checklist_analysis(
    custom_checklist_items: list[str] | None = None,
    item_verify_by: dict[str, str] | None = None,
) -> str:
    """Build changedoc-anchored GEPA-style diagnostic analysis for checklist modes.

    Replaces the generic _build_checklist_analysis() when changedoc is enabled.
    Combines GEPA diagnostic structure with changedoc-specific sections
    (Decision Audit, Implementation Accuracy).
    """
    return f"""## Changedoc-Anchored Diagnostic Analysis

Complete your full analysis before reading the Decision section below. Do not let
the decision criteria influence your assessment.

**Anchor every finding to evaluation criteria.** For each failure, success, or root
cause, reference the specific E-criterion it affects (E1, E2, E3, etc.). This
prevents gaps from getting lost between analysis and scoring.

### Decision Audit

For each decision (DEC-*) in the changedoc:
- **Rationale strength**: Is the "Why" field specific and tied to task requirements,
  or generic and hand-wavy? A strong rationale references concrete constraints, trade-offs,
  or evidence — not just "this seemed best."
- **Alternative depth**: Are rejected alternatives genuinely different approaches, or
  strawmen set up to lose? Would a thoughtful colleague have considered these same
  alternatives?
- **Implementation accuracy**: Do the Implementation fields reference actual files
  and sections that exist and match what was decided? Verify that the referenced
  files and code locations (functions, classes, section names) are real. Documenting
  features or symbols that do not actually exist in the output is fabrication, not
  aspiration. Flag any fabricated Implementation fields as critical failures.

Then ask: **What decisions are MISSING?** What important choices were made implicitly
in code but never recorded? What trade-offs were navigated without being articulated?

### Failure Patterns

What specific errors, gaps, or broken functionality exist — in the output, the
changedoc, and the alignment between them? Map each failure to the E-criterion
it violates.

For each answer:
{_build_changedoc_failure_bullets(custom_checklist_items, item_verify_by)}

If you cannot find meaningful failures, your review is probably too generous.

**Evidence-Based Findings:** If you used read_media to evaluate the output,
include its key findings here. If read_media flagged fundamental issues with
the approach, these belong in root causes — not just surface notes.

### Success Patterns

What works well and MUST be preserved in any revision? Regression on these is
worse than not improving.

For each answer, identify strengths by criterion:
- Which E-criteria are well-satisfied? What makes them strong?
- **Decision quality**: Which changedoc decisions are well-reasoned with strong
  rationale and real alternatives?
- **Unique contributions**: What does this answer do well — in output or decisions —
  that others don't?

Any new answer must retain these strengths. Identify what would be most damaging to lose.

### Root Causes

What underlying issues explain the failures you identified?

- Are output failures caused by wrong decisions, missing decisions, or correct
  decisions poorly executed?
- Which E-criteria are affected by each root cause? A single root cause often
  drags down multiple criteria.
- Would fixing surface-level symptoms actually improve the result, or does the
  fundamental approach need to change?
- Are changedoc weaknesses (thin rationale, missing decisions) causing output
  problems, or are they independent issues?

### Goal Alignment

Step back — does the output actually achieve what the user asked for? Map your
assessment to E-criteria.

- Re-read the original message. What did the user actually want?
- Does the best answer deliver that, or has it drifted toward what was easier
  to build or more interesting to work on?
- For each E-criterion, how far is the current best from genuinely fulfilling it?
  Hold this distance in mind when you score.

### Cross-Answer Synthesis

*If there is only one answer, evaluate its changedoc on its own merits — consider
what decisions are missing or under-reasoned.*

For multiple answers: which specific elements from other answers would directly
fix the failures you identified? Be targeted:
- Does another answer's changedoc contain decisions or rationale worth preserving?
- Are there NEW-marked decisions that represent genuinely original thinking?
- What specific output elements from other answers should be adopted?

### Substantiveness Test

Classify each planned change as:
- **TRANSFORMATIVE**: Fundamentally different approach, architecture, or creative direction
- **STRUCTURAL**: Meaningful redesign of a component, new capability, or significant quality lift —
  the bar is: *would a user with no knowledge of the implementation notice this as a meaningfully
  different experience?*
- **INCREMENTAL**: Minor polish, formatting, or small additions

The following are INCREMENTAL, not STRUCTURAL — do not upgrade them:
- CSS tweaks, animation refinements, reduced-motion support, async decoding
- Adding source notes, attribution, or citation formatting
- Adding test tooling, QA scripts, or developer-facing infrastructure
- Adding individual keyboard shortcuts (Home/End, etc.)
- Accessibility micro-fixes (aria labels, alt text on existing elements)
- Reformatting, reordering sections, or renaming variables
- Adding, strengthening, or reorganizing changedoc decisions without corresponding output changes

If no planned changes are TRANSFORMATIVE or STRUCTURAL, seriously consider whether
further iteration will produce meaningful improvement — or just accumulate incremental
changes. Voting may be the better choice.

### Approach Challenge

Before scoring, answer honestly: **Is the current approach the right approach,
or just the first approach that was tried?**

Name one fundamentally different way to solve this problem — not a variation,
a genuinely different strategy. If you can name one that would plausibly produce
a better result, seriously consider pursuing it. Polishing a mediocre approach
will never produce an excellent result.

If all current answers share the same basic approach, that is a warning sign,
not validation. If the output has accumulated features across rounds but still
feels unpolished, the problem is the foundation, not the feature count.

### Pre-Score Audit (MANDATORY)

For EACH E-criterion:
1. Copy your single biggest finding from Failure Patterns for this criterion.
2. Ask: does my planned score honestly reflect this finding's severity?
3. If your finding describes a missing requirement or broken behavior, a score
   above 5 needs strong justification.
4. If your finding describes a significant gap, a score above 7 is suspect.
5. If you wrote "no meaningful failures": what would a harsh critic say?

A score that contradicts your own Failure Patterns section is dishonest — fix
either the analysis or the score.\""""


def _build_checklist_decision(
    threshold: int,
    remaining: int,
    total: int,
    checklist_items: list,
    terminate_action: str = "vote",
    iterate_action: str = "new_answer",
) -> str:
    """Build checklist decision section (binary T/F, visible threshold)."""
    effective_t = _checklist_effective_threshold(threshold, remaining, total)
    required = _checklist_required_true(effective_t)
    budget = _checklist_budget_context(remaining, total)

    # Build numbered checklist with E-prefix
    numbered = "\n".join(f"  E{i+1}. {item}  → **TRUE** / **FALSE**" for i, item in enumerate(checklist_items))

    force_terminate = ""
    if remaining <= 0:
        force_terminate = f"\n\nIf budget remaining == 0 → call `{terminate_action}` regardless."

    return f"""---

## Decision

Now decide: call `{iterate_action}` or `{terminate_action}`.

- `{iterate_action}`: build a new answer, drawing the strongest elements from
  each existing answer. Identify what each answer does well before you start —
  do not anchor to any single answer as your base.
- `{terminate_action}`: select the answer with the strongest overall scores and stop.

The default is `{iterate_action}`. To justify `{terminate_action}`, you must demonstrate that
every dimension is already well-covered by at least one existing answer, and the gaps
between answers are minor enough that synthesis would add little. If you cannot
confidently make that case, choose `{iterate_action}`.

### Threshold

Your threshold is **{threshold}** on a 0-10 scale. This controls how strong your
case for `{terminate_action}` must be:
- 0: only `{terminate_action}` if answers are virtually identical — any unique content
  justifies `{iterate_action}`.
- 5: `{terminate_action}` if all dimensions are well-covered across answers and gaps are minor.
- 10: `{terminate_action}` as long as answers are adequate across dimensions, even if
  some improvements remain possible.

### Budget

{budget}

### Termination Checklist

To justify `{terminate_action}`, assess each of the following. You need enough of these to
be TRUE to clear the bar set by your threshold and budget.

{numbered}

### Decision Rule

Effective threshold (budget-adjusted): **{effective_t}**
Required TRUE count to `{terminate_action}`: **{required}**

If TRUE count >= {required} → `{terminate_action}`.
Otherwise → `{iterate_action}` (if budget remaining > 0).{force_terminate}

Reason through each checklist item, state your TRUE/FALSE verdict, count the TRUEs,
then apply the decision rule above."""


def _build_checklist_scored_decision(
    threshold: int,
    remaining: int,
    total: int,
    checklist_items: list,
    terminate_action: str = "vote",
    iterate_action: str = "new_answer",
) -> str:
    """Build checklist_scored decision section (0-10 confidence, visible cutoff)."""
    effective_t = _checklist_effective_threshold(threshold, remaining, total)
    required = _checklist_required_true(effective_t)
    cutoff = _checklist_confidence_cutoff(effective_t)
    budget = _checklist_budget_context(remaining, total)

    # Build numbered checklist with confidence instructions and E-prefix
    numbered = "\n".join(f"  E{i+1}. {item}  → **___/10**" for i, item in enumerate(checklist_items))

    force_terminate = ""
    if remaining <= 0:
        force_terminate = f"\n\nIf budget remaining == 0 → call `{terminate_action}` regardless."

    return f"""---

## Decision

Now decide: call `{iterate_action}` or `{terminate_action}`.

- `{iterate_action}`: build a new answer, drawing the strongest elements from
  each existing answer. Identify what each answer does well before you start —
  do not anchor to any single answer as your base.
- `{terminate_action}`: select the answer with the strongest overall scores and stop.

The default is `{iterate_action}`. To justify `{terminate_action}`, you must demonstrate that
every dimension is already well-covered by at least one existing answer, and the gaps
between answers are minor enough that synthesis would add little. If you cannot
confidently make that case, choose `{iterate_action}`.

### Threshold

Your threshold is **{threshold}** on a 0-10 scale. This controls how strong your
case for `{terminate_action}` must be:
- 0: only `{terminate_action}` if answers are virtually identical — any unique content
  justifies `{iterate_action}`.
- 5: `{terminate_action}` if all dimensions are well-covered across answers and gaps are minor.
- 10: `{terminate_action}` as long as answers are adequate across dimensions, even if
  some improvements remain possible.

### Budget

{budget}

### Confidence Assessment

Based on your analysis, rate your confidence (0-10) in each of the following
statements. 0 = completely disagree, 10 = fully agree, no reservations.

Calibrate your scores against these anchors:
- **9-10**: A professional would publish this as-is. No meaningful improvement possible.
- **7-8**: Good with real gaps. You can name specific things a demanding user would improve.
- **5-6**: Adequate but uninspired. Does what was asked but not well. Most first drafts belong here.
- **3-4**: Significant problems. Approach may be sound but execution has clear failures.
- **1-2**: Fundamentally wrong direction or non-functional.

Calibration rule: your score for each criterion MUST be consistent with the
weaknesses in your diagnostic analysis. If your analysis identified significant
gaps but your scores are 8+, your scores are inflated — lower them to match.

{numbered}

### Decision Rule

Effective threshold (budget-adjusted): **{effective_t}**
Confidence cutoff: **{cutoff}**
Required TRUE count to `{terminate_action}`: **{required}**

A score >= {cutoff} counts as TRUE.
If TRUE count >= {required} → `{terminate_action}`.
Otherwise → `{iterate_action}` (if budget remaining > 0).{force_terminate}

Rate your confidence on each item, count how many meet the {cutoff} cutoff,
then apply the decision rule above."""


def _build_checklist_gated_decision(
    checklist_items: list,
    terminate_action: str = "vote",
    iterate_action: str = "new_answer",
    require_gap_report: bool = True,
    gap_report_mode: str = "changedoc",
    builder_enabled: bool = True,
) -> str:
    """Build checklist_gated decision section (tool-gated, hidden threshold).

    Unlike checklist/checklist_scored, this mode hides the threshold, cutoff,
    and required count from the agent. The agent rates confidence honestly,
    submits scores via the submit_checklist MCP tool, and follows the verdict.

    Args:
        gap_report_mode: Controls report instructions.
            "changedoc": Requires diagnostic report (separate from changedoc).
            "separate": Requires diagnostic report file.
            "none": No report instructions.
    """
    numbered = "\n".join(f"  E{i+1}. {item}  → **___/10**" for i, item in enumerate(checklist_items))
    # Build dynamic example showing all E-items so agents know to score every criterion
    _example_entries = []
    for i in range(len(checklist_items)):
        key = f'"E{i+1}"'
        hint = "<why — cite specific evidence>" if i == 0 else "<why>"
        _example_entries.append(f'{key}: {{"score": <0-10>, "reasoning": "{hint}"}}')
    score_lines = ",\n      ".join(_example_entries)
    # Diagnostic report is always required as a separate artifact
    _diagnostic_report_section = (
        "### Diagnostic Report (REQUIRED)\n\n"
        "Before submitting scores, write a markdown diagnostic report in your workspace\n"
        "(e.g., `tasks/diagnostic_report.md`). This is separate from your changedoc.\n\n"
        "The report MUST cover, anchored to the E-criteria above:\n\n"
        "1. **Failure Patterns** — map each failure to the E-criterion it violates\n"
        '   (e.g., "E1: missing mobile nav = requirement unmet")\n'
        "2. **Root Causes** — underlying issues and which E-criteria they drag down\n"
        "3. **Goal Alignment** — per-criterion assessment of how far the output is\n"
        "   from genuinely fulfilling each E-criterion\n\n"
        "Optional but valuable: Success Patterns, Cross-Answer Synthesis.\n\n"
        "Start with output quality from the user's perspective — experience the output\n"
        "the way a user would before evaluating it.\n\n"
        "Pass the file path via `report_path` when calling `submit_checklist`.\n"
        "Submission will be rejected if no diagnostic report is provided.\n"
    )
    if gap_report_mode == "changedoc":
        report_requirement = _diagnostic_report_section
    elif gap_report_mode == "separate":
        report_requirement = _diagnostic_report_section
    else:
        # "none" — no report instructions
        report_requirement = ""

    # Phase 3 execution guidance — conditional on builder availability
    if builder_enabled:
        _phase3_execution = (
            "Annotate each task:\n"
            "- `[builder]` — focused single-deliverable spec; can run in parallel\n"
            "- `[main]` — judgment-heavy work you do inline "
            "(architectural decisions, synthesis)\n"
            "- `[synthesize]` — pull a specific element from another agent's "
            "answer and keep it\n"
            "- `[skip]` — deprioritized for this round\n"
            "\n"
            "Add `depends_on` links only where the output of one task is genuinely "
            "required\n"
            "input for another. Most improvements are independent — don't add "
            "false dependencies.\n"
            "\n"
            "**Step 3b — Maximize parallelism when executing.**\n"
            "\n"
            "Look at your task plan. Identify all `[builder]` tasks with no "
            "dependencies on\n"
            "each other. Spawn them all in a **single** `spawn_subagents` call "
            "— they run\n"
            "simultaneously:\n"
            "\n"
            "- `tasks`: one entry per deliverable (not one entry for all of them)\n"
            "- `background=True, refine=False`\n"
            "- Parent workspace is auto-mounted read-only. The shared peer snapshot "
            "directory\n"
            "  (temp_workspaces) is also auto-mounted read-only so subagents can "
            "access peer\n"
            "  context without explicit `context_paths`. Use `context_paths` only "
            "for\n"
            "  additional paths beyond these defaults.\n"
            "- **Subagent file artifacts**: Subagents write to their OWN workspace "
            "(not yours —\n"
            "  yours is read-only to them). In blocking mode, access artifacts via\n"
            '  `result["workspace"] + "/filename"`. In background mode the '
            "workspace path is\n"
            "  in the running status. Tell subagents to save files with relative "
            "paths and\n"
            "  report what they saved. Do NOT direct subagents to write into your "
            "workspace.\n"
            "\n"
            "Do your `[main]` work while builders run. Collect and integrate when "
            "all finish.\n"
            "Then spawn the next wave for tasks that depended on this batch.\n"
            "\n"
            "When collecting builder results:\n"
            "- **Output doesn't match spec**: Check whether the spec was ambiguous. "
            "If the\n"
            "  builder's interpretation was reasonable, accept it and note the "
            "deviation. If\n"
            "  the spec was clear and the builder diverged, re-spawn that one task "
            "with an\n"
            "  explicit correction — do not re-run all builders.\n"
            "- **Builder surfaces a hidden dependency**: It will say so in its "
            "output. Spawn\n"
            "  the blocking task first, then re-run the dependent builder once it "
            "completes.\n"
            "- **Multiple builders rewrote the same file**: You arbitrate — pick "
            "the better\n"
            "  version or merge manually inline. Do not silently discard either "
            "output.\n"
            "\n"
            "If no specialized subagents are available, execute tasks inline in "
            "dependency\n"
            "order.\n"
            "\n"
            f"**CHECKPOINT**: Before calling `{iterate_action}`, confirm ALL "
            "builder subagents\n"
            "have returned. Use `list_subagents()` — if any are still running, "
            "continue\n"
            "working on `[main]` tasks or wait. Submitting before builders finish "
            "wastes\n"
            "their work and budget."
        )
    else:
        _phase3_execution = (
            "Annotate each task:\n"
            "- `[main]` — judgment-heavy work you do inline "
            "(architectural decisions, synthesis)\n"
            "- `[synthesize]` — pull a specific element from another agent's "
            "answer and keep it\n"
            "- `[skip]` — deprioritized for this round\n"
            "\n"
            "Execute all tasks inline in dependency order. Focus on the "
            "highest-impact\n"
            "improvements first. Most improvements are independent — complete "
            "each fully\n"
            "before starting the next."
        )

    return f"""---

## Decision

Now decide: call `{iterate_action}` or `{terminate_action}`.

- `{iterate_action}`: build a new answer, drawing the strongest elements from
  each existing answer. Identify what each answer does well before you start —
  do not anchor to any single answer as your base.
- `{terminate_action}`: select the answer with the strongest overall scores and stop.

### Substantiveness Test

Classify each planned change as:
- **TRANSFORMATIVE**: Fundamentally different approach, architecture, or creative direction.
  Examples: switching from client-side to server-side rendering, replacing a REST API with
  GraphQL, rewriting a synchronous pipeline as event-driven, choosing a completely different
  data model or storage engine.
- **STRUCTURAL**: Meaningful redesign of a component, new capability, or significant quality
  lift — the bar is: *would a user with no knowledge of the implementation notice this as a
  meaningfully different experience?*
  Examples: adding real-time collaboration to a single-user editor, introducing a caching
  layer that changes perceived performance, redesigning navigation to support a new workflow,
  adding offline support, building a new visualization that reveals patterns previously hidden.
- **INCREMENTAL**: Minor polish, formatting, or small additions that do not change the user's
  experience in a meaningful way.
  Examples: CSS tweaks and animation refinements, adding aria labels or alt text to existing
  elements, reformatting code or reordering sections, adding source notes or attribution,
  adding individual keyboard shortcuts, reduced-motion support, async decoding, adding test
  tooling or developer-facing infrastructure, adding/strengthening/reorganizing changedoc
  decisions without corresponding changes to the actual deliverable.

If no planned changes are TRANSFORMATIVE or STRUCTURAL, seriously consider whether
further iteration will produce meaningful improvement — or just accumulate incremental
changes. Voting may be the better choice.

### Confidence Assessment

Your goal is **excellence**, not minimum viability. The question is not "does this
satisfy the bare requirements?" but "is this the best version we can produce?"
Depth, features, polish, and richness all count — they are never "beyond scope" or
"unnecessary." If the answer can be meaningfully better, it should be.

Rate your confidence (0-10) in each of the following statements.
0 = completely disagree, 10 = fully agree, no reservations.
Calibrate your scores against these anchors:
- **9-10**: A professional would publish this as-is. No meaningful improvement possible.
- **7-8**: Good with real gaps. You can name specific things a demanding user would improve.
- **5-6**: Adequate but uninspired. Does what was asked but not well. Most first drafts belong here.
- **3-4**: Significant problems. Approach may be sound but execution has clear failures.
- **1-2**: Fundamentally wrong direction or non-functional.

Calibration rule: your score for each criterion MUST be consistent with the
weaknesses in your diagnostic analysis. If your analysis identified significant
gaps but your scores are 8+, your scores are inflated — lower them to match.

{numbered}

{report_requirement}

### Submit Your Scores

Call `submit_checklist` with per-item reasoning and a report path.

Each score entry MUST include `"reasoning"` explaining why you gave that score —
reference specific evidence from your analysis.

  # When multiple agents exist, use per-agent format (REQUIRED):
  submit_checklist(
    scores={{
      "<agent_label>": {{
        {score_lines}
      }},
      "<other_agent_label>": {{
        {score_lines}
      }}
    }},
    report_path="<path to your markdown gap report>",
  )

The tool will evaluate your scores and return a verdict telling you whether
to call `{terminate_action}` or `{iterate_action}`. Follow the verdict.

**Round lifecycle — full sequence:**

**Phase 1 — Gather evidence. Do this BEFORE calling `submit_checklist`.**

Spawn **one evaluator** that sees **all candidate answers together**,
while you do qualitative analysis in parallel:

- Give the evaluator paths to all agents' answers. Instruct it to compare
  cross-agent: what does each answer have that the others lack? What gaps appear
  in all of them? Cross-agent comparison surfaces gaps that per-answer evaluation
  misses entirely.
- Evaluators handle: screenshots + visual observations (for visual artifacts:
  render to images or video first, then view), test runs, completeness checks,
  feature verification. Evaluators observe and report — they do NOT make changes.
- Split into parallel evaluators only when concerns are truly independent and
  span all answers equally (e.g. "visual quality" vs "link integrity") — never
  split by agent.
- **File access**: Your workspace is automatically mounted read-only for subagents
  (include_parent_workspace=True by default). Reference files by their full
  workspace-absolute paths. Do NOT reference the Shared Reference (temp_workspaces)
  path for files you created this round — those are only archived there after you
  submit, not during execution. For fully isolated research subagents that don't
  need your files, pass `include_parent_workspace: false`.
- You handle: read all agents' answers, identify qualitative gaps, assess
  creative/craft quality. You make the value judgments — evaluator gives you
  evidence to reason from, not scores.
- Once the evaluator returns, interpret its observations through your own
  quality lens to assign per-agent scores per dimension.

If no specialized subagents are available: do all evidence gathering and
qualitative analysis inline.

**CHECKPOINT**: Before moving to Phase 2, confirm your evaluator has returned
results. Use `list_subagents()` to check — it shows `elapsed_seconds` and
`seconds_remaining` for each running subagent. Evaluator evidence (screenshots,
test results, accessibility findings) directly affects your scores. Do NOT
score without this evidence.

**Phase 2 — Score and submit `submit_checklist`.**

Score EACH agent per dimension using the evidence from Phase 1. Submit with
per-agent scores format.

`submit_checklist` returns a verdict:
- **`{iterate_action}`** — improvements needed; call `propose_improvements` next
- **`{terminate_action}`** — output is sufficient; skip to Phase 5 to submit

Follow the verdict. Do not call `submit_checklist` again after receiving it.

When verdict is `{iterate_action}`, review each existing answer before proposing:
- What does each existing answer do well for each criterion?
- Which answer has the strongest element for each failing criterion?
Use this to fill in the `sources` and `preserve` fields accurately.

You MUST call `propose_improvements` with:
- **`improvements`**: plans for **every** failing criterion — each entry has a `plan` \
and `sources` (which answers you're drawing from for that specific change)
- **`preserve`**: what's already working and must not regress — each entry has `what` \
(the specific strength) and `source` (which answer it comes from)

  propose_improvements(
    improvements={{
      "E2": [{{"plan": "rethink the feature cards with distinct visual identity", "sources": ["agent_b.1"]}}],
      "E5": [{{"plan": "build a full signup form CTA", "sources": ["agent_b.1", "agent_a.1"]}}],
    }},
    preserve={{
      "E1": {{"what": "hero section visual impact — gradient animation and typography", "source": "agent_a.2"}},
      "E2": {{"what": "section header and layout grid — preserve while reworking cards", "source": "agent_a.2"}},
      "E3": {{"what": "sci-fi color palette coherence — neon-on-dark theme unified", "source": "agent_a.2"}},
    }}
  )

- `improvements`: each entry names a `plan` and its `sources` — which answers \
you're drawing from. This traces provenance of every change.
- `preserve` forces you to articulate what's WORKING before changing anything. \
A criterion can appear in BOTH — fix one part, protect another.

The tool validates all failing criteria are covered and returns a task_plan.
Add each item to your task plan tool, then proceed to Phase 3.

**Phase 3 — Execute improvements (`{iterate_action}` verdict only).**

Your `propose_improvements` call returned a validated `task_plan`. Add these
tasks to your task plan tool, then execute them.

{_phase3_execution}

**Phase 4 — Targeted subagents (when criteria plateau).**

If `submit_checklist` reports plateaued criteria (with score trajectories and
criterion details in the `plateaued_criteria` field), spawn a quality_rethinking
subagent AND a novelty subagent side-by-side in background — pass each the
`plateaued_criteria` detail from the checklist result (it includes criterion
text, category, and full score history so subagents know exactly what's stuck
and by how much). Meanwhile, proceed with `propose_improvements` and start
implementing your own ideas. When the subagents return, integrate their
proposals into your remaining work — their fresh perspective may suggest
approaches you wouldn't have tried.

**Phase 5 — Integrate, verify, submit.**

After all tasks complete:
1. Verify no regressions — confirm features from prior rounds still work. A working
   output with fewer features is always better than a broken output with more.
2. Confirm you implemented the full scope of identified improvements, not just some.
   Each round is expensive — deliver everything you identified, not just the easiest item.
3. Call `{iterate_action}` to submit your improved answer and end this round.

Your answer MUST be **obviously and substantially better** than the prior round —
not just marginally different. A user should immediately notice the improvement.
Do not copy or resubmit the same content with minor tweaks.

**What happens after `{iterate_action}`:** Your improved answer is submitted and this
round ends. If another coordination round is needed, you will receive a new prompt and
the lifecycle restarts at Phase 1 with all agents' updated answers. If the output is
now sufficient, the session terminates. You do not need to do anything to trigger the
next round — the system handles it."""


class Priority(IntEnum):
    """
    Explicit priority levels for system prompt sections.

    Lower numbers = higher priority (appear earlier in final prompt).
    Based on research showing critical instructions should appear at top
    or bottom of prompts for maximum attention.

    References:
        - Lakera AI Prompt Engineering Guide 2025
        - Anthropic Claude 4 Best Practices
        - "Position is Power" research (arXiv:2505.21091v2)
    """

    CRITICAL = 1  # Agent identity, MassGen primitives (vote/new_answer), core behaviors
    HIGH = 5  # Skills, memory, filesystem workspace - essential context
    MEDIUM = 10  # Operational guidance, task planning
    LOW = 15  # Task-specific context
    AUXILIARY = 20  # Optional guidance, best practices


@dataclass
class SystemPromptSection(ABC):
    """
    Base class for all system prompt sections.

    Each section encapsulates a specific set of instructions with explicit
    priority, optional XML structure, and support for hierarchical subsections.

    Attributes:
        title: Human-readable section title (for debugging/logging)
        priority: Priority level determining render order
        xml_tag: Optional XML tag name for wrapping content
        enabled: Whether this section should be included
        subsections: Optional list of child sections for hierarchy

    Example:
        >>> class CustomSection(SystemPromptSection):
        ...     def build_content(self) -> str:
        ...         return "Custom instructions here"
        >>>
        >>> section = CustomSection(
        ...     title="Custom",
        ...     priority=Priority.MEDIUM,
        ...     xml_tag="custom"
        ... )
        >>> print(section.render())
        <custom priority="medium">
        Custom instructions here
        </custom>
    """

    title: str
    priority: Priority
    xml_tag: str | None = None
    enabled: bool = True
    subsections: list["SystemPromptSection"] = field(default_factory=list)

    @abstractmethod
    def build_content(self) -> str:
        """
        Build the actual content for this section.

        Subclasses must implement this to provide their specific instructions.

        Returns:
            String content for this section (without XML wrapping)
        """

    def render(self) -> str:
        """
        Render the complete section with XML structure if specified.

        Automatically handles:
        - XML tag wrapping with priority attributes
        - Recursive rendering of subsections
        - Skipping if disabled

        Returns:
            Formatted section string ready for inclusion in system prompt
        """
        if not self.enabled:
            return ""

        # Build main content
        content = self.build_content()

        # Render and append subsections if present
        if self.subsections:
            enabled_subsections = [s for s in self.subsections if s.enabled]
            if enabled_subsections:
                sorted_subsections = sorted(
                    enabled_subsections,
                    key=lambda s: s.priority,
                )
                subsection_content = "\n\n".join(s.render() for s in sorted_subsections)
                content = f"{content}\n\n{subsection_content}"

        # Wrap in XML if tag specified
        if self.xml_tag:
            # Handle both Priority enum and raw integers
            if isinstance(self.priority, Priority):
                priority_name = self.priority.name.lower()
            else:
                # Map integer priorities to names
                priority_map = {1: "critical", 2: "critical", 3: "critical", 4: "critical", 5: "high", 10: "medium", 15: "low", 20: "auxiliary"}
                priority_name = priority_map.get(self.priority, "medium")
            return f'<{self.xml_tag} priority="{priority_name}">\n{content}\n</{self.xml_tag}>'

        return content


class AgentIdentitySection(SystemPromptSection):
    """
    Agent's core identity: role, expertise, personality.

    This section ALWAYS comes first (Priority 1) to establish
    WHO the agent is before any operational instructions.
    Skips rendering if empty.

    Args:
        agent_message: The agent's custom system message from
                      agent.get_configurable_system_message()
    """

    def __init__(self, agent_message: str):
        super().__init__(
            title="Agent Identity",
            priority=1,  # First, before massgen_coordination(2) and core_behaviors(3)
            xml_tag="agent_identity",
        )
        self.agent_message = agent_message

    def build_content(self) -> str:
        return self.agent_message

    def render(self) -> str:
        """Skip rendering if agent message is empty."""
        if not self.agent_message or not self.agent_message.strip():
            return ""
        return super().render()


class CoreBehaviorsSection(SystemPromptSection):
    """
    Core behavioral principles for Claude agents.

    Includes critical guidance on:
    - Default to action vs suggestion
    - Parallel tool calling
    - File cleanup

    Based on Anthropic Claude 4 best practices.
    Priority 4 puts this after agent_identity(1), massgen_coordination(2), and skills(3).
    """

    def __init__(self):
        super().__init__(
            title="Core Behaviors",
            priority=4,  # After agent_identity(1), massgen_coordination(2), skills(3)
            xml_tag="core_behaviors",
        )

    def build_content(self) -> str:
        return """## Core Behavioral Principles

**Default to Action:**
By default, implement changes rather than only suggesting them. If the user's intent is unclear,
infer the most useful likely action and proceed, using tools to discover any missing details instead
of guessing. Try to infer the user's intent about whether a tool call (e.g., file edit or read) is
intended or not, and act accordingly.

**Parallel Tool Calling:**
If you intend to call multiple tools and there are no dependencies between the tool calls, make all
of the independent tool calls in parallel. Prioritize calling tools simultaneously whenever the
actions can be done in parallel rather than sequentially. For example, when reading 3 files, run 3
tool calls in parallel to read all 3 files into context at the same time. Maximize use of parallel
tool calls where possible to increase speed and efficiency. However, if some tool calls depend on
previous calls to inform dependent values like the parameters, do NOT call these tools in parallel
and instead call them sequentially. Never use placeholders or guess missing parameters in tool calls.

**Task Persistence:**
Your context window will be automatically compacted as it approaches its limit, allowing you to
continue working indefinitely from where you left off. Therefore, do not stop tasks early due to
token budget concerns. As you approach your token budget limit, save your current progress and state
to memory before the context window refreshes. Always be as persistent and autonomous as possible
and complete tasks fully, even if the end of your budget is approaching. Never artificially stop any
task early regardless of the context remaining."""


# Task Persistence guidance sourced from Anthropic Claude prompting best practices:
# https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#context-awareness-and-multi-window-workflows


class GPT5GuidanceSection(SystemPromptSection):
    """
    GPT-5.x specific guidance for solution persistence and tool preambles.

    Encourages autonomous, end-to-end task completion and structured tool
    usage narration based on OpenAI's GPT-5 prompting guides.

    Only included when the model is GPT-5.x (gpt-5, gpt-5.1, gpt-5.2, etc.)
    Priority 4 places this alongside CoreBehaviorsSection.

    References:
        - https://cookbook.openai.com/examples/gpt-5/gpt-5-1_prompting_guide#encouraging-complete-solutions
        - https://cookbook.openai.com/examples/gpt-5/gpt-5_prompting_guide#tool-preambles
    """

    def __init__(self):
        super().__init__(
            title="GPT-5 Guidance",
            priority=4,  # Same priority as CoreBehaviorsSection
            xml_tag=None,  # Uses internal XML tags for each subsection
        )

    def build_content(self) -> str:
        return (
            "<solution_persistence>\n"
            "- Treat yourself as an autonomous senior pair-programmer: once the user gives a direction, "
            "proactively gather context, plan, implement, test, and refine without waiting for additional "
            "prompts at each step.\n"
            "- Persist until the task is fully handled end-to-end within the current turn whenever feasible: "
            "do not stop at analysis or partial fixes; carry changes through implementation, verification, "
            "and a clear explanation of outcomes unless the user explicitly pauses or redirects you.\n"
            "- Be extremely biased for action. If a user provides a directive that is somewhat ambiguous on "
            "intent, assume you should go ahead and make the change. If the user asks a question like "
            '"should we do x?" and your answer is "yes", you should also go ahead and perform the action. '
            "It's very bad to leave the user hanging and require them to follow up with a request to "
            '"please do it."\n'
            "</solution_persistence>\n\n"
            "<tool_preambles>\n"
            "- As you execute your file edit(s) and other tool calls, narrate each step succinctly and "
            "sequentially, marking progress clearly.\n"
            "- CRITICAL: If your task requires creating or modifying files, you MUST use file tools to "
            "actually write them to the filesystem. Do NOT just output file contents in the new_answer "
            "text using markdown - the files will not exist unless you call the appropriate writing and "
            "editing tools.\n"
            "</tool_preambles>"
        )


class GrokGuidanceSection(SystemPromptSection):
    """
    Grok-specific guidance for file content encoding.

    Addresses a known issue where Grok models (particularly Grok 4.1) HTML-escape
    file content when writing SVG, XML, HTML, or other files containing angle
    brackets. This results in corrupted files with &lt; instead of <, etc.

    Only included when the model is Grok (grok-*).
    Priority 4 places this alongside CoreBehaviorsSection.
    """

    def __init__(self):
        super().__init__(
            title="Grok Guidance",
            priority=4,  # Same priority as CoreBehaviorsSection
            xml_tag=None,  # Uses internal XML tags
        )

    def build_content(self) -> str:
        return (
            "<file_content_encoding>\n"
            "CRITICAL: When writing file content, pass the content EXACTLY as it should appear in the file. "
            "Do NOT HTML-escape or XML-escape the content.\n"
            '- Write literal characters: use < not &lt;, use > not &gt;, use " not &quot;, use & not &amp;\n'
            "- The file writing tool expects raw content, not escaped content. Escaping will corrupt the file.\n"
            "</file_content_encoding>"
        )


class SkillsSection(SystemPromptSection):
    """
    Available skills that agents can invoke.

    CRITICAL priority (3) ensures skills appear before general behaviors.
    Skills define fundamental capabilities that must be known before task execution.

    When a SKILL_REGISTRY.md exists, uses its compact content as the primary
    routing guide and appends a "Recently Added" section for skills not yet
    cataloged in the registry.  Falls back to per-skill XML when no registry
    exists.

    Args:
        skills: List of all skills (both builtin and project) with name, description, location
        skills_dir: Optional path to the skills directory (for registry lookup)
    """

    REGISTRY_FILENAME = "SKILL_REGISTRY.md"

    def __init__(
        self,
        skills: list[dict[str, Any]],
        skills_dir: Optional["Path"] = None,
    ):
        super().__init__(
            title="Available Skills",
            priority=3,  # After agent_identity(1) and massgen_coordination(2), before core_behaviors(4)
            xml_tag="skills",
        )
        self.skills = skills
        self.skills_dir = skills_dir

    def _try_load_registry(self) -> str | None:
        """Attempt to load registry content if it exists."""
        if self.skills_dir is None:
            return None
        try:
            from pathlib import Path

            registry_path = Path(self.skills_dir) / self.REGISTRY_FILENAME
            if registry_path.exists():
                return registry_path.read_text(encoding="utf-8")
        except Exception:
            pass
        return None

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Strip YAML frontmatter from registry content."""
        import re

        return re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL).strip()

    @staticmethod
    def _extract_registry_skill_names(registry_body: str) -> set:
        """Extract skill names mentioned in the registry body.

        Looks for patterns like **skill-name** in markdown bullet lists.
        """
        import re

        return {m.group(1).lower() for m in re.finditer(r"\*\*([^*]+)\*\*", registry_body)}

    def _build_usage_instructions(self) -> list[str]:
        """Build the common usage instructions block."""
        parts = []
        parts.append("<usage>")
        parts.append("When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively.")
        parts.append("")
        parts.append("How to use skills:")
        parts.append(
            "- To load a skill's full instructions, read its SKILL.md file from .agent/skills/<skill-name>/SKILL.md (workspace-relative) or ~/.agent/skills/<skill-name>/SKILL.md (home/Docker path)",
        )
        parts.append(
            "- Skills may be hierarchical: a single SKILL.md can contain multiple sections covering related sub-capabilities (e.g., a web-app-dev skill with frontend, backend, and testing sections)",
        )
        parts.append("- Each skill directory may also contain bundled resources (templates, examples, configs) in subdirectories")
        parts.append("")
        parts.append("Usage notes:")
        parts.append("- Only use skills listed below")
        parts.append("- Do not invoke a skill that is already loaded in your context")
        parts.append("</usage>")
        return parts

    def build_content(self) -> str:
        """Build skills section content.

        Uses compact registry when available, with a 'Recently Added' section
        for skills not yet in the registry.  Falls back to per-skill XML
        listing when no registry exists.
        """
        content_parts = []

        # Header
        content_parts.append("## Available Skills")
        content_parts.append("")
        content_parts.append("<!-- SKILLS_TABLE_START -->")

        # Usage instructions
        content_parts.extend(self._build_usage_instructions())
        content_parts.append("")

        # Try registry path
        registry_content = self._try_load_registry()
        if registry_content:
            body = self._strip_frontmatter(registry_content)
            content_parts.append("<skill_registry>")
            content_parts.append(body)
            content_parts.append("</skill_registry>")

            # Find skills not mentioned in registry -> "Recently Added"
            registry_names = self._extract_registry_skill_names(body)
            unregistered = [s for s in self.skills if s.get("name", "").lower() not in registry_names]
            if unregistered:
                content_parts.append("")
                content_parts.append("<recently_added>")
                content_parts.append("## Recently Added")
                content_parts.append("Skills created since last registry update:")
                for skill in unregistered:
                    name = skill.get("name", "Unknown")
                    desc = skill.get("description", "No description")
                    loc = skill.get("location", "project")
                    content_parts.append(f"- **{name}** ({loc}): {desc}")
                content_parts.append("</recently_added>")

            content_parts.append("<!-- SKILLS_TABLE_END -->")
            return "\n".join(content_parts)

        # Per-skill XML listing (no registry)
        content_parts.append("<available_skills>")

        for skill in self.skills:
            name = skill.get("name", "Unknown")
            description = skill.get("description", "No description")
            location = skill.get("location", "project")

            content_parts.append("")
            content_parts.append("<skill>")
            content_parts.append(f"<name>{name}</name>")
            content_parts.append(f"<description>{description}</description>")
            content_parts.append(f"<location>{location}</location>")
            content_parts.append("</skill>")

        content_parts.append("")
        content_parts.append("</available_skills>")
        content_parts.append("<!-- SKILLS_TABLE_END -->")

        return "\n".join(content_parts)


class FileSearchSection(SystemPromptSection):
    """
    Lightweight file search guidance for ripgrep and ast-grep.

    This provides essential usage patterns for the pre-installed search tools.
    For comprehensive guidance, agents can run: `openskills read file-search`

    MEDIUM priority - useful but not critical for all tasks.
    """

    def __init__(self):
        super().__init__(
            title="File Search Tools",
            priority=Priority.MEDIUM,
            xml_tag="file_search_tools",
        )

    def build_content(self) -> str:
        """Build concise file search guidance."""
        return """## File Search Tools

You have access to fast search tools for code exploration:

**ripgrep (rg)** - Fast text/regex search:
```bash
# Search with file type filtering
rg "pattern" --type py --type js

# Common flags: -i (case-insensitive), -w (whole words), -l (files only), -C N (context lines)
rg "function.*login" --type js src/
```

**ast-grep (sg)** - Structural code search:
```bash
# Find code patterns by syntax
sg --pattern 'function $NAME($$$) { $$$ }' --lang js

# Metavariables: $VAR (single node), $$$ (zero or more nodes)
sg --pattern 'class $NAME { $$$ }' --lang python
```

**Key principles:**
- Start narrow: Specify file types (--type py) and directories (src/)
- Count first: Use `rg "pattern" --count` to check result volume before full search
- Limit output: Pipe to `head -N` if results are large
- Use rg for text, sg for code structure

For detailed guidance including targeting strategies and examples, run: `openskills read file-search`"""


class CodeBasedToolsSection(SystemPromptSection):
    """
    Guidance for code-based tool access (CodeAct paradigm).

    When enabled, MCP tools are presented as Python code in the filesystem.
    Agents discover tools by exploring servers/, read docstrings, and call via imports.

    MEDIUM priority - important for tool discovery and usage.

    Args:
        workspace_path: Path to agent's workspace
        shared_tools_path: Optional path to shared tools directory
        mcp_servers: List of MCP server configurations (for fetching descriptions)
    """

    def __init__(
        self,
        workspace_path: str,
        shared_tools_path: str = None,
        mcp_servers: list[dict[str, Any]] = None,
    ):
        super().__init__(
            title="Code-Based Tools",
            priority=Priority.MEDIUM,
            xml_tag="code_based_tools",
        )
        self.workspace_path = workspace_path
        self.shared_tools_path = shared_tools_path
        self.mcp_servers = mcp_servers or []
        # Use shared tools path if available, otherwise workspace
        self.tools_location = shared_tools_path if shared_tools_path else workspace_path

    def build_content(self) -> str:
        """Build code-based tools guidance."""
        location_note = ""
        if self.shared_tools_path:
            location_note = f"\n\n**Note**: Tools are in a shared read-only location (`{self.shared_tools_path}`) accessible to all agents."

        # Read ExecutionResult class definition for custom tools
        import re
        from pathlib import Path

        result_file = Path(__file__).parent / "tool" / "_result.py"
        try:
            execution_result_code = result_file.read_text()
        except Exception:
            execution_result_code = "# ExecutionResult definition not available"

        # Discover custom tools by reading TOOL.md files
        custom_tools_list = ""
        custom_tools_path = Path(self.tools_location) / "custom_tools"
        if custom_tools_path.exists():
            tool_descriptions = []
            for tool_md in custom_tools_path.glob("*/TOOL.md"):
                try:
                    content = tool_md.read_text()
                    # Extract description from YAML frontmatter
                    match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
                    if match:
                        tool_name = tool_md.parent.name
                        description = match.group(1).strip()
                        tool_descriptions.append(f"- **{tool_name}**: {description}")
                except Exception:
                    continue

            if tool_descriptions:
                custom_tools_list = "\n\n**Available Custom Tools:**\n" + "\n".join(tool_descriptions)

        # Fetch MCP server descriptions from registry
        mcp_servers_list = ""
        if self.mcp_servers:
            try:
                from massgen.mcp_tools.registry_client import (
                    get_mcp_server_descriptions,
                )

                mcp_descriptions = get_mcp_server_descriptions(self.mcp_servers)
                if mcp_descriptions:
                    mcp_items = [f"- **{name}**: {desc}" for name, desc in mcp_descriptions.items()]
                    mcp_servers_list = "\n\n**Available MCP Servers:**\n" + "\n".join(mcp_items)
            except Exception as e:
                logger.warning(f"Failed to fetch MCP descriptions: {e}")
                # Fall back to just showing server names
                server_names = [s.get("name", "unknown") for s in self.mcp_servers]
                if server_names:
                    mcp_servers_list = "\n\n**Available MCP Servers:** " + ", ".join(server_names)

        return f"""## Available Tools (Code-Based Access)

Tools are available as **Python code** in your workspace filesystem. Discover and call them like regular Python modules (e.g., use normal search tools such as `rg` or `sg`){location_note}

**Directory Structure:**
```
{self.tools_location}/
├── servers/              # MCP tool wrappers (auto-generated, read-only)
│   ├── __init__.py      # Package marker (import from here)
│   ├── weather/
│   │   ├── __init__.py  # Exports: get_forecast, get_current
│   │   ├── get_forecast.py
│   │   └── get_current.py
│   └── github/
│       ├── __init__.py  # Exports: create_issue
│       └── create_issue.py
└── custom_tools/         # Full Python implementations (read-only)
    └── [user-provided tools]

Your workspace/
└── utils/               # CREATE THIS - for your scripts (workflows, async, filtering)
    └── [write your own scripts here as needed]
```{mcp_servers_list}{custom_tools_list}

**Important:** All tools and servers listed here are already configured and ready to use. If a tool requires API keys, they are already available - we only show tools you can actually use.

**Note:** Skills provide guidance and workflows, while tools provide actual functionality. They complement each other - for
example, a skill might guide you through a process that requires using specific tools to complete it.

While it's not always necessary to use additional tools, there are some cases where they are required (e.g., multimodal
content generation and understanding, as by default agents only handle text). In other cases, using tools can help you
complete tasks more efficiently.

**Tool Discovery (Efficient Patterns):**

Custom tools (listed above) - read TOOL.md for details:
```bash
head -n 80 custom_tools/<tool_name>/TOOL.md
```

MCP servers - extract function docstrings:
```bash
# List servers and functions
ls servers/ && ls servers/<server_name>/

# Get function docstring (first 25 lines)
head -n 25 servers/<server_name>/<function>.py

# Extract all function signatures with ast-grep
sg --pattern 'def $FUNC($$$):' --lang python servers/<server_name>/
```

Search patterns:
```bash
# Search custom tools by capability
rg 'tasks:' custom_tools/*/TOOL.md -A 3 | rg -i '<keyword>'

# Search MCP server functions by name/keyword
rg -i '<keyword>' servers/ -l
```

**Usage Pattern:**
```python
# Import MCP tools from servers/
from servers.weather import get_forecast
from servers.github import create_issue

# Import custom tools - use module path from TOOL.md entry_points
# Simple tool: from custom_tools.{{file}} import {{function}}
from custom_tools.string_utils import reverse_string

# Tool in subdirectory: from custom_tools.{{dir}}.{{file}} import {{function}}
# Example from TOOL.md: entry_points[0] = {{file: "_multimodal_tools/generation/generate_media.py", function: "generate_media"}}
from custom_tools._multimodal_tools.generation.generate_media import generate_media

# Use the tools
weather = get_forecast("San Francisco", days=3)
reversed_text = reverse_string("hello")
image = await generate_media(prompt="sunset", mode="image")
```

**Important:**
- Subdirectories under `custom_tools/` don't auto-import tools. Always import directly from the `.py` file using the path from TOOL.md.
- **CRITICAL**: When running Python scripts that import from `servers/` or `custom_tools/`, always specify `work_dir="{self.workspace_path}"` in your
  execute_command call. The symlinks to these directories only exist in your main workspace, not in temporary snapshot directories.

**Custom Tools Return Type:**

Custom tools MUST return `ExecutionResult`. Here's the definition from `massgen/tool/_result.py`:

```python
{execution_result_code}
```

**Creating Workflows (utils/):**
Write scripts in `utils/` to combine multiple tools:

```python
# utils/daily_weather_report.py
from servers.weather import get_forecast, get_current

def generate_report(city: str) -> str:
    current = get_current(city)
    forecast = get_forecast(city, days=3)

    report = f"Current: {{current['temp']}}°F\\n"
    report += f"Forecast: {{forecast['summary']}}"
    return report

# Run directly
if __name__ == "__main__":
    print(generate_report("San Francisco"))
```

Then execute: `python utils/daily_weather_report.py`

**Advanced Patterns:**
- **Async operations**: Use `asyncio` to call multiple tools in parallel
- **Data filtering**: Process large datasets in utils/ before returning (reduce tokens)
- **Error handling**: Add try/except in utils/ for robust workflows
- **Tool composition**: Chain multiple tools together in single script

**Key Principles:**
1. **Batch discovery operations**: Combine `ls`, `rg`, `sg` in a single command execution call
2. **Search then extract**: Use `rg -l` to find candidates, then `head`/`sg` for targeted reads
3. **Minimize context**: Extract only signatures/docstrings with `sg` or `head -n 25` (not full `cat`)
4. **Import only needed tools**: Don't import everything upfront (reduces context)
5. **Create utils/ for complex workflows**: Combine tools, add async, filter data

**Example - Async Multi-Tool Call:**
```python
# utils/parallel_weather.py
import asyncio
from servers.weather import get_forecast

async def get_forecasts(cities: list) -> dict:
    tasks = [get_forecast(city) for city in cities]
    results = await asyncio.gather(*tasks)
    return dict(zip(cities, results))

# Get weather for 5 cities in parallel
cities = ["SF", "NYC", "LA", "Chicago", "Boston"]
forecasts = asyncio.run(get_forecasts(cities))
```

**Example - Data Filtering:**
```python
# utils/top_leads.py
from servers.salesforce import get_records

def get_qualified_leads(limit: int = 50) -> list:
    # Fetch 10k records from Salesforce
    all_records = get_records(object="Lead", limit=10000)

    # Filter in execution environment (not sent to LLM context)
    qualified = [r for r in all_records if r["score"] > 80]

    # Return only top N (massive context reduction)
    return sorted(qualified, key=lambda x: x["score"], reverse=True)[:limit]
```

This approach provides context reduction compared to loading all tool schemas upfront."""


class MemorySection(SystemPromptSection):
    """
    Memory system instructions for context retention across conversations.

    HIGH priority ensures memory usage is prominent and agents use it
    proactively rather than only when explicitly prompted.

    Args:
        memory_config: Dictionary containing memory system configuration
                      including short-term and long-term memory content
        read_only: If True, show memory context without write/reminder instructions.
    """

    def __init__(self, memory_config: dict[str, Any], read_only: bool = False):
        super().__init__(
            title="Memory System",
            priority=Priority.HIGH,
            xml_tag="memory",
        )
        self.memory_config = memory_config
        self.read_only = read_only

    def build_content(self) -> str:
        """Build memory system instructions."""
        content_parts = []

        # Header - concise overview
        content_parts.append(
            "## Decision Documentation System\n\n"
            "Document decisions and learnings to **optimize future work** and **prevent repeated mistakes**. "
            "This isn't just memory - it's about capturing **why** decisions were made, **what worked/failed**, "
            "and **what would help similar tasks succeed**.\n",
        )

        # Memory tiers - clarified with usage guidance
        content_parts.append(
            "### Storage Tiers\n\n"
            "**short_term** (auto-loaded every turn):\n"
            "- User preferences and workflow patterns\n"
            "- Quick reference info needed frequently\n"
            "- Current task context and findings\n"
            "- Small, tactical observations (<100 lines)\n"
            "- Examples: user_prefs.md, current_findings.md\n\n"
            "**long_term** (load manually when needed):\n"
            "- Detailed post-mortems and analyses\n"
            "- Comprehensive skill effectiveness reports\n"
            "- Complex lessons with context (>100 lines)\n"
            "- Knowledge that's useful but not needed every turn\n"
            "- Examples: detailed_analysis.md, comprehensive_guide.md\n\n"
            "**Rule of thumb**: If it's small and useful every turn → short_term. "
            "If it's detailed and situationally useful → long_term.\n",
        )

        # Show existing short-term memories (full content)
        short_term = self.memory_config.get("short_term", {})
        if short_term:
            content_parts.append("\n### Current Short-Term Memories\n")
            short_term_content = short_term.get("content", "")
            if short_term_content:
                content_parts.append(short_term_content)
            else:
                content_parts.append("*No short-term memories yet*")

        # Show existing long-term memories (summaries only)
        long_term = self.memory_config.get("long_term", [])
        if long_term:
            content_parts.append("\n### Available Long-Term Memories\n")
            content_parts.append("<available_long_term_memories>")
            for memory in long_term:
                mem_id = memory.get("id", "N/A")
                summary = memory.get("summary", "No summary")
                created = memory.get("created_at", "Unknown")
                content_parts.append("")
                content_parts.append("<memory>")
                content_parts.append(f"<id>{mem_id}</id>")
                content_parts.append(f"<summary>{summary}</summary>")
                content_parts.append(f"<created>{created}</created>")
                content_parts.append("</memory>")
            content_parts.append("")
            content_parts.append("</available_long_term_memories>")

        # Show current memories from temp workspaces (all agents' current work)
        temp_workspace_memories = self.memory_config.get("temp_workspace_memories", [])
        if temp_workspace_memories:
            content_parts.append("\n### Current Agent Memories (For Comparison)\n")
            content_parts.append(
                "These are the current memories from all agents working on this task. " "Review to compare approaches and avoid duplicating work.\n",
            )

            for agent_mem in temp_workspace_memories:
                agent_label = agent_mem.get("agent_label", "unknown")
                memories = agent_mem.get("memories", {})

                content_parts.append(f"\n**{agent_label}:**")

                # Show short_term memories (full content)
                if memories.get("short_term"):
                    content_parts.append("\n*short_term:*")
                    for mem_name, mem_data in memories["short_term"].items():
                        content = mem_data.get("content", mem_data) if isinstance(mem_data, dict) else mem_data
                        content_parts.append(f"- `{mem_name}.md`")
                        content_parts.append(f"  ```\n  {content.strip()}\n  ```")

                # Show long_term memories (name + description only)
                if memories.get("long_term"):
                    content_parts.append("\n*long_term:*")
                    for mem_name, mem_data in memories["long_term"].items():
                        if isinstance(mem_data, dict):
                            description = mem_data.get("description", "No description")
                            content_parts.append(f"- `{mem_name}.md`: {description}")
                        else:
                            # Fallback if not parsed
                            content_parts.append(f"- `{mem_name}.md`")

                if not memories.get("short_term") and not memories.get("long_term"):
                    content_parts.append("  *No memories*")

        # Show archived memories (deduplicated historical context)
        archived = self.memory_config.get("archived_memories", {})
        if archived and (archived.get("short_term") or archived.get("long_term")):
            content_parts.append("\n### Archived Memories (Historical - Deduplicated)\n")
            content_parts.append(
                "These are historical memories from previous answers. Duplicate names have been resolved " "(showing only the most recent version of each memory). This is read-only context.\n",
            )

            # Show short_term archived memories (full content)
            if archived.get("short_term"):
                content_parts.append("\n**Short-term (full content):**")
                for mem_name, mem_data in archived["short_term"].items():
                    content = mem_data.get("content", "")
                    content_parts.append(f"\n- `{mem_name}.md`")
                    content_parts.append(f"  ```\n  {content.strip()}\n  ```")

            # Show long_term archived memories (name + description only)
            if archived.get("long_term"):
                content_parts.append("\n**Long-term (summaries only):**")
                for mem_name, mem_data in archived["long_term"].items():
                    content = mem_data.get("content", "")
                    # Try to extract description from YAML frontmatter
                    description = "No description"
                    if "description:" in content:
                        try:
                            # Simple extraction of description line
                            for line in content.split("\n"):
                                if line.strip().startswith("description:"):
                                    description = line.split("description:", 1)[1].strip()
                                    break
                        except Exception:
                            pass
                    content_parts.append(f"- `{mem_name}.md`: {description}")

        if self.read_only:
            content_parts.append(
                "\n### Memory Mode\n\n"
                "Round-time memory capture is disabled for this run. Use the memory context above as read-only guidance "
                "during coordination. Consolidation can happen at final presentation.\n",
            )
            return "\n".join(content_parts)

        # File operations - simple and direct
        content_parts.append(
            "\n### Saving Memories\n\n"
            "Before writing memory files, review `tasks/changedoc.md`.\n\n"
            "Save memories by writing markdown files to the memory directory:\n"
            "- **Short-term** → `memory/short_term/{name}.md` (auto-loaded every turn)\n"
            "- **Long-term** → `memory/long_term/{name}.md` (load manually when needed)\n\n"
            "**File Format (REQUIRED YAML Frontmatter):**\n"
            "```markdown\n"
            "---\n"
            "name: skill_effectiveness\n"
            "description: Tracking which skills and tools work well for different task types\n"
            "created: 2025-11-23T20:00:00\n"
            "updated: 2025-11-23T20:00:00\n"
            "---\n\n"
            "## Your Content Here\n"
            "Document your findings...\n"
            "```\n\n"
            "**Important:** You are stateless - you don't have a persistent identity across restarts. "
            "When you call `new_answer`, your workspace is cleared and archived. The system shows you:\n"
            "1. Current memories from all agents (for comparing approaches)\n"
            "2. Historical archived memories (deduplicated - newest version of each name)\n\n"
            "If the same memory name appears multiple times, only the most recent version is shown.\n",
        )

        # Task completion reminders
        content_parts.append(
            "\n### Automatic Reminders\n\n"
            "When you complete high-priority tasks, tool responses will include reminders to document decisions. "
            "These help you optimize future work by capturing what worked, what didn't, and why.\n",
        )

        # When to document - with clear tier guidance
        content_parts.append(
            "\n### What to Document\n\n"
            "**SHORT-TERM (use for most things):**\n\n"
            "**User Preferences** → memory/short_term/user_prefs.md\n"
            "- What does the user value (speed vs quality, iteration vs one-shot, etc.)?\n"
            "- Coding style, naming conventions, workflow preferences\n"
            "- Example: 'User prefers iterative refinement with visual feedback'\n\n"
            "**Quick Observations** → memory/short_term/quick_notes.md\n"
            "- Tactical findings from current work\n"
            "- What worked/failed in this specific task\n"
            "- Tool tips and gotchas discovered\n"
            "- Example: 'create_directory fails on nested paths - create parent first'\n\n"
            "**Current Context** → memory/short_term/task_context.md\n"
            "- Key findings about the current task\n"
            "- Important decisions made\n"
            "- State of work in progress\n\n"
            "**LONG-TERM (only if detailed/comprehensive):**\n\n"
            "**Comprehensive Skill Analysis** → memory/long_term/skill_effectiveness.md\n"
            "- Detailed comparison of multiple skills/approaches\n"
            "- Cross-task patterns (>3 examples)\n"
            "- Only save if you have substantial evidence (100+ lines)\n\n"
            "**Detailed Post-Mortems** → memory/long_term/approach_patterns.md\n"
            "- In-depth analysis of complex approaches\n"
            "- Multi-step strategies with rationale\n"
            "- Only for significant architectural decisions\n\n"
            "**Note**: Most observations should go in **short_term**. Reserve long_term for truly "
            "detailed analyses that would clutter the auto-loaded context.\n",
        )

        # Examples - emphasize short-term for most uses
        content_parts.append(
            "\n### Examples\n\n"
            "**SHORT-TERM: Quick tactical observation** (PREFERRED for most things)\n"
            "Use the file write tool to save to `memory/short_term/quick_notes.md`:\n"
            "```markdown\n"
            "---\n"
            "name: quick_notes\n"
            "description: Tactical observations from current work\n"
            "created: 2025-11-23T20:00:00\n"
            "updated: 2025-11-23T20:00:00\n"
            "---\n\n"
            "## Web Development\n"
            "- create_directory fails on nested paths - create parent first\n"
            "- CSS variables work well for theming\n"
            "- Always test with `printf` for CLI stdin validation\n"
            "```\n\n"
            "**SHORT-TERM: User preferences**\n"
            "Save to `memory/short_term/user_prefs.md`:\n"
            "```markdown\n"
            "---\n"
            "name: user_prefs\n"
            "description: User workflow and style preferences\n"
            "created: 2025-11-23T20:00:00\n"
            "updated: 2025-11-23T20:00:00\n"
            "---\n\n"
            "## Preferences\n"
            "- Prefers clean, minimal code\n"
            "- Wants explanations with examples\n"
            "```\n\n"
            "**LONG-TERM: Only for detailed analysis** (>100 lines)\n"
            "Save to `memory/long_term/comprehensive_analysis.md`:\n"
            "```markdown\n"
            "---\n"
            "name: comprehensive_analysis\n"
            "description: Detailed multi-task skill effectiveness analysis\n"
            "created: 2025-11-23T20:00:00\n"
            "updated: 2025-11-23T20:00:00\n"
            "---\n\n"
            "[100+ lines of detailed analysis comparing approaches across multiple tasks...]\n"
            "```\n",
        )

        return "\n".join(content_parts)


class WorkspaceStructureSection(SystemPromptSection):
    """
    Critical workspace paths and structure information.

    This subsection of FilesystemSection contains the MUST-KNOW information
    about where files are located and how the workspace is organized.

    Args:
        workspace_path: Path to the agent's workspace directory
        context_paths: List of paths containing important context
        use_two_tier_workspace: If True, include documentation for scratch/deliverable structure
    """

    def __init__(
        self,
        workspace_path: str,
        context_paths: list[str],
        use_two_tier_workspace: bool = False,
        decomposition_mode: bool = False,
        worktree_paths: dict[str, str] | None = None,
        branch_name: str | None = None,
        other_branches: dict[str, str] | None = None,
        branch_diff_summaries: dict[str, str] | None = None,
    ):
        super().__init__(
            title="Workspace Structure",
            priority=Priority.HIGH,
            xml_tag="workspace_structure",
        )
        self.workspace_path = workspace_path
        self.context_paths = context_paths
        self.use_two_tier_workspace = use_two_tier_workspace
        self.decomposition_mode = decomposition_mode
        self.worktree_paths = worktree_paths  # {worktree_path: original_path}
        self.branch_name = branch_name  # This agent's current branch
        self.other_branches = other_branches  # {anon_id: branch_name}
        self.branch_diff_summaries = branch_diff_summaries  # {anon_id: diff_summary}

    def build_content(self) -> str:
        """Build workspace structure documentation."""
        content_parts = []

        content_parts.append("## Workspace Paths\n")
        content_parts.append(f"**Workspace directory**: `{self.workspace_path}`")
        content_parts.append(
            "\nThis is your primary working directory where you should create " "and manage files for this task.\n",
        )

        # Worktree-based workspace (new unified model) takes precedence
        if self.worktree_paths:
            for wt_path in self.worktree_paths:
                content_parts.append("## Project Workspace\n")
                content_parts.append(f"Your project code is at `{wt_path}`. **All code changes must be made here.**")
                content_parts.append(f"Run `cd {wt_path}` before starting any code work.\n")
                content_parts.append(
                    f"Scratch space: `{wt_path}/.massgen_scratch/` "
                    f"(git-excluded, for experiments)\n"
                    f"  - Verification: `.massgen_scratch/verification/` — save test output, "
                    f"screenshots, videos here to confirm your work is correct before submitting\n",
                )
                content_parts.append(
                    f"**Important**: Internal files (`tasks/changedoc.md`, `tasks/evolving_skill/`, "
                    f"implementation checklists) belong in your main workspace directory, NOT in the "
                    f"project worktree at `{wt_path}`. Only write actual project deliverables to the worktree.\n",
                )

                content_parts.append("### Code Branches\n")
                if self.branch_name:
                    content_parts.append(
                        f"Your work is on branch `{self.branch_name}`. " "All changes are auto-committed when your turn ends. " "Manual commits are optional.\n",
                    )
                else:
                    content_parts.append(
                        "All changes are auto-committed when your turn ends. " "Manual commits are optional.\n",
                    )

                if self.other_branches:
                    if self.branch_diff_summaries:
                        content_parts.append("**Other agents' code changes:**")
                        for label, branch in self.other_branches.items():
                            summary = self.branch_diff_summaries.get(label, "")
                            if summary:
                                # First line is the stats, second line (indented) is the file list
                                summary_lines = summary.split("\n", 1)
                                content_parts.append(f"- {label} (`{branch}`) — {summary_lines[0]}")
                                if len(summary_lines) > 1:
                                    content_parts.append(f"  {summary_lines[1].strip()}")
                            else:
                                content_parts.append(f"- {label}: `{branch}`")
                    else:
                        content_parts.append("**Other agents' branches:**")
                        for label, branch in self.other_branches.items():
                            content_parts.append(f"- {label}: `{branch}`")
                    content_parts.append("\nUse `git diff <branch>` for full details, `git merge <branch>` to incorporate.\n")

        # Legacy two-tier workspace (deprecated, skipped when worktree_paths set)
        elif self.use_two_tier_workspace:
            content_parts.append("### Two-Tier Workspace Structure\n")
            content_parts.append("Your workspace has two directories for organizing your work:\n")
            content_parts.append("- **`scratch/`** - Use for working files, experiments, intermediate results, evaluation scripts")
            audience = "other agents" if self.decomposition_mode else "voters"
            content_parts.append(f"- **`deliverable/`** - Use for final outputs you want to showcase to {audience}\n")
            content_parts.append("**IMPORTANT: Deliverables must be self-contained and complete.**")
            content_parts.append("The `deliverable/` directory should contain everything needed to use your output:")
            content_parts.append("- All required files (not just one component)")
            content_parts.append("- Any dependencies, assets, or supporting files")
            content_parts.append("- A README explaining how to run/use it")
            content_parts.append(f"Think of `deliverable/` as a standalone package that {audience} can immediately use without needing files from `scratch/` or anywhere else.\n")
            content_parts.append("To promote files from scratch to deliverable, use standard file operations:")
            content_parts.append("- Copy: Use filesystem tools to copy files")
            content_parts.append("- Move: Use command line `mv` or filesystem move\n")
            reviewers = "Other agents" if self.decomposition_mode else "Voters"
            content_parts.append(f"**Note**: {reviewers} will see BOTH directories, so scratch/ helps them understand your process.\n")
            content_parts.append("### Git Version Control\n")
            content_parts.append("Your workspace is version controlled with git. Changes are automatically committed:")
            content_parts.append("- `[INIT]` - When workspace is created")
            content_parts.append("- `[SNAPSHOT]` - Before coordination checkpoints")
            content_parts.append("- `[TASK]` - When you complete a task with completion notes\n")
            content_parts.append("**Tip**: Use `git log --oneline` to see your work history. This can help you:")
            content_parts.append("- Review what you've accomplished")
            content_parts.append("- Find when specific changes were made")
            content_parts.append("- Recover previous versions if needed\n")

        if self.context_paths and not self.worktree_paths:
            content_parts.append("**Context paths**:")
            for path in self.context_paths:
                content_parts.append(f"- `{path}`")
            content_parts.append(
                "\nThese paths contain important context for your task. " "Review them before starting work.",
            )

        return "\n".join(content_parts)


class ProjectInstructionsSection(SystemPromptSection):
    """
    Project-specific instructions from CLAUDE.md or AGENTS.md files.

    Automatically discovers and includes project instruction files when they exist
    in context paths. Follows the agents.md standard (https://agents.md/) with
    hierarchical discovery - the closest CLAUDE.md or AGENTS.md to the context
    path wins.

    Priority order:
    1. CLAUDE.md (Claude Code specific)
    2. AGENTS.md (universal standard - 60k+ projects)

    Discovery algorithm:
    - Starts at context path directory
    - Walks UP the directory tree searching for instruction files
    - Returns first CLAUDE.md or AGENTS.md found (closest wins)
    - CLAUDE.md takes precedence over AGENTS.md at same level
    - Stops at filesystem root or after 10 levels (safety limit)

    Args:
        context_paths: List of context path dictionaries (with "path" key)
        workspace_root: Agent workspace root (kept for backwards compatibility, not used for search boundary)
    """

    def __init__(self, context_paths: list[dict[str, str]], workspace_root: str):
        super().__init__(
            title="Project Instructions",
            priority=Priority.HIGH,  # Important context, but not operational instructions
            xml_tag="project_instructions",
        )
        self.context_paths = context_paths
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()

    def discover_instruction_file(self, context_path: Path) -> Path | None:
        """
        Walk up from context_path searching for CLAUDE.md or AGENTS.md.
        Returns the closest instruction file found.
        CLAUDE.md takes precedence over AGENTS.md at the same level.

        Stops searching when:
        1. An instruction file is found (success)
        2. We reach the filesystem root (no more parents)
        3. We've searched up to a reasonable depth (safety limit)
        """
        current = context_path if context_path.is_dir() else context_path.parent

        # Safety limit: search up to 10 levels max (prevents infinite loops)
        max_depth = 10
        depth = 0

        # Walk up directory hierarchy
        while current and depth < max_depth:
            # Priority 1: CLAUDE.md (Claude-specific)
            claude_md = current / "CLAUDE.md"
            if claude_md.exists() and claude_md.is_file():
                return claude_md

            # Priority 2: AGENTS.md (universal standard)
            agents_md = current / "AGENTS.md"
            if agents_md.exists() and agents_md.is_file():
                return agents_md

            # Stop at filesystem root
            parent = current.parent
            if parent == current:
                break

            current = parent
            depth += 1

        return None

    def build_content(self) -> str:
        """
        Discover and inject CLAUDE.md/AGENTS.md contents from context paths.
        Uses "closest wins" semantics - only one instruction file per context path.
        """
        # Collect discovered instruction files (deduplicate by path)
        discovered_files = {}  # path -> file_path mapping

        for ctx_path in self.context_paths:
            path_str = ctx_path.get("path", "")
            if not path_str:
                continue

            try:
                path = Path(path_str).resolve()

                # Check if path IS an instruction file directly
                if path.name in ["CLAUDE.md", "AGENTS.md"]:
                    if path.exists() and path.is_file():
                        discovered_files[str(path)] = path
                        continue

                # Otherwise, discover from directory hierarchy
                instruction_file = self.discover_instruction_file(path)
                if instruction_file:
                    discovered_files[str(instruction_file)] = instruction_file

            except Exception as e:
                logger.warning(f"Error checking context path {path_str} for instruction files: {e}")

        if not discovered_files:
            return ""  # No instruction files found

        # Read and format contents
        content_parts = []

        for file_path in discovered_files.values():
            try:
                contents = file_path.read_text(encoding="utf-8")
                # Dedent/clean up any leading/trailing whitespace
                contents = contents.strip()

                logger.info(f"[ProjectInstructionsSection] Loaded {file_path.name} ({len(contents)} chars)")
                content_parts.append(f"**From {file_path.name}** (`{file_path}`):")
                content_parts.append(contents)

            except Exception as e:
                logger.warning(f"Could not read instruction file {file_path}: {e}")

        if not content_parts:
            return ""  # Failed to read any files

        # Format with appropriate framing
        # NOTE: We follow Claude in using a softer framing than strict "Follow these instructions"
        # because this context may or may not be relevant to the current task
        header = [
            "The following project instructions were found in your context paths.",
            "",
            "**IMPORTANT**: This context may or may not be relevant to your current task.",
            "Use these instructions as helpful reference material when applicable,",
            "but do not feel obligated to follow guidance that doesn't apply to what you're doing.",
            "",
        ]

        return "\n".join(header + content_parts)


class CommandExecutionSection(SystemPromptSection):
    """
    Command execution environment and instructions.

    Documents the execution environment (Docker vs native), available packages,
    and any restrictions.

    NOTE: Package list is manually maintained and should match massgen/docker/Dockerfile.
    TODO: Consider auto-generating this from the Dockerfile for accuracy.

    Args:
        docker_mode: Whether commands execute in Docker containers
        enable_sudo: Whether sudo is available in Docker containers
        concurrent_tool_execution: Whether tools execute in parallel
    """

    def __init__(self, docker_mode: bool = False, enable_sudo: bool = False, concurrent_tool_execution: bool = False):
        super().__init__(
            title="Command Execution",
            priority=Priority.MEDIUM,
            xml_tag="command_execution",
        )
        self.docker_mode = docker_mode
        self.enable_sudo = enable_sudo
        self.concurrent_tool_execution = concurrent_tool_execution

    def build_content(self) -> str:
        parts = ["## Command Execution"]
        parts.append("You can run command line commands using your command execution tool.")
        parts.append("**Efficiency**: Batch multiple commands in one call using `&&` (e.g., `ls servers/ && ls custom_tools/`)\n")
        parts.append("### Background Tool Execution")
        parts.append("Always run `read_media` and `generate_media` in background.")
        parts.append(
            "Order matters: create `CONTEXT.md` first, then start any `read_media` background job. " "`generate_media` does not require CONTEXT.md.",
        )
        parts.append(
            "Only run them in foreground when the user explicitly needs an immediate blocking result " "(set `background: false` on that call).",
        )
        parts.append(
            "For `execute_command`, choose background mode only for long-running work " "(for example: test suites, installs, crawls, benchmarks, or long server runs).",
        )
        parts.append(
            "Use foreground when output is needed immediately " "(for example: quick `ls`, `pwd`, `cat`, `git status`, or short grep checks).",
        )
        parts.append(
            "For other tools, use your judgment: run in background when the call is slow and " "you can continue meaningful work without waiting for its result.",
        )
        parts.append(
            "Simplest for custom tools: set `background: true` directly on the tool call " "(keep normal tool arguments unchanged).",
        )
        parts.append(
            "Pass tool arguments as JSON objects (normal key/value fields), " "not escaped or stringified JSON blobs.",
        )
        parts.append(
            "Use `custom_tool__start_background_tool` when you need wrapper-style lifecycle control " "or for tools where direct background control is not practical.",
        )
        parts.append("Use this lifecycle:")
        parts.append("- Start: `custom_tool__start_background_tool`")
        parts.append("- Check progress: `custom_tool__get_background_tool_status`")
        parts.append("- Fetch final output when complete: `custom_tool__get_background_tool_result`")
        parts.append("- Cancel if no longer needed: `custom_tool__cancel_background_tool`")
        parts.append(
            "- List running tasks (default): `custom_tool__list_background_tools`; " "use `include_all: true` to include completed history",
        )
        parts.append("- Block until next completion (when idle): `custom_tool__wait_for_background_tool`")
        parts.append(
            "If no meaningful work remains while waiting on background jobs, " "call `custom_tool__wait_for_background_tool` instead of tight polling loops.",
        )
        parts.append(
            "The wait call may return early with `interrupted: true` and `injected_content` " "when runtime input or completion updates are ready; treat that payload as new context and continue.",
        )
        parts.append(
            "Background results may be auto-injected on a later turn. If not injected, poll status and then fetch the result manually.\n",
        )

        if self.docker_mode:
            parts.append("**IMPORTANT: Docker Execution Environment**")
            parts.append("- You are running in a Linux Docker container (Debian-based)")
            parts.append("- Base image: Python 3.11-slim with Node.js 20.x LTS")
            parts.append(
                "- Pre-installed packages:\n"
                "  - System: git, curl, build-essential, ripgrep, gh (GitHub CLI)\n"
                "  - Python: pytest, requests, numpy, pandas, ast-grep-cli\n"
                "  - Node: npm, openskills (global)",
            )
            parts.append("- Use `apt-get` for system packages (NOT brew, dnf, yum, etc.)")

            if self.enable_sudo:
                parts.append(
                    "- **Sudo is available**: You can install packages with " "`sudo apt-get install <package>`",
                )
                parts.append("- Example: `sudo apt-get update && sudo apt-get install -y ffmpeg`")
            else:
                parts.append("- Sudo is NOT available - use pip/npm for user-level packages only")
                parts.append(
                    "- For system packages, ask the user to rebuild the Docker image with " "needed packages",
                )

            parts.append("")

        if self.concurrent_tool_execution:
            parts.append("**PARALLEL TOOL EXECUTION ENABLED**")
            parts.append("- Multiple tool calls in your response will execute SIMULTANEOUSLY, not sequentially")
            parts.append("- Do NOT call dependent tools together in the same response:")
            parts.append("  - BAD: creating a directory + writing a file into it (directory may not exist yet)")
            parts.append("  - BAD: starting a server + curling it in the same response (server not ready)")
            parts.append("- Each tool call should be independent and not rely on another tool's output")
            parts.append("- If you need sequential execution, make separate responses for each step")
            parts.append("")

        return "\n".join(parts)


class FilesystemOperationsSection(SystemPromptSection):
    """
    Filesystem tool usage instructions.

    Documents how to use filesystem tools for creating answers, managing
    files, and coordinating with other agents.

    Args:
        main_workspace: Path to agent's main workspace
        temp_workspace: Path to shared reference workspace
        context_paths: List of context paths with permissions
        previous_turns: List of previous turn metadata
        workspace_prepopulated: Whether workspace is pre-populated
        agent_answers: Dict of agent answers to show workspace structure
        enable_command_execution: Whether command line execution is enabled
    """

    def __init__(
        self,
        main_workspace: str | None = None,
        temp_workspace: str | None = None,
        context_paths: list[dict[str, str]] | None = None,
        previous_turns: list[dict[str, Any]] | None = None,
        workspace_prepopulated: bool = False,
        agent_answers: dict[str, str] | None = None,
        enable_command_execution: bool = False,
        agent_mapping: dict[str, str] | None = None,
        has_native_tools: bool = False,
    ):
        super().__init__(
            title="Filesystem Operations",
            priority=Priority.MEDIUM,
            xml_tag="filesystem_operations",
        )
        self.main_workspace = main_workspace
        self.temp_workspace = temp_workspace
        self.context_paths = context_paths or []
        self.previous_turns = previous_turns or []
        self.workspace_prepopulated = workspace_prepopulated
        self.agent_answers = agent_answers
        self.enable_command_execution = enable_command_execution
        self.agent_mapping = agent_mapping  # Optional: from coordination_tracker.get_reverse_agent_mapping()
        self.has_native_tools = has_native_tools  # True when backend has native file tools (skip MCP-specific language)

    def build_content(self) -> str:
        parts = ["## Filesystem Access"]

        # Explain workspace behavior
        parts.append(
            "Your working directory is set to your workspace, so all relative paths in your file "
            "operations will be resolved from there. This ensures each agent works in isolation "
            "while having access to shared references. Move intermediate files to scratch space "
            "rather than deleting them.\n",
        )

        if self.main_workspace:
            workspace_note = f"**Your Workspace**: `{self.main_workspace}` - Write actual files here using " "file tools. All your file operations will be relative to this directory."
            if self.workspace_prepopulated:
                workspace_note += (
                    " **Note**: Your workspace already contains a writable copy of the previous "
                    "turn's results - you can modify or build upon these files. The original "
                    "unmodified version is also available as a read-only context path if you need "
                    "to reference what was originally there."
                )
            parts.append(workspace_note)

        if self.temp_workspace:
            # Build workspace tree structure
            workspace_tree = f"**Shared Reference**: `{self.temp_workspace}` - Contains previous answers from " "all agents (read/execute-only)\n"

            # Add agent subdirectories in tree format
            if self.agent_answers:
                # Use provided mapping or create from agent_answers keys (legacy behavior)
                if self.agent_mapping:
                    # Filter to only agents with answers, maintain global numbering
                    agent_mapping = {aid: self.agent_mapping[aid] for aid in self.agent_answers.keys() if aid in self.agent_mapping}
                else:
                    agent_mapping = {}
                    for i, agent_id in enumerate(sorted(self.agent_answers.keys()), 1):
                        agent_mapping[agent_id] = f"agent{i}"

                workspace_tree += "   Available agent workspaces:\n"
                # Sort by anon ID to ensure consistent display order
                agent_items = sorted(agent_mapping.items(), key=lambda x: x[1])
                for idx, (agent_id, anon_id) in enumerate(agent_items):
                    is_last = idx == len(agent_items) - 1
                    prefix = "   └── " if is_last else "   ├── "
                    workspace_tree += f"{prefix}{self.temp_workspace}/{anon_id}/\n"

            workspace_tree += (
                "   **Building on Others' Work:**\n"
                "   - **Inspect First**: Examine files before copying to understand what you're "
                "working with.\n"
                "   - **Selective Copying**: Only copy specific files you'll actually modify or "
                "use, not entire directories wholesale.\n"
                "   - **Merging Approaches**: If combining work from multiple agents, consider "
                "merging complementary parts (e.g., agent1's data model + agent2's API layer) "
                "rather than picking one entire solution.\n"
                "   - **Attribution**: Be explicit in your answer about what you built on (e.g., "
                "'Extended agent1's parser.py to handle edge cases').\n"
                "   - **Verify Files**: Not all workspaces may have matching answers in CURRENT "
                "ANSWERS section (restart scenarios). Check actual files in Shared Reference.\n"
            )
            parts.append(workspace_tree)

        if self.context_paths:
            has_target = any(p.get("will_be_writable", False) for p in self.context_paths)
            has_readonly_context = any(not p.get("will_be_writable", False) and p.get("permission") == "read" for p in self.context_paths)

            if has_target:
                parts.append(
                    "\n**Important Context**: If the user asks about improving, fixing, debugging, "
                    "or understanding an existing code/project (e.g., 'Why is this code not "
                    "working?', 'Fix this bug', 'Add feature X'), they are referring to the Target "
                    "Path below. First READ the existing files from that path to understand what's "
                    "there, then make your changes based on that codebase. Final deliverables must "
                    "end up there.\n",
                )
            elif has_readonly_context:
                parts.append(
                    "\n**Important Context**: If the user asks about debugging or understanding an "
                    "existing code/project (e.g., 'Why is this code not working?', 'Explain this "
                    "bug'), they are referring to (one of) the Context Path(s) below. Read then "
                    "provide analysis/explanation based on that codebase - you cannot modify it "
                    "directly.\n",
                )

            for path_config in self.context_paths:
                path = path_config.get("path", "")
                permission = path_config.get("permission", "read")
                will_be_writable = path_config.get("will_be_writable", False)
                if path:
                    if permission == "read" and will_be_writable:
                        parts.append(
                            f"**Target Path**: `{path}` (read-only now, write access later) - This "
                            "is where your changes will be delivered. Work in your workspace first, "
                            f"then the final presenter will place or update files DIRECTLY into "
                            f"`{path}` using the FULL ABSOLUTE PATH.",
                        )
                    elif permission == "write":
                        parts.append(
                            f"**Target Path**: `{path}` (write access) - This is where your changes "
                            "must be delivered. First, ensure you place your answer in your "
                            f"workspace, then copy/write files DIRECTLY into `{path}` using FULL "
                            f"ABSOLUTE PATH (not relative paths). Files must go directly into the "
                            f"target path itself (e.g., `{path}/file.txt`), NOT into a `.massgen/` "
                            "subdirectory within it.",
                        )
                    else:
                        parts.append(
                            f"**Context Path**: `{path}` (read-only) - Use FULL ABSOLUTE PATH when " "reading.",
                        )

        # Add note about multi-turn conversations
        if self.previous_turns:
            parts.append(
                "\n**Note**: This is a multi-turn conversation. Each User/Assistant exchange in "
                "the conversation history represents one turn. The workspace from each turn is "
                "available as a read-only context path listed above (e.g., turn 1's workspace is "
                "at the path ending in `/turn_1/workspace`).",
            )

        # Add task handling priority
        parts.append(
            "\n**Task Handling Priority**: When responding to user requests, follow this priority "
            "order:\n"
            "1. **Use Tools First**: If you have specialized tools available, call them "
            "DIRECTLY to complete the task\n"
            "   - Save any outputs/artifacts to your workspace\n"
            "2. **Write Code If Needed**: If tools cannot complete the task, write and execute "
            "code\n"
            "3. **Create Other Files**: Create configs, documents, or other deliverables as "
            "needed\n"
            "4. **Text Response Otherwise**: If no tools or files are needed, provide a direct "
            "text answer\n\n"
            "**Important**: Do NOT ask the user for clarification or additional input. Make "
            "reasonable assumptions and proceed with sensible defaults. You will not receive user "
            "feedback, so complete the task autonomously based on the original request.\n",
        )

        # Add new answer guidance
        new_answer_guidance = "\n**New Answer**: When calling `new_answer`:\n"
        if self.enable_command_execution:
            new_answer_guidance += "- If you executed commands (e.g., running tests), explain the results in your " "answer (what passed, what failed, what the output shows)\n"
        new_answer_guidance += "- If you created files, list your cwd and file paths (but do NOT paste full file " "contents)\n"
        new_answer_guidance += "- If providing a text response, include your analysis/explanation in the `content` " "field\n"
        parts.append(new_answer_guidance)

        return "\n".join(parts)


class FilesystemBestPracticesSection(SystemPromptSection):
    """
    Optional filesystem best practices and tips.

    Lower priority guidance about workspace cleanup, comparison tools, and evaluation.

    Args:
        enable_code_based_tools: Whether code-based tools mode is enabled
    """

    def __init__(self, enable_code_based_tools: bool = False, decomposition_mode: bool = False):
        super().__init__(
            title="Filesystem Best Practices",
            priority=Priority.AUXILIARY,
            xml_tag="filesystem_best_practices",
        )
        self.enable_code_based_tools = enable_code_based_tools
        self.decomposition_mode = decomposition_mode

    def build_content(self) -> str:
        parts = []

        # Workspace management guidance
        parts.append(
            "**Workspace Management**: \n"
            "- **Selective Copying**: When building on other agents' work, only copy the specific "
            "files you need to modify or use. Do not copy entire workspaces wholesale. Be explicit "
            "about what you're building on (e.g., 'Using agent1's parser.py with "
            "modifications').\n"
            "- **Never Copy Gitignored Files**: Do NOT copy files/directories that are typically "
            "gitignored: `node_modules/`, `__pycache__/`, `.git/`, `venv/`, `env/`, `.env`, "
            "`dist/`, `build/`, `*.pyc`, `.cache/`, etc. These files are regenerated by running "
            "`npm install`, `pip install`, or build commands. Copying them breaks symlinks and "
            "causes errors. Instead, include proper dependency files (`package.json`, "
            "`requirements.txt`) and let users reinstall.\n"
            "- **Cleanup**: Move temporary files, intermediate artifacts, test scripts, or "
            "unused files to scratch space (`.massgen_scratch/` or `scratch/`) before submitting "
            "`new_answer`. Your workspace should contain only the files that are part of your "
            "final deliverable. For example, move `test_output.txt` or `old_version.py` to scratch. "
            "**Never delete system-managed directories**: `.worktree/`, `.git/`, symlinks to shared "
            "tools, or any directory you did not create.\n"
            "- **Verification Artifacts**: Save test results, screenshots, videos, and other "
            "verification evidence to `.massgen_scratch/verification/`. These are preserved "
            "in scratch archives for reference in subsequent rounds.\n"
            "- **Organization**: Keep files logically organized. If you're combining work from "
            "multiple agents, structure the result clearly.\n"
            "- **Internal Documents**: Never write internal documents (decision journals, evolving "
            "skills, checklists) to the project directory. These belong in your main workspace.\n",
        )

        # Comparison tools (conditional on mode)
        finalize_phrase = "before finalizing your work" if self.decomposition_mode else "before voting"
        if self.enable_code_based_tools:
            parts.append(
                "**Comparison Tools**: Use directory and file comparison operations to understand "
                "differences between workspaces or versions. These read-only operations help you "
                "understand what changed, build upon existing work effectively, or verify solutions "
                f"{finalize_phrase}.\n",
            )
        else:
            parts.append(
                "**Comparison Tools**: Use directory and file comparison tools to see differences "
                "between workspaces or versions. These read-only tools help you understand what "
                f"changed, build upon existing work effectively, or verify solutions {finalize_phrase}.\n",
            )

        # Evaluation guidance - emphasize outcome-based evaluation
        parts.append(
            "**Evaluation**: When evaluating agents' answers, assess both implementation and results:\n"
            "- **For code quality**: Verify key files or substantially different implementations in "
            "their workspaces (via Shared Reference)\n"
            "- **For functionality**: Evaluate outcomes by running tests, checking visualizations, "
            "validating outputs, or testing the deliverables\n"
            "- **Run your own verification**: Do not rely solely on agents' self-reported results. "
            "Run tests, take screenshots, and validate deliverables yourself. Save your "
            "verification evidence to `.massgen_scratch/verification/{agentN}/` (create subdirs "
            "as needed per agent you're evaluating). Agents' own verification may be available "
            "in their Shared Reference under `.scratch_archive/{agentN}/verification/` as "
            "optional context, but it may be incomplete or stale — always verify independently.\n"
            "- **Focus verification**: Prioritize critical functionality and substantial differences "
            "rather than exhaustively reviewing every file\n"
            "- **Don't rely solely on answer text**: Ensure the actual work matches their claims\n",
        )

        return "\n".join(parts)


class FilesystemSection(SystemPromptSection):
    """
    Parent section for all filesystem-related instructions.

    Breaks the monolithic filesystem instructions into three prioritized
    subsections:
    1. Workspace structure (HIGH) - Must-know paths
    2. Operations (MEDIUM) - Tool usage
    3. Best practices (AUXILIARY) - Optional guidance

    Args:
        workspace_path: Path to agent's workspace
        context_paths: List of context paths
        main_workspace: Path to agent's main workspace
        temp_workspace: Path to shared reference workspace
        previous_turns: List of previous turn metadata
        workspace_prepopulated: Whether workspace is pre-populated
        agent_answers: Dict of agent answers to show workspace structure
        enable_command_execution: Whether command line execution is enabled
        docker_mode: Whether commands execute in Docker containers
        enable_sudo: Whether sudo is available in Docker containers
        enable_code_based_tools: Whether code-based tools mode is enabled
        use_two_tier_workspace: Whether two-tier workspace (scratch/deliverable) is enabled
    """

    def __init__(
        self,
        workspace_path: str,
        context_paths: list[str],
        main_workspace: str | None = None,
        temp_workspace: str | None = None,
        context_paths_detailed: list[dict[str, str]] | None = None,
        previous_turns: list[dict[str, Any]] | None = None,
        workspace_prepopulated: bool = False,
        agent_answers: dict[str, str] | None = None,
        enable_command_execution: bool = False,
        docker_mode: bool = False,
        enable_sudo: bool = False,
        enable_code_based_tools: bool = False,
        use_two_tier_workspace: bool = False,
    ):
        super().__init__(
            title="Filesystem & Workspace",
            priority=Priority.HIGH,
            xml_tag="filesystem",
        )

        # Create subsections with appropriate priorities
        self.subsections = [
            WorkspaceStructureSection(workspace_path, context_paths, use_two_tier_workspace=use_two_tier_workspace),
            FilesystemOperationsSection(
                main_workspace=main_workspace,
                temp_workspace=temp_workspace,
                context_paths=context_paths_detailed,
                previous_turns=previous_turns,
                workspace_prepopulated=workspace_prepopulated,
                agent_answers=agent_answers,
                enable_command_execution=enable_command_execution,
            ),
            FilesystemBestPracticesSection(enable_code_based_tools=enable_code_based_tools),
        ]

        # Add command execution section if enabled
        if enable_command_execution:
            self.subsections.append(
                CommandExecutionSection(docker_mode=docker_mode, enable_sudo=enable_sudo),
            )

    def build_content(self) -> str:
        """Brief intro - subsections contain the details."""
        return "# Filesystem Instructions\n\n" "You have access to a filesystem-based workspace for managing your work " "and coordinating with other agents."


class TaskPlanningSection(SystemPromptSection):
    """
    Task planning guidance for complex multi-step tasks.

    Provides comprehensive instructions on when and how to use task planning
    tools for organizing multi-step work.

    Args:
        filesystem_mode: If True, includes guidance about filesystem-based task storage
    """

    def __init__(self, filesystem_mode: bool = False, decomposition_mode: bool = False):
        super().__init__(
            title="Task Planning",
            priority=Priority.MEDIUM,
            xml_tag="task_planning",
        )
        self.filesystem_mode = filesystem_mode
        self.decomposition_mode = decomposition_mode

    def build_content(self) -> str:
        base_guidance = """
# Task Planning and Management

You have access to task planning tools to organize complex work.

**IMPORTANT WORKFLOW - Plan Before Executing:**

When working on multi-step tasks:
1. **Think first** - Understand the requirements (some initial research/analysis is fine)
2. **Create your task plan EARLY** - Use the task plan tool BEFORE executing file operations or major
   actions
3. **Execute tasks** - Work through your plan systematically
4. **Update as you go** - Use the **add_task** tool to capture new requirements you discover

**DO NOT:**
- ❌ Jump straight into creating files without planning first
- ❌ Start executing complex work without a clear task breakdown
- ❌ Ignore the planning tools for multi-step work

**DO:**
- ✅ Create a task plan early, even if it's just 3-4 high-level tasks
- ✅ Refine your plan as you learn more (tasks can be added/edited/deleted)
- ✅ Brief initial analysis is OK before planning (e.g., reading docs, checking existing code)

**When to create a task plan:**
- Multi-step tasks with dependencies (most common)
- Multiple files or components to create
- Complex features requiring coordination
- Work that needs to be tracked or broken down
- Any task where you'd benefit from a checklist

**Skip task planning ONLY for:**
- Trivial single-step tasks
- Simple questions/analysis with no execution
- Quick one-off operations

**Tools available:**
- **create_task_plan** - Create a plan with tasks, dependencies, and verification criteria
- **get_ready_tasks** - Get tasks ready to start (dependencies satisfied)
- **get_blocked_tasks** - See what's waiting on dependencies
- **update_task_status** - Mark progress (pending/in_progress/completed/verified)
- **add_task** - Add new tasks (priority: low/medium/high, verification criteria required by default)
- **get_task_plan** - View your complete task plan
- **edit_task** - Update task descriptions
- **delete_task** - Remove tasks no longer needed

**Reading Tool Responses:**
Tool responses may include important reminders and guidance (e.g., when completing high-priority tasks,
you'll receive reminders to save learnings to memory). Always read tool response messages carefully.

**Recommended workflow:**
1. **Create your task plan** with tasks including verification criteria:
   - `{"id": "research", "description": "Research OAuth providers", "verification": "Comparison table with 3+ providers", "verification_method": "Review output table"}`
   - `{"id": "design", "description": "Design auth flow", "depends_on": ["research"], "verification": "Flow diagram renders correctly", "verification_method": "Screenshot and visual check"}`
   - `{"id": "implement", "description": "Implement endpoints", "depends_on": ["design"], "verification": "Endpoints return 200", "verification_method": "curl test each endpoint"}`
2. **Update task status** as you work: set status="in_progress", then "completed", then "verified" after confirming
3. **Add tasks** as you discover new requirements:
   - `description="Write integration tests", depends_on=["implement"], verification="Integration tests pass for auth flow", verification_method="Run integration test suite"`
4. **Check ready tasks** to see what's unblocked next

**Dependency formats:**
Tasks support two dependency styles:
- **By index** (0-based): `{"description": "Task 2", "depends_on": [0], "verification": "Task 2 output is complete"}` — depends on the first task
- **By ID** (recommended): `{"id": "api", "description": "Build API", "depends_on": ["auth"], "verification": "API returns expected responses"}` — depends on task with id "auth"

**IMPORTANT - Including Task Plan in Your Answer:**
If you created a task plan, include a summary at the end of your `new_answer` showing:
1. Each task name
2. Status: ✓ (verified), ◐ (completed but unverified), ✗ (not done)
3. Brief description of what you did

**Verification is required.** When you mark a task `completed`, you must then verify it
actually works (screenshots, tests, visual inspection) and mark it `verified`. Tasks left
at `completed` without verification are unverified — they will show as ◐ in your summary.

Example format:
```
[Your main answer content here]

---
**Task Execution Summary:**
✓ Research OAuth providers - Analyzed OAuth 2.0 spec and compared providers
✓ Design auth flow - Created flow diagram with PKCE and token refresh (verified: diagram renders correctly)
◐ Implement endpoints - Built /auth/login, /auth/callback, /auth/refresh (unverified: no test run yet)
✗ Write tests - Not started

Status: 2/4 verified, 1/4 completed (unverified), 1/4 not done
```

This helps other agents understand your approach and evaluate your work."""

        if self.filesystem_mode:
            filesystem_guidance = """

**Filesystem Mode Enabled:**
Your task plans are automatically saved to `tasks/plan.json` in your workspace. You can write notes
or comments in `tasks/notes.md` or other files in the `tasks/` directory.

*NOTE*: You will also have access to other agents' task plans in the shared reference."""
            return base_guidance + filesystem_guidance

        return base_guidance


class EvaluationSection(SystemPromptSection):
    """
    MassGen evaluation and coordination mechanics.

    Priority 2 places this after agent_identity(1) but before core_behaviors(3).
    This defines the fundamental MassGen primitives that the agent needs to understand:
    vote tool, new_answer tool, and coordination mechanics.

    Args:
        voting_sensitivity: Controls evaluation strictness ('lenient', 'balanced', 'strict', 'roi', 'sequential', 'adversarial', 'consistency', 'diversity', 'reflective')
        answer_novelty_requirement: Controls novelty requirements ('lenient', 'balanced', 'strict')
        vote_only: If True, agent has reached max answers and can only vote (no new_answer)
        round_number: Current round of coordination (used for sequential sensitivity)
    """

    def __init__(
        self,
        voting_sensitivity: str = "lenient",
        answer_novelty_requirement: str = "lenient",
        vote_only: bool = False,
        round_number: int = 1,
        voting_threshold: int | None = None,
        answers_used: int = 0,
        answer_cap: int | None = None,
        checklist_require_gap_report: bool = True,
        gap_report_mode: str = "changedoc",
        has_changedoc: bool = False,
        custom_checklist_items: list[str] | None = None,
        item_categories: dict[str, str] | None = None,
        item_verify_by: dict[str, str] | None = None,
        has_existing_answers: bool = True,
        builder_enabled: bool = True,
    ):
        super().__init__(
            title="MassGen Coordination",
            priority=2,  # After agent_identity(1), before core_behaviors(3)
            xml_tag="massgen_coordination",
        )
        self.voting_sensitivity = voting_sensitivity
        self.answer_novelty_requirement = answer_novelty_requirement
        self.vote_only = vote_only
        self.round_number = round_number
        self.voting_threshold = voting_threshold
        self.answers_used = answers_used
        self.answer_cap = answer_cap
        self.checklist_require_gap_report = checklist_require_gap_report
        self.gap_report_mode = gap_report_mode
        self.has_changedoc = has_changedoc
        self.custom_checklist_items = custom_checklist_items
        self.item_categories = item_categories
        self.item_verify_by = item_verify_by
        self.has_existing_answers = has_existing_answers
        self.builder_enabled = builder_enabled

    def build_content(self) -> str:
        # Vote-only mode: agent has exhausted their answer limit
        if self.vote_only:
            return f"""You are evaluating existing solutions to determine the best answer.

You have provided your maximum number of new answers. Now you MUST vote for the best existing answer.

Analyze the existing answers carefully, then call the `vote` tool to select the best one.

Note: All your other tools are still available to help you evaluate answers. The only restriction is that `vote` is your only workflow tool - you cannot submit new answers.

*Note*: The CURRENT TIME is **{time.strftime("%Y-%m-%d")}**."""

        # Handle sequential sensitivity: reverse order (strict -> balanced -> lenient)
        effective_sensitivity = self.voting_sensitivity
        phase_context = ""
        if self.voting_sensitivity == "sequential":
            if self.round_number <= 1:
                effective_sensitivity = "strict"
                coordination_phase = "EXPLORATION (Round 1): High-rigor phase to ensure diverse and robust initial solutions. Avoid voting unless the answer is exceptional."
            elif self.round_number <= 2:
                effective_sensitivity = "balanced"
                coordination_phase = "CONVERGENCE (Round 2): Balanced evaluation to identify gaps and begin merging the best components of existing answers."
            else:
                effective_sensitivity = "lenient"
                coordination_phase = f"FINALIZATION (Round {self.round_number}): Lean evaluation to ensure timely delivery of the polished final result."

            phase_context = f"\n**COORDINATION STRATEGY**: {coordination_phase}\n"

        # Determine evaluation criteria based on effective sensitivity
        if effective_sensitivity == "strict":
            evaluation_section = """**CRITICAL RUBRIC-BASED EVALUATION (STRICT)**

**Step 0: Per-Answer Strengths**
For each existing answer, identify its strongest contributions — what does this
answer do better than the others? This ensures your evaluation draws from all
available work, not just one.

Before you can vote, you MUST evaluate the best answer against this rubric:
1. **Correctness & Robustness**: Is the logic sound? Does it handle edge cases and potential errors?
2. **Completeness & Optimization**: Does it address ALL requirements efficiently without bloat?
3. **Clarity & Quality**: Is it production-grade with crystal clear explanations?

**Scoring Guide (Internal):**
- 3: Excellent (No room for improvement)
- 2: Good (Minor gaps)
- 1: Fair (Significant gaps)
- 0: Poor (Fails criterion)

**Step 1: Identify Weaknesses**
List specific gaps in the rubric above.

**Step 2: Decision**
- If you can improve ANY rubric item's score -> `new_answer`
- If the answer already scores 3/3 on all items -> `vote`

You may NOT vote if you can provide a substantively better solution."""
        elif effective_sensitivity == "balanced":
            evaluation_section = """**RUBRIC-BASED EVALUATION (BALANCED)**

**Per-Answer Analysis**: For each existing answer, note its specific strengths
and weaknesses. Use this to inform whether synthesis would produce
a better result.

Critically examine existing answers against these criteria:
1. **Alignment**: Does the answer directly and fully address the user's intent?
2. **Accuracy**: Are tool calls, parameters, and logic correct?
3. **Completeness**: Are there any missing steps or information?

**Before voting:**
1. Identify at least 1 weakness or missed opportunity.
2. Can you fix it or combine with another answer to address it?

If you CAN improve the answer's alignment, accuracy, or completeness, produce a `new_answer`."""
        elif effective_sensitivity.startswith("roi"):
            if self.voting_threshold is not None:
                threshold = self.voting_threshold
            elif effective_sensitivity == "roi_conservative":
                threshold = 30
            elif effective_sensitivity == "roi_aggressive":
                threshold = 5
            else:
                threshold = 15

            roi_block = build_roi_decision_block(
                threshold,
                answers_used=self.answers_used,
                answer_cap=self.answer_cap,
                iterate_action="new_answer",
                satisfied_action="vote",
                satisfied_detail="for the best existing answer",
            )

            evaluation_section = f"""**ROI-BASED EVALUATION**

Your goal is to iteratively refine answers until they meet the quality bar.

{roi_block}"""
        elif effective_sensitivity in ("checklist", "checklist_scored"):
            remaining = max(0, (self.answer_cap or 5) - self.answers_used)
            total = self.answer_cap or 5
            threshold = self.voting_threshold if self.voting_threshold is not None else 5

            items = self.custom_checklist_items if self.custom_checklist_items is not None else (_CHECKLIST_ITEMS_CHANGEDOC if self.has_changedoc else _CHECKLIST_ITEMS)
            analysis = (
                _build_changedoc_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                if self.has_changedoc
                else _build_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
            )
            if effective_sensitivity == "checklist":
                decision = _build_checklist_decision(
                    threshold,
                    remaining,
                    total,
                    items,
                )
            else:
                decision = _build_checklist_scored_decision(
                    threshold,
                    remaining,
                    total,
                    items,
                )
            evaluation_section = f"""{analysis}

{decision}"""
        elif effective_sensitivity == "checklist_gated":
            if not self.has_existing_answers:
                # Round 1 — no prior answers to evaluate against. Skip checklist instructions
                # entirely; agent should build and submit directly.
                evaluation_section = (
                    "## Decision\n\n"
                    "**Round 1 — First Answer:** Build your best initial version and submit it "
                    "via the `new_answer` workflow tool. Verify your work before submitting. "
                    "Checklist-based evaluation begins in round 2 when there are prior answers "
                    "to compare against."
                )
            else:
                items = self.custom_checklist_items if self.custom_checklist_items is not None else (_CHECKLIST_ITEMS_CHANGEDOC if self.has_changedoc else _CHECKLIST_ITEMS)
                analysis = (
                    _build_changedoc_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                    if self.has_changedoc
                    else _build_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                )
                decision = _build_checklist_gated_decision(
                    items,
                    require_gap_report=self.checklist_require_gap_report,
                    gap_report_mode=self.gap_report_mode,
                    builder_enabled=self.builder_enabled,
                )
                evaluation_section = f"""{analysis}

{decision}"""
        elif effective_sensitivity == "adversarial":
            evaluation_section = """**ADVERSARIAL EVALUATION (INTERNAL RED-TEAMING)**

You are a skeptic. Before voting YES, you MUST perform a 'pre-mortem' on the best answer.

**The Pre-Mortem Challenge:**
0. Before red-teaming, identify what each answer does uniquely well — a flaw
   in one answer may already be solved by another.
1. Imagine the current best answer has been delivered and **FAILED** completely.
2. What is the most likely cause of that failure? (e.g., hidden edge case, missing dependency, logical flaw, security risk).
3. If you can identify a plausible failure mode, you MUST provide a `new_answer` that hardens the solution against it.

**Decision Rule:**
- If you find a way to 'break' the solution -> `new_answer`
- If the solution is resilient to your most aggressive attempts to find flaws -> `vote`"""
        elif effective_sensitivity == "consistency":
            evaluation_section = """**LOGICAL CONSISTENCY CHECK**

Before voting, you MUST independently re-derive the logic of the best answer.

**The Verification Process:**
0. Before re-deriving, note which answers take different approaches. If multiple
   approaches exist, evaluate each answer independently before picking one to verify.
1. **Re-derive**: Without looking at the answer's steps, how would YOU solve this?
2. **Compare**: Where does the best answer differ from your re-derivation?
3. **Validate**: Is the difference an improvement, or a potential logical error?

**Decision Rule:**
- If you find a logical inconsistency or a more sound path -> `new_answer`
- If the answer's logic is sound and matches your independent derivation -> `vote`"""
        elif effective_sensitivity == "diversity":
            evaluation_section = """**DIVERSITY-AWARE SYNTHESIS**

Your goal is to ensure the final solution incorporates the best unique insights from ALL existing answers.

**The Synthesis Challenge:**
1. List the unique strengths of **at least two** different existing answers.
2. Does the current best answer capture all of these strengths?
3. Can you combine these insights into a single, more powerful solution?

**Decision Rule:**
- If you can synthesize a more comprehensive answer by combining insights -> `new_answer`
- If the best answer already achieves the best possible synthesis -> `vote`"""
        elif effective_sensitivity == "reflective":
            evaluation_section = """**REFLECTIVE USER-INTENT EVALUATION**

Before evaluating, you must explicitly restate and reflect on the user's ultimate goal.

**Reflection Steps:**
0. **Per-Answer Fit**: Which answers best serve which success criteria? Different
   answers may excel at different criteria — identify these before judging.
1. **Restate Intent**: "The user's core intent is..."
2. **Success Criteria**: Define 3 specific criteria that must be met for the user to be delighted.
3. **Gap Analysis**: Does the best answer meet all 3 criteria perfectly?

**Decision Rule:**
- If there is any gap between the answer and the user's delight criteria -> `new_answer`
- If the answer perfectly fulfills the refined success criteria -> `vote`"""
        else:
            # Default to lenient (including explicit "lenient" or any other value)
            evaluation_section = """Does the best CURRENT ANSWER address the ORIGINAL MESSAGE well?

If YES, use the `vote` tool to record your vote and skip the `new_answer` tool."""

        # Add novelty requirement instructions if not lenient
        novelty_section = ""
        if self.answer_novelty_requirement == "balanced":
            novelty_section = """
IMPORTANT: If you provide a new answer, it must be meaningfully different from existing answers.
- Don't just rephrase or reword existing solutions
- Introduce new insights, approaches, or tools
- Make substantive improvements, not cosmetic changes"""
        elif self.answer_novelty_requirement == "strict":
            novelty_section = """
CRITICAL: New answers must be SUBSTANTIALLY different from existing answers.
- Use a fundamentally different approach or methodology
- Employ different tools or techniques
- Provide significantly more depth or novel perspectives
- If you cannot provide a truly novel solution, vote instead"""

        return f"""You are evaluating answers from multiple agents for final response to a message.
Different agents may have different builtin tools and capabilities.
{phase_context}{evaluation_section}
Otherwise, use the `new_answer` tool to record a better answer to the ORIGINAL MESSAGE.
Before building a new answer, identify the strongest element from each existing answer —
not just the best overall. Different answers may excel at different aspects.

You have two strategies:
- **Synthesize**: Take the best elements from multiple answers and combine them.
  Name which specific elements you're taking from which answer.
- **Rethink**: Keep what works from any answer but take a fundamentally different
  approach for the weakest parts. Explain what you're keeping and what you're replacing.
Both are valid. If all existing answers are converging on the same approach, rethinking
is especially valuable.
Each iteration costs time and resources. When you produce a `new_answer`, the result must be
**obviously and substantially better** — a user should immediately see the improvement.
Identify concrete improvements, then actually implement them — do not just acknowledge gaps.{novelty_section}
**ANSWER FORMAT GUIDELINES:**
When calling `new_answer`, your content should be HIGH-LEVEL and concise:
✓ DO:
- State what you created/accomplished
- Specify where files are located (workspace paths)
- Explain how to run/use it
- List key features or improvements
- Include task completion status if using task planning
✗ DON'T:
- Include full code listings (code belongs in workspace files)
- Copy-paste entire file contents
- Include implementation details that other agents don't need
EXAMPLE FORMAT:
```
I created a Snake game with mobile support and saved it to deliverable/.
Workspace: /workspace/agent1/
Files created:
- deliverable/index.html (main game)
- deliverable/README.md (instructions)
How to run:
1. Open deliverable/index.html in a browser
Features:
- Keyboard and touch controls
- Scoring system
- Responsive design
Task Status: 5/5 completed
```
Remember: Other agents will see your answer as context. Keep it focused on WHAT you delivered, not HOW you implemented it.

Make sure you actually call `vote` or `new_answer` (in tool call format).

*Note*: The CURRENT TIME is **{time.strftime("%Y-%m-%d")}**."""


class DecompositionSection(SystemPromptSection):
    """
    MassGen decomposition mode coordination mechanics.

    In decomposition mode, each agent owns a specific subtask and uses `stop`
    instead of `vote` to signal completion. Agents refine their own work and
    integrate relevant parts of other agents' contributions.

    Same priority slot as EvaluationSection (Priority 2 / CRITICAL).

    Args:
        subtask: The agent's assigned subtask description (if any)
    """

    def __init__(
        self,
        subtask: str | None = None,
        voting_threshold: int | None = None,
        voting_sensitivity: str = "roi",
        answers_used: int = 0,
        answer_cap: int | None = None,
        checklist_require_gap_report: bool = True,
        gap_report_mode: str = "changedoc",
        has_changedoc: bool = False,
        custom_checklist_items: list[str] | None = None,
        item_categories: dict[str, str] | None = None,
        item_verify_by: dict[str, str] | None = None,
    ):
        super().__init__(
            title="MassGen Decomposition Coordination",
            priority=2,  # Same slot as EvaluationSection
            xml_tag="massgen_coordination",
        )
        self.subtask = subtask
        self.voting_threshold = voting_threshold
        self.voting_sensitivity = voting_sensitivity
        self.answers_used = answers_used
        self.answer_cap = answer_cap
        self.checklist_require_gap_report = checklist_require_gap_report
        self.gap_report_mode = gap_report_mode
        self.has_changedoc = has_changedoc
        self.custom_checklist_items = custom_checklist_items
        self.item_categories = item_categories
        self.item_verify_by = item_verify_by

    def _build_decision_block(self) -> str:
        """Build the new_answer vs stop decision block, threshold-aware if set."""
        if self.voting_threshold is not None:
            remaining = max(0, (self.answer_cap or 5) - self.answers_used)
            total = self.answer_cap or 5

            if self.voting_sensitivity in ("checklist", "checklist_scored"):
                items = self.custom_checklist_items if self.custom_checklist_items is not None else (_CHECKLIST_ITEMS_CHANGEDOC if self.has_changedoc else _CHECKLIST_ITEMS)
                analysis = (
                    _build_changedoc_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                    if self.has_changedoc
                    else _build_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                )
                if self.voting_sensitivity == "checklist":
                    decision = _build_checklist_decision(
                        self.voting_threshold,
                        remaining,
                        total,
                        items,
                        terminate_action="stop",
                        iterate_action="new_answer",
                    )
                else:
                    decision = _build_checklist_scored_decision(
                        self.voting_threshold,
                        remaining,
                        total,
                        items,
                        terminate_action="stop",
                        iterate_action="new_answer",
                    )
                return f"""**CHOOSING THE RIGHT TOOL — `new_answer` vs `stop`:**
Both are terminal actions that end your round.

{analysis}

{decision}"""
            elif self.voting_sensitivity == "checklist_gated":
                items = self.custom_checklist_items if self.custom_checklist_items is not None else (_CHECKLIST_ITEMS_CHANGEDOC if self.has_changedoc else _CHECKLIST_ITEMS)
                analysis = (
                    _build_changedoc_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                    if self.has_changedoc
                    else _build_checklist_analysis(self.custom_checklist_items, self.item_verify_by)
                )
                decision = _build_checklist_gated_decision(
                    items,
                    terminate_action="stop",
                    iterate_action="new_answer",
                    require_gap_report=self.checklist_require_gap_report,
                    gap_report_mode=self.gap_report_mode,
                    builder_enabled=self.builder_enabled,
                )
                return f"""**CHOOSING THE RIGHT TOOL — `new_answer` vs `stop`:**
Both are terminal actions that end your round.

{analysis}

{decision}"""
            else:
                # roi (default) and roi_* variants
                roi_block = build_roi_decision_block(
                    self.voting_threshold,
                    answers_used=self.answers_used,
                    answer_cap=self.answer_cap,
                    iterate_action="new_answer",
                    satisfied_action="stop",
                    satisfied_detail="(your subtask is done)",
                )

                return f"""**CHOOSING THE RIGHT TOOL — `new_answer` vs `stop`:**
Both are terminal actions that end your round.

{roi_block}"""
        else:
            return """**CHOOSING THE RIGHT TOOL — `new_answer` vs `stop`:**
Both are terminal actions that end your round. Choose based on whether you produced new work:
- `new_answer`: You did work this round — wrote code, updated files, made improvements. Use this to **share your work** with other agents and the presenter.
- `stop`: You reviewed everything and are satisfied — no further changes needed from you. This signals completion without sharing new work."""

    def build_content(self) -> str:
        subtask_section = ""
        if self.subtask:
            subtask_section = f"""
**YOUR ASSIGNED SUBTASK:**
{self.subtask}

"""

        return f"""You are working as part of a decomposed team. Each agent owns a specific subtask of a larger project.
{subtask_section}
**CRITICAL: OWNERSHIP-FIRST EXECUTION.**
You own one primary subtask. Keep roughly 80% of your effort on that scope.
Use up to roughly 20% for adjacent integration work only when needed (interfaces, contracts, shared styles/tests, wiring).
Do NOT take over unrelated domains owned by other agents.
There may be overlap near your boundaries; you may refine/integrate that overlap, but do NOT expand into unrelated subtasks.

Team fairness policy is active to prevent runaway iteration loops. It does NOT mean reducing quality or stopping early.
Aim for similar effort bands across agents while maintaining a strong quality bar in your own area.

**HOW DECOMPOSITION MODE WORKS:**

1. **Self-refinement**: Continue improving your own work across iterations. Fix issues you spot, try better approaches, increase quality. Submit `new_answer` whenever you have meaningful improvements.

2. **Full awareness**: When you see other agents' work, READ and UNDERSTAND all of it. Maintain awareness of the entire project state, not just your subtask.

3. **Selective integration**: Integrate parts that touch your subtask — adapt interfaces, align contracts, resolve conflicts. \
For parts outside your area, maintain awareness but don't redo their work.

4. **Quality bar for `new_answer`**: When you submit `new_answer`, include concrete deliverables in your scope, validation evidence (tests/checks/manual verification), and boundary integration notes.

5. **Dual-purpose new_answer**: Submit `new_answer` when you have meaningful improvements — from self-refinement, integration insights, or both.

6. **Completion**: Call `stop` when you have reviewed the current state of work (yours and others') and are satisfied that your subtask is done. This ends your execution for this round.

{self._build_decision_block()}

**IMPORTANT:** If you improved or updated your deliverable work this round (fixed bugs, updated code, aligned interfaces), \
use `new_answer` to share those changes. It's fine to call `stop` if you only ran tests or created scratch files \
for verification without changing your actual output.

**TOOLS:**
- `new_answer`: Submit your work (content = summary of what you did + key deliverables)
- `stop`: Signal you are satisfied and done (summary = what you accomplished and how it connects; status = "complete" or "blocked")

**ANSWER FORMAT GUIDELINES:**
Your `new_answer` content should be HIGH-LEVEL and concise:
✓ DO:
- State what you created/accomplished in your subtask
- Specify where files are located (workspace paths)
- Explain how to run/use your component
- List key features or improvements
- Mention integration points with other agents' work
✗ DON'T:
- Include full code listings (code belongs in workspace files)
- Copy-paste entire file contents
- Include low-level implementation details
EXAMPLE:
```
I completed the authentication module and saved it to deliverable/auth/.
Workspace: /workspace/agent2/
Files created:
- deliverable/auth/login.py (JWT-based auth)
- deliverable/auth/middleware.py (request validation)
- tests/test_auth.py (unit tests)
How to use:
- Import AuthMiddleware in your app
- Add JWT_SECRET to environment
Integration points:
- Exports authenticate() function for agent1's API
- Uses database models from agent3
Tests: 12/12 passing
```
Remember: Other agents need to understand what you delivered and how to integrate with it, not HOW you implemented it.

Make sure you actually call `new_answer` or `stop` (in tool call format).

*Note*: The CURRENT TIME is **{time.strftime("%Y-%m-%d")}**."""


class PostEvaluationSection(SystemPromptSection):
    """
    Post-evaluation phase instructions.

    After final presentation, the winning agent evaluates its own answer
    and decides whether to submit or restart with improvements.

    MEDIUM priority as this is phase-specific operational guidance.
    """

    def __init__(self):
        super().__init__(
            title="Post-Presentation Evaluation",
            priority=Priority.MEDIUM,
            xml_tag="post_evaluation",
        )

    def build_content(self) -> str:
        return """## Post-Presentation Evaluation

You have just presented a final answer to the user. Now you must evaluate whether your answer fully addresses the original task.

**Your Task:**
Review the final answer that was presented and determine if it completely and accurately addresses the original task requirements.

**Available Tools:**
You have access to the same filesystem and tools that were available during presentation. Use these tools to:
- Verify that claimed files actually exist in the workspace
- Check file contents to confirm they match what was described
- Validate any technical claims or implementations

**Decision:**
You must call ONE of these tools:

1. **submit(confirmed=True)** - Use this when:
   - The answer fully addresses ALL parts of the original task
   - All claims in the answer are accurate and verified
   - The work is complete and ready for the user

2. **restart_orchestration(reason, instructions)** - Use this when:
   - The answer is incomplete (missing required elements)
   - The answer contains errors or inaccuracies
   - Important aspects of the task were not addressed

   Provide:
   - **reason**: Clear explanation of what's wrong (e.g., "The task required descriptions of two Beatles, but only John Lennon was described")
   - **instructions**: Detailed, actionable guidance for the next attempt (e.g.,
     "Provide two descriptions (John Lennon AND Paul McCartney). Each should include:
     birth year, role in band, notable songs, impact on music. Use 4-6 sentences per person.")

**Important Notes:**
- Be honest and thorough in your evaluation
- You are evaluating your own work with a fresh perspective
- If you find problems, restarting with clear instructions will lead to a better result
- The restart process gives you another opportunity to get it right
"""


class PlanningModeSection(SystemPromptSection):
    """
    Planning mode instructions (conditional).

    Only included when planning mode is enabled. Instructs agent to
    think through approach before executing.

    Args:
        planning_mode_instruction: The planning mode instruction text
    """

    def __init__(self, planning_mode_instruction: str):
        super().__init__(
            title="Planning Mode",
            priority=Priority.MEDIUM,
            xml_tag="planning_mode",
        )
        self.planning_mode_instruction = planning_mode_instruction

    def build_content(self) -> str:
        return self.planning_mode_instruction


_CHANGEDOC_FIRST_ROUND_PROMPT = """## Change Document (Decision Journal)

**Before you start writing your answer**, create `tasks/changedoc.md` in your main agent \
workspace directory (NOT in the project code directory or worktree). The changedoc is an internal \
decision journal — it must never be written to the project directory where it could end up in \
the repository. Start it first, then update it as you make each significant decision while \
working.

### Workflow

1. **Create `tasks/changedoc.md` immediately** in your workspace when you begin working. Write the Summary with your initial approach.
2. **Log each significant decision as you make it.** When you choose an approach, architecture, tool, or trade-off — write a DEC entry in the changedoc before or as you implement it.
3. **After implementing**, fill in the Implementation field on each decision with the actual files and symbols.
4. **Verify accuracy**: Before submitting, confirm that every Implementation field
   describes what actually exists in the files. Open the referenced locations and check.
   Do not document features you plan to add — only what is already built.
5. **Submit your answer** via `new_answer` once your work is complete. The changedoc should already be up to date.

The changedoc captures your reasoning in real-time, not as a summary after the fact. Focus on decisions where a reasonable person might have chosen differently.

### What to document

For each significant choice:
- What you decided and why
- What alternatives you considered and why you rejected them
- Which parts of the original task drove the decision
- **Where in the code** this decision is implemented (files, functions/classes, brief mechanism)

### Code references

Use relative paths within the workspace. Reference files and sections — the filename plus
the function/class name, section heading, or brief area description is enough for anyone
to locate the code.

Format: `relative/path/file.py` → `ClassName.method()` or `section name` — brief description

### Decision provenance

Every decision has an **Origin** field tracking who first introduced it. As the first agent,
all your decisions are new — mark them with `NEW`. This helps future agents (and humans) see
where each idea came from and which agents contributed genuinely new thinking vs refined
existing ideas.

### Template

```markdown
# Change Document

**Based on:** (original — no prior answers)

## Summary
[1-2 sentences describing your approach and key reasoning]

## Decisions

### DEC-001: [Decision title]
**Origin:** [SELF] — NEW
**Choice:** [What you chose]
**Why:** [Rationale tied to task requirements]
**Alternatives considered:**
- [Alternative A]: [Why rejected]
**Implementation:**
- `src/handler.py` → `RequestHandler.process()` — validates input then dispatches to worker pool
- `src/config.py` → `WORKER_COUNT` constant — set to 4 based on benchmark results

### DEC-002: [Next decision]
...

## Deliberation Trail
[Empty for first answer — subsequent agents will add entries here]
```

Write concisely — explain your thinking to a colleague who will pick up your work."""


def _build_changedoc_subsequent_round_prompt(gap_report_mode: str = "changedoc") -> str:
    """Build subsequent-round changedoc instructions.

    Args:
        gap_report_mode: Controls Open Gaps placement.
            "changedoc" appends Open Gaps section to the template.
            "separate" / "none" omit it.
    """
    quality_assessment = ""
    if gap_report_mode == "changedoc":
        quality_assessment = """

## Open Gaps
[Gaps you identified but chose not to address. One line each. These are for transparency,
not directives — the next agent should form their OWN assessment of what matters, not
treat this as a todo list.]
- [Gap]: [why not addressed — e.g., "incremental", "out of scope", "insufficient time"]"""

    return f"""## Change Document (Decision Journal)

**Before you start writing your answer**, create `tasks/changedoc.md` in your main agent \
workspace directory (NOT in the project code directory or worktree). The changedoc is an \
internal decision journal — it must never be written to the project directory where it could \
end up in the repository. Build it by evaluating ALL prior answers' changedocs
(shown in `<changedoc>` tags), then update it as you make each decision.

### Workflow

1. **Create `tasks/changedoc.md` immediately** when you begin working. Review ALL prior
changedocs to understand what decisions exist across answers, then draft YOUR changedoc
by selecting, modifying, or replacing decisions — do not just copy one changedoc wholesale.
2. **Run the checklist evaluation before you start building.** Evaluate the existing answers,
identify gaps and improvements, then `submit_checklist` with your scores. Do NOT make edits
to the deliverable before the checklist verdict — work done before a "vote" verdict is wasted
because changes are only locked in when you call `new_answer`.
3. **If the verdict says iterate**: implement your planned improvements. Log each decision in
the changedoc as you make it. Update the Implementation fields to reference YOUR code locations.
4. **Verify before submitting**: Confirm that every Implementation field describes what
   actually exists in the files — open the referenced locations and check. Also verify
   that features from prior rounds still work after your changes. Do not document
   features you plan to add — only what is already built.
5. **Submit your answer** via `new_answer` once your work is complete. The changedoc should already be up to date.

### Evaluating prior answers

Before building anything, analyze each existing answer independently:
- What does each answer do uniquely well?
- What is each answer's weakest aspect?
- Are there elements in lower-scoring answers that the "best" answer is missing?

Prior work is evidence of what has been tried, not a foundation you must build on.
Your job is to produce the best possible answer, which may mean:

- Synthesizing the best elements from multiple answers (name what from where)
- Taking a completely different approach because current ones are mediocre
- Keeping most of one answer but replacing its weakest component with something
  drawn from another answer or built fresh

**Warning: the copy-as-base trap.** You may see prior deliverables already in your
workspace. Do NOT default to patching them. Adding features to a mediocre base
produces a feature-rich mediocre result. Ask honestly: if you were starting fresh
with everything you now know, would you build it the same way? If the answer is no,
rebuilding the weak parts is higher-value work than adding new parts on top.

Default to "what would the best answer look like?" then decide whether existing
work gets you there. The DEC Origin fields track per-decision lineage.

For each decision the task requires:

1. For each decision, **compare all answers' versions**. Note what each answer does well — the strongest version may combine elements from multiple answers, \
not just pick one. Preserve the FULL Origin chain — do not truncate who first introduced a decision.
2. **Modify decisions** when you can improve them. Append to the Origin chain (e.g., `agent1.1 → agent1.2 (kept) → [SELF] (modified)`). Explain the change in the Deliberation Trail.
3. **Add genuinely new decisions** with Origin marked as `[SELF] — NEW`. These are ideas not present in any prior answer — novel approaches, new features, or original solutions you introduce.
4. **Challenge inherited decisions.** If every prior answer made the same choice, ask whether a different choice would produce a better result.
Convergence on the same approach is not proof it is the best approach.
5. **Update the Summary** to reflect your version of the answer.
6. **Update Implementation fields** to point to your code.
7. **Append to the Deliberation Trail** to record what changed and why, flagging NEW ideas explicitly.

Five deeply-reasoned decisions beat twelve adequate ones. You may REMOVE or MERGE decisions
from the inherited changedoc if they are redundant, weak, or dilute the overall quality.
Fewer, stronger decisions produce better outcomes than accumulating every idea.
This applies to changedoc decision count — it does not limit the scope of output changes
you should make. If your gap analysis identifies five output improvements, implement all five.

**Changedoc changes must accompany output changes.** Improving the changedoc alone — adding
decisions, strengthening rationale, deepening alternatives — does not constitute a round of
work. Every changedoc update should reflect a corresponding change in the actual deliverable.
If your only planned changes are to the changedoc itself, that is a signal to vote, not iterate.

If you start fresh rather than building on an existing answer, note in the Deliberation Trail why you chose a different approach.

### Rationale Preservation Rule

When inheriting a decision (marking Origin with `(kept)` or `(modified)`):

**REQUIRED:**
1. Preserve the ORIGINAL "Why:" field as written by the first agent who introduced it. The "Why:" must explain the domain reasoning — why this choice suits the task requirements.
2. Add a separate **"Synthesis Note:"** field below "Why:" for your meta-reasoning about why you kept or modified the decision.
3. Update "Implementation:" to reference YOUR code locations.

**FORBIDDEN:**
- Do NOT replace "Why:" with meta-justification like "this was the best prior answer" or "agent X had strong rationale"
- Do NOT collapse "Why:" into "use agent X as base"

**Why this matters:** When `"Why:"` becomes `"this was best"`, future agents lose the original reasoning and spend cycles restoring it instead of adding features.
Keep domain reasoning in `"Why:"` and process reasoning in `"Synthesis Note:"`.

### Code references

Use relative paths within the workspace. Reference files and sections — filename plus
the function/class name, section heading, or brief area description.

Format: `relative/path/file.py` → `ClassName.method()` or `section name` — brief description

### Answer labels

The answer labels in `<CURRENT ANSWERS>` headers (e.g., `<agent1.2>`, `<agent2.1>`) uniquely identify each
version of an agent's work. Use these exact labels when referencing OTHER agents' answers. Use `[SELF]`
when referencing your own work — the system will replace it with your real label (e.g., `agent1.2`)
when your answer is submitted.

### Template

```markdown
# Change Document

**Sources reviewed:** [list ALL prior answer labels you drew from, e.g., agent1.1, agent2.1]

## Summary
[1-2 sentences describing your approach]

## Decisions

### DEC-001: [Decision drawn from agent2.1]
**Origin:** agent2.1 (kept)
**Choice:** [What was chosen]
**Why:** [PRESERVE original domain rationale from agent2.1]
**Synthesis Note:** [Why agent2.1's version was stronger than agent1's for this decision]
**Alternatives considered:**
- agent1.1's approach: [Why agent2.1's was better]
**Implementation:**
- `path/to/file.py` → `ClassName.method()` — [brief mechanism description]

### DEC-002: [Decision combining ideas from multiple answers]
**Origin:** agent1.1 → [SELF] (modified)
**Choice:** [Your revised choice — combining strengths from both agents]
**Why:** [Domain rationale for this hybrid approach]
**Synthesis Note:** [agent1 did X, agent2 did Y — combined because...]
**Alternatives considered:**
- agent1.1's original: [trade-off]
- agent2.1's original: [trade-off]
**Implementation:**
- `path/to/file.py` → `new_function()` or `relevant section` — [mechanism]

### DEC-003: [Your new idea]
**Origin:** [SELF] — NEW
**Choice:** [What you introduced — not in any prior answer]
**Why:** [Rationale — this wasn't in any prior answer]
**Implementation:**
- `path/to/new_file.py` → `NovelClass` or `section name` — [mechanism]

## Deliberation Trail

### [SELF] (synthesized from agent1.1, agent2.1):
- DEC-001: Adopted from agent2.1 — [why this version was better]
- DEC-002: Combined agent1.1 + agent2.1 — [what each contributed]
- DEC-003: NEW — [what this adds that wasn't there before]

## Key Output Changes from Prior
- [User-visible change 1 — what is different in the deliverable]
- [User-visible change 2 — what is different in the deliverable]
```
{quality_assessment}

Write concisely — explain your thinking to a colleague who will pick up your work."""


_CHANGEDOC_PRESENTER_INSTRUCTIONS = """
### Change Document Consolidation

The agents' answers include changedoc decision journals (shown in `<changedoc>` tags).
Your final output MUST include a consolidated `tasks/changedoc.md` in your main agent \
workspace directory (NOT in the project code directory or worktree — the changedoc is an \
internal decision journal) that:

1. **Finalizes the Summary** to reflect the final delivered answer.
2. **Consolidates Decisions** into the definitive list. Remove superseded decisions. Keep the final version of each with full rationale.
3. **Preserves Origin fields** on every decision — these track which agent first introduced each idea. Keep `NEW` markers to highlight genuinely novel contributions.
4. **Updates all Implementation fields** to reference YOUR final code — file paths, symbol
names, and section descriptions pointing to the delivered files. The agents' code references
point to their frozen snapshots; yours must point to the final deliverable.
5. **Preserves the Deliberation Trail** showing how key decisions evolved. Clean up for readability but keep the substance, attribution, and `NEW` markers.
6. **Removes the Key Output Changes section** (not needed in the final document).

The final changedoc is a decision record, not a comparison report. Do not editorialize or
narrate which agent "won" — just state what was decided, why, and where in the code it lives.
A developer who was not present should be able to read the changedoc and:
- Trace every decision to specific files and functions in the codebase
- See where each idea originated (Origin field)
- Identify which ideas were genuinely new contributions (NEW markers)
- Follow how decisions evolved through the deliberation trail"""

_MEMORY_PRESENTER_INSTRUCTIONS = """
### Memory Consolidation

Your final output MUST include consolidated memory files in your main agent workspace directory:

1. Write concise reusable memories to `memory/short_term/*.md` (auto-loaded every turn).
2. Write detailed durable analyses to `memory/long_term/*.md` only when substantial.
3. Preserve YAML frontmatter (`name`, `description`, `created`, `updated`) in each memory file.
4. De-duplicate overlaps across agents and keep only the clearest final version of each memory.
5. Use `tasks/changedoc.md` as your primary source for what to retain:
   - decision rationale
   - what worked/failed
   - pitfalls to avoid next time
   - user preferences discovered
6. Use the same changedoc-backed learnings to align both memory files and any consolidated
   evolving skill (`tasks/evolving_skill/SKILL.md`) so they do not conflict.

Do not copy the changedoc verbatim. Synthesize short, reusable memory entries for future turns."""

_SPEC_PRESENTER_INSTRUCTIONS = """\

### Spec Compliance Report

Before presenting the final answer, produce a spec compliance summary. \
For each requirement in the spec:

1. List the requirement by ID and title
2. Mark status: **SATISFIED** / **PARTIAL** / **NOT ADDRESSED**
3. For PARTIAL requirements, explain what remains
4. Note any requirements blocked by dependencies or deferred to a later chunk
5. Report overall coverage (e.g., "8/10 requirements satisfied, 1 partial, 1 deferred")

Format as a markdown table in your changedoc under `## Spec Compliance`:

| REQ-ID | Title | Status | Notes |
|--------|-------|--------|-------|
| REQ-001 | ... | SATISFIED | Implemented in src/auth.py |
| REQ-002 | ... | PARTIAL | Missing edge case handling |

This compliance report is the primary quality signal for spec-driven execution. \
Be honest — marking an unsatisfied requirement as SATISFIED defeats the purpose."""


class NoveltyPressureSection(SystemPromptSection):
    """Injects novelty pressure when convergence is detected.

    Escalates from gentle suggestion to mandatory divergence depending on
    the configured novelty_level and how many consecutive incremental rounds
    have occurred.
    """

    def __init__(
        self,
        novelty_level: str,
        consecutive_incremental_rounds: int,
        restart_count: int,
    ):
        super().__init__(
            title="Novelty Pressure",
            priority=Priority.MEDIUM,
            xml_tag="novelty_pressure",
        )
        self.novelty_level = novelty_level
        self.consecutive_incremental_rounds = consecutive_incremental_rounds
        self.restart_count = restart_count

    def build_content(self) -> str:
        n = self.consecutive_incremental_rounds
        if n == 0:
            return (
                "Before committing to a refinement strategy, consider whether the "
                "existing approach is the RIGHT approach, not just the CURRENT approach. "
                "If a fundamentally different direction would serve the user better, "
                "now is the cheapest time to change course."
            )
        if self.novelty_level == "gentle":
            return (
                "Previous rounds identified only incremental improvements. Consider whether a "
                "fundamentally different approach — a different architecture, creative direction, "
                "or interaction model — would yield a stronger result than continued polish."
            )
        elif self.novelty_level == "moderate":
            return (
                f"CONVERGENCE DETECTED: {n} consecutive rounds found no transformative or structural "
                "work remaining. The current line of refinement is stalling. You MUST explore a "
                "fundamentally different direction for at least one major aspect of the answer. "
                "Continued incremental polish will not pass the novelty requirement."
            )
        elif self.novelty_level == "aggressive":
            return (
                "MANDATORY DIVERGENCE: You are REQUIRED to take a fundamentally different approach "
                "to at least one core aspect of the problem. Do not refine the existing direction — "
                "challenge it. Try a different architecture, a different creative vision, or a "
                "different problem decomposition. The existing approach has been explored; now "
                "explore alternatives."
            )
        return ""


class ChangedocSection(SystemPromptSection):
    """
    Changedoc instructions for coordination.

    Instructs agents to produce a decision journal (tasks/changedoc.md) alongside
    their answer, explaining WHY choices were made. When prior answers exist,
    agents inherit and extend the changedoc from the answer they build upon.

    Args:
        has_prior_answers: Whether other agents' answers are visible.
    """

    def __init__(self, has_prior_answers: bool = False, gap_report_mode: str = "changedoc"):
        super().__init__(
            title="Change Document",
            priority=Priority.MEDIUM,
            xml_tag="changedoc_instructions",
        )
        self.has_prior_answers = has_prior_answers
        self.gap_report_mode = gap_report_mode

    def build_content(self) -> str:
        if self.has_prior_answers:
            return _build_changedoc_subsequent_round_prompt(gap_report_mode=self.gap_report_mode)
        return _CHANGEDOC_FIRST_ROUND_PROMPT


class SubagentSection(SystemPromptSection):
    """
    Subagent delegation guidance for spawning independent agent instances.

    Provides instructions on when and how to use subagents for task delegation,
    parallel execution, and context isolation.

    Args:
        workspace_path: Path to the agent's workspace (for subagent workspace location)
        max_concurrent: Maximum concurrent subagents allowed
        specialized_subagents: List of discovered specialized subagent types
        default_timeout: Configured timeout for subagents in seconds (default 300)
    """

    def __init__(
        self,
        workspace_path: str,
        max_concurrent: int = 3,
        specialized_subagents=None,
        default_timeout: int = 300,
    ):
        super().__init__(
            title="Subagent Delegation",
            priority=Priority.MEDIUM,
            xml_tag="subagent_delegation",
        )
        self.workspace_path = workspace_path
        self.max_concurrent = max_concurrent
        self.specialized_subagents = specialized_subagents or []
        self.default_timeout = default_timeout

    def _build_attached_subagents_section(self) -> str:
        """Build the ATTACHED SUBAGENTS section listing discovered types."""
        if not self.specialized_subagents:
            return ""

        # All subagent types default to background=True — they do substantial work
        # that should not block the main agent's context. Override only when a type
        # genuinely must be blocking (e.g., a quick synchronous check).
        background_by_type: dict[str, bool] = {}

        lines = [
            "",
            "## ATTACHED SUBAGENTS — USE THESE INSTEAD OF DOING THE WORK YOURSELF",
            "",
            "Prefer spawning these specialized subagents over doing the equivalent work inline — they save your token budget and come pre-equipped with the right tools.",
            "",
        ]

        for t in self.specialized_subagents:
            background_default = background_by_type.get(t.name.lower(), True)
            background_str = "True" if background_default else "False"
            lines.append(f"**{t.name}** — {t.description}")
            lines.append(
                f'`spawn_subagents(tasks=[{{"task": "...", "subagent_type": "{t.name}"}}], background={background_str}, refine=False)`',
            )
            if getattr(t, "expected_input", None):
                lines.append("Expected input for this type:")
                for item in t.expected_input:
                    lines.append(f"- {item}")
            if t.name.lower() == "evaluator":
                lines.append(
                    "Use this when the task is mostly programmatic execution/reporting "
                    "(batch tests, Playwright flows, evidence capture sweeps, scripted validation). "
                    "Your workspace is mounted read-only by default. Use `include_parent_workspace: false` "
                    "only for tasks with no workspace file dependencies.",
                )
            if t.name.lower() == "builder":
                lines.append(
                    "**FOR `BUILDER` TASKS — one task per deliverable, run independent ones in parallel:**\n\n"
                    "**The key rule: one builder task per independent deliverable.** Do NOT write one "
                    "large spec that covers multiple improvements. Split them into separate tasks and "
                    "spawn them in a single `spawn_subagents` call — they run simultaneously.\n\n"
                    "Bad (monolithic — DO NOT DO THIS):\n"
                    '`tasks=[{"task": "Rewrite member portraits, redesign album section, fix timeline, '
                    'update CSS, rewrite narrative, fix scroll-reveal", "subagent_type": "builder", ...}]`\n\n'
                    "Good (parallel — each improvement is its own task):\n"
                    "`tasks=[\n"
                    '  {"task": "Rewrite member portraits section...", "subagent_type": "builder"},\n'
                    '  {"task": "Redesign album section with artwork...", "subagent_type": "builder"},\n'
                    '  {"task": "Fix alternating timeline layout...", "subagent_type": "builder"},\n'
                    '  {"task": "Rewrite narrative prose in About + Hero...", "subagent_type": "builder"},\n'
                    "]`\n\n"
                    "**You decide what to build — builder executes it.** Make all creative and "
                    "architectural decisions yourself before writing the spec. Builder does not "
                    "decide what to change or which direction to take.\n\n"
                    "**Parent workspace is auto-mounted read-only by default.** "
                    "Use `context_paths` only for additional paths outside your workspace "
                    "(e.g. peer workspace paths from Available agent workspaces).\n\n"
                    "**The novelty → build loop** (when criteria plateau):\n"
                    "1. Novelty returns directions for plateaued criteria. Evaluate each: "
                    "does it break the anchoring pattern? Is it implementable? Differs from "
                    "what's been tried?\n"
                    "2. If at least one passes, adopt it and include it in your "
                    "`propose_improvements` call.\n"
                    "3. Write a focused spec for ONE deliverable and spawn a builder task.\n"
                    "4. Integrate and verify the result.\n\n"
                    "**Ignoring novelty output wastes a full round** — "
                    "engage seriously with each direction, even to reject it.",
                )
            lines.append("")

        return "\n".join(lines)

    def build_content(self) -> str:
        attached = self._build_attached_subagents_section()
        specialized_names = {t.name.lower() for t in self.specialized_subagents}
        specialized_guidance = ""
        if specialized_names:
            evaluator_guidance = ""
            if "evaluator" in specialized_names:
                evaluator_guidance = """
**FOR `EVALUATOR` TASKS, EXPLICITLY INCLUDE:**
- What to run (tests, scripts, flows, URLs, targets)
- How to set it up (install/build/start steps, ports, env vars, prerequisites)
- Exact commands (copy-pastable command list in order)
- What evidence to capture (screenshots, video recordings, audio samples, logs, timings, failing cases, artifact paths)
- Pass/fail format (explicit rubric or required report sections)
"""
            specialized_guidance = f"""
**WHEN WRITING A `TASK` FOR SPECIALIZED SUBAGENTS:**
Give a high-quality brief so the subagent can execute correctly. Include:
- **Objective**: exact outcome and scope boundary
- **Setup**: dependencies, environment details, paths, credentials assumptions, and how to set it up
- **Commands to run**: exact commands or scripts in execution order
- **Expected output format**: section names, fields, and how results should be structured
- **Constraints**: runtime limits, deterministic requirements, and what not to change

**EXPECTED INPUT FOR EACH SPECIALIZED TYPE:**
Read the "Expected input for this type" bullets in ATTACHED SUBAGENTS and adapt your task accordingly.
If that checklist is present, treat it as required inputs for your task brief.

{evaluator_guidance}
"""
        return f"""{attached}
# Subagent Delegation

You can spawn **subagents** to execute tasks with fresh context and isolated workspaces.

## When to Use Subagents

**USING TASK DEPENDENCIES TO IDENTIFY SUBAGENT CANDIDATES:**
When you create a task plan, tasks with the SAME dependencies (or no dependencies) can potentially run in parallel via subagents. Look at your plan:
- Tasks that share dependencies → candidates for parallel subagent execution
- Tasks that depend on each other → must be sequential (do NOT subagent)
- Simple/quick tasks → do yourself (subagent overhead not worth it)

Example task plan analysis:
```
Task A: Research biography (no deps)        ← Can parallelize
Task B: Research discography (no deps)      ← Can parallelize
Task C: Research quotes (no deps)           ← Can parallelize
Task D: Build website (deps: A, B, C)       ← Sequential, do yourself after A/B/C
```
→ Spawn subagents for A, B, C simultaneously. Wait for results. Then do D yourself.

**IDEAL USE CASES:**
- **Research and exploration** - gathering information, searching, analyzing sources
- **Parallel data collection** - multiple independent lookups that can run simultaneously
- **Programmatic evaluation at scale** - batch test runs, Playwright verification, evidence capture sweeps, repetitive scripted checks
- Complex subtasks that benefit from fresh context (avoid context pollution)
- Experimental operations you want isolated from your main workspace

**SUBAGENT RELIABILITY:**
Subagents are useful helpers but have limitations:
- They run with simpler configs and may be less capable than you
- Their outputs are **raw materials** - expect to review, refine, and fix their work
- Don't blindly trust subagent results - verify and integrate thoughtfully
- If a subagent produces something broken or incomplete, **you fix it** rather than reporting failure

{specialized_guidance}

**EVALUATION DELEGATION (background pattern):**
When your output needs testing or evaluation that involves procedural tool use, delegate it
to a background subagent so you can keep working on implementation. Spawn with
`background=True, refine=False` — the subagent evaluates while you continue building.

Subagent handles (procedural observations):
- High-volume batch workflows where execution is mostly mechanical and repeatable
- Serving a website and capturing evidence (screenshots, video recordings, etc.), running Playwright tests, using read_media
- Executing test suites, linters, or validation scripts against generated code
- Running benchmarks, profiling, or performance measurements
- Checking file integrity, link resolution, or cross-references in documents
- Comparing output against specs or acceptance criteria with automated tools

You handle (analytical judgment):
- Analyzing previous answers and peer approaches in depth
- Making quality judgments and deciding what to improve next
- Synthesizing insights from multiple sources into a coherent strategy
- Prioritizing which gaps matter most and what to build next

The subagent returns a descriptive report of findings and observations — what it measured,
what passed, what failed, what it saw. It may include suggestions, but treat those as optional
input. Trust its observations and measurements. Keep your judgment as the source of truth for
quality and priorities, since you have the full context and the subagent may run on a simpler model.

**AVOID SUBAGENTS FOR:**
- Simple, quick operations you can do directly (overhead not worth it)
- Tasks requiring back-and-forth coordination (high overhead)
- Operations that need to modify your main workspace directly
- Sequential tasks that depend on other task outputs
- High-stakes deliverables that need careful quality control (do these yourself)

## How Subagents Work

1. **Isolated Workspace**: Each subagent gets its own workspace
   - You can READ files from subagent workspaces
   - You CANNOT write directly to subagent workspaces
2. **Fresh Context**: Subagents start with a clean slate (just the task you provide)
3. **Workspace Access**: Your workspace is auto-mounted read-only by default
   - `include_parent_workspace` (default `true`): subagent can read your files
   - Set `include_parent_workspace: false` for fully isolated research subagents
   - `context_paths` (optional): additional read-only paths — use for peer workspace
     paths listed under Available agent workspaces
   - `context_files` remains optional for copying files into subagent workspace
4. **No Nesting**: Subagents cannot spawn their own subagents
5. **No Human Broadcast**: Subagents cannot ask the human or request human input,
   but they CAN receive runtime messages from you via `send_message_to_subagent`

## Waiting for Subagents (CRITICAL)

**DO NOT submit your answer until ALL subagents have returned results.**

When you spawn subagents:
1. **Use `background=True` (default)** — the tool returns immediately with subagent IDs.
   Continue your own work while subagents run. Results are auto-injected or retrievable via `list_subagents()`.
2. **Do NOT say "I will now run subagents"** and submit an answer before collecting results.
3. **Only after receiving results** should you integrate outputs and submit your answer.

**BAD**: "I spawned 5 subagents. I will now wait for them and report back." (submitting answer before results)
**GOOD**: Wait for spawn tool to return → read results → integrate → then submit answer with completed work

## Integrating Subagent Results (MANDATORY)

**YOU MUST INTEGRATE SUBAGENT OUTPUTS.** Subagents are helpers - YOU are responsible for the final deliverable.

After subagents complete (or timeout):
1. **Read each subagent's answer** to get the file paths they created
2. **Read those files** from the paths listed in the answer
3. **Write integrated files to YOUR workspace** - combine, merge, and organize the content
4. **If a subagent timed out**: Check its workspace anyway - it may have created partial work you can use. Complete any remaining work yourself.
5. **Your final answer**: Describe the COMPLETED work in your workspace, not what subagents did

**Handling timeouts/failures - YOU MUST CHECK WORKSPACES AND LOGS:**
When a subagent times out or fails, the result includes both `workspace` and `log_path`. You MUST:
1. **Check the workspace** (e.g., `/path/to/subagents/bio/workspace`) for partial work
2. **Check the log_path** (if provided) for debugging info - contains `full_logs/` with conversation history
3. **List files in both directories** to see what was created before failure
4. **Read and use any partial work** - even a half-finished file is better than nothing
5. **Complete the remaining work yourself** - don't just report the timeout

**DO NOT:**
- ❌ Submit answer before subagents finish
- ❌ Say "I will run subagents and report back" as your answer
- ❌ List what subagents produced and ask "what do you want next?"
- ❌ Leave files scattered in subagent workspaces
- ❌ Report subagent failures without completing the work yourself
- ❌ Provide "next steps" menus (A/B/C options) instead of finished work

**DO:**
- ✅ Wait for all subagent results before submitting answer
- ✅ Read subagent output files and write them to YOUR workspace
- ✅ If building a website: create the actual HTML/CSS/content files in your workspace
- ✅ If subagent timed out: check for partial work, use it, complete the rest
- ✅ Final answer: "I created X, Y, Z in my workspace" with the actual files present

## Retrieving Files from Subagents

When a subagent creates files you need:
1. **Check the answer**: The subagent lists relevant file paths in its answer
2. **Read the files**: Read from the paths in the answer
3. **Copy to your workspace**: Save files you need to your workspace

**IMPORTANT**: Only copy files you actually need. Context isolation is a key feature - you don't need every file the subagent created, just the relevant outputs.

## The spawn_subagents Tool

**CRITICAL: Tasks run in PARALLEL (simultaneously), NOT sequentially!**

All subagents start at the same time and cannot see each other's output. Design tasks that are INDEPENDENT:
- ✅ GOOD: "Research biography" + "Research discography" + "Research songs" (independent research)
- ❌ BAD: "Research content" + "Build site using researched content" (task 2 can't access task 1's output!)

**REQUIREMENTS:**
1. **Maximum {self.max_concurrent} tasks per call** - requests for more will error
2. **`CONTEXT.md` in workspace is REQUIRED** - subagents need to know the project/goal
3. **Each task dict must have `"task"` field** (other fields are optional)
4. **Workspace access**:
   - Your workspace is auto-mounted read-only (include_parent_workspace=true by default)
   - Set `include_parent_workspace: false` for fully isolated research
   - Use `context_paths` only for additional paths (e.g. peer workspaces)

```python
# CORRECT: Independent parallel tasks (each can complete without the others)
# Parent workspace is auto-mounted read-only — no context_paths needed
spawn_subagents(
    tasks=[
        {{"task": "Research and write Bob Dylan biography to bio.md", "subagent_id": "bio"}},
        {{"task": "Create discography table in discography.md", "subagent_id": "discog"}},
        {{"task": "List 20 famous songs with years in songs.md", "subagent_id": "songs"}}
    ],
    background=True,  # default: run async, continue working; set False only when you must block
    refine=False,  # default: single-pass, fast/cheap; set True only when quality justifies cost
)

# WRONG - DO NOT DO THIS (task 2 depends on task 1's output):
# spawn_subagents(tasks=[
#     {{"task": "Research all content"}},
#     {{"task": "Build website using the researched content"}}  # CAN'T ACCESS TASK 1!
# ])
```

**background parameter (async mode):**
- `background=True` **(default)**: Spawn in background and continue working asynchronously.
  Results are often auto-injected on a later tool call. Use `list_subagents()` to check
  status and discover workspace paths.
- `background=False`: Wait for results before proceeding. Only use when you genuinely
  cannot continue any meaningful work until the subagent completes.

**refine parameter:**
- `refine=False` **(default)**: Single-pass execution. Faster and cheaper. Use for most tasks.
- `refine=True`: Multi-round refinement with voting. Higher quality but significantly slower
  and more expensive. Only use when quality is critical and cost is acceptable.

## Background Subagent Lifecycle

When using `background=True`, subagents run asynchronously. Here is the full lifecycle:

1. **Launch**: `spawn_subagents(tasks, background=True)` — starts running, returns immediately with subagent IDs
2. **Monitor**: `list_subagents()` — check status (`running` / `completed` / `timeout` / `failed`), get workspace path
3. **Steer** (while running): `send_message_to_subagent(subagent_id, message)` — inject guidance mid-execution (e.g., "focus on X", "skip Y"). Delivered at next checkpoint.
4. **Resume** (after completion): `continue_subagent(subagent_id, message)` — start a new turn with full conversation history preserved

**Patience and steering:**
Background subagents run a full MassGen process internally. They have up to \
{self.default_timeout} seconds ({self.default_timeout // 60} minutes) to complete \
before timing out automatically. `list_subagents()` reports `elapsed_seconds`, \
`timeout_seconds`, and `seconds_remaining` for each running subagent — use these \
to calibrate your patience before considering a cancel.
Check in on them intermittently via `list_subagents()` while you work on other tasks —
they will complete on their own. If one appears to be going in the wrong direction,
**prefer `send_message_to_subagent`** to redirect it rather than cancelling. Cancel
only as a last resort when the subagent is clearly going nowhere and redirecting won't
help. Finding partial files in the workspace is normal while a subagent runs — that
alone is not a reason to cancel.

**Monitoring a running subagent's progress:**
Use `list_subagents()` to get the workspace path, then:
- **Live output**: Read `{{workspace}}/.massgen/massgen_logs/log_*/turn_*/attempt_*/agent_outputs/*.txt` to see streaming text, tool calls, and thinking from each agent in the subagent process.
- **Work products**: Read files directly in `{{workspace}}/` to see what the subagent has created so far.

## Available Tools

- `spawn_subagents(tasks, background?, refine?)` -- Max {self.max_concurrent} parallel tasks.
  Each task must include `task`. Parent workspace auto-mounted read-only.
- `list_subagents()` - Discovery/index of spawned subagents (status, workspace, session_id); \
  for running subagents also includes `elapsed_seconds`, `timeout_seconds`, and `seconds_remaining`
- `continue_subagent(subagent_id, message, timeout_seconds?)` - Continue an existing subagent conversation
- `send_message_to_subagent(subagent_id, message)` - Send a message to a RUNNING background subagent.
  Use to steer direction mid-execution without waiting for completion.
  Only works for background subagents that are currently running (not completed/failed).
- `cancel_subagent(subagent_id)` - Cancel a running subagent. **Last resort only.**
  Prefer `send_message_to_subagent` to redirect. Only cancel if the subagent is clearly
  going nowhere and cannot be salvaged.

## Result Format

```json
{{
    "success": true,
    "operation": "spawn_subagents",
    "results": [
        {{
            "subagent_id": "research_oauth",
            "status": "completed",  // or "completed_but_timeout", "partial", "timeout", "error"
            "workspace": "{self.workspace_path}/subagents/research_oauth/workspace",
            "answer": "The subagent's answer with file paths...",
            "execution_time_seconds": 45.2,
            "completion_percentage": 100,  // Progress when timeout occurred (0-100)
            "token_usage": {{"input_tokens": 1000, "output_tokens": 500}}
        }}
    ],
    "summary": {{"total": 1, "completed": 1, "failed": 0, "timeout": 0}}
}}
```

**Status values:**
- `completed`: Normal successful completion
- `completed_but_timeout`: Timed out but answer was recovered (use it!)
- `partial`: Some work done, check workspace for partial files
- `timeout`: No recoverable work, but workspace still accessible
- `error`: Failed with error

## Workspace Structure

```
{self.workspace_path}/
├── ... (your files)
└── subagents/
    ├── _registry.json    # Subagent tracking
    ├── sub_abc123/
    │   ├── workspace/    # Subagent's files (READ-ONLY to you)
    │   └── _metadata.json
    └── sub_def456/
        ├── workspace/
        └── _metadata.json
```
"""


class BroadcastCommunicationSection(SystemPromptSection):
    """
    Agent-to-agent communication capabilities via broadcast tools.

    Provides instructions for using ask_others() tool for collaborative
    problem-solving between agents, with configurable sensitivity levels.

    This section appears at HIGH priority to provide coordination guidance
    after critical context but before auxiliary best practices.

    Args:
        broadcast_mode: Communication mode - "agents" (agent-to-agent only)
                       or "human" (agents can ask agents + human)
        wait_by_default: Whether ask_others() blocks by default (True)
                        or returns immediately for polling (False)
        sensitivity: How frequently to use ask_others():
                    - "low": Only for critical decisions/when blocked
                    - "medium": For significant decisions and design choices (default)
                    - "high": Frequently - whenever considering options

    Example:
        >>> section = BroadcastCommunicationSection(
        ...     broadcast_mode="agents",
        ...     wait_by_default=True,
        ...     sensitivity="medium"
        ... )
        >>> print(section.render())
    """

    def __init__(
        self,
        broadcast_mode: str,
        wait_by_default: bool = True,
        sensitivity: str = "medium",
        human_qa_history: list[dict[str, Any]] = None,
    ):
        super().__init__(
            title="Broadcast Communication",
            priority=Priority.HIGH,  # Elevated from MEDIUM for stronger emphasis
            xml_tag="broadcast_communication",
        )
        self.broadcast_mode = broadcast_mode
        self.wait_by_default = wait_by_default
        self.sensitivity = sensitivity
        self.human_qa_history = human_qa_history or []

    def build_content(self) -> str:
        """Build broadcast communication instructions."""
        lines = [
            "## Agent Communication",
            "",
            "**CRITICAL TOOL: ask_others()**",
            "",
        ]

        if self.broadcast_mode == "human":
            lines.append("You MUST use the `ask_others()` tool to ask questions to the human user.")
        else:
            lines.append("You MUST use the `ask_others()` tool to collaborate with other agents.")

        lines.append("")

        # Add sensitivity-specific guidance
        if self.sensitivity == "high":
            lines.append("**Collaboration frequency: HIGH - You MUST use ask_others() frequently whenever you're considering options, proposing approaches, or making decisions.**")
        elif self.sensitivity == "low":
            lines.append("**Collaboration frequency: LOW - You MUST use ask_others() when blocked or for critical architectural decisions.**")
        else:  # medium
            lines.append("**Collaboration frequency: MEDIUM - You MUST use ask_others() for significant decisions, design choices, or when confirmation would be valuable.**")

        lines.extend(
            [
                "",
                "**When you MUST use ask_others():**",
                '- **User explicitly requests collaboration**: If prompt says "ask_others for..." then CALL THE TOOL immediately',
                "- **Before key decisions**: Architecture, framework, approach choices",
                "- **When you need specific information**: Include context about YOUR project so others can help",
                "- **Before significant implementation**: Describe your current setup and ask for input",
                "",
                "**When NOT to use ask_others():**",
                "- For rhetorical questions or obvious answers",
                "- Repeatedly on the same topic (one broadcast per decision)",
                "- For trivial implementation details",
                "",
                "**Timing:**",
                '- **User says "ask_others"**: Call tool immediately',
                "- **Before deciding**: Ask first, then provide answer with responses",
                "- **For feedback**: Provide answer first, then ask for feedback",
                "",
                "**IMPORTANT: Include responses in your answer:**",
                "When you receive responses from ask_others(), INCLUDE them in your new_answer():",
                '- Example: "I asked about framework. Response: Use Vue. Based on this, I will..."',
                "- Check your answer before asking again - reuse documented responses",
                "",
                "**How it works:**",
            ],
        )

        if self.wait_by_default:
            if self.broadcast_mode == "human":
                lines.extend(
                    [
                        "- Call `ask_others(questions=[...])` with structured questions (PREFERRED)",
                        "- The tool blocks and waits for the human's response",
                        "- Returns the human's selections/responses when ready",
                        "- You can then continue with your task",
                    ],
                )
            else:
                lines.extend(
                    [
                        "- Call `ask_others(questions=[...])` with structured questions (PREFERRED)",
                        "- The tool blocks and waits for responses from other agents",
                        "- Returns all responses immediately when ready",
                        "- You can then continue with your task",
                    ],
                )
        else:
            lines.extend(
                [
                    "- Call `ask_others(questions=[...], wait=False)` to send without waiting",
                    "- Continue working on other tasks",
                    "- Later, check status with `check_broadcast_status(request_id)`",
                    "- Get responses with `get_broadcast_responses(request_id)` when ready",
                ],
            )

        lines.extend(
            [
                "",
                "**Best practices:**",
                "- Be specific and actionable in your questions",
                "- Use when you genuinely need coordination or input",
                "- Actually CALL THE TOOL (don't just mention it in your answer text)",
                "- Respond helpfully when others ask you questions",
                "- **Limit to 5-7 questions max per call** - too many questions overwhelms the responder",
                "- For each question, **provide 2-5 predefined options** when possible",
                "",
                "**PREFERRED: Use structured questions with the `questions` parameter:**",
                "Structured questions provide a better UX with clear options. Use them for most questions.",
                "",
                "Example - single structured question:",
                "```json",
                "ask_others(questions=[{",
                '  "text": "Which rendering approach should I use for product pages?",',
                '  "options": [',
                '    {"id": "ssr", "label": "SSR", "description": "Server-side rendering"},',
                '    {"id": "ssg", "label": "SSG", "description": "Static site generation"},',
                '    {"id": "isr", "label": "ISR", "description": "Incremental static regeneration"}',
                "  ],",
                '  "multiSelect": false,',
                '  "allowOther": true',
                "}])",
                "```",
                "",
                "Example - multiple questions in one call:",
                "```json",
                "ask_others(questions=[",
                "  {",
                '    "text": "Which frontend framework?",',
                '    "options": [',
                '      {"id": "react", "label": "React"},',
                '      {"id": "vue", "label": "Vue"},',
                '      {"id": "svelte", "label": "Svelte"}',
                "    ]",
                "  },",
                "  {",
                '    "text": "Which databases do you use?",',
                '    "options": [',
                '      {"id": "postgres", "label": "PostgreSQL"},',
                '      {"id": "mysql", "label": "MySQL"},',
                '      {"id": "mongodb", "label": "MongoDB"}',
                "    ],",
                '    "multiSelect": true',
                "  }",
                "])",
                "```",
                "",
                "**FALLBACK: Use simple text for truly open-ended questions:**",
                'Only use `ask_others(question="...")` when predefined options don\'t make sense:',
                '- "What specific challenges have you encountered with this codebase?"',
                '- "Describe your ideal workflow for this feature."',
            ],
        )

        if self.broadcast_mode == "human":
            lines.extend(
                [
                    "",
                    "**Note:** In human mode, only the human responds to your questions (other agents are not notified).",
                ],
            )

        # Inject human Q&A history if available (human mode only)
        if self.human_qa_history and self.broadcast_mode == "human":
            lines.extend(
                [
                    "",
                    "**Human has already answered these questions this turn:**",
                ],
            )
            for i, qa in enumerate(self.human_qa_history, 1):
                lines.append(f"- Q{i}: {qa['question']}")
                lines.append(f"  A{i}: {qa['answer']}")
            lines.extend(
                [
                    "",
                    "Check if your question is already answered above before calling ask_others().",
                ],
            )

        return "\n".join(lines)


class EvolvingSkillsSection(SystemPromptSection):
    """
    Guidance on evolving skills - detailed workflow plans.

    Includes the full evolving-skill-creator content directly in the system prompt
    so agents don't need to read it separately.

    When plan_context is provided (from tasks/plan.json), adds guidance to
    reference the plan and capture task-specific learnings.
    """

    def __init__(self, plan_context: dict | None = None):
        super().__init__(
            title="Evolving Skills",
            priority=6,  # After core_behaviors(4), task_planning(5)
            xml_tag="evolving_skills",
        )
        self.plan_context = plan_context

    def build_content(self) -> str:
        base_content = """## Evolving Skills

**REQUIRED**: Before starting work on any task, you MUST create an evolving skill - a detailed workflow plan.

### What is an Evolving Skill?

An evolving skill is a workflow plan that:
1. Documents specific steps to accomplish a goal
2. Lists Python scripts you'll create as reusable tools
3. Captures learnings after execution for future improvement

Unlike static skills, evolving skills are refined through use.

### Directory Structure

```
tasks/evolving_skill/
├── SKILL.md              # Your workflow plan
└── scripts/              # Python tools you create during execution
    ├── scrape_data.py
    └── generate_output.py
```

### SKILL.md Format

```yaml
---
name: task-name-here
description: What this workflow does and when to use it
---
# Task Name

## Overview
Brief description of the problem this skill solves.

## Workflow
Detailed numbered steps:
1. First step - be specific
2. Second step - include commands/tools to use
3. ...

## Tools to Create
Python scripts you'll write. Document BEFORE writing them:

### scripts/example_tool.py
- **Purpose**: What it does
- **Inputs**: What it takes (args, files, etc.)
- **Outputs**: What it produces
- **Dependencies**: Required packages

## Tools to Use
(Discover what's available, list ones you'll use)
- servers/name: MCP server tools
- custom_tools/name: Python tool implementations

## Skills
- skill_name: how it will help

## Packages
- package_name (pip install package_name)

## Expected Outputs
- Files this workflow produces
- Formats and locations

## Verification & Improvement
How to verify and iterate on output (output-first approach):
- For code: Run it, fix issues, rerun until working correctly
- For websites/UIs: Interact and capture evidence (screenshots for layout, recordings for behavior), adjust, re-verify until polished
- For files: Open and inspect, refine content, re-check until quality meets bar
- For data: Validate format/values, fix accuracy issues, re-validate until correct

## Learnings
(Add after execution)

### What Worked Well
- ...

### What Didn't Work
- ...

### Tips for Future Use
- ...
```

### Tools to Create Section

This is key. When your workflow involves writing Python scripts, document them upfront:

```markdown
## Tools to Create

### scripts/fetch_artist_data.py
- **Purpose**: Crawl Wikipedia and extract artist biographical data
- **Inputs**: artist_name (str), output_path (str)
- **Outputs**: JSON file with structured bio data
- **Dependencies**: crawl4ai, json

### scripts/build_site.py
- **Purpose**: Generate static HTML from artist data
- **Inputs**: data_path (str), theme (str), output_dir (str)
- **Outputs**: Complete website in output_dir/
- **Dependencies**: jinja2
```

After execution, the actual scripts live in `scripts/` and can be reused.

### Required Steps

1. **BEFORE starting work**: Create `tasks/evolving_skill/SKILL.md` in your main agent workspace directory \
(NOT in the project code directory or worktree). Evolving skills are internal artifacts and must not be written to the project repository.
2. **Use `tasks/changedoc.md` as the canonical decision log for your evolving skill.**
3. **During execution**: Follow your plan, create scripts as documented
4. **BEFORE answering**: Verify outputs work (run code, view visuals, check files)
5. **AFTER completing work**: Update SKILL.md with Learnings section

### Key Principles

1. **Be specific** - Workflow steps should be actionable, not vague
2. **Document tools upfront** - Plan scripts before writing them
3. **Test like a user** - Verify artifacts through interaction, not just observation \
(click buttons, play games, navigate pages, run with edge cases, etc)
4. **Update with learnings** - The skill improves through use
5. **Keep scripts reusable** - Design tools to work in similar future tasks"""

        # Append plan-specific guidance if plan context is available
        if self.plan_context:
            task_count = len(self.plan_context.get("tasks", []))
            base_content += f"""

### Plan Integration

You have an active task plan with **{task_count} tasks** in `tasks/plan.json`.

When creating your evolving skill:
1. **Reference the plan**: Add `Task plan: tasks/plan.json ({task_count} tasks)` in your Overview section
2. **Focus on learnings**: The plan has task structure - your skill should capture HOW to execute and what you LEARNED
3. **Map insights to tasks**: In your Learnings section, note which task IDs your insights apply to (e.g., "T003: Found that X works better than Y")
4. **Keep minimal**: Don't duplicate the entire plan in your skill - focus on execution details and improvements
"""

        return base_content


class OutputFirstVerificationSection(SystemPromptSection):
    """
    Core principle: verify outcomes and iterate improvements.

    HIGH priority - fundamental operating principle for quality work.
    This is not just about checking if something works (for voting),
    but actively improving outputs through iteration.
    Always included regardless of tools available.
    """

    def __init__(self, decomposition_mode: bool = False):
        super().__init__(
            title="Output-First Iteration",
            priority=Priority.CRITICAL,  # TODO: Change back to 'HIGH' ?
            xml_tag="output_first_iteration",
        )
        self.decomposition_mode = decomposition_mode

    def build_content(self) -> str:
        base = """## Output-First Iteration

**Core Principle: Experience your work exactly as a user would - through dynamic interaction, not just static observation.**

This is an **improvement loop**, not just a verification step:
1. Run/view output → 2. **Interact as a user would** → 3. Identify gaps or issues → 4. Fix and enhance → 5. Re-run and re-interact → 6. Repeat until excellent

### Dynamic Verification: Think Like a User

A single static observation (screenshot, one test run) is often not sufficient. Users don't just look at artifacts - they interact with them:

| Artifact Type | Shallow Check (incomplete) | Full Check (required) |
|--------------|---------------------------|--------------------------|
| Website/App | Screenshot looks good | Click all buttons, navigate all pages, test forms, verify links work |
| Game | Screenshot shows UI | Play the game - test controls, scoring, game over states, restart |
| Animation/transition | Single frame looks correct | Record and review the full motion sequence |
| Interactive tool | Interface renders | Use every feature, test edge cases, verify all interactions |
| Script/Code | No errors on run | Test with various inputs, edge cases, invalid data |
| API | Single call works | Test all endpoints, error states, authentication flows |
| Audio output | File exists | Listen/analyze the actual audio content — play it, don't just check the file exists |
| Data pipeline | Output exists | Validate accuracy, test with edge case inputs |
| Visual document / static artifact | File generates without error | Render to image(s) and **view each page/slide** — does layout, imagery, colors, and content actually look right? \
Render to images using available tools, then read_media each one. |

**Match evidence to how the output is experienced:**
- **Static visual** (documents, images, layouts) → render to images and view them; \
  generating a file without error says nothing about what it looks like
- **Dynamic / motion** (animations, transitions, interactive flows) → capture video; \
  a screenshot cannot verify movement or interaction sequences
- **Audio** → listen to the actual output, not just confirm the file exists

When in doubt: *does this move?* → video. *Does it stay still?* → screenshot. \
`read_media` accepts images, video, and audio — use whichever matches what you are proving.

### The User Experience Test

Before considering any interactive artifact complete, ask:
1. **What will users click/interact with?** → Do it. Does it work?
2. **What will users type/input?** → Try it. Does it respond correctly?
3. **What paths will users take?** → Navigate them all. Any broken routes?
4. **How will users break it?** → Try to break it. Does it handle errors gracefully?

### Why this matters:
- A website screenshot can look perfect while half the links are broken
- A game screenshot shows nothing about whether gameplay works
- An interactive tool may render but crash on first click
- Any artifact may LOOK correct but FAIL when actually used

**The goal is to verify INTERACTION OUTCOMES, not just visual appearance.**

### Apply at every stage:
1. **During development** - short loops: interact, improve, re-interact
2. **Before answering** - full interaction test on the actual output
3. **During evaluation** - judge by interaction results, improve if gaps found

### Iteration examples:
- **Websites**: Visit all pages → click every nav link → found 2 broken links → fix routes → re-test all links → confirm working
- **Games**: Play game → controls unresponsive → fix input handling → replay → confirm smooth gameplay
- **Interactive tools**: Use all features → export fails on large files → add chunking → re-test export → confirm fixed
- **Code**: Run with test inputs → crashes on empty array → add validation → rerun with edge cases → confirm robust

### Finalization:
- Use `new_answer` when you produced work or iterated improvements based on **interaction testing**."""

        if self.decomposition_mode:
            base += "\n- Use `stop` only when you have reviewed everything and are satisfied with your deliverables as-is. If you improved your deliverable work this round, use `new_answer` instead."
        else:
            base += "\n- Use `vote` only when an existing answer already meets the bar after **testing as a user would**."

        return base


class MultimodalToolsSection(SystemPromptSection):
    """
    Guidance for using read_media to verify artifacts with appropriate evidence.

    MEDIUM priority - extends output-first verification with evidence capture.
    Only included when multimodal tools are enabled.
    """

    def __init__(self):
        super().__init__(
            title="Evidence-Based Verification",
            priority=Priority.MEDIUM,
            xml_tag="evidence_based_verification",
        )

    def build_content(self) -> str:
        return """## Evidence-Based Verification

Use `read_media` to analyze evidence of your work, but remember: **interact first, capture evidence second.**

### Key Principle
Choose the evidence format that actually proves correctness for your artifact:
1. **Interact** with the artifact as a user would (click, navigate, play, input)
2. **Capture** evidence that demonstrates correctness — screenshots for layout, video recordings for animations/interactions, audio analysis for sound
3. **Analyze** with read_media using **critical prompts**

You can create any evidence you need: Playwright `recordVideo()`, `ffmpeg` screen/audio capture, VHS terminal recordings, or plain screenshots. `read_media` accepts images, video, and audio.

### Built-In Critical Analysis
The vision model is already instructed to be a critical reviewer — it will identify
problems and distinguish fundamental issues from surface-level fixes. You don't need
to write elaborate critical prompts, but you should still be specific about what to
evaluate.

**Good prompts by domain (e.g.):**
- Website/UI: "What flaws, layout issues, or broken elements do you see? Does it look polished or like a template?"
- Generated image: "Does this match what was requested? What's off about composition, style, or detail?"
- Chart/diagram: "Is the data clearly communicated? Are labels readable? What's misleading?"
- Document/presentation: "Is the content well-organized? What would a reviewer flag as unclear or incomplete?"

If read_media reports fundamental issues with the approach, treat this as a signal
to reconsider your direction — not just patch individual problems.

### Follow-Up Conversations
You can ask follow-up questions to a previous read_media analysis by passing
`continue_from` with the `conversation_id` from a previous result. This continues
the vision model conversation — it remembers the previous images and analysis.

Use follow-ups for:
- Comparing before/after: "I fixed the spacing. Is it better now?"
- Drilling into specifics: "Focus on just the navigation bar"
- Verifying fixes: "Does this version address the issues you found?"

You can include a new `file_path` with a follow-up, or just send a new prompt
to ask about the same image(s).

A broad first analysis often flags issues in passing without going deep. Use
follow-ups to drill into specific quality dimensions that matter for your task —
don't settle for a single surface-level pass when a targeted follow-up would
give you better direction.

**Supported formats:**
- Images: png, jpg, jpeg, gif, webp, bmp
- Audio: mp3, wav, m4a, ogg, flac, aac
- Video: mp4, mov, avi, mkv, webm

A beautiful screenshot means nothing if buttons don't work. A single frame cannot prove an animation is smooth. Test functionality, then verify with evidence that matches what you're proving.

### Audio Generation
For text-to-speech, music, or sound effects, prefer `generate_media` with \
`mode="audio"` over installing third-party packages (e.g., `edge-tts`, `pyttsx3`). \
It handles backend selection and file management automatically. \
If no API keys are available, falling back to free packages like `edge-tts` is fine.

**Important for TTS:** The `prompt` parameter is the **literal text to speak** — \
do NOT include speaking instructions in it (the TTS will read them aloud). \
Use the `instructions` parameter for tone/style guidance instead. \
Voice names like "Rachel" or "Sarah" are auto-resolved to ElevenLabs UUIDs.

### Modality Skills
For detailed guidance on backends, advanced features, and parameter reference, \
read the per-modality skills: `image-generation`, `video-generation`, \
`audio-generation`. These cover backend comparison tables, continuation \
workflows, and editing capabilities.

### Media Editing Capabilities
`generate_media` supports editing and transformation beyond basic generation:

**Video:** Use `continue_from` with a previous result's `continuation_id` to \
refine videos iteratively (OpenAI Sora remix, Google Veo extension, Grok \
editing). Use `input_images` with `mode="video"` for image-to-video \
generation (OpenAI Sora, Google Veo, Grok). \
Veo supports `size` for resolution (`"720p"`, `"1080p"`, `"4k"`; \
1080p/4k require 8s duration), `video_reference_images` (up to 3 images \
for style guidance), and `negative_prompt`. Veo extensions are forced to 720p. \
Veo 3.1 generates audio natively — include dialogue in quotes and \
describe sounds/atmosphere in the prompt.

**Image editing:** Use `mask_path` for inpainting (OpenAI). Use `style_image`, \
`control_image`, or `subject_image` for Google Imagen advanced editing. Use \
`negative_prompt`, `seed`, and `guidance_scale` for fine-grained control \
(Google Imagen).

**Audio editing:** Use `audio_type` to select operation:
- `"voice_conversion"` — change voice timbre (requires `input_audio`)
- `"audio_isolation"` — remove background noise (requires `input_audio`)
- `"voice_design"` — create voice from text description
- `"voice_clone"` — clone voice from samples (requires `voice_samples`)
- `"dubbing"` — translate and dub preserving voice (requires `input_audio`, \
`target_language`)

**Advanced TTS:** Use `speed` (OpenAI, 0.25-4.0), `voice_stability` and \
`voice_similarity` (ElevenLabs, 0.0-1.0) for fine-grained speech control.

### Image Sourcing Fallback
If you encounter legal restrictions when trying to use or reference existing photographs
(e.g., celebrity photos, copyrighted images), **generate original images** using
`generate_media` instead of leaving the content without visuals. A custom-generated
image is always better than a placeholder or missing visual."""


class TaskContextSection(SystemPromptSection):
    """
    Instructions for creating CONTEXT.md before using multimodal tools or subagents.

    This ensures external API calls (to GPT-4.1, Gemini, etc.) have context about
    what the user is trying to accomplish, preventing hallucinations about
    task-specific terminology.

    MEDIUM priority - included when multimodal tools or subagents are enabled.
    """

    def __init__(self):
        super().__init__(
            title="Task Context",
            priority=Priority.MEDIUM,
            xml_tag="task_context",
        )

    def build_content(self) -> str:
        return """## Task Context for Tools and Subagents

**REQUIRED**: Before spawning subagents or using `read_media`,
you MUST create a `CONTEXT.md` file in your workspace with task context.
This ordering is strict even for background jobs: write `CONTEXT.md` first, then start `read_media`.

`generate_media` does **not** require CONTEXT.md — it works without it.

### Why This Matters
External APIs (like in `read_media`) have no idea what you're working on.
Without context, they will hallucinate - for example, interpreting "MassGen" as
"Massachusetts General Hospital" instead of "multi-agent AI system".

### What to Include in CONTEXT.md
Write a brief file explaining:
- **What we're building/doing** - the core task in 1-2 sentences
- **Key terminology** - project-specific terms that could be misinterpreted
- **Visual/brand details** - style, colors, aesthetic if relevant
- **Any other context** tools or subagents need to understand the task

### Example CONTEXT.md
```markdown
# Task Context

Building a marketing website for MassGen - a multi-agent AI orchestration system
that coordinates parallel AI agents through voting and consensus.

## Key Terms
- MassGen: Multi-agent AI coordination system (NOT Massachusetts General Hospital)
- Agents: Individual AI instances that collaborate
- Voting: Consensus mechanism where agents vote on best solutions

## Visual Style
- Dark theme with terminal aesthetic
- Primary color: indigo (#4F46E5)
- Modern, technical but approachable tone
```

### When to Create It
Create CONTEXT.md **before** your first use of:
- `spawn_subagents` - subagents will inherit this context
- `read_media` - image/audio/video analysis will use this context

The file will be read automatically and injected into external API calls.
`generate_media` does not require CONTEXT.md."""


class SystemPromptBuilder:
    """
    Builder for assembling system prompts from sections.

    Automatically handles:
    - Priority-based sorting
    - XML structure wrapping
    - Conditional section inclusion (via enabled flag)
    - Hierarchical subsection rendering

    Example:
        >>> builder = SystemPromptBuilder()
        >>> builder.add_section(AgentIdentitySection("You are..."))
        >>> builder.add_section(SkillsSection(skills=[...]))
        >>> system_prompt = builder.build()
    """

    def __init__(self):
        self.sections: list[SystemPromptSection] = []

    def add_section(self, section: SystemPromptSection) -> "SystemPromptBuilder":
        """
        Add a section to the builder.

        Args:
            section: SystemPromptSection instance to add

        Returns:
            Self for method chaining (builder pattern)
        """
        self.sections.append(section)
        return self

    def build(self) -> str:
        """
        Assemble the final system prompt.

        Process:
        1. Filter to enabled sections only
        2. Sort by priority (lower number = earlier in prompt)
        3. Render each section (with XML if specified)
        4. Join with blank lines
        5. Wrap in root <system_prompt> XML tag

        Returns:
            Complete system prompt string ready for use
        """
        # Filter to enabled sections only
        enabled_sections = [s for s in self.sections if s.enabled]

        # Sort by priority (CRITICAL=1 comes before LOW=15)
        sorted_sections = sorted(enabled_sections, key=lambda s: s.priority)

        # Render each section
        rendered_sections = [s.render() for s in sorted_sections]

        # Join with blank lines
        content = "\n\n".join(rendered_sections)

        # Wrap in root tag
        return f"<system_prompt>\n\n{content}\n\n</system_prompt>"
