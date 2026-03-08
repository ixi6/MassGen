"""
Background Tasks Modal Widget for MassGen TUI.

Modal overlay for viewing background/async operations.
Supports drilling down into individual tasks to see live output.
"""

import json
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class BackgroundTaskRow(Static, can_focus=True):
    """Clickable row for a background task."""

    def __init__(
        self,
        task_data: dict[str, Any],
        index: int,
        agent_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._task_data = task_data
        self.index = index
        self.agent_id = agent_id

    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), classes="task-content")

    def _build_content(self) -> Text:
        """Build the task row content."""
        text = Text()
        task = self._task_data

        latest_status = str(task.get("latest_status") or task.get("status") or "running").lower().strip()
        status_icon = "●"
        status_style = "bold #d29922"
        if latest_status in {"completed", "success"}:
            status_icon = "✓"
            status_style = "bold #3fb950"
        elif latest_status in {"error", "failed", "cancelled", "canceled", "stopped"}:
            status_icon = "✗"
            status_style = "bold #f85149"
        elif latest_status == "timeout":
            status_icon = "⏱"
            status_style = "bold #d29922"

        # Tool name (no emoji)
        tool_name = task.get("tool_name", "Unknown")
        display_name = task.get("display_name", tool_name)
        text.append(f"{status_icon} ", style=status_style)
        text.append(display_name, style="bold")

        agent_id = task.get("agent_id")
        if agent_id:
            text.append(f"  ({agent_id})", style="dim")

        # Async ID (e.g., background job ID)
        async_id = task.get("async_id")
        if async_id:
            text.append(f"  [{async_id}]", style="dim #d29922")

        text.append("\n")

        # Elapsed time
        start_time = task.get("start_time")
        if start_time and latest_status in {"running", "background", "pending", "queued"}:
            if isinstance(start_time, datetime):
                elapsed = (datetime.now() - start_time).total_seconds()
            else:
                elapsed = 0
            minutes, seconds = divmod(int(elapsed), 60)
            text.append(f"  ⏱ {minutes}m{seconds:02d}s running", style="dim")
        elif latest_status:
            text.append(f"  {latest_status}", style="dim")

        # Click hint
        text.append("  [click for details]", style="dim italic #d29922")

        return text

    def on_click(self) -> None:
        """Handle click to show detail view."""
        # Post message to parent modal
        self.app.push_screen(BackgroundTaskDetailModal(self._task_data, self.agent_id))


class BackgroundTaskDetailModal(ModalScreen[None]):
    """Detail modal for a single background task with live output."""

    BINDINGS = [
        ("escape", "close", "Back"),
        ("r", "refresh", "Refresh Output"),
    ]

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, task_data: dict[str, Any], agent_id: str | None = None) -> None:
        super().__init__()
        self._task_data = task_data
        self.agent_id = agent_id
        self._output_widget: Static | None = None
        self._status_widget: Static | None = None

    def compose(self) -> ComposeResult:
        task = self._task_data
        display_name = task.get("display_name", task.get("tool_name", "Unknown"))
        async_id = task.get("async_id", "")

        with Container():
            # Header
            with Container(classes="modal-header"):
                with Container(classes="header-row"):
                    title = f"Background Task . {display_name}"
                    if async_id:
                        title += f" [{async_id}]"
                    yield Static(title, classes="modal-title")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

            # Info section
            with ScrollableContainer(classes="info-section", id="info_section"):
                yield Static(self._build_info(), id="info_content")

            # Output header with status
            with Container(classes="output-header"):
                yield Static(self._build_output_header(), id="output_header")

            # Output section
            with ScrollableContainer(classes="output-section"):
                self._output_widget = Static(
                    self._build_output(),
                    classes="output-content",
                    id="output_content",
                )
                yield self._output_widget

            # Footer with buttons
            with Container(classes="modal-footer"):
                yield Button("↻ Refresh (r)", variant="default", classes="footer-button", id="refresh_btn")
                yield Button("← Back (Esc)", variant="primary", classes="footer-button", id="back_btn")

    def _build_info(self) -> Text:
        """Build the info section content."""
        text = Text()
        task = self._task_data

        # Background job ID
        async_id = task.get("async_id")
        if async_id:
            text.append("Job ID: ", style="bold")
            text.append(f"{async_id}\n", style="#d29922")

        # Agent / tool metadata
        agent_id = task.get("agent_id")
        if agent_id:
            text.append("Agent: ", style="bold")
            text.append(f"{agent_id}\n")
        tool_type = task.get("tool_type")
        if tool_type:
            text.append("Tool Type: ", style="bold")
            text.append(f"{tool_type}\n")
        status = task.get("status")
        if status:
            text.append("Status: ", style="bold")
            text.append(f"{status}\n")

        # Start time
        start_time = task.get("start_time")
        if start_time:
            if isinstance(start_time, datetime):
                text.append("Started: ", style="bold")
                text.append(f"{start_time.strftime('%H:%M:%S')}\n")

                elapsed = (datetime.now() - start_time).total_seconds()
                minutes, seconds = divmod(int(elapsed), 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    elapsed_str = f"{hours}h {minutes}m {seconds}s"
                else:
                    elapsed_str = f"{minutes}m {seconds}s"
                text.append("Elapsed: ", style="bold")
                text.append(f"{elapsed_str}\n")

        # Original request args (contains full prompt payload for background jobs)
        params = task.get("params", "")
        if params:
            text.append("Request:\n", style="bold")
            text.append(self._format_display_payload(params), style="dim")
            text.append("\n")

        # Latest captured tool result (typically start/status response)
        result = task.get("result", "")
        if result:
            text.append("Latest Result:\n", style="bold")
            text.append(self._format_display_payload(result), style="dim")

        error = task.get("error")
        if error:
            text.append("\nError: ", style="bold")
            text.append(str(error), style="#f85149")

        return text

    @staticmethod
    def _format_display_payload(payload: Any) -> str:
        """Format JSON-ish payloads for readable, wrapped modal display."""
        if payload is None:
            return ""
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False, indent=2)
        if not isinstance(payload, str):
            return str(payload)

        raw = payload.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return payload
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        return str(parsed)

    def _build_output_header(self) -> Text:
        """Build the output section header with status."""
        text = Text()
        text.append("Live Output", style="bold")

        # Get current status
        status_info = self._get_shell_status()
        if status_info:
            status = status_info.get("status", "unknown")
            text.append("  [", style="dim")
            if status == "running":
                text.append("● running", style="#d29922")  # amber/orange
            elif status == "background":
                text.append("● background", style="#d29922")
            elif status == "completed":
                text.append("✓ completed", style="#3fb950")
            elif status == "cancelled":
                text.append("✗ cancelled", style="#f85149")
            elif status == "error":
                text.append("✗ failed", style="#f85149")
            elif status == "stopped":
                exit_code = status_info.get("exit_code", 0)
                if exit_code == 0:
                    text.append("✓ completed", style="#3fb950")  # green
                else:
                    text.append(f"✗ failed (exit {exit_code})", style="#f85149")  # red
            else:
                text.append(status, style="dim")
            text.append("]", style="dim")

        text.append("  (press 'r' to refresh)", style="dim italic")

        return text

    def _build_output(self) -> Text:
        """Build the output content from a background task."""
        async_id = self._task_data.get("async_id")
        if not async_id:
            return Text("No background job ID available.", style="no-output")

        output_info = self._get_shell_output()
        if not output_info:
            return Text("Unable to fetch output for this background task.", style="no-output")

        text = Text()

        stdout = output_info.get("stdout", "")
        stderr = output_info.get("stderr", "")

        if not stdout and not stderr:
            return Text("No output yet...", style="no-output")

        # Show stdout
        if stdout:
            text.append("─── stdout ───\n", style="dim #3fb950")
            # Show last 100 lines to avoid overwhelming the display
            lines = stdout.split("\n")
            if len(lines) > 100:
                text.append(f"... ({len(lines) - 100} lines omitted) ...\n", style="dim italic")
                lines = lines[-100:]
            text.append("\n".join(lines), style="#c9d1d9")

        # Show stderr if present
        if stderr:
            if stdout:
                text.append("\n\n")
            text.append("─── stderr ───\n", style="dim #f85149")
            lines = stderr.split("\n")
            if len(lines) > 50:
                text.append(f"... ({len(lines) - 50} lines omitted) ...\n", style="dim italic")
                lines = lines[-50:]
            text.append("\n".join(lines), style="#f85149")

        return text

    def _get_shell_output(self) -> dict[str, Any] | None:
        """Get background output from stored tool result.

        The TUI currently shows the result payload captured by the tool card.
        """
        # Return a synthetic output dict using stored result
        result = self._task_data.get("result", "")
        if result:
            return {
                "stdout": result,
                "stderr": "",
                "status": "running",
                "note": "Showing captured result. Use get_background_tool_result for latest state.",
            }
        return None

    def _get_shell_status(self) -> dict[str, Any] | None:
        """Get background status metadata for display."""
        async_id = self._task_data.get("async_id")
        status = str(self._task_data.get("status") or "background")
        return {
            "job_id": async_id,
            "status": status,
            "note": "Use get_background_tool_status for live status updates.",
        }

    def action_refresh(self) -> None:
        """Refresh the output display."""
        try:
            # Update output
            output_widget = self.query_one("#output_content", Static)
            output_widget.update(self._build_output())

            # Update header with status
            header_widget = self.query_one("#output_header", Static)
            header_widget.update(self._build_output_header())

            # Update info section (for elapsed time)
            info_widget = self.query_one("#info_content", Static)
            info_widget.update(self._build_info())

            # Scroll to bottom
            scroll_container = self.query_one(".output-section", ScrollableContainer)
            scroll_container.scroll_end(animate=False)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close_btn" or event.button.id == "back_btn":
            self.dismiss()
        elif event.button.id == "refresh_btn":
            self.action_refresh()

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss()


class BackgroundTasksModal(ModalScreen[None]):
    """Modal screen showing background operations with status details."""

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        background_tasks: list[dict[str, Any]],
        recent_tasks: list[dict[str, Any]] | None = None,
        agent_id: str | None = None,
    ) -> None:
        super().__init__()
        self.background_tasks = background_tasks or []
        self.recent_tasks = recent_tasks or []
        self.agent_id = agent_id

    def compose(self) -> ComposeResult:
        active_count = len(self.background_tasks)
        recent_count = len(self.recent_tasks)

        with Container():
            # Header section
            with Container(classes="modal-header"):
                with Container(classes="header-row"):
                    title = "Background Operations"
                    if self.agent_id:
                        title += f" . {self.agent_id}"
                    yield Static(title, classes="modal-title")
                    stats = f"{active_count} active"
                    if recent_count:
                        stats += f" • {recent_count} recent"
                    yield Static(stats, classes="modal-stats")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

            # Task list
            with ScrollableContainer(classes="modal-body"):
                if not self.background_tasks and not self.recent_tasks:
                    yield Static(
                        "No background operations running.",
                        classes="empty-message",
                    )
                else:
                    row_index = 0
                    if self.background_tasks:
                        yield Static("Active", classes="section-heading")
                        for task in self.background_tasks:
                            yield BackgroundTaskRow(task, row_index, self.agent_id, id=f"task_row_{row_index}")
                            row_index += 1
                    if self.recent_tasks:
                        yield Static("Recent", classes="section-heading")
                        for task in self.recent_tasks:
                            yield BackgroundTaskRow(task, row_index, self.agent_id, id=f"task_row_{row_index}")
                            row_index += 1

            # Footer
            with Container(classes="modal-footer"):
                yield Button("Close (Esc)", variant="primary", classes="close-button", id="close_btn_footer")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id in ("close_btn", "close_btn_footer"):
            self.dismiss()

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss()
