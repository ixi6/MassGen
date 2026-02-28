"""Content-related modals: Text, Turn details, Conversation history, Context."""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from textual.app import ComposeResult
    from textual.containers import (
        Container,
        Horizontal,
        ScrollableContainer,
        VerticalScroll,
    )
    from textual.widget import Widget
    from textual.widgets import Button, Input, Label, Select, Static, TextArea

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal

if TYPE_CHECKING:
    from massgen.frontend.displays.textual_terminal_display import (
        TextualApp,
        TextualTerminalDisplay,
    )


class TextContentModal(BaseModal):
    """Generic modal to display text content from a file or buffer."""

    def __init__(self, title: str, content: str):
        super().__init__()
        self.title = title
        self.content = content

    def compose(self) -> ComposeResult:
        with Container(id="text_content_container"):
            yield Label(self.title, id="text_content_header")
            yield TextArea(self.content, id="text_content_body", read_only=True)
            yield Button("Close (ESC)", id="close_text_content_button")


class EvaluationCriteriaModal(BaseModal):
    """Modal showing the active evaluation criteria (E1, E2, …) for the current run."""

    # Category badge markup: MUST=red bold, SHOULD=yellow, COULD=green dim
    _CATEGORY_COLORS: dict[str, str] = {
        "must": "[bold red]MUST[/]",
        "should": "[yellow]SHOULD[/]",
        "could": "[green]COULD[/]",
    }

    def __init__(
        self,
        criteria: list[dict] | None,
        source: str = "default",
    ):
        super().__init__()
        self._criteria: list[dict] = list(criteria) if criteria else []
        self._source = source

    # ------------------------------------------------------------------
    # Helper methods (tested directly by unit tests)
    # ------------------------------------------------------------------

    def _category_badge(self, category: str) -> str:
        """Return Rich-markup badge for a criterion category."""
        return self._CATEGORY_COLORS.get(category.lower(), f"[dim]{category.upper()}[/]")

    def _build_summary_line(self) -> str:
        """Return a one-line summary: count + source + per-category breakdown."""
        total = len(self._criteria)
        if total == 0:
            return "[dim]No evaluation criteria loaded.[/]"
        counts: dict[str, int] = {}
        for c in self._criteria:
            cat = c.get("category", "should").lower()
            counts[cat] = counts.get(cat, 0) + 1
        parts = []
        for cat in ("must", "should", "could"):
            n = counts.get(cat, 0)
            if n:
                parts.append(f"{n} {cat}")
        breakdown = ", ".join(parts) if parts else f"{total}"
        source_label = f"  [dim]source: {self._source}[/]" if self._source != "default" else ""
        return f"[bold]{total}[/] criteria ({breakdown}){source_label}"

    def _render_criterion(self, criterion: dict) -> str:
        """Return Rich-markup string for a single criterion entry."""
        cid = criterion.get("id", "?")
        text = criterion.get("text", "")
        category = criterion.get("category", "should")
        verify_by = criterion.get("verify_by")

        badge = self._category_badge(category)
        lines = [f"[bold cyan]{cid}[/]  {badge}   {text}"]
        if verify_by:
            lines.append(f"  [dim]Verify: {verify_by}[/]")
        return "\n".join(lines)

    def _build_content(self) -> str:
        """Return the full scrollable content string for all criteria."""
        if not self._criteria:
            return "[dim]No evaluation criteria are active for this run.[/]"
        separator = "\n" + "─" * 60 + "\n"
        return separator.join(self._render_criterion(c) for c in self._criteria)

    # ------------------------------------------------------------------
    # Textual compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="eval_criteria_container"):
            yield Label("Evaluation Criteria", id="eval_criteria_header")
            yield Static(
                self._build_summary_line(),
                id="eval_criteria_summary",
                markup=True,
            )
            with VerticalScroll(id="eval_criteria_scroll"):
                yield Static(
                    self._build_content(),
                    id="eval_criteria_body",
                    markup=True,
                )
            yield Button("Close (ESC)", id="eval_criteria_close_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "eval_criteria_close_button":
            self.dismiss()


class TurnDetailModal(BaseModal):
    """Modal showing full details of a conversation turn."""

    def __init__(
        self,
        turn_data: dict[str, Any],
        agent_color_class: str,
    ):
        super().__init__()
        self._turn_data = turn_data
        self._agent_color_class = agent_color_class

    def compose(self) -> ComposeResult:
        turn = self._turn_data.get("turn", "?")
        question = self._turn_data.get("question", "")
        answer = self._turn_data.get("answer", "")
        agent_id = self._turn_data.get("agent_id", "")
        model = self._turn_data.get("model", "")
        timestamp = self._turn_data.get("timestamp", 0)
        workspace_path = self._turn_data.get("workspace_path")

        # Format timestamp
        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else ""
        agent_info = f"{agent_id} ({model})" if model else agent_id

        with Container(id="turn_detail_container", classes=self._agent_color_class):
            # Header with turn info
            yield Label(
                f"[bold cyan]Turn {turn}[/] - {time_str}",
                id="turn_detail_header",
                markup=True,
            )
            yield Label(f"[dim]Winner: {agent_info}[/]", id="turn_detail_agent", markup=True)

            # Question
            yield Label("[bold]Question:[/]", markup=True)
            yield Static(question, id="turn_detail_question")

            # Full answer in scrollable container
            yield Label("[bold]Answer:[/]", markup=True)
            with ScrollableContainer(id="turn_detail_answer_scroll"):
                yield Static(answer, id="turn_detail_answer")

            # Footer buttons
            with Horizontal(id="turn_detail_footer"):
                if workspace_path:
                    yield Button("📂 Open Workspace", id="turn_detail_workspace_button")
                yield Button("Close (ESC)", id="turn_detail_close_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "turn_detail_close_button":
            self.dismiss()
        elif event.button.id == "turn_detail_workspace_button":
            self._open_workspace_in_explorer()

    def _open_workspace_in_explorer(self) -> None:
        """Open the turn's workspace directory in the system file explorer."""
        import platform
        import subprocess

        workspace_path = self._turn_data.get("workspace_path")
        if not workspace_path:
            self.notify("No workspace available for this turn", severity="warning", timeout=2)
            return

        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.run(["open", str(workspace_path)])
            elif system == "Windows":
                subprocess.run(["explorer", str(workspace_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(workspace_path)])
        except Exception as e:
            self.notify(f"Error opening workspace: {e}", severity="error", timeout=3)


class ConversationHistoryModal(BaseModal):
    """Modal showing conversation history and current prompt."""

    def __init__(
        self,
        conversation_history: list[dict[str, Any]],
        current_question: str,
        agent_ids: list[str],
    ):
        super().__init__()
        self._history = conversation_history
        self._current_question = current_question
        self._agent_ids = agent_ids

    def compose(self) -> ComposeResult:
        with Container(id="history_container"):
            yield Label("📜 Conversation History", id="history_header")

            # Show current prompt if any
            if self._current_question:
                yield Label(f"[bold]Current:[/] {self._current_question}", id="current_prompt")

            # Scrollable history container
            with ScrollableContainer(id="history_scroll"):
                if self._history:
                    for idx, entry in enumerate(reversed(self._history)):  # Most recent first
                        yield self._create_turn_widget(entry, idx)
                else:
                    yield Label("[dim]No conversation history yet.[/]", id="no_history")

            yield Button("Close (ESC)", id="close_history_button")

    def _get_agent_color_class(self, agent_id: str) -> str:
        """Get the agent color class for an agent ID."""
        if agent_id in self._agent_ids:
            agent_idx = self._agent_ids.index(agent_id) + 1
            return f"agent-color-{((agent_idx - 1) % 8) + 1}"
        return "agent-color-1"

    def _create_turn_widget(self, entry: dict[str, Any], idx: int) -> Widget:
        """Create a clickable widget for a conversation turn with agent color."""
        turn = entry.get("turn", "?")
        question = entry.get("question", "")
        answer = entry.get("answer", "")
        agent_id = entry.get("agent_id", "")
        model = entry.get("model", "")
        timestamp = entry.get("timestamp", 0)
        workspace_path = entry.get("workspace_path")

        # Format timestamp
        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else ""

        # Truncate answer for display
        answer_preview = answer[:200] + "..." if len(answer) > 200 else answer

        agent_info = f"{agent_id} ({model})" if model else agent_id
        agent_color_class = self._get_agent_color_class(agent_id)

        # Build content - workspace indicator if available
        workspace_indicator = " 📂" if workspace_path else ""

        content = f"""[bold cyan]Turn {turn}[/] - {time_str}{workspace_indicator}
[bold]Q:[/] {question}
[dim]Winner: {agent_info}[/]
[bold]A:[/] {answer_preview}
"""
        # Return a container with turn index in ID for click handling
        # The actual_idx is the original index in _history (before reversal)
        actual_idx = len(self._history) - 1 - idx
        return Static(
            content,
            id=f"history_turn_{actual_idx}",
            classes=f"history-turn turn-entry {agent_color_class}",
            markup=True,
        )

    def on_click(self, event) -> None:
        """Handle clicks on turn entries to show full details."""
        # Walk up to find the turn widget
        target = event.widget
        while target and not (hasattr(target, "id") and target.id and target.id.startswith("history_turn_")):
            target = getattr(target, "parent", None)

        if target and target.id:
            try:
                idx = int(target.id.split("_")[-1])
                if 0 <= idx < len(self._history):
                    entry = self._history[idx]
                    agent_id = entry.get("agent_id", "")
                    agent_color_class = self._get_agent_color_class(agent_id)
                    self.app.push_screen(TurnDetailModal(entry, agent_color_class))
            except (ValueError, IndexError):
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close_history_button":
            self.dismiss()


class ContextModal(BaseModal):
    """Modal for managing context paths with interactive permission toggling and removal."""

    DEFAULT_CSS = """
    ContextModal #context_container {
        width: 80;
        max-height: 35;
    }

    ContextModal .context-path-row {
        height: 3;
        width: 100%;
    }

    ContextModal .context-path-text {
        width: 1fr;
        height: 3;
        content-align: left middle;
        padding: 0 1;
    }

    ContextModal .perm-badge {
        min-width: 10;
        max-width: 10;
        margin: 0 1;
    }

    ContextModal .remove-path-btn {
        min-width: 5;
        max-width: 5;
    }

    ContextModal #context_paths_list {
        max-height: 15;
        border: solid $primary-background;
        margin: 1 0;
        padding: 1;
    }

    ContextModal #add_path_form {
        height: 3;
        width: 100%;
    }

    ContextModal #new_path_input {
        width: 1fr;
    }

    ContextModal #new_perm_select {
        width: 14;
        margin: 0 1;
    }

    ContextModal #context_info_hint {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 0;
    }

    ContextModal #close_context_button {
        margin-top: 1;
    }
    """

    def __init__(self, display: "TextualTerminalDisplay", app: "TextualApp"):
        super().__init__()
        self.coordination_display = display
        self.app_ref = app

    def _get_current_paths(self) -> list[dict[str, Any]]:
        """Get current context paths from agents' PathPermissionManager."""
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator or not hasattr(orchestrator, "agents"):
            return []
        # Read from first agent's PathPermissionManager
        for _agent_id, agent in orchestrator.agents.items():
            ppm = getattr(getattr(agent, "backend", None), "filesystem_manager", None)
            if ppm:
                ppm = getattr(ppm, "path_permission_manager", None)
            if ppm:
                return ppm.get_context_paths()
        return []

    def _get_worktree_info(self) -> dict[str, dict[str, str]]:
        """Get worktree path mappings from orchestrator, keyed by agent_id.

        Returns: {agent_id: {worktree_path: original_path}}
        """
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator:
            return {}
        return getattr(orchestrator, "_round_worktree_paths", {})

    def _get_write_mode(self) -> str:
        """Get write_mode from coordination config."""
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator:
            return ""
        coord_config = getattr(getattr(orchestrator, "config", None), "coordination_config", None)
        return getattr(coord_config, "write_mode", None) or ""

    def compose(self) -> ComposeResult:
        with Container(id="context_container"):
            yield Label("Context Paths", id="context_header")
            write_mode = self._get_write_mode()
            if write_mode and write_mode != "legacy":
                yield Label(
                    f"write_mode={write_mode} — agents work in worktrees, originals not mounted",
                    id="context_hint",
                )
            else:
                yield Label("Paths that agents can access:", id="context_hint")
            with ScrollableContainer(id="context_paths_list"):
                yield from self._build_path_rows()
            yield Label("Add new path:", id="add_path_label")
            with Horizontal(id="add_path_form"):
                yield Input(placeholder="Enter path to add...", id="new_path_input")
                yield Select(
                    [("Read", "read"), ("Write", "write")],
                    value="read",
                    id="new_perm_select",
                    allow_blank=False,
                )
                yield Button("Add", id="add_path_button", variant="primary")
            yield Label("Changes take effect on the next turn.", id="context_info_hint")
            yield Button("Close (ESC)", id="close_context_button", variant="default")

    def _build_path_rows(self) -> list[Widget]:
        """Build interactive rows for each context path."""
        paths = self._get_current_paths()
        if not paths:
            return [Static("[dim]No context paths configured.[/]", id="no_paths_msg", markup=True)]

        # Build reverse mapping: original_path -> worktree_path (from any agent)
        worktree_lookup: dict[str, str] = {}
        for _agent_id, wt_map in self._get_worktree_info().items():
            for wt_path, orig_path in wt_map.items():
                worktree_lookup[orig_path] = wt_path

        rows = []
        for i, path_info in enumerate(paths):
            path_str = path_info.get("path", "")
            perm = path_info.get("permission", "read")
            perm_label = "Write" if perm == "write" else "Read"
            perm_variant = "success" if perm == "write" else "primary"

            # Show worktree path if this context path has one
            wt_path = worktree_lookup.get(path_str)
            if wt_path:
                display_text = f"{path_str}\n  [dim]worktree: {wt_path}[/]"
            else:
                display_text = path_str

            row = Horizontal(
                Static(display_text, classes="context-path-text", markup=True),
                Button(perm_label, id=f"toggle_perm_{i}", variant=perm_variant, classes="perm-badge"),
                Button("X", id=f"remove_path_{i}", variant="error", classes="remove-path-btn"),
                classes="context-path-row",
                id=f"path_row_{i}",
            )
            rows.append(row)
        return rows

    def _refresh_paths_display(self) -> None:
        """Refresh the paths list by clearing and re-mounting rows."""
        container = self.query_one("#context_paths_list", ScrollableContainer)
        container.remove_children()
        for row in self._build_path_rows():
            container.mount(row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for toggle, remove, add, and close."""
        button_id = event.button.id or ""

        if button_id.startswith("toggle_perm_"):
            idx = int(button_id.split("_")[-1])
            self._toggle_permission(idx)
        elif button_id.startswith("remove_path_"):
            idx = int(button_id.split("_")[-1])
            self._remove_path(idx)
        elif button_id == "add_path_button":
            self._add_path()
        elif button_id == "close_context_button":
            self.dismiss()

    def _toggle_permission(self, idx: int) -> None:
        """Toggle permission between read and write for path at index."""
        paths = self._get_current_paths()
        if idx < 0 or idx >= len(paths):
            return
        path_info = paths[idx]
        path_str = path_info["path"]
        current_perm = path_info.get("permission", "read")
        new_perm = "write" if current_perm == "read" else "read"

        self._propagate_permission_update(path_str, new_perm)
        self._refresh_paths_display()
        self.app_ref.notify(f"Permission: {path_str} -> {new_perm}", severity="information")

    def _remove_path(self, idx: int) -> None:
        """Remove the context path at the given index."""
        paths = self._get_current_paths()
        if idx < 0 or idx >= len(paths):
            return
        path_str = paths[idx]["path"]

        self._propagate_remove(path_str)
        self._refresh_paths_display()
        self.app_ref.notify(f"Removed: {path_str}", severity="information")

    def _add_path(self) -> None:
        """Add a new context path."""
        input_widget = self.query_one("#new_path_input", Input)
        select_widget = self.query_one("#new_perm_select", Select)
        new_path = input_widget.value.strip()
        permission = str(select_widget.value) if select_widget.value != Select.BLANK else "read"

        if not new_path:
            self.app_ref.notify("Please enter a path", severity="warning")
            return

        path = Path(new_path).expanduser().resolve()
        if not path.exists():
            self.app_ref.notify(f"Path does not exist: {new_path}", severity="warning")
            return

        # Check for duplicates
        existing = self._get_current_paths()
        for p in existing:
            if Path(p["path"]).resolve() == path:
                self.app_ref.notify("Path already in context", severity="warning")
                return

        self._propagate_add(str(path), permission)
        input_widget.value = ""
        self._refresh_paths_display()
        self.app_ref.notify(f"Added: {path} ({permission})", severity="information")

    def _get_orchestrator_agents(self):
        """Get the orchestrator agents dict."""
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator or not hasattr(orchestrator, "agents"):
            return {}
        return orchestrator.agents

    def _propagate_permission_update(self, path_str: str, new_permission: str) -> None:
        """Update permission on all agents' PathPermissionManager."""
        for _agent_id, agent in self._get_orchestrator_agents().items():
            ppm = self._get_ppm(agent)
            if ppm:
                ppm.update_context_path_permission(path_str, new_permission)
            # Update backend config for subagent spawning consistency
            self._update_agent_config_context_paths(agent, path_str, new_permission=new_permission)

    def _propagate_remove(self, path_str: str) -> None:
        """Remove a context path from all agents' PathPermissionManager."""
        for _agent_id, agent in self._get_orchestrator_agents().items():
            ppm = self._get_ppm(agent)
            if ppm:
                ppm.remove_context_path(path_str)
            # Update backend config for subagent spawning consistency
            self._update_agent_config_context_paths(agent, path_str, remove=True)

    def _propagate_add(self, path_str: str, permission: str) -> None:
        """Add a context path to all agents' PathPermissionManager."""
        path_config = {"path": path_str, "permission": permission}
        for _agent_id, agent in self._get_orchestrator_agents().items():
            ppm = self._get_ppm(agent)
            if ppm:
                ppm.add_context_paths([path_config])
            # Update backend config for subagent spawning consistency
            self._update_agent_config_context_paths(agent, path_str, permission=permission, add=True)

    def _get_ppm(self, agent):
        """Get PathPermissionManager from an agent."""
        fm = getattr(getattr(agent, "backend", None), "filesystem_manager", None)
        if fm:
            return getattr(fm, "path_permission_manager", None)
        return None

    def _update_agent_config_context_paths(
        self,
        agent,
        path_str: str,
        *,
        new_permission: str = "",
        remove: bool = False,
        add: bool = False,
        permission: str = "read",
    ) -> None:
        """Update agent.backend.config['context_paths'] to stay in sync."""
        backend = getattr(agent, "backend", None)
        if not backend or not hasattr(backend, "config"):
            return
        config_paths = backend.config.get("context_paths", [])

        resolved = str(Path(path_str).resolve())

        if remove:
            backend.config["context_paths"] = [p for p in config_paths if str(Path(p["path"]).resolve()) != resolved]
        elif add:
            backend.config["context_paths"] = config_paths + [{"path": path_str, "permission": permission}]
        elif new_permission:
            for p in config_paths:
                if str(Path(p["path"]).resolve()) == resolved:
                    p["permission"] = new_permission
                    break


class SubagentContextModal(BaseModal):
    """Read-only context paths modal for subagent views."""

    DEFAULT_CSS = """
    SubagentContextModal #context_container {
        width: 80;
        max-height: 35;
    }

    SubagentContextModal .context-path-row {
        height: 3;
        width: 100%;
    }

    SubagentContextModal .context-path-text {
        width: 1fr;
        height: 3;
        content-align: left middle;
        padding: 0 1;
    }

    SubagentContextModal .perm-badge {
        min-width: 10;
        max-width: 10;
        margin: 0 1;
    }

    SubagentContextModal #context_paths_list {
        max-height: 15;
        border: solid $primary-background;
        margin: 1 0;
        padding: 1;
    }

    SubagentContextModal #close_context_button {
        margin-top: 1;
    }
    """

    def __init__(self, context_paths_labeled: list[dict[str, str]]):
        super().__init__()
        self._paths = context_paths_labeled

    def compose(self) -> ComposeResult:
        with Container(id="context_container"):
            yield Label("Subagent Context Paths", id="context_header")
            yield Label(
                "All paths are read-only for subagents",
                id="context_hint",
            )
            with ScrollableContainer(id="context_paths_list"):
                yield from self._build_path_rows()
            yield Button("Close (ESC)", id="close_context_button", variant="default")

    def _build_path_rows(self) -> list[Widget]:
        rows: list[Widget] = []
        for i, entry in enumerate(self._paths):
            path_str = entry.get("path", "")
            label = entry.get("label", Path(path_str).name)
            row = Horizontal(
                Static(
                    f"{path_str}\n  [dim]{label}[/]",
                    markup=True,
                    classes="context-path-text",
                ),
                Button(
                    "Read",
                    variant="primary",
                    classes="perm-badge",
                    disabled=True,
                ),
                classes="context-path-row",
                id=f"path_row_{i}",
            )
            rows.append(row)
        if not rows:
            rows.append(
                Static(
                    "[dim]No context paths configured.[/]",
                    markup=True,
                ),
            )
        return rows
