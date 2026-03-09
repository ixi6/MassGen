# Subagents Module

## Overview

Subagents are child MassGen processes spawned by parent agents for parallel, isolated task execution.

Subagent isolation has two dimensions:

- Workspace isolation: each subagent has its own workspace directory
- Runtime boundary isolation: where the subagent process itself executes

## Runtime Modes

Subagent runtime mode is configured under `orchestrator.coordination`.

- `subagent_runtime_mode: isolated` (default) — run subagents as independent processes on the host
- `subagent_runtime_mode: inherited` — run subagents in the same runtime boundary as the parent
- `subagent_runtime_mode: delegated` — file-based delegation to a host-side watcher that creates isolated containers (see below)
- `subagent_runtime_fallback_mode: inherited` — optional explicit fallback when isolated prerequisites are unavailable
- `subagent_host_launch_prefix: [...]` — optional host-launch bridge for containerized parent runtimes

Behavior:

- `isolated` tries to run subagents in an isolated runtime boundary
- If isolated prerequisites are unavailable:
  - with no fallback: launch fails with actionable diagnostics
  - with `subagent_runtime_fallback_mode: inherited`: launch proceeds in inherited mode and emits an explicit warning
- `inherited` runs subagents in the same runtime boundary as the parent
- `delegated` uses the outbox pattern: the container writes a request file, a trusted host-side `SubagentLaunchWatcher` creates an isolated container per subagent (see [Delegated Mode](#delegated-mode-codex--docker) below)
- Codex+Docker auto-detection: when the backend is Codex with `command_line_execution_mode: docker` and no explicit fallback/prefix is set, the orchestrator automatically switches to `delegated` mode if a delegation directory is available. This replaces the old `inherited` fallback with secure per-subagent container isolation.

## Delegated Mode (Codex + Docker)

When the parent agent runs inside a Docker container (e.g. the Codex backend), subagents cannot be launched as isolated host processes without mounting the Docker socket — a critical security risk. The **delegated mode** solves this via the outbox pattern:

```
Container (untrusted)                  Host (trusted)
┌──────────────────┐                   ┌─────────────────────────┐
│ SubagentManager   │  request.json    │ SubagentLaunchWatcher   │
│ (_execute_        │ ──────────────►  │                         │
│  delegated)       │                  │ - Validates workspace   │
│                   │  response.json   │   against allowlist     │
│ polls for result  │ ◄────────────── │ - Hardcodes image,      │
│                   │                  │   network=none, etc.    │
│                   │                  │ - Creates container via │
│                   │                  │   DockerManager         │
└──────────────────┘                   └─────────────────────────┘
```

### How It Works

1. `SubagentManager._execute_delegated()` writes a `request_{subagent_id}.json` atomically to the shared delegation directory (mounted rw in both container and host)
2. `SubagentLaunchWatcher` on the host polls for new request files
3. For each request, the watcher:
   - Validates the workspace path against `allowed_workspace_roots`
   - Sanitizes the YAML config: overrides `command_line_execution_mode=local`, strips all `command_line_docker_*` keys (the container IS the sandbox — no Docker-in-Docker)
   - Creates an isolated container via `DockerManager` with hardcoded `network_mode="none"` and the image from orchestrator config
   - Runs `massgen --automation` inside the container
   - Writes `response_{subagent_id}.json` atomically
4. `SubagentManager` polls for the response file and reads the answer

### Security Properties

All security-critical parameters are set by the **host-side watcher**, not from the request file:
- Docker image hardcoded from orchestrator config
- `network_mode` hardcoded to `"none"`
- `privileged` always `False`
- Workspace path validated against allowlist before any container is created
- Unknown fields in request files are silently ignored (forward compatibility)

### Cancellation

On timeout or `asyncio.CancelledError`, `SubagentManager` writes an empty `cancel_{subagent_id}` sentinel file. The watcher monitors for this and cancels the running container task.

### Key Files

- `massgen/subagent/delegation_protocol.py` — `DelegationRequest`/`DelegationResponse` dataclasses, atomic write helpers, cancel sentinel
- `massgen/subagent/launch_watcher.py` — `SubagentLaunchWatcher` host-side polling loop
- `massgen/subagent/manager.py` — `_execute_delegated()` method

## Context Contract

`spawn_subagents` mounts workspaces read-only for subagents. Per-task options:

- `include_parent_workspace` (bool, default `True`) — mount the parent's workspace read-only.
  Set `False` for fully isolated research subagents.
- `include_temp_workspace` (bool, default `True`) — auto-mount the shared reference directory
  (`temp_workspaces/`) read-only. Contains peer agent snapshots. Set `False` to skip.
- `context_paths` (list, optional, default `[]`) — additional read-only paths beyond the
  auto-mounted parent workspace and temp_workspaces. Must be a list if provided. Only needed
  for paths outside the two auto-mounted locations.

The `_subagent_mcp_server.py` MCP gateway validates that `context_paths`, if provided, is a list
and that all paths exist on the filesystem.

### File Write-Back Pattern

Subagents can **only** write to their own workspace — the parent workspace is mounted read-only
to them. Correct pattern:

1. Tell the subagent to save artifacts with relative paths (e.g. `verification/`).
2. The spawn result always includes `"workspace": "/abs/path/to/subagent/workspace"`.
3. After the subagent completes, read artifacts from that path.

**WRONG**: `"Save screenshots to /parent/workspace/.massgen_scratch/verification/"`
**RIGHT**: `"Save screenshots to verification/ in your workspace and list them in your answer."`

## Subagent Backend Inheritance

Subagent child teams resolve differently for `round_evaluator` vs other subagent types.

`round_evaluator` defaults to the shared evaluator pool from `subagent_orchestrator.agents`
when configured. Other subagent types default to the spawning parent's own child-team config.

Use `subagent_orchestrator.shared_child_team_types` to choose which subagent types use
that shared pool:

- default: `["round_evaluator"]`
- targeted opt-in: `["round_evaluator", "builder"]`
- all subagent types: `["*"]`

Non-`round_evaluator` subagents resolve from:

- parent-local agents from `agents[].subagent_agents` on the spawning parent agent
- synthesized parent-local inheritance from the spawning parent's backend when no
  explicit `subagent_agents` exist
- shared common agents from `subagent_orchestrator.agents` only as a last resort if
  no parent-local source can be resolved

`round_evaluator` resolves from:

- shared common agents from `subagent_orchestrator.agents`
- parent-local agents from `agents[].subagent_agents` only when no shared evaluator
  pool is configured
- synthesized parent-local inheritance when `inherit_spawning_agent_backend: true`
  and no shared evaluator pool or parent-local child team exists

Legacy fallback to inheriting all parent agent backends only applies when none of the
above sources are configured.

`subagent_orchestrator.inherit_spawning_agent_backend: true` is a fill-in rule for missing
parent-local config:

- if the spawning parent agent has no `subagent_agents`, the system synthesizes one local
  subagent agent copied from that parent's backend config (including type/model)
- if the spawning parent agent already defines `subagent_agents`, inheritance does nothing
  for that parent
- task-level `model` overrides in `spawn_subagents` are rejected when this mode is enabled

Effective resolution order:

1. `round_evaluator`: shared common agents from `subagent_orchestrator.agents`
2. non-`round_evaluator`: spawning parent agent's `subagent_agents` when present
3. non-`round_evaluator`: synthesized parent-local inherited agent copied from the
   spawning parent's backend when local config is absent
4. `round_evaluator`: spawning parent agent's `subagent_agents` when no shared pool exists
5. shared common agents for non-`round_evaluator` only when no parent-local source exists
6. legacy fallback to all parent agent backends only when none of the above exist

If `shared_child_team_types` contains a subagent type, step 1 applies to that type.

## Specialized Subagent Profiles

MassGen supports specialized `subagent_type` profiles that inject role-specific prompt + skills.

Built-in profiles:

- `explorer`: repo exploration and discovery
- `researcher`: external-source research and evidence gathering
- `evaluator`: high-volume procedural verification
- `round_evaluator`: round-2+ cross-answer critique that returns a very critical, spec-style improvement packet for the parent
- `novelty`: proposes transformative alternatives when agents are stuck in incremental refinement (opt-in only)

### Configuring Active Types

`subagent_types` under `orchestrator.coordination` controls which types are exposed:

- Default (omitted/null): `["evaluator", "explorer", "researcher", "critic"]`
- Explicit list filters to only those types; unknown names warn but don't fail
- Empty list `[]` disables all specialized types
- When `novelty` is active, checklist evaluation auto-suggests spawning a novelty subagent on zero transformative changes
- `round_evaluator` is opt-in via an explicit list such as `subagent_types: [round_evaluator]`

### Round Evaluator Loop

`coordination.round_evaluator_before_checklist: true` enables the single-parent
manual/prompt-guided v1 flow:

- round 1: parent builds and submits its first answer normally
- round 2+: the parent launches one blocking `round_evaluator` subagent before
  checklist submission unless the separate orchestrator-managed gate is enabled
- the round evaluator returns a critique/spec packet with `criteria_interpretation`, `criterion_findings`, `cross_answer_synthesis`, `preserve`, `improvement_spec`, `verification_plan`, and `evidence_gaps`
- the parent saves or copies that packet into its workspace as the diagnostic
  report used for `submit_checklist`
- the parent does not run a second full self-evaluation pass; additional
  verification is only for explicit `evidence_gaps`
- the parent still owns `submit_checklist`, `propose_improvements`, `new_answer`, and `vote`
- generated child YAML for `round_evaluator` always mounts the shared
  temp-workspace root read-only
- with `refine: false`, `round_evaluator` remains a quick critique-only child
  run and omits checklist-gated child settings
- with `refine: true`, `round_evaluator` may inherit the parent checklist gate;
  when no child-specific criteria are configured, it falls back to a built-in
  `round_evaluator` criteria preset for judging the critique packet itself
- when the child run is using presenter-stage `synthesize`/`winner_present`, it
  keeps `skip_final_presentation: false`

`coordination.orchestrator_managed_round_evaluator: true` is a separate,
currently gated mode that lets the orchestrator launch that same blocking
`round_evaluator` before round 2+.

Validation constraints for this mode:

- top-level run must have exactly one parent agent
- `orchestrator.voting_sensitivity` must be `checklist_gated`
- `coordination.enable_subagents` must be `true`
- `coordination.subagent_orchestrator.enabled` must be `true`
- `coordination.subagent_types` must include `round_evaluator`

### Multi-Agent Quick Runs

For subagent child runs with more than one inner agent:

- if `refine=False` and no explicit child `subagent_orchestrator.final_answer_strategy` is set, generated child YAML now defaults to `final_answer_strategy: synthesize`
- if `subagent_orchestrator.final_answer_strategy` is set explicitly, that value wins
- `round_evaluator` is the current exception: multi-agent quick child runs keep the presenter stage when the effective child strategy is `synthesize` or `winner_present`
- quick multi-agent child runs with effective `final_answer_strategy: synthesize` and `max_new_answers_per_agent: 1` now end after the first answer from each child and go straight to presenter-stage synthesis without an intermediate vote round

This keeps evaluator-style quick runs returning one synthesized child result instead of a reused winner by default.

Profile discovery:

- Built-ins are read from `massgen/subagent_types/*/SUBAGENT.md`
- Project overrides are read from `.agent/subagent_types/*/SUBAGENT.md`
- Project definitions override built-ins on case-insensitive name collisions
- Template directories such as `massgen/subagent_types/_template/` are excluded from discovery

Profile schema (strict):

- Allowed frontmatter keys: `name`, `description`, `skills`, `expected_input`
- Legacy keys (for example `default_background`, `default_refine`, `mcp_servers`) are rejected

Runtime validation:

- Unknown `subagent_type` fails fast at the MCP gateway with an explicit error listing available types
- Known `subagent_type` injects `system_prompt` and `skills` before spawn

Authoring template:

- Use `massgen/subagent_types/_template/SUBAGENT_TEMPLATE.md` as the canonical scaffold for new profiles

## Timeout Layering

Subagent timeout behavior has three layers:

1. Subagent runtime timeout (`subagent_default_timeout`, clamped by min/max)
2. MCP client timeout (spawn_subagents is timeout-exempt)
3. Codex tool timeout buffer (`tool_timeout_sec = subagent_default_timeout + 60`)

The runtime timeout is the authoritative limit for subagent execution.

## MCP Tool Surface

Subagent MCP server intentionally keeps a small interface:

- `spawn_subagents(tasks, background?, refine?)`
- `list_subagents()`
- `continue_subagent(subagent_id, message, timeout_seconds?)`

Removed specialized subagent polling/cost tools:

- `check_subagent_status`
- `get_subagent_result`
- `get_subagent_costs`

Reasoning:

- Use standardized background lifecycle tools for background job control (`custom_tool__get_background_tool_status`, `custom_tool__get_background_tool_result`, `custom_tool__wait_for_background_tool`, `custom_tool__cancel_background_tool`, `custom_tool__list_background_tools`)
- Keep `list_subagents()` as discovery/index metadata for subagent IDs, workspace/session pointers, and status
- Read detailed cost/status internals from `full_logs/status.json` and run-level totals from `metrics_summary.json`

## Launch Flow

1. Parent orchestrator creates subagent MCP config and passes runtime settings (including `--delegation-directory`)
2. Subagent MCP server initializes `SubagentManager` with those settings
3. `SubagentManager` resolves effective runtime mode:
   - `isolated` — subprocess on host
   - `inherited` — subprocess in same container
   - `inherited` via explicit fallback with warning
   - `delegated` — file-based outbox to host-side `SubagentLaunchWatcher`
4. For `delegated` mode: request file → watcher → isolated container → response file
5. Subagent result and log/TUI contracts are preserved across all modes

## Logging and TUI Contracts

Across runtime modes, contracts remain stable:

- blocking/background `spawn_subagents` response structure
- standardized background-tool lifecycle semantics for async jobs
- `live_logs`/`full_logs` layout and references
- subagent result `warning` field for fallback diagnostics

## Key Files

- `massgen/subagent/manager.py` — runtime routing, launch, lifecycle, results, `_execute_delegated()`
- `massgen/subagent/delegation_protocol.py` — request/response protocol dataclasses and file helpers
- `massgen/subagent/launch_watcher.py` — host-side `SubagentLaunchWatcher` for delegated mode
- `massgen/mcp_tools/subagent/_subagent_mcp_server.py` — tool schema and task validation
- `massgen/orchestrator.py` — subagent MCP config wiring, delegation dir setup, watcher lifecycle
- `massgen/agent_config.py` — runtime config surface on coordination settings
- `massgen/config_validator.py` — validation of runtime mode/fallback combinations
