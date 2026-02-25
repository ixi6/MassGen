"""
Plan Review Modal Widget for MassGen TUI.

Shown after planning completes to support iterative planning review before execution.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from massgen.frontend.displays.textual.widgets.rework_controls import (
    ReworkControlsMixin,
)


@dataclass
class PlanApprovalResult:
    """Result from the plan review modal."""

    approved: bool
    action: str  # "continue", "quick_edit", "finalize", "finalize_manual", "cancel"
    feedback: str | None = None
    plan_data: dict[str, Any] | None = None
    plan_path: Path | None = None


class PlanJsonEditorModal(ModalScreen[Optional[str]]):
    """Full-screen modal for editing plan JSON."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ""

    def __init__(
        self,
        initial_json: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._json_value = initial_json

    def compose(self) -> ComposeResult:
        with Container():
            with Container(classes="modal-header"):
                with Horizontal(classes="header-row"):
                    yield Static("Edit Plan JSON", classes="modal-title")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

            with ScrollableContainer(classes="modal-body"):
                editor = TextArea(
                    self._json_value,
                    id="plan_json_editor",
                )
                yield editor

            with Container(classes="modal-footer"):
                with Horizontal(classes="footer-buttons"):
                    yield Button(
                        "Apply JSON Edits",
                        variant="primary",
                        id="apply_btn",
                    )
                    yield Button(
                        "Cancel (Esc)",
                        variant="default",
                        id="cancel_btn",
                    )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "plan_json_editor":
            self._json_value = event.text_area.text

    def _dismiss_with_value(self) -> None:
        try:
            self._json_value = self.query_one("#plan_json_editor", TextArea).text
        except Exception:
            pass
        self.dismiss(self._json_value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply_btn":
            self._dismiss_with_value()
        elif event.button.id in ("cancel_btn", "close_btn"):
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PlanApprovalModal(ReworkControlsMixin, ModalScreen[PlanApprovalResult]):
    """Modal screen for planning review and action routing."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "finalize_plan", "Finalize Plan and Execute"),
        ("ctrl+e", "toggle_expand", "Expand/Collapse"),
    ]

    # CSS moved to theme files for consistency.
    DEFAULT_CSS = ""

    # Widget IDs for backward compat with existing CSS selectors
    REWORK_FEEDBACK_INPUT_ID = "planning_feedback_input"
    REWORK_CONTINUE_BTN_ID = "continue_btn"
    REWORK_QUICK_EDIT_BTN_ID = "quick_edit_btn"

    STATUS_ICONS = {
        "pending": "○",
        "in_progress": "●",
        "completed": "✓",
        "verified": "✓",
        "blocked": "◌",
    }

    PRIORITY_COLORS = {
        "high": "#f85149",
        "medium": "#d29922",
        "low": "#8b949e",
        # Spec priority levels (P0=urgent, P1=high, P2=normal)
        "p0": "#f85149",
        "p1": "#d29922",
        "p2": "#8b949e",
    }

    def __init__(
        self,
        tasks: list[dict[str, Any]],
        plan_path: Path,
        plan_data: dict[str, Any],
        revision: int | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        super().__init__(name=name, id=id, classes=classes)
        # Detect spec artifacts (requirements key, no tasks key)
        self._is_spec = "requirements" in plan_data and "tasks" not in plan_data
        items_key = "requirements" if self._is_spec else "tasks"
        plan_items = plan_data.get(items_key, [])
        if isinstance(plan_items, list):
            self.tasks = [task for task in plan_items if isinstance(task, dict)]
            self.plan_data = dict(plan_data)
            self.plan_data[items_key] = self.tasks
        else:
            self.tasks = [task for task in tasks if isinstance(task, dict)]
            self.plan_data = dict(plan_data)
            self.plan_data[items_key] = self.tasks
        self.plan_path = plan_path
        self.revision = revision
        self._expanded = True
        self._rework_feedback_value = ""
        self._json_edit_status = ""
        self._rework_action_status = ""
        self._plan_json_value = json.dumps(self.plan_data, indent=2)
        self._chunk_order, self._tasks_by_chunk = self._group_tasks_by_chunk(self.tasks)
        self._rebuild_chunk_groups()

    @staticmethod
    def _group_tasks_by_chunk(
        tasks: list[dict[str, Any]],
    ) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
        chunk_order: list[str] = []
        tasks_by_chunk: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            chunk = str(task.get("chunk", "")).strip() or "unassigned"
            if chunk not in tasks_by_chunk:
                tasks_by_chunk[chunk] = []
                chunk_order.append(chunk)
            tasks_by_chunk[chunk].append(task)
        return chunk_order, tasks_by_chunk

    def _rebuild_chunk_groups(self) -> None:
        """Recompute chunk grouping after in-modal edits."""
        self._chunk_order, self._tasks_by_chunk = self._group_tasks_by_chunk(self.tasks)

    def _persist_plan_data(self) -> None:
        """Persist in-modal plan edits back to project_plan.json."""
        try:
            self.plan_path.parent.mkdir(parents=True, exist_ok=True)
            self.plan_path.write_text(json.dumps(self.plan_data, indent=2), encoding="utf-8")
        except Exception:
            # Best effort. Finalize path also attempts persistence.
            pass

    def compose(self) -> ComposeResult:
        # Adapt labels for spec vs plan artifacts
        artifact_label = "Spec" if self._is_spec else "Plan"
        items_label = "Requirements" if self._is_spec else "Tasks"

        container_classes = "expanded" if self._expanded else None
        with Container(classes=container_classes):
            with Container(classes="modal-header"):
                with Container(classes="header-row"):
                    title = f"{artifact_label} Review"
                    if self.revision:
                        title = f"{artifact_label} Review (rev {self.revision})"
                    yield Static(title, classes="modal-title")
                    expand_label = "Collapse View" if self._expanded else "Expand View"
                    yield Button(expand_label, variant="default", classes="modal-expand", id="expand_btn")
                    yield Button("✕", variant="default", classes="modal-close", id="close_btn")

            with Horizontal(classes="modal-stats"):
                yield Static(f"{items_label}: {len(self.tasks)}", classes="stat-item")
                yield Static(f"Chunks: {len(self._chunk_order)}", classes="stat-item")
                yield Static(f"View: {'Expanded' if self._expanded else 'Compact'}", classes="stat-item")
                high_priority = sum(1 for t in self.tasks if str(t.get("priority", "")).lower() in {"high", "p0"})
                if high_priority > 0:
                    yield Static(f"High Priority: {high_priority}", classes="stat-item")

            body_classes = "modal-body expanded-body" if self._expanded else "modal-body"
            with ScrollableContainer(classes=body_classes):
                for chunk in self._chunk_order:
                    chunk_tasks = self._tasks_by_chunk.get(chunk, [])
                    completed = sum(1 for task in chunk_tasks if str(task.get("status", "pending")).lower() in {"completed", "verified"})
                    yield Static(
                        f"[bold]{chunk}[/bold] [dim]({completed}/{len(chunk_tasks)} complete)[/dim]",
                        classes="plan-chunk-header",
                    )
                    for task in chunk_tasks:
                        yield Static(self._format_task_row(task), classes="task-row")

            with Container(classes="plan-json-actions"):
                yield Button(
                    f"Edit {artifact_label} JSON",
                    variant="default",
                    id="edit_plan_json_btn",
                    classes="edit-plan-json-button",
                )
                if self._json_edit_status:
                    yield Static(self._json_edit_status, classes="plan-json-edit-status")

            rework_label = "spec refinement" if self._is_spec else "planning"
            yield from self.compose_rework_controls(
                feedback_label=f"Prompt for next {rework_label} turn (required for Continue/Quick Edit):",
                feedback_placeholder="Example: tighten scope, reorder chunks, add requirements" if self._is_spec else "Example: tighten scope, reorder chunks, add migration tasks",
                continue_label=f"Continue {artifact_label}",
                quick_edit_label="Quick Edit (Single Agent)",
            )

            with Container(classes="modal-footer"):
                with Horizontal(classes="footer-buttons"):
                    yield Button(
                        f"Finalize {artifact_label} and Execute (Enter)",
                        variant="primary",
                        id="finalize_btn",
                        classes="execute-button",
                    )
                    yield Button(
                        f"Finalize {artifact_label} (Manual Execute)",
                        variant="default",
                        id="finalize_manual_btn",
                    )
                    yield Button("Cancel (Esc)", variant="error", id="cancel_btn")
                if self._rework_action_status:
                    yield Static(self._rework_action_status, classes="plan-action-status")

    def _format_task_row(self, task: dict[str, Any]) -> Text:
        text = Text()

        status = str(task.get("status", "pending")).lower()
        icon = self.STATUS_ICONS.get(status, "○")
        text.append(f"{icon} ", style="dim")

        task_id = task.get("id", "?")
        text.append(f"[{task_id}] ", style="cyan")

        priority = str(task.get("priority", "")).lower()
        if priority in self.PRIORITY_COLORS:
            text.append("● ", style=self.PRIORITY_COLORS[priority])

        name = task.get("name") or task.get("title") or task.get("description", "Untitled")
        if not self._expanded and len(name) > 72:
            name = name[:69] + "..."
        text.append(name)

        # For spec requirements, show EARS statement as dimmed suffix
        ears = task.get("ears", "")
        if ears and self._is_spec:
            ears_display = ears if len(ears) <= 60 else ears[:57] + "..."
            text.append(f" — {ears_display}", style="dim")

        deps = task.get("depends_on") or task.get("dependencies") or []
        if isinstance(deps, list) and deps:
            text.append(f" (→{len(deps)})", style="dim")

        return text

    def _feedback_text(self) -> str | None:
        return self._rework_feedback_text()

    def _has_feedback(self) -> bool:
        return self._has_rework_feedback()

    def _sync_feedback_action_controls(self) -> None:
        self._sync_rework_button_states()

    def _snapshot_input_values(self) -> None:
        """Capture current input values before recompose/dismiss."""
        self._snapshot_rework_input()

    def _open_plan_json_editor(self) -> None:
        """Open full-screen JSON editor and apply edits if confirmed."""
        self._snapshot_input_values()
        editor = PlanJsonEditorModal(self._plan_json_value)

        def _on_dismiss(updated_json: str | None) -> None:
            if updated_json is None:
                return
            self._plan_json_value = updated_json
            self._apply_plan_json_edit()

        self.push_screen(editor, _on_dismiss)

    def _apply_plan_json_edit(self) -> bool:
        """Apply plan JSON edits from inline editor."""
        self._snapshot_input_values()
        payload = (self._plan_json_value or "").strip()
        if not payload:
            self._json_edit_status = "Plan JSON cannot be empty."
            self.refresh(recompose=True)
            return False

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as e:
            self._json_edit_status = f"Invalid JSON: {e}"
            self.refresh(recompose=True)
            return False

        items_key = "requirements" if self._is_spec else "tasks"
        items_label = "requirements" if self._is_spec else "tasks"

        if not isinstance(parsed, dict):
            self._json_edit_status = f"JSON must be an object with a '{items_key}' array."
            self.refresh(recompose=True)
            return False

        raw_items = parsed.get(items_key)
        if not isinstance(raw_items, list) or not raw_items:
            self._json_edit_status = f"JSON must include a non-empty '{items_key}' array."
            self.refresh(recompose=True)
            return False

        parsed_items = [item for item in raw_items if isinstance(item, dict)]
        if not parsed_items:
            self._json_edit_status = f"JSON contains no valid {items_label} objects."
            self.refresh(recompose=True)
            return False

        parsed[items_key] = parsed_items
        self.plan_data = parsed
        self.tasks = parsed_items
        self._plan_json_value = json.dumps(self.plan_data, indent=2)
        self._rebuild_chunk_groups()
        self._json_edit_status = f"Applied JSON edits ({len(self.tasks)} {items_label} loaded)."
        self._persist_plan_data()
        self.refresh(recompose=True)
        return True

    def _validate_action(self, action: str) -> bool:
        """Validate modal action requirements before dismissing."""
        self._rework_action_status = ""
        if action in {"continue", "quick_edit"} and not self._feedback_text():
            self._rework_action_status = "Enter a planning prompt before Continue or Quick Edit."
            self.refresh(recompose=True)
            return False
        return True

    def _dismiss_with_action(self, action: str) -> None:
        self._snapshot_input_values()

        if action != "cancel":
            if not self._apply_plan_json_edit():
                return
            if not self._validate_action(action):
                return

        if action != "cancel":
            self._persist_plan_data()
        self.dismiss(
            PlanApprovalResult(
                approved=action in {"finalize", "finalize_manual"},
                action=action,
                feedback=self._feedback_text(),
                plan_data=self.plan_data,
                plan_path=self.plan_path,
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "continue_btn":
            self._dismiss_with_action("continue")
        elif button_id == "quick_edit_btn":
            self._dismiss_with_action("quick_edit")
        elif button_id == "finalize_btn":
            self._dismiss_with_action("finalize")
        elif button_id == "finalize_manual_btn":
            self._dismiss_with_action("finalize_manual")
        elif button_id == "expand_btn":
            self.action_toggle_expand()
        elif button_id == "edit_plan_json_btn":
            self._open_plan_json_editor()
        elif button_id in ("cancel_btn", "close_btn"):
            self._dismiss_with_action("cancel")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Keep local state in sync so recompose preserves edits."""
        if event.input.id == self.REWORK_FEEDBACK_INPUT_ID:
            self._rework_feedback_value = event.value
            self._sync_feedback_action_controls()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Keep JSON editor state synced across recomposes."""
        if event.text_area.id == "plan_json_editor":
            self._plan_json_value = event.text_area.text

    def action_cancel(self) -> None:
        self._dismiss_with_action("cancel")

    def action_toggle_expand(self) -> None:
        self._snapshot_input_values()
        self._expanded = not self._expanded
        self.refresh(recompose=True)

    def action_continue_planning(self) -> None:
        self._dismiss_with_action("continue")

    def action_finalize_plan(self) -> None:
        self._dismiss_with_action("finalize")

    def on_mount(self) -> None:
        self._sync_feedback_action_controls()
        try:
            self.query_one("#finalize_btn", Button).focus()
        except Exception:
            pass
