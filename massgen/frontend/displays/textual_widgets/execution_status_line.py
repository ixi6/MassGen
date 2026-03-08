"""
Execution Status Line Widget

Phase 13.2: Multi-agent status line showing activity across all agents.
Displays a compact, centered view with pulsing dots for working agents.
"""

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class ExecutionStatusLine(Widget):
    """Multi-agent status line showing activity across all agents.

    Design (centered, casual):
    ```
                    A ✓   B ...   C ✓
    ```

    Working agents show "..." which pulses. Done agents show "✓".
    This sits at the bottom of the main content, above the mode bar.
    """

    # Agent colors matching the theme (same as $agent-1 through $agent-8)
    AGENT_COLORS = [
        "#58a6ff",  # Blue (agent 1)
        "#3fb950",  # Green (agent 2)
        "#a371f7",  # Purple (agent 3)
        "#f0883e",  # Orange (agent 4)
        "#39c5cf",  # Cyan (agent 5)
        "#db61a2",  # Pink (agent 6)
        "#d29922",  # Yellow (agent 7)
        "#f85149",  # Red (agent 8)
    ]

    # Pulse state for animation
    _pulse_frame = reactive(0)

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        agent_ids: list[str],
        focused_agent: str = "",
        id: str | None = None,
    ) -> None:
        """Initialize the execution status line.

        Args:
            agent_ids: List of agent IDs to display
            focused_agent: Initially focused agent ID
            id: Widget ID
        """
        super().__init__(id=id)
        self._agent_ids = agent_ids
        self._focused_agent = focused_agent
        self._agent_states: dict[str, str] = {aid: "idle" for aid in agent_ids}
        self._pulse_timer = None

    def on_mount(self) -> None:
        """Start the pulse animation timer."""
        self._pulse_timer = self.set_interval(0.3, self._advance_pulse)

    def _advance_pulse(self) -> None:
        """Advance the pulse animation frame."""
        self._pulse_frame = (self._pulse_frame + 1) % 12

    def watch__pulse_frame(self, frame: int) -> None:
        """Refresh display when pulse frame changes."""
        # Only refresh if any agent is working
        if any(s in ("working", "streaming", "thinking", "tool_use") for s in self._agent_states.values()):
            self.refresh()

    def set_focused_agent(self, agent_id: str) -> None:
        """Set which agent is currently focused.

        Args:
            agent_id: Agent ID to focus
        """
        self._focused_agent = agent_id
        self.refresh()

    def set_agent_state(self, agent_id: str, state: str, tool_name: str = "") -> None:
        """Set the state for an agent.

        Args:
            agent_id: Agent ID
            state: State name. Valid states:
                - idle: Agent is idle (dim circle "○")
                - working/streaming/thinking/tool_use: Agent is actively processing (pulsing dots)
                - voted: Agent has voted, waiting for consensus (green "✓")
                - done: Agent finished final presentation (dim "✓")
                - cancelled: Agent was aborted/cancelled (yellow "✗")
                - error: Agent encountered an error (red "✗")
            tool_name: Optional tool name when state is tool_use
        """
        if agent_id in self._agent_states:
            self._agent_states[agent_id] = state
            self.refresh()

    def _get_agent_label(self, agent_id: str, index: int) -> str:
        """Extract a short label from agent_id.

        Examples:
            agent_a -> A
            agent_b -> B
            agent_1 -> 1
            my_agent -> M
        """
        # Try to get suffix after underscore (e.g., "a" from "agent_a")
        if "_" in agent_id:
            suffix = agent_id.split("_")[-1]
            if suffix:
                return suffix[0].upper()
        # Fallback to index-based letter
        return chr(ord("A") + index)

    def _get_agent_color(self, index: int) -> str:
        """Get the color for an agent based on its index.

        Args:
            index: Agent index (0-based)

        Returns:
            Hex color string
        """
        return self.AGENT_COLORS[index % len(self.AGENT_COLORS)]

    def render(self) -> Text:
        """Render the status line showing all agents' states."""
        text = Text()

        # Opening border
        text.append("╭ ", style="dim")

        # Organic 12-frame wave animation: breathing wave with bullet point
        pulse_patterns = [
            "   ",
            ".  ",
            ".. ",
            "...",
            "•..",
            ".•.",
            "..•",
            "...",
            ".. ",
            ".  ",
            "   ",
            "   ",
        ]
        pulse_dots = pulse_patterns[self._pulse_frame]

        for i, agent_id in enumerate(self._agent_ids):
            if i > 0:
                text.append("   ", style="dim")  # Spacing between agents

            # Get short agent label and color
            label = self._get_agent_label(agent_id, i)
            agent_color = self._get_agent_color(i)

            # Check if focused
            is_focused = agent_id == self._focused_agent
            state = self._agent_states.get(agent_id, "idle")

            # Label style - use agent color, focused is bold
            if is_focused:
                label_style = f"bold {agent_color}"
            else:
                label_style = f"dim {agent_color}"

            text.append(label, style=label_style)
            text.append(" ", style="")

            # State indicator - also use agent color for working state
            if state in ("working", "streaming", "thinking", "tool_use"):
                # Pulsing dots for working states - use agent color
                text.append(pulse_dots, style=f"{agent_color} bold")
            elif state in ("voted", "stopped"):
                # Green checkmark for voted/stopped (waiting for consensus/subtask done)
                text.append("✓  ", style="green")
            elif state == "done":
                # Dim checkmark for done (final presentation in progress)
                text.append("✓  ", style="dim")
            elif state == "cancelled":
                # X for cancelled (yellow)
                text.append("✗  ", style="yellow")
            elif state == "error":
                # X for error (red)
                text.append("✗  ", style="red")
            else:
                # Dim dot for idle
                text.append("○  ", style="dim")

        # Closing border (with space to avoid overlap with dots)
        text.append(" ╮", style="dim")

        return text
