# Subagents Module

## Overview

Subagents are child MassGen processes spawned by parent agents for parallel, isolated task execution.

Subagent isolation has two dimensions:

- Workspace isolation: each subagent has its own workspace directory
- Runtime boundary isolation: where the subagent process itself executes

## Runtime Modes

Subagent runtime mode is configured under `orchestrator.coordination`.

- `subagent_runtime_mode: isolated` (default)
- `subagent_runtime_mode: inherited`
- `subagent_runtime_fallback_mode: inherited` (optional explicit fallback)
- `subagent_host_launch_prefix: [...]` (optional host-launch bridge for containerized parent runtimes)

Behavior:

- `isolated` tries to run subagents in an isolated runtime boundary
- If isolated prerequisites are unavailable:
  - with no fallback: launch fails with actionable diagnostics
  - with `subagent_runtime_fallback_mode: inherited`: launch proceeds in inherited mode and emits an explicit warning
- `inherited` runs subagents in the same runtime boundary as the parent

## Context Contract

`spawn_subagents` requires every task to include `context_paths`.

- `context_paths` must be present in each task object
- `context_paths` must be a list
- Use `[]` for no additional context
- Use `["./"]` for parent workspace read access

This is validated at the subagent MCP gateway (`_subagent_mcp_server.py`), not only by prompt guidance.

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

1. Parent orchestrator creates subagent MCP config and passes runtime settings
2. Subagent MCP server initializes `SubagentManager` with those settings
3. `SubagentManager` resolves effective runtime mode:
   - isolated
   - inherited
   - inherited via explicit fallback with warning
4. Subagent process is launched and log/TUI contracts are preserved

## Logging and TUI Contracts

Across runtime modes, contracts remain stable:

- blocking/background `spawn_subagents` response structure
- standardized background-tool lifecycle semantics for async jobs
- `live_logs`/`full_logs` layout and references
- subagent result `warning` field for fallback diagnostics

## Key Files

- `massgen/subagent/manager.py`: runtime routing, launch, lifecycle, results
- `massgen/mcp_tools/subagent/_subagent_mcp_server.py`: tool schema and task validation
- `massgen/orchestrator.py`: subagent MCP config wiring
- `massgen/agent_config.py`: runtime config surface on coordination settings
- `massgen/config_validator.py`: validation of runtime mode/fallback combinations
