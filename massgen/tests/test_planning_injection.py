"""Unit tests for planning task injection from propose_improvements.

Tests cover:
- _check_and_inject_pending_tasks reads inject_tasks.json and adds tasks
- Injection file is consumed (deleted) after processing
- No injection when injection_dir is None
- Both improve and preserve item types convert correctly
- Repeated propose_improvements overwrites (not appends) injection file
"""

import json
import sys
from pathlib import Path

import pytest

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

    def test_append_terminal_verification_memory_task(self):
        """Terminal verification memo task should be appended with full-plan deps."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _append_terminal_verification_memory_task,
        )

        tasks = [
            {
                "id": "implement",
                "description": "Implement feature",
                "verification": "Feature works end-to-end",
            },
            {
                "id": "test",
                "description": "Run tests",
                "depends_on": ["implement"],
                "verification": "All tests pass",
            },
        ]

        out = _append_terminal_verification_memory_task(tasks)
        assert out[-1]["id"] == "write_verification_memo"
        assert set(out[-1]["depends_on"]) == {"implement", "test"}
        assert "memory/short_term/verification_latest.md" in out[-1]["description"]
        assert "workspace path" in out[-1]["description"]
        assert "artifact under test" in out[-1]["description"]
        assert "generated this run" in out[-1]["description"]
        assert "concrete assertion extracted" not in out[-1]["description"].lower()

    @pytest.mark.asyncio
    async def test_create_task_plan_memory_mode_appends_terminal_verification_task(self, monkeypatch, tmp_path):
        """create_task_plan should auto-append terminal verification memo task in memory mode."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        server._task_plans.clear()
        server._workspace_path = None
        server._injection_dir = None

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "planning-server",
                "--agent-id",
                "agent_a",
                "--orchestrator-id",
                "orch_verification_memory",
                "--workspace-path",
                str(tmp_path),
                "--memory-enabled",
            ],
        )
        mcp = await server.create_server()

        create_task_plan = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task_plan":
                create_task_plan = tool.fn
                break
        assert create_task_plan is not None

        result = create_task_plan(
            tasks=[
                {
                    "id": "build",
                    "description": "Build feature",
                    "verification": "Feature is implemented",
                    "verification_method": "Inspect output files",
                },
            ],
        )

        assert result["success"] is True
        task_ids = [task["id"] for task in result["tasks"]]
        assert task_ids[-1] == "write_verification_memo"
        assert set(result["tasks"][-1]["dependencies"]) == set(task_ids[:-1])

    @pytest.mark.asyncio
    async def test_create_task_plan_verification_memory_mode_only_adds_terminal_verification_task(self, monkeypatch, tmp_path):
        """verification-memory mode should append only write_verification_memo (no prep/save memory tasks)."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        server._task_plans.clear()
        server._workspace_path = None
        server._injection_dir = None

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "planning-server",
                "--agent-id",
                "agent_a",
                "--orchestrator-id",
                "orch_verification_only",
                "--workspace-path",
                str(tmp_path),
                "--verification-memory-enabled",
            ],
        )
        mcp = await server.create_server()

        create_task_plan = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task_plan":
                create_task_plan = tool.fn
                break
        assert create_task_plan is not None

        result = create_task_plan(
            tasks=[
                {
                    "id": "build",
                    "description": "Build feature",
                    "verification": "Feature is implemented",
                    "verification_method": "Inspect output files",
                },
            ],
        )

        assert result["success"] is True
        task_ids = [task["id"] for task in result["tasks"]]
        assert "prep_memory" not in task_ids
        assert "save_memories" not in task_ids
        assert task_ids[-1] == "write_verification_memo"
        assert set(result["tasks"][-1]["dependencies"]) == {"build"}


class TestVerificationMemoSinksToEnd:
    """write_verification_memo must stay the last task after propose_improvements injects new tasks."""

    def _make_plan_with_memo(self) -> "TaskPlan":
        """Create a plan with 3 framework tasks + write_verification_memo appended at end."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _append_terminal_verification_memory_task,
        )

        plan = TaskPlan(agent_id="test_agent", require_verification=False)
        for tid in ("build", "evaluate", "final_decision"):
            plan.add_task(description=f"Task {tid}", task_id=tid, skip_verification=True)

        memo_specs = _append_terminal_verification_memory_task([{"id": t.id} for t in plan.tasks])
        memo = memo_specs[-1]
        plan.add_task(
            description=memo["description"],
            task_id=memo["id"],
            depends_on=memo.get("depends_on", []),
            skip_verification=True,
        )
        return plan

    def test_verification_memo_is_last_after_injection(self, tmp_path):
        """After propose_improvements injects improvement tasks, write_verification_memo is still last."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        plan = self._make_plan_with_memo()
        assert plan.tasks[-1].id == "write_verification_memo"  # sanity

        improvement_tasks = [
            {
                "id": f"e{i}",
                "description": f"[E{i}] Improve something",
                "priority": "high",
                "metadata": {"type": "improve", "injected": True},
            }
            for i in range(1, 4)
        ]
        (tmp_path / "inject_tasks.json").write_text(json.dumps(improvement_tasks))
        _check_and_inject_pending_tasks(plan, tmp_path)

        task_ids = [t.id for t in plan.tasks]
        assert task_ids[-1] == "write_verification_memo", f"write_verification_memo should be last, got order: {task_ids}"

    def test_verification_memo_depends_on_injected_tasks(self, tmp_path):
        """After injection, write_verification_memo depends on the newly injected improvement tasks."""
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        plan = self._make_plan_with_memo()

        improvement_tasks = [
            {
                "id": f"e{i}",
                "description": f"[E{i}] Improve something",
                "priority": "high",
                "metadata": {"type": "improve", "injected": True},
            }
            for i in range(1, 4)
        ]
        (tmp_path / "inject_tasks.json").write_text(json.dumps(improvement_tasks))
        _check_and_inject_pending_tasks(plan, tmp_path)

        memo = next(t for t in plan.tasks if t.id == "write_verification_memo")
        for imp_id in ("e1", "e2", "e3"):
            assert imp_id in memo.dependencies, f"write_verification_memo should depend on {imp_id}, got deps: {memo.dependencies}"

    def test_no_memo_in_plan_injection_is_no_op_for_memo(self, tmp_path):
        """If verification_memory is disabled, injection into a non-empty plan never creates memo."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        orig = server._verification_memory_enabled
        server._verification_memory_enabled = False
        try:
            plan = TaskPlan(agent_id="test_agent", require_verification=False)
            plan.add_task(description="Build feature", task_id="build", skip_verification=True)

            (tmp_path / "inject_tasks.json").write_text(
                json.dumps(
                    [
                        {"id": "e1", "description": "[E1] Improve", "priority": "high", "metadata": {"injected": True}},
                    ],
                ),
            )
            _check_and_inject_pending_tasks(plan, tmp_path)

            task_ids = [t.id for t in plan.tasks]
            assert "write_verification_memo" not in task_ids
            assert task_ids == ["build", "e1"]
        finally:
            server._verification_memory_enabled = orig

    def test_injection_into_empty_plan_appends_memo_when_enabled(self, tmp_path):
        """When plan is empty before injection and verification_memory is enabled, memo is appended last."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        orig = server._verification_memory_enabled
        server._verification_memory_enabled = True
        try:
            plan = TaskPlan(agent_id="test_agent", require_verification=False)
            improvement_tasks = [
                {
                    "id": "e1",
                    "description": "[E1] Improve X",
                    "priority": "high",
                    "metadata": {"injected": True},
                },
                {
                    "id": "e2",
                    "description": "[E2] Improve Y",
                    "priority": "high",
                    "metadata": {"injected": True},
                },
            ]
            (tmp_path / "inject_tasks.json").write_text(json.dumps(improvement_tasks))
            _check_and_inject_pending_tasks(plan, tmp_path)

            task_ids = [t.id for t in plan.tasks]
            assert task_ids[-1] == "write_verification_memo", f"Got: {task_ids}"
            memo = plan.tasks[-1]
            assert "e1" in memo.dependencies
            assert "e2" in memo.dependencies
        finally:
            server._verification_memory_enabled = orig

    def test_injection_into_nonempty_plan_does_not_append_memo(self, tmp_path):
        """When plan already has tasks before injection, memo is NOT auto-created by injection."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server
        from massgen.mcp_tools.planning._planning_mcp_server import (
            _check_and_inject_pending_tasks,
        )

        orig = server._verification_memory_enabled
        server._verification_memory_enabled = True
        try:
            plan = TaskPlan(agent_id="test_agent", require_verification=False)
            plan.add_task(description="Existing task", task_id="existing", skip_verification=True)

            (tmp_path / "inject_tasks.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "e1",
                            "description": "[E1] Improve X",
                            "priority": "high",
                            "metadata": {"injected": True},
                        },
                    ],
                ),
            )
            _check_and_inject_pending_tasks(plan, tmp_path)

            task_ids = [t.id for t in plan.tasks]
            assert "write_verification_memo" not in task_ids
            assert task_ids == ["existing", "e1"]
        finally:
            server._verification_memory_enabled = orig


class TestCreateTaskPlanSubagentMetadata:
    """create_task_plan should preserve subagent delegation metadata."""

    @pytest.mark.asyncio
    async def test_create_task_plan_preserves_top_level_subagent_fields(self, monkeypatch):
        """Top-level subagent_id/subagent_name should be kept in task metadata."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        server._task_plans.clear()
        server._workspace_path = None
        server._injection_dir = None

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "planning-server",
                "--agent-id",
                "agent_a",
                "--orchestrator-id",
                "orch_subagent_meta_top_level",
            ],
        )
        mcp = await server.create_server()

        create_task_plan = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task_plan":
                create_task_plan = tool.fn
                break
        assert create_task_plan is not None

        result = create_task_plan(
            tasks=[
                {
                    "id": "initial_eval",
                    "description": "Run initial evaluation checks",
                    "verification": "Evaluation report is generated",
                    "verification_method": "Review produced report",
                    "subagent_id": "eval_subagent_1",
                    "subagent_name": "evaluator",
                },
            ],
        )

        assert result["success"] is True
        created = result["tasks"][0]
        assert created["id"] == "initial_eval"
        assert created["metadata"]["subagent_id"] == "eval_subagent_1"
        assert created["metadata"]["subagent_name"] == "evaluator"

    @pytest.mark.asyncio
    async def test_create_task_plan_preserves_subagent_fields_from_metadata(self, monkeypatch):
        """metadata.subagent_id/subagent_name should be honored in create_task_plan."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        server._task_plans.clear()
        server._workspace_path = None
        server._injection_dir = None

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "planning-server",
                "--agent-id",
                "agent_a",
                "--orchestrator-id",
                "orch_subagent_meta_nested",
            ],
        )
        mcp = await server.create_server()

        create_task_plan = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "create_task_plan":
                create_task_plan = tool.fn
                break
        assert create_task_plan is not None

        result = create_task_plan(
            tasks=[
                {
                    "id": "initial_eval_meta",
                    "description": "Run initial evaluation checks with metadata-only delegation",
                    "metadata": {
                        "verification": "Evaluation report is generated",
                        "verification_method": "Review produced report",
                        "verification_group": "initial_eval",
                        "subagent_id": "eval_subagent_2",
                        "subagent_name": "evaluator",
                        "custom_tag": "initial-eval",
                    },
                },
            ],
        )

        assert result["success"] is True
        created = result["tasks"][0]
        assert created["id"] == "initial_eval_meta"
        assert created["metadata"]["subagent_id"] == "eval_subagent_2"
        assert created["metadata"]["subagent_name"] == "evaluator"
        assert created["metadata"]["verification_group"] == "initial_eval"
        assert created["metadata"]["custom_tag"] == "initial-eval"
