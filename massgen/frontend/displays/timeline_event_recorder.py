"""Timeline event recorder for events.jsonl parity debugging.

Uses TimelineEventAdapter with a mock panel/timeline so that ALL filtering,
dedup, and special-casing from the live TUI is applied identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from massgen.events import MassGenEvent

from .timeline_transcript import format_separator, format_text, format_tool
from .tui_event_pipeline import TimelineEventAdapter

logger = logging.getLogger(__name__)


class _MockTimeline:
    """Minimal mock that captures what the adapter would render."""

    def __init__(self, line_callback: Callable[[str], None]) -> None:
        self._cb = line_callback
        self._tools: dict[str, Any] = {}
        self._batches: dict[str, list[Any]] = {}
        self._tool_to_batch: dict[str, str] = {}
        self._deferred_round_banners: dict[int, tuple[str, str]] = {}
        self._shown_round_banners: set[int] = set()

    # --- Text / separators ---

    def add_text(
        self,
        content: str,
        *,
        style: str = "",
        text_class: str = "content-inline",
        round_number: int = 1,
    ) -> None:
        self._ensure_round_banner(round_number)
        self._cb(format_text(content, text_class, round_number))

    def add_separator(
        self,
        label: str,
        *,
        round_number: int = 1,
        subtitle: str = "",
    ) -> None:
        is_round = label.startswith("Round ")
        is_final = "FINAL" in label.upper()
        if is_round or is_final:
            self._shown_round_banners.add(round_number)
            self._deferred_round_banners.pop(round_number, None)
        self._cb(format_separator(label, round_number, subtitle))

    def defer_round_banner(self, round_number: int, label: str, subtitle: str | None = None) -> None:
        if round_number in self._shown_round_banners:
            return
        self._deferred_round_banners[round_number] = (label, subtitle or "")

    def _ensure_round_banner(self, round_number: int) -> None:
        if round_number in self._shown_round_banners:
            return
        if round_number in self._deferred_round_banners:
            label, subtitle = self._deferred_round_banners.pop(round_number)
        else:
            label, subtitle = (f"Round {round_number}", "")
        self._shown_round_banners.add(round_number)
        self._cb(format_separator(label, round_number, subtitle))

    # --- Tools ---

    def add_tool(self, tool_data: Any, *, round_number: int = 1) -> None:
        self._ensure_round_banner(round_number)
        self._tools[tool_data.tool_id] = (tool_data, round_number)
        action = "pending" if tool_data.status == "running" else "standalone"
        self._cb(format_tool(tool_data, round_number, action, server_name=getattr(tool_data, "server_name", None)))

    def update_tool(self, tool_id: str, tool_data: Any) -> None:
        prev = self._tools.get(tool_id)
        rn = prev[1] if prev else 1
        self._tools[tool_id] = (tool_data, rn)
        # In the real TUI, update_tool modifies an existing widget in-place
        # (e.g., changes status dot from orange to green). No new timeline
        # entry is created, so we only emit for meaningful status transitions.
        if prev and prev[0].status != tool_data.status:
            self._cb(format_tool(tool_data, rn, "update_standalone", server_name=getattr(tool_data, "server_name", None)))

    def get_tool(self, tool_id: str) -> Any | None:
        entry = self._tools.get(tool_id)
        return entry[0] if entry else None

    # --- Batches ---

    def add_batch(self, batch_id: str, server_name: str, *, round_number: int = 1) -> None:
        self._ensure_round_banner(round_number)
        self._batches[batch_id] = []

    def convert_tool_to_batch(
        self,
        pending_tool_id: str,
        tool_data: Any,
        batch_id: str,
        server_name: str,
        *,
        round_number: int = 1,
    ) -> None:
        self._ensure_round_banner(round_number)
        self._batches[batch_id] = []
        self._tool_to_batch[pending_tool_id] = batch_id
        self._tool_to_batch[tool_data.tool_id] = batch_id
        self._tools[tool_data.tool_id] = (tool_data, round_number)
        self._cb(format_tool(tool_data, round_number, "convert_to_batch", batch_id=batch_id, server_name=server_name))

    def add_tool_to_batch(self, batch_id: str, tool_data: Any) -> None:
        prev = self._tools.get(tool_data.tool_id)
        rn = prev[1] if prev else 1
        self._ensure_round_banner(rn)
        if batch_id in self._batches:
            self._batches[batch_id].append(tool_data)
        self._tool_to_batch[tool_data.tool_id] = batch_id
        self._tools[tool_data.tool_id] = (tool_data, rn)
        self._cb(format_tool(tool_data, rn, "add_to_batch", batch_id=batch_id, server_name=getattr(tool_data, "server_name", None)))

    def update_tool_in_batch(self, tool_id: str, tool_data: Any) -> None:
        batch_id = self._tool_to_batch.get(tool_id)
        prev = self._tools.get(tool_id)
        rn = prev[1] if prev else 1
        self._tools[tool_id] = (tool_data, rn)
        if not prev or prev[0].status != tool_data.status:
            self._cb(format_tool(tool_data, rn, "update_batch", batch_id=batch_id, server_name=getattr(tool_data, "server_name", None)))

    def get_tool_batch(self, tool_id: str) -> str | None:
        return self._tool_to_batch.get(tool_id)

    # --- No-ops for widget-specific calls ---

    def mount(self, widget: Any) -> None:
        pass

    def lock_to_final_answer(self, widget_id: str) -> None:
        pass

    def _close_reasoning_batch(self) -> None:
        pass


class _MockPanel:
    """Minimal mock panel that provides a timeline and agent_id."""

    def __init__(self, timeline: _MockTimeline, agent_id: str | None = None) -> None:
        self._timeline = timeline
        self.agent_id = agent_id

    def _get_timeline(self) -> _MockTimeline:
        return self._timeline

    def start_new_round(
        self,
        round_number: int,
        _is_context_reset: bool = False,
        defer_banner: bool = False,
    ) -> None:
        if defer_banner and hasattr(self._timeline, "defer_round_banner"):
            self._timeline.defer_round_banner(round_number, f"Round {round_number}", None)
        else:
            self._timeline.add_separator(f"Round {round_number}", round_number=round_number)


class TimelineEventRecorder:
    """Record timeline transcript lines from MassGen events.

    Wraps TimelineEventAdapter with mock widgets so all TUI filtering,
    dedup, and special-casing is applied identically to the live TUI.
    """

    def __init__(
        self,
        line_callback: Callable[[str], None],
        *,
        agent_ids: set[str] | None = None,
    ) -> None:
        self._line_callback = line_callback
        self._agent_ids = agent_ids
        self._timeline = _MockTimeline(line_callback)
        self._panel = _MockPanel(self._timeline)
        self._adapter = TimelineEventAdapter(self._panel)

    def reset(self) -> None:
        """Reset internal state for a fresh event stream."""
        self._timeline = _MockTimeline(self._line_callback)
        self._panel = _MockPanel(self._timeline)
        self._adapter = TimelineEventAdapter(self._panel)

    def handle_event(self, event: MassGenEvent) -> None:
        """Process a single event through the real TUI adapter pipeline.

        Applies the same agent_id filtering as the live TUI: only events
        whose agent_id is in the known agent set are processed.
        """
        if event.event_type == "timeline_entry":
            return
        if event.event_type == "stream_chunk":
            logger.debug("Skipping legacy stream_chunk event during replay")
            return
        # Mirror the live TUI's agent_id gate (textual_terminal_display.py L3001)
        if self._agent_ids is not None:
            aid = event.agent_id
            if not aid or aid not in self._agent_ids:
                return
        self._adapter.handle_event(event)

    def flush(self) -> None:
        """Flush pending tool batches."""
        self._adapter.flush()
