"""
Subagent Modal Widget for MassGen TUI.

Full-screen modal overlay for viewing detailed subagent information,
live log streaming, workspace files, and final answers.
"""

from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, RichLog, Static

from massgen.frontend.displays.log_streamer import LogStreamer
from massgen.subagent.models import SubagentDisplayData


class SubagentModal(ModalScreen[None]):
    """Modal screen showing full subagent details with live log streaming.

    Design:
    ```
    ┌─────────────────── bio_researcher ──────────────── ✓ Complete ──┐
    │                                                                  │
    │  Task: Research Bob's academic background and publications       │
    │  Model: claude-sonnet-4-20250514 | 12.3s | 4.5k/2.1k tokens     │
    │                                                                  │
    │  ┌─ Live Log Stream ──────────────────────────────────────────┐ │
    │  │ [11:19:32] Starting research task...                       │ │
    │  │ [11:19:33] Tool: read_file → papers/bob_2024.pdf           │ │
    │  │ ...                                                        │ │
    │  └────────────────────────────────────────────────────────────┘ │
    │                                                                  │
    │  ┌─ Answer ───────────────────────────────────────────────────┐ │
    │  │ Bob Smith is a researcher at MIT with 15 publications...   │ │
    │  └────────────────────────────────────────────────────────────┘ │
    │                                                 [Close] [Copy]  │
    └──────────────────────────────────────────────────────────────────┘
    ```
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("c", "copy_answer", "Copy Answer"),
        ("tab", "next_subagent", "Next Subagent"),
        ("shift+tab", "prev_subagent", "Previous Subagent"),
    ]

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Status indicators
    STATUS_ICONS = {
        "completed": "✓",
        "running": "●",
        "pending": "○",
        "error": "✗",
        "timeout": "⏱",
        "failed": "✗",
    }

    STATUS_COLORS = {
        "completed": "#7ee787",
        "running": "#a371f7",
        "pending": "#8b949e",
        "error": "#f85149",
        "timeout": "#d29922",
        "failed": "#f85149",
    }

    # Polling interval
    POLL_INTERVAL = 0.5

    def __init__(
        self,
        subagent: SubagentDisplayData,
        all_subagents: list[SubagentDisplayData] | None = None,
        status_callback: Callable[[str], SubagentDisplayData | None] | None = None,
        subagent_index: int | None = None,
    ) -> None:
        """Initialize the modal.

        Args:
            subagent: The subagent to display
            all_subagents: All subagents for navigation
            status_callback: Callback to get updated status
            subagent_index: Explicit index of the subagent in all_subagents
        """
        super().__init__()
        self._subagent = subagent
        self._all_subagents = all_subagents or [subagent]
        self._current_index = 0
        # Find current index: prefer explicit index, fall back to identity match
        if subagent_index is not None and 0 <= subagent_index < len(self._all_subagents):
            self._current_index = subagent_index
        else:
            for i, sa in enumerate(self._all_subagents):
                if sa is subagent:
                    self._current_index = i
                    break

        self._status_callback = status_callback
        self._log_streamer: LogStreamer | None = None
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Container():
            # Header
            with Container(classes="modal-header"):
                with Horizontal(classes="header-row"):
                    yield Static(self._build_title(), classes="modal-title", id="modal-title")
                    yield Static(self._build_status(), classes="modal-status", id="modal-status")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

                # Progress bar
                yield Static(self._build_progress_bar(), classes="progress-bar", id="progress-bar")

            # Subagent navigation (if multiple)
            if len(self._all_subagents) > 1:
                with Horizontal(classes="subagent-nav"):
                    yield Button("◀", variant="default", classes="nav-button", id="prev_btn")
                    yield Static(self._build_nav_text(), id="nav-text")
                    yield Button("▶", variant="default", classes="nav-button", id="next_btn")

            # Metadata section
            with Container(classes="metadata-section"):
                yield Static(self._build_metadata(), id="metadata")

            # Log stream section
            with Container(classes="log-section"):
                yield Static("Live Log Stream", classes="section-title")
                yield RichLog(highlight=True, markup=True, id="log-stream")

            # Workspace section
            with Container(classes="workspace-section"):
                yield Static(self._build_workspace_info(), id="workspace-info")

            # Answer section (if completed)
            if self._subagent.answer_preview or self._subagent.error:
                with ScrollableContainer(classes="answer-section"):
                    yield Static(self._build_answer(), id="answer")

            # Footer
            with Container(classes="modal-footer"):
                with Horizontal(classes="footer-buttons"):
                    yield Button("Copy Answer", variant="default", classes="footer-button", id="copy_btn")
                    yield Button("Close (Esc)", variant="primary", classes="footer-button", id="close_btn_footer")

    def on_mount(self) -> None:
        """Start polling and log streaming when mounted."""
        # Initialize log streamer
        self._init_log_streamer()

        # Load initial logs (tail last 50 lines)
        self._load_initial_logs()

        # Start polling if subagent is running
        if self._subagent.status in ("running", "pending"):
            self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

    def on_unmount(self) -> None:
        """Stop polling when unmounted."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

    def _init_log_streamer(self) -> None:
        """Initialize the log streamer for the current subagent."""
        # First try log_path if available (stored as relative path in result)
        if hasattr(self._subagent, "log_path") and self._subagent.log_path:
            log_dir = Path(self._subagent.log_path)
            if not log_dir.is_absolute():
                # Make relative to cwd
                log_dir = Path.cwd() / log_dir

            # Check for logs in priority order:
            # 1. full_logs/ - completed subagent logs (copied after completion)
            # 2. live_logs/ - symlink to active subprocess logs (during execution)
            log_candidates = [
                log_dir / "full_logs" / "massgen.log",  # Completed logs
            ]

            # Check live_logs symlink for active subprocess logs
            # live_logs -> workspace/.massgen/massgen_logs/
            live_logs_base = log_dir / "live_logs"
            if live_logs_base.exists():
                # Find most recent log_* directory inside live_logs
                try:
                    for subdir in sorted(live_logs_base.glob("log_*"), reverse=True):
                        live_log = subdir / "turn_1" / "attempt_1" / "massgen.log"
                        if live_log.exists():
                            log_candidates.insert(0, live_log)  # Prioritize live log
                            break
                except Exception:
                    pass

            for log_file in log_candidates:
                if log_file.exists():
                    self._log_streamer = LogStreamer(log_file)
                    return

        # Fall back to workspace-based log locations (legacy)
        workspace = Path(self._subagent.workspace_path) if self._subagent.workspace_path else None
        if workspace and workspace.exists():
            log_candidates = [
                workspace / "full_logs" / "massgen.log",
                workspace / "massgen.log",
            ]
            for log_path in log_candidates:
                if log_path.exists():
                    self._log_streamer = LogStreamer(log_path)
                    break

    def _load_initial_logs(self) -> None:
        """Load initial log content (tail last 50 lines)."""
        if not self._log_streamer:
            return

        try:
            log_widget = self.query_one("#log-stream", RichLog)
            lines = self._log_streamer.tail(50)
            for line in lines:
                log_widget.write(self._format_log_line(line))

            # Skip to end so get_new_lines() only returns new content
            self._log_streamer.skip_to_end()
        except Exception:
            pass

    def _poll_updates(self) -> None:
        """Poll for status and log updates."""
        # Update status if callback available
        if self._status_callback:
            new_data = self._status_callback(self._subagent.id)
            if new_data:
                self._subagent = new_data
                self._refresh_content()

        # Stream new log lines
        if self._log_streamer:
            try:
                log_widget = self.query_one("#log-stream", RichLog)
                for line in self._log_streamer.get_new_lines():
                    log_widget.write(self._format_log_line(line))
            except Exception:
                pass

        # Stop polling if completed
        if self._subagent.status not in ("running", "pending"):
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None

    def _format_log_line(self, line: str) -> Text:
        """Format a log line with syntax highlighting.

        Args:
            line: Raw log line

        Returns:
            Rich Text with formatting
        """
        text = Text()

        # Try to extract timestamp
        if line.startswith("[") and "]" in line:
            bracket_end = line.index("]") + 1
            timestamp = line[:bracket_end]
            rest = line[bracket_end:].strip()
            text.append(timestamp, style="dim #6e7681")
            text.append(" ")
            line = rest

        # Highlight tool calls
        if "Tool:" in line or "tool:" in line:
            text.append(line, style="#58a6ff")
        elif "Error:" in line or "error:" in line:
            text.append(line, style="#f85149")
        elif "✓" in line or "completed" in line.lower():
            text.append(line, style="#7ee787")
        elif line.startswith("💬") or line.startswith('"'):
            text.append(line, style="italic #8b949e")
        else:
            text.append(line, style="#c9d1d9")

        return text

    def _refresh_content(self) -> None:
        """Refresh all dynamic content."""
        try:
            self.query_one("#modal-title", Static).update(self._build_title())
            self.query_one("#modal-status", Static).update(self._build_status())
            self.query_one("#progress-bar", Static).update(self._build_progress_bar())
            self.query_one("#metadata", Static).update(self._build_metadata())
            self.query_one("#workspace-info", Static).update(self._build_workspace_info())

            # Update answer if exists
            try:
                self.query_one("#answer", Static).update(self._build_answer())
            except Exception:
                pass
        except Exception:
            pass

    def _build_title(self) -> Text:
        """Build the modal title."""
        text = Text()
        text.append("Subagent . ", style="")
        text.append(self._subagent.id, style="bold #7c3aed")
        return text

    def _build_status(self) -> Text:
        """Build the status indicator."""
        text = Text()
        icon = self.STATUS_ICONS.get(self._subagent.status, "○")
        color = self.STATUS_COLORS.get(self._subagent.status, "#8b949e")
        text.append(f"{icon} {self._subagent.status.capitalize()}", style=f"bold {color}")
        return text

    def _build_progress_bar(self) -> Text:
        """Build a visual progress bar."""
        bar_width = 60
        filled = int(bar_width * self._subagent.progress_percent / 100)
        empty = bar_width - filled

        text = Text()
        if filled > 0:
            color = self.STATUS_COLORS.get(self._subagent.status, "#a371f7")
            text.append("█" * filled, style=color)
        if empty > 0:
            text.append("░" * empty, style="#30363d")
        text.append(f" {self._subagent.progress_percent}%", style="#8b949e")

        return text

    def _build_nav_text(self) -> Text:
        """Build navigation text for multiple subagents."""
        text = Text()
        text.append(f" {self._current_index + 1}/{len(self._all_subagents)} ", style="#8b949e")
        return text

    def _build_metadata(self) -> Text:
        """Build the metadata section."""
        text = Text()

        # Task description
        task = self._subagent.task
        if len(task) > 100:
            task = task[:97] + "..."
        text.append("Task: ", style="bold #8b949e")
        text.append(f"{task}\n", style="#c9d1d9")

        # Timing info
        text.append("Duration: ", style="bold #8b949e")
        text.append(f"{self._subagent.elapsed_seconds:.1f}s", style="#c9d1d9")
        text.append(f" / {self._subagent.timeout_seconds:.0f}s timeout", style="dim #6e7681")

        return text

    def _build_workspace_info(self) -> Text:
        """Build workspace info section."""
        text = Text()
        text.append("Workspace: ", style="bold #8b949e")
        text.append(f"{self._subagent.workspace_file_count} files", style="#c9d1d9")

        if self._subagent.workspace_path:
            path = self._subagent.workspace_path
            if len(path) > 60:
                path = "..." + path[-57:]
            text.append(f"  ({path})", style="dim #6e7681")

        return text

    def _build_answer(self) -> Text:
        """Build the answer/error section."""
        text = Text()

        if self._subagent.error:
            text.append("Error\n", style="bold #f85149")
            text.append(self._subagent.error, style="#f85149")
        elif self._subagent.answer_preview:
            text.append("Answer\n", style="bold #7ee787")
            text.append(self._subagent.answer_preview, style="#c9d1d9")
        else:
            text.append("Awaiting completion...", style="dim #8b949e")

        return text

    def _switch_subagent(self, index: int) -> None:
        """Switch to a different subagent."""
        if 0 <= index < len(self._all_subagents):
            self._current_index = index
            self._subagent = self._all_subagents[index]

            # Re-initialize log streamer
            self._init_log_streamer()

            # Clear and reload logs
            try:
                log_widget = self.query_one("#log-stream", RichLog)
                log_widget.clear()
                self._load_initial_logs()
            except Exception:
                pass

            # Refresh all content
            self._refresh_content()

            # Update nav text
            try:
                self.query_one("#nav-text", Static).update(self._build_nav_text())
            except Exception:
                pass

            # Restart polling if needed
            if self._subagent.status in ("running", "pending") and not self._poll_timer:
                self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id in ("close_btn", "close_btn_footer"):
            self.dismiss()
        elif event.button.id == "prev_btn":
            self._switch_subagent(self._current_index - 1)
        elif event.button.id == "next_btn":
            self._switch_subagent(self._current_index + 1)
        elif event.button.id == "copy_btn":
            self._copy_answer()

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss()

    def action_next_subagent(self) -> None:
        """Navigate to next subagent."""
        self._switch_subagent(self._current_index + 1)

    def action_prev_subagent(self) -> None:
        """Navigate to previous subagent."""
        self._switch_subagent(self._current_index - 1)

    def action_copy_answer(self) -> None:
        """Copy answer to clipboard."""
        self._copy_answer()

    def _copy_answer(self) -> None:
        """Copy the answer to clipboard."""
        if self._subagent.answer_preview:
            try:
                import pyperclip

                pyperclip.copy(self._subagent.answer_preview)
                self.notify("Answer copied to clipboard!")
            except ImportError:
                self.notify("pyperclip not installed - cannot copy", severity="warning")
            except Exception as e:
                self.notify(f"Failed to copy: {e}", severity="error")
