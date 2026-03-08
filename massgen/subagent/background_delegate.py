"""Background tool delegate for subagents.

Bridges the BackgroundToolManager's 6 handler methods to subagent MCP tools,
so the model can manage subagents using the same background tool interface.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Subagent statuses that map to background tool "completed"
_SUBAGENT_COMPLETED_STATUSES = {"completed", "completed_but_timeout", "partial"}
# Subagent statuses that map to background tool "error"
_SUBAGENT_ERROR_STATUSES = {"failed", "timeout"}
# Subagent statuses that map to background tool "cancelled"
_SUBAGENT_CANCELLED_STATUSES = {"cancelled", "canceled"}
# Background tool terminal statuses (for filtering)
_BG_TERMINAL_STATUSES = {"completed", "error", "cancelled"}


@runtime_checkable
class BackgroundToolDelegate(Protocol):
    """Protocol for delegates that extend BackgroundToolManager with external job types."""

    async def owns(self, job_id: str) -> bool:
        """Return True if this delegate manages the given job ID."""
        ...

    async def list_jobs(self, include_all: bool) -> list[dict[str, Any]]:
        """List delegate-managed jobs in background-tool-compatible format."""
        ...

    async def get_status(self, job_id: str) -> dict[str, Any]:
        """Get status of a delegate-managed job."""
        ...

    async def get_result(self, job_id: str) -> dict[str, Any]:
        """Get result of a delegate-managed job."""
        ...

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a delegate-managed job."""
        ...

    async def drain_completed(self) -> list[dict[str, Any]]:
        """Return and clear completed job payloads pending injection."""
        ...


def _map_subagent_status(subagent_status: str) -> str:
    """Map subagent status to background tool status."""
    if subagent_status == "running":
        return "running"
    if subagent_status in _SUBAGENT_CANCELLED_STATUSES:
        return "cancelled"
    if subagent_status in _SUBAGENT_COMPLETED_STATUSES:
        return "completed"
    if subagent_status in _SUBAGENT_ERROR_STATUSES:
        return "error"
    if subagent_status == "pending":
        return "running"  # pending subagents are treated as running
    return "running"


def _subagent_to_bg_job(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a subagent list entry to a background-tool-shaped dict."""
    subagent_id = entry.get("subagent_id", "")
    status = _map_subagent_status(entry.get("status", "running"))

    job: dict[str, Any] = {
        "job_id": subagent_id,
        "subagent_id": subagent_id,
        "tool_name": "subagent",
        "tool_type": "subagent",
        "status": status,
        "created_at": entry.get("created_at", ""),
    }

    # Include result for completed subagents
    result_payload = entry.get("result")
    if result_payload and isinstance(result_payload, dict):
        answer = result_payload.get("answer", "")
        if answer:
            job["result"] = answer

    # Include task description as arguments summary
    task = entry.get("task", "")
    if task:
        job["arguments"] = {"task": task}

    return job


class SubagentBackgroundDelegate:
    """Delegate that bridges subagent MCP tools to BackgroundToolManager.

    Uses the orchestrator's _call_subagent_mcp_tool() to communicate with the
    subagent MCP server running in a separate process.
    """

    def __init__(
        self,
        call_tool: Callable[..., Any],
        agent_id: str,
    ) -> None:
        self._call_tool = call_tool
        self._agent_id = agent_id
        self._known_ids: set[str] = set()

    async def _call(self, tool_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call the subagent MCP tool, handling both sync and async call_tool."""
        result = self._call_tool(tool_name, params or {})
        if isinstance(result, Awaitable):
            result = await result
        if result is None:
            return {"success": False, "error": "No response from subagent MCP"}
        return result

    async def _list_subagents_raw(self) -> list[dict[str, Any]]:
        """Fetch raw subagent list from MCP and update known IDs cache."""
        try:
            result = await self._call("list_subagents")
            if not result.get("success"):
                return []
            entries = result.get("subagents", [])
            # Update cache
            for entry in entries:
                sid = entry.get("subagent_id", "")
                if sid:
                    self._known_ids.add(sid)
            return entries
        except Exception:
            logger.debug(
                "[SubagentBgDelegate] Failed to list subagents for %s",
                self._agent_id,
                exc_info=True,
            )
            return []

    async def _find_subagent(self, job_id: str) -> dict[str, Any] | None:
        """Find a specific subagent by ID."""
        entries = await self._list_subagents_raw()
        for entry in entries:
            if entry.get("subagent_id") == job_id:
                return entry
        return None

    # -- Protocol methods --

    async def owns(self, job_id: str) -> bool:
        if job_id in self._known_ids:
            return True
        # Re-query in case new subagents were spawned
        try:
            await self._list_subagents_raw()
            return job_id in self._known_ids
        except Exception:
            return False

    async def list_jobs(self, include_all: bool) -> list[dict[str, Any]]:
        try:
            entries = await self._list_subagents_raw()
            jobs = [_subagent_to_bg_job(e) for e in entries]
            if not include_all:
                jobs = [j for j in jobs if j["status"] not in _BG_TERMINAL_STATUSES]
            return jobs
        except Exception:
            logger.debug(
                "[SubagentBgDelegate] list_jobs failed for %s",
                self._agent_id,
                exc_info=True,
            )
            return []

    async def get_status(self, job_id: str) -> dict[str, Any]:
        entry = await self._find_subagent(job_id)
        if entry is None:
            return {"success": False, "error": f"Subagent not found: {job_id}"}
        job = _subagent_to_bg_job(entry)
        job["success"] = True
        return job

    async def get_result(self, job_id: str) -> dict[str, Any]:
        entry = await self._find_subagent(job_id)
        if entry is None:
            return {"success": False, "error": f"Subagent not found: {job_id}"}
        job = _subagent_to_bg_job(entry)
        ready = job["status"] in _BG_TERMINAL_STATUSES
        job.update({"success": True, "ready": ready})
        if not ready:
            job["message"] = "Subagent still running"
        return job

    async def cancel(self, job_id: str) -> dict[str, Any]:
        # Verify the subagent exists
        if not await self.owns(job_id):
            return {"success": False, "error": f"Subagent not found: {job_id}"}
        try:
            result = await self._call("cancel_subagent", {"subagent_id": job_id})
            if isinstance(result, dict):
                resolved_subagent_id = str(result.get("subagent_id") or job_id).strip()
                if resolved_subagent_id:
                    result.setdefault("subagent_id", resolved_subagent_id)
                    result.setdefault("job_id", resolved_subagent_id)
            return result
        except Exception as exc:
            logger.debug(
                "[SubagentBgDelegate] cancel failed for %s/%s: %s",
                self._agent_id,
                job_id,
                exc,
            )
            return {"success": False, "error": f"Cancel failed: {exc}"}

    async def drain_completed(self) -> list[dict[str, Any]]:
        # Subagent completion injection is handled by SubagentCompleteHook
        return []
