"""Unit tests for runtime human-input targeting and TUI injection visibility."""

from types import SimpleNamespace

from massgen.frontend.displays import textual_terminal_display as textual_display_module


class _HookStub:
    def __init__(self) -> None:
        self.pending_calls: list[tuple[str, list[str] | None, str]] = []
        self.counts: dict[str, int] = {}
        self.pending_messages: list[dict] = []
        self._next_id = 1
        self.pop_calls = 0
        self.clear_calls = 0

    def _recompute_counts(self) -> None:
        counts: dict[str, int] = {}
        for message in self.pending_messages:
            pending_agents = message.get("pending_agents") or []
            for aid in pending_agents:
                counts[aid] = counts.get(aid, 0) + 1
        self.counts = counts

    def set_pending_input(self, content: str, target_agents=None, source: str = "human") -> int:
        targets = list(target_agents) if target_agents is not None else None
        self.pending_calls.append((content, targets, source))
        message_id = self._next_id
        self._next_id += 1
        pending_agents = list(targets or [])
        self.pending_messages.append(
            {
                "id": message_id,
                "content": content,
                "pending_agents": pending_agents,
                "target_label": "all agents" if not targets else ", ".join(targets),
                "source": source,
                "source_label": source,
            },
        )
        self._recompute_counts()
        return message_id

    def get_pending_counts_for_agents(self, agent_ids: list[str]) -> dict[str, int]:
        return {aid: self.counts.get(aid, 0) for aid in agent_ids}

    def get_pending_messages(self, agent_ids=None) -> list[dict]:
        if agent_ids is None:
            return [dict(msg) for msg in self.pending_messages]
        allowed = set(agent_ids)
        normalized = []
        for msg in self.pending_messages:
            pending_agents = [aid for aid in msg.get("pending_agents", []) if aid in allowed]
            if pending_agents:
                cloned = dict(msg)
                cloned["pending_agents"] = pending_agents
                normalized.append(cloned)
        return normalized

    def pop_latest_pending_input(self):
        self.pop_calls += 1
        if not self.pending_messages:
            return None
        removed = self.pending_messages.pop()
        self._recompute_counts()
        return removed

    def clear_pending_input(self) -> None:
        self.clear_calls += 1
        self.pending_messages.clear()
        self._recompute_counts()


class _TabBarStub:
    def __init__(self) -> None:
        self.last_counts: dict[str, int] = {}

    def set_pending_injection_counts(self, counts: dict[str, int]) -> None:
        self.last_counts = dict(counts)


class _BannerStub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.replaced_messages: list[dict] = []
        self.last_counts: dict[str, int] = {}
        self.cleared = 0

    def add_message(self, text: str, target_label: str = "", source_label: str = "") -> None:
        self.messages.append((text, target_label, source_label))

    def set_messages(self, messages: list[dict]) -> None:
        self.replaced_messages = [dict(msg) for msg in messages]

    def set_pending_counts(self, counts: dict[str, int]) -> None:
        self.last_counts = dict(counts)

    def clear(self) -> None:
        self.cleared += 1


class _TimelineStub:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, int]] = []

    def add_text(self, content: str, style: str = "", text_class: str = "", round_number: int = 1) -> None:
        self.added.append((content, text_class, round_number))


class _PanelStub:
    _timeline_section_id = "timeline"

    def __init__(self, timeline: _TimelineStub, round_number: int = 1) -> None:
        self._timeline = timeline
        self._current_round = round_number

    def query_one(self, selector: str, _type=None):
        if selector == "#timeline":
            return self._timeline
        raise LookupError(selector)


class _InjectButtonStub:
    def __init__(self) -> None:
        self.label = ""
        self.classes: set[str] = set()

    def remove_class(self, *names: str) -> None:
        for name in names:
            self.classes.discard(name)

    def add_class(self, name: str) -> None:
        self.classes.add(name)


class _ButtonPressedEvent:
    def __init__(self, button_id: str) -> None:
        self.button = SimpleNamespace(id=button_id)
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _InputAreaStub:
    def __init__(self) -> None:
        self.mounted = []

    def mount(self, widget, before=None) -> None:
        self.mounted.append((widget, before))


class _RegionStub:
    def __init__(self) -> None:
        self.classes: set[str] = set()

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)


class _InputAreaClassStub:
    def __init__(self) -> None:
        self.classes: set[str] = set()

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)


def test_resolve_human_input_targets_current_mode_uses_active_agent():
    app = SimpleNamespace(
        _human_input_target_mode="current",
        _active_agent_id="agent_b",
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
    )

    targets = textual_display_module.TextualApp._resolve_human_input_targets(app)
    assert targets == ["agent_b"]


def test_resolve_human_input_targets_all_mode_returns_all_agents():
    app = SimpleNamespace(
        _human_input_target_mode="all",
        _active_agent_id="agent_b",
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
    )

    targets = textual_display_module.TextualApp._resolve_human_input_targets(app)
    assert targets == ["agent_a", "agent_b"]


def test_queue_human_input_uses_targeted_agents_and_updates_per_agent_counts():
    hook = _HookStub()
    tab_bar = _TabBarStub()
    banner = _BannerStub()
    notifications: list[str] = []

    app = SimpleNamespace(
        _queued_human_input=None,
        _human_input_hook=hook,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        _tab_bar=tab_bar,
        _human_input_target_mode="current",
        _active_agent_id="agent_b",
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
        notify=lambda message, **_kwargs: notifications.append(message),
    )
    app._resolve_human_input_targets = lambda: textual_display_module.TextualApp._resolve_human_input_targets(app)
    app._describe_human_input_targets = lambda targets: textual_display_module.TextualApp._describe_human_input_targets(app, targets)
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp._queue_human_input(app, "Need stronger citations.")

    assert hook.pending_calls == [("Need stronger citations.", ["agent_b"], "human")]
    assert tab_bar.last_counts == {"agent_a": 0, "agent_b": 1}
    assert banner.last_counts == {"agent_a": 0, "agent_b": 1}
    assert banner.replaced_messages
    assert banner.replaced_messages[0]["content"] == "Need stronger citations."
    assert banner.replaced_messages[0]["pending_agents"] == ["agent_b"]
    assert banner.replaced_messages[0]["source"] == "human"
    assert any("agent_b" in msg for msg in notifications)


def test_on_human_input_injected_adds_timeline_entry_and_keeps_queue_when_others_pending():
    hook = _HookStub()
    hook.counts = {"agent_a": 0, "agent_b": 1}
    tab_bar = _TabBarStub()
    banner = _BannerStub()
    timeline = _TimelineStub()
    clear_calls: list[bool] = []

    app = SimpleNamespace(
        _human_input_hook=hook,
        _tab_bar=tab_bar,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
        agent_widgets={"agent_a": _PanelStub(timeline, round_number=2)},
        _clear_queued_input=lambda: clear_calls.append(True),
        notify=lambda *_args, **_kwargs: None,
    )
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._add_runtime_injection_timeline_entry = lambda agent_id, content, message_id=None, source_label=None: textual_display_module.TextualApp._add_runtime_injection_timeline_entry(
        app,
        agent_id,
        content,
        message_id=message_id,
        source_label=source_label,
    )
    app._set_queued_input_region_visible = lambda _visible: None
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp._on_human_input_injected(
        app,
        "Use edge-case tests too.",
        "agent_a",
        [{"id": 7, "content": "Use edge-case tests too."}],
    )

    assert clear_calls == []
    assert tab_bar.last_counts == {"agent_a": 0, "agent_b": 1}
    assert timeline.added
    first_entry, first_class, first_round = timeline.added[0]
    assert "#7" in first_entry
    assert "Runtime Injection" in first_entry
    assert "Use edge-case tests too." in first_entry
    assert "runtime-injection" in first_class
    assert first_round == 2


def test_on_human_input_injected_clears_queue_when_fully_delivered():
    hook = _HookStub()
    hook.counts = {"agent_a": 0, "agent_b": 0}
    clear_calls: list[bool] = []

    app = SimpleNamespace(
        _human_input_hook=hook,
        _tab_bar=_TabBarStub(),
        _queued_input_banner=_BannerStub(),
        _queued_input_region=_RegionStub(),
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
        agent_widgets={},
        _clear_queued_input=lambda: clear_calls.append(True),
        notify=lambda *_args, **_kwargs: None,
    )
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._add_runtime_injection_timeline_entry = lambda agent_id, content, message_id=None, source_label=None: textual_display_module.TextualApp._add_runtime_injection_timeline_entry(
        app,
        agent_id,
        content,
        message_id=message_id,
        source_label=source_label,
    )
    app._set_queued_input_region_visible = lambda _visible: None
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp._on_human_input_injected(app, "Delivered", "agent_a")

    assert clear_calls == [True]


def test_handle_local_slash_command_sets_injection_target_mode():
    changes: list[str] = []
    toggles: list[bool] = []

    app = SimpleNamespace(
        _toggle_vim_mode=lambda: None,
        action_toggle_theme=lambda: None,
        _set_human_input_target_mode=lambda mode: changes.append(mode),
        _toggle_human_input_target_mode=lambda: toggles.append(True),
    )

    handled = textual_display_module.TextualApp._handle_local_slash_command(app, "/inject-target current")
    assert handled is True
    assert changes == ["current"]

    handled_toggle = textual_display_module.TextualApp._handle_local_slash_command(app, "/inject-target")
    assert handled_toggle is True
    assert toggles == [True]


def test_set_human_input_target_mode_updates_button_label():
    button = _InjectButtonStub()
    notifications: list[str] = []

    app = SimpleNamespace(
        _human_input_target_mode="all",
        _inject_target_button=button,
        _active_agent_id="agent_b",
        size=SimpleNamespace(width=150),
        app=SimpleNamespace(size=SimpleNamespace(width=150)),
        notify=lambda message, **_kwargs: notifications.append(message),
    )
    app._build_human_input_target_button_label = lambda: textual_display_module.TextualApp._build_human_input_target_button_label(app)
    app._update_human_input_target_button = lambda: textual_display_module.TextualApp._update_human_input_target_button(app)

    textual_display_module.TextualApp._set_human_input_target_mode(app, "current")

    assert "agent_b" in str(button.label)
    assert "mode-current" in button.classes
    assert any("current agent tab" in msg for msg in notifications)


def test_inject_target_button_click_toggles_mode():
    toggles: list[bool] = []
    app = SimpleNamespace(
        coordination_display=SimpleNamespace(request_cancellation=lambda: None),
        notify=lambda *_args, **_kwargs: None,
        action_toggle_human_input_target=lambda: toggles.append(True),
    )

    event = _ButtonPressedEvent("inject_target_button")
    textual_display_module.TextualApp.on_button_pressed(app, event)

    assert toggles == [True]
    assert event.stopped is True


def test_queue_action_buttons_delegate_to_queue_handlers():
    actions = []
    app = SimpleNamespace(
        coordination_display=SimpleNamespace(request_cancellation=lambda: None),
        notify=lambda *_args, **_kwargs: None,
        _cancel_latest_queued_human_input=lambda: actions.append("cancel"),
        _clear_all_queued_human_input=lambda: actions.append("clear"),
        action_toggle_human_input_target=lambda: None,
    )

    cancel_event = _ButtonPressedEvent("queue_cancel_latest_button")
    textual_display_module.TextualApp.on_button_pressed(app, cancel_event)
    clear_event = _ButtonPressedEvent("queue_clear_button")
    textual_display_module.TextualApp.on_button_pressed(app, clear_event)

    assert actions == ["cancel", "clear"]
    assert cancel_event.stopped is True
    assert clear_event.stopped is True


def test_compose_pending_human_input_for_new_turn_joins_all_messages():
    hook = _HookStub()
    hook.set_pending_input("First queued item", target_agents=["agent_a", "agent_b"])
    hook.set_pending_input("Second queued item", target_agents=["agent_b"])

    app = SimpleNamespace(
        _human_input_hook=hook,
        coordination_display=SimpleNamespace(agent_ids=["agent_a", "agent_b"]),
    )

    pending = textual_display_module.TextualApp._compose_pending_human_input_for_new_turn(app)
    assert pending == "First queued item\nSecond queued item"


def test_cancel_latest_queued_human_input_pops_message_and_refreshes_ui():
    hook = _HookStub()
    hook.set_pending_input("First", target_agents=["agent_a"])
    hook.set_pending_input("Second", target_agents=["agent_a"])
    banner = _BannerStub()
    notifications: list[str] = []

    app = SimpleNamespace(
        _human_input_hook=hook,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        _tab_bar=_TabBarStub(),
        coordination_display=SimpleNamespace(agent_ids=["agent_a"]),
        notify=lambda message, **_kwargs: notifications.append(message),
    )
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._set_queued_input_region_visible = lambda _visible: None
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp._cancel_latest_queued_human_input(app)

    assert hook.pop_calls == 1
    assert banner.replaced_messages
    assert [entry["content"] for entry in banner.replaced_messages] == ["First"]
    assert any("Cancelled latest queued injection" in message for message in notifications)


def test_clear_all_queued_human_input_clears_hook_and_ui():
    hook = _HookStub()
    hook.set_pending_input("First", target_agents=["agent_a"])
    banner = _BannerStub()
    tab_bar = _TabBarStub()

    app = SimpleNamespace(
        _human_input_hook=hook,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        _tab_bar=tab_bar,
        _queued_human_input="First",
        _queued_human_input_pending_by_agent={"agent_a": 1},
        coordination_display=SimpleNamespace(agent_ids=["agent_a"]),
        notify=lambda *_args, **_kwargs: None,
    )
    app._set_queued_input_region_visible = lambda _visible: None
    app._clear_queued_input = lambda: textual_display_module.TextualApp._clear_queued_input(app)

    textual_display_module.TextualApp._clear_all_queued_human_input(app)

    assert hook.clear_calls == 1
    assert banner.cleared == 1
    assert tab_bar.last_counts == {}


def test_ensure_queued_banner_mounts_above_input_header():
    input_area = _InputAreaStub()
    input_header = object()
    question_input = object()

    def _query_one(selector, _type=None):
        if selector == "#input_area":
            return input_area
        raise LookupError(selector)

    app = SimpleNamespace(
        _queued_input_banner=None,
        _input_header=input_header,
        question_input=question_input,
        query_one=_query_one,
    )

    textual_display_module.TextualApp._ensure_queued_input_banner_mounted(app)

    assert len(input_area.mounted) == 1
    _widget, before = input_area.mounted[0]
    assert before is input_header


def test_prepare_for_restart_attempt_preserves_queued_runtime_messages():
    hook = _HookStub()
    hook.set_pending_input("Keep this queued on restart", target_agents=["agent_b"])
    banner = _BannerStub()
    status_counts = []

    class _Panel:
        def show_restart_separator(self, attempt: int, reason: str = "", instructions: str = "") -> None:
            return None

    app = SimpleNamespace(
        _human_input_hook=hook,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        _tab_bar=_TabBarStub(),
        _status_ribbon=SimpleNamespace(reset_round_state_all_agents=lambda: None),
        _status_bar=SimpleNamespace(show_restart_count=lambda attempt, max_attempts: status_counts.append((attempt, max_attempts))),
        agent_widgets={"agent_a": _Panel(), "agent_b": _Panel()},
        clear_winner_state=lambda: None,
        set_agent_working=lambda *_args, **_kwargs: None,
    )
    app.coordination_display = SimpleNamespace(agent_ids=["agent_a", "agent_b"])
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._set_queued_input_region_visible = lambda visible: app._queued_input_region.add_class("visible") if visible else app._queued_input_region.remove_class("visible")
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp.prepare_for_restart_attempt(
        app,
        attempt=2,
        max_attempts=3,
        reason="Need another attempt",
        instructions="Retry with stronger evidence",
    )

    assert banner.replaced_messages
    assert banner.replaced_messages[0]["content"] == "Keep this queued on restart"
    assert "visible" in app._queued_input_region.classes
    assert status_counts == [(2, 3)]
    assert app._skip_queued_fallback_once_after_restart is True


def test_notify_phase_idle_skips_once_fallback_submit_after_restart():
    input_area = _InputAreaClassStub()
    set_timer_calls = []
    clear_calls = []
    hook = _HookStub()
    hook.set_pending_input("Queued injection", target_agents=["agent_a"])

    def _query_one(selector, _type=None):
        if selector == "#input_area":
            return input_area
        raise LookupError(selector)

    app = SimpleNamespace(
        _status_bar=SimpleNamespace(update_phase=lambda _phase: None),
        query_one=_query_one,
        _dismiss_decomposition_generation_modal=lambda: None,
        _execution_status_timer=None,
        _human_input_hook=hook,
        _skip_queued_fallback_once_after_restart=True,
        _queued_input_banner=_BannerStub(),
        _queued_input_region=_RegionStub(),
        _tab_bar=_TabBarStub(),
        coordination_display=SimpleNamespace(agent_ids=["agent_a"]),
        _compose_pending_human_input_for_new_turn=lambda: "Queued injection",
        _clear_queued_input=lambda: clear_calls.append(True),
        _submit_question=lambda _text: None,
        set_timer=lambda _delay, callback: set_timer_calls.append(callback),
    )
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._set_queued_input_region_visible = lambda _visible: None
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    textual_display_module.TextualApp.notify_phase(app, "idle")

    assert set_timer_calls == []
    assert clear_calls == []
    assert app._skip_queued_fallback_once_after_restart is False


def test_update_execution_status_reconciles_queue_when_pending_drains_without_callback():
    hook = _HookStub()
    hook.set_pending_input("also research bob dylan", target_agents=["agent_a"])
    banner = _BannerStub()
    tab_bar = _TabBarStub()
    status_updates: list[str] = []

    app = SimpleNamespace(
        _execution_status=SimpleNamespace(update=lambda text: status_updates.append(text)),
        _status_bar=None,
        _human_input_hook=hook,
        _queued_input_banner=banner,
        _queued_input_region=_RegionStub(),
        _tab_bar=tab_bar,
        _queued_human_input="also research bob dylan",
        _queued_human_input_pending_by_agent={},
        coordination_display=SimpleNamespace(agent_ids=["agent_a"]),
    )

    def _set_visible(visible: bool) -> None:
        if visible:
            app._queued_input_region.add_class("visible")
        else:
            app._queued_input_region.remove_class("visible")

    app._set_queued_input_region_visible = _set_visible
    app._refresh_human_input_pending_state = lambda: textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    app._sync_queued_input_banner_from_hook = lambda: textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)

    # Initial queued state is visible in tab counts/banner metadata.
    textual_display_module.TextualApp._refresh_human_input_pending_state(app)
    textual_display_module.TextualApp._sync_queued_input_banner_from_hook(app)
    assert tab_bar.last_counts == {"agent_a": 1}
    assert "visible" in app._queued_input_region.classes
    assert banner.replaced_messages

    # Simulate Codex flush path draining pending input without firing inject callback.
    hook.pending_messages.clear()
    hook._recompute_counts()

    textual_display_module.TextualApp._update_execution_status(app)

    assert status_updates == ["Working..."]
    assert tab_bar.last_counts == {"agent_a": 0}
    assert "visible" not in app._queued_input_region.classes
    assert banner.replaced_messages == []
