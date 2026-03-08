"""Streaming buffer mixin for compression recovery.

This module provides a mixin class that adds streaming buffer functionality
to LLM backends. The buffer tracks accumulated content during streaming so
it can be included in compression summaries when context limits are exceeded.

Also provides execution trace functionality for persisting structured execution
history to files for context recovery and cross-agent coordination.
"""

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    from ..execution_trace import ExecutionTraceWriter

# Global flag to enable buffer saving (set by CLI)
_save_streaming_buffers: bool = False
_buffer_save_counter: int = 0


def set_save_streaming_buffers(enabled: bool) -> None:
    """Enable or disable streaming buffer saving.

    Args:
        enabled: Whether to save streaming buffers to files
    """
    global _save_streaming_buffers
    _save_streaming_buffers = enabled
    if enabled:
        logger.info("[StreamingBuffer] Buffer saving enabled")


def get_save_streaming_buffers() -> bool:
    """Check if streaming buffer saving is enabled."""
    return _save_streaming_buffers


class StreamingBufferMixin:
    """Mixin providing streaming buffer for compression recovery.

    Tracks accumulated content during streaming so it can be included
    in compression summaries when context limits are exceeded. The buffer
    captures:
    - Streaming text content (deltas)
    - Tool call requests (name + arguments)
    - Tool execution results
    - Tool errors
    - Reasoning/thinking content

    Usage:
        class MyBackend(StreamingBufferMixin, CustomToolAndMCPBackend):
            pass

    Note:
        The mixin should be listed BEFORE the main parent class in the
        inheritance list for correct Method Resolution Order (MRO).
    """

    _streaming_buffer: str = ""
    _in_reasoning_block: bool = False
    _execution_trace: Optional["ExecutionTraceWriter"] = None

    def __init__(self, *args, **kwargs):
        """Initialize streaming buffer.

        Uses cooperative multiple inheritance - calls super().__init__()
        to ensure proper MRO chain.
        """
        super().__init__(*args, **kwargs)
        self._streaming_buffer = ""
        self._in_reasoning_block = False
        self._execution_trace = None

    def _clear_streaming_buffer(
        self,
        *,
        _compression_retry: bool = False,
        **kwargs,
    ) -> None:
        """Clear the streaming buffer and optionally initialize execution trace.

        Respects the _compression_retry flag - does NOT clear if this is
        a retry after compression (to preserve accumulated context).

        If agent_id is provided in kwargs, initializes execution trace for
        structured history tracking.

        Args:
            _compression_retry: If True, preserve buffer (retry after compression)
            **kwargs: Additional keyword arguments including:
                - agent_id: Agent identifier for trace initialization
        """
        if not _compression_retry:
            self._streaming_buffer = ""
            self._in_reasoning_block = False

            # Always create a fresh execution trace when clearing buffer (new answer/restart)
            # This ensures each answer has its own trace, not accumulated from previous answers
            agent_id = kwargs.get("agent_id") or getattr(self, "agent_id", None)
            if agent_id:
                model = "unknown"
                if hasattr(self, "config") and isinstance(self.config, dict):
                    model = self.config.get("model", "unknown")
                self._init_execution_trace(agent_id=agent_id, model=model)

    def _finalize_streaming_buffer(self, agent_id: str | None = None) -> None:
        """Finalize and optionally save the streaming buffer.

        Call this at the end of streaming to save the buffer if enabled.

        Args:
            agent_id: Optional agent identifier for the filename
        """
        logger.debug(f"[StreamingBuffer] _finalize_streaming_buffer called, agent={agent_id}, buffer_len={len(self._streaming_buffer)}")
        if self._streaming_buffer:
            self._save_streaming_buffer(agent_id=agent_id)

    def _append_to_streaming_buffer(self, content: str) -> None:
        """Append content to the streaming buffer.

        Args:
            content: Text content to append (typically streaming deltas)
        """
        if content:
            self._in_reasoning_block = False  # End reasoning block when regular content comes
            self._streaming_buffer += content

    def _append_tool_call_to_buffer(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> None:
        """Append tool call requests to the streaming buffer.

        Records the tool calls made by the LLM before execution.
        Also records to execution trace if initialized.

        Args:
            tool_calls: List of tool call dictionaries with name, arguments, etc.
        """
        if not tool_calls:
            return

        for call in tool_calls:
            # Handle both flat format {"name": "...", "arguments": ...}
            # and nested format {"function": {"name": "...", "arguments": ...}}
            if "function" in call and isinstance(call["function"], dict):
                name = call["function"].get("name", "unknown")
                args = call["function"].get("arguments", {})
            else:
                name = call.get("name", "unknown")
                args = call.get("arguments", {})

            # Format arguments - handle both string and dict
            if isinstance(args, str):
                try:
                    args_dict = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args_dict = {"raw": args}  # Keep as raw for trace
                args = args_dict if isinstance(args_dict, dict) else args

            # Record to execution trace (full args dict)
            if self._execution_trace:
                self._execution_trace.add_tool_call(name=name, args=args if isinstance(args, dict) else {"raw": str(args)})

            # Compact JSON for buffer
            if isinstance(args, dict):
                args_str = json.dumps(args, separators=(",", ":"))
            else:
                args_str = str(args)

            self._in_reasoning_block = False  # End reasoning block when tool call comes
            self._streaming_buffer += f"\n\n[Tool Call: {name}({args_str})]"

    def _append_tool_to_buffer(
        self,
        tool_name: str,
        result_text: str,
        is_error: bool = False,
    ) -> None:
        """Append a tool result to the streaming buffer with consistent formatting.

        Also records to execution trace if initialized.

        Args:
            tool_name: Name of the tool that was executed
            result_text: The result text or error message
            is_error: Whether this is an error result
        """
        # Record to execution trace (full result, no truncation)
        if self._execution_trace:
            self._execution_trace.add_tool_result(name=tool_name, result=result_text, is_error=is_error)

        self._in_reasoning_block = False  # End reasoning block when tool result comes
        prefix = "Tool Error" if is_error else "Tool"
        self._streaming_buffer += f"\n\n[{prefix}: {tool_name}]\n{result_text}"

    def _append_reasoning_to_buffer(self, reasoning_text: str) -> None:
        """Append reasoning/thinking content to the streaming buffer.

        Also records to execution trace if initialized.

        Args:
            reasoning_text: Reasoning or thinking text from the model
        """
        if reasoning_text:
            # Record to execution trace
            if self._execution_trace:
                self._execution_trace.add_reasoning(content=reasoning_text)

            # Only add header if this is start of reasoning block
            if not self._in_reasoning_block:
                if self._streaming_buffer and not self._streaming_buffer.endswith("\n"):
                    self._streaming_buffer += "\n"
                self._streaming_buffer += "\n[Reasoning]\n"
                self._in_reasoning_block = True
            self._streaming_buffer += reasoning_text

    def _get_streaming_buffer(self) -> str | None:
        """Get buffer content for compression, or None if empty.

        Returns:
            Buffer content string or None if empty
        """
        return self._streaming_buffer if self._streaming_buffer else None

    def _save_streaming_buffer(self, agent_id: str | None = None) -> None:
        """Save the streaming buffer to a file if saving is enabled.

        Args:
            agent_id: Optional agent identifier for the filename
        """
        global _buffer_save_counter

        if not _save_streaming_buffers:
            logger.debug("[StreamingBuffer] Saving disabled, skipping")
            return

        buffer = self._get_streaming_buffer()
        if not buffer:
            logger.debug(f"[StreamingBuffer] Buffer empty for agent {agent_id}, skipping save")
            return

        logger.debug(f"[StreamingBuffer] Saving buffer for agent {agent_id}, size={len(buffer)}")

        # Import here to avoid circular imports
        from ..logger_config import get_log_session_dir

        try:
            log_dir = get_log_session_dir()
            buffers_dir = log_dir / "streaming_buffers"
            buffers_dir.mkdir(parents=True, exist_ok=True)

            _buffer_save_counter += 1
            timestamp = time.strftime("%H%M%S")

            # Get backend name
            backend_name = "unknown"
            if hasattr(self, "get_provider_name"):
                backend_name = self.get_provider_name()

            agent_prefix = f"{agent_id}_" if agent_id else ""
            filename = f"{agent_prefix}{backend_name}_{timestamp}_{_buffer_save_counter:03d}.txt"
            filepath = buffers_dir / filename

            with open(filepath, "w") as f:
                f.write("# Streaming Buffer\n")
                f.write(f"# Backend: {backend_name}\n")
                f.write(f"# Agent: {agent_id or 'unknown'}\n")
                f.write(f"# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Buffer size: {len(buffer)} chars\n")
                f.write(f"{'=' * 60}\n\n")
                f.write(buffer)

            logger.debug(f"[StreamingBuffer] Saved to {filepath}")
        except Exception as e:
            logger.warning(f"[StreamingBuffer] Failed to save buffer: {e}")

    # =========================================================================
    # Execution Trace Methods
    # =========================================================================

    def _init_execution_trace(self, agent_id: str, model: str) -> None:
        """Initialize execution trace for structured history tracking.

        Call this at the start of agent execution to begin tracking.

        Args:
            agent_id: The agent identifier
            model: The model name being used
        """
        from ..execution_trace import ExecutionTraceWriter

        self._execution_trace = ExecutionTraceWriter(agent_id=agent_id, model=model)
        logger.debug(f"[StreamingBuffer] Initialized execution trace for {agent_id}")

    def _start_trace_round(self, round_num: int, answer_label: str) -> None:
        """Start a new round in the execution trace.

        Args:
            round_num: The round number (1-indexed)
            answer_label: The answer label (e.g., "1.1")
        """
        if self._execution_trace:
            self._execution_trace.start_round(round_num=round_num, answer_label=answer_label)

    def _add_tool_call_to_trace(self, name: str, args: dict[str, Any]) -> None:
        """Add a tool call to the execution trace.

        Args:
            name: The tool name
            args: The tool arguments
        """
        if self._execution_trace:
            self._execution_trace.add_tool_call(name=name, args=args)

    def _add_tool_result_to_trace(self, name: str, result: str, is_error: bool = False) -> None:
        """Add a tool result to the execution trace.

        Args:
            name: The tool name
            result: The tool result (full content)
            is_error: Whether this is an error result
        """
        if self._execution_trace:
            self._execution_trace.add_tool_result(name=name, result=result, is_error=is_error)

    def _add_reasoning_to_trace(self, content: str) -> None:
        """Add reasoning content to the execution trace.

        Args:
            content: The reasoning content
        """
        if self._execution_trace:
            self._execution_trace.add_reasoning(content=content)

    def _add_answer_to_trace(self, answer_label: str, content: str) -> None:
        """Add an answer submission to the execution trace.

        Args:
            answer_label: The answer label
            content: The answer content preview
        """
        if self._execution_trace:
            self._execution_trace.add_answer(answer_label=answer_label, content=content)

    def _add_vote_to_trace(
        self,
        voted_for_agent: str,
        voted_for_label: str | None,
        reason: str,
        available_options: list[str] | None = None,
    ) -> None:
        """Add a vote submission to the execution trace.

        Args:
            voted_for_agent: The agent ID that was voted for
            voted_for_label: The answer label voted for (e.g., "agent1.2")
            reason: The reason for the vote
            available_options: List of available answer labels when vote was cast
        """
        if self._execution_trace:
            self._execution_trace.add_vote(
                voted_for_agent=voted_for_agent,
                voted_for_label=voted_for_label,
                reason=reason,
                available_options=available_options,
            )

    def _save_execution_trace(self, snapshot_dir: Path) -> Path | None:
        """Save the execution trace to the snapshot directory.

        Args:
            snapshot_dir: The directory to save the trace file to

        Returns:
            Path to the saved file, or None if no trace to save
        """
        if not self._execution_trace:
            logger.debug("[StreamingBuffer] No execution trace to save")
            return None

        try:
            trace_path = snapshot_dir / "execution_trace.md"
            self._execution_trace.save(trace_path)
            logger.info(f"[StreamingBuffer] Saved execution trace to {trace_path}")
            return trace_path
        except OSError as e:
            logger.warning(f"[StreamingBuffer] Failed to save execution trace: {e}")
            return None

    def _get_execution_trace(self) -> Optional["ExecutionTraceWriter"]:
        """Get the current execution trace writer.

        Returns:
            The ExecutionTraceWriter instance, or None if not initialized
        """
        return self._execution_trace
