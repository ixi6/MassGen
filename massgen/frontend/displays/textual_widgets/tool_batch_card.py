"""
Tool Batch Card Widget for MassGen TUI.

Displays consecutive MCP tool calls from the same server as a single
collapsible tree view card, reducing visual clutter.

Visual design:
```
┌─────────────────────────────────────────────────────────────────┐
│  filesystem                                           [0.8s] ✓  │
│    ├─ create_directory  "deliverable"                       ✓   │
│    ├─ create_directory  "scratch"                           ✓   │
│    └─ write_file        "deliverable/poem.txt" (+2 more)    ✓   │
└─────────────────────────────────────────────────────────────────┘
```
"""

from dataclasses import dataclass
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.events import Click
from textual.message import Message
from textual.widgets import Static


@dataclass
class ToolBatchItem:
    """Data for a single tool within a batch."""

    tool_id: str
    tool_name: str
    display_name: str  # Just the tool name part (e.g., "write_file")
    status: str  # running, success, error
    args_summary: str | None = None
    args_full: str | None = None
    result_summary: str | None = None
    result_full: str | None = None
    error: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    elapsed_seconds: float | None = None


class ToolBatchCard(Static, can_focus=True):
    """Collapsible card showing batched MCP tool calls from the same server.

    Groups consecutive tool calls from the same MCP server into a single
    tree-view card for cleaner display.

    Attributes:
        server_name: Name of the MCP server (e.g., "filesystem").
        tools: List of ToolBatchItem in this batch.
    """

    class BatchCardClicked(Message):
        """Posted when a batch card is clicked (for modal)."""

        def __init__(self, card: "ToolBatchCard") -> None:
            self.card = card
            super().__init__()

    class ToolInBatchClicked(Message):
        """Posted when a tool line within a batch is clicked."""

        def __init__(self, card: "ToolBatchCard", tool_item: ToolBatchItem) -> None:
            self.card = card
            self.tool_item = tool_item
            super().__init__()

    # Number of tools to show when collapsed
    COLLAPSED_VISIBLE_COUNT = 3

    STATUS_ICONS = {
        "running": "◉",
        "success": "✓",
        "error": "✗",
    }

    def __init__(
        self,
        server_name: str,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the batch card.

        Args:
            server_name: Name of the MCP server.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.server_name = server_name
        self._tools: dict[str, ToolBatchItem] = {}  # tool_id -> ToolBatchItem
        self._tool_order: list[str] = []  # Maintain insertion order
        self._tool_line_map: dict[int, str] = {}  # line_number -> tool_id for click detection
        self._expanded = False
        self._start_time = datetime.now()

        # Add initial classes
        self.add_class("status-running")

        # Appearance animation
        self.add_class("appearing")

    def on_mount(self) -> None:
        """Complete appearance animation."""
        self.set_timer(0.3, self._complete_appearance)

    def _complete_appearance(self) -> None:
        """Complete the appearance animation."""
        self.remove_class("appearing")
        self.add_class("appeared")

    def compose(self) -> ComposeResult:
        """Compose the card content."""
        yield Static(self._build_content(), id="batch-content")

    def _build_content(self) -> Text:
        """Build the card content as Rich Text."""
        text = Text()

        # Clear line map for fresh tracking
        self._tool_line_map.clear()
        current_line = 0  # Track line numbers for click detection

        # Calculate aggregate status
        statuses = [t.status for t in self._tools.values()]
        has_running = "running" in statuses
        has_error = "error" in statuses
        all_success = all(s == "success" for s in statuses) if statuses else False

        if has_running:
            aggregate_status = "running"
        elif has_error:
            aggregate_status = "error"
        elif all_success:
            aggregate_status = "success"
        else:
            aggregate_status = "running"

        # Calculate total elapsed time
        total_elapsed = self._get_total_elapsed()
        elapsed_str = f"[{total_elapsed:.1f}s]" if total_elapsed else "[...]"

        # Header line with expand indicator
        expand_indicator = "▾" if self._expanded else "▸"

        # Status icon
        status_icon = self.STATUS_ICONS.get(aggregate_status, "◉")

        # Header styling based on status
        if aggregate_status == "running":
            header_style = "bold cyan"
            icon_style = "bold cyan"
        elif aggregate_status == "error":
            header_style = "bold"
            icon_style = "red"
        else:
            header_style = "bold"
            icon_style = "green"

        # Build header: "▸ filesystem [0.8s] ✓" (line 0)
        text.append(f"{expand_indicator} ", style="dim")
        text.append(self.server_name, style=header_style)
        text.append(f"  {elapsed_str} ", style="dim")
        text.append(status_icon, style=icon_style)

        tool_count = len(self._tools)
        all_tools = list(self._tools.values())

        # When collapsed, show the NEWEST tools (last N) and put "(+N more)" at top
        if not self._expanded and tool_count > self.COLLAPSED_VISIBLE_COUNT:
            hidden = tool_count - self.COLLAPSED_VISIBLE_COUNT
            text.append(f"\n    ├─ (+{hidden} earlier)", style="dim italic")
            current_line += 1  # "(+N earlier)" line
            tools_to_show = all_tools[-self.COLLAPSED_VISIBLE_COUNT :]
        else:
            tools_to_show = all_tools

        # Render tool tree and track line numbers
        for i, tool in enumerate(tools_to_show):
            is_last = i == len(tools_to_show) - 1
            current_line += 1  # Each tool starts on a new line
            self._tool_line_map[current_line] = tool.tool_id
            lines_added = self._render_tool_line(text, tool, is_last)
            # Account for extra lines (e.g., error preview)
            current_line += lines_added

        return text

    def _render_tool_line(self, text: Text, tool: ToolBatchItem, is_last: bool) -> int:
        """Render a single tool line in the tree.

        Args:
            text: Rich Text to append to.
            tool: ToolBatchItem to render.
            is_last: Whether this is the last visible item.

        Returns:
            Number of extra lines added (e.g., 1 for error preview, 0 otherwise).
        """
        extra_lines = 0

        # Tree connector
        connector = "└─" if is_last else "├─"

        # Status icon for this tool
        tool_icon = self.STATUS_ICONS.get(tool.status, "◉")

        # Style based on status
        if tool.status == "running":
            name_style = "cyan"
            icon_style = "cyan"
        elif tool.status == "error":
            name_style = "red"
            icon_style = "red"
        else:
            name_style = ""
            icon_style = "green"

        # Extract just the tool name (remove server prefix for display)
        display_name = tool.display_name

        # Build line: "  ├─ write_file  "path/to/file"  ✓"
        text.append(f"\n    {connector} ", style="dim")
        text.append(f"{display_name:<18}", style=name_style)

        # Args summary (width based on terminal size)
        if tool.args_summary:
            max_len = self._get_available_args_width()
            args_display = self._truncate_args(tool.args_summary, max_len)
            text.append(f" {args_display}", style="dim")

        # Status icon at end
        text.append(f"  {tool_icon}", style=icon_style)

        # Show error preview if failed
        if tool.status == "error" and tool.error and self._expanded:
            error_preview = tool.error.replace("\n", " ")[:50]
            text.append(f"\n         ✗ {error_preview}", style="dim red")
            extra_lines = 1

        return extra_lines

    def _shorten_path(self, path: str, max_len: int) -> str:
        """Shorten a path, keeping the end (filename/dirs) visible.

        For long absolute paths, shows .../<meaningful_part> instead of
        /very/long/path/that/gets/trun...
        """
        if len(path) <= max_len:
            return path

        # For paths, keep the end (filename + parent dirs) visible
        if "/" in path or "\\" in path:
            # Reserve 3 chars for "..."
            suffix_len = max_len - 3
            if suffix_len > 0:
                return "..." + path[-suffix_len:]

        # Fallback: truncate from the end (non-path values)
        return path[: max_len - 3] + "..."

    def _truncate_args(self, args: str, max_len: int) -> str:
        """Truncate args string for display, keeping end of paths visible."""
        import json
        import re

        try:
            data = json.loads(args)
            if isinstance(data, dict):
                # For any dict with a path-like key, just show that path value
                for key in ["path", "file_path", "directory", "url"]:
                    if key in data:
                        val = str(data[key])
                        val = self._shorten_path(val, max_len - 2)  # -2 for quotes
                        return f'"{val}"'
                # For content, show beginning
                if "content" in data:
                    val = str(data["content"]).replace("\n", "\\n")
                    if len(val) > max_len - 3:
                        val = val[: max_len - 6] + "..."
                    return f'"{val}"'
                # For other dicts, find any path-like value and show its end
                for k, v in data.items():
                    if isinstance(v, str) and self._is_path_like(v):
                        v = self._shorten_path(v, max_len - 2)  # -2 for quotes
                        return f'"{v}"'
                # No paths found - show truncated JSON
                result = json.dumps(data)
                if len(result) <= max_len:
                    return result
                return result[: max_len - 3] + "..."
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: check for path patterns in non-JSON strings
        # Match patterns like "path": "/some/path" or path=/some/path
        path_match = re.search(r'["\']?(/[^"\'>\s]+|[A-Za-z]:\\[^"\'>\s]+)', args)
        if path_match:
            path_val = path_match.group(1)
            if self._is_path_like(path_val):
                shortened = self._shorten_path(path_val, max_len - 2)
                return f'"{shortened}"'

        # Final fallback: if contains path-like content, keep the end visible
        if self._is_path_like(args):
            return self._shorten_path(args, max_len)

        # Non-path content: truncate from the end normally
        if len(args) > max_len:
            return args[: max_len - 3] + "..."
        return args

    def _is_path_like(self, value: str) -> bool:
        """Check if a string looks like a file path."""
        if "/" in value or "\\" in value:
            return True
        if value.startswith(".") or value.endswith((".txt", ".py", ".md", ".json", ".yaml")):
            return True
        return False

    def _get_available_args_width(self) -> int:
        """Calculate available width for args based on terminal size."""
        try:
            if self.app and hasattr(self.app, "size"):
                terminal_width = self.app.size.width
                # Subtract: indent(6) + connector(3) + tool_name(18) + status_icon(4) + padding(5)
                used_width = 36
                available = terminal_width - used_width
                return max(30, min(available, 200))  # Between 30 and 200 chars
        except Exception:
            pass
        return 60  # Reasonable default

    def _get_total_elapsed(self) -> float:
        """Calculate total elapsed time for the batch."""
        if not self._tools:
            return 0.0

        # Use the max end_time - min start_time for total span
        # Or current time if any tools still running
        has_running = any(t.status == "running" for t in self._tools.values())

        if has_running:
            return (datetime.now() - self._start_time).total_seconds()

        # Find the span
        start_times = [t.start_time for t in self._tools.values() if t.start_time]
        end_times = [t.end_time for t in self._tools.values() if t.end_time]

        if start_times and end_times:
            min_start = min(start_times)
            max_end = max(end_times)
            return (max_end - min_start).total_seconds()

        # Fallback: sum of individual elapsed times
        return sum(t.elapsed_seconds or 0.0 for t in self._tools.values())

    def _refresh_content(self) -> None:
        """Refresh the displayed content."""
        try:
            content_widget = self.query_one("#batch-content", Static)
            content_widget.update(self._build_content())
        except Exception:
            self.refresh()

    def _update_status_class(self) -> None:
        """Update CSS class based on aggregate status."""
        statuses = [t.status for t in self._tools.values()]
        has_running = "running" in statuses
        has_error = "error" in statuses
        all_success = all(s == "success" for s in statuses) if statuses else False

        self.remove_class("status-running", "status-success", "status-error")

        if has_running:
            self.add_class("status-running")
        elif has_error:
            self.add_class("status-error")
        elif all_success:
            self.add_class("status-success")
        else:
            self.add_class("status-running")

    def on_click(self, event: Click) -> None:
        """Handle click - toggle expansion or open tool detail modal."""
        click_x = event.x if hasattr(event, "x") else 0
        click_y = event.y if hasattr(event, "y") else 0

        if not self._expanded:
            # Collapsed: expand on any click
            self._expanded = True
            self.add_class("expanded")
            self._refresh_content()
        elif click_x < 3:
            # Left edge when expanded: collapse
            self._expanded = False
            self.remove_class("expanded")
            self._refresh_content()
        else:
            # Expanded + click elsewhere: check if clicking a tool line
            tool_id = self._tool_line_map.get(click_y)
            if tool_id and tool_id in self._tools:
                # Post message to open tool detail modal
                self.post_message(self.ToolInBatchClicked(self, self._tools[tool_id]))
            # Don't collapse - user clicked a tool line or empty space

    def add_tool(self, tool: ToolBatchItem) -> None:
        """Add a tool to this batch.

        Args:
            tool: ToolBatchItem to add.
        """
        self._tools[tool.tool_id] = tool
        if tool.tool_id not in self._tool_order:
            self._tool_order.append(tool.tool_id)
        self._update_status_class()
        self._refresh_content()

    def update_tool(self, tool_id: str, tool: ToolBatchItem) -> None:
        """Update an existing tool in this batch.

        Args:
            tool_id: ID of the tool to update.
            tool: Updated ToolBatchItem.
        """
        if tool_id in self._tools:
            self._tools[tool_id] = tool
            self._update_status_class()
            self._refresh_content()

    def get_tool(self, tool_id: str) -> ToolBatchItem | None:
        """Get a tool by ID.

        Args:
            tool_id: ID of the tool.

        Returns:
            ToolBatchItem if found, None otherwise.
        """
        return self._tools.get(tool_id)

    def has_tool(self, tool_id: str) -> bool:
        """Check if a tool is in this batch.

        Args:
            tool_id: ID of the tool.

        Returns:
            True if the tool exists in this batch.
        """
        return tool_id in self._tools

    @property
    def tools(self) -> list[ToolBatchItem]:
        """Get all tools in insertion order."""
        return [self._tools[tid] for tid in self._tool_order if tid in self._tools]

    @property
    def tool_count(self) -> int:
        """Get the number of tools in this batch."""
        return len(self._tools)

    @property
    def is_expanded(self) -> bool:
        """Check if the card is expanded."""
        return self._expanded

    @property
    def has_running_tools(self) -> bool:
        """Check if any tools are still running."""
        return any(t.status == "running" for t in self._tools.values())

    @property
    def aggregate_status(self) -> str:
        """Get the aggregate status of the batch."""
        statuses = [t.status for t in self._tools.values()]
        if "running" in statuses:
            return "running"
        if "error" in statuses:
            return "error"
        if all(s == "success" for s in statuses) and statuses:
            return "success"
        return "running"
