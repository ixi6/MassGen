"""
Task Plan Host for MassGen TUI.

Provides a single, reusable container for the pinned TaskPlanCard so both
the main TUI and subagent TUI share identical behavior and layout.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.containers import Container

from .task_plan_card import TaskPlanCard


class TaskPlanHost(Container):
    """Container that hosts a pinned TaskPlanCard and manages its state."""

    def __init__(
        self,
        *,
        agent_id: str,
        ribbon: Any | None = None,
        has_persisted_plan: Callable[[], bool] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._agent_id = agent_id
        self._ribbon = ribbon
        self._has_persisted_plan = has_persisted_plan
        self._active_task_plan_id: str | None = None
        self._active_task_plan_tasks: list[dict[str, Any]] | None = None
        self._task_plan_visible: bool = False

    def set_ribbon(self, ribbon: Any | None) -> None:
        """Set the status ribbon reference for task counts."""
        self._ribbon = ribbon

    def get_active_tasks(self) -> list[dict[str, Any]] | None:
        """Return current task list, if any."""
        return self._active_task_plan_tasks

    def get_active_plan_id(self) -> str | None:
        """Return current plan id, if any."""
        return self._active_task_plan_id

    def should_accept_task_plan(self) -> bool:
        """Return whether task plan UI should be visible for this host."""
        if self._has_persisted_plan is None:
            return True
        try:
            return bool(self._has_persisted_plan())
        except Exception:
            # If host-level persistence check is unavailable, prefer showing
            # task updates rather than suppressing all task UI.
            return True

    def update_task_plan(self, tasks: list[dict[str, Any]], plan_id: str | None = None, operation: str = "create") -> None:
        """Update cached task plan state and ribbon counts."""
        if not self.should_accept_task_plan():
            self.clear()
            return

        self._active_task_plan_id = plan_id
        self._active_task_plan_tasks = [t.copy() for t in tasks] if tasks else None

        if tasks and self._ribbon:
            completed = sum(1 for t in tasks if t.get("status") in ("completed", "verified"))
            self._ribbon.set_tasks(self._agent_id, completed, len(tasks))

    def update_pinned_task_plan(
        self,
        tasks: list[dict[str, Any]],
        focused_task_id: str | None = None,
        operation: str = "update",
        show_notification: bool = True,
    ) -> None:
        """Update or create the pinned TaskPlanCard."""
        if not self.should_accept_task_plan():
            self.clear()
            return

        existing_card = None
        try:
            existing_card = self.query_one(TaskPlanCard)
        except Exception:
            pass

        if existing_card:
            existing_card.update_tasks(tasks, focused_task_id=focused_task_id, operation=operation)
        else:
            card = TaskPlanCard(
                tasks=tasks,
                focused_task_id=focused_task_id,
                operation=operation,
                id=f"pinned_card_{self._agent_id}",
            )
            self.mount(card)

        self.remove_class("hidden")
        self._task_plan_visible = True

    def on_click(self) -> None:
        """Click to toggle collapse/expand."""
        self.toggle()

    def toggle(self) -> None:
        """Toggle visibility (collapsed/expanded) of the pinned task plan."""
        if not self._active_task_plan_tasks:
            return

        self._task_plan_visible = not self._task_plan_visible
        if self._task_plan_visible:
            self.remove_class("collapsed")
        else:
            self.add_class("collapsed")

    def collapse(self) -> None:
        """Collapse the task plan (hide content, keep header)."""
        if self._active_task_plan_tasks:
            self._task_plan_visible = False
            self.add_class("collapsed")

    def clear(self) -> None:
        """Clear task plan state and hide the host."""
        self._active_task_plan_id = None
        self._active_task_plan_tasks = None
        if self._ribbon:
            try:
                self._ribbon.set_tasks(self._agent_id, 0, 0)
            except Exception:
                pass
        try:
            self.remove_children()
        except Exception:
            pass
        self.add_class("hidden")
        self.remove_class("collapsed")
        self._task_plan_visible = True

    def get_task_plan_card(self) -> TaskPlanCard | None:
        """Return the current TaskPlanCard if mounted."""
        try:
            return self.query_one(TaskPlanCard)
        except Exception:
            return None
