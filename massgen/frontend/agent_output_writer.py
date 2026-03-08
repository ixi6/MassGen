"""Lightweight agent output file writer driven by structured events.

Subscribes to the global EventEmitter and writes agent content to
individual text files (agent_outputs/{agent_id}.txt), independent
of any display class or buffer/flush pipeline.
"""

import time
from pathlib import Path

from massgen.events import EventType, MassGenEvent
from massgen.logger_config import get_event_emitter, get_log_session_dir


class AgentOutputWriter:
    """Writes agent output files from structured events."""

    def __init__(self, output_dir: Path, agent_ids: list[str]):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, Path] = {}

        for agent_id in agent_ids:
            file_path = self._output_dir / f"{agent_id}.txt"
            self._files[agent_id] = file_path
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"=== {agent_id.upper()} OUTPUT LOG ===\n\n")

    def handle_event(self, event: MassGenEvent) -> None:
        """EventEmitter listener callback."""
        agent_id = event.agent_id
        if not agent_id or agent_id not in self._files:
            return

        content = self._extract_content(event)
        if content is None:
            return

        self._append(agent_id, content, event.event_type)

    def _extract_content(self, event: MassGenEvent) -> str | None:
        """Extract writable content from a structured event."""
        etype = event.event_type
        data = event.data or {}

        if etype == EventType.TEXT:
            return data.get("content", "")
        elif etype == EventType.THINKING:
            return data.get("content", "")
        elif etype == EventType.STATUS:
            return data.get("message", "")
        elif etype == EventType.FINAL_ANSWER:
            return data.get("content", "")
        elif etype == EventType.TOOL_START:
            tool_name = data.get("tool_name", "unknown")
            args = data.get("args", {})
            args_str = str(args)[:200]
            return f"🔧 Calling {tool_name}({args_str})"
        elif etype == EventType.TOOL_COMPLETE:
            tool_name = data.get("tool_name", "unknown")
            elapsed = data.get("elapsed_seconds", 0)
            is_error = data.get("is_error", False)
            icon = "❌" if is_error else "✅"
            result = str(data.get("result", ""))[:500]
            return f"{icon} {tool_name} completed ({elapsed:.1f}s): {result}"

        return None

    def _append(self, agent_id: str, content: str, event_type: EventType) -> None:
        """Append content to an agent's output file."""
        file_path = self._files[agent_id]
        try:
            timestamp = time.strftime("%H:%M:%S")
            # Tool events and status get timestamped on their own line
            if event_type in (
                EventType.TOOL_START,
                EventType.TOOL_COMPLETE,
                EventType.STATUS,
            ):
                formatted = f"\n[{timestamp}] {content}\n"
            else:
                formatted = content

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(formatted)
        except Exception:
            pass  # Don't crash for file write errors

    def close(self) -> None:
        """Clean up (no-op, files are opened/closed per write)."""


def create_agent_output_writer(
    agent_ids: list[str],
    output_dir: Path | None = None,
) -> AgentOutputWriter | None:
    """Create an AgentOutputWriter and register it on the global EventEmitter.

    Args:
        agent_ids: List of agent IDs to track.
        output_dir: Directory for output files. Defaults to
            {log_session_dir}/agent_outputs.

    Returns:
        The writer instance, or None if no emitter is available.
    """

    emitter = get_event_emitter()
    if emitter is None:
        return None

    if output_dir is None:
        output_dir = get_log_session_dir() / "agent_outputs"

    writer = AgentOutputWriter(output_dir, agent_ids)
    emitter.add_listener(writer.handle_event)
    return writer
