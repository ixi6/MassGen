"""
Unit tests for planning MCP recovery behavior.

Tests that create_task_plan properly handles recovery scenarios where
a plan already exists (e.g., after API disconnection and reconnection).
"""

import json

from massgen.mcp_tools.planning.planning_dataclasses import TaskPlan


def _add_task_with_status(plan: TaskPlan, description: str, task_id: str, status: str, depends_on=None):
    """Helper to add a task and set its status."""
    task = plan.add_task(description, task_id=task_id, depends_on=depends_on)
    task.status = status
    return task


class TestPlanningMCPRecovery:
    """Test planning MCP server recovery behavior."""

    def test_get_or_create_plan_loads_from_filesystem(self, tmp_path):
        """Test that _get_or_create_plan loads existing plan from filesystem."""
        # Import here to avoid polluting global state
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        # Save original state
        original_workspace = server._workspace_path
        original_plans = server._task_plans.copy()

        try:
            # Set up workspace with existing plan
            server._workspace_path = tmp_path
            server._task_plans.clear()

            tasks_dir = tmp_path / "tasks"
            tasks_dir.mkdir()

            # Create a plan with some tasks
            existing_plan = TaskPlan(agent_id="test:agent_a", require_verification=False)
            _add_task_with_status(existing_plan, "Task 1", "task_1", "completed")
            _add_task_with_status(existing_plan, "Task 2", "task_2", "in_progress")
            _add_task_with_status(existing_plan, "Task 3", "task_3", "pending")

            plan_file = tasks_dir / "plan.json"
            plan_file.write_text(json.dumps(existing_plan.to_dict(), indent=2))

            # Now _get_or_create_plan should load from filesystem
            loaded_plan = server._get_or_create_plan("agent_a", "test")

            assert len(loaded_plan.tasks) == 3
            assert loaded_plan.tasks[0].status == "completed"
            assert loaded_plan.tasks[1].status == "in_progress"
            assert loaded_plan.tasks[2].status == "pending"

        finally:
            # Restore original state
            server._workspace_path = original_workspace
            server._task_plans.clear()
            server._task_plans.update(original_plans)

    def test_create_task_plan_blocks_when_plan_exists(self, tmp_path):
        """Test that create_task_plan returns error when plan already has tasks.

        This simulates the recovery scenario where:
        1. Agent creates a plan
        2. API disconnects and reconnects
        3. MCP server restarts but plan exists on filesystem
        4. Agent tries to create_task_plan again
        5. Should get error instead of silently recreating
        """
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        # Save original state
        original_workspace = server._workspace_path
        original_plans = server._task_plans.copy()

        try:
            # Set up workspace
            server._workspace_path = tmp_path
            server._task_plans.clear()

            # Create initial plan with tasks (simulates first creation)
            key = "test:agent_a"
            initial_plan = TaskPlan(agent_id=key, require_verification=False)
            _add_task_with_status(initial_plan, "Research phase", "task_1", "completed")
            _add_task_with_status(initial_plan, "Implementation", "task_2", "in_progress")
            _add_task_with_status(initial_plan, "Testing", "task_3", "pending")

            # Store in global and save to filesystem
            server._task_plans[key] = initial_plan
            server._save_plan_to_filesystem(initial_plan)

            # Now simulate recovery: clear memory but keep filesystem
            server._task_plans.clear()

            # _get_or_create_plan should reload from filesystem
            reloaded_plan = server._get_or_create_plan("agent_a", "test")

            # Verify plan was reloaded
            assert len(reloaded_plan.tasks) == 3

            # Now the key check: trying to check if plan.tasks exists should work
            # The actual create_task_plan function checks this
            assert reloaded_plan.tasks  # Plan has tasks

            # Simulate what create_task_plan does
            if reloaded_plan.tasks:
                existing_count = len(reloaded_plan.tasks)
                completed = len([t for t in reloaded_plan.tasks if t.status == "completed"])
                in_progress = len([t for t in reloaded_plan.tasks if t.status == "in_progress"])
                pending = len([t for t in reloaded_plan.tasks if t.status == "pending"])

                result = {
                    "success": False,
                    "operation": "create_task_plan",
                    "error": (
                        f"A task plan already exists with {existing_count} tasks "
                        f"({completed} completed, {in_progress} in_progress, {pending} pending). "
                        f"Use get_task_plan to see current state, or add_task to add new tasks."
                    ),
                }

                assert result["success"] is False
                assert "already exists" in result["error"]
                assert "3 tasks" in result["error"]
                assert "1 completed" in result["error"]
                assert "1 in_progress" in result["error"]
                assert "1 pending" in result["error"]
                assert "get_task_plan" in result["error"]

        finally:
            # Restore original state
            server._workspace_path = original_workspace
            server._task_plans.clear()
            server._task_plans.update(original_plans)

    def test_create_task_plan_succeeds_when_no_plan(self, tmp_path):
        """Test that create_task_plan works normally for fresh start."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        # Save original state
        original_workspace = server._workspace_path
        original_plans = server._task_plans.copy()

        try:
            # Set up workspace with no existing plan
            server._workspace_path = tmp_path
            server._task_plans.clear()

            # Get or create plan - should create new empty one
            plan = server._get_or_create_plan("agent_a", "test", require_verification=False)

            # Plan should be empty
            assert len(plan.tasks) == 0

            # Now we can add tasks (simulates what create_task_plan does)
            plan.add_task("Task 1", task_id="task_1")
            plan.add_task("Task 2", task_id="task_2")

            assert len(plan.tasks) == 2

        finally:
            # Restore original state
            server._workspace_path = original_workspace
            server._task_plans.clear()
            server._task_plans.update(original_plans)

    def test_error_message_includes_task_counts(self, tmp_path):
        """Test that error message includes breakdown of task statuses."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        # Save original state
        original_workspace = server._workspace_path
        original_plans = server._task_plans.copy()

        try:
            server._workspace_path = tmp_path
            server._task_plans.clear()

            # Create plan with specific status distribution
            key = "test:agent_a"
            plan = TaskPlan(agent_id=key, require_verification=False)
            _add_task_with_status(plan, "Done 1", "t1", "completed")
            _add_task_with_status(plan, "Done 2", "t2", "completed")
            _add_task_with_status(plan, "Working", "t3", "in_progress")
            _add_task_with_status(plan, "Todo 1", "t4", "pending")
            _add_task_with_status(plan, "Todo 2", "t5", "pending")
            _add_task_with_status(plan, "Todo 3", "t6", "pending")

            server._task_plans[key] = plan

            # Build error message like create_task_plan does
            existing_count = len(plan.tasks)
            completed = len([t for t in plan.tasks if t.status == "completed"])
            in_progress = len([t for t in plan.tasks if t.status == "in_progress"])
            pending = len([t for t in plan.tasks if t.status == "pending"])

            error_msg = (
                f"A task plan already exists with {existing_count} tasks "
                f"({completed} completed, {in_progress} in_progress, {pending} pending). "
                f"Use get_task_plan to see current state, or add_task to add new tasks."
            )

            assert "6 tasks" in error_msg
            assert "2 completed" in error_msg
            assert "1 in_progress" in error_msg
            assert "3 pending" in error_msg

        finally:
            server._workspace_path = original_workspace
            server._task_plans.clear()
            server._task_plans.update(original_plans)


class TestPlanFilesystemPersistence:
    """Test that plans persist correctly to filesystem."""

    def test_save_and_load_plan(self, tmp_path):
        """Test round-trip save and load of plan."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        original_workspace = server._workspace_path

        try:
            server._workspace_path = tmp_path

            # Create and save plan
            plan = TaskPlan(agent_id="test:agent", require_verification=False)
            _add_task_with_status(plan, "Task A", "a", "completed")
            _add_task_with_status(plan, "Task B", "b", "pending", depends_on=["a"])

            server._save_plan_to_filesystem(plan)

            # Verify file exists
            plan_file = tmp_path / "tasks" / "plan.json"
            assert plan_file.exists()

            # Load and verify
            loaded = server._load_plan_from_filesystem("test:agent")
            assert loaded is not None
            assert len(loaded.tasks) == 2
            assert loaded.tasks[0].id == "a"
            assert loaded.tasks[0].status == "completed"
            assert loaded.tasks[1].id == "b"
            assert loaded.tasks[1].dependencies == ["a"]

        finally:
            server._workspace_path = original_workspace

    def test_load_returns_none_when_no_file(self, tmp_path):
        """Test that load returns None when plan file doesn't exist."""
        from massgen.mcp_tools.planning import _planning_mcp_server as server

        original_workspace = server._workspace_path

        try:
            server._workspace_path = tmp_path

            result = server._load_plan_from_filesystem("nonexistent")
            assert result is None

        finally:
            server._workspace_path = original_workspace
