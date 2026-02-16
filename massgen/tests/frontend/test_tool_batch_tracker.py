# -*- coding: utf-8 -*-
"""Unit tests for ToolBatchTracker timeline batching behavior."""

from datetime import datetime, timezone

from massgen.frontend.displays.content_handlers import ToolBatchTracker, ToolDisplayData


def _make_tool(tool_id: str, tool_name: str, status: str = "running") -> ToolDisplayData:
    return ToolDisplayData(
        tool_id=tool_id,
        tool_name=tool_name,
        display_name=tool_name,
        tool_type="mcp" if tool_name.startswith("mcp__") else "tool",
        category="filesystem",
        icon="F",
        color="blue",
        status=status,
        start_time=datetime.now(timezone.utc),
    )


def test_consecutive_mcp_tools_convert_to_batch():
    tracker = ToolBatchTracker()

    action1, server1, batch_id1, pending_id1 = tracker.process_tool(_make_tool("t1", "mcp__filesystem__read_text_file"))
    assert action1 == "pending"
    assert server1 == "filesystem"
    assert batch_id1 is None
    assert pending_id1 is None

    action2, server2, batch_id2, pending_id2 = tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file"))
    assert action2 == "convert_to_batch"
    assert server2 == "filesystem"
    assert batch_id2 == "batch_1"
    assert pending_id2 == "t1"


def test_content_breaks_batching_sequence():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__filesystem__read_text_file"))

    # Chronology rule: non-tool content between tools prevents batch conversion.
    tracker.mark_content_arrived()

    action, server, batch_id, pending_id = tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file"))
    assert action == "pending"
    assert server == "filesystem"
    assert batch_id is None
    assert pending_id is None


def test_non_mcp_tools_are_standalone():
    tracker = ToolBatchTracker()

    action, server, batch_id, pending_id = tracker.process_tool(_make_tool("t1", "web_search"))
    assert action == "standalone"
    assert server is None
    assert batch_id is None
    assert pending_id is None


def test_third_consecutive_tool_adds_to_existing_batch():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__filesystem__read_text_file"))
    tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file"))

    action, server, batch_id, pending_id = tracker.process_tool(_make_tool("t3", "mcp__filesystem__list_directory"))
    assert action == "add_to_batch"
    assert server == "filesystem"
    assert batch_id == "batch_1"
    assert pending_id is None


def test_status_update_for_batched_tool_uses_update_batch_action():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__filesystem__read_text_file"))
    tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file"))
    tracker.process_tool(_make_tool("t3", "mcp__filesystem__list_directory"))

    action, server, batch_id, pending_id = tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file", status="success"))
    assert action == "update_batch"
    assert server == "filesystem"
    assert batch_id == "batch_1"
    assert pending_id is None


def test_non_mcp_tools_with_server_name_batch_together():
    """codex_shell tools with server_name should batch like mcp__ tools."""
    tracker = ToolBatchTracker()

    t1 = _make_tool("t1", "codex_shell")
    t1.server_name = "codex"
    action1, server1, batch_id1, _ = tracker.process_tool(t1)
    assert action1 == "pending"
    assert server1 == "codex"

    t2 = _make_tool("t2", "codex_shell")
    t2.server_name = "codex"
    action2, server2, batch_id2, pending_id2 = tracker.process_tool(t2)
    assert action2 == "convert_to_batch"
    assert server2 == "codex"
    assert batch_id2 == "batch_1"
    assert pending_id2 == "t1"


def test_non_mcp_tools_without_server_name_stay_standalone():
    """Tools with no mcp__ prefix and no server_name remain standalone."""
    tracker = ToolBatchTracker()

    action, server, batch_id, _ = tracker.process_tool(_make_tool("t1", "web_search"))
    assert action == "standalone"
    assert server is None
    assert batch_id is None


def test_server_name_fallback_third_tool_adds_to_batch():
    """Third consecutive codex_shell tool should add to existing batch."""
    tracker = ToolBatchTracker()

    for tid in ("t1", "t2"):
        t = _make_tool(tid, "codex_shell")
        t.server_name = "codex"
        tracker.process_tool(t)

    t3 = _make_tool("t3", "codex_shell")
    t3.server_name = "codex"
    action, server, batch_id, _ = tracker.process_tool(t3)
    assert action == "add_to_batch"
    assert server == "codex"
    assert batch_id == "batch_1"


def test_server_name_completion_update_uses_update_batch():
    """Completing a codex_shell tool in a batch should route to update_batch."""
    tracker = ToolBatchTracker()

    for tid in ("t1", "t2"):
        t = _make_tool(tid, "codex_shell")
        t.server_name = "codex"
        tracker.process_tool(t)

    t1_done = _make_tool("t1", "codex_shell", status="success")
    t1_done.server_name = "codex"
    action, server, batch_id, _ = tracker.process_tool(t1_done)
    assert action == "update_batch"
    assert batch_id == "batch_1"


def test_reset_clears_batch_state():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__filesystem__read_text_file"))
    tracker.process_tool(_make_tool("t2", "mcp__filesystem__write_file"))
    assert tracker.current_batch_id == "batch_1"

    tracker.reset()
    assert tracker.current_batch_id is None
    assert tracker.current_server is None

    action, server, batch_id, pending_id = tracker.process_tool(_make_tool("t3", "mcp__filesystem__list_directory"))
    assert action == "pending"
    assert server == "filesystem"
    assert batch_id is None
    assert pending_id is None
