"""Tests for background job indicator in AgentStatusRibbon."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from massgen.frontend.displays.textual_widgets.agent_status_ribbon import (
    AgentStatusRibbon,
    BackgroundTasksLabel,
    TasksLabel,
)


class _RibbonApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.clicked_agent_id: str | None = None

    def compose(self) -> ComposeResult:
        yield AgentStatusRibbon(agent_id="agent_a", id="ribbon")

    def on_background_tasks_clicked(self, event) -> None:  # noqa: ANN001 - Textual event handler
        self.clicked_agent_id = event.agent_id


@pytest.mark.asyncio
async def test_background_indicator_shows_next_to_tasks_in_ribbon():
    app = _RibbonApp()
    async with app.run_test(headless=True) as pilot:
        ribbon = app.query_one(AgentStatusRibbon)
        ribbon.set_tasks("agent_a", 10, 16)
        ribbon.set_background_jobs("agent_a", 2)
        await pilot.pause()

        tasks_label = app.query_one("#tasks_display", TasksLabel)
        bg_label = app.query_one("#background_tasks_display", BackgroundTasksLabel)

        assert "Tasks 10/16" in str(tasks_label.render())
        assert "BG 2" in str(bg_label.render())
        assert "hidden" not in bg_label.classes
        assert bg_label.region.x > tasks_label.region.x


@pytest.mark.asyncio
async def test_background_indicator_click_emits_background_tasks_clicked_message():
    app = _RibbonApp()
    async with app.run_test(headless=True) as pilot:
        ribbon = app.query_one(AgentStatusRibbon)
        ribbon.set_background_jobs("agent_a", 1)
        await pilot.pause()

        bg_label = app.query_one("#background_tasks_display", BackgroundTasksLabel)
        await bg_label.on_click()
        await pilot.pause()

        assert app.clicked_agent_id == "agent_a"
