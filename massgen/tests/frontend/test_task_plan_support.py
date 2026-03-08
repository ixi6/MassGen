"""Tests for planning tool task plan display helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from massgen.frontend.displays.task_plan_support import update_task_plan_from_tool
from massgen.frontend.displays.textual_widgets.task_plan_host import TaskPlanHost


class _HostStub:
    def __init__(self, *, accept_task_plan: bool = True) -> None:
        self.accept_task_plan = accept_task_plan
        self.cleared = 0
        self.pinned_updates: list[dict[str, Any]] = []
        self.plan_updates: list[dict[str, Any]] = []
        self._active_tasks: list[dict[str, Any]] | None = None

    def should_accept_task_plan(self) -> bool:
        return self.accept_task_plan

    def clear(self) -> None:
        self.cleared += 1
        self._active_tasks = None

    def get_active_tasks(self) -> list[dict[str, Any]] | None:
        return self._active_tasks

    def update_pinned_task_plan(
        self,
        *,
        tasks: list[dict[str, Any]],
        focused_task_id: str | None = None,
        operation: str = "update",
        show_notification: bool = True,
    ) -> None:
        self.pinned_updates.append(
            {
                "tasks": tasks,
                "focused_task_id": focused_task_id,
                "operation": operation,
                "show_notification": show_notification,
            },
        )

    def update_task_plan(
        self,
        tasks: list[dict[str, Any]],
        plan_id: str | None = None,
        operation: str = "create",
    ) -> None:
        self.plan_updates.append(
            {
                "tasks": tasks,
                "plan_id": plan_id,
                "operation": operation,
            },
        )
        self._active_tasks = [task.copy() for task in tasks]


def _tool_data(*, tool_name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        tool_name=tool_name,
        tool_id="tool_123",
        result_full=json.dumps(payload),
    )


def test_update_task_plan_from_tool_clears_when_plan_is_cleared() -> None:
    host = _HostStub()

    handled = update_task_plan_from_tool(
        host=host,
        tool_data=_tool_data(
            tool_name="mcp__planning_agent_a__clear_task_plan",
            payload={"success": True, "operation": "clear_task_plan"},
        ),
        timeline=None,
    )

    assert handled is True
    assert host.cleared == 1
    assert not host.pinned_updates
    assert not host.plan_updates


def test_update_task_plan_from_tool_suppresses_when_host_rejects_plan() -> None:
    host = _HostStub(accept_task_plan=False)

    handled = update_task_plan_from_tool(
        host=host,
        tool_data=_tool_data(
            tool_name="mcp__planning_agent_a__create_task_plan",
            payload={
                "success": True,
                "tasks": [
                    {"id": "t1", "description": "Task 1", "status": "pending"},
                    {"id": "t2", "description": "Task 2", "status": "pending"},
                ],
            },
        ),
        timeline=None,
    )

    assert handled is True
    assert host.cleared == 1
    assert not host.pinned_updates
    assert not host.plan_updates


def test_update_task_plan_from_tool_updates_when_host_accepts_plan() -> None:
    host = _HostStub(accept_task_plan=True)

    handled = update_task_plan_from_tool(
        host=host,
        tool_data=_tool_data(
            tool_name="mcp__planning_agent_a__create_task_plan",
            payload={
                "success": True,
                "tasks": [
                    {"id": "t1", "description": "Task 1", "status": "completed"},
                    {"id": "t2", "description": "Task 2", "status": "pending"},
                ],
            },
        ),
        timeline=None,
    )

    assert handled is True
    assert host.cleared == 0
    assert len(host.pinned_updates) == 1
    assert len(host.plan_updates) == 1
    assert host.plan_updates[0]["operation"] == "create"


def test_task_plan_host_accepts_when_persistence_check_unavailable() -> None:
    def _raise_runtime_error() -> bool:
        raise RuntimeError("workspace not ready")

    host = TaskPlanHost(agent_id="agent_a", has_persisted_plan=_raise_runtime_error)
    assert host.should_accept_task_plan() is True


def test_task_plan_host_rejects_when_persistence_check_explicitly_false() -> None:
    host = TaskPlanHost(agent_id="agent_a", has_persisted_plan=lambda: False)
    assert host.should_accept_task_plan() is False
