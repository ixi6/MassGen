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
    app._subagent_message_callback = None

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
    app._subagent_message_callback = None

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
    app._subagent_message_callback = None

    running = _make_subagent("sub_1", status="running")
    card = SimpleNamespace(subagents=[running])

    class _FakePanel:
        def query(self, _selector):
            return [card]

    app.agent_widgets = {"agent_a": _FakePanel()}
    app._precollab_subagents = {}
    app._open_precollab_screen = lambda sid: False
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


def test_subagent_status_line_renders_terminal_reason() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentStatusLine,
    )

    line = SubagentStatusLine(status="running")
    line.update_status("failed", 12, reason="Subagent cancelled")

    rendered = line.render().plain
    assert "Failed" in rendered
    assert "Subagent cancelled" in rendered


def test_subagent_status_line_renders_canceled_reason() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentStatusLine,
    )

    line = SubagentStatusLine(status="running")
    line.update_status("cancelled", 7, reason="Cancelled by user")

    rendered = line.render().plain
    assert "Canceled" in rendered
    assert "Cancelled by user" in rendered


def test_subagent_status_line_sets_canceled_style_class() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentStatusLine,
    )

    line = SubagentStatusLine(status="running")
    line.update_status("cancelled", 7, reason="Cancelled by user")

    assert line.has_class("canceled")
    assert not line.has_class("running")
    assert not line.has_class("completed")
    assert not line.has_class("error")


def test_subagent_status_line_avoids_redundant_cancel_reason() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentStatusLine,
    )

    line = SubagentStatusLine(status="running")
    line.update_status("cancelled", 7, reason="Subagent cancelled")

    rendered = line.render().plain
    assert "Canceled" in rendered
    assert "Canceled: Subagent cancelled" not in rendered
    assert "Subagent cancelled" not in rendered


def test_subagent_view_sets_cancelled_state_class() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentView,
    )

    subagent = _make_subagent("sub_1", status="cancelled")

    view = SubagentView.__new__(SubagentView)
    view.__init__(subagent=subagent)

    assert not view.has_class("cancelled-state")
    view._update_status_display()
    assert view.has_class("cancelled-state")

    subagent.status = "running"
    view._update_status_display()
    assert not view.has_class("cancelled-state")


def test_subagent_view_adds_terminal_status_note_when_events_absent() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentView,
    )

    class _TimelineStub:
        def __init__(self) -> None:
            self.entries: list[tuple[str, str, str, int]] = []

        def add_text(
            self,
            content: str,
            *,
            style: str = "",
            text_class: str = "",
            round_number: int = 1,
        ) -> None:
            self.entries.append((content, style, text_class, round_number))

    class _PanelStub:
        def __init__(self, timeline: _TimelineStub) -> None:
            self._timeline = timeline

        def query_one(self, selector: str, _cls):  # noqa: ANN001 - Textual query compat
            if selector == "#subagent-timeline-inner_a":
                return self._timeline
            raise LookupError(selector)

    subagent = _make_subagent("sub_1", status="cancelled")
    subagent.error = "Cancelled by user"

    view = SubagentView.__new__(SubagentView)
    view.__init__(subagent=subagent)
    view._round_number = 1
    timeline = _TimelineStub()
    view._panel = _PanelStub(timeline)

    view._ensure_terminal_status_note("inner_a", event_count=0)
    view._ensure_terminal_status_note("inner_a", event_count=0)

    assert len(timeline.entries) == 1
    message, style, text_class, round_number = timeline.entries[0]
    assert "Subagent canceled: Cancelled by user" in message
    assert style
    assert text_class == "status"
    assert round_number == 1


def test_subagent_view_avoids_redundant_cancel_reason_in_terminal_note() -> None:
    from massgen.frontend.displays.textual_widgets.subagent_screen import (
        SubagentView,
    )

    class _TimelineStub:
        def __init__(self) -> None:
            self.entries: list[tuple[str, str, str, int]] = []

        def add_text(
            self,
            content: str,
            *,
            style: str = "",
            text_class: str = "",
            round_number: int = 1,
        ) -> None:
            self.entries.append((content, style, text_class, round_number))

    class _PanelStub:
        def __init__(self, timeline: _TimelineStub) -> None:
            self._timeline = timeline

        def query_one(self, selector: str, _cls):  # noqa: ANN001 - Textual query compat
            if selector == "#subagent-timeline-inner_a":
                return self._timeline
            raise LookupError(selector)

    subagent = _make_subagent("sub_1", status="cancelled")
    subagent.error = "Subagent cancelled"

    view = SubagentView.__new__(SubagentView)
    view.__init__(subagent=subagent)
    view._round_number = 1
    timeline = _TimelineStub()
    view._panel = _PanelStub(timeline)

    view._ensure_terminal_status_note("inner_a", event_count=0)

    assert len(timeline.entries) == 1
    message, _style, _text_class, _round_number = timeline.entries[0]
    assert message == "Subagent canceled."
