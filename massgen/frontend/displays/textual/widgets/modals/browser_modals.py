"""Browser-related modals: Answer browser, Timeline, Browser tabs, Workspace browser."""

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import (
        Container,
        Horizontal,
        ScrollableContainer,
        VerticalScroll,
    )
    from textual.widgets import Button, Label, Select, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from massgen.filesystem_manager._constants import SKIP_DIRS_FOR_LOGGING

from ....shared.tui_debug import tui_debug_enabled, tui_log
from ..modal_base import BaseModal

# Additional patterns to skip in workspace view
WORKSPACE_SKIP_PATTERNS = [
    re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"),  # UUID
    re.compile(r"^\d{8}_\d{6}_\d+$"),  # Timestamp directories like 20260122_123456_789012
    re.compile(r"^agent_[a-z]$"),  # agent_a, agent_b, etc.
    re.compile(r"^subagent_"),  # subagent workspaces
]


def _should_skip_dir(name: str) -> bool:
    """Check if a directory should be skipped in workspace view."""
    if name in SKIP_DIRS_FOR_LOGGING:
        return True
    for pattern in WORKSPACE_SKIP_PATTERNS:
        if pattern.match(name):
            return True
    return False


def render_file_preview(file_path: Path, max_lines: int = 100) -> tuple:
    """Render a file preview with syntax highlighting if possible.

    Returns:
        Tuple of (renderable, is_rich) where is_rich indicates if it's a Rich object
    """
    try:
        from rich.markdown import Markdown
        from rich.syntax import Syntax

        if not file_path.exists():
            return ("[red]File not found[/]", False)

        # Check file size
        size = file_path.stat().st_size
        if size > 100000:  # 100KB limit
            return (f"[yellow]File too large ({size:,} bytes)[/]", False)

        # Determine file type
        suffix = file_path.suffix.lower()
        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Limit lines
        lines = content.split("\n")
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines]) + f"\n\n... ({len(lines) - max_lines} more lines)"

        # Use syntax highlighting for code files
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".html": "html",
            ".css": "css",
            ".sh": "bash",
            ".bash": "bash",
            ".md": "markdown",
            ".sql": "sql",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }

        if suffix == ".md":
            return (Markdown(content), True)
        elif suffix in lang_map:
            return (Syntax(content, lang_map[suffix], theme="monokai", line_numbers=True), True)
        else:
            return (content, False)

    except Exception as e:
        return (f"[red]Error reading file: {e}[/]", False)


class AnswerBrowserModal(BaseModal):
    """Modal for browsing all answers with filtering and details."""

    def __init__(
        self,
        answers: list[dict[str, Any]],
        votes: list[dict[str, Any]],
        agent_ids: list[str],
        winner_agent_id: str | None = None,
    ):
        super().__init__()
        self.answers = answers
        self.votes = votes
        self.agent_ids = agent_ids
        self.winner_agent_id = winner_agent_id
        self._current_filter: str | None = None  # None = all agents
        self._selected_answer_idx: int = 0  # Start with first (most recent after sorting)
        self._filtered_answers: list[dict[str, Any]] = []
        self._selected_content: str = ""  # Store selected answer content for copy
        self._render_count: int = 0  # Counter for unique widget IDs to avoid DuplicateIds

    def compose(self) -> ComposeResult:
        with Container(id="answer_browser_container"):
            yield Label("📋 Answer Browser", id="answer_browser_header")

            # Summary stats
            total_answers = len(self.answers)
            total_votes = len(self.votes)
            yield Label(
                f"{total_answers} answers • {total_votes} votes",
                id="answer_browser_summary",
            )

            # Agent filter
            with Horizontal(id="answer_filter_row"):
                yield Label("Filter: ", id="filter_label")
                options = [("All Agents", None)] + [(aid, aid) for aid in self.agent_ids]
                yield Select(options, id="agent_filter", value=None)

            # Main content area with answer list and detail panel
            with Horizontal(id="answer_browser_content"):
                # Answer list (left side - 40%)
                yield VerticalScroll(id="answer_list")

                # Answer detail panel (right side - 60%)
                with Container(id="answer_detail_panel"):
                    yield Label("📄 Answer Details", id="answer_detail_header")
                    yield ScrollableContainer(id="answer_detail_scroll")
                    with Horizontal(id="answer_detail_buttons"):
                        yield Button("📋 Copy", id="copy_answer_button", classes="action-primary")
                        yield Button("💾 Save to File", id="save_answer_button")

            # Close button
            with Horizontal(id="answer_browser_buttons"):
                yield Button("Close (ESC)", id="close_browser_button")

    def on_mount(self) -> None:
        """Called when modal is mounted - populate the answer list."""
        self._render_answers()
        # Auto-select most recent answer (now first in sorted list)
        if self._filtered_answers:
            self._show_answer_detail(0)

    def _render_answers(self) -> None:
        """Render the answer list based on current filter."""
        # Increment render counter to ensure unique IDs
        self._render_count += 1

        answer_list = self.query_one("#answer_list", VerticalScroll)
        answer_list.remove_children()

        self._filtered_answers = self.answers.copy()
        if self._current_filter:
            self._filtered_answers = [a for a in self.answers if a["agent_id"] == self._current_filter]

        # Sort by timestamp descending (most recent first)
        self._filtered_answers.sort(key=lambda a: a.get("timestamp", 0), reverse=True)

        if not self._filtered_answers:
            answer_list.mount(Static("[dim]No answers yet[/]", markup=True))
            return

        for idx, answer in enumerate(self._filtered_answers):
            agent_id = answer["agent_id"]
            model = answer.get("model", "")
            answer_label = answer.get("answer_label", f"{agent_id}.{answer.get('answer_number', 1)}")
            timestamp = answer.get("timestamp", 0)
            is_winner = answer.get("is_winner", False) or agent_id == self.winner_agent_id

            # Format timestamp
            time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else ""

            # Build display
            badge = ""
            if is_winner:
                badge = " [bold yellow]🏆[/]"
            elif answer.get("is_final"):
                badge = " [bold green]✓[/]"

            agent_display = f"{agent_id}" + (f" ({model})" if model else "")

            # Count votes for this agent
            vote_count = len([v for v in self.votes if v["voted_for"] == agent_id])

            # Build content preview (shorter for list view)
            content = answer.get("content", "")
            content_preview = content[:60] + "..." if len(content) > 60 else content
            content_preview = content_preview.replace("\n", " ")

            # Determine if this is selected
            is_selected = idx == self._selected_answer_idx
            selected_class = "answer-item-selected" if is_selected else ""

            # Assign color class based on agent index (1-8 to match AgentPanel colors)
            agent_idx = self.agent_ids.index(agent_id) + 1 if agent_id in self.agent_ids else 1
            agent_color_class = f"agent-color-{((agent_idx - 1) % 8) + 1}"  # Cycle through colors 1-8

            # Use render_count in ID to ensure uniqueness across re-renders
            item = Static(
                f"[bold]{answer_label}[/] - {agent_display}{badge}\n" f"   [dim]{time_str} • {vote_count} votes[/]\n" f"   {content_preview}",
                classes=f"answer-item clickable {selected_class} {agent_color_class}",
                markup=True,
                id=f"answer_item_{self._render_count}_{idx}",
            )
            answer_list.mount(item)

    def _show_answer_detail(self, idx: int) -> None:
        """Show full content of selected answer in detail panel."""
        if idx < 0 or idx >= len(self._filtered_answers):
            return

        self._selected_answer_idx = idx
        answer = self._filtered_answers[idx]

        agent_id = answer["agent_id"]
        model = answer.get("model", "")
        answer_label = answer.get("answer_label", f"{agent_id}.{answer.get('answer_number', 1)}")
        timestamp = answer.get("timestamp", 0)
        is_winner = answer.get("is_winner", False) or agent_id == self.winner_agent_id
        content = answer.get("content", "")

        # Store for copy
        self._selected_content = content

        # Format timestamp
        time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""

        # Build header
        badge = ""
        if is_winner:
            badge = " 🏆 WINNER"
        elif answer.get("is_final"):
            badge = " ✓ FINAL"

        vote_count = len([v for v in self.votes if v["voted_for"] == agent_id])

        # Update header
        header = self.query_one("#answer_detail_header", Label)
        header.update(f"📄 {answer_label} - {agent_id} ({model}){badge}")

        # Update content in scroll container
        detail_scroll = self.query_one("#answer_detail_scroll", ScrollableContainer)
        detail_scroll.remove_children()

        # Add metadata
        meta_text = f"[dim]Time: {time_str} | Votes: {vote_count}[/]\n\n"

        # Add full content with proper formatting
        # Use render_count in ID to ensure uniqueness across re-renders
        detail_scroll.mount(Static(meta_text + content, markup=True, id=f"answer_content_{self._render_count}"))

        # Re-render answer list to update selection highlighting
        self._render_answers()

    def on_click(self, event) -> None:
        """Handle click on answer items."""
        # Use event.widget (Textual) not event.target
        target = getattr(event, "widget", None)
        if target is None:
            return
        # Walk up to find answer-item
        while target and not (hasattr(target, "classes") and "answer-item" in target.classes):
            target = target.parent

        if target and hasattr(target, "id") and target.id and target.id.startswith("answer_item_"):
            # ID format is "answer_item_{render_count}_{idx}", extract idx from last part
            parts = target.id.split("_")
            idx = int(parts[-1]) if parts else 0
            self._show_answer_detail(idx)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle agent filter change."""
        self._current_filter = event.value
        self._selected_answer_idx = 0
        self._render_answers()
        if self._filtered_answers:
            self._show_answer_detail(len(self._filtered_answers) - 1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_browser_button":
            self.dismiss()
        elif event.button.id == "copy_answer_button":
            self._copy_to_clipboard()
        elif event.button.id == "save_answer_button":
            self._save_to_file()

    def _copy_to_clipboard(self) -> None:
        """Copy selected answer content to clipboard."""
        import platform
        import subprocess

        if not self._selected_content:
            self.notify("No answer selected", severity="warning")
            return

        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["pbcopy"], input=self._selected_content.encode(), check=True)
            elif system == "Windows":
                subprocess.run(["clip"], input=self._selected_content.encode(), check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=self._selected_content.encode(), check=True)
            self.notify("Copied to clipboard!", severity="information")
        except Exception as e:
            self.notify(f"Copy failed: {e}", severity="error")

    def _save_to_file(self) -> None:
        """Save selected answer to file."""
        if not self._selected_content:
            self.notify("No answer selected", severity="warning")
            return

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            answer = self._filtered_answers[self._selected_answer_idx]
            label = answer.get("answer_label", "answer")
            filename = f"answer_{label}_{timestamp}.txt"

            with open(filename, "w") as f:
                f.write(self._selected_content)
            self.notify(f"Saved to {filename}", severity="information")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    def key_up(self) -> None:
        """Navigate to previous answer."""
        if self._selected_answer_idx > 0:
            self._show_answer_detail(self._selected_answer_idx - 1)

    def key_down(self) -> None:
        """Navigate to next answer."""
        if self._selected_answer_idx < len(self._filtered_answers) - 1:
            self._show_answer_detail(self._selected_answer_idx + 1)


class TimelineModal(BaseModal):
    """Modal showing ASCII timeline visualization of answers and votes with swimlane layout."""

    def __init__(
        self,
        answers: list[dict[str, Any]],
        votes: list[dict[str, Any]],
        agent_ids: list[str],
        winner_agent_id: str | None = None,
        restart_history: list[dict[str, Any]] | None = None,
    ):
        super().__init__()
        self.answers = answers
        self.votes = votes
        self.agent_ids = agent_ids
        self.winner_agent_id = winner_agent_id
        self.restart_history = restart_history or []

    def compose(self) -> ComposeResult:
        with Container(id="timeline_modal_container"):
            yield Label("📊 Timeline - Answer & Vote Flow", id="timeline_header")
            yield Label(
                "○ answer  ◇ vote  ★ winner  ⟿ context  🔄 restart",
                id="timeline_legend",
            )
            with VerticalScroll(id="timeline_content"):
                yield Static(self._render_swimlane_timeline(), id="timeline_diagram", markup=True)
            yield Button("Close (ESC)", id="close_timeline_button")

    def _render_swimlane_timeline(self) -> str:
        """Render swimlane-style ASCII timeline visualization."""
        # Get unique agents from answers and votes
        seen = set()
        all_agents = []
        for aid in self.agent_ids:
            if aid not in seen:
                seen.add(aid)
                all_agents.append(aid)
        for a in self.answers:
            if a["agent_id"] not in seen:
                seen.add(a["agent_id"])
                all_agents.append(a["agent_id"])

        if not all_agents:
            return "[dim]No activity yet[/]"

        # Calculate column widths (min 12 chars per agent)
        col_width = 14
        num_agents = len(all_agents)

        # Collect all events with timestamps
        events = []

        # Add restart events
        for restart in self.restart_history:
            events.append(
                {
                    "type": "restart",
                    "timestamp": restart.get("timestamp", 0),
                    "attempt": restart.get("attempt", 1),
                    "max_attempts": restart.get("max_attempts", 3),
                    "reason": restart.get("reason", ""),
                },
            )

        for answer in self.answers:
            events.append(
                {
                    "type": "answer",
                    "agent_id": answer["agent_id"],
                    "label": answer.get("answer_label", ""),
                    "timestamp": answer.get("timestamp", 0),
                    "is_winner": answer.get("is_winner", False) or answer["agent_id"] == self.winner_agent_id,
                    "is_final": answer.get("is_final", False),
                    "context_sources": answer.get("context_sources", []),
                },
            )

        for vote in self.votes:
            # Use voted_for_label (e.g., "1.2") if available, otherwise fall back to agent number
            target_label = vote.get("voted_for_label")
            if target_label:
                # Convert "agent1.2" format to shorter "1.2" format
                target_display = target_label.replace("agent", "")
            else:
                # Fallback: try to get agent number from voted_for
                voted_for = vote["voted_for"]
                if voted_for in all_agents:
                    agent_num = all_agents.index(voted_for) + 1
                    target_display = str(agent_num)
                else:
                    target_display = voted_for[:6]
            events.append(
                {
                    "type": "vote",
                    "agent_id": vote["voter"],
                    "target": target_display,
                    "timestamp": vote.get("timestamp", 0),
                },
            )

        # Sort by timestamp (most recent first for display)
        events.sort(key=lambda e: e.get("timestamp", 0), reverse=True)

        if not events:
            return "[dim]No activity yet[/]"

        # Build swimlane visualization
        lines = []

        # Header row with agent names
        header = ""
        for agent in all_agents:
            short_name = agent[: col_width - 2].center(col_width)
            header += f"[bold cyan]{short_name}[/]"
        lines.append(header)

        # Separator
        lines.append("─" * (col_width * num_agents))

        # Event rows
        for event in events:
            ts = event.get("timestamp", 0)
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "??:??"

            if event["type"] == "restart":
                # Full-width restart indicator
                attempt = event.get("attempt", 1)
                max_att = event.get("max_attempts", 3)
                reason = event.get("reason", "")[:30]
                restart_line = f"[bold yellow]{'─' * 10} 🔄 RESTART {attempt}/{max_att}: {reason} {'─' * 10}[/]"
                lines.append(restart_line)
                continue

            # Build row with proper placement
            row = ""
            for agent in all_agents:
                cell = " " * col_width

                if event["type"] == "answer" and event["agent_id"] == agent:
                    label = event.get("label", "?")[:6]
                    # Format context sources if present
                    ctx = event.get("context_sources", [])
                    ctx_str = ""
                    if ctx:
                        # Show which answers this agent saw (e.g., ←A1.1)
                        short_ctx = [c.replace("agent", "A")[:4] for c in ctx[:1]]
                        ctx_str = f"[dim cyan]←{','.join(short_ctx)}[/]"

                    if event.get("is_winner"):
                        cell = f" [bold yellow]★{label}[/]{ctx_str}"
                    elif event.get("is_final"):
                        cell = f" [yellow]★{label}[/]{ctx_str}"
                    else:
                        cell = f" [green]○{label}[/]{ctx_str}"

                elif event["type"] == "vote" and event["agent_id"] == agent:
                    target = event.get("target", "?")[:6]
                    cell = f" [magenta]◇→{target}[/]"

                # Pad cell to column width (Rich markup doesn't count toward visible width)
                # Just add trailing spaces - the markup handling will work
                row += cell.ljust(col_width + 20)[: col_width + 20]  # Extra for markup

            # Add timestamp at end
            lines.append(f"{row} [dim]{time_str}[/]")

        # Separator
        lines.append("─" * (col_width * num_agents))

        # Summary
        answer_count = len([e for e in events if e["type"] == "answer"])
        vote_count = len([e for e in events if e["type"] == "vote"])
        restart_count = len([e for e in events if e["type"] == "restart"])

        summary_parts = [f"{answer_count} answers", f"{vote_count} votes"]
        if restart_count:
            summary_parts.append(f"{restart_count} restarts")
        if self.winner_agent_id:
            summary_parts.append(f"Winner: {self.winner_agent_id}")

        lines.append(f"[dim]{' • '.join(summary_parts)}[/]")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_timeline_button":
            self.dismiss()


class BrowserTabsModal(BaseModal):
    """Unified browser modal with tabs for Answers, Votes, Workspace, and Timeline."""

    BINDINGS = [
        Binding("1", "tab_answers", "Answers"),
        Binding("2", "tab_votes", "Votes"),
        Binding("3", "tab_workspace", "Workspace"),
        Binding("4", "tab_timeline", "Timeline"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(
        self,
        answers: list[dict[str, Any]],
        votes: list[dict[str, Any]],
        vote_counts: dict[str, int],
        agent_ids: list[str],
        winner_agent_id: str | None = None,
        initial_tab: str = "timeline",
    ):
        super().__init__()
        self.answers = answers
        self.votes = votes
        self.vote_counts = vote_counts
        self.agent_ids = agent_ids
        self.winner_agent_id = winner_agent_id
        self._current_tab = initial_tab

    def compose(self) -> ComposeResult:
        with Container(id="browser_tabs_container"):
            yield Label(
                self._build_tab_bar_text(),
                id="browser_tab_bar",
            )
            with VerticalScroll(id="browser_content"):
                yield Static(self._render_current_tab(), id="browser_content_text", markup=True)
            yield Button("Close (ESC)", id="close_browser_button")

    def _build_tab_bar_text(self) -> str:
        """Build tab bar text with correct highlight for current tab."""
        tabs = ["answers", "votes", "workspace", "timeline"]
        tab_labels = ["Answers", "Votes", "Workspace", "Timeline"]
        parts = []
        for i, (t, label) in enumerate(zip(tabs, tab_labels), 1):
            if t == self._current_tab:
                parts.append(f"[bold reverse] {i} {label} [/]")
            else:
                parts.append(f"[bold]{i}[/] {label}")
        return "  ".join(parts)

    def _render_current_tab(self) -> str:
        """Render content for the current tab."""
        if self._current_tab == "answers":
            return self._render_answers_tab()
        elif self._current_tab == "votes":
            return self._render_votes_tab()
        elif self._current_tab == "workspace":
            return self._render_workspace_tab()
        elif self._current_tab == "timeline":
            return self._render_timeline_tab()
        return ""

    def _format_duration(self, timestamp: float) -> str:
        """Format elapsed time since timestamp."""
        elapsed = time.time() - timestamp
        if elapsed < 60:
            return f"{int(elapsed)}s"
        elif elapsed < 3600:
            return f"{elapsed/60:.1f}m"
        else:
            return f"{elapsed/3600:.1f}h"

    def _render_answers_tab(self) -> str:
        """Render answers list."""
        if not self.answers:
            return "[dim]No answers yet[/]"

        lines = ["[bold cyan]📝 Answers[/]", "─" * 50]

        for i, answer in enumerate(self.answers, 1):
            agent = answer.get("agent_id", "?")[:12]
            model = answer.get("model", "")[:15]
            label = answer.get("answer_label", f"#{i}")
            is_winner = answer.get("is_winner", False) or answer.get("agent_id") == self.winner_agent_id

            badge = " [bold yellow]🏆[/]" if is_winner else ""
            model_info = f" ({model})" if model else ""

            # Duration since answer was submitted
            timestamp = answer.get("timestamp")
            duration_info = f" [dim]({self._format_duration(timestamp)} ago)[/]" if timestamp else ""

            # Content preview
            content = answer.get("content", "")[:60].replace("\n", " ")
            if len(answer.get("content", "")) > 60:
                content += "..."

            lines.append(f"  {i}. [bold]{agent}[/]{model_info} - {label}{badge}{duration_info}")
            lines.append(f"     [dim]{content}[/]")

        return "\n".join(lines)

    def _render_votes_tab(self) -> str:
        """Render vote distribution and individual votes."""
        lines = ["[bold cyan]🗳️ Votes[/]", "─" * 50]

        # Vote distribution
        if self.vote_counts:
            non_zero = {k: v for k, v in self.vote_counts.items() if v > 0}
            if non_zero:
                max_votes = max(non_zero.values())
                total = sum(non_zero.values())
                lines.append("\n[bold]Distribution:[/]")
                for agent, count in sorted(non_zero.items(), key=lambda x: -x[1]):
                    bar_width = int((count / max_votes) * 15) if max_votes > 0 else 0
                    bar = "█" * bar_width + "░" * (15 - bar_width)
                    prefix = "🏆 " if count == max_votes else "   "
                    pct = (count / total * 100) if total > 0 else 0
                    lines.append(f"{prefix}{agent[:10]:10} {bar} {count} ({pct:.0f}%)")

        # Individual votes
        if self.votes:
            lines.append("\n[bold]Vote History:[/]")
            for i, vote in enumerate(self.votes, 1):
                voter = vote.get("voter", "?")[:10]
                target = vote.get("voted_for", "?")[:10]
                timestamp = vote.get("timestamp")
                duration_info = f" [dim]({self._format_duration(timestamp)} ago)[/]" if timestamp else ""
                lines.append(f"  {i}. [dim]{voter}[/] → [bold]{target}[/]{duration_info}")
        elif not self.vote_counts:
            lines.append("[dim]No votes yet[/]")

        return "\n".join(lines)

    def _render_workspace_tab(self) -> str:
        """Render workspace info summary."""
        if not self.answers:
            return "[dim]No workspaces available yet[/]\n\n[dim]Tip: Press 'w' to browse current workspace[/]"

        lines = ["[bold cyan]📁 Workspaces[/]", "─" * 50]
        lines.append("[dim]Press 'w' for full workspace browser with file preview[/]\n")

        for i, answer in enumerate(self.answers, 1):
            agent = answer.get("agent_id", "?")[:12]
            workspace = answer.get("workspace_path", "")

            if workspace:
                if os.path.isdir(workspace):
                    try:
                        file_count = sum(1 for f in os.listdir(workspace) if os.path.isfile(os.path.join(workspace, f)))
                        lines.append(f"  {i}. [bold]{agent}[/]: {file_count} files")
                    except Exception:
                        lines.append(f"  {i}. [bold]{agent}[/]: [dim]path unavailable[/]")
                else:
                    lines.append(f"  {i}. [bold]{agent}[/]: [dim]no workspace[/]")
            else:
                lines.append(f"  {i}. [bold]{agent}[/]: [dim]no workspace[/]")

        return "\n".join(lines)

    def _render_timeline_tab(self) -> str:
        """Render swimlane-style timeline visualization (like WebUI)."""
        # Get unique agents
        seen = set()
        all_agents = []
        for aid in self.agent_ids:
            if aid not in seen:
                seen.add(aid)
                all_agents.append(aid)
        for a in self.answers:
            if a["agent_id"] not in seen:
                seen.add(a["agent_id"])
                all_agents.append(a["agent_id"])

        if not all_agents:
            return "[dim]No activity yet[/dim]"

        # Collect all events with timestamps
        events = []

        for answer in self.answers:
            events.append(
                {
                    "type": "answer",
                    "agent_id": answer["agent_id"],
                    "label": answer.get("answer_label", ""),
                    "timestamp": answer.get("timestamp", 0),
                    "is_winner": answer.get("is_winner", False) or answer["agent_id"] == self.winner_agent_id,
                    "context_sources": answer.get("context_sources", []),
                },
            )

        for vote in self.votes:
            events.append(
                {
                    "type": "vote",
                    "agent_id": vote["voter"],
                    "target": vote.get("voted_for", "?")[:6],
                    "timestamp": vote.get("timestamp", 0),
                },
            )

        events.sort(key=lambda e: e.get("timestamp", 0), reverse=True)

        if not events:
            return "[dim]No activity yet[/]"

        # Build swimlane visualization
        col_width = 14
        num_agents = len(all_agents)
        lines = []

        # Header
        header = ""
        for agent in all_agents:
            short_name = agent[: col_width - 2].center(col_width)
            header += f"[bold cyan]{short_name}[/]"
        lines.append(header)
        lines.append("─" * (col_width * num_agents))

        # Events
        for event in events[:15]:  # Limit for performance
            ts = event.get("timestamp", 0)
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "??:??"

            row = ""
            for agent in all_agents:
                cell = " " * col_width
                if event["type"] == "answer" and event["agent_id"] == agent:
                    label = event.get("label", "?")[:6]
                    if event.get("is_winner"):
                        cell = f" [bold yellow]★{label}[/]"
                    else:
                        cell = f" [green]○{label}[/]"
                elif event["type"] == "vote" and event["agent_id"] == agent:
                    target = event.get("target", "?")[:6]
                    cell = f" [magenta]◇→{target}[/]"
                row += cell.ljust(col_width + 20)[: col_width + 20]

            lines.append(f"{row} [dim]{time_str}[/]")

        lines.append("─" * (col_width * num_agents))

        return "\n".join(lines)

    def _switch_tab(self, tab: str) -> None:
        """Switch to a different tab."""
        self._current_tab = tab
        try:
            content = self.query_one("#browser_content_text", Static)
            content.update(self._render_current_tab())

            # Update tab bar to show active tab
            tab_bar = self.query_one("#browser_tab_bar", Label)
            tab_bar.update(self._build_tab_bar_text())
        except Exception:
            pass

    def action_tab_answers(self) -> None:
        """Switch to answers tab."""
        self._switch_tab("answers")

    def action_tab_votes(self) -> None:
        """Switch to votes tab."""
        self._switch_tab("votes")

    def action_tab_workspace(self) -> None:
        """Switch to workspace tab."""
        self._switch_tab("workspace")

    def action_tab_timeline(self) -> None:
        """Switch to timeline tab."""
        self._switch_tab("timeline")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_browser_button":
            self.dismiss()


class WorkspaceBrowserModal(BaseModal):
    """Modal for browsing workspace files from answer snapshots."""

    # Special indices for workspace types
    CURRENT_WORKSPACE_IDX = -100
    FINAL_WORKSPACE_IDX = -200  # Final workspace (after consensus)
    _MAX_SCAN_FILES = 400
    _MAX_SCAN_DEPTH = 6

    def __init__(
        self,
        answers: list[dict[str, Any]],
        agent_ids: list[str],
        agent_workspace_paths: dict[str, str] | None = None,
        agent_final_paths: dict[str, str] | None = None,
        default_agent: str | None = None,
        default_to_final: bool = False,
    ):
        super().__init__()
        self.answers = answers
        self.agent_ids = agent_ids
        self.agent_workspace_paths = agent_workspace_paths or {}
        self.agent_final_paths = agent_final_paths or {}

        # Auto-default to final if final workspaces exist (unless explicitly disabled)
        # Final workspace is the most useful view after a turn completes
        self._default_to_final = default_to_final or bool(self.agent_final_paths)

        # Default to specified agent or first agent
        selected_agent = default_agent if default_agent and default_agent in agent_ids else (agent_ids[0] if agent_ids else None)

        # Determine default selection based on preferences
        # Priority: Final workspace > Current workspace > Most recent answer
        if self._default_to_final and selected_agent and selected_agent in self.agent_final_paths:
            self._selected_answer_idx: int = self.FINAL_WORKSPACE_IDX
        elif selected_agent and selected_agent in self.agent_workspace_paths:
            self._selected_answer_idx: int = self.CURRENT_WORKSPACE_IDX
        else:
            self._selected_answer_idx: int = len(answers) - 1 if answers else 0

        self._current_files: list[dict[str, Any]] = []
        self._selected_file_idx: int = 0
        self._load_counter: int = 0  # Counter to ensure unique widget IDs
        self._current_workspace_path: str | None = None  # Track currently displayed workspace
        self._tree_lines: list[tuple] = []  # Store tree structure for click handling
        self._expanded_dirs: set[str] = set()  # Track which directories are expanded
        self._dir_file_counts: dict[str, int] = {}  # Track file counts per directory
        # Default to specified agent or first agent
        self._current_agent_filter: str | None = selected_agent  # None = all agents
        self._timing_debug = tui_debug_enabled() and os.environ.get("MASSGEN_TUI_TIMING_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def compose(self) -> ComposeResult:
        with Container(id="workspace_browser_container"):
            yield Label("Workspace Browser", id="workspace_browser_header")

            # Selector row with agent filter and answer selector
            with Horizontal(id="workspace_selector_row"):
                # Agent filter (no "All Agents" - must pick one)
                with Horizontal(id="workspace_agent_filter_container"):
                    yield Label("Agent: ", id="workspace_agent_label")
                    # Default to first agent
                    default_agent = self.agent_ids[0] if self.agent_ids else None
                    agent_options = [(aid, aid) for aid in self.agent_ids]
                    if not agent_options:
                        agent_options = [("No agents", None)]
                    yield Select(agent_options, id="agent_filter_selector", value=default_agent)

                # Answer selector
                with Horizontal(id="workspace_answer_container"):
                    yield Label("Answer: ", id="workspace_answer_label")
                    yield Select([], id="answer_selector")  # Populated in on_mount

            # Split view: file list on left, preview on right
            with Horizontal(id="workspace_split"):
                # File list
                with Container(id="workspace_file_list_container"):
                    yield Label("[bold]Files[/]", id="file_list_header", markup=True)
                    yield VerticalScroll(id="workspace_file_list")

                # File preview
                with Container(id="workspace_preview_container"):
                    yield Label("[bold]Preview[/]", id="preview_header", markup=True)
                    yield VerticalScroll(id="workspace_preview")

            # Footer buttons
            with Horizontal(id="workspace_browser_footer"):
                yield Button("Open in Finder", id="open_workspace_finder_button")
                yield Button("Close (ESC)", id="close_workspace_browser_button")

    def on_mount(self) -> None:
        """Called when modal is mounted - populate the answer selector and files."""
        self._update_answer_selector()
        # Load files for the default selection (final, current, or most recent answer)
        if self._default_to_final and self._current_agent_filter and self._current_agent_filter in self.agent_final_paths:
            self._load_workspace_files(self.FINAL_WORKSPACE_IDX)
        elif self._current_agent_filter and self._current_agent_filter in self.agent_workspace_paths:
            self._load_workspace_files(self.CURRENT_WORKSPACE_IDX)
        elif self.answers:
            self._load_workspace_files(len(self.answers) - 1)

    def _update_answer_selector(self) -> None:
        """Update answer selector options based on current agent filter."""
        answer_selector = self.query_one("#answer_selector", Select)

        # Build answer options
        options = []

        # Add "Final Workspace" option FIRST if the selected agent has a final workspace
        if self._current_agent_filter and self._current_agent_filter in self.agent_final_paths:
            options.append(("Final Workspace", self.FINAL_WORKSPACE_IDX))

        # Add "Current Workspace" option if the selected agent has a current workspace
        if self._current_agent_filter and self._current_agent_filter in self.agent_workspace_paths:
            options.append(("Current Workspace", self.CURRENT_WORKSPACE_IDX))

        # Filter answers by agent
        if self._current_agent_filter:
            for i, a in enumerate(self.answers):
                if a["agent_id"] == self._current_agent_filter:
                    label = a.get("answer_label", f"Answer {i+1}")
                    options.append((f"{label}", i))

        if not options:
            options = [("No workspace available", -1)]

        # Determine default value - prefer final workspace if requested, else current
        if self._default_to_final and self._current_agent_filter and self._current_agent_filter in self.agent_final_paths:
            default_value = self.FINAL_WORKSPACE_IDX
        elif self._current_agent_filter and self._current_agent_filter in self.agent_workspace_paths:
            default_value = self.CURRENT_WORKSPACE_IDX
        elif options and options[0][1] != -1:
            # Pick the most recent answer for this agent
            default_value = options[-1][1] if len(options) > 1 else options[0][1]
        else:
            default_value = -1

        # Update selector
        answer_selector.set_options(options)
        if default_value in [opt[1] for opt in options]:
            answer_selector.value = default_value
        elif options:
            answer_selector.value = options[0][1]

    def _load_workspace_files(self, answer_idx: int) -> None:
        """Load files from the workspace path of the selected answer, current, or final workspace."""
        started = time.perf_counter()
        file_list = self.query_one("#workspace_file_list", VerticalScroll)
        preview = self.query_one("#workspace_preview", VerticalScroll)
        file_list.remove_children()
        preview.remove_children()
        preview.mount(Static("[dim]Select a file to preview[/]", markup=True))
        self._current_files = []
        self._selected_file_idx = -1
        self._tree_lines = []  # Reset tree structure
        self._expanded_dirs = set()  # Reset expanded state
        self._dir_file_counts = {}  # Reset file counts
        self._load_counter += 1  # Increment to ensure unique IDs

        # Determine workspace path based on selection
        workspace_path = None
        if answer_idx == self.FINAL_WORKSPACE_IDX:
            # Final workspace (after consensus)
            workspace_path = self.agent_final_paths.get(self._current_agent_filter)
        elif answer_idx == self.CURRENT_WORKSPACE_IDX:
            # Current workspace (live)
            workspace_path = self.agent_workspace_paths.get(self._current_agent_filter)
        elif answer_idx >= 0 and answer_idx < len(self.answers):
            # Answer snapshot
            answer = self.answers[answer_idx]
            workspace_path = answer.get("workspace_path")
        else:
            self._current_workspace_path = None
            file_list.mount(Static("[dim]No workspace selected[/]", markup=True))
            return

        # Store current workspace path for "Open in Finder" functionality
        self._current_workspace_path = workspace_path

        if not workspace_path or not os.path.isdir(workspace_path):
            file_list.mount(Static(f"[dim]No workspace available[/]\n[dim]{workspace_path or 'N/A'}[/]", markup=True))
            return

        # List files in workspace (bounded for responsiveness)
        try:
            files, truncated = self._scan_workspace_files(workspace_path)
            self._current_files = files

            if not self._current_files:
                file_list.mount(Static("[dim]Workspace is empty[/]", markup=True))
                return

            # Build tree structure for display
            self._tree_lines = self._build_file_tree(self._current_files)
            for idx, (display_text, file_idx) in enumerate(self._tree_lines):
                # Use idx (tree line index) for unique widget IDs, not file_idx
                # (multiple directories would have file_idx=-1 causing duplicates)
                file_list.mount(
                    Static(
                        display_text,
                        id=f"file_item_{self._load_counter}_{idx}",
                        classes="workspace-file-item",
                        markup=True,
                    ),
                )

            if truncated:
                file_list.mount(
                    Static(
                        f"[dim]... showing first {self._MAX_SCAN_FILES} files[/]",
                        markup=True,
                    ),
                )
            else:
                file_list.mount(Static("[dim]Select a file to preview[/]", markup=True))

        except Exception as e:
            file_list.mount(Static(f"[red]Error: {e}[/]", markup=True))
        finally:
            if self._timing_debug:
                tui_log(
                    "[TIMING] WorkspaceBrowserModal._load_workspace_files " f"{(time.perf_counter() - started) * 1000.0:.1f}ms " f"files={len(self._current_files)} workspace={workspace_path}",
                )

    def _scan_workspace_files(self, workspace_path: str) -> tuple[list[dict[str, Any]], bool]:
        """Return a bounded, filtered file listing for a workspace."""
        files: list[dict[str, Any]] = []
        truncated = False
        for root, dirs, filenames in os.walk(workspace_path, topdown=True):
            # Skip hidden/ignored directories and enforce a max traversal depth.
            rel_root = os.path.relpath(root, workspace_path)
            depth = 0 if rel_root == "." else len(rel_root.split(os.sep))
            dirs[:] = [d for d in dirs if not d.startswith(".") and not _should_skip_dir(d) and depth < self._MAX_SCAN_DEPTH]
            if depth >= self._MAX_SCAN_DEPTH:
                filenames = []

            for fname in filenames:
                if fname.startswith("."):
                    continue
                if len(files) >= self._MAX_SCAN_FILES:
                    truncated = True
                    break
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, workspace_path)
                try:
                    stat = os.stat(full_path)
                    files.append(
                        {
                            "name": fname,
                            "rel_path": rel_path,
                            "full_path": full_path,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        },
                    )
                except OSError:
                    pass
            if truncated:
                break
        return sorted(files, key=lambda f: f["rel_path"]), truncated

    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size // 1024}KB"
        else:
            return f"{size // (1024 * 1024)}MB"

    def _build_file_tree(self, files: list[dict[str, Any]]) -> list[tuple]:
        """Build tree-style display for files with collapsible directories.

        Returns:
            List of (display_text, file_idx_or_dir_name) tuples
            - file_idx >= 0: clickable file
            - file_idx == -1: non-clickable item
            - file_idx is str starting with "dir:": clickable directory toggle
        """
        # Group files by directory
        dir_files: dict[str, list[tuple]] = {}  # dir -> [(filename, size, file_idx), ...]
        root_files: list[tuple] = []  # [(filename, size, file_idx), ...]

        for idx, f in enumerate(files):
            rel_path = f["rel_path"]
            size_str = self._format_size(f["size"])

            if "/" in rel_path or "\\" in rel_path:
                # Has directory component
                parts = rel_path.replace("\\", "/").split("/")
                dir_name = parts[0]
                file_name = "/".join(parts[1:])
                if dir_name not in dir_files:
                    dir_files[dir_name] = []
                dir_files[dir_name].append((file_name, size_str, idx))
            else:
                root_files.append((rel_path, size_str, idx))

        # Store file counts for auto-collapse logic
        self._dir_file_counts = {d: len(f) for d, f in dir_files.items()}

        result = []

        # Add directories with their files
        sorted_dirs = sorted(dir_files.keys())
        for i, dir_name in enumerate(sorted_dirs):
            is_last_dir = (i == len(sorted_dirs) - 1) and not root_files
            dir_connector = "└── " if is_last_dir else "├── "

            dir_file_list = dir_files[dir_name]
            file_count = len(dir_file_list)

            # Auto-expand directories with <= 3 files, collapse others
            is_expanded = dir_name in self._expanded_dirs
            if file_count <= 3 and dir_name not in self._expanded_dirs:
                # Auto-expand small directories (unless explicitly collapsed)
                is_expanded = True
                self._expanded_dirs.add(dir_name)

            # Directory header with expand/collapse indicator
            arrow = "▼" if is_expanded else "▶"
            count_hint = f" ({file_count})" if not is_expanded else ""
            result.append(
                (
                    f"[bold cyan]{dir_connector}{arrow} {dir_name}/{count_hint}[/]",
                    f"dir:{dir_name}",  # Special marker for directory toggle
                ),
            )

            # Only show files if expanded
            if is_expanded:
                for j, (file_name, size_str, file_idx) in enumerate(dir_file_list):
                    is_last_file = j == len(dir_file_list) - 1
                    prefix = "    " if is_last_dir else "│   "
                    file_connector = "└── " if is_last_file else "├── "
                    result.append((f"{prefix}{file_connector}[cyan]{file_name}[/] [dim]({size_str})[/]", file_idx))

        # Add root-level files
        for i, (file_name, size_str, file_idx) in enumerate(root_files):
            is_last = i == len(root_files) - 1
            connector = "└── " if is_last else "├── "
            result.append((f"{connector}[cyan]{file_name}[/] [dim]({size_str})[/]", file_idx))

        return result

    def _preview_file(self, file_idx: int) -> None:
        """Preview the selected file with syntax highlighting."""
        preview = self.query_one("#workspace_preview", VerticalScroll)
        preview.remove_children()

        if file_idx < 0 or file_idx >= len(self._current_files):
            preview.mount(Static("[dim]Select a file to preview[/]", markup=True))
            return

        f = self._current_files[file_idx]
        full_path = Path(f["full_path"])

        # Add file header
        header = Static(
            f"[bold cyan]{f['rel_path']}[/]\n[dim]{'─' * 40}[/]",
            markup=True,
        )
        preview.mount(header)

        # Use render_file_preview for syntax highlighting
        renderable, is_rich = render_file_preview(full_path)

        if is_rich:
            # Rich object (Syntax or Markdown)
            preview.mount(Static(renderable))
        else:
            # Plain text or error message
            preview.mount(Static(str(renderable), markup=True))

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle agent filter or answer selection change."""
        if event.select.id == "agent_filter_selector":
            # Agent filter changed - update answer selector options
            self._current_agent_filter = event.value
            self._update_answer_selector()
            # Auto-load files for the new default answer (current workspace or most recent)
            answer_selector = self.query_one("#answer_selector", Select)
            if answer_selector.value is not None and isinstance(answer_selector.value, int):
                self._load_workspace_files(answer_selector.value)
        elif event.select.id == "answer_selector":
            # Answer selection changed - load files
            answer_idx = event.value
            if isinstance(answer_idx, int):
                self._selected_answer_idx = answer_idx
                self._load_workspace_files(answer_idx)

    def on_click(self, event) -> None:
        """Handle click on file items and directory toggles."""
        # Check if clicked on a file item
        if hasattr(event, "widget") and event.widget:
            widget_id = getattr(event.widget, "id", "")
            # ID format is: file_item_{load_counter}_{tree_line_idx}
            if widget_id and widget_id.startswith("file_item_"):
                try:
                    # Get the tree line index from widget ID
                    tree_idx = int(widget_id.split("_")[-1])
                    # Look up the actual file index from tree_lines
                    if self._tree_lines and 0 <= tree_idx < len(self._tree_lines):
                        item_data = self._tree_lines[tree_idx][1]

                        # Check if it's a directory toggle
                        if isinstance(item_data, str) and item_data.startswith("dir:"):
                            dir_name = item_data[4:]  # Remove "dir:" prefix
                            self._toggle_directory(dir_name)
                            return

                        # Skip non-clickable items
                        if item_data == -1:
                            return

                        # It's a file - preview it
                        file_idx = item_data
                        self._selected_file_idx = file_idx
                        self._preview_file(file_idx)
                except (ValueError, IndexError):
                    pass

    def _toggle_directory(self, dir_name: str) -> None:
        """Toggle directory expansion and refresh the file list."""
        if dir_name in self._expanded_dirs:
            self._expanded_dirs.remove(dir_name)
        else:
            self._expanded_dirs.add(dir_name)
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        """Refresh the file list display without reloading files."""
        if not self._current_files:
            return

        try:
            file_list = self.query_one("#workspace_file_list", VerticalScroll)
            file_list.remove_children()
            self._load_counter += 1

            # Rebuild tree with current expansion state
            self._tree_lines = self._build_file_tree(self._current_files)
            for idx, (display_text, item_data) in enumerate(self._tree_lines):
                file_list.mount(
                    Static(
                        display_text,
                        id=f"file_item_{self._load_counter}_{idx}",
                        classes="workspace-file-item",
                        markup=True,
                    ),
                )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_workspace_browser_button":
            self.dismiss()
        elif event.button.id == "open_workspace_finder_button":
            self._open_workspace_in_explorer()

    def _open_workspace_in_explorer(self) -> None:
        """Open the current workspace directory in the system file explorer."""
        import platform
        import subprocess

        if not self._current_workspace_path:
            self.notify("No workspace selected", severity="warning", timeout=2)
            return

        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.run(["open", str(self._current_workspace_path)])
            elif system == "Windows":
                subprocess.run(["explorer", str(self._current_workspace_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(self._current_workspace_path)])
        except Exception as e:
            self.notify(f"Error opening workspace: {e}", severity="error", timeout=3)
