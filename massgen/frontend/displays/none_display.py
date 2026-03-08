"""
None Display for MassGen Coordination

Silent display that suppresses all output. Used for programmatic API and LiteLLM.
"""

from .base_display import BaseDisplay


class NoneDisplay(BaseDisplay):
    """Silent display that produces no output."""

    def __init__(self, agent_ids, **kwargs):
        """Initialize none display."""
        super().__init__(agent_ids, **kwargs)

    def initialize(self, question: str, log_filename: str | None = None):
        """Initialize the display (no-op)."""

    def update_agent_content(
        self,
        agent_id: str,
        content: str,
        content_type: str = "thinking",
        tool_call_id: str | None = None,
    ):
        """Update content for a specific agent (no-op)."""
        if agent_id in self.agent_ids:
            self.agent_outputs[agent_id].append(content.strip())

    def update_agent_status(self, agent_id: str, status: str):
        """Update status for a specific agent (no-op)."""
        if agent_id in self.agent_ids:
            self.agent_status[agent_id] = status

    def add_orchestrator_event(self, event: str):
        """Add an orchestrator coordination event (no-op)."""
        self.orchestrator_events.append(event)

    def show_final_answer(self, answer: str, vote_results=None, selected_agent=None):
        """Display the final coordinated answer (no-op)."""

    def show_post_evaluation_content(self, content: str, agent_id: str):
        """Display post-evaluation streaming content (no-op)."""

    def show_restart_banner(self, reason: str, instructions: str, attempt: int, max_attempts: int):
        """Display restart decision banner (no-op)."""

    def show_restart_context_panel(self, reason: str, instructions: str):
        """Display restart context panel (no-op)."""

    def cleanup(self):
        """Clean up resources (no-op)."""
