# -*- coding: utf-8 -*-
"""Regression tests for subagent screen live-status wiring in Textual TUI."""

from types import SimpleNamespace

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.subagent.models import SubagentDisplayData


def _make_subagent(
    subagent_id: str,
    *,
    status: str = "running",
    log_path: str | None = None,
) -> SubagentDisplayData:
    return SubagentDisplayData(
        id=subagent_id,
        task="check output",
        status=status,
        progress_percent=0,
        elapsed_seconds=0.0,
        timeout_seconds=300.0,
        workspace_path="",
        workspace_file_count=0,
        last_log_line="",
        error=None,
        answer_preview=None,
        log_path=log_path,
    )


def test_on_subagent_card_open_modal_passes_status_callback(monkeypatch):
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.coordination_display = SimpleNamespace(agent_ids=[])
    app.agent_widgets = {}
    app.notify = lambda *args, **kwargs: None

    captured: dict = {}

    class _FakeSubagentScreen:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(textual_display_module, "SubagentScreen", _FakeSubagentScreen)
    app.push_screen = lambda screen, dismiss_callback=None: captured.setdefault("screen", screen)

    initial = _make_subagent("sub_1", status="running")
    card = SimpleNamespace(subagents=[initial])
    stopped = {"called": False}
    event = SimpleNamespace(
        card=card,
        subagent=initial,
        all_subagents=[initial],
        stop=lambda: stopped.__setitem__("called", True),
    )

    app.on_subagent_card_open_modal(event)

    callback = captured["kwargs"].get("status_callback")
    assert callback is not None
    assert callback("sub_1") is initial

    updated = _make_subagent("sub_1", status="completed", log_path="/tmp/events.jsonl")
    card.subagents = [updated]
    assert callback("sub_1") is updated
    assert stopped["called"] is True


def test_on_subagent_card_open_modal_without_card_attr_uses_fallback_snapshot(monkeypatch):
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.coordination_display = SimpleNamespace(agent_ids=[])
    app.agent_widgets = {}
    app.notify = lambda *args, **kwargs: None

    captured: dict = {}

    class _FakeSubagentScreen:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(textual_display_module, "SubagentScreen", _FakeSubagentScreen)
    app.push_screen = lambda screen, dismiss_callback=None: captured.setdefault("screen", screen)

    initial = _make_subagent("sub_1", status="running")
    stopped = {"called": False}
    event = SimpleNamespace(
        subagent=initial,
        all_subagents=[initial],
        stop=lambda: stopped.__setitem__("called", True),
    )

    app.on_subagent_card_open_modal(event)

    callback = captured["kwargs"].get("status_callback")
    assert callback is not None
    assert callback("sub_1") is initial
    assert stopped["called"] is True


def test_action_show_subagents_passes_status_callback(monkeypatch):
    app_cls = textual_display_module.TextualApp
    app = app_cls.__new__(app_cls)
    app.coordination_display = SimpleNamespace(agent_ids=["agent_a"])

    running = _make_subagent("sub_1", status="running")
    card = SimpleNamespace(subagents=[running])

    class _FakePanel:
        def query(self, _selector):
            return [card]

    app.agent_widgets = {"agent_a": _FakePanel()}
    app._open_decomposition_runtime_subagent_screen = lambda: False
    app._open_persona_runtime_subagent_screen = lambda: False
    app.notify = lambda *args, **kwargs: None

    captured: dict = {}

    class _FakeSubagentScreen:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(textual_display_module, "SubagentScreen", _FakeSubagentScreen)
    app.push_screen = lambda screen: captured.setdefault("screen", screen)

    app.action_show_subagents()

    callback = captured["kwargs"].get("status_callback")
    assert callback is not None
    assert callback("sub_1") is running
