"""Unit tests for TimelineEventRecorder and its timeline mocks."""

from datetime import datetime, timezone

from massgen.events import EventType, MassGenEvent
from massgen.frontend.displays.content_handlers import ToolDisplayData
from massgen.frontend.displays.timeline_event_recorder import (
    TimelineEventRecorder,
    _MockPanel,
    _MockTimeline,
)


def _make_tool(
    tool_id: str,
    *,
    tool_name: str = "mcp__filesystem__read_text_file",
    display_name: str = "filesystem/read_text_file",
    status: str = "running",
) -> ToolDisplayData:
    return ToolDisplayData(
        tool_id=tool_id,
        tool_name=tool_name,
        display_name=display_name,
        tool_type="mcp" if tool_name.startswith("mcp__") else "tool",
        category="filesystem",
        icon="F",
        color="blue",
        status=status,
        start_time=datetime.now(timezone.utc),
    )


def test_deferred_round_banner_flushes_on_first_content():
    lines: list[str] = []
    timeline = _MockTimeline(lines.append)
    panel = _MockPanel(timeline, agent_id="agent_a")

    panel.start_new_round(2, defer_banner=True)
    assert lines == []

    timeline.add_text("hello", round_number=2)
    assert lines[0].startswith("[2] separator: Round 2")
    assert lines[1].startswith("[2] content-inline: hello")

    # Deferring again after banner was shown should do nothing.
    panel.start_new_round(2, defer_banner=True)
    timeline.add_text("again", round_number=2)
    assert sum("separator: Round 2" in line for line in lines) == 1


def test_mock_timeline_tool_add_update_and_get():
    lines: list[str] = []
    timeline = _MockTimeline(lines.append)

    timeline.add_tool(_make_tool("t1"), round_number=1)
    assert timeline.get_tool("t1") is not None
    assert timeline.get_tool("t1").status == "running"
    assert any("tool pending" in line and "id=t1" in line for line in lines)

    timeline.update_tool("t1", _make_tool("t1", status="success"))
    assert timeline.get_tool("t1").status == "success"
    assert any("tool update_standalone" in line and "id=t1" in line for line in lines)

    before = len(lines)
    timeline.update_tool("t1", _make_tool("t1", status="success"))
    assert len(lines) == before


def test_mock_timeline_batch_conversion_add_and_update_paths():
    lines: list[str] = []
    timeline = _MockTimeline(lines.append)

    timeline.add_tool(_make_tool("t1"), round_number=1)
    timeline.convert_tool_to_batch("t1", _make_tool("t2"), "batch_1", "filesystem", round_number=1)
    timeline.add_tool_to_batch("batch_1", _make_tool("t3"))

    assert timeline.get_tool_batch("t1") == "batch_1"
    assert timeline.get_tool_batch("t2") == "batch_1"
    assert timeline.get_tool_batch("t3") == "batch_1"
    assert any("tool convert_to_batch" in line and "batch=batch_1" in line for line in lines)
    assert any("tool add_to_batch" in line and "id=t3" in line for line in lines)

    timeline.update_tool_in_batch("t3", _make_tool("t3", status="success"))
    assert any("tool update_batch" in line and "id=t3" in line for line in lines)

    before = len(lines)
    timeline.update_tool_in_batch("t3", _make_tool("t3", status="success"))
    assert len(lines) == before


def test_recorder_filters_legacy_events_and_agent_ids_and_reset_works():
    lines: list[str] = []
    recorder = TimelineEventRecorder(lines.append, agent_ids={"agent_a"})

    recorder.handle_event(MassGenEvent.create("timeline_entry", agent_id="agent_a", line="ignore"))
    recorder.handle_event(MassGenEvent.create("stream_chunk", agent_id="agent_a", content="ignore"))
    recorder.handle_event(MassGenEvent.create(EventType.TEXT, agent_id="agent_b", content="ignored"))
    assert lines == []

    recorder.handle_event(MassGenEvent.create(EventType.TEXT, agent_id="agent_a", content="hello"))
    assert any("content-inline: hello" in line for line in lines)
    separators_before_reset = sum("separator: Round 1" in line for line in lines)

    recorder.reset()
    recorder.handle_event(MassGenEvent.create(EventType.TEXT, agent_id="agent_a", content="again"))
    separators_after_reset = sum("separator: Round 1" in line for line in lines)
    assert separators_after_reset == separators_before_reset + 1


def test_recorder_defers_round_banner_then_batches_and_updates_tools():
    lines: list[str] = []
    recorder = TimelineEventRecorder(lines.append, agent_ids={"agent_a"})

    recorder.handle_event(
        MassGenEvent.create(
            EventType.AGENT_RESTART,
            agent_id="agent_a",
            restart_round=2,
            restart_reason="new answer received",
        ),
    )
    assert lines == []

    recorder.handle_event(MassGenEvent.create(EventType.TEXT, agent_id="agent_a", content="resuming"))
    assert lines[0].startswith("[2] separator: Round 2")
    assert lines[1].startswith("[2] content-inline: resuming")

    recorder.handle_event(
        MassGenEvent.create(
            EventType.TOOL_START,
            agent_id="agent_a",
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            args={"path": "/tmp/a.txt"},
            server_name="filesystem",
        ),
    )
    recorder.handle_event(
        MassGenEvent.create(
            EventType.TOOL_START,
            agent_id="agent_a",
            tool_id="t2",
            tool_name="mcp__filesystem__write_file",
            args={"path": "/tmp/b.txt"},
            server_name="filesystem",
        ),
    )
    recorder.handle_event(
        MassGenEvent.create(
            EventType.TOOL_START,
            agent_id="agent_a",
            tool_id="t3",
            tool_name="mcp__filesystem__list_directory",
            args={"path": "/tmp"},
            server_name="filesystem",
        ),
    )
    recorder.handle_event(
        MassGenEvent.create(
            EventType.TOOL_COMPLETE,
            agent_id="agent_a",
            tool_id="t2",
            tool_name="mcp__filesystem__write_file",
            result="ok",
            elapsed_seconds=0.01,
            is_error=False,
        ),
    )

    assert any("tool convert_to_batch" in line and "batch=batch_1" in line for line in lines)
    assert any("tool add_to_batch" in line and "id=t3" in line for line in lines)
    assert any("tool update_batch" in line and "id=t2" in line for line in lines)

    # No-op flush should not fail.
    recorder.flush()


def test_recorder_does_not_emit_round_banner_after_final_presentation_separator():
    lines: list[str] = []
    recorder = TimelineEventRecorder(lines.append, agent_ids={"agent_a"})

    recorder.handle_event(
        MassGenEvent.create(
            EventType.FINAL_PRESENTATION_START,
            agent_id="agent_a",
            vote_counts={"agent_a": 1},
            answer_labels={"agent_a": "A1.1"},
            is_tie=False,
        ),
    )
    recorder.handle_event(
        MassGenEvent.create(
            EventType.TOOL_START,
            agent_id="agent_a",
            tool_id="t_final_1",
            tool_name="Read",
            args={"file_path": "/tmp/final.txt"},
        ),
    )

    assert any(line.startswith("[2] separator: FINAL PRESENTATION") for line in lines)
    assert not any(line.startswith("[2] separator: Round 2") for line in lines)
