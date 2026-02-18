#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Planning MCP Server for MassGen

This MCP server provides task planning and management tools for agents,
enabling them to create, track, and manage task plans with dependencies.

Tools provided:
- create_task_plan: Create a new task plan with dependencies
- add_task: Add a new task to the plan
- update_task_status: Update task status and detect newly ready tasks
- edit_task: Edit a task's description
- get_task_plan: Get the complete current task plan
- delete_task: Remove a task from the plan
- get_ready_tasks: Get tasks ready to start (dependencies satisfied)
- get_blocked_tasks: Get tasks blocked by dependencies
"""

import argparse
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import fastmcp

from massgen.mcp_tools.planning.planning_dataclasses import Task, TaskPlan

# Setup logging for debugging
logger = logging.getLogger(__name__)


def _has_extended_task_fields(task_spec: Dict[str, Any]) -> bool:
    """Check if task dict has extended fields beyond basic add_task parameters."""
    extended_fields = {"status", "metadata", "verification_group", "completed_at", "verified_at", "created_at"}
    return bool(extended_fields & set(task_spec.keys()))


def _create_task_from_dict(task_spec: Dict[str, Any]) -> Task:
    """Create a Task object from a dict, preserving all fields including extended ones."""
    from datetime import datetime

    task_id = task_spec.get("id") or str(uuid.uuid4())

    # Parse timestamps if present
    created_at = datetime.now()
    if task_spec.get("created_at"):
        try:
            created_at = datetime.fromisoformat(task_spec["created_at"])
        except (ValueError, TypeError):
            pass

    completed_at = None
    if task_spec.get("completed_at"):
        try:
            completed_at = datetime.fromisoformat(task_spec["completed_at"])
        except (ValueError, TypeError):
            pass

    verified_at = None
    if task_spec.get("verified_at"):
        try:
            verified_at = datetime.fromisoformat(task_spec["verified_at"])
        except (ValueError, TypeError):
            pass

    # Build metadata, including verification_group if present
    metadata = task_spec.get("metadata", {}).copy()
    if "verification_group" in task_spec and "verification_group" not in metadata:
        metadata["verification_group"] = task_spec["verification_group"]

    return Task(
        id=task_id,
        description=task_spec.get("description", ""),
        status=task_spec.get("status", "pending"),
        priority=task_spec.get("priority", "medium"),
        created_at=created_at,
        completed_at=completed_at,
        verified_at=verified_at,
        dependencies=task_spec.get("dependencies", task_spec.get("depends_on", [])),
        metadata=metadata,
    )


# Global storage for task plans (keyed by agent_id)
_task_plans: Dict[str, TaskPlan] = {}

# Optional workspace path for filesystem-based task storage
_workspace_path: Optional[Path] = None

# Whether two-tier workspace with git versioning is enabled
_use_two_tier_workspace: bool = False


def _git_commit_on_task_completion(task_id: str, completion_notes: Optional[str]) -> bool:
    """
    Create a git commit when a task is completed (if two-tier workspace is enabled).

    Args:
        task_id: The ID of the completed task
        completion_notes: Optional notes about the completion

    Returns:
        True if a commit was made, False otherwise
    """
    logger.info(f"[PlanningMCP] _git_commit_on_task_completion called for task {task_id}")
    logger.info(f"[PlanningMCP] _use_two_tier_workspace={_use_two_tier_workspace}, _workspace_path={_workspace_path}")

    if not _use_two_tier_workspace or _workspace_path is None:
        logger.info(f"[PlanningMCP] Skipping git commit - two_tier={_use_two_tier_workspace}, workspace={_workspace_path}")
        return False

    try:
        from massgen.filesystem_manager import git_commit_if_changed

        msg = f"[TASK] Completed: {task_id}"
        if completion_notes:
            msg += f"\n\n{completion_notes}"

        logger.info(f"[PlanningMCP] Calling git_commit_if_changed with workspace={_workspace_path}")
        result = git_commit_if_changed(_workspace_path, msg)
        logger.info(f"[PlanningMCP] git_commit_if_changed returned: {result}")
        return result
    except Exception as e:
        logger.warning(f"[PlanningMCP] Git commit error for task {task_id}: {e}")
        return False


def _save_plan_to_filesystem(plan: TaskPlan) -> None:
    """
    Save task plan to filesystem if workspace path is configured.

    Writes to tasks/plan.json in the workspace directory.

    Args:
        plan: TaskPlan to save
    """
    if _workspace_path is None:
        return

    tasks_dir = _workspace_path / "tasks"
    tasks_dir.mkdir(exist_ok=True)

    plan_file = tasks_dir / "plan.json"
    plan_file.write_text(json.dumps(plan.to_dict(), indent=2))


def _load_plan_from_filesystem(agent_id: str) -> Optional[TaskPlan]:
    """
    Load task plan from filesystem if it exists.

    Handles two formats:
    1. Full serialized format: {agent_id, tasks, created_at, updated_at, subagents}
    2. Simplified format: {tasks: [...]} - used by plan_and_execute frozen plans

    Args:
        agent_id: Agent identifier

    Returns:
        TaskPlan if found on filesystem, None otherwise
    """
    if _workspace_path is None:
        return None

    plan_file = _workspace_path / "tasks" / "plan.json"
    if not plan_file.exists():
        return None

    try:
        plan_data = json.loads(plan_file.read_text())

        # Check if this is the full serialized format or simplified format
        if "agent_id" in plan_data and "created_at" in plan_data:
            # Full format - use from_dict
            plan = TaskPlan.from_dict(plan_data)
            logger.info(f"[PlanningMCP] Loaded plan from filesystem (full format) with {len(plan.tasks)} tasks")
        else:
            # Simplified format - just has {"tasks": [...]}
            # Create a new TaskPlan and add tasks manually
            plan = TaskPlan(agent_id=agent_id)
            tasks_data = plan_data.get("tasks", [])

            # Two-pass loading for extended tasks:
            # Pass 1: Create all tasks and validate ID uniqueness
            # Pass 2: Validate dependencies exist (handles forward references)
            # Note: Circular dependency checking is skipped, as the file is assumed valid since it was refined
            extended_tasks = []

            for task_spec in tasks_data:
                # Handle both string tasks and dict tasks
                if isinstance(task_spec, str):
                    plan.add_task(description=task_spec)
                elif _has_extended_task_fields(task_spec):
                    # Task has extended fields (status, metadata, verification_group, etc.)
                    # Create Task directly to preserve all fields
                    task = _create_task_from_dict(task_spec)

                    # Validate ID uniqueness
                    if task.id in plan._task_index:
                        raise ValueError(f"Duplicate task ID in plan: {task.id}")

                    # Add to plan (dependencies validated in pass 2)
                    plan.tasks.append(task)
                    plan._task_index[task.id] = task
                    extended_tasks.append(task)
                else:
                    # Basic dict task - use add_task for validation
                    plan.add_task(
                        description=task_spec.get("description", ""),
                        task_id=task_spec.get("id"),
                        depends_on=task_spec.get("depends_on", []),
                        priority=task_spec.get("priority", "medium"),
                    )

            # Pass 2: Validate dependencies for extended tasks
            for task in extended_tasks:
                for dep_id in task.dependencies:
                    if dep_id not in plan._task_index:
                        raise ValueError(f"Task {task.id} has missing dependency: {dep_id}")

            logger.info(f"[PlanningMCP] Loaded plan from filesystem (simplified format) with {len(plan.tasks)} tasks")

        return plan
    except Exception as e:
        logger.warning(f"[PlanningMCP] Failed to load plan from filesystem: {e}")
        return None


def _get_or_create_plan(agent_id: str, orchestrator_id: str, require_verification: bool = True) -> TaskPlan:
    """
    Get existing plan or create new one for agent.

    If filesystem storage is enabled, attempts to load from tasks/plan.json first.

    Args:
        agent_id: Agent identifier
        orchestrator_id: Orchestrator identifier
        require_verification: Whether to require verification fields on new tasks

    Returns:
        TaskPlan for the agent
    """
    key = f"{orchestrator_id}:{agent_id}"

    if key not in _task_plans:
        # Try loading from filesystem if configured
        loaded_plan = _load_plan_from_filesystem(key)
        if loaded_plan is not None:
            loaded_plan.require_verification = require_verification
            _task_plans[key] = loaded_plan
        else:
            _task_plans[key] = TaskPlan(agent_id=key, require_verification=require_verification)
    else:
        # Update flag on existing plan (in case it changed)
        _task_plans[key].require_verification = require_verification

    return _task_plans[key]


def _resolve_dependency_references(
    task_list: List[Union[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Resolve dependency references (indices -> IDs) in task list.

    Args:
        task_list: List of task specifications

    Returns:
        List of normalized task dictionaries with resolved dependencies

    Raises:
        ValueError: If dependencies are invalid
    """
    # First pass: Generate IDs for all tasks
    normalized_tasks = []
    for i, task_spec in enumerate(task_list):
        if isinstance(task_spec, str):
            # Simple string task
            task_dict = {
                "id": f"task_{i}_{uuid.uuid4().hex[:8]}",
                "description": task_spec,
                "depends_on": [],
            }
        elif isinstance(task_spec, dict):
            # Dictionary task
            task_dict = task_spec.copy()
            if "id" not in task_dict:
                task_dict["id"] = f"task_{i}_{uuid.uuid4().hex[:8]}"
            if "depends_on" not in task_dict:
                task_dict["depends_on"] = []
        else:
            raise ValueError(f"Invalid task specification at index {i}: {task_spec}")

        normalized_tasks.append(task_dict)

    # Second pass: Resolve index-based dependencies to IDs
    for i, task_dict in enumerate(normalized_tasks):
        resolved_deps = []
        for dep in task_dict.get("depends_on", []):
            if isinstance(dep, int):
                # Index-based reference
                if dep < 0 or dep >= len(normalized_tasks):
                    raise ValueError(
                        f"Task '{task_dict['id']}': Invalid dependency index {dep}",
                    )
                if dep >= i:
                    raise ValueError(
                        f"Task '{task_dict['id']}': Dependencies must reference earlier tasks",
                    )
                resolved_deps.append(normalized_tasks[dep]["id"])
            else:
                # ID-based reference
                resolved_deps.append(dep)

        task_dict["depends_on"] = resolved_deps

    return normalized_tasks


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create and configure the planning MCP server."""
    global _workspace_path

    parser = argparse.ArgumentParser(description="Planning MCP Server")
    parser.add_argument(
        "--agent-id",
        type=str,
        required=True,
        help="ID of the agent using this planning server",
    )
    parser.add_argument(
        "--orchestrator-id",
        type=str,
        required=True,
        help="ID of the orchestrator managing this agent",
    )
    parser.add_argument(
        "--workspace-path",
        type=str,
        required=False,
        help="Optional path to agent workspace for filesystem-based task storage",
    )
    parser.add_argument(
        "--skills-enabled",
        action="store_true",
        help="Enable skills discovery task reminder",
    )
    parser.add_argument(
        "--auto-discovery-enabled",
        action="store_true",
        help="Enable custom tools/MCP discovery task reminder",
    )
    parser.add_argument(
        "--memory-enabled",
        action="store_true",
        help="Enable memory discovery and saving task reminders",
    )
    parser.add_argument(
        "--use-two-tier-workspace",
        action="store_true",
        help="Enable git commits on task completion (requires two-tier workspace)",
    )
    parser.add_argument(
        "--no-require-verification",
        action="store_true",
        help="Disable requiring verification and verification_method fields on agent-created tasks (enabled by default)",
    )
    args = parser.parse_args()

    # Configure logging to stderr so it appears in MCP server output
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"[PlanningMCP] Server starting for agent_id={args.agent_id}, orchestrator_id={args.orchestrator_id}")

    # Set workspace path if provided
    global _workspace_path, _use_two_tier_workspace
    if args.workspace_path:
        _workspace_path = Path(args.workspace_path)
        logger.info(f"[PlanningMCP] Workspace path set to: {_workspace_path}")

    # Set two-tier workspace flag for git commits on task completion
    _use_two_tier_workspace = args.use_two_tier_workspace
    logger.info(f"[PlanningMCP] Two-tier workspace flag: {_use_two_tier_workspace}")

    # Create the FastMCP server
    mcp = fastmcp.FastMCP("Agent Task Planning")

    # Store agent and orchestrator IDs
    mcp.agent_id = args.agent_id
    mcp.orchestrator_id = args.orchestrator_id

    # Store feature flags for auto-inserting discovery tasks
    mcp.skills_enabled = args.skills_enabled
    mcp.auto_discovery_enabled = args.auto_discovery_enabled
    mcp.memory_enabled = args.memory_enabled
    mcp.require_verification = not args.no_require_verification

    logger.debug(f"[PlanningMCP] Server configured - skills={args.skills_enabled}, auto_discovery={args.auto_discovery_enabled}, memory={args.memory_enabled}")

    @mcp.tool()
    def create_task_plan(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create a new task plan with a list of tasks.

        Each task must be a structured dictionary.
        By default, task dictionaries should include verification criteria.
        (If server is started with --no-require-verification, verification fields are optional.)

        Args:
            tasks: List of task dictionaries. Each task can have:
                - description (str): Task description (required)
                - verification (str): Acceptance criteria (required by default)
                - verification_method (str): How to verify output-first (strongly recommended)
                - id (str): Custom task ID (optional, auto-generated if not provided)
                - depends_on (list): Task IDs or indices this task depends on
                - priority (str): "low", "medium", or "high" (default: "medium")

        Returns:
            Dictionary with plan_id and created task list

        Priority:
            Indicates mission criticality. All tasks should be completed regardless
            of priority. Mark the core deliverables as "high" - completing them triggers
            a reflection reminder.

        Examples:
            create_task_plan([
                {
                    "id": "research",
                    "description": "Research OAuth providers",
                    "verification": "Comparison table with 3+ providers",
                    "verification_method": "Review output table for coverage and accuracy"
                },
                {
                    "id": "implement",
                    "description": "Implement OAuth",
                    "depends_on": ["research"],
                    "priority": "high",
                    "verification": "OAuth login works end-to-end",
                    "verification_method": "Run login flow and confirm callback exchanges token"
                },
                {
                    "id": "test",
                    "description": "Write tests",
                    "depends_on": ["implement"],
                    "verification": "All auth tests pass",
                    "verification_method": "Run pytest auth test suite"
                }
            ])

        Dependency Rules:
            - Can reference by index (0-based) or by custom task ID
            - Dependencies must reference earlier tasks in the list
            - Circular dependencies are rejected
            - Tasks with no dependencies can start immediately
            - Tasks with dependencies wait until all deps are completed
        """
        try:
            # Get or create plan for this agent
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))

            # Check if plan already has tasks - error to prevent duplicate work after recovery
            if plan.tasks:
                existing_count = len(plan.tasks)
                completed = len([t for t in plan.tasks if t.status == "completed"])
                in_progress = len([t for t in plan.tasks if t.status == "in_progress"])
                pending = len([t for t in plan.tasks if t.status == "pending"])
                logger.warning(
                    f"[PlanningMCP] REJECTING create_task_plan - plan already exists! " f"existing_count={existing_count}, completed={completed}, " f"in_progress={in_progress}, pending={pending}",
                )
                return {
                    "success": False,
                    "operation": "create_task_plan",
                    "error": (
                        f"A task plan already exists with {existing_count} tasks "
                        f"({completed} completed, {in_progress} in_progress, {pending} pending). "
                        f"Use get_task_plan to see current state, or add_task to add new tasks."
                    ),
                }

            # Auto-insert discovery tasks based on enabled features
            preparation_tasks = []

            # Create evolving skill - reminder to follow system prompt instructions
            if mcp.auto_discovery_enabled:
                preparation_tasks.append(
                    {
                        "id": "create_evolving_skill",
                        "description": ("Create tasks/evolving_skill/SKILL.md with your workflow plan. " "See the Evolving Skills section in system prompt for format."),
                        "priority": "high",
                    },
                )
            if mcp.memory_enabled:
                preparation_tasks.append(
                    {
                        "id": "prep_memory",
                        "description": "Check long-term memories for relevant context from previous work. Consider patterns, decisions, or discoveries that could inform your approach to this task.",
                        "priority": "high",
                    },
                )

            cleanup_tasks = []
            if mcp.auto_discovery_enabled:
                cleanup_tasks.append(
                    {
                        "id": "update_evolving_skill",
                        "description": (
                            "Update tasks/evolving_skill/SKILL.md with learnings from this session:\n"
                            "1. Refine ## Workflow based on what actually worked\n"
                            "2. Update ## Tools to Create - ensure scripts exist in scripts/ directory\n"
                            "3. Add ## Learnings section with:\n"
                            "   - What worked well\n"
                            "   - What didn't work or needed adjustment\n"
                            "   - Tips for future use\n"
                            "4. Update ## Dependencies if you discovered better approaches\n\n"
                            "This makes the skill reusable for similar future tasks."
                        ),
                        "priority": "medium",
                    },
                )
            if mcp.memory_enabled:
                cleanup_tasks.append(
                    {
                        "id": "save_memories",
                        "description": "Document decisions to optimize future work: skill/tool effectiveness, approach patterns, lessons learned, user preferences",
                        "priority": "medium",
                    },
                )

            # Combine: prep + user tasks + cleanup
            all_tasks = preparation_tasks + tasks + cleanup_tasks

            # Validate and resolve dependencies
            normalized_tasks = _resolve_dependency_references(all_tasks)
            plan.validate_dependencies(normalized_tasks)

            # Collect framework-injected task IDs so we can exempt them from verification
            framework_task_ids = {t["id"] for t in preparation_tasks + cleanup_tasks if isinstance(t, dict) and "id" in t}

            # Create tasks
            created_tasks = []
            for task_spec in normalized_tasks:
                is_framework = task_spec.get("id") in framework_task_ids

                task = plan.add_task(
                    description=task_spec["description"],
                    task_id=task_spec["id"],
                    depends_on=task_spec.get("depends_on", []),
                    priority=task_spec.get("priority", "medium"),
                    verification=task_spec.get("verification") or task_spec.get("metadata", {}).get("verification"),
                    verification_method=task_spec.get("verification_method") or task_spec.get("metadata", {}).get("verification_method"),
                    skip_verification=is_framework,
                )
                created_tasks.append(task.to_dict())

            # Save to filesystem if configured
            _save_plan_to_filesystem(plan)

            return {
                "success": True,
                "operation": "create_task_plan",
                "plan_id": plan.agent_id,
                "tasks": created_tasks,
                "summary": {
                    "total_tasks": len(created_tasks),
                    "ready_tasks": len(plan.get_ready_tasks()),
                    "blocked_tasks": len(plan.get_blocked_tasks()),
                },
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "create_task_plan",
                "error": str(e),
            }

    @mcp.tool()
    def clear_task_plan() -> Dict[str, Any]:
        """
        Clear the current task plan to start fresh.

        Removes all tasks from memory. Called by framework on agent restart.

        Returns:
            Dictionary with operation status
        """
        key = f"{mcp.orchestrator_id}:{mcp.agent_id}"

        had_plan = key in _task_plans
        if had_plan:
            del _task_plans[key]

        # Also clear filesystem if configured
        if _workspace_path is not None:
            plan_file = _workspace_path / "tasks" / "plan.json"
            if plan_file.exists():
                plan_file.unlink()

        return {"success": True, "operation": "clear_task_plan", "had_existing_plan": had_plan}

    @mcp.tool()
    def add_task(
        description: str,
        after_task_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: str = "medium",
        verification: Optional[str] = None,
        verification_method: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a new task to the plan.

        Args:
            description: Task description
            after_task_id: Optional ID to insert after (otherwise appends)
            depends_on: Optional list of task IDs this task depends on
            priority: Task priority (low/medium/high, defaults to medium)
            verification: What success looks like (acceptance criteria). Required by default unless server runs with --no-require-verification.
            verification_method: How to verify (specific steps, e.g. "screenshot and check with read_media")

        Returns:
            Dictionary with new task details

        Example:
            # Add high-priority task with verification criteria
            add_task(
                "Deploy to production",
                depends_on=["run_tests", "update_docs"],
                priority="high",
                verification="Site is live and returns 200 on /healthz",
                verification_method="curl https://example.com/healthz"
            )
        """
        try:
            # Validate priority
            valid_priorities = ["low", "medium", "high"]
            if priority not in valid_priorities:
                return {
                    "success": False,
                    "operation": "add_task",
                    "error": f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}",
                }

            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))

            task = plan.add_task(
                description=description,
                after_task_id=after_task_id,
                depends_on=depends_on or [],
                priority=priority,
                verification=verification,
                verification_method=verification_method,
            )

            # Save to filesystem if configured
            _save_plan_to_filesystem(plan)

            return {
                "success": True,
                "operation": "add_task",
                "task": task.to_dict(),
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "add_task",
                "error": str(e),
            }

    @mcp.tool()
    def update_task_status(
        task_id: str,
        status: str,  # Will be validated as Literal in the function
        completion_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update the status of a task.

        Status flow: pending -> in_progress -> completed -> verified
        - 'completed': Implementation is done, but may need verification
        - 'verified': Task has been tested and confirmed working

        Args:
            task_id: ID of task to update
            status: New status (pending/in_progress/completed/verified/blocked)
            completion_notes: Optional notes (for 'completed': how it was done; for 'verified': what was tested)

        Returns:
            Dictionary with updated task details and newly ready tasks

        Example:
            # Mark task as completed
            update_task_status("setup_project", "completed", "Created Next.js app with Tailwind")

            # Later, after verification passes
            update_task_status("setup_project", "verified", "npm run build passes, dev server runs")
        """
        try:
            # Validate status
            valid_statuses = ["pending", "in_progress", "completed", "verified", "blocked"]
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status '{status}'. Must be one of: {valid_statuses}",
                )

            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))
            result = plan.update_task_status(task_id, status, completion_notes)

            # Save to filesystem if configured
            _save_plan_to_filesystem(plan)

            # Git commit on task completion (if two-tier workspace enabled)
            git_committed = False
            if status == "completed":
                git_committed = _git_commit_on_task_completion(task_id, completion_notes)

            response = {
                "success": True,
                "operation": "update_task_status",
                **result,
            }

            # Include git commit info in response so agent knows what happened
            if git_committed:
                response["git_committed"] = True
                response["git_message"] = f"[TASK] Completed: {task_id}"

            return response

        except Exception as e:
            return {
                "success": False,
                "operation": "update_task_status",
                "error": str(e),
            }

    @mcp.tool()
    def edit_task(
        task_id: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Edit a task's description.

        Args:
            task_id: ID of task to edit
            description: New description (if provided)

        Returns:
            Dictionary with updated task details

        Example:
            edit_task("research_oauth", "Research OAuth 2.0 providers and best practices")
        """
        try:
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))
            task = plan.edit_task(task_id, description)

            # Save to filesystem if configured
            _save_plan_to_filesystem(plan)

            return {
                "success": True,
                "operation": "edit_task",
                "task": task.to_dict(),
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "edit_task",
                "error": str(e),
            }

    @mcp.tool()
    def get_task_plan() -> Dict[str, Any]:
        """
        Get the current task plan for this agent.

        Returns:
            Dictionary with complete task plan including all tasks and their statuses

        Example:
            plan = get_task_plan()
            print(f"Total tasks: {plan['summary']['total_tasks']}")
            print(f"Ready tasks: {plan['summary']['ready_tasks']}")
            print(f"Awaiting verification: {plan['summary']['awaiting_verification']}")
        """
        try:
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))

            ready_tasks = plan.get_ready_tasks()
            blocked_tasks = plan.get_blocked_tasks()
            awaiting_verification = plan.get_tasks_awaiting_verification()

            return {
                "success": True,
                "operation": "get_task_plan",
                "plan": plan.to_dict(),
                "summary": {
                    "total_tasks": len(plan.tasks),
                    "completed_tasks": sum(1 for t in plan.tasks if t.status == "completed"),
                    "verified_tasks": sum(1 for t in plan.tasks if t.status == "verified"),
                    "in_progress_tasks": sum(1 for t in plan.tasks if t.status == "in_progress"),
                    "ready_tasks": len(ready_tasks),
                    "blocked_tasks": len(blocked_tasks),
                    "awaiting_verification": sum(len(tasks) for tasks in awaiting_verification.values()),
                },
                "verification_groups": {group: [t.to_dict() for t in tasks] for group, tasks in awaiting_verification.items()},
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "get_task_plan",
                "error": str(e),
            }

    @mcp.tool()
    def delete_task(task_id: str) -> Dict[str, Any]:
        """
        Remove a task from the plan.

        Args:
            task_id: ID of task to delete

        Returns:
            Success confirmation

        Raises:
            Error if other tasks depend on this task

        Example:
            delete_task("obsolete_task_id")
        """
        try:
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))
            plan.delete_task(task_id)

            # Save to filesystem if configured
            _save_plan_to_filesystem(plan)

            return {
                "success": True,
                "operation": "delete_task",
                "deleted_task_id": task_id,
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "delete_task",
                "error": str(e),
            }

    @mcp.tool()
    def get_ready_tasks() -> Dict[str, Any]:
        """
        Get all tasks that are ready to start (dependencies satisfied).

        Returns:
            Dictionary with list of tasks that have status='pending' and all
            dependencies completed

        Use cases:
            - Identify which tasks can be worked on now
            - Find tasks that can be delegated in parallel
            - Avoid blocking on incomplete dependencies

        Example:
            result = get_ready_tasks()
            for task in result['ready_tasks']:
                print(f"Ready: {task['description']}")
        """
        try:
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))
            ready_tasks = plan.get_ready_tasks()

            return {
                "success": True,
                "operation": "get_ready_tasks",
                "ready_tasks": [t.to_dict() for t in ready_tasks],
                "count": len(ready_tasks),
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "get_ready_tasks",
                "error": str(e),
            }

    @mcp.tool()
    def get_blocked_tasks() -> Dict[str, Any]:
        """
        Get all tasks that are blocked by incomplete dependencies.

        Returns:
            Dictionary with list of tasks that have status='pending' but
            dependencies not completed, including what each task is waiting on

        Use cases:
            - Understand what's blocking progress
            - Prioritize completing blocking tasks
            - Visualize dependency chains

        Example:
            result = get_blocked_tasks()
            for task in result['blocked_tasks']:
                print(f"Blocked: {task['description']}")
                print(f"  Waiting on: {task['blocking_task_ids']}")
        """
        try:
            plan = _get_or_create_plan(mcp.agent_id, mcp.orchestrator_id, getattr(mcp, "require_verification", False))
            blocked_tasks = plan.get_blocked_tasks()

            # Add blocking task info for each blocked task
            blocked_with_info = []
            for task in blocked_tasks:
                task_dict = task.to_dict()
                task_dict["blocking_task_ids"] = plan.get_blocking_tasks(task.id)
                blocked_with_info.append(task_dict)

            return {
                "success": True,
                "operation": "get_blocked_tasks",
                "blocked_tasks": blocked_with_info,
                "count": len(blocked_tasks),
            }

        except Exception as e:
            return {
                "success": False,
                "operation": "get_blocked_tasks",
                "error": str(e),
            }

    return mcp


if __name__ == "__main__":
    import asyncio

    import fastmcp

    asyncio.run(fastmcp.run(create_server))
