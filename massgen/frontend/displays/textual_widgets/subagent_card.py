# -*- coding: utf-8 -*-
"""
Subagent Card Widget for MassGen TUI.

Horizontal overview for spawned subagents with per-agent columns.
Shows a compact summary line and recent tool context for each subagent,
and opens the subagent view on click.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static

from massgen.frontend.displays.content_handlers import format_tool_display_name
from massgen.subagent.models import SubagentDisplayData, SubagentResult


@dataclass
class _ToolCache:
    path: Optional[Path]
    size: int
    tools: List[str]


@dataclass
class _PlanCache:
    path: Optional[Path]
    mtime: float
    summary: Optional[str]


class SubagentColumn(Vertical, can_focus=True):
    """Single subagent column inside the overview card."""

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        subagent: SubagentDisplayData,
        all_subagents: List[SubagentDisplayData],
        summary: str,
        tools: List[str],
        open_callback: Callable[[SubagentDisplayData, List[SubagentDisplayData]], None],
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id)
        self._subagent = subagent
        self._all_subagents = all_subagents
        self._summary = summary
        self._tools = tools
        self._open_callback = open_callback
        self._pulse_frame = 0

    def compose(self) -> ComposeResult:
        yield Static("", classes="agent-header", id="agent_header")
        yield Static("", classes="task-description", id="task_desc")
        yield Static("", classes="progress-bar", id="progress_bar")
        yield Static("", classes="summary-line", id="summary_line")
        yield Static("", classes="tool-current", id="tool_current")
        yield Static("", classes="tool-recent", id="tool_recent_1")
        yield Static("", classes="tool-recent", id="tool_recent_2")

    def on_mount(self) -> None:
        self._update_display()

    def on_resize(self) -> None:
        # Reflow progress bars to use the current column width.
        self._update_display()

    def on_click(self) -> None:
        self._open_callback(self._subagent, self._all_subagents)

    def update_content(self, subagent: SubagentDisplayData, summary: str, tools: List[str]) -> None:
        self._subagent = subagent
        self._summary = summary
        self._tools = tools
        self._update_display()

    def _update_display(self) -> None:
        header = self._build_header()
        task_desc = self._build_task_description()
        progress = self._build_progress_bar()
        summary = self._summary or ""
        current_tool, recent_tools = self._split_tools(self._tools)

        try:
            self.query_one("#agent_header", Static).update(header)
            self._set_line("#task_desc", task_desc)
            self.query_one("#progress_bar", Static).update(progress)
            self._set_line("#summary_line", summary)
            self._set_line("#tool_current", current_tool)
            self._set_line("#tool_recent_1", recent_tools[0] if recent_tools else "")
            self._set_line("#tool_recent_2", recent_tools[1] if len(recent_tools) > 1 else "")
        except Exception:
            pass

    def _set_line(self, selector: str, content: str | Text) -> None:
        widget = self.query_one(selector, Static)
        widget.update(content)
        plain = content.plain if isinstance(content, Text) else str(content)
        if plain.strip():
            widget.remove_class("is-empty")
        else:
            widget.add_class("is-empty")

    def advance_pulse(self) -> None:
        """Advance pulse animation frame (called by parent card)."""
        if self._subagent.status == "running":
            self._pulse_frame = (self._pulse_frame + 1) % 3

    def _build_header(self) -> Text:
        """Build header: status icon + name + elapsed time + click arrow."""
        text = Text()
        icon, style = SubagentCard.status_icon_and_style(self._subagent.status)

        # Pulsing icon for running state
        if self._subagent.status == "running":
            pulse_icons = ["●", "◉", "○"]
            icon = pulse_icons[self._pulse_frame]

        label = self._truncate(self._subagent.id, 20)
        text.append(f"{icon} ", style=style)
        text.append(label, style=style)

        # Right-align elapsed time + click arrow
        elapsed = int(self._subagent.elapsed_seconds)
        suffix_parts = []
        if elapsed > 0:
            if elapsed >= 60:
                suffix_parts.append(f"{elapsed // 60}m{elapsed % 60:02d}s")
            else:
                suffix_parts.append(f"{elapsed}s")

        suffix = " ".join(suffix_parts)
        arrow = " ▸"
        name_len = len(label) + 2  # icon + space + label
        total_suffix = len(suffix) + len(arrow)
        padding = max(1, 28 - name_len - total_suffix)
        text.append(" " * padding)
        if suffix:
            text.append(suffix, style="#8b949e")
        text.append(arrow, style="dim #6e7681")

        return text

    def _build_task_description(self) -> Text:
        """Build task description row (truncated)."""
        task = self._subagent.task or ""
        if not task:
            return Text("")

        # On completion, show answer preview instead
        if self._subagent.status == "completed" and self._subagent.answer_preview:
            preview = self._subagent.answer_preview.strip()
            if len(preview) > 300:
                preview = preview[:297] + "..."
            text = Text()
            text.append("✓ ", style="#7ee787")
            text.append(preview, style="#7ee787 dim")
            return text

        truncated = task if len(task) <= 60 else task[:57] + "..."
        return Text(truncated, style="#c9d1d9")

    def _build_progress_bar(self) -> Text:
        """Build progress bar with thin lines and color transitions."""
        elapsed = self._subagent.elapsed_seconds
        timeout = self._subagent.timeout_seconds
        status = self._subagent.status

        if status == "completed":
            text = Text()
            bar_width = self._measure_progress_bar_width()
            text.append("━" * bar_width, style="bold #7ee787")
            return text
        elif status in ("error", "failed"):
            text = Text()
            bar_width = self._measure_progress_bar_width()
            text.append("━" * bar_width, style="bold #f85149")
            return text
        elif status == "timeout":
            text = Text()
            bar_width = self._measure_progress_bar_width()
            text.append("━" * bar_width, style="bold #d29922")
            return text

        if timeout <= 0:
            return Text("")

        # Keep running state below 100% until terminal status is confirmed.
        ratio = min(max(elapsed / timeout, 0.0), 0.99)
        percent_text = f" {int(ratio * 100)}%"
        bar_width = self._measure_progress_bar_width(len(percent_text))
        filled = int(ratio * bar_width)
        empty = bar_width - filled

        # Color shifts by progress
        if ratio < 0.33:
            fill_style = "#a371f7"
        elif ratio < 0.66:
            fill_style = "#58a6ff"
        else:
            fill_style = "#39c5cf"

        text = Text()
        text.append("━" * filled, style=fill_style)
        text.append("─" * empty, style="dim #30363d")
        text.append(percent_text, style="dim #8b949e")
        return text

    def _measure_progress_bar_width(self, suffix_width: int = 0) -> int:
        """Measure available characters for the bar body, excluding optional suffix text."""
        candidate_widths: List[int] = []

        try:
            progress_widget = self.query_one("#progress_bar", Static)
            if progress_widget.size.width > 0:
                candidate_widths.append(progress_widget.size.width)
        except Exception:
            pass

        if self.size.width > 0:
            candidate_widths.append(max(0, self.size.width - 2))

        if candidate_widths:
            available = max(candidate_widths)
        else:
            available = 20 + suffix_width

        return max(8, available - max(0, suffix_width))

    def _split_tools(self, tools: List[str]) -> Tuple[str, List[str]]:
        if not tools:
            return "", []
        current = f"› {tools[0]}"
        recent = [f"  {t}" for t in tools[1:3]]
        return current, recent

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."


class SubagentCard(Vertical, can_focus=True):
    """Overview card displaying spawned subagents with per-agent columns."""

    BINDINGS = [
        ("enter", "open_selected", "Open"),
        ("left", "focus_prev_column", "Previous"),
        ("right", "focus_next_column", "Next"),
        ("h", "focus_prev_column", "Previous"),
        ("l", "focus_next_column", "Next"),
    ]

    class OpenModal(Message):
        """Message posted when user clicks to open subagent view."""

        def __init__(self, subagent: SubagentDisplayData, all_subagents: List[SubagentDisplayData]) -> None:
            self.subagent = subagent
            self.all_subagents = all_subagents
            super().__init__()

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    STATUS_ICONS = {
        "completed": "✓",
        "running": "●",
        "pending": "○",
        "error": "✗",
        "timeout": "⏱",
        "failed": "✗",
    }

    STATUS_STYLES = {
        "completed": "#7ee787",
        "running": "bold #a371f7",
        "pending": "#6e7681",
        "error": "#f85149",
        "timeout": "#d29922",
        "failed": "#f85149",
    }

    POLL_INTERVAL = 0.5

    _IGNORED_TOOL_NAMES = {
        "new_answer",
        "final_answer",
    }

    def __init__(
        self,
        subagents: Optional[List[SubagentDisplayData]] = None,
        tool_call_id: Optional[str] = None,
        status_callback: Optional[Callable[[str], Optional[SubagentDisplayData]]] = None,
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id)
        self._subagents = subagents or []
        self._tool_call_id = tool_call_id
        self._status_callback = status_callback
        self._poll_timer: Optional[Timer] = None
        self._tool_cache: Dict[str, _ToolCache] = {}
        self._plan_cache: Dict[str, _PlanCache] = {}
        self._columns: Dict[str, SubagentColumn] = {}
        self._selected_index = 0
        # Track start times for elapsed computation
        self._start_times: Dict[str, float] = {}
        now = time.monotonic()
        for sa in self._subagents:
            if sa.status in ("running", "pending"):
                self._start_times[sa.id] = now - sa.elapsed_seconds
            else:
                self._start_times[sa.id] = now - sa.elapsed_seconds

    def compose(self) -> ComposeResult:
        yield Static(self._build_card_header(), id="subagent-card-title")
        with ScrollableContainer(id="subagent-scroll"):
            with Horizontal(id="subagent-columns"):
                for sa in self._subagents:
                    summary = self._get_summary_line(sa)
                    tools = self._get_tool_lines(sa)
                    column = SubagentColumn(
                        subagent=sa,
                        all_subagents=self._subagents,
                        summary=summary,
                        tools=tools,
                        open_callback=self._request_open,
                        id=f"subagent_col_{sa.id}",
                    )
                    self._columns[sa.id] = column
                    yield column

    def on_mount(self) -> None:
        self.add_class("variant-a")
        self._start_polling_if_needed()
        # Entrance animation
        self.add_class("appearing")
        self.set_timer(0.05, self._complete_appearance)

    def _complete_appearance(self) -> None:
        self.remove_class("appearing")
        self.add_class("appeared")

    def _build_card_header(self) -> Text:
        """Build compact status summary header with aggregate counts."""
        running = sum(1 for sa in self._subagents if sa.status in {"running", "pending"})
        completed = sum(1 for sa in self._subagents if sa.status == "completed")
        failed = sum(1 for sa in self._subagents if sa.status in {"failed", "error", "timeout"})
        text = Text()
        text.append("⬡ ", style="bold #7c3aed")
        text.append("Subagents", style="bold #e6edf3")

        if running:
            text.append(f"  {running} active", style="bold #a371f7")
        if completed:
            text.append(f"  {completed} done", style="bold #7ee787")
        if failed:
            text.append(f"  {failed} issues", style="bold #f85149")

        all_done = self._subagents and running == 0
        if all_done and failed == 0:
            text.append("  ✓", style="bold #7ee787")
        return text

    def on_unmount(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

    def _request_open(self, subagent: SubagentDisplayData, all_subagents: List[SubagentDisplayData]) -> None:
        try:
            self._selected_index = self._subagents.index(subagent)
        except ValueError:
            pass
        self.post_message(self.OpenModal(subagent, all_subagents))

    def _start_polling_if_needed(self) -> None:
        if self._poll_timer is not None:
            return
        if any(sa.status in ("running", "pending") for sa in self._subagents):
            self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_status)

    def _poll_status(self) -> None:
        updated = False
        new_subagents: List[SubagentDisplayData] = []

        if self._status_callback:
            for sa in self._subagents:
                if sa.status in ("running", "pending"):
                    new_data = self._status_callback(sa.id)
                    if new_data:
                        new_subagents.append(new_data)
                        updated = True
                    else:
                        new_subagents.append(sa)
                else:
                    new_subagents.append(sa)
            if updated:
                self._subagents = new_subagents

        # Update elapsed_seconds from wall clock for running subagents
        now = time.monotonic()
        for sa in self._subagents:
            if sa.status in ("running", "pending") and sa.id in self._start_times:
                sa.elapsed_seconds = now - self._start_times[sa.id]

        # Advance pulse frames for running columns
        for sa in self._subagents:
            col = self._columns.get(sa.id)
            if col:
                col.advance_pulse()

        # Refresh header (status summary changes as subagents complete)
        try:
            self.query_one("#subagent-card-title", Static).update(self._build_card_header())
        except Exception:
            pass

        # Always refresh tool lines for running subagents
        if any(sa.status in ("running", "pending") for sa in self._subagents):
            self._refresh_columns()
        else:
            # All subagents finished — apply completed styling
            self.add_class("all-completed")
            self._refresh_columns()
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None

    def _refresh_columns(self) -> None:
        try:
            columns_container = self.query_one("#subagent-columns", Horizontal)
        except Exception:
            return

        if len(self._columns) != len(self._subagents) or any(sa.id not in self._columns for sa in self._subagents):
            columns_container.remove_children()
            self._columns = {}
            for sa in self._subagents:
                summary = self._get_summary_line(sa)
                tools = self._get_tool_lines(sa)
                column = SubagentColumn(
                    subagent=sa,
                    all_subagents=self._subagents,
                    summary=summary,
                    tools=tools,
                    open_callback=self._request_open,
                    id=f"subagent_col_{sa.id}",
                )
                self._columns[sa.id] = column
                columns_container.mount(column)
            return

        for sa in self._subagents:
            column = self._columns.get(sa.id)
            if column:
                summary = self._get_summary_line(sa)
                tools = self._get_tool_lines(sa)
                column.update_content(sa, summary, tools)

    def _get_summary_line(self, sa: SubagentDisplayData) -> str:
        plan_summary = self._get_plan_summary(sa)
        if plan_summary:
            return plan_summary

        status_label = sa.status
        if status_label == "completed":
            status_label = "done"
        elif status_label == "failed":
            status_label = "failed"
        elif status_label == "timeout":
            status_label = "timeout"

        return status_label

    def _get_plan_summary(self, sa: SubagentDisplayData) -> Optional[str]:
        if not sa.workspace_path:
            return None
        workspace = Path(sa.workspace_path)
        plan_path = workspace / "tasks" / "plan.json"
        if not plan_path.exists():
            return None

        try:
            mtime = plan_path.stat().st_mtime
        except (OSError, IOError):
            return None

        cached = self._plan_cache.get(sa.id)
        if cached and cached.path == plan_path and cached.mtime == mtime:
            return cached.summary

        summary = None
        try:
            data = json.loads(plan_path.read_text())
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            total = len(tasks)
            if total > 0:
                completed = sum(1 for t in tasks if t.get("status") in ("completed", "verified"))
                summary = f"{completed}/{total} done"
        except (OSError, IOError, json.JSONDecodeError, TypeError):
            summary = None

        self._plan_cache[sa.id] = _PlanCache(path=plan_path, mtime=mtime, summary=summary)
        return summary

    def _get_tool_lines(self, sa: SubagentDisplayData) -> List[str]:
        events_path = self._resolve_events_path(sa)
        if not events_path or not events_path.exists():
            return []

        try:
            size = events_path.stat().st_size
        except (OSError, IOError):
            return []

        cached = self._tool_cache.get(sa.id)
        if cached and cached.path == events_path and cached.size == size:
            return cached.tools

        tools = self._extract_tools_from_events(events_path)
        self._tool_cache[sa.id] = _ToolCache(path=events_path, size=size, tools=tools)
        return tools

    def _resolve_events_path(self, sa: SubagentDisplayData) -> Optional[Path]:
        if not sa.log_path:
            return None
        log_path = Path(sa.log_path)
        if not log_path.is_absolute():
            log_path = (Path.cwd() / log_path).resolve()
        if log_path.is_dir():
            resolved = SubagentResult.resolve_events_path(log_path)
            return Path(resolved) if resolved else None
        return log_path

    def _extract_tools_from_events(self, path: Path, max_tools: int = 3) -> List[str]:
        try:
            tail_lines: deque[str] = deque(maxlen=200)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.strip():
                        tail_lines.append(line)
        except (OSError, IOError):
            return []

        tools: List[str] = []
        seen: set[str] = set()

        for line in reversed(tail_lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("event_type") != "stream_chunk":
                continue

            chunk = (event.get("data") or {}).get("chunk") or {}
            if chunk.get("type") != "tool_calls":
                continue

            for tc in reversed(chunk.get("tool_calls") or []):
                name = (tc.get("function") or {}).get("name")
                if not name or name in self._IGNORED_TOOL_NAMES:
                    continue
                display_name = format_tool_display_name(name)
                if display_name in seen:
                    continue
                tools.append(self._truncate(display_name, 26))
                seen.add(display_name)
                if len(tools) >= max_tools:
                    return tools

        return tools

    @staticmethod
    def status_icon_and_style(status: str) -> Tuple[str, str]:
        icon = SubagentCard.STATUS_ICONS.get(status, "○")
        style = SubagentCard.STATUS_STYLES.get(status, "#6e7681")
        return icon, style

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    @property
    def subagents(self) -> List[SubagentDisplayData]:
        return self._subagents

    @property
    def tool_call_id(self) -> Optional[str]:
        """Tool call identifier used to correlate start/complete lifecycle updates."""
        return self._tool_call_id

    def update_subagents(self, subagents: List[SubagentDisplayData]) -> None:
        self._subagents = subagents
        self._refresh_columns()
        self._start_polling_if_needed()

    def update_subagent(self, subagent_id: str, data: SubagentDisplayData) -> None:
        for i, sa in enumerate(self._subagents):
            if sa.id == subagent_id:
                self._subagents[i] = data
                break
        self._refresh_columns()

    def set_status_callback(self, callback: Callable[[str], Optional[SubagentDisplayData]]) -> None:
        self._status_callback = callback
        self._start_polling_if_needed()

    def action_open_selected(self) -> None:
        if not self._subagents:
            return
        selected = self._subagents[self._selected_index % len(self._subagents)]
        self._request_open(selected, self._subagents)

    def action_focus_prev_column(self) -> None:
        if not self._subagents:
            return
        self._selected_index = (self._selected_index - 1) % len(self._subagents)
        self._focus_column(self._selected_index)

    def action_focus_next_column(self) -> None:
        if not self._subagents:
            return
        self._selected_index = (self._selected_index + 1) % len(self._subagents)
        self._focus_column(self._selected_index)

    def _focus_column(self, index: int) -> None:
        try:
            sa = self._subagents[index]
            column = self._columns.get(sa.id)
            if column:
                column.focus()
        except (IndexError, KeyError):
            pass

    @classmethod
    def from_spawn_result(
        cls,
        result: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        status_callback: Optional[Callable[[str], Optional[SubagentDisplayData]]] = None,
    ) -> "SubagentCard":
        subagents = []
        spawned = result.get("results", result.get("spawned_subagents", result.get("subagents", [])))
        for sa_data in spawned:
            subagents.append(
                SubagentDisplayData(
                    id=sa_data.get("subagent_id", sa_data.get("id", "unknown")),
                    task=sa_data.get("task", ""),
                    status=sa_data.get("status", "running"),
                    progress_percent=0,
                    elapsed_seconds=sa_data.get("execution_time_seconds", 0.0),
                    timeout_seconds=sa_data.get("timeout_seconds", 300),
                    workspace_path=sa_data.get("workspace", ""),
                    workspace_file_count=0,
                    last_log_line="",
                    error=sa_data.get("error"),
                    answer_preview=(sa_data.get("answer", "") or "")[:200] or None,
                    log_path=sa_data.get("log_path"),
                ),
            )
        return cls(subagents=subagents, tool_call_id=tool_call_id, status_callback=status_callback)
