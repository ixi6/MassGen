# -*- coding: utf-8 -*-
"""Layer 3 Textual SVG snapshot tests for critical timeline states."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.content_handlers import ToolDisplayData
from massgen.frontend.displays.textual_terminal_display import TextualTerminalDisplay
from massgen.frontend.displays.textual_widgets.collapsible_text_card import (
    CollapsibleTextCard,
)
from massgen.frontend.displays.textual_widgets.content_sections import TimelineSection
from massgen.frontend.displays.textual_widgets.tool_batch_card import (
    ToolBatchCard,
    ToolBatchItem,
)
from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard


def _configure_snapshot_terminal_environment(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Pin terminal color behavior so snapshot rendering is deterministic across runners."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("COLUMNS", "140")
    monkeypatch.setenv("LINES", "42")
    monkeypatch.setenv("FORCE_COLOR", "1")


class _TimelineSnapshotApp(App):
    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")

    def on_mount(self) -> None:
        timeline = self.query_one(TimelineSection)
        fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        timeline.add_separator("Round 1", round_number=1)
        timeline.add_text("Agent is preparing plan", text_class="content-inline", round_number=1)

        tool_running = ToolDisplayData(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="filesystem/read_text_file",
            tool_type="mcp",
            category="filesystem",
            icon="F",
            color="blue",
            status="running",
            start_time=fixed_time,
            args_summary='{"path": "/tmp/a.txt"}',
            args_full='{"path": "/tmp/a.txt"}',
        )
        timeline.add_tool(tool_running, round_number=1)

        tool_done = ToolDisplayData(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="filesystem/read_text_file",
            tool_type="mcp",
            category="filesystem",
            icon="F",
            color="blue",
            status="success",
            start_time=fixed_time,
            end_time=fixed_time,
            args_summary='{"path": "/tmp/a.txt"}',
            args_full='{"path": "/tmp/a.txt"}',
            result_summary="read ok",
            result_full="read ok",
            elapsed_seconds=0.0,
        )
        timeline.update_tool("t1", tool_done)


async def _settle_scaffold_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    """Settle animation/timer state before capturing widget-only snapshots."""
    _complete_tool_appearance_states(pilot.app)
    _stop_all_tui_timers(pilot.app)
    await pilot.pause()


def test_timeline_snapshot_baseline(snap_compare, monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Snapshot for baseline timeline state with separator, content, and tool card."""
    _configure_snapshot_terminal_environment(monkeypatch)
    assert snap_compare(
        _TimelineSnapshotApp(),
        terminal_size=(120, 32),
        run_before=_settle_scaffold_snapshot,
    )


class _TimelineBatchSnapshotApp(App):
    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")

    def on_mount(self) -> None:
        timeline = self.query_one(TimelineSection)
        fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        timeline.add_separator("Round 1", round_number=1)
        batch = timeline.add_batch("batch_1", "filesystem", round_number=1)
        batch._complete_appearance()

        item_one = ToolBatchItem(
            tool_id="t1",
            tool_name="mcp__filesystem__read_text_file",
            display_name="read_text_file",
            status="success",
            args_summary='{"path": "/tmp/a.txt"}',
            result_summary="done",
            start_time=fixed_time,
            end_time=fixed_time,
            elapsed_seconds=0.0,
        )
        item_two = ToolBatchItem(
            tool_id="t2",
            tool_name="mcp__filesystem__write_file",
            display_name="write_file",
            status="success",
            args_summary='{"path": "/tmp/b.txt"}',
            result_summary="ok",
            start_time=fixed_time,
            end_time=fixed_time,
            elapsed_seconds=0.0,
        )
        batch.add_tool(item_one)
        batch.add_tool(item_two)


def test_timeline_snapshot_batch_card(snap_compare, monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Snapshot for batched MCP tool presentation."""
    _configure_snapshot_terminal_environment(monkeypatch)
    assert snap_compare(
        _TimelineBatchSnapshotApp(),
        terminal_size=(120, 32),
        run_before=_settle_scaffold_snapshot,
    )


def _configure_real_tui_snapshot_environment(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    _configure_snapshot_terminal_environment(monkeypatch)
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )


def _build_real_tui_snapshot_app(tmp_path: Path) -> App:
    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "claude-sonnet-4-5"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Create a poem about Bob Dylan and write it to a file in my workspace.",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app
    return app


def _stop_round_timers_if_running(app: App) -> None:
    ribbon = getattr(app, "_status_ribbon", None)
    if not ribbon:
        return

    if hasattr(ribbon, "stop_all_round_timers"):
        ribbon.stop_all_round_timers()
    timer_handle = getattr(ribbon, "_timer_handle", None)
    if timer_handle:
        timer_handle.stop()
        ribbon._timer_handle = None


def _stop_all_tui_timers(app: App) -> None:
    """Stop recurring timers so full-app snapshots stay deterministic."""
    auto_refresh_timer = getattr(app, "_auto_refresh_timer", None)
    if auto_refresh_timer:
        auto_refresh_timer.stop()
        app._auto_refresh_timer = None

    for timer in list(getattr(app, "_timers", [])):
        try:
            timer.stop()
        except Exception:
            pass


def _complete_tool_appearance_states(app: App) -> None:
    """Force tool cards to their post-animation state before capture."""
    for card in app.query(CollapsibleTextCard):
        card._complete_appearance()
        refresh_timer = getattr(card, "_refresh_timer", None)
        if refresh_timer:
            refresh_timer.stop()
            card._refresh_timer = None
            card._refresh_pending = False

    for card in app.query(ToolCallCard):
        card._complete_appearance()

    for batch in app.query(ToolBatchCard):
        batch._complete_appearance()


async def _seed_real_tui_round_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    timeline = panel._get_timeline()
    assert timeline is not None
    fixed_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    timeline.add_text(
        "I'll create a poem about Bob Dylan and write it to a file in my workspace.",
        text_class="content-inline",
        round_number=1,
    )

    tool_running = ToolDisplayData(
        tool_id="t_real",
        tool_name="Write",
        display_name="Write",
        tool_type="tool",
        category="workspace",
        icon="W",
        color="green",
        status="running",
        start_time=fixed_time,
        args_summary='{"file_path": "/workspace/deliverable/final.txt"}',
        args_full='{"file_path": "/workspace/deliverable/final.txt"}',
    )
    timeline.add_tool(tool_running, round_number=1)

    tool_done = ToolDisplayData(
        tool_id="t_real",
        tool_name="Write",
        display_name="Write",
        tool_type="tool",
        category="workspace",
        icon="W",
        color="green",
        status="success",
        start_time=fixed_time,
        end_time=fixed_time,
        args_summary='{"file_path": "/workspace/deliverable/final.txt"}',
        args_full='{"file_path": "/workspace/deliverable/final.txt"}',
        result_summary="File created",
        result_full="File created",
        elapsed_seconds=0.8,
    )
    timeline.update_tool("t_real", tool_done)

    timeline.add_text(
        "The file has been saved to the deliverable folder and is ready for use.",
        text_class="content-inline",
        round_number=1,
    )
    app.query_one("#timeout_display", Label).update("⏱ 0:00 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)
    _complete_tool_appearance_states(app)
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_round_view(snap_compare, monkeypatch, tmp_path: Path) -> None:
    """Snapshot of the runtime Textual app shell with agent panel content."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(140, 42),
        run_before=_seed_real_tui_round_snapshot,
    )


async def _seed_real_tui_toast_snapshot(pilot) -> None:  # noqa: ANN001 - fixture-provided type
    app = pilot.app
    panel = app.agent_widgets["agent_a"]
    panel._hide_loading()
    _stop_round_timers_if_running(app)

    app.query_one("#timeout_display", Label).update("⏱ 0:00 / 10:00")
    app.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
    app.set_focus(None)

    app.notify("Info: collecting agent updates", severity="information", timeout=30)
    app.notify("Warning: context budget is nearly full", severity="warning", timeout=30)
    app.notify("Error: failed to parse plan metadata", severity="error", timeout=30)
    app.notify("Success: final answer saved", severity="success", timeout=30)

    await pilot.pause()
    _stop_all_tui_timers(app)
    await pilot.pause()


def test_timeline_snapshot_real_tui_toast_stack(snap_compare, monkeypatch, tmp_path: Path) -> None:
    """Snapshot of runtime Textual app with stacked toast severities."""
    _configure_real_tui_snapshot_environment(monkeypatch)
    assert snap_compare(
        _build_real_tui_snapshot_app(tmp_path),
        terminal_size=(140, 42),
        run_before=_seed_real_tui_toast_snapshot,
    )
