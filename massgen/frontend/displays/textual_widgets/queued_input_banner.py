"""
Queued Input Banner Widget for MassGen TUI.

Shows a banner above the input bar when human input has been queued
for injection during agent execution.
"""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class QueuedInputBanner(Static):
    """Banner showing queued human input pending injection.

    Displayed above the input bar when the user types input while
    agents are executing. Shows a preview of queued messages and
    indicates they will be injected after the next tool call.
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the queued input banner.

        Args:
            id: Optional widget ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._queued_messages: list[dict[str, Any]] = []
        self._pending_counts: dict[str, int] = {}

    def add_message(
        self,
        text: str,
        target_label: str = "all agents",
        source_label: str = "human",
    ) -> None:
        """Add a queued message and show/update the banner.

        Args:
            text: The queued human input text to add
            target_label: Human-friendly target description (e.g., "all agents", "agent_b")
            source_label: Runtime source label (e.g., "human", "parent")
        """
        self._queued_messages.append(
            {
                "id": None,
                "content": text,
                "target_label": target_label,
                "source_label": source_label,
                "pending_agents": [],
            },
        )
        self._rebuild()
        self.add_class("visible")

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        """Replace queued message entries with authoritative queue state."""
        normalized: list[dict[str, Any]] = []
        for message in messages:
            normalized.append(
                {
                    "id": message.get("id"),
                    "content": str(message.get("content", "")),
                    "target_label": str(message.get("target_label", "all agents")),
                    "source_label": str(message.get("source_label", message.get("source", "human"))),
                    "pending_agents": [str(aid) for aid in message.get("pending_agents", [])],
                },
            )
        self._queued_messages = normalized
        self._rebuild()
        if normalized:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def has_messages(self) -> bool:
        """Return True when queue banner has message rows to display."""
        return bool(self._queued_messages)

    def set_text(self, text: str) -> None:
        """Set a single queued message (replaces all). For backwards compatibility.

        Args:
            text: The queued human input text to display
        """
        self._queued_messages = [
            {
                "id": None,
                "content": text,
                "target_label": "all agents",
                "source_label": "human",
                "pending_agents": [],
            },
        ]
        self._rebuild()
        self.add_class("visible")

    def set_pending_counts(self, counts: dict[str, int]) -> None:
        """Update per-agent pending counts displayed in the banner."""
        self._pending_counts = {aid: int(count) for aid, count in counts.items() if int(count) > 0}
        self._rebuild()

    def clear(self) -> None:
        """Clear all messages and hide the banner."""
        self._queued_messages.clear()
        self._pending_counts.clear()
        self.update("")
        self.remove_class("visible")

    def _rebuild(self) -> None:
        """Rebuild the banner content."""
        if not self._queued_messages:
            self.update("")
            return

        def _compact_preview(raw_text: str, *, max_len: int) -> str:
            single_line = " ".join(raw_text.split())
            if len(single_line) <= max_len:
                return single_line
            return single_line[: max_len - 3] + "..."

        content = Text()
        count = len(self._queued_messages)
        pending_summary = ""
        if self._pending_counts:
            # Keep summary compact and deterministic.
            ordered = sorted(self._pending_counts.items(), key=lambda item: item[0])
            parts = [f"{aid}:{cnt}" for aid, cnt in ordered]
            pending_summary = f" | pending: {', '.join(parts)}"

        if count == 1:
            # Single message - show preview
            message = self._queued_messages[0]
            message_id = message.get("id")
            display_text = _compact_preview(str(message.get("content", "")), max_len=52)
            target_label = message.get("target_label", "all agents")
            source_label = str(message.get("source_label", "human"))
            pending_agents = [str(aid) for aid in message.get("pending_agents", [])]
            pending_agent_label = ",".join(pending_agents) if pending_agents else ""

            content.append("📝 ", style="bold yellow")
            content.append("Queued", style="bold")
            if message_id is not None:
                content.append(f" #{message_id}", style="bold")
            content.append(": ", style="bold")
            content.append(f'"{display_text}"', style="italic")
            content.append(f" (source: {source_label}, target: {target_label})", style="dim")
            if pending_agent_label:
                content.append(f" [pending: {pending_agent_label}]", style="dim")
            if pending_summary:
                content.append(pending_summary, style="dim")
        else:
            # Multiple messages - compact summary with latest entry preview.
            latest = self._queued_messages[-1]
            latest_target = str(latest.get("target_label", "all agents"))
            latest_source = str(latest.get("source_label", "human"))
            latest_id = latest.get("id")
            latest_preview = _compact_preview(str(latest.get("content", "")), max_len=44)
            latest_pending_agents = [str(aid) for aid in latest.get("pending_agents", [])]
            latest_pending_label = ",".join(latest_pending_agents) if latest_pending_agents else ""

            content.append("📝 ", style="bold yellow")
            content.append(f"{count} messages queued", style="bold")
            if pending_summary:
                content.append(pending_summary, style="dim")
            content.append(" | ", style="dim")
            if latest_id is not None:
                content.append(f"latest #{latest_id} ", style="dim")
            else:
                content.append("latest ", style="dim")
            content.append(f"[{latest_source} -> {latest_target}] ", style="dim")
            content.append(latest_preview, style="italic")
            if latest_pending_label:
                content.append(f" [pending: {latest_pending_label}]", style="dim")

        self.update(content)
