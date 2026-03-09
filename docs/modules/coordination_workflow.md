# Coordination Workflow: End-to-End Lifecycle

This is the canonical backend workflow for MassGen coordination. It explains how orchestration actually works in code across:

- turn startup and pre-coordination checks
- per-agent execution rounds and workflow-tool enforcement
- answer/vote/stop semantics
- restart and injection delivery across backend hook paths
- fairness, timeout, and answer-limit gates
- final presentation, post-evaluation, and restart attempts

MassGen is asynchronous: agents are not lockstep-synchronized and can sit in different local rounds at the same time.

## Backend Module Map

| Module | Responsibility in this workflow |
|---|---|
| `massgen/orchestrator.py` | Primary control loop and policy enforcement |
| `massgen/chat_agent.py` | Per-agent chat streaming surface over provider backends |
| `massgen/coordination_tracker.py` | Source of truth for answer labels, rounds, votes, restart events, status snapshots |
| `massgen/backend/*` | Provider/runtime integration (tool transport, hooks, streaming chunks, MCP/custom tool execution) |
| `massgen/mcp_tools/hooks.py` | Injection, reminder, and per-round timeout hook primitives |
| `massgen/mcp_tools/checklist_tools_server.py` | Checklist policy tooling (`submit_checklist`, `propose_improvements`) |

## Key Entry Points

- `Orchestrator.chat()` is the turn entrypoint.
- `Orchestrator._coordinate_agents_with_timeout()` wraps coordination with orchestrator timeout.
- `Orchestrator._coordinate_agents()` runs pre-coordination preparation.
- `Orchestrator._stream_coordination_with_agents()` runs the parallel coordination loop.
- `Orchestrator._stream_agent_execution()` executes one agent round with retries/enforcement.
- `Orchestrator._present_final_answer()` and `get_final_presentation()` run final synthesis/presentation.

## Concrete Walkthrough: "Create a website about the Beatles."

Use this as a mental model for how one real turn flows:

1. `Orchestrator.chat()` receives the prompt, builds context, resets turn state, and prepares workflow tools.
2. `_stream_coordination_with_agents()` starts three agents in parallel.
3. In round 1, each agent works independently on a different angle:
   - agent 1 drafts visual layout and page structure
   - agent 2 drafts Beatles content architecture and copy
   - agent 3 drafts accessibility/performance constraints
4. Suppose agent 2 submits `new_answer` first (`agent2.1`):
   - tracker records the answer label
   - terminal flags are reset for re-evaluation
   - peers are marked `restart_pending` when injection is enabled
5. Agents continue in `_stream_agent_execution()` with the binary branch:
   - iterate branch: submit another `new_answer`
   - terminal branch: submit `vote` (or `stop` in decomposition mode)
6. Optional checklist-gated mode:
   - agent runs `submit_checklist`
   - if gaps exist, it may call `propose_improvements` and then `new_answer`
   - in voting mode, accepted terminal verdicts move to `vote`
   - in decomposition mode, accepted terminal verdicts move to `stop`, and the checklist scores the agent's current subtask work rather than ranking all peers as competing final answers
   - when decomposition provides per-agent execution criteria, those criteria are routed to that agent's prompt and checklist tool state; otherwise runtime decomposition defaults are synthesized from the owned subtask
   - when `coordination.round_evaluator_before_checklist: true`, the parent is
     guided to run one blocking `round_evaluator` subagent before round 2+ and
     then use that packet as the diagnostic basis for `submit_checklist` /
     `propose_improvements`
   - when `coordination.orchestrator_managed_round_evaluator: true` is also
     enabled, the orchestrator owns that launch instead
7. Restart and/or mid-stream injection delivers fresh peer updates.
8. Agents keep iterating until all active agents are terminal (`has_voted=True` or stop path).
9. Finalization selects the winner, runs presenter synthesis, and writes final artifacts/snapshots.

See `docs/source/user_guide/coordination_scrollytelling.rst` for an interactive scroll version of this same flow.

## User-Facing View (ASCII)

```text
                           USER REQUEST
                                │
                                ▼
          ┌────────────────────────────────────────────┐
          │         PRE-COLLABORATION CHECKS           │
          │ - context/history setup                    │
          │ - workspace + tools/hook wiring            │
          │ - optional planning safety analysis         │
          │ - optional personas/criteria/decomposition │
          └─────────────────────┬──────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │      ORCHESTRATOR      │
                    │ (traffic + decisions)  │
                    └───────┬────────┬───────┘
                            │        │
                 sends context+tools  │ receives workflow tool results
                            │         │ (new_answer/vote/stop)
                            ▼         ▲
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│   AGENT A     │       │   AGENT B     │       │   AGENT C     │
│ think + tools │       │ think + tools │       │ think + tools │
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        ├────────── new_answer ─┼───────────────────────┤
        │                       │                       │
        │     shared updates / injections to peers      │
        │   (after first-answer diversity protection)   │
        │                       │                       │
        └─────────────── keep refining in parallel ─────┘
                                │
                   eventually each agent does vote/stop
                                │
                                ▼
                    ┌────────────────────────┐
                    │  consensus / selection │
                    │ (winner or presenter)  │
                    └───────────┬────────────┘
                                │
                                ▼
                         FINAL PRESENTATION
```

## Detailed System Flow (ASCII)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ TURN START: chat()                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Build conversation context (current message + history)
        ├─ Validate user message exists (else error/exit)
        ├─ Optional DSPy paraphrase generation per agent
        ├─ Reset turn-scoped state:
        │    restart flags, fairness logs, runtime injection history,
        │    context-path write tracking, multi-turn workspace clearing rules
        ├─ Optional planning-mode irreversibility analysis:
        │    set planning mode + blocked tools on each backend
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ATTEMPT WRAPPER: _coordinate_agents_with_timeout()                          │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Reset attempt timers/state
        ├─ Apply orchestrator-level timeout guard
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ PRE-COORD PREP: _coordinate_agents()                                        │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Optional write-mode orphan branch cleanup
        ├─ Optional persona generation
        ├─ Optional evaluation-criteria generation
        ├─ Optional task auto-decomposition (decomposition mode)
        ├─ Optional debug bypass: skip_coordination_rounds -> presentation
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ MAIN LOOP: _stream_coordination_with_agents()                               │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Optional resume path: restore from previous log (resume_from_log)
        │
        ├─ Completion gate:
        │    all agents terminal? (has_voted / stopped)
        │    OR skip_voting mode with all agents answered?
        │
        ├─ Global guards:
        │    cancellation? orchestrator timeout?
        │
        ├─ For each agent, pre-start gates:
        │    - defer_voting_until_all_answered waiting gate
        │    - decomposition auto-stop gate
        │    - fairness pre-start pause gate
        │    - startup rate limit
        │    - if eligible: spawn _stream_agent_execution(agent)
        │
        ├─ Consume parallel stream chunks:
        │    content / reasoning / tool status / result / done / error
        │
        ├─ If result = answer:
        │    save snapshot + tracker update
        │    reset all terminal decisions for re-evaluation
        │    if injection enabled: restart_pending=True set across agents
        │
        ├─ If result = vote or stop:
        │    apply terminal fairness checks
        │    allow stale-restart exceptions (single-agent/no-unseen/hard-timeout)
        │    record terminal decision
        │
        ├─ If external client tool call surfaced:
        │    emit tool_calls chunk and stop MassGen coordination loop
        │
        └─ Repeat until completion gate passes
        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ FINALIZATION                                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
        │
        ├─ Select presenter:
        │    voting mode -> vote winner
        │    decomposition mode -> configured presenter (or fallback)
        ├─ Optional memory merge into presenter workspace
        └─ Final presentation + optional post-evaluation/restart decision
```

## Core State Model

### AgentState (`orchestrator.py`)

Per-agent runtime state includes:

- `answer`, `has_voted`, `votes`
- `restart_pending`, `restart_count`, `is_killed`
- `known_answer_ids`, `seen_answer_counts`
- `decomposition_answer_streak` (consecutive local revisions without seeing external updates)
- round timeout fields (`round_start_time`, `round_timeout_hooks`, `round_timeout_state`)
- checklist counters (`answer_count`, `checklist_calls_this_round`, `checklist_history`)

### CoordinationTracker (`coordination_tracker.py`)

Tracker is the coordination ledger:

- versioned answer labels (`agentN.M`) and final labels (`agentN.final`)
- per-agent round counters (`agent_rounds`) and context labels seen per agent
- votes with voter-context label resolution (prevents race-condition mislabeling)
- restart events (`RESTART_TRIGGERED` / `RESTART_COMPLETED`)
- event timeline and status snapshots used by UI/automation

## Pre-Coordination Checks

### A. Orchestrator initialization checks (once per orchestrator instance)

- per-agent workspace/snapshot/orchestration path setup
- optional skills validation and setup
- optional planning and subagent tool injection
- optional NLIP and broadcast initialization
- optional checklist tool registration when `voting_sensitivity: checklist_gated`

### B. Turn-start checks (every user turn)

- user message presence
- conversation context and history assembly
- optional paraphrase generation
- coordination tracker re-initialization for the turn
- restart/fairness/runtime-injection state reset
- context write-tracking reset
- optional planning-mode irreversibility analysis and tool blocking setup

### C. Coordination-iteration checks (inside the parallel loop)

- completion gate (all terminal, or `skip_voting` all-answered)
- cancellation and orchestrator-timeout guards
- per-agent spawn gates:
  - waiting-for-all-answers gate
  - decomposition auto-stop gate
  - fairness pre-start pause gate
  - startup rate-limit gate

## Per-Agent Round Engine (ASCII)

```text
_stream_agent_execution(agent_i)
    │
    ├─ Round setup
    │   - reset per-round timeout counters/hooks
    │   - copy latest snapshots to temp workspace
    │   - build system+user context (persona, criteria, planning mode, mappings)
    │   - setup delivery path (general hooks / native hooks / MCP hook file IPC)
    │   - choose tools for this round (normal or vote-only)
    │
    ├─ Retry/enforcement loop (max attempts)
    │   │
    │   ├─ Restart/injection checkpoint
    │   │   - if restart_pending and no first answer: defer (first-answer protection)
    │   │   - vote-only mode + pending updates: force restart (to refresh vote enum)
    │   │   - hookless backend: fallback to enforcement-message injection or restart
    │   │
    │   ├─ Stream backend response (+ tools)
    │   │
    │   ├─ Enforcement checks
    │   │   - unavailable workflow tools for this round
    │   │   - mixed vote + new_answer in same response
    │   │   - vote/stop fairness gate
    │   │   - new_answer limits, novelty, duplicate constraints
    │   │
    │   └─ Exit on valid workflow result
    │       new_answer -> ("result","answer")
    │       vote/stop  -> ("result","vote")  # stop shares terminal pipeline
    │
    └─ finally: telemetry, span closure, round cleanup, context clear
```

## First-Answer Diversity Protection

First answers are protected by design:

- if an agent has not produced a first answer yet, peer-answer restart/injection is deferred
- this avoids premature convergence and preserves independent initial exploration
- protection applies across all peer-answer delivery paths (hook injection, native hook, MCP hook, and hookless fallback)

Internal round numbering starts at `0`; many UIs show this as "Round 1".

## Submission Semantics

Workflow tools are the coordination contract:

- `new_answer` = iterative submission
- `vote` = terminal submission in voting mode
- `stop` = terminal submission in decomposition mode

When `new_answer` is accepted:

- answer revision is added to tracker with a new label (`agentN.M`)
- all terminal decisions are reset (`has_voted`, vote payloads, stop metadata)
- if `disable_injection: false`, restart signaling is broadcast so others can observe updates

When `vote`/`stop` is accepted:

- terminal decision is recorded in tracker
- `has_voted=True` marks that agent terminal for completion gating
- decomposition `stop` stores stop summary/status and uses stop-specific tracker events

### Binary Decision Framework (Explicit)

Each agent turn must end in exactly one of two branches:

- iterate branch: submit `new_answer`
- terminal branch: submit `vote` (or `stop` in decomposition mode)

The orchestrator enforces this as a hard invariant:

- mixed `vote` + `new_answer` in one response is rejected and retried
- missing workflow decision after tool/text output is rejected and retried
- after max retries, the agent turn fails

## Injection and Restart Delivery

When new peer work exists, delivery path is selected by backend capability:

| Backend capability | Delivery path |
|---|---|
| `set_general_hook_manager` | General hook manager (`MidStreamInjectionHook`) |
| `supports_native_hooks()` | Native backend hook adapter (Claude Code path) |
| `supports_mcp_server_hooks()` | MCP server-level hook file IPC (Codex path) |
| none of the above | Defensive hookless fallback via enforcement-message injection/restart |

### Delivery rules

- First-answer protection can defer peer update delivery.
- `vote-only` mode forces restart instead of mid-stream injection so vote options/tool schema refresh correctly.
- If near soft timeout (`_should_skip_injection_due_to_timeout`), injection is skipped and restart is deferred.
- `max_midstream_injections_per_round` caps unseen-update fanout per round.
- `defer_peer_updates_until_restart: true` queues peer answer updates for the next restart instead of delivering them mid-stream.
- In checklist mode, `allow_midstream_peer_updates_before_checklist_submit: true` keeps mid-stream peer updates enabled until the first accepted `submit_checklist` for the current answer.
- `disable_injection: true` bypasses peer-answer propagation (independent refinement mode).

Non-peer runtime payloads can also inject:

- runtime human input
- background subagent completions
- background tool completions
- timeout warning messages

## Workspace and Snapshot Lifecycle

Each agent has three storage locations:

- **workspace**: active working directory
- **snapshot_storage**: latest delivered workspace snapshot used for peer visibility
- **log directory**: timestamped append-only archival data

### Normal answer submission

On `new_answer`, `_save_agent_snapshot(answer_content=...)`:

- writes answer text (and optional changedoc/context) to timestamped log directory
- writes execution trace
- saves workspace snapshot (overwrites snapshot_storage)
- clears workspace after save (unless deferred by round-isolation cleanup)

### Vote/stop submission

On vote/stop, `_save_agent_snapshot(vote_data=...)`:

- writes vote JSON and context
- intentionally skips workspace snapshot so deliverable files from last answer remain preserved

### Interrupted and early termination saves

Two distinct save paths exist:

1. `_save_partial_snapshots_for_early_termination()`:
   - used in no-answer finalization paths
   - calls `_save_agent_snapshot(answer_content=None, vote_data=None)`
   - this uses `save_snapshot(... preserve_existing_snapshot=True)`

2. `_save_partial_execution_traces_for_interrupted_turn()`:
   - best-effort interrupted-session flush (used by partial result capture)
   - preserves existing `snapshot_storage` if it already has meaningful content
   - writes execution traces and optional workspace copy without overwriting good submitted snapshots

### Snapshot preservation invariant

For interrupted/partial saves, submitted snapshots are never overwritten by incomplete in-flight workspace content.

| `snapshot_storage` | workspace | Action |
|---|---|---|
| Has meaningful content | Any | Preserve existing snapshot |
| Empty | Has meaningful content | Copy workspace to snapshot_storage |
| Empty | Empty | Skip |

## Fairness and Pacing

Fairness controls coordination pace and stale terminal decisions:

- `fairness_lead_cap_answers`: max revision lead over slowest active peer
- pre-start fairness pause: prevents expensive rounds that would fail fairness anyway
- terminal fairness gate: blocks `vote`/`stop` until latest unseen updates are observed
- `max_midstream_injections_per_round`: caps unseen-source mid-stream fanout

Important exceptions:

- first answer is never blocked by fairness lead gating
- hard timeout is a fairness cutoff that allows terminal progress to avoid deadlock

## Timeouts and Retry Enforcement

Per-round timeout hooks (registered via hook layer):

- soft timeout: injects wrap-up guidance
- hard timeout: blocks non-terminal tools after grace period
- repeated denied tool calls after hard timeout can force agent turn termination

Enforcement loop behavior:

- invalid/missing workflow usage triggers bounded retries with structured tool-error messages
- mixed or unavailable workflow tools are rejected and retried
- after max attempts, agent turn fails with error result

## Checklist Policy Layer (Optional)

Checklist mode is policy, not the core coordination primitive:

- enabled with `voting_sensitivity: checklist_gated`
- default behavior blocks checklist before first answer unless `checklist_first_answer: true`
- when `defer_peer_updates_until_restart: true`, peer updates wait for restart unless `allow_midstream_peer_updates_before_checklist_submit` keeps the pre-submit window open
- common flow:
  1. implement + verify
  2. if `round_evaluator_before_checklist: true` and this is round 2+, launch one blocking `round_evaluator` before checklist submission
  3. if the evaluator returns valid structured `next_tasks`, those tasks are auto-injected into the parent plan
  4. in that task-driven branch, the parent uses `get_task_plan` as the source of truth, may open the evaluator artifact paths for rationale, and does not call `submit_checklist` or `propose_improvements`
  5. in that task-driven branch, the parent implements, verifies, and submits via `new_answer` directly; for pure text artifacts, the final artifact body goes straight into `new_answer.content`
  6. if structured `next_tasks` are missing or invalid, the parent uses the returned critique/spec packet as the diagnostic basis for checklist submission
  7. in that fallback branch, the parent saves or copies that packet into its workspace as the diagnostic report and calls `submit_checklist`
  8. if checklist returns `status=validation_error`, fix payload/report and call `submit_checklist` again
  9. if accepted iterate verdict, call `propose_improvements`
  10. implement plan (use `improvement_spec` from the evaluator packet as richer guidance when present)
  11. write/update `memory/short_term/verification_latest.md` with replayable verification steps/artifacts
  12. submit via `new_answer` (or terminal action)
- round evaluator contract notes:
  - returns a packet with `criteria_interpretation`, `criterion_findings`, `cross_answer_synthesis`, `preserve`, `improvement_spec`, `verification_plan`, and `evidence_gaps`
  - the packet is critique/spec guidance only, not a checklist payload or terminal recommendation
  - the inline `verdict_block` is intentionally minimal and carries verdict metadata (`verdict` + `scores`) rather than the full task handoff
  - `next_tasks.json` is the authoritative machine-readable task handoff on the normal path
  - tasks in `next_tasks.json` use canonical `execution` metadata:
    - `execution.mode: "inline"` means the parent agent executes the task itself
    - `execution.mode: "delegate"` means the task is a good subagent target when the parent can delegate to a matching specialized subagent
    - the evaluator should base delegation hints on the parent-facing `PARENT DELEGATION OPTIONS` context, not on whether the evaluator child run itself can spawn subagents
    - if the task brief says no parent-specialized subagents are available, task handoff stays inline-only and should not offer delegate execution hints
  - the round evaluator never calls `submit_checklist`, `propose_improvements`, or `vote` itself
  - when valid structured `next_tasks` are present, the evaluator result header points to exact `critique_packet.md` and `next_tasks.json` paths and the parent treats those files as reference-only, not something to rewrite into a second report
  - the parent should not run a second full self-evaluation pass after delegation; only close explicit `evidence_gaps` if grounded checklist submission still needs more facts
  - generated child YAML for `round_evaluator` always mounts the shared temp-workspace root read-only
  - `refine=false` keeps the evaluator child checklist-free; `refine=true` may inherit the parent checklist gate
  - checklist-enabled `round_evaluator` child runs use a dedicated default criteria preset for evaluator-packet quality when no child-specific criteria are configured
- checklist result contract:
  - accepted path: `status=accepted` + `verdict`
  - invalid path: `status=validation_error`, `requires_resubmission=true`, no `verdict`
- scoring scope:
  - voting mode: when multiple answers are in context, `submit_checklist` expects per-agent scores across the candidate answers
  - decomposition mode: `submit_checklist` evaluates the agent's current owned work against the latest peer context, using flat criterion scores for that current work
- `propose_improvements` is only valid after the latest accepted iterate checklist result
- after injection updates arrive post-checklist, one bounded recheck is allowed:
  - preferred: score only newly injected labels (delta recheck)
  - also allowed: score all latest context labels

Verification replay notes:

- in memory-enabled runs, task planning auto-appends a terminal `write_verification_memo` task
- replay memories are auto-injected in a dedicated prompt section (`Verification Replay Memories (Auto-Injected)`)
- replay memos should include environment context, exact verification commands/scripts, exhaustive artifact paths, and freshness notes
- absolute artifact paths are normalized to current `temp_workspaces/<agent_token>/...` paths during injection

`max_checklist_calls_per_round` prevents in-round checklist loops, with an exception for post-injection rechecks when newer labels are pending.

Checklist state is backend-bound (`backend._checklist_state`) and refreshed per round/injection so answer labels and remaining budgets stay consistent.

## Limits and Mode-Specific Outcomes

Limit gates:

- `max_new_answers_per_agent`
- `max_new_answers_global`

Mode behavior:

- voting mode:
  - hitting limits moves agent to vote-only behavior (when allowed)
- decomposition mode:
  - per-agent limit is treated as a consecutive streak limit
  - streak resets when agent observes unseen external updates
  - hit limits auto-stop the agent instead of vote-only mode

`defer_voting_until_all_answered` can keep capped agents waiting until all peers have at least one answer (unless global cap is already reached).

## Completion and Final Answer Path

Coordination completes when all active agents are terminal (`has_voted=True`, including stop paths).

Then:

1. Presenter selected (vote winner or configured decomposition presenter).
2. `get_final_presentation()` starts final round and builds presenter context.
3. Presenter runs with final-presentation instructions and `new_answer`-only workflow tool.
4. Final snapshot is saved (`final/<agent>/...`) and final answer is tracked.
5. Optional post-evaluation may trigger orchestration restart attempts (bounded by `max_orchestration_restarts`).
6. Optional write-isolation review applies approved file changes.
7. Workflow ends with final `done`.

`skip_final_presentation` can short-circuit the extra presentation LLM call in compatible modes while still snapshotting and recording final output.

## External Tool Passthrough Behavior

Client-provided tools are passed to backends but never executed by MassGen itself.

- if a model emits an external client tool call, orchestrator surfaces a `tool_calls` chunk to caller
- MassGen coordination loop then exits so caller can execute tool and continue externally

This keeps ownership boundaries clear between MassGen workflow tools and caller-managed tools.

## Observability and Artifacts

Important runtime artifacts for technical debugging:

- `status.json`: continuously updated tracker snapshot
- per-agent timestamped logs: answer/vote/context/trace/workspace artifacts
- `final/` artifacts for winning presenter output
- tracker event history (iterations, labels, votes, restarts, finalization)
- round-level usage and tool metrics when backend exposes them

## Practical Notes

- internal round numbers start at `0`
- agents reason over anonymous labels (`agent1.1`, etc.), not real backend IDs
- tracker context labels are the source of truth for vote label resolution
- when `disable_injection: true`, agents refine independently without peer propagation

## Config Quick Reference

```yaml
orchestrator:
  coordination_mode: voting                 # or decomposition
  voting_sensitivity: balanced              # or checklist_gated
  disable_injection: false                  # true = independent refinement
  fairness_enabled: true
  fairness_lead_cap_answers: 2
  max_midstream_injections_per_round: 2
  defer_peer_updates_until_restart: false
  allow_midstream_peer_updates_before_checklist_submit: null
  max_new_answers_per_agent: 2              # null = unlimited
  max_new_answers_global: 8                 # null = unlimited
  defer_voting_until_all_answered: false
  max_checklist_calls_per_round: 1
  checklist_first_answer: false
```

## Self-Improvement and Evaluator Rescue Cycle

MassGen agents self-improve iteratively within each round, then submit their best answer. This cycle is by design — agents should push themselves to plateau before asking for external feedback. The round evaluator exists to rescue agents from plateaus they cannot break through alone.

### The plateau problem

Agents get stuck in two distinct ways:

1. **Blind spots**: The agent cannot identify remaining problems. It believes its answer is strong, but hidden requirement misses, verification gaps, or ambition ceilings persist. The agent's self-evaluation converges prematurely.

2. **Implementation ceiling**: The agent can identify problems (via checklist, self-critique, or prior evaluator feedback) but fails to fix them. It sees the gap, attempts a fix, and the fix either doesn't land or creates new problems. The agent loops without progress.

### Evaluator as rescue, not just critic

The round evaluator addresses both failure modes:

- **For blind spots**: Fresh-eyes critique with cross-answer synthesis reveals weaknesses the agent cannot see in its own work. Multiple evaluator agents with different strengths (code analysis, visual inspection, domain expertise) catch different blind spots.

- **For implementation ceilings**: This is where the evaluator's `implementation_guidance` field in `next_tasks.json` is critical. High-level task descriptions ("fix the animation") are not enough when the agent already tried and failed. The evaluator must provide concrete HOW-to specs: specific techniques, code patterns, step-by-step approaches, and — crucially — a diagnosis of why the agent's previous approach likely failed.

### The escalation pattern

```text
Agent self-improves (checklist, self-critique, tool use)
    │
    ├─ Makes progress → continues iterating
    │
    └─ Plateaus (can't improve further) → submits new_answer
                                              │
                                              ▼
                                    Round evaluator runs
                                    (fresh critique + implementation specs)
                                              │
                                              ▼
                                    Agent receives:
                                    - What's still wrong (blind spot rescue)
                                    - HOW to fix it (implementation rescue)
                                    - What NOT to break (preserve list)
                                              │
                                              ▼
                                    Agent tries fundamentally different approach
                                              │
                                    Repeat until quality bar met or plateau acknowledged
```

### When to accept a plateau

Not every criterion can be driven to 10/10. If evaluator scores remain flat across 3+ rounds despite genuinely different `implementation_guidance` each time, the criterion may be at the limit of what the current agent configuration can achieve. The evaluator should acknowledge this explicitly in its critique rather than prescribing yet another approach — this signal lets the orchestrator make informed convergence decisions rather than burning rounds on diminishing returns.

## Related Docs

- `docs/modules/architecture.md` - core system architecture and backend hierarchy
- `docs/modules/injection.md` - hook and injection internals
- `docs/modules/composition.md` - personas/criteria/decomposition composition
- `docs/source/reference/yaml_schema.rst` - orchestration and fairness config reference
