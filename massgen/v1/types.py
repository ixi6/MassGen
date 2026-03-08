"""
MassGen System Types

This module contains all the core type definitions and dataclasses
used throughout the MassGen framework.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnswerRecord:
    """Represents a single answer record in an agent's update history."""

    timestamp: float
    answer: str
    status: str

    def __post_init__(self):
        """Ensure timestamp is set if not provided."""
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class VoteRecord:
    """Records a vote cast by an agent."""

    voter_id: int
    target_id: int
    reason: str = ""  # the full response text that led to this vote
    timestamp: float = 0.0

    def __post_init__(self):
        """Ensure timestamp is set if not provided."""
        if not self.timestamp:
            import time

            self.timestamp = time.time()


@dataclass
class ModelConfig:
    """Configuration for agent model parameters."""

    model: str | None = None
    tools: list[str] | None = None
    max_retries: int = 10  # max retries for each LLM call
    max_rounds: int = 10  # max round for task
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    inference_timeout: float | None = 180  # seconds
    stream: bool = True  # whether to stream the response


@dataclass
class TaskInput:
    """Represents a task to be processed by the MassGen system."""

    question: str
    context: dict[str, Any] = field(default_factory=dict)  # may support more information in the future, like images
    task_id: str | None = None


@dataclass
class SystemState:
    """Overall state of the MassGen orchestrator.
    Simplified phases:
    - collaboration: agents are working together to solve the task
    - completed: the representative agent has presented the solution and the task is completed
    """

    task: TaskInput | None = None
    phase: str = "collaboration"  # "collaboration", "debate", "completed"
    start_time: float | None = None
    end_time: float | None = None
    consensus_reached: bool = False
    representative_agent_id: int | None = None


@dataclass
class AgentState:
    """Represents the current state of an agent in the MassGen system."""

    agent_id: int
    status: str = "working"  # "working", "voted", "failed"
    curr_answer: str = ""  # the latest answer of the agent's work
    updated_answers: list[AnswerRecord] = field(default_factory=list)  # a list of answer records
    curr_vote: VoteRecord | None = None  # Which agent's solution this agent voted for
    cast_votes: list[VoteRecord] = field(default_factory=list)  # a list of vote records
    seen_updates_timestamps: dict[int, float] = field(default_factory=dict)  # agent_id -> last_seen_timestamp
    chat_history: list[dict[str, Any]] = field(default_factory=list)  # a list of conversation records
    chat_round: int = 0  # the number of chat rounds the agent has participated in
    execution_start_time: float | None = None
    execution_end_time: float | None = None

    @property
    def execution_time(self) -> float | None:
        """Calculate execution time if both start and end times are available."""
        if self.execution_start_time and self.execution_end_time:
            return self.execution_end_time - self.execution_start_time
        return None

    def add_update(self, answer: str, timestamp: float | None = None):
        """Add an update to the agent's history."""
        if timestamp is None:
            timestamp = time.time()

        record = AnswerRecord(
            timestamp=timestamp,
            answer=answer,
            status=self.status,
        )
        self.updated_answers.append(record)
        self.curr_answer = answer

    def mark_updates_seen(self, agent_updates: dict[int, float]):
        """Mark updates from other agents as seen."""
        for agent_id, timestamp in agent_updates.items():
            if agent_id != self.agent_id:  # Don't track own updates
                self.seen_updates_timestamps[agent_id] = timestamp

    def has_unseen_updates(self, other_agent_updates: dict[int, float]) -> bool:
        """Check if there are unseen updates from other agents."""
        for agent_id, timestamp in other_agent_updates.items():
            if agent_id != self.agent_id:  # Don't check own updates
                last_seen = self.seen_updates_timestamps.get(agent_id, 0)
                if timestamp > last_seen:
                    return True
        return False


@dataclass
class AgentResponse:
    """Response from an agent's process_message function."""

    text: str
    code: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    function_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LogEntry:
    """Represents a single log entry in the MassGen system."""

    timestamp: float
    event_type: str  # e.g., "agent_answer_update", "voting", "phase_change", etc.
    agent_id: int | None
    phase: str
    data: dict[str, Any]
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class StreamingDisplayConfig:
    """Configuration for streaming display system."""

    display_enabled: bool = True
    max_lines: int = 10
    save_logs: bool = True
    stream_callback: Any | None = None  # Callable, but avoid circular imports


@dataclass
class LoggingConfig:
    """Configuration for logging system."""

    log_dir: str = "logs"
    session_id: str | None = None
    non_blocking: bool = False


@dataclass
class OrchestratorConfig:
    """Configuration for MassGen orchestrator."""

    max_duration: int = 600
    consensus_threshold: float = 0.0
    max_debate_rounds: int = 1
    status_check_interval: float = 2.0
    thread_pool_timeout: int = 5


@dataclass
class AgentConfig:
    """Complete configuration for a single agent."""

    agent_id: int
    agent_type: str  # "openai", "gemini", "grok"
    model_config: ModelConfig

    def __post_init__(self):
        """Validate agent configuration."""
        if self.agent_type not in ["openai", "gemini", "grok"]:
            raise ValueError(f"Invalid agent_type: {self.agent_type}. Must be one of: openai, gemini, grok")


@dataclass
class MassConfig:
    """Complete MassGen system configuration."""

    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    agents: list[AgentConfig] = field(default_factory=list)
    streaming_display: StreamingDisplayConfig = field(default_factory=StreamingDisplayConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    task: dict[str, Any] | None = None  # Task-specific configuration

    def validate(self) -> bool:
        """Validate the complete configuration."""
        if not self.agents:
            raise ValueError("At least one agent must be configured")

        # Check for duplicate agent IDs
        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Agent IDs must be unique")

        # Validate consensus threshold
        if not 0.0 <= self.orchestrator.consensus_threshold <= 1.0:
            raise ValueError("Consensus threshold must be between 0.0 and 1.0")

        return True
