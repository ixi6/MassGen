"""
Phase Indicator Bar Widget for MassGen TUI.

Shows the coordination flow progress for multi-agent mode.
"""

import logging

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

logger = logging.getLogger(__name__)


class PhaseIndicatorBar(Widget):
    """Shows coordination flow progress for multi-agent mode.

    Design:
    ```
    ┌───────────────────────────────────────────────────────────────────────┐
    │   ✓ Initial Answer  →  ● Voting  →  ○ Consensus  →  ○ Presentation   │
    └───────────────────────────────────────────────────────────────────────┘
    ```

    Phases:
    - initial_answer: Agents generating initial answers
    - voting: Agents voting on answers
    - consensus: Reaching agreement
    - presentation: Final answer presentation
    """

    DEFAULT_CSS = """
    PhaseIndicatorBar {
        width: 100%;
        height: 1;
        background: $surface;
        border-bottom: solid $primary-darken-3;
        padding: 0 2;
        content-align: center middle;
    }

    PhaseIndicatorBar.hidden {
        display: none;
    }

    PhaseIndicatorBar #phase_content {
        width: auto;
        height: 1;
        text-align: center;
    }
    """

    # Phases in order
    PHASES = ["initial_answer", "voting", "consensus", "presentation"]

    PHASE_LABELS = {
        "initial_answer": "Initial Answer",
        "voting": "Voting",
        "consensus": "Consensus",
        "presentation": "Presentation",
    }

    # Reactive current phase
    current_phase: reactive[str] = reactive("initial_answer")

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._completed_phases: set = set()

    def compose(self) -> ComposeResult:
        yield Static(self._build_phase_display(), id="phase_content")

    def _build_phase_display(self) -> Text:
        """Build the phase indicator text with icons."""
        text = Text()
        text.append("  ")  # Left padding

        for i, phase in enumerate(self.PHASES):
            label = self.PHASE_LABELS[phase]

            if phase in self._completed_phases:
                # Completed phase
                icon = "✓"
                style = "#3a9d52"  # Green
            elif phase == self.current_phase:
                # Current phase
                icon = "●"
                style = "#5199d9"  # Blue
            else:
                # Future phase
                icon = "○"
                style = "#6e7681"  # Dim

            text.append(f"{icon} ", style=style)
            text.append(label, style=style)

            # Arrow separator (except for last phase)
            if i < len(self.PHASES) - 1:
                text.append("  →  ", style="#6e7681")

        text.append("  ")  # Right padding
        return text

    def set_phase(self, phase: str) -> None:
        """Set the current coordination phase.

        Args:
            phase: One of "initial_answer", "voting", "consensus", "presentation"
                   or workflow phases like "idle", "coordinating", "presenting"
        """
        # Map workflow phases to our internal phases
        phase_map = {
            "idle": "initial_answer",
            "coordinating": "voting",
            "presenting": "presentation",
        }

        mapped_phase = phase_map.get(phase, phase)

        if mapped_phase not in self.PHASES:
            logger.warning(f"Unknown phase: {phase}")
            return

        # Mark all phases before current as completed
        phase_index = self.PHASES.index(mapped_phase)
        self._completed_phases = set(self.PHASES[:phase_index])

        self.current_phase = mapped_phase
        self._update_display()

    def complete_phase(self, phase: str) -> None:
        """Mark a phase as completed.

        Args:
            phase: The phase to mark as completed
        """
        if phase in self.PHASES:
            self._completed_phases.add(phase)
            self._update_display()

    def reset(self) -> None:
        """Reset all phases to initial state."""
        self._completed_phases = set()
        self.current_phase = "initial_answer"
        self._update_display()

    def _update_display(self) -> None:
        """Update the phase display."""
        try:
            content = self.query_one("#phase_content", Static)
            content.update(self._build_phase_display())
        except Exception:
            pass

    def watch_current_phase(self, old_phase: str, new_phase: str) -> None:
        """React to phase changes."""
        self._update_display()

    def show(self) -> None:
        """Show the phase indicator (for multi-agent mode)."""
        self.remove_class("hidden")

    def hide(self) -> None:
        """Hide the phase indicator (for single-agent mode)."""
        self.add_class("hidden")
