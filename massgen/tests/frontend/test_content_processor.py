# -*- coding: utf-8 -*-
"""Unit tests for ContentProcessor event handling."""

from massgen.events import EventType, MassGenEvent
from massgen.frontend.displays.content_processor import ContentProcessor


def test_tool_start_creates_tool_output():
    processor = ContentProcessor()
    event = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="mcp__filesystem__read_text_file",
        args={"path": "/tmp/a.txt"},
        server_name="filesystem",
    )

    output = processor.process_event(event, round_number=1)
    assert output is not None
    assert output.output_type == "tool"
    assert output.tool_data is not None
    assert output.tool_data.status == "running"
    assert output.batch_action == "pending"


def test_status_info_level_is_skipped():
    processor = ContentProcessor()
    event = MassGenEvent.create(
        EventType.STATUS,
        agent_id="agent_a",
        message="Voting complete",
        level="info",
    )

    assert processor.process_event(event, round_number=1) is None


def test_thinking_whitespace_is_filtered():
    processor = ContentProcessor()
    event = MassGenEvent.create(
        EventType.THINKING,
        agent_id="agent_a",
        content="   ",
    )

    assert processor.process_event(event, round_number=1) is None


def test_two_consecutive_tools_convert_to_batch():
    processor = ContentProcessor()

    first = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="mcp__filesystem__read_text_file",
        args={"path": "/tmp/a.txt"},
        server_name="filesystem",
    )
    second = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t2",
        tool_name="mcp__filesystem__write_file",
        args={"path": "/tmp/b.txt"},
        server_name="filesystem",
    )

    first_out = processor.process_event(first, round_number=1)
    second_out = processor.process_event(second, round_number=1)

    assert first_out is not None and first_out.batch_action == "pending"
    assert second_out is not None and second_out.batch_action == "convert_to_batch"
    assert second_out.pending_tool_id == "t1"


def test_content_between_tools_prevents_batch_conversion():
    processor = ContentProcessor()

    first_tool = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="mcp__filesystem__read_text_file",
        args={"path": "/tmp/a.txt"},
        server_name="filesystem",
    )
    # Thinking whitespace is filtered from display, but still marks content arrival.
    interleaved_content = MassGenEvent.create(
        EventType.THINKING,
        agent_id="agent_a",
        content=" \n ",
    )
    second_tool = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t2",
        tool_name="mcp__filesystem__write_file",
        args={"path": "/tmp/b.txt"},
        server_name="filesystem",
    )

    first_out = processor.process_event(first_tool, round_number=1)
    thinking_out = processor.process_event(interleaved_content, round_number=1)
    second_out = processor.process_event(second_tool, round_number=1)

    assert first_out is not None and first_out.batch_action == "pending"
    assert thinking_out is None
    assert second_out is not None and second_out.batch_action == "pending"


def test_server_name_stored_on_tool_display_data():
    """server_name from event should be preserved on ToolDisplayData."""
    processor = ContentProcessor()
    event = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="codex_shell",
        args={"command": "ls"},
        server_name="codex",
    )

    output = processor.process_event(event, round_number=1)
    assert output is not None
    assert output.tool_data.server_name == "codex"


def test_server_name_preserved_through_tool_complete():
    """server_name should survive from tool_start through tool_complete."""
    processor = ContentProcessor()
    start = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="codex_shell",
        args={"command": "ls"},
        server_name="codex",
    )
    complete = MassGenEvent.create(
        EventType.TOOL_COMPLETE,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="codex_shell",
        result="file1.txt",
        elapsed_seconds=0.5,
    )

    processor.process_event(start, round_number=1)
    output = processor.process_event(complete, round_number=1)
    assert output is not None
    assert output.tool_data.server_name == "codex"


def test_consecutive_codex_shell_tools_batch():
    """codex_shell tools with server_name should batch like mcp__ tools."""
    processor = ContentProcessor()

    first = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t1",
        tool_name="codex_shell",
        args={"command": "ls"},
        server_name="codex",
    )
    second = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t2",
        tool_name="codex_shell",
        args={"command": "pwd"},
        server_name="codex",
    )

    first_out = processor.process_event(first, round_number=1)
    second_out = processor.process_event(second, round_number=1)

    assert first_out is not None and first_out.batch_action == "pending"
    assert second_out is not None and second_out.batch_action == "convert_to_batch"
    assert second_out.pending_tool_id == "t1"


def test_tool_complete_background_status_preserves_async_id():
    """Background completions should render as background status with async identifier."""
    processor = ContentProcessor()
    start = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t-bg",
        tool_name="custom_tool__generate_media",
        args={"prompt": "sunset"},
    )
    complete = MassGenEvent.create(
        EventType.TOOL_COMPLETE,
        agent_id="agent_a",
        tool_id="t-bg",
        tool_name="custom_tool__generate_media",
        result='{"status":"background"}',
        elapsed_seconds=0.01,
        status="background",
        async_id="bgtool_123",
    )

    processor.process_event(start, round_number=1)
    output = processor.process_event(complete, round_number=1)

    assert output is not None
    assert output.tool_data is not None
    assert output.tool_data.status == "background"
    assert output.tool_data.async_id == "bgtool_123"


def test_start_background_tool_success_payload_sets_background_status():
    """start_background_tool success payload should surface as background in TUI."""
    processor = ContentProcessor()
    start = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t-start-bg",
        tool_name="custom_tool__start_background_tool",
        args={"tool_name": "custom_tool__generate_media"},
    )
    complete = MassGenEvent.create(
        EventType.TOOL_COMPLETE,
        agent_id="agent_a",
        tool_id="t-start-bg",
        tool_name="custom_tool__start_background_tool",
        result=('{"job_id":"bgtool_2694dfb86446","tool_name":"custom_tool__generate_media",' '"status":"running","success":true}'),
        elapsed_seconds=0.02,
        status="success",
    )

    processor.process_event(start, round_number=1)
    output = processor.process_event(complete, round_number=1)

    assert output is not None
    assert output.tool_data is not None
    assert output.tool_data.status == "background"
    assert output.tool_data.async_id == "bgtool_2694dfb86446"


def test_start_background_tool_python_repr_payload_sets_background_status():
    """Claude Code list/dict string payloads should still infer background metadata."""
    processor = ContentProcessor()
    start = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t-start-bg-repr",
        tool_name="mcp__massgen_custom_tools__custom_tool__start_background_tool",
        args={"tool_name": "mcp__massgen_custom_tools__custom_tool__generate_media"},
    )
    complete = MassGenEvent.create(
        EventType.TOOL_COMPLETE,
        agent_id="agent_a",
        tool_id="t-start-bg-repr",
        tool_name="mcp__massgen_custom_tools__custom_tool__start_background_tool",
        result=("[{'type': 'text', 'text': '{\"job_id\": \"bgtool_repr_123\", " '"tool_name": "custom_tool__generate_media", "status": "running", ' '"success": true}\'}]'),
        elapsed_seconds=0.02,
        status="success",
    )

    processor.process_event(start, round_number=1)
    output = processor.process_event(complete, round_number=1)

    assert output is not None
    assert output.tool_data is not None
    assert output.tool_data.status == "background"
    assert output.tool_data.async_id == "bgtool_repr_123"


def test_media_tool_background_payload_without_async_id_sets_background_status():
    """Background payloads from direct media tool calls should show as background in TUI."""
    processor = ContentProcessor()
    start = MassGenEvent.create(
        EventType.TOOL_START,
        agent_id="agent_a",
        tool_id="t-media-bg",
        tool_name="mcp__massgen_custom_tools__custom_tool__read_media",
        args={"inputs": [{"files": {"goat": "goat.png"}, "prompt": "Describe"}]},
    )
    complete = MassGenEvent.create(
        EventType.TOOL_COMPLETE,
        agent_id="agent_a",
        tool_id="t-media-bg",
        tool_name="mcp__massgen_custom_tools__custom_tool__read_media",
        result=("[{'type': 'text', 'text': '{\"success\": true, \"status\": \"background\", " '"job_id": "bgtool_read_789", "tool_name": "custom_tool__read_media"}\'}]'),
        elapsed_seconds=0.02,
        status="success",
    )

    processor.process_event(start, round_number=1)
    output = processor.process_event(complete, round_number=1)

    assert output is not None
    assert output.tool_data is not None
    assert output.tool_data.status == "background"
    assert output.tool_data.async_id == "bgtool_read_789"
