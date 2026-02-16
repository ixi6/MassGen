# -*- coding: utf-8 -*-
"""
Subagent Data Models for MassGen

Provides dataclasses for configuring, tracking, and returning results from subagents.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# Subagent timeout defaults (in seconds)
# These are defaults; actual min/max are configurable via YAML
SUBAGENT_MIN_TIMEOUT = 60  # 1 minute (default minimum)
SUBAGENT_MAX_TIMEOUT = 600  # 10 minutes (default maximum)
SUBAGENT_DEFAULT_TIMEOUT = 300  # 5 minutes


@dataclass
class SubagentConfig:
    """
    Configuration for spawning a subagent.

    Attributes:
        id: Unique subagent identifier (UUID if not provided)
        task: The task/prompt for the subagent to execute
        parent_agent_id: ID of the agent that spawned this subagent
        model: Optional model override (inherits from parent if None)
        timeout_seconds: Maximum execution time (clamped to configured min/max range)
        context_files: List of file paths the subagent can READ (read-only access enforced)
        context_paths: Paths to mount read-only (files/dirs, "./" = parent workspace)
        use_docker: Whether to use Docker container (inherits from parent settings)
        system_prompt: Optional custom system prompt for the subagent
    """

    id: str
    task: str
    parent_agent_id: str
    model: Optional[str] = None
    timeout_seconds: int = 300
    context_files: List[str] = field(default_factory=list)
    context_paths: List[str] = field(default_factory=list)
    use_docker: bool = True
    system_prompt: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        task: str,
        parent_agent_id: str,
        subagent_id: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: int = SUBAGENT_DEFAULT_TIMEOUT,
        context_files: Optional[List[str]] = None,
        context_paths: Optional[List[str]] = None,
        use_docker: bool = True,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SubagentConfig":
        """
        Factory method to create a SubagentConfig with auto-generated ID.

        Args:
            task: The task for the subagent
            parent_agent_id: ID of the parent agent
            subagent_id: Optional custom ID (generates UUID if not provided)
            model: Optional model override
            timeout_seconds: Execution timeout (clamped at manager level to configured range)
            context_files: File paths subagent can read (read-only, no write access)
            context_paths: Paths to mount read-only (files/dirs, "./" = parent workspace)
            use_docker: Whether to use Docker
            system_prompt: Optional custom system prompt
            metadata: Additional metadata

        Returns:
            Configured SubagentConfig instance
        """
        # Note: timeout clamping is done at SubagentManager level with configurable min/max
        return cls(
            id=subagent_id or f"sub_{uuid.uuid4().hex[:8]}",
            task=task,
            parent_agent_id=parent_agent_id,
            model=model,
            timeout_seconds=timeout_seconds,
            context_files=context_files or [],
            context_paths=context_paths or [],
            use_docker=use_docker,
            system_prompt=system_prompt,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization."""
        return {
            "id": self.id,
            "task": self.task,
            "parent_agent_id": self.parent_agent_id,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "context_files": self.context_files.copy(),
            "context_paths": self.context_paths.copy(),
            "use_docker": self.use_docker,
            "system_prompt": self.system_prompt,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata.copy(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentConfig":
        """Create config from dictionary."""
        # Note: timeout clamping is done at SubagentManager level with configurable min/max
        return cls(
            id=data["id"],
            task=data["task"],
            parent_agent_id=data["parent_agent_id"],
            model=data.get("model"),
            timeout_seconds=data.get("timeout_seconds", SUBAGENT_DEFAULT_TIMEOUT),
            context_files=data.get("context_files", []),
            context_paths=data.get("context_paths", []),
            use_docker=data.get("use_docker", True),
            system_prompt=data.get("system_prompt"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SubagentOrchestratorConfig:
    """
    Configuration for subagent orchestrator mode.

    When enabled, subagents use a full Orchestrator with multiple agents.
    This enables multi-agent coordination within subagent execution.

    Attributes:
        enabled: Whether orchestrator mode is enabled (default False = single agent)
        agents: List of agent configurations for the subagent orchestrator.
                Each agent config can have: id (optional, auto-generated if missing),
                backend (with type, model, base_url, etc.)
                If empty/None, inherits from parent config.
        coordination: Optional coordination config subset (broadcast, planning, etc.)
        max_new_answers: Maximum new answers per agent before forcing consensus.
                        Default 3 for subagents to prevent runaway iterations.
        enable_web_search: Whether to enable web search for subagents (None = inherit from parent).
                          This is set in YAML config, not by agents at runtime.
    """

    enabled: bool = False
    agents: List[Dict[str, Any]] = field(default_factory=list)
    coordination: Dict[str, Any] = field(default_factory=dict)
    max_new_answers: int = 3  # Conservative default for subagents
    enable_web_search: Optional[bool] = None  # None = inherit from parent

    @property
    def num_agents(self) -> int:
        """Number of agents configured (defaults to 1 if no agents specified)."""
        return len(self.agents) if self.agents else 1

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.agents and len(self.agents) > 10:
            raise ValueError("Cannot have more than 10 agents for subagents")

    def get_agent_config(self, agent_index: int, subagent_id: str) -> Dict[str, Any]:
        """
        Get the config for a specific agent index.

        Args:
            agent_index: 0-based index of the agent
            subagent_id: ID of the parent subagent (for auto-generating agent IDs)

        Returns:
            Agent config dict with id and backend, or empty dict if not specified
        """
        if self.agents and agent_index < len(self.agents):
            config = self.agents[agent_index].copy()
            # Auto-generate ID if not provided
            if "id" not in config:
                config["id"] = f"{subagent_id}_agent_{agent_index + 1}"
            return config
        return {}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentOrchestratorConfig":
        """Create config from dictionary (YAML parsing)."""
        # Note: 'blocking' key is ignored (kept for backwards compatibility)
        return cls(
            enabled=data.get("enabled", False),
            agents=data.get("agents", []),
            coordination=data.get("coordination", {}),
            max_new_answers=data.get("max_new_answers", 3),
            enable_web_search=data.get("enable_web_search"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization."""
        result = {
            "enabled": self.enabled,
            "agents": [a.copy() for a in self.agents] if self.agents else [],
            "coordination": self.coordination.copy() if self.coordination else {},
            "max_new_answers": self.max_new_answers,
        }
        if self.enable_web_search is not None:
            result["enable_web_search"] = self.enable_web_search
        return result


@dataclass
class SubagentResult:
    """
    Structured result returned from subagent execution.

    Attributes:
        subagent_id: ID of the subagent
        status: Final status - one of:
            - completed: Normal successful completion
            - completed_but_timeout: Work completed but parent timed out (recovered answer)
            - partial: Partial work available (in voting phase, no winner)
            - timeout: Timed out with no recoverable work
            - error: Failed with error
        success: Whether execution was successful
        answer: Final answer text from the subagent (includes relevant file paths)
        workspace_path: Path to the subagent's workspace (always set, even on timeout/error)
        execution_time_seconds: How long the subagent ran
        error: Error message if status is error/timeout
        token_usage: Token usage statistics (if available)
        log_path: Path to subagent log directory (for debugging on failure/timeout)
        completion_percentage: Coordination completion percentage (0-100) if available
    """

    subagent_id: str
    status: Literal["completed", "completed_but_timeout", "partial", "timeout", "error"]
    success: bool
    answer: Optional[str] = None
    workspace_path: str = ""
    execution_time_seconds: float = 0.0
    error: Optional[str] = None
    token_usage: Dict[str, int] = field(default_factory=dict)
    log_path: Optional[str] = None
    completion_percentage: Optional[int] = None
    warning: Optional[str] = None  # Warning messages (e.g., context truncation)

    @staticmethod
    def resolve_events_path(base_log_dir: Path) -> Optional[str]:
        """Resolve the path to events.jsonl from a base log directory.

        This method finds the exact events.jsonl file path from a subagent's
        base log directory, checking both completed and live subagent paths.

        Priority:
        1. full_logs/events.jsonl (completed subagents)
        2. full_logs/turn_1/attempt_1/events.jsonl (legacy completed layout)
        3. live_logs/log_*/turn_1/attempt_1/events.jsonl (running subagents)
        4. subprocess_logs.json reference (fallback)

        Args:
            base_log_dir: Base log directory for the subagent (e.g., /logs/sub_abc123/)

        Returns:
            Full path to events.jsonl if found, None otherwise
        """
        # Check full_logs (completed subagents)
        full_logs_events = base_log_dir / "full_logs" / "events.jsonl"
        if full_logs_events.exists():
            return str(full_logs_events.resolve())

        # Legacy layout: full_logs/turn_1/attempt_1/events.jsonl
        legacy_full_logs = base_log_dir / "full_logs" / "turn_1" / "attempt_1" / "events.jsonl"
        if legacy_full_logs.exists():
            return str(legacy_full_logs.resolve())

        # Check live_logs (running subagents)
        live_logs = base_log_dir / "live_logs"
        if live_logs.exists():
            try:
                for subdir in sorted(live_logs.glob("log_*"), reverse=True):
                    candidate = subdir / "turn_1" / "attempt_1" / "events.jsonl"
                    if candidate.exists():
                        return str(candidate.resolve())
                    # Fallback if events.jsonl lives at root of log_* (older layout)
                    candidate = subdir / "events.jsonl"
                    if candidate.exists():
                        return str(candidate.resolve())
            except Exception:
                pass

        # Read subprocess_logs.json for live path
        subprocess_ref = base_log_dir / "subprocess_logs.json"
        if subprocess_ref.exists():
            try:
                ref_data = json.loads(subprocess_ref.read_text())
                subprocess_log_dir = ref_data.get("subprocess_log_dir")
                if subprocess_log_dir:
                    live_events = Path(subprocess_log_dir) / "events.jsonl"
                    if live_events.exists():
                        return str(live_events.resolve())
            except (json.JSONDecodeError, OSError):
                pass

        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for tool return value."""
        result = {
            "subagent_id": self.subagent_id,
            "status": self.status,
            "success": self.success,
            "answer": self.answer,
            "workspace": self.workspace_path,
            "execution_time_seconds": self.execution_time_seconds,
            "error": self.error,
            "token_usage": self.token_usage.copy(),
        }
        # Include log_path if available (useful for debugging failed/timed out subagents)
        # Resolve to the events.jsonl file path for TUI consumption
        if self.log_path:
            log_dir = Path(self.log_path)
            resolved = SubagentResult.resolve_events_path(log_dir)
            result["log_path"] = resolved or self.log_path
        # Include completion_percentage if available (for timeout recovery)
        if self.completion_percentage is not None:
            result["completion_percentage"] = self.completion_percentage
        # Include warning if present (e.g., context truncation)
        if self.warning:
            result["warning"] = self.warning
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentResult":
        """Create result from dictionary."""
        return cls(
            subagent_id=data["subagent_id"],
            status=data["status"],
            success=data["success"],
            answer=data.get("answer"),
            workspace_path=data.get("workspace", ""),
            execution_time_seconds=data.get("execution_time_seconds", 0.0),
            error=data.get("error"),
            token_usage=data.get("token_usage", {}),
            log_path=data.get("log_path"),
            completion_percentage=data.get("completion_percentage"),
            warning=data.get("warning"),
        )

    @classmethod
    def create_success(
        cls,
        subagent_id: str,
        answer: str,
        workspace_path: str,
        execution_time_seconds: float,
        token_usage: Optional[Dict[str, int]] = None,
        log_path: Optional[str] = None,
        warning: Optional[str] = None,
    ) -> "SubagentResult":
        """Create a successful result."""
        return cls(
            subagent_id=subagent_id,
            status="completed",
            success=True,
            answer=answer,
            workspace_path=workspace_path,
            execution_time_seconds=execution_time_seconds,
            token_usage=token_usage or {},
            log_path=log_path,
            warning=warning,
        )

    @classmethod
    def create_timeout(
        cls,
        subagent_id: str,
        workspace_path: str,
        timeout_seconds: float,
        log_path: Optional[str] = None,
        warning: Optional[str] = None,
    ) -> "SubagentResult":
        """Create a timeout result."""
        return cls(
            subagent_id=subagent_id,
            status="timeout",
            success=False,
            answer=None,
            workspace_path=workspace_path,
            execution_time_seconds=timeout_seconds,
            error=f"Subagent exceeded timeout of {timeout_seconds} seconds",
            log_path=log_path,
            warning=warning,
        )

    @classmethod
    def create_error(
        cls,
        subagent_id: str,
        error: str,
        workspace_path: str = "",
        execution_time_seconds: float = 0.0,
        log_path: Optional[str] = None,
        warning: Optional[str] = None,
    ) -> "SubagentResult":
        """Create an error result."""
        return cls(
            subagent_id=subagent_id,
            status="error",
            success=False,
            answer=None,
            workspace_path=workspace_path,
            execution_time_seconds=execution_time_seconds,
            error=error,
            log_path=log_path,
            warning=warning,
        )

    @classmethod
    def create_timeout_with_recovery(
        cls,
        subagent_id: str,
        workspace_path: str,
        timeout_seconds: float,
        recovered_answer: Optional[str] = None,
        completion_percentage: Optional[int] = None,
        token_usage: Optional[Dict[str, Any]] = None,
        log_path: Optional[str] = None,
        is_partial: bool = False,
        warning: Optional[str] = None,
    ) -> "SubagentResult":
        """
        Create a timeout result with recovered work from the workspace.

        This factory method is used when a subagent times out but has completed
        or partial work that can be recovered from its workspace.

        Args:
            subagent_id: ID of the subagent
            workspace_path: Path to subagent workspace (always provided)
            timeout_seconds: How long the subagent ran before timeout
            recovered_answer: Answer extracted from workspace (None if no work)
            completion_percentage: Coordination completion percentage (0-100)
            token_usage: Token costs extracted from status.json
            log_path: Path to log directory
            is_partial: True if work is partial (no winner selected)
            warning: Warning message (e.g., context truncation)

        Returns:
            SubagentResult with appropriate status:
            - completed_but_timeout: Full answer recovered (success=True)
            - partial: Partial work recovered (success=False)
            - timeout: No work recovered (success=False)
        """
        if recovered_answer is not None:
            if is_partial:
                status = "partial"
                success = False
            else:
                status = "completed_but_timeout"
                success = True
        else:
            status = "timeout"
            success = False

        return cls(
            subagent_id=subagent_id,
            status=status,
            success=success,
            answer=recovered_answer,
            workspace_path=workspace_path,
            execution_time_seconds=timeout_seconds,
            error=f"Subagent exceeded timeout of {timeout_seconds} seconds",
            token_usage=token_usage or {},
            log_path=log_path,
            completion_percentage=completion_percentage,
            warning=warning,
        )


@dataclass
class SubagentPointer:
    """
    Pointer to a subagent for tracking in plan.json.

    Used to track subagents spawned during task execution and provide
    visibility into their workspaces and results.

    Attributes:
        id: Subagent identifier
        task: Task description given to the subagent
        workspace: Path to the subagent's workspace
        status: Current status (running/completed/failed/timeout)
        created_at: When the subagent was spawned
        completed_at: When the subagent finished (if applicable)
        result_summary: Brief summary of the result (if completed)
    """

    id: str
    task: str
    workspace: str
    status: Literal["running", "completed", "failed", "timeout"]
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    result_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert pointer to dictionary for serialization."""
        return {
            "id": self.id,
            "task": self.task,
            "workspace": self.workspace,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentPointer":
        """Create pointer from dictionary."""
        return cls(
            id=data["id"],
            task=data["task"],
            workspace=data["workspace"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result_summary=data.get("result_summary"),
        )

    def mark_completed(self, result: SubagentResult) -> None:
        """Update pointer when subagent completes."""
        self.status = "completed" if result.success else ("timeout" if result.status == "timeout" else "failed")
        self.completed_at = datetime.now()
        if result.answer:
            # Truncate summary to first 200 chars
            self.result_summary = result.answer[:200] + ("..." if len(result.answer) > 200 else "")


@dataclass
class SubagentState:
    """
    Runtime state of a subagent for tracking during execution.

    Used internally by SubagentManager to track active subagents.

    Attributes:
        config: The subagent configuration
        status: Current execution status
        workspace_path: Path to subagent workspace
        started_at: When execution started
        finished_at: When execution finished
        result: Final result (when completed)
    """

    config: SubagentConfig
    status: Literal["pending", "running", "completed", "completed_but_timeout", "partial", "failed", "timeout"] = "pending"
    workspace_path: str = ""
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[SubagentResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "config": self.config.to_dict(),
            "status": self.status,
            "workspace_path": self.workspace_path,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result.to_dict() if self.result else None,
        }


@dataclass
class SubagentDisplayData:
    """
    Display data for rendering a subagent in the TUI.

    Used by SubagentCard to show live progress, activity, and status.
    Provides a snapshot of subagent state optimized for display purposes.

    Attributes:
        id: Subagent identifier
        task: The task description
        status: Current execution status
        progress_percent: Progress estimate (0-100), based on elapsed/timeout
        elapsed_seconds: Time elapsed since start
        timeout_seconds: Maximum allowed execution time
        workspace_path: Path to subagent workspace directory
        workspace_file_count: Number of files in workspace
        last_log_line: Most recent log line for activity display
        error: Error message if status is error/failed
        answer_preview: First ~100 chars of answer if completed
    """

    id: str
    task: str
    status: Literal["pending", "running", "completed", "error", "timeout", "failed"]
    progress_percent: int  # 0-100, based on elapsed/timeout
    elapsed_seconds: float
    timeout_seconds: float
    workspace_path: str
    workspace_file_count: int
    last_log_line: str
    error: Optional[str] = None
    answer_preview: Optional[str] = None
    log_path: Optional[str] = None  # Path to log directory for log streaming

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "elapsed_seconds": self.elapsed_seconds,
            "timeout_seconds": self.timeout_seconds,
            "workspace_path": self.workspace_path,
            "workspace_file_count": self.workspace_file_count,
            "last_log_line": self.last_log_line,
            "error": self.error,
            "answer_preview": self.answer_preview,
            "log_path": self.log_path,
        }
