# -*- coding: utf-8 -*-
"""Standalone MCP server that wraps MassGen custom tools.

This module creates a FastMCP server from a ToolManager's registered tools,
allowing any CLI-based backend (Codex, etc.) to access MassGen custom tools
via stdio MCP transport.

Usage (launched by backend):
    fastmcp run massgen/mcp_tools/custom_tools_server.py:create_server -- \
        --tool-specs /path/to/tool_specs.json \
        --allowed-paths /workspace

The tool_specs.json file is written by the backend before launch and contains
the serialized tool configurations needed to reconstruct the ToolManager.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import fastmcp

logger = logging.getLogger(__name__)


BACKGROUND_TOOL_START_NAME = "custom_tool__start_background_tool"
BACKGROUND_TOOL_STATUS_NAME = "custom_tool__get_background_tool_status"
BACKGROUND_TOOL_RESULT_NAME = "custom_tool__get_background_tool_result"
BACKGROUND_TOOL_CANCEL_NAME = "custom_tool__cancel_background_tool"
BACKGROUND_TOOL_LIST_NAME = "custom_tool__list_background_tools"
BACKGROUND_TOOL_WAIT_NAME = "custom_tool__wait_for_background_tool"
BACKGROUND_TOOL_MANAGEMENT_NAMES = {
    BACKGROUND_TOOL_START_NAME,
    BACKGROUND_TOOL_STATUS_NAME,
    BACKGROUND_TOOL_RESULT_NAME,
    BACKGROUND_TOOL_CANCEL_NAME,
    BACKGROUND_TOOL_LIST_NAME,
    BACKGROUND_TOOL_WAIT_NAME,
}
BACKGROUND_TOOL_TERMINAL_STATUSES = {"completed", "error", "cancelled"}
BACKGROUND_CONTROL_MODES = {"background"}
FOREGROUND_CONTROL_MODES = {"foreground", "blocking", "sync"}
BACKGROUND_TOOL_WAIT_DEFAULT_TIMEOUT_SECONDS = 30.0
BACKGROUND_TOOL_WAIT_MAX_TIMEOUT_SECONDS = 600.0
BACKGROUND_TOOL_WAIT_POLL_INTERVAL_SECONDS = 0.2


def _normalize_background_target_tool_name(tool_name: str) -> str:
    """Normalize target tool names across custom and MCP naming styles."""
    normalized = (tool_name or "").strip()
    massgen_prefix = "mcp__massgen_custom_tools__"
    if normalized.startswith(massgen_prefix):
        normalized = normalized[len(massgen_prefix) :]
    return normalized


def _is_default_media_background_tool(tool_name: str) -> bool:
    """Return True for media tools that should default to background execution."""
    normalized = _normalize_background_target_tool_name(tool_name)
    return normalized in {
        "read_media",
        "generate_media",
        "custom_tool__read_media",
        "custom_tool__generate_media",
    }


def _is_explicit_foreground_request(arguments: Dict[str, Any]) -> bool:
    """Return True when args explicitly request foreground/blocking behavior."""
    if arguments.get("background") is False:
        return True
    if arguments.get("run_in_background") is False:
        return True
    mode = arguments.get("mode")
    return isinstance(mode, str) and mode.lower() in FOREGROUND_CONTROL_MODES


def _should_auto_background_execution(tool_name: str, arguments: Dict[str, Any]) -> bool:
    """Return True when args request automatic background scheduling."""
    if not isinstance(arguments, dict):
        return False
    if _is_explicit_foreground_request(arguments):
        return False
    if _is_default_media_background_tool(tool_name):
        return True
    mode = arguments.get("mode")
    mode_is_background = isinstance(mode, str) and mode.lower() in BACKGROUND_CONTROL_MODES
    return arguments.get("background") is True or mode_is_background


def _strip_background_control_args(
    arguments: Dict[str, Any],
    control_args_to_strip: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Strip background control args before normal tool execution.

    Args:
        arguments: Raw tool arguments.
        control_args_to_strip: Optional explicit set of control arg names to strip.
            When omitted, strips all known background control fields for backwards
            compatibility. Callers should pass synthetic-only controls when a tool
            defines real parameters like `background`.
    """
    controls = {"mode", "background", "run_in_background"} if control_args_to_strip is None else set(control_args_to_strip)
    cleaned = dict(arguments)
    if "background" in controls:
        cleaned.pop("background", None)
    if "run_in_background" in controls:
        cleaned.pop("run_in_background", None)
    if "mode" in controls:
        mode = cleaned.get("mode")
        if mode is None or (isinstance(mode, str) and mode.lower() in BACKGROUND_CONTROL_MODES):
            cleaned.pop("mode", None)
    return cleaned


@dataclass
class BackgroundToolJob:
    """Runtime state for a background tool execution."""

    job_id: str
    tool_name: str
    tool_type: str
    arguments: Dict[str, Any]
    status: str
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None


class BackgroundToolManager:
    """Background lifecycle manager for custom_tools_server."""

    def __init__(
        self,
        tool_manager: Any,
        execution_context: Dict[str, Any],
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._execution_context = execution_context
        self._mcp_servers = self._filter_background_mcp_servers(mcp_servers or [])
        self._mcp_client = None
        self._mcp_initialized = False
        self._jobs: Dict[str, BackgroundToolJob] = {}
        self._tasks: Dict[str, asyncio.Task[Any]] = {}
        self._wait_seen_job_ids: set[str] = set()

    @staticmethod
    def _filter_background_mcp_servers(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop unsupported/recursive servers for background execution."""
        filtered: List[Dict[str, Any]] = []
        for server in servers:
            if not isinstance(server, dict):
                continue
            name = server.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if name == "massgen_custom_tools":
                continue
            if server.get("type") == "sdk":
                continue
            if "__sdk_server__" in server:
                continue
            filtered.append(server.copy())
        return filtered

    @staticmethod
    def _format_unix_timestamp(timestamp: Optional[float]) -> Optional[str]:
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp).isoformat()

    @staticmethod
    def _normalize_mcp_tool_name(tool_name: str) -> str:
        name = (tool_name or "").strip()
        if name.startswith("mcp__"):
            return name
        if "/" in name:
            server, tool = name.split("/", 1)
            if server and tool:
                return f"mcp__{server}__{tool}"
        return name

    def _is_background_management_tool(self, tool_name: str) -> bool:
        return tool_name in BACKGROUND_TOOL_MANAGEMENT_NAMES

    def _resolve_target(self, tool_name: str) -> Optional[Tuple[str, str]]:
        """Resolve requested target to (tool_type, effective_tool_name)."""
        raw_name = (tool_name or "").strip()
        if not raw_name:
            return None
        if raw_name in {"new_answer", "vote", "stop"}:
            return None
        if self._is_background_management_tool(raw_name):
            return None

        massgen_prefix = "mcp__massgen_custom_tools__"
        if raw_name.startswith(massgen_prefix):
            custom_name = raw_name[len(massgen_prefix) :]
            if custom_name in self._tool_manager.registered_tools:
                return ("custom", custom_name)

        if raw_name.startswith("massgen_custom_tools/"):
            _, custom_name = raw_name.split("/", 1)
            if custom_name in self._tool_manager.registered_tools:
                return ("custom", custom_name)

        if raw_name in self._tool_manager.registered_tools:
            return ("custom", raw_name)

        normalized_mcp = self._normalize_mcp_tool_name(raw_name)
        if normalized_mcp.startswith("mcp__"):
            return ("mcp", normalized_mcp)

        return None

    def _validate_start_prerequisites(self, tool_name: str) -> Optional[str]:
        """Return an error string when background start prerequisites are missing."""
        if not _is_default_media_background_tool(tool_name):
            return None

        workspace_path = self._execution_context.get("agent_cwd")
        try:
            from massgen.context.task_context import TaskContextError, load_task_context

            load_task_context(workspace_path, required=True)
        except TaskContextError as exc:
            return f"CONTEXT.md must be created before starting {tool_name} in background. {exc}"

        return None

    def _serialize_job(self, job: BackgroundToolJob, include_result: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "job_id": job.job_id,
            "tool_name": job.tool_name,
            "tool_type": job.tool_type,
            "status": job.status,
            "created_at": self._format_unix_timestamp(job.created_at),
            "started_at": self._format_unix_timestamp(job.started_at),
            "completed_at": self._format_unix_timestamp(job.completed_at),
        }
        if include_result and job.result is not None:
            payload["result"] = job.result
        if job.error:
            payload["error"] = job.error
        return payload

    @staticmethod
    def _extract_text_from_output_blocks(blocks: List[Any]) -> str:
        text_parts: List[str] = []
        for block in blocks:
            if isinstance(block, dict):
                if block.get("data") is not None:
                    text_parts.append(str(block.get("data")))
                    continue
                if block.get("text") is not None:
                    text_parts.append(str(block.get("text")))
                    continue
                if block.get("content") is not None:
                    text_parts.append(str(block.get("content")))
                    continue
            data = getattr(block, "data", None)
            if data is not None:
                text_parts.append(str(data))
                continue
            text = getattr(block, "text", None)
            if text is not None:
                text_parts.append(str(text))
                continue
            content = getattr(block, "content", None)
            if content is not None:
                text_parts.append(str(content))
        return "\n".join(part for part in text_parts if part).strip()

    @classmethod
    def _extract_text_from_mcp_content(cls, content: Any) -> str:
        if content is None:
            return ""
        blocks = content if isinstance(content, list) else [content]
        return cls._extract_text_from_output_blocks(blocks)

    async def _run_custom_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        tool_request = {"name": tool_name, "input": arguments}
        final_result = None
        async for result in self._tool_manager.execute_tool(
            tool_request,
            self._execution_context,
        ):
            final_result = result

        if final_result is None:
            return "Tool executed successfully"

        output_blocks = getattr(final_result, "output_blocks", None)
        if isinstance(output_blocks, list):
            text = self._extract_text_from_output_blocks(output_blocks)
            if text:
                return text

        if hasattr(final_result, "model_dump"):
            dumped = final_result.model_dump()
            text = self._extract_text_from_output_blocks(dumped.get("output_blocks", []))
            if text:
                return text
            return json.dumps(dumped, default=str)

        if hasattr(final_result, "__dict__"):
            dumped = final_result.__dict__
            text = self._extract_text_from_output_blocks(dumped.get("output_blocks", []))
            if text:
                return text
            return json.dumps(dumped, default=str)

        return str(final_result)

    async def _get_mcp_client(self):
        if self._mcp_client is not None:
            return self._mcp_client
        if self._mcp_initialized:
            return None

        self._mcp_initialized = True
        if not self._mcp_servers:
            return None

        from massgen.mcp_tools.backend_utils import MCPResourceManager

        try:
            self._mcp_client = await MCPResourceManager.setup_mcp_client(
                servers=self._mcp_servers,
                allowed_tools=None,
                exclude_tools=None,
                circuit_breaker=None,
                timeout_seconds=300,
                backend_name="massgen_custom_tools_server",
                agent_id=str(self._execution_context.get("agent_id", "unknown")),
            )
            return self._mcp_client
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to initialize MCP client for background manager: %s",
                e,
                exc_info=True,
            )
            self._mcp_client = None
            return None

    async def _run_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        client = await self._get_mcp_client()
        if client is None:
            return ("Error: MCP client not available for background execution", True)

        try:
            result = await client.call_tool(tool_name, arguments)
        except Exception as e:  # noqa: BLE001
            return (f"Error: {e}", True)

        content = getattr(result, "content", None)
        text = self._extract_text_from_mcp_content(content)
        return (text or str(result), False)

    async def _run_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return

        job.started_at = time.time()
        try:
            if job.tool_type == "custom":
                result = await self._run_custom_tool(job.tool_name, job.arguments)
                job.status = "completed"
                job.result = result
            elif job.tool_type == "mcp":
                result, is_error = await self._run_mcp_tool(job.tool_name, job.arguments)
                if is_error:
                    job.status = "error"
                    job.error = result
                else:
                    job.status = "completed"
                    job.result = result
            else:
                raise ValueError(f"Unsupported background tool type: {job.tool_type}")
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = job.error or "Background tool execution cancelled"
            raise
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = f"Background tool failed: {e}"
            logger.warning(
                "Background tool %s failed: %s",
                job.tool_name,
                e,
                exc_info=True,
            )
        finally:
            job.completed_at = time.time()
            self._tasks.pop(job_id, None)

    async def start(self, tool_name: str, arguments: Optional[Any] = None) -> Dict[str, Any]:
        """Start background execution for a custom or MCP target tool."""
        from massgen.utils.tool_argument_normalization import (
            normalize_json_object_argument,
        )

        target_args_raw = {} if arguments is None else arguments
        try:
            target_args, decode_passes = normalize_json_object_argument(
                target_args_raw,
                field_name="arguments",
            )
        except ValueError:
            return {"success": False, "error": "arguments must be a JSON object"}
        if decode_passes > 1:
            logger.info(
                "Normalized %s decode passes for background start arguments (%s)",
                decode_passes,
                tool_name,
            )

        resolved = self._resolve_target(tool_name)
        if resolved is None:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' is not available for background execution",
            }

        tool_type, effective_tool_name = resolved
        prereq_error = self._validate_start_prerequisites(effective_tool_name)
        if prereq_error:
            return {"success": False, "error": prereq_error}

        job_id = f"bgtool_{uuid.uuid4().hex[:12]}"
        job = BackgroundToolJob(
            job_id=job_id,
            tool_name=effective_tool_name,
            tool_type=tool_type,
            arguments=dict(target_args),
            status="running",
            created_at=time.time(),
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(
            self._run_job(job_id),
            name=f"background_tool:{effective_tool_name}:{job_id}",
        )

        payload = self._serialize_job(job)
        payload.update(
            {
                "success": True,
                "message": f"Started {effective_tool_name} in background",
            },
        )
        return payload

    def get_status(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get((job_id or "").strip())
        if job is None:
            return {"success": False, "error": f"Background job not found: {job_id}"}
        payload = self._serialize_job(job)
        payload["success"] = True
        return payload

    def get_result(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get((job_id or "").strip())
        if job is None:
            return {"success": False, "error": f"Background job not found: {job_id}"}
        ready = job.status in BACKGROUND_TOOL_TERMINAL_STATUSES
        payload = self._serialize_job(job, include_result=True)
        payload.update({"success": True, "ready": ready})
        if not ready:
            payload["message"] = "Background tool still running"
        return payload

    def cancel(self, job_id: str) -> Dict[str, Any]:
        normalized = (job_id or "").strip()
        if not normalized:
            return {"success": False, "error": "job_id is required"}
        job = self._jobs.get(normalized)
        if job is None:
            return {"success": False, "error": f"Background job not found: {normalized}"}

        task = self._tasks.get(normalized)
        if task and not task.done():
            job.status = "cancelled"
            job.error = "Cancelled by user request"
            task.cancel()

        payload = self._serialize_job(job)
        payload["success"] = True
        return payload

    def list_jobs(self, include_all: bool = False) -> Dict[str, Any]:
        jobs = [self._serialize_job(job) for job in self._jobs.values() if include_all or job.status not in BACKGROUND_TOOL_TERMINAL_STATUSES]
        jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
        return {
            "success": True,
            "count": len(jobs),
            "include_all": include_all,
            "jobs": jobs,
        }

    @staticmethod
    def _coerce_wait_timeout(timeout_seconds: Optional[float]) -> float:
        """Normalize wait timeout to a safe bounded value."""
        if timeout_seconds is None:
            return BACKGROUND_TOOL_WAIT_DEFAULT_TIMEOUT_SECONDS
        try:
            coerced = float(timeout_seconds)
        except (TypeError, ValueError):
            return BACKGROUND_TOOL_WAIT_DEFAULT_TIMEOUT_SECONDS
        if coerced < 0:
            return 0.0
        return min(coerced, BACKGROUND_TOOL_WAIT_MAX_TIMEOUT_SECONDS)

    def _next_waitable_job(self) -> Optional[BackgroundToolJob]:
        """Get the next unseen terminal job for wait calls."""
        candidates = [job for job in self._jobs.values() if job.status in BACKGROUND_TOOL_TERMINAL_STATUSES and job.job_id not in self._wait_seen_job_ids]
        if not candidates:
            return None
        candidates.sort(
            key=lambda job: (
                job.completed_at if job.completed_at is not None else job.created_at,
                job.created_at,
            ),
        )
        return candidates[0]

    async def wait_for_next_completion(self, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Block until the next unseen terminal job is available or timeout elapses."""
        timeout = self._coerce_wait_timeout(timeout_seconds)
        started_at = time.time()

        while True:
            ready_job = self._next_waitable_job()
            if ready_job is not None:
                self._wait_seen_job_ids.add(ready_job.job_id)
                payload = self._serialize_job(ready_job, include_result=True)
                payload.update(
                    {
                        "success": True,
                        "ready": True,
                        "waited_seconds": round(time.time() - started_at, 3),
                    },
                )
                return payload

            elapsed = time.time() - started_at
            if elapsed >= timeout:
                return {
                    "success": True,
                    "ready": False,
                    "timed_out": True,
                    "waited_seconds": round(elapsed, 3),
                    "message": "No background tool completed before timeout",
                }

            sleep_seconds = min(
                BACKGROUND_TOOL_WAIT_POLL_INTERVAL_SECONDS,
                max(timeout - elapsed, 0.0),
            )
            if sleep_seconds <= 0:
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(sleep_seconds)

    async def shutdown(self) -> None:
        running_tasks: List[asyncio.Task[Any]] = []
        for job_id, task in list(self._tasks.items()):
            if task.done():
                continue
            job = self._jobs.get(job_id)
            if job:
                job.status = "cancelled"
                job.error = "Cancelled during server shutdown"
            task.cancel()
            running_tasks.append(task)

        if running_tasks:
            await asyncio.gather(*running_tasks, return_exceptions=True)

        self._tasks.clear()

        if self._mcp_client is not None:
            try:
                await self._mcp_client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._mcp_client = None


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from custom tool specs.

    Reads tool specifications from a JSON file (passed via --tool-specs)
    and registers each as an MCP tool backed by the actual Python function.
    """
    parser = argparse.ArgumentParser(description="MassGen Custom Tools MCP Server")
    parser.add_argument(
        "--tool-specs",
        type=str,
        required=True,
        help="Path to JSON file containing tool specifications",
    )
    parser.add_argument(
        "--allowed-paths",
        type=str,
        nargs="*",
        default=[],
        help="Allowed filesystem paths for tool execution",
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        default="unknown",
        help="Agent ID for execution context",
    )
    args = parser.parse_args()

    # Load tool specs
    specs_path = Path(args.tool_specs)
    if not specs_path.exists():
        logger.error(f"Tool specs file not found: {specs_path}")
        return fastmcp.FastMCP("massgen_custom_tools")

    with open(specs_path) as f:
        tool_specs = json.load(f)

    # Import ToolManager and reconstruct tools
    # Add project root to path so imports work
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from massgen.tool._manager import ToolManager

    tool_manager = ToolManager()

    # Register tools from specs using the same logic as _register_custom_tools
    custom_tools_config = tool_specs.get("custom_tools", [])
    for tool_config in custom_tools_config:
        try:
            if not isinstance(tool_config, dict):
                continue
            path = tool_config.get("path")
            category = tool_config.get("category", "default")

            # Setup category if needed
            if category != "default" and category not in tool_manager.tool_categories:
                tool_manager.setup_category(
                    category_name=category,
                    description=f"Custom {category} tools",
                    enabled=True,
                )

            # Normalize function field to list
            func_field = tool_config.get("function") or tool_config.get("func")
            if isinstance(func_field, str):
                functions = [func_field]
            elif isinstance(func_field, list):
                functions = func_field
            else:
                logger.error(f"Invalid function field: {func_field}")
                continue

            # Normalize name field
            name_field = tool_config.get("name")
            if name_field is None:
                names = [None] * len(functions)
            elif isinstance(name_field, str):
                names = [name_field] * len(functions)
            elif isinstance(name_field, list):
                names = name_field
            else:
                names = [None] * len(functions)

            # Normalize description field
            desc_field = tool_config.get("description")
            if desc_field is None:
                descs = [None] * len(functions)
            elif isinstance(desc_field, str):
                descs = [desc_field] * len(functions)
            elif isinstance(desc_field, list):
                descs = desc_field
            else:
                descs = [None] * len(functions)

            for i, func in enumerate(functions):
                name = names[i] if i < len(names) else None
                desc = descs[i] if i < len(descs) else None

                # If custom name, load and rename
                if name and name != func:
                    loaded = tool_manager._load_function_from_path(path, func) if path else tool_manager._load_builtin_function(func)
                    if loaded is None:
                        logger.error(f"Could not load function '{func}' from {path}")
                        continue
                    loaded.__name__ = name
                    tool_manager.add_tool_function(
                        path=None,
                        func=loaded,
                        category=category,
                        description=desc,
                    )
                else:
                    tool_manager.add_tool_function(
                        path=path,
                        func=func,
                        category=category,
                        description=desc,
                    )
        except Exception as e:
            logger.error(f"Failed to register tool from config: {e}")

    # Build execution context
    execution_context = {
        "agent_id": args.agent_id,
        "allowed_paths": [str(Path(p).resolve()) for p in args.allowed_paths],
    }
    if args.allowed_paths:
        execution_context["agent_cwd"] = args.allowed_paths[0]

    background_manager = BackgroundToolManager(
        tool_manager=tool_manager,
        execution_context=execution_context,
        mcp_servers=tool_specs.get("background_mcp_servers", []),
    )

    @asynccontextmanager
    async def _server_lifespan(_server: fastmcp.FastMCP):
        try:
            yield
        finally:
            await background_manager.shutdown()

    mcp = fastmcp.FastMCP(
        "massgen_custom_tools",
        lifespan=_server_lifespan,
    )

    # Register each tool as an MCP tool
    schemas = tool_manager.fetch_tool_schemas()
    for schema in schemas:
        func_info = schema.get("function", {})
        tool_name = func_info.get("name", "")
        tool_desc = func_info.get("description", "")
        tool_params = func_info.get("parameters", {})

        if not tool_name:
            continue

        # Create the MCP tool handler
        _register_mcp_tool(
            mcp,
            tool_name,
            tool_desc,
            tool_params,
            tool_manager,
            execution_context,
            background_manager=background_manager,
        )
        logger.info(f"Registered MCP tool: {tool_name}")

    @mcp.tool(
        name=BACKGROUND_TOOL_START_NAME,
        description=("Start any custom or MCP tool in the background and return a job_id " "for polling or cancellation."),
    )
    async def _start_background_tool(
        tool_name: str,
        arguments: Optional[Any] = None,
        args: Optional[Any] = None,
    ) -> str:
        target_arguments = arguments if arguments is not None else args
        payload = await background_manager.start(
            tool_name=tool_name,
            arguments=target_arguments if target_arguments is not None else {},
        )
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_STATUS_NAME,
        description="Get lightweight status for a background tool job.",
    )
    async def _get_background_tool_status(job_id: str) -> str:
        payload = background_manager.get_status(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_RESULT_NAME,
        description="Get the current or final result payload for a background tool job.",
    )
    async def _get_background_tool_result(job_id: str) -> str:
        payload = background_manager.get_result(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_CANCEL_NAME,
        description="Cancel a running background tool job.",
    )
    async def _cancel_background_tool(job_id: str) -> str:
        payload = background_manager.cancel(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_LIST_NAME,
        description=("List background tool jobs. By default returns only currently running jobs; " "set include_all=true to include completed/error/cancelled history."),
    )
    async def _list_background_tools(include_all: bool = False) -> str:
        payload = background_manager.list_jobs(include_all=include_all)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_WAIT_NAME,
        description=("Block until the next unseen background tool reaches a terminal status " "or timeout elapses."),
    )
    async def _wait_for_background_tool(
        timeout_seconds: Optional[float] = BACKGROUND_TOOL_WAIT_DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        payload = await background_manager.wait_for_next_completion(
            timeout_seconds=timeout_seconds,
        )
        return json.dumps(payload, default=str)

    logger.info(
        "Custom tools MCP server ready with %s tool(s) + background lifecycle tools",
        len(schemas),
    )
    return mcp


def _json_schema_to_python_type(prop_schema: Dict[str, Any]) -> Any:
    """Map a JSON Schema property to a Python type annotation.

    Handles both plain ``{"type": "array"}`` and Pydantic-style
    ``{"anyOf": [{"type": "array"}, {"type": "null"}]}`` for Optional types.
    Falls back to ``Any`` for unrecognised schemas.
    """
    from typing import Any as _Any

    _JSON_TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    # Direct type
    direct = prop_schema.get("type")
    if direct in _JSON_TYPE_MAP:
        return _JSON_TYPE_MAP[direct]

    # anyOf (e.g. Optional[List[str]])
    any_of = prop_schema.get("anyOf")
    if isinstance(any_of, list):
        non_null = [v for v in any_of if isinstance(v, dict) and v.get("type") != "null"]
        has_null = any(isinstance(v, dict) and v.get("type") == "null" for v in any_of)
        if non_null:
            base = _JSON_TYPE_MAP.get(non_null[0].get("type", ""), _Any)
            return Optional[base] if has_null else base

    return _Any


def _register_mcp_tool(
    mcp: fastmcp.FastMCP,
    tool_name: str,
    tool_desc: str,
    tool_params: Dict[str, Any],
    tool_manager: Any,
    execution_context: Dict[str, Any],
    background_manager: Optional[BackgroundToolManager] = None,
) -> None:
    """Register a single custom tool as an MCP tool on the server.

    FastMCP doesn't support **kwargs handlers, so we build a concrete function
    with named parameters derived from the tool's JSON schema.
    """
    import inspect

    # Build parameter list from schema properties
    properties = tool_params.get("properties", {})
    required = set(tool_params.get("required", []))
    signature_to_input_name: Dict[str, str] = {}
    synthetic_control_input_names: set[str] = set()

    def _signature_param_name(param_name: str) -> str:
        # Python identifiers cannot use reserved keyword "async" as a param name.
        if param_name == "async":
            return "async_"
        return param_name

    # Create parameters for the dynamic function
    params = []
    handler_annotations: Dict[str, Any] = {}
    for param_name, param_info in properties.items():
        signature_name = _signature_param_name(param_name)
        signature_to_input_name[signature_name] = param_name
        py_type = _json_schema_to_python_type(param_info)
        handler_annotations[signature_name] = py_type
        if param_name in required:
            params.append(
                inspect.Parameter(
                    signature_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=py_type,
                ),
            )
        else:
            # Use None as default for optional params
            params.append(
                inspect.Parameter(
                    signature_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=None,
                    annotation=py_type,
                ),
            )

    # Add synthetic background-control parameters for tools that don't define them.
    if "mode" not in properties:
        params.append(
            inspect.Parameter(
                "mode",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=Optional[str],
            ),
        )
        handler_annotations["mode"] = Optional[str]
        signature_to_input_name["mode"] = "mode"
        synthetic_control_input_names.add("mode")

    if "background" not in properties:
        params.append(
            inspect.Parameter(
                "background",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=Optional[bool],
            ),
        )
        handler_annotations["background"] = Optional[bool]
        signature_to_input_name["background"] = "background"
        synthetic_control_input_names.add("background")

    # Create the handler with a proper signature
    async def _handler(**kwargs) -> str:
        input_kwargs: Dict[str, Any] = {}
        for signature_name, value in kwargs.items():
            input_name = signature_to_input_name.get(signature_name, signature_name)
            input_kwargs[input_name] = value

        if background_manager and _should_auto_background_execution(tool_name, input_kwargs):
            control_args_to_strip = set(synthetic_control_input_names)
            # Legacy control alias should never be forwarded unless a tool
            # explicitly declares it (rare).
            if "run_in_background" not in properties:
                control_args_to_strip.add("run_in_background")
            payload = await background_manager.start(
                tool_name=tool_name,
                arguments=_strip_background_control_args(
                    input_kwargs,
                    control_args_to_strip=control_args_to_strip,
                ),
            )
            if payload.get("success"):
                payload.setdefault("status", "background")
            return json.dumps(payload, default=str)

        # Remove synthetic control args before normal tool execution.
        for control_arg in synthetic_control_input_names:
            input_kwargs.pop(control_arg, None)

        tool_request = {"name": tool_name, "input": input_kwargs}
        results = []
        async for result in tool_manager.execute_tool(tool_request, execution_context):
            results.append(result)

        if not results:
            return json.dumps({"success": False, "error": "No result from tool"})

        final = results[-1]
        if hasattr(final, "model_dump"):
            return json.dumps(final.model_dump(), default=str)
        elif hasattr(final, "__dict__"):
            return json.dumps(final.__dict__, default=str)
        return json.dumps({"success": True, "result": str(final)})

    # Apply the correct signature and type annotations so FastMCP generates
    # a properly typed JSON schema.  Without annotations, FastMCP produces
    # typeless schemas and models send all arguments as strings.
    sig = inspect.Signature(params)
    _handler.__signature__ = sig
    _handler.__name__ = tool_name
    _handler.__doc__ = tool_desc
    _handler.__annotations__ = {**handler_annotations, "return": str}

    mcp.tool(name=tool_name, description=tool_desc)(_handler)


def write_tool_specs(
    custom_tools: List[Dict[str, Any]],
    output_path: Path,
    background_mcp_servers: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Write tool specifications to a JSON file for the server to load.

    This is called by the backend before launching the MCP server process.

    Args:
        custom_tools: List of custom tool configurations from YAML config.
        output_path: Path to write the specs file.
        background_mcp_servers: Optional MCP server configs for background target execution.

    Returns:
        Path to the written specs file.
    """
    specs: Dict[str, Any] = {"custom_tools": custom_tools}
    if background_mcp_servers is not None:
        specs["background_mcp_servers"] = background_mcp_servers
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(specs, f, indent=2)
    return output_path


def build_server_config(
    tool_specs_path: Path,
    allowed_paths: Optional[List[str]] = None,
    agent_id: str = "unknown",
    env: Optional[Dict[str, str]] = None,
    tool_timeout_sec: int = 300,
) -> Dict[str, Any]:
    """Build an MCP server config dict for use in .codex/config.toml or mcp_servers list.

    Args:
        tool_specs_path: Path to the tool specs JSON file.
        allowed_paths: List of allowed filesystem paths.
        agent_id: Agent identifier.
        tool_timeout_sec: Timeout in seconds for tool execution (default 300 for media generation).

    Returns:
        MCP server configuration dict (stdio type).
    """
    # Use absolute file path - works in Docker because massgen is bind-mounted at same host path
    script_path = Path(__file__).resolve()

    cmd_args = [
        "run",
        f"{script_path}:create_server",
        "--",
        "--tool-specs",
        str(tool_specs_path),
        "--agent-id",
        agent_id,
    ]
    if allowed_paths:
        cmd_args.extend(["--allowed-paths"] + allowed_paths)

    env_vars = {"FASTMCP_SHOW_CLI_BANNER": "false"}
    if env:
        env_vars.update(env)
        # Always enforce banner suppression
        env_vars["FASTMCP_SHOW_CLI_BANNER"] = "false"

    return {
        "name": "massgen_custom_tools",
        "type": "stdio",
        "command": "fastmcp",
        "args": cmd_args,
        "env": env_vars,
        "tool_timeout_sec": tool_timeout_sec,
    }
