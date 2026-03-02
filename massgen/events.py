"""
Unified Event System for MassGen.

This module provides a structured event system that:
1. Supplements streaming_debug.log with a machine-readable events.jsonl format
2. Enables TUI reconstruction for subagent modals
3. Provides debugging capabilities with explicit event types

Event Schema:
- All events are JSON objects with timestamp, event_type, and event-specific data
- Events are appended atomically to events.jsonl
- Events can be read/streamed for live display or post-hoc analysis

See the ``EventType`` class for the full list of event types.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Type for event listeners
EventListener = Callable[["MassGenEvent"], None]


@dataclass
class MassGenEvent:
    """Structured event for TUI reconstruction and debugging.

    Attributes:
        timestamp: ISO format timestamp when event was created
        event_type: Type of event (tool_start, tool_complete, thinking, text, etc.)
        agent_id: Which agent emitted this event (None for orchestrator events)
        round_number: Current coordination round (0 for non-orchestrated)
        data: Event-specific payload
    """

    timestamp: str
    event_type: str
    agent_id: str | None = None
    round_number: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> MassGenEvent:
        """Deserialize event from JSON string."""
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def create(
        cls,
        event_type: str,
        agent_id: str | None = None,
        round_number: int = 0,
        **kwargs: Any,
    ) -> MassGenEvent:
        """Factory method to create an event with current timestamp.

        Args:
            event_type: Type of event
            agent_id: Agent ID that emitted this event
            round_number: Current round number
            **kwargs: Event-specific data fields

        Returns:
            New MassGenEvent instance
        """
        return cls(
            timestamp=datetime.now().isoformat(),
            event_type=event_type,
            agent_id=agent_id,
            round_number=round_number,
            data=kwargs,
        )


# Predefined event type constants
class EventType:
    """Event type constants for type safety and autocomplete."""

    # Tool events
    TOOL_START = "tool_start"
    TOOL_COMPLETE = "tool_complete"

    # Content events
    THINKING = "thinking"
    TEXT = "text"

    # Status events
    STATUS = "status"
    BACKEND_STATUS = "backend_status"

    # Coordination events
    ROUND_START = "round_start"
    ROUND_END = "round_end"
    FINAL_ANSWER = "final_answer"

    # Timeline transcript lines (debugging/parity checks)
    TIMELINE_ENTRY = "timeline_entry"

    # Orchestration events
    WORKSPACE_ACTION = "workspace_action"
    PHASE_CHANGE = "phase_change"
    RESTART_BANNER = "restart_banner"
    AGENT_RESTART = "agent_restart"
    PRESENTATION_START = "presentation_start"

    # Pipeline gap events (for subagent parity)
    HOOK_EXECUTION = "hook_execution"
    POST_EVALUATION = "post_evaluation"
    SYSTEM_STATUS = "system_status"

    # Coordination events (emitted by orchestrator for subagent TUI parity)
    ANSWER_SUBMITTED = "answer_submitted"
    VOTE = "vote"
    AGENT_STOPPED = "agent_stopped"  # Decomposition mode: agent signaled stop
    WINNER_SELECTED = "winner_selected"
    CONTEXT_RECEIVED = "context_received"

    # Final presentation events (unified pipeline for main + subagent TUI)
    FINAL_PRESENTATION_START = "final_presentation_start"
    FINAL_PRESENTATION_CHUNK = "final_presentation_chunk"
    FINAL_PRESENTATION_END = "final_presentation_end"
    ANSWER_LOCKED = "answer_locked"

    # Timeout events
    ORCHESTRATOR_TIMEOUT = "orchestrator_timeout"

    # Injection events
    INJECTION_RECEIVED = "injection_received"

    # Error events
    ERROR = "error"


class EventEmitter:
    """Writes structured events to events.jsonl.

    Thread-safe, append-only event logging that supplements streaming_debug.log.
    Events are written atomically to ensure file integrity.

    Usage:
        emitter = EventEmitter("/path/to/log/dir")
        emitter.emit_tool_start("tool_123", "read_file", {"path": "/foo.txt"})
        emitter.emit_tool_complete("tool_123", "read_file", "file contents", 0.5)
    """

    def __init__(self, log_dir: str | Path | None = None):
        """Initialize the event emitter.

        Args:
            log_dir: Directory to write events.jsonl. If None, events are
                    not written to file (useful for testing or when
                    log directory is not yet initialized).
        """
        self._log_dir = Path(log_dir) if log_dir else None
        self._file_path: Path | None = None
        self._file_handle = None
        self._lock = threading.Lock()
        self._listeners: list[EventListener] = []
        self._current_agent_id: str | None = None
        self._current_round_numbers: dict[str, int] = {}
        self._default_round_number: int = 0

        # Initialize file if log_dir provided
        if self._log_dir:
            self._init_file()

    def _init_file(self) -> None:
        """Initialize the events.jsonl file."""
        if self._log_dir:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._file_path = self._log_dir / "events.jsonl"
            # Open file in append mode with line buffering
            self._file_handle = open(self._file_path, "a", encoding="utf-8", buffering=1)

    def set_log_dir(self, log_dir: str | Path) -> None:
        """Update the log directory (e.g., when attempt changes).

        Args:
            log_dir: New directory for events.jsonl
        """
        with self._lock:
            # Close existing file handle
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None

            self._log_dir = Path(log_dir)
            self._init_file()

    def set_context(self, agent_id: str | None = None, round_number: int | None = None) -> None:
        """Set the current context for events.

        Args:
            agent_id: Current agent ID (None to clear)
            round_number: Current round number (None to keep existing)
        """
        if agent_id is not None:
            self._current_agent_id = agent_id
        if round_number is not None:
            self._default_round_number = round_number

    def add_listener(self, listener: EventListener) -> None:
        """Add a listener to be notified of all events.

        Args:
            listener: Callback function that receives MassGenEvent
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: EventListener) -> None:
        """Remove a previously added listener.

        Args:
            listener: Callback to remove
        """
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def emit(self, event: MassGenEvent) -> None:
        """Emit an event.

        Writes to file (if configured) and notifies listeners.

        Args:
            event: The event to emit
        """
        # Write to file
        with self._lock:
            if self._file_handle:
                try:
                    self._file_handle.write(event.to_json() + "\n")
                    self._file_handle.flush()
                except Exception as e:
                    import logging as _logging

                    _logging.getLogger(__name__).debug("EventEmitter file write failed: %s", e)

        # Notify listeners (copy to avoid concurrent modification)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as e:
                import logging as _logging

                _logging.getLogger(__name__).debug("Event listener %s failed: %s", listener, e)

    def emit_raw(self, event_type: str, **kwargs: Any) -> None:
        """Emit an event with automatic timestamp and context.

        Args:
            event_type: Type of event
            **kwargs: Event-specific data
        """
        resolved_agent_id = kwargs.pop("agent_id", self._current_agent_id)
        explicit_round = kwargs.pop("round_number", None)
        if explicit_round is not None:
            resolved_round = explicit_round
        elif resolved_agent_id and resolved_agent_id in self._current_round_numbers:
            resolved_round = self._current_round_numbers[resolved_agent_id]
        else:
            resolved_round = self._default_round_number
        event = MassGenEvent.create(
            event_type=event_type,
            agent_id=resolved_agent_id,
            round_number=resolved_round,
            **kwargs,
        )
        self.emit(event)

    # Convenience methods for common event types

    def emit_tool_start(
        self,
        tool_id: str,
        tool_name: str,
        args: dict[str, Any],
        server_name: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Emit a tool start event.

        Args:
            tool_id: Unique ID for this tool call
            tool_name: Name of the tool being called
            args: Tool arguments
            server_name: MCP server name if applicable
            agent_id: Override agent ID (uses context if None)
        """
        self.emit_raw(
            EventType.TOOL_START,
            tool_id=tool_id,
            tool_name=tool_name,
            args=args,
            server_name=server_name,
            agent_id=agent_id,
        )

    def emit_tool_complete(
        self,
        tool_id: str,
        tool_name: str,
        result: Any,
        elapsed_seconds: float,
        status: str = "success",
        is_error: bool = False,
        async_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Emit a tool completion event.

        Args:
            tool_id: ID of the tool call
            tool_name: Name of the tool
            result: Tool result (will be truncated if too long)
            elapsed_seconds: How long the tool took
            status: Status string (success, error, etc.)
            is_error: Whether this is an error result
            async_id: Optional async/background job ID for long-running operations
            agent_id: Override agent ID
        """
        result_str = str(result)

        self.emit_raw(
            EventType.TOOL_COMPLETE,
            tool_id=tool_id,
            tool_name=tool_name,
            result=result_str,
            elapsed_seconds=elapsed_seconds,
            status=status,
            is_error=is_error,
            async_id=async_id,
            agent_id=agent_id,
        )

    def emit_thinking(
        self,
        content: str,
        is_redacted: bool = False,
        agent_id: str | None = None,
    ) -> None:
        """Emit a thinking/reasoning content event.

        Args:
            content: Thinking content
            is_redacted: Whether content is redacted
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.THINKING,
            content=content,
            is_redacted=is_redacted,
            agent_id=agent_id,
        )

    def emit_text(self, content: str, agent_id: str | None = None) -> None:
        """Emit a text content event.

        Args:
            content: Text content
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.TEXT,
            content=content,
            agent_id=agent_id,
        )

    def emit_status(
        self,
        message: str,
        level: str = "info",
        agent_id: str | None = None,
    ) -> None:
        """Emit a status update event.

        Args:
            message: Status message
            level: Level (info, warning, error)
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.STATUS,
            message=message,
            level=level,
            agent_id=agent_id,
        )

    def emit_round_start(self, round_number: int, agent_id: str | None = None) -> None:
        """Emit a round start event.

        Args:
            round_number: The round number starting
            agent_id: Agent starting this round
        """
        if agent_id:
            self._current_round_numbers[agent_id] = round_number
        else:
            self._default_round_number = round_number
        self.emit_raw(
            EventType.ROUND_START,
            round_number=round_number,
            agent_id=agent_id,
        )

    def emit_final_answer(self, content: str, agent_id: str | None = None) -> None:
        """Emit a final answer event.

        Args:
            content: The final answer content
            agent_id: Agent that produced the answer
        """
        self.emit_raw(
            EventType.FINAL_ANSWER,
            content=content,
            agent_id=agent_id,
        )

    def emit_hook_execution(
        self,
        tool_call_id: str | None,
        hook_info: Any,
        agent_id: str | None = None,
    ) -> None:
        """Emit a hook execution event.

        Args:
            tool_call_id: ID of the tool call that triggered the hook
            hook_info: Hook execution details
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.HOOK_EXECUTION,
            tool_call_id=tool_call_id,
            hook_info=hook_info,
            agent_id=agent_id,
        )

    def emit_post_evaluation(
        self,
        phase: str,
        content: str | None = None,
        winner: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Emit a post-evaluation event.

        Args:
            phase: "start", "content", or "end"
            content: Evaluation content (for "content" phase)
            winner: Winning agent (for "end" phase)
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.POST_EVALUATION,
            phase=phase,
            content=content,
            winner=winner,
            agent_id=agent_id,
        )

    def emit_system_status(
        self,
        message: str,
        agent_id: str | None = None,
    ) -> None:
        """Emit a system status event.

        Args:
            message: Status message
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.SYSTEM_STATUS,
            message=message,
            agent_id=agent_id,
        )

    def emit_error(self, error: str, agent_id: str | None = None) -> None:
        """Emit an error event.

        Args:
            error: Error message
            agent_id: Override agent ID
        """
        self.emit_raw(
            EventType.ERROR,
            error=error,
            agent_id=agent_id,
        )

    def emit_injection_received(
        self,
        agent_id: str,
        source_agents: list[str],
        injection_type: str = "mid_stream",
    ) -> None:
        """Emit an injection_received event.

        Args:
            agent_id: Agent that received the injection
            source_agents: Agent IDs whose answers were injected
            injection_type: "mid_stream" or "full_restart"
        """
        self.emit_raw(
            EventType.INJECTION_RECEIVED,
            agent_id=agent_id,
            source_agents=source_agents,
            injection_type=injection_type,
        )

    def emit_workspace_action(
        self,
        action_type: str,
        params: Any = None,
        agent_id: str | None = None,
    ) -> None:
        """Emit a workspace action event (new_answer, vote, etc.)."""
        self.emit_raw(
            EventType.WORKSPACE_ACTION,
            action_type=action_type,
            params=params,
            agent_id=agent_id,
        )

    def emit_answer_submitted(
        self,
        agent_id: str,
        content: Any,
        answer_number: int,
        answer_label: str,
        workspace_path: str | None = None,
    ) -> None:
        """Emit an answer_submitted coordination event."""
        self.emit_raw(
            EventType.ANSWER_SUBMITTED,
            agent_id=agent_id,
            content=str(content)[:500] if content else "",
            answer_number=answer_number,
            answer_label=answer_label,
            workspace_path=workspace_path,
        )

    def emit_vote(
        self,
        voter_id: str,
        target_id: str,
        reason: str | None = None,
        vote_label: str | None = None,
        voted_for_label: str | None = None,
    ) -> None:
        """Emit a vote coordination event."""
        self.emit_raw(
            EventType.VOTE,
            agent_id=voter_id,
            target_id=target_id,
            reason=reason,
            vote_label=vote_label,
            voted_for_label=voted_for_label,
        )

    def emit_stop(
        self,
        agent_id: str,
        summary: str = "",
        status: str = "complete",
    ) -> None:
        """Emit an agent_stopped coordination event (decomposition mode)."""
        self.emit_raw(
            EventType.AGENT_STOPPED,
            agent_id=agent_id,
            summary=summary,
            status=status,
        )

    def emit_winner_selected(
        self,
        winner_id: str,
        vote_results: Any = None,
    ) -> None:
        """Emit a winner_selected coordination event."""
        self.emit_raw(
            EventType.WINNER_SELECTED,
            agent_id=winner_id,
            vote_results=str(vote_results) if vote_results else None,
        )

    def emit_context_received(
        self,
        agent_id: str,
        context_labels: Any | None = None,
    ) -> None:
        """Emit a context_received coordination event."""
        self.emit_raw(
            EventType.CONTEXT_RECEIVED,
            agent_id=agent_id,
            context_labels=context_labels,
        )

    def emit_final_presentation_start(
        self,
        agent_id: str,
        vote_counts: dict[str, Any] | None = None,
        answer_labels: dict[str, str] | None = None,
        is_tie: bool = False,
    ) -> None:
        """Emit a final_presentation_start event."""
        self.emit_raw(
            EventType.FINAL_PRESENTATION_START,
            agent_id=agent_id,
            vote_counts=vote_counts,
            answer_labels=answer_labels,
            is_tie=is_tie,
        )

    def emit_final_presentation_chunk(
        self,
        agent_id: str,
        content: str,
    ) -> None:
        """Emit a final_presentation_chunk event."""
        self.emit_raw(
            EventType.FINAL_PRESENTATION_CHUNK,
            agent_id=agent_id,
            content=content,
        )

    def emit_final_presentation_end(
        self,
        agent_id: str,
    ) -> None:
        """Emit a final_presentation_end event."""
        self.emit_raw(
            EventType.FINAL_PRESENTATION_END,
            agent_id=agent_id,
        )

    def emit_answer_locked(
        self,
        agent_id: str,
    ) -> None:
        """Emit an answer_locked event (timeline locks to final answer)."""
        self.emit_raw(
            EventType.ANSWER_LOCKED,
            agent_id=agent_id,
        )

    def emit_phase_change(
        self,
        phase: str,
        agent_id: str | None = None,
    ) -> None:
        """Emit a phase change event."""
        self.emit_raw(
            EventType.PHASE_CHANGE,
            phase=phase,
            agent_id=agent_id,
        )

    def emit_restart_banner(
        self,
        reason: str,
        instructions: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Emit a restart banner event."""
        self.emit_raw(
            EventType.RESTART_BANNER,
            reason=reason,
            instructions=instructions,
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def emit_agent_restart(
        self,
        round_number: int,
        agent_id: str | None = None,
        restart_reason: str | None = None,
    ) -> None:
        """Emit an agent restart event and update round tracking.

        Args:
            round_number: The new round number
            agent_id: Agent that is restarting
            restart_reason: Why the agent is restarting (e.g., "new answer", "context update")
        """
        # Update the round tracking for this agent so subsequent events
        # (answer_submitted, vote, etc.) have the correct round number
        if agent_id:
            self._current_round_numbers[agent_id] = round_number
        self.emit_raw(
            EventType.AGENT_RESTART,
            restart_round=round_number,
            agent_id=agent_id,
            restart_reason=restart_reason,
        )

    def emit_presentation_start(
        self,
        agent_id: str | None = None,
        vote_counts: Any = None,
        answer_labels: Any = None,
    ) -> None:
        """Emit a presentation start event."""
        self.emit_raw(
            EventType.PRESENTATION_START,
            vote_counts=vote_counts,
            answer_labels=answer_labels,
            agent_id=agent_id,
        )

    def emit_orchestrator_timeout(
        self,
        timeout_reason: str,
        available_answers: int,
        selected_agent: str | None = None,
        selection_reason: str = "",
        agent_answer_summary: dict[str, Any] | None = None,
    ) -> None:
        """Emit an orchestrator timeout event.

        Args:
            timeout_reason: Why the timeout occurred (e.g. "Time limit exceeded (30.1s/30s)")
            available_answers: Number of answers available at timeout
            selected_agent: Which agent was selected for presentation (None if no answers)
            selection_reason: Why this agent was selected
            agent_answer_summary: Per-agent summary {agent_id: {has_answer, vote_count}}
        """
        self.emit_raw(
            EventType.ORCHESTRATOR_TIMEOUT,
            timeout_reason=timeout_reason,
            available_answers=available_answers,
            selected_agent=selected_agent,
            selection_reason=selection_reason,
            agent_answer_summary=agent_answer_summary or {},
        )

    def close(self) -> None:
        """Close the event file handle."""
        with self._lock:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None

    @property
    def file_path(self) -> Path | None:
        """Get the path to the events.jsonl file."""
        return self._file_path


class EventReader:
    """Reads events from events.jsonl file.

    Supports both batch reading and live streaming of events.

    Usage:
        reader = EventReader("/path/to/events.jsonl")

        # Read all events
        for event in reader.read_all():
            print(event)

        # Stream new events (for live display)
        for event in reader.stream():
            update_display(event)
    """

    def __init__(self, file_path: str | Path):
        """Initialize the event reader.

        Args:
            file_path: Path to events.jsonl file
        """
        self._file_path = Path(file_path)
        self._last_position = 0

    def exists(self) -> bool:
        """Check if the events file exists."""
        return self._file_path.exists()

    def read_all(self) -> list[MassGenEvent]:
        """Read all events from the file.

        Returns:
            List of all events in the file
        """
        events = []
        if not self._file_path.exists():
            return events

        with open(self._file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(MassGenEvent.from_json(line))
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines
            self._last_position = f.tell()

        return events

    def read_since(self, position: int = 0) -> tuple[list[MassGenEvent], int]:
        """Read events from a specific file position.

        Args:
            position: File position to start reading from

        Returns:
            Tuple of (events list, new position)
        """
        events = []
        new_position = position

        if not self._file_path.exists():
            return events, new_position

        with open(self._file_path, encoding="utf-8") as f:
            f.seek(position)
            for line in f:
                line_stripped = line.strip()
                if line_stripped:
                    try:
                        events.append(MassGenEvent.from_json(line_stripped))
                    except json.JSONDecodeError:
                        continue
            new_position = f.tell()

        return events, new_position

    def get_new_events(self) -> list[MassGenEvent]:
        """Get events added since last read.

        Returns:
            List of new events
        """
        events, new_position = self.read_since(self._last_position)
        self._last_position = new_position
        return events

    def stream(self, poll_interval: float = 0.5) -> Generator[MassGenEvent]:
        """Stream events as they are written (blocking generator).

        Args:
            poll_interval: How often to check for new events (seconds)

        Yields:
            New events as they are written
        """
        while True:
            events = self.get_new_events()
            yield from events

            if not events:
                time.sleep(poll_interval)

    def filter_by_type(self, event_types: list[str]) -> list[MassGenEvent]:
        """Read events filtered by type.

        Args:
            event_types: List of event types to include

        Returns:
            Filtered list of events
        """
        return [e for e in self.read_all() if e.event_type in event_types]

    def filter_by_agent(self, agent_id: str) -> list[MassGenEvent]:
        """Read events filtered by agent.

        Args:
            agent_id: Agent ID to filter by

        Returns:
            Events from the specified agent
        """
        return [e for e in self.read_all() if e.agent_id == agent_id]

    def get_tools_summary(self) -> list[dict[str, Any]]:
        """Get a summary of all tool calls.

        Returns:
            List of tool call summaries with name, args, result, duration
        """
        all_events = self.read_all()
        tool_starts: dict[str, MassGenEvent] = {}
        summaries = []

        for event in all_events:
            if event.event_type == EventType.TOOL_START:
                tool_id = event.data.get("tool_id")
                if tool_id:
                    tool_starts[tool_id] = event
            elif event.event_type == EventType.TOOL_COMPLETE:
                tool_id = event.data.get("tool_id")
                start_event = tool_starts.get(tool_id)
                summaries.append(
                    {
                        "tool_id": tool_id,
                        "tool_name": event.data.get("tool_name"),
                        "args": start_event.data.get("args") if start_event else None,
                        "result": event.data.get("result"),
                        "elapsed_seconds": event.data.get("elapsed_seconds"),
                        "status": event.data.get("status"),
                        "is_error": event.data.get("is_error", False),
                        "async_id": event.data.get("async_id"),
                        "agent_id": event.agent_id,
                    },
                )

        return summaries

    def reset_position(self) -> None:
        """Reset the read position to the beginning of the file."""
        self._last_position = 0

    def skip_to_end(self) -> None:
        """Skip to the end of the file (ignore existing events)."""
        if self._file_path.exists():
            self._last_position = self._file_path.stat().st_size


# Global event emitter instance (initialized by logger_config.py)
_global_emitter: EventEmitter | None = None


def get_event_emitter() -> EventEmitter | None:
    """Get the event emitter for the current logging session.

    When a ``LoggingSession`` is active in the current context (set via
    ``massgen.logger_config.set_current_session``), returns that session's
    emitter so concurrent ``massgen.run()`` calls stay isolated.
    Falls back to the legacy global emitter for backward compatibility.

    Returns:
        The session-scoped EventEmitter, or the global one if no session is active
    """
    try:
        from .logger_config import get_current_session

        session = get_current_session()
        if session is not None and session.event_emitter is not None:
            return session.event_emitter
    except Exception:
        pass
    return _global_emitter


def set_event_emitter(emitter: EventEmitter) -> None:
    """Set the global event emitter instance.

    Args:
        emitter: The EventEmitter to use globally
    """
    global _global_emitter
    _global_emitter = emitter


def emit_event(event_type: str, **kwargs: Any) -> None:
    """Emit an event using the current session's emitter (or the global fallback).

    Args:
        event_type: Type of event
        **kwargs: Event data
    """
    emitter = get_event_emitter()
    if emitter:
        emitter.emit_raw(event_type, **kwargs)


# Export public API
__all__ = [
    "MassGenEvent",
    "EventType",
    "EventEmitter",
    "EventReader",
    "get_event_emitter",
    "set_event_emitter",
    "emit_event",
]
