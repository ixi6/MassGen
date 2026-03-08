"""
Shared helpers for Planning MCP task plan display.

This keeps the main TUI and subagent TUI in sync by centralizing:
- planning tool detection
- task plan extraction from tool results
- pinned TaskPlanCard updates
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from typing import Any

# Planning MCP tool names -> operation label
_PLANNING_TOOL_OPERATIONS = {
    "create_task_plan": "create",
    "update_task_status": "update",
    "add_task": "add",
    "edit_task": "edit",
    "get_task_plan": "get",
    "clear_task_plan": "clear",
}

# Planning tool names used for tool filtering (skip normal tool cards)
_PLANNING_TOOL_NAMES = {
    "create_task_plan",
    "update_task_status",
    "add_task",
    "edit_task",
    "get_task_plan",
    "clear_task_plan",
    "delete_task",
    "get_ready_tasks",
    "get_blocked_tasks",
}


def _safe_parse_mapping(raw: Any) -> dict[str, Any] | None:
    """Best-effort parse for tool result payloads (JSON or Python-literal)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    parsed: Any = None
    try:
        parsed = json.loads(text)
    except Exception:
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return None

    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_structured_result(raw_result: Any) -> dict[str, Any] | None:
    """Extract the structured Planning MCP payload from a tool result.

    Handles:
    - Direct JSON dict payloads
    - Python-literal wrapper payloads (Codex style) with `structured_content`
    - Wrapper payloads where the JSON lives in `content[*].text`
    """
    result_data = _safe_parse_mapping(raw_result)
    if not result_data:
        return None

    structured = _safe_parse_mapping(result_data.get("structured_content"))
    if structured:
        return structured

    content_blocks = result_data.get("content")
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            parsed_text = _safe_parse_mapping(block.get("text"))
            if parsed_text:
                return parsed_text

    return result_data


def is_planning_tool(tool_name: str) -> bool:
    """Return True if tool_name matches a Planning MCP tool."""
    tool_lower = tool_name.lower()
    return any(name in tool_lower for name in _PLANNING_TOOL_NAMES)


def update_task_plan_from_tool(
    host: Any,
    tool_data: Any,
    timeline: Any,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Update the pinned task plan from a Planning MCP tool result.

    Expects host to provide:
    - get_active_tasks() -> Optional[List[Dict[str, Any]]]
    - update_pinned_task_plan(...)
    - update_task_plan(...)

    Returns True if a planning tool was handled, False otherwise.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)

    tool_name = tool_data.tool_name.lower()
    operation = None
    for planning_tool, op in _PLANNING_TOOL_OPERATIONS.items():
        if planning_tool in tool_name:
            operation = op
            break

    if not operation:
        return False

    if operation == "clear":
        if hasattr(host, "clear"):
            host.clear()  # type: ignore[attr-defined]
        _log("_task_plan: cleared")
        return True

    should_accept = getattr(host, "should_accept_task_plan", None)
    if callable(should_accept):
        try:
            if not bool(should_accept()):
                if hasattr(host, "clear"):
                    host.clear()  # type: ignore[attr-defined]
                _log("_task_plan: suppressed (no persisted plan artifact)")
                return True
        except Exception:
            pass

    result = tool_data.result_full
    _log(f"_task_plan: tool_name={tool_name}")
    if not result:
        _log("_task_plan: no result_full")
        return True

    result_data = _extract_structured_result(result)
    if not result_data:
        result_len = len(result) if isinstance(result, str) else "n/a"
        _log(f"_task_plan: parse error (result length={result_len})")
        return True

    if not isinstance(result_data, dict):
        return True

    tasks: list[dict[str, Any]] = []
    focused_task_id: str | None = None

    if "tasks" in result_data:
        tasks = result_data["tasks"]
    elif "plan" in result_data and isinstance(result_data["plan"], dict):
        tasks = result_data["plan"].get("tasks", [])

    if operation in ("update", "edit") and "task" in result_data:
        updated_task = result_data["task"]
        focused_task_id = updated_task.get("id")

        # If we have cached tasks and no explicit list, patch the cache
        if host.get_active_tasks() and not tasks:
            tasks = [t.copy() for t in host.get_active_tasks()]  # type: ignore[attr-defined]
            for i, task in enumerate(tasks):
                if task.get("id") == focused_task_id:
                    tasks[i] = updated_task.copy()
                    break

    if not tasks:
        _log("_task_plan: no tasks found")
        return True

    _log(f"_task_plan: updating pinned area with {len(tasks)} tasks")
    host.update_pinned_task_plan(  # type: ignore[attr-defined]
        tasks=tasks,
        focused_task_id=focused_task_id,
        operation=operation,
        show_notification=(operation != "create"),
    )
    host.update_task_plan(tasks, plan_id=tool_data.tool_id, operation=operation)  # type: ignore[attr-defined]
    return True
