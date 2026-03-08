"""
Task Plan Modal Widget for MassGen TUI.

Full-screen modal overlay for viewing and interacting with the complete task plan.
"""

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class TaskPlanModal(ModalScreen[None]):
    """Modal screen showing full task plan details with rich formatting."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Status indicators
    STATUS_ICONS = {
        "completed": "✓",
        "in_progress": "●",
        "pending": "○",
        "blocked": "◌",
        "verified": "✔",
    }

    STATUS_COLORS = {
        "completed": "#7ee787",
        "in_progress": "#58a6ff",
        "pending": "#8b949e",
        "blocked": "#f85149",
        "verified": "#7ee787",
    }

    PRIORITY_COLORS = {
        "high": "#f85149",
        "medium": "#d29922",
        "low": "#8b949e",
    }

    def __init__(
        self,
        tasks: list[dict[str, Any]],
        focused_task_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        super().__init__()
        self.tasks = tasks or []
        self.focused_task_id = focused_task_id
        self.agent_id = agent_id

    def compose(self) -> ComposeResult:
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.get("status") in ("completed", "verified"))
        in_progress = sum(1 for t in self.tasks if t.get("status") == "in_progress")
        blocked = sum(1 for t in self.tasks if t.get("status") == "blocked")

        with Container():
            # Header section
            with Container(classes="modal-header"):
                with Container(classes="header-row"):
                    yield Static("Task Plan", classes="modal-title")
                    yield Static(self._build_stats(total, completed, in_progress, blocked), classes="modal-stats")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

                # Progress bar
                yield Static(self._build_progress_bar(total, completed, in_progress), classes="progress-bar")

            # Task list
            with ScrollableContainer(classes="modal-body"):
                for task in self.tasks:
                    yield self._build_task_widget(task)

            # Footer
            with Container(classes="modal-footer"):
                yield Button("Close (Esc)", variant="primary", classes="close-button", id="close_btn_footer")

    def _build_stats(self, total: int, completed: int, in_progress: int, blocked: int) -> Text:
        """Build stats display."""
        text = Text()
        text.append(f"{completed}", style="bold #7ee787")
        text.append(f"/{total}", style="#8b949e")
        if in_progress > 0:
            text.append(f"  ●{in_progress}", style="bold #58a6ff")
        if blocked > 0:
            text.append(f"  ◌{blocked}", style="#f85149")
        return text

    def _build_progress_bar(self, total: int, completed: int, in_progress: int) -> Text:
        """Build a visual progress bar."""
        if total == 0:
            return Text("─" * 60, style="dim")

        bar_width = 60
        completed_width = int((completed / total) * bar_width)
        in_progress_width = int((in_progress / total) * bar_width)
        remaining_width = bar_width - completed_width - in_progress_width

        text = Text()
        if completed_width > 0:
            text.append("█" * completed_width, style="#7ee787")
        if in_progress_width > 0:
            text.append("▓" * in_progress_width, style="#58a6ff")
        if remaining_width > 0:
            text.append("░" * remaining_width, style="#30363d")

        return text

    def _build_task_widget(self, task: dict[str, Any]) -> Static:
        """Build a task row widget."""
        task_id = task.get("id", "")
        is_focused = task_id == self.focused_task_id
        task.get("status", "pending")

        classes = "task-row"
        if is_focused:
            classes += " task-focused"

        return Static(self._build_task_content(task), classes=classes)

    def _build_task_content(self, task: dict[str, Any]) -> Text:
        """Build rich text content for a single task."""
        text = Text()

        task_id = task.get("id", "")
        is_focused = task_id == self.focused_task_id
        status = task.get("status", "pending")
        priority = task.get("priority", "medium")
        desc = task.get("description", "Untitled task")
        dependencies = task.get("dependencies", [])
        created_at = task.get("created_at")
        completed_at = task.get("completed_at")
        metadata = task.get("metadata", {})

        # Status icon and color
        icon = self.STATUS_ICONS.get(status, "○")
        status_color = self.STATUS_COLORS.get(status, "#8b949e")

        # Focus indicator
        if is_focused:
            text.append("▶ ", style="bold #58a6ff")
        else:
            text.append("  ", style="")

        # Status icon
        text.append(f"{icon} ", style=f"bold {status_color}")

        # Description - style based on status
        if status in ("completed", "verified"):
            text.append(desc, style="dim #6e7681 strike" if status == "completed" else "#7ee787")
        elif status == "in_progress":
            text.append(desc, style="bold #58a6ff")
        elif status == "blocked":
            text.append(desc, style="italic #f85149")
        else:
            text.append(desc, style="#c9d1d9")

        # Priority badge (only for high)
        if priority == "high":
            text.append("  !", style="bold #f85149")

        # Status label
        if status == "in_progress":
            text.append("  ← current", style="dim #58a6ff")
        elif status == "blocked":
            text.append("  ← blocked", style="dim #f85149")

        # Metadata line (dependencies, timestamps)
        meta_parts = []

        # Dependencies
        if dependencies:
            dep_count = len(dependencies)
            meta_parts.append(f"⧉ {dep_count} dep{'s' if dep_count > 1 else ''}")

        # Timestamps
        if completed_at:
            try:
                if isinstance(completed_at, str):
                    dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                else:
                    dt = completed_at
                meta_parts.append(f"✓ {dt.strftime('%H:%M')}")
            except (ValueError, AttributeError):
                pass
        elif created_at:
            try:
                if isinstance(created_at, str):
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                else:
                    dt = created_at
                meta_parts.append(f"+ {dt.strftime('%H:%M')}")
            except (ValueError, AttributeError):
                pass

        # Verification group from metadata
        if metadata.get("verification_group"):
            meta_parts.append(f"⚑ {metadata['verification_group']}")

        # Add metadata line if we have any
        if meta_parts:
            text.append("\n   ", style="")
            text.append(" · ".join(meta_parts), style="dim #6e7681")

        return text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id in ("close_btn", "close_btn_footer"):
            self.dismiss()

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss()
