"""Coordination-related modals: Vote results, Orchestrator events, Coordination table, Agent selector."""

from typing import Any

try:
    from textual.app import ComposeResult
    from textual.containers import Container
    from textual.widgets import Button, Label, ListItem, ListView, Static, TextArea

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal


class VoteResultsModal(BaseModal):
    """Modal to display vote results and distribution."""

    def __init__(
        self,
        results_text: str,
        vote_counts: dict[str, int] | None = None,
        votes: list[dict[str, Any]] | None = None,
    ):
        super().__init__()
        self.results_text = results_text
        self.vote_counts = vote_counts or {}
        self.votes = votes or []

    def _render_vote_distribution(self) -> str:
        """Render ASCII bar chart of vote distribution."""
        if not self.vote_counts:
            return ""

        # Only show agents with votes > 0
        non_zero = {k: v for k, v in self.vote_counts.items() if v > 0}
        if not non_zero:
            return ""

        max_votes = max(non_zero.values())
        total = sum(non_zero.values())

        lines = ["[bold cyan]Vote Distribution[/]", "─" * 45]

        for agent, count in sorted(non_zero.items(), key=lambda x: -x[1]):
            bar_width = int((count / max_votes) * 20) if max_votes > 0 else 0
            bar = "█" * bar_width + "░" * (20 - bar_width)
            pct = (count / total * 100) if total > 0 else 0
            prefix = "🏆 " if count == max_votes else "   "
            lines.append(f"{prefix}{agent[:12]:12} {bar} {count} ({pct:.0f}%)")

        lines.append("")
        return "\n".join(lines)

    def _render_vote_details(self) -> str:
        """Render detailed vote breakdown with voter → target."""
        if not self.votes:
            return ""

        lines = ["[bold cyan]Vote Details[/]", "─" * 45]

        for i, vote in enumerate(self.votes, 1):
            voter = vote.get("voter", "?")[:12]
            target = vote.get("voted_for", "?")[:12]
            reason = vote.get("reason", "")[:40]
            lines.append(f"  {i}. [dim]{voter}[/] → [bold]{target}[/]")
            if reason:
                lines.append(f"     [italic dim]{reason}[/]")

        lines.append("")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        # Build combined content
        distribution = self._render_vote_distribution()
        details = self._render_vote_details()

        # Combine distribution, details, and original text
        combined_parts = []
        if distribution:
            combined_parts.append(distribution)
        if details:
            combined_parts.append(details)
        if self.results_text:
            combined_parts.append("[bold cyan]Vote Summary[/]\n" + "─" * 45 + "\n" + self.results_text)

        full_content = "\n".join(combined_parts) if combined_parts else "No votes recorded."

        with Container(id="vote_results_container"):
            yield Label("🗳️ Voting Results", id="vote_header")
            yield Static(full_content, id="vote_results_content", markup=True)
            yield Button("Close (ESC)", id="close_vote_button")


class OrchestratorEventsModal(BaseModal):
    """Modal to display orchestrator events log."""

    def __init__(self, events: list[str]):
        super().__init__()
        self.events = events

    def compose(self) -> ComposeResult:
        content = "\n".join(self.events) if self.events else "No orchestrator events yet."
        with Container(id="orchestrator_events_container"):
            yield Label("📋 Orchestrator Events", id="orchestrator_events_header")
            yield TextArea(content, id="orchestrator_events_content", read_only=True)
            yield Button("Close (ESC)", id="close_orchestrator_events_button")


class CoordinationTableModal(BaseModal):
    """Modal to display coordination table."""

    def __init__(self, table_content: str):
        super().__init__()
        self.table_content = table_content

    def compose(self) -> ComposeResult:
        with Container(id="coordination_table_container"):
            yield Label("📊 Coordination Table", id="coordination_table_header")
            yield TextArea(self.table_content, id="coordination_table_content", read_only=True)
            yield Button("Close (ESC)", id="close_coordination_table_button")


class AgentSelectorModal(BaseModal):
    """Modal for selecting an agent from a list."""

    def __init__(self, agent_ids: list[str], current_agent_id: str | None = None):
        super().__init__()
        self.agent_ids = agent_ids
        self.current_agent_id = current_agent_id
        self.selected_agent: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="agent_selector_container"):
            yield Label("🔀 Select Agent", id="agent_selector_header")
            yield Label("Choose an agent to view:", id="agent_selector_hint")
            yield ListView(
                *[
                    ListItem(
                        Label(f"{'→ ' if aid == self.current_agent_id else '  '}{aid}"),
                        id=f"agent_item_{aid}",
                    )
                    for aid in self.agent_ids
                ],
                id="agent_list",
            )
            yield Button("Close (ESC)", id="close_agent_selector_button")

    def on_list_view_selected(self, event) -> None:
        """Handle agent selection."""
        if event.item and event.item.id:
            agent_id = event.item.id.replace("agent_item_", "")
            if agent_id in self.agent_ids:
                self.selected_agent = agent_id
                self.dismiss(agent_id)
