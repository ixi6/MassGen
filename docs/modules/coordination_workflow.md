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
   - if quality gates pass, it can move to `vote`
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
- common flow:
  1. implement + verify
  2. call `submit_checklist`
  3. if iterate verdict, call `propose_improvements`
  4. implement plan
  5. write/update `memory/short_term/verification_latest.md` with replayable verification steps/artifacts
  6. submit via `new_answer` (or terminal action)

Verification replay notes:

- in memory-enabled runs, task planning auto-appends a terminal `write_verification_memo` task
- replay memories are auto-injected in a dedicated prompt section (`Verification Replay Memories (Auto-Injected)`)
- replay memos should include environment context, exact verification commands/scripts, exhaustive artifact paths, and freshness notes
- absolute artifact paths are normalized to current `temp_workspaces/<agent_token>/...` paths during injection

`max_checklist_calls_per_round` prevents in-round checklist loops.

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
  max_new_answers_per_agent: 2              # null = unlimited
  max_new_answers_global: 8                 # null = unlimited
  defer_voting_until_all_answered: false
  max_checklist_calls_per_round: 1
  checklist_first_answer: false
```

## Related Docs

- `docs/modules/architecture.md` - core system architecture and backend hierarchy
- `docs/modules/injection.md` - hook and injection internals
- `docs/modules/composition.md` - personas/criteria/decomposition composition
- `docs/source/reference/yaml_schema.rst` - orchestration and fairness config reference
