"""Regression tests for subagent card completion wiring in Textual TUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from textual.app import App, ComposeResult

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.textual_widgets.content_sections import TimelineSection
from massgen.frontend.displays.textual_widgets.subagent_card import (
    SubagentCard,
    SubagentColumn,
)
from massgen.subagent.models import SubagentDisplayData


def _make_subagent(
    subagent_id: str,
    *,
    status: str = "running",
    task: str = "evaluate output",
    elapsed_seconds: float = 0.0,
    timeout_seconds: float = 300.0,
    subagent_type: str | None = None,
) -> SubagentDisplayData:
    return SubagentDisplayData(
        id=subagent_id,
        task=task,
        status=status,
        progress_percent=0,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=timeout_seconds,
        workspace_path="",
        workspace_file_count=0,
        last_log_line="",
        error=None,
        answer_preview=None,
        log_path=None,
        subagent_type=subagent_type,
    )


class _FakeCard:
    def __init__(self, subagents: list[SubagentDisplayData], tool_call_id: str) -> None:
        self.subagents = subagents
        self.tool_call_id = tool_call_id
        self.id = f"subagent_{tool_call_id}"
        self.last_update: list[SubagentDisplayData] | None = None

    def update_subagents(self, subagents: list[SubagentDisplayData]) -> None:
        self.subagents = subagents
        self.last_update = subagents


class _FakeTimeline:
    def __init__(self, card: _FakeCard) -> None:
        self._card = card

    def query_one(self, selector: str, _cls):  # noqa: ANN001 - Textual query compat
        if selector == f"#subagent_{self._card.tool_call_id}":
            return self._card
        raise LookupError(selector)

    def query(self, _cls):  # noqa: ANN001 - Textual query compat
        return [self._card]


class _CardHostApp(App):
    def __init__(self, card: SubagentCard) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        yield self._card


class _SpawnTimeline:
    def __init__(self, existing_cards: list[object] | None = None) -> None:
        self._existing_cards = existing_cards or []
        self.added_round_numbers: list[int] = []
        self.added_cards: list[object] = []

    def query(self, _cls):  # noqa: ANN001 - Textual query compat
        return list(self._existing_cards)

    def add_widget(self, card, round_number: int = 1):  # noqa: ANN001 - Textual compat
        self.added_round_numbers.append(round_number)
        self.added_cards.append(card)


class _SpawnPanel:
    def __init__(self, timeline: _SpawnTimeline, current_round: int = 1) -> None:
        self._timeline = timeline
        self._timeline_section_id = "timeline"
        self._current_round = current_round

    def _hide_loading(self) -> None:
        return None

    def query_one(self, selector: str, _cls):  # noqa: ANN001 - Textual query compat
        if selector == "#timeline":
            return self._timeline
        raise LookupError(selector)


class _HistoryPanel:
    def __init__(self, history: list[dict[str, Any]]) -> None:
        self._history = history

    def _get_background_tool_history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def query(self, _cls):  # noqa: ANN001 - Textual query compat
        return []


class _KnownStatusTimeline:
    def __init__(self, statuses: dict[str, str]) -> None:
        self._statuses = statuses

    def _collect_known_background_statuses(self) -> dict[str, str]:
        return dict(self._statuses)


class _KnownStatusPanel:
    def __init__(self, timeline: _KnownStatusTimeline) -> None:
        self._timeline = timeline

    def _get_timeline(self) -> _KnownStatusTimeline:
        return self._timeline

    def query(self, _cls):  # noqa: ANN001 - Textual query compat
        return []


class _ExistingSubagentCard:
    def __init__(self, tool_call_id: str) -> None:
        self._tool_call_id = tool_call_id
        self.tool_call_id = tool_call_id
        self.removed = False

    def remove(self) -> None:
        self.removed = True


class _ArgsTimeline:
    def __init__(self) -> None:
        self.added_round_number: int | None = None
        self.added_card: object | None = None

    def query_one(self, _selector: str, _cls):  # noqa: ANN001 - Textual query compat
        raise LookupError(_selector)

    def query(self, _cls):  # noqa: ANN001 - Textual query compat
        return []

    def add_widget(self, card, round_number: int = 1):  # noqa: ANN001 - Textual compat
        self.added_round_number = round_number
        self.added_card = card


def test_update_subagent_card_with_repr_result_payload_updates_status():
    """spawn_subagents repr payloads should still mark cards as completed."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)

    running = _make_subagent("evaluator_beatles_site", status="running")
    card = _FakeCard([running], tool_call_id="item_33")
    timeline = _FakeTimeline(card)

    result_payload = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "operation": "spawn_subagents",
                        "results": [
                            {
                                "subagent_id": "evaluator_beatles_site",
                                "status": "completed",
                                "success": True,
                                "answer": "## Evaluation complete",
                                "workspace": "/tmp/workspace",
                                "execution_time_seconds": 12.5,
                            },
                        ],
                    },
                ),
            },
        ],
        "structured_content": {
            "success": True,
            "operation": "spawn_subagents",
            "results": [
                {
                    "subagent_id": "evaluator_beatles_site",
                    "status": "completed",
                    "success": True,
                    "answer": "## Evaluation complete",
                    "workspace": "/tmp/workspace",
                    "execution_time_seconds": 12.5,
                },
            ],
        },
    }
    tool_data = SimpleNamespace(
        tool_id="item_33",
        tool_name="subagent_agent_a/spawn_subagents",
        result_full=str(result_payload),  # real logs often use Python repr payloads
    )

    panel._update_subagent_card_with_results(tool_data, timeline)

    assert card.last_update is not None
    assert card.subagents[0].status == "completed"
    assert card.subagents[0].answer_preview == "## Evaluation complete"


def test_show_subagent_card_from_spawn_uses_current_round_and_keeps_existing_cards(monkeypatch) -> None:
    """Spawn callback cards should stay in the current round and not purge unrelated cards."""
    existing_card = _ExistingSubagentCard("call_old")
    timeline = _SpawnTimeline(existing_cards=[existing_card])
    panel = _SpawnPanel(timeline, current_round=3)

    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.agent_widgets = {"agent_a": panel}
    app._build_spawn_status_callback = lambda agent_id, seed_subagents, card=None: None

    monkeypatch.setattr(textual_display_module, "get_log_session_dir", lambda: None)

    app.show_subagent_card_from_spawn(
        agent_id="agent_a",
        args={
            "tasks": [
                {
                    "subagent_id": "evaluator",
                    "task": "Evaluate current website behavior",
                },
            ],
        },
        call_id="call:27.1",
    )

    assert existing_card.removed is False
    assert timeline.added_round_numbers == [3]
    assert len(timeline.added_cards) == 1
    card = timeline.added_cards[0]
    assert isinstance(card, SubagentCard)
    assert card.id is not None
    assert ":" not in card.id
    assert "." not in card.id


def test_show_subagent_card_from_spawn_carries_context_paths(monkeypatch) -> None:
    """Spawn callback cards should keep task context paths for subagent top-bar display."""
    timeline = _SpawnTimeline(existing_cards=[])
    panel = _SpawnPanel(timeline, current_round=2)

    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.agent_widgets = {"agent_a": panel}
    app._build_spawn_status_callback = lambda agent_id, seed_subagents, card=None: None

    monkeypatch.setattr(textual_display_module, "get_log_session_dir", lambda: None)

    app.show_subagent_card_from_spawn(
        agent_id="agent_a",
        args={
            "tasks": [
                {
                    "subagent_id": "evaluator",
                    "task": "Evaluate current website behavior",
                    "context_paths": ["docs/brief.md", "src/components"],
                },
            ],
        },
        call_id="call:ctx.1",
    )

    assert len(timeline.added_cards) == 1
    card = timeline.added_cards[0]
    assert isinstance(card, SubagentCard)
    assert getattr(card.subagents[0], "context_paths", None) == ["docs/brief.md", "src/components"]


def test_show_subagent_card_from_spawn_carries_subagent_type(monkeypatch) -> None:
    """Spawn callback cards should keep specialized subagent type labels for UI display."""
    timeline = _SpawnTimeline(existing_cards=[])
    panel = _SpawnPanel(timeline, current_round=2)

    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.agent_widgets = {"agent_a": panel}
    app._build_spawn_status_callback = lambda agent_id, seed_subagents, card=None: None

    monkeypatch.setattr(textual_display_module, "get_log_session_dir", lambda: None)

    app.show_subagent_card_from_spawn(
        agent_id="agent_a",
        args={
            "tasks": [
                {
                    "subagent_id": "explorer_scan",
                    "task": "Analyze repository structure",
                    "subagent_type": "explorer",
                },
            ],
        },
        call_id="call:type.1",
    )

    assert len(timeline.added_cards) == 1
    card = timeline.added_cards[0]
    assert isinstance(card, SubagentCard)
    assert getattr(card.subagents[0], "subagent_type", None) == "explorer"


def test_show_subagent_card_from_spawn_builds_card_scoped_status_callback(monkeypatch) -> None:
    """Spawn callback should scope status polling to the newly-created card."""
    timeline = _SpawnTimeline(existing_cards=[])
    panel = _SpawnPanel(timeline, current_round=2)

    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.agent_widgets = {"agent_a": panel}

    captured_cards: list[object | None] = []

    def _capture_callback(agent_id, seed_subagents, card=None):  # noqa: ANN001 - test helper shape
        captured_cards.append(card)
        return None

    app._build_spawn_status_callback = _capture_callback
    monkeypatch.setattr(textual_display_module, "get_log_session_dir", lambda: None)

    app.show_subagent_card_from_spawn(
        agent_id="agent_a",
        args={
            "tasks": [
                {
                    "subagent_id": "retry_same_id",
                    "task": "Run evaluator task",
                },
            ],
        },
        call_id="call:scoped.spawn",
    )

    assert len(timeline.added_cards) == 1
    assert len(captured_cards) == 1
    assert captured_cards[0] is timeline.added_cards[0]
    assert isinstance(captured_cards[0], SubagentCard)


def test_build_subagent_display_data_preserves_existing_context_paths() -> None:
    """Status refreshes should not drop previously-known subagent context paths."""
    existing = _make_subagent("evaluator_beatles_site", status="running")
    existing.context_paths = ["docs/brief.md"]

    updated = textual_display_module._build_subagent_display_data(
        {
            "subagent_id": "evaluator_beatles_site",
            "status": "running",
            "execution_time_seconds": 1.5,
        },
        existing,
    )

    assert getattr(updated, "context_paths", None) == ["docs/brief.md"]


def test_build_subagent_display_data_preserves_existing_subagent_type() -> None:
    """Status refreshes should not drop previously-known specialized subagent type."""
    existing = _make_subagent("explorer_scan", status="running", subagent_type="explorer")

    updated = textual_display_module._build_subagent_display_data(
        {
            "subagent_id": "explorer_scan",
            "status": "running",
            "execution_time_seconds": 2.0,
        },
        existing,
    )

    assert getattr(updated, "subagent_type", None) == "explorer"


def test_build_subagent_display_data_reads_subprocess_reference_error(tmp_path) -> None:
    """Terminal refreshes should surface subprocess reference errors for display."""
    log_dir = tmp_path / "subagent_logs" / "remote_evaluator"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "subprocess_logs.json").write_text(
        json.dumps(
            {
                "subagent_id": "remote_evaluator",
                "error": "Subagent cancelled",
            },
        ),
    )

    existing = _make_subagent("remote_evaluator", status="running")
    existing.log_path = str(log_dir)

    updated = textual_display_module._build_subagent_display_data(
        {
            "subagent_id": "remote_evaluator",
            "status": "failed",
        },
        existing,
    )

    assert updated.error == "Subagent cancelled"


def test_show_subagent_card_from_args_respects_round_number() -> None:
    """Fallback subagent card path should place cards in the active round."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)
    panel.agent_id = "agent_a"

    timeline = _ArgsTimeline()
    tool_data = SimpleNamespace(
        tool_id="call:subagent.42",
        args_full=json.dumps(
            {
                "tasks": [
                    {
                        "subagent_id": "evaluator",
                        "task": "Verify responsive layout",
                    },
                ],
            },
        ),
    )

    panel._show_subagent_card_from_args(tool_data, timeline, round_number=4)

    assert timeline.added_round_number == 4
    assert isinstance(timeline.added_card, SubagentCard)


def test_show_subagent_card_from_args_supports_continue_subagent() -> None:
    """Continue-subagent tool args should render a single-running SubagentCard."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)
    panel.agent_id = "agent_a"

    timeline = _ArgsTimeline()
    tool_data = SimpleNamespace(
        tool_id="call:subagent.continue",
        tool_name="subagent_agent_a/continue_subagent",
        args_full=json.dumps(
            {
                "subagent_id": "evaluator",
                "message": "Continue with deeper accessibility review",
                "timeout_seconds": 240,
            },
        ),
    )

    assert panel._is_subagent_tool(tool_data.tool_name, tool_data.args_full) is True
    panel._show_subagent_card_from_args(tool_data, timeline, round_number=3)

    assert timeline.added_round_number == 3
    assert isinstance(timeline.added_card, SubagentCard)
    assert timeline.added_card.subagents[0].id == "evaluator"
    assert timeline.added_card.subagents[0].status == "running"
    assert "deeper accessibility review" in timeline.added_card.subagents[0].task


def test_show_subagent_card_from_args_accepts_start_background_wrapper_payload() -> None:
    """Wrapper start_background_tool payloads targeting spawn_subagents should still render SubagentCard."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)
    panel.agent_id = "agent_a"

    timeline = _ArgsTimeline()
    tool_data = SimpleNamespace(
        tool_id="call:subagent.wrapper",
        tool_name="custom_tool__start_background_tool",
        args_full=json.dumps(
            {
                "tool_name": "mcp__subagent_agent_a__spawn_subagents",
                "arguments": {
                    "tasks": [
                        {
                            "subagent_id": "jazz_researcher",
                            "task": "Research jazz history",
                        },
                    ],
                    "background": False,
                },
            },
        ),
    )

    assert panel._is_subagent_tool(tool_data.tool_name, tool_data.args_full) is True
    panel._show_subagent_card_from_args(tool_data, timeline, round_number=2)

    assert timeline.added_round_number == 2
    assert isinstance(timeline.added_card, SubagentCard)
    assert timeline.added_card.subagents[0].id == "jazz_researcher"


def test_update_subagent_card_with_continue_result_payload_updates_status() -> None:
    """continue_subagent payloads should update existing SubagentCard status."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)

    running = _make_subagent("evaluator", status="running")
    card = _FakeCard([running], tool_call_id="item_77")
    timeline = _FakeTimeline(card)

    result_payload = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "success": True,
                        "operation": "continue_subagent",
                        "subagent_id": "evaluator",
                        "status": "completed",
                        "answer": "Follow-up complete with accessibility fixes.",
                        "workspace": "/tmp/workspace",
                        "execution_time_seconds": 8.0,
                    },
                ),
            },
        ],
        "structured_content": {
            "success": True,
            "operation": "continue_subagent",
            "subagent_id": "evaluator",
            "status": "completed",
            "answer": "Follow-up complete with accessibility fixes.",
            "workspace": "/tmp/workspace",
            "execution_time_seconds": 8.0,
        },
    }
    tool_data = SimpleNamespace(
        tool_id="item_77",
        tool_name="subagent_agent_a/continue_subagent",
        result_full=str(result_payload),  # real logs often use Python repr payloads
    )

    panel._update_subagent_card_with_results(tool_data, timeline)

    assert card.last_update is not None
    assert card.subagents[0].status == "completed"
    assert card.subagents[0].answer_preview == "Follow-up complete with accessibility fixes."


def test_show_subagent_card_from_args_builds_card_scoped_status_callback(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Fallback args path should scope status callback to the card it just created."""
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)
    panel.agent_id = "agent_a"

    captured_cards: list[object | None] = []
    fake_app = SimpleNamespace(
        _build_spawn_status_callback=lambda agent_id, seed_subagents, card=None: captured_cards.append(card) or None,
    )
    monkeypatch.setattr(panel_cls, "app", property(lambda _self: fake_app), raising=False)

    timeline = _ArgsTimeline()
    tool_data = SimpleNamespace(
        tool_id="call:subagent.scoped.args",
        tool_name="subagent_agent_a/spawn_subagents",
        args_full=json.dumps(
            {
                "tasks": [
                    {
                        "subagent_id": "retry_same_id",
                        "task": "Retry task",
                    },
                ],
            },
        ),
    )

    panel._show_subagent_card_from_args(tool_data, timeline, round_number=2)

    assert isinstance(timeline.added_card, SubagentCard)
    assert len(captured_cards) == 1
    assert captured_cards[0] is timeline.added_card


def test_spawn_status_callback_uses_spawn_status_file_when_tool_result_is_missing(tmp_path):
    """Spawn status file should unblock cards that otherwise remain running."""
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.agent_widgets = {}

    workspace = tmp_path / "workspace_agent_a"
    status_file = workspace / "subagents" / "_spawn_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(
        json.dumps(
            {
                "status": "completed",
                "subagents": [
                    {
                        "subagent_id": "evaluator_beatles_site_round2",
                        "status": "completed",
                        "answer": "# Final evaluator report",
                        "workspace": str(workspace / "subagents" / "evaluator_beatles_site_round2" / "workspace"),
                        "execution_time_seconds": 42.0,
                    },
                ],
            },
        ),
    )

    filesystem_manager = SimpleNamespace(get_current_workspace=lambda: workspace)
    orchestrator = SimpleNamespace(
        agents={
            "agent_a": SimpleNamespace(
                backend=SimpleNamespace(filesystem_manager=filesystem_manager),
            ),
        },
    )
    app.coordination_display = SimpleNamespace(orchestrator=orchestrator)

    initial = _make_subagent(
        "evaluator_beatles_site_round2",
        status="running",
        task="re-evaluate website after fixes",
        timeout_seconds=300.0,
    )

    callback = app._build_spawn_status_callback("agent_a", [initial])
    updated = callback("evaluator_beatles_site_round2")

    assert updated is not None
    assert updated.status == "completed"
    assert updated.answer_preview == "# Final evaluator report"


def test_spawn_status_callback_uses_background_history_on_cancel() -> None:
    """When _spawn_status.json is missing, background history should mark cancellation."""
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    history_entry = {
        "async_id": "remote_evaluator",
        "latest_status": "cancelled",
        "is_active": False,
        "result": "Cancelled by user",
    }
    panel = _HistoryPanel([history_entry])
    app.agent_widgets = {"agent_a": panel}
    app.coordination_display = SimpleNamespace(orchestrator=SimpleNamespace(agents={}))

    initial = _make_subagent(
        "remote_evaluator",
        status="running",
        task="re-evaluate asynchronous path",
        timeout_seconds=300.0,
    )

    callback = app._build_spawn_status_callback("agent_a", [initial])
    updated = callback("remote_evaluator")

    assert updated is not None
    assert updated.status == "canceled"
    assert updated.error == "Cancelled by user"


def test_spawn_status_callback_uses_known_background_statuses_without_history() -> None:
    """Terminal statuses from timeline payloads should update spawn cards."""
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    timeline = _KnownStatusTimeline({"remote_evaluator": "cancelled"})
    panel = _KnownStatusPanel(timeline)
    app.agent_widgets = {"agent_a": panel}
    app.coordination_display = SimpleNamespace(orchestrator=SimpleNamespace(agents={}))

    initial = _make_subagent(
        "remote_evaluator",
        status="running",
        task="monitor cancellation wiring",
        timeout_seconds=300.0,
    )

    callback = app._build_spawn_status_callback("agent_a", [initial])
    updated = callback("remote_evaluator")

    assert updated is not None
    assert updated.status == "canceled"


def test_extract_background_statuses_from_subagent_payloads() -> None:
    """ToolSection status extraction should understand subagent lifecycle payloads."""
    # cancel_subagent style payload
    cancel_payload = json.dumps(
        {
            "success": True,
            "operation": "cancel_subagent",
            "subagent_id": "jazz_research",
            "status": "cancelled",
        },
    )
    cancel_statuses = TimelineSection._extract_background_statuses_from_payload(cancel_payload)
    assert cancel_statuses.get("jazz_research") == "cancelled"

    # list_subagents style payload
    list_payload = json.dumps(
        {
            "success": True,
            "operation": "list_subagents",
            "subagents": [
                {
                    "subagent_id": "jazz_research",
                    "status": "cancelled",
                },
            ],
        },
    )
    list_statuses = TimelineSection._extract_background_statuses_from_payload(list_payload)
    assert list_statuses.get("jazz_research") == "cancelled"

    # spawn_subagents style payload
    spawn_payload = json.dumps(
        {
            "success": True,
            "operation": "spawn_subagents",
            "subagents": [
                {
                    "subagent_id": "jazz_research",
                    "status": "running",
                },
            ],
        },
    )
    spawn_statuses = TimelineSection._extract_background_statuses_from_payload(spawn_payload)
    assert spawn_statuses.get("jazz_research") == "running"


def test_running_progress_bar_caps_at_99_percent() -> None:
    """Running subagents should not render a full 100% bar until terminal state."""
    subagent = _make_subagent(
        "sub_1",
        status="running",
        elapsed_seconds=999.0,
        timeout_seconds=300.0,
    )
    column = SubagentColumn(
        subagent=subagent,
        all_subagents=[subagent],
        summary="running",
        tools=[],
        open_callback=lambda _subagent, _all_subagents: None,
    )

    bar = column._build_progress_bar()
    assert "99%" in bar.plain
    assert "100%" not in bar.plain


def test_completed_progress_bar_has_no_inline_done_label() -> None:
    """Completed bar should fill the row without an early inline 'Done' suffix."""
    subagent = _make_subagent(
        "sub_done",
        status="completed",
        elapsed_seconds=42.0,
        timeout_seconds=300.0,
    )
    column = SubagentColumn(
        subagent=subagent,
        all_subagents=[subagent],
        summary="done",
        tools=[],
        open_callback=lambda _subagent, _all_subagents: None,
    )

    bar = column._build_progress_bar()
    assert "Done" not in bar.plain
    assert "✓" not in bar.plain


def test_completed_progress_bar_uses_available_width(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Completed bar should use measured row width so it reaches the column edge."""
    subagent = _make_subagent(
        "sub_done_wide",
        status="completed",
        elapsed_seconds=5.0,
        timeout_seconds=300.0,
    )
    column = SubagentColumn(
        subagent=subagent,
        all_subagents=[subagent],
        summary="done",
        tools=[],
        open_callback=lambda _subagent, _all_subagents: None,
    )

    monkeypatch.setattr(column, "_measure_progress_bar_width", lambda _suffix_width=0: 37, raising=False)

    bar = column._build_progress_bar()
    assert bar.plain == "━" * 37


def test_subagent_column_header_includes_subagent_type_when_available() -> None:
    """Subagent header should surface specialized type on the right side when present."""
    subagent = _make_subagent(
        "analysis_worker",
        status="running",
        elapsed_seconds=65.0,
        subagent_type="explorer",
    )
    column = SubagentColumn(
        subagent=subagent,
        all_subagents=[subagent],
        summary="running",
        tools=[],
        open_callback=lambda _subagent, _all_subagents: None,
    )

    header = column._build_header()
    assert "explorer" in header.plain.lower()


def test_subagent_column_header_right_aligns_type_and_timing(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Type/timing suffix should be right-aligned in the header row."""
    subagent = _make_subagent(
        "analysis_worker",
        status="running",
        elapsed_seconds=65.0,
        subagent_type="explorer",
    )
    column = SubagentColumn(
        subagent=subagent,
        all_subagents=[subagent],
        summary="running",
        tools=[],
        open_callback=lambda _subagent, _all_subagents: None,
    )

    monkeypatch.setattr(column, "_measure_header_width", lambda: 40, raising=False)

    header_plain = column._build_header().plain
    assert len(header_plain) == 40
    assert "[explorer]" in header_plain
    assert header_plain.endswith("5s ▸")


def test_subagent_card_open_modal_event_carries_source_card() -> None:
    """OpenModal events should include source card for same-ID collision handling."""
    running = _make_subagent("evaluator_beatles_site", status="running")
    card = SubagentCard(subagents=[running], tool_call_id="item_88")

    posted: list[object] = []
    card.post_message = lambda message: posted.append(message)  # type: ignore[assignment]

    card._request_open(running, [running])

    assert posted
    event = posted[0]
    assert getattr(event, "card", None) is card


async def test_subagent_card_ignores_style_env_variants(monkeypatch) -> None:  # noqa: ANN001 - pytest fixture type
    """Subagent card should stay on Option A styling regardless of env variant value."""
    monkeypatch.setenv("MASSGEN_SUBAGENT_CARD_STYLE", "option-b")

    running = _make_subagent("evaluator_beatles_site", status="running")
    card = SubagentCard(subagents=[running], tool_call_id="item_44")
    app = _CardHostApp(card)

    async with app.run_test(headless=True, size=(120, 24)):
        assert card.has_class("variant-a")
        assert not card.has_class("variant-b")
        assert not card.has_class("variant-c")


def test_subagent_column_focus_border_is_thin() -> None:
    """Focused subagent columns should use a thin focus border, not thick."""
    css = Path("massgen/frontend/displays/textual_themes/base.tcss").read_text(encoding="utf-8")
    match = re.search(r"SubagentColumn:focus\s*\{([^}]*)\}", css, re.DOTALL)
    assert match is not None
    block = match.group(1)
    assert "border-left: thick" not in block
    assert "border-left: none" in block


def test_update_subagent_card_preserves_type_when_server_assigns_different_id() -> None:
    """subagent_type must survive when the MCP server assigns a different ID than
    the placeholder used when the card was created.

    Scenario: agent spawns one novelty subagent without an explicit subagent_id.
    show_subagent_card_from_spawn creates the card with placeholder id="subagent_0"
    (position index 0).  The MCP server assigns id="subagent_1" (globally
    sequential).  _update_subagent_card_with_results must fall back to positional
    matching so subagent_type="novelty" is not lost.
    """
    panel_cls = textual_display_module.AgentPanel
    panel = panel_cls.__new__(panel_cls)

    # Card created with placeholder id="subagent_0", subagent_type="novelty"
    placeholder = _make_subagent("subagent_0", status="running", subagent_type="novelty")
    card = _FakeCard([placeholder], tool_call_id="spawn_tool_99")
    timeline = _FakeTimeline(card)

    # Spawn result assigns id="subagent_1" (different from placeholder "subagent_0")
    result_payload = {
        "success": True,
        "operation": "spawn_subagents",
        "mode": "background",
        "subagents": [
            {
                "subagent_id": "subagent_1",
                "status": "running",
                "workspace": "/tmp/ws",
                "task": "You are a novelty subagent...",
            },
        ],
    }

    tool_data = SimpleNamespace(
        tool_id="spawn_tool_99",
        tool_name="mcp__subagent_agent_a__spawn_subagents",
        result_full=json.dumps(result_payload),
    )

    panel._update_subagent_card_with_results(tool_data, timeline)

    assert card.last_update is not None
    updated = card.last_update[0]
    assert updated.id == "subagent_1"
    assert updated.subagent_type == "novelty", (
        "subagent_type should be preserved via positional fallback " f"when server assigns id='subagent_1' but card placeholder was 'subagent_0'; " f"got subagent_type={updated.subagent_type!r}"
    )


def test_subagent_card_variant_a_uses_single_thin_left_rail() -> None:
    """Option A should avoid stacked thick rails on the left edge."""
    css = Path("massgen/frontend/displays/textual_themes/base.tcss").read_text(encoding="utf-8")

    variant_match = re.search(r"SubagentCard\.variant-a\s*\{([^}]*)\}", css, re.DOTALL)
    assert variant_match is not None
    variant_block = variant_match.group(1)
    assert "border-left: solid" in variant_block
    assert "border-left: tall" not in variant_block

    focus_match = re.search(r"SubagentCard\.variant-a:focus-within\s*\{([^}]*)\}", css, re.DOTALL)
    assert focus_match is not None
    focus_block = focus_match.group(1)
    assert "border-left: solid" in focus_block
