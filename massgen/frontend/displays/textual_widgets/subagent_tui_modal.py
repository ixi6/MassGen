"""
Full TUI Modal for Subagents.

Displays the complete MassGen TUI experience for subagents by reading
events from events.jsonl and reconstructing the timeline.

Features:
- Timeline with tool cards, thinking sections, and text content
- Live updates while subagent is running (500ms polling)
- Multi-agent support with tab bar
- Status ribbon with round, tool count, and elapsed time
- Keyboard shortcuts (Esc to close, Tab for agent switching)
- Full parity with main TUI styling and widgets
"""

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Markdown, Static

from massgen.events import EventReader, MassGenEvent
from massgen.logger_config import get_log_session_dir
from massgen.subagent.models import SubagentDisplayData

from ..content_processor import ContentOutput, ContentProcessor
from ..shared.tui_debug import tui_log
from .content_sections import TimelineSection


class SubagentFinalAnswerCard(Vertical):
    """Simplified final answer card for subagent modal.

    Shows the final answer with green styling but without the full
    FinalPresentationCard features (voting, post-eval, etc.).
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, content: str = "", id: str | None = None) -> None:
        super().__init__(id=id)
        self._content = content

    def compose(self) -> ComposeResult:
        yield Static("✓ FINAL ANSWER", id="final_answer_header")
        with ScrollableContainer(id="final_answer_content"):
            yield Markdown(self._content, id="final_answer_text")

    def update_content(self, content: str) -> None:
        """Update the final answer content."""
        self._content = content
        try:
            md = self.query_one("#final_answer_text", Markdown)
            md.update(content)
        except Exception as e:
            tui_log(f"[SubagentTuiModal] {e}")


class SubagentTuiModal(ModalScreen[None]):
    """Modal screen showing full TUI experience for subagent.

    Now uses TimelineSection for full parity with the main TUI,
    including proper tool card styling, batching, and formatting.

    Design:
    ```
    +----------------------------------------------------------+
    | Subagent: bio_researcher                    [X] Close    |
    | Model: claude-haiku | 45.2s | 3.2k/1.1k tokens           |
    +----------------------------------------------------------+
    |                                                          |
    | Round 1                                                  |
    | -------------------------------------------------------- |
    |                                                          |
    | Let me research Bob Dylan's biography...                 |
    |                                                          |
    | [filesystem] read_file                          (0.3s)   |
    |   {"path": "/tmp/test.txt"}                              |
    |   → Found 2,345 bytes...                                 |
    |                                                          |
    +----------------------------------------------------------+
    | Status: Working | Round 1 | 12 tools | 45s elapsed       |
    +----------------------------------------------------------+
    | [Copy Answer]  [Close (Esc)]                             |
    +----------------------------------------------------------+
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
        self._poll_timer: Timer | None = None
        self._event_reader: EventReader | None = None
        self._content_processor: ContentProcessor | None = None
        self._tool_count = 0
        self._round_number = 1
        self._final_answer: str | None = None

    def compose(self) -> ComposeResult:
        with Container():
            # Header
            with Container(classes="modal-header"):
                with Horizontal(classes="header-row"):
                    yield Static(self._build_title(), classes="modal-title", id="modal-title")
                    yield Static(self._build_status(), classes="modal-status", id="modal-status")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

                # Metadata row
                yield Static(self._build_metadata(), classes="metadata-row", id="metadata")

            # Subagent navigation (if multiple)
            if len(self._all_subagents) > 1:
                with Horizontal(classes="subagent-nav"):
                    yield Button("◀", variant="default", classes="nav-button", id="prev_btn")
                    yield Static(self._build_nav_text(), id="nav-text")
                    yield Button("▶", variant="default", classes="nav-button", id="next_btn")

            # Timeline section (reusing main TUI component)
            yield TimelineSection(id="subagent-timeline")

            # Status ribbon
            yield Static(self._build_status_ribbon(), classes="status-ribbon", id="status-ribbon")

            # Footer
            with Container(classes="modal-footer"):
                with Horizontal(classes="footer-buttons"):
                    yield Button("Copy Answer", variant="default", classes="footer-button", id="copy_btn")
                    yield Button("Close (Esc)", variant="primary", classes="footer-button", id="close_btn_footer")

    def on_mount(self) -> None:
        """Initialize event reader and load events."""
        self._init_event_reader()
        self._load_initial_events()

        # Start polling if subagent is running
        if self._subagent.status in ("running", "pending"):
            self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

    def on_unmount(self) -> None:
        """Stop polling when unmounted."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

    def on_streaming_event(self, event: MassGenEvent) -> None:
        """Handle a streaming event from the parent process.

        This method is called by the TUI display when --stream-events is used.
        It replaces file-based polling with direct event streaming.

        Args:
            event: The MassGenEvent received from the subprocess stdout
        """
        # Ensure we have a content processor
        if self._content_processor is None:
            self._content_processor = ContentProcessor()

        # Process the event and add to timeline
        output = self._content_processor.process_event(event, self._round_number)
        if output:
            try:
                timeline = self.query_one("#subagent-timeline", TimelineSection)
                outputs = output if isinstance(output, list) else [output]
                for item in outputs:
                    # Update round number from round_start events
                    if item.output_type == "separator" and item.round_number:
                        self._round_number = item.round_number
                    self._apply_output_to_timeline(timeline, item)
            except Exception as e:
                tui_log(f"[SubagentTuiModal] {e}")

        # Update status ribbon
        self._update_status_ribbon()

    def enable_streaming_mode(self) -> None:
        """Enable streaming mode and disable file-based polling.

        Call this when using streaming events instead of file polling.
        """
        # Stop any existing polling timer
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

        # Initialize content processor for streaming
        if self._content_processor is None:
            self._content_processor = ContentProcessor()

    def _init_event_reader(self) -> None:
        """Initialize the event reader for the current subagent.

        Uses get_log_session_dir() to find subagent logs at a predictable path.
        Structure: {log_session_dir}/subagents/{subagent_id}/live_logs/log_*/turn_1/attempt_1/events.jsonl
        """
        events_file = None

        # Debug logging
        debug_lines = []
        debug_lines.append("=== SubagentTuiModal._init_event_reader ===")
        debug_lines.append(f"subagent.id: {self._subagent.id}")

        # Simple path: subagent logs are in the log directory
        # Structure: {log_session_dir}/subagents/{subagent_id}/live_logs/log_*/turn_1/attempt_1/events.jsonl
        try:
            log_dir = get_log_session_dir().resolve()  # Resolve to absolute path
            debug_lines.append(f"log_dir: {log_dir}")

            subagent_logs = log_dir / "subagents" / self._subagent.id
            debug_lines.append(f"subagent_logs: {subagent_logs}")
            debug_lines.append(f"subagent_logs.exists(): {subagent_logs.exists()}")

            # Check live_logs first (symlinked during run)
            live_logs = subagent_logs / "live_logs"
            debug_lines.append(f"live_logs: {live_logs}")
            debug_lines.append(f"live_logs.exists(): {live_logs.exists()}")

            if live_logs.exists():
                log_subdirs = list(live_logs.glob("log_*"))
                debug_lines.append(f"log_subdirs: {log_subdirs}")
                for log_subdir in sorted(log_subdirs, reverse=True):
                    candidate = log_subdir / "turn_1" / "attempt_1" / "events.jsonl"
                    debug_lines.append(f"checking candidate: {candidate}")
                    if candidate.exists():
                        events_file = candidate
                        debug_lines.append(f"FOUND events_file (live_logs): {events_file}")
                        break

            # Fall back to full_logs (after completion)
            if not events_file:
                full_logs = subagent_logs / "full_logs"
                debug_lines.append(f"full_logs: {full_logs}")
                debug_lines.append(f"full_logs.exists(): {full_logs.exists()}")
                if full_logs.exists():
                    candidate = full_logs / "turn_1" / "attempt_1" / "events.jsonl"
                    debug_lines.append(f"checking full_logs candidate: {candidate}")
                    if candidate.exists():
                        events_file = candidate
                        debug_lines.append(f"FOUND events_file (full_logs): {events_file}")

        except Exception as e:
            debug_lines.append(f"Error finding events: {e}")

        debug_lines.append(f"Final events_file: {events_file}")
        debug_lines.append(f"events_file exists: {events_file.exists() if events_file else 'N/A'}")

        # Write debug log via shared logger
        try:
            for line in debug_lines:
                tui_log(f"[SubagentTuiModal] {line}")
        except Exception:
            pass

        if events_file and events_file.exists():
            self._event_reader = EventReader(events_file)
            self._content_processor = ContentProcessor()

    def _load_initial_events(self) -> None:
        """Load all existing events and build timeline."""
        if not self._event_reader or not self._content_processor:
            # Show empty state
            try:
                timeline = self.query_one("#subagent-timeline", TimelineSection)
                timeline.mount(Static("No events available yet...", classes="empty-timeline"))
            except Exception as e:
                tui_log(f"[SubagentTuiModal] {e}")
            return

        events = self._event_reader.read_all()
        self._process_events(events)

    def _process_events(self, events: list[MassGenEvent]) -> None:
        """Process events and add widgets to timeline."""
        if not self._content_processor:
            return

        try:
            timeline = self.query_one("#subagent-timeline", TimelineSection)

            for event in events:
                output = self._content_processor.process_event(event, self._round_number)
                if output:
                    outputs = output if isinstance(output, list) else [output]
                    for item in outputs:
                        # Update round number from round_start events
                        if item.output_type == "separator" and item.round_number:
                            self._round_number = item.round_number
                        self._apply_output_to_timeline(timeline, item)

            # Flush any remaining batch
            final_output = self._content_processor.flush_pending_batch(self._round_number)
            if final_output:
                self._apply_output_to_timeline(timeline, final_output)

        except Exception as e:
            tui_log(f"[SubagentTuiModal] {e}")

    def _apply_output_to_timeline(self, timeline: TimelineSection, output: ContentOutput) -> None:
        """Apply a ContentOutput to the timeline.

        This method translates ContentOutput objects into TimelineSection calls,
        providing visual parity with the main TUI.

        Args:
            timeline: The TimelineSection to add content to
            output: The ContentOutput from ContentProcessor
        """
        round_number = output.round_number or self._round_number

        if output.output_type == "tool" and output.tool_data:
            self._tool_count += 1
            tool_data = output.tool_data

            # Handle batch actions
            batch_action = output.batch_action

            if batch_action in ("pending", "standalone"):
                # Add as standalone tool card
                timeline.add_tool(tool_data, round_number=round_number)
            elif batch_action == "convert_to_batch" and output.batch_id and output.pending_tool_id:
                # Convert pending tool to batch
                timeline.convert_tool_to_batch(
                    output.pending_tool_id,
                    tool_data,
                    output.batch_id,
                    output.server_name or "tools",
                    round_number=round_number,
                )
            elif batch_action == "add_to_batch" and output.batch_id:
                # Add to existing batch
                timeline.add_tool_to_batch(output.batch_id, tool_data)
            elif batch_action == "update_batch":
                # Update tool in batch
                timeline.update_tool_in_batch(tool_data.tool_id, tool_data)
            elif batch_action == "update_standalone":
                # Update standalone tool
                timeline.update_tool(tool_data.tool_id, tool_data)
            else:
                # Default: add as standalone
                timeline.add_tool(tool_data, round_number=round_number)

        elif output.output_type == "tool_batch":
            # Handle pre-batched tools
            if output.batch_tools:
                self._tool_count += len(output.batch_tools)
                batch_id = output.batch_id or f"batch_{self._tool_count}"
                server_name = output.server_name or "tools"

                timeline.add_batch(batch_id, server_name, round_number=round_number)

                for tool_data in output.batch_tools:
                    timeline.add_tool_to_batch(batch_id, tool_data)
                    if tool_data.status in ("success", "error"):
                        timeline.update_tool_in_batch(tool_data.tool_id, tool_data)

        elif output.output_type == "thinking":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "thinking-inline",
                    round_number=round_number,
                )

        elif output.output_type == "text":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "content-inline",
                    round_number=round_number,
                )

        elif output.output_type == "status":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "status",
                    round_number=round_number,
                )

        elif output.output_type == "presentation":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "response",
                    round_number=round_number,
                )

        elif output.output_type == "injection":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "injection",
                    round_number=round_number,
                )

        elif output.output_type == "reminder":
            if output.text_content:
                timeline.add_text(
                    output.text_content,
                    style=output.text_style,
                    text_class=output.text_class or "reminder",
                    round_number=round_number,
                )

        elif output.output_type == "separator":
            self._round_number = output.round_number
            timeline.add_separator(
                output.separator_label,
                round_number=output.round_number,
                subtitle=output.separator_subtitle,
            )

        elif output.output_type == "final_answer":
            self._final_answer = output.text_content
            if output.text_content:
                card = SubagentFinalAnswerCard(content=output.text_content, id="final_answer_card")
                timeline.mount(card)

        # Update status ribbon after adding content
        self._update_status_ribbon()

    def _poll_updates(self) -> None:
        """Poll for status and event updates."""
        # Update status if callback available
        if self._status_callback:
            new_data = self._status_callback(self._subagent.id)
            if new_data:
                self._subagent = new_data
                self._refresh_header()

        # Read new events
        if self._event_reader and self._content_processor:
            new_events = self._event_reader.get_new_events()
            if new_events:
                self._process_events(new_events)

        # Stop polling if completed
        if self._subagent.status not in ("running", "pending"):
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None

    def _refresh_header(self) -> None:
        """Refresh header content."""
        try:
            self.query_one("#modal-title", Static).update(self._build_title())
            self.query_one("#modal-status", Static).update(self._build_status())
            self.query_one("#metadata", Static).update(self._build_metadata())
        except Exception as e:
            tui_log(f"[SubagentTuiModal] {e}")

    def _update_status_ribbon(self) -> None:
        """Update the status ribbon."""
        try:
            self.query_one("#status-ribbon", Static).update(self._build_status_ribbon())
        except Exception as e:
            tui_log(f"[SubagentTuiModal] {e}")

    def _build_title(self) -> Text:
        """Build the modal title."""
        text = Text()
        text.append("Subagent: ", style="")
        text.append(self._subagent.id, style="bold #7c3aed")
        return text

    def _build_status(self) -> Text:
        """Build the status indicator."""
        text = Text()
        icon = self.STATUS_ICONS.get(self._subagent.status, "○")
        color = self.STATUS_COLORS.get(self._subagent.status, "#8b949e")
        text.append(f"{icon} {self._subagent.status.capitalize()}", style=f"bold {color}")
        return text

    def _build_metadata(self) -> Text:
        """Build the metadata row."""
        text = Text()

        # Task preview
        task = self._subagent.task
        if len(task) > 80:
            task = task[:77] + "..."
        text.append(task, style="#8b949e")

        return text

    def _build_nav_text(self) -> Text:
        """Build navigation text for multiple subagents."""
        text = Text()
        text.append(f" {self._current_index + 1}/{len(self._all_subagents)} ", style="#8b949e")
        return text

    def _build_status_ribbon(self) -> Text:
        """Build the status ribbon with richer metrics."""
        text = Text()

        # Status icon
        icon = self.STATUS_ICONS.get(self._subagent.status, "○")
        color = self.STATUS_COLORS.get(self._subagent.status, "#8b949e")
        text.append(f"{icon} {self._subagent.status.capitalize()}", style=f"{color}")
        text.append(" │ ", style="dim")

        # Round number
        text.append(f"Round {self._round_number}", style="#8b949e")
        text.append(" │ ", style="dim")

        # Duration
        text.append(f"{self._subagent.elapsed_seconds:.1f}s", style="#8b949e")
        text.append(" │ ", style="dim")

        # Tool count
        text.append(f"{self._tool_count} tools", style="#8b949e")

        # Progress
        if self._subagent.progress_percent > 0:
            text.append(" │ ", style="dim")
            text.append(f"{self._subagent.progress_percent}%", style="#8b949e")

        return text

    def _switch_subagent(self, index: int) -> None:
        """Switch to a different subagent."""
        if 0 <= index < len(self._all_subagents):
            self._current_index = index
            self._subagent = self._all_subagents[index]

            # Reset state
            self._tool_count = 0
            self._round_number = 1
            self._final_answer = None
            self._content_processor = ContentProcessor()

            # Re-initialize event reader
            self._init_event_reader()

            # Clear and reload timeline
            try:
                timeline = self.query_one("#subagent-timeline", TimelineSection)
                timeline.clear()
                self._load_initial_events()
            except Exception as e:
                tui_log(f"[SubagentTuiModal] {e}")

            # Refresh header
            self._refresh_header()

            # Update nav text
            try:
                self.query_one("#nav-text", Static).update(self._build_nav_text())
            except Exception as e:
                tui_log(f"[SubagentTuiModal] {e}")

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
        content = self._final_answer or self._subagent.answer_preview
        if content:
            try:
                import pyperclip

                pyperclip.copy(content)
                self.notify("Answer copied to clipboard!")
            except ImportError:
                self.notify("pyperclip not installed - cannot copy", severity="warning")
            except Exception as e:
                self.notify(f"Failed to copy: {e}", severity="error")
