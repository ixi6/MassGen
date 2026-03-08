"""
Session Info Panel Widget for MassGen TUI.

Displays aggregated session statistics in the header area.
"""

import logging
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

logger = logging.getLogger(__name__)


class SessionInfoPanel(Widget):
    """Aggregated session stats display.

    Design:
    ```
    ┌─ Session ──────────────────────────────────────────────────────────────┐
    │  Turn 2 of 5  •  1m 23s elapsed  •  ~$0.02 cost  •  12.4k tokens used │
    └────────────────────────────────────────────────────────────────────────┘
    ```
    """

    DEFAULT_CSS = """
    SessionInfoPanel {
        width: 100%;
        height: 1;
        background: $surface;
        border: solid $primary-darken-3;
        border-title-color: $text-muted;
        padding: 0 1;
        content-align: center middle;
    }

    SessionInfoPanel.hidden {
        display: none;
    }

    SessionInfoPanel #session_content {
        width: auto;
        height: 1;
        text-align: center;
    }
    """

    # Reactive attributes
    current_turn: reactive[int] = reactive(0)
    max_turns: reactive[int] = reactive(0)
    elapsed_seconds: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)
    total_tokens: reactive[int] = reactive(0)

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._start_time: float | None = None
        self._timer_handle = None
        self._agent_tokens: dict[str, int] = {}
        self._agent_costs: dict[str, float] = {}
        self.border_title = "Session"

    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), id="session_content")

    def on_mount(self) -> None:
        """Start the elapsed time timer."""
        self._timer_handle = self.set_interval(1.0, self._update_elapsed_time)

    def on_unmount(self) -> None:
        """Clean up timer."""
        if self._timer_handle:
            self._timer_handle.stop()

    def _update_elapsed_time(self) -> None:
        """Update the elapsed time counter."""
        if self._start_time is not None:
            self.elapsed_seconds = int(time.time() - self._start_time)
            self._update_display()

    def _build_content(self) -> Text:
        """Build the session info text."""
        text = Text()

        # Turn counter
        if self.max_turns > 0:
            text.append(f"Turn {self.current_turn} of {self.max_turns}", style="#e6edf3")
        else:
            text.append(f"Turn {self.current_turn}", style="#e6edf3")

        text.append("  •  ", style="#6e7681")

        # Elapsed time
        mins = self.elapsed_seconds // 60
        secs = self.elapsed_seconds % 60
        if mins > 0:
            text.append(f"{mins}m {secs}s elapsed", style="#8b949e")
        else:
            text.append(f"{secs}s elapsed", style="#8b949e")

        text.append("  •  ", style="#6e7681")

        # Cost
        if self.total_cost > 0:
            text.append(f"~${self.total_cost:.2f} cost", style="#8b949e")
        else:
            text.append("~$0.00 cost", style="#8b949e")

        text.append("  •  ", style="#6e7681")

        # Tokens
        if self.total_tokens >= 1000:
            text.append(f"{self.total_tokens / 1000:.1f}k tokens used", style="#8b949e")
        else:
            text.append(f"{self.total_tokens} tokens used", style="#8b949e")

        return text

    def _update_display(self) -> None:
        """Update the display content."""
        try:
            content = self.query_one("#session_content", Static)
            content.update(self._build_content())
        except Exception:
            pass

    def start_session(self, max_turns: int = 0) -> None:
        """Start tracking a new session.

        Args:
            max_turns: Maximum number of turns (0 for unlimited)
        """
        self._start_time = time.time()
        self.current_turn = 1
        self.max_turns = max_turns
        self.elapsed_seconds = 0
        self.total_cost = 0.0
        self.total_tokens = 0
        self._agent_tokens.clear()
        self._agent_costs.clear()
        self._update_display()

    def increment_turn(self) -> None:
        """Increment the turn counter."""
        self.current_turn += 1
        self._update_display()

    def set_turn(self, turn: int) -> None:
        """Set the current turn number.

        Args:
            turn: The current turn number
        """
        self.current_turn = turn
        self._update_display()

    def add_tokens(self, agent_id: str, tokens: int) -> None:
        """Add tokens for an agent.

        Args:
            agent_id: The agent ID
            tokens: Number of tokens to add
        """
        self._agent_tokens[agent_id] = self._agent_tokens.get(agent_id, 0) + tokens
        self.total_tokens = sum(self._agent_tokens.values())
        self._update_display()

    def set_agent_tokens(self, agent_id: str, tokens: int) -> None:
        """Set total tokens for an agent.

        Args:
            agent_id: The agent ID
            tokens: Total tokens for this agent
        """
        self._agent_tokens[agent_id] = tokens
        self.total_tokens = sum(self._agent_tokens.values())
        self._update_display()

    def add_cost(self, agent_id: str, cost: float) -> None:
        """Add cost for an agent.

        Args:
            agent_id: The agent ID
            cost: Cost to add in dollars
        """
        self._agent_costs[agent_id] = self._agent_costs.get(agent_id, 0.0) + cost
        self.total_cost = sum(self._agent_costs.values())
        self._update_display()

    def set_agent_cost(self, agent_id: str, cost: float) -> None:
        """Set total cost for an agent.

        Args:
            agent_id: The agent ID
            cost: Total cost for this agent in dollars
        """
        self._agent_costs[agent_id] = cost
        self.total_cost = sum(self._agent_costs.values())
        self._update_display()

    def reset(self) -> None:
        """Reset session statistics."""
        self._start_time = None
        self.current_turn = 0
        self.elapsed_seconds = 0
        self.total_cost = 0.0
        self.total_tokens = 0
        self._agent_tokens.clear()
        self._agent_costs.clear()
        self._update_display()

    def show(self) -> None:
        """Show the session info panel."""
        self.remove_class("hidden")

    def hide(self) -> None:
        """Hide the session info panel."""
        self.add_class("hidden")
