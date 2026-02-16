# -*- coding: utf-8 -*-
"""
Unified Content Processor for MassGen TUI.

Provides a single source of truth for content processing logic, used by both
the main TUI (AgentPanel) and SubagentTuiModal. This ensures:
- Visual parity between main TUI and subagent modal
- No duplicate code to maintain
- Automatic propagation of improvements

Design Philosophy:
- Process structured events into data for TimelineSection
- Respect Timeline Chronology Rule: tools only batch when consecutive
"""

import ast
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from massgen.events import EventType, MassGenEvent

from .content_handlers import (
    ThinkingContentHandler,
    ToolBatchTracker,
    ToolDisplayData,
    format_tool_display_name,
    get_tool_category,
)
from .content_normalizer import ContentNormalizer, NormalizedContent
from .shared.tui_debug import tui_log
from .task_plan_support import is_planning_tool

# Output types for ContentProcessor
OutputType = Literal[
    "tool",
    "tool_batch",
    "thinking",
    "text",
    "status",
    "presentation",
    "injection",
    "reminder",
    "separator",
    "final_answer",
    "final_presentation_start",
    "final_presentation_chunk",
    "final_presentation_end",
    "answer_locked",
    "thinking_done",
    "hook",
    "orchestrator_timeout",
    "skip",  # Filter out this content
]

# Batch actions from ToolBatchTracker
BatchAction = Literal[
    "standalone",  # Non-MCP tool, use regular ToolCallCard
    "pending",  # First MCP tool, show as ToolCallCard but track for potential batch
    "convert_to_batch",  # Second tool arrived - convert pending to batch
    "add_to_batch",  # Add to existing batch
    "update_standalone",  # Update a standalone/pending tool
    "update_batch",  # Update existing tool in batch
]


@dataclass
class ContentOutput:
    """Structured output from ContentProcessor for TimelineSection.

    This dataclass contains all the information needed to render content
    in the timeline, regardless of the content type.
    """

    output_type: OutputType
    round_number: int = 1

    # For tool content
    tool_data: Optional[ToolDisplayData] = None
    batch_action: Optional[BatchAction] = None
    batch_id: Optional[str] = None
    server_name: Optional[str] = None
    pending_tool_id: Optional[str] = None  # For convert_to_batch

    # For text content
    text_content: Optional[str] = None
    text_style: str = ""
    text_class: str = ""

    # For batched tools (multiple tools in a batch)
    batch_tools: List[ToolDisplayData] = field(default_factory=list)

    # For separators
    separator_label: str = ""
    separator_subtitle: str = ""

    # For hook attachments to tool cards
    hook_tool_call_id: Optional[str] = None
    hook_info: Optional[Dict[str, Any]] = None

    # Original normalized content (for debugging/advanced use)
    normalized: Optional[NormalizedContent] = None

    # Extra metadata for specialized output types (final_presentation_start, etc.)
    extra: Optional[Dict[str, Any]] = None


class ContentProcessor:
    """Unified content processing for TUI and subagent modal.

    Handles:
    - Tool event lifecycle tracking via structured events
    - Tool batching logic (Timeline Chronology Rule) via ToolBatchTracker
    - Thinking/content filtering via ThinkingContentHandler

    Usage:
        processor = ContentProcessor()

        # For structured events
        output = processor.process_event(event, round_number)
        if output and output.output_type != "skip":
            timeline.apply_output(output)
    """

    def __init__(self) -> None:
        # Content handlers (shared logic)
        self._thinking_handler = ThinkingContentHandler()
        self._batch_tracker = ToolBatchTracker()

        # Counter for tracking events (debugging)
        self._event_counter = 0

        # Event processing state
        self._event_tool_states: Dict[str, Dict[str, Any]] = {}
        self._event_pending_batch: List[ToolDisplayData] = []
        self._event_round_number: int = 1

    def reset(self) -> None:
        """Reset processor state (e.g., for new session/round)."""
        self._batch_tracker.reset()
        self._event_counter = 0
        self._event_tool_states.clear()
        self._event_pending_batch.clear()
        self._event_round_number = 1

    def get_pending_tool_count(self) -> int:
        """Get count of pending (running) tools."""
        return len(self._event_tool_states)

    # =========================================================================
    # Event Processing
    # =========================================================================

    def process_event(
        self,
        event: MassGenEvent,
        round_number: int = 1,
    ) -> Optional[Union[ContentOutput, List[ContentOutput]]]:
        """Process a structured MassGenEvent.

        This is the entry point for processing events. It handles the different
        event types and returns ContentOutput objects that can be applied to
        TimelineSection.

        Args:
            event: The MassGenEvent to process
            round_number: Current round number (overridden by ROUND_START events)

        Returns:
            ContentOutput with structured data for TimelineSection, or None if
            the event should be filtered out.
        """
        if event.event_type == EventType.TOOL_START:
            return self._handle_event_tool_start(event, round_number)
        elif event.event_type == EventType.TOOL_COMPLETE:
            return self._handle_event_tool_complete(event, round_number)
        elif event.event_type == EventType.THINKING:
            return self._handle_event_thinking(event, round_number)
        elif event.event_type == EventType.TEXT:
            return self._handle_event_text(event, round_number)
        elif event.event_type == EventType.STATUS:
            return self._handle_event_status(event, round_number)
        elif event.event_type == EventType.ROUND_START:
            return self._handle_event_round_start(event)
        elif event.event_type == EventType.FINAL_ANSWER:
            return self._handle_event_final_answer(event, round_number)
        elif event.event_type == "stream_chunk":
            # Legacy stream_chunk events from old log files — skip gracefully
            return None
        elif event.event_type == EventType.WORKSPACE_ACTION:
            return self._handle_event_workspace_action(event, round_number)
        elif event.event_type == EventType.RESTART_BANNER:
            return self._handle_event_restart_banner(event, round_number)
        elif event.event_type == EventType.PRESENTATION_START:
            return self._handle_event_presentation_start(event, round_number)
        elif event.event_type == EventType.AGENT_RESTART:
            return self._handle_event_agent_restart(event, round_number)
        elif event.event_type == EventType.PHASE_CHANGE:
            return self._handle_event_phase_change(event, round_number)
        elif event.event_type == EventType.HOOK_EXECUTION:
            return self._handle_event_hook_execution(event, round_number)
        elif event.event_type == EventType.POST_EVALUATION:
            return self._handle_event_post_evaluation(event, round_number)
        elif event.event_type == EventType.SYSTEM_STATUS:
            return self._handle_event_system_status(event, round_number)
        elif event.event_type == EventType.ANSWER_SUBMITTED:
            return self._handle_event_answer_submitted(event, round_number)
        elif event.event_type == EventType.VOTE:
            return self._handle_event_vote(event, round_number)
        elif event.event_type == EventType.AGENT_STOPPED:
            return self._handle_event_agent_stopped(event, round_number)
        elif event.event_type == EventType.WINNER_SELECTED:
            return self._handle_event_winner_selected(event, round_number)
        elif event.event_type == EventType.CONTEXT_RECEIVED:
            return self._handle_event_context_received(event, round_number)
        elif event.event_type == EventType.INJECTION_RECEIVED:
            return self._handle_event_injection_received(event, round_number)
        elif event.event_type == EventType.FINAL_PRESENTATION_START:
            return self._handle_event_final_presentation_start(event, round_number)
        elif event.event_type == EventType.FINAL_PRESENTATION_CHUNK:
            return self._handle_event_final_presentation_chunk(event, round_number)
        elif event.event_type == EventType.FINAL_PRESENTATION_END:
            return self._handle_event_final_presentation_end(event, round_number)
        elif event.event_type == EventType.ANSWER_LOCKED:
            return self._handle_event_answer_locked(event, round_number)
        elif event.event_type == EventType.ORCHESTRATOR_TIMEOUT:
            return self._handle_event_orchestrator_timeout(event, round_number)
        return None

    def _handle_event_tool_start(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle tool_start event."""
        tool_id = event.data.get("tool_id", "")
        tool_name = event.data.get("tool_name", "unknown")
        args = event.data.get("args", {})
        server_name = event.data.get("server_name")

        # Filter out internal coordination tools (task_plan, etc.),
        # but keep planning tools so task plans can update.
        if ContentNormalizer.is_filtered_tool(tool_name) and not is_planning_tool(tool_name):
            return None

        tui_log(f"[TOOL_EVENT] tool_name={tool_name} server_name={server_name} tool_type={'mcp' if server_name else 'tool'}")

        # Get category info for proper styling
        category_info = get_tool_category(tool_name)
        display_name = format_tool_display_name(tool_name)

        # Create args summary
        if isinstance(args, str):
            args_str = args
        elif isinstance(args, (dict, list)):
            args_str = json.dumps(args)
        else:
            args_str = str(args)
        args_summary = args_str[:77] + "..." if len(args_str) > 80 else args_str

        # Create ToolDisplayData
        tool_data = ToolDisplayData(
            tool_id=tool_id,
            tool_name=tool_name,
            display_name=display_name,
            tool_type="mcp" if server_name else "tool",
            category=category_info["category"],
            icon=category_info["icon"],
            color=category_info["color"],
            status="running",
            start_time=datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now(),
            args_summary=args_summary,
            args_full=args_str,
            server_name=server_name,
        )

        # Store tool state for completion matching
        self._event_tool_states[tool_id] = {
            "tool_data": tool_data,
            "start_time": event.timestamp,
        }

        # Determine batch action
        batch_action, batch_server, batch_id, pending_id = self._batch_tracker.process_tool(tool_data)

        return ContentOutput(
            output_type="tool",
            round_number=round_number,
            tool_data=tool_data,
            batch_action=batch_action,
            batch_id=batch_id,
            server_name=batch_server,
            pending_tool_id=pending_id,
        )

    def _handle_event_tool_complete(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle tool_complete event."""
        tool_id = event.data.get("tool_id", "")
        tool_name = event.data.get("tool_name", "")
        result_text = event.data.get("result", "")
        elapsed = event.data.get("elapsed_seconds", 0)
        is_error = event.data.get("is_error", False)

        # Filter out internal coordination tools (task_plan, etc.),
        # but keep planning tools so task plans can update.
        if tool_name and ContentNormalizer.is_filtered_tool(tool_name) and not is_planning_tool(tool_name):
            # Clean up tool state if present
            self._event_tool_states.pop(tool_id, None)
            return None

        # Get stored tool state
        tool_state = self._event_tool_states.get(tool_id, {})
        original_data = tool_state.get("tool_data")

        if not original_data:
            # No matching start - create minimal tool data
            tool_name = event.data.get("tool_name", "unknown")
            server_name = event.data.get("server_name")
            category_info = get_tool_category(tool_name)
            display_name = format_tool_display_name(tool_name)
            original_data = ToolDisplayData(
                tool_id=tool_id,
                tool_name=tool_name,
                display_name=display_name,
                tool_type="mcp" if server_name else "tool",
                category=category_info["category"],
                icon=category_info["icon"],
                color=category_info["color"],
                status="running",
                start_time=datetime.now(),
                server_name=server_name,
            )

        # Create result summary
        result_summary = result_text[:100] + "..." if len(result_text) > 100 else result_text

        # Create updated ToolDisplayData
        tool_data = ToolDisplayData(
            tool_id=tool_id,
            tool_name=original_data.tool_name,
            display_name=original_data.display_name,
            tool_type=original_data.tool_type,
            category=original_data.category,
            icon=original_data.icon,
            color=original_data.color,
            status="error" if is_error else "success",
            start_time=original_data.start_time,
            end_time=datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now(),
            args_summary=original_data.args_summary,
            args_full=original_data.args_full,
            result_summary=result_summary,
            result_full=result_text,
            error=result_text if is_error else None,
            elapsed_seconds=elapsed,
            server_name=original_data.server_name,
        )

        # Determine batch action for completion
        batch_action, batch_server, batch_id, _ = self._batch_tracker.process_tool(tool_data)

        # Clean up tool state
        self._event_tool_states.pop(tool_id, None)

        return ContentOutput(
            output_type="tool",
            round_number=round_number,
            tool_data=tool_data,
            batch_action=batch_action,
            batch_id=batch_id,
            server_name=batch_server,
        )

    def _handle_event_thinking(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle thinking event.

        Thinking events arrive as small streaming tokens (e.g. " planning",
        " the").  We must NOT run them through the full normalize pipeline
        which calls .strip() and would remove the leading spaces that
        separate words.  Instead we only filter obviously empty content.

        Events with ``done=True`` signal the end of a reasoning block.
        """
        content = event.data.get("content", "")
        is_done = event.data.get("done", False)

        if not content and not is_done:
            return None

        # Mark that content arrived BEFORE filtering whitespace.
        # This ensures the tool batch tracker knows content appeared between
        # tools, even if the content is just whitespace (e.g., Kimi's
        # interleaved \n tokens).
        if content:
            self._batch_tracker.mark_content_arrived()

        # Only filter empty/whitespace-only content (but allow done markers)
        if not is_done and not content.strip():
            return None

        return ContentOutput(
            output_type="thinking_done" if is_done else "thinking",
            round_number=round_number,
            text_content=content,
            text_style="dim italic",
            text_class="thinking-inline",
        )

    def _handle_event_text(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle text event.

        Applies the same filtering as main TUI for visual parity.
        """
        content = event.data.get("content", "")
        if not content:
            return None

        # Apply same filtering as main TUI for parity
        normalized = ContentNormalizer.normalize(content, "text")
        if not normalized.should_display:
            return None

        cleaned = self._thinking_handler.process(normalized)
        if not cleaned:
            return None

        # Mark that content arrived
        self._batch_tracker.mark_content_arrived()

        return ContentOutput(
            output_type="text",
            round_number=round_number,
            text_content=cleaned,
            text_style="",
            text_class="content-inline",
        )

    def _handle_event_status(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle status event."""
        message = event.data.get("message", "")
        level = event.data.get("level", "info")
        if not message:
            return None

        # Skip info-level status messages — these are internal/operational
        # (e.g., "Voting complete", "Presenting final answer") and are already
        # handled by dedicated display paths (vote notifications, presentation
        # start events, etc.).
        if level == "info":
            return None

        # Use ContentNormalizer as single source of truth for filtering
        normalized = ContentNormalizer.normalize(message, "status")
        if not normalized.should_display:
            return None

        return ContentOutput(
            output_type="status",
            round_number=round_number,
            text_content=normalized.cleaned_content,
            text_style="dim cyan",
            text_class="status",
        )

    def _handle_event_round_start(
        self,
        event: MassGenEvent,
    ) -> Optional[ContentOutput]:
        """Handle round_start event.

        Round banners are now handled exclusively by agent_restart events.
        This avoids duplicate banners and stale round numbers that occur when
        round_start fires with the orchestrator's view (not the agent's actual round).

        Round 1 is handled by _ensure_round_banner(1) in content_sections.py.
        """
        return None

    def _handle_event_final_answer(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle final_answer event."""
        content = event.data.get("content", "")

        return ContentOutput(
            output_type="final_answer",
            round_number=round_number,
            text_content=content,
        )

    def _handle_event_workspace_action(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle workspace_action event."""
        action_type = event.data.get("action_type", "unknown")
        params = event.data.get("params")
        # Suppress vote/new_answer/stop actions (rendered via dedicated tool cards)
        if action_type in {"vote", "new_answer", "stop"}:
            return None
        label = f"workspace/{action_type}"
        if params:
            label += f" {params}"

        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="status",
            round_number=round_number,
            text_content=f"🔧 {label}",
            text_style="dim cyan",
            text_class="status",
        )

    def _handle_event_restart_banner(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle restart_banner event."""
        attempt = event.data.get("attempt", 1)
        max_attempts = event.data.get("max_attempts", 3)
        reason = event.data.get("reason", "")

        return ContentOutput(
            output_type="separator",
            round_number=attempt,
            separator_label=f"Restart Attempt {attempt}/{max_attempts}",
            separator_subtitle=reason,
        )

    def _handle_event_presentation_start(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle presentation_start event.

        Note: This event is suppressed because FINAL_PRESENTATION_START
        will follow with the proper banner including vote counts and
        answer labels. Returning the separator here would create a
        duplicate "Final Presentation" banner without vote info.
        """
        # Suppress - FINAL_PRESENTATION_START handles the banner with vote info
        return None

    def _handle_event_agent_restart(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle agent_restart event."""
        agent_round = event.data.get("restart_round", round_number)
        try:
            agent_round = max(1, int(agent_round))
        except Exception:
            agent_round = 1

        # Extract restart reason from event data
        restart_reason = event.data.get("restart_reason", "")
        subtitle = ""
        if restart_reason:
            subtitle = f"Restart: {restart_reason}"

        # Use agent_restart to advance the displayed round for this agent.
        # The banner is deferred by the adapter to avoid mid-stream ordering issues.
        return ContentOutput(
            output_type="separator",
            round_number=agent_round,
            separator_label=f"Round {agent_round}",
            separator_subtitle=subtitle,
        )

    def _handle_event_phase_change(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle phase_change event."""
        phase = event.data.get("phase", "unknown")

        return ContentOutput(
            output_type="status",
            round_number=round_number,
            text_content=f"Phase: {phase}",
            text_style="dim cyan",
            text_class="status",
        )

    def _handle_event_hook_execution(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle hook_execution event.

        Returns a hook ContentOutput so the event pipeline can attach hook
        details (including injection content) to the preceding tool card.
        On the main display path this is handled via update_hook_execution →
        add_hook_to_tool, but for subagent screens the ContentProcessor
        pipeline is the only path, so we must emit the data here.
        """
        tool_call_id = event.data.get("tool_call_id")
        raw_hook_info = event.data.get("hook_info")

        # hook_info may be a dict or a stringified dict (legacy JSONL logs)
        if isinstance(raw_hook_info, str):
            try:
                raw_hook_info = ast.literal_eval(raw_hook_info)
            except Exception:
                raw_hook_info = {}
        if not isinstance(raw_hook_info, dict):
            raw_hook_info = {}

        hook_info = {
            "hook_name": raw_hook_info.get("hook_name", ""),
            "hook_type": raw_hook_info.get("hook_type", ""),
            "status": raw_hook_info.get("decision", raw_hook_info.get("status", "")),
            "injection_content": raw_hook_info.get("injection_content"),
            "output": raw_hook_info.get("output", ""),
        }
        # Only emit if there's a tool to attach to
        if not tool_call_id:
            return None
        return ContentOutput(
            output_type="hook",
            round_number=round_number,
            hook_tool_call_id=tool_call_id,
            hook_info=hook_info,
        )

    def _handle_event_post_evaluation(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle post_evaluation event."""
        phase = event.data.get("phase", "")
        content = event.data.get("content", "")
        winner = event.data.get("winner", "")

        if phase == "start":
            return ContentOutput(
                output_type="status",
                round_number=round_number,
                text_content=content or "Post-evaluation started",
                text_style="bold magenta",
                text_class="status",
            )
        elif phase == "content":
            return ContentOutput(
                output_type="text",
                round_number=round_number,
                text_content=content or "",
                text_style="",
                text_class="content-inline",
            )
        elif phase == "end":
            label = f"Evaluation complete — winner: {winner}" if winner else "Evaluation complete"
            return ContentOutput(
                output_type="status",
                round_number=round_number,
                text_content=label,
                text_style="bold green",
                text_class="status",
            )
        return None

    def _handle_event_system_status(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle system_status event."""
        message = event.data.get("message", "")

        return ContentOutput(
            output_type="status",
            round_number=round_number,
            text_content=message,
            text_style="dim cyan",
            text_class="status",
        )

    def _handle_event_answer_submitted(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle answer_submitted coordination event.

        Creates a workspace/new_answer tool card matching the main TUI's
        notify_new_answer() rendering for subagent TUI parity.

        Note: Uses event's embedded round_number to ensure the answer is tagged
        with the round it was submitted IN, not the adapter's current round
        which may have advanced. The event system uses round_number=0 for
        initial round (display round 1), and post-restart rounds are already
        1-indexed (e.g., round_number=2 means display round 2).
        """
        # Event round_number=0 means initial round (display round 1)
        # Post-restart round_number is already the correct display round
        event_round = event.round_number if event.round_number > 0 else 1

        agent_id = event.agent_id or "unknown"
        label = event.data.get("answer_label", "")
        content = event.data.get("content", "")
        answer_number = event.data.get("answer_number", 1)
        preview = content[:100].replace("\n", " ")
        if len(content) > 100:
            preview += "..."

        tool_id = f"new_answer_{agent_id}_{answer_number}"
        now = datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now()

        tool_data = ToolDisplayData(
            tool_id=tool_id,
            tool_name="workspace/new_answer",
            display_name="Workspace/New Answer",
            tool_type="workspace",
            category="workspace",
            icon="\U0001f4dd",
            color="#4fc1ff",
            status="success",
            start_time=now,
            end_time=now,
            args_summary=f'content="{preview}"',
            args_full=f'content="{content}"',
            result_summary=f"Answer {label} submitted",
            result_full=content,
            elapsed_seconds=0.0,
        )

        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="tool",
            round_number=event_round,
            tool_data=tool_data,
            batch_action="standalone",
        )

    def _handle_event_vote(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle vote coordination event.

        Creates a workspace/vote tool card matching the main TUI's
        notify_vote() rendering for subagent TUI parity.

        Note: Uses event's embedded round_number to ensure the vote is tagged
        with the round it was cast IN, not the adapter's current round which
        may have advanced. The event system uses round_number=0 for initial
        round (display round 1), and post-restart rounds are already 1-indexed
        (e.g., round_number=4 means display round 4).
        """
        # Event round_number=0 means initial round (display round 1)
        # Post-restart round_number is already the correct display round
        event_round = event.round_number if event.round_number > 0 else 1

        voter = event.agent_id or "unknown"
        target = event.data.get("target_id", "unknown")
        reason = event.data.get("reason", "")

        tool_id = f"vote_{voter}_{id(event)}"
        now = datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now()

        result_text = f"Voted for {target}"
        if reason:
            result_text += f"\nReason: {reason}"

        tool_data = ToolDisplayData(
            tool_id=tool_id,
            tool_name="workspace/vote",
            display_name="Workspace/Vote",
            tool_type="workspace",
            category="workspace",
            icon="\U0001f5f3\ufe0f",
            color="#a371f7",
            status="success",
            start_time=now,
            end_time=now,
            args_summary=f'voted_for="{target}"',
            args_full=f'voted_for="{target}", reason="{reason}"',
            result_summary=f"Voted for {target}",
            result_full=result_text,
            elapsed_seconds=0.0,
        )

        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="tool",
            round_number=event_round,
            tool_data=tool_data,
            batch_action="standalone",
        )

    def _handle_event_agent_stopped(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle agent_stopped coordination event (decomposition mode).

        Creates a workspace/stop tool card for the subagent TUI parity.
        """
        event_round = event.round_number if event.round_number > 0 else 1

        agent_id = event.agent_id or "unknown"
        summary = event.data.get("summary", "")
        stop_status = event.data.get("status", "complete")

        tool_id = f"stop_{agent_id}_{id(event)}"
        now = datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.now()

        status_emoji = "\u2705" if stop_status == "complete" else "\u26a0\ufe0f"
        result_text = f"Stopped ({stop_status})"
        if summary:
            result_text += f"\nSummary: {summary}"

        tool_data = ToolDisplayData(
            tool_id=tool_id,
            tool_name="workspace/stop",
            display_name="Workspace/Stop",
            tool_type="workspace",
            category="workspace",
            icon=status_emoji,
            color="#3fb950",
            status="success",
            start_time=now,
            end_time=now,
            args_summary=f'status="{stop_status}"',
            args_full=f'status="{stop_status}", summary="{summary}"',
            result_summary=f"Stopped ({stop_status})",
            result_full=result_text,
            elapsed_seconds=0.0,
        )

        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="tool",
            round_number=event_round,
            tool_data=tool_data,
            batch_action="standalone",
        )

    def _handle_event_winner_selected(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[Union[ContentOutput, List[ContentOutput]]]:
        """Handle winner_selected coordination event.

        Creates a FinalPresentationCard in completion-only mode (no streaming
        content — the answer is already in the timeline via normal pipeline).
        """
        winner = event.agent_id or "unknown"
        vote_results_str = event.data.get("vote_results", "")

        # Parse vote_results if it's a string repr
        vote_counts: Dict[str, Any] = {}
        is_tie = False
        if vote_results_str:
            try:
                vr = ast.literal_eval(vote_results_str)
                if isinstance(vr, dict):
                    vote_counts = vr.get("vote_counts", {})
                    is_tie = vr.get("is_tie", False)
            except Exception:
                pass

        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="final_presentation_start",
            round_number=round_number,
            text_content="",
            text_style="",
            text_class="final_presentation",
            extra={
                "agent_id": winner,
                "vote_counts": vote_counts,
                "answer_labels": {},
                "is_tie": is_tie,
                "completion_only": True,
            },
        )

    def _handle_event_context_received(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle context_received coordination event."""
        # Context sharing is an internal orchestration detail — don't render
        return None

    def _handle_event_injection_received(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle injection_received event.

        The injection content is already carried by the preceding
        hook_execution event and attached to the tool card there.
        Suppress the standalone banner to avoid duplication.
        """
        return None

    def _handle_event_final_presentation_start(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle final_presentation_start event.

        Returns a ContentOutput with output_type="final_presentation_start"
        carrying vote_counts and answer_labels for the TUI pipeline to
        create a FinalPresentationCard.
        """
        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="final_presentation_start",
            round_number=round_number,
            text_content="",
            text_style="",
            text_class="final_presentation",
            extra={
                "agent_id": event.agent_id or "",
                "vote_counts": event.data.get("vote_counts", {}),
                "answer_labels": event.data.get("answer_labels", {}),
                "is_tie": event.data.get("is_tie", False),
            },
        )

    def _handle_event_final_presentation_chunk(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle final_presentation_chunk event — streamed content for the card."""
        content = event.data.get("content", "")
        if not content:
            return None
        return ContentOutput(
            output_type="final_presentation_chunk",
            round_number=round_number,
            text_content=content,
            text_style="",
            text_class="final_presentation",
        )

    def _handle_event_final_presentation_end(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle final_presentation_end event — marks the card as complete."""
        return ContentOutput(
            output_type="final_presentation_end",
            round_number=round_number,
            text_content="",
            text_style="",
            text_class="final_presentation",
            extra={"agent_id": event.agent_id or ""},
        )

    def _handle_event_answer_locked(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle answer_locked event — timeline locks to final answer."""
        return ContentOutput(
            output_type="answer_locked",
            round_number=round_number,
            text_content="",
            text_style="",
            text_class="",
            extra={"agent_id": event.agent_id or ""},
        )

    def _handle_event_orchestrator_timeout(
        self,
        event: MassGenEvent,
        round_number: int,
    ) -> Optional[ContentOutput]:
        """Handle orchestrator_timeout event.

        Returns a ContentOutput with structured timeout data for the TUI
        to render as a distinct banner card.
        """
        self._batch_tracker.mark_content_arrived()
        return ContentOutput(
            output_type="orchestrator_timeout",
            round_number=round_number,
            extra={
                "timeout_reason": event.data.get("timeout_reason", ""),
                "available_answers": event.data.get("available_answers", 0),
                "selected_agent": event.data.get("selected_agent"),
                "selection_reason": event.data.get("selection_reason", ""),
                "agent_answer_summary": event.data.get("agent_answer_summary", {}),
            },
        )

    def flush_pending_batch(self, round_number: int = 1) -> Optional[ContentOutput]:
        """Flush any pending tool batch and return it.

        Call this when done processing events to finalize any incomplete batch.

        Returns:
            ContentOutput with batch data, or None if no pending batch.
        """
        batch_id = self._batch_tracker.finalize_current_batch()
        if batch_id and self._event_pending_batch:
            tools = self._event_pending_batch.copy()
            self._event_pending_batch.clear()
            return ContentOutput(
                output_type="tool_batch",
                round_number=round_number,
                batch_tools=tools,
                batch_id=batch_id,
            )
        return None
