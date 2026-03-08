"""
Base TUI Layout Mixin for MassGen TUI.

Provides shared round-management and abstract timeline/ribbon access for TUI panels.
Both AgentPanel (main TUI) and SubagentPanel (subagent screen) inherit this mixin.

Usage:
    class AgentPanel(Container, BaseTUILayoutMixin):
        def _get_timeline(self) -> TimelineSection:
            return self.query_one("#my_timeline", TimelineSection)

        def _get_ribbon(self) -> Optional[AgentStatusRibbon]:
            return self.app._status_ribbon
"""

from abc import abstractmethod

from .content_handlers import ToolBatchTracker
from .shared import tui_log


class BaseTUILayoutMixin:
    """Mixin class providing round management and abstract accessors for TUI panels.

    Subclasses must implement:
    - _get_timeline(): Return the TimelineSection widget
    - _get_ribbon(): Return the AgentStatusRibbon widget (or None)

    State provided by mixin:
    - _current_round: Which round content is being received
    - _viewed_round: Which round is currently displayed
    - _batch_tracker: ToolBatchTracker instance (for reset on round change)
    - _context_by_round: Context sources per round
    """

    def init_content_pipeline(self) -> None:
        """Initialize the content pipeline state.

        Call this in __init__ after super().__init__().
        """
        # Content handlers (used by start_new_round / show_restart_separator)
        self._batch_tracker = ToolBatchTracker()

        # Round tracking
        self._current_round: int = 1
        self._viewed_round: int = 1

        # Context tracking per round
        self._context_by_round: dict[int, list[str]] = {}

    # -------------------------------------------------------------------------
    # Abstract methods - subclasses must implement
    # -------------------------------------------------------------------------

    @abstractmethod
    def _get_timeline(self):
        """Get the TimelineSection widget.

        Returns:
            TimelineSection: The timeline widget for content display
        """
        raise NotImplementedError

    @abstractmethod
    def _get_ribbon(self):
        """Get the AgentStatusRibbon widget (or None).

        Returns:
            Optional[AgentStatusRibbon]: The status ribbon widget, or None
        """
        raise NotImplementedError

    # -------------------------------------------------------------------------
    # Round management
    # -------------------------------------------------------------------------

    def start_new_round(
        self,
        round_number: int,
        is_context_reset: bool = False,
        defer_banner: bool = False,
    ) -> None:
        """Start a new round - update tracking and switch visibility.

        Args:
            round_number: The new round number
            is_context_reset: Whether this round started with a context reset
            defer_banner: If True, defer the round banner until first content
        """
        # Update round tracking
        self._current_round = round_number
        self._viewed_round = round_number

        try:
            timeline = self._get_timeline()
            if timeline is None:
                return
            timeline.switch_to_round(round_number)

            # Clear tools tracking for new round
            if hasattr(timeline, "clear_tools_tracking"):
                timeline.clear_tools_tracking()

            # Add (or defer) "Round X" banner
            if round_number >= 1:
                subtitle = "Restart" if round_number > 1 else None
                if is_context_reset:
                    subtitle = (subtitle or "") + " • Context cleared"
                if defer_banner and hasattr(timeline, "defer_round_banner"):
                    timeline.defer_round_banner(
                        round_number,
                        f"Round {round_number}",
                        subtitle if subtitle else None,
                    )
                else:
                    timeline.add_separator(
                        f"Round {round_number}",
                        round_number=round_number,
                        subtitle=subtitle if subtitle else None,
                    )
        except Exception as e:
            tui_log(f"start_new_round error: {e}")

        # Reset per-round state
        self._batch_tracker.reset()

        # Update ribbon if available
        self._update_ribbon_round(round_number, is_context_reset)

    def _update_ribbon_round(self, round_number: int, is_context_reset: bool = False) -> None:
        """Update the status ribbon with the new round number.

        Args:
            round_number: The round number
            is_context_reset: Whether this was a context reset
        """
        ribbon = self._get_ribbon()
        if ribbon is not None:
            try:
                # Get agent_id if available
                agent_id = getattr(self, "agent_id", None) or ""
                ribbon.set_round(agent_id, round_number, is_context_reset)
            except Exception:
                pass

    def show_restart_separator(self, attempt: int = 1, reason: str = "") -> None:
        """Handle restart - start new round.

        Args:
            attempt: The attempt/round number
            reason: Reason for restart
        """
        # Mark that non-tool content arrived
        self._batch_tracker.mark_content_arrived()
        self._batch_tracker.finalize_current_batch()

        # Determine if this was a context reset
        is_context_reset = "context" in reason.lower() or "reset" in reason.lower()

        # Start the new round
        self.start_new_round(attempt, is_context_reset)
