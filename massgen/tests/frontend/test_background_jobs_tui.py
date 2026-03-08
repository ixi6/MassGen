"""Frontend tests for generalized background-job tracking in the TUI."""

from __future__ import annotations

import json

import pytest
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.textual_widgets.background_tasks_modal import (
    BackgroundTaskDetailModal,
    BackgroundTasksModal,
)
from massgen.frontend.displays.textual_widgets.content_sections import TimelineSection
from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard


class _StatusBarStub:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def update_running_tools(self, count: int, background_count: int = 0) -> None:
        self.calls.append((count, background_count))


class _RibbonStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def set_background_jobs(self, agent_id: str, count: int) -> None:
        self.calls.append((agent_id, count))


class _PanelStub:
    def __init__(
        self,
        running_count: int,
        background_jobs: list[dict],
        background_history: list[dict] | None = None,
    ) -> None:
        self._running_count = running_count
        self._background_jobs = background_jobs
        self._background_history = background_history or []

    def _get_running_tools_count(self) -> int:
        return self._running_count

    def _get_background_tools(self) -> list[dict]:
        return self._background_jobs

    def _get_background_tool_history(self) -> list[dict]:
        return self._background_history


class _BackgroundDetailModalHostApp(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


def test_timeline_get_background_tools_includes_generalized_metadata():
    timeline = TimelineSection(id="timeline")

    card = ToolCallCard(
        tool_name="mcp__media__generate_image",
        tool_type="mcp",
        call_id="tool_bg_1",
    )
    card.set_params(
        "background start args",
        params_full='{"tool_name":"custom_tool__generate_media","arguments":{"prompts":["p1","p2"]}}',
    )
    card.set_background_result(
        "started in background",
        result_full='{"status":"background","job_id":"bgtool_123"}',
        async_id="bgtool_123",
    )

    timeline._tools["tool_bg_1"] = card

    jobs = timeline.get_background_tools()

    assert len(jobs) == 1
    assert jobs[0]["tool_id"] == "tool_bg_1"
    assert jobs[0]["tool_name"] == "mcp__media__generate_image"
    assert jobs[0]["tool_type"] == "mcp"
    assert jobs[0]["status"] == "background"
    assert jobs[0]["async_id"] == "bgtool_123"
    assert jobs[0]["params"] == '{"tool_name":"custom_tool__generate_media","arguments":{"prompts":["p1","p2"]}}'


def test_timeline_background_jobs_excludes_terminal_status_jobs():
    """Background list/count should hide jobs once terminal status is observed for job_id."""
    timeline = TimelineSection(id="timeline")

    start_card = ToolCallCard(
        tool_name="custom_tool__start_background_tool",
        tool_type="tool",
        call_id="tool_bg_start",
    )
    start_card.set_background_result(
        "started in background",
        result_full='{"job_id":"bgtool_123","status":"running","success":true}',
        async_id="bgtool_123",
    )

    poll_card = ToolCallCard(
        tool_name="custom_tool__get_background_tool_result",
        tool_type="tool",
        call_id="tool_bg_poll",
    )
    poll_card.set_result(
        "job completed",
        result_full='{"job_id":"bgtool_123","status":"completed","ready":true,"success":true}',
    )

    timeline._tools["tool_bg_start"] = start_card
    timeline._tools["tool_bg_poll"] = poll_card

    assert timeline.get_background_tools() == []
    assert timeline.get_background_tools_count() == 0


def test_background_task_detail_modal_shows_full_request_prompt_payload():
    task_data = {
        "tool_name": "custom_tool__start_background_tool",
        "display_name": "Start Background Tool",
        "tool_type": "tool",
        "status": "background",
        "async_id": "bgtool_e1b83f3a1b02",
        "params": json.dumps(
            {
                "tool_name": "custom_tool__generate_media",
                "arguments": {
                    "mode": "image",
                    "prompts": [
                        "A majestic mountain goat standing on a rocky cliff at sunset",
                        "A playful baby goat jumping in a meadow with wildflowers",
                    ],
                },
            },
        ),
        "result": '{"job_id":"bgtool_e1b83f3a1b02","status":"running"}',
    }

    modal = BackgroundTaskDetailModal(task_data)
    info_plain = modal._build_info().plain

    assert "Request:" in info_plain
    assert "A majestic mountain goat standing on a rocky cliff at sunset" in info_plain
    assert "A playful baby goat jumping in a meadow with wildflowers" in info_plain


@pytest.mark.asyncio
async def test_background_task_detail_modal_uses_scrollable_info_and_output_sections():
    long_prompts = [f"Prompt line {i}: describe the goat image quality in detail." for i in range(120)]
    task_data = {
        "tool_name": "custom_tool__read_media",
        "display_name": "Read Media",
        "tool_type": "tool",
        "status": "background",
        "async_id": "bgtool_scroll_test",
        "params": json.dumps({"inputs": [{"files": {"goat1": "goat1.png"}, "prompt": p} for p in long_prompts]}),
        "result": json.dumps({"stdout": "\n".join(long_prompts)}),
    }

    app = _BackgroundDetailModalHostApp()
    async with app.run_test(headless=True, size=(120, 30)) as pilot:
        detail_modal = BackgroundTaskDetailModal(task_data)
        app.push_screen(detail_modal)
        await pilot.pause()

        info_section = detail_modal.query_one("#info_section", ScrollableContainer)
        output_section = detail_modal.query_one(".output-section", ScrollableContainer)

        assert info_section is not None
        assert output_section is not None
        assert info_section.max_scroll_y >= 0
        assert output_section.max_scroll_y >= 0


def test_action_open_background_tools_aggregates_jobs_across_agents():
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    app.agent_widgets = {
        "agent_a": _PanelStub(
            running_count=2,
            background_jobs=[{"tool_name": "tool_a", "async_id": "job_a"}],
        ),
        "agent_b": _PanelStub(
            running_count=1,
            background_jobs=[{"tool_name": "tool_b", "async_id": "job_b"}],
        ),
    }

    captured: dict[str, object] = {}
    app._show_modal_async = lambda modal: captured.setdefault("modal", modal)
    app.notify = lambda *_args, **_kwargs: captured.setdefault("notified", True)

    app.action_open_background_tools()

    modal = captured.get("modal")
    assert isinstance(modal, BackgroundTasksModal)

    assert len(modal.background_tasks) == 2
    assert {task["agent_id"] for task in modal.background_tasks} == {"agent_a", "agent_b"}


def test_action_open_background_tools_notifies_when_empty():
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    app.agent_widgets = {"agent_a": _PanelStub(running_count=0, background_jobs=[])}

    captured: dict[str, object] = {}
    app._show_modal_async = lambda modal: captured.setdefault("modal", modal)
    app.notify = lambda message, **_kwargs: captured.setdefault("message", message)

    app.action_open_background_tools()

    assert captured.get("modal") is None
    assert captured.get("message") == "No background jobs running"


def test_action_open_background_tools_shows_recent_completed_history() -> None:
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    app.agent_widgets = {
        "agent_a": _PanelStub(
            running_count=0,
            background_jobs=[],
            background_history=[
                {
                    "tool_name": "custom_tool__generate_media",
                    "display_name": "Generate Media",
                    "status": "completed",
                    "is_active": False,
                    "async_id": "bgtool_done_1",
                    "agent_id": "agent_a",
                },
            ],
        ),
    }

    captured: dict[str, object] = {}
    app._show_modal_async = lambda modal: captured.setdefault("modal", modal)
    app.notify = lambda *_args, **_kwargs: captured.setdefault("notified", True)

    app.action_open_background_tools()

    modal = captured.get("modal")
    assert isinstance(modal, BackgroundTasksModal)
    assert modal.background_tasks == []
    assert len(modal.recent_tasks) == 1
    assert modal.recent_tasks[0]["status"] == "completed"


def test_update_running_tools_count_aggregates_across_agent_panels():
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    app._status_bar = _StatusBarStub()
    app._status_ribbon = _RibbonStub()
    app.agent_widgets = {
        "agent_a": _PanelStub(
            running_count=3,
            background_jobs=[{"tool_name": "tool_a", "async_id": "job_a"}],
        ),
        "agent_b": _PanelStub(
            running_count=1,
            background_jobs=[],
        ),
    }

    app._update_running_tools_count()

    assert app._status_bar.calls[-1] == (4, 1)
    assert ("agent_a", 1) in app._status_ribbon.calls
    assert ("agent_b", 0) in app._status_ribbon.calls


def test_status_bar_tools_click_opens_background_tools_modal():
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    captured: dict[str, object] = {}
    app.action_open_background_tools = lambda: captured.setdefault("opened", True)

    event = textual_display_module.StatusBarToolsClicked()
    app.on_status_bar_tools_clicked(event)

    assert captured.get("opened") is True


def test_ribbon_background_tasks_click_opens_background_tools_modal():
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)

    captured: dict[str, object] = {}
    app.agent_widgets = {
        "agent_a": _PanelStub(
            running_count=1,
            background_jobs=[{"tool_name": "tool_a", "async_id": "job_a"}],
        ),
        "agent_b": _PanelStub(
            running_count=2,
            background_jobs=[{"tool_name": "tool_b", "async_id": "job_b"}],
        ),
    }
    app._show_modal_async = lambda modal: captured.setdefault("modal", modal)
    app.notify = lambda *_args, **_kwargs: captured.setdefault("notified", True)

    event = textual_display_module.BackgroundTasksClicked("agent_a")
    app.on_background_tasks_clicked(event)

    modal = captured.get("modal")
    assert isinstance(modal, BackgroundTasksModal)
    assert modal.agent_id == "agent_a"
    assert len(modal.background_tasks) == 1
    assert modal.background_tasks[0]["tool_name"] == "tool_a"
