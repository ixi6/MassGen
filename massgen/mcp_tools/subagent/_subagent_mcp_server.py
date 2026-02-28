#!/usr/bin/env python3
"""
Subagent MCP Server for MassGen

This MCP server provides tools for spawning and managing subagents,
enabling agents to delegate tasks to independent agent instances
with fresh context and isolated workspaces.

Tools provided:
- spawn_subagents: Spawn one or more subagents (runs in parallel if multiple)
- list_subagents: List all spawned subagents with their status
- continue_subagent: Continue a subagent conversation by session ID
"""

import argparse
import asyncio
import atexit
import json
import logging
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import fastmcp

from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SUBAGENT_DEFAULT_TIMEOUT, SubagentOrchestratorConfig

logger = logging.getLogger(__name__)

# Global storage for subagent manager (initialized per server instance)
_manager: SubagentManager | None = None

# Server configuration
_workspace_path: Path | None = None
_agent_temporary_workspace: str | None = None
_parent_agent_id: str | None = None
_orchestrator_id: str | None = None
_parent_agent_configs: list[dict[str, Any]] = []
_subagent_orchestrator_config: SubagentOrchestratorConfig | None = None
_log_directory: str | None = None
_max_concurrent: int = 3
_default_timeout: int = SUBAGENT_DEFAULT_TIMEOUT
_min_timeout: int = 60
_max_timeout: int = 600
_subagent_runtime_mode: str = "isolated"
_subagent_runtime_fallback_mode: str | None = None
_subagent_host_launch_prefix: list[str] = []
_delegation_directory: str | None = None
_parent_context_paths: list[dict[str, str]] = []
_parent_coordination_config: dict[str, Any] = {}
_specialized_subagents: dict[str, dict[str, Any]] = {}  # name -> type config dict
_subagent_types_loaded: bool = False  # set to True after first lazy scan
_next_subagent_index: int = 0  # auto-increment counter for default subagent IDs


def _find_temp_workspace_mcp_fallback(file_name: str) -> Path | None:
    """Find a subagent MCP config file copied into agent temp workspace snapshots.

    During round transitions, workspace branch switches may remove
    workspace/.massgen/subagent_mcp/* before lazy MCP startup. Snapshot copies
    under agent temp workspace remain available and are safe fallback sources.
    """
    if not _agent_temporary_workspace:
        return None

    temp_root = Path(_agent_temporary_workspace)
    if not temp_root.exists() or not temp_root.is_dir():
        return None

    candidates = [path for path in temp_root.glob(f"*/.massgen/subagent_mcp/{file_name}") if path.is_file()]
    if not candidates:
        return None

    try:
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        candidates.sort(reverse=True)

    return candidates[0]


def _load_json_with_temp_workspace_fallback(path_str: str) -> tuple[Any, Path]:
    """Load JSON from primary path, falling back to temp workspace snapshot copy."""
    primary = Path(path_str)
    try:
        with open(primary) as f:
            return json.load(f), primary
    except (json.JSONDecodeError, FileNotFoundError, OSError) as primary_err:
        fallback = _find_temp_workspace_mcp_fallback(primary.name)
        if fallback is None:
            raise primary_err
        with open(fallback) as f:
            return json.load(f), fallback


def _ensure_specialized_types_loaded() -> None:
    """Lazily scan workspace for SUBAGENT.md dirs on first call to spawn_subagents.

    Parsed using only stdlib + PyYAML to stay independent of the massgen package,
    since the fastmcp subprocess may run under a Python that can partially import
    massgen but lacks some of its transitive dependencies (e.g. gitpython).
    """
    global _specialized_subagents, _subagent_types_loaded
    if _subagent_types_loaded:
        return
    _subagent_types_loaded = True
    if _workspace_path is None:
        return
    types_dir = _workspace_path / ".massgen" / "subagent_types"
    if not types_dir.is_dir():
        logger.warning(f"[SubagentMCP] subagent_types dir not found: {types_dir}")
        return
    try:
        import re

        import yaml

        loaded = 0
        for type_path in sorted(types_dir.iterdir()):
            if not type_path.is_dir():
                continue
            md_file = type_path / "SUBAGENT.md"
            if not md_file.exists():
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                # Extract YAML frontmatter between --- delimiters
                fm_match = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
                if not fm_match:
                    logger.warning(f"[SubagentMCP] No frontmatter in {md_file}")
                    continue
                metadata = yaml.safe_load(fm_match.group(1)) or {}
                description = metadata.get("description", "")
                if not description:
                    logger.warning(f"[SubagentMCP] No description in {md_file}, skipping")
                    continue
                # System prompt is everything after the closing ---
                sp_match = re.match(r"^---\n.*?\n---\n?(.*)", content, re.DOTALL)
                system_prompt = sp_match.group(1).strip() if sp_match else ""
                name = str(metadata.get("name", "")).strip() or type_path.name
                _specialized_subagents[name.lower()] = {
                    "name": name,
                    "description": description,
                    "system_prompt": system_prompt,
                    "skills": metadata.get("skills") or [],
                    "expected_input": metadata.get("expected_input") or [],
                }
                loaded += 1
            except Exception as e:
                logger.warning(f"[SubagentMCP] Failed to parse {md_file}: {e}")
        logger.info(f"[SubagentMCP] Lazily loaded {loaded} specialized subagent types")
    except Exception as e:
        logger.warning(f"[SubagentMCP] Failed to scan subagent types: {e}")


def _get_manager() -> SubagentManager:
    """Get or create the SubagentManager instance."""
    global _manager
    if _manager is None:
        if _workspace_path is None:
            raise RuntimeError("Subagent server not properly configured: workspace_path is None")
        _manager = SubagentManager(
            parent_workspace=str(_workspace_path),
            parent_agent_id=_parent_agent_id or "unknown",
            orchestrator_id=_orchestrator_id or "unknown",
            parent_agent_configs=_parent_agent_configs,
            subagent_orchestrator_config=_subagent_orchestrator_config,
            log_directory=_log_directory,
            max_concurrent=_max_concurrent,
            default_timeout=_default_timeout,
            min_timeout=_min_timeout,
            max_timeout=_max_timeout,
            parent_context_paths=_parent_context_paths,
            parent_coordination_config=_parent_coordination_config,
            agent_temporary_workspace=_agent_temporary_workspace,
            subagent_runtime_mode=_subagent_runtime_mode,
            subagent_runtime_fallback_mode=_subagent_runtime_fallback_mode,
            subagent_host_launch_prefix=_subagent_host_launch_prefix,
            delegation_directory=_delegation_directory,
        )
    return _manager


def _save_subagents_to_filesystem() -> None:
    """
    Save subagent registry to filesystem for visibility.

    Writes to subagents/_registry.json in the workspace directory.
    """
    if _workspace_path is None:
        return

    manager = _get_manager()
    subagents_dir = _workspace_path / "subagents"
    subagents_dir.mkdir(exist_ok=True)
    # Keep registry metadata lightweight and stable across turns.
    # Full result payloads are surfaced via list_subagents() at runtime only.
    subagents = []
    for entry in manager.list_subagents():
        entry_copy = dict(entry)
        entry_copy.pop("result", None)
        subagents.append(entry_copy)

    registry = {
        "parent_agent_id": _parent_agent_id,
        "orchestrator_id": _orchestrator_id,
        "subagents": subagents,
    }

    registry_file = subagents_dir / "_registry.json"
    try:
        registry_file.write_text(json.dumps(registry, indent=2))
    except OSError as e:
        logger.error(f"[SubagentMCP] Failed to save registry: {e}")


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create and configure the subagent MCP server."""
    global _workspace_path, _parent_agent_id, _orchestrator_id, _parent_agent_configs
    global _subagent_orchestrator_config, _log_directory, _parent_context_paths
    global _max_concurrent, _default_timeout, _min_timeout, _max_timeout
    global _subagent_runtime_mode, _subagent_runtime_fallback_mode, _subagent_host_launch_prefix
    global _delegation_directory
    global _parent_coordination_config, _specialized_subagents, _agent_temporary_workspace

    parser = argparse.ArgumentParser(description="Subagent MCP Server")
    parser.add_argument(
        "--agent-id",
        type=str,
        required=True,
        help="ID of the parent agent using this subagent server",
    )
    parser.add_argument(
        "--orchestrator-id",
        type=str,
        required=True,
        help="ID of the orchestrator managing this agent",
    )
    parser.add_argument(
        "--workspace-path",
        type=str,
        required=True,
        help="Path to parent agent workspace for subagent workspaces",
    )
    parser.add_argument(
        "--agent-temporary-workspace",
        type=str,
        required=False,
        default="",
        help="Path to parent agent temporary workspace root (read-only shared reference)",
    )
    parser.add_argument(
        "--agent-configs-file",
        type=str,
        required=False,
        default="",
        help="Path to JSON file containing list of parent agent configurations",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=3,
        help="Maximum concurrent subagents (default: 3)",
    )
    parser.add_argument(
        "--default-timeout",
        type=int,
        default=300,
        help="Default timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--min-timeout",
        type=int,
        default=60,
        help="Minimum allowed timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--max-timeout",
        type=int,
        default=600,
        help="Maximum allowed timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--orchestrator-config",
        type=str,
        required=False,
        default="{}",
        help="JSON-encoded subagent orchestrator configuration",
    )
    parser.add_argument(
        "--log-directory",
        type=str,
        required=False,
        default="",
        help="Path to log directory for subagent logs",
    )
    parser.add_argument(
        "--context-paths-file",
        type=str,
        required=False,
        default="",
        help="Path to JSON file containing parent context paths",
    )
    parser.add_argument(
        "--coordination-config-file",
        type=str,
        required=False,
        default="",
        help="Path to JSON file containing parent coordination config",
    )
    parser.add_argument(
        "--runtime-mode",
        type=str,
        required=False,
        default="isolated",
        help="Subagent runtime mode: isolated or inherited",
    )
    parser.add_argument(
        "--runtime-fallback-mode",
        type=str,
        required=False,
        default="",
        help="Optional fallback mode when isolated runtime is unavailable",
    )
    parser.add_argument(
        "--host-launch-prefix",
        type=str,
        required=False,
        default="[]",
        help="JSON-encoded command prefix for host-isolated launch in containerized runtimes",
    )
    parser.add_argument(
        "--delegation-directory",
        type=str,
        required=False,
        default="",
        help="Path to shared delegation directory for file-based container-to-host subagent launch (delegated mode).",
    )
    parser.add_argument(
        "--hook-dir",
        type=str,
        default=None,
        help="Optional path to directory for hook IPC files (PostToolUse injection).",
    )
    args = parser.parse_args()

    # Set global configuration
    _workspace_path = Path(args.workspace_path)
    _agent_temporary_workspace = args.agent_temporary_workspace or None
    _parent_agent_id = args.agent_id
    _orchestrator_id = args.orchestrator_id

    # Parse agent configs from file (avoids command line / env var length limits)
    _parent_agent_configs = []
    if args.agent_configs_file:
        try:
            _agent_configs_loaded_path: Path | None = None
            _parent_agent_configs, _agent_configs_loaded_path = _load_json_with_temp_workspace_fallback(
                args.agent_configs_file,
            )
            if not isinstance(_parent_agent_configs, list):
                _parent_agent_configs = [_parent_agent_configs]
            if _agent_configs_loaded_path and _agent_configs_loaded_path != Path(args.agent_configs_file):
                logger.info(
                    "[SubagentMCP] Loaded agent configs via temp workspace fallback: %s",
                    _agent_configs_loaded_path,
                )
            # Do NOT delete the file here. The MCP server process may start
            # after a delay (Docker, lazy launch) or be restarted, and early
            # deletion causes a race where the file is gone before it can be
            # read. The orchestrator owns cleanup via mcp_temp_dir.
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to load agent configs from {args.agent_configs_file}: {e}")
            _parent_agent_configs = []

    # Parse subagent orchestrator config
    try:
        orch_cfg_data = json.loads(args.orchestrator_config)
        if orch_cfg_data:
            _subagent_orchestrator_config = SubagentOrchestratorConfig.from_dict(orch_cfg_data)
    except json.JSONDecodeError:
        pass  # Keep default None

    # Set log directory
    _log_directory = args.log_directory if args.log_directory else None

    # Parse context paths from file (similar to agent configs, avoids length limits)
    _parent_context_paths = []
    if args.context_paths_file:
        try:
            _context_paths_loaded_path: Path | None = None
            _parent_context_paths, _context_paths_loaded_path = _load_json_with_temp_workspace_fallback(
                args.context_paths_file,
            )
            if not isinstance(_parent_context_paths, list):
                _parent_context_paths = []
            # Do NOT delete — see agent_configs_file comment above.
            if _context_paths_loaded_path and _context_paths_loaded_path != Path(args.context_paths_file):
                logger.info(
                    "[SubagentMCP] Loaded parent context paths via temp workspace fallback: %s",
                    _context_paths_loaded_path,
                )
            logger.info(f"[SubagentMCP] Loaded {len(_parent_context_paths)} parent context paths")
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to load context paths from {args.context_paths_file}: {e}")
            _parent_context_paths = []

    # Parse coordination config from file (similar to context paths)
    _parent_coordination_config = {}
    if args.coordination_config_file:
        try:
            _coord_cfg_loaded_path: Path | None = None
            _parent_coordination_config, _coord_cfg_loaded_path = _load_json_with_temp_workspace_fallback(
                args.coordination_config_file,
            )
            if not isinstance(_parent_coordination_config, dict):
                _parent_coordination_config = {}
            # Do NOT delete — see agent_configs_file comment above.
            if _coord_cfg_loaded_path and _coord_cfg_loaded_path != Path(args.coordination_config_file):
                logger.info(
                    "[SubagentMCP] Loaded parent coordination config via temp workspace fallback: %s",
                    _coord_cfg_loaded_path,
                )
            logger.info("[SubagentMCP] Loaded parent coordination config")
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to load coordination config from {args.coordination_config_file}: {e}")
            _parent_coordination_config = {}

    # Specialized subagent types are loaded lazily on first spawn_subagents call
    # by _ensure_specialized_types_loaded() scanning workspace/.massgen/subagent_types/.
    global _specialized_subagents, _subagent_types_loaded, _next_subagent_index
    _specialized_subagents = {}
    _subagent_types_loaded = False
    _next_subagent_index = 0

    # Set concurrency and timeout limits
    _max_concurrent = args.max_concurrent
    _default_timeout = args.default_timeout
    _min_timeout = args.min_timeout
    _max_timeout = args.max_timeout
    _subagent_runtime_mode = args.runtime_mode or "isolated"
    _subagent_runtime_fallback_mode = args.runtime_fallback_mode or None
    try:
        parsed_prefix = json.loads(args.host_launch_prefix)
        if isinstance(parsed_prefix, list) and all(isinstance(token, str) for token in parsed_prefix):
            _subagent_host_launch_prefix = parsed_prefix
        else:
            _subagent_host_launch_prefix = []
            logger.warning("[SubagentMCP] Invalid --host-launch-prefix payload; expected JSON list of strings")
    except json.JSONDecodeError:
        _subagent_host_launch_prefix = []
        logger.warning("[SubagentMCP] Failed to parse --host-launch-prefix JSON; defaulting to empty list")
    _delegation_directory = args.delegation_directory if args.delegation_directory else None

    # Set up signal handlers for graceful shutdown
    try:
        loop = asyncio.get_running_loop()
        _setup_signal_handlers(loop)
    except RuntimeError:
        pass  # No running loop yet, handlers will be set up later if needed
    except Exception as e:
        logger.warning(f"[SubagentMCP] Signal handler setup failed: {e}")

    # Register atexit handler as a fallback for cleanup
    atexit.register(_sync_cleanup)

    # Create the FastMCP server
    mcp = fastmcp.FastMCP("Subagent Spawning")

    # Attach hook middleware for PostToolUse injection if hook_dir is configured
    if args.hook_dir:
        from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

        mcp.add_middleware(MassGenHookMiddleware(Path(args.hook_dir)))
        logger.info("Hook middleware attached (hook_dir=%s)", args.hook_dir)

    @mcp.tool()
    def spawn_subagents(
        tasks: list[dict[str, Any]],
        background: bool = False,
        refine: bool = True,
        context_paths: list[str] | None = None,
        # NOTE: timeout_seconds parameter intentionally removed from MCP interface.
        # Allowing models to set custom timeouts could cause issues:
        # - Models might set very short timeouts and want to retry
        # - Subagents are blocking, so retries would be problematic
        # - Better to use the configured default from YAML (subagent_default_timeout)
        # timeout_seconds: Optional[int] = None,
    ) -> dict[str, Any]:
        f"""
        Spawn subagents to work on INDEPENDENT tasks in PARALLEL.

        CRITICAL RULES:
        1. Maximum {_max_concurrent} tasks per call (will error if exceeded)
        2. CONTEXT.md file MUST exist in workspace before calling this tool
        3. Tasks run SIMULTANEOUSLY - do NOT design tasks that depend on each other
        4. Each task dict MUST have "task". "context_paths" is optional (defaults to []).
        5. Parent workspace is mounted read-only by default (include_parent_workspace=True).
           Set include_parent_workspace=False for fully isolated research subagents.
           All mounted paths (parent workspace, context_paths) are always READ-ONLY.

        CONTEXT.MD REQUIREMENT:
        Before spawning subagents, you MUST create a CONTEXT.md file in the workspace describing
        the project/goal. This helps subagents understand what they're working on.
        Example CONTEXT.md content: "Building a Bob Dylan tribute website with bio, discography, timeline"

        PARALLEL EXECUTION WARNING:
        All tasks start at the same time! Do NOT create tasks like:
        - BAD: "Research content" then "Build website using researched content" (sequential dependency)
        - GOOD: "Research biography" and "Research discography" (independent, can run together)

        Args:
            tasks: List of task dicts (max {_max_concurrent}). Each MUST have:
                   - "task": (REQUIRED) string describing what to do
                   - "include_parent_workspace": (optional bool, default True) mount parent
                     workspace read-only. Set False for fully isolated research.
                   - "include_temp_workspace": (optional bool, default True) auto-mount the
                     shared reference directory (temp_workspaces) read-only. Contains
                     snapshots from all peer agents. Set False for fully isolated subagents
                     that don't need peer context.
                   - "context_paths": (optional) extra read-only paths beyond the parent
                     workspace. Use for peer workspace paths (from Available agent
                     workspaces section) or other allowed paths. Defaults to [].
                   - "subagent_id": (optional) custom identifier
                   - "context_files": (optional) files to copy into subagent workspace
            background: (optional) If True, spawn subagents in the background and return immediately.
                        Results will be automatically injected into your context when subagents complete.
                        Default is False (blocking - waits for all subagents to complete).
            refine: (optional) If True (default), allow multi-round coordination and refinement.
                    If False, return the first answer without iterative refinement (faster).
            context_paths: (optional) Top-level extra read-only paths applied to ALL tasks.
                           Merged with any per-task context_paths. Use this when all subagents
                           need the same peer workspace paths (e.g. temp_workspaces for evaluation).

        FILE ARTIFACTS:
        Subagents can ONLY write to their OWN workspace. Do NOT tell a subagent to save
        files into your workspace — it is mounted read-only to them.

        Correct pattern:
        1. Tell the subagent to save artifacts to its own workspace (no path prefix needed —
           relative paths work from the subagent's cwd).
        2. The spawn result always includes "workspace": "/abs/path/to/subagent/workspace".
        3. After the subagent completes, read artifacts from that path.

        Example task wording:
          WRONG: "Save screenshots to /parent/workspace/.massgen_scratch/verification/"
          RIGHT: "Save screenshots to verification/ in your workspace and list them in your answer."

        Then access: result["workspace"] + "/verification/"

        TIMEOUT HANDLING (for blocking mode, background=False):
        Subagents that timeout will attempt to recover any completed work:
        - "completed_but_timeout": Full answer recovered (success=True, use the answer)
        - "partial": Some work done but incomplete (check workspace for partial files)
        - "timeout": No recoverable work (check workspace anyway for any files)
        The "workspace" path is ALWAYS provided, even on timeout/error.

        Returns (background=False, blocking mode):
            {{
                "success": bool,
                "mode": "blocking",
                "results": [
                    {{
                        "subagent_id": "...",
                        "status": "completed" | "completed_but_timeout" | "partial" | "timeout" | "error",
                        "workspace": "/path/to/subagent/workspace",  # ALWAYS provided
                        "answer": "..." | null,  # May be recovered even on timeout
                        "execution_time_seconds": float,
                        "completion_percentage": int | null,  # Progress before timeout (0-100)
                        "token_usage": {{"input_tokens": N, "output_tokens": N}}
                    }}
                ],
                "summary": {{"total": N, "completed": N, "timeout": N}}
            }}

        Returns (background=True, background mode):
            {{
                "success": bool,
                "mode": "background",
                "subagents": [
                    {{
                        "subagent_id": "...",
                        "status": "running",
                        "workspace": "/path/to/subagent/workspace",
                        "status_file": "/path/to/status.json"  # For manual polling if needed
                    }}
                ],
                "note": "Results will be automatically injected when subagents complete."
            }}

        Examples:
            # FIRST: Create CONTEXT.md (REQUIRED)
            # write_file("CONTEXT.md", "Building a Bob Dylan tribute website with biography, discography, songs, and quotes pages")

            # BLOCKING: Independent parallel tasks (waits for completion)
            # Parent workspace is always mounted read-only by default.
            spawn_subagents(
                tasks=[
                    {{"task": "Research and write Bob Dylan biography to bio.md", "subagent_id": "bio"}},
                    {{"task": "Create discography table in discography.md", "subagent_id": "discog"}},
                    {{"task": "List 20 famous songs with years in songs.md", "subagent_id": "songs"}}
                ]
            )

            # BACKGROUND: Fully isolated research (no parent workspace, no peer snapshots)
            # FIRST: write_file("CONTEXT.md", "Building secure authentication system")
            spawn_subagents(
                tasks=[{{"task": "Research OAuth 2.0 best practices", "subagent_id": "oauth-research",
                         "include_parent_workspace": False,
                         "include_temp_workspace": False}}],
                background=True  # Returns immediately, result injected later
            )

            # Evaluate a peer's deliverable (path from Available agent workspaces)
            spawn_subagents(
                tasks=[{{"task": "Evaluate agent1's website", "subagent_id": "eval",
                         "context_paths": ["/abs/path/temp_workspaces/agent_a/agent1"]}}]
            )

            # WRONG: Sequential dependency (task 2 needs task 1's output)
            # spawn_subagents(tasks=[
            #     {{"task": "Research content"}},
            #     {{"task": "Build website using the researched content"}}  # CAN'T USE TASK 1's OUTPUT!
            # ])
        """
        try:
            manager = _get_manager()

            # Validate tasks
            if not tasks:
                return {
                    "success": False,
                    "operation": "spawn_subagents",
                    "error": "No tasks provided. Must provide at least one task.",
                }

            # Enforce hard limit on number of subagents
            if len(tasks) > _max_concurrent:
                return {
                    "success": False,
                    "operation": "spawn_subagents",
                    "error": f"Too many tasks: {len(tasks)} requested but maximum is {_max_concurrent}. " f"Please reduce to {_max_concurrent} or fewer tasks per spawn_subagents call.",
                }

            # Merge top-level context_paths into every task so callers can share
            # peer workspace mounts without repeating them per-task.
            top_level_paths: list[str] = context_paths or []
            if top_level_paths:
                merged_tasks = []
                for t in tasks:
                    t = dict(t)  # shallow copy — don't mutate caller's dicts
                    per_task = list(t.get("context_paths") or [])
                    # Append top-level paths, preserving per-task order and
                    # avoiding duplicates while keeping list semantics.
                    for p in top_level_paths:
                        if p not in per_task:
                            per_task.append(p)
                    t["context_paths"] = per_task
                    merged_tasks.append(t)
                tasks = merged_tasks

            # Auto-mount temp_workspace (shared reference dir) for all tasks unless
            # opted out via include_temp_workspace=False. Prepended so it's always
            # first, giving subagents immediate access to peer agent snapshots.
            if _agent_temporary_workspace:
                tw_str = str(_agent_temporary_workspace)
                merged_tasks = []
                for t in tasks:
                    if t.get("include_temp_workspace", True):
                        t = dict(t)
                        per_task = list(t.get("context_paths") or [])
                        if tw_str not in per_task:
                            per_task.insert(0, tw_str)
                        t["context_paths"] = per_task
                    merged_tasks.append(t)
                tasks = merged_tasks

            for i, task_config in enumerate(tasks):
                if "task" not in task_config:
                    return {
                        "success": False,
                        "operation": "spawn_subagents",
                        "error": f"Task at index {i} missing required 'task' field",
                    }
                # context_paths is now optional (defaults to []).
                # Parent workspace is always mounted unless include_parent_workspace=False.
                context_paths_val = task_config.get("context_paths", [])
                if context_paths_val is not None and not isinstance(context_paths_val, list):
                    actual_type = type(context_paths_val).__name__
                    return {
                        "success": False,
                        "operation": "spawn_subagents",
                        "error": (f"Task at index {i} has invalid 'context_paths' type: " f"expected list, got {actual_type}. " "Use [] for no extra paths or a list of path strings."),
                    }
                for idx, path_str in enumerate(context_paths_val or []):
                    if not isinstance(path_str, str):
                        return {
                            "success": False,
                            "operation": "spawn_subagents",
                            "error": (f"Task at index {i} context_paths[{idx}]: " f"expected string, got {type(path_str).__name__}"),
                        }
                if _workspace_path:
                    workspace_root = Path(_workspace_path)
                    for path_str in context_paths_val or []:
                        resolved = Path(path_str)
                        if not resolved.is_absolute():
                            resolved = workspace_root / path_str
                        if not resolved.exists():
                            return {
                                "success": False,
                                "operation": "spawn_subagents",
                                "error": (f"Task at index {i} has a non-existent context_path: '{path_str}'. " f"Your workspace is at: {_workspace_path}. " "Check the path exists first."),
                            }

            # Normalize task IDs using a global counter so IDs are unique
            # across multiple spawn_subagents calls (not just within one call).
            # _auto_id marks tasks whose ID was assigned here (not caller-provided),
            # so we can reclaim the counter slot if the spawn immediately fails.
            global _next_subagent_index
            normalized_tasks = []
            for t in tasks:
                if "subagent_id" in t:
                    task_id = t["subagent_id"]
                else:
                    task_id = f"subagent_{_next_subagent_index}"
                    _next_subagent_index += 1
                normalized_tasks.append(
                    {
                        **t,
                        "subagent_id": task_id,
                    },
                )

            task_ids = [str(t["subagent_id"]) for t in normalized_tasks]

            # Reject duplicate IDs in a single spawn request.
            seen_ids: set[str] = set()
            duplicate_ids: set[str] = set()
            for task_id in task_ids:
                if task_id in seen_ids:
                    duplicate_ids.add(task_id)
                seen_ids.add(task_id)
            if duplicate_ids:
                duplicate_list = ", ".join(sorted(duplicate_ids))
                return {
                    "success": False,
                    "operation": "spawn_subagents",
                    "error": (f"Duplicate subagent_id values in this spawn request: {duplicate_list}. " "Each task must use a unique subagent_id."),
                }

            # Reject IDs that are already running to avoid accidental double-spawn.
            existing_subagents = manager.list_subagents() or []
            running_ids = {str(entry.get("subagent_id", "")).strip() for entry in existing_subagents if isinstance(entry, dict) and str(entry.get("status", "")).lower() == "running"}
            running_ids.discard("")
            conflicting_running_ids = sorted(set(task_ids) & running_ids)
            if conflicting_running_ids:
                conflict_text = ", ".join(conflicting_running_ids)
                return {
                    "success": False,
                    "operation": "spawn_subagents",
                    "error": (f"Cannot spawn subagent_id already running: {conflict_text}. " "Use send_message_to_subagent() to steer the existing run, " "or wait/cancel it before spawning again."),
                }

            # Resolve specialized subagent types (lazy load on first call)
            _ensure_specialized_types_loaded()
            for t in normalized_tasks:
                subagent_type = t.get("subagent_type", "")
                if not subagent_type:
                    continue

                type_config = _specialized_subagents.get(subagent_type.lower())
                if not type_config:
                    available_types = sorted(_specialized_subagents.keys())
                    available_text = ", ".join(available_types) if available_types else "(none configured)"
                    return {
                        "success": False,
                        "operation": "spawn_subagents",
                        "error": (f"Unknown subagent_type '{subagent_type}' for task '{t['subagent_id']}'. " f"Available subagent types: {available_text}."),
                    }

                # Inject system_prompt from type definition
                if "system_prompt" not in t and type_config.get("system_prompt"):
                    t["system_prompt"] = type_config["system_prompt"]
                # Inject skills list for the manager to configure
                if "skills" not in t and type_config.get("skills"):
                    t["skills"] = type_config["skills"]
                logger.info(f"[SubagentMCP] Resolved subagent_type '{subagent_type}' for task {t['subagent_id']}")

            logger.info(f"[SubagentMCP] Spawning {len(normalized_tasks)} subagents: {task_ids}")

            if background:
                # BACKGROUND MODE: Spawn subagents in background and return immediately
                # Results will be injected via SubagentCompleteHook when they complete
                spawned = []
                for task_config in normalized_tasks:
                    # Task is passed as-is; context will be loaded from CONTEXT.md
                    info = manager.spawn_subagent_background(
                        task=task_config["task"],
                        subagent_id=task_config.get("subagent_id"),
                        context_files=task_config.get("context_files"),
                        context_paths=task_config.get("context_paths") or [],
                        include_parent_workspace=task_config.get("include_parent_workspace", True),
                        system_prompt=task_config.get("system_prompt"),
                        timeout_seconds=_default_timeout,
                        refine=refine,
                        skills=task_config.get("skills"),
                        subagent_type=task_config.get("subagent_type") or None,
                    )
                    # Clean up manager state for immediately-failed spawns
                    if info.get("status") == "error":
                        assigned_id = task_config.get("subagent_id", "")
                        manager.remove_immediately_failed_subagent(assigned_id)
                    spawned.append(info)

                # Save registry to filesystem
                _save_subagents_to_filesystem()

                return {
                    "success": True,
                    "operation": "spawn_subagents",
                    "mode": "background",
                    "subagents": spawned,
                    "note": "Results will be automatically injected when subagents complete.",
                }

            else:
                # BLOCKING MODE: Wait for all subagents to complete (existing behavior)
                started_at = datetime.now().isoformat()
                # Write spawning status to file for TUI polling (BEFORE starting)
                if _workspace_path is not None:
                    subagents_dir = _workspace_path / "subagents"
                    subagents_dir.mkdir(exist_ok=True)
                    status_file = subagents_dir / "_spawn_status.json"
                    spawn_status = {
                        "status": "spawning",
                        "started_at": started_at,
                        "subagents": [
                            {
                                "subagent_id": t["subagent_id"],
                                "task": t.get("task", ""),
                                "status": "running",
                                "progress_percent": 0,
                                "workspace": "",
                                "log_path": "",
                            }
                            for t in normalized_tasks
                        ],
                    }
                    status_file.write_text(json.dumps(spawn_status, indent=2))
                    logger.info(f"[SubagentMCP] Wrote spawn status to {status_file}")

                from massgen.utils import run_async_safely

                results = run_async_safely(
                    manager.spawn_parallel(
                        tasks=normalized_tasks,
                        timeout_seconds=_default_timeout,  # Use configured default, not model-specified
                        refine=refine,
                    ),
                )

                # Update status file with completion
                if _workspace_path is not None:
                    status_file = _workspace_path / "subagents" / "_spawn_status.json"
                    completed_status = {
                        "status": "completed",
                        "started_at": started_at,
                        "completed_at": datetime.now().isoformat(),
                        "subagents": [r.to_dict() for r in results],
                    }
                    status_file.write_text(json.dumps(completed_status, indent=2))

                # Save registry to filesystem
                _save_subagents_to_filesystem()

                # Compute summary
                completed = sum(1 for r in results if r.status in ("completed", "completed_but_timeout", "partial"))
                failed = sum(1 for r in results if r.status == "error")
                timeout = sum(1 for r in results if r.status in ("timeout", "completed_but_timeout"))
                all_success = all(r.success for r in results)

                return {
                    "success": all_success,
                    "operation": "spawn_subagents",
                    "mode": "blocking",
                    "results": [r.to_dict() for r in results],
                    "summary": {
                        "total": len(results),
                        "completed": completed,
                        "failed": failed,
                        "timeout": timeout,
                    },
                }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error spawning subagents: {e}")
            return {
                "success": False,
                "operation": "spawn_subagents",
                "error": str(e),
            }

    @mcp.tool()
    def list_subagents() -> dict[str, Any]:
        """
        List all subagents spawned by this agent with their current status.

        This includes subagents from the current turn and all previous turns
        in the current parent session (tracked via the registry file).

        Returns:
            Dictionary with:
            - success: bool
            - operation: str - "list_subagents"
            - subagents: list - Discovery/index view with id, status, workspace, task, session_id, continuable
              and optional `result` payload for completed in-memory subagents
            - count: int - Total number of subagents

        Example:
            result = list_subagents()
            for sub in result['subagents']:
                print(f"{sub['subagent_id']}: {sub['status']}")
                if sub['continuable']:
                    print(f"  Can continue with session_id: {sub['session_id']}")
        """
        try:
            manager = _get_manager()
            subagents = manager.list_subagents()

            return {
                "success": True,
                "operation": "list_subagents",
                "subagents": subagents,
                "count": len(subagents),
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error listing subagents: {e}")
            return {
                "success": False,
                "operation": "list_subagents",
                "error": str(e),
            }

    @mcp.tool()
    def continue_subagent(
        subagent_id: str,
        message: str,
        timeout_seconds: int | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        """
        Continue a previously spawned subagent with a new message.

        This allows you to:
        - Resume timed-out subagents with additional instructions
        - Follow up on completed subagents with refinement requests
        - Continue failed subagents after fixing issues
        - Have multi-turn conversations with any subagent

        The subagent's conversation history is automatically restored using
        the existing --session-id mechanism. The new message is appended to
        the conversation.

        Args:
            subagent_id: ID of the subagent to continue (from spawn_subagents or list_subagents)
            message: New message to send to the subagent
            timeout_seconds: Optional timeout override (uses default if not specified)
            background: If True, continue in background and return immediately

        Returns:
            Dictionary with subagent result.

            Blocking mode (background=False):
            {
                "success": bool,
                "subagent_id": "...",
                "status": "completed" | "timeout" | "error",
                "workspace": "/path/to/subagent/workspace",
                "answer": "..." | null,
                "execution_time_seconds": float,
                "token_usage": {"input_tokens": N, "output_tokens": N}
            }

            Background mode (background=True):
            {
                "success": true,
                "operation": "continue_subagent",
                "mode": "background",
                "subagents": [
                    {
                        "subagent_id": "...",
                        "status": "running",
                        "workspace": "...",
                        "status_file": "..."
                    }
                ]
            }

        Examples:
            # Resume a timed-out subagent with more time
            result = continue_subagent(
                subagent_id="research_oauth",
                message="Please continue where you left off and finish the research"
            )

            # Refine a completed subagent's answer
            result = continue_subagent(
                subagent_id="bio",
                message="Please add more details about Bob Dylan's early life in the biography"
            )

            # Ask follow-up questions
            result = continue_subagent(
                subagent_id="discog",
                message="What were the most commercially successful albums?"
            )
        """
        try:
            manager = _get_manager()

            # Validate inputs
            if not subagent_id or not subagent_id.strip():
                return {
                    "success": False,
                    "operation": "continue_subagent",
                    "error": "Missing required 'subagent_id' parameter",
                }

            if not message or not message.strip():
                return {
                    "success": False,
                    "operation": "continue_subagent",
                    "error": "Missing required 'message' parameter",
                }

            if background:
                info = manager.continue_subagent_background(
                    subagent_id=subagent_id,
                    new_message=message,
                    timeout_seconds=timeout_seconds,
                )
                if str(info.get("status", "")).lower() == "error" or info.get("error"):
                    return {
                        "success": False,
                        "operation": "continue_subagent",
                        "mode": "background",
                        "error": str(info.get("error") or "Failed to continue subagent in background"),
                        "subagents": [info],
                    }
                return {
                    "success": True,
                    "operation": "continue_subagent",
                    "mode": "background",
                    "subagents": [info],
                    "note": "Results will be automatically injected when subagent completes.",
                }

            # Use asyncio.run to execute the async method
            # This is safe because MCP tool handlers run in their own context
            from massgen.utils import run_async_safely

            result = run_async_safely(
                manager.continue_subagent(
                    subagent_id=subagent_id,
                    new_message=message,
                    timeout_seconds=timeout_seconds,
                ),
            )

            if not result.success:
                return {
                    "success": False,
                    "operation": "continue_subagent",
                    "mode": "blocking",
                    "error": result.error,
                    **result.to_dict(),
                }

            return {
                "success": True,
                "operation": "continue_subagent",
                "mode": "blocking",
                **result.to_dict(),
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error continuing subagent: {e}")
            return {
                "success": False,
                "operation": "continue_subagent",
                "error": str(e),
            }

    @mcp.tool()
    def send_message_to_subagent(
        subagent_id: str,
        message: str,
        target_agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send a runtime message to a currently running background subagent.

        Unlike continue_subagent (which resumes finished subagents), this delivers
        a message to a subagent that is CURRENTLY RUNNING. The message is injected
        into the subagent's next tool call or enforcement checkpoint.

        Use this to steer a background subagent's direction without waiting for it
        to finish — e.g., "focus on performance metrics" or "skip the CSS audit".

        Args:
            subagent_id: ID of the running subagent
            message: Message content to deliver
            target_agents: Optional list of inner agent IDs to target.
                None broadcasts to all inner agents within the subagent.
        """
        try:
            manager = _get_manager()

            if not subagent_id or not subagent_id.strip():
                return {
                    "success": False,
                    "operation": "send_message",
                    "error": "Missing required 'subagent_id' parameter",
                }

            if not message or not message.strip():
                return {
                    "success": False,
                    "operation": "send_message",
                    "error": "Missing required 'message' parameter",
                }

            success, error = manager.send_message_to_subagent(
                subagent_id,
                message,
                target_agents=target_agents,
            )
            result: dict[str, Any] = {
                "success": success,
                "subagent_id": subagent_id,
                "operation": "send_message",
            }
            if error:
                result["error"] = error
            return result

        except Exception as e:
            logger.error(f"[SubagentMCP] Error sending message to subagent: {e}")
            return {
                "success": False,
                "operation": "send_message",
                "error": str(e),
            }

    @mcp.tool()
    async def cancel_subagent(subagent_id: str) -> dict[str, Any]:
        """Cancel a running subagent.

        Internal handler called by the background tool delegate — not intended
        for direct model use. The model uses cancel_background_tool instead.

        Args:
            subagent_id: ID of the subagent to cancel
        """
        try:
            manager = _get_manager()

            if not subagent_id or not subagent_id.strip():
                return {
                    "success": False,
                    "operation": "cancel_subagent",
                    "error": "Missing required 'subagent_id' parameter",
                }

            result = await manager.cancel_subagent(subagent_id)
            if result.get("success"):
                _save_subagents_to_filesystem()
            return result

        except Exception as e:
            logger.error(f"[SubagentMCP] Error cancelling subagent: {e}")
            return {
                "success": False,
                "operation": "cancel_subagent",
                "error": str(e),
            }

    return mcp


async def _cleanup_on_shutdown():
    """Clean up subagent processes on shutdown."""
    if _manager is not None:
        logger.info("[SubagentMCP] Shutting down - cancelling active subagents...")
        cancelled = await _manager.cancel_all_subagents()
        if cancelled > 0:
            logger.info(f"[SubagentMCP] Cancelled {cancelled} subagent(s)")


def _setup_signal_handlers(loop: asyncio.AbstractEventLoop):
    """Set up signal handlers for graceful shutdown."""

    def handle_signal(signum, frame):
        logger.info(f"[SubagentMCP] Received signal {signum}, initiating shutdown...")
        # Schedule cleanup on the event loop
        loop.create_task(_cleanup_on_shutdown())

    # Handle SIGTERM (from process termination) and SIGINT (Ctrl+C)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def _sync_cleanup():
    """Synchronous cleanup for atexit handler."""
    if _manager is not None and _manager._active_processes:
        logger.info("[SubagentMCP] atexit cleanup - terminating active subagents...")
        for subagent_id, process in list(_manager._active_processes.items()):
            if process.returncode is None:
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"[SubagentMCP] Force killing {subagent_id}")
                        process.kill()
                except Exception as e:
                    logger.error(f"[SubagentMCP] Error terminating {subagent_id}: {e}")


if __name__ == "__main__":
    import asyncio

    import fastmcp

    asyncio.run(fastmcp.run(create_server))
