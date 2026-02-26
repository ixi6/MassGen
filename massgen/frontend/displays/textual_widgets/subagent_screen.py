"""
Full-Screen Subagent View for MassGen TUI.

Replaces the small modal overlay with a full-screen subagent view that
looks and behaves like the main TUI using inheritance to share code.

Design:
```
+---------------------------------------------------------------------+
| <- Back | Subagent: bio_agent                  | Model: gpt-4o      |
+---------------------------------------------------------------------+
| [bio_agent] [data_agent] [research_agent]                           |
+---------------------------------------------------------------------+
| R1 * R2 * F                     | 5:30 | 2.4k | $0.003              |
+---------------------------------------------------------------------+
|                                                                     |
| [Timeline content - tools, thinking, text, etc.]                    |
|                                                                     |
+---------------------------------------------------------------------+
| * Running...                                                        |
+---------------------------------------------------------------------+
|               [Copy Answer]  [Back to Main]                         |
+---------------------------------------------------------------------+
```

Features:
- Full-screen layout with TUI parity
- Tab bar for multiple subagents (reuses AgentTabBar)
- Status ribbon with round navigation (reuses AgentStatusRibbon)
- Live updates while subagent is running
- Keyboard shortcuts (Esc to close, Tab for agent switching)
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.widgets import Button, Input, Static

from massgen.events import EventReader, MassGenEvent
from massgen.subagent.models import SubagentDisplayData, SubagentResult

from ..base_tui_layout import BaseTUILayoutMixin
from ..shared.tui_debug import tui_log
from ..tui_event_pipeline import TimelineEventAdapter
from .agent_status_ribbon import AgentStatusRibbon
from .content_sections import FinalPresentationCard, TimelineSection
from .queued_input_banner import QueuedInputBanner
from .tab_bar import AgentTabBar, AgentTabChanged, SessionInfoClicked

logger = logging.getLogger(__name__)


class SubagentHeader(Horizontal):
    """Header bar for subagent screen with back button and subagent info."""

    class ContextPathClicked(Message):
        """Emitted when a context path link is clicked."""

        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    DEFAULT_CSS = """
    SubagentHeader {
        dock: top;
        height: 1;
        background: $surface;
        padding: 0 2;
    }

    SubagentHeader .back-button {
        width: auto;
        min-width: 8;
        height: 1;
        border: none;
        background: transparent;
        color: $text-muted;
        margin-right: 1;
    }

    SubagentHeader .back-button:hover {
        color: $primary;
        text-style: bold;
    }

    SubagentHeader .subagent-title {
        width: 1fr;
        color: $primary;
        text-style: bold;
    }

    SubagentHeader #header_context_paths {
        width: auto;
    }

    SubagentHeader .context-path-btn {
        width: auto;
        color: $text-muted;
        min-width: 1;
        height: 1;
        border: none;
        background: transparent;
        margin-left: 1;
    }

    SubagentHeader .context-path-btn:hover {
        color: $primary;
        text-style: underline;
    }
    """

    def __init__(
        self,
        subagent: SubagentDisplayData,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._subagent = subagent
        self._context_button_map: dict[str, str] = {}
        self._context_btn_generation: int = 0

    def compose(self) -> ComposeResult:
        yield Button("← Back", classes="back-button", id="back_btn")
        yield Static(f"Subagent: {self._subagent.id}", classes="subagent-title", id="header_title")
        yield Horizontal(id="header_context_paths")

    def on_mount(self) -> None:
        self._refresh_context_path_buttons()

    @staticmethod
    def _normalize_context_paths(raw_paths: Any) -> list[str]:
        if not raw_paths:
            return []
        if not isinstance(raw_paths, list):
            raw_paths = [raw_paths]

        normalized: list[str] = []
        seen: set[str] = set()
        for entry in raw_paths:
            path_value = ""
            if isinstance(entry, str):
                path_value = entry.strip()
            elif isinstance(entry, dict):
                candidate = entry.get("path")
                if candidate is not None:
                    path_value = str(candidate).strip()
            elif entry is not None:
                path_value = str(entry).strip()

            if not path_value or path_value in seen:
                continue
            seen.add(path_value)
            normalized.append(path_value)

        return normalized

    @staticmethod
    def _format_context_label(path: str) -> str:
        path_obj = Path(path)
        label = path_obj.name or path
        return f"📂 {label}"

    def _refresh_context_path_buttons(self) -> None:
        try:
            container = self.query_one("#header_context_paths", Horizontal)
        except Exception:
            return

        self._context_button_map = {}
        self._context_btn_generation += 1
        gen = self._context_btn_generation
        container.remove_children()

        context_paths = self._normalize_context_paths(getattr(self._subagent, "context_paths", []))
        for index, path in enumerate(context_paths):
            button_id = f"context_path_btn_{gen}_{index}"
            self._context_button_map[button_id] = path
            container.mount(
                Button(
                    self._format_context_label(path),
                    id=button_id,
                    classes="context-path-btn",
                ),
            )

    def update_subagent(self, subagent: SubagentDisplayData) -> None:
        """Update the header for a new subagent."""
        self._subagent = subagent
        try:
            self.query_one("#header_title", Static).update(f"Subagent: {subagent.id}")
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")
        self._refresh_context_path_buttons()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        context_path = self._context_button_map.get(button_id)
        if context_path:
            self.post_message(self.ContextPathClicked(context_path))
            event.stop()


class ReturnToMainPromptModal(ModalScreen[bool]):
    """Prompt to return from decomposition subagent view to the main screen."""

    BINDINGS = [
        ("escape", "stay_here", "Stay Here"),
    ]

    DEFAULT_CSS = """
    ReturnToMainPromptModal {
        align: center middle;
    }

    ReturnToMainPromptModal #return_prompt_container {
        width: 74;
        max-width: 96%;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ReturnToMainPromptModal #return_prompt_title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    ReturnToMainPromptModal #return_prompt_message {
        margin-bottom: 1;
    }

    ReturnToMainPromptModal #return_prompt_countdown {
        color: $text-muted;
        margin-bottom: 1;
    }

    ReturnToMainPromptModal #return_prompt_actions {
        height: auto;
    }

    ReturnToMainPromptModal #return_prompt_actions Button {
        margin-right: 1;
    }
    """

    def __init__(self, timeout_seconds: int = 8) -> None:
        super().__init__()
        self._remaining_seconds = max(1, int(timeout_seconds))
        self._countdown_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Container(id="return_prompt_container"):
            yield Static("Decomposition complete", id="return_prompt_title")
            yield Static(
                "Subtasks are ready. Return to the main agent screen?",
                id="return_prompt_message",
            )
            yield Static("", id="return_prompt_countdown")
            with Horizontal(id="return_prompt_actions"):
                yield Button("Back to Main", id="return_prompt_back", variant="primary")
                yield Button("Stay Here", id="return_prompt_stay")

    def on_mount(self) -> None:
        self._update_countdown()
        self._countdown_timer = self.set_interval(1.0, self._tick_countdown)

    def on_unmount(self) -> None:
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def _update_countdown(self) -> None:
        try:
            self.query_one("#return_prompt_countdown", Static).update(
                f"Auto-return in {self._remaining_seconds}s",
            )
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

    def _tick_countdown(self) -> None:
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self.dismiss(True)
            return
        self._update_countdown()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "return_prompt_back":
            self.dismiss(True)
            return
        if event.button.id == "return_prompt_stay":
            self.dismiss(False)

    def action_stay_here(self) -> None:
        self.dismiss(False)


class ContinueSubagentModal(ModalScreen[str | None]):
    """Prompt for a continuation message for a completed/failed subagent."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ContinueSubagentModal {
        align: center middle;
    }

    ContinueSubagentModal #continue_subagent_container {
        width: 78;
        max-width: 96%;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ContinueSubagentModal #continue_subagent_title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }

    ContinueSubagentModal #continue_subagent_hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    ContinueSubagentModal #continue_subagent_input {
        margin-bottom: 1;
    }

    ContinueSubagentModal #continue_subagent_actions {
        height: auto;
    }

    ContinueSubagentModal #continue_subagent_actions Button {
        margin-right: 1;
    }
    """

    def __init__(self, subagent_id: str) -> None:
        super().__init__()
        self._subagent_id = subagent_id

    def compose(self) -> ComposeResult:
        with Container(id="continue_subagent_container"):
            yield Static(f"Continue subagent `{self._subagent_id}`", id="continue_subagent_title")
            yield Static("Add instructions for the next continuation turn.", id="continue_subagent_hint")
            yield Input(
                placeholder="e.g. Continue and focus on edge cases...",
                id="continue_subagent_input",
            )
            with Horizontal(id="continue_subagent_actions"):
                yield Button("Continue", id="continue_subagent_confirm", variant="primary")
                yield Button("Cancel", id="continue_subagent_cancel")

    def on_mount(self) -> None:
        try:
            self.query_one("#continue_subagent_input", Input).focus()
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

    def _submit(self) -> None:
        try:
            content = self.query_one("#continue_subagent_input", Input).value.strip()
        except Exception:
            content = ""
        if not content:
            return
        self.dismiss(content)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "continue_subagent_input":
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue_subagent_confirm":
            self._submit()
            return
        if event.button.id == "continue_subagent_cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _FooterAction(Static, can_focus=True):
    """A single-line clickable text action for the footer."""

    DEFAULT_CSS = """
    _FooterAction {
        width: auto;
        height: 1;
        color: $text-muted;
        padding: 0 2;
    }

    _FooterAction:hover {
        color: $primary;
        text-style: bold;
    }
    """

    class Clicked(Message):
        def __init__(self, action_id: str) -> None:
            super().__init__()
            self.action_id = action_id

    def __init__(self, label: str, action_id: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self._action_id = action_id

    def on_click(self) -> None:
        self.post_message(self.Clicked(self._action_id))


class SubagentFooter(Horizontal):
    """Footer bar with action links."""

    DEFAULT_CSS = """
    SubagentFooter {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 2;
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield _FooterAction("📋 Copy Answer", action_id="copy", id="copy_btn")
        yield _FooterAction("← Back to Main", action_id="back", id="back_btn_footer")


class SubagentStatusLine(Static):
    """Status line showing agent activity dots and execution status.

    Displays: A ● B ●  ● Running (42s)  esc:back ?:help
    """

    DEFAULT_CSS = """
    SubagentStatusLine {
        height: 1;
        width: 100%;
        background: $surface;
        padding: 0 1;
    }
    """

    STATUS_ICONS = {
        "running": "●",
        "completed": "✓",
        "error": "✗",
        "failed": "✗",
        "timeout": "⏱",
        "canceled": "⊘",
        "cancelled": "⊘",
        "stopped": "⊘",
        "pending": "○",
        "success": "✓",
    }
    _STATUS_STYLE_CLASSES = (
        "running",
        "completed",
        "error",
        "canceled",
        "cancelled",
    )

    @staticmethod
    def _normalize_status(status: str) -> str:
        normalized = str(status or "").lower().strip()
        if normalized in {"cancelled", "canceled", "stopped"}:
            return "canceled"
        return normalized or "running"

    @staticmethod
    def _format_status_label(status: str) -> str:
        if status == "canceled":
            return "Canceled"
        if status == "error":
            return "Error"
        return status.capitalize()

    @staticmethod
    def _is_redundant_reason(status: str, reason: str) -> bool:
        """Suppress reason text that just repeats the status label."""
        if status != "canceled":
            return False
        normalized_reason = " ".join(
            reason.lower().replace(".", " ").replace(":", " ").replace("_", " ").split(),
        )
        redundant_cancel_reasons = {
            "canceled",
            "cancelled",
            "stopped",
            "subagent canceled",
            "subagent cancelled",
            "subagent stopped",
        }
        return normalized_reason in redundant_cancel_reasons

    def __init__(self, status: str = "running", **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = self._normalize_status(status)
        self._elapsed = 0
        self._reason = ""
        self._agent_order: list[str] = []
        self._agent_letters: dict[str, str] = {}
        self._agent_active: dict[str, bool] = {}
        self._update_status_class()

    def _update_status_class(self) -> None:
        """Apply a stable status class so themes can style terminal states."""
        for status_class in self._STATUS_STYLE_CLASSES:
            self.remove_class(status_class)

        normalized = self._normalize_status(self._status)
        if normalized in {"completed", "success"}:
            self.add_class("completed")
            return
        if normalized == "canceled":
            self.add_class("canceled")
            self.add_class("cancelled")
            return
        if normalized in {"failed", "error", "timeout"}:
            self.add_class("error")
            return
        self.add_class("running")

    def set_agents(self, agent_ids: list[str]) -> None:
        """Register the inner agents for activity display."""
        self._agent_order = list(agent_ids)
        self._agent_letters.clear()
        self._agent_active.clear()
        for idx, aid in enumerate(agent_ids):
            self._agent_letters[aid] = chr(ord("A") + idx) if idx < 26 else str(idx + 1)
            self._agent_active[aid] = False
        self.refresh()

    def set_agent_active(self, agent_id: str, active: bool) -> None:
        """Set whether an agent is currently active."""
        if agent_id in self._agent_active:
            self._agent_active[agent_id] = active
            self.refresh()

    def render(self) -> Text:
        """Render agent dots + status."""
        text = Text()
        normalized_status = self._normalize_status(self._status)

        # Agent activity dots: A ● B ○
        if self._agent_order:
            for agent_id in self._agent_order:
                letter = self._agent_letters.get(agent_id, "?")
                active = self._agent_active.get(agent_id, False)
                if active:
                    text.append(f" {letter} ", style="bold")
                    text.append("●", style="bold green")
                else:
                    text.append(f" {letter} ", style="dim")
                    text.append("·", style="dim")
            text.append("  ")

        # Status
        icon = self.STATUS_ICONS.get(normalized_status, "●")
        text.append(f"{icon} ", style="bold")
        text.append(self._format_status_label(normalized_status))
        if normalized_status == "running":
            text.append(f" ({self._elapsed}s)")
        elif self._reason and normalized_status in {"failed", "error", "timeout", "canceled"}:
            reason = self._reason.replace("\n", " ").strip()
            if len(reason) > 72:
                reason = reason[:69] + "..."
            if not self._is_redundant_reason(normalized_status, reason):
                text.append(f": {reason}")

        # Hints
        text.append("  ")
        text.append("esc:back • ?:help", style="dim")

        return text

    def update_status(self, status: str, elapsed: int = 0, reason: str | None = None) -> None:
        """Update the status display."""
        self._status = self._normalize_status(status)
        self._elapsed = elapsed
        if reason is not None:
            self._reason = reason
        elif self._status == "running":
            self._reason = ""
        self._update_status_class()
        self.refresh()


class _AgentTimelineProxy:
    """Routes a TimelineEventAdapter to a specific timeline within SubagentPanel."""

    def __init__(self, panel: "SubagentPanel", timeline_id: str) -> None:
        self._panel = panel
        self._timeline_id = timeline_id

    def _get_timeline(self) -> TimelineSection | None:
        try:
            return self._panel.query_one(f"#{self._timeline_id}", TimelineSection)
        except Exception:
            return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._panel, name)


class SubagentPanel(Container, BaseTUILayoutMixin):
    """Panel for subagent content - inherits content pipeline from BaseTUILayoutMixin.

    This panel provides full content handling parity with the main TUI's AgentPanel
    by inheriting the shared BaseTUILayoutMixin.
    """

    DEFAULT_CSS = """
    SubagentPanel {
        width: 100%;
        height: 1fr;
        background: $background;
    }

    SubagentPanel .pinned-task-plan {
        width: 100%;
        height: auto;
        max-height: 12;
        padding: 0 0 1 0;
        border-bottom: solid rgba(61, 68, 77, 0.5);
    }

    SubagentPanel .pinned-task-plan.collapsed {
        max-height: 3;
        overflow: hidden;
    }

    SubagentPanel .pinned-task-plan.hidden {
        display: none;
    }

    SubagentPanel TimelineSection {
        width: 100%;
        height: 1fr;
        padding: 0 2 2 2;
        overflow-y: auto;
        scrollbar-size: 1 3;
        scrollbar-gutter: stable;
    }
    """

    def __init__(
        self,
        subagent: SubagentDisplayData,
        ribbon: AgentStatusRibbon | None = None,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.agent_id = subagent.id  # For compatibility with BaseTUILayoutMixin
        self._subagent = subagent
        self._ribbon = ribbon
        self._active_timeline_id: str | None = None

        # Per-inner-agent task plan hosts (created in mount_agent_timelines)
        from massgen.frontend.displays.textual_widgets.task_plan_host import (
            TaskPlanHost,
        )

        self._TaskPlanHost = TaskPlanHost  # Store class ref for later instantiation
        self._task_plan_hosts: dict[str, "TaskPlanHost"] = {}
        self._active_task_plan_agent: str | None = None

        # Initialize content pipeline from mixin
        self.init_content_pipeline()

    @property
    def _task_plan_host(self):
        """Return the active agent's TaskPlanHost (compatibility with BaseTUILayoutMixin)."""
        if self._active_task_plan_agent and self._active_task_plan_agent in self._task_plan_hosts:
            return self._task_plan_hosts[self._active_task_plan_agent]
        # Fallback to first available
        if self._task_plan_hosts:
            return next(iter(self._task_plan_hosts.values()))
        return None

    def compose(self) -> ComposeResult:
        # Task plan hosts and timelines are mounted dynamically via mount_agent_timelines()
        return
        yield  # Make this a generator

    # -------------------------------------------------------------------------
    # Multi-timeline management
    # -------------------------------------------------------------------------

    def mount_agent_timelines(self, agent_ids: list[str]) -> None:
        """Mount one timeline and one TaskPlanHost per inner agent. All start hidden except the first."""
        # Remove any existing timelines and task plan hosts first
        for tl in list(self.query(TimelineSection)):
            tl.remove()
        from massgen.frontend.displays.textual_widgets.task_plan_host import (
            TaskPlanHost,
        )

        for tph in list(self.query(TaskPlanHost)):
            tph.remove()
        self._active_timeline_id = None
        self._task_plan_hosts.clear()
        self._active_task_plan_agent = None

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_ids: list[str] = []
        for aid in agent_ids:
            if aid not in seen:
                seen.add(aid)
                unique_ids.append(aid)

        for i, aid in enumerate(unique_ids):
            # Mount TaskPlanHost per agent (skip if ID still in DOM from pending async removal)
            tph_id = f"subagent-task-plan-{aid}"
            try:
                self.query_one(f"#{tph_id}")
            except Exception:
                hidden_cls = "pinned-task-plan hidden"
                tph = self._TaskPlanHost(
                    agent_id=aid,
                    ribbon=self._ribbon,
                    id=tph_id,
                    classes=hidden_cls,
                )
                self._task_plan_hosts[aid] = tph
                self.mount(tph)

            # Mount timeline per agent (skip if ID still in DOM)
            widget_id = f"subagent-timeline-{aid}"
            try:
                self.query_one(f"#{widget_id}")
                continue
            except Exception as e:
                tui_log(f"[SubagentScreen] {e}")
            tl = TimelineSection(id=widget_id)
            if i > 0:
                tl.add_class("hidden")
            self.mount(tl)

        if unique_ids:
            self._active_timeline_id = f"subagent-timeline-{unique_ids[0]}"
            self._active_task_plan_agent = unique_ids[0]

    def switch_timeline(self, agent_id: str) -> None:
        """Show one timeline and task plan host, hide the rest."""
        new_id = f"subagent-timeline-{agent_id}"
        if new_id == self._active_timeline_id:
            return
        # Hide current timeline
        if self._active_timeline_id:
            try:
                old = self.query_one(f"#{self._active_timeline_id}", TimelineSection)
                old.add_class("hidden")
            except Exception as e:
                tui_log(f"[SubagentScreen] {e}")
        # Hide current task plan host
        if self._active_task_plan_agent and self._active_task_plan_agent in self._task_plan_hosts:
            self._task_plan_hosts[self._active_task_plan_agent].add_class("hidden")
        # Show new timeline
        try:
            new = self.query_one(f"#{new_id}", TimelineSection)
            new.remove_class("hidden")
            new._scroll_to_end(animate=False, force=True)
            self._active_timeline_id = new_id
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")
        # Show new task plan host (only if it has content — check if it was ever unhidden)
        self._active_task_plan_agent = agent_id
        if agent_id in self._task_plan_hosts:
            tph = self._task_plan_hosts[agent_id]
            # Only show if it has task plan content (don't unhide empty ones)
            if tph.get_active_plan_id() is not None:
                tph.remove_class("hidden")

    # -------------------------------------------------------------------------
    # BaseTUILayoutMixin abstract method implementations
    # -------------------------------------------------------------------------

    def _get_timeline(self) -> TimelineSection | None:
        """Get the active TimelineSection widget (implements BaseTUILayoutMixin)."""
        if not self._active_timeline_id:
            return None
        try:
            return self.query_one(f"#{self._active_timeline_id}", TimelineSection)
        except Exception:
            return None

    def _get_ribbon(self) -> AgentStatusRibbon | None:
        """Get the AgentStatusRibbon widget (implements BaseTUILayoutMixin)."""
        return self._ribbon

    def set_ribbon(self, ribbon: AgentStatusRibbon) -> None:
        """Set the ribbon reference after mounting."""
        self._ribbon = ribbon
        for tph in self._task_plan_hosts.values():
            tph.set_ribbon(ribbon)

    def update_task_plan(self, tasks: list[dict[str, Any]], plan_id: str | None = None, operation: str = "create") -> None:
        """Update the active task plan for this subagent panel."""
        host = self._task_plan_host
        if host:
            host.update_task_plan(tasks, plan_id=plan_id, operation=operation)

    def _update_pinned_task_plan(
        self,
        tasks: list[dict[str, Any]],
        focused_task_id: str | None = None,
        operation: str = "update",
        show_notification: bool = True,
    ) -> None:
        """Update the pinned task plan widget."""
        try:
            host = self._task_plan_host
            if host:
                host.update_pinned_task_plan(
                    tasks=tasks,
                    focused_task_id=focused_task_id,
                    operation=operation,
                    show_notification=show_notification,
                )
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

    def toggle_task_plan(self) -> None:
        """Toggle the active agent's task plan between collapsed and expanded."""
        host = self._task_plan_host
        if host:
            host.toggle()

    def _is_planning_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool is a Planning MCP tool (skip normal tool cards)."""
        from massgen.frontend.displays.task_plan_support import is_planning_tool

        return is_planning_tool(tool_name)

    def _check_and_display_task_plan(self, tool_data, timeline) -> None:
        """Check if tool result is from Planning MCP and display/update TaskPlanCard."""
        from massgen.frontend.displays.base_tui_layout import tui_log
        from massgen.frontend.displays.task_plan_support import (
            update_task_plan_from_tool,
        )

        host = self._task_plan_host
        if host:
            update_task_plan_from_tool(host, tool_data, timeline, log=tui_log)


class SubagentView(Container):
    """Reusable subagent view (used in screen and side panel).

    Provides full TUI parity with the main view:
    - Tab bar for multiple subagents
    - Status ribbon with round navigation
    - Timeline with tools, thinking, text
    - Live updates while running
    """

    BINDINGS = [
        ("escape", "close", "Back"),
        ("tab", "next_subagent", "Next Subagent"),
        ("shift+tab", "prev_subagent", "Previous Subagent"),
        ("ctrl+t", "toggle_task_plan", "Toggle Task Plan"),
    ]

    class CloseRequested(Message):
        """Request the parent to close the subagent view."""

        def __init__(self) -> None:
            super().__init__()

    DEFAULT_CSS = """
    SubagentView {
        width: 100%;
        height: 100%;
        background: $background;
    }

    SubagentView #subagent-content {
        width: 100%;
        height: 1fr;
    }

    SubagentView #subagent-tab-bar #session_info {
        display: none;
    }

    SubagentView #subagent-input-area {
        dock: bottom;
        height: auto;
        width: 1fr;
        padding: 0 1;
        background: $background;
    }

    SubagentView #subagent-input-bar {
        dock: none;
        width: 1fr;
        padding: 0;
        background: transparent;
    }

    SubagentView .subagent-queued-input-region {
        margin: 0 0 1 0;
        padding: 0 0 1 0;
    }

    SubagentView #subagent-queue-spacer {
        height: 1;
    }

    SubagentView #subagent-continue-row {
        height: auto;
        width: 100%;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    SubagentView #continue_subagent_button {
        width: auto;
        min-width: 14;
    }
    """

    # Polling interval for live updates
    POLL_INTERVAL = 0.5

    def __init__(
        self,
        subagent: SubagentDisplayData,
        all_subagents: list[SubagentDisplayData] | None = None,
        status_callback: Callable[[str], SubagentDisplayData | None] | None = None,
        auto_return_on_completion: bool = False,
        auto_return_prompt_delay_seconds: float = 2.0,
        auto_return_timeout_seconds: int = 8,
        send_message_callback: Callable[..., bool] | None = None,
        continue_subagent_callback: Callable[..., bool] | None = None,
        id: str | None = None,
    ) -> None:
        """Initialize the subagent screen.

        Args:
            subagent: The subagent to display
            all_subagents: All subagents for navigation (tab bar)
            status_callback: Callback to get updated status
            send_message_callback: Callback(subagent_id, content, target_agents=...) to send a message
                to a running subagent
            continue_subagent_callback: Callback(subagent_id, message) to continue
                a completed/failed subagent
        """
        super().__init__(id=id)
        self._subagent = subagent
        self._all_subagents = all_subagents or [subagent]
        self._current_index = 0

        # Find current index
        for i, sa in enumerate(self._all_subagents):
            if sa.id == subagent.id:
                self._current_index = i
                break

        self._status_callback = status_callback
        self._send_message_callback = send_message_callback
        self._continue_subagent_callback = continue_subagent_callback
        self._poll_timer: Timer | None = None
        self._event_reader: EventReader | None = None
        self._round_number = 1
        self._final_answer: str | None = None

        # Per-agent adapters (keyed by agent_id)
        self._event_adapters: dict[str, TimelineEventAdapter] = {}
        self._agents_loaded: set[str] = set()
        self._final_answer_locked: set[str] = set()  # Agents with final answer lock applied
        self._inner_winner: str | None = None  # Winner agent ID (persists across rebuilds)

        # References to widgets (set after compose)
        self._header: SubagentHeader | None = None
        self._tab_bar: AgentTabBar | None = None
        self._inner_tab_bar: AgentTabBar | None = None
        self._ribbon: AgentStatusRibbon | None = None
        self._panel: SubagentPanel | None = None
        self._status_line: SubagentStatusLine | None = None

        # Inner agent tracking
        self._inner_agents: list[str] = []
        self._agent_active_set: set[str] = set()
        self._inner_agent_models: dict[str, str] = {}
        self._current_inner_agent: str | None = None
        self._tool_call_agent_map: dict[str, str] = {}
        self._terminal_status_notes: set[str] = set()
        self._waiting_placeholder_shown: bool = False
        self._auto_return_on_completion = auto_return_on_completion
        self._auto_return_prompt_delay_seconds = max(0.0, float(auto_return_prompt_delay_seconds))
        self._auto_return_timeout_seconds = max(1, int(auto_return_timeout_seconds))
        self._auto_return_prompt_timer: Timer | None = None
        self._auto_return_prompt_shown = False
        self._auto_return_prompt_cancelled = False

        # Runtime message queue strip state (subagent input parity with main TUI).
        self._queued_runtime_banner: QueuedInputBanner | None = None
        self._queued_runtime_region: Vertical | None = None
        self._queue_cancel_latest_button: Button | None = None
        self._queue_clear_button: Button | None = None
        self._queued_runtime_messages: list[dict[str, Any]] = []
        self._queued_runtime_pending_by_agent: dict[str, int] = {}
        self._next_runtime_message_id: int = 1
        self._runtime_inbox_dir: Path | None = None
        self._runtime_inbox_seen_files: set[str] = set()
        self._continue_subagent_button: Button | None = None

    def _build_unique_tab_ids(self) -> list[str]:
        """Build unique tab IDs from subagent list, disambiguating duplicates."""
        seen: dict[str, int] = {}
        tab_ids: list[str] = []
        self._tab_id_to_index: dict[str, int] = {}
        for idx, sa in enumerate(self._all_subagents):
            count = seen.get(sa.id, 0)
            seen[sa.id] = count + 1
            tab_id = f"{sa.id}_{count}" if count > 0 else sa.id
            tab_ids.append(tab_id)
            self._tab_id_to_index[tab_id] = idx
        return tab_ids

    def compose(self) -> ComposeResult:
        # Build agent IDs and models for tab bar.
        # Disambiguate duplicate subagent IDs to avoid widget ID collisions.
        agent_ids = self._build_unique_tab_ids()
        agent_models: dict[str, str] = {}  # Would come from config

        # Header with back button
        yield SubagentHeader(self._subagent, id="subagent-header")

        # Top-level subagent selector (only if multiple subagents)
        if len(self._all_subagents) > 1:
            yield AgentTabBar(
                agent_ids=agent_ids,
                agent_models=agent_models,
                question=self._subagent.task or "",
                tab_id_prefix="subagent_",  # Prefix to avoid ID conflicts
                id="subagent-tab-bar",
            )

        # Inner agent tabs - ALWAYS shown (this subagent's full TUI)
        # Each subagent IS a full MassGen subcall that may have multiple inner agents
        # Initialize with placeholder - will be updated in on_mount after event reader is ready
        inner_tabs = AgentTabBar(
            agent_ids=[self._subagent.id],  # Placeholder, updated in on_mount
            agent_models={},
            question=self._subagent.task or "",
            tab_id_prefix="inner_",  # Prefix to avoid ID conflicts with outer tabs
            id="inner-agent-tabs",
        )
        yield inner_tabs

        # Status ribbon
        yield AgentStatusRibbon(
            agent_id=self._subagent.id,
            id="subagent-ribbon",
        )

        # Content panel
        with Vertical(id="subagent-content"):
            yield SubagentPanel(self._subagent, id="subagent-panel")

        # Runtime queued-input strip (for parity with main TUI), shown above status line.
        if self._send_message_callback:
            with Vertical(id="queued_input_region", classes="subagent-queued-input-region"):
                with Horizontal(id="queued_input_row"):
                    yield QueuedInputBanner(id="queued_input_banner")
                    with Horizontal(id="queued_input_actions"):
                        yield Button("Cancel latest", id="queue_cancel_latest_button")
                        yield Button("Clear queue", id="queue_clear_button")
            yield Static("", id="subagent-queue-spacer")

        # Execution status line
        yield SubagentStatusLine(
            status=self._subagent.status,
            id="subagent-status-line",
        )

        # Message input bar (only when callback is available)
        if self._send_message_callback:
            from .message_input_bar import MessageInputBar

            with Vertical(id="subagent-input-area"):

                # Inherit vim mode from the main app if available
                vim_mode = False
                try:
                    vim_mode = getattr(self.app, "question_input", None) and self.app.question_input.vim_mode
                except Exception:
                    pass

                input_bar = MessageInputBar(
                    placeholder="Send message to subagent... (Enter to send)",
                    vim_mode=bool(vim_mode),
                    id="subagent-input-bar",
                )
                if self._subagent.status not in ("running", "pending"):
                    input_bar.display = False
                yield input_bar

    def on_mount(self) -> None:
        """Initialize event reader and load events."""
        # Get widget references
        try:
            self._header = self.query_one("#subagent-header", SubagentHeader)
            self._panel = self.query_one("#subagent-panel", SubagentPanel)
            self._status_line = self.query_one("#subagent-status-line", SubagentStatusLine)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        try:
            self._ribbon = self.query_one("#subagent-ribbon", AgentStatusRibbon)
            if self._panel and self._ribbon:
                self._panel.set_ribbon(self._ribbon)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        try:
            self._tab_bar = self.query_one("#subagent-tab-bar", AgentTabBar)
            if self._tab_bar:
                # Use disambiguated tab ID for correct activation
                index_to_tab = {v: k for k, v in self._tab_id_to_index.items()} if hasattr(self, "_tab_id_to_index") else {}
                active_tab_id = index_to_tab.get(self._current_index, self._subagent.id)
                self._tab_bar.set_active(active_tab_id)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        try:
            self._inner_tab_bar = self.query_one("#inner-agent-tabs", AgentTabBar)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        # Initialize event reader
        self._init_event_reader()

        # Detect inner agents and update the inner tab bar
        self._inner_agents, self._inner_agent_models = self._detect_inner_agents()
        self._agent_active_set = set(self._inner_agents)
        self._current_inner_agent = self._inner_agents[0] if self._inner_agents else self._subagent.id

        # Update inner agent tabs with detected agents
        if self._inner_tab_bar and self._inner_agents:
            self._inner_tab_bar.update_agents(self._inner_agents, self._inner_agent_models)
            self._inner_tab_bar.set_active(self._current_inner_agent)

        # Register agents on the status line for activity dots
        if self._status_line and self._inner_agents:
            self._status_line.set_agents(self._inner_agents)

        # Update message input bar with detected inner agent targets
        if self._send_message_callback and self._inner_agents:
            try:
                from .message_input_bar import MessageInputBar

                input_bar = self.query_one("#subagent-input-bar", MessageInputBar)
                input_bar.set_targets(self._inner_agents)
            except Exception:
                pass

        if self._send_message_callback:
            try:
                self._queued_runtime_region = self.query_one("#queued_input_region", Vertical)
            except Exception:
                self._queued_runtime_region = None
            try:
                self._queued_runtime_banner = self.query_one(
                    "#queued_input_banner",
                    QueuedInputBanner,
                )
            except Exception:
                self._queued_runtime_banner = None
            try:
                self._queue_cancel_latest_button = self.query_one(
                    "#queue_cancel_latest_button",
                    Button,
                )
            except Exception:
                self._queue_cancel_latest_button = None
            try:
                self._queue_clear_button = self.query_one(
                    "#queue_clear_button",
                    Button,
                )
            except Exception:
                self._queue_clear_button = None
            self._refresh_runtime_queue_banner()
            self._runtime_inbox_dir = self._resolve_runtime_inbox_dir()
            self._runtime_inbox_seen_files = set()
            self._sync_runtime_queue_from_inbox()

        if self._continue_subagent_callback:
            try:
                self._continue_subagent_button = self.query_one("#continue_subagent_button", Button)
            except Exception:
                self._continue_subagent_button = None
            self._refresh_continue_button_visibility()

        # Mount one timeline per inner agent
        if self._panel:
            self._panel.mount_agent_timelines(self._inner_agents)

        # Load events for the first (default) agent
        if self._current_inner_agent:
            self._load_events_for_agent(self._current_inner_agent)
            self._agents_loaded.add(self._current_inner_agent)

        # If we still have no event reader (log file not created yet) and the
        # subagent is running, show the task text so the screen isn't blank.
        if self._event_reader is None and self._current_inner_agent and self._subagent.status in ("running", "pending"):
            self._ensure_waiting_placeholder(self._current_inner_agent)

        # Ensure status classes/reason are applied even for terminal states on first paint.
        self._update_status_display()

        # Start polling if subagent is running
        if self._subagent.status in ("running", "pending"):
            self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

    def on_unmount(self) -> None:
        """Stop polling when unmounted."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._auto_return_prompt_timer is not None:
            self._auto_return_prompt_timer.stop()
            self._auto_return_prompt_timer = None

    @staticmethod
    def _normalize_context_paths(raw_paths: Any) -> list[str]:
        if not raw_paths:
            return []
        if not isinstance(raw_paths, list):
            raw_paths = [raw_paths]

        normalized: list[str] = []
        seen: set[str] = set()
        for entry in raw_paths:
            path_value = ""
            if isinstance(entry, str):
                path_value = entry.strip()
            elif isinstance(entry, dict):
                candidate = entry.get("path")
                if candidate is not None:
                    path_value = str(candidate).strip()
            elif entry is not None:
                path_value = str(entry).strip()

            if not path_value or path_value in seen:
                continue
            seen.add(path_value)
            normalized.append(path_value)

        return normalized

    def _hydrate_context_paths_from_metadata(self, metadata: dict[str, Any]) -> None:
        """Populate context paths on the active subagent from execution metadata."""
        existing_paths = self._normalize_context_paths(getattr(self._subagent, "context_paths", []))
        if existing_paths:
            return

        config = metadata.get("config", {}) if isinstance(metadata, dict) else {}
        orchestrator_cfg = config.get("orchestrator", {}) if isinstance(config, dict) else {}
        context_paths = self._normalize_context_paths(orchestrator_cfg.get("context_paths", []))
        if not context_paths:
            return

        self._subagent.context_paths = context_paths

    def _detect_inner_agents(self) -> tuple[list[str], dict[str, str]]:
        """Detect agent IDs and models from the subagent's logs.

        Tries multiple sources:
        1. execution_metadata.yaml - contains full config with agent names and models
        2. events.jsonl - has agent_id fields on events

        Returns:
            Tuple of (agent_ids list, agent_models dict mapping agent_id to model name).
            Always returns at least the subagent ID itself if no agents are found.
        """
        import yaml

        agent_ids: list[str] = []
        agent_models: dict[str, str] = {}

        from pathlib import Path

        # Try to read from execution_metadata.yaml using resolved events path
        try:
            metadata_file: Path | None = None
            events_file = self._resolve_events_file()
            if events_file and events_file.exists():
                candidate = events_file.parent / "execution_metadata.yaml"
                if candidate.exists():
                    metadata_file = candidate

            # Fallbacks if events path isn't available yet
            if metadata_file is None and self._subagent.log_path:
                log_path = Path(self._subagent.log_path)
                if not log_path.is_absolute():
                    log_path = (Path.cwd() / log_path).resolve()

                if log_path.is_dir():
                    candidate = log_path / "full_logs" / "execution_metadata.yaml"
                    if candidate.exists():
                        metadata_file = candidate
                    else:
                        candidate = log_path / "execution_metadata.yaml"
                        if candidate.exists():
                            metadata_file = candidate
                else:
                    candidate = log_path.parent / "execution_metadata.yaml"
                    if candidate.exists():
                        metadata_file = candidate

            if metadata_file and metadata_file.exists():
                with open(metadata_file, encoding="utf-8") as f:
                    metadata = yaml.safe_load(f)
                self._hydrate_context_paths_from_metadata(metadata)

                # Extract agents from config
                # Note: agents is a LIST, not a dict - each item has 'id' and 'backend' keys
                config = metadata.get("config", {})
                agents_list = config.get("agents", [])

                if isinstance(agents_list, list) and agents_list:
                    for agent_cfg in agents_list:
                        if isinstance(agent_cfg, dict):
                            agent_id = agent_cfg.get("id")
                            if agent_id:
                                agent_ids.append(agent_id)
                                # Get model from nested backend config
                                backend_cfg = agent_cfg.get("backend", {})
                                model = backend_cfg.get("model", "")
                                if model:
                                    # Shorten model name for display
                                    short_model = model.split("/")[-1]  # Handle "openai/gpt-4o" format
                                    agent_models[agent_id] = short_model

        except Exception as e:
            print(f"[SubagentScreen] Error detecting inner agents: {e}")

        # Fallback: detect from events if no config found
        if not agent_ids and self._event_reader:
            seen_ids: set[str] = set()
            events = self._event_reader.read_all()
            for event in events:
                # Check agent_id field
                if event.agent_id and self._is_agent_source(event.agent_id) and event.agent_id not in seen_ids:
                    seen_ids.add(event.agent_id)
                # Also check data.source for backwards compatibility
                source = event.data.get("source")
                if not source:
                    source = (event.data.get("chunk") or {}).get("source")
                if source and self._is_agent_source(source) and source not in seen_ids:
                    seen_ids.add(source)
            agent_ids = sorted(seen_ids)

        # Always return at least the subagent ID
        if not agent_ids:
            logger.info(
                f"[SubagentScreen] No inner agents detected for {self._subagent.id}, using fallback",
            )
            return [self._subagent.id], {}

        logger.info(
            f"[SubagentScreen] Detected {len(agent_ids)} inner agents: {agent_ids}, models: {agent_models}",
        )
        return agent_ids, agent_models

    def _init_event_reader(self) -> None:
        """Initialize the event reader for the current subagent."""
        events_file = self._resolve_events_file()
        if not events_file:
            logger.warning(
                f"[SubagentScreen] No events.jsonl found for subagent {self._subagent.id}",
            )
            return

        if events_file.exists():
            logger.info(f"[SubagentScreen] Using events file: {events_file}")
            self._event_reader = EventReader(events_file)
        else:
            logger.warning(
                f"[SubagentScreen] Events file does not exist: {events_file}",
            )

    def _resolve_events_file(self) -> Path | None:
        """Resolve the events.jsonl file for the current subagent."""
        # 1) Use explicit log_path if provided (file or directory)
        if self._subagent.log_path:
            log_path = Path(self._subagent.log_path)
            if not log_path.is_absolute():
                log_path = (Path.cwd() / log_path).resolve()

            if log_path.is_dir():
                resolved = SubagentResult.resolve_events_path(log_path)
                if resolved:
                    return Path(resolved)
            else:
                return log_path

        # 2) Fall back to current session log dir
        try:
            from massgen.logger_config import get_log_session_dir

            log_dir = get_log_session_dir().resolve()
            subagent_logs = log_dir / "subagents" / self._subagent.id
            resolved = SubagentResult.resolve_events_path(subagent_logs)
            if resolved:
                return Path(resolved)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        return None

    def _load_initial_events(self) -> None:
        """Load all existing events and build timeline (fallback for no inner agents)."""
        if not self._event_reader or not self._panel:
            return

        events = self._event_reader.read_all()
        self._update_tool_call_agent_map(events)
        agent_id = self._current_inner_agent or self._subagent.id
        self._load_events_for_agent(agent_id)
        self._agents_loaded.add(agent_id)

        # Advance reader to end so polling only reads new events
        try:
            self._event_reader._last_position = self._event_reader._file_path.stat().st_size  # type: ignore[attr-defined]
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

    @staticmethod
    def _display_round(event: MassGenEvent) -> MassGenEvent:
        """Pass through events unchanged.

        The 0-based to 1-based round conversion is handled by
        ContentProcessor._handle_event_round_start(), so no extra
        conversion is needed here.
        """
        return event

    def _sync_adapter_state(self) -> None:
        """Sync round/final answer state from the active agent's adapter."""
        agent_id = self._current_inner_agent
        if agent_id and agent_id in self._event_adapters:
            adapter = self._event_adapters[agent_id]
            self._round_number = adapter.round_number
            self._final_answer = adapter.final_answer

    def _has_final_answer_content(self) -> bool:
        """Return True when any final answer content is available."""
        if self._final_answer_locked:
            return True
        if self._final_answer and str(self._final_answer).strip():
            return True
        preview = getattr(self._subagent, "answer_preview", None)
        return bool(str(preview).strip()) if preview else False

    def _show_auto_return_prompt(self) -> None:
        """Show delayed prompt to return to main view after decomposition completion."""
        self._auto_return_prompt_timer = None

        if not self._auto_return_on_completion or self._auto_return_prompt_cancelled or self._auto_return_prompt_shown:
            return
        if self._subagent.status in ("running", "pending"):
            return
        if not self._has_final_answer_content():
            return

        self._auto_return_prompt_shown = True
        modal = ReturnToMainPromptModal(timeout_seconds=self._auto_return_timeout_seconds)

        def _on_dismiss(result: bool | None) -> None:
            if result is False:
                self._auto_return_prompt_cancelled = True
                return
            self._request_close()

        try:
            self.app.push_screen(modal, _on_dismiss)
        except Exception as e:
            tui_log(f"[SubagentScreen] Failed to open return prompt: {e}")
            self._request_close()

    def _maybe_schedule_auto_return_prompt(self) -> None:
        """Schedule the delayed return prompt once completion + final answer are present."""
        if not self._auto_return_on_completion or self._auto_return_prompt_cancelled or self._auto_return_prompt_shown:
            return
        if self._auto_return_prompt_timer is not None:
            return
        if self._subagent.status in ("running", "pending"):
            return
        if not self._has_final_answer_content():
            return

        self._auto_return_prompt_timer = self.set_timer(
            self._auto_return_prompt_delay_seconds,
            self._show_auto_return_prompt,
        )

    def _detect_and_apply_winner(self, events: list[MassGenEvent]) -> None:
        """Scan events for presentation_start/final_presentation_start and apply winner crown."""
        for event in events:
            if event.event_type in ("presentation_start", "final_presentation_start") and event.agent_id:
                if event.agent_id in self._inner_agents:
                    self._inner_winner = event.agent_id
        if self._inner_winner and self._inner_tab_bar:
            self._inner_tab_bar.set_winner(self._inner_winner)

    @staticmethod
    def _normalize_subagent_status(status: str | None) -> str:
        normalized = str(status or "").lower().strip()
        if normalized in {"cancelled", "canceled", "stopped"}:
            return "canceled"
        return normalized or "running"

    @staticmethod
    def _tab_status(status: str | None) -> str:
        normalized = SubagentView._normalize_subagent_status(status)
        if normalized == "canceled":
            return "cancelled"
        return normalized

    @staticmethod
    def _is_redundant_terminal_reason(status: str, reason: str) -> bool:
        """Return True when reason only repeats the terminal status message."""
        normalized_reason = " ".join(
            reason.lower().replace(".", " ").replace(":", " ").replace("_", " ").split(),
        )
        if not normalized_reason:
            return True

        redundant_reasons = {
            "completed": {"completed", "subagent completed"},
            "timeout": {"timeout", "timed out", "subagent timeout", "subagent timed out"},
            "canceled": {
                "canceled",
                "cancelled",
                "stopped",
                "subagent canceled",
                "subagent cancelled",
                "subagent stopped",
            },
            "failed": {"failed", "error", "subagent failed", "subagent error"},
            "error": {"failed", "error", "subagent failed", "subagent error"},
        }
        return normalized_reason in redundant_reasons.get(status, set())

    def _build_terminal_status_note(self) -> tuple[str, str] | None:
        status = self._normalize_subagent_status(self._subagent.status)
        if status in {"running", "pending"}:
            return None

        reason = str(self._subagent.error or "").strip()
        if status == "completed":
            message = "Subagent completed."
            style = "#7ee787"
        elif status == "timeout":
            message = "Subagent timed out."
            style = "#d29922"
        elif status == "canceled":
            message = "Subagent canceled."
            style = "#d29922"
        elif status in {"failed", "error"}:
            message = "Subagent failed."
            style = "#f85149"
        else:
            message = f"Subagent {status}."
            style = "#8b949e"

        if reason and not self._is_redundant_terminal_reason(status, reason):
            if message.endswith("."):
                message = message[:-1]
            message = f"{message}: {reason}"
        return message, style

    def _ensure_waiting_placeholder(self, agent_id: str) -> None:
        """Show the task text as a placeholder while waiting for the log file to appear.

        Called when status=running but no events.jsonl has been found yet (t=0s on
        fast drilldown open). Adds the task text once so the screen isn't blank.
        """
        if self._waiting_placeholder_shown or not self._panel:
            return
        task = (self._subagent.task or "").strip()
        if not task:
            return
        try:
            timeline = self._panel.query_one(
                f"#subagent-timeline-{agent_id}",
                TimelineSection,
            )
        except Exception:
            return
        try:
            timeline.add_text(task, style="dim", text_class="status", round_number=1)
            self._waiting_placeholder_shown = True
        except Exception as e:
            tui_log(f"[SubagentScreen] Failed to add waiting placeholder: {e}")

    def _ensure_terminal_status_note(self, agent_id: str, event_count: int = 0) -> None:
        """Add a one-line terminal status note when no events were rendered."""
        if event_count > 0 or not self._panel:
            return

        status = self._normalize_subagent_status(self._subagent.status)
        if status in {"running", "pending"}:
            return
        if agent_id in self._terminal_status_notes:
            return

        note = self._build_terminal_status_note()
        if note is None:
            return
        message, style = note

        try:
            timeline = self._panel.query_one(
                f"#subagent-timeline-{agent_id}",
                TimelineSection,
            )
        except Exception:
            return

        try:
            round_number = max(1, int(self._round_number or 1))
        except Exception:
            round_number = 1

        try:
            timeline.add_text(
                message,
                style=style,
                text_class="status",
                round_number=round_number,
            )
            self._terminal_status_notes.add(agent_id)
        except Exception as e:
            tui_log(f"[SubagentScreen] Failed to add terminal status note: {e}")

    def _poll_updates(self) -> None:
        """Poll for status and event updates."""
        # Update status if callback available
        if self._status_callback:
            new_data = self._status_callback(self._subagent.id)
            if new_data:
                self._subagent = new_data
                self._update_status_display()

        # Attempt to initialize event reader if it wasn't ready at mount time
        if self._event_reader is None:
            self._init_event_reader()
            if self._event_reader:
                self._load_initial_events()
            elif self._current_inner_agent:
                status = self._normalize_subagent_status(self._subagent.status)
                if status in {"running", "pending"}:
                    self._ensure_waiting_placeholder(self._current_inner_agent)
                else:
                    self._ensure_terminal_status_note(self._current_inner_agent, event_count=0)

        # Read new events and route to all loaded adapters
        if self._event_reader:
            new_events = self._event_reader.get_new_events()
            # Parent runtime messages are file-backed and can arrive between
            # event batches, so poll inbox every tick (not only when events arrive).
            self._sync_runtime_queue_from_inbox()
            if new_events:
                self._update_tool_call_agent_map(new_events)
                self._update_activity_dots(new_events)
                self._update_runtime_queue_from_events(new_events)
                for agent_id in list(self._agents_loaded):
                    if agent_id in self._event_adapters:
                        filtered = self._filter_events_for_agent(new_events, agent_id)
                        if filtered:
                            adapter = self._event_adapters[agent_id]
                            for event in filtered:
                                adapter.handle_event(self._display_round(event))
                            adapter.flush()
                self._sync_adapter_state()
                self._update_status_display()

                # Check for winner events and update inner tab crown
                self._detect_and_apply_winner(new_events)

                # Check if any agent got a final answer
                for agent_id in list(self._agents_loaded):
                    self._maybe_lock_final_answer(agent_id)

        self._maybe_schedule_auto_return_prompt()

        # Stop polling if completed
        if self._subagent.status not in ("running", "pending"):
            # Finalize any incomplete final presentation cards (e.g. timeout
            # killed the subagent before chunks/end events were written)
            for adapter in self._event_adapters.values():
                adapter.finalize_if_incomplete()

            # Mark all agents as inactive
            if self._status_line:
                for aid in self._inner_agents:
                    self._status_line.set_agent_active(aid, False)

            # Hide message input bar
            try:
                input_bar = self.query_one("#subagent-input-bar")
                input_bar.display = False
            except Exception:
                pass
            self._queued_runtime_messages = []
            self._queued_runtime_pending_by_agent = {}
            self._refresh_runtime_queue_banner()

            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None

    def _update_status_display(self) -> None:
        """Update status displays."""
        # Update status line
        agent_id = self._current_inner_agent
        adapter = self._event_adapters.get(agent_id) if agent_id else None
        current_round = adapter.round_number if adapter else self._round_number
        status = self._normalize_subagent_status(self._subagent.status)
        self._set_cancelled_state_class(status)

        if self._header:
            self._header.update_subagent(self._subagent)

        if self._status_line:
            self._status_line.update_status(
                status,
                int(self._subagent.elapsed_seconds),
                reason=self._subagent.error,
            )

        # Update ribbon
        if self._ribbon:
            self._ribbon.set_round(self._subagent.id, current_round, False)

        # Update tab bar status (use disambiguated tab ID)
        if self._tab_bar:
            index_to_tab = {v: k for k, v in self._tab_id_to_index.items()} if hasattr(self, "_tab_id_to_index") else {}
            tab_id = index_to_tab.get(self._current_index, self._subagent.id)
            self._tab_bar.update_agent_status(tab_id, self._tab_status(status))
        self._refresh_continue_button_visibility()

    def _set_cancelled_state_class(self, normalized_status: str) -> None:
        """Mirror main-screen cancelled treatment for subagent full-screen view."""
        is_cancelled = normalized_status == "canceled"
        self.set_class(is_cancelled, "cancelled-state")
        self.set_class(is_cancelled, "canceled-state")

    def _update_activity_dots(self, events: list[MassGenEvent]) -> None:
        """Update agent activity dots based on new events."""
        if not self._status_line:
            return
        # Track which agents had activity in this batch
        active_agents: set[str] = set()
        for event in events:
            aid = event.agent_id
            if aid and aid in self._agent_active_set:
                et = event.event_type
                # Active event types
                if et in ("thinking_start", "text_start", "tool_start", "stream_chunk"):
                    active_agents.add(aid)
                # Completion event types — mark inactive
                elif et in ("thinking_complete", "text_complete", "tool_complete", "round_end"):
                    active_agents.discard(aid)
        # Apply: any agent with recent activity is active
        for aid in self._inner_agents:
            if aid in active_agents:
                self._status_line.set_agent_active(aid, True)

    def _switch_subagent(self, index: int) -> None:
        """Switch to a different subagent (top-level switch — full rebuild needed)."""
        if 0 <= index < len(self._all_subagents):
            self._current_index = index
            self._subagent = self._all_subagents[index]

            # Reset state
            self._round_number = 1
            self._final_answer = None
            self._event_adapters.clear()
            self._agents_loaded.clear()
            self._final_answer_locked.clear()
            self._tool_call_agent_map.clear()
            self._terminal_status_notes.clear()
            self._inner_winner = None
            self._queued_runtime_messages = []
            self._queued_runtime_pending_by_agent = {}
            self._runtime_inbox_dir = self._resolve_runtime_inbox_dir()
            self._runtime_inbox_seen_files = set()
            self._refresh_runtime_queue_banner()

            # Remove old timelines
            if self._panel:
                for tl in list(self._panel.query(TimelineSection)):
                    tl.remove()
                self._panel._active_timeline_id = None

            # Re-initialize event reader
            self._init_event_reader()

            # Detect inner agents for the new subagent
            self._inner_agents, self._inner_agent_models = self._detect_inner_agents()
            self._agent_active_set = set(self._inner_agents)
            self._current_inner_agent = self._inner_agents[0] if self._inner_agents else self._subagent.id

            # Update inner agent tabs and prompt for new subagent
            if self._inner_tab_bar and self._inner_agents:
                self._inner_tab_bar.update_agents(self._inner_agents, self._inner_agent_models)
                self._inner_tab_bar.set_active(self._current_inner_agent)
                self._inner_tab_bar.update_question(self._subagent.task or "")

            # Update activity dots on status line
            if self._status_line and self._inner_agents:
                self._status_line.set_agents(self._inner_agents)

            # Update message input bar targets for the new subagent's agents
            if self._send_message_callback and self._inner_agents:
                try:
                    from .message_input_bar import MessageInputBar

                    input_bar = self.query_one("#subagent-input-bar", MessageInputBar)
                    input_bar.set_targets(self._inner_agents)
                except Exception:
                    pass

            # Mount new timelines and load first agent
            if self._panel:
                self._panel.mount_agent_timelines(self._inner_agents)
            if self._current_inner_agent:
                self._load_events_for_agent(self._current_inner_agent)
                self._agents_loaded.add(self._current_inner_agent)

            # Update header
            if self._header:
                self._header.update_subagent(self._subagent)

            # Update tab bar and sync completed subagent statuses
            if self._tab_bar:
                # Use index-to-tab-id mapping for correct activation
                index_to_tab = {v: k for k, v in self._tab_id_to_index.items()} if hasattr(self, "_tab_id_to_index") else {}
                active_tab_id = index_to_tab.get(self._current_index, self._subagent.id)
                self._tab_bar.set_active(active_tab_id)
                for idx, sa in enumerate(self._all_subagents):
                    tab_id = index_to_tab.get(idx, sa.id)
                    self._tab_bar.update_agent_status(
                        tab_id,
                        self._tab_status(sa.status),
                    )

            # Update ribbon agent
            if self._ribbon:
                self._ribbon.set_agent(self._subagent.id)

            # Update status
            self._update_status_display()

            # Restart polling if needed
            if self._subagent.status in ("running", "pending") and not self._poll_timer:
                self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

    def _switch_inner_agent(self, agent_id: str) -> None:
        """Switch to a different inner agent's timeline.

        Toggles CSS visibility — no clear/rebuild needed.
        """
        if agent_id == self._current_inner_agent:
            return

        self._current_inner_agent = agent_id

        # Toggle timeline visibility
        if self._panel:
            self._panel.switch_timeline(agent_id)

        # Load events if this agent's timeline hasn't been populated yet
        if agent_id not in self._agents_loaded:
            self._load_events_for_agent(agent_id)
            self._agents_loaded.add(agent_id)

        # Sync state from the newly active adapter
        self._sync_adapter_state()

        # Update ribbon to show selected agent
        if self._ribbon:
            self._ribbon.set_agent(agent_id)

        # Update inner tab bar selection
        if self._inner_tab_bar:
            self._inner_tab_bar.set_active(agent_id)

    def _load_events_for_agent(self, agent_id: str | None) -> None:
        """Load events filtered by agent ID into that agent's dedicated timeline.

        Args:
            agent_id: The agent ID to filter by, or None for all events
        """
        if not self._panel:
            return

        aid = agent_id or self._subagent.id
        if not self._event_reader:
            self._ensure_terminal_status_note(aid, event_count=0)
            self._update_status_display()
            return

        # Create adapter for this agent if needed
        if aid not in self._event_adapters:
            proxy = _AgentTimelineProxy(self._panel, f"subagent-timeline-{aid}")
            self._event_adapters[aid] = TimelineEventAdapter(proxy, agent_id=aid)

        adapter = self._event_adapters[aid]
        all_events = self._event_reader.read_all()
        self._update_tool_call_agent_map(all_events)
        # Scan all events for winner before filtering
        self._detect_and_apply_winner(all_events)
        events = self._filter_events_for_agent(all_events, agent_id) if agent_id else all_events

        logger.info(f"[SubagentScreen] Loading {len(events)} events for agent {aid}")
        if not events:
            self._ensure_terminal_status_note(aid, event_count=0)
        for event in events:
            adapter.handle_event(self._display_round(event))
        adapter.flush()
        self._sync_adapter_state()
        self._update_status_display()

        # Check if final answer is ready and lock timeline
        self._maybe_lock_final_answer(aid)

    def _maybe_lock_final_answer(self, agent_id: str) -> None:
        """Create a FinalPresentationCard and lock the timeline if final_answer is ready.

        Mirrors the main TUI's behavior: after the final answer event is processed,
        a card is added to the timeline and the timeline locks to show only that card.
        """
        if agent_id in self._final_answer_locked:
            return
        adapter = self._event_adapters.get(agent_id)
        if not adapter or not adapter.final_answer:
            return
        if not self._panel:
            return

        timeline_id = f"subagent-timeline-{agent_id}"
        try:
            timeline = self._panel.query_one(f"#{timeline_id}", TimelineSection)
        except Exception:
            return

        is_running = self._subagent.status in ("running", "pending")
        card: FinalPresentationCard | None = None
        card_id: str | None = None

        # Prefer card created by TimelineEventAdapter answer_locked flow.
        adapter_card = getattr(adapter, "_final_presentation_card", None)
        if isinstance(adapter_card, FinalPresentationCard):
            card = adapter_card
            card_id = card.id or "final_presentation_card"

        # Fallback to any existing final presentation card in this timeline.
        if card is None:
            try:
                existing_cards = list(timeline.query(FinalPresentationCard))
                if existing_cards:
                    card = existing_cards[-1]
                    card_id = card.id or "final_presentation_card"
            except Exception as e:
                tui_log(f"[SubagentScreen] {e}")

        # While still running, avoid synthesizing a fallback card.
        # The canonical final card is created by answer_locked flow.
        if card is None and is_running:
            return

        # Last resort: synthesize a completion-only card from final_answer text.
        if card is None:
            card_id = f"final_presentation_card_{agent_id}"
            card = FinalPresentationCard(
                agent_id=agent_id,
                id=card_id,
            )
            timeline.add_widget(card)

        # Ensure card has final answer text.
        try:
            if adapter.final_answer and not getattr(card, "_final_content", []):
                card.append_chunk(adapter.final_answer)
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        # Mark the card as complete (shows footer with buttons)
        try:
            card.complete()
        except Exception as e:
            tui_log(f"[SubagentScreen] {e}")

        # Auto-collapse task plan when final answer shows
        tph = self._panel._task_plan_hosts.get(agent_id) if self._panel else None
        if tph:
            tph.collapse()

        self._final_answer_locked.add(agent_id)
        logger.info(f"[SubagentScreen] Final answer lock applied for agent {agent_id}")

    def _filter_events_for_agent(self, events: list[MassGenEvent], agent_id: str) -> list[MassGenEvent]:
        """Filter structured events to those relevant for a specific inner agent.

        Routing rules:
        - round_start: pass through for all agents (session-level)
        - tool_start/tool_complete: route via tool_id → agent mapping, fall back to agent_id
        - All other structured events: match on event.agent_id
        - Legacy stream_chunk events: skip (handled by ContentProcessor as no-ops)
        """
        filtered: list[MassGenEvent] = []
        seen_rounds: set = set()

        for event in events:
            if event.event_type == "round_start":
                if event.round_number is not None and event.round_number not in seen_rounds:
                    seen_rounds.add(event.round_number)
                    filtered.append(event)
            elif event.event_type in ("tool_start", "tool_complete"):
                tool_id = event.data.get("tool_id", "")
                mapped = self._tool_call_agent_map.get(tool_id)
                if mapped == agent_id:
                    filtered.append(event)
                elif mapped is None and (event.agent_id == agent_id or len(self._inner_agents) <= 1):
                    filtered.append(event)
            elif event.event_type == "stream_chunk":
                continue
            elif event.agent_id == agent_id:
                filtered.append(event)

        return filtered

    def _update_tool_call_agent_map(self, events: list[MassGenEvent]) -> None:
        """Update tool_id -> agent_id mapping from structured tool_start events."""
        for event in events:
            if event.event_type == "tool_start":
                tool_id = event.data.get("tool_id", "")
                agent_id = event.agent_id
                if tool_id and agent_id and self._is_agent_source(agent_id):
                    self._tool_call_agent_map.setdefault(tool_id, agent_id)
            elif event.event_type == "stream_chunk":
                # Legacy fallback: extract from hook_execution chunks
                chunk = event.data.get("chunk", {}) or {}
                if chunk.get("type") == "hook_execution":
                    tool_call_id = chunk.get("tool_call_id")
                    source = chunk.get("source")
                    if tool_call_id and source and self._is_agent_source(source):
                        self._tool_call_agent_map.setdefault(tool_call_id, source)

    def _is_agent_source(self, source: str | None) -> bool:
        """Check if a source string looks like an inner agent ID (not MCP/hook/system)."""
        if not source:
            return False
        lowered = source.lower()
        if lowered.startswith("mcp_") or lowered.startswith("mcp__") or "mcp__" in lowered:
            return False
        if lowered in ("mcp_setup", "mcp_session"):
            return False
        if "task_reminder" in lowered or "high_priority_task_reminder" in lowered:
            return False
        if lowered.startswith("hook_") or lowered.endswith("_hook"):
            return False
        return True

    def on_subagent_header_context_path_clicked(self, event: SubagentHeader.ContextPathClicked) -> None:
        """Handle context path click from the subagent header."""
        event.stop()
        self._open_context_path(event.path)

    def _open_context_path(self, path_str: str) -> None:
        """Open a context path from the header."""
        if not path_str:
            self.notify("Context path is empty", severity="warning", timeout=2)
            return

        path = Path(path_str).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()

        if not path.exists():
            self.notify(f"Context path not found: {path}", severity="warning", timeout=3)
            return

        try:
            from massgen.frontend.displays.textual import (
                FileInspectionModal,
                TextContentModal,
            )

            if path.is_dir():
                self.app.push_screen(FileInspectionModal(workspace_path=path, app=self.app))
                return

            content = path.read_text(encoding="utf-8", errors="replace")
            if len(content) > 500000:
                content = content[:500000] + "\n\n... [truncated]"
            self.app.push_screen(TextContentModal(title=f"Context: {path}", content=content))
        except Exception as e:
            self.notify(f"Cannot open context path: {e}", severity="error", timeout=3)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle header back button press."""
        if event.button.id == "back_btn":
            self._request_close()
        elif event.button.id == "queue_cancel_latest_button":
            event.stop()
            self._cancel_latest_runtime_queue_message()
        elif event.button.id == "queue_clear_button":
            event.stop()
            self._clear_runtime_queue_messages()
        elif event.button.id == "continue_subagent_button":
            event.stop()
            self._open_continue_subagent_modal()

    def _set_runtime_queue_region_visible(self, visible: bool) -> None:
        if self._queued_runtime_region is None:
            try:
                self._queued_runtime_region = self.query_one("#queued_input_region", Vertical)
            except Exception:
                self._queued_runtime_region = None
        if not self._queued_runtime_region:
            return
        if visible:
            self._queued_runtime_region.add_class("visible")
        else:
            self._queued_runtime_region.remove_class("visible")

        if self._queue_cancel_latest_button is None:
            try:
                self._queue_cancel_latest_button = self.query_one(
                    "#queue_cancel_latest_button",
                    Button,
                )
            except Exception:
                self._queue_cancel_latest_button = None
        if self._queue_clear_button is None:
            try:
                self._queue_clear_button = self.query_one(
                    "#queue_clear_button",
                    Button,
                )
            except Exception:
                self._queue_clear_button = None

        for button in (self._queue_cancel_latest_button, self._queue_clear_button):
            if button is not None:
                button.disabled = not visible

    def _recompute_runtime_pending_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {aid: 0 for aid in self._inner_agents}
        for message in self._queued_runtime_messages:
            for aid in message.get("pending_agents", []) or []:
                counts[aid] = counts.get(aid, 0) + 1
        self._queued_runtime_pending_by_agent = counts
        return counts

    def _refresh_runtime_queue_banner(self) -> None:
        if self._queued_runtime_banner is None:
            try:
                self._queued_runtime_banner = self.query_one(
                    "#queued_input_banner",
                    QueuedInputBanner,
                )
            except Exception:
                self._queued_runtime_banner = None
        counts = self._recompute_runtime_pending_counts()
        if self._queued_runtime_banner:
            try:
                self._queued_runtime_banner.set_messages(self._queued_runtime_messages)
                self._queued_runtime_banner.set_pending_counts(counts)
            except Exception as e:
                tui_log(f"[SubagentScreen] Failed to update runtime queue banner: {e}")
        self._set_runtime_queue_region_visible(bool(self._queued_runtime_messages))

    def _queue_runtime_message(self, content: str, target: str, source_label: str = "parent") -> None:
        if target == "all":
            pending_agents = list(self._inner_agents)
            if not pending_agents:
                fallback_agent = self._current_inner_agent or self._subagent.id
                pending_agents = [fallback_agent] if fallback_agent else []
            target_label = "all agents"
        else:
            pending_agents = [target] if target else []
            target_label = target

        unique_pending = list(dict.fromkeys([aid for aid in pending_agents if aid]))
        message = {
            "id": self._next_runtime_message_id,
            "content": content,
            "target_label": target_label,
            "source_label": source_label,
            "pending_agents": unique_pending,
        }
        self._next_runtime_message_id += 1
        self._queued_runtime_messages.append(message)
        self._refresh_runtime_queue_banner()

    def _append_runtime_queue_status_note(
        self,
        content: str,
        target: str,
        source_label: str = "parent",
        pending_agents: list[str] | None = None,
        target_label_override: str | None = None,
    ) -> None:
        """Render an immediate timeline note when runtime input is queued.

        Delivery still occurs at the next hook/checkpoint; this note confirms
        the queue action in the subagent timeline right away.
        """
        if not self._panel:
            return

        payload = self._normalize_runtime_message_text(content)
        if not payload:
            return
        if len(payload) > 180:
            payload = payload[:177] + "..."

        if pending_agents is not None:
            target_agents = [aid for aid in pending_agents if aid]
            target_label = target_label_override or (target if target else "selected agents")
        elif target == "all":
            target_agents = [aid for aid in self._inner_agents if aid]
            if not target_agents:
                fallback_agent = self._current_inner_agent or self._subagent.id
                target_agents = [fallback_agent] if fallback_agent else []
            target_label = target_label_override or "all agents"
        else:
            fallback_agent = self._current_inner_agent or self._subagent.id
            target_agents = [target] if target else ([fallback_agent] if fallback_agent else [])
            target_label = target_label_override or (target or "selected agent")

        unique_agents = list(dict.fromkeys(target_agents))
        if not unique_agents:
            return

        normalized_source = " ".join((source_label or "parent").split()) or "parent"
        note = f"Runtime Injection -> Queued from {normalized_source} to {target_label}: {payload}"

        try:
            round_number = max(1, int(self._round_number or 1))
        except Exception:
            round_number = 1

        for agent_id in unique_agents:
            try:
                timeline = self._panel.query_one(
                    f"#subagent-timeline-{agent_id}",
                    TimelineSection,
                )
            except Exception:
                continue

            try:
                timeline.add_text(
                    note,
                    style="dim cyan",
                    text_class="status runtime-injection",
                    round_number=round_number,
                )
            except Exception as e:
                tui_log(f"[SubagentScreen] Failed to add runtime queue status note: {e}")

    def _resolve_runtime_inbox_dir(self) -> Path | None:
        """Resolve this subagent's runtime inbox directory, if available."""
        workspace_path = str(getattr(self._subagent, "workspace_path", "") or "").strip()
        if not workspace_path:
            return None

        workspace = Path(workspace_path).expanduser()
        if not workspace.is_absolute():
            workspace = (Path.cwd() / workspace).resolve()
        return workspace / ".massgen" / "runtime_inbox"

    def _normalize_runtime_targets_from_inbox(self, target_agents: Any) -> tuple[list[str], str]:
        """Convert runtime inbox target payload into pending agent IDs + label."""
        parsed_targets: list[str] = []
        if isinstance(target_agents, list):
            for raw in target_agents:
                value = str(raw or "").strip()
                if value:
                    parsed_targets.append(value)

        if parsed_targets:
            unique_targets = list(dict.fromkeys(parsed_targets))
            return unique_targets, ", ".join(unique_targets)

        broadcast_targets = [aid for aid in self._inner_agents if aid]
        if not broadcast_targets:
            fallback_agent = self._current_inner_agent or self._subagent.id
            broadcast_targets = [fallback_agent] if fallback_agent else []
        return list(dict.fromkeys(broadcast_targets)), "all agents"

    def _sync_runtime_queue_from_inbox(self) -> None:
        """Mirror pending runtime inbox files into queued banner/timeline state."""
        if not self._send_message_callback:
            return

        if self._runtime_inbox_dir is None:
            self._runtime_inbox_dir = self._resolve_runtime_inbox_dir()
        inbox_dir = self._runtime_inbox_dir
        if inbox_dir is None or not inbox_dir.exists() or not inbox_dir.is_dir():
            return

        changed = False
        try:
            inbox_files = sorted(inbox_dir.glob("msg_*.json"))
        except Exception:
            return

        for message_file in inbox_files:
            file_key = str(message_file.resolve())
            if file_key in self._runtime_inbox_seen_files:
                continue
            self._runtime_inbox_seen_files.add(file_key)

            try:
                payload = json.loads(message_file.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue

            content = str(payload.get("content", "")).strip()
            if not content:
                continue

            source_label = str(payload.get("source", "parent") or "parent").strip().lower() or "parent"
            pending_agents, target_label = self._normalize_runtime_targets_from_inbox(payload.get("target_agents"))
            if not pending_agents:
                continue

            normalized_content = self._normalize_runtime_message_text(content)
            pending_set = set(pending_agents)
            duplicate = False
            for queued in self._queued_runtime_messages:
                queued_content = self._normalize_runtime_message_text(str(queued.get("content", "")))
                queued_source = str(queued.get("source_label", "human"))
                queued_target_label = str(queued.get("target_label", ""))
                queued_pending = {str(aid) for aid in queued.get("pending_agents", []) if str(aid)}
                if queued_content == normalized_content and queued_source == source_label and queued_target_label == target_label and queued_pending == pending_set:
                    duplicate = True
                    break

            if duplicate:
                continue

            self._queued_runtime_messages.append(
                {
                    "id": message_file.stem,
                    "content": content,
                    "target_label": target_label,
                    "source_label": source_label,
                    "pending_agents": pending_agents,
                },
            )
            self._append_runtime_queue_status_note(
                content,
                target="all" if target_label == "all agents" else (pending_agents[0] if pending_agents else "all"),
                source_label=source_label,
                pending_agents=pending_agents,
                target_label_override=target_label,
            )
            changed = True

        if changed:
            self._refresh_runtime_queue_banner()

    def _cancel_latest_runtime_queue_message(self) -> None:
        if not self._queued_runtime_messages:
            return
        removed = self._queued_runtime_messages.pop()
        self._refresh_runtime_queue_banner()
        preview = " ".join(str(removed.get("content", "")).split())
        if len(preview) > 56:
            preview = preview[:53] + "..."
        self.notify(f'Cancelled latest queued message: "{preview}"', timeout=3)

    def _clear_runtime_queue_messages(self) -> None:
        if not self._queued_runtime_messages:
            return
        self._queued_runtime_messages = []
        self._queued_runtime_pending_by_agent = {}
        self._refresh_runtime_queue_banner()
        self.notify("Cleared queued runtime messages", timeout=2)

    def _refresh_continue_button_visibility(self) -> None:
        """Show continue control only when subagent is not actively running."""
        if self._continue_subagent_button is None:
            return
        is_running = self._subagent.status in ("running", "pending")
        self._continue_subagent_button.display = not is_running
        self._continue_subagent_button.disabled = is_running

    def _open_continue_subagent_modal(self) -> None:
        """Open modal prompt for continuation message."""
        if not self._continue_subagent_callback:
            return

        def _on_dismiss(message: str | None) -> None:
            if not message:
                return
            self._continue_subagent_with_message(message)

        try:
            self.app.push_screen(
                ContinueSubagentModal(self._subagent.id),
                _on_dismiss,
            )
        except Exception as e:
            self.notify(f"Cannot open continue prompt: {e}", severity="error", timeout=3)

    def _continue_subagent_with_message(self, message: str) -> bool:
        """Continue this subagent with a user-provided message."""
        normalized = (message or "").strip()
        if not normalized:
            self.notify("Continue message cannot be empty", severity="warning", timeout=2)
            return False
        if not self._continue_subagent_callback:
            self.notify("Continue callback unavailable", severity="warning", timeout=2)
            return False

        try:
            success = bool(self._continue_subagent_callback(self._subagent.id, normalized))
        except Exception as e:
            self.notify(f"Failed to continue subagent: {e}", severity="warning", timeout=3)
            return False

        if not success:
            self.notify("Failed to continue subagent", severity="warning", timeout=3)
            return False

        self._subagent.status = "running"
        self._subagent.error = None
        self._subagent.elapsed_seconds = 0.0
        self._terminal_status_notes.clear()
        self._update_status_display()

        try:
            input_bar = self.query_one("#subagent-input-bar")
            input_bar.display = True
        except Exception:
            pass

        if self._poll_timer is None:
            self._poll_timer = self.set_interval(self.POLL_INTERVAL, self._poll_updates)

        self.notify("Continuing subagent...", timeout=2)
        return True

    @staticmethod
    def _normalize_runtime_message_text(raw: str) -> str:
        return " ".join((raw or "").split())

    @staticmethod
    def _extract_human_input_payload(injection_content: str) -> str:
        content = injection_content or ""
        marker = "[Human Input]:"
        idx = content.find(marker)
        if idx >= 0:
            content = content[idx + len(marker) :]
        return content.strip()

    def _mark_runtime_messages_delivered_for_agent(
        self,
        agent_id: str,
        injection_content: str | None = None,
    ) -> None:
        changed = False
        normalized_payload = self._normalize_runtime_message_text(
            self._extract_human_input_payload(injection_content or ""),
        )
        updated_messages: list[dict[str, Any]] = []

        candidate_indices: list[int] = []
        for idx, message in enumerate(self._queued_runtime_messages):
            pending_agents = list(message.get("pending_agents", []) or [])
            if agent_id in pending_agents:
                candidate_indices.append(idx)

        matched_indices: set[int] = set()
        if normalized_payload:
            for idx in candidate_indices:
                message_content = self._normalize_runtime_message_text(
                    str(self._queued_runtime_messages[idx].get("content", "")),
                )
                if message_content and message_content in normalized_payload:
                    matched_indices.add(idx)

        # Fallback: if no text match is available, mark only the oldest pending message.
        if not matched_indices and candidate_indices:
            matched_indices.add(candidate_indices[0])

        for message_idx, message in enumerate(self._queued_runtime_messages):
            pending_agents = list(message.get("pending_agents", []) or [])
            if message_idx in matched_indices and agent_id in pending_agents:
                pending_agents = [aid for aid in pending_agents if aid != agent_id]
                changed = True
            message["pending_agents"] = pending_agents
            if pending_agents:
                updated_messages.append(message)
            else:
                changed = True

        if changed:
            self._queued_runtime_messages = updated_messages
            self._refresh_runtime_queue_banner()

    def _update_runtime_queue_from_events(self, events: list[MassGenEvent]) -> None:
        for event in events:
            if event.event_type == "hook_execution":
                hook_info = event.data.get("hook_info", {}) if isinstance(event.data, dict) else {}
                if hook_info.get("hook_name") != "human_input_hook":
                    continue
                injection_content = hook_info.get("injection_content")
                if not injection_content:
                    continue
                if event.agent_id:
                    self._mark_runtime_messages_delivered_for_agent(
                        event.agent_id,
                        injection_content=str(injection_content),
                    )
                continue

            if event.event_type == "injection_received" and event.agent_id:
                event_data = event.data if isinstance(event.data, dict) else {}
                injection_type = str(event_data.get("injection_type", "")).strip().lower()
                source_agents = [str(source).strip().lower() for source in event_data.get("source_agents", []) or [] if str(source).strip()]
                if injection_type in {"runtime_inbox_input", "hookless_human_input"} or "parent" in source_agents or "human" in source_agents:
                    self._mark_runtime_messages_delivered_for_agent(event.agent_id)

    def on_message_input_bar_submitted(self, event: Any) -> None:
        """Handle message submission from the MessageInputBar."""
        if not self._send_message_callback:
            return
        event.stop()
        subagent_id = self._subagent.id
        target = event.target
        if target == "all":
            success = self._send_message_callback(subagent_id, event.value, target_agents=None)
        else:
            success = self._send_message_callback(subagent_id, event.value, target_agents=[target])
        if success:
            source_label = "parent"
            self._queue_runtime_message(event.value, target=target, source_label=source_label)
            self._append_runtime_queue_status_note(
                event.value,
                target=target,
                source_label=source_label,
            )
            label = "all agents" if target == "all" else target
            self.notify(f"Message sent to {label}", timeout=2)
        else:
            self.notify("Failed to send message", severity="warning", timeout=3)

    def on__footer_action_clicked(self, event: _FooterAction.Clicked) -> None:
        """Handle footer action clicks."""
        if event.action_id == "back":
            self._request_close()
        elif event.action_id == "copy":
            self._copy_answer()

    def on_session_info_clicked(self, event: SessionInfoClicked) -> None:
        """Handle click on session info to show full prompt."""
        event.stop()
        try:
            from massgen.frontend.displays.textual import TextContentModal

            content = ""
            if event.subtask:
                content += f"Subtask: {event.subtask}\n\n"
            content += event.question or "(No prompt)"
            self.app.push_screen(
                TextContentModal(
                    title=f"Turn {event.turn} • Prompt",
                    content=content,
                ),
            )
        except Exception as e:
            self.notify(f"Cannot show prompt: {e}", severity="error", timeout=3)

    def on_agent_tab_changed(self, event: AgentTabChanged) -> None:
        """Handle tab bar agent selection."""
        event.stop()

        # Determine which tab bar sent the event
        # Check by comparing the control's ID or parent
        control_id = event.control.id if event.control else None

        if control_id == "subagent-tab-bar":
            # Top-level subagent selector - use tab_id_to_index for safe lookup
            # (handles duplicate subagent IDs correctly)
            idx = getattr(self, "_tab_id_to_index", {}).get(event.agent_id)
            if idx is not None:
                self._switch_subagent(idx)
            else:
                # Fallback: linear scan by sa.id
                for i, sa in enumerate(self._all_subagents):
                    if sa.id == event.agent_id:
                        self._switch_subagent(i)
                        break
        elif control_id == "inner-agent-tabs":
            # Inner agent tabs - switch to different inner agent within same subagent
            self._switch_inner_agent(event.agent_id)
        else:
            # Fallback: check tab_id_to_index first, then linear scan
            idx = getattr(self, "_tab_id_to_index", {}).get(event.agent_id)
            if idx is not None:
                self._switch_subagent(idx)
            elif event.agent_id in self._inner_agents:
                self._switch_inner_agent(event.agent_id)
            else:
                for i, sa in enumerate(self._all_subagents):
                    if sa.id == event.agent_id:
                        self._switch_subagent(i)
                        return

    def action_close(self) -> None:
        """Close the screen and return to main view."""
        self._request_close()

    def action_next_subagent(self) -> None:
        """Navigate to next subagent."""
        self._switch_subagent((self._current_index + 1) % len(self._all_subagents))

    def action_prev_subagent(self) -> None:
        """Navigate to previous subagent."""
        self._switch_subagent((self._current_index - 1) % len(self._all_subagents))

    def action_toggle_task_plan(self) -> None:
        """Toggle task plan collapse/expand."""
        if self._panel:
            self._panel.toggle_task_plan()

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

    def on_key(self, event) -> None:
        """Handle single-key shortcuts and stop propagation to prevent main TUI from handling them."""
        char = event.character or ""
        key_lower = char.lower()

        if key_lower == "w":
            self.action_open_workspace()
            event.stop()
        elif key_lower == "h":
            self.action_open_history()
            event.stop()
        elif char == "?":
            self.action_show_shortcuts()
            event.stop()
        elif key_lower == "c":
            self.action_copy_answer()
            event.stop()
        elif key_lower == "s":
            self._show_subagent_status()
            event.stop()
        elif key_lower == "o":
            self._show_full_output()
            event.stop()
        elif key_lower == "v":
            self.notify("Vote results not available in subagent view", severity="information", timeout=2)
            event.stop()
        elif key_lower == "t":
            self.notify("Timeline browser not available in subagent view", severity="information", timeout=2)
            event.stop()
        elif key_lower == "a":
            self._show_answer_view()
            event.stop()
        elif key_lower == "m":
            self.notify("MCP status not available in subagent view", severity="information", timeout=2)
            event.stop()
        elif key_lower == "q":
            self._request_close()
            event.stop()
        elif char.isdigit() and char != "0":
            # Number keys to switch subagents
            idx = int(char) - 1
            if 0 <= idx < len(self._all_subagents):
                self._switch_subagent(idx)
            event.stop()

    def action_open_workspace(self) -> None:
        """Open workspace browser scoped to subagent's workspace."""
        workspace_path = self._subagent.workspace_path
        if not workspace_path:
            self.notify("No workspace available", severity="warning", timeout=2)
            return
        from pathlib import Path

        wp = Path(workspace_path)
        if not wp.exists():
            self.notify("Workspace not found", severity="warning", timeout=2)
            return
        try:
            from massgen.frontend.displays.textual import FileInspectionModal

            modal = FileInspectionModal(workspace_path=wp, app=self.app)
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot open workspace: {e}", severity="error", timeout=3)

    def action_open_history(self) -> None:
        """Open conversation history for subagent."""
        # Read events and build a simple history view
        if not self._event_reader:
            self.notify("No event data available", severity="warning", timeout=2)
            return
        try:
            from massgen.frontend.displays.textual import TextContentModal

            events = self._event_reader.read_all()
            # Build a simple text summary of the conversation
            lines = []
            for event in events:
                if event.event_type == "stream_chunk":
                    chunk = event.data.get("chunk", {}) or {}
                    chunk_type = chunk.get("type")
                    if chunk_type == "text":
                        content = chunk.get("content", "")
                        if content.strip():
                            source = chunk.get("source", event.agent_id or "agent")
                            lines.append(f"[{source}] {content[:200]}")
                    elif chunk_type == "thinking":
                        content = chunk.get("content", "")
                        if content.strip():
                            lines.append(f"[thinking] {content[:100]}...")
            if not lines:
                self.notify("No conversation history yet", severity="information", timeout=2)
                return
            text = "\n\n".join(lines[-50:])  # Last 50 entries
            modal = TextContentModal(title=f"History: {self._subagent.id}", content=text)
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot open history: {e}", severity="error", timeout=3)

    def action_show_shortcuts(self) -> None:
        """Show keyboard shortcuts help for subagent view."""
        try:
            from massgen.frontend.displays.textual import TextContentModal

            shortcuts = (
                "Subagent View Shortcuts\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Navigation\n"
                "  Tab        Next subagent\n"
                "  Shift+Tab  Previous subagent\n"
                "  1-9        Switch to subagent by number\n"
                "  Escape/q   Back to main view\n\n"
                "Info\n"
                "  w          Workspace browser\n"
                "  h          Conversation history\n"
                "  s          Subagent status\n"
                "  o          Full output (raw events)\n"
                "  a          Answer preview\n"
                "  c          Copy answer\n"
                "  ?          This help\n"
            )
            modal = TextContentModal(title="Keyboard Shortcuts", content=shortcuts)
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot show shortcuts: {e}", severity="error", timeout=3)

    def _show_subagent_status(self) -> None:
        """Show subagent status summary."""
        try:
            from massgen.frontend.displays.textual import TextContentModal

            sa = self._subagent
            lines = [
                f"Subagent: {sa.id}",
                f"Status:   {sa.status}",
                f"Elapsed:  {int(sa.elapsed_seconds)}s",
                f"Timeout:  {int(sa.timeout_seconds)}s",
            ]
            if sa.task:
                lines.append(f"Task:     {sa.task}")
            if sa.workspace_path:
                lines.append(f"Workspace: {sa.workspace_path}")
            if sa.log_path:
                lines.append(f"Log path: {sa.log_path}")
            if sa.error:
                lines.append(f"Error:    {sa.error}")
            if self._inner_agents:
                lines.append(f"\nInner agents: {', '.join(sorted(self._inner_agents))}")

            modal = TextContentModal(title=f"Status: {sa.id}", content="\n".join(lines))
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot show status: {e}", severity="error", timeout=3)

    def _show_full_output(self) -> None:
        """Show full raw output from subagent events."""
        if not self._event_reader:
            self.notify("No event data available", severity="warning", timeout=2)
            return
        try:
            from massgen.frontend.displays.textual import TextContentModal

            events = self._event_reader.read_all()
            lines = []
            for ev in events:
                if ev.event_type != "stream_chunk":
                    continue
                chunk = ev.data.get("chunk", {}) or {}
                chunk_type = chunk.get("type")
                content = chunk.get("content", "")
                if chunk_type == "text" and content.strip():
                    lines.append(content)
                elif chunk_type == "thinking" and content.strip():
                    lines.append(f"[thinking] {content}")

            if not lines:
                self.notify("No output yet", severity="information", timeout=2)
                return

            modal = TextContentModal(
                title=f"Full Output: {self._subagent.id}",
                content="\n".join(lines[-100:]),
            )
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot show output: {e}", severity="error", timeout=3)

    def _show_answer_view(self) -> None:
        """Show the subagent's answer."""
        content = self._final_answer or self._subagent.answer_preview
        if not content:
            self.notify("No answer yet", severity="information", timeout=2)
            return
        try:
            from massgen.frontend.displays.textual import TextContentModal

            modal = TextContentModal(title=f"Answer: {self._subagent.id}", content=content)
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Cannot show answer: {e}", severity="error", timeout=3)

    def _request_close(self) -> None:
        """Request the parent to close the view."""
        self.post_message(self.CloseRequested())


class SubagentScreen(Screen):
    """Screen wrapper for the reusable SubagentView."""

    DEFAULT_CSS = """
    SubagentScreen {
        width: 100%;
        height: 100%;
        background: $background;
    }
    """

    def __init__(
        self,
        subagent: SubagentDisplayData,
        all_subagents: list[SubagentDisplayData] | None = None,
        status_callback: Callable[[str], SubagentDisplayData | None] | None = None,
        auto_return_on_completion: bool = False,
        send_message_callback: Callable[..., bool] | None = None,
        continue_subagent_callback: Callable[..., bool] | None = None,
    ) -> None:
        super().__init__()
        self._subagent = subagent
        self._all_subagents = all_subagents
        self._status_callback = status_callback
        self._auto_return_on_completion = auto_return_on_completion
        self._send_message_callback = send_message_callback
        self._continue_subagent_callback = continue_subagent_callback

    def compose(self) -> ComposeResult:
        yield SubagentView(
            subagent=self._subagent,
            all_subagents=self._all_subagents,
            status_callback=self._status_callback,
            auto_return_on_completion=self._auto_return_on_completion,
            send_message_callback=self._send_message_callback,
            continue_subagent_callback=self._continue_subagent_callback,
            id="subagent-view",
        )

    def on_subagent_view_close_requested(self, event: SubagentView.CloseRequested) -> None:
        event.stop()
        self.dismiss()
