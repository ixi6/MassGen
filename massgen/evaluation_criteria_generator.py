"""GEPA-inspired evaluation criteria generation for MassGen.

This module generates task-specific evaluation criteria via a pre-collaboration
consensus run, replacing fixed T1-T4 items with dynamic E1-EN criteria tailored
to the actual task. When generation is disabled or fails, concrete static defaults
are used instead.

Each criterion is tagged with a tier:
- "must": Hard requirements — failing these means the answer is wrong.
- "should": Quality expectations that demand deliberate craft — not just
  functional completeness, but thoughtful execution a user would notice.
- "could": Excellence markers — genuine creative ambition or distinctive
  quality that makes the output stand out.

For backward compatibility, old "core" maps to "must" and "stretch" maps to "could".
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class EvaluationCriteriaGeneratorConfig:
    """Configuration for evaluation criteria generation.

    Attributes:
        enabled: Whether criteria generation is enabled
        persist_across_turns: If True, reuse criteria across interactive turns
        min_criteria: Minimum number of criteria to generate
        max_criteria: Maximum number of criteria to generate
    """

    enabled: bool = False
    persist_across_turns: bool = False
    min_criteria: int = 4
    max_criteria: int = 7


@dataclass
class GeneratedCriterion:
    """A single evaluation criterion.

    Attributes:
        id: Criterion identifier (e.g., "E1", "E2")
        text: The criterion description text
        category: "must", "should", or "could" (legacy: "core"→"must", "stretch"→"could")
        verify_by: Optional free-form instruction for how to gather evidence for this
            criterion. Set when reading the output text is insufficient — e.g.
            "render each slide to PNG and view visually with read_media",
            "record a video of the full animation and review the motion",
            "listen to the audio output from start to finish",
            "open in browser and test: click all links, submit forms, check states".
            None when textual inspection of the output is sufficient.
    """

    id: str
    text: str
    category: str  # "must", "should", or "could" (legacy: "core"→"must", "stretch"→"could")
    verify_by: str | None = None


# Static defaults inspired by GEPA's diagnostic structure.
# These replace the legacy abstract T1-T4 items with concrete defaults
# that work for any task type.
_DEFAULT_CRITERIA_TEXTS = [
    ("The output directly achieves what was asked for — requirements are met," " not just approximated. Missing or partially implemented requirements" " count as failures."),
    ("No broken functionality, errors, or obvious defects. Everything that's" " present works correctly. A working output with fewer features beats a" " broken one with more."),
    ("The output is thorough — no significant gaps, thin sections, or" " placeholder content. Each component has enough depth to be genuinely" " useful, not just present."),
    ("The output shows care beyond correctness — thoughtful choices," " consistent style, attention to edge cases, or creative elements that" " distinguish it from adequate work."),
]

_DEFAULT_CATEGORIES = ["must", "must", "should", "could"]

# ---------------------------------------------------------------------------
# Domain-specific criteria presets
# ---------------------------------------------------------------------------
# Each preset maps to a list of (text, category) tuples.  The criteria are
# sourced from docs/modules/composition.md and cover the well-defined quality
# characteristics of each special primitive.

_CRITERIA_PRESETS: dict[str, list[tuple[str, str]]] = {
    "persona": [
        (
            "Each persona articulates a clear, specific perspective that would lead to"
            " meaningfully different outputs — not just surface variation in tone or"
            " vocabulary. Two personas that would produce essentially the same answer"
            " are a failure.",
            "must",
        ),
        (
            "Personas are grounded in the actual task. Each perspective is relevant to" " the problem domain and brings a genuinely useful lens, not an arbitrary" " or forced viewpoint.",
            "must",
        ),
        (
            "Personas are actionable instructions, not character descriptions. An agent"
            " receiving this persona knows exactly how it changes their approach,"
            " priorities, and decision-making — not just who they are pretending to be.",
            "must",
        ),
        (
            "The persona set collectively provides coverage — the major reasonable"
            " approaches, value trade-offs, or methodological choices for this task are"
            " represented. No critical perspective is missing.",
            "should",
        ),
        (
            "Personas are vivid enough to resist homogenization under peer pressure."
            " The perspective is strongly stated so that even after seeing other agents'"
            " answers, the core viewpoint remains distinguishable.",
            "could",
        ),
    ],
    "decomposition": [
        (
            "Subtasks are collectively exhaustive — completing all subtasks fully"
            " produces the complete output. No significant aspect of the original task"
            " falls through the cracks between subtasks.",
            "must",
        ),
        (
            "Subtasks have minimal coupling — each can be executed independently"
            " without requiring intermediate results from other subtasks. Where"
            " dependencies exist, they are explicit and the dependency order is"
            " specified.",
            "must",
        ),
        (
            "Subtask scoping is balanced — no single subtask is trivial while another"
            " carries the bulk of the complexity. Work is distributed so each agent has"
            " a meaningful, roughly comparable contribution.",
            "should",
        ),
        (
            "Each subtask description is self-contained and specific enough that an" " agent can execute it without needing to infer intent from other subtasks" " or the original prompt.",
            "must",
        ),
        (
            "The decomposition strategy is appropriate for the task type — creative"
            " tasks split along conceptual boundaries, technical tasks along component"
            " boundaries, analytical tasks along dimension boundaries.",
            "could",
        ),
    ],
    "evaluation": [
        (
            "Each criterion is specific to the actual task — not generic advice that" " applies to any output. A criterion that could be copy-pasted to an" " unrelated task is too vague.",
            "must",
        ),
        (
            "Criteria are evaluable — an agent can determine pass/fail by examining the"
            ' output, not by making subjective judgments about intent. "Addresses edge'
            ' cases" is vague; "handles empty input, null values, and boundary'
            ' conditions" is evaluable.',
            "must",
        ),
        (
            "The criteria set distinguishes excellent work from adequate work. If every"
            " competent first draft would pass all criteria, the bar is too low. At"
            " least one criterion should require genuine effort to satisfy.",
            "should",
        ),
        (
            "Tier categorization is correct. MUST criteria represent"
            " non-negotiable requirements; COULD criteria represent quality"
            " differentiators. A misclassified MUST criterion blocks good work; a"
            " misclassified COULD criterion lets mediocre work pass.",
            "must",
        ),
        (
            "Criteria do not conflict with each other or create impossible trade-offs."
            " Meeting one criterion should not require violating another. Where genuine"
            " tensions exist, the criteria acknowledge the trade-off explicitly.",
            "could",
        ),
    ],
    "prompt": [
        (
            "The prompt achieves its functional goal — an agent receiving this prompt"
            " would produce the intended type of output without additional"
            " clarification. Test: could you hand this to a capable model cold and get"
            " back what you need?",
            "must",
        ),
        (
            "The prompt is appropriately scoped — it constrains enough to prevent" " unhelpful outputs but does not over-constrain in ways that eliminate" " valid approaches.",
            "must",
        ),
        (
            "Important requirements are explicit, not implied. The prompt does not" ' depend on shared context, cultural assumptions, or "obvious" intentions' " that a model might miss.",
            "should",
        ),
        (
            "The prompt is structured for parseability — key instructions are" " prominent, not buried in paragraphs. An agent skimming the prompt would" " still catch the critical constraints.",
            "could",
        ),
        (
            "The prompt anticipates likely failure modes for its task type and includes"
            ' guardrails against them (e.g., "do not summarize when asked to analyze"'
            ' or "include concrete examples, not abstract principles").',
            "could",
        ),
    ],
    "analysis": [
        (
            "The analysis identifies concrete, specific findings — not vague" " observations. Each finding points to a specific location, pattern, or" " data point in the source material.",
            "must",
        ),
        (
            "Findings are supported by evidence from the actual data, not inferred from"
            ' assumptions about what "usually" happens. Claims include references to'
            " specific log entries, metrics, or examples.",
            "must",
        ),
        (
            "The analysis distinguishes symptoms from root causes. Surface-level"
            ' observations (e.g., "agent 2 was slow") are traced to underlying'
            ' explanations (e.g., "agent 2 hit rate limits due to tool call volume").',
            "should",
        ),
        (
            "Actionable recommendations follow from findings. Each significant finding" " includes a concrete suggestion for what to change, not just a description" " of what went wrong.",
            "must",
        ),
        (
            "The analysis identifies patterns across the dataset, not just individual"
            " anomalies. Recurring behaviors, systematic biases, or structural issues"
            " are surfaced alongside one-off events.",
            "could",
        ),
    ],
    "planning": [
        (
            "The plan captures the user's requested outcome and constraints" " without scope drift. Critical requirements are explicit, and no" " mandatory deliverable expectation is omitted.",
            "must",
        ),
        (
            "The task graph is executable and internally consistent:" " dependencies are valid, ordering is coherent, and there are no" " contradictory or impossible steps.",
            "must",
        ),
        (
            "Tasks describe both what to produce AND how to approach it —"
            " the method, key decisions, and constraints that guide execution."
            " 'Create the hero section' is insufficient; 'restructure the hero"
            " section: move value proposition above the fold, use existing brand"
            " palette, add a single prominent CTA' tells the executor what to"
            " actually do. Each task should be actionable without requiring the"
            " executor to infer creative or technical direction.",
            "must",
        ),
        (
            "Each task has verification guidance matched to its type."
            " Verification may be deterministic (run tests, validate responses,"
            " check file structure) or qualitative (render to images and assess"
            " visual quality, read the output and evaluate tone, watch playback"
            " and judge pacing). Plans must NOT force numeric thresholds on"
            " inherently qualitative work — 'visually inspect the rendered page"
            " for layout balance and readability' is valid verification."
            " Verification says what to examine and what to look for.",
            "must",
        ),
        (
            "Technology and tooling choices are explicit and justified."
            " Frameworks, libraries, APIs, and tools are named — not left for"
            " the executor to guess. For existing codebases, the plan respects"
            " the established stack and conventions rather than introducing"
            " gratuitous alternatives.",
            "must",
        ),
        (
            "Where tasks connect or produce artifacts consumed by other tasks,"
            " interface contracts are specified: data shapes, file conventions,"
            " API signatures, or shared types. Independent execution of tasks"
            " should not require reverse-engineering unstated agreements.",
            "should",
        ),
        (
            "Assumptions, boundaries, and trade-offs are documented with" " rationale. Ambiguities are resolved with explicit defaults rather" " than left implicit.",
            "should",
        ),
        (
            "The plan demonstrates thoughtful sequencing and risk management:"
            " chunking and prioritization reduce rework, high-risk or"
            " foundational tasks come first, and quality gates are placed"
            " where they most improve final output quality.",
            "should",
        ),
    ],
    "spec": [
        (
            "Requirements are complete and unambiguous — each requirement" " describes a single, testable behavior or property. A developer" " reading the spec can implement without guessing intent.",
            "must",
        ),
        (
            "Each requirement has concrete acceptance criteria: specific" " conditions, inputs, expected outputs, or observable behaviors" " that prove the requirement is met.",
            "must",
        ),
        (
            "Scope boundaries are explicit — what is in scope and what is"
            " deliberately out of scope are both stated. The spec does not"
            " silently omit aspects the user would expect to be covered.",
            "must",
        ),
        (
            "Requirements are prioritized and internally consistent — no two"
            " requirements contradict each other, and the priority or"
            " ordering reflects genuine implementation dependencies and"
            " user-facing importance.",
            "should",
        ),
        (
            "Requirements anticipate edge cases, error states, and boundary" " conditions relevant to the domain. The spec does not only" " describe the happy path.",
            "could",
        ),
    ],
}

# Public constant for validation (used by config_validator and tests)
VALID_CRITERIA_PRESETS: frozenset[str] = frozenset(_CRITERIA_PRESETS.keys())


def criteria_from_inline(inline_list: list[dict[str, str]]) -> list[GeneratedCriterion]:
    """Convert inline criteria dicts to GeneratedCriterion objects.

    Args:
        inline_list: List of dicts with 'text' and 'category' keys.

    Returns:
        List of GeneratedCriterion with E1..EN IDs.
    """
    return [GeneratedCriterion(id=f"E{i + 1}", text=item["text"], category=item["category"]) for i, item in enumerate(inline_list)]


def get_criteria_for_preset(preset: str) -> list[GeneratedCriterion]:
    """Return domain-specific criteria for a named preset.

    Args:
        preset: One of the known preset names (persona, decomposition,
                evaluation, prompt, analysis).

    Returns:
        List of GeneratedCriterion with E1..E5 IDs.

    Raises:
        ValueError: If preset name is not recognized.
    """
    if preset not in _CRITERIA_PRESETS:
        valid = ", ".join(sorted(_CRITERIA_PRESETS.keys()))
        raise ValueError(
            f"Unknown criteria preset: '{preset}'. Valid presets: {valid}",
        )

    return [GeneratedCriterion(id=f"E{i + 1}", text=text, category=category) for i, (text, category) in enumerate(_CRITERIA_PRESETS[preset])]


# Quality/craft criterion — always appended as the last should-tier criterion.
# Ensures evaluators assess whether the output shows intentional, thoughtful
# choices beyond functional correctness. Without this, agents satisfy all
# requirements while producing output that feels like a minimum viable version.
_QUALITY_CRAFT_TEXT = (
    "The output reflects intentional, thoughtful choices — not just"
    " minimum viable execution. A knowledgeable person in this domain"
    " would recognize craft, not just correctness. The whole feels"
    " cohesive and considered, not assembled from adequate parts."
)

# Changedoc traceability criterion — appended when changedoc is enabled
_CHANGEDOC_TRACEABILITY_TEXT = (
    "Changedoc is honest, complete, and traceable. Every significant"
    " decision is documented with genuine rationale. Implementation"
    " references point to code that actually exists. No fabricated claims."
)


def get_default_criteria(has_changedoc: bool = False) -> list[GeneratedCriterion]:
    """Return static default evaluation criteria.

    These are used when generation is disabled or fails. They are concrete,
    GEPA-inspired defaults that work for any task type.

    Always appends a quality/craft criterion.  Optionally appends changedoc
    traceability when changedoc mode is active.

    Args:
        has_changedoc: If True, append changedoc traceability criterion.

    Returns:
        List of GeneratedCriterion with E-prefix IDs.
    """
    criteria = [
        GeneratedCriterion(
            id=f"E{i + 1}",
            text=text,
            category=category,
        )
        for i, (text, category) in enumerate(
            zip(_DEFAULT_CRITERIA_TEXTS, _DEFAULT_CATEGORIES),
        )
    ]

    # Always append quality/craft criterion
    criteria.append(
        GeneratedCriterion(
            id=f"E{len(criteria) + 1}",
            text=_QUALITY_CRAFT_TEXT,
            category="should",
        ),
    )

    if has_changedoc:
        criteria.append(
            GeneratedCriterion(
                id=f"E{len(criteria) + 1}",
                text=_CHANGEDOC_TRACEABILITY_TEXT,
                category="must",
            ),
        )

    return criteria


def _parse_criteria_response(
    response: str,
    min_criteria: int = 4,
    max_criteria: int = 7,
) -> list[GeneratedCriterion] | None:
    """Parse LLM response into GeneratedCriterion objects.

    Tries to extract JSON from the response using multiple strategies:
    1. Direct JSON parse
    2. Extract from markdown code blocks
    3. Find JSON object by braces

    Returns None if parsing fails or validation doesn't pass (triggering fallback).
    """
    json_str = response.strip()

    data = _try_parse_json(json_str)

    # Strategy 2: Extract from markdown code blocks
    if data is None and "```" in json_str:
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            if end > start:
                data = _try_parse_json(json_str[start:end].strip())
        if data is None:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            if end > start:
                data = _try_parse_json(json_str[start:end].strip())

    # Strategy 3: Find JSON by braces
    if data is None:
        criteria_start = json_str.find('{"criteria"')
        if criteria_start >= 0:
            brace_count = 0
            json_end = -1
            for i, char in enumerate(json_str[criteria_start:]):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = criteria_start + i + 1
                        break
            if json_end > criteria_start:
                data = _try_parse_json(json_str[criteria_start:json_end])

    if data is None or "criteria" not in data:
        logger.warning("Failed to parse criteria response")
        return None

    try:
        raw_criteria = data["criteria"]
        if not isinstance(raw_criteria, list):
            logger.warning("criteria field is not a list")
            return None

        # Validate count
        if len(raw_criteria) < min_criteria:
            logger.warning(
                f"Too few criteria: {len(raw_criteria)} < {min_criteria}",
            )
            return None
        if len(raw_criteria) > max_criteria:
            logger.warning(
                f"Too many criteria: {len(raw_criteria)} > {max_criteria}",
            )
            return None

        # Parse into GeneratedCriterion objects with tier mapping
        # Backward compat: "core" → "must", "stretch" → "could"
        _CATEGORY_MAP = {"core": "must", "stretch": "could"}
        _VALID_CATEGORIES = {"must", "should", "could"}
        criteria = []
        for i, item in enumerate(raw_criteria):
            text = item.get("text", "")
            raw_category = item.get("category", "core")
            category = _CATEGORY_MAP.get(raw_category, raw_category)
            if category not in _VALID_CATEGORIES:
                category = "must"
            verify_by = item.get("verify_by") or None
            if verify_by and not isinstance(verify_by, str):
                verify_by = None
            criteria.append(
                GeneratedCriterion(
                    id=f"E{i + 1}",
                    text=text,
                    category=category,
                    verify_by=verify_by,
                ),
            )

        # Validate: at least min_criteria - 1 must/should items
        core_count = sum(1 for c in criteria if c.category in ("must", "should"))
        if core_count < min_criteria - 1:
            logger.warning(
                f"Not enough core criteria: {core_count} < {min_criteria - 1}",
            )
            return None

        return criteria

    except (KeyError, TypeError, AttributeError) as e:
        logger.warning(f"Failed to extract criteria from parsed data: {e}")
        return None


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Attempt to parse JSON, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


class EvaluationCriteriaGenerator:
    """Generates task-specific evaluation criteria via subagent coordination.

    When enabled, spawns a pre-collaboration subagent run to generate criteria
    specific to the task. Falls back to static defaults on failure.
    """

    def __init__(self):
        self.last_generation_source = "unknown"

    def _build_generation_prompt(
        self,
        task: str,
        has_changedoc: bool,
        min_criteria: int = 4,
        max_criteria: int = 7,
        has_planning_spec_context: bool = False,
    ) -> str:
        """Build the prompt for criteria generation.

        Args:
            task: The user's task description
            has_changedoc: Whether changedoc mode is active
            min_criteria: Minimum number of criteria
            max_criteria: Maximum number of criteria
            has_planning_spec_context: Whether planning/spec context is mounted
                and should be explicitly referenced by prompt guidance.

        Returns:
            The formatted prompt string
        """
        changedoc_instruction = ""
        if has_changedoc:
            changedoc_instruction = """
- **One criterion MUST assess changedoc traceability**: whether decisions are
  documented with genuine rationale and implementation references are accurate.
  Tag this criterion as "must".
"""

        planning_context_section = ""
        if has_planning_spec_context:
            planning_context_section = """

## Planning/Spec Context Alignment
Read the mounted planning/spec context before generating criteria and align with \
it so goals, personas, and deliverable expectations stay coherent. Treat planning/spec \
files as read-only references — do not modify them.
"""

        return f"""You are generating evaluation criteria for a multi-agent AI system.

## Task Being Evaluated
{task}
{planning_context_section}

## Your Goal
Generate {min_criteria}-{max_criteria} concrete, verifiable evaluation criteria \
specific to THIS task. Each criterion names a quality dimension and describes \
what to look for when assessing it.

Criteria must be **concrete and verifiable** — specific enough that an evaluator \
can point to evidence in the output.

## What Correctness Means

Correctness is not just "the file exists and opens." A correct output is one that \
works as the user actually experiences it across all relevant dimensions:

- **Structural correctness**: the output has the right form and can be used at all \
  (file opens, code runs, API responds)
- **Content correctness**: the output says or computes the right things — accurate, \
  complete, no factual errors or wrong results
- **Experiential correctness**: the output behaves correctly in its primary use \
  environment — text renders without overflow or clipped characters, visuals display \
  as intended, interactions work, audio/video plays back properly, no obvious visual \
  glitches or broken elements at the normal viewing context

An output that passes structural checks but fails experiential ones (e.g., text that \
renders with a single letter orphaned on its own line, a chart that displays blank, a \
button that does nothing, a layout that is visually broken at the default viewport) is \
a *wrong* output, not a mediocre one. Correctness criteria must cover all three \
dimensions, not just structural validity.

Experiential correctness at the **primary use context** is always MUST — the output \
must work correctly where and how it will normally be used. Extended contexts (e.g., \
multiple screen sizes, edge-case inputs, non-default settings) may be SHOULD or COULD \
depending on whether the task explicitly requires them.

Correctness is separate from **quality/craft**: a correct output can still be mediocre. Craft \
criteria ask whether the output shows intentional quality — cohesive choices, thoughtful \
structure, elegance — beyond what is merely correct. Include at least one craft criterion \
tagged "should".

BAD (abstract): "Visual design quality."
GOOD (concrete): "Visual design: typography is legible at mobile resolution \
(16px+ body text, sufficient contrast), layout has clear visual hierarchy, \
color palette is consistent across all pages."

BAD (abstract): "Code quality."
GOOD (concrete): "Code quality: functions have single responsibility, error \
paths are handled (no swallowed exceptions), public API has type annotations, \
no hardcoded secrets or credentials."

BAD (only structural): all criteria check whether the output exists and has the right form
GOOD (covers all dimensions): criteria cover what it says/computes, how it behaves \
when actually used, and whether it shows intentional craft beyond correctness.

## Tier System

Organize criteria into three tiers:
- **MUST**: Hard requirements from the task. Failing these means the answer is wrong — \
across all dimensions of correctness (structural, content, and experiential). A first-year \
professional in the domain would not ship output that fails this. \
(e.g., "Output is a working 30-second video, not a still image or broken render")
- **SHOULD**: Quality dimensions where the output must demonstrate deliberate, \
thoughtful execution — not just functional completeness. A SHOULD criterion \
asks "did the creator make intentional choices here, or just do the obvious \
thing?" Functional baselines (e.g., "has mobile support", "images load") \
belong in MUST if they're requirements, not SHOULD. SHOULD criteria target \
the quality of execution: how well something is done, not whether it exists. \
(e.g., "Typography creates clear visual hierarchy with intentional size, \
weight, and spacing choices — not just default browser styles")
- **COULD**: Creative ambition and distinctive quality that makes the output \
memorable. COULD criteria ask "does this show a point of view?" — not just \
competent execution but something a viewer would specifically remember or \
comment on. These matter; they are what separates \
forgettable-but-correct output from work someone would show to a colleague. \
(e.g., "The site has a distinctive interactive moment that reinforces the \
brand identity — not a generic animation library demo but something that \
feels designed for this specific product")

**Calibration test**: first ask whether this is a correctness criterion — does failing \
it mean the output is *wrong* (broken, inaccurate, or misbehaving in its actual \
environment)? If yes, it is MUST regardless of how difficult it is to achieve. \
Only after ruling that out, ask: is this about the *quality of execution* — how \
thoughtfully something is done? Then it is SHOULD. Is this about *distinctive \
creative ambition* — would someone specifically notice or remember this? Then \
it is COULD. If a criterion can be satisfied by a simple checkbox action \
(add X, include Y, support Z), it belongs in MUST, not SHOULD.

## Requirements
1. Generate between {min_criteria} and {max_criteria} criteria
2. Tag each as "must", "should", or "could"
3. At least {min_criteria - 1} criteria must be "must" or "should"
4. 1-3 criteria may be "could" (what separates good from exceptional)
5. Each criterion must be specific to THIS task, not generic
6. Each criterion should be scoreable — an evaluator rates it on a 1-10 scale
7. **One criterion MUST assess quality/craft** — whether the output shows intentional, \
cohesive choices that a viewer would notice and appreciate. This criterion should \
demand evidence of a point of view, not just absence of defects. Tag it as "should". \
Without this, agents produce correct but forgettable output.
8. **Criteria must cover distinct dimensions of the task** — do not cluster \
multiple criteria around the same aspect. Think about what the major \
independent quality axes are for this specific task (e.g., content correctness, \
experiential correctness, completeness, error handling, usability, craft) and \
ensure each significant dimension gets at least one criterion. An evaluator \
reading the full set should feel like the entire task space is covered.
9. **For tasks that produce a rendered or experienced artifact** (website, slides, \
document, video, audio, interactive app): you MUST include a dedicated `must` \
criterion whose sole focus is rendering/playback correctness in the primary use \
context — no defects when the output is opened and experienced normally. This means: \
no text overflow or clipping, no element collisions, no invisible or blank content, \
no broken playback. Do NOT merge this into a craft or polish criterion — those are \
separate. Do NOT make this criterion `should`. It is always `must`.
10. **Per-part quality**: When the output has multiple distinct parts (sections of a \
page, chapters of a document, modules of a codebase, scenes of a video), include at \
least one criterion that assesses whether EACH significant part independently meets a \
quality bar. Whole-output criteria like "visual craft is intentional" allow one strong \
area to mask mediocrity elsewhere — an impressive hero section can pull up the score \
while feature cards, testimonials, and CTAs remain template-tier. A per-part criterion \
forces evaluation of the weakest component, not the average. Tag this "should".
{changedoc_instruction}
## Examples

For a task "Create an SVG of a pelican riding a bicycle":
- "Pelican accuracy: beak shape, throat pouch, plumage detail are recognizable and correct."
- "Bicycle accuracy: wheels, frame, handlebars, and pedals are all present and structurally plausible."
- "Convincingness of the riding pose: pelican's body position, grip, and balance look physically coherent."
- "Visual appeal: scenery, color palette, and composition make the image engaging beyond just accurate."

For a task "Write an API client library":
- "API coverage: all documented endpoints have working method signatures with correct parameters."
- "Error handling: client is resilient to network failures, rate limits, and malformed responses."
- "Developer ergonomics: naming is clear, the public API is discoverable, and usage is self-evident."

For tasks producing an artifact that is experienced rather than just read (rendered \
visuals, video, audio, interactive output): always include a MUST criterion covering \
correctness in the primary use context — for rendered output this means no visual \
defects when viewed normally; for video/audio this means plays back correctly without \
distortion, sync errors, or gaps; for interactive output this means all interactions \
work as expected without errors. This is separate from extended-context correctness \
(other viewports, edge devices, alternative players), which is typically SHOULD. \
The verify_by must require actually experiencing the full artifact, not just checking \
its source or structure.

Notice: these name a quality axis and list what to look for — they do NOT prescribe \
specific quantities, thresholds, or implementation choices.

BAD (prescriptive requirement): "The website contains at least 4 distinct pages covering history, discography, members, and legacy"
GOOD (evaluation dimension): "Breadth and depth of topic coverage: all major aspects of the subject are addressed with meaningful depth."

BAD (implementation plan): "Each of the four Beatles is individually featured with accurate biographical details including birth year, role, and contributions"
GOOD (evaluation dimension): "Individual member coverage: each member has accurate biographical detail, distinct contributions, and is not reduced to a footnote."

BAD (whole-output only): "The output shows intentional design choices"
GOOD (per-part): "Per-section quality: each significant section of the output independently \
demonstrates craft and purpose — no section is carried by the strength of others. \
Evaluate the weakest section, not the average."

## Output Format
Return JSON with this structure:
{{
    "criteria": [
        {{"text": "[Aspect name]: [concrete things to look for and how to assess them].", "category": "must"}},
        {{"text": "[Aspect name]: [concrete things to look for and how to assess them].", "category": "should", "verify_by": "render output to images and inspect for [specific defects to check]"}},
        {{"text": "[Aspect name]: [concrete things to look for and how to assess them].", "category": "could"}}
    ]
}}

**`verify_by` field**: Required whenever the criterion involves experiential correctness \
or craft that cannot be assessed by reading the source alone. Describe WHAT EVIDENCE to \
gather and WHAT TO CHECK — not which specific application or GUI to use. The evaluator \
will choose the best available tool (rendering, screenshots, browser automation, code \
execution, computer use, etc.) based on their capabilities.

State the full scope (all pages, all slides, full playback — not a sample) and list \
the specific defects or properties to look for.

- Rendered output (slides, pages, images): render ALL pages/slides to images and inspect \
  each for specific defects (e.g. text overflow, clipped elements, unreadable font sizes \
  below Npt, element collisions, blank content areas)
- Interactive output (web apps, forms): test all navigation links, form submissions, \
  button actions, and interactive state changes — list what each interaction should do
- Motion/animation: capture and review full animation playback — list expected motion \
  behavior and timing
- Audio/video: listen to or watch the complete output — list what to assess (clarity, \
  pacing, content accuracy)
- Executable code: run with representative inputs and check outputs against expected results

Do NOT name specific desktop applications (e.g. "open in PowerPoint", "view in Finder"). \
Do NOT describe GUI-specific actions (e.g. "hover to see cursor change", "right-click and \
select"). Instead describe the observable property to verify and let the evaluator choose \
the method.

Omit only when the criterion can be fully assessed by reading the output text or \
inspecting the source file structure.

Write the JSON to a file called `criteria.json` in your workspace.
Generate evaluation criteria now for the task above."""

    async def generate_criteria_via_subagent(
        self,
        task: str,
        agent_configs: list[dict[str, Any]],
        has_changedoc: bool,
        parent_workspace: str,
        log_directory: str | None,
        orchestrator_id: str,
        min_criteria: int = 4,
        max_criteria: int = 7,
        on_subagent_started: Callable | None = None,
        voting_sensitivity: str | None = None,
        voting_threshold: int | None = None,
        has_planning_spec_context: bool = False,
    ) -> list[GeneratedCriterion]:
        """Generate criteria via a subagent run.

        Args:
            task: The user's task
            agent_configs: Parent agent configs to inherit models from
            has_changedoc: Whether changedoc mode is active
            parent_workspace: Path to parent workspace
            log_directory: Path to log directory
            orchestrator_id: Parent orchestrator ID
            min_criteria: Minimum criteria count
            max_criteria: Maximum criteria count
            on_subagent_started: Callback when subagent starts
            voting_sensitivity: Optional voting sensitivity to pass through to
                the pre-collaboration subagent coordination config.
            voting_threshold: Optional voting threshold to pass through to
                the pre-collaboration subagent coordination config.
            has_planning_spec_context: Whether planning/spec context is mounted
                and should be explicitly referenced by prompt guidance.

        Returns:
            List of GeneratedCriterion objects
        """
        logger.info("Generating evaluation criteria via subagent")

        # Build workspace
        criteria_workspace = os.path.join(parent_workspace, ".criteria_generation")
        try:
            os.makedirs(criteria_workspace, exist_ok=True)
            context_md = os.path.join(criteria_workspace, "CONTEXT.md")
            with open(context_md, "w", encoding="utf-8") as f:
                f.write(
                    "# Evaluation Criteria Generation\n\n" f"Task:\n{task}\n\n" "Goal: Generate task-specific evaluation criteria in criteria.json.\n",
                )
        except Exception as e:
            logger.warning(f"Failed to prepare criteria workspace: {e}")
            criteria_workspace = parent_workspace

        try:
            from massgen.subagent.manager import SubagentManager
            from massgen.subagent.models import SubagentOrchestratorConfig

            # Simplified agent configs (no tools, pure LLM reasoning)
            simplified = []
            for i, config in enumerate(agent_configs):
                backend = config.get("backend", {})
                simplified.append(
                    {
                        "id": config.get("id", f"criteria_agent_{i}"),
                        "backend": {
                            "type": backend.get("type", "openai"),
                            "model": backend.get("model"),
                            "base_url": backend.get("base_url"),
                            "enable_mcp_command_line": False,
                            "enable_code_based_tools": False,
                            "exclude_file_operation_mcps": True,
                        },
                    },
                )

            coordination = {
                "enable_subagents": False,
                "broadcast": False,
                "checklist_criteria_preset": "evaluation",
            }
            if voting_sensitivity:
                coordination["voting_sensitivity"] = voting_sensitivity
            if voting_threshold is not None:
                coordination["voting_threshold"] = voting_threshold

            subagent_config = SubagentOrchestratorConfig(
                enabled=True,
                agents=simplified,
                coordination=coordination,
            )
            parent_context_paths = self._build_subagent_parent_context_paths(
                parent_workspace=parent_workspace,
                agent_configs=agent_configs,
            )

            manager = SubagentManager(
                parent_workspace=criteria_workspace,
                parent_agent_id="criteria_generator",
                orchestrator_id=orchestrator_id,
                parent_agent_configs=simplified,
                max_concurrent=1,
                default_timeout=300,
                subagent_orchestrator_config=subagent_config,
                log_directory=log_directory,
                parent_context_paths=parent_context_paths,
            )

            prompt = self._build_generation_prompt(
                task,
                has_changedoc,
                min_criteria,
                max_criteria,
                has_planning_spec_context=has_planning_spec_context,
            )

            def _status_callback(subagent_id: str) -> Any | None:
                try:
                    return manager.get_subagent_display_data(subagent_id)
                except Exception:
                    return None

            if on_subagent_started:
                try:
                    subagent_log_path = None
                    if log_directory:
                        subagent_log_path = str(
                            Path(log_directory) / "subagents" / "criteria_generation",
                        )
                    on_subagent_started(
                        "criteria_generation",
                        prompt,
                        300,
                        _status_callback,
                        subagent_log_path,
                    )
                except Exception:
                    pass

            result = await manager.spawn_subagent(
                task=prompt,
                subagent_id="criteria_generation",
                timeout_seconds=300,
            )

            # Try to find criteria.json in output
            if log_directory:
                criteria = self._find_criteria_json(
                    log_directory,
                    min_criteria,
                    max_criteria,
                )
                if criteria:
                    self.last_generation_source = "subagent"
                    logger.info(
                        f"Loaded {len(criteria)} criteria from criteria.json",
                    )
                    return criteria

            # Try parsing from answer text
            if result.answer:
                criteria = _parse_criteria_response(
                    result.answer,
                    min_criteria,
                    max_criteria,
                )
                if criteria:
                    self.last_generation_source = "subagent"
                    logger.info(
                        f"Parsed {len(criteria)} criteria from answer",
                    )
                    return criteria

            logger.warning("No valid criteria output found, using defaults")
            self.last_generation_source = "fallback"
            return get_default_criteria(has_changedoc=has_changedoc)

        except Exception as e:
            logger.error(f"Failed to generate criteria via subagent: {e}")
            self.last_generation_source = "fallback"
            return get_default_criteria(has_changedoc=has_changedoc)

    @staticmethod
    def _build_subagent_parent_context_paths(
        parent_workspace: str,
        agent_configs: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Build read-only context paths for pre-collab criteria subagents."""
        base_workspace = Path(parent_workspace).resolve()
        context_paths: list[dict[str, str]] = []
        seen: set[str] = set()

        def _add_path(raw_path: str | None) -> None:
            if not raw_path:
                return
            try:
                path_obj = Path(raw_path)
                resolved = path_obj.resolve() if path_obj.is_absolute() else (base_workspace / path_obj).resolve()
            except Exception:
                return

            path_str = str(resolved)
            if path_str in seen:
                return
            seen.add(path_str)
            context_paths.append({"path": path_str, "permission": "read"})

        _add_path(str(base_workspace))

        for config in agent_configs:
            if not isinstance(config, dict):
                continue
            backend = config.get("backend", {})
            if not isinstance(backend, dict):
                continue
            inherited_paths = backend.get("context_paths", [])
            if not isinstance(inherited_paths, list):
                continue
            for entry in inherited_paths:
                if isinstance(entry, str):
                    _add_path(entry)
                elif isinstance(entry, dict):
                    raw_path = entry.get("path")
                    _add_path(str(raw_path).strip() if raw_path else None)

        return context_paths

    def _find_criteria_json(
        self,
        log_directory: str,
        min_criteria: int,
        max_criteria: int,
    ) -> list[GeneratedCriterion] | None:
        """Search for criteria.json in subagent logs."""
        log_dir = Path(log_directory)
        criteria_gen_dir = log_dir / "subagents" / "criteria_generation"

        if not criteria_gen_dir.exists():
            return None

        search_patterns = [
            "full_logs/final/agent_*/workspace/criteria.json",
            "full_logs/agent_*/*/*/criteria.json",
            "workspace/snapshots/agent_*/criteria.json",
            "workspace/agent_*/criteria.json",
            "workspace/temp/agent_*/agent*/criteria.json",
        ]

        found_files: list[Path] = []
        for pattern in search_patterns:
            found_files.extend(criteria_gen_dir.glob(pattern))

        if not found_files:
            return None

        def _safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except (FileNotFoundError, OSError):
                return 0

        found_files = sorted(found_files, key=_safe_mtime, reverse=True)

        for criteria_file in found_files:
            if not criteria_file.exists():
                continue
            try:
                content = criteria_file.read_text()
                criteria = _parse_criteria_response(
                    content,
                    min_criteria,
                    max_criteria,
                )
                if criteria:
                    return criteria
            except Exception as e:
                logger.debug(f"Failed to parse {criteria_file}: {e}")
                continue

        return None
