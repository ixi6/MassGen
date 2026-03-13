# Composable Primitives and Phase Architecture

> **This is one of the most important conceptual documents in MassGen.** The system's power comes not from any single primitive, but from how they compose. Finding the right compositions — the right personas to build a rigorous plan, the right evaluation criteria to ensure every aspect of that plan is executed to a shockingly high standard, the right decomposition to let specialists own what they're best at — is what unlocks the full potential of multi-agent coordination.

## The Primitives

MassGen provides composable primitives that each shape a different dimension of agent behavior. Some run as **subagent spawns** (separate MassGen execution outside the main coordination loop), some run as **inline analysis** (reusing existing agents), and one operates as **per-round injection** into the main loop.

### Primitive Inventory

| Primitive | Mechanism | What it shapes | Output | Injection point |
|---|---|---|---|---|
| **Persona generation** | Subagent spawn | WHO the agents are — perspective, values, approach | Per-agent persona text (strong + softened) | Prepended to system message each round |
| **Evaluation criteria generation** | Subagent spawn | WHAT quality means — task-specific checklist gates | E1..EN criteria (core/stretch) | Replaces default E1-E4 in checklist tool + system message |
| **Task decomposition** | Subagent spawn | WHAT each agent works on — subtask ownership | Agent-to-subtask mapping plus optional per-agent execution criteria | Wraps user message with `[YOUR ASSIGNED SUBTASK: ...]` + fed into coordination system message |
| **Planning mode analysis** | Inline (reuses agent) | HOW agents can act — tool access during coordination | Planning/execution mode flags | Sets `backend.set_planning_mode()`, blocks tool access |

### How Output Flows Into the System

Understanding where each primitive's output lands is critical for reasoning about compositions:

**Persona generation** output flows into the **system message** at the start of every round. Round 0 gets the strong version ("your perspective is X, prioritize Y, approach Z"). Round 1+ gets the softened version ("treat your perspective as a preference, not a position to defend"). This means personas shape how agents interpret the task, what they prioritize, and what they notice in peer answers.

**Evaluation criteria** output flows into two places: (1) the **checklist tool state**, replacing the default E1-E4 items that gate the `submit_checklist` decision, and (2) the **system message** via `custom_checklist_items`, so agents know what they're being evaluated on. This means criteria control whether agents vote to converge or keep iterating.

**Task decomposition** output flows into (1) the **user message** per agent, wrapping the original prompt with the agent's assigned subtask, (2) the **coordination system message** so agents and the final presenter understand the decomposition, and optionally (3) **per-agent checklist criteria** used when checklist-gated decomposition is active. This means each agent sees a scoped version of the task rather than the full prompt, and can be held to subtask-specific quality bars instead of one shared generic bar.

**Planning mode** output flows into **backend state**, toggling tool availability. During coordination rounds, agents describe what they would do rather than doing it. Only the winning agent gets tools restored for final execution. This means agents compete on plans, not partially-executed actions.

### How Primitives Differ from Main Coordination Turns

Main coordination turns involve N agents iterating over rounds, seeing each other's work, voting via checklist gates, and converging. The subagent primitives are different:

- They run **before** the main loop, not as part of it.
- They spawn a **separate MassGen execution** with stripped-down config (no filesystem tools, no MCP).
- Their output is **structured data** (personas, criteria, subtask maps) consumed by the orchestrator, not free-form answers.
- They do not participate in the voting/convergence loop — they produce their output and exit.

This distinction matters for composition: a subagent primitive produces context that shapes all subsequent rounds, but it cannot be refined by those rounds. If you want iterative refinement of personas themselves, you need to compose multiple phases (see [Composition Patterns](#composition-patterns)).

## Why Composition Matters

No single primitive is sufficient for high-quality output. Consider the quality matrix:

```
                    Without refinement          With refinement
                    ─────────────────           ───────────────
Without personas    Generic first drafts        Polished mediocrity
With personas       Ambitious but rough         Distinctive, mature work
```

Now extend this to the full primitive set:

- **Personas alone** → diverse perspectives, but agents may not know what "good" looks like for this task.
- **Eval criteria alone** → agents know quality gates, but all approach the task identically.
- **Personas + eval criteria** → diverse approaches held to task-specific quality standards.
- **Personas + eval criteria + decomposition** → specialized agents with quality gates on their owned subtasks.
- **Planning + personas + eval criteria + execution** → agents with strong perspectives debate the best plan, the plan is held to rigorous criteria, then the winning plan is executed with fresh personas optimized for implementation.

The power grows combinatorially. And because subagent primitives are themselves MassGen executions, you can apply the quality matrix to them too:

- Generate personas using **multiple agents with iterative refinement** — N agents debating what the best personas would be.
- Generate evaluation criteria with **personas already injected** — so each evaluator brings a different quality philosophy.
- Decompose tasks with **multiple agents voting** on the best decomposition strategy.

## Composition Patterns

### Pattern 1: Quality-Gated Planning → Chunked Execution

The most immediately powerful composition. Multiple agents with strong personas debate a plan. The plan must pass task-specific evaluation criteria before execution begins. Then the winning plan is executed in chunks — each chunk potentially with its own personas, decomposition strategy, or evaluation criteria.

```
Phase 1: Plan generation
  ├── Persona generation (diverse planning perspectives)
  ├── Eval criteria generation (what makes a good plan?)
  └── N agents × M rounds → winning plan
       ↓ plan output

Phase 2: Chunk execution (per plan section)
  ├── Persona generation (implementation-focused, per chunk)
  ├── Eval criteria generation (what makes good execution of THIS chunk?)
  └── N agents × M rounds → executed chunk
       ↓ chunk output

  Some chunks may use decomposition instead of parallel:
  ├── Chunk A: parallel mode, creative personas, creative eval criteria
  ├── Chunk B: decomposition mode, specialist subtask owners
  └── Chunk C: parallel mode, analytical personas, correctness eval criteria
```

### Pattern 2: Decomposition with Per-Subtask Quality Gates

Different subtasks need different quality standards. A creative writing subtask needs different evaluation criteria than a data analysis subtask. A decomposition primitive assigns ownership, and can now emit per-agent execution criteria alongside each subtask. When it does not, runtime fallback criteria still adapt to the owned subtask so checklist-gated stopping stays role-specific instead of collapsing back to one shared rubric.

```
Phase 1: Task decomposition
  ├── Persona generation (architectural perspectives)
  └── N agents vote on decomposition
       ↓ subtask map

Phase 2: Per-subtask execution (each a separate coordination)
  ├── Subtask A: parallel mode, creative personas, creative eval criteria
  ├── Subtask B: parallel mode, analytical personas, correctness eval criteria
  └── Subtask C: single agent, deep specialist persona, domain eval criteria
       ↓ per-subtask outputs

Phase 3: Synthesis
  ├── Integration personas (cross-domain connectors)
  ├── Synthesis eval criteria (coherence, consistency, completeness)
  └── Combine subtask outputs into unified result
```

### Pattern 3: Recursive Refinement of Primitives

Use MassGen to improve MassGen's own preparation. Generate rough personas, use them to generate better evaluation criteria, then use those criteria to evaluate and regenerate the personas.

```
Phase 1: Bootstrap → rough personas
Phase 2: Rough personas → eval criteria for personas
Phase 3: Eval criteria → refined personas (iterative refinement)
Phase 4: Refined personas + task-specific eval criteria → main execution
```

### Pattern 4: Analysis → Synthesis

For complex analytical tasks, decompose into parallel analysis tracks with methodology-specific personas, then synthesize across dimensions.

```
Phase 1: Decompose into analysis dimensions
Phase 2: Per-dimension parallel analysis (methodology personas per dimension)
Phase 3: Cross-dimension synthesis (integration personas, synthesis eval criteria)
```

### Pattern 5: Ensemble (Produce → Vote → Synthesize)

For tasks where independent diversity matters more than iterative refinement. Each agent produces their best answer in isolation, then agents vote, and the winner synthesizes insights from all others.

```
Phase 1: Independent parallel production (disable_injection: true)
Phase 2: Vote on best answer (defer_voting_until_all_answered: true)
Phase 3: Winner synthesizes from all (final_answer_strategy: synthesize)
```

This is the default pattern for multi-agent subagent runs. It maximizes answer diversity by preventing agents from anchoring on each other's work, while still producing a high-quality synthesized final answer.

See ``docs/source/reference/yaml_schema.rst`` and ``configs/voting/ensemble_mode.yaml`` for configuration details.

## Checklist Gate Criteria for Special Primitives

The default checklist items (E1-E4) are designed for general task output. But special primitives — persona generation, task decomposition, evaluation criteria generation, and analytical tasks like prompt crafting or log analysis — have well-defined quality characteristics that don't require another level of prompt generation to specify.

These are the recommended default criteria for each primitive type. When a primitive runs as a standalone coordination, these criteria should replace the generic E1-E4.

### Persona Generation

What makes personas good is well-specified: they must be distinct, actionable, and task-relevant.

| ID | Criterion | Category |
|----|-----------|----------|
| E1 | Each persona articulates a clear, specific perspective that would lead to meaningfully different outputs — not just surface variation in tone or vocabulary. Two personas that would produce essentially the same answer are a failure. | core |
| E2 | Personas are grounded in the actual task. Each perspective is relevant to the problem domain and brings a genuinely useful lens, not an arbitrary or forced viewpoint. | core |
| E3 | Personas are actionable instructions, not character descriptions. An agent receiving this persona knows exactly how it changes their approach, priorities, and decision-making — not just who they are pretending to be. | core |
| E4 | The persona set collectively provides coverage — the major reasonable approaches, value trade-offs, or methodological choices for this task are represented. No critical perspective is missing. | core |
| E5 | Personas are vivid enough to resist homogenization under peer pressure. The perspective is strongly stated so that even after seeing other agents' answers, the core viewpoint remains distinguishable. | stretch |

### Task Decomposition

Good decomposition must produce subtasks that are independently executable, collectively exhaustive, and appropriately scoped.

| ID | Criterion | Category |
|----|-----------|----------|
| E1 | Subtasks are collectively exhaustive — completing all subtasks fully produces the complete output. No significant aspect of the original task falls through the cracks between subtasks. | core |
| E2 | Subtasks have minimal coupling — each can be executed independently without requiring intermediate results from other subtasks. Where dependencies exist, they are explicit and the dependency order is specified. | core |
| E3 | Subtask scoping is balanced — no single subtask is trivial while another carries the bulk of the complexity. Work is distributed so each agent has a meaningful, roughly comparable contribution. | core |
| E4 | Each subtask description is self-contained and specific enough that an agent can execute it without needing to infer intent from other subtasks or the original prompt. | core |
| E5 | The decomposition strategy is appropriate for the task type — creative tasks split along conceptual boundaries, technical tasks along component boundaries, analytical tasks along dimension boundaries. | stretch |

### Evaluation Criteria Generation

Meta-quality: the criteria that judge quality must themselves be high quality.

| ID | Criterion | Category |
|----|-----------|----------|
| E1 | Each criterion is specific to the actual task — not generic advice that applies to any output. A criterion that could be copy-pasted to an unrelated task is too vague. | core |
| E2 | Criteria are evaluable — an agent can determine pass/fail by examining the output, not by making subjective judgments about intent. "Addresses edge cases" is vague; "handles empty input, null values, and boundary conditions" is evaluable. | core |
| E3 | The criteria set distinguishes excellent work from adequate work. If every competent first draft would pass all criteria, the bar is too low. At least one criterion should require genuine effort to satisfy. | core |
| E4 | Core vs. stretch categorization is correct. Core criteria represent non-negotiable requirements; stretch criteria represent quality differentiators. A misclassified core criterion blocks good work; a misclassified stretch criterion lets mediocre work pass. | core |
| E5 | Criteria do not conflict with each other or create impossible trade-offs. Meeting one criterion should not require violating another. Where genuine tensions exist, the criteria acknowledge the trade-off explicitly. | stretch |

### Prompt / Brief Crafting

When using MassGen to generate prompts, system messages, briefs, or instructions for downstream use.

| ID | Criterion | Category |
|----|-----------|----------|
| E1 | The prompt achieves its functional goal — an agent receiving this prompt would produce the intended type of output without additional clarification. Test: could you hand this to a capable model cold and get back what you need? | core |
| E2 | The prompt is appropriately scoped — it constrains enough to prevent unhelpful outputs but does not over-constrain in ways that eliminate valid approaches. | core |
| E3 | Important requirements are explicit, not implied. The prompt does not depend on shared context, cultural assumptions, or "obvious" intentions that a model might miss. | core |
| E4 | The prompt is structured for parseability — key instructions are prominent, not buried in paragraphs. An agent skimming the prompt would still catch the critical constraints. | stretch |
| E5 | The prompt anticipates likely failure modes for its task type and includes guardrails against them (e.g., "do not summarize when asked to analyze" or "include concrete examples, not abstract principles"). | stretch |

### Log / Output Analysis

When using MassGen to analyze logs, execution traces, performance data, or prior MassGen outputs.

| ID | Criterion | Category |
|----|-----------|----------|
| E1 | The analysis identifies concrete, specific findings — not vague observations. Each finding points to a specific location, pattern, or data point in the source material. | core |
| E2 | Findings are supported by evidence from the actual data, not inferred from assumptions about what "usually" happens. Claims include references to specific log entries, metrics, or examples. | core |
| E3 | The analysis distinguishes symptoms from root causes. Surface-level observations (e.g., "agent 2 was slow") are traced to underlying explanations (e.g., "agent 2 hit rate limits due to tool call volume"). | core |
| E4 | Actionable recommendations follow from findings. Each significant finding includes a concrete suggestion for what to change, not just a description of what went wrong. | core |
| E5 | The analysis identifies patterns across the dataset, not just individual anomalies. Recurring behaviors, systematic biases, or structural issues are surfaced alongside one-off events. | stretch |

## Current Execution Order

Today, primitives execute in this fixed sequence:

```
In chat() — before coordination:
  1. Planning mode analysis (if enabled)
     → Reuses an existing agent inline
     → Sets tool constraints on all agent backends
     → Output: backend.set_planning_mode() flags

In _coordinate_agents() — at coordination start:
  2. Persona generation  ⎤  Subagent spawns
                         ⎥  (concurrent if both enabled)
  3. Eval criteria gen   ⎦  Output stored in orchestrator state

  4. Task decomposition (decomposition mode only)
     → Subagent spawn, runs after personas/criteria
     → Output: self._agent_subtasks dict

  5. Main round loop begins
     Per round, per agent:
       → Persona text prepended to system message
       → Eval criteria passed as checklist items + system message section
       → Subtask (if decomposition) wraps user message
       → Planning mode constrains available tools
```

## Future: Explicit Phase Composition

The current implementation hard-codes the ordering and each primitive runs as a single subagent spawn without iterative refinement. The vision is explicit phase composition where users define ordered phases, each phase being a full MassGen coordination (with its own agents, rounds, primitives, and checklist gates):

```yaml
# Conceptual — not yet implemented
phases:
  - name: persona_generation
    coordination:
      agents: 3
      max_rounds: 2
      checklist_criteria: persona  # uses persona-specific gates from above
    output_type: personas
    feeds_into: [plan, execute]    # which phases consume this output

  - name: plan
    coordination:
      agents: 5
      max_rounds: 4
      persona_generator:
        enabled: true             # personas for the planners themselves
      checklist_criteria: prompt  # plan judged as a brief/prompt
    output_type: plan
    feeds_into: [execute]

  - name: execute
    coordination:
      agents: 3
      max_rounds: 6
      personas: $phases.persona_generation.output
      evaluation_criteria_generator:
        enabled: true
      checklist_criteria: auto
    input: $phases.plan.output
```

Each phase is a full coordination with its own quality gates. The output of one phase feeds specific injection points in the next. This is where the combinatorial power lives — and finding the right compositions for different task types is one of MassGen's most important ongoing research directions.

The space is vast: different personas for planning vs. execution, different evaluation criteria per plan chunk, decomposition within one phase but parallel in another, recursive refinement of the primitives themselves. The primitives are simple; the compositions are where the magic happens.
