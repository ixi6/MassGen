"""
Task Plan Card Widget for MassGen TUI.

Visual todo list display for Planning MCP integration.
Shows tasks from create_task_plan, update_task_status, etc.
"""

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class TaskPlanCard(Static):
    """Card displaying a visual todo list from Planning MCP.

    Design:
    ```
    ┌─ Tasks ────────────────────────────────────┐
    │ ✓ Research OAuth providers                 │  ← completed (dimmed)
    │ ✓ Compare authentication methods           │  ← completed (dimmed)
    │ ● Implement OAuth flow                     │  ← in_progress (highlighted)
    │ ○ Write integration tests                  │  ← pending (ready)
    │ ○ Deploy to staging                        │  ← pending (blocked)
    └────────────────────────────────────────────┘
    ```

    Display Logic:
    - On create_task_plan: Show first N tasks (based on terminal size)
    - On update_task_status/edit_task: Show neighborhood around focused task
      (2 above, focused task, 2 below)
    - Click to open full task plan modal
    """

    class OpenModal(Message):
        """Message posted when user clicks to open the task plan modal."""

        def __init__(self, tasks: list[dict[str, Any]], focused_task_id: str | None = None) -> None:
            self.tasks = tasks
            self.focused_task_id = focused_task_id
            super().__init__()

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Status indicators
    STATUS_ICONS = {
        "completed": "✓",
        "in_progress": "●",
        "pending": "○",
        "blocked": "◌",
    }

    # Default maximum tasks to show (used if terminal size unavailable)
    DEFAULT_MAX_VISIBLE = 5

    # Reactive properties
    tasks: reactive[list[dict[str, Any]]] = reactive(list, always_update=True)
    focused_task_id: reactive[str | None] = reactive(None)

    def __init__(
        self,
        tasks: list[dict[str, Any]] | None = None,
        focused_task_id: str | None = None,
        operation: str = "create",
        id: str | None = None,
    ) -> None:
        """Initialize the task plan card.

        Args:
            tasks: List of task dictionaries with id, description, status, priority
            focused_task_id: ID of the task to focus on (for update operations)
            operation: Type of operation (create, update, edit)
            id: Widget ID
        """
        super().__init__(id=id)
        self._tasks = tasks or []
        self._focused_task_id = focused_task_id
        self._operation = operation
        self._reminder: str | None = None
        self._changed_task_ids: set = set()  # Track recently changed tasks for highlighting

    def render(self) -> Text:
        """Render the card content directly."""
        return self._build_content()

    def on_click(self) -> None:
        """Open the task plan modal on click."""
        self.post_message(self.OpenModal(self._tasks, self._focused_task_id))

    def _refresh_content(self) -> None:
        """Refresh the displayed content."""
        self.refresh()

    def _clear_highlights(self) -> None:
        """Clear task change highlights."""
        self._changed_task_ids = set()
        self.refresh()

    def set_reminder(self, content: str) -> None:
        """Set a high priority task reminder to display at the bottom of the card.

        Args:
            content: The reminder text to display
        """
        self._reminder = content
        self._refresh_content()

    def _get_max_visible(self) -> int:
        """Get maximum visible tasks based on terminal size."""
        try:
            # Try to get terminal height from app
            if self.app and hasattr(self.app, "size"):
                terminal_height = self.app.size.height
                # Reserve space for header, footer, and other UI elements
                # Allocate roughly 1/3 of terminal height to task list
                available = max(3, (terminal_height - 10) // 3)
                return min(available, 10)  # Cap at 10 tasks
        except Exception:
            pass
        return self.DEFAULT_MAX_VISIBLE

    def _get_max_description_length(self) -> int:
        """Get maximum description length based on terminal width."""
        try:
            if self.app and hasattr(self.app, "size"):
                terminal_width = self.app.size.width
                # Reserve space for icon, priority, padding, etc. (~10 chars)
                available = terminal_width - 15
                return max(30, min(available, 120))  # Between 30 and 120 chars
        except Exception:
            pass
        return 60  # Default reasonable width

    def _build_content(self) -> Text:
        """Build the card content as Rich Text - clean minimal style."""
        text = Text()

        if not self._tasks:
            text.append("No tasks", style="dim #6e7681")
            return text

        # Count tasks
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks if t.get("status") == "completed")

        # Clean header: "Tasks 3/5" - minimal, no icons or progress bars
        text.append(f"Tasks {completed}/{total}", style="#8b949e")

        # Get visible tasks (click card to see all in modal)
        visible_tasks, start_idx = self._get_visible_tasks()
        max_desc_len = self._get_max_description_length()

        # Show "more above" indicator
        if start_idx > 0:
            text.append(f" (+{start_idx} above)", style="dim #6e7681")

        # Render each visible task - clean minimal style
        for task in visible_tasks:
            task_id = task.get("id")
            is_focused = task_id == self._focused_task_id
            is_changed = task_id in self._changed_task_ids
            status = task.get("status", "pending")

            # Simple icons: ✓ done, → active, · pending
            if status == "completed":
                icon = "✓"
                style = "dim #6e7681"
            elif status == "in_progress":
                icon = "→"
                style = "#58a6ff"
            else:
                icon = "·"
                style = "dim #8b949e"

            # Focus highlight
            if is_focused and status != "completed":
                style = "#58a6ff"

            # Changed task highlight (brief flash) - bright color
            if is_changed:
                style = "bold #7ee787"  # Bright green for changed tasks

            # Description (truncate based on terminal width)
            desc = task.get("description", "Untitled task")
            if len(desc) > max_desc_len:
                desc = desc[: max_desc_len - 3] + "..."

            text.append(f"\n{icon} {desc}", style=style)

        # Show "more below" indicator
        remaining = total - (start_idx + len(visible_tasks))
        if remaining > 0:
            text.append(f" (+{remaining} more)", style="dim #6e7681")

        # Render reminder if set (keep this prominent)
        if self._reminder:
            reminder_text = self._reminder.replace("\n", " ").strip()
            max_len = self._get_max_description_length()
            if len(reminder_text) > max_len:
                reminder_text = reminder_text[: max_len - 3] + "..."
            text.append(f"\n! {reminder_text}", style="#ffa657")

        return text

    def _get_visible_tasks(self) -> tuple[list[dict[str, Any]], int]:
        """Get the visible subset of tasks (click card to see all in modal).

        Returns:
            Tuple of (visible_tasks, start_index)
        """
        total = len(self._tasks)
        max_visible = self._get_max_visible()

        if total <= max_visible:
            return self._tasks, 0

        if self._operation == "create" or not self._focused_task_id:
            # Show first max_visible tasks
            return self._tasks[:max_visible], 0

        # Find focused task index
        focused_idx = 0
        for i, task in enumerate(self._tasks):
            if task.get("id") == self._focused_task_id:
                focused_idx = i
                break

        # Calculate window: 2 above, focused, 2 below
        context_above = 2
        context_below = 2

        start = max(0, focused_idx - context_above)
        end = min(total, focused_idx + context_below + 1)

        # Adjust if we're at the edges
        if end - start < max_visible:
            if start == 0:
                end = min(total, max_visible)
            elif end == total:
                start = max(0, total - max_visible)

        return self._tasks[start:end], start

    def update_tasks(self, tasks: list[dict[str, Any]], focused_task_id: str | None = None, operation: str = "update") -> None:
        """Update the displayed tasks.

        Args:
            tasks: New list of tasks
            focused_task_id: Task to focus on
            operation: Type of operation
        """
        # Detect which tasks changed (status changed)
        old_status_map = {t.get("id"): t.get("status") for t in self._tasks if t.get("id")}
        self._changed_task_ids = set()

        for task in tasks:
            task_id = task.get("id")
            if task_id:
                old_status = old_status_map.get(task_id)
                new_status = task.get("status")
                # Highlight if status changed or it's a new task
                if old_status is None or old_status != new_status:
                    self._changed_task_ids.add(task_id)

        self._tasks = tasks
        self._focused_task_id = focused_task_id
        self._operation = operation

        # Update display
        self.refresh()

        # Clear highlights after brief delay
        if self._changed_task_ids and self.app:
            self.app.set_timer(0.8, self._clear_highlights)

    @classmethod
    def from_mcp_result(cls, result: dict[str, Any], operation: str = "create") -> "TaskPlanCard":
        """Create a TaskPlanCard from MCP tool result.

        Args:
            result: Result dictionary from Planning MCP tool
            operation: Type of operation (create, update, add, edit)

        Returns:
            Configured TaskPlanCard instance
        """
        tasks = []
        focused_task_id = None

        # Extract tasks from result
        if "tasks" in result:
            tasks = result["tasks"]
        elif "plan" in result and "tasks" in result["plan"]:
            tasks = result["plan"]["tasks"]

        # Extract focused task from update operations
        if operation in ("update", "edit") and "task" in result:
            focused_task_id = result["task"].get("id")

        return cls(tasks=tasks, focused_task_id=focused_task_id, operation=operation)
