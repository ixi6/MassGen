"""Tests for BackgroundToolDelegate protocol and SubagentBackgroundDelegate."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.subagent.background_delegate import (
    BackgroundToolDelegate,
    SubagentBackgroundDelegate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subagent_entry(
    subagent_id: str,
    status: str = "running",
    task: str = "test task",
    answer: str | None = None,
) -> dict[str, Any]:
    """Create a mock subagent entry as returned by list_subagents MCP."""
    entry: dict[str, Any] = {
        "subagent_id": subagent_id,
        "status": status,
        "task": task,
        "workspace": f"/tmp/subagents/{subagent_id}",
    }
    if answer is not None:
        entry["result"] = {"answer": answer}
    return entry


def _make_list_result(subagents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": True,
        "operation": "list_subagents",
        "subagents": subagents,
        "count": len(subagents),
    }


def _make_cancel_result(subagent_id: str, success: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "success": success,
        "operation": "cancel_subagent",
        "subagent_id": subagent_id,
    }
    if not success:
        result["error"] = "not found"
    return result


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestBackgroundToolDelegateProtocol:
    """Verify SubagentBackgroundDelegate satisfies the protocol."""

    def test_is_protocol_instance(self):
        delegate = SubagentBackgroundDelegate(
            call_tool=AsyncMock(return_value=_make_list_result([])),
            agent_id="agent-1",
        )
        assert isinstance(delegate, BackgroundToolDelegate)


# ---------------------------------------------------------------------------
# owns()
# ---------------------------------------------------------------------------


class TestOwns:
    @pytest.mark.asyncio
    async def test_owns_known_id(self):
        entries = [_make_subagent_entry("sub-1"), _make_subagent_entry("sub-2")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        assert await delegate.owns("sub-1") is True
        assert await delegate.owns("sub-2") is True

    @pytest.mark.asyncio
    async def test_does_not_own_unknown_id(self):
        call_tool = AsyncMock(return_value=_make_list_result([]))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        assert await delegate.owns("unknown-id") is False

    @pytest.mark.asyncio
    async def test_owns_caches_known_ids(self):
        entries = [_make_subagent_entry("sub-1")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        # First call queries
        assert await delegate.owns("sub-1") is True
        first_call_count = call_tool.call_count

        # Second call should use cache
        assert await delegate.owns("sub-1") is True
        assert call_tool.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_owns_requeries_on_miss(self):
        """If an ID is not in cache, delegate should re-query in case new subagents spawned."""
        entries_v1 = [_make_subagent_entry("sub-1")]
        entries_v2 = [_make_subagent_entry("sub-1"), _make_subagent_entry("sub-2")]

        call_tool = AsyncMock(
            side_effect=[
                _make_list_result(entries_v1),
                _make_list_result(entries_v2),
            ],
        )
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        assert await delegate.owns("sub-1") is True
        # sub-2 not in cache, triggers re-query
        assert await delegate.owns("sub-2") is True

    @pytest.mark.asyncio
    async def test_owns_handles_call_failure(self):
        call_tool = AsyncMock(side_effect=Exception("MCP down"))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        assert await delegate.owns("any-id") is False


# ---------------------------------------------------------------------------
# list_jobs()
# ---------------------------------------------------------------------------


class TestListJobs:
    @pytest.mark.asyncio
    async def test_list_jobs_maps_statuses(self):
        entries = [
            _make_subagent_entry("s1", "running"),
            _make_subagent_entry("s2", "completed", answer="done"),
            _make_subagent_entry("s3", "failed"),
            _make_subagent_entry("s4", "timeout"),
            _make_subagent_entry("s5", "completed_but_timeout", answer="partial"),
            _make_subagent_entry("s6", "partial", answer="partial"),
            _make_subagent_entry("s7", "cancelled"),
        ]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        jobs = await delegate.list_jobs(include_all=True)

        status_map = {j["job_id"]: j["status"] for j in jobs}
        assert status_map["s1"] == "running"
        assert status_map["s2"] == "completed"
        assert status_map["s3"] == "error"
        assert status_map["s4"] == "error"
        assert status_map["s5"] == "completed"
        assert status_map["s6"] == "completed"
        assert status_map["s7"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_jobs_filters_terminal_when_not_include_all(self):
        entries = [
            _make_subagent_entry("s1", "running"),
            _make_subagent_entry("s2", "completed", answer="done"),
        ]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        jobs = await delegate.list_jobs(include_all=False)
        job_ids = {j["job_id"] for j in jobs}
        assert "s1" in job_ids
        assert "s2" not in job_ids

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self):
        call_tool = AsyncMock(return_value=_make_list_result([]))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        jobs = await delegate.list_jobs(include_all=True)
        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_jobs_handles_failure(self):
        call_tool = AsyncMock(side_effect=Exception("boom"))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        jobs = await delegate.list_jobs(include_all=True)
        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_jobs_includes_tool_type(self):
        entries = [_make_subagent_entry("s1", "running")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        jobs = await delegate.list_jobs(include_all=True)
        assert jobs[0]["tool_type"] == "subagent"
        assert jobs[0]["tool_name"] == "subagent"
        assert jobs[0]["subagent_id"] == "s1"


# ---------------------------------------------------------------------------
# get_status() / get_result()
# ---------------------------------------------------------------------------


class TestGetStatusAndResult:
    @pytest.mark.asyncio
    async def test_get_status_running(self):
        entries = [_make_subagent_entry("s1", "running")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.get_status("s1")
        assert result["success"] is True
        assert result["status"] == "running"
        assert result["job_id"] == "s1"
        assert result["subagent_id"] == "s1"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self):
        call_tool = AsyncMock(return_value=_make_list_result([]))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.get_status("unknown")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_result_completed(self):
        entries = [_make_subagent_entry("s1", "completed", answer="The answer is 42")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.get_result("s1")
        assert result["success"] is True
        assert result["ready"] is True
        assert result["job_id"] == "s1"
        assert result["subagent_id"] == "s1"
        assert "42" in result["result"]

    @pytest.mark.asyncio
    async def test_get_result_still_running(self):
        entries = [_make_subagent_entry("s1", "running")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.get_result("s1")
        assert result["success"] is True
        assert result["ready"] is False


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_calls_mcp(self):
        entries = [_make_subagent_entry("s1", "running")]
        cancel_result = _make_cancel_result("s1", success=True)

        call_tool = AsyncMock(
            side_effect=[
                _make_list_result(entries),  # owns() lookup
                cancel_result,  # cancel call
            ],
        )
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.cancel("s1")
        assert result["success"] is True
        assert result["job_id"] == "s1"
        assert result["subagent_id"] == "s1"

        # Verify cancel was called with right tool name
        cancel_call = call_tool.call_args_list[-1]
        assert cancel_call[0][0] == "cancel_subagent" or cancel_call[1].get("tool_name") == "cancel_subagent" or "cancel" in str(cancel_call)

    @pytest.mark.asyncio
    async def test_cancel_unknown_id(self):
        call_tool = AsyncMock(return_value=_make_list_result([]))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.cancel("unknown")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_handles_failure(self):
        entries = [_make_subagent_entry("s1", "running")]
        call_tool = AsyncMock(
            side_effect=[
                _make_list_result(entries),
                Exception("cancel failed"),
            ],
        )
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.cancel("s1")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# drain_completed()
# ---------------------------------------------------------------------------


class TestDrainCompleted:
    @pytest.mark.asyncio
    async def test_drain_returns_empty(self):
        """Subagents use SubagentCompleteHook, so drain is always empty."""
        call_tool = AsyncMock(return_value=_make_list_result([]))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        result = await delegate.drain_completed()
        assert result == []


# ---------------------------------------------------------------------------
# Integration: BackgroundToolManager + delegate merge
# ---------------------------------------------------------------------------


class TestBackgroundToolManagerDelegateIntegration:
    """Test that handler methods properly route to delegate via the real async methods."""

    @pytest.mark.asyncio
    async def test_list_merges_delegate_jobs(self):
        """list_background_tools should include both native jobs and delegate jobs."""
        from massgen.backend.base_with_custom_tool_and_mcp import (
            BackgroundToolJob,
            CustomToolAndMCPBackend,
        )

        entries = [_make_subagent_entry("sub-1", "running")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        # Create a mock that has the real method behavior
        native_job = BackgroundToolJob(
            job_id="native-1",
            tool_name="test_tool",
            tool_type="custom",
            arguments={},
            status="running",
            created_at=1000.0,
        )

        mock_self = MagicMock()
        mock_self._background_tool_jobs = {"native-1": native_job}
        mock_self._background_tool_delegate = delegate
        mock_self._coerce_include_all_background_jobs = CustomToolAndMCPBackend._coerce_include_all_background_jobs
        mock_self._format_unix_timestamp = CustomToolAndMCPBackend._format_unix_timestamp

        def serialize(job, include_result=False):
            return CustomToolAndMCPBackend._serialize_background_job(mock_self, job, include_result)

        mock_self._serialize_background_job = serialize

        # Call the real async method unbound
        result = await CustomToolAndMCPBackend._list_background_tools_from_request(
            mock_self,
            {"include_all": True},
        )

        assert result["success"] is True
        job_ids = {j["job_id"] for j in result["jobs"]}
        assert "native-1" in job_ids
        assert "sub-1" in job_ids

    @pytest.mark.asyncio
    async def test_status_routes_to_delegate(self):
        """get_background_tool_status routes to delegate for delegate-owned IDs."""
        entries = [_make_subagent_entry("sub-1", "running")]
        call_tool = AsyncMock(return_value=_make_list_result(entries))
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        from massgen.backend.base_with_custom_tool_and_mcp import (
            CustomToolAndMCPBackend,
        )

        mock_self = MagicMock()
        mock_self._background_tool_jobs = {}
        mock_self._background_tool_delegate = delegate

        result = await CustomToolAndMCPBackend._get_background_tool_status_from_request(
            mock_self,
            {"job_id": "sub-1"},
        )

        assert result["success"] is True
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_cancel_routes_to_delegate(self):
        """cancel_background_tool routes to delegate for delegate-owned IDs."""
        entries = [_make_subagent_entry("sub-1", "running")]
        cancel_result = _make_cancel_result("sub-1")

        call_tool = AsyncMock(
            side_effect=[
                _make_list_result(entries),  # owns
                cancel_result,  # cancel
            ],
        )
        delegate = SubagentBackgroundDelegate(call_tool=call_tool, agent_id="a1")

        from massgen.backend.base_with_custom_tool_and_mcp import (
            CustomToolAndMCPBackend,
        )

        mock_self = MagicMock()
        mock_self._background_tool_jobs = {}
        mock_self._background_tool_delegate = delegate
        mock_self._background_tool_tasks = {}

        result = await CustomToolAndMCPBackend._cancel_background_tool_from_request(
            mock_self,
            {"job_id": "sub-1"},
        )

        assert result["success"] is True
