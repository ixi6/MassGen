# Coordination Workflow: End-to-End Lifecycle

This is the canonical high-level flow for MassGen coordination across modes. It covers:

- pre-coordination checks
- per-agent round execution
- submission semantics (`new_answer`, `vote`, `stop`)
- injection and restart behavior
- fairness and timeout gates
- optional checklist policy behavior

MassGen is asynchronous: agents are not lockstep-synchronized and can be in different local rounds at the same time.

## User-Facing View (ASCII)

If you want the simplest mental model first, use this:

```text
                           USER REQUEST
                                │
                                ▼
          ┌────────────────────────────────────────────┐
          │         PRE-COLLABORATION CHECKS           │
          │ - build turn context + history             │
          │ - setup tools/workspaces/permissions       │
          │ - run safety/planning checks               │
          │ - optional personas/criteria/decomposition │
          └─────────────────────┬──────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │      ORCHESTRATOR      │
                    │ (traffic + decisions)  │
                    └───────┬────────┬───────┘
                            │        │
                 sends context+tools  │ receives
                            │         │ new_answer/vote/stop
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
        │      shared updates / injections to peers     │
        │   (after first-answer diversity protection)   │
        │                       │                       │
        └─────────────── keep refining in parallel ─────┘
                                │
                      eventually each agent does:
                         vote (or stop in decomposition)
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

In plain terms:

- Before agents start, MassGen runs pre-collaboration setup/safety checks.
- Multiple agents work at the same time.
- They can submit improved answers (`new_answer`) and learn from each other.
- Early on, each agent gets protected space to produce an independent first answer.
- Later, updates are shared, and agents converge by voting (or stopping in decomposition mode).
- A final presenter delivers the final answer.

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
        │    restart/fairness logs, runtime injection history,
        │    context-path write tracking, workspace clearing rules
        ├─ Optional planning-mode irreversibility analysis:
        │    decide planning mode + blocked tools per backend
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
        ├─ Completion gate:
        │    all agents terminal? (voted/stopped)
        │    OR skip_voting mode with all agents answered?
        │
        ├─ Global guards:
        │    cancellation? orchestrator timeout?
        │
        ├─ For each agent, pre-start gates:
        │    - waiting_for_all_answers gate
        │    - decomposition auto-stop on limits
        │    - fairness pre-start pause gate
        │    - startup rate limit
        │    - if eligible: spawn _stream_agent_execution(agent)
        │
        ├─ Consume parallel stream chunks from agents:
        │    content / reasoning / tool status / result / done / error
        │
        ├─ If agent result = answer:
        │    save snapshot + tracker update
        │    reset votes/stops for all agents
        │    if injection enabled: set restart_pending for peers
        │
        ├─ If agent result = vote or stop:
        │    apply terminal fairness checks
        │    allow stale-restart exceptions (single-agent/no-unseen/hard-timeout)
        │    record terminal decision
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
        ├─ Merge memories to presenter workspace (if enabled)
        └─ Final presentation/synthesis phase
```

## Per-Agent Round Engine (ASCII)

```text
_stream_agent_execution(agent_i)
    │
    ├─ Round setup
    │   - reset per-round counters/timeouts
    │   - copy latest snapshots to temp workspace
    │   - build system/user context (persona, criteria, planning mode, mappings)
    │   - setup hooks/injection delivery path
    │   - choose tools (normal or vote-only)
    │
    ├─ Retry loop (max attempts)
    │   │
    │   ├─ Restart/injection checkpoint
    │   │   - if restart_pending and agent has no first answer:
    │   │       defer restart (first-answer diversity protection)
    │   │   - else resolve delivery path:
    │   │       first peer update => restart-style refresh
    │   │       later updates     => mid-stream injection (when supported)
    │   │       no-hook backend   => fallback enforcement injection or restart
    │   │
    │   ├─ Stream backend response (+ tools)
    │   │
    │   ├─ Enforcement checks on tool calls:
    │   │   - tool availability this round
    │   │   - disallow mixed vote+new_answer
    │   │   - terminal fairness gate for vote/stop
    │   │   - answer limits / novelty / duplicate constraints for new_answer
    │   │
    │   └─ Exit on valid workflow result:
    │       new_answer -> ("result","answer")
    │       vote/stop  -> ("result","vote")  # stop reuses vote pipeline
    │
    └─ finally: round telemetry + cleanup
```

## Pre-Coordination Checks

### A. Orchestrator initialization checks (once per orchestrator instance)

- Per-agent workspace/snapshot/orchestration path setup.
- Optional skills validation and workspace skill directory setup.
- Optional planning/subagent tool injection.
- Optional NLIP and broadcast tool initialization.
- Optional checklist tool registration when `voting_sensitivity: checklist_gated`.

### B. Turn-start checks (every user turn)

- User message presence.
- Conversation context build and history handling.
- Optional paraphrase generation.
- Session/tracker re-initialization for the new turn.
- Turn-scoped state reset (restart flags, fairness logs, injection delivery history).
- Optional planning-mode irreversibility analysis and tool blocking policy setup.

### C. Coordination-iteration checks (inside the parallel loop)

- Completion gate (all terminal, or skip-voting all-answered).
- Cancellation and orchestrator-timeout guards.
- Per-agent spawn gates:
  - defer-voting-until-all-answered
  - decomposition auto-stop
  - fairness pre-start pause
  - startup rate-limit

## First-Answer Diversity Protection

First answers are protected by design:

- Agents that have not yet produced an answer are not interrupted by peer-answer updates.
- This preserves independent initial exploration and avoids premature convergence.
- Protection applies to peer-answer delivery paths (restart, mid-stream injection, and no-hook fallback).

This is why internal round `0` (human-facing "Round 1") behaves differently for peer-answer injection.

## Submission Semantics

Workflow tools are the coordination contract:

- `new_answer` = iterative submission
- `vote` = terminal submission in voting mode
- `stop` = terminal submission in decomposition mode

When a `new_answer` is accepted:

- agent answer revision is recorded
- terminal decisions are reset for re-evaluation
- peers are marked for update delivery (unless `disable_injection: true`)

## Workspace And Snapshot Lifecycle

Each agent has three storage locations:

- **workspace** — the agent's live working directory during a round
- **snapshot_storage** — single-slot buffer holding the most recent deliverable; peers read this via `temp_workspace` before each round
- **log directory** — append-only per-timestamp archive for debugging

### Normal Answer Submission

When an agent calls `new_answer`:

```text
Agent calls new_answer
  │
  ├─ _save_agent_snapshot(answer_content="...")
  │   ├─ Save answer text → log dir (timestamped)
  │   ├─ save_snapshot(preserve_existing_snapshot=False)
  │   │   ├─ OVERWRITE snapshot_storage with workspace
  │   │   └─ Copy workspace → log dir
  │   └─ clear_workspace()
  │
  ├─ Record answer in coordination_tracker
  └─ Set restart_pending=True on all peers (unless disable_injection)
```

### Peer Update Delivery (Injection vs Restart)

When a peer submits a `new_answer`, the current agent needs to see it. Delivery depends on backend capabilities and first-answer protection:

```text
Peer submits new_answer → restart_pending=True set on current agent
  │
  ├─ Agent hasn't produced first answer yet?
  │   └─ DEFER — first-answer diversity protection, clear restart_pending
  │       (handled by _should_defer_restart_for_first_answer)
  │
  ├─ Backend has hook delivery?
  │   │  (GeneralHookManager, native hooks, or MCP server hooks)
  │   │
  │   │  Hook delivery mechanisms:
  │   │  - Standard backends → GeneralHookManager + MidStreamInjectionHook
  │   │  - Claude Code → supports_native_hooks() (SDK-level)
  │   │  - Codex → supports_mcp_server_hooks() + file IPC
  │   │    (_setup_codex_mcp_hooks / _flush_codex_hook_payloads)
  │   │
  │   ├─ Not too close to soft timeout?
  │   │   └─ MID-STREAM INJECTION — content injected via hook callback
  │   │      (no restart, agent continues working with injected context)
  │   │
  │   └─ Too close to timeout?
  │       └─ SKIP — restart_pending stays set; agent finishes current round,
  │          and the next round starts with the new answer already in context
  │
  └─ No hook delivery? (defensive fallback — all current backends have hooks)
      ├─ Stream already started → enforcement message injection
      └─ No in-flight buffer → clean restart
```

Non-peer payloads can also inject during rounds:

- runtime human input
- background subagent completions
- background tool completions
- timeout warnings

On restart, the agent's workspace carries forward (it is NOT cleared between rounds). The new round starts with the same workspace, but updated system context and peer snapshots in `temp_workspace`.

### Vote/Stop Submission

```text
Agent calls vote (or stop in decomposition mode)
  │
  ├─ _save_agent_snapshot(vote_data={...})
  │   ├─ Save vote JSON → log dir
  │   └─ SKIP workspace snapshot (preserve previous answer's workspace)
  │
  └─ Record terminal decision
```

### Interrupted/Early Termination Saves

Two code paths handle saving when agents don't complete normally:

1. **Orchestration cancelled/timed out** → `_save_partial_execution_traces_for_interrupted_turn()` runs for all agents
2. **No successful agents** → `_save_partial_snapshots_for_early_termination()` calls `_save_agent_snapshot(answer_content=None)` per agent

Both paths invoke `save_snapshot(preserve_existing_snapshot=True)`.

### Snapshot Preservation Invariant

During interrupted or early-termination saves, `snapshot_storage` is **never** overwritten if it already contains content from a previous submission. The agent was interrupted mid-work — whatever's in the workspace is by definition incomplete. The previous snapshot (from an actual `new_answer` submission) is always more valuable.

| `snapshot_storage` | workspace | Action |
|---|---|---|
| Has content | Any | **SKIP** — preserve submitted answer |
| Empty | Has content | **COPY** — partial work better than nothing |
| Empty | Empty | **SKIP** — nothing to save |

Normal saves (`answer_content` provided) and final saves (`is_final=True`) always overwrite as before.

This is enforced in:
- `save_snapshot(preserve_existing_snapshot=True)` in `FilesystemManager`
- `_save_partial_workspace_snapshots_for_interrupted_turn()` in `Orchestrator` (inline copy logic)

### Final Answer Phase

```text
Presenter selected (vote winner or configured)
  │
  ├─ _save_agent_snapshot(is_final=True)
  │   ├─ save_snapshot(is_final=True, preserve=False) → OVERWRITE snapshot_storage
  │   │   └─ Copy → log dir under "final/"
  │   └─ restore_from_snapshot_storage() (for post-evaluator visibility)
  │
  ├─ Final presentation runs
  └─ clear_workspace() (after presentation complete)
```

## Fairness And Pacing

Fairness limits pace and stale-terminal decisions:

- `fairness_lead_cap_answers`: max revision lead over slowest active peer.
- Pre-start fairness pause: can defer starting a new expensive round.
- Terminal fairness gate: block `vote`/`stop` until unseen peer updates are observed.
- `max_midstream_injections_per_round`: cap mid-stream unseen update fanout.

Important exceptions:

- First-answer diversity phase is not blocked by fairness lead gating.
- Hard-timeout cutoff can bypass fairness waiting to prevent deadlock.

## Timeouts And Retry Enforcement

Timeout hooks are per-round:

- soft timeout injects wrap-up guidance
- hard timeout blocks non-terminal tools after grace period
- repeated hard-timeout denials can force terminate the agent turn

If models emit invalid workflow behavior, orchestrator retries with enforcement messages (bounded attempts), then fails the agent turn if unresolved.

## Optional Checklist Layer (Not Core Runtime Primitive)

Checklist mode is policy, not the core control loop:

- enabled by `voting_sensitivity: checklist_gated`
- default: checklist is disabled before first submitted answer (`checklist_first_answer: false`)
- typical use:
  1. implement and self-verify
  2. call `submit_checklist` once
  3. execute verdict via workflow tool (`new_answer` or terminal action)

`max_checklist_calls_per_round` prevents in-round checklist loops and keeps coordination progress moving through shared rounds.

## Limits And Mode-Specific Outcomes

Limit gates:

- `max_new_answers_per_agent`
- `max_new_answers_global`

Mode-dependent behavior:

- voting mode: limit can force vote-only tool availability.
- decomposition mode: limit can auto-stop agent instead of vote-only state.

Optional `defer_voting_until_all_answered` can keep capped agents waiting until all peers have at least one answer.

## Completion And Final Answer

Coordination completes when all active agents are terminal (`has_voted` / stopped), then:

- presenter is selected
- final answer phase runs
- final output is produced with coordination metadata

## Practical Notes

- Internal round numbers start at `0` (first-answer phase).
- Human-facing UIs often label that as "Round 1".
- Agents evaluate anonymous answer labels, not real agent identities.
- `disable_injection: true` switches to independent refinement behavior (no peer-answer propagation).

## Config Quick Reference

```yaml
orchestrator:
  coordination_mode: voting                 # or decomposition
  voting_sensitivity: balanced              # or checklist_gated
  disable_injection: false                  # true = independent refinement (no peer answer updates)
  fairness_enabled: true
  fairness_lead_cap_answers: 2
  max_midstream_injections_per_round: 2
  max_new_answers_per_agent: 2              # null = unlimited
  max_new_answers_global: 8                 # null = unlimited
  defer_voting_until_all_answered: false
  max_checklist_calls_per_round: 1          # checklist policy
  checklist_first_answer: false             # checklist starts after first submitted answer
```

## Related Docs

- `docs/modules/architecture.md` - core system architecture
- `docs/modules/injection.md` - hook and injection delivery internals
- `docs/modules/composition.md` - personas, criteria, decomposition composition
- `docs/source/reference/yaml_schema.rst` - orchestration/fairness config reference
