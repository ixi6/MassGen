"""
Final Answer View Widget for MassGen TUI.

Displays the final answer in a full-panel view with metadata, action buttons,
and voting details. Used when user navigates to "Final Answer" via the view dropdown.
"""

import logging
import platform
import subprocess
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Button, Label, Markdown, Static

logger = logging.getLogger(__name__)


class FinalAnswerView(Vertical):
    """Full-panel view for displaying the final answer.

    Design:
    ```
    ─────────────────────────────────────────────────────────────────
                             Final Answer
    ─────────────────────────────────────────────────────────────────

    [Markdown-rendered final answer content]

    ─────────────────────────────────────────────────────────────────
    Consensus reached | Presented by Agent A | 3 rounds | 2/3 agreed
                        [Copy] [Workspace] [Voting Details]
    ─────────────────────────────────────────────────────────────────
                         Type below to continue...
    ```
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    class CopyRequested(Message):
        """Message emitted when copy button is clicked."""

        def __init__(self, content: str) -> None:
            self.content = content
            super().__init__()

    class WorkspaceRequested(Message):
        """Message emitted when workspace button is clicked."""

        def __init__(self, agent_id: str) -> None:
            self.agent_id = agent_id
            super().__init__()

    class VotingDetailsRequested(Message):
        """Message emitted when voting details button is clicked."""

        def __init__(self, vote_results: dict[str, Any]) -> None:
            self.vote_results = vote_results
            super().__init__()

    def __init__(
        self,
        agent_id: str = "",
        content: str = "",
        metadata: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """Initialize the FinalAnswerView.

        Args:
            agent_id: The agent ID that presented this answer
            content: The final answer text
            metadata: Optional metadata dict with keys:
                - winner: The winning agent ID
                - vote_counts: Dict of agent_id -> vote count
                - total_rounds: Number of rounds
                - agreement: Number of agents that agreed
                - total_agents: Total number of agents
        """
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self._content = content
        self._metadata = metadata or {}
        self.add_class("hidden")  # Start hidden

    def compose(self) -> ComposeResult:
        # Header with title
        with Vertical(id="final_header"):
            yield Static(
                "─" * 60 + "\n" "                      ✓ Final Answer\n" "─" * 60,
                id="final_header_title",
            )

        # Scrollable content area with markdown
        with ScrollableContainer(id="final_content_container"):
            yield Markdown(self._content, id="final_content")

        # Footer with metadata and buttons
        with Vertical(id="final_footer"):
            yield Static("─" * 60, classes="separator")
            yield Label(self._build_metadata_text(), id="final_metadata")
            with Horizontal(id="final_buttons"):
                yield Button("📋 Copy", id="copy_btn")
                yield Button("📂 Workspace", id="workspace_btn")
                yield Button("📊 Voting Details", id="voting_btn")
            yield Label("💬 Type below to continue the conversation", id="continue_hint")

    def _build_metadata_text(self) -> str:
        """Build the metadata line text."""
        parts = []

        # Consensus status
        parts.append("✓ Consensus reached")

        # Presenting agent
        winner = self._metadata.get("winner", self.agent_id)
        if winner:
            parts.append(f"Presented by {winner}")

        # Round count
        total_rounds = self._metadata.get("total_rounds")
        if total_rounds:
            parts.append(f"{total_rounds} round{'s' if total_rounds != 1 else ''}")

        # Agreement
        agreement = self._metadata.get("agreement")
        total_agents = self._metadata.get("total_agents")
        if agreement is not None and total_agents:
            parts.append(f"{agreement}/{total_agents} agreed")

        return " │ ".join(parts) if parts else ""

    def set_content(self, content: str) -> None:
        """Update the displayed content.

        Args:
            content: The new content to display
        """
        self._content = content
        try:
            md_widget = self.query_one("#final_content", Markdown)
            md_widget.update(content)
        except Exception:
            pass

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        """Update the metadata display.

        Args:
            metadata: The metadata dict
        """
        self._metadata = metadata
        try:
            label = self.query_one("#final_metadata", Label)
            label.update(self._build_metadata_text())
        except Exception:
            pass

    def show(self) -> None:
        """Show the final answer view."""
        self.remove_class("hidden")

    def hide(self) -> None:
        """Hide the final answer view."""
        self.add_class("hidden")

    def get_content(self) -> str:
        """Get the current content."""
        return self._content

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button_id = event.button.id

        if button_id == "copy_btn":
            self._copy_to_clipboard()
        elif button_id == "workspace_btn":
            self.post_message(self.WorkspaceRequested(self.agent_id))
        elif button_id == "voting_btn":
            self.post_message(self.VotingDetailsRequested(self._metadata))

    def _copy_to_clipboard(self) -> None:
        """Copy the content to the system clipboard."""
        try:
            system = platform.system()
            if system == "Darwin":
                process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                process.communicate(self._content.encode("utf-8"))
            elif system == "Windows":
                process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                process.communicate(self._content.encode("utf-8"))
            else:
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                )
                process.communicate(self._content.encode("utf-8"))

            # Notify success
            self.notify("Copied to clipboard", severity="information")
        except Exception as e:
            self.notify(f"Copy failed: {e}", severity="error")
