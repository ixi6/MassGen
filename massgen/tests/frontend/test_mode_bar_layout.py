"""Layout regression tests for the bottom input/mode bar area."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.geometry import Size

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.textual_terminal_display import TextualTerminalDisplay
from massgen.frontend.displays.textual_widgets.mode_bar import ModeBar, ModeToggle
from massgen.frontend.displays.textual_widgets.queued_input_banner import (
    QueuedInputBanner,
)


def _widget_text(widget: object) -> str:
    """Extract visible text from a Textual widget."""
    return str(widget.render())


def _strip_text(line: object) -> str:
    """Extract plain text from a Textual Strip-like render line."""
    segments = getattr(line, "segments", None) or getattr(line, "_segments", None)
    if not segments:
        return str(line)
    return "".join(getattr(segment, "text", "") for segment in segments)


def test_mode_toggle_compact_labels_do_not_keep_wide_padding() -> None:
    """Compact mode should avoid wide fixed padding to preserve horizontal space."""
    toggle = ModeToggle(
        mode_type="plan",
        initial_state="normal",
        states=["normal", "plan", "execute", "analysis"],
    )
    toggle.set_compact(True)

    rendered = str(toggle.render())
    assert "Norm" in rendered
    assert "Norm   " not in rendered


def test_mode_toggle_compact_analysis_label_is_anly() -> None:
    """Compact analysis label should use a short neutral token."""
    toggle = ModeToggle(
        mode_type="plan",
        initial_state="analysis",
        states=["normal", "plan", "execute", "analysis"],
    )
    toggle.set_compact(True)

    rendered = str(toggle.render())
    assert "Anly" in rendered
    assert "Analyze" not in rendered


def test_mode_toggle_persona_off_label_is_neutral() -> None:
    """Persona toggle should avoid explicit OFF text; inactive state is shown via styling."""
    compact_toggle = ModeToggle(
        mode_type="personas",
        initial_state="off",
        states=["off", "on"],
    )
    compact_toggle.set_compact(True)
    compact_rendered = str(compact_toggle.render())
    assert "Persona Off" not in compact_rendered
    assert "Persona" in compact_rendered

    full_toggle = ModeToggle(
        mode_type="personas",
        initial_state="off",
        states=["off", "on"],
    )
    full_toggle.set_compact(False)
    full_rendered = str(full_toggle.render())
    assert "Personas OFF" not in full_rendered
    assert "Personas" in full_rendered


@pytest.mark.asyncio
async def test_mode_bar_keeps_compact_labels_when_width_temporarily_unavailable(monkeypatch, tmp_path: Path) -> None:
    """Transient zero-width measurements should not flip compact labels to long variants."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None
        app._mode_bar.set_plan_mode("plan")
        await pilot.pause()

        for toggle in (
            app._mode_bar._plan_toggle,
            app._mode_bar._agent_toggle,
            app._mode_bar._coordination_toggle,
            app._mode_bar._refinement_toggle,
            app._mode_bar._persona_toggle,
        ):
            if toggle:
                toggle.set_compact(True)
        app._mode_bar._last_responsive_width = 80

        monkeypatch.setattr(
            ModeBar,
            "size",
            property(lambda _self: Size(0, 0)),
        )

        app._mode_bar._refresh_responsive_labels()
        rendered = _widget_text(app.query_one("#plan_toggle"))
        assert "Plan" in rendered
        assert "Planning" not in rendered


@pytest.mark.asyncio
async def test_mode_bar_does_not_stack_when_initial_width_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    """Startup with unknown widths should not force the two-row compact layout."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None

        app._mode_bar.remove_class("compact-layout")
        app._mode_bar._last_responsive_width = 0

        monkeypatch.setattr(ModeBar, "size", property(lambda _self: Size(0, 0)))
        monkeypatch.setattr(type(app), "size", property(lambda _self: Size(0, 0)))

        app._mode_bar._refresh_responsive_labels()

        assert not app._mode_bar.has_class("compact-layout")


@pytest.mark.asyncio
async def test_default_plan_mode_bootstraps_into_plan_mode(monkeypatch, tmp_path: Path) -> None:
    """Display-level default plan mode should initialize the TUI in Plan mode."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
        default_plan_mode="plan",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()

        assert app._mode_state.plan_mode == "plan"
        assert app._mode_bar is not None
        assert app._mode_bar.get_plan_mode() == "plan"


@pytest.mark.asyncio
async def test_mode_bar_logs_layout_refresh_decisions(monkeypatch, tmp_path: Path) -> None:
    """Mode bar should emit explicit debug lines for layout refresh calculations."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    import massgen.frontend.displays.textual_widgets.mode_bar as mode_bar_module

    layout_logs: list[str] = []
    monkeypatch.setattr(mode_bar_module, "_mode_log", lambda msg: layout_logs.append(msg))

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None
        app._mode_bar._refresh_responsive_labels()
        await pilot.pause()

        assert any("layout refresh:" in msg for msg in layout_logs)
        assert any("layout decision:" in msg for msg in layout_logs)


@pytest.mark.asyncio
async def test_input_modes_row_logs_layout_decisions(monkeypatch, tmp_path: Path) -> None:
    """Input row layout refresh should emit calculation details for debugging."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    layout_logs: list[str] = []
    monkeypatch.setattr(textual_display_module, "tui_log", lambda msg, level="debug": layout_logs.append(msg))

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        app._refresh_input_modes_row_layout()
        await pilot.pause()

        assert any("[INPUT_LAYOUT]" in msg for msg in layout_logs)


@pytest.mark.asyncio
async def test_normal_mode_compacts_labels_to_keep_input_header_single_row_at_thin_startup(monkeypatch, tmp_path: Path) -> None:
    """Thin startup widths should prefer compact mode labels over stacking the input header row."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )
    # Keep hint width deterministic across environments.
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: Path("/home/u/project")))

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(113, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()

        input_modes_row = app.query_one("#input_modes_row")
        assert "meta-stacked" not in input_modes_row.classes
        assert "Norm" in _widget_text(app.query_one("#plan_toggle"))
        assert "Multi" in _widget_text(app.query_one("#agent_toggle"))
        assert "Par" in _widget_text(app.query_one("#coordination_toggle"))


@pytest.mark.asyncio
async def test_mode_bar_stays_within_input_header_at_narrow_width(monkeypatch, tmp_path: Path) -> None:
    """Mode bar should stay in bounds while keeping primary toggle labels visible."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=True),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(90, 24)) as pilot:
        await pilot.pause()

        # Max out mode-bar content to mimic the reported overlap case.
        app._update_vim_indicator(False)  # insert mode -> input hint visible
        assert app._mode_bar is not None
        app._mode_bar.set_plan_mode("analysis")
        app._mode_bar.set_coordination_mode("decomposition")
        app._mode_bar.set_skills_available(True)
        await pilot.pause()
        app._refresh_input_modes_row_layout()
        await pilot.pause()

        mode_bar = app.query_one("#mode_bar")
        input_header = app.query_one("#input_header")

        mode_left = mode_bar.region.x
        mode_right = mode_left + mode_bar.region.width
        header_left = input_header.region.x
        header_right = header_left + input_header.region.width

        assert mode_left >= header_left
        assert mode_right <= header_right
        assert mode_bar.region.height >= 2

        # Primary run-mode toggles should remain visible, not clipped to icon-only.
        for toggle_id in ("#plan_toggle", "#agent_toggle", "#refinement_toggle", "#coordination_toggle"):
            toggle = app.query_one(toggle_id)
            assert toggle.region.width > 0
            assert toggle.region.height > 0
            assert toggle.region.x + toggle.region.width <= mode_right

        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Anly", "Analyze"))
        assert "Decomp" in _widget_text(app.query_one("#coordination_toggle"))

        # Row layout may remain single-line if controls fit after responsive compaction.
        row_primary = app.query_one("#mode_row_primary")
        row_secondary = app.query_one("#mode_row_secondary")
        assert row_secondary.region.y >= row_primary.region.y

        # Meta panel should move below mode controls on narrow layouts.
        input_modes_row = app.query_one("#input_modes_row")
        input_meta_panel = app.query_one("#input_meta_panel")
        assert "meta-stacked" in input_modes_row.classes
        assert input_meta_panel.region.y > mode_bar.region.y

        vim_indicator = app.query_one("#vim_indicator")
        input_hint = app.query_one("#input_hint")
        assert "Insert" in _widget_text(vim_indicator)
        assert "Ctrl+P" in _widget_text(input_hint)
        assert input_hint.region.y > mode_bar.region.y


@pytest.mark.asyncio
async def test_analysis_mode_stacks_meta_panel_at_standard_narrow_width(monkeypatch, tmp_path: Path) -> None:
    """Analysis mode should prioritize run controls and stack right-side meta hints earlier."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=True),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(150, 24)) as pilot:
        await pilot.pause()
        app._update_vim_indicator(False)
        assert app._mode_bar is not None
        app._mode_state.plan_mode = "analysis"
        app._mode_bar.set_plan_mode("analysis")
        app._refresh_input_modes_row_layout()
        await pilot.pause()

        input_modes_row = app.query_one("#input_modes_row")
        input_meta_panel = app.query_one("#input_meta_panel")
        mode_bar = app.query_one("#mode_bar")

        assert "meta-stacked" in input_modes_row.classes
        assert input_meta_panel.region.y > mode_bar.region.y
        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Anly", "Analyze", "Analyzing"))


@pytest.mark.asyncio
async def test_mode_bar_does_not_render_skills_button(monkeypatch, tmp_path: Path) -> None:
    """Skills manager should no longer appear as a mode-bar control."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause()
        assert len(app.query("#skills_btn")) == 0


@pytest.mark.asyncio
async def test_mode_bar_uses_single_row_when_space_is_available(monkeypatch, tmp_path: Path) -> None:
    """Wide terminals should keep mode controls on a single row."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(170, 28)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None
        app._mode_bar.set_skills_available(True)
        await pilot.pause()

        row_primary = app.query_one("#mode_row_primary")
        row_secondary = app.query_one("#mode_row_secondary")
        assert row_secondary.region.y == row_primary.region.y

        # Plan label should remain visible in wider states when toggled.
        app._mode_bar.set_plan_mode("plan")
        await pilot.pause()
        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Planning", "Plan"))

        app._mode_bar.set_plan_mode("execute")
        await pilot.pause()
        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Executing", "Exec"))

        app._mode_bar.set_plan_mode("analysis")
        await pilot.pause()
        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Analyzing", "Analyze", "Anly"))


@pytest.mark.asyncio
async def test_mode_bar_prefers_single_row_near_boundary_width(monkeypatch, tmp_path: Path) -> None:
    """Near-boundary widths should keep mode controls on one row."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(130, 26)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None
        app._mode_bar._refresh_responsive_labels()
        await pilot.pause()

        row_primary = app.query_one("#mode_row_primary")
        row_secondary = app.query_one("#mode_row_secondary")
        assert row_secondary.region.y == row_primary.region.y

        assert any(token in _widget_text(app.query_one("#plan_toggle")) for token in ("Normal", "Norm"))
        assert any(token in _widget_text(app.query_one("#agent_toggle")) for token in ("Multi-Agent", "Multi"))
        assert any(token in _widget_text(app.query_one("#coordination_toggle")) for token in ("Parallel", "Par"))


@pytest.mark.asyncio
async def test_mode_bar_compacts_labels_at_standard_narrow_width(monkeypatch, tmp_path: Path) -> None:
    """Borderline narrow widths should compact labels before the mode row looks cramped."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(129, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None
        app._mode_bar._refresh_responsive_labels()
        await pilot.pause()
        assert "Norm" in _widget_text(app.query_one("#plan_toggle"))
        assert "Multi" in _widget_text(app.query_one("#agent_toggle"))
        assert "Par" in _widget_text(app.query_one("#coordination_toggle"))


@pytest.mark.asyncio
async def test_mode_bar_uses_full_labels_when_row_has_spare_space(monkeypatch, tmp_path: Path) -> None:
    """Roomy single-row layouts should keep full labels instead of compact tokens."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=True),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(150, 24)) as pilot:
        await pilot.pause()
        app._update_vim_indicator(False)
        assert app._mode_bar is not None
        app._mode_bar.set_plan_mode("normal")
        app._refresh_input_modes_row_layout()
        await pilot.pause()

        plan_text = _widget_text(app.query_one("#plan_toggle"))
        assert "Normal" in plan_text
        assert " ○ Norm " not in plan_text
        assert "Multi-Agent" in _widget_text(app.query_one("#agent_toggle"))
        assert "Parallel" in _widget_text(app.query_one("#coordination_toggle"))


@pytest.mark.asyncio
async def test_normal_mode_keeps_meta_panel_inline_when_content_fits(monkeypatch, tmp_path: Path) -> None:
    """Normal mode should keep right-side meta hints on the same row when content fits."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=True),
    )
    # Pin CWD to a short deterministic path so hint text width is stable
    # across local (macOS) and CI (Ubuntu) environments.
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: Path("/home/u/project")))

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(150, 24)) as pilot:
        await pilot.pause()
        app._update_vim_indicator(False)
        assert app._mode_bar is not None
        app._mode_bar.set_plan_mode("normal")
        app._refresh_input_modes_row_layout()
        await pilot.pause()
        await pilot.pause()

        input_modes_row = app.query_one("#input_modes_row")
        assert "meta-stacked" not in input_modes_row.classes


@pytest.mark.asyncio
async def test_mode_bar_does_not_flip_labels_with_small_width_jitter(monkeypatch, tmp_path: Path) -> None:
    """Small width jitter around the breakpoint should not toggle compact/full labels repeatedly."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(130, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None

        widths = [103, 104, 103, 104, 103, 104]
        idx = {"value": 0}
        original_size = app._mode_bar.size

        def _next_width() -> int:
            if idx["value"] >= len(widths):
                return widths[-1]
            width = widths[idx["value"]]
            idx["value"] += 1
            return width

        monkeypatch.setattr(
            ModeBar,
            "size",
            property(lambda _self: Size(_next_width(), original_size.height or 2)),
        )

        labels = []
        for _ in range(len(widths)):
            app._mode_bar._refresh_responsive_labels()
            labels.append(_widget_text(app.query_one("#plan_toggle")))

        # Should stay in one representation instead of flickering between
        # "Normal" and "Norm" while width jitters by one column.
        has_long = any("Normal" in text for text in labels)
        has_short = any("Norm" in text and "Normal" not in text for text in labels)
        assert not (has_long and has_short)


@pytest.mark.asyncio
async def test_mode_bar_unstacks_as_soon_as_compact_labels_fit(monkeypatch, tmp_path: Path) -> None:
    """Mode bar should return to one row once compact labels fit available width."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(130, 24)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None

        widths = [100, 113]
        width_idx = {"value": 0}
        original_size = app._mode_bar.size

        def _next_width() -> int:
            if width_idx["value"] >= len(widths):
                return widths[-1]
            width = widths[width_idx["value"]]
            width_idx["value"] += 1
            return width

        monkeypatch.setattr(
            ModeBar,
            "size",
            property(lambda _self: Size(_next_width(), original_size.height or 2)),
        )

        # First refresh: full labels overflow and compact labels also overflow,
        # so stacked layout is required.
        # Second refresh: full labels still overflow, but compact labels fit;
        # layout should return to a single row immediately.
        measured_widths = [120, 110, 118, 111]
        measured_idx = {"value": 0}

        def _next_measured_width() -> int:
            if measured_idx["value"] >= len(measured_widths):
                return measured_widths[-1]
            value = measured_widths[measured_idx["value"]]
            measured_idx["value"] += 1
            return value

        monkeypatch.setattr(app._mode_bar, "_measure_control_width", _next_measured_width)

        app._mode_bar._refresh_responsive_labels()
        assert app._mode_bar.has_class("compact-layout")

        app._mode_bar._refresh_responsive_labels()
        assert not app._mode_bar.has_class("compact-layout")
        assert "Norm" in _widget_text(app.query_one("#plan_toggle"))
        assert "Normal" not in _widget_text(app.query_one("#plan_toggle"))


@pytest.mark.asyncio
async def test_single_agent_mode_disables_decomposition(monkeypatch, tmp_path: Path) -> None:
    """Single-agent mode should force parallel coordination and disable decomposition toggle."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 26)) as pilot:
        await pilot.pause()
        assert app._mode_bar is not None

        # Multi-agent mode can use decomposition.
        app._handle_coordination_mode_change("decomposition")
        await pilot.pause()
        assert app._mode_state.coordination_mode == "decomposition"
        assert app._mode_bar.get_coordination_mode() == "decomposition"

        # Switching to single-agent mode forces coordination back to parallel.
        app._handle_agent_mode_change("single")
        await pilot.pause()
        coordination_toggle = app.query_one("#coordination_toggle")
        assert app._mode_state.coordination_mode == "parallel"
        assert app._mode_bar.get_coordination_mode() == "parallel"
        assert "disabled" in coordination_toggle.classes

        # Attempting decomposition while single-agent should be rejected.
        app._handle_coordination_mode_change("decomposition")
        await pilot.pause()
        assert app._mode_state.coordination_mode == "parallel"
        assert app._mode_bar.get_coordination_mode() == "parallel"

        # Returning to multi-agent mode re-enables the coordination toggle.
        app._handle_agent_mode_change("multi")
        await pilot.pause()
        assert "disabled" not in coordination_toggle.classes


@pytest.mark.asyncio
async def test_welcome_screen_reflows_for_narrow_terminals(monkeypatch, tmp_path: Path) -> None:
    """Welcome screen should use compact content while keeping right-panel hints readable."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(70, 24)) as pilot:
        await pilot.pause()

        logo_text = _widget_text(app.query_one("#welcome_logo"))
        agents_text = _widget_text(app.query_one("#welcome_agents"))
        input_hint_text = _widget_text(app.query_one("#input_hint"))
        vim_indicator = app.query_one("#vim_indicator")
        input_header = app.query_one("#input_header")
        input_hint = app.query_one("#input_hint")

        assert logo_text.strip() == "MASSGEN"
        assert "agent_a" in agents_text
        assert "openai/gpt-5.3-codex" in agents_text
        assert "anthropic/claude-opus-4-6" in agents_text
        assert "google/gemini-3-flash-preview" in agents_text
        assert "Ctrl+P" in input_hint_text
        assert "CWD" in input_hint_text
        assert Path.cwd().name in input_hint_text
        assert len(input_hint_text) <= 42
        assert input_header.region.y <= vim_indicator.region.y < input_header.region.y + input_header.region.height
        assert input_header.region.y <= input_hint.region.y < input_header.region.y + input_header.region.height
        assert input_hint.region.y > vim_indicator.region.y


@pytest.mark.asyncio
async def test_welcome_screen_uses_left_aligned_agent_model_rows(monkeypatch, tmp_path: Path) -> None:
    """Wide welcome layout should render agent/model lines in left-aligned rows."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b", "agent_c"],
        agent_models={
            "agent_a": "gpt-5.3-codex",
            "agent_b": "claude-opus-4-6",
            "agent_c": "gemini-3-flash-preview",
        },
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 26)) as pilot:
        await pilot.pause()
        agents_widget = app.query_one("#welcome_agents")
        agents_text = _widget_text(app.query_one("#welcome_agents"))
        model_rows = [line for line in agents_text.splitlines() if " - " in line and "/" in line]
        assert len(model_rows) == 3
        assert all(line.startswith("agent_") for line in model_rows)
        assert all(" - " in line for line in model_rows)
        assert agents_widget.region.x > 0


@pytest.mark.asyncio
async def test_context_hint_persists_after_first_prompt(monkeypatch, tmp_path: Path) -> None:
    """CWD/context hint should remain visible in the input meta panel after welcome is dismissed."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(100, 24)) as pilot:
        await pilot.pause()
        input_hint = app.query_one("#input_hint")
        assert "Ctrl+P" in _widget_text(input_hint)
        assert "CWD" in _widget_text(input_hint)
        assert Path.cwd().name in _widget_text(input_hint)

        app._dismiss_welcome()
        await pilot.pause()
        assert "hidden" not in input_hint.classes
        assert "Ctrl+P" in _widget_text(input_hint)
        assert "CWD" in _widget_text(input_hint)


@pytest.mark.asyncio
async def test_input_bar_shows_placeholder_shadow_text(monkeypatch, tmp_path: Path) -> None:
    """Empty input should still show guidance text in-place."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(100, 24)) as pilot:
        await pilot.pause()
        question_input = app.query_one("#question_input")
        assert question_input.text == ""
        placeholder_line = _strip_text(question_input.render_line(0))
        assert "Enter to submit" in placeholder_line


@pytest.mark.asyncio
async def test_ctrl_p_toggle_emits_full_cwd_toast(monkeypatch, tmp_path: Path) -> None:
    """Ctrl+P should emit a toast that includes full CWD and new context mode."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    toasts: list[str] = []

    def _capture_toast(message: str, **_: object) -> None:
        toasts.append(message)

    async with app.run_test(headless=True, size=(100, 24)) as pilot:
        await pilot.pause()
        app.notify = _capture_toast  # type: ignore[assignment]
        app._toggle_cwd_auto_include()  # off -> read
        await pilot.pause()

        assert toasts
        assert "Ctrl+P: CWD context read-only" in toasts[-1]
        assert str(Path.cwd()) in toasts[-1]


@pytest.mark.asyncio
async def test_ctrl_p_hint_uses_short_mode_tokens(monkeypatch, tmp_path: Path) -> None:
    """Right-side CWD hint should use short mode tokens (ro/rw) to preserve space."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(110, 24)) as pilot:
        await pilot.pause()
        input_hint = app.query_one("#input_hint")

        app._toggle_cwd_auto_include()  # off -> read
        await pilot.pause()
        hint_text = _widget_text(input_hint)
        assert "CWD ro" in hint_text
        assert "read-only" not in hint_text
        assert "@path include" not in hint_text

        app._toggle_cwd_auto_include()  # read -> write
        await pilot.pause()
        hint_text = _widget_text(input_hint)
        assert "CWD rw" in hint_text
        assert "read+write" not in hint_text
        assert "@path include" not in hint_text


@pytest.mark.asyncio
async def test_ctrl_p_hint_markup_emphasizes_ro_rw_tokens(monkeypatch, tmp_path: Path) -> None:
    """Hint source text should emphasize ro/rw tokens for quick visual scanning."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(110, 24)) as pilot:
        await pilot.pause()

        app._toggle_cwd_auto_include()  # off -> read
        await pilot.pause()
        hint_markup = app._build_welcome_context_hint_text()
        assert "[bold]ro[/]" in hint_markup
        assert "@path include" not in hint_markup

        app._toggle_cwd_auto_include()  # read -> write
        await pilot.pause()
        hint_markup = app._build_welcome_context_hint_text()
        assert "[bold]rw[/]" in hint_markup
        assert "@path include" not in hint_markup


@pytest.mark.asyncio
async def test_cwd_context_default_mode_initializes_like_ctrl_p(monkeypatch, tmp_path: Path) -> None:
    """Default CWD context mode should initialize app/UI state as if toggled via Ctrl+P."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
        default_cwd_context_mode="write",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(110, 24)) as pilot:
        await pilot.pause()
        assert app._cwd_context_mode == "write"
        assert "CWD rw" in _widget_text(app.query_one("#input_hint"))
        assert "read+write" in _widget_text(app.query_one("#status_cwd"))


@pytest.mark.asyncio
async def test_ctrl_p_blocked_in_execute_mode(monkeypatch, tmp_path: Path) -> None:
    """Ctrl+P should not change CWD context mode while execute mode is active."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a"],
        agent_models={"agent_a": "gpt-5.3-codex"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    toasts: list[str] = []

    def _capture_toast(message: str, **_: object) -> None:
        toasts.append(message)

    async with app.run_test(headless=True, size=(110, 24)) as pilot:
        await pilot.pause()
        app.notify = _capture_toast  # type: ignore[assignment]
        app._mode_state.plan_mode = "execute"

        app.action_toggle_cwd()
        await pilot.pause()

        assert app._cwd_context_mode == "off"
        assert "Cannot change CWD context in execute mode." in toasts[-1]


@pytest.mark.asyncio
async def test_inject_button_is_embedded_inside_input_bar(monkeypatch, tmp_path: Path) -> None:
    """Inject target control should be structurally embedded in the input bar."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={"agent_a": "gpt-5.3-codex", "agent_b": "claude-opus-4-6"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(120, 26)) as pilot:
        await pilot.pause()
        await pilot.pause()

        mode_bar = app.query_one("#mode_bar")
        question_input_row = app.query_one("#question_input_row")
        question_input = app.query_one("#question_input")
        inject_button = app.query_one("#inject_target_button")

        assert inject_button.region.x >= question_input.region.right - 1
        assert inject_button.region.right <= question_input_row.region.right
        assert inject_button.region.y >= question_input_row.region.y
        assert inject_button.region.y > mode_bar.region.y


@pytest.mark.asyncio
async def test_queue_action_buttons_share_row_with_queue_summary(monkeypatch, tmp_path: Path) -> None:
    """Queue action buttons should align to the right of the queue summary row."""
    monkeypatch.setattr(textual_display_module, "get_event_emitter", lambda: None)
    monkeypatch.setattr(
        textual_display_module,
        "get_user_settings",
        lambda: SimpleNamespace(theme="dark", vim_mode=False),
    )

    display = TextualTerminalDisplay(
        ["agent_a", "agent_b"],
        agent_models={"agent_a": "gpt-5.3-codex", "agent_b": "claude-opus-4-6"},
        keyboard_interactive_mode=False,
        output_dir=tmp_path,
        theme="dark",
    )
    app = textual_display_module.TextualApp(
        display=display,
        question="Welcome! Type your question below...",
        buffers=display._buffers,
        buffer_lock=display._buffer_lock,
        buffer_flush_interval=display.buffer_flush_interval,
    )
    display._app = app

    async with app.run_test(headless=True, size=(130, 34)) as pilot:
        await pilot.pause()
        await pilot.pause()

        banner = app._queued_input_banner
        assert isinstance(banner, QueuedInputBanner)
        banner.set_messages(
            [
                {
                    "id": 11,
                    "content": "Please include edge-case handling in your revised answer.",
                    "target_label": "all agents",
                    "pending_agents": ["agent_b"],
                },
                {
                    "id": 12,
                    "content": "Also add one adversarial test case for malformed input.",
                    "target_label": "all agents",
                    "pending_agents": ["agent_b"],
                },
            ],
        )
        banner.set_pending_counts({"agent_b": 2})
        app._set_queued_input_region_visible(True)
        await pilot.pause()

        mode_bar = app.query_one("#mode_bar")
        cancel_button = app.query_one("#queue_cancel_latest_button")
        clear_button = app.query_one("#queue_clear_button")

        assert cancel_button.region.y == banner.region.y
        assert clear_button.region.y == banner.region.y
        assert cancel_button.region.x >= banner.region.right
        assert clear_button.region.x > cancel_button.region.x
        assert mode_bar.region.y - clear_button.region.bottom <= 1
