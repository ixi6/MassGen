"""TDD tests for subagent message input bar on SubagentScreen."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from massgen.events import MassGenEvent
from massgen.subagent.models import SubagentDisplayData

pytestmark = pytest.mark.snapshot


def _make_subagent(
    subagent_id: str = "sub_1",
    *,
    status: str = "running",
) -> SubagentDisplayData:
    return SubagentDisplayData(
        id=subagent_id,
        task="test task",
        status=status,
        progress_percent=0,
        elapsed_seconds=0.0,
        timeout_seconds=300.0,
        workspace_path="",
        workspace_file_count=0,
        last_log_line="",
        error=None,
        answer_preview=None,
        log_path=None,
    )


# =============================================================================
# SubagentView callback wiring
# =============================================================================


class TestSubagentViewMessageCallback:
    """Tests for send_message_callback wiring on SubagentView."""

    def test_subagent_view_accepts_send_message_callback(self):
        """SubagentView stores the callback when passed."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        callback = MagicMock(return_value=True)
        view = SubagentView.__new__(SubagentView)
        subagent = _make_subagent()
        view.__init__(subagent=subagent, send_message_callback=callback)
        assert view._send_message_callback is callback

    def test_subagent_view_no_callback_by_default(self):
        """SubagentView has no callback when not passed."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        view = SubagentView.__new__(SubagentView)
        subagent = _make_subagent()
        view.__init__(subagent=subagent)
        assert view._send_message_callback is None

    def test_subagent_screen_passes_callback_to_view(self, monkeypatch):
        """SubagentScreen forwards send_message_callback to SubagentView."""
        from massgen.frontend.displays.textual_widgets import subagent_screen as mod

        captured = {}

        class _FakeView:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(mod, "SubagentView", _FakeView)

        callback = MagicMock(return_value=True)
        screen = mod.SubagentScreen.__new__(mod.SubagentScreen)
        screen._subagent = _make_subagent()
        screen._all_subagents = [screen._subagent]
        screen._status_callback = None
        screen._auto_return_on_completion = False
        screen._send_message_callback = callback
        screen._continue_subagent_callback = None
        screen._subagent_index = None

        list(screen.compose())

        assert captured.get("send_message_callback") is callback

    def test_subagent_screen_no_callback_passes_none(self, monkeypatch):
        """SubagentScreen passes None when no callback set."""
        from massgen.frontend.displays.textual_widgets import subagent_screen as mod

        captured = {}

        class _FakeView:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(mod, "SubagentView", _FakeView)

        screen = mod.SubagentScreen.__new__(mod.SubagentScreen)
        screen._subagent = _make_subagent()
        screen._all_subagents = [screen._subagent]
        screen._status_callback = None
        screen._auto_return_on_completion = False
        screen._send_message_callback = None
        screen._continue_subagent_callback = None
        screen._subagent_index = None

        list(screen.compose())

        assert captured.get("send_message_callback") is None

    def test_subagent_view_accepts_continue_subagent_callback(self):
        """SubagentView stores the continue callback when passed."""
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        callback = MagicMock(return_value=True)
        view = SubagentView.__new__(SubagentView)
        subagent = _make_subagent(status="completed")
        view.__init__(subagent=subagent, continue_subagent_callback=callback)
        assert view._continue_subagent_callback is callback

    def test_subagent_screen_passes_continue_callback_to_view(self, monkeypatch):
        """SubagentScreen forwards continue_subagent_callback to SubagentView."""
        from massgen.frontend.displays.textual_widgets import subagent_screen as mod

        captured = {}

        class _FakeView:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(mod, "SubagentView", _FakeView)

        callback = MagicMock(return_value=True)
        screen = mod.SubagentScreen.__new__(mod.SubagentScreen)
        screen._subagent = _make_subagent(status="completed")
        screen._all_subagents = [screen._subagent]
        screen._status_callback = None
        screen._auto_return_on_completion = False
        screen._send_message_callback = None
        screen._continue_subagent_callback = callback
        screen._subagent_index = None

        list(screen.compose())

        assert captured.get("continue_subagent_callback") is callback


# =============================================================================
# Display callback wiring
# =============================================================================


class TestDisplayCallbackWiring:
    """Tests for callback wiring through TextualTerminalDisplay and TextualApp."""

    def test_textual_app_stores_subagent_message_callback(self, monkeypatch):
        """TextualApp.set_subagent_message_callback stores the callback."""
        from massgen.frontend.displays import textual_terminal_display as mod

        app_cls = mod.TextualApp
        app = app_cls.__new__(app_cls)
        callback = MagicMock(return_value=True)
        app.set_subagent_message_callback(callback)
        assert app._subagent_message_callback is callback

    def test_textual_terminal_display_forwards_callback(self, monkeypatch):
        """TextualTerminalDisplay.set_subagent_message_callback forwards to app."""
        from massgen.frontend.displays import textual_terminal_display as mod

        display = mod.TextualTerminalDisplay.__new__(mod.TextualTerminalDisplay)
        mock_app = MagicMock()
        mock_app.set_subagent_message_callback = MagicMock()
        display._app = mock_app

        callback = MagicMock(return_value=True)
        display.set_subagent_message_callback(callback)
        mock_app.set_subagent_message_callback.assert_called_once_with(callback)

    def test_subagent_screen_instantiation_passes_callback(self, monkeypatch):
        """SubagentScreen call sites pass send_message_callback from app."""
        from massgen.frontend.displays import textual_terminal_display as mod

        app_cls = mod.TextualApp
        app = app_cls.__new__(app_cls)
        app.coordination_display = SimpleNamespace(agent_ids=[])
        app.agent_widgets = {}
        app.notify = lambda *args, **kwargs: None
        app._subagent_message_callback = MagicMock(return_value=True)
        app._subagent_continue_callback = MagicMock(return_value=True)

        captured = {}

        class _FakeSubagentScreen:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(mod, "SubagentScreen", _FakeSubagentScreen)
        app.push_screen = lambda screen, dismiss_callback=None: None

        subagent = _make_subagent()
        card = SimpleNamespace(subagents=[subagent])
        event = SimpleNamespace(
            card=card,
            subagent=subagent,
            all_subagents=[subagent],
            stop=lambda: None,
        )

        app.on_subagent_card_open_modal(event)

        assert captured.get("send_message_callback") is app._subagent_message_callback
        assert captured.get("continue_subagent_callback") is app._subagent_continue_callback

    def test_textual_app_stores_subagent_continue_callback(self):
        """TextualApp.set_subagent_continue_callback stores the callback."""
        from massgen.frontend.displays import textual_terminal_display as mod

        app_cls = mod.TextualApp
        app = app_cls.__new__(app_cls)
        callback = MagicMock(return_value=True)
        app.set_subagent_continue_callback(callback)
        assert app._subagent_continue_callback is callback

    def test_textual_terminal_display_forwards_continue_callback(self):
        """TextualTerminalDisplay.set_subagent_continue_callback forwards to app."""
        from massgen.frontend.displays import textual_terminal_display as mod

        display = mod.TextualTerminalDisplay.__new__(mod.TextualTerminalDisplay)
        mock_app = MagicMock()
        mock_app.set_subagent_continue_callback = MagicMock()
        display._app = mock_app

        callback = MagicMock(return_value=True)
        display.set_subagent_continue_callback(callback)
        mock_app.set_subagent_continue_callback.assert_called_once_with(callback)


# =============================================================================
# MessageInputBar widget
# =============================================================================


class TestMessageInputBar:
    """Tests for the reusable MessageInputBar widget."""

    def test_message_input_bar_initializes(self):
        """MessageInputBar can be constructed with placeholder and targets."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar(placeholder="test placeholder", targets=["agent_a", "agent_b"])
        assert bar._placeholder == "test placeholder"
        assert bar._targets == ["agent_a", "agent_b"]
        assert bar._current_target == "all"

    def test_message_input_bar_default_target_is_all(self):
        """Default inject target is 'all'."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar()
        assert bar._current_target == "all"

    def test_set_targets_updates_list(self):
        """set_targets() updates the target list and resets to 'all'."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar()
        bar._current_target = "agent_a"
        bar.set_targets(["agent_x", "agent_y"])
        assert bar._targets == ["agent_x", "agent_y"]
        assert bar._current_target == "all"

    def test_cycle_target(self):
        """_cycle_target cycles: all -> targets[0] -> targets[1] -> all."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar(targets=["agent_a", "agent_b"])
        assert bar._current_target == "all"
        bar._cycle_target()
        assert bar._current_target == "agent_a"
        bar._cycle_target()
        assert bar._current_target == "agent_b"
        bar._cycle_target()
        assert bar._current_target == "all"

    def test_cycle_target_no_targets(self):
        """_cycle_target does nothing when no targets."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar()
        bar._cycle_target()
        assert bar._current_target == "all"

    def test_target_label_matches_main_input_wording(self):
        """Target label should mirror the main app's Inject wording."""
        from massgen.frontend.displays.textual_widgets.message_input_bar import (
            MessageInputBar,
        )

        bar = MessageInputBar(targets=["agent_a"])
        assert bar._format_target_label() == "Inject: all"

        bar._cycle_target()
        assert bar._format_target_label() == "Inject: agent_a"


class TestSubagentRuntimeQueueBanner:
    """Tests for subagent queued-runtime banner behavior."""

    def _init_view(self):
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        view = SubagentView.__new__(SubagentView)
        callback_calls: list[tuple[str, str, list[str] | None]] = []

        def _callback(subagent_id: str, content: str, target_agents=None):  # noqa: ANN001 - callback shape
            callback_calls.append((subagent_id, content, target_agents))
            return True

        subagent = _make_subagent("runtime_subagent")
        view.__init__(subagent=subagent, send_message_callback=_callback)
        view._inner_agents = ["agent_a", "agent_b"]
        view._queued_runtime_messages = []
        view._queued_runtime_pending_by_agent = {}
        view._next_runtime_message_id = 1
        return view, callback_calls

    def test_subagent_submit_queues_banner_entry_for_all_targets(self):
        view, callback_calls = self._init_view()

        class _BannerStub:
            def __init__(self):
                self.messages = []
                self.pending_counts = {}

            def set_messages(self, messages):
                self.messages = messages

            def set_pending_counts(self, counts):
                self.pending_counts = counts

        banner = _BannerStub()
        view._queued_runtime_banner = banner
        visibility: list[bool] = []
        notifications: list[str] = []
        view._set_runtime_queue_region_visible = lambda visible: visibility.append(visible)
        view.notify = lambda message, **kwargs: notifications.append(str(message))

        event = SimpleNamespace(
            value="Please prioritize the accessibility section.",
            target="all",
            stop=lambda: None,
        )

        view.on_message_input_bar_submitted(event)

        assert callback_calls == [
            (
                "runtime_subagent",
                "Please prioritize the accessibility section.",
                None,
            ),
        ]
        assert len(view._queued_runtime_messages) == 1
        assert view._queued_runtime_messages[0]["target_label"] == "all agents"
        assert view._queued_runtime_messages[0]["pending_agents"] == ["agent_a", "agent_b"]
        assert view._queued_runtime_messages[0]["source_label"] == "parent"
        assert banner.pending_counts == {"agent_a": 1, "agent_b": 1}
        assert visibility and visibility[-1] is True
        assert any("Message sent to all agents" in msg for msg in notifications)

    def test_subagent_runtime_delivery_event_reduces_pending_queue(self):
        view, _ = self._init_view()

        class _BannerStub:
            def __init__(self):
                self.messages = []
                self.pending_counts = {}

            def set_messages(self, messages):
                self.messages = messages

            def set_pending_counts(self, counts):
                self.pending_counts = counts

        banner = _BannerStub()
        visibility: list[bool] = []
        view._queued_runtime_banner = banner
        view._set_runtime_queue_region_visible = lambda visible: visibility.append(visible)

        # Seed a queued "all agents" runtime message.
        view._queue_runtime_message(
            "Please focus on test coverage gaps.",
            target="all",
        )
        assert banner.pending_counts == {"agent_a": 1, "agent_b": 1}

        # Simulate subagent hook-delivery to agent_a.
        delivery_event = MassGenEvent.create(
            "hook_execution",
            agent_id="agent_a",
            hook_info={
                "hook_name": "human_input_hook",
                "injection_content": "\n[Human Input]: Please focus on test coverage gaps.\n",
            },
        )

        view._update_runtime_queue_from_events([delivery_event])

        assert len(view._queued_runtime_messages) == 1
        assert view._queued_runtime_messages[0]["pending_agents"] == ["agent_b"]
        assert banner.pending_counts == {"agent_a": 0, "agent_b": 1}
        assert visibility and visibility[-1] is True

    def test_subagent_runtime_delivery_event_only_clears_matching_message(self):
        view, _ = self._init_view()

        class _BannerStub:
            def __init__(self):
                self.messages = []
                self.pending_counts = {}

            def set_messages(self, messages):
                self.messages = messages

            def set_pending_counts(self, counts):
                self.pending_counts = counts

        banner = _BannerStub()
        view._queued_runtime_banner = banner
        view._set_runtime_queue_region_visible = lambda _visible: None

        view._queue_runtime_message("First queued request", target="all")
        view._queue_runtime_message("Second queued request", target="all")
        assert len(view._queued_runtime_messages) == 2

        delivery_event = MassGenEvent.create(
            "hook_execution",
            agent_id="agent_a",
            hook_info={
                "hook_name": "human_input_hook",
                "injection_content": "\n[Human Input]: First queued request\n",
            },
        )
        view._update_runtime_queue_from_events([delivery_event])

        assert len(view._queued_runtime_messages) == 2
        first, second = view._queued_runtime_messages
        assert first["pending_agents"] == ["agent_b"]
        assert second["pending_agents"] == ["agent_a", "agent_b"]
        assert banner.pending_counts == {"agent_a": 1, "agent_b": 2}

    def test_subagent_runtime_injection_received_event_reduces_pending_queue(self):
        view, _ = self._init_view()

        class _BannerStub:
            def __init__(self):
                self.messages = []
                self.pending_counts = {}

            def set_messages(self, messages):
                self.messages = messages

            def set_pending_counts(self, counts):
                self.pending_counts = counts

        banner = _BannerStub()
        visibility: list[bool] = []
        view._queued_runtime_banner = banner
        view._set_runtime_queue_region_visible = lambda visible: visibility.append(visible)

        view._queue_runtime_message(
            "Please include the British Invasion links.",
            target="all",
        )
        assert banner.pending_counts == {"agent_a": 1, "agent_b": 1}

        delivery_event = MassGenEvent.create(
            "injection_received",
            agent_id="agent_a",
            source_agents=["parent"],
            injection_type="runtime_inbox_input",
        )
        view._update_runtime_queue_from_events([delivery_event])

        assert len(view._queued_runtime_messages) == 1
        assert view._queued_runtime_messages[0]["pending_agents"] == ["agent_b"]
        assert banner.pending_counts == {"agent_a": 0, "agent_b": 1}
        assert visibility and visibility[-1] is True

    def test_subagent_submit_adds_timeline_queue_note_for_parent_source(self):
        view, callback_calls = self._init_view()

        class _TimelineStub:
            def __init__(self) -> None:
                self.entries: list[dict[str, object]] = []

            def add_text(self, content, style="", text_class="", round_number=1):
                self.entries.append(
                    {
                        "content": content,
                        "style": style,
                        "text_class": text_class,
                        "round_number": round_number,
                    },
                )

        class _PanelStub:
            def __init__(self, timeline):
                self._timeline = timeline

            def query_one(self, selector, _cls=None):
                if selector == "#subagent-timeline-agent_a":
                    return self._timeline
                raise LookupError(selector)

        timeline = _TimelineStub()
        view._panel = _PanelStub(timeline)
        view._current_inner_agent = "agent_a"
        view._round_number = 1
        view._set_runtime_queue_region_visible = lambda _visible: None
        notifications: list[str] = []
        view.notify = lambda message, **kwargs: notifications.append(str(message))

        event = SimpleNamespace(
            value="How's progress?",
            target="all",
            stop=lambda: None,
        )

        view.on_message_input_bar_submitted(event)

        assert callback_calls == [("runtime_subagent", "How's progress?", None)]
        assert any("Message sent to all agents" in msg for msg in notifications)
        assert any("Runtime Injection -> Queued from parent to all agents: How's progress?" == entry["content"] for entry in timeline.entries)
        assert any(entry["text_class"] == "status runtime-injection" for entry in timeline.entries)

    @pytest.mark.asyncio
    async def test_subagent_input_widget_submit_triggers_send_callback(self):
        from textual.app import App, ComposeResult

        from massgen.frontend.displays.textual_widgets.multi_line_input import (
            MultiLineInput,
        )
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        callback_calls: list[tuple[str, str, list[str] | None]] = []

        def _callback(subagent_id: str, content: str, target_agents=None):  # noqa: ANN001
            callback_calls.append((subagent_id, content, target_agents))
            return True

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield SubagentView(
                    subagent=_make_subagent("runtime_subagent", status="running"),
                    send_message_callback=_callback,
                    id="subagent-view",
                )

        app = _Harness()
        async with app.run_test(headless=True, size=(130, 38)) as pilot:
            await pilot.pause()
            view = app.query_one("#subagent-view", SubagentView)
            input_widget = view.query_one(".shared-question-input", MultiLineInput)
            input_widget.text = "How's progress?"
            input_widget.action_submit()
            await pilot.pause()

            assert callback_calls == [("runtime_subagent", "How's progress?", None)]
            assert len(view._queued_runtime_messages) == 1
            assert view._queued_runtime_messages[0]["source_label"] == "parent"

    def test_subagent_syncs_runtime_inbox_messages_into_queue_and_timeline(self, tmp_path):
        view, _ = self._init_view()
        workspace = tmp_path / "subagent_workspace"
        inbox = workspace / ".massgen" / "runtime_inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        message_payload = {
            "content": "Please include blues influence and Harlem clubs.",
            "source": "parent",
            "target_agents": None,
        }
        (inbox / "msg_1700000000_1.json").write_text(json.dumps(message_payload))

        class _TimelineStub:
            def __init__(self) -> None:
                self.entries: list[dict[str, object]] = []

            def add_text(self, content, style="", text_class="", round_number=1):
                self.entries.append(
                    {
                        "content": content,
                        "style": style,
                        "text_class": text_class,
                        "round_number": round_number,
                    },
                )

        class _PanelStub:
            def __init__(self, timeline):
                self._timeline = timeline

            def query_one(self, selector, _cls=None):
                if selector in {"#subagent-timeline-agent_a", "#subagent-timeline-agent_b"}:
                    return self._timeline
                raise LookupError(selector)

        timeline = _TimelineStub()
        view._panel = _PanelStub(timeline)
        view._round_number = 1
        view._subagent.workspace_path = str(workspace)
        view._runtime_inbox_dir = None
        view._runtime_inbox_seen_files = set()
        view._set_runtime_queue_region_visible = lambda _visible: None

        view._sync_runtime_queue_from_inbox()

        assert len(view._queued_runtime_messages) == 1
        queued = view._queued_runtime_messages[0]
        assert queued["source_label"] == "parent"
        assert queued["target_label"] == "all agents"
        assert queued["pending_agents"] == ["agent_a", "agent_b"]
        assert any("Runtime Injection -> Queued from parent to all agents: Please include blues influence and Harlem clubs." == entry["content"] for entry in timeline.entries)

    def test_poll_updates_syncs_runtime_inbox_without_new_events(self):
        view, _ = self._init_view()
        sync_calls: list[str] = []

        view._status_callback = None
        view._event_reader = SimpleNamespace(get_new_events=lambda: [])
        view._init_event_reader = lambda: None
        view._load_initial_events = lambda: None
        view._current_inner_agent = "agent_a"
        view._ensure_terminal_status_note = lambda *_args, **_kwargs: None
        view._maybe_schedule_auto_return_prompt = lambda: None
        view._sync_runtime_queue_from_inbox = lambda: sync_calls.append("sync")
        view._subagent.status = "running"

        view._poll_updates()

        assert sync_calls == ["sync"]


class TestSubagentContinueAction:
    """Tests for continue-subagent action handling in SubagentView."""

    @pytest.mark.asyncio
    async def test_continue_button_not_rendered_even_when_callback_exists(self):
        from textual.app import App, ComposeResult

        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield SubagentView(
                    subagent=_make_subagent("sub_1", status="completed"),
                    continue_subagent_callback=lambda *_args, **_kwargs: True,
                    id="subagent-view",
                )

        app = _Harness()
        async with app.run_test(headless=True, size=(130, 38)) as pilot:
            await pilot.pause()
            view = app.query_one("#subagent-view", SubagentView)
            assert list(view.query("#continue_subagent_button")) == []

    def test_continue_subagent_with_message_sets_running_state(self):
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        calls: list[tuple[str, str]] = []

        def _callback(subagent_id: str, message: str) -> bool:
            calls.append((subagent_id, message))
            return True

        subagent = _make_subagent("sub_1", status="completed")
        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=subagent, continue_subagent_callback=_callback)
        notifications: list[str] = []
        view.notify = lambda message, **kwargs: notifications.append(str(message))
        view._status_callback = None
        view._poll_timer = None
        view._inner_agents = []
        view._event_adapters = {}
        view._agents_loaded = set()
        view._queued_runtime_messages = []
        view._queued_runtime_pending_by_agent = {}
        view._refresh_runtime_queue_banner = lambda: None
        view._update_status_display = lambda: None
        view._set_runtime_queue_region_visible = lambda _visible: None
        view.set_interval = lambda _interval, _callback: SimpleNamespace(stop=lambda: None)

        class _InputBar:
            def __init__(self) -> None:
                self.display = False

        input_bar = _InputBar()
        view.query_one = lambda selector, _cls=None: input_bar if selector == "#subagent-input-bar" else (_ for _ in ()).throw(LookupError(selector))  # type: ignore[assignment]

        result = view._continue_subagent_with_message("Please continue with deeper analysis.")

        assert result is True
        assert calls == [("sub_1", "Please continue with deeper analysis.")]
        assert view._subagent.status == "running"
        assert input_bar.display is True
        assert any("Continuing subagent" in msg for msg in notifications)

    def test_continue_subagent_with_message_reports_failure(self):
        from massgen.frontend.displays.textual_widgets.subagent_screen import (
            SubagentView,
        )

        def _callback(_subagent_id: str, _message: str) -> bool:
            return False

        subagent = _make_subagent("sub_1", status="completed")
        view = SubagentView.__new__(SubagentView)
        view.__init__(subagent=subagent, continue_subagent_callback=_callback)
        notifications: list[str] = []
        view.notify = lambda message, **kwargs: notifications.append(str(message))

        result = view._continue_subagent_with_message("try again")

        assert result is False
        assert view._subagent.status == "completed"
        assert any("Failed to continue subagent" in msg for msg in notifications)


# =============================================================================
# Pipeline: target_agents in SubagentManager
# =============================================================================


class TestSubagentManagerTargetAgents:
    """Tests for target_agents support in SubagentManager.send_message_to_subagent."""

    def _make_manager(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

    def _register_running_subagent(self, manager, subagent_id, workspace_path):
        from massgen.subagent.models import SubagentConfig, SubagentState

        config = SubagentConfig(id=subagent_id, task="test task", parent_agent_id="test-agent")
        state = SubagentState(
            config=config,
            status="running",
            workspace_path=str(workspace_path),
        )
        manager._subagents[subagent_id] = state

    def test_send_message_includes_target_agents_in_json(self, tmp_path):
        """target_agents is written to the JSON message file."""
        manager = self._make_manager(tmp_path)
        sub_workspace = tmp_path / "workspace" / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)
        self._register_running_subagent(manager, "sub1", sub_workspace)

        success, error = manager.send_message_to_subagent("sub1", "focus", target_agents=["agent_a"])
        assert success is True
        assert error is None

        inbox = sub_workspace / ".massgen" / "runtime_inbox"
        msg_files = list(inbox.glob("msg_*.json"))
        assert len(msg_files) == 1

        data = json.loads(msg_files[0].read_text())
        assert data["content"] == "focus"
        assert data["target_agents"] == ["agent_a"]

    def test_send_message_without_target_agents_writes_none(self, tmp_path):
        """Without target_agents, field is None in JSON."""
        manager = self._make_manager(tmp_path)
        sub_workspace = tmp_path / "workspace" / "subagents" / "sub2" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)
        self._register_running_subagent(manager, "sub2", sub_workspace)

        manager.send_message_to_subagent("sub2", "broadcast")

        inbox = sub_workspace / ".massgen" / "runtime_inbox"
        msg_files = list(inbox.glob("msg_*.json"))
        data = json.loads(msg_files[0].read_text())
        assert data["target_agents"] is None


# =============================================================================
# Pipeline: RuntimeInboxPoller returns dicts with target_agents
# =============================================================================


class TestRuntimeInboxPollerTargetAgents:
    """Tests for target_agents passthrough in RuntimeInboxPoller."""

    def test_poll_returns_dicts_with_target_agents(self, tmp_path):
        """Poll returns list of dicts with content and target_agents."""
        from massgen.mcp_tools.hooks import RuntimeInboxPoller

        inbox = tmp_path / "inbox"
        inbox.mkdir()

        msg = {"content": "hello", "source": "parent", "timestamp": "2025-01-01", "target_agents": ["agent_a"]}
        (inbox / "msg_1740000001_0.json").write_text(json.dumps(msg))

        poller = RuntimeInboxPoller(inbox_dir=inbox, min_poll_interval=0.0)
        results = poller.poll()

        assert len(results) == 1
        assert results[0]["content"] == "hello"
        assert results[0]["target_agents"] == ["agent_a"]
        assert results[0]["source"] == "parent"

    def test_poll_returns_none_target_for_old_messages(self, tmp_path):
        """Messages without target_agents field return None."""
        from massgen.mcp_tools.hooks import RuntimeInboxPoller

        inbox = tmp_path / "inbox"
        inbox.mkdir()

        msg = {"content": "legacy", "source": "parent", "timestamp": "2025-01-01"}
        (inbox / "msg_1740000001_0.json").write_text(json.dumps(msg))

        poller = RuntimeInboxPoller(inbox_dir=inbox, min_poll_interval=0.0)
        results = poller.poll()

        assert len(results) == 1
        assert results[0]["content"] == "legacy"
        assert results[0]["target_agents"] is None


def test_subagent_input_bar_snapshot_matches_main_input(snap_compare, monkeypatch):  # noqa: ANN001 - pytest fixture type
    """Visual regression: subagent input bar should mirror main input bar styling."""
    from textual.app import App, ComposeResult
    from textual.containers import Container, Vertical
    from textual.widgets import Button, Label

    from massgen.frontend.displays.textual_widgets.message_input_bar import (
        MessageInputBar,
    )
    from massgen.frontend.displays.textual_widgets.multi_line_input import (
        MultiLineInput,
    )

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("COLUMNS", "140")
    monkeypatch.setenv("LINES", "40")
    monkeypatch.setenv("FORCE_COLOR", "1")

    class _InputParityApp(App):
        CSS = """
        #snapshot-root {
            width: 100%;
            height: auto;
            padding: 1 2;
            background: $background;
            layout: vertical;
        }

        .snapshot-block {
            width: 100%;
            height: auto;
            margin-bottom: 1;
        }

        .snapshot-title {
            width: 100%;
            color: $text-muted;
            margin-bottom: 1;
        }

        #subagent-input-bar {
            dock: none;
            width: 100%;
            padding: 0;
            background: transparent;
        }

        #question_input_row,
        .shared-question-input-row {
            layout: horizontal;
            width: 100%;
            height: auto;
            align: left middle;
            margin: 0 1;
            padding: 0 1;
            border: round $surface-lighten-2;
            background: transparent;
        }

        #question_input,
        .shared-question-input {
            background: transparent;
            border: none;
            width: 1fr;
            height: auto;
            min-height: 1;
            max-height: 10;
            margin: 0;
            margin-top: 0;
            padding: 0 1 0 0;
        }

        #question_input.vim-normal,
        .shared-question-input.vim-normal {
            border: solid $warning;
        }

        #inject_target_button,
        .shared-inject-target-button {
            height: 1;
            min-height: 1;
            width: auto;
            min-width: 10;
            margin-left: 1;
            margin-right: 0;
            padding: 0 1;
            border: none;
            background: transparent;
            color: $text-muted;
            align: right middle;
        }

        #inject_target_button.mode-current,
        .shared-inject-target-button.mode-current {
            background: $primary 18%;
            color: $text;
        }
        """

        def compose(self) -> ComposeResult:
            with Vertical(id="snapshot-root"):
                with Vertical(classes="snapshot-block"):
                    yield Label("Main Agent Input", classes="snapshot-title")
                    with Container(id="question_input_row"):
                        yield MultiLineInput(
                            placeholder="Enter to submit • Shift+Enter for newline",
                            id="question_input",
                            vim_mode=True,
                        )
                        yield Button("Inject: all", id="inject_target_button")

                with Vertical(classes="snapshot-block"):
                    yield Label("Subagent Input", classes="snapshot-title")
                    yield MessageInputBar(
                        placeholder="Send message to subagent... (Enter to send)",
                        vim_mode=True,
                        id="subagent-input-bar",
                    )

        def on_mount(self) -> None:
            subagent_bar = self.query_one("#subagent-input-bar", MessageInputBar)
            subagent_bar.set_targets(["agent_a", "agent_b"])

            main_input = self.query_one("#question_input", MultiLineInput)
            main_input.add_class("vim-normal")
            sub_input = self.query_one(".shared-question-input", MultiLineInput)
            sub_input.add_class("vim-normal")

    async def _settle(pilot) -> None:  # noqa: ANN001 - fixture-provided type
        await pilot.pause()

    assert snap_compare(
        _InputParityApp(),
        terminal_size=(130, 26),
        run_before=_settle,
    )
