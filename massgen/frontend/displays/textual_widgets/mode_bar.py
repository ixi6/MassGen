"""
Mode Bar Widget for MassGen TUI.

Provides a responsive mode bar with toggles for plan/analyze mode, agent mode,
coordination mode, refinement mode, and override functionality.
"""

from typing import TYPE_CHECKING, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from massgen.frontend.displays.tui_modes import PlanDepth


class ModeChanged(Message):
    """Message emitted when a mode toggle changes."""

    def __init__(self, mode_type: str, value: str) -> None:
        """Initialize the message.

        Args:
            mode_type: The type of mode changed ("plan", "agent", "coordination", "refinement", "personas").
            value: The new value of the mode.
        """
        self.mode_type = mode_type
        self.value = value
        super().__init__()


class PlanConfigChanged(Message):
    """Message emitted when plan configuration changes."""

    def __init__(self, depth: Optional["PlanDepth"] = None, auto_execute: bool | None = None) -> None:
        """Initialize the message.

        Args:
            depth: New plan depth if changed.
            auto_execute: New auto-execute setting if changed.
        """
        self.depth = depth
        self.auto_execute = auto_execute
        super().__init__()


class OverrideRequested(Message):
    """Message emitted when user requests override."""


class PlanSettingsClicked(Message):
    """Message emitted when plan settings button is clicked."""


class ModeHelpClicked(Message):
    """Message emitted when mode bar help button is clicked."""


class SubtasksClicked(Message):
    """Message emitted when subtasks button is clicked."""


class SkillsClicked(Message):
    """Deprecated message kept for compatibility with older imports."""


def _mode_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[MODE] {msg}")


class ModeToggle(Static):
    """A clickable toggle button for a mode.

    Displays current state and cycles through states on click.
    """

    can_focus = True

    # Icons for different modes - using radio indicators for clean look
    ICONS = {
        "plan": {"normal": "○", "plan": "◉", "spec": "◉", "execute": "◉", "analysis": "◉"},
        "agent": {"multi": "◉", "single": "○"},
        "coordination": {"parallel": "◉", "decomposition": "○"},
        "refinement": {"on": "◉", "off": "○"},
        "personas": {"off": "○", "perspective": "◉", "implementation": "◉", "methodology": "◉"},
    }

    # Labels for states - concise without redundant ON/OFF
    LABELS = {
        "plan": {"normal": "Normal", "plan": "Planning", "spec": "Spec", "execute": "Executing", "analysis": "Analyzing"},
        "agent": {"multi": "Multi-Agent", "single": "Single"},
        "coordination": {"parallel": "Parallel", "decomposition": "Decomposition"},
        "refinement": {"on": "Refine", "off": "Refine OFF"},
        "personas": {"off": "Personas", "perspective": "Perspective", "implementation": "Implementation", "methodology": "Methodology"},
    }

    COMPACT_LABELS = {
        "plan": {"normal": "Norm", "plan": "Plan", "spec": "Spec", "execute": "Exec", "analysis": "Anly"},
        "agent": {"multi": "Multi", "single": "Single"},
        "coordination": {"parallel": "Par", "decomposition": "Decomp"},
        "refinement": {"on": "Refine", "off": "Refine Off"},
        "personas": {"off": "Persona", "perspective": "Persp", "implementation": "Impl", "methodology": "Method"},
    }

    def __init__(
        self,
        mode_type: str,
        initial_state: str,
        states: list[str],
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the mode toggle.

        Args:
            mode_type: The type of mode ("plan", "agent", "coordination", "refinement").
            initial_state: The initial state value.
            states: List of valid states to cycle through.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.mode_type = mode_type
        self._states = states
        self._current_state = initial_state
        self._enabled = True
        self._compact = False

    def on_mount(self) -> None:
        """Apply initial style class on mount."""
        self._update_style()

    def render(self) -> str:
        """Render the toggle button."""
        icon = self.ICONS.get(self.mode_type, {}).get(self._current_state, "⚙️")
        labels = self.COMPACT_LABELS if self._compact else self.LABELS
        label_map = labels.get(self.mode_type, {})
        label = label_map.get(self._current_state, self._current_state)
        if self._compact:
            # Preserve horizontal space on narrow terminals by avoiding fixed-width
            # padding in compact mode.
            return f" {icon} {label} "

        # Keep a stable width across state transitions so longer plan labels
        # (Planning/Executing/Analyzing) remain fully visible.
        max_label_width = max((len(value) for value in label_map.values()), default=len(label))
        return f" {icon} {label.ljust(max_label_width)} "

    def set_state(self, state: str) -> None:
        """Set the toggle state.

        Args:
            state: The new state value.
        """
        if state in self._states:
            self._current_state = state
            self._update_style()
            self.refresh()

    def get_state(self) -> str:
        """Get the current state."""
        return self._current_state

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the toggle.

        Args:
            enabled: True to enable, False to disable.
        """
        self._enabled = enabled
        if enabled:
            self.remove_class("disabled")
        else:
            self.add_class("disabled")

    def set_compact(self, compact: bool) -> None:
        """Toggle compact labels for narrow terminals."""
        if self._compact == compact:
            return
        self._compact = compact
        self.refresh(layout=True)

    def _update_style(self) -> None:
        """Update CSS classes based on current state."""
        # Remove all state classes
        for state in self._states:
            self.remove_class(f"state-{state}")
        # Add current state class
        self.add_class(f"state-{self._current_state}")

    async def on_click(self) -> None:
        """Handle click to cycle to next state."""
        if not self._enabled:
            return

        _mode_log(f"ModeToggle.on_click: {self.mode_type} current={self._current_state}")

        # For plan mode, cycle through: normal -> plan -> spec -> execute -> analysis -> normal
        if self.mode_type == "plan":
            if self._current_state == "normal":
                new_state = "plan"
            elif self._current_state == "plan":
                new_state = "spec"
            elif self._current_state == "spec":
                new_state = "execute"
            elif self._current_state == "execute":
                new_state = "analysis"
            elif self._current_state == "analysis":
                new_state = "normal"
            else:
                return
        else:
            # Cycle through states
            current_idx = self._states.index(self._current_state)
            next_idx = (current_idx + 1) % len(self._states)
            new_state = self._states[next_idx]

        self._current_state = new_state
        self._update_style()
        self.refresh()
        self.post_message(ModeChanged(self.mode_type, new_state))


class ModeBar(Widget):
    """Responsive mode bar with toggles positioned above the input area.

    Contains toggles for:
    - Plan/analyze mode: normal → plan → execute → analysis
    - Agent mode: multi ↔ single
    - Refinement mode: on ↔ off
    - Coordination mode: parallel ↔ decomposition
    - Personas toggle (parallel mode only)
    - Subtasks button (shown in decomposition mode)
    - Help button for mode bar explanations
    - Override button (shown when override is available)
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Reactive for override button visibility
    override_available: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the mode bar."""
        super().__init__(id=id, classes=classes)
        self._plan_toggle: ModeToggle | None = None
        self._agent_toggle: ModeToggle | None = None
        self._coordination_toggle: ModeToggle | None = None
        self._refinement_toggle: ModeToggle | None = None
        self._persona_toggle: ModeToggle | None = None
        self._subtasks_btn: Button | None = None
        self._mode_help_btn: Button | None = None
        self._override_btn: Button | None = None
        self._plan_info: Label | None = None
        self._plan_settings_btn: Button | None = None
        self._plan_status: Static | None = None
        self._last_responsive_width: int = 0
        self._compact_labels_active: bool = False

    def compose(self) -> ComposeResult:
        """Create mode bar contents."""
        with Vertical(id="mode_rows"):
            with Horizontal(id="mode_row_primary"):
                # Plan mode toggle
                self._plan_toggle = ModeToggle(
                    mode_type="plan",
                    initial_state="normal",
                    states=["normal", "plan", "spec", "execute", "analysis"],
                    id="plan_toggle",
                )
                yield self._plan_toggle

                # Agent mode toggle
                self._agent_toggle = ModeToggle(
                    mode_type="agent",
                    initial_state="multi",
                    states=["multi", "single"],
                    id="agent_toggle",
                )
                yield self._agent_toggle

                # Refinement mode toggle
                self._refinement_toggle = ModeToggle(
                    mode_type="refinement",
                    initial_state="on",
                    states=["on", "off"],
                    id="refinement_toggle",
                )
                yield self._refinement_toggle

                # Coordination mode toggle (parallel voting vs decomposition subtasks)
                self._coordination_toggle = ModeToggle(
                    mode_type="coordination",
                    initial_state="parallel",
                    states=["parallel", "decomposition"],
                    id="coordination_toggle",
                )
                yield self._coordination_toggle

            with Horizontal(id="mode_row_secondary"):
                # Parallel persona generation toggle with diversity mode selection
                self._persona_toggle = ModeToggle(
                    mode_type="personas",
                    initial_state="off",
                    states=["off", "perspective", "implementation", "methodology"],
                    id="persona_toggle",
                )
                yield self._persona_toggle

                # Subtasks editor button (decomposition mode only)
                self._subtasks_btn = Button("Subtasks", id="subtasks_btn", variant="default")
                self._subtasks_btn.add_class("hidden")
                yield self._subtasks_btn

                # Plan settings button (hidden when plan mode is "normal")
                self._plan_settings_btn = Button("⋮", id="plan_settings_btn", variant="default")
                self._plan_settings_btn.add_class("hidden")
                yield self._plan_settings_btn

                # Mode bar help button
                self._mode_help_btn = Button("?", id="mode_help_btn", variant="default")
                yield self._mode_help_btn

                # Plan info (shown when executing plan)
                self._plan_info = Label("", id="plan_info")
                yield self._plan_info

                # Spacer to push status and override button to the right
                yield Static("", id="mode_spacer")

                # Plan status text (right-aligned, shows plan being executed)
                self._plan_status = Static("", id="plan_status", classes="hidden")
                yield self._plan_status

                # Override button (hidden by default)
                self._override_btn = Button("Override [Ctrl+O]", id="override_btn", variant="warning")
                self._override_btn.add_class("hidden")
                yield self._override_btn

    def on_mount(self) -> None:
        """Initialize responsive labels once layout is available."""
        app_width = self.app.size.width if self.app is not None else 0
        _mode_log(
            "layout refresh: " f"source=on_mount widget_width={self.size.width} app_width={app_width} " f"last_width={self._last_responsive_width}",
        )
        self.call_after_refresh(self._refresh_responsive_labels)

    def on_resize(self, event: events.Resize) -> None:
        """Keep toggle labels readable on narrow terminals."""
        _mode_log(
            "layout refresh: " f"source=on_resize event_width={event.size.width} widget_width={self.size.width} " f"last_width={self._last_responsive_width}",
        )
        del event
        self._refresh_responsive_labels()

    def _refresh_responsive_labels(self) -> None:
        """Switch to compact labels and shorter button text when constrained."""
        width = self.size.width
        app_width = self.app.size.width if self.app is not None else 0
        if width > 0:
            self._last_responsive_width = width
        elif self._last_responsive_width > 0:
            width = self._last_responsive_width
        else:
            width = app_width

        # Guard against transient widget-size mismatches by considering app width.
        if width > 0 and app_width > 0:
            effective_width = min(width, app_width)
        else:
            effective_width = width or app_width

        _mode_log(
            "layout refresh: "
            f"source=responsive_pass widget_width={self.size.width} app_width={app_width} "
            f"derived_width={width} effective_width={effective_width} "
            f"last_width={self._last_responsive_width} compact_active={self._compact_labels_active}",
        )

        # During cold-start layout, both widget/app width can be temporarily
        # unavailable. Avoid forcing the conservative stacked fallback here;
        # keep the current layout until a real width arrives.
        if effective_width <= 0:
            _mode_log("layout decision: unresolved_width keep_current_layout")
            return

        # Compute full-label footprint first, then apply hysteresis so tiny
        # width changes don't flip labels between compact/non-compact states.
        self._apply_compact_labels(False)
        full_required = self._measure_control_width()
        utilization = (full_required / max(1, effective_width)) if effective_width > 0 else 0.0

        if self._compact_labels_active:
            # Stay compact while controls are near capacity, but return to full
            # labels once the row has comfortable slack.
            near_capacity = utilization >= 0.86
            compact_labels = (effective_width > 0 and full_required > max(0, effective_width - 8)) or near_capacity
        else:
            # Enter compact when controls are close to saturating row width.
            near_capacity = utilization >= 0.90
            compact_labels = (effective_width > 0 and full_required > max(0, effective_width - 3)) or near_capacity

        self._apply_compact_labels(compact_labels)
        self._compact_labels_active = compact_labels

        # Prefer a single row when controls can fit; stack only when necessary.
        required_width = self._measure_control_width()
        if effective_width > 0 and required_width > 0:
            # Keep the mode bar on one row whenever compact/full labels fit.
            # Only stack when controls exceed available width.
            stacked_layout = required_width > max(0, effective_width - 2)
        else:
            # Conservative fallback during initial mount before regions settle.
            stacked_layout = effective_width < 88

        if stacked_layout:
            self.add_class("compact-layout")
        else:
            self.remove_class("compact-layout")

        _mode_log(
            "layout decision: "
            f"compact_labels={compact_labels} full_required={full_required} "
            f"required_width={required_width} utilization={utilization:.3f} "
            f"stacked_layout={stacked_layout} has_compact_class={self.has_class('compact-layout')}",
        )

    def _apply_compact_labels(self, compact_labels: bool) -> None:
        """Apply compact/full labels across toggles and dependent buttons."""
        for toggle in (
            self._plan_toggle,
            self._agent_toggle,
            self._coordination_toggle,
            self._refinement_toggle,
            self._persona_toggle,
        ):
            if toggle:
                toggle.set_compact(compact_labels)

        if self._subtasks_btn:
            self._subtasks_btn.label = "Tasks" if compact_labels else "Subtasks"
        if self._override_btn:
            self._override_btn.label = "Override" if compact_labels else "Override [Ctrl+O]"

    def _measure_control_width(self) -> int:
        """Estimate total width of visible interactive controls."""
        controls = (
            self._plan_toggle,
            self._agent_toggle,
            self._refinement_toggle,
            self._coordination_toggle,
            self._persona_toggle,
            self._subtasks_btn,
            self._plan_settings_btn,
            self._mode_help_btn,
            self._override_btn,
        )

        total = 0
        visible_controls = 0
        for control in controls:
            if control is None:
                continue
            if control.has_class("hidden"):
                continue
            visible_controls += 1
            if isinstance(control, ModeToggle):
                total += len(str(control.render()))
            elif isinstance(control, Button):
                total += len(str(control.label)) + 4
            elif control.region.width > 0:
                total += control.region.width
            else:
                total += 8

        # Account for inter-control spacing (toggle/button margin and separator gaps).
        return total + max(0, visible_controls - 1)

    def watch_override_available(self, available: bool) -> None:
        """React to override availability changes."""
        if self._override_btn:
            if available:
                self._override_btn.remove_class("hidden")
            else:
                self._override_btn.add_class("hidden")
        self.call_after_refresh(self._refresh_responsive_labels)

    def set_plan_mode(self, mode: str, plan_info: str = "") -> None:
        """Set the plan mode state.

        Args:
            mode: "normal", "plan", "execute", or "analysis".
            plan_info: Optional plan info text (shown in execute mode).
        """
        if self._plan_toggle:
            self._plan_toggle.set_state(mode)
        if self._plan_info:
            if mode == "execute" and plan_info:
                self._plan_info.update(f"📂 {plan_info}")
            else:
                self._plan_info.update("")

        # Show/hide plan settings button based on mode
        if self._plan_settings_btn:
            if mode != "normal":
                self._plan_settings_btn.remove_class("hidden")
            else:
                self._plan_settings_btn.add_class("hidden")
        self.call_after_refresh(self._refresh_responsive_labels)

    def set_agent_mode(self, mode: str) -> None:
        """Set the agent mode state.

        Args:
            mode: "multi" or "single".
        """
        if self._agent_toggle:
            self._agent_toggle.set_state(mode)

    def set_refinement_mode(self, enabled: bool) -> None:
        """Set the refinement mode state.

        Args:
            enabled: True for "on", False for "off".
        """
        if self._refinement_toggle:
            self._refinement_toggle.set_state("on" if enabled else "off")

    def set_coordination_mode(self, mode: str) -> None:
        """Set the coordination mode state.

        Args:
            mode: "parallel" or "decomposition".
        """
        if self._coordination_toggle:
            self._coordination_toggle.set_state(mode)
        self._update_coordination_aux_controls(mode)

    def set_coordination_enabled(self, enabled: bool) -> None:
        """Enable/disable coordination toggle interaction.

        Used to prevent unsupported combinations (e.g., decomposition in single-agent mode).
        """
        if self._coordination_toggle:
            self._coordination_toggle.set_enabled(enabled)
        self.call_after_refresh(self._refresh_responsive_labels)

    def set_parallel_personas_enabled(self, enabled: bool, diversity_mode: str = "perspective") -> None:
        """Set the parallel persona toggle state.

        Args:
            enabled: Whether personas are enabled.
            diversity_mode: The diversity mode to set when enabled ("perspective", "implementation", "methodology").
        """
        if self._persona_toggle:
            if enabled:
                state = diversity_mode if diversity_mode in ("perspective", "implementation", "methodology") else "perspective"
            else:
                state = "off"
            self._persona_toggle.set_state(state)

    def set_skills_available(self, available: bool) -> None:
        """Compatibility no-op: skills are no longer a mode-bar control."""
        del available

    def _update_coordination_aux_controls(self, mode: str) -> None:
        """Update controls that depend on coordination mode."""
        if not self._subtasks_btn:
            pass
        elif mode == "decomposition":
            self._subtasks_btn.remove_class("hidden")
        else:
            self._subtasks_btn.add_class("hidden")

        if self._persona_toggle:
            if mode == "parallel":
                self._persona_toggle.remove_class("hidden")
            else:
                self._persona_toggle.add_class("hidden")
        self.call_after_refresh(self._refresh_responsive_labels)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all mode toggles.

        Args:
            enabled: True to enable all toggles, False to disable.
        """
        if self._plan_toggle:
            self._plan_toggle.set_enabled(enabled)
        if self._agent_toggle:
            self._agent_toggle.set_enabled(enabled)
        if self._coordination_toggle:
            self._coordination_toggle.set_enabled(enabled)
        if self._refinement_toggle:
            self._refinement_toggle.set_enabled(enabled)
        if self._persona_toggle:
            self._persona_toggle.set_enabled(enabled)
        if self._subtasks_btn:
            self._subtasks_btn.disabled = not enabled

    def get_plan_mode(self) -> str:
        """Get current plan mode."""
        return self._plan_toggle.get_state() if self._plan_toggle else "normal"

    def get_agent_mode(self) -> str:
        """Get current agent mode."""
        return self._agent_toggle.get_state() if self._agent_toggle else "multi"

    def get_coordination_mode(self) -> str:
        """Get current coordination mode."""
        return self._coordination_toggle.get_state() if self._coordination_toggle else "parallel"

    def get_refinement_enabled(self) -> bool:
        """Get current refinement mode."""
        return self._refinement_toggle.get_state() == "on" if self._refinement_toggle else True

    def get_parallel_personas_enabled(self) -> bool:
        """Get current parallel persona toggle state (True if any mode is active)."""
        if not self._persona_toggle:
            return False
        return self._persona_toggle.get_state() != "off"

    def get_persona_diversity_mode(self) -> str:
        """Get current persona diversity mode."""
        if not self._persona_toggle:
            return "perspective"
        state = self._persona_toggle.get_state()
        return state if state != "off" else "perspective"

    def set_plan_status(self, status: str) -> None:
        """Set the plan status text shown on the right side.

        Args:
            status: Status text to display, or empty to hide.
        """
        if self._plan_status:
            if status:
                self._plan_status.update(status)
                self._plan_status.remove_class("hidden")
            else:
                self._plan_status.update("")
                self._plan_status.add_class("hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "override_btn":
            _mode_log("ModeBar: Override button pressed")
            self.post_message(OverrideRequested())
        elif event.button.id == "plan_settings_btn":
            _mode_log("ModeBar: Plan settings button pressed")
            self.post_message(PlanSettingsClicked())
        elif event.button.id == "mode_help_btn":
            _mode_log("ModeBar: Help button pressed")
            self.post_message(ModeHelpClicked())
        elif event.button.id == "subtasks_btn":
            _mode_log("ModeBar: Subtasks button pressed")
            self.post_message(SubtasksClicked())

    def on_mode_changed(self, event: ModeChanged) -> None:
        """Let mode change messages bubble to parent."""
        _mode_log(f"ModeBar.on_mode_changed: {event.mode_type}={event.value}")
        if event.mode_type == "coordination":
            self._update_coordination_aux_controls(event.value)
        # Don't stop - let it bubble to TextualApp
