"""
Task Planning Data Structures for MassGen

Provides dataclasses for managing agent task plans with dependency tracking,
status management, validation, and subagent tracking.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass


@dataclass
class Task:
    """
    Represents a single task in an agent's plan.

    Attributes:
        id: Unique task identifier (UUID or custom string)
        description: Human-readable task description
        status: Current task status (pending/in_progress/completed/verified/blocked)
        priority: Task priority level (low/medium/high, defaults to medium)
        created_at: Timestamp when task was created
        completed_at: Timestamp when task was completed (if applicable)
        verified_at: Timestamp when task was verified (if applicable)
        dependencies: List of task IDs this task depends on
        metadata: Additional task-specific metadata (includes verification_group)
    """

    id: str
    description: str
    status: Literal["pending", "in_progress", "completed", "verified", "blocked"] = "pending"
    priority: Literal["low", "medium", "high"] = "medium"
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    verified_at: datetime | None = None
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary for serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "dependencies": self.dependencies.copy(),
            "metadata": self.metadata.copy(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create task from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            status=data["status"],
            priority=data.get("priority", "medium"),
            created_at=datetime.fromisoformat(data["created_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            verified_at=datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else None,
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskPlan:
    """
    Manages an agent's task plan with dependency tracking.

    Attributes:
        agent_id: ID of the agent who owns this plan
        tasks: List of tasks in the plan
        created_at: Timestamp when plan was created
        updated_at: Timestamp when plan was last updated
    """

    agent_id: str
    display_id: str | None = None  # Anonymous ID for serialization; defaults to agent_id if None
    tasks: list[Task] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    subagents: dict[str, dict[str, Any]] = field(default_factory=dict)
    require_verification: bool = True

    def __post_init__(self):
        """Initialize task index for fast lookups."""
        self._task_index: dict[str, Task] = {task.id: task for task in self.tasks}

    def get_task(self, task_id: str) -> Task | None:
        """
        Get a task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task if found, None otherwise
        """
        return self._task_index.get(task_id)

    def can_start_task(self, task_id: str) -> bool:
        """
        Check if a task can be started (all dependencies completed or verified).

        Args:
            task_id: Task to check

        Returns:
            True if all dependencies are completed/verified, False otherwise
        """
        task = self.get_task(task_id)
        if not task:
            return False

        for dep_id in task.dependencies:
            dep_task = self.get_task(dep_id)
            if not dep_task or dep_task.status not in ("completed", "verified"):
                return False

        return True

    def get_ready_tasks(self) -> list[Task]:
        """
        Get all tasks ready to start (pending with satisfied dependencies).

        Returns:
            List of tasks with status='pending' and all dependencies completed
        """
        return [task for task in self.tasks if task.status == "pending" and self.can_start_task(task.id)]

    def get_blocked_tasks(self) -> list[Task]:
        """
        Get all tasks blocked by dependencies.

        Returns:
            List of tasks with status='pending' but dependencies not completed,
            including information about what each task is waiting on
        """
        blocked = []
        for task in self.tasks:
            if task.status == "pending" and not self.can_start_task(task.id):
                blocked.append(task)
        return blocked

    def get_tasks_awaiting_verification(self) -> dict[str, list[Task]]:
        """
        Get all tasks with status='completed' that need verification, grouped by verification_group.

        Returns:
            Dictionary mapping verification_group to list of completed tasks.
            Tasks without a verification_group are grouped under 'ungrouped'.
        """
        awaiting: dict[str, list[Task]] = {}
        for task in self.tasks:
            if task.status == "completed":
                group = task.metadata.get("verification_group", "ungrouped")
                if group not in awaiting:
                    awaiting[group] = []
                awaiting[group].append(task)
        return awaiting

    def get_verification_group_status(self, group: str) -> dict[str, Any]:
        """
        Get the status of a verification group.

        Args:
            group: The verification_group name to check

        Returns:
            Dict containing:
                - group (str): The verification_group name
                - total (int): Total number of tasks in the group
                - status_counts (dict): Counts per status with keys:
                    pending, in_progress, completed, verified, blocked
                - all_completed (bool): True if no tasks are pending, in_progress, or blocked
                - all_verified (bool): True if all tasks have status "verified"
        """
        status_counts = {"pending": 0, "in_progress": 0, "completed": 0, "verified": 0, "blocked": 0}
        tasks_in_group = []

        for task in self.tasks:
            task_group = task.metadata.get("verification_group", "ungrouped")
            if task_group == group:
                status_counts[task.status] += 1
                tasks_in_group.append(task)

        return {
            "group": group,
            "total": len(tasks_in_group),
            "status_counts": status_counts,
            "all_completed": status_counts["pending"] == 0 and status_counts["in_progress"] == 0 and status_counts["blocked"] == 0,
            "all_verified": status_counts["pending"] == 0 and status_counts["in_progress"] == 0 and status_counts["blocked"] == 0 and status_counts["completed"] == 0,
        }

    def get_blocking_tasks(self, task_id: str) -> list[str]:
        """
        Get list of incomplete dependency task IDs blocking a task.

        Args:
            task_id: Task to check

        Returns:
            List of task IDs that are blocking this task
        """
        task = self.get_task(task_id)
        if not task:
            return []

        blocking = []
        for dep_id in task.dependencies:
            dep_task = self.get_task(dep_id)
            if dep_task and dep_task.status not in ("completed", "verified"):
                blocking.append(dep_id)

        return blocking

    def add_task(
        self,
        description: str,
        task_id: str | None = None,
        after_task_id: str | None = None,
        depends_on: list[str] | None = None,
        priority: Literal["low", "medium", "high"] = "medium",
        verification: str | None = None,
        verification_method: str | None = None,
        skip_verification: bool = False,
        subagent_id: str | None = None,
        subagent_name: str | None = None,
    ) -> Task:
        """
        Add a new task to the plan.

        Args:
            description: Task description
            task_id: Optional custom task ID (generates UUID if not provided)
            after_task_id: Optional ID to insert after (otherwise appends)
            depends_on: Optional list of task IDs this task depends on
            priority: Task priority level (low/medium/high, defaults to medium)
            verification: What success looks like (acceptance criteria)
            verification_method: How to verify it (specific steps)
            skip_verification: If True, bypass require_verification enforcement (for framework tasks)

        Returns:
            The newly created task

        Raises:
            ValueError: If dependencies are invalid or circular
        """
        # Generate ID if not provided
        if not task_id:
            task_id = str(uuid.uuid4())

        # Validate task ID is unique
        if task_id in self._task_index:
            raise ValueError(f"Task ID already exists: {task_id}")

        # Validate dependencies exist
        if depends_on:
            for dep_id in depends_on:
                if dep_id not in self._task_index:
                    raise ValueError(f"Dependency task does not exist: {dep_id}")

        # Enforce verification fields if required (skip for framework-injected tasks)
        if self.require_verification and not skip_verification and not verification:
            raise ValueError(
                f"Task '{description[:60]}' is missing required 'verification' field. " "Provide acceptance criteria describing what success looks like.",
            )

        # Build metadata with verification fields if provided
        metadata: dict[str, Any] = {}
        if verification:
            metadata["verification"] = verification
        if verification_method:
            metadata["verification_method"] = verification_method
        if subagent_id:
            metadata["subagent_id"] = subagent_id
        if subagent_name:
            metadata["subagent_name"] = subagent_name

        # Create task
        task = Task(
            id=task_id,
            description=description,
            dependencies=depends_on or [],
            priority=priority,
            metadata=metadata,
        )

        # Check for circular dependencies before adding
        temp_tasks = self.tasks + [task]
        if self._has_circular_dependency(task_id, temp_tasks):
            raise ValueError(f"Circular dependency detected for task: {task_id}")

        # Add to plan
        if after_task_id:
            # Find position and insert
            for i, t in enumerate(self.tasks):
                if t.id == after_task_id:
                    self.tasks.insert(i + 1, task)
                    break
            else:
                raise ValueError(f"after_task_id not found: {after_task_id}")
        else:
            # Append to end
            self.tasks.append(task)

        # Update index and timestamp
        self._task_index[task_id] = task
        self.updated_at = datetime.now()

        return task

    def update_task_status(
        self,
        task_id: str,
        status: Literal["pending", "in_progress", "completed", "verified", "blocked"],
        completion_notes: str | None = None,
    ) -> dict[str, Any]:
        """
        Update task status and detect newly unblocked tasks.

        Status flow: pending -> in_progress -> completed -> verified
        - 'completed' means the implementation is done
        - 'verified' means the task has been tested and confirmed working

        Args:
            task_id: ID of task to update
            status: New status
            completion_notes: Optional notes documenting how task was completed/verified

        Returns:
            Dictionary with updated task and newly_ready_tasks

        Raises:
            ValueError: If task not found
        """
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        task.status = status
        self.updated_at = datetime.now()

        if status == "completed":
            task.completed_at = datetime.now()

            # Store completion notes in metadata if provided
            if completion_notes:
                task.metadata["completion_notes"] = completion_notes

            # Find newly ready tasks
            newly_ready = []
            for other_task in self.tasks:
                if other_task.status == "pending" and task_id in other_task.dependencies and self.can_start_task(other_task.id):
                    newly_ready.append(other_task)

            # Build completion result
            result: dict[str, Any] = {
                "task": task.to_dict(),
                "newly_ready_tasks": [t.to_dict() for t in newly_ready],
            }

            # Surface verification reminder if task has verification criteria
            has_verification = "verification" in task.metadata and task.metadata["verification"]
            if has_verification:
                result["verification_pending"] = True
                result["verification"] = task.metadata["verification"]
                if "verification_method" in task.metadata:
                    result["verification_method"] = task.metadata["verification_method"]

                # Count all completed-but-unverified tasks with verification criteria
                unverified = sum(1 for t in self.tasks if t.status == "completed" and "verification" in t.metadata and t.metadata["verification"])
                result["unverified_count"] = unverified

            return result

        if status == "verified":
            task.verified_at = datetime.now()

            # Store verification notes in metadata if provided
            if completion_notes:
                task.metadata["verification_notes"] = completion_notes

            return {"task": task.to_dict()}

        return {"task": task.to_dict()}

    def edit_task(self, task_id: str, description: str | None = None) -> Task:
        """
        Edit a task's description.

        Args:
            task_id: ID of task to edit
            description: New description (if provided)

        Returns:
            Updated task

        Raises:
            ValueError: If task not found
        """
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        if description is not None:
            task.description = description

        self.updated_at = datetime.now()
        return task

    def delete_task(self, task_id: str) -> None:
        """
        Remove a task from the plan.

        Args:
            task_id: ID of task to delete

        Raises:
            ValueError: If task not found or other tasks depend on it
        """
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Check if any tasks depend on this one
        for other_task in self.tasks:
            if task_id in other_task.dependencies:
                raise ValueError(
                    f"Cannot delete task {task_id}: task {other_task.id} depends on it",
                )

        # Remove from list and index
        self.tasks.remove(task)
        del self._task_index[task_id]
        self.updated_at = datetime.now()

    def validate_dependencies(self, task_list: list[dict[str, Any]]) -> None:
        """
        Validate dependencies when creating a task plan.

        Checks:
        - Dependencies reference valid tasks (earlier in list or by valid ID)
        - No circular dependencies
        - No self-references

        Args:
            task_list: List of task dictionaries with potential dependencies

        Raises:
            ValueError: If validation fails
        """
        # Build ID mapping
        task_ids = set()
        for i, task_spec in enumerate(task_list):
            if isinstance(task_spec, dict) and "id" in task_spec:
                task_id = task_spec["id"]
            else:
                task_id = f"task_{i}"
            task_ids.add(task_id)

        # Validate each task's dependencies
        for i, task_spec in enumerate(task_list):
            if isinstance(task_spec, dict):
                task_id = task_spec.get("id", f"task_{i}")
                depends_on = task_spec.get("depends_on", [])

                if depends_on:
                    for dep in depends_on:
                        # Handle index-based dependency
                        if isinstance(dep, int):
                            if dep < 0 or dep >= len(task_list):
                                raise ValueError(
                                    f"Task {task_id}: Invalid dependency index {dep}",
                                )
                            if dep >= i:
                                raise ValueError(
                                    f"Task {task_id}: Dependencies must reference earlier tasks (index {dep} >= {i})",
                                )
                        # Handle ID-based dependency
                        else:
                            if dep not in task_ids:
                                raise ValueError(
                                    f"Task {task_id}: Dependency {dep} not found in task list",
                                )
                            if dep == task_id:
                                raise ValueError(
                                    f"Task {task_id}: Self-dependency detected",
                                )

    def _has_circular_dependency(self, task_id: str, all_tasks: list[Task]) -> bool:
        """
        Check if adding a task would create a circular dependency.

        Args:
            task_id: ID of task to check
            all_tasks: All tasks including the new one

        Returns:
            True if circular dependency detected, False otherwise
        """
        # Build dependency graph
        task_map = {t.id: t for t in all_tasks}

        # DFS to detect cycles
        visited = set()
        rec_stack = set()

        def has_cycle(tid: str) -> bool:
            if tid in rec_stack:
                return True
            if tid in visited:
                return False

            visited.add(tid)
            rec_stack.add(tid)

            task = task_map.get(tid)
            if task:
                for dep_id in task.dependencies:
                    if has_cycle(dep_id):
                        return True

            rec_stack.remove(tid)
            return False

        return has_cycle(task_id)

    def to_dict(self) -> dict[str, Any]:
        """Convert plan to dictionary for serialization."""
        return {
            "agent_id": self.display_id if self.display_id is not None else self.agent_id,
            "tasks": [task.to_dict() for task in self.tasks],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "subagents": self.subagents.copy(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        """Create plan from dictionary."""
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        plan = cls(
            agent_id=data["agent_id"],
            tasks=tasks,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            subagents=data.get("subagents", {}),
        )
        return plan

    def add_subagent(
        self,
        subagent_id: str,
        task: str,
        workspace: str,
        status: str = "running",
    ) -> None:
        """
        Add a subagent pointer to the plan for tracking.

        Args:
            subagent_id: Unique subagent identifier
            task: Task description given to the subagent
            workspace: Path to subagent's workspace
            status: Initial status (default: "running")
        """
        self.subagents[subagent_id] = {
            "id": subagent_id,
            "task": task,
            "workspace": workspace,
            "status": status,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "result_summary": None,
        }
        self.updated_at = datetime.now()

    def update_subagent_status(
        self,
        subagent_id: str,
        status: str,
        result_summary: str | None = None,
    ) -> None:
        """
        Update a subagent's status in the plan.

        Args:
            subagent_id: Subagent identifier
            status: New status (running/completed/failed/timeout)
            result_summary: Optional summary of the result
        """
        if subagent_id not in self.subagents:
            return

        self.subagents[subagent_id]["status"] = status
        if status in ("completed", "failed", "timeout"):
            self.subagents[subagent_id]["completed_at"] = datetime.now().isoformat()
        if result_summary:
            self.subagents[subagent_id]["result_summary"] = result_summary
        self.updated_at = datetime.now()

    def get_subagent(self, subagent_id: str) -> dict[str, Any] | None:
        """
        Get a subagent pointer by ID.

        Args:
            subagent_id: Subagent identifier

        Returns:
            Subagent info dict if found, None otherwise
        """
        return self.subagents.get(subagent_id)
