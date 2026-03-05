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
from typing import Any, Optional

import fastmcp

logger = logging.getLogger(__name__)


def _resolve_hook_middleware() -> Any:
    """Return hook middleware class in both package and file-path launch modes."""
    try:
        from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    try:
        from .hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    # fastmcp file-path launches can drop package context; add repo root explicitly.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

    return MassGenHookMiddleware


def _resolve_media_call_ledger_hook() -> Any:
    """Return MediaCallLedgerHook in package and standalone launch modes."""
    try:
        from massgen.mcp_tools.hooks import MediaCallLedgerHook

        return MediaCallLedgerHook
    except ImportError:
        pass

    try:
        from .hooks import MediaCallLedgerHook

        return MediaCallLedgerHook
    except ImportError:
        pass

    # fastmcp file-path launches can drop package context; add repo root explicitly.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from massgen.mcp_tools.hooks import MediaCallLedgerHook

    return MediaCallLedgerHook


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


def _is_explicit_foreground_request(arguments: dict[str, Any]) -> bool:
    """Return True when args explicitly request foreground/blocking behavior."""
    if arguments.get("background") is False:
        return True
    if arguments.get("run_in_background") is False:
        return True
    mode = arguments.get("mode")
    return isinstance(mode, str) and mode.lower() in FOREGROUND_CONTROL_MODES


def _should_auto_background_execution(
    tool_name: str,
    arguments: dict[str, Any],
    declared_control_args: set[str] | None = None,
) -> bool:
    """Return True when args request automatic background scheduling."""
    if not isinstance(arguments, dict):
        return False
    if _is_explicit_foreground_request(arguments):
        return False
    if _is_default_media_background_tool(tool_name):
        return True
    if declared_control_args and ("background" in declared_control_args or "run_in_background" in declared_control_args or "mode" in declared_control_args):
        return False
    mode = arguments.get("mode")
    mode_is_background = isinstance(mode, str) and mode.lower() in BACKGROUND_CONTROL_MODES
    return arguments.get("background") is True or mode_is_background


def _strip_background_control_args(
    arguments: dict[str, Any],
    control_args_to_strip: set[str] | None = None,
) -> dict[str, Any]:
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
    arguments: dict[str, Any]
    status: str
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None


class BackgroundToolManager:
    """Background lifecycle manager for custom_tools_server."""

    def __init__(
        self,
        tool_manager: Any,
        execution_context: dict[str, Any],
        mcp_servers: list[dict[str, Any]] | None = None,
        wait_interrupt_file: str | Path | None = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._execution_context = execution_context
        self._mcp_servers = self._filter_background_mcp_servers(mcp_servers or [])
        self._mcp_client = None
        self._mcp_initialized = False
        self._jobs: dict[str, BackgroundToolJob] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._wait_seen_job_ids: set[str] = set()
        self._subagent_delegate = None
        self._subagent_delegate_initialized = False
        self._subagent_tool_name_cache: dict[str, str] = {}
        self._wait_interrupt_file: Path | None = Path(wait_interrupt_file) if wait_interrupt_file else None
        self._media_call_ledger_hook = None
        try:
            MediaCallLedgerHook = _resolve_media_call_ledger_hook()
            self._media_call_ledger_hook = MediaCallLedgerHook()
        except Exception:
            logger.debug("Media call ledger hook unavailable in custom tools server", exc_info=True)

    @staticmethod
    def _filter_background_mcp_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop unsupported/recursive servers for background execution."""
        filtered: list[dict[str, Any]] = []
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
    def _format_unix_timestamp(timestamp: float | None) -> str | None:
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

    def _resolve_target(self, tool_name: str) -> tuple[str, str] | None:
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

    @staticmethod
    def _is_subagent_spawn_target_tool(tool_name: str) -> bool:
        """Return True when tool name represents subagent spawn."""
        normalized = str(tool_name or "").strip().lower()
        return "spawn_subagent" in normalized and "subagent" in normalized

    @staticmethod
    def _normalize_subagent_spawn_background_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        """Force wrapper-routed subagent starts into direct background mode."""
        normalized = dict(arguments)
        normalized["background"] = True
        normalized.pop("run_in_background", None)
        mode = normalized.get("mode")
        if not (isinstance(mode, str) and mode.lower() == "background"):
            normalized.pop("mode", None)
        return normalized

    def _validate_start_prerequisites(self, tool_name: str) -> str | None:
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

    def _serialize_job(self, job: BackgroundToolJob, include_result: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
    def _extract_text_from_output_blocks(blocks: list[Any]) -> str:
        text_parts: list[str] = []
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

    async def _run_custom_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        tool_request = {"name": tool_name, "input": arguments}
        final_result = None
        async for result in self._tool_manager.execute_tool(
            tool_request,
            self._execution_context,
        ):
            final_result = result

        if final_result is None:
            missing_result_error = "No final result payload captured from custom tool execution"
            await self._record_media_call_ledger(tool_name, arguments, missing_result_error)
            return (missing_result_error, True)

        output_blocks = getattr(final_result, "output_blocks", None)
        if isinstance(output_blocks, list):
            text = self._extract_text_from_output_blocks(output_blocks)
            if text:
                await self._record_media_call_ledger(tool_name, arguments, text)
                return (text, False)

        if hasattr(final_result, "model_dump"):
            dumped = final_result.model_dump()
            text = self._extract_text_from_output_blocks(dumped.get("output_blocks", []))
            if text:
                await self._record_media_call_ledger(tool_name, arguments, text)
                return (text, False)
            dumped_text = json.dumps(dumped, default=str)
            if dumped_text:
                await self._record_media_call_ledger(tool_name, arguments, dumped_text)
                return (dumped_text, False)
            missing_result_error = "No final result payload captured from custom tool execution"
            await self._record_media_call_ledger(tool_name, arguments, missing_result_error)
            return (missing_result_error, True)

        if hasattr(final_result, "__dict__"):
            dumped = final_result.__dict__
            text = self._extract_text_from_output_blocks(dumped.get("output_blocks", []))
            if text:
                await self._record_media_call_ledger(tool_name, arguments, text)
                return (text, False)
            dumped_text = json.dumps(dumped, default=str)
            if dumped_text:
                await self._record_media_call_ledger(tool_name, arguments, dumped_text)
                return (dumped_text, False)
            missing_result_error = "No final result payload captured from custom tool execution"
            await self._record_media_call_ledger(tool_name, arguments, missing_result_error)
            return (missing_result_error, True)

        result_text = str(final_result).strip()
        if result_text:
            await self._record_media_call_ledger(tool_name, arguments, result_text)
            return (result_text, False)
        missing_result_error = "No final result payload captured from custom tool execution"
        await self._record_media_call_ledger(tool_name, arguments, missing_result_error)
        return (missing_result_error, True)

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

    @staticmethod
    def _parse_json_payload(raw_text: str) -> dict[str, Any] | None:
        """Parse a JSON object payload from tool text, if possible."""
        if not raw_text:
            return None
        try:
            parsed = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    @staticmethod
    def _looks_like_json_payload(raw_text: str) -> bool:
        stripped = str(raw_text or "").lstrip()
        return stripped.startswith("{") or stripped.startswith("[")

    @classmethod
    def _annotate_custom_tool_outcome(
        cls,
        payload: dict[str, Any],
        job: BackgroundToolJob,
        *,
        ready: bool,
    ) -> None:
        """Attach tool-level outcome fields for terminal custom-tool jobs."""
        if not ready or job.tool_type != "custom":
            return

        if job.status in {"error", "cancelled"}:
            payload["tool_success"] = False
            payload["tool_error"] = str(job.error or "Custom tool execution failed")
            return

        if job.status != "completed":
            payload["tool_success"] = None
            return

        raw_result = str(job.result or "").strip()
        if not raw_result:
            payload["tool_success"] = False
            payload["tool_error"] = "No final result payload captured from custom tool execution"
            return

        parsed = cls._parse_json_payload(raw_result)
        if parsed is not None:
            parsed_success = parsed.get("success")
            if isinstance(parsed_success, bool):
                payload["tool_success"] = parsed_success
                if not parsed_success:
                    parsed_error = parsed.get("error")
                    if parsed_error is not None:
                        payload["tool_error"] = str(parsed_error)
                    else:
                        payload["tool_error"] = "Custom tool reported success=false"
            else:
                payload["tool_success"] = True
            return

        if raw_result.startswith("Error:"):
            payload["tool_success"] = False
            payload["tool_error"] = raw_result
            return

        if cls._looks_like_json_payload(raw_result):
            payload["tool_success"] = None
            payload["result_parse_error"] = "Could not parse custom tool JSON result payload"
            return

        payload["tool_success"] = True

    async def _record_media_call_ledger(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> None:
        """Run media call ledger capture as a non-blocking side effect."""
        hook = self._media_call_ledger_hook
        if hook is None:
            return

        try:
            arguments_str = json.dumps(arguments)
        except (TypeError, ValueError):
            arguments_str = "{}"

        workspace_path = self._execution_context.get("agent_cwd")
        context = {
            "agent_id": self._execution_context.get("agent_id"),
            "workspace_path": workspace_path,
            "agent_cwd": workspace_path,
            "tool_output": result_text,
        }

        try:
            hook_result = await hook.execute(
                tool_name,
                arguments_str,
                context=context,
            )
            if hook_result.has_errors():
                logger.debug(
                    "Media call ledger hook reported non-blocking errors for %s: %s",
                    tool_name,
                    "; ".join(hook_result.hook_errors),
                )
        except Exception:
            logger.debug("Media call ledger capture failed for %s", tool_name, exc_info=True)

    async def _resolve_subagent_mcp_tool_name(self, tool_name: str) -> str | None:
        """Resolve list_subagents/cancel_subagent style names to concrete MCP names."""
        cached = self._subagent_tool_name_cache.get(tool_name)
        if cached is not None:
            return cached or None

        client = await self._get_mcp_client()
        if client is None:
            self._subagent_tool_name_cache[tool_name] = ""
            return None

        available_tools = getattr(client, "tools", None)
        if not isinstance(available_tools, dict):
            self._subagent_tool_name_cache[tool_name] = ""
            return None

        suffix = f"__{tool_name}"
        candidates = [name for name in available_tools.keys() if isinstance(name, str) and name.startswith("mcp__subagent_") and name.endswith(suffix)]
        resolved = sorted(candidates)[0] if candidates else ""
        self._subagent_tool_name_cache[tool_name] = resolved
        return resolved or None

    async def _call_subagent_delegate_tool(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a resolved subagent MCP tool and normalize to JSON dict."""
        resolved_tool_name = await self._resolve_subagent_mcp_tool_name(tool_name)
        if not resolved_tool_name:
            return {
                "success": False,
                "error": f"Subagent MCP tool not available: {tool_name}",
            }

        client = await self._get_mcp_client()
        if client is None:
            return {
                "success": False,
                "error": "MCP client not available for subagent delegate",
            }

        try:
            result = await client.call_tool(resolved_tool_name, params or {})
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"Subagent MCP call failed: {e}"}

        parsed = self._parse_json_payload(
            self._extract_text_from_mcp_content(getattr(result, "content", None)),
        )
        if parsed is not None:
            return parsed
        return {
            "success": False,
            "error": f"Unexpected response from subagent MCP tool: {resolved_tool_name}",
        }

    async def _get_subagent_delegate(self):
        """Lazily initialize a subagent background delegate when MCP tools exist."""
        if self._subagent_delegate_initialized:
            return self._subagent_delegate

        self._subagent_delegate_initialized = True
        list_tool_name = await self._resolve_subagent_mcp_tool_name("list_subagents")
        if not list_tool_name:
            self._subagent_delegate = None
            return None

        try:
            from massgen.subagent.background_delegate import SubagentBackgroundDelegate

            self._subagent_delegate = SubagentBackgroundDelegate(
                call_tool=self._call_subagent_delegate_tool,
                agent_id=str(self._execution_context.get("agent_id", "unknown")),
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "Failed to initialize SubagentBackgroundDelegate",
                exc_info=True,
            )
            self._subagent_delegate = None

        return self._subagent_delegate

    async def _run_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
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
                result, is_error = await self._run_custom_tool(job.tool_name, job.arguments)
                if is_error:
                    job.status = "error"
                    job.error = result
                else:
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

    async def _start_subagent_spawn_direct(
        self,
        tool_name: str,
        target_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Treat start_background_tool(subagent spawn) as direct spawn_subagents(background=true)."""
        normalized_args = self._normalize_subagent_spawn_background_arguments(target_args)
        result_text, is_error = await self._run_mcp_tool(tool_name, normalized_args)
        if is_error:
            return {
                "success": False,
                "error": result_text.removeprefix("Error:").strip() or result_text,
            }

        payload = self._parse_json_payload(result_text)
        if isinstance(payload, dict):
            if payload.get("success") is True and "mode" not in payload:
                payload["mode"] = "background"
            return self._attach_subagent_background_ids(payload)

        return {
            "success": True,
            "operation": "spawn_subagents",
            "mode": "background",
            "result": result_text,
        }

    @staticmethod
    def _attach_subagent_background_ids(payload: dict[str, Any]) -> dict[str, Any]:
        """Ensure subagent background payloads expose both job and subagent IDs."""
        subagents_raw = payload.get("subagents")
        if not isinstance(subagents_raw, list):
            return payload

        subagents: list[dict[str, Any]] = []
        job_ids: list[str] = []
        for item in subagents_raw:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            subagent_id = str(entry.get("subagent_id") or entry.get("id") or "").strip()
            job_id = str(entry.get("job_id") or subagent_id).strip()
            if subagent_id:
                entry["subagent_id"] = subagent_id
            if job_id:
                entry["job_id"] = job_id
                job_ids.append(job_id)
            subagents.append(entry)

        if subagents:
            payload["subagents"] = subagents

        if not job_ids:
            return payload

        unique_job_ids = list(dict.fromkeys(job_ids))
        payload.setdefault("job_ids", unique_job_ids)

        if len(unique_job_ids) == 1:
            payload.setdefault("job_id", unique_job_ids[0])
            first_subagent_id = str(subagents[0].get("subagent_id") or "").strip() if subagents else ""
            if first_subagent_id:
                payload.setdefault("subagent_id", first_subagent_id)

        return payload

    async def start(self, tool_name: str, arguments: Any | None = None) -> dict[str, Any]:
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

        if tool_type == "mcp" and self._is_subagent_spawn_target_tool(effective_tool_name):
            return await self._start_subagent_spawn_direct(
                effective_tool_name,
                target_args,
            )

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

    async def get_status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get((job_id or "").strip())
        if job is not None:
            payload = self._serialize_job(job)
            payload["success"] = True
            return payload

        delegate = await self._get_subagent_delegate()
        if delegate:
            try:
                normalized_job_id = (job_id or "").strip()
                if await delegate.owns(normalized_job_id):
                    return await delegate.get_status(normalized_job_id)
            except Exception:  # noqa: BLE001
                logger.debug("Subagent delegate get_status failed for %s", job_id, exc_info=True)

        return {"success": False, "error": f"Background job not found: {job_id}"}

    async def get_result(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get((job_id or "").strip())
        if job is not None:
            ready = job.status in BACKGROUND_TOOL_TERMINAL_STATUSES
            payload = self._serialize_job(job, include_result=True)
            payload.update({"success": True, "ready": ready})
            self._annotate_custom_tool_outcome(payload, job, ready=ready)
            if not ready:
                payload["message"] = "Background tool still running"
            return payload

        delegate = await self._get_subagent_delegate()
        if delegate:
            try:
                normalized_job_id = (job_id or "").strip()
                if await delegate.owns(normalized_job_id):
                    return await delegate.get_result(normalized_job_id)
            except Exception:  # noqa: BLE001
                logger.debug("Subagent delegate get_result failed for %s", job_id, exc_info=True)

        return {"success": False, "error": f"Background job not found: {job_id}"}

    async def cancel(self, job_id: str) -> dict[str, Any]:
        normalized = (job_id or "").strip()
        if not normalized:
            return {"success": False, "error": "job_id is required"}
        job = self._jobs.get(normalized)
        if job is not None:
            task = self._tasks.get(normalized)
            if task and not task.done():
                job.status = "cancelled"
                job.error = "Cancelled by user request"
                task.cancel()

            payload = self._serialize_job(job)
            payload["success"] = True
            return payload

        delegate = await self._get_subagent_delegate()
        if delegate:
            try:
                if await delegate.owns(normalized):
                    return await delegate.cancel(normalized)
            except Exception:  # noqa: BLE001
                logger.debug("Subagent delegate cancel failed for %s", normalized, exc_info=True)

        return {"success": False, "error": f"Background job not found: {normalized}"}

    async def list_jobs(self, include_all: bool = False) -> dict[str, Any]:
        jobs = [self._serialize_job(job) for job in self._jobs.values() if include_all or job.status not in BACKGROUND_TOOL_TERMINAL_STATUSES]

        delegate = await self._get_subagent_delegate()
        if delegate:
            try:
                jobs.extend(await delegate.list_jobs(include_all=include_all))
            except Exception:  # noqa: BLE001
                logger.debug("Subagent delegate list_jobs failed", exc_info=True)

        jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
        return {
            "success": True,
            "count": len(jobs),
            "include_all": include_all,
            "jobs": jobs,
        }

    @staticmethod
    def _coerce_wait_timeout(timeout_seconds: float | None) -> float:
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

    def _next_waitable_job(self) -> BackgroundToolJob | None:
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

    @staticmethod
    def _coerce_job_sort_timestamp(value: Any) -> float:
        """Best-effort conversion of job timestamp fields to unix epoch seconds."""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if not isinstance(value, str):
            return 0.0

        text = value.strip()
        if not text:
            return 0.0

        try:
            return float(text)
        except ValueError:
            pass

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return 0.0

    @classmethod
    def _wait_sort_key_for_payload(cls, payload: dict[str, Any]) -> tuple[float, float]:
        """Sort terminal jobs by completion time, then creation time."""
        completed_ts = cls._coerce_job_sort_timestamp(payload.get("completed_at"))
        created_ts = cls._coerce_job_sort_timestamp(payload.get("created_at"))
        primary_ts = completed_ts if completed_ts > 0 else created_ts
        return (primary_ts, created_ts)

    async def _next_waitable_delegate_job(self) -> dict[str, Any] | None:
        """Get next unseen terminal delegate job (for subagent-backed background work)."""
        delegate = await self._get_subagent_delegate()
        if not delegate:
            return None

        try:
            jobs = await delegate.list_jobs(include_all=True)
        except Exception:  # noqa: BLE001
            logger.debug("Subagent delegate list_jobs failed during wait", exc_info=True)
            return None

        candidates: list[dict[str, Any]] = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("job_id") or "").strip()
            if not job_id or job_id in self._wait_seen_job_ids:
                continue
            status = str(job.get("status") or "").strip().lower()
            if status not in BACKGROUND_TOOL_TERMINAL_STATUSES:
                continue
            normalized = dict(job)
            normalized["job_id"] = job_id
            candidates.append(normalized)

        if not candidates:
            return None

        candidates.sort(
            key=lambda payload: (
                self._wait_sort_key_for_payload(payload),
                str(payload.get("job_id") or ""),
            ),
        )
        return candidates[0]

    def _consume_wait_interrupt_signal(self) -> dict[str, Any] | None:
        """Read and clear a pending wait interrupt signal from disk."""
        signal_path = self._wait_interrupt_file
        if signal_path is None or not signal_path.exists():
            return None

        try:
            raw = signal_path.read_text(encoding="utf-8").strip()
            signal_path.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to read wait interrupt signal from %s: %s", signal_path, e)
            return None

        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("Invalid wait interrupt payload in %s: %s", signal_path, e)
            return None

        if not isinstance(payload, dict):
            return None

        raw_reason = payload.get("interrupt_reason", "runtime_injection_available")
        interrupt_reason = str(raw_reason).strip() or "runtime_injection_available"
        injected_content = payload.get("injected_content")
        if injected_content is not None:
            injected_content = str(injected_content)

        return {
            "interrupt_reason": interrupt_reason,
            "injected_content": injected_content,
        }

    async def wait_for_next_completion(self, timeout_seconds: float | None = None) -> dict[str, Any]:
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
                self._annotate_custom_tool_outcome(payload, ready_job, ready=True)
                return payload

            delegate_ready_job = await self._next_waitable_delegate_job()
            if delegate_ready_job is not None:
                delegate_job_id = str(delegate_ready_job.get("job_id") or "").strip()
                if delegate_job_id:
                    self._wait_seen_job_ids.add(delegate_job_id)
                payload = dict(delegate_ready_job)
                payload.update(
                    {
                        "success": True,
                        "ready": True,
                        "waited_seconds": round(time.time() - started_at, 3),
                    },
                )
                return payload

            interrupt_payload = self._consume_wait_interrupt_signal()
            if interrupt_payload is not None:
                return {
                    "success": True,
                    "ready": False,
                    "interrupted": True,
                    "interrupt_reason": interrupt_payload.get("interrupt_reason"),
                    "injected_content": interrupt_payload.get("injected_content"),
                    "waited_seconds": round(time.time() - started_at, 3),
                    "message": "Background wait interrupted by runtime input",
                }

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
        running_tasks: list[asyncio.Task[Any]] = []
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
    parser.add_argument(
        "--wait-interrupt-file",
        type=str,
        default=None,
        help="Optional path to a JSON file used to interrupt wait_for_background_tool.",
    )
    parser.add_argument(
        "--hook-dir",
        type=str,
        default=None,
        help="Optional path to directory for hook IPC files (PostToolUse injection).",
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
        wait_interrupt_file=args.wait_interrupt_file,
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

    # Attach hook middleware for PostToolUse injection if hook_dir is configured
    if args.hook_dir:
        MassGenHookMiddleware = _resolve_hook_middleware()
        mcp.add_middleware(MassGenHookMiddleware(Path(args.hook_dir)))
        logger.info("Hook middleware attached (hook_dir=%s)", args.hook_dir)

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
        arguments: Any | None = None,
        args: Any | None = None,
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
        payload = await background_manager.get_status(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_RESULT_NAME,
        description="Get the current or final result payload for a background tool job.",
    )
    async def _get_background_tool_result(job_id: str) -> str:
        payload = await background_manager.get_result(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_CANCEL_NAME,
        description="Cancel a running background tool job.",
    )
    async def _cancel_background_tool(job_id: str) -> str:
        payload = await background_manager.cancel(job_id=job_id)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_LIST_NAME,
        description=("List background tool jobs. By default returns only currently running jobs; " "set include_all=true to include completed/error/cancelled history."),
    )
    async def _list_background_tools(include_all: bool = False) -> str:
        payload = await background_manager.list_jobs(include_all=include_all)
        return json.dumps(payload, default=str)

    @mcp.tool(
        name=BACKGROUND_TOOL_WAIT_NAME,
        description=("Block until the next unseen background tool reaches a terminal status " "or timeout elapses."),
    )
    async def _wait_for_background_tool(
        timeout_seconds: float | None = BACKGROUND_TOOL_WAIT_DEFAULT_TIMEOUT_SECONDS,
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


def _json_schema_to_python_type(prop_schema: dict[str, Any]) -> Any:
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
        "object": dict,
    }
    _ARRAY_COMPAT_TYPE = list | str

    # Direct type
    direct = prop_schema.get("type")
    if direct == "array":
        # Allow stringified JSON lists through FastMCP's runtime validation.
        return _ARRAY_COMPAT_TYPE
    if direct in _JSON_TYPE_MAP:
        return _JSON_TYPE_MAP[direct]

    # anyOf (e.g. Optional[List[str]])
    any_of = prop_schema.get("anyOf")
    if isinstance(any_of, list):
        non_null = [v for v in any_of if isinstance(v, dict) and v.get("type") != "null"]
        has_null = any(isinstance(v, dict) and v.get("type") == "null" for v in any_of)
        if non_null:
            base_type = non_null[0].get("type", "")
            base = _ARRAY_COMPAT_TYPE if base_type == "array" else _JSON_TYPE_MAP.get(base_type, _Any)
            return Optional[base] if has_null else base

    return _Any


def _register_mcp_tool(
    mcp: fastmcp.FastMCP,
    tool_name: str,
    tool_desc: str,
    tool_params: dict[str, Any],
    tool_manager: Any,
    execution_context: dict[str, Any],
    background_manager: BackgroundToolManager | None = None,
) -> None:
    """Register a single custom tool as an MCP tool on the server.

    FastMCP doesn't support **kwargs handlers, so we build a concrete function
    with named parameters derived from the tool's JSON schema.
    """
    import inspect

    # Build parameter list from schema properties
    properties = tool_params.get("properties", {})
    required = set(tool_params.get("required", []))
    declared_control_args = {name for name in ("mode", "background", "run_in_background") if name in properties}
    signature_to_input_name: dict[str, str] = {}
    synthetic_control_input_names: set[str] = set()

    def _signature_param_name(param_name: str) -> str:
        # Python identifiers cannot use reserved keyword "async" as a param name.
        if param_name == "async":
            return "async_"
        return param_name

    # Create parameters for the dynamic function
    params = []
    handler_annotations: dict[str, Any] = {}
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
        input_kwargs: dict[str, Any] = {}
        for signature_name, value in kwargs.items():
            input_name = signature_to_input_name.get(signature_name, signature_name)
            input_kwargs[input_name] = value

        if background_manager and _should_auto_background_execution(
            tool_name,
            input_kwargs,
            declared_control_args=declared_control_args,
        ):
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
    custom_tools: list[dict[str, Any]],
    output_path: Path,
    background_mcp_servers: list[dict[str, Any]] | None = None,
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
    specs: dict[str, Any] = {"custom_tools": custom_tools}
    if background_mcp_servers is not None:
        specs["background_mcp_servers"] = background_mcp_servers
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(specs, f, indent=2)
    return output_path


def build_server_config(
    tool_specs_path: Path,
    allowed_paths: list[str] | None = None,
    agent_id: str = "unknown",
    env: dict[str, str] | None = None,
    tool_timeout_sec: int = 300,
    wait_interrupt_file: Path | None = None,
    hook_dir: Path | None = None,
) -> dict[str, Any]:
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
    if wait_interrupt_file is not None:
        cmd_args.extend(["--wait-interrupt-file", str(wait_interrupt_file)])
    if hook_dir is not None:
        cmd_args.extend(["--hook-dir", str(hook_dir)])

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
