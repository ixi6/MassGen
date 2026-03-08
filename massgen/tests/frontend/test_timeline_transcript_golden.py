"""Golden transcript tests for timeline chronology behavior."""

from __future__ import annotations

import os
from pathlib import Path

from massgen.events import EventType, MassGenEvent
from massgen.frontend.displays.timeline_event_recorder import TimelineEventRecorder

GOLDEN_DIR = Path(__file__).with_name("golden")
UPDATE_GOLDENS = os.getenv("UPDATE_GOLDENS") == "1"


def _render_lines(events: list[MassGenEvent]) -> list[str]:
    lines: list[str] = []
    recorder = TimelineEventRecorder(lines.append, agent_ids={"agent_a"})
    for event in events:
        recorder.handle_event(event)
    recorder.flush()
    return lines


def _assert_matches_golden(golden_name: str, lines: list[str]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden_path = GOLDEN_DIR / f"{golden_name}.txt"
    actual = "\n".join(lines).rstrip() + "\n"

    if UPDATE_GOLDENS:
        golden_path.write_text(actual, encoding="utf-8")

    expected = golden_path.read_text(encoding="utf-8")
    assert actual == expected


def test_golden_consecutive_mcp_tools_batch() -> None:
    lines = _render_lines(
        [
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                args={"path": "/tmp/a.txt"},
                server_name="filesystem",
            ),
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                args={"path": "/tmp/b.txt"},
                server_name="filesystem",
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                result="ok",
                elapsed_seconds=0.01,
                is_error=False,
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                result="done",
                elapsed_seconds=0.02,
                is_error=False,
            ),
        ],
    )
    _assert_matches_golden("consecutive_mcp_batch", lines)


def test_golden_text_breaks_batching_sequence() -> None:
    lines = _render_lines(
        [
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                args={"path": "/tmp/a.txt"},
                server_name="filesystem",
            ),
            MassGenEvent.create(
                EventType.TEXT,
                agent_id="agent_a",
                content="interleaved content",
            ),
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                args={"path": "/tmp/b.txt"},
                server_name="filesystem",
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                result="done",
                elapsed_seconds=0.02,
                is_error=False,
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                result="ok",
                elapsed_seconds=0.01,
                is_error=False,
            ),
        ],
    )
    _assert_matches_golden("text_breaks_batch_sequence", lines)


def test_golden_restart_round_banner_is_deferred_until_first_content() -> None:
    lines = _render_lines(
        [
            MassGenEvent.create(
                EventType.AGENT_RESTART,
                agent_id="agent_a",
                restart_round=2,
                restart_reason="new answer received",
            ),
            MassGenEvent.create(
                EventType.TEXT,
                agent_id="agent_a",
                content="resuming after restart",
            ),
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t_restart",
                tool_name="mcp__filesystem__list_directory",
                args={"path": "/tmp"},
                server_name="filesystem",
            ),
        ],
    )
    _assert_matches_golden("restart_deferred_banner", lines)


def test_golden_final_presentation_advances_round_for_following_content() -> None:
    lines = _render_lines(
        [
            MassGenEvent.create(
                EventType.FINAL_PRESENTATION_START,
                agent_id="agent_a",
                vote_counts={"agent_a": 2, "agent_b": 1},
                answer_labels={"agent_a": "A1.2", "agent_b": "B1.1"},
                is_tie=False,
            ),
            MassGenEvent.create(
                EventType.TEXT,
                agent_id="agent_a",
                content="final answer content",
            ),
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t_final",
                tool_name="Read",
                args={"file_path": "/tmp/final.txt"},
                server_name=None,
            ),
        ],
    )
    _assert_matches_golden("final_presentation_round_transition", lines)


def test_golden_tools_from_different_servers_do_not_batch() -> None:
    lines = _render_lines(
        [
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t_fs",
                tool_name="mcp__filesystem__read_text_file",
                args={"path": "/tmp/a.txt"},
                server_name="filesystem",
            ),
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t_web",
                tool_name="mcp__web__fetch_url",
                args={"url": "https://example.com"},
                server_name="web",
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t_fs",
                tool_name="mcp__filesystem__read_text_file",
                result="done",
                elapsed_seconds=0.01,
                is_error=False,
            ),
            MassGenEvent.create(
                EventType.TOOL_COMPLETE,
                agent_id="agent_a",
                tool_id="t_web",
                tool_name="mcp__web__fetch_url",
                result="ok",
                elapsed_seconds=0.01,
                is_error=False,
            ),
        ],
    )
    _assert_matches_golden("different_servers_no_batch", lines)
