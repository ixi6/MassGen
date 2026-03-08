"""
Agent Tab Bar Widget for MassGen TUI.

Provides a horizontal tab bar for switching between agent panels.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class AgentTabChanged(Message):
    """Message emitted when the active agent tab changes."""

    def __init__(self, agent_id: str) -> None:
        """Initialize the message.

        Args:
            agent_id: The ID of the newly active agent.
        """
        self.agent_id = agent_id
        super().__init__()


class SessionInfoClicked(Message):
    """Message emitted when session info is clicked to show full prompt."""

    def __init__(
        self,
        turn: int,
        question: str,
        subtask: str | None = None,
        assignment_kind: str = "Subtask",
    ) -> None:
        """Initialize the message.

        Args:
            turn: Current turn number.
            question: Full question text.
            subtask: Optional subtask for the active agent.
            assignment_kind: Label for the assignment (e.g., "Subtask", "Persona").
        """
        self.turn = turn
        self.question = question
        self.subtask = subtask
        self.assignment_kind = assignment_kind
        super().__init__()


def _tab_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[TAB] {msg}")


class SessionInfoWidget(Static):
    """Clickable session info widget showing turn and question."""

    can_focus = True

    def __init__(
        self,
        turn: int = 1,
        question: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._turn = turn
        self._question = question
        self._assignment: str | None = None
        self._assignment_kind: str = "Subtask"

    def render(self) -> Text:
        """Render the session info."""
        text = Text()

        # Line 1: Assignment label (if present) + Turn number
        if self._assignment:
            st = self._assignment.replace("\n", " ").strip()
            if len(st) > 30:
                st = st[:27] + "…"
            text.append(st, style="bold #d2a8ff")
            text.append("  ", style="")

        text.append("◈ ", style="#58a6ff")
        text.append(f"Turn {self._turn}", style="#58a6ff")

        # Line 2: Truncated question (dimmed)
        if self._question and self._question != "Welcome! Type your question below...":
            text.append("\n")
            q = self._question.replace("\n", " ").strip()
            if len(q) > 40:
                q = q[:37] + "…"
            text.append(q, style="italic #6e7681")

        return text

    def update_info(self, turn: int, question: str) -> None:
        """Update turn and question."""
        self._turn = turn
        self._question = question
        self.refresh()

    def update_subtask(self, subtask: str | None) -> None:
        """Update the displayed subtask label."""
        self.update_assignment(subtask, kind="Subtask")

    def update_assignment(self, assignment: str | None, kind: str = "Subtask") -> None:
        """Update the displayed agent assignment label."""
        self._assignment = assignment
        self._assignment_kind = kind
        self.refresh()

    async def on_click(self) -> None:
        """Handle click to show full prompt."""
        self.post_message(
            SessionInfoClicked(
                self._turn,
                self._question,
                self._assignment,
                assignment_kind=self._assignment_kind,
            ),
        )


class AgentTab(Static):
    """Individual tab representing an agent.

    Displays agent ID with a status badge and supports click-to-select.
    Styles are defined in the TCSS theme files (dark.tcss, light.tcss).
    """

    # Enable clicking on the widget
    can_focus = True

    # Status icon mapping - minimal dot indicators for cleaner look
    STATUS_ICONS = {
        "waiting": "○",  # Empty dot - idle/waiting
        "working": "◉",  # Filled dot - active
        "voted": "✓",  # Green check - voted (waiting for consensus)
        "stopped": "✓",  # Green check - stopped in decomposition mode (subtask done)
        "done": "✓",  # Dim check - final presentation in progress
        "error": "✗",  # X mark - error
        "cancelled": "✗",  # X mark - cancelled (yellow when rendered)
        "winner": "👑",  # Crown - winner
    }

    # Map raw status strings to our icon states
    # "voted" = green checkmark (waiting for consensus)
    # "done" = dim checkmark (final presentation in progress)
    STATUS_MAP = {
        "working": "working",
        "thinking": "working",
        "streaming": "working",
        "processing": "working",
        "tool_call": "working",
        "mcp_tool_called": "working",
        "custom_tool_called": "working",
        "mcp_tool_response": "working",
        "custom_tool_response": "working",
        "voting": "working",
        "voted": "voted",  # Green checkmark - agent voted
        "stopped": "stopped",  # Green checkmark - agent stopped (decomposition mode)
        "waiting": "voted",  # Waiting for others after voting
        "complete": "voted",  # Finished, waiting for consensus
        "completed": "voted",
        "winner": "winner",  # Crown - winner of voting
        "done": "done",  # Dim checkmark - final presentation happening
        "error": "error",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "idle": "waiting",
    }

    def __init__(
        self,
        agent_id: str,
        key_index: int = 0,
        model_name: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the agent tab.

        Args:
            agent_id: The agent's identifier.
            key_index: Keyboard shortcut index (1-9, 0 for none).
            model_name: Model name to display as subtitle.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.agent_id = agent_id
        self.key_index = key_index
        self.model_name = model_name
        self._status = "waiting"
        self._disabled = False  # For single-agent mode
        self._pending_injection_count = 0

    def compose(self) -> ComposeResult:
        """No child widgets needed - we use renderable."""
        return []

    def render(self) -> str:
        """Render the tab content with two-line format: agent ID + model name."""
        # Map raw status to our icon states, default to working if unknown
        mapped_status = self.STATUS_MAP.get(self._status, "working")
        status_icon = self.STATUS_ICONS.get(mapped_status, "◉")
        pending_badge = f" Q{self._pending_injection_count}" if self._pending_injection_count > 0 else ""
        # Two-line display: agent name with status on first line, model on second
        if self.model_name:
            short_model = self._shorten_model_name(self.model_name)
            return f" {status_icon} {self.agent_id}{pending_badge}\n   {short_model} "
        return f" {status_icon} {self.agent_id}{pending_badge}\n "

    def _shorten_model_name(self, model: str) -> str:
        """Shorten model name for compact display."""
        # Remove common suffixes
        for suffix in ["-preview", "-latest", "-turbo"]:
            if model.endswith(suffix):
                model = model[: -len(suffix)]
                break
        # Truncate if still too long (max ~15 chars)
        if len(model) > 15:
            model = model[:12] + "…"
        return model

    def update_status(self, status: str) -> None:
        """Update the agent's status.

        Args:
            status: Raw status from orchestrator - gets mapped to display states.
        """
        # Remove old status classes
        self.remove_class(
            "status-waiting",
            "status-working",
            "status-voted",
            "status-stopped",
            "status-done",
            "status-error",
            "status-cancelled",
            "status-winner",
        )
        self._status = status
        # Map to display state for CSS class
        mapped = self.STATUS_MAP.get(status, "working")
        self.add_class(f"status-{mapped}")
        self.refresh()

    def set_active(self, active: bool) -> None:
        """Set whether this tab is the active (selected) tab.

        Args:
            active: True if this is the active tab.
        """
        if active:
            self.remove_class("inactive")
            self.add_class("active")
        else:
            self.remove_class("active")
            self.add_class("inactive")

    def set_disabled(self, disabled: bool) -> None:
        """Set whether this tab is disabled (greyed out in single-agent mode).

        Args:
            disabled: True to disable (grey out), False to enable.
        """
        self._disabled = disabled
        if disabled:
            self.add_class("disabled")
        else:
            self.remove_class("disabled")
        self.refresh()

    def is_disabled(self) -> bool:
        """Check if this tab is disabled."""
        return self._disabled

    def set_pending_injection_count(self, count: int) -> None:
        """Set queued runtime-injection count for this agent tab."""
        self._pending_injection_count = max(0, int(count))
        self.refresh()

    async def on_click(self) -> None:
        """Handle click to select this tab.

        In single-agent mode, clicking a disabled tab selects it as the new active agent.
        """
        _tab_log(f"AgentTab.on_click: {self.agent_id} (disabled={self._disabled})")
        # Always post the message - let parent handle single-agent selection logic
        self.post_message(AgentTabChanged(self.agent_id))


class AgentTabBar(Widget):
    """Horizontal tab bar for switching between agent panels.

    Displays a row of tabs, one per agent, with status badges.
    Right side shows session info (turn, question).
    Supports keyboard navigation (Tab, Shift+Tab, number keys).
    """

    DEFAULT_CSS = """
    AgentTabBar {
        height: 3;
        width: 100%;
        layout: horizontal;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }

    AgentTabBar #tab_container {
        width: auto;
        height: 100%;
        layout: horizontal;
    }

    AgentTabBar #session_info {
        width: 1fr;
        height: 100%;
        content-align: right middle;
        text-align: right;
        padding-right: 1;
    }
    """

    # Reactive attribute for the active agent
    active_agent: reactive[str] = reactive("")

    def __init__(
        self,
        agent_ids: list[str],
        agent_models: dict[str, str] | None = None,
        turn: int = 1,
        question: str = "",
        tab_id_prefix: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the tab bar.

        Args:
            agent_ids: List of agent IDs to display as tabs.
            agent_models: Optional mapping of agent IDs to model names.
            turn: Current turn number.
            question: Current question text.
            tab_id_prefix: Prefix for tab widget IDs to avoid conflicts.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._agent_ids = agent_ids
        self._agent_models = agent_models or {}
        self._tabs: dict[str, AgentTab] = {}
        self._turn = turn
        self._question = question
        self._tab_id_prefix = tab_id_prefix
        self._session_info_widget: SessionInfoWidget | None = None
        self._agent_assignments: dict[str, str] = {}
        self._assignment_kind: str = "Subtask"

    def compose(self) -> ComposeResult:
        """Create agent tabs and session info."""
        # Left side: agent tabs in a container
        with Horizontal(id="tab_container"):
            for idx, agent_id in enumerate(self._agent_ids):
                key_index = idx + 1 if idx < 9 else 0  # 1-9 for first 9 agents
                # Assign a color class based on agent index (cycles through 8 colors)
                color_class = f"agent-color-{(idx % 8) + 1}"
                model_name = self._agent_models.get(agent_id, "")
                tab_id = f"{self._tab_id_prefix}tab_{agent_id.replace(' ', '_').replace('.', '_')}"
                tab = AgentTab(
                    agent_id=agent_id,
                    key_index=key_index,
                    model_name=model_name,
                    id=tab_id,
                    classes=f"inactive {color_class}",
                )
                self._tabs[agent_id] = tab
                yield tab

        # Right side: session info (turn + question) - clickable to show full prompt
        self._session_info_widget = SessionInfoWidget(
            turn=self._turn,
            question=self._question,
            id="session_info",
        )
        yield self._session_info_widget

    def update_turn(self, turn: int) -> None:
        """Update the turn number display.

        Args:
            turn: The new turn number.
        """
        self._turn = turn
        self._update_session_info()

    def update_question(self, question: str) -> None:
        """Update the question display.

        Args:
            question: The new question text.
        """
        self._question = question
        self._update_session_info()

    def _update_session_info(self) -> None:
        """Refresh the session info widget."""
        if self._session_info_widget:
            self._session_info_widget.update_info(self._turn, self._question)

    def on_mount(self) -> None:
        """Set initial active agent after mounting."""
        if self._agent_ids and not self.active_agent:
            self.set_active(self._agent_ids[0])

    def set_active(self, agent_id: str) -> None:
        """Set the active (selected) agent tab.

        Args:
            agent_id: The agent to make active.
        """
        if agent_id not in self._tabs:
            return

        # Deactivate all tabs
        for tab in self._tabs.values():
            tab.set_active(False)

        # Activate the selected tab
        self._tabs[agent_id].set_active(True)
        self.active_agent = agent_id

        # Update assignment display for the newly active agent
        if self._session_info_widget and self._agent_assignments:
            self._session_info_widget.update_assignment(
                self._agent_assignments.get(agent_id),
                kind=self._assignment_kind,
            )

    def set_agent_subtasks(self, subtasks: dict[str, str]) -> None:
        """Set per-agent subtask assignments for decomposition mode.

        Args:
            subtasks: Mapping of agent_id to subtask description.
        """
        self._set_agent_assignments(subtasks, kind="Subtask")

    def set_agent_personas(self, personas: dict[str, str]) -> None:
        """Set per-agent persona assignments for parallel mode."""
        self._set_agent_assignments(personas, kind="Persona")

    def _set_agent_assignments(self, assignments: dict[str, str], kind: str) -> None:
        """Set and render per-agent assignment labels."""
        self._agent_assignments = assignments
        self._assignment_kind = kind
        # Update display for currently active agent
        if self._session_info_widget and self.active_agent:
            self._session_info_widget.update_assignment(
                assignments.get(self.active_agent),
                kind=kind,
            )

    def update_agent_status(self, agent_id: str, status: str) -> None:
        """Update the status badge for an agent.

        Args:
            agent_id: The agent to update.
            status: One of "waiting", "working", "streaming", "completed", "error", "winner".
        """
        if agent_id in self._tabs:
            self._tabs[agent_id].update_status(status)

    def set_pending_injection_counts(self, counts: dict[str, int]) -> None:
        """Update per-agent queued runtime-injection counts shown on tabs."""
        for agent_id, tab in self._tabs.items():
            tab.set_pending_injection_count(int(counts.get(agent_id, 0)))

    def set_winner(self, agent_id: str) -> None:
        """Mark an agent as winner, dimming all others.

        Args:
            agent_id: The winning agent's ID.
        """
        if agent_id not in self._tabs:
            return

        for aid, tab in self._tabs.items():
            if aid == agent_id:
                tab.update_status("winner")
                tab.remove_class("dimmed")
            else:
                tab.add_class("dimmed")

    def clear_winner(self) -> None:
        """Reset all tabs to normal state, removing winner/dimmed styling."""
        for tab in self._tabs.values():
            tab.remove_class("dimmed")
            # If the tab was a winner, set it to completed
            if tab._status == "winner":
                tab.update_status("completed")

    def update_agents(
        self,
        agent_ids: list[str],
        agent_models: dict[str, str] | None = None,
    ) -> None:
        """Update the tabs with a new set of agents.

        Dynamically replaces all tabs with new ones for the given agents.
        This is useful for subagent screens that need to show inner agents.

        Args:
            agent_ids: New list of agent IDs to display.
            agent_models: Optional mapping of agent IDs to model names.
        """
        # Skip if no change
        if agent_ids == self._agent_ids:
            return

        self._agent_ids = agent_ids
        self._agent_models = agent_models or {}

        # Find the tab container
        try:
            container = self.query_one("#tab_container")
        except Exception:
            return

        # Remove existing tabs
        for tab in list(self._tabs.values()):
            tab.remove()
        self._tabs.clear()

        # Create new tabs
        for idx, agent_id in enumerate(agent_ids):
            key_index = idx + 1 if idx < 9 else 0
            color_class = f"agent-color-{(idx % 8) + 1}"
            model_name = self._agent_models.get(agent_id, "")
            tab_id = f"{self._tab_id_prefix}tab_{agent_id.replace(' ', '_').replace('.', '_')}"
            tab = AgentTab(
                agent_id=agent_id,
                key_index=key_index,
                model_name=model_name,
                id=tab_id,
                classes=f"inactive {color_class}",
            )
            self._tabs[agent_id] = tab
            container.mount(tab)

        # Set first agent as active
        if agent_ids:
            self.set_active(agent_ids[0])

    def get_next_agent(self) -> str | None:
        """Get the next agent ID after the currently active one.

        Returns:
            The next agent ID, wrapping to first if at end.
        """
        if not self._agent_ids:
            return None
        try:
            idx = self._agent_ids.index(self.active_agent)
            next_idx = (idx + 1) % len(self._agent_ids)
            return self._agent_ids[next_idx]
        except ValueError:
            return self._agent_ids[0] if self._agent_ids else None

    def get_previous_agent(self) -> str | None:
        """Get the previous agent ID before the currently active one.

        Returns:
            The previous agent ID, wrapping to last if at start.
        """
        if not self._agent_ids:
            return None
        try:
            idx = self._agent_ids.index(self.active_agent)
            prev_idx = (idx - 1) % len(self._agent_ids)
            return self._agent_ids[prev_idx]
        except ValueError:
            return self._agent_ids[-1] if self._agent_ids else None

    def get_agent_by_index(self, index: int) -> str | None:
        """Get agent ID by 1-based index.

        Args:
            index: 1-based index (1-9 for keyboard shortcuts).

        Returns:
            The agent ID at that index, or None if invalid.
        """
        zero_index = index - 1
        if 0 <= zero_index < len(self._agent_ids):
            return self._agent_ids[zero_index]
        return None

    def set_single_agent_mode(self, enabled: bool, selected_agent: str | None = None) -> None:
        """Enable or disable single-agent mode with visual feedback.

        In single-agent mode, only the selected agent tab is enabled (not greyed out).
        All other tabs are disabled (greyed out) but can still be clicked to
        switch the selected agent.

        Args:
            enabled: True to enable single-agent mode, False for multi-agent mode.
            selected_agent: The agent ID to keep enabled (required when enabled=True).
        """
        _tab_log(f"AgentTabBar.set_single_agent_mode: enabled={enabled}, selected={selected_agent}")

        if enabled:
            if not selected_agent or selected_agent not in self._tabs:
                # Default to first agent if none specified
                selected_agent = self._agent_ids[0] if self._agent_ids else None

            for agent_id, tab in self._tabs.items():
                if agent_id == selected_agent:
                    tab.set_disabled(False)
                    tab.set_active(True)
                else:
                    tab.set_disabled(True)
                    tab.set_active(False)
        else:
            # Multi-agent mode: enable all tabs, keep current selection
            for tab in self._tabs.values():
                tab.set_disabled(False)

    def is_single_agent_mode(self) -> bool:
        """Check if any tabs are disabled (single-agent mode indicator)."""
        return any(tab.is_disabled() for tab in self._tabs.values())

    def get_enabled_agents(self) -> list[str]:
        """Get list of enabled (non-disabled) agent IDs.

        Returns:
            List of agent IDs that are not disabled.
        """
        return [agent_id for agent_id, tab in self._tabs.items() if not tab.is_disabled()]

    def on_agent_tab_changed(self, event: AgentTabChanged) -> None:
        """Handle tab click - let it bubble to parent.

        The parent (TextualApp) will handle the actual panel switching.
        We don't stop or re-post - just let it bubble naturally.
        """
        _tab_log(f"AgentTabBar.on_agent_tab_changed: {event.agent_id} - letting bubble to parent")
        # Don't stop or re-post - let the message bubble up naturally
        # The parent TextualApp will receive this via on_agent_tab_changed
