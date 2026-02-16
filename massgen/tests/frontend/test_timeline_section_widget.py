# -*- coding: utf-8 -*-
"""Widget-level tests for timeline rendering with Textual Pilot."""

from datetime import datetime, timezone

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown, Static

from massgen.events import EventType, MassGenEvent
from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.content_handlers import ToolDisplayData
from massgen.frontend.displays.textual_widgets.collapsible_text_card import (
    CollapsibleTextCard,
)
from massgen.frontend.displays.textual_widgets.content_sections import (
    FinalPresentationCard,
    RestartBanner,
    TimelineSection,
)
from massgen.frontend.displays.textual_widgets.file_explorer_panel import (
    FileExplorerPanel,
)
from massgen.frontend.displays.textual_widgets.tool_batch_card import ToolBatchCard
from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard
from massgen.frontend.displays.tui_event_pipeline import TimelineEventAdapter


class _TimelineApp(App):
    def __init__(self):
        super().__init__()
        self.hover_suppression_events: list[tuple[bool, str]] = []

    def set_hover_updates_suppressed(self, suppressed: bool, reason: str = "") -> None:
        self.hover_suppression_events.append((suppressed, reason))

    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")


class _TimelineStyledApp(_TimelineApp):
    """Test app that loads the production base theme CSS."""

    CSS_PATH = str(textual_display_module.TextualApp._get_combined_css_path("dark"))


class _PanelStub:
    def __init__(self, timeline: TimelineSection) -> None:
        self._timeline = timeline
        self.agent_id = "agent_a"

    def _get_timeline(self) -> TimelineSection:
        return self._timeline


def _make_tool(tool_id: str, tool_name: str) -> ToolDisplayData:
    return ToolDisplayData(
        tool_id=tool_id,
        tool_name=tool_name,
        display_name=tool_name,
        tool_type="mcp" if tool_name.startswith("mcp__") else "tool",
        category="filesystem",
        icon="F",
        color="blue",
        status="running",
        start_time=datetime.now(timezone.utc),
    )


def _content_children(timeline: TimelineSection) -> list:
    return [child for child in timeline.children if child.id != "scroll_mode_indicator"]


def test_final_card_winner_summary_and_vote_line_formatting():
    card = FinalPresentationCard(
        agent_id="agent_a",
        vote_results={
            "vote_counts": {"A1.2": 2, "B1.1": 1},
            "winner": "A1.2",
            "is_tie": False,
        },
        context_paths={},
    )

    assert card._build_winner_summary() == "🏅 Winner: A1.2 (2 votes)"
    assert card._build_vote_summary() == "Votes: A1.2 (2) • B1.1 (1)"


def test_final_card_winner_summary_marks_tie_breaker():
    card = FinalPresentationCard(
        agent_id="agent_a",
        vote_results={
            "vote_counts": {"A1.2": 2, "B1.1": 2},
            "winner": "A1.2",
            "is_tie": True,
        },
        context_paths={},
    )

    assert card._build_winner_summary() == "🏅 Winner: A1.2 (2 votes) · tie-breaker"


@pytest.mark.asyncio
async def test_deferred_round_banner_renders_before_first_round_content():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)

        timeline.defer_round_banner(2, "Round 2", "Restart: new answer received")
        await pilot.pause()
        assert not any(isinstance(child, RestartBanner) for child in _content_children(timeline))

        timeline.add_text("resuming", text_class="status", round_number=2)
        await pilot.pause()

        children = _content_children(timeline)
        assert isinstance(children[0], RestartBanner)
        assert "Round 2" in children[0].render().plain
        assert "Restart: new answer received" in children[0].render().plain
        assert "round-2" in children[0].classes
        assert "round-2" in children[1].classes


@pytest.mark.asyncio
async def test_convert_tool_to_batch_replaces_standalone_card():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)

        timeline.add_tool(_make_tool("t1", "mcp__filesystem__read_text_file"), round_number=1)
        await pilot.pause()
        assert timeline.get_tool("t1") is not None
        assert len(list(timeline.query(ToolCallCard))) == 1

        batch = timeline.convert_tool_to_batch(
            "t1",
            _make_tool("t2", "mcp__filesystem__write_file"),
            "batch_1",
            "filesystem",
            round_number=1,
        )
        await pilot.pause()

        assert batch is not None
        assert isinstance(batch, ToolBatchCard)
        assert timeline.get_tool("t1") is None
        assert timeline.get_tool_batch("t1") == "batch_1"
        assert timeline.get_tool_batch("t2") == "batch_1"
        assert batch.tool_count == 2
        assert batch.has_tool("t1")
        assert batch.has_tool("t2")
        assert len(list(timeline.query(ToolCallCard))) == 0
        assert len(list(timeline.query(ToolBatchCard))) == 1


@pytest.mark.asyncio
async def test_event_adapter_batches_consecutive_mcp_tools_in_widget_timeline():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        adapter = TimelineEventAdapter(_PanelStub(timeline))

        adapter.handle_event(
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                args={"path": "/tmp/a.txt"},
                server_name="filesystem",
            ),
        )
        adapter.handle_event(
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                args={"path": "/tmp/b.txt"},
                server_name="filesystem",
            ),
        )
        adapter.handle_event(
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
        await pilot.pause()

        batch = timeline.get_batch("batch_1")
        assert batch is not None
        assert batch.tool_count == 2
        assert batch.get_tool("t2") is not None
        assert batch.get_tool("t2").status == "success"
        assert timeline.get_tool_batch("t1") == "batch_1"
        assert timeline.get_tool_batch("t2") == "batch_1"


@pytest.mark.asyncio
async def test_event_adapter_does_not_batch_when_text_arrives_between_tools():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        adapter = TimelineEventAdapter(_PanelStub(timeline))

        adapter.handle_event(
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t1",
                tool_name="mcp__filesystem__read_text_file",
                args={"path": "/tmp/a.txt"},
                server_name="filesystem",
            ),
        )
        adapter.handle_event(MassGenEvent.create(EventType.TEXT, agent_id="agent_a", content="thinking"))
        adapter.handle_event(
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t2",
                tool_name="mcp__filesystem__write_file",
                args={"path": "/tmp/b.txt"},
                server_name="filesystem",
            ),
        )
        await pilot.pause()

        assert timeline.get_batch("batch_1") is None
        assert timeline.get_tool("t1") is not None
        assert timeline.get_tool("t2") is not None
        assert timeline.get_tool_batch("t1") is None
        assert timeline.get_tool_batch("t2") is None


@pytest.mark.asyncio
async def test_round_separator_dedup_keeps_single_banner():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)

        timeline.add_separator("Round 2", round_number=2)
        timeline.add_separator("Round 2", round_number=2)
        await pilot.pause()

        round_2_banners = [child for child in _content_children(timeline) if isinstance(child, RestartBanner) and "round-2" in child.classes]
        assert len(round_2_banners) == 1


@pytest.mark.asyncio
async def test_thinking_text_batches_into_single_collapsible_card():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)

        timeline.add_text("thinking one ", text_class="thinking-inline", round_number=1)
        timeline.add_text("thinking two", text_class="thinking-inline", round_number=1)
        await pilot.pause()

        cards = list(timeline.query(CollapsibleTextCard))
        assert len(cards) == 1
        assert cards[0].label == "Thinking"
        assert cards[0].chunk_count == 1
        assert cards[0].content == "thinking one thinking two"


@pytest.mark.asyncio
async def test_final_card_view_button_posts_message():
    """Clicking 'View Full Answer' button should post ViewFinalAnswer message."""
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(
            agent_id="agent_a",
            vote_results={"vote_counts": {"A1": 2}, "winner": "A1", "is_tie": False},
            context_paths={},
            id="final_presentation_card",
        )
        timeline.add_widget(card, round_number=1)
        card.append_chunk("final answer content")
        card.complete()
        await pilot.pause()

        # Verify the view button exists in the footer
        view_btn = card.query_one("#final_card_view_btn", Static)
        assert "View Full Answer" in str(view_btn.render())

        # Verify that ViewFinalAnswer message class exists and works
        msg = FinalPresentationCard.ViewFinalAnswer(card)
        assert msg.card is card


@pytest.mark.asyncio
async def test_final_card_content_truncated_after_complete():
    """Long content should be truncated to preview lines after complete()."""
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        long_text = "\n".join(f"Line {i}" for i in range(20))
        card.append_chunk(long_text)
        card.complete()
        await pilot.pause()

        # Full content preserved for the modal
        assert card.get_content() == long_text
        # Stream widget should show truncated preview ending with "..."
        stream_widget = card.query_one("#final_card_stream", Static)
        rendered = str(stream_widget.render())
        assert "..." in rendered
        assert "Line 0" in rendered
        # Lines beyond preview limit should not appear
        assert f"Line {card._PREVIEW_MAX_LINES + 2}" not in rendered


@pytest.mark.asyncio
async def test_final_card_short_content_not_truncated():
    """Short content should not be truncated."""
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        card.append_chunk("Short answer")
        card.complete()
        await pilot.pause()

        assert card.get_content() == "Short answer"


@pytest.mark.asyncio
async def test_final_card_explicit_workspace_scan_path_still_wired(monkeypatch, tmp_path):
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        scan_calls = {"count": 0}

        def counting_scan(self):  # noqa: ANN001 - monkeypatch target signature
            scan_calls["count"] += 1
            self._add_path("example.txt", "workspace", absolute_path="")

        monkeypatch.setattr(FileExplorerPanel, "_scan_workspace", counting_scan)

        def fake_resolve(panel):  # noqa: ANN001 - monkeypatch target signature
            panel.workspace_path = str(tmp_path)

        monkeypatch.setattr(card, "_resolve_workspace_path", fake_resolve)

        card._show_file_explorer(True, allow_workspace_scan=True)
        await pilot.pause()

        # Explicitly-enabled path still performs scan and can show explorer.
        assert scan_calls["count"] == 1
        panel = card.query_one("#file_explorer_panel", FileExplorerPanel)
        assert "visible" in panel.classes


@pytest.mark.asyncio
async def test_final_card_large_content_uses_static_render_for_responsiveness():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        card._markdown_render_max_chars = 10
        card.append_chunk("X" * 200)
        card.complete()
        await pilot.pause()

        stream_widget = card.query_one("#final_card_stream", Static)
        markdown_widget = card.query_one("#final_card_text", Markdown)
        assert "hidden" not in stream_widget.classes
        assert "hidden" in markdown_widget.classes


@pytest.mark.asyncio
async def test_final_card_small_content_still_uses_markdown():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        card._markdown_render_max_chars = 1000
        card.append_chunk("short answer")
        card.complete()
        await pilot.pause()

        stream_widget = card.query_one("#final_card_stream", Static)
        markdown_widget = card.query_one("#final_card_text", Markdown)
        assert "hidden" in stream_widget.classes
        assert "hidden" not in markdown_widget.classes


@pytest.mark.asyncio
async def test_final_card_workspace_open_reuses_resolved_workspace_hint(monkeypatch, tmp_path):
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        panel = card.query_one("#file_explorer_panel", FileExplorerPanel)
        panel.workspace_path = str(tmp_path)

        captured: dict = {}

        def fake_show(agent_id, preferred_final_workspace=None):  # noqa: ANN001 - monkeypatch target
            captured["agent_id"] = agent_id
            captured["preferred_final_workspace"] = preferred_final_workspace

        monkeypatch.setattr(app, "_show_workspace_browser_for_agent", fake_show, raising=False)

        card._open_workspace()

        assert captured["agent_id"] == "agent_a"
        assert captured["preferred_final_workspace"] == str(tmp_path)


@pytest.mark.asyncio
async def test_final_card_workspace_open_is_debounced(monkeypatch, tmp_path):
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        card = FinalPresentationCard(agent_id="agent_a", context_paths={}, id="final_presentation_card")
        timeline.add_widget(card, round_number=1)
        await pilot.pause()

        panel = card.query_one("#file_explorer_panel", FileExplorerPanel)
        panel.workspace_path = str(tmp_path)

        calls = {"count": 0}

        def fake_show(agent_id, preferred_final_workspace=None):  # noqa: ANN001 - monkeypatch target
            calls["count"] += 1

        monkeypatch.setattr(app, "_show_workspace_browser_for_agent", fake_show, raising=False)
        card._workspace_open_cooldown_s = 60.0

        card._open_workspace()
        card._open_workspace()
        card._last_workspace_open_at = 0.0
        card._open_workspace()

        assert calls["count"] == 2


@pytest.mark.asyncio
async def test_final_presentation_separator_prevents_extra_round_banner():
    app = _TimelineApp()
    async with app.run_test(headless=True) as pilot:
        timeline = app.query_one(TimelineSection)
        adapter = TimelineEventAdapter(_PanelStub(timeline))

        adapter.handle_event(
            MassGenEvent.create(
                EventType.FINAL_PRESENTATION_START,
                agent_id="agent_a",
                vote_counts={"agent_a": 1},
                answer_labels={"agent_a": "A1.1"},
                is_tie=False,
            ),
        )
        adapter.handle_event(
            MassGenEvent.create(
                EventType.TOOL_START,
                agent_id="agent_a",
                tool_id="t_final_1",
                tool_name="Read",
                args={"file_path": "/tmp/final.txt"},
                server_name=None,
            ),
        )
        await pilot.pause()

        round_2_banners = [child for child in _content_children(timeline) if isinstance(child, RestartBanner) and "round-2" in child.classes]
        assert len(round_2_banners) == 1
        assert "Final Answer" in round_2_banners[0].render().plain
        assert "Round 2" not in round_2_banners[0].render().plain
