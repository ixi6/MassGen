"""
Injection Sub-Card Widget for MassGen TUI.

Provides collapsible sub-cards for displaying injection content
attached to tool cards. Injections show cross-agent context updates
and other hook-injected content.
"""

from datetime import datetime

from rich.text import Text
from textual.message import Message
from textual.widgets import Static


class InjectionSubCard(Static, can_focus=True):
    """Collapsible sub-card for displaying injection content within a tool card.

    Shows a collapsed preview by default, expandable to show full injection content.
    Used to display hook injections (pre or post tool) attached to their parent tool card.
    """

    # Enable mouse interaction
    ALLOW_SELECT = False

    # Message for click events
    class Clicked(Message):
        """Posted when the injection sub-card is clicked."""

        def __init__(self, subcard: "InjectionSubCard") -> None:
            self.subcard = subcard
            super().__init__()

    def __init__(
        self,
        hook_name: str,
        hook_type: str,  # "pre" or "post"
        content: str,
        preview: str | None = None,
        execution_time_ms: float | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the injection sub-card.

        Args:
            hook_name: Name of the hook that created this injection.
            hook_type: "pre" for pre-tool hooks, "post" for post-tool hooks.
            content: Full injection content.
            preview: Optional preview text (defaults to truncated content).
            execution_time_ms: How long the hook took to execute.
            id: Optional widget ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.hook_name = hook_name
        self.hook_type = hook_type
        self.content = content
        # Always generate our own preview from full content for cleaner display
        # The passed preview may contain decorative characters
        self.preview = self._generate_preview(content)
        self.execution_time_ms = execution_time_ms
        self.timestamp = datetime.now()
        self._expanded = False

    def _generate_preview(self, content: str, max_length: int = 80) -> str:
        """Generate a preview from the content.

        Extracts meaningful text from injection content, skipping decorative
        lines like '======' banners and extracting the core message.
        """
        # Split into lines and filter out decorative/empty lines
        lines = content.split("\n")
        meaningful_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty lines, separator lines, and pure decoration
            if not stripped:
                continue
            if stripped.startswith("=") and stripped.count("=") > 10:
                continue
            if stripped.startswith("-") and stripped.count("-") > 10:
                continue
            meaningful_lines.append(stripped)

        # Build preview from meaningful content
        if meaningful_lines:
            preview = " ".join(meaningful_lines)
        else:
            # Fallback: flatten everything
            preview = content.replace("\n", " ").strip()

        if len(preview) > max_length:
            return preview[:max_length] + "..."
        return preview

    @property
    def expanded(self) -> bool:
        """Whether the sub-card is expanded."""
        return self._expanded

    @expanded.setter
    def expanded(self, value: bool) -> None:
        """Set expanded state and update CSS classes."""
        self._expanded = value
        if value:
            self.add_class("expanded")
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")
            self.remove_class("expanded")
        self.refresh()

    def toggle(self) -> None:
        """Toggle the expanded/collapsed state."""
        self.expanded = not self.expanded

    def on_mount(self) -> None:
        """Set initial CSS class on mount."""
        self.add_class("collapsed")

    def on_click(self, event) -> None:
        """Handle click to toggle expand/collapse."""
        from massgen.logger_config import logger

        logger.info(f"[InjectionSubCard] CLICKED! hook={self.hook_name}, expanded_before={self._expanded}")
        event.stop()  # Prevent parent ToolCallCard from also handling this click
        self.toggle()
        logger.info(f"[InjectionSubCard] After toggle: expanded={self._expanded}")
        self.post_message(self.Clicked(self))

    def render(self) -> Text:
        """Render the sub-card content."""
        if self._expanded:
            return self._render_expanded()
        return self._render_collapsed()

    def _render_collapsed(self) -> Text:
        """Render collapsed single-line view."""
        # Icon based on hook type
        icon = "📥" if self.hook_type == "post" else "⚡"
        arrow = "▶"

        # Build the line
        result = Text()
        result.append(f"{arrow} ", style="dim")
        result.append(f"{icon} ", style="bold #d2a8ff")
        result.append(f"{self.hook_name}", style="bold #d2a8ff")
        result.append(": ", style="dim")
        result.append(self.preview, style="#c9b8e0")

        return result

    def _render_expanded(self) -> Text:
        """Render expanded full content view."""
        icon = "📥" if self.hook_type == "post" else "⚡"
        arrow = "▼"

        result = Text()

        # Header line
        result.append(f"{arrow} ", style="dim")
        result.append(f"{icon} ", style="bold #d2a8ff")
        result.append(f"{self.hook_name}", style="bold #d2a8ff")

        # Execution time if available
        if self.execution_time_ms is not None:
            result.append(f" ({self.execution_time_ms:.1f}ms)", style="dim")

        result.append("\n")

        # Content lines (limit to prevent huge displays)
        max_lines = 30
        content_lines = self.content.split("\n")

        for i, line in enumerate(content_lines[:max_lines]):
            result.append("  ", style="dim")
            result.append(line, style="#c9b8e0")
            if i < min(len(content_lines), max_lines) - 1:
                result.append("\n")

        # Truncation notice
        if len(content_lines) > max_lines:
            result.append("\n")
            result.append(
                f"  ... ({len(content_lines) - max_lines} more lines)",
                style="dim italic",
            )

        return result
