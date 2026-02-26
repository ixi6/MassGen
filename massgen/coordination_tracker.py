"""
Coordination Tracker for MassGen Orchestrator

This module provides comprehensive tracking of agent coordination events,
state transitions, and context sharing. It's integrated into the orchestrator
to capture the complete coordination flow for visualization and analysis.

The new approach is principled: we simply record what happens as it happens,
without trying to infer or manage state transitions. The orchestrator tells
us exactly what occurred and when.
"""

import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .logger_config import logger
from .structured_logging import (
    log_agent_answer,
    log_agent_restart,
    log_agent_vote,
    log_final_answer,
    log_winner_selected,
    trace_coordination_session,
)
from .utils import ActionType, AgentStatus


class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    ITERATION_START = "iteration_start"
    ITERATION_END = "iteration_end"
    STATUS_CHANGE = "status_change"
    CONTEXT_RECEIVED = "context_received"
    RESTART_TRIGGERED = "restart_triggered"
    RESTART_COMPLETED = "restart_completed"
    NEW_ANSWER = "new_answer"
    VOTE_CAST = "vote_cast"
    FINAL_AGENT_SELECTED = "final_agent_selected"
    FINAL_ANSWER = "final_answer"
    FINAL_ROUND_START = "final_round_start"

    AGENT_ERROR = "agent_error"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_CANCELLED = "agent_cancelled"
    UPDATE_INJECTED = "update_injected"
    VOTE_IGNORED = "vote_ignored"
    AGENT_STOPPED = "agent_stopped"  # Agent stopped in decomposition mode

    # Broadcast/communication events
    BROADCAST_CREATED = "broadcast_created"
    BROADCAST_RESPONSE = "broadcast_response"
    BROADCAST_COMPLETE = "broadcast_complete"
    BROADCAST_TIMEOUT = "broadcast_timeout"
    HUMAN_BROADCAST_RESPONSE = "human_broadcast_response"


ACTION_TO_EVENT = {
    ActionType.ERROR: EventType.AGENT_ERROR,
    ActionType.TIMEOUT: EventType.AGENT_TIMEOUT,
    ActionType.CANCELLED: EventType.AGENT_CANCELLED,
    ActionType.UPDATE_INJECTED: EventType.UPDATE_INJECTED,
    ActionType.VOTE_IGNORED: EventType.VOTE_IGNORED,
    ActionType.STOP: EventType.AGENT_STOPPED,
}


@dataclass
class CoordinationEvent:
    """A single coordination event with timestamp."""

    timestamp: float
    event_type: EventType
    agent_id: str | None = None
    details: str = ""
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "details": self.details,
            "context": self.context,
        }


@dataclass
class AgentAnswer:
    """Represents an answer from an agent."""

    agent_id: str
    content: str
    timestamp: float
    changedoc: str | None = None  # Content from changedoc.md decision journal

    @property
    def label(self) -> str:
        """Auto-generate label based on answer properties."""
        # This will be set by the tracker when it knows agent order
        return getattr(self, "_label", "unknown")

    @label.setter
    def label(self, value: str):
        self._label = value


@dataclass
class AgentVote:
    """Represents a vote from an agent."""

    voter_id: str
    voted_for: str  # Real agent ID like "gpt5nano_1"
    voted_for_label: str  # Answer label like "agent1.1"
    voter_anon_id: str  # Anonymous voter ID like "agent1"
    reason: str
    timestamp: float
    available_answers: list[str]  # Available answer labels like ["agent1.1", "agent2.1"]


class CoordinationTracker:
    """
    Principled coordination tracking that simply records what happens.

    The orchestrator tells us exactly what occurred and when, without
    us having to infer or manage complex state transitions.
    """

    def __init__(self):
        # Event log - chronological record of everything that happens
        self.events: list[CoordinationEvent] = []

        # Answer tracking
        self.answers_by_agent: dict[
            str,
            list[AgentAnswer],
        ] = {}  # agent_id -> list of regular answers
        self.final_answers: dict[str, AgentAnswer] = {}  # agent_id -> final answer

        # Vote tracking
        self.votes: list[AgentVote] = []

        # Coordination iteration tracking
        self.current_iteration: int = 0
        self.agent_rounds: dict[
            str,
            int,
        ] = {}  # Per-agent round tracking - increments when restart completed
        self.agent_round_context: dict[
            str,
            dict[int, list[str]],
        ] = {}  # What context each agent had in each round
        self.iteration_available_labels: list[str] = []  # Frozen snapshot of available answer labels for current iteration

        # Restart tracking - track pending restarts per agent
        self.pending_agent_restarts: dict[
            str,
            bool,
        ] = {}  # agent_id -> is restart pending

        # Session info
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.agent_ids: list[str] = []
        self.final_winner: str | None = None
        self.final_context: dict[str, Any] | None = None  # Context provided to final agent
        self.is_final_round: bool = False  # Track if we're in the final presentation round
        self.user_prompt: str | None = None  # Store the initial user prompt
        self.log_path: str | None = None  # MAS-199: Path to log directory for hybrid access

        # Agent mappings - coordination tracker is the single source of truth
        self.agent_context_labels: dict[
            str,
            list[str],
        ] = {}  # Track what labels each agent can see

        # Snapshot mapping - tracks filesystem snapshots for answers/votes
        self.snapshot_mappings: dict[
            str,
            dict[str, Any],
        ] = {}  # label/vote_id -> snapshot info

        # Logfire tracing - context manager for session span
        self._session_span_context = None

        # Enforcement observability - track workflow enforcement events per agent
        self.enforcement_events: dict[str, list[dict[str, Any]]] = {}

    def _make_snapshot_path(self, kind: str, agent_id: str, timestamp: str) -> str:
        """Generate standardized snapshot paths.

        Args:
            kind: Type of snapshot ('answer', 'vote', 'final_answer', etc.)
            agent_id: The agent ID
            timestamp: The timestamp or 'final' for final answers

        Returns:
            The formatted path string
        """
        if kind == "final_answer" and timestamp == "final":
            return f"final/{agent_id}/answer.txt"
        if kind == "answer":
            return f"{agent_id}/{timestamp}/answer.txt"
        if kind == "vote":
            return f"{agent_id}/{timestamp}/vote.json"
        return f"{agent_id}/{timestamp}/{kind}.txt"

    def initialize_session(
        self,
        agent_ids: list[str],
        user_prompt: str | None = None,
        # New workflow analysis fields (MAS-199)
        log_path: str | None = None,
    ):
        """Initialize a new coordination session."""
        self.start_time = time.time()
        self.agent_ids = agent_ids.copy()
        self.answers_by_agent = {aid: [] for aid in agent_ids}
        self.user_prompt = user_prompt
        self.log_path = log_path  # Store for later use (MAS-199)

        # Initialize per-agent round tracking
        self.agent_rounds = {aid: 0 for aid in agent_ids}
        self.agent_round_context = {aid: {0: []} for aid in agent_ids}  # Each agent starts in round 0 with empty context
        self.pending_agent_restarts = {aid: False for aid in agent_ids}

        # Initialize agent context tracking
        self.agent_context_labels = {aid: [] for aid in agent_ids}

        # Initialize enforcement tracking per agent
        self.enforcement_events = {aid: [] for aid in agent_ids}

        self._add_event(
            EventType.SESSION_START,
            None,
            f"Started with agents: {agent_ids}",
        )

        # Start Logfire session span for hierarchical tracing (MAS-199: includes log_path)
        self._session_span_context = trace_coordination_session(
            task=user_prompt or "",
            num_agents=len(agent_ids),
            agent_ids=agent_ids,
            log_path=log_path,
        )
        try:
            self._session_span_context.__enter__()
        except Exception:
            # Gracefully handle if Logfire is not enabled
            self._session_span_context = None

    # Agent ID utility methods
    def get_anonymous_id(self, agent_id: str) -> str:
        """Get anonymous ID (agent1, agent2) for a full agent ID."""
        agent_num = self._get_agent_number(agent_id)
        return f"agent{agent_num}" if agent_num else agent_id

    def _get_agent_number(self, agent_id: str) -> int | None:
        """Get the 1-based number for an agent (1, 2, 3, etc.)."""
        if agent_id in self.agent_ids:
            return self.agent_ids.index(agent_id) + 1
        return None

    def get_anonymous_agent_mapping(self) -> dict[str, str]:
        """
        Get consistent anonymous agent ID mapping (anon → real).

        Uses global agent numbering based on sorted agent IDs.
        This ensures consistency between injections, vote tool, vote validation,
        vote results display, and snapshots.

        Returns:
            Dict mapping anonymous IDs to real IDs, e.g.:
            {"agent1": "agent_a", "agent2": "agent_b", "agent3": "agent_c"}
        """
        sorted_ids = sorted(self.agent_ids)
        return {f"agent{i}": real_id for i, real_id in enumerate(sorted_ids, 1)}

    def get_reverse_agent_mapping(self) -> dict[str, str]:
        """
        Get reverse mapping from real agent ID to anonymous ID.

        Returns:
            Dict mapping real IDs to anonymous IDs, e.g.:
            {"agent_a": "agent1", "agent_b": "agent2", "agent_c": "agent3"}
        """
        sorted_ids = sorted(self.agent_ids)
        return {real_id: f"agent{i}" for i, real_id in enumerate(sorted_ids, 1)}

    def get_answer_label_mapping(self) -> dict[str, str]:
        """Get mapping from real agent ID to their latest versioned answer label.

        Returns:
            Dict mapping real IDs to versioned labels, e.g.:
            {"agent_a": "agent1.2", "agent_b": "agent2.1"}

        Only includes agents that have at least one answer.
        """
        mapping = {}
        for agent_id in self.agent_ids:
            label = self.get_latest_answer_label(agent_id)
            if label:
                mapping[agent_id] = label
        return mapping

    def get_agents_with_answers_anon(self, answers: dict[str, Any]) -> list[str]:
        """
        Get list of anonymous IDs for agents that have answers.

        Uses global numbering, filtered to only agents with answers.

        Args:
            answers: Dict of agent_id -> answer content

        Returns:
            List of anonymous IDs like ["agent1", "agent3"] for agents with answers
        """
        sorted_ids = sorted(self.agent_ids)
        return [f"agent{i}" for i, aid in enumerate(sorted_ids, 1) if aid in answers]

    def get_agent_context_labels(self, agent_id: str) -> list[str]:
        """Get the answer labels this agent can currently see."""
        return self.agent_context_labels.get(agent_id, []).copy()

    def get_latest_answer_label(self, agent_id: str) -> str | None:
        """Get the latest answer label for an agent."""
        if agent_id in self.answers_by_agent and self.answers_by_agent[agent_id]:
            return self.answers_by_agent[agent_id][-1].label
        return None

    def get_voted_for_label(
        self,
        voter_id: str,
        voted_for_agent_id: str,
    ) -> str | None:
        """Get the answer label that a voter was shown for a specific agent.

        This looks up what label the voter saw in their context when they were
        shown answers, avoiding race conditions in parallel execution where
        agents may submit new answers while others are voting.

        Args:
            voter_id: The agent ID who is voting
            voted_for_agent_id: The agent ID being voted for

        Returns:
            The answer label (e.g., "agent1.1") that the voter saw for the
            voted-for agent, or None if not found.
        """
        # Get what this voter was shown
        voter_context = self.agent_context_labels.get(voter_id, [])

        # Get the agent number for the voted-for agent (e.g., "agent_a" -> 1)
        agent_num = self._get_agent_number(voted_for_agent_id)
        if agent_num is None:
            return None

        # Look for a label matching the voted-for agent in the voter's context
        # Labels are like "agent1.1", "agent2.1", etc.
        prefix = f"agent{agent_num}."
        for label in voter_context:
            if label.startswith(prefix):
                return label
        return None

    def get_agent_round(self, agent_id: str) -> int:
        """Get the current round for a specific agent."""
        return self.agent_rounds.get(agent_id, 0)

    def set_agent_round(self, agent_id: str, round_num: int) -> None:
        """Set the round counter for an agent directly.

        Used by round resume to fast-forward agents to the target round
        without replaying the full event-driven round loop.
        """
        self.agent_rounds[agent_id] = round_num

    @property
    def max_round(self) -> int:
        """Get the highest round number across all agents."""
        return max(self.agent_rounds.values()) if self.agent_rounds else 0

    def start_new_iteration(self):
        """Start a new coordination iteration."""
        self.current_iteration += 1

        # Capture available answer labels at start of this iteration (freeze snapshot)
        self.iteration_available_labels = []
        for agent_id, answers_list in self.answers_by_agent.items():
            if answers_list:  # Agent has provided at least one answer
                latest_answer = answers_list[-1]  # Get most recent answer
                self.iteration_available_labels.append(
                    latest_answer.label,
                )  # e.g., "agent1.1"

        self._add_event(
            EventType.ITERATION_START,
            None,
            f"Starting coordination iteration {self.current_iteration}",
            {
                "iteration": self.current_iteration,
                "available_answers": self.iteration_available_labels.copy(),
            },
        )
        # Note: We don't create Logfire spans for every iteration - only meaningful
        # events (answers, votes, winner selection) are logged to avoid noise

    def _close_session_span(self):
        """Close the session span if one exists."""
        if self._session_span_context is not None:
            try:
                self._session_span_context.__exit__(None, None, None)
            except Exception:
                pass
            self._session_span_context = None

    def end_iteration(self, reason: str, details: dict[str, Any] | None = None):
        """Record how an iteration ended."""
        context = {
            "iteration": self.current_iteration,
            "end_reason": reason,
            "available_answers": self.iteration_available_labels.copy(),
        }
        if details:
            context.update(details)

        self._add_event(
            EventType.ITERATION_END,
            None,
            f"Iteration {self.current_iteration} ended: {reason}",
            context,
        )
        # Note: We don't log every iteration end to Logfire - only meaningful
        # events are logged (answers, votes, winner selection)

    def set_user_prompt(self, prompt: str):
        """Set or update the user prompt."""
        self.user_prompt = prompt

    def change_status(self, agent_id: str, new_status: AgentStatus):
        """Record when an agent changes status."""
        self._add_event(
            EventType.STATUS_CHANGE,
            agent_id,
            f"Changed to status: {new_status.value}",
        )

    def track_agent_context(
        self,
        agent_id: str,
        answers: dict[str, str],
        conversation_history: dict[str, Any] | None = None,
        agent_full_context: str | None = None,
        snapshot_dir: str | None = None,
    ):
        """Record when an agent receives context.

        Args:
            agent_id: The agent receiving context
            answers: Dict of agent_id -> answer content
            conversation_history: Optional conversation history
            agent_full_context: Optional full context string/dict to save
            snapshot_dir: Optional directory path to save context.txt
        """
        # Convert full agent IDs to their corresponding answer labels using canonical mappings
        answer_labels = []
        for answering_agent_id in answers.keys():
            if answering_agent_id in self.answers_by_agent and self.answers_by_agent[answering_agent_id]:
                # Get the most recent answer's label
                latest_answer = self.answers_by_agent[answering_agent_id][-1]
                answer_labels.append(latest_answer.label)

        # Update this agent's context labels using canonical mapping
        self.agent_context_labels[agent_id] = answer_labels.copy()

        # Use anonymous agent IDs for the event context
        anon_answering_agents = [self.get_anonymous_id(aid) for aid in answers.keys()]

        context = {
            "available_answers": anon_answering_agents,  # Anonymous IDs for backward compat
            "available_answer_labels": answer_labels.copy(),  # Store actual labels in event
            "answer_count": len(answers),
            "has_conversation_history": bool(conversation_history),
        }
        self._add_event(
            EventType.CONTEXT_RECEIVED,
            agent_id,
            f"Received context with {len(answers)} answers",
            context,
        )

    def update_agent_context_with_new_answers(
        self,
        agent_id: str,
        new_answer_agent_ids: list[str],
    ):
        """Update an agent's context labels when they receive injected updates.

        This is called when an agent receives new answers via update injection
        (preempt-not-restart), ensuring their context_labels accurately reflects
        what they've seen for vote label resolution.

        Args:
            agent_id: The agent receiving the update
            new_answer_agent_ids: List of agent IDs whose answers are being injected
        """
        # Get current context labels for this agent
        current_labels = self.agent_context_labels.get(agent_id, [])

        # Add labels for the new answers
        for answering_agent_id in new_answer_agent_ids:
            if answering_agent_id in self.answers_by_agent and self.answers_by_agent[answering_agent_id]:
                # Get the most recent answer's label
                latest_answer = self.answers_by_agent[answering_agent_id][-1]
                if latest_answer.label not in current_labels:
                    current_labels.append(latest_answer.label)

        # Update the agent's context labels
        self.agent_context_labels[agent_id] = current_labels

    def track_restart_signal(self, triggering_agent: str, agents_restarted: list[str]):
        """Record when a restart is triggered - but don't increment rounds yet."""
        # Mark affected agents as having pending restarts
        for agent_id in agents_restarted:
            if True:  # agent_id != triggering_agent:  # Triggering agent doesn't restart themselves
                self.pending_agent_restarts[agent_id] = True

        # Log restart event (no round increment yet)
        context = {
            "affected_agents": agents_restarted,
            "triggering_agent": triggering_agent,
        }
        self._add_event(
            EventType.RESTART_TRIGGERED,
            triggering_agent,
            f"Triggered restart affecting {len(agents_restarted)} agents",
            context,
        )

        # Log to Logfire for observability
        for agent_id in agents_restarted:
            restart_count = self.agent_rounds.get(agent_id, 0) + 1
            log_agent_restart(
                agent_id=agent_id,
                reason="new_answer_available",
                triggering_agent=triggering_agent,
                restart_count=restart_count,
                affected_agents=agents_restarted,
            )

    def complete_agent_restart(self, agent_id: str):
        """Record when an agent has completed its restart and increment their round.

        Args:
            agent_id: The agent that completed restart
        """
        if not self.pending_agent_restarts.get(agent_id, False):
            # This agent wasn't pending a restart, nothing to do
            return

        # Mark restart as completed
        self.pending_agent_restarts[agent_id] = False

        # Increment this agent's round
        self.agent_rounds[agent_id] += 1
        new_round = self.agent_rounds[agent_id]

        # Store the context this agent will work with in their new round
        if agent_id not in self.agent_round_context:
            self.agent_round_context[agent_id] = {}

        # Log restart completion
        context = {
            "agent_round": new_round,
        }
        self._add_event(
            EventType.RESTART_COMPLETED,
            agent_id,
            f"Completed restart - now in round {new_round}",
            context,
        )

    def add_agent_answer(
        self,
        agent_id: str,
        answer: str,
        snapshot_timestamp: str | None = None,
    ):
        """Record when an agent provides a new answer.

        Args:
            agent_id: ID of the agent
            answer: The answer content
            snapshot_timestamp: Timestamp of the filesystem snapshot (if any)
        """
        # Create answer object
        agent_answer = AgentAnswer(
            agent_id=agent_id,
            content=answer,
            timestamp=time.time(),
        )

        # Auto-generate label based on agent position and answer count
        agent_num = self._get_agent_number(agent_id)
        answer_num = len(self.answers_by_agent[agent_id]) + 1
        label = f"agent{agent_num}.{answer_num}"
        agent_answer.label = label

        # Store the answer
        self.answers_by_agent[agent_id].append(agent_answer)

        # Track snapshot mapping if provided
        if snapshot_timestamp:
            self.snapshot_mappings[label] = {
                "type": "answer",
                "label": label,
                "agent_id": agent_id,
                "timestamp": snapshot_timestamp,
                "iteration": self.current_iteration,
                "round": self.get_agent_round(agent_id),
                "path": self._make_snapshot_path(
                    "answer",
                    agent_id,
                    snapshot_timestamp,
                ),
            }

        # Record event with label (important info) but no preview (that's for display only)
        context = {"label": label}
        self._add_event(
            EventType.NEW_ANSWER,
            agent_id,
            f"Provided answer {label}",
            context,
        )

        # Log to Logfire for structured tracing (MAS-199: add answer_path for hybrid access)
        # Build answer path from log_path and snapshot path if available
        answer_path = None
        if self.log_path and snapshot_timestamp:
            relative_path = self._make_snapshot_path("answer", agent_id, snapshot_timestamp)
            answer_path = f"{self.log_path}/{relative_path}"
        log_agent_answer(
            agent_id=agent_id,
            answer_label=label,
            iteration=self.current_iteration,
            round_number=self.get_agent_round(agent_id),
            answer_preview=answer[:200] if answer else None,
            answer_path=answer_path,
        )

    def add_agent_vote(
        self,
        agent_id: str,
        vote_data: dict[str, Any],
        snapshot_timestamp: str | None = None,
    ):
        """Record when an agent votes.

        Args:
            agent_id: ID of the voting agent
            vote_data: Dictionary with vote information
            snapshot_timestamp: Timestamp of the filesystem snapshot (if any)
        """
        # Handle both "voted_for" and "agent_id" keys (orchestrator uses "agent_id")
        voted_for = vote_data.get("voted_for") or vote_data.get("agent_id", "unknown")
        reason = vote_data.get("reason", "")

        # Convert real agent IDs to anonymous IDs and answer labels
        voter_anon_id = self.get_anonymous_id(agent_id)

        # Find the voted-for answer label (agent1.1, agent2.1, etc.)
        # Use the voter's context to find what label they actually saw
        voted_for_label = "unknown"
        if voted_for not in self.agent_ids:
            logger.warning(f"Vote from {agent_id} for unknown agent {voted_for}")

        if voted_for in self.agent_ids:
            # Find the label from the voter's context (what they were shown)
            context_label = self.get_voted_for_label(agent_id, voted_for)
            if context_label:
                voted_for_label = context_label
            else:
                # Fallback to latest if not in context (shouldn't happen normally)
                voted_agent_answers = self.answers_by_agent.get(voted_for, [])
                if voted_agent_answers:
                    voted_for_label = voted_agent_answers[-1].label
                    logger.warning(
                        f"Vote from {agent_id} for {voted_for}: label not in voter context, " f"using latest {voted_for_label}",
                    )

        # Store the vote
        vote = AgentVote(
            voter_id=agent_id,
            voted_for=voted_for,
            voted_for_label=voted_for_label,
            voter_anon_id=voter_anon_id,
            reason=reason,
            timestamp=time.time(),
            available_answers=self.iteration_available_labels.copy(),
        )
        self.votes.append(vote)

        # Track snapshot mapping if provided
        if snapshot_timestamp:
            # Create a meaningful vote label similar to answer labels
            agent_num = self._get_agent_number(agent_id) or 0
            vote_num = len([v for v in self.votes if v.voter_id == agent_id])
            vote_label = f"agent{agent_num}.vote{vote_num}"

            self.snapshot_mappings[vote_label] = {
                "type": "vote",
                "label": vote_label,
                "agent_id": agent_id,
                "timestamp": snapshot_timestamp,
                "voted_for": voted_for,
                "voted_for_label": voted_for_label,
                "iteration": self.current_iteration,
                "round": self.get_agent_round(agent_id),
                "path": self._make_snapshot_path("vote", agent_id, snapshot_timestamp),
            }

        # Record event - only essential info in context
        context = {
            "voted_for": voted_for,  # Real agent ID for compatibility
            "voted_for_label": voted_for_label,  # Answer label for display
            "reason": reason,
            "available_answers": self.iteration_available_labels.copy(),
        }
        self._add_event(
            EventType.VOTE_CAST,
            agent_id,
            f"Voted for {voted_for_label}",
            context,
        )

        # Log to Logfire for structured tracing (MAS-199: add vote context for workflow analysis)
        # Count agents who have submitted at least one answer
        agents_with_answers = sum(1 for aid in self.agent_ids if self.answers_by_agent.get(aid))
        # Build mapping of answer labels to agent IDs for the available answers
        answer_label_mapping = {}
        for label in self.iteration_available_labels:
            # Find which agent owns this label
            for aid, answers_list in self.answers_by_agent.items():
                for ans in answers_list:
                    if ans.label == label:
                        answer_label_mapping[label] = aid
                        break
        log_agent_vote(
            agent_id=agent_id,
            voted_for_label=voted_for_label,
            iteration=self.current_iteration,
            round_number=self.get_agent_round(agent_id),
            reason=reason,
            available_answers=self.iteration_available_labels.copy(),
            agents_with_answers=agents_with_answers,
            answer_label_mapping=answer_label_mapping,
        )

    def add_agent_stop(
        self,
        agent_id: str,
        stop_data: dict[str, Any],
    ):
        """Record when an agent stops in decomposition mode.

        This is a thin wrapper that records a stop event for logging/tracing.
        The core state management (has_voted = True) happens in the orchestrator.

        Args:
            agent_id: ID of the stopping agent
            stop_data: Dictionary with stop information (summary, status)
        """
        summary = stop_data.get("summary", "")
        status = stop_data.get("status", "complete")

        context = {
            "summary": summary,
            "status": status,
        }
        self._add_event(
            EventType.AGENT_STOPPED,
            agent_id,
            f"Stopped ({status}): {summary[:100]}",
            context,
        )

    def set_final_agent(
        self,
        agent_id: str,
        vote_summary: str,
        all_answers: dict[str, str],
    ):
        """Record when final agent is selected."""
        self.final_winner = agent_id

        # Convert agent IDs to their answer labels
        answer_labels = []
        answers_with_labels = {}
        for aid, answer_content in all_answers.items():
            if aid in self.answers_by_agent and self.answers_by_agent[aid]:
                # Get the latest answer label for this agent from regular answers
                if self.answers_by_agent[aid]:
                    latest_answer = self.answers_by_agent[aid][-1]
                    answer_labels.append(latest_answer.label)
                    answers_with_labels[latest_answer.label] = answer_content

        self.final_context = {
            "vote_summary": vote_summary,
            "all_answers": answer_labels,  # Now contains labels like ["agent1.1", "agent2.1"]
            "answers_for_context": answers_with_labels,  # Now keyed by labels
        }
        self._add_event(
            EventType.FINAL_AGENT_SELECTED,
            agent_id,
            "Selected as final presenter",
            self.final_context,
        )

        # Log to Logfire for structured tracing
        # Get the winning agent's latest answer label
        winner_label = "unknown"
        if agent_id in self.answers_by_agent and self.answers_by_agent[agent_id]:
            winner_label = self.answers_by_agent[agent_id][-1].label

        # Calculate vote counts from stored votes
        vote_counts = {}
        for vote in self.votes:
            label = vote.voted_for_label
            vote_counts[label] = vote_counts.get(label, 0) + 1

        log_winner_selected(
            winner_agent_id=agent_id,
            winner_label=winner_label,
            vote_counts=vote_counts,
            total_iterations=self.current_iteration,
        )

    def set_final_answer(
        self,
        agent_id: str,
        final_answer: str,
        snapshot_timestamp: str | None = None,
    ):
        """Record the final answer presentation.

        Args:
            agent_id: ID of the agent
            final_answer: The final answer content
            snapshot_timestamp: Timestamp of the filesystem snapshot (if any)
        """
        # Create final answer object
        final_answer_obj = AgentAnswer(
            agent_id=agent_id,
            content=final_answer,
            timestamp=time.time(),
        )

        # Auto-generate final label
        agent_num = self._get_agent_number(agent_id)
        label = f"agent{agent_num}.final"
        final_answer_obj.label = label

        # Store the final answer separately
        self.final_answers[agent_id] = final_answer_obj

        # Track snapshot mapping if provided
        if snapshot_timestamp:
            self.snapshot_mappings[label] = {
                "type": "final_answer",
                "label": label,
                "agent_id": agent_id,
                "timestamp": snapshot_timestamp,
                "iteration": self.current_iteration,
                "round": self.get_agent_round(agent_id),
                "path": self._make_snapshot_path(
                    "final_answer",
                    agent_id,
                    snapshot_timestamp,
                ),
            }

        # Record event with label only (no preview)
        context = {"label": label, **(self.final_context or {})}
        self._add_event(
            EventType.FINAL_ANSWER,
            agent_id,
            f"Presented final answer {label}",
            context,
        )

        # Log to Logfire for structured tracing
        log_final_answer(
            agent_id=agent_id,
            iteration=self.current_iteration,
            answer_preview=final_answer[:200] if final_answer else None,
        )

        # Close session span when final answer is provided
        self._close_session_span()

    def start_final_round(self, selected_agent_id: str):
        """Start the final presentation round."""
        self.is_final_round = True
        # Set the final round to be max round across all agents + 1
        final_round = self.max_round + 1
        self.agent_rounds[selected_agent_id] = final_round
        self.final_winner = selected_agent_id

        # Mark winner as starting final presentation
        self.change_status(selected_agent_id, AgentStatus.STREAMING)

        self._add_event(
            EventType.FINAL_ROUND_START,
            selected_agent_id,
            f"Starting final presentation round {final_round}",
            {"round_type": "final", "final_round": final_round},
        )

    def track_agent_action(self, agent_id: str, action_type, details: str = ""):
        """Track any agent action using ActionType enum."""
        if action_type == ActionType.NEW_ANSWER:
            # For answers, details should be the actual answer content
            self.add_agent_answer(agent_id, details)
        elif action_type == ActionType.VOTE:
            # For votes, details should be vote data dict - but this needs to be handled separately
            # since add_agent_vote expects a dict, not a string
            pass  # Use add_agent_vote directly
        else:
            event_type = ACTION_TO_EVENT.get(action_type)
            if event_type is None:
                raise ValueError(f"Unsupported ActionType: {action_type}")
            message = f"{action_type.value.upper()}: {details}" if details else action_type.value.upper()
            self._add_event(event_type, agent_id, message)

    def add_broadcast_created(self, request_id: str, sender_id: str, question: str):
        """Record when a broadcast is created.

        Args:
            request_id: ID of the broadcast request
            sender_id: ID of the agent sending the broadcast
            question: The question being broadcast
        """
        context = {
            "request_id": request_id,
            "question_preview": question[:100] + "..." if len(question) > 100 else question,
        }
        self._add_event(
            EventType.BROADCAST_CREATED,
            sender_id,
            f"Created broadcast: {question[:50]}...",
            context,
        )

    def add_broadcast_response(
        self,
        request_id: str,
        responder_id: str,
        is_human: bool = False,
    ):
        """Record when an agent or human responds to a broadcast.

        Args:
            request_id: ID of the broadcast request
            responder_id: ID of the responder (agent ID or "human")
            is_human: Whether this is a human response
        """
        context = {
            "request_id": request_id,
            "is_human": is_human,
        }
        event_type = EventType.HUMAN_BROADCAST_RESPONSE if is_human else EventType.BROADCAST_RESPONSE
        details = "Responded to broadcast" if not is_human else "Human responded to broadcast"
        self._add_event(
            event_type,
            responder_id if not is_human else None,
            details,
            context,
        )

    def add_broadcast_complete(self, request_id: str, status: str):
        """Record when a broadcast completes.

        Args:
            request_id: ID of the broadcast request
            status: Status of completion ("complete" or "timeout")
        """
        context = {"request_id": request_id, "completion_status": status}
        event_type = EventType.BROADCAST_TIMEOUT if status == "timeout" else EventType.BROADCAST_COMPLETE
        details = f"Broadcast {status}"
        self._add_event(event_type, None, details, context)

    def _add_event(
        self,
        event_type: EventType,
        agent_id: str | None,
        details: str,
        context: dict[str, Any] | None = None,
    ):
        """Internal method to add an event."""
        # Automatically include current iteration and round in context
        if context is None:
            context = {}
        context = context.copy()  # Don't modify the original
        context["iteration"] = self.current_iteration

        # Include agent-specific round if agent_id is provided, otherwise use max round
        if agent_id:
            context["round"] = self.get_agent_round(agent_id)
        else:
            context["round"] = self.max_round

        event = CoordinationEvent(
            timestamp=time.time(),
            event_type=event_type,
            agent_id=agent_id,
            details=details,
            context=context,
        )
        self.events.append(event)

    def _end_session(self):
        """Mark the end of the coordination session."""
        self.end_time = time.time()
        duration = self.end_time - (self.start_time or self.end_time)
        self._add_event(
            EventType.SESSION_END,
            None,
            f"Session completed in {duration:.1f}s",
        )
        # Ensure session span is closed
        self._close_session_span()

    @property
    def all_answers(self) -> dict[str, str]:
        """Get all answers as a label->content dictionary."""
        result = {}
        # Add regular answers
        for answers in self.answers_by_agent.values():
            for answer in answers:
                result[answer.label] = answer.content
        # Add final answers
        for answer in self.final_answers.values():
            result[answer.label] = answer.content
        return result

    def get_summary(self) -> dict[str, Any]:
        """Get session summary statistics."""
        duration = (self.end_time or time.time()) - (self.start_time or time.time())
        restart_count = len(
            [e for e in self.events if e.event_type == EventType.RESTART_TRIGGERED],
        )

        return {
            "duration": duration,
            "total_events": len(self.events),
            "total_restarts": restart_count,
            "total_answers": sum(len(answers) for answers in self.answers_by_agent.values()),
            "final_winner": self.final_winner,
            "agent_count": len(self.agent_ids),
        }

    def save_status_file(self, log_dir: Path, orchestrator=None):
        """Save current coordination status to status.json for real-time monitoring.

        This file is continuously updated during coordination to provide real-time
        status monitoring for automation tools and LLM agents.

        Args:
            log_dir: Directory to save the status file
            orchestrator: Optional orchestrator reference for accessing agent states
        """
        try:
            log_dir = Path(log_dir)
            status_file = log_dir / "status.json"

            # Calculate elapsed time
            elapsed = (time.time() - self.start_time) if self.start_time else 0

            # Determine current coordination phase
            phase = "initial_answer"
            if self.is_final_round:
                phase = "presentation"
            elif len(self.votes) > 0:
                phase = "enforcement"

            # Determine which agent is currently active (streaming)
            # An agent is active if it hasn't answered yet and others have, or if it's in voting phase without a vote
            active_agent = None
            if orchestrator and hasattr(orchestrator, "agent_states"):
                for agent_id in self.agent_ids:
                    agent_state = orchestrator.agent_states.get(agent_id)
                    if agent_state:
                        # Agent is active if it hasn't completed its current task
                        # Check if agent is waiting to answer or vote
                        answers = self.answers_by_agent.get(agent_id, [])
                        has_answer = len(answers) > 0

                        # In voting phase, active agent is one without a vote
                        if len(self.votes) > 0 and not agent_state.has_voted:
                            active_agent = agent_id
                            break
                        # In answer phase, active agent is one without an answer (if others have answered)
                        elif not has_answer and any(len(self.answers_by_agent.get(aid, [])) > 0 for aid in self.agent_ids if aid != agent_id):
                            active_agent = agent_id
                            break
                        # If no one has answered yet, first agent is active
                        elif not has_answer and not any(len(self.answers_by_agent.get(aid, [])) > 0 for aid in self.agent_ids):
                            active_agent = self.agent_ids[0]
                            break

            # Build agent status entries with per-agent details
            agent_statuses = {}
            for agent_id in self.agent_ids:
                answers = self.answers_by_agent.get(agent_id, [])
                latest_answer_label = answers[-1].label if answers else None

                # Find vote cast by this agent
                agent_vote = None
                for vote in self.votes:
                    if vote.voter_id == agent_id:
                        agent_vote = {
                            "voted_for_agent": vote.voted_for,
                            "voted_for_label": vote.voted_for_label,
                            "reason_preview": vote.reason[:100] if vote.reason else None,
                        }
                        break

                # Determine agent status from orchestrator if available
                status = "waiting"  # Default
                error = None
                if orchestrator and hasattr(orchestrator, "agent_states"):
                    agent_state = orchestrator.agent_states.get(agent_id)
                    if agent_state:
                        # Infer status from AgentState attributes
                        if agent_state.is_killed:
                            status = "error" if not agent_state.timeout_reason else "timeout"
                        elif agent_state.has_voted:
                            status = "voted"
                        elif agent_state.answer:
                            status = "answered"
                        elif agent_state.restart_pending:
                            status = "restarting"
                        else:
                            # Check if agent is currently streaming by looking at coordination phase
                            # If we have answers from other agents but not this one, it's likely streaming
                            if answers:
                                status = "streaming"
                            else:
                                status = "waiting"

                        # Check for error conditions
                        if agent_state.is_killed:
                            if agent_state.timeout_reason:
                                error = {
                                    "type": "timeout",
                                    "message": agent_state.timeout_reason,
                                    "timestamp": time.time(),
                                }
                            else:
                                error = {
                                    "type": "error",
                                    "message": "Agent was killed",
                                    "timestamp": time.time(),
                                }

                # Get last activity timestamp
                last_activity = self.start_time
                if answers:
                    last_activity = answers[-1].timestamp
                elif agent_vote and hasattr(self.votes[-1], "timestamp"):
                    for vote in self.votes:
                        if vote.voter_id == agent_id:
                            last_activity = vote.timestamp
                            break

                # Get workspace paths from filesystem_manager if available
                workspace_paths = None
                if orchestrator and hasattr(orchestrator, "agents"):
                    agent = orchestrator.agents.get(agent_id)
                    if agent and hasattr(agent, "backend") and agent.backend and hasattr(agent.backend, "filesystem_manager"):
                        fm = agent.backend.filesystem_manager
                        if fm:
                            workspace_paths = {
                                "workspace": str(fm.cwd) if fm.cwd else None,
                                "snapshot_storage": str(fm.snapshot_storage) if fm.snapshot_storage else None,
                                "temp_workspace": str(fm.agent_temporary_workspace) if fm.agent_temporary_workspace else None,
                            }

                # Get token usage from agent backend if available
                token_usage = None
                tool_metrics = None
                round_history = None
                if orchestrator and hasattr(orchestrator, "agents"):
                    agent = orchestrator.agents.get(agent_id)
                    if agent and hasattr(agent, "backend") and agent.backend:
                        backend = agent.backend
                        if hasattr(backend, "token_usage") and backend.token_usage:
                            tu = backend.token_usage
                            token_usage = {
                                "input_tokens": tu.input_tokens,
                                "output_tokens": tu.output_tokens,
                                "reasoning_tokens": tu.reasoning_tokens,
                                "cached_input_tokens": tu.cached_input_tokens,
                                "estimated_cost": round(tu.estimated_cost, 6),
                            }
                        # Get tool metrics if available
                        if hasattr(backend, "get_tool_metrics_summary"):
                            tool_metrics = backend.get_tool_metrics_summary()
                        # Get round token history if available
                        if hasattr(backend, "get_round_token_history"):
                            round_history = backend.get_round_token_history()

                # Get per-round timing info for debugging
                round_timing = None
                if orchestrator and hasattr(orchestrator, "agent_states"):
                    agent_state = orchestrator.agent_states.get(agent_id)
                    if agent_state and agent_state.round_start_time:
                        agent_round = self.agent_rounds.get(agent_id, 0)
                        round_timing = {
                            "round_number": agent_round,
                            "round_start_time": agent_state.round_start_time,
                        }

                # Get reliability metrics (enforcement tracking)
                reliability = self.get_agent_reliability(agent_id)

                agent_statuses[agent_id] = {
                    "status": status,
                    "answer_count": len(answers),
                    "latest_answer_label": latest_answer_label,
                    "vote_cast": agent_vote,
                    "times_restarted": self.agent_rounds.get(agent_id, 0),
                    "last_activity": last_activity,
                    "error": error,
                    "workspace_paths": workspace_paths,
                    "token_usage": token_usage,
                    "tool_metrics": tool_metrics,
                    "round_history": round_history,
                    "round_timing": round_timing,
                    "reliability": reliability,
                }

            # Aggregate vote counts by answer label
            vote_counts = {}
            for vote in self.votes:
                label = vote.voted_for_label
                vote_counts[label] = vote_counts.get(label, 0) + 1

            # Calculate completion percentage estimate
            # Each agent needs to: (1) provide answer, (2) cast vote
            total_steps = len(self.agent_ids) * 2
            completed_steps = sum(len(answers) for answers in self.answers_by_agent.values()) + len(self.votes)
            completion_pct = min(100, int((completed_steps / total_steps) * 100)) if total_steps > 0 else 0

            # Get final answer preview if available
            final_answer_preview = None
            if self.final_winner and self.final_winner in self.final_answers:
                final_content = self.final_answers[self.final_winner].content
                final_answer_preview = final_content[:200] if final_content else None

            # Get orchestrator-level paths for debugging
            orchestrator_paths = None
            if orchestrator:
                orchestrator_paths = {
                    "snapshot_storage": orchestrator._snapshot_storage if hasattr(orchestrator, "_snapshot_storage") else None,
                    "temp_workspace_parent": orchestrator._agent_temporary_workspace if hasattr(orchestrator, "_agent_temporary_workspace") else None,
                }

            # Calculate total costs across all agents
            total_cost = 0.0
            total_input_tokens = 0
            total_output_tokens = 0
            for agent_status in agent_statuses.values():
                if agent_status.get("token_usage"):
                    tu = agent_status["token_usage"]
                    total_cost += tu.get("estimated_cost", 0)
                    total_input_tokens += tu.get("input_tokens", 0)
                    total_output_tokens += tu.get("output_tokens", 0)

            # Aggregate tool metrics across all agents
            total_tool_calls = 0
            total_tool_failures = 0
            total_tool_time_ms = 0.0
            tools_by_name: dict[str, dict[str, Any]] = {}
            for agent_status in agent_statuses.values():
                tm = agent_status.get("tool_metrics")
                if tm:
                    total_tool_calls += tm.get("total_calls", 0)
                    total_tool_failures += tm.get("total_failures", 0)
                    total_tool_time_ms += tm.get("total_execution_time_ms", 0)
                    # Merge per-tool stats
                    for tool_name, tool_stats in tm.get("by_tool", {}).items():
                        if tool_name not in tools_by_name:
                            tools_by_name[tool_name] = {
                                "call_count": 0,
                                "success_count": 0,
                                "failure_count": 0,
                                "total_execution_time_ms": 0.0,
                                "total_input_chars": 0,
                                "total_output_chars": 0,
                                "tool_type": tool_stats.get("tool_type", "unknown"),
                            }
                        tools_by_name[tool_name]["call_count"] += tool_stats.get(
                            "call_count",
                            0,
                        )
                        tools_by_name[tool_name]["success_count"] += tool_stats.get(
                            "success_count",
                            0,
                        )
                        tools_by_name[tool_name]["failure_count"] += tool_stats.get(
                            "failure_count",
                            0,
                        )
                        tools_by_name[tool_name]["total_execution_time_ms"] += tool_stats.get("total_execution_time_ms", 0)
                        tools_by_name[tool_name]["total_input_chars"] += tool_stats.get(
                            "total_input_chars",
                            0,
                        )
                        tools_by_name[tool_name]["total_output_chars"] += tool_stats.get("total_output_chars", 0)

            # Calculate averages for aggregated tools
            for tool_stats in tools_by_name.values():
                count = tool_stats["call_count"]
                if count > 0:
                    tool_stats["avg_execution_time_ms"] = round(
                        tool_stats["total_execution_time_ms"] / count,
                        2,
                    )
                    tool_stats["input_tokens_est"] = tool_stats["total_input_chars"] // 4
                    tool_stats["output_tokens_est"] = tool_stats["total_output_chars"] // 4

            # Aggregate round token history across all agents
            all_rounds = []
            rounds_summary = {
                "total_rounds": 0,
                "by_outcome": {
                    "answer": 0,
                    "vote": 0,
                    "presentation": 0,
                    "post_evaluation": 0,
                    "restarted": 0,
                    "error": 0,
                    "timeout": 0,
                },
                "total_round_input_tokens": 0,
                "total_round_output_tokens": 0,
                "total_round_cost": 0.0,
            }
            for agent_status in agent_statuses.values():
                rh = agent_status.get("round_history")
                if rh:
                    all_rounds.extend(rh)
                    for r in rh:
                        rounds_summary["total_rounds"] += 1
                        outcome = r.get("outcome", "unknown")
                        if outcome in rounds_summary["by_outcome"]:
                            rounds_summary["by_outcome"][outcome] += 1
                        rounds_summary["total_round_input_tokens"] += r.get(
                            "input_tokens",
                            0,
                        )
                        rounds_summary["total_round_output_tokens"] += r.get(
                            "output_tokens",
                            0,
                        )
                        rounds_summary["total_round_cost"] += r.get(
                            "estimated_cost",
                            0.0,
                        )

            # Round the cost to 6 decimal places
            rounds_summary["total_round_cost"] = round(
                rounds_summary["total_round_cost"],
                6,
            )

            # Build historical workspaces from snapshot mappings
            historical_workspaces = []
            if self.snapshot_mappings:
                for label, mapping in self.snapshot_mappings.items():
                    if mapping.get("type") != "answer":
                        continue

                    agent_id = mapping.get("agent_id", "")
                    timestamp = mapping.get("timestamp", "")

                    # Build workspace path from mapping (step up from answer.txt to workspace dir)
                    mapping_path = mapping.get("path", "")
                    if mapping_path.endswith("/answer.txt"):
                        workspace_path = mapping_path[: -len("/answer.txt")] + "/workspace"
                    else:
                        # Fallback: agent/timestamp/workspace
                        workspace_path = f"{agent_id}/{timestamp}/workspace"

                    # Convert to absolute path - resolve log_dir to absolute path first
                    if log_dir:
                        absolute_log_dir = Path(log_dir).resolve()
                        absolute_workspace_path = str(absolute_log_dir / workspace_path)
                    else:
                        absolute_workspace_path = workspace_path

                    historical_workspaces.append(
                        {
                            "answerId": f"{agent_id}-{timestamp}",
                            "agentId": agent_id,
                            "answerNumber": mapping.get("round", 1),
                            "answerLabel": label,
                            "timestamp": timestamp,
                            "workspacePath": absolute_workspace_path,
                        },
                    )

            # Build complete status data structure
            # Determine finish reason - prioritize showing termination cause at top level
            finish_reason = None
            finish_reason_details = None
            is_complete = False

            if orchestrator:
                # Check for orchestrator timeout
                if hasattr(orchestrator, "is_orchestrator_timeout") and orchestrator.is_orchestrator_timeout:
                    finish_reason = "timeout"
                    finish_reason_details = orchestrator.timeout_reason if hasattr(orchestrator, "timeout_reason") else "Orchestrator time limit exceeded"
                    is_complete = True
                # Check if final presentation completed
                elif self.is_final_round and self.final_winner:
                    finish_reason = "completed"
                    finish_reason_details = f"Winner: {self.final_winner}"
                    is_complete = True
                # Check for any agent errors that stopped execution
                elif any(agent_statuses.get(aid, {}).get("error") is not None for aid in self.agent_ids):
                    error_agents = [aid for aid in self.agent_ids if agent_statuses.get(aid, {}).get("error") is not None]
                    finish_reason = "error"
                    finish_reason_details = f"Agent(s) encountered errors: {', '.join(error_agents)}"
                    is_complete = True
                # Still in progress
                else:
                    finish_reason = "in_progress"
                    finish_reason_details = f"Phase: {phase}"
                    is_complete = False

            status_data = {
                # IMPORTANT: finish_reason is placed first for visibility
                "finish_reason": finish_reason,
                "finish_reason_details": finish_reason_details,
                "is_complete": is_complete,
                "meta": {
                    "last_updated": time.time(),
                    "session_id": log_dir.name if log_dir else "",
                    "log_dir": str(log_dir) if log_dir else "",
                    "question": self.user_prompt,
                    "start_time": self.start_time,
                    "elapsed_seconds": round(elapsed, 3),
                    "orchestrator_paths": orchestrator_paths,
                },
                "costs": {
                    "total_estimated_cost": round(total_cost, 6),
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                },
                "tools": {
                    "total_calls": total_tool_calls,
                    "total_failures": total_tool_failures,
                    "total_execution_time_ms": round(total_tool_time_ms, 2),
                    "by_tool": tools_by_name,
                },
                "rounds": rounds_summary,
                "coordination": {
                    "phase": phase,
                    "active_agent": active_agent,
                    "completion_percentage": completion_pct,
                    "is_final_presentation": self.is_final_round,
                },
                "agents": agent_statuses,
                "historical_workspaces": historical_workspaces,
                "results": {
                    "votes": vote_counts,
                    "winner": self.final_winner,
                    "final_answer_preview": final_answer_preview,
                },
            }

            # Write atomically: write to temp file, then rename
            temp_file = status_file.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2, default=str)

            # Atomic rename
            if status_file:
                temp_file.replace(status_file)

        except Exception as e:
            logger.warning(f"Failed to save status file: {e}", exc_info=True)

    def save_coordination_logs(self, log_dir):
        """Save all coordination data and create timeline visualization.

        Args:
            log_dir: Directory to save logs
            format_style: "old", "new", or "both" (default)
        """
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            # Save raw events with session metadata
            events_file = log_dir / "coordination_events.json"
            with open(events_file, "w", encoding="utf-8") as f:
                events_data = [event.to_dict() for event in self.events]

                # Include session metadata at the beginning of the JSON
                session_data = {
                    "session_metadata": {
                        "user_prompt": self.user_prompt,
                        "agent_ids": self.agent_ids,
                        "start_time": self.start_time,
                        "end_time": self.end_time,
                        "final_winner": self.final_winner,
                    },
                    "events": events_data,
                }
                json.dump(session_data, f, indent=2, default=str)

            # Save snapshot mappings to track filesystem snapshots
            if self.snapshot_mappings:
                snapshot_mappings_file = log_dir / "snapshot_mappings.json"
                with open(snapshot_mappings_file, "w", encoding="utf-8") as f:
                    json.dump(self.snapshot_mappings, f, indent=2, default=str)

            # Generate coordination table using the new table generator
            try:
                self._generate_coordination_table(log_dir, session_data)
            except Exception as e:
                logger.warning(
                    f"Warning: Could not generate coordination table: {e}",
                    exc_info=True,
                )

        except Exception as e:
            logger.warning(f"Failed to save coordination logs: {e}", exc_info=True)

    def _generate_coordination_table(self, log_dir, session_data):
        """Generate coordination table using the create_coordination_table.py module."""
        try:
            # Import the table builder
            from massgen.frontend.displays.create_coordination_table import (
                CoordinationTableBuilder,
            )

            # Create the event-driven table directly from session data (includes metadata)
            builder = CoordinationTableBuilder(session_data)
            table_content = builder.generate_event_table()

            # Save the table to a file
            table_file = log_dir / "coordination_table.txt"
            with open(table_file, "w", encoding="utf-8") as f:
                f.write(table_content)

            logger.info(f"Coordination table generated at {table_file}")

        except Exception as e:
            logger.warning(f"Error generating coordination table: {e}", exc_info=True)

    def _get_agent_id_from_label(self, label: str) -> str:
        """Extract agent_id from a label like 'agent1.1' or 'agent2.final'."""
        import re

        match = re.match(r"agent(\d+)", label)
        if match:
            agent_num = int(match.group(1))
            if 0 < agent_num <= len(self.agent_ids):
                return self.agent_ids[agent_num - 1]
        return "unknown"

    def _get_agent_display_name(self, agent_id: str) -> str:
        """Get display name for agent (Agent1, Agent2, etc.)."""
        agent_num = self._get_agent_number(agent_id)
        return f"Agent{agent_num}" if agent_num else agent_id

    def track_enforcement_event(
        self,
        agent_id: str,
        reason: str,
        attempt: int,
        max_attempts: int,
        tool_calls: list[str] | None = None,
        error_message: str | None = None,
        buffer_preview: str | None = None,
        buffer_chars: int = 0,
        docker_health: dict[str, Any] | None = None,
    ) -> None:
        """Track a workflow enforcement event for an agent.

        This records when the orchestrator triggers enforcement due to missing
        or invalid workflow tool usage (vote/new_answer).

        Args:
            agent_id: The agent that triggered enforcement
            reason: Enforcement reason code (e.g., 'no_workflow_tool', 'invalid_vote_id')
            attempt: Current attempt number (1-indexed)
            max_attempts: Maximum allowed attempts
            tool_calls: List of tool names that were called
            error_message: Specific error message if applicable
            buffer_preview: First 500 chars of streaming buffer content
            buffer_chars: Total characters in buffer before clear
            docker_health: Docker container health info if applicable (for mcp_disconnected)
        """
        # Ensure agent is tracked
        if agent_id not in self.enforcement_events:
            self.enforcement_events[agent_id] = []

        # Get current round for this agent
        current_round = self.get_agent_round(agent_id)

        # Build the enforcement event record
        event = {
            "round": current_round,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "reason": reason,
            "tool_calls": tool_calls or [],
            "error_message": error_message,
            "buffer_preview": buffer_preview[:500] if buffer_preview else None,
            "buffer_chars": buffer_chars,
            "timestamp": time.time(),
        }

        # Add Docker health info for MCP-related failures
        if docker_health:
            event["docker_health"] = docker_health

        self.enforcement_events[agent_id].append(event)

        # Log the enforcement event for debugging
        logger.debug(
            f"[CoordinationTracker] Enforcement event for {agent_id}: " f"reason={reason}, attempt={attempt}/{max_attempts}, " f"tools={tool_calls}, buffer_chars={buffer_chars}",
        )

    def get_agent_reliability(self, agent_id: str) -> dict[str, Any]:
        """Get reliability metrics for an agent based on enforcement events.

        Returns a summary of enforcement attempts including:
        - List of enforcement events
        - Aggregated counts by round
        - Unknown tools encountered
        - Workflow errors encountered
        - Total retry count
        - Total buffer chars lost
        - Final outcome

        Args:
            agent_id: The agent to get reliability for

        Returns:
            Dictionary with reliability metrics
        """
        events = self.enforcement_events.get(agent_id, [])

        if not events:
            return None  # No enforcement events means perfect reliability

        # Aggregate by round
        by_round: dict[str, dict[str, Any]] = {}
        unknown_tools: list[str] = []
        workflow_errors: list[str] = []
        total_buffer_chars_lost = 0

        for event in events:
            round_num = str(event.get("round", 0))
            reason = event.get("reason", "unknown")

            # Initialize round entry if needed
            if round_num not in by_round:
                by_round[round_num] = {"count": 0, "reasons": []}

            by_round[round_num]["count"] += 1
            if reason not in by_round[round_num]["reasons"]:
                by_round[round_num]["reasons"].append(reason)

            # Track unknown tools
            if reason == "unknown_tool":
                for tool in event.get("tool_calls", []):
                    if tool not in unknown_tools:
                        unknown_tools.append(tool)

            # Track workflow errors (non-tool issues)
            if reason in ("vote_no_answers", "vote_and_answer", "invalid_vote_id", "answer_limit", "answer_novelty", "answer_duplicate"):
                if reason not in workflow_errors:
                    workflow_errors.append(reason)

            # Sum buffer chars lost
            total_buffer_chars_lost += event.get("buffer_chars", 0)

        return {
            "enforcement_attempts": events,
            "by_round": by_round,
            "unknown_tools": unknown_tools,
            "workflow_errors": workflow_errors,
            "total_enforcement_retries": len(events),
            "total_buffer_chars_lost": total_buffer_chars_lost,
            "outcome": "ok",  # Outcome determined by orchestrator - will be updated if agent fails
        }
