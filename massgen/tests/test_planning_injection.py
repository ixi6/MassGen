"""Unit tests for planning task injection from propose_improvements.

Tests cover:
- _check_and_inject_pending_tasks reads inject_tasks.json and adds tasks
- Injection file is consumed (deleted) after processing
- No injection when injection_dir is None
- Both improve and preserve item types convert correctly
- Repeated propose_improvements overwrites (not appends) injection file
"""

import json
from pathlib import Path

from massgen.mcp_tools.planning.planning_dataclasses import TaskPlan


class TestCheckAndInjectPendingTasks:
    """Tests for _check_and_inject_pending_tasks in planning MCP server."""

    def _inject_tasks(self, plan: TaskPlan, injection_dir: Path, tasks: list[dict]) -> list[str]:
        """Call the injection function with the given injection dir and tasks."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        # Write inject file
        inject_file = injection_dir / "inject_tasks.json"
        inject_file.write_text(json.dumps(tasks))

        return _check_and_inject_pending_tasks(plan, injection_dir)

    def test_inject_tasks_creates_plan_entries(self, tmp_path):
        """Injected tasks appear in the plan with correct descriptions and metadata."""
        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        tasks = [
            {
                "description": "[E1] Add more vivid imagery",
                "verification": "Uses vivid imagery throughout",
                "priority": "high",
                "metadata": {
                    "criterion_id": "E1",
                    "criterion": "Uses vivid imagery throughout",
                    "type": "improve",
                    "sources": ["agent1.1"],
                    "injected": True,
                },
            },
            {
                "description": "[E3] Preserve: Maintains consistent tone",
                "verification": "Tone is consistent",
                "priority": "medium",
                "metadata": {
                    "criterion_id": "E3",
                    "criterion": "Tone is consistent",
                    "type": "preserve",
                    "source": "agent2.1",
                    "injected": True,
                },
            },
        ]

        added_ids = self._inject_tasks(plan, tmp_path, tasks)

        assert len(added_ids) == 2
        assert len(plan.tasks) == 2

        # Verify first task
        t1 = plan.tasks[0]
        assert t1.description == "[E1] Add more vivid imagery"
        assert t1.priority == "high"
        assert t1.metadata["criterion_id"] == "E1"
        assert t1.metadata["type"] == "improve"
        assert t1.metadata["injected"] is True
        assert t1.metadata["verification"] == "Uses vivid imagery throughout"

        # Verify second task
        t2 = plan.tasks[1]
        assert t2.description == "[E3] Preserve: Maintains consistent tone"
        assert t2.priority == "medium"
        assert t2.metadata["type"] == "preserve"

    def test_inject_file_consumed_after_read(self, tmp_path):
        """After injection, the inject_tasks.json file is deleted. Second call is no-op."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        tasks = [{"description": "Test task", "priority": "medium", "metadata": {"injected": True}}]
        inject_file = tmp_path / "inject_tasks.json"
        inject_file.write_text(json.dumps(tasks))

        # First call: should add task and delete file
        added = _check_and_inject_pending_tasks(plan, tmp_path)
        assert len(added) == 1
        assert not inject_file.exists()

        # Second call: no file, no-op
        added2 = _check_and_inject_pending_tasks(plan, tmp_path)
        assert len(added2) == 0
        assert len(plan.tasks) == 1  # still only 1 task from first inject

    def test_no_injection_dir_no_effect(self):
        """When injection_dir is None, no error and no tasks added."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        # None injection dir should be safe no-op
        added = _check_and_inject_pending_tasks(plan, None)
        assert added == []
        assert len(plan.tasks) == 0

    def test_injection_improve_and_preserve_items(self, tmp_path):
        """Both improve and preserve item types are correctly injected with metadata."""
        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        tasks = [
            {
                "description": "[E2] Improve: Add rhyming scheme",
                "verification": "Uses ABAB rhyme scheme",
                "priority": "high",
                "metadata": {
                    "criterion_id": "E2",
                    "type": "improve",
                    "sources": ["agent1.1", "agent2.1"],
                    "injected": True,
                },
            },
            {
                "description": "[E4] Preserve: Keep metaphor quality",
                "verification": "Metaphors are rich and layered",
                "priority": "medium",
                "metadata": {
                    "criterion_id": "E4",
                    "type": "preserve",
                    "source": "agent1.1",
                    "injected": True,
                },
            },
        ]

        added_ids = self._inject_tasks(plan, tmp_path, tasks)
        assert len(added_ids) == 2

        improve_task = plan.tasks[0]
        assert improve_task.metadata["type"] == "improve"
        assert improve_task.metadata["sources"] == ["agent1.1", "agent2.1"]

        preserve_task = plan.tasks[1]
        assert preserve_task.metadata["type"] == "preserve"
        assert preserve_task.metadata["source"] == "agent1.1"

    def test_inject_overwrites_on_repeated_propose(self, tmp_path):
        """Second write replaces first; only one set of tasks after consumption."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        inject_file = tmp_path / "inject_tasks.json"

        # First write
        first_tasks = [{"description": "Task A", "priority": "high", "metadata": {"injected": True}}]
        inject_file.write_text(json.dumps(first_tasks))

        # Second write (overwrites)
        second_tasks = [
            {"description": "Task X", "priority": "high", "metadata": {"injected": True}},
            {"description": "Task Y", "priority": "medium", "metadata": {"injected": True}},
        ]
        inject_file.write_text(json.dumps(second_tasks))

        plan = TaskPlan(agent_id="test_agent", require_verification=False)
        added = _check_and_inject_pending_tasks(plan, tmp_path)

        # Should have the second set, not the first
        assert len(added) == 2
        assert plan.tasks[0].description == "Task X"
        assert plan.tasks[1].description == "Task Y"

    def test_inject_with_task_id(self, tmp_path):
        """Injected tasks can specify custom IDs."""
        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        tasks = [
            {
                "id": "improve_E1",
                "description": "[E1] Fix imagery",
                "priority": "high",
                "metadata": {"injected": True},
            },
        ]

        added_ids = self._inject_tasks(plan, tmp_path, tasks)
        assert added_ids == ["improve_E1"]
        assert plan.tasks[0].id == "improve_E1"

    def test_injection_forwards_subagent_name(self, tmp_path):
        """Top-level subagent fields are forwarded to task metadata during injection."""
        plan = TaskPlan(agent_id="test_agent", require_verification=False)

        tasks = [
            {
                "id": "improve_E1",
                "description": "[E1] Build hero section",
                "priority": "high",
                "verification": "Hero renders correctly",
                "subagent_name": "builder",
                "subagent_id": "sub_123",
                "criterion_id": "E1",
                "impact": "structural",
                "sources": ["agent1.1"],
                "type": "improve",
                "metadata": {
                    "injected": True,
                },
            },
        ]

        added_ids = self._inject_tasks(plan, tmp_path, tasks)
        assert added_ids == ["improve_E1"]

        task = plan.tasks[0]
        assert task.metadata["subagent_name"] == "builder"
        assert task.metadata["subagent_id"] == "sub_123"
        assert task.metadata["criterion_id"] == "E1"
        assert task.metadata["impact"] == "structural"
        assert task.metadata["sources"] == ["agent1.1"]
        assert task.metadata["type"] == "improve"

    def test_inject_malformed_json_is_safe(self, tmp_path):
        """Malformed inject_tasks.json doesn't crash, returns empty list."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        inject_file = tmp_path / "inject_tasks.json"
        inject_file.write_text("not valid json{{{")

        plan = TaskPlan(agent_id="test_agent", require_verification=False)
        added = _check_and_inject_pending_tasks(plan, tmp_path)
        assert added == []
