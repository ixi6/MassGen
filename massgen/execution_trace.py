"""Execution Trace Writer.

Formats streaming buffer content as a structured, searchable markdown file
for agent context recovery and cross-agent coordination.

The trace file captures:
- Tool calls with full arguments (no truncation)
- Tool results with full output (no truncation)
- Reasoning/thinking blocks
- Errors with timestamps
- Metadata for searchability
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class EntryType(Enum):
    """Types of trace entries."""

    ROUND_START = "round_start"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    REASONING = "reasoning"
    CONTENT = "content"  # Model's text output (distinct from internal reasoning)
    ANSWER = "answer"
    VOTE = "vote"  # Vote submission during enforcement phase


@dataclass
class TraceEntry:
    """A single entry in the execution trace."""

    entry_type: EntryType
    timestamp: datetime
    content: dict[str, Any]


@dataclass
class ExecutionTraceWriter:
    """Formats streaming buffer content as structured, searchable markdown.

    Usage:
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/main.py"})
        writer.add_tool_result(name="Read", result="file content...")
        writer.add_reasoning("I need to understand the code structure...")
        writer.add_answer(answer_label="1.1", content="Completed the task...")
        writer.save(Path("/path/to/execution_trace.md"))
    """

    agent_id: str
    model: str
    start_time: datetime = field(default_factory=datetime.now)
    entries: list[TraceEntry] = field(default_factory=list)
    errors: list[TraceEntry] = field(default_factory=list)
    current_round: int = 0
    current_answer_label: str = ""
    # Track active reasoning entry to accumulate streaming tokens
    _active_reasoning_entry: TraceEntry | None = field(default=None, repr=False)
    # Track active content entry to accumulate streaming tokens
    _active_content_entry: TraceEntry | None = field(default=None, repr=False)

    def start_round(self, round_num: int, answer_label: str) -> None:
        """Mark the start of a new round/answer.

        Args:
            round_num: The round number (1-indexed)
            answer_label: The answer label (e.g., "1.1", "1.2")
        """
        self.finalize_reasoning()  # Close any open reasoning block from previous round
        self.finalize_content()  # Close any open content block from previous round
        self.current_round = round_num
        self.current_answer_label = answer_label
        self.entries.append(
            TraceEntry(
                entry_type=EntryType.ROUND_START,
                timestamp=datetime.now(),
                content={"round_num": round_num, "answer_label": answer_label},
            ),
        )

    def add_tool_call(self, name: str, args: dict[str, Any]) -> None:
        """Record a tool call (before execution).

        Args:
            name: The tool name
            args: The tool arguments as a dictionary
        """
        self.finalize_reasoning()  # Close any open reasoning block
        self.entries.append(
            TraceEntry(
                entry_type=EntryType.TOOL_CALL,
                timestamp=datetime.now(),
                content={"name": name, "args": args},
            ),
        )

    def add_tool_result(self, name: str, result: str, is_error: bool = False) -> None:
        """Record a tool result (after execution).

        Args:
            name: The tool name
            result: The tool result (full content, no truncation)
            is_error: Whether this is an error result
        """
        self.finalize_reasoning()  # Close any open reasoning block
        entry = TraceEntry(
            entry_type=EntryType.TOOL_ERROR if is_error else EntryType.TOOL_RESULT,
            timestamp=datetime.now(),
            content={"name": name, "result": result},
        )
        self.entries.append(entry)

        # Also track errors separately for aggregation
        if is_error:
            self.errors.append(entry)

    def add_reasoning(self, content: str) -> None:
        """Record reasoning/thinking content.

        Accumulates streaming tokens into a single reasoning entry.
        Call finalize_reasoning() or add a non-reasoning entry to close
        the current reasoning block.

        Args:
            content: The reasoning content (may be a streaming token)
        """
        self.finalize_content()  # Close any open content block first

        if self._active_reasoning_entry is not None:
            # Accumulate into existing reasoning entry
            self._active_reasoning_entry.content["reasoning"] += content
        else:
            # Start new reasoning entry
            self._active_reasoning_entry = TraceEntry(
                entry_type=EntryType.REASONING,
                timestamp=datetime.now(),
                content={"reasoning": content},
            )
            self.entries.append(self._active_reasoning_entry)

    def finalize_reasoning(self) -> None:
        """Close the current reasoning block.

        Call this when reasoning is complete (e.g., when switching to
        content output or tool calls).
        """
        self._active_reasoning_entry = None

    def add_content(self, content: str) -> None:
        """Record model text output (distinct from internal reasoning).

        This captures the model's visible output/response text, as opposed to
        internal thinking/reasoning. Useful for tracking what the model said
        vs what it was thinking.

        Accumulates streaming tokens into a single content entry.
        Call finalize_content() or add a non-content entry to close
        the current content block.

        Args:
            content: The text content (may be a streaming token)
        """
        self.finalize_reasoning()  # Close any open reasoning block first

        if self._active_content_entry is not None:
            # Accumulate into existing content entry
            self._active_content_entry.content["text"] += content
        else:
            # Start new content entry
            self._active_content_entry = TraceEntry(
                entry_type=EntryType.CONTENT,
                timestamp=datetime.now(),
                content={"text": content},
            )
            self.entries.append(self._active_content_entry)

    def finalize_content(self) -> None:
        """Close the current content block.

        Call this when content output is complete (e.g., when switching to
        tool calls or reasoning).
        """
        self._active_content_entry = None

    def add_answer(self, answer_label: str, content: str) -> None:
        """Record an answer submission.

        Args:
            answer_label: The answer label (e.g., "1.1")
            content: The answer content (preview)
        """
        self.finalize_reasoning()  # Close any open reasoning block
        self.entries.append(
            TraceEntry(
                entry_type=EntryType.ANSWER,
                timestamp=datetime.now(),
                content={"answer_label": answer_label, "content": content},
            ),
        )

    def add_vote(
        self,
        voted_for_agent: str,
        voted_for_label: str | None,
        reason: str,
        available_options: list[str] | None = None,
    ) -> None:
        """Record a vote submission during enforcement phase.

        Args:
            voted_for_agent: The agent ID that was voted for
            voted_for_label: The answer label voted for (e.g., "agent1.2")
            reason: The reason for the vote
            available_options: List of available answer labels when vote was cast
        """
        self.finalize_reasoning()  # Close any open reasoning block
        self.finalize_content()  # Close any open content block
        self.entries.append(
            TraceEntry(
                entry_type=EntryType.VOTE,
                timestamp=datetime.now(),
                content={
                    "voted_for_agent": voted_for_agent,
                    "voted_for_label": voted_for_label,
                    "reason": reason,
                    "available_options": available_options or [],
                },
            ),
        )

    def to_markdown(self) -> str:
        """Format the trace as searchable markdown.

        Returns:
            Markdown string with full content (no truncation)
        """
        self.finalize_reasoning()  # Close any pending reasoning block
        self.finalize_content()  # Close any pending content block
        lines = []

        # Header
        lines.append(f"# Execution Trace: {self.agent_id}")
        lines.append(f"**Model**: {self.model} | **Started**: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # Process entries
        for entry in self.entries:
            if entry.entry_type == EntryType.ROUND_START:
                round_num = entry.content["round_num"]
                answer_label = entry.content["answer_label"]
                lines.append(f"## Round {round_num} (Answer {answer_label})")
                lines.append("")

            elif entry.entry_type == EntryType.TOOL_CALL:
                name = entry.content["name"]
                args = entry.content["args"]
                lines.append(f"### Tool Call: {name}")
                lines.append("**Args**:")
                lines.append("```json")
                lines.append(json.dumps(args, indent=2))
                lines.append("```")
                lines.append("")

            elif entry.entry_type == EntryType.TOOL_RESULT:
                name = entry.content["name"]
                result = entry.content["result"]
                lines.append(f"### Tool Result: {name}")
                lines.append("```")
                lines.append(result)
                lines.append("```")
                lines.append("")

            elif entry.entry_type == EntryType.TOOL_ERROR:
                name = entry.content["name"]
                result = entry.content["result"]
                lines.append(f"### Tool Error: {name}")
                lines.append("```")
                lines.append(result)
                lines.append("```")
                lines.append("")

            elif entry.entry_type == EntryType.REASONING:
                reasoning = entry.content["reasoning"].rstrip()  # Strip trailing whitespace
                lines.append("### Reasoning")
                lines.append(reasoning)
                lines.append("")

            elif entry.entry_type == EntryType.CONTENT:
                text = entry.content["text"]
                lines.append("### Content")
                lines.append(text)
                lines.append("")

            elif entry.entry_type == EntryType.ANSWER:
                answer_label = entry.content["answer_label"]
                content = entry.content["content"]
                lines.append(f"### Answer Submitted ({answer_label})")
                lines.append(content)
                lines.append("")

            elif entry.entry_type == EntryType.VOTE:
                voted_for_agent = entry.content["voted_for_agent"]
                voted_for_label = entry.content.get("voted_for_label")
                reason = entry.content["reason"]
                available_options = entry.content.get("available_options", [])
                vote_target = voted_for_label or voted_for_agent
                lines.append(f"### Vote Cast: {vote_target}")
                if available_options:
                    lines.append(f"**Available options**: {', '.join(available_options)}")
                lines.append(f"**Voted for**: {vote_target}")
                lines.append(f"**Reason**: {reason}")
                lines.append("")

        # Aggregated errors section
        if self.errors:
            lines.append("---")
            lines.append("")
            lines.append("## Errors")
            lines.append("")
            for error in self.errors:
                timestamp = error.timestamp.strftime("%H:%M:%S")
                name = error.content["name"]
                result = error.content["result"]
                lines.append(f"- [{timestamp}] **Tool Error: {name}** - {result}")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: Path) -> None:
        """Write the trace to a file.

        Args:
            path: The file path to write to
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown())
