#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Subagent MCP Server for MassGen

This MCP server provides tools for spawning and managing subagents,
enabling agents to delegate tasks to independent agent instances
with fresh context and isolated workspaces.

Tools provided:
- spawn_subagents: Spawn one or more subagents (runs in parallel if multiple)
- list_subagents: List all spawned subagents with their status
- get_subagent_result: Get the result from a completed subagent
- check_subagent_status: Check status of a running subagent
"""

import argparse
import asyncio
import atexit
import json
import logging
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import fastmcp

from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SUBAGENT_DEFAULT_TIMEOUT, SubagentOrchestratorConfig

logger = logging.getLogger(__name__)

# Global storage for subagent manager (initialized per server instance)
_manager: Optional[SubagentManager] = None

# Server configuration
_workspace_path: Optional[Path] = None
_parent_agent_id: Optional[str] = None
_orchestrator_id: Optional[str] = None
_parent_agent_configs: List[Dict[str, Any]] = []
_subagent_orchestrator_config: Optional[SubagentOrchestratorConfig] = None
_log_directory: Optional[str] = None
_max_concurrent: int = 3
_default_timeout: int = SUBAGENT_DEFAULT_TIMEOUT
_min_timeout: int = 60
_max_timeout: int = 600
_parent_context_paths: List[Dict[str, str]] = []
_parent_coordination_config: Dict[str, Any] = {}


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

    registry = {
        "parent_agent_id": _parent_agent_id,
        "orchestrator_id": _orchestrator_id,
        "subagents": manager.list_subagents(),
    }

    registry_file = subagents_dir / "_registry.json"
    registry_file.write_text(json.dumps(registry, indent=2))


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create and configure the subagent MCP server."""
    global _workspace_path, _parent_agent_id, _orchestrator_id, _parent_agent_configs
    global _subagent_orchestrator_config, _log_directory, _parent_context_paths
    global _max_concurrent, _default_timeout, _min_timeout, _max_timeout
    global _parent_coordination_config

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
    args = parser.parse_args()

    # Set global configuration
    _workspace_path = Path(args.workspace_path)
    _parent_agent_id = args.agent_id
    _orchestrator_id = args.orchestrator_id

    # Parse agent configs from file (avoids command line / env var length limits)
    _parent_agent_configs = []
    if args.agent_configs_file:
        try:
            with open(args.agent_configs_file) as f:
                _parent_agent_configs = json.load(f)
            if not isinstance(_parent_agent_configs, list):
                _parent_agent_configs = [_parent_agent_configs]
            # Clean up the temp file after reading
            try:
                os.unlink(args.agent_configs_file)
            except OSError:
                pass  # Ignore if file already deleted
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
            with open(args.context_paths_file) as f:
                _parent_context_paths = json.load(f)
            if not isinstance(_parent_context_paths, list):
                _parent_context_paths = []
            # Clean up the temp file after reading
            try:
                os.unlink(args.context_paths_file)
            except OSError:
                pass  # Ignore if file already deleted
            logger.info(f"[SubagentMCP] Loaded {len(_parent_context_paths)} parent context paths")
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to load context paths from {args.context_paths_file}: {e}")
            _parent_context_paths = []

    # Parse coordination config from file (similar to context paths)
    _parent_coordination_config = {}
    if args.coordination_config_file:
        try:
            with open(args.coordination_config_file) as f:
                _parent_coordination_config = json.load(f)
            if not isinstance(_parent_coordination_config, dict):
                _parent_coordination_config = {}
            # Clean up the temp file after reading
            try:
                os.unlink(args.coordination_config_file)
            except OSError:
                pass  # Ignore if file already deleted
            logger.info("[SubagentMCP] Loaded parent coordination config")
        except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to load coordination config from {args.coordination_config_file}: {e}")
            _parent_coordination_config = {}

    # Set concurrency and timeout limits
    _max_concurrent = args.max_concurrent
    _default_timeout = args.default_timeout
    _min_timeout = args.min_timeout
    _max_timeout = args.max_timeout

    # Set up signal handlers for graceful shutdown
    try:
        loop = asyncio.get_running_loop()
        _setup_signal_handlers(loop)
    except RuntimeError:
        pass  # No running loop yet, handlers will be set up later if needed

    # Register atexit handler as a fallback for cleanup
    atexit.register(_sync_cleanup)

    # Create the FastMCP server
    mcp = fastmcp.FastMCP("Subagent Spawning")

    @mcp.tool()
    def spawn_subagents(
        tasks: List[Dict[str, Any]],
        async_: bool = False,
        refine: bool = True,
        # NOTE: timeout_seconds parameter intentionally removed from MCP interface.
        # Allowing models to set custom timeouts could cause issues:
        # - Models might set very short timeouts and want to retry
        # - Subagents are blocking, so retries would be problematic
        # - Better to use the configured default from YAML (subagent_default_timeout)
        # timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        f"""
        Spawn subagents to work on INDEPENDENT tasks in PARALLEL.

        CRITICAL RULES:
        1. Maximum {_max_concurrent} tasks per call (will error if exceeded)
        2. CONTEXT.md file MUST exist in workspace before calling this tool
        3. Tasks run SIMULTANEOUSLY - do NOT design tasks that depend on each other
        4. Each task dict MUST have a "task" field (not "description" or "id")

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
                   - "subagent_id": (optional) custom identifier
                   - "context_files": (optional) files to copy into subagent workspace
                   - "context_paths": (optional) files/dirs to mount read-only. Use "./" for entire parent workspace
            async_: (optional) If True, spawn subagents in the background and return immediately.
                    Results will be automatically injected into your context when subagents complete.
                    Default is False (blocking - waits for all subagents to complete).
            refine: (optional) If True (default), allow multi-round coordination and refinement.
                    If False, return the first answer without iterative refinement (faster).

        TIMEOUT HANDLING (for blocking mode, async_=False):
        Subagents that timeout will attempt to recover any completed work:
        - "completed_but_timeout": Full answer recovered (success=True, use the answer)
        - "partial": Some work done but incomplete (check workspace for partial files)
        - "timeout": No recoverable work (check workspace anyway for any files)
        The "workspace" path is ALWAYS provided, even on timeout/error.

        Returns (async_=False, blocking mode):
            {{
                "success": bool,
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

        Returns (async_=True, background mode):
            {{
                "success": bool,
                "mode": "async",
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
            spawn_subagents(
                tasks=[
                    {{"task": "Research and write Bob Dylan biography to bio.md", "subagent_id": "bio"}},
                    {{"task": "Create discography table in discography.md", "subagent_id": "discog"}},
                    {{"task": "List 20 famous songs with years in songs.md", "subagent_id": "songs"}}
                ]
            )

            # ASYNC: Spawn background subagent and continue working
            # FIRST: write_file("CONTEXT.md", "Building secure authentication system")
            spawn_subagents(
                tasks=[{{"task": "Research OAuth 2.0 best practices", "subagent_id": "oauth-research"}}],
                async_=True  # Returns immediately, result injected later
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

            for i, task_config in enumerate(tasks):
                if "task" not in task_config:
                    return {
                        "success": False,
                        "operation": "spawn_subagents",
                        "error": f"Task at index {i} missing required 'task' field",
                    }

            # Normalize task IDs
            normalized_tasks = []
            for i, t in enumerate(tasks):
                task_id = t.get("subagent_id", f"subagent_{i}")
                normalized_tasks.append(
                    {
                        **t,
                        "subagent_id": task_id,
                    },
                )

            task_ids = [t["subagent_id"] for t in normalized_tasks]
            logger.info(f"[SubagentMCP] Spawning {len(normalized_tasks)} subagents: {task_ids}")

            # Branch based on async mode
            if async_:
                # ASYNC MODE: Spawn subagents in background and return immediately
                # Results will be injected via SubagentCompleteHook when they complete
                spawned = []
                for task_config in normalized_tasks:
                    # Task is passed as-is; context will be loaded from CONTEXT.md
                    info = manager.spawn_subagent_background(
                        task=task_config["task"],
                        subagent_id=task_config.get("subagent_id"),
                        context_files=task_config.get("context_files"),
                        context_paths=task_config.get("context_paths"),
                        timeout_seconds=_default_timeout,
                        refine=refine,
                    )
                    spawned.append(info)

                # Save registry to filesystem
                _save_subagents_to_filesystem()

                return {
                    "success": True,
                    "operation": "spawn_subagents",
                    "mode": "async",
                    "subagents": spawned,
                    "note": "Results will be automatically injected when subagents complete.",
                }

            else:
                # BLOCKING MODE: Wait for all subagents to complete (existing behavior)
                # Write spawning status to file for TUI polling (BEFORE starting)
                if _workspace_path is not None:
                    subagents_dir = _workspace_path / "subagents"
                    subagents_dir.mkdir(exist_ok=True)
                    status_file = subagents_dir / "_spawn_status.json"
                    spawn_status = {
                        "status": "spawning",
                        "started_at": datetime.now().isoformat(),
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
                        "started_at": spawn_status.get("started_at", ""),
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
    def list_subagents() -> Dict[str, Any]:
        """
        List all subagents spawned by this agent with their current status.

        This includes subagents from the current turn and all previous turns
        in the current parent session (tracked via the registry file).

        Returns:
            Dictionary with:
            - success: bool
            - operation: str - "list_subagents"
            - subagents: list - List of subagent info with id, status, workspace, task, session_id, continuable
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
    def get_subagent_costs() -> Dict[str, Any]:
        """
        Get aggregated cost summary for all subagents spawned by this agent.

        Returns:
            Dictionary with:
            - success: bool
            - operation: str - "get_subagent_costs"
            - total_subagents: int - Number of subagents spawned
            - total_input_tokens: int - Sum of input tokens across all subagents
            - total_output_tokens: int - Sum of output tokens across all subagents
            - total_estimated_cost: float - Sum of estimated costs
            - subagents: list - Per-subagent cost breakdown

        Example:
            costs = get_subagent_costs()
            print(f"Total subagent cost: ${costs['total_estimated_cost']:.4f}")
        """
        try:
            manager = _get_manager()
            summary = manager.get_subagent_costs_summary()

            return {
                "success": True,
                "operation": "get_subagent_costs",
                **summary,
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error getting subagent costs: {e}")
            return {
                "success": False,
                "operation": "get_subagent_costs",
                "error": str(e),
            }

    @mcp.tool()
    def check_subagent_status(subagent_id: str) -> Dict[str, Any]:
        """
        Check the current status of a subagent (especially useful for background subagents).

        Use this to monitor progress of subagents spawned in non-blocking mode.

        Args:
            subagent_id: ID of the subagent to check

        Returns:
            Dictionary with status information:
            - success: bool
            - operation: str - "check_subagent_status"
            - subagent_id: str - The subagent ID
            - status: str - "pending", "running", "completed", "failed", or "timeout"
            - task: str - The task description
            - progress: str - Progress message (if available)
            - started_at: str - ISO timestamp
            - updated_at: str - ISO timestamp
            - completed_at: str - ISO timestamp (if finished)
            - error: str - Error message (if failed)

        Example:
            status = check_subagent_status("research_oauth")
            if status['status'] == 'completed':
                result = get_subagent_result("research_oauth")
        """
        try:
            manager = _get_manager()
            status = manager.get_subagent_status(subagent_id)

            if status is None:
                return {
                    "success": False,
                    "operation": "check_subagent_status",
                    "error": f"Subagent not found: {subagent_id}",
                }

            return {
                "success": True,
                "operation": "check_subagent_status",
                **status,
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error checking subagent status: {e}")
            return {
                "success": False,
                "operation": "check_subagent_status",
                "error": str(e),
            }

    @mcp.tool()
    def get_subagent_result(subagent_id: str) -> Dict[str, Any]:
        """
        Get the result from a previously spawned subagent.

        Use this to retrieve results if you need to check on a subagent later.
        For background subagents, first check status with check_subagent_status().

        Args:
            subagent_id: ID of the subagent to get results for

        Returns:
            Dictionary with subagent result (same format as spawn_subagents results)

        Example:
            result = get_subagent_result("research_oauth")
            if result['success']:
                print(result['answer'])
        """
        try:
            manager = _get_manager()
            result = manager.get_subagent_result(subagent_id)

            if result is None:
                return {
                    "success": False,
                    "operation": "get_subagent_result",
                    "error": f"Subagent not found: {subagent_id}",
                }

            return {
                "success": True,
                "operation": "get_subagent_result",
                **result.to_dict(),
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error getting subagent result: {e}")
            return {
                "success": False,
                "operation": "get_subagent_result",
                "error": str(e),
            }

    @mcp.tool()
    def continue_subagent(
        subagent_id: str,
        message: str,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
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

        Returns:
            Dictionary with subagent result (same format as spawn_subagents results):
            {
                "success": bool,
                "subagent_id": "...",
                "status": "completed" | "timeout" | "error",
                "workspace": "/path/to/subagent/workspace",
                "answer": "..." | null,
                "execution_time_seconds": float,
                "token_usage": {"input_tokens": N, "output_tokens": N}
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
                    "error": result.error,
                    **result.to_dict(),
                }

            return {
                "success": True,
                "operation": "continue_subagent",
                **result.to_dict(),
            }

        except Exception as e:
            logger.error(f"[SubagentMCP] Error continuing subagent: {e}")
            return {
                "success": False,
                "operation": "continue_subagent",
                "error": str(e),
            }

    return mcp


async def _cleanup_on_shutdown():
    """Clean up subagent processes on shutdown."""
    global _manager
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
    global _manager
    if _manager is not None and _manager._active_processes:
        logger.info("[SubagentMCP] atexit cleanup - terminating active subagents...")
        for subagent_id, process in list(_manager._active_processes.items()):
            if process.returncode is None:
                try:
                    process.terminate()
                    logger.info(f"[SubagentMCP] Terminated subagent {subagent_id}")
                except Exception as e:
                    logger.error(f"[SubagentMCP] Error terminating {subagent_id}: {e}")


if __name__ == "__main__":
    import asyncio

    import fastmcp

    asyncio.run(fastmcp.run(create_server))
