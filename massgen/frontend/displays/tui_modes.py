"""TUI Mode State management for MassGen Textual terminal display.

This module provides the TuiModeState dataclass that tracks mode configuration
and generates orchestrator overrides based on current mode settings.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from massgen.plan_storage import PlanSession

# Type alias for plan depth
PlanDepth = Literal["dynamic", "shallow", "medium", "deep"]
AnalysisProfile = Literal["dev", "user"]
AnalysisTarget = Literal["log", "skills"]
SkillLifecycleMode = Literal["create_new", "create_or_update"]


@dataclass
class PlanConfig:
    """Configuration for plan mode behavior.

    Attributes:
        depth: Plan granularity level
            - "dynamic": planner chooses based on scope (default)
            - "shallow": 5-10 high-level tasks
            - "medium": 20-50 tasks
            - "deep": 100-200+ granular tasks
        target_steps: Optional explicit target number of tasks (None = dynamic)
        target_chunks: Optional explicit target number of chunks (default = 1, None = dynamic)
        execute_auto_continue_chunks: If True, auto-continue to next chunk after completion.
        execute_refinement_mode: Execute-time refinement mode:
            - "inherit": Use mode-bar refinement toggle
            - "on": Force refinement ON during execute turns
            - "off": Force refinement OFF during execute turns
        auto_execute: If True, skip approval and auto-execute after planning
        broadcast: Broadcast mode for planning phase
            - "human": Agents can ask human questions
            - "agents": Agents debate among themselves
            - False: Fully autonomous, no questions (default)
    """

    depth: PlanDepth = "dynamic"
    target_steps: int | None = None
    target_chunks: int | None = 1
    execute_auto_continue_chunks: bool = True
    execute_refinement_mode: Literal["inherit", "on", "off"] = "inherit"
    auto_execute: bool = False
    broadcast: Any = False  # "human" | "agents" | False

    def get_depth_description(self) -> str:
        """Get human-readable description of current depth."""
        descriptions = {
            "dynamic": "scope-adaptive",
            "shallow": "5-10 tasks",
            "medium": "20-50 tasks",
            "deep": "100-200+ tasks",
        }
        return descriptions.get(self.depth, "scope-adaptive")


@dataclass
class SpecConfig:
    """Configuration for spec creation mode behavior.

    Attributes:
        broadcast: Broadcast mode for spec creation phase
            - "human": Agents can ask human questions
            - "agents": Agents debate among themselves
            - False: Fully autonomous, no questions (default)
    """

    broadcast: Any = False  # "human" | "agents" | False


@dataclass
class AnalysisConfig:
    """Configuration for log analysis mode behavior."""

    # Analysis target:
    # - "log": analyze a specific log session/turn (existing behavior)
    # - "skills": analyze all installed skills for organization/merging/registry
    target: AnalysisTarget = "log"

    # Profile focus (used when target is "log"):
    # - "dev": internal MassGen debugging/improvement focus
    # - "user": reusable skill creation/refinement focus
    profile: AnalysisProfile = "user"

    # Selected analysis target. None means "auto-select current/latest".
    selected_log_dir: str | None = None
    selected_turn: int | None = None

    # Session-only skill allowlist. None means "no filtering" (all discovered skills).
    enabled_skill_names: list[str] | None = None

    # Include evolving skills discovered from previous sessions.
    include_previous_session_skills: bool = False

    # How newly discovered analysis skills are applied to project skills.
    skill_lifecycle_mode: SkillLifecycleMode = "create_or_update"

    # Pre-analysis snapshot for detecting new skills. Internal state only.
    _pre_analysis_skill_dirs: set[str] | None = field(default=None, repr=False)

    def get_enabled_skill_names(self) -> list[str] | None:
        """Return normalized enabled skill names, or None if unfiltered."""
        if self.enabled_skill_names is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for name in self.enabled_skill_names:
            cleaned = (name or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
        return normalized


@dataclass
class TuiModeState:
    """Tracks TUI mode configuration.

    Manages state for:
    - Plan mode: normal → plan → execute workflow
    - Agent mode: single vs multi-agent
    - Coordination mode: parallel voting vs decomposition subtasks
    - Refinement mode: enable/disable voting
    - Override state: human override of final answer selection
    """

    # Plan mode: "normal" | "plan" | "spec" | "plan_and_execute" | "execute" | "analysis"
    # - "normal": Standard mode, no planning
    # - "plan": Planning mode, will show approval before execute
    # - "spec": Spec creation mode, agents produce requirements specification
    # - "plan_and_execute": Planning mode, auto-execute without approval
    # - "execute": Currently executing a plan or spec
    plan_mode: str = "normal"
    plan_session: Optional["PlanSession"] = None
    pending_plan_approval: bool = False
    plan_config: PlanConfig = field(default_factory=PlanConfig)
    spec_config: SpecConfig = field(default_factory=SpecConfig)
    analysis_config: AnalysisConfig = field(default_factory=AnalysisConfig)
    plan_revision: int = 0
    planning_iteration_count: int = 0
    planning_feedback_history: list[str] = field(default_factory=list)
    last_planning_mode: str = "multi"  # "multi" | "single"
    pending_planning_feedback: str | None = None
    pending_planning_mode: str | None = None  # "multi" | "single"
    quick_edit_prev_agent_mode: str | None = None
    quick_edit_prev_selected_agent: str | None = None
    quick_edit_restore_pending: bool = False

    # Selected plan ID for execution (None = use latest, "new" = create new)
    selected_plan_id: str | None = None

    # Track the original question for plan execution prompt
    last_planning_question: str | None = None
    # Track which turn planning was initiated on
    planning_started_turn: int | None = None
    # Store context paths from planning phase for execution
    planning_context_paths: list[dict[str, Any]] | None = None

    # Agent mode: "multi" | "single"
    agent_mode: str = "multi"
    selected_single_agent: str | None = None

    # Coordination mode shown in TUI:
    # - "parallel" -> orchestrator coordination_mode="voting"
    # - "decomposition" -> orchestrator coordination_mode="decomposition"
    coordination_mode: str = "parallel"
    # Parallel persona generation toggle (off by default).
    # When enabled (and coordination mode is parallel), runtime persona generation is used.
    parallel_personas_enabled: bool = False
    # Diversity mode for persona generation ("perspective", "implementation", "methodology").
    persona_diversity_mode: str = "perspective"
    # Set to True after the user explicitly changes the coordination toggle
    coordination_mode_user_set: bool = False
    # Optional per-agent subtask overrides for decomposition mode
    decomposition_subtasks: dict[str, str] = field(default_factory=dict)

    # Refinement mode: True = normal voting, False = disabled
    refinement_enabled: bool = True

    # Override state
    override_pending: bool = False
    override_selected_agent: str | None = None

    # Track if override is available (after voting, before presentation)
    override_available: bool = False

    # Track cancelled state - persists until user provides new input
    was_cancelled: bool = False

    # Execution lock - prevents mode changes during agent execution
    execution_locked: bool = False

    def is_locked(self) -> bool:
        """Check if mode changes are locked (during execution)."""
        return self.execution_locked

    def lock(self) -> None:
        """Lock mode changes (call when execution starts)."""
        self.execution_locked = True

    def unlock(self) -> None:
        """Unlock mode changes (call when execution completes or is cancelled)."""
        self.execution_locked = False

    def get_orchestrator_overrides(self) -> dict[str, Any]:
        """Generate orchestrator config overrides based on current mode state.

        Returns:
            Dictionary of config overrides to apply to the orchestrator.

        Behavior matrix:
        - Coordination: parallel -> voting, decomposition -> decomposition
        - Single agent + refinement ON: Keep voting (vote = "I'm done refining")
        - Single agent + refinement OFF: max_new_answers_per_agent=1, skip_voting=True,
          skip_final_presentation=True (quick mode: one answer → done, no extra LLM call)
        - Multi-agent + refinement ON: Normal behavior
        - Multi-agent + refinement OFF: max_new_answers_per_agent=1, skip_final_presentation=True,
          disable_injection=True, defer_voting_until_all_answered=True
          (quick mode: agents work independently, vote once after all answered)
        """
        overrides: dict[str, Any] = {}

        # Coordination mode mapping from TUI labels to orchestrator config values.
        # Decomposition requires multiple active agents, so single-agent mode
        # always falls back to voting/parallel.
        effective_coordination_mode = self.coordination_mode
        if self.agent_mode == "single" and effective_coordination_mode == "decomposition":
            effective_coordination_mode = "parallel"
        overrides["coordination_mode"] = "decomposition" if effective_coordination_mode == "decomposition" else "voting"

        # Refinement disabled = quick mode
        if not self.refinement_enabled:
            # Limit to one answer per agent
            overrides["max_new_answers_per_agent"] = 1
            # Skip the final presentation LLM call - use existing answer directly
            overrides["skip_final_presentation"] = True

            if self.agent_mode == "single":
                # Single agent + refinement off = one answer, skip voting enforcement
                # Agent submits new_answer → immediate use as final answer
                overrides["skip_voting"] = True
            else:
                # Multi-agent + refinement off = agents work independently
                # No injection (each agent sees only the original task)
                overrides["disable_injection"] = True
                # Defer voting until all agents have answered (avoid wasteful restarts)
                overrides["defer_voting_until_all_answered"] = True
        # Note: Single agent + refinement ON keeps voting - vote signals "I'm done refining"

        return overrides

    def get_coordination_overrides(self) -> dict[str, Any]:
        """Generate coordination config overrides for plan mode.

        Returns:
            Dictionary of coordination config overrides to apply.
            Returns empty dict if plan mode is not active.

        When plan mode is active, enables:
        - enable_agent_task_planning: True
        - task_planning_filesystem_mode: True
        - plan_depth: From plan_config
        - broadcast: From plan_config
        """
        if self.plan_mode not in ("plan", "plan_and_execute", "spec"):
            return {}

        if self.plan_mode == "spec":
            return {
                "enable_agent_task_planning": True,
                "task_planning_filesystem_mode": True,
                "broadcast": self.spec_config.broadcast,
            }

        return {
            "enable_agent_task_planning": True,
            "task_planning_filesystem_mode": True,
            "plan_depth": self.plan_config.depth,
            "plan_target_steps": self.plan_config.target_steps,
            "plan_target_chunks": self.plan_config.target_chunks,
            "broadcast": self.plan_config.broadcast,
        }

    def get_effective_agents(self, all_agents: dict[str, Any]) -> dict[str, Any]:
        """Return active agents based on mode.

        Args:
            all_agents: Dictionary mapping agent_id to agent config/object.

        Returns:
            Filtered dictionary containing only active agents.
        """
        if self.agent_mode == "single" and self.selected_single_agent:
            if self.selected_single_agent in all_agents:
                return {self.selected_single_agent: all_agents[self.selected_single_agent]}
        return all_agents

    def get_effective_agent_ids(self, all_agent_ids: list[str]) -> list[str]:
        """Return active agent IDs based on mode.

        Args:
            all_agent_ids: List of all agent IDs from config.

        Returns:
            List containing only active agent IDs.
        """
        if self.agent_mode == "single" and self.selected_single_agent:
            if self.selected_single_agent in all_agent_ids:
                return [self.selected_single_agent]
        return all_agent_ids

    def reset_plan_state(self) -> None:
        """Reset plan-related state after plan completion or cancellation."""
        self.plan_mode = "normal"
        self.plan_session = None
        self.pending_plan_approval = False
        self.last_planning_question = None
        self.planning_started_turn = None
        self.selected_plan_id = None
        self.planning_context_paths = None
        self.plan_revision = 0
        self.planning_iteration_count = 0
        self.planning_feedback_history = []
        self.last_planning_mode = "multi"
        self.pending_planning_feedback = None
        self.pending_planning_mode = None
        self.quick_edit_prev_agent_mode = None
        self.quick_edit_prev_selected_agent = None
        self.quick_edit_restore_pending = False
        self.spec_config = SpecConfig()

    def reset_plan_state_with_error(self, error_msg: str) -> str:
        """Reset plan state due to an error.

        Logs the error and resets to normal mode.

        Args:
            error_msg: Description of what went wrong.

        Returns:
            The error message (for chaining with notifications).
        """
        import logging

        logger = logging.getLogger("massgen.tui.modes")
        logger.error(f"[TuiModeState] Plan error - resetting state: {error_msg}")
        self.reset_plan_state()
        return error_msg

    def reset_override_state(self) -> None:
        """Reset override-related state after override completion or cancellation."""
        self.override_pending = False
        self.override_selected_agent = None
        self.override_available = False

    def reset_cancelled_state(self) -> None:
        """Reset cancelled state when user starts a new turn."""
        self.was_cancelled = False

    def is_plan_active(self) -> bool:
        """Check if plan mode is active (not normal)."""
        return self.plan_mode != "normal"

    def is_single_agent_mode(self) -> bool:
        """Check if single-agent mode is active."""
        return self.agent_mode == "single"

    def get_mode_summary(self) -> str:
        """Return a human-readable summary of current mode state."""
        parts = []

        # Plan mode
        if self.plan_mode == "plan":
            parts.append("Plan: Creating")
        elif self.plan_mode == "execute":
            parts.append("Plan: Executing")
        elif self.plan_mode == "analysis":
            if self.analysis_config.target == "skills":
                parts.append("Analyze: Organize Skills")
            else:
                profile = self.analysis_config.profile.capitalize()
                parts.append(f"Analyze: {profile}")

        # Agent mode
        if self.agent_mode == "single":
            agent_name = self.selected_single_agent or "None"
            parts.append(f"Agent: {agent_name}")
        else:
            parts.append("Agents: Multi")

        # Coordination mode
        if self.coordination_mode == "decomposition":
            parts.append("Coord: Decomposition")
        elif self.parallel_personas_enabled:
            parts.append(f"Personas: {self.persona_diversity_mode.title()}")

        # Refinement mode
        if not self.refinement_enabled:
            parts.append("Refine: OFF")

        if not parts:
            return "Normal mode"

        return " | ".join(parts)


def get_analysis_placeholder_text(target: str) -> str:
    """Return input bar placeholder text for the given analysis target type."""
    if target == "skills":
        return "Enter to organize skills • or describe what to organize • Shift+Enter newline • @ for files • \u22ee for analysis options"
    return "Enter to analyze selected log • or describe what to analyze • Shift+Enter newline • @ for files • \u22ee for analysis options"
