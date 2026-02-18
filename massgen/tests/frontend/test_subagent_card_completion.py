# -*- coding: utf-8 -*-
"""Regression tests for subagent card completion wiring in Textual TUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from textual.app import App, ComposeResult

from massgen.frontend.displays import textual_terminal_display as textual_display_module
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
    app._build_spawn_status_callback = lambda agent_id, seed_subagents: None

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
