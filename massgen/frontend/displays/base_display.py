"""
Base Display Interface for MassGen Coordination

Defines the interface that all display implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseDisplay(ABC):
    """Abstract base class for MassGen coordination displays."""

    def __init__(self, agent_ids: list[str], **kwargs):
        """Initialize display with agent IDs and configuration."""
        self.agent_ids = agent_ids
        self.agent_outputs = {agent_id: [] for agent_id in agent_ids}
        self.agent_status = {agent_id: "waiting" for agent_id in agent_ids}
        self.orchestrator_events = []
        self.config = kwargs

    @abstractmethod
    def initialize(self, question: str, log_filename: str | None = None):
        """Initialize the display with question and optional log file."""

    @abstractmethod
    def update_agent_content(
        self,
        agent_id: str,
        content: str,
        content_type: str = "thinking",
        tool_call_id: str | None = None,
    ):
        """Update content for a specific agent.

        Args:
            agent_id: The agent whose content to update
            content: The content to add/update
            content_type: Type of content ("thinking", "tool", "status")
            tool_call_id: Optional unique ID for tool calls (enables tracking across events)
        """

    @abstractmethod
    def update_agent_status(self, agent_id: str, status: str):
        """Update status for a specific agent.

        Args:
            agent_id: The agent whose status to update
            status: New status ("waiting", "working", "completed")
        """

    def update_timeout_status(self, agent_id: str, timeout_state: dict[str, Any]) -> None:
        """Update timeout display for an agent.

        Called periodically during coordination to update timeout countdown.

        Args:
            agent_id: The agent whose timeout status to update
            timeout_state: Dictionary containing timeout state from orchestrator.get_agent_timeout_state():
                - round_number: Current coordination round
                - round_start_time: When current round started
                - active_timeout: Soft timeout for current round type
                - grace_seconds: Grace period before hard block
                - elapsed: Seconds elapsed since round start
                - remaining_soft: Seconds until soft timeout
                - remaining_hard: Seconds until hard block
                - soft_timeout_fired: Whether soft timeout warning was injected
                - is_hard_blocked: Whether hard timeout is active
        """
        pass  # Override in subclasses

    def update_hook_execution(
        self,
        agent_id: str,
        tool_call_id: str | None,
        hook_info: dict[str, Any],
    ) -> None:
        """Update display with hook execution information.

        Called after hooks execute to show pre/post hook activity on tool cards.

        Args:
            agent_id: The agent whose tool call has hooks
            tool_call_id: Optional ID of the tool call this hook is attached to
            hook_info: Dictionary containing hook execution info:
                - hook_name: Name of the hook
                - hook_type: "pre" or "post"
                - decision: "allow", "deny", "error", etc.
                - reason: Reason for the decision (if any)
                - execution_time_ms: How long the hook took
                - injection_preview: Preview of injected content (if any)
        """
        pass  # Override in subclasses

    @abstractmethod
    def add_orchestrator_event(self, event: str):
        """Add an orchestrator coordination event.

        Args:
            event: The coordination event message
        """

    @abstractmethod
    def show_final_answer(self, answer: str, vote_results=None, selected_agent=None):
        """Display the final coordinated answer.

        Args:
            answer: The final coordinated answer
            vote_results: Dictionary of vote results (optional)
            selected_agent: The selected agent (optional)
        """

    @abstractmethod
    def show_post_evaluation_content(self, content: str, agent_id: str):
        """Display post-evaluation streaming content.

        Args:
            content: Post-evaluation content from the agent
            agent_id: The agent performing the evaluation
        """

    @abstractmethod
    def show_restart_banner(self, reason: str, instructions: str, attempt: int, max_attempts: int):
        """Display restart decision banner.

        Args:
            reason: Why the restart was triggered
            instructions: Instructions for the next attempt
            attempt: Next attempt number
            max_attempts: Maximum attempts allowed
        """

    @abstractmethod
    def show_restart_context_panel(self, reason: str, instructions: str):
        """Display restart context panel at top of UI (for attempt 2+).

        Args:
            reason: Why the previous attempt restarted
            instructions: Instructions for this attempt
        """

    def show_agent_restart(self, agent_id: str, round_num: int):
        """Notify that a specific agent is starting a new round.

        This is called when an agent restarts due to new context from other agents.
        The display should show a fresh view for this agent.

        Args:
            agent_id: The agent that is restarting
            round_num: The new round number for this agent
        """
        pass  # Default implementation does nothing

    def show_final_presentation_start(self, agent_id: str, vote_counts: dict[str, int] | None = None, answer_labels: dict[str, str] | None = None):
        """Notify that the final presentation phase is starting.

        This is called when the winning agent begins their final presentation.
        The display should show a fresh view with a distinct banner.

        Args:
            agent_id: The winning agent presenting the final answer
            vote_counts: Optional dict of {agent_id: vote_count} for vote summary display
            answer_labels: Optional dict of {agent_id: label} for display (e.g., {"agent1": "A1.1"})
        """
        pass  # Default implementation does nothing

    @abstractmethod
    def cleanup(self):
        """Clean up display resources."""

    def get_agent_content(self, agent_id: str) -> list[str]:
        """Get all content for a specific agent."""
        return self.agent_outputs.get(agent_id, [])

    def get_agent_status(self, agent_id: str) -> str:
        """Get current status for a specific agent."""
        return self.agent_status.get(agent_id, "unknown")

    def get_orchestrator_events(self) -> list[str]:
        """Get all orchestrator events."""
        return self.orchestrator_events.copy()

    def process_reasoning_content(self, chunk_type: str, content: str, source: str) -> str:
        """Process reasoning content and add prefixes as needed.

        Args:
            chunk_type: Type of the chunk (e.g., "reasoning_summary")
            content: The content to process
            source: The source agent/component

        Returns:
            Processed content with prefix if needed
        """
        if chunk_type == "reasoning":
            # Track if we're in an active reasoning for this source
            reasoning_active_key = f"_reasoning_active_{source}"

            if not hasattr(self, reasoning_active_key) or not getattr(self, reasoning_active_key, False):
                # Start of new reasoning - add prefix and mark as active
                setattr(self, reasoning_active_key, True)
                return f"🧠 [Reasoning Started]\n{content}\n"
            else:
                # Continuing existing reasoning - no prefix
                return content

        elif chunk_type == "reasoning_done":
            # End of reasoning - reset flag
            reasoning_active_key = f"_reasoning_active_{source}"
            if hasattr(self, reasoning_active_key):
                setattr(self, reasoning_active_key, False)
            return "\n🧠 [Reasoning Complete]\n"

        elif chunk_type == "reasoning_summary":
            # Track if we're in an active summary for this source
            summary_active_key = f"_summary_active_{source}"

            if not hasattr(self, summary_active_key) or not getattr(self, summary_active_key, False):
                # Start of new summary - add prefix and mark as active
                setattr(self, summary_active_key, True)
                return f"📋 [Reasoning Summary]\n{content}\n"
            else:
                # Continuing existing summary - no prefix
                return content

        elif chunk_type == "reasoning_summary_done":
            # End of reasoning summary - reset flag
            summary_active_key = f"_summary_active_{source}"
            if hasattr(self, summary_active_key):
                setattr(self, summary_active_key, False)

        return content
