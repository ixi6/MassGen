# -*- coding: utf-8 -*-
"""
Content Section Widgets for MassGen TUI.

Composable UI sections for displaying different content types:
- ToolSection: Collapsible box containing tool cards
- TimelineSection: Chronological view with interleaved tools and text
- ThinkingSection: Streaming content area
- ResponseSection: Clean response display area
- StatusBadge: Compact inline status indicator
- CompletionFooter: Subtle completion indicator
"""

import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import RichLog, Static

from ..content_handlers import ToolDisplayData, get_mcp_tool_name
from ..shared.tui_debug import tui_log
from .collapsible_text_card import CollapsibleTextCard
from .tool_batch_card import ToolBatchCard, ToolBatchItem
from .tool_card import ToolCallCard

logger = logging.getLogger(__name__)


def _sanitize_widget_id(raw_id: str) -> str:
    """Sanitize a string for use as a Textual widget ID.

    Textual widget IDs must match ``[a-zA-Z_][a-zA-Z0-9_-]*``.  Some backends
    (e.g. OpenRouter/Kimi) produce tool IDs containing ``.`` and ``:`` which
    are invalid and cause silent mount failures.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw_id)


class ToolSection(Vertical):
    """Collapsible section containing tool call cards.

    Design:
    ```
    ┌ Tools ──────────────────────────────────────────────── 2 calls ┐
    │ 📁 read_file                                       ✓ 0.3s      │
    │ 💻 execute_command                                 ✓ 1.2s      │
    └────────────────────────────────────────────────────────────────┘
    ```

    When expanded, individual tools can also be expanded to show details.
    """

    is_collapsed = reactive(False)  # Default expanded to show tool activity
    tool_count = reactive(0)

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._tools: Dict[str, ToolCallCard] = {}
        self.add_class("collapsed")
        self.add_class("hidden")  # Start hidden until first tool

    def compose(self) -> ComposeResult:
        yield Static(
            self._build_header(),
            id="tool_section_header",
            classes="section-header",
        )
        yield ScrollableContainer(id="tool_container")

    def _build_header(self) -> Text:
        """Build the section header text."""
        text = Text()

        # Collapse indicator
        indicator = "▶" if self.is_collapsed else "▼"
        text.append(f"{indicator} ", style="dim")

        # Title
        text.append("Tools", style="bold")

        # Count badge
        if self.tool_count > 0:
            text.append(" ─" + "─" * 40 + "─ ", style="dim")
            text.append(
                f"{self.tool_count} call{'s' if self.tool_count != 1 else ''}",
                style="cyan",
            )

        return text

    def watch_is_collapsed(self, collapsed: bool) -> None:
        """Update UI when collapse state changes."""
        if collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")

        # Update header
        try:
            header = self.query_one("#tool_section_header", Static)
            header.update(self._build_header())
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def watch_tool_count(self, count: int) -> None:
        """Update header when tool count changes."""
        # Show section when we have tools
        if count > 0:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")

        try:
            header = self.query_one("#tool_section_header", Static)
            header.update(self._build_header())
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def on_click(self, event) -> None:
        """Toggle collapsed state on header click."""
        # Only toggle if clicking the header area
        try:
            header = self.query_one("#tool_section_header", Static)
            if event.widget == header or event.widget == self:
                self.is_collapsed = not self.is_collapsed
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def add_tool(self, tool_data: ToolDisplayData) -> ToolCallCard:
        """Add a new tool card.

        Args:
            tool_data: Tool display data from handler

        Returns:
            The created ToolCallCard for later updates
        """
        card = ToolCallCard(
            tool_name=tool_data.tool_name,
            tool_type=tool_data.tool_type,
            call_id=tool_data.tool_id,
            id=f"card_{_sanitize_widget_id(tool_data.tool_id)}",
        )

        # Set args preview if available (both truncated and full)
        if tool_data.args_summary:
            card.set_params(tool_data.args_summary, tool_data.args_full)

        self._tools[tool_data.tool_id] = card
        self.tool_count = len(self._tools)

        try:
            container = self.query_one("#tool_container", ScrollableContainer)
            container.mount(card)
            # Auto-scroll to show new tool
            container.scroll_end(animate=False)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        return card

    def update_tool(self, tool_id: str, tool_data: ToolDisplayData) -> None:
        """Update an existing tool card.

        Args:
            tool_id: The tool ID to update
            tool_data: Updated tool data
        """
        if tool_id not in self._tools:
            return

        card = self._tools[tool_id]

        # Apply args if available and not already set on card
        if tool_data.args_full and not card._params_full:
            args_summary = tool_data.args_summary or (tool_data.args_full[:77] + "..." if len(tool_data.args_full) > 80 else tool_data.args_full)
            card.set_params(args_summary, tool_data.args_full)

        if tool_data.status == "success":
            card.set_result(tool_data.result_summary or "", tool_data.result_full)
        elif tool_data.status == "error":
            card.set_error(tool_data.error or "Unknown error")
        elif tool_data.status == "background":
            card.set_background_result(
                tool_data.result_summary or "",
                tool_data.result_full,
                tool_data.async_id,
            )

        # Auto-scroll after update
        try:
            container = self.query_one("#tool_container", ScrollableContainer)
            container.scroll_end(animate=False)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def get_tool(self, tool_id: str) -> Optional[ToolCallCard]:
        """Get a tool card by ID."""
        return self._tools.get(tool_id)

    def get_running_tools_count(self) -> int:
        """Count tools that are currently running."""
        return sum(1 for card in self._tools.values() if card.status == "running")

    def clear(self) -> None:
        """Clear all tool cards."""
        try:
            container = self.query_one("#tool_container", ScrollableContainer)
            container.remove_children()
        except Exception as e:
            tui_log(f"[ContentSections] {e}")
        self._tools.clear()
        self.tool_count = 0
        self.add_class("hidden")


class ReasoningSection(Vertical):
    """Collapsible section for agent coordination/reasoning content.

    Groups voting, reasoning, and internal coordination content together
    in a collapsible section. Collapsed by default but can be expanded
    to see the full reasoning.

    Design (collapsed):
    ```
    ▶ 🧠 Reasoning (5 items) ─────────────────────────────────────────
    ```

    Design (expanded):
    ```
    ▼ 🧠 Reasoning ───────────────────────────────────────────────────
    │ I'll vote for Agent 1 because the answer is clear...
    │ The existing answers are correct and complete.
    │ Agent 2 provides a concise explanation.
    │ ...
    └─────────────────────────────────────────────────────────────────
    ```
    """

    # Start expanded, auto-collapse after threshold
    is_collapsed = reactive(False)
    item_count = reactive(0)
    COLLAPSE_THRESHOLD = 5  # Auto-collapse after this many items
    PREVIEW_LINES = 2  # Show this many lines when collapsed

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._items: list = []
        # Start expanded (not collapsed) but hidden until content arrives
        self.add_class("hidden")

    def compose(self) -> ComposeResult:
        yield Static(self._build_header(), id="reasoning_header")
        yield ScrollableContainer(id="reasoning_content")

    def _build_header(self) -> Text:
        """Build the section header text."""
        text = Text()

        # Collapse indicator
        indicator = "▶" if self.is_collapsed else "▼"
        text.append(f"{indicator} ", style="cyan")

        # Icon and title
        text.append("💭 ", style="")
        text.append("Reasoning", style="bold #c9d1d9")

        # Count badge - show hidden count when collapsed
        if self.item_count > 0:
            if self.is_collapsed and self.item_count > self.PREVIEW_LINES:
                hidden = self.item_count - self.PREVIEW_LINES
                text.append(f"  (+{hidden} more)", style="dim cyan")
            else:
                text.append(f"  ({self.item_count})", style="dim")

        return text

    def watch_is_collapsed(self, collapsed: bool) -> None:
        """Update UI when collapse state changes."""
        if collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")

        try:
            header = self.query_one("#reasoning_header", Static)
            header.update(self._build_header())
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def watch_item_count(self, count: int) -> None:
        """Update header when item count changes."""
        if count > 0:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")

        try:
            header = self.query_one("#reasoning_header", Static)
            header.update(self._build_header())
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def on_click(self, event) -> None:
        """Toggle collapsed state on header click."""
        try:
            header = self.query_one("#reasoning_header", Static)
            if event.widget == header or event.widget == self:
                self.is_collapsed = not self.is_collapsed
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def add_content(self, content: str) -> None:
        """Add reasoning content.

        Args:
            content: Reasoning/coordination text
        """
        if not content.strip():
            return

        self._items.append(content)
        self.item_count = len(self._items)

        try:
            container = self.query_one("#reasoning_content", ScrollableContainer)

            # Format content with bullet point for structure
            formatted = Text()
            formatted.append("• ", style="cyan")
            formatted.append(content, style="#c9d1d9")

            widget = Static(
                formatted,
                id=f"reasoning_{self.item_count}",
                classes="reasoning-text",
            )
            container.mount(widget)

            # Auto-collapse after threshold (but still show preview)
            if self.item_count > self.COLLAPSE_THRESHOLD and not self.is_collapsed:
                self.is_collapsed = True

        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def clear(self) -> None:
        """Clear all reasoning content."""
        try:
            container = self.query_one("#reasoning_content", ScrollableContainer)
            container.remove_children()
        except Exception as e:
            tui_log(f"[ContentSections] {e}")
        self._items.clear()
        self.item_count = 0
        self.add_class("hidden")


class TimelineSection(ScrollableContainer):
    """Chronological timeline showing tools and text interleaved.

    This widget displays content in the order it arrives, preserving
    the natural flow of agent activity. Tool cards and text blocks
    appear inline as they occur.

    Coordination/reasoning content is grouped into a collapsible
    ReasoningSection at the top of the timeline.

    Note: TimelineSection inherits from ScrollableContainer directly,
    eliminating the nested container architecture that caused scrollbar
    thumb position sync issues. All content is mounted directly into
    this widget.

    Design:
    ```
    ▶ 🧠 Reasoning (5 items) ─────────────────────────────────────────

    │ Let me help you with that...                                    │
    │                                                                 │
    │ ▶ 📁 filesystem/read_file                         ⏳ running... │
    │   {"path": "/tmp/test.txt"}                                     │
    │                                                                 │
    │   📁 filesystem/read_file                              ✓ (0.3s) │
    │   {"path": "/tmp/test.txt"}                                     │
    │   → File contents: Hello world...                               │
    │                                                                 │
    │ The file contains: Hello world                                  │
    ```
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Maximum number of items to keep in timeline (prevents memory/performance issues)
    MAX_TIMELINE_ITEMS = 30  # Viewport culling threshold
    SCROLL_DEBOUNCE_MS = 25  # Minimum gap between scroll operations (reduced for responsiveness)
    SCROLL_ANIMATION_THRESHOLD_MS = 300  # Threshold for animation vs instant scroll

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._tools: Dict[str, ToolCallCard] = {}
        self._batches: Dict[str, ToolBatchCard] = {}  # batch_id -> ToolBatchCard
        self._tool_to_batch: Dict[str, str] = {}  # tool_id -> batch_id mapping
        self._tool_rounds: Dict[str, int] = {}  # tool_id -> round_number
        self._item_count = 0
        self._reasoning_section_id = f"reasoning_{id}" if id else "reasoning_section"
        # Scroll mode: when True, auto-scroll is paused (user is reading history)
        self._scroll_mode = False
        self._new_content_count = 0  # Count of new items since entering scroll mode
        # Removed widgets cache for scroll-back (widget ID -> widget)
        self._removed_widgets: Dict[str, any] = {}
        self._truncation_shown = False  # Track if we've shown truncation message
        # Phase 12: View-based round navigation
        self._viewed_round: int = 1  # Which round is currently being displayed
        # Content batch: accumulates consecutive thinking/content into single card
        self._current_reasoning_card: Optional[CollapsibleTextCard] = None
        self._current_batch_label: Optional[str] = None  # Track label for batch switching
        # Scroll detection flags (moved from TimelineScrollContainer)
        self._user_scrolled_up = False
        self._auto_scrolling = False
        self._scroll_pending = False
        self._debug_scroll = True  # Debug flag (enabled for debugging compression)
        # Performance: Time-based scroll debouncing (QUICK-002)
        self._last_scroll_time: float = 0.0
        # Performance: Cancel previous timer before creating new one (QUICK-004)
        self._scroll_timer = None
        # Deferred scroll pattern: ensures scroll happens even when debounced
        self._scroll_requested = False
        self._debounce_timer = None
        # Answer lock mode: when True, timeline shows only the final answer card
        self._answer_lock_mode = False
        self._locked_card_id: Optional[str] = None
        # Track if Round 1 banner has been shown
        self._round_1_shown = False
        # Track highest round separator shown (for dedup)
        self._last_round_shown = 0
        # Track pending round separators to avoid duplicates before mount completes
        self._pending_round_separators: set[int] = set()
        # Track which rounds already have banners
        self._shown_round_banners: set[int] = set()
        # Track deferred round banners (round_number -> (label, subtitle))
        self._deferred_round_banners: Dict[int, tuple[str, Optional[str]]] = {}

    def compose(self) -> ComposeResult:
        # Scroll mode indicator (hidden by default)
        yield Static("", id="scroll_mode_indicator", classes="scroll-indicator hidden")
        # Content is mounted directly into TimelineSection (no nested container)
        # Winner hint is mounted dynamically at the end when needed

    def show_winner_hint(self, show: bool = True) -> None:
        """Show or hide the winner navigation hint at the bottom of the timeline."""
        try:
            hint = self.query_one("#winner_hint", Static)
            if show:
                hint.remove_class("hidden")
            else:
                hint.add_class("hidden")
        except Exception:
            # Hint doesn't exist yet - mount it if we need to show it
            if show:
                hint = Static(
                    "─────────────── Press f to see final answer ───────────────",
                    id="winner_hint",
                    classes="winner-hint",
                )
                self.mount(hint)  # Mounts at end of children

    def _ensure_round_1_shown(self) -> None:
        """Ensure Round 1 banner is shown before any content."""
        self._ensure_round_banner(1)

    def defer_round_banner(self, round_number: int, label: str, subtitle: Optional[str] = None) -> None:
        """Defer a round banner until the first item of that round is rendered."""
        if round_number in self._shown_round_banners:
            return
        self._deferred_round_banners[round_number] = (label, subtitle)

    def _ensure_round_banner(self, round_number: int) -> None:
        """Ensure the Round X banner appears before the first content of that round."""
        round_number = max(1, int(round_number))
        has_banner = self._has_round_banner(round_number)
        try:
            from massgen.frontend.displays.shared.tui_debug import tui_log

            tui_log(
                f"[ROUND_DEBUG] ensure_round_banner panel={self.id} round={round_number} " f"round_1_shown={self._round_1_shown} has_banner={has_banner}",
                level="info",
            )
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        if has_banner:
            self._shown_round_banners.add(round_number)
            self._last_round_shown = max(self._last_round_shown, round_number)
            if round_number == 1:
                self._round_1_shown = True
            return
        if round_number == 1 and self._round_1_shown:
            return
        if round_number in self._shown_round_banners:
            return
        if round_number in self._pending_round_separators:
            return

        label, subtitle = self._deferred_round_banners.pop(
            round_number,
            (f"Round {round_number}", None),
        )
        insert_before = None
        try:
            indicator = self.query_one("#scroll_mode_indicator", Static)
        except Exception:
            indicator = None
        for child in self.children:
            if indicator is not None and child is indicator:
                continue
            if f"round-{round_number}" in child.classes:
                insert_before = child
                break
        if insert_before is None:
            insert_before = self._find_insert_before_for_round(round_number)
        if round_number == 1:
            self._round_1_shown = True
        self.add_separator(
            label,
            round_number=round_number,
            subtitle=subtitle or "",
            before=insert_before,
        )

    def _has_round_banner(self, round_number: int) -> bool:
        """Check if a RestartBanner exists for the given round."""
        try:
            for widget in self.query(f".round-{round_number}"):
                if isinstance(widget, RestartBanner):
                    return True
        except Exception as e:
            tui_log(f"[ContentSections] {e}")
        return False

    def _first_content_child(self) -> Optional[Any]:
        """Get the first timeline child after the scroll indicator, if any."""
        try:
            indicator = self.query_one("#scroll_mode_indicator", Static)
        except Exception:
            indicator = None

        for child in self.children:
            if indicator is not None and child is indicator:
                continue
            return child
        return None

    def _find_insert_before_for_round(self, round_number: int) -> Optional[Any]:
        """Find the earliest widget belonging to a later round.

        This allows late-arriving items from an earlier round to be inserted
        before the next round's banner/content.
        """
        try:
            indicator = self.query_one("#scroll_mode_indicator", Static)
        except Exception:
            indicator = None

        for child in self.children:
            if indicator is not None and child is indicator:
                continue
            if not hasattr(child, "classes"):
                continue
            for cls in child.classes:
                if not cls.startswith("round-"):
                    continue
                try:
                    child_round = int(cls.split("-", 1)[1])
                except Exception:
                    continue
                if child_round > round_number:
                    return child
        return None

    def _log(self, msg: str) -> None:
        """Debug logging helper."""
        if self._debug_scroll:
            from datetime import datetime

            with open(os.path.join(tempfile.gettempdir(), "scroll_debug.log"), "a") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Detect when user scrolls away from bottom.

        IMPORTANT: Must call super() to update the scrollbar position!
        """
        # Call parent's watch_scroll_y to update scrollbar position
        super().watch_scroll_y(old_value, new_value)

        self._log(f"watch_scroll_y: scroll_y={new_value:.1f} max={self.max_scroll_y:.1f} auto={self._auto_scrolling}")

        if self._auto_scrolling:
            return  # Ignore programmatic scrolls

        # Don't trigger scroll mode if there's no scrollable content yet
        if self.max_scroll_y <= 0:
            return

        # Check if at bottom (with tolerance for float precision)
        at_bottom = new_value >= self.max_scroll_y - 2

        if new_value < old_value and not at_bottom:
            # User scrolled up - enter scroll mode
            if not self._user_scrolled_up:
                self._user_scrolled_up = True
                if not self._scroll_mode:
                    self._scroll_mode = True
                    self._new_content_count = 0
                    self._update_scroll_indicator()
        elif at_bottom and self._user_scrolled_up:
            # User scrolled to bottom - exit scroll mode
            self._user_scrolled_up = False
            if self._scroll_mode:
                self._scroll_mode = False
                self._new_content_count = 0
                self._update_scroll_indicator()

    def refresh_scrollbar(self) -> None:
        """Force refresh of the vertical scrollbar.

        Call this after mounting content to ensure the scrollbar
        position indicator reflects the new content size and scroll position.
        Textual automatically syncs scrollbar position from scroll_y.
        """
        try:
            vscroll = self.vertical_scrollbar
            if vscroll:
                vscroll.refresh()
                self._log(f"refresh_scrollbar: scroll_y={self.scroll_y:.1f} max={self.max_scroll_y:.1f}")
        except Exception as e:
            self._log(f"refresh_scrollbar error: {e}")

    def _reset_auto_scroll(self) -> None:
        """Reset auto-scrolling flag after scroll completes."""
        self._log(f"_reset_auto_scroll: scroll_y={self.scroll_y:.1f}")
        self._auto_scrolling = False

    def reset_scroll_mode(self) -> None:
        """Reset scroll mode tracking state."""
        self._user_scrolled_up = False

    def _update_scroll_indicator(self) -> None:
        """Update the scroll mode indicator in the UI."""
        try:
            indicator = self.query_one("#scroll_mode_indicator", Static)
            if self._scroll_mode:
                # Compact pill format
                if self._new_content_count > 0:
                    msg = f"↑ Scrolling ({self._new_content_count} new) · q/Esc"
                else:
                    msg = "↑ Scrolling · q/Esc"
                indicator.update(msg)
                indicator.remove_class("hidden")
            else:
                indicator.add_class("hidden")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def _auto_scroll(self) -> None:
        """Scroll to end only if not in scroll mode."""
        self._log(f"[AUTO_SCROLL] Called: scroll_mode={self._scroll_mode}, max_scroll_y={self.max_scroll_y:.2f}, scroll_y={self.scroll_y:.2f}")
        if self._scroll_mode:
            self._new_content_count += 1
            self._update_scroll_indicator()  # Update to show new content count
            return
        # Use smooth animated scrolling for better UX
        self._scroll_to_end(animate=True)

    def _scroll_to_end(self, animate: bool = True, duration: float = 0.15, force: bool = False) -> None:
        """Auto-scroll to end with smooth animation.

        Uses a deferred scroll pattern: if called during debounce window,
        marks that scroll is needed and ensures it happens after debounce.

        Args:
            animate: Whether to animate the scroll (default True for smooth UX)
            duration: Animation duration in seconds (default 0.15s)
            force: If True, bypass debounce (e.g., when switching tabs)
        """
        self._log(f"_scroll_to_end called: pending={self._scroll_pending} force={force} max_scroll_y={self.max_scroll_y:.1f} current_scroll_y={self.scroll_y:.1f}")

        current_time = time.monotonic()
        time_since_last = current_time - self._last_scroll_time

        # Force mode bypasses debounce (e.g., explicit user actions like tab switching)
        if not force:
            # If scroll already pending, mark that we need another scroll after
            if self._scroll_pending:
                self._scroll_requested = True
                self._log("_scroll_to_end: marked for deferred scroll (pending)")
                return

            # Time-based debouncing - but DON'T drop the request, defer it
            if time_since_last < (self.SCROLL_DEBOUNCE_MS / 1000.0):
                self._scroll_requested = True
                self._log(f"_scroll_to_end: deferred (debounce: {time_since_last*1000:.1f}ms < {self.SCROLL_DEBOUNCE_MS}ms)")
                # Schedule deferred scroll if not already scheduled
                if self._debounce_timer is None:
                    remaining_ms = self.SCROLL_DEBOUNCE_MS - (time_since_last * 1000)
                    self._debounce_timer = self.set_timer(
                        remaining_ms / 1000.0,
                        self._execute_deferred_scroll,
                    )
                return

        self._scroll_pending = True
        self._scroll_requested = False  # Clear any pending request

        def do_scroll() -> None:
            self._log(f"do_scroll executing: max_scroll_y={self.max_scroll_y:.1f} scroll_y before={self.scroll_y:.1f}")
            self._scroll_pending = False
            self._last_scroll_time = time.monotonic()
            self._auto_scrolling = True

            # Use named constant for animation threshold
            use_animation = animate and self.max_scroll_y > 0 and time_since_last > (self.SCROLL_ANIMATION_THRESHOLD_MS / 1000.0)

            if use_animation:
                self.scroll_to(y=self.max_scroll_y, animate=True, duration=duration, easing="out_cubic")
            else:
                # Fast path: no animation during streaming
                self.scroll_end(animate=False)

            self._log(f"do_scroll after scroll: scroll_y={self.scroll_y:.1f}")

            # QUICK-004: Cancel previous timer before creating new one
            if self._scroll_timer is not None:
                try:
                    self._scroll_timer.stop()
                except Exception as e:
                    tui_log(f"[ContentSections] {e}")  # Timer may have already completed
            self._scroll_timer = self.set_timer(
                duration + 0.1 if use_animation else 0.1,
                self._reset_auto_scroll,
            )

            # Check if another scroll was requested while we were pending
            if self._scroll_requested:
                self._scroll_requested = False
                self.call_after_refresh(lambda: self._scroll_to_end(animate=False))

        # Defer scroll until after layout is complete
        self.call_after_refresh(do_scroll)

    def _execute_deferred_scroll(self) -> None:
        """Execute a deferred scroll after debounce period."""
        self._debounce_timer = None
        if self._scroll_requested:
            self._scroll_requested = False
            self._scroll_to_end(animate=False)

    def exit_scroll_mode(self) -> None:
        """Exit scroll mode and scroll to bottom."""
        self._scroll_mode = False
        self._new_content_count = 0
        self.reset_scroll_mode()  # Reset scroll state
        self._scroll_to_end(animate=False, force=True)
        self._update_scroll_indicator()

    def scroll_to_widget(self, widget_id: str) -> None:
        """Scroll to bring a specific widget to the top of the view.

        Args:
            widget_id: The ID of the widget to scroll to (without #)
        """
        try:
            # Find the widget by ID (content is mounted directly in TimelineSection)
            target = self.query_one(f"#{widget_id}")
            if target:
                # Scroll so the widget is at the top
                target.scroll_visible(top=True, animate=False)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    @property
    def in_scroll_mode(self) -> bool:
        """Whether scroll mode is active."""
        return self._scroll_mode

    @property
    def new_content_count(self) -> int:
        """Number of new items since entering scroll mode."""
        return self._new_content_count

    @property
    def is_answer_locked(self) -> bool:
        """Whether the timeline is locked to show only the final answer."""
        return self._answer_lock_mode

    def lock_to_final_answer(self, card_id: str) -> None:
        """Lock timeline to show only the final answer card.

        Hides all other timeline content and makes the final card fill
        the available space for better readability.

        Args:
            card_id: The ID of the FinalPresentationCard to lock to
        """
        from massgen.frontend.displays.shared.tui_debug import tui_log

        tui_log(f"[LOCK] lock_to_final_answer called: card_id={card_id}, already_locked={self._answer_lock_mode}")

        if self._answer_lock_mode:
            return  # Already locked

        self._answer_lock_mode = True
        self._locked_card_id = card_id

        # Add lock mode class to timeline
        self.add_class("answer-locked")

        # Hide all children except the final card
        children = list(self.children)
        tui_log(f"[LOCK] Found {len(children)} children, timeline height={self.size.height}")
        card_found = False
        for child in children:
            child_id = getattr(child, "id", None)
            if child_id != card_id:
                child.add_class("answer-lock-hidden")
            else:
                card_found = True
                # Check if terminal is too small for full presentation
                if self.size.height < 15:
                    tui_log(f"[LOCK] Using compact mode (height={self.size.height})")
                    child.add_class("final-card-compact")
                else:
                    tui_log(f"[LOCK] Using locked mode (height={self.size.height})")
                    child.add_class("final-card-locked")

        if not card_found:
            tui_log(f"[LOCK] WARNING: Card with id={card_id} not found among children!")

    def unlock_final_answer(self) -> None:
        """Unlock timeline to show all content.

        Restores normal timeline view with all tools and text visible.
        """
        from massgen.frontend.displays.shared.tui_debug import tui_log

        if not self._answer_lock_mode:
            return  # Already unlocked

        tui_log(f"[LOCK] unlock_final_answer called, locked_card_id={self._locked_card_id}")

        self._answer_lock_mode = False
        card_id = self._locked_card_id

        # Remove lock mode class from timeline
        self.remove_class("answer-locked")

        # Show all children again
        for child in self.children:
            child.remove_class("answer-lock-hidden")
            child.remove_class("final-card-locked")
            child.remove_class("final-card-compact")

        self._locked_card_id = None

        # Scroll to show the final card (scroll to it specifically, not just end)
        if card_id:
            try:
                card = self.query_one(f"#{card_id}")
                card.scroll_visible(animate=True, top=True)
                tui_log(f"[LOCK] Scrolled to card {card_id}")
            except Exception as e:
                tui_log(f"[LOCK] Could not scroll to card: {e}")
                self._scroll_to_end(animate=False, force=True)
        else:
            self._scroll_to_end(animate=False, force=True)

    def on_resize(self, event) -> None:
        """Handle resize events to switch between compact and full modes."""
        if self._answer_lock_mode and self._locked_card_id:
            try:
                card = self.query_one(f"#{self._locked_card_id}")
                if self.size.height < 15:
                    card.remove_class("final-card-locked")
                    card.add_class("final-card-compact")
                else:
                    card.remove_class("final-card-compact")
                    card.add_class("final-card-locked")
            except Exception:
                pass

    def _trim_old_items(self) -> None:
        """ARCH-001: Cull items outside viewport using visibility toggling.

        Instead of removing items from DOM, we hide them with CSS display:none.
        This preserves scroll-back capability and tool state while maintaining
        performance by not rendering hidden items.
        """
        try:
            children = list(self.children)

            # Skip special UI elements
            content_children = [c for c in children if "scroll-indicator" not in c.classes and "truncation-notice" not in c.classes]

            total_items = len(content_children)

            self._log(f"[TRIM] Starting trim: total_items={total_items}, MAX={self.MAX_TIMELINE_ITEMS}, max_scroll_y_before={self.max_scroll_y:.2f}")

            # If under limit, restore any removed items
            if total_items <= self.MAX_TIMELINE_ITEMS:
                # Check if we have removed widgets to restore
                if self._removed_widgets:
                    self._log(f"[TRIM] Under limit, restoring {len(self._removed_widgets)} removed widgets")
                    # Note: Restoring would require preserving original order, which is complex
                    # For now, just clear the cache when we go back under limit
                    # In practice, items rarely go back under the limit
                return

            # Calculate how many to hide
            items_to_hide = total_items - self.MAX_TIMELINE_ITEMS

            if items_to_hide <= 0:
                return

            self._log(f"[TRIM] Hiding {items_to_hide} items (keeping {self.MAX_TIMELINE_ITEMS})")

            # Remove oldest items from DOM (but keep in cache for scroll-back)
            hidden_count = 0
            for child in content_children[:items_to_hide]:
                # Don't hide tool cards that are still running
                if hasattr(child, "tool_id") and child.tool_id in self._tools:
                    tool_card = self._tools.get(child.tool_id)
                    if tool_card and hasattr(tool_card, "_status") and tool_card._status == "running":
                        self._log(f"[TRIM] Skipping running tool: {child.tool_id}")
                        continue

                # Actually remove from DOM to free up space
                # Cache it for potential scroll-back restoration
                if child.id and child in self.children:
                    self._removed_widgets[child.id] = child
                    child.remove()
                    hidden_count += 1

            # Note: We don't need to "show" remaining items since they're already in DOM

            self._log(f"[TRIM] Actually hid {hidden_count} items")

        except Exception as e:
            self._log(f"[TRIM] Exception: {e}")

    def add_tool(self, tool_data: ToolDisplayData, round_number: int = 1) -> ToolCallCard:
        """Add a tool card to the timeline.

        Args:
            tool_data: Tool display data
            round_number: The round this content belongs to (for view switching)

        Returns:
            The created ToolCallCard
        """
        # Ensure this round's banner is shown before first content
        self._ensure_round_banner(round_number)

        # Close any open reasoning batch when tool arrives
        self._close_reasoning_batch()

        # Debug logging - include widget ID to identify which panel
        widget_id = self.id or "unknown"
        from massgen.frontend.displays.shared.tui_debug import tui_log

        tui_log(f"TimelineSection.add_tool: panel={widget_id}, tool={tool_data.tool_name}, round={round_number}, viewed={self._viewed_round}")
        try:
            from massgen.frontend.displays.timeline_transcript import record_tool

            record_tool(tool_data, round_number, action="add")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        card = ToolCallCard(
            tool_name=tool_data.tool_name,
            tool_type=tool_data.tool_type,
            call_id=tool_data.tool_id,
            id=f"tl_card_{_sanitize_widget_id(tool_data.tool_id)}",
        )

        if tool_data.args_summary:
            card.set_params(tool_data.args_summary, tool_data.args_full)

        # Tag with round class for navigation (scroll-to behavior)
        card.add_class(f"round-{round_number}")

        self._tools[tool_data.tool_id] = card
        self._tool_rounds[tool_data.tool_id] = round_number
        self._item_count += 1

        try:
            insert_before = self._find_insert_before_for_round(round_number)
            self.mount(card, before=insert_before)

            from datetime import datetime

            tui_log(
                f"[MOUNT_DEBUG] add_tool: round={round_number} tool={tool_data.tool_name} " f"time={datetime.now().isoformat()}",
            )

            # Defer trim and scroll until after mount completes
            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        return card

    def update_tool(self, tool_id: str, tool_data: ToolDisplayData) -> None:
        """Update an existing tool card.

        Args:
            tool_id: Tool ID to update
            tool_data: Updated tool data
        """
        if tool_id not in self._tools:
            return
        try:
            from massgen.frontend.displays.timeline_transcript import record_tool

            round_number = self._tool_rounds.get(tool_id, self._viewed_round)
            record_tool(tool_data, round_number, action="update")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        card = self._tools[tool_id]

        # Apply args if available and not already set on card
        if tool_data.args_full and not card._params_full:
            args_summary = tool_data.args_summary or (tool_data.args_full[:77] + "..." if len(tool_data.args_full) > 80 else tool_data.args_full)
            card.set_params(args_summary, tool_data.args_full)

        if tool_data.status == "success":
            card.set_result(tool_data.result_summary or "", tool_data.result_full)
        elif tool_data.status == "error":
            card.set_error(tool_data.error or "Unknown error")
        elif tool_data.status == "background":
            card.set_background_result(
                tool_data.result_summary or "",
                tool_data.result_full,
                tool_data.async_id,
            )

        self._auto_scroll()

    def get_tool(self, tool_id: str) -> Optional[ToolCallCard]:
        """Get a tool card by ID."""
        return self._tools.get(tool_id)

    def get_running_tools_count(self) -> int:
        """Count tools that are currently running or running in background."""
        return sum(1 for card in self._tools.values() if card.status in ("running", "background"))

    def get_background_tools_count(self) -> int:
        """Count tools that are running in background (async operations).

        Note: We don't check if shells are still alive because background shells
        run in separate MCP subprocess(es), not in the main TUI process.
        The shell manager singleton is per-process, so we can't check cross-process.
        """
        return sum(1 for card in self._tools.values() if card.status == "background")

    def get_background_tools(self) -> list:
        """Get list of background tool data for modal display.

        Note: We don't filter by shell alive status because shells run in MCP
        subprocesses with their own BackgroundShellManager singleton.
        """
        bg_tools = []
        for card in self._tools.values():
            if card.status == "background":
                bg_tools.append(
                    {
                        "tool_name": card.tool_name,
                        "display_name": card._display_name,
                        "async_id": card._async_id,
                        "start_time": card._start_time,
                        "result": card._result,
                    },
                )
        return bg_tools

    # === Batch Card Methods ===

    def add_batch(self, batch_id: str, server_name: str, round_number: int = 1) -> ToolBatchCard:
        """Create a new batch card for grouping MCP tools from the same server.

        Args:
            batch_id: Unique ID for this batch
            server_name: MCP server name (e.g., "filesystem")
            round_number: Round number for CSS visibility

        Returns:
            The created ToolBatchCard
        """
        # Ensure this round's banner is shown before first content
        self._ensure_round_banner(round_number)

        card = ToolBatchCard(
            server_name=server_name,
            id=f"batch_{batch_id}",
        )

        # Tag with round class for navigation (scroll-to behavior)
        card.add_class(f"round-{round_number}")

        self._batches[batch_id] = card
        self._item_count += 1
        try:
            from massgen.frontend.displays.timeline_transcript import record_batch

            record_batch(round_number, "start", batch_id, server_name)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        try:
            insert_before = self._find_insert_before_for_round(round_number)
            self.mount(card, before=insert_before)

            # Defer trim and scroll until after mount completes
            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        return card

    def add_tool_to_batch(
        self,
        batch_id: str,
        tool_data: ToolDisplayData,
    ) -> None:
        """Add a tool to an existing batch card.

        Args:
            batch_id: ID of the batch to add to
            tool_data: Tool display data
        """
        if batch_id not in self._batches:
            return

        batch_card = self._batches[batch_id]

        # Create ToolBatchItem from ToolDisplayData
        from datetime import datetime

        mcp_tool_name = get_mcp_tool_name(tool_data.tool_name) or tool_data.tool_name
        item = ToolBatchItem(
            tool_id=tool_data.tool_id,
            tool_name=tool_data.tool_name,
            display_name=mcp_tool_name,
            status=tool_data.status,
            args_summary=tool_data.args_summary,
            args_full=tool_data.args_full,
            start_time=tool_data.start_time or datetime.now(),
        )

        batch_card.add_tool(item)
        self._tool_to_batch[tool_data.tool_id] = batch_id
        self._tool_rounds[tool_data.tool_id] = self._viewed_round
        self._auto_scroll()
        try:
            from massgen.frontend.displays.timeline_transcript import record_batch_tool

            round_number = self._tool_rounds.get(tool_data.tool_id, self._viewed_round)
            record_batch_tool(tool_data, round_number, batch_id, "add")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def update_tool_in_batch(self, tool_id: str, tool_data: ToolDisplayData) -> bool:
        """Update a tool within a batch card.

        Args:
            tool_id: ID of the tool to update
            tool_data: Updated tool data

        Returns:
            True if tool was found and updated, False otherwise
        """
        batch_id = self._tool_to_batch.get(tool_id)
        if not batch_id or batch_id not in self._batches:
            return False

        batch_card = self._batches[batch_id]
        mcp_tool_name = get_mcp_tool_name(tool_data.tool_name) or tool_data.tool_name

        # Calculate elapsed time
        elapsed_seconds = None
        if tool_data.elapsed_seconds is not None:
            elapsed_seconds = tool_data.elapsed_seconds
        elif tool_data.start_time and tool_data.end_time:
            elapsed_seconds = (tool_data.end_time - tool_data.start_time).total_seconds()

        item = ToolBatchItem(
            tool_id=tool_data.tool_id,
            tool_name=tool_data.tool_name,
            display_name=mcp_tool_name,
            status=tool_data.status,
            args_summary=tool_data.args_summary,
            args_full=tool_data.args_full,
            result_summary=tool_data.result_summary,
            result_full=tool_data.result_full,
            error=tool_data.error,
            start_time=tool_data.start_time,
            end_time=tool_data.end_time,
            elapsed_seconds=elapsed_seconds,
        )

        batch_card.update_tool(tool_id, item)
        self._auto_scroll()
        try:
            from massgen.frontend.displays.timeline_transcript import record_batch_tool

            round_number = self._tool_rounds.get(tool_id, self._viewed_round)
            record_batch_tool(tool_data, round_number, batch_id, "update")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")
        return True

    def get_batch(self, batch_id: str) -> Optional[ToolBatchCard]:
        """Get a batch card by ID."""
        return self._batches.get(batch_id)

    def get_tool_batch(self, tool_id: str) -> Optional[str]:
        """Get the batch ID for a tool, if it's in a batch."""
        return self._tool_to_batch.get(tool_id)

    def convert_tool_to_batch(
        self,
        pending_tool_id: str,
        new_tool_data: ToolDisplayData,
        batch_id: str,
        server_name: str,
        round_number: int = 1,
    ) -> Optional[ToolBatchCard]:
        """Convert a standalone tool card to a batch and add a second tool.

        This is called when a second consecutive MCP tool from the same server arrives.
        It removes the original standalone ToolCallCard and creates a ToolBatchCard
        containing both tools.

        Args:
            pending_tool_id: ID of the existing standalone tool to convert
            new_tool_data: The second tool's data
            batch_id: ID for the new batch
            server_name: MCP server name
            round_number: Round number for CSS visibility

        Returns:
            The created ToolBatchCard, or None if conversion failed
        """
        from datetime import datetime

        # Get the existing tool card
        existing_card = self._tools.get(pending_tool_id)
        if not existing_card:
            return None

        # Extract data from existing card to create batch item
        first_item = ToolBatchItem(
            tool_id=pending_tool_id,
            tool_name=existing_card.tool_name,
            display_name=get_mcp_tool_name(existing_card.tool_name) or existing_card._display_name,
            status=existing_card.status,
            args_summary=existing_card._params,
            args_full=existing_card._params_full,
            result_summary=existing_card._result,
            result_full=existing_card._result_full,
            start_time=existing_card._start_time,
        )

        # Create second item from new tool data
        second_item = ToolBatchItem(
            tool_id=new_tool_data.tool_id,
            tool_name=new_tool_data.tool_name,
            display_name=get_mcp_tool_name(new_tool_data.tool_name) or new_tool_data.tool_name,
            status=new_tool_data.status,
            args_summary=new_tool_data.args_summary,
            args_full=new_tool_data.args_full,
            start_time=new_tool_data.start_time or datetime.now(),
        )

        # Create batch card
        batch_card = ToolBatchCard(
            server_name=server_name,
            id=f"batch_{batch_id}",
        )

        # Tag with round class for navigation (scroll-to behavior)
        batch_card.add_class(f"round-{round_number}")

        # Add both tools to batch
        batch_card.add_tool(first_item)
        batch_card.add_tool(second_item)

        # Track in our dictionaries
        self._batches[batch_id] = batch_card
        self._tool_to_batch[pending_tool_id] = batch_id
        self._tool_to_batch[new_tool_data.tool_id] = batch_id
        self._tool_rounds[new_tool_data.tool_id] = round_number
        try:
            from massgen.frontend.displays.timeline_transcript import (
                record_batch,
                record_batch_tool,
            )

            record_batch(round_number, "convert", batch_id, server_name)
            record_batch_tool(new_tool_data, round_number, batch_id, "add")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        # Mount batch card right after the existing tool card, then remove the old card
        try:
            self.mount(batch_card, after=existing_card)
            existing_card.remove()
            del self._tools[pending_tool_id]

            # Defer trim and scroll until after mount completes
            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        return batch_card

    def add_hook_to_tool(self, tool_call_id: Optional[str], hook_info: dict) -> None:
        """Add hook execution info to a tool card.

        Args:
            tool_call_id: The tool call ID to attach the hook to
            hook_info: Hook execution information dict with keys:
                - hook_name: Name of the hook
                - hook_type: "pre" or "post"
                - decision: "allow", "deny", or "error"
                - reason: Optional reason string
                - execution_time_ms: Optional execution time
                - injection_preview: Optional preview of injected content
                - injection_content: Optional full injection content
        """
        from massgen.logger_config import logger

        # Find the tool card to attach the hook to
        tool_card = None
        if tool_call_id:
            tool_card = self._tools.get(tool_call_id)

        # If no specific tool_id, attach to the most recent tool
        if not tool_card and self._tools:
            # Get the most recently added tool
            tool_card = list(self._tools.values())[-1] if self._tools else None

        hook_name = hook_info.get("hook_name", "unknown")
        has_content = bool(hook_info.get("injection_content"))
        logger.info(
            f"[TimelineSection] add_hook_to_tool: tool_call_id={tool_call_id}, "
            f"hook={hook_name}, has_content={has_content}, tool_found={tool_card is not None}, "
            f"known_tools={list(self._tools.keys())}",
        )

        if tool_card:
            hook_type = hook_info.get("hook_type", "pre")
            hook_name = hook_info.get("hook_name", "unknown")
            decision = hook_info.get("decision", "allow")
            reason = hook_info.get("reason")
            injection_preview = hook_info.get("injection_preview")
            injection_content = hook_info.get("injection_content")
            execution_time_ms = hook_info.get("execution_time_ms")

            if hook_type == "pre":
                tool_card.add_pre_hook(
                    hook_name=hook_name,
                    decision=decision,
                    reason=reason,
                    execution_time_ms=execution_time_ms,
                    injection_content=injection_content,
                )
            else:
                tool_card.add_post_hook(
                    hook_name=hook_name,
                    injection_preview=injection_preview,
                    execution_time_ms=execution_time_ms,
                    injection_content=injection_content,
                )

    def add_text(self, content: str, style: str = "", text_class: str = "", round_number: int = 1) -> None:
        """Add text content to the timeline.

        Args:
            content: Text content
            style: Rich style string
            text_class: CSS class (status, thinking-inline, content-inline, response)
            round_number: The round this content belongs to (for view switching)
        """
        # Clean up excessive newlines only - preserve all spacing
        import re

        content = re.sub(r"\n{3,}", "\n\n", content)  # Max 2 consecutive newlines

        if not content.strip():  # Check if effectively empty
            return

        # Ensure this round's banner is shown before first content
        self._ensure_round_banner(round_number)

        # Check if this is thinking or content - route to appropriate batching
        is_thinking = "thinking" in text_class
        is_content = "content" in text_class and "content-inline" in text_class

        if is_thinking:
            self.add_reasoning(content, round_number=round_number, label="Thinking")
            return
        elif is_content:
            self.add_reasoning(content, round_number=round_number, label="Content")
            return

        # Other content - close any open batch
        self._close_reasoning_batch()

        self._item_count += 1
        widget_id = f"tl_text_{self._item_count}"

        try:
            classes = "timeline-text"
            if text_class:
                classes += f" {text_class}"

            if style:
                # Short content with explicit style
                widget = Static(
                    Text(content, style=style),
                    id=widget_id,
                    classes=classes,
                )
            else:
                # Short content - simple inline display
                widget = Static(content, id=widget_id, classes=classes)

            try:
                from massgen.frontend.displays.timeline_transcript import record_text

                record_text(content, text_class or "text", round_number)
            except Exception as e:
                tui_log(f"[ContentSections] {e}")

            # Tag with round class for navigation (scroll-to behavior)
            widget.add_class(f"round-{round_number}")

            insert_before = self._find_insert_before_for_round(round_number)
            self.mount(widget, before=insert_before)

            # Defer trim and scroll until after mount completes
            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def add_separator(
        self,
        label: str = "",
        round_number: int = 1,
        subtitle: str = "",
        *,
        before: Optional[Any] = None,
        after: Optional[Any] = None,
    ) -> None:
        """Add a visual separator to the timeline.

        Args:
            label: Optional label for the separator
            round_number: The round this content belongs to (for view switching)
            subtitle: Optional subtitle (e.g., "Restart • Context cleared")
            before: Optional widget to insert before
            after: Optional widget to insert after
        """
        from massgen.logger_config import logger

        if subtitle is None:
            subtitle = ""

        try:
            from massgen.frontend.displays.shared.tui_debug import tui_log

            tui_log(
                f"[ROUND_DEBUG] add_separator panel={self.id} label='{label}' round={round_number} before={bool(before)} after={bool(after)}",
                level="info",
            )
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        # Close any open reasoning batch
        self._close_reasoning_batch()

        # Deduplicate round separators — multiple round_start events per round
        if label.startswith("Round "):
            if round_number in self._pending_round_separators or round_number in self._shown_round_banners:
                try:
                    from massgen.frontend.displays.shared.tui_debug import tui_log

                    tui_log(
                        f"[ROUND_DEBUG] add_separator_dedup panel={self.id} label='{label}' round={round_number}",
                        level="info",
                    )
                except Exception as e:
                    tui_log(f"[ContentSections] {e}")
                return
            self._pending_round_separators.add(round_number)

        self._item_count += 1
        widget_id = f"tl_sep_{self._item_count}"

        logger.debug(
            f"TimelineSection.add_separator: label='{label}', round={round_number}, " f"viewed_round={self._viewed_round}, widget_id={widget_id}",
        )

        try:
            # Check if this is a round/restart/final separator (should be prominent)
            is_round = label.upper().startswith("ROUND") if label else False
            is_restart = "RESTART" in label.upper() if label else False
            is_final = "FINAL" in label.upper() if label else False

            if is_round or is_restart or is_final:
                # Create prominent round/restart/final banner
                widget = RestartBanner(label=label, subtitle=subtitle, id=widget_id)
                logger.debug(f"TimelineSection.add_separator: Created RestartBanner for '{label}' subtitle='{subtitle}'")
            else:
                # Regular separator
                sep_text = Text()
                sep_text.append("─" * 50, style="dim")
                if label:
                    sep_text.append(f" {label} ", style="dim italic")
                    sep_text.append("─" * 10, style="dim")
                widget = Static(sep_text, id=widget_id)

            # Tag with round class for navigation (scroll-to behavior)
            widget.add_class(f"round-{round_number}")
            logger.debug(f"TimelineSection.add_separator: Adding widget for round {round_number}")

            self.mount(widget, before=before, after=after)

            from datetime import datetime

            tui_log(
                f"[MOUNT_DEBUG] add_separator: label='{label}' round={round_number} " f"time={datetime.now().isoformat()}",
            )

            if label.startswith("Round "):
                self._pending_round_separators.discard(round_number)
                self._shown_round_banners.add(round_number)
                self._last_round_shown = max(self._last_round_shown, round_number)
                if round_number == 1:
                    self._round_1_shown = True

            # Defer trim and scroll until after mount completes
            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
            logger.debug(f"TimelineSection.add_separator: Successfully mounted {widget_id}")
            try:
                from massgen.frontend.displays.timeline_transcript import (
                    record_separator,
                )

                record_separator(label, round_number, subtitle)
            except Exception as e:
                tui_log(f"[ContentSections] {e}")
        except Exception as e:
            # Log the error but don't crash
            if label.startswith("Round "):
                self._pending_round_separators.discard(round_number)
            logger.error(f"TimelineSection.add_separator failed: {e}")

    def add_attempt_banner(
        self,
        attempt: int,
        reason: str = "",
        instructions: str = "",
        round_number: int = 1,
    ) -> None:
        """Add a prominent AttemptBanner widget to the timeline.

        Args:
            attempt: The attempt number (1-indexed).
            reason: Why the restart was triggered.
            instructions: Instructions for the next attempt.
            round_number: The round to tag this content with.
        """
        from massgen.logger_config import logger

        self._close_reasoning_batch()
        self._item_count += 1
        widget_id = f"tl_attempt_{self._item_count}"

        try:
            widget = AttemptBanner(
                attempt=attempt,
                reason=reason,
                instructions=instructions,
                id=widget_id,
            )
            widget.add_class(f"round-{round_number}")
            self.mount(widget)

            def trim_and_scroll():
                self._trim_old_items()
                self._auto_scroll()

            self.call_after_refresh(trim_and_scroll)
            logger.debug(f"TimelineSection.add_attempt_banner: mounted {widget_id}")
        except Exception as e:
            logger.error(f"TimelineSection.add_attempt_banner failed: {e}")

    def _close_reasoning_batch(self) -> None:
        """Close current reasoning batch when non-reasoning content arrives.

        This ends the accumulation of content into a single card, so the next
        content will start a new batch.
        """
        self._current_reasoning_card = None
        self._current_batch_label = None

    def add_reasoning(self, content: str, round_number: int = 1, label: str = "Thinking") -> None:
        """Add thinking/content - accumulates into single collapsible card.

        Consecutive statements with the same label are batched into ONE CollapsibleTextCard.
        The batch closes when:
        - Non-batched content (tools, separators) arrives
        - The label changes (Thinking → Content or vice versa)

        Args:
            content: Text content
            round_number: The round this content belongs to (for view switching)
            label: Label for the card ("Thinking" or "Content")
        """
        if not content.strip():
            return

        # Debug logging for reasoning batching
        content_preview = content[:50].replace("\n", "\\n")
        with open(os.path.join(tempfile.gettempdir(), "tui_debug.log"), "a") as f:
            f.write(
                f"DEBUG add_reasoning: label={label}, current_card={self._current_reasoning_card is not None}, " f"current_label={self._current_batch_label}, content_preview={content_preview}\n",
            )
        # Ensure this round's banner is shown before reasoning content
        self._ensure_round_banner(round_number)

        try:
            from massgen.frontend.displays.timeline_transcript import record_text

            record_text(content, f"reasoning-{label.lower()}", round_number)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        try:
            # Close batch if label changed
            if self._current_reasoning_card is not None and self._current_batch_label != label:
                self._close_reasoning_batch()

            if self._current_reasoning_card is not None:
                # Append to existing batch (streaming tokens)
                self._current_reasoning_card.append_content(content, streaming=True)
                # Just scroll for append case (no mount, no trim needed)
                self._auto_scroll()
            else:
                # Start new batch
                self._item_count += 1
                widget_id = f"tl_reasoning_{self._item_count}"

                self._current_reasoning_card = CollapsibleTextCard(
                    content,
                    label=label,
                    id=widget_id,
                    classes="timeline-text thinking-inline",
                )
                self._current_reasoning_card.add_class(f"round-{round_number}")
                self._current_batch_label = label
                insert_before = self._find_insert_before_for_round(round_number)
                self.mount(self._current_reasoning_card, before=insert_before)

                # Defer trim and scroll until after mount completes
                def trim_and_scroll():
                    self._trim_old_items()
                    self._auto_scroll()

                self.call_after_refresh(trim_and_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def add_widget(self, widget, round_number: int = 1) -> None:
        """Add a generic widget to the timeline.

        Args:
            widget: Any Textual widget to add to the timeline
            round_number: The round this content belongs to (for view switching)
        """
        # Ensure this round's banner is shown before first content
        self._ensure_round_banner(round_number)

        self._item_count += 1

        # Tag with round class for navigation (scroll-to behavior)
        widget.add_class(f"round-{round_number}")

        try:
            insert_before = self._find_insert_before_for_round(round_number)
            self.mount(widget, before=insert_before)
            self._log(f"Timeline items: {len(list(self.children))}")
            self._trim_old_items()  # Keep timeline size bounded (do before scroll)
            # Defer scroll to ensure trim's layout refresh completes first
            self.call_after_refresh(self._auto_scroll)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def clear(self, add_round_1: bool = True) -> None:
        """Clear all timeline content.

        Args:
            add_round_1: If True, add a "Round 1" separator after clearing (default: True)
        """
        from massgen.logger_config import logger

        logger.info(f"[TimelineSection] clear() called with add_round_1={add_round_1}")

        # Close any open reasoning batch
        self._close_reasoning_batch()

        try:
            # Keep the scroll indicator, remove everything else
            indicator = None
            try:
                indicator = self.query_one("#scroll_mode_indicator", Static)
            except Exception as e:
                tui_log(f"[ContentSections] {e}")
            child_count_before = len(self.children)
            self.remove_children()
            logger.info(f"[TimelineSection] Removed {child_count_before} children")
            if indicator:
                self.mount(indicator)
                logger.info("[TimelineSection] Re-mounted scroll indicator")
        except Exception as e:
            logger.error(f"[TimelineSection] Error during clear: {e}", exc_info=True)
        self._tools.clear()
        self._batches.clear()  # Also clear batch tracking
        self._tool_to_batch.clear()  # Clear tool-to-batch mapping
        self._removed_widgets.clear()  # Clear removed widgets cache
        self._item_count = 0
        logger.info("[TimelineSection] Cleared tracking dicts, reset _item_count to 0")
        # Reset truncation tracking to avoid stale state
        if hasattr(self, "_truncation_shown_rounds"):
            self._truncation_shown_rounds.clear()

        # Reset round tracking flags
        self._round_1_shown = False
        self._last_round_shown = 0
        self._pending_round_separators.clear()
        self._shown_round_banners.clear()
        self._deferred_round_banners.clear()
        logger.info("[TimelineSection] Set _round_1_shown = False")

        # CRITICAL FIX: Force layout refresh after clearing and defer Round 1 separator
        # This ensures max_scroll_y is recalculated before any new content tries to scroll
        self.refresh()
        self._log(f"[CLEAR] Before call_after_refresh: max_scroll_y={self.max_scroll_y:.2f}")

        # Defer Round 1 separator addition until after layout refresh completes
        if add_round_1:

            def add_round_1_separator():
                self._log(f"[CLEAR] After refresh: max_scroll_y={self.max_scroll_y:.2f}")
                logger.info("[TimelineSection] Adding initial Round 1 separator (from clear)")
                self._round_1_shown = True  # Set flag before adding to avoid re-entry
                self.add_separator("Round 1", round_number=1)
                logger.info("[TimelineSection] Round 1 separator added (from clear)")

            self.call_after_refresh(add_round_1_separator)

    def reset_round_state(self) -> None:
        """Reset round tracking state for a new turn."""
        from massgen.logger_config import logger

        logger.info("[TimelineSection] reset_round_state() called")
        logger.info(f"[TimelineSection] Before reset: _viewed_round={self._viewed_round}, _round_1_shown={self._round_1_shown}")

        self._viewed_round = 1
        # NOTE: Don't reset _round_1_shown here - it's managed by clear() and prepare_for_new_turn()
        # Resetting it here would cause duplicate "Round 1" separators
        # Clear tools/batch tracking to prevent ID collisions
        self._tools.clear()
        self._batches.clear()
        self._tool_to_batch.clear()

        logger.info(f"[TimelineSection] After reset: _viewed_round={self._viewed_round}, _round_1_shown={self._round_1_shown}")

    def clear_tools_tracking(self) -> None:
        """Clear tools and batch tracking dicts without removing UI elements.

        Used when a new round starts to reset tool/batch ID tracking while
        keeping the visual timeline history intact. This prevents tool_id
        and batch_id collisions between rounds.
        """
        self._tools.clear()
        self._batches.clear()
        self._tool_to_batch.clear()

    def set_viewed_round(self, round_number: int) -> None:
        """Update which round is currently being viewed.

        Phase 12: Called when a new round starts to track the active round.
        New content will use this round number for visibility tagging.

        Args:
            round_number: The round number being viewed
        """
        self._viewed_round = round_number

    def switch_to_round(self, round_number: int) -> None:
        """Scroll to the specified round's content.

        All rounds stay visible in a unified timeline. Selecting a round
        smoothly scrolls to that round's separator banner.

        Args:
            round_number: The round number to scroll to
        """
        from massgen.logger_config import logger

        self._viewed_round = round_number

        logger.debug(f"TimelineSection.switch_to_round: scrolling to round {round_number}")

        try:
            # Find the RestartBanner for this round and scroll to it
            # RestartBanners are tagged with round-X class
            found_separator = False
            for widget in self.query(f".round-{round_number}"):
                # Look for RestartBanner (has the round separator banner)
                if isinstance(widget, RestartBanner):
                    widget.scroll_visible(animate=True, top=True)
                    found_separator = True
                    break

            # If no RestartBanner found (e.g., round 1 which may not have one),
            # find the first widget for this round
            if not found_separator:
                for widget in self.query(f".round-{round_number}"):
                    widget.scroll_visible(animate=True, top=True)
                    break

            logger.debug(f"TimelineSection.switch_to_round: done scrolling to round {round_number}")
        except Exception as e:
            logger.error(f"TimelineSection.switch_to_round error: {e}")


class ThinkingSection(Vertical):
    """Section for streaming thinking/reasoning content.

    Phase 11.1: Now collapsible - auto-collapses when content exceeds threshold.
    Click header to toggle expanded/collapsed state.

    Design (collapsed):
    ```
    ▶ 💭 Reasoning [+12 more lines] ──────────────────────────────────────
    │ First few lines of reasoning visible here...
    ```

    Design (expanded):
    ```
    ▼ 💭 Reasoning ───────────────────────────────────────────────────────
    │ Full reasoning content visible...
    │ Multiple lines of thinking...
    │ ...
    ```
    """

    # Collapse threshold - auto-collapse when exceeding this many lines
    COLLAPSE_THRESHOLD = 5
    # Preview lines to show when collapsed
    PREVIEW_LINES = 3

    is_collapsed = reactive(False)

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._line_count = 0
        self._auto_collapsed = False  # Track if we auto-collapsed
        self.add_class("hidden")  # Start hidden until content arrives

    def compose(self) -> ComposeResult:
        yield Static(self._build_header(), id="thinking_header", classes="section-header")
        yield ScrollableContainer(
            RichLog(id="thinking_log", highlight=False, wrap=True, markup=True),
            id="thinking_content",
        )

    def _build_header(self) -> Text:
        """Build the section header text."""
        text = Text()

        # Collapse indicator
        indicator = "▶" if self.is_collapsed else "▼"
        text.append(f"{indicator} ", style="dim")

        # Icon and title
        text.append("💭 ", style="")
        text.append("Reasoning", style="bold dim")

        # Show hidden line count when collapsed
        if self.is_collapsed and self._line_count > self.PREVIEW_LINES:
            hidden_count = self._line_count - self.PREVIEW_LINES
            text.append(" ─" + "─" * 20 + "─ ", style="dim")
            text.append(f"[+{hidden_count} more lines]", style="dim cyan")

        return text

    def watch_is_collapsed(self, collapsed: bool) -> None:
        """Update UI when collapse state changes."""
        if collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")

        # Update header
        try:
            header = self.query_one("#thinking_header", Static)
            header.update(self._build_header())
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def on_click(self, event) -> None:
        """Toggle collapsed state on header click."""
        try:
            header = self.query_one("#thinking_header", Static)
            # Check if click was on header area
            if event.widget == header or (hasattr(event, "widget") and event.widget.id == "thinking_header"):
                self.is_collapsed = not self.is_collapsed
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def append(self, content: str, style: str = "") -> None:
        """Append content to the thinking log.

        Args:
            content: Text content to append
            style: Optional Rich style string
        """
        try:
            # Show section when content arrives
            self.remove_class("hidden")

            log = self.query_one("#thinking_log", RichLog)
            if style:
                log.write(Text(content, style=style))
            else:
                log.write(content)
            self._line_count += 1

            # Auto-collapse when exceeding threshold (only once)
            if not self._auto_collapsed and self._line_count > self.COLLAPSE_THRESHOLD:
                self._auto_collapsed = True
                self.is_collapsed = True

            # Update header to show line count
            try:
                header = self.query_one("#thinking_header", Static)
                header.update(self._build_header())
            except Exception as e:
                tui_log(f"[ContentSections] {e}")

        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def append_text(self, text: Text) -> None:
        """Append a Rich Text object.

        Args:
            text: Pre-styled Rich Text
        """
        try:
            # Show section when content arrives
            self.remove_class("hidden")

            log = self.query_one("#thinking_log", RichLog)
            log.write(text)
            self._line_count += 1

            # Auto-collapse when exceeding threshold (only once)
            if not self._auto_collapsed and self._line_count > self.COLLAPSE_THRESHOLD:
                self._auto_collapsed = True
                self.is_collapsed = True

            # Update header to show line count
            try:
                header = self.query_one("#thinking_header", Static)
                header.update(self._build_header())
            except Exception as e:
                tui_log(f"[ContentSections] {e}")

        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def clear(self) -> None:
        """Clear the thinking log."""
        try:
            log = self.query_one("#thinking_log", RichLog)
            log.clear()
            self._line_count = 0
            self._auto_collapsed = False
            self.is_collapsed = False
            self.add_class("hidden")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    @property
    def line_count(self) -> int:
        """Get the number of lines written."""
        return self._line_count

    def expand(self) -> None:
        """Expand the section (show all content)."""
        self.is_collapsed = False

    def collapse(self) -> None:
        """Collapse the section (show preview only)."""
        self.is_collapsed = True


class ResponseSection(Vertical):
    """Section for displaying final agent responses.

    Provides a clean, visually distinct area for the agent's answer
    separate from status updates and thinking content.

    Design:
    ```
    ╭─────────────────────────────────────────────────────────────────╮
    │ Response                                                         │
    ├─────────────────────────────────────────────────────────────────┤
    │                                                                  │
    │ The answer to your question is 42.                               │
    │                                                                  │
    │ Here's why:                                                      │
    │ - First reason                                                   │
    │ - Second reason                                                  │
    │                                                                  │
    ╰─────────────────────────────────────────────────────────────────╯
    ```
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._content_parts: list = []
        self.add_class("hidden")  # Start hidden until content arrives

    def compose(self) -> ComposeResult:
        yield Static("📝 Response", id="response_header")
        yield ScrollableContainer(id="response_content")

    def set_content(self, content: str, style: str = "") -> None:
        """Set the response content (replaces existing).

        Args:
            content: Response text
            style: Optional Rich style
        """
        try:
            container = self.query_one("#response_content", ScrollableContainer)
            container.remove_children()

            if content.strip():
                self.remove_class("hidden")
                if style:
                    container.mount(Static(Text(content, style=style)))
                else:
                    container.mount(Static(content))
            else:
                self.add_class("hidden")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def append_content(self, content: str, style: str = "") -> None:
        """Append to response content.

        Args:
            content: Text to append
            style: Optional Rich style
        """
        try:
            container = self.query_one("#response_content", ScrollableContainer)
            self.remove_class("hidden")

            if style:
                container.mount(Static(Text(content, style=style)))
            else:
                container.mount(Static(content))

            # Auto-scroll to bottom
            container.scroll_end(animate=False)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def clear(self) -> None:
        """Clear response content."""
        try:
            container = self.query_one("#response_content", ScrollableContainer)
            container.remove_children()
            self.add_class("hidden")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")


class StatusBadge(Static):
    """Compact inline status indicator.

    Design: `● Connected` or `⟳ Working` - small, not prominent.
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    status = reactive("waiting")

    STATUS_DISPLAY = {
        "connected": ("●", "Connected"),
        "working": ("⟳", "Working"),
        "streaming": ("▶", "Streaming"),
        "completed": ("✓", "Complete"),
        "error": ("✗", "Error"),
        "waiting": ("○", "Waiting"),
    }

    def __init__(
        self,
        initial_status: str = "waiting",
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id)
        self.status = initial_status
        self.add_class(f"status-{initial_status}")

    def render(self) -> Text:
        """Render the status badge."""
        icon, label = self.STATUS_DISPLAY.get(self.status, ("?", "Unknown"))
        return Text(f"{icon} {label}")

    def watch_status(self, old_status: str, new_status: str) -> None:
        """Update styling when status changes."""
        self.remove_class(f"status-{old_status}")
        self.add_class(f"status-{new_status}")
        self.refresh()

    def set_status(self, status: str) -> None:
        """Set the status.

        Args:
            status: One of: connected, working, streaming, completed, error, waiting
        """
        self.status = status


class CompletionFooter(Static):
    """Subtle completion indicator at bottom of panel.

    Design: `────────────────────────────────────── ✓ Complete ───`
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    is_visible = reactive(False)
    status = reactive("completed")

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self.add_class("hidden")

    def render(self) -> Text:
        """Render the footer line."""
        if self.status == "completed":
            return Text("─" * 30 + " ✓ Complete " + "─" * 30, style="dim green")
        elif self.status == "error":
            return Text("─" * 30 + " ✗ Error " + "─" * 30, style="dim red")
        else:
            return Text("")

    def watch_is_visible(self, visible: bool) -> None:
        """Show/hide footer."""
        if visible:
            self.remove_class("hidden")
        else:
            self.add_class("hidden")

    def watch_status(self, old_status: str, new_status: str) -> None:
        """Update styling on status change."""
        self.remove_class(f"status-{old_status}")
        self.add_class(f"status-{new_status}")
        self.refresh()

    def show_completed(self) -> None:
        """Show completion indicator."""
        self.status = "completed"
        self.is_visible = True

    def show_error(self) -> None:
        """Show error indicator."""
        self.status = "error"
        self.is_visible = True

    def hide(self) -> None:
        """Hide the footer."""
        self.is_visible = False


class RestartBanner(Static):
    """Prominent round separator banner - single strong line spanning full width.

    Design:
    ```
    ━━━━━━━━━━ Round 2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Context reset ━━
    ```

    For Final Answer:
    ```
    ━━━━━━━━━━ ✓ Final Answer ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ A1.1 won (2) ━━━━━
    ```
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(self, label: str = "", subtitle: str = "", id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._label = label
        self._subtitle = subtitle

    def render(self) -> Text:
        """Render a single strong line separator with label and subtitle."""
        import re

        # Use no_wrap to prevent line breaking
        text = Text(no_wrap=True)

        # Clean up the label - extract meaningful info
        display_label = self._label
        is_final = "FINAL" in display_label.upper()

        # Thin line character for minimalist look
        line_char = "─"
        # Get actual widget width dynamically
        try:
            total_width = self.size.width
            if total_width < 40:
                # Fallback if width not yet computed or too small
                total_width = 200
        except Exception:
            total_width = 200  # Fallback

        if is_final:
            # Final Presentation - muted green styling
            display_label = "✓ Final Answer"
            line_color = "#4b5563"  # Neutral gray line
            label_color = "#6b9e7a"  # Muted green for label
            subtitle_color = "#9ca3af"  # Gray for subtitle
        elif "RESTART" in display_label.upper():
            # Extract round number for restart - neutral gray styling
            match = re.search(r"ROUND\s*(\d+)", display_label, re.IGNORECASE)
            if match:
                round_num = match.group(1)
                display_label = f"Round {round_num}"
            else:
                display_label = "New Round"
            line_color = "#4b5563"  # Neutral gray line
            label_color = "#9ca3af"  # Gray for label
            subtitle_color = "#6b7280"  # Dim gray for subtitle
        elif display_label.upper().startswith("ROUND"):
            # Simple "Round X" label - neutral gray styling
            match = re.search(r"ROUND\s*(\d+)", display_label, re.IGNORECASE)
            if match:
                round_num = match.group(1)
                display_label = f"Round {round_num}"
            line_color = "#4b5563"  # Neutral gray line
            label_color = "#9ca3af"  # Gray for label
            subtitle_color = "#6b7280"  # Dim gray for subtitle
        else:
            line_color = "#4b5563"  # Neutral gray
            label_color = "#9ca3af"  # Gray
            subtitle_color = "#6b7280"  # Dim gray

        # Build single line: ━━━━━ Label ━━━━━━━━━━━━━━━━━━━━━ Subtitle ━━━━━
        left_line_len = 6
        label_text = f" {display_label} "

        # Start with left segment - use same color as label for visibility
        text.append(line_char * left_line_len, style=line_color)
        text.append(label_text, style=f"bold {label_color}")

        if self._subtitle:
            subtitle_text = f" {self._subtitle} "
            # Middle segment fills the space
            middle_len = total_width - left_line_len - len(label_text) - len(subtitle_text) - 6
            if middle_len < 4:
                middle_len = 4

            text.append(line_char * middle_len, style=line_color)
            text.append(subtitle_text, style=f"italic {subtitle_color}")
            text.append(line_char * 6, style=line_color)
        else:
            # No subtitle - just fill with line
            remaining = total_width - left_line_len - len(label_text)
            text.append(line_char * remaining, style=line_color)

        return text


class AttemptBanner(Vertical):
    """Prominent banner for orchestration-level restarts (new attempts).

    More visually distinct than a round separator to clearly signal that the
    entire coordination is restarting, not just an intra-round agent restart.

    Collapsed (default):
    ```
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ▸ ↻ Attempt 2  ·  The answer was incomplete...
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ```

    Expanded (click header):
    ```
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ▾ ↻ Attempt 2
    ──────────────────────────────────────────────────────────────────────────
     Reason: The answer only describes John Lennon and omits Paul McCartney
     Instructions: Provide two descriptions (John Lennon AND Paul McCartney)
                   ...
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ```
    """

    DEFAULT_CSS = """
    AttemptBanner {
        width: 100%;
        height: auto;
        margin: 1 0;
        padding: 0;
        background: transparent;
    }

    AttemptBanner .attempt-header {
        width: 100%;
        height: auto;
        padding: 0;
    }

    AttemptBanner .attempt-header:hover {
        background: #1a1a1a;
    }

    AttemptBanner .attempt-detail {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: #1a1507;
        display: none;
    }

    AttemptBanner .attempt-footer {
        width: 100%;
        height: 1;
        padding: 0;
    }

    AttemptBanner.expanded .attempt-detail {
        display: block;
    }

    AttemptBanner .attempt-footer {
        display: none;
    }

    AttemptBanner.expanded .attempt-footer {
        display: block;
    }
    """

    def __init__(self, attempt: int = 2, reason: str = "", instructions: str = "", id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._attempt = attempt
        self._reason = reason
        self._instructions = instructions
        self._expanded = False

    def compose(self) -> ComposeResult:
        yield Static(id="attempt_header", classes="attempt-header")
        yield Static(id="attempt_detail", classes="attempt-detail")
        yield Static(id="attempt_footer", classes="attempt-footer")

    def on_mount(self) -> None:
        # Defer initial render so layout has computed the real width
        self.call_after_refresh(self._refresh_all)

    def on_resize(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._update_header()
        self._update_detail()
        self._update_footer()

    def _get_width(self) -> int:
        try:
            w = self.size.width
            return w if w >= 40 else 200
        except Exception:
            return 200

    def _update_header(self) -> None:
        text = Text(no_wrap=False)
        total_width = self._get_width()

        line_char = "━"
        line_color = "#b45309"
        label_color = "#f59e0b"
        reason_color = "#6b7280"
        indicator_color = "#9ca3af"

        # Top line
        text.append(line_char * total_width, style=line_color)
        text.append("\n")

        # Label line
        indicator = "▾" if self._expanded else "▸"
        text.append(f" {indicator} ", style=indicator_color)
        text.append(f"\u21bb Attempt {self._attempt}", style=f"bold {label_color}")

        if not self._expanded and self._reason:
            truncated = self._reason[:70] + "..." if len(self._reason) > 70 else self._reason
            text.append(f"  \u00b7  {truncated}", style=f"italic {reason_color}")

        if not self._expanded:
            text.append("\n")
            # Bottom line when collapsed
            text.append(line_char * total_width, style=line_color)

        try:
            header = self.query_one("#attempt_header", Static)
            header.update(text)
        except Exception:
            pass

    def _update_detail(self) -> None:
        text = Text(no_wrap=False)

        label_color = "#b45309"
        content_color = "#d4d4d4"

        if self._reason:
            text.append("Reason\n", style=f"bold {label_color}")
            text.append(self._reason, style=content_color)

        if self._instructions:
            if self._reason:
                text.append("\n\n")
            text.append("Instructions\n", style=f"bold {label_color}")
            text.append(self._instructions, style=content_color)

        try:
            detail = self.query_one("#attempt_detail", Static)
            detail.update(text)
        except Exception:
            pass

    def _update_footer(self) -> None:
        text = Text(no_wrap=True)
        total_width = self._get_width()
        text.append("━" * total_width, style="#b45309")

        try:
            footer = self.query_one("#attempt_footer", Static)
            footer.update(text)
        except Exception:
            pass

    def on_click(self, event) -> None:
        """Toggle expanded/collapsed on click."""
        self._expanded = not self._expanded
        if self._expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")
        self._update_header()
        self._update_detail()


class FinalPresentationCard(Vertical):
    """Unified card widget for displaying the final answer presentation.

    Shows a header with trophy icon, vote summary, streaming content area,
    collapsible post-evaluation section, action buttons (Copy/Workspace), and continue message.

    Design:
    ```
    ┌─ 🏆 FINAL ANSWER ─────────────────────────────────────────────────┐
    │  Winner: Agent A (2 votes)  |  Votes: A(2), B(1)                  │
    ├───────────────────────────────────────────────────────────────────┤
    │  [Final answer content with markdown rendering...]                │
    │                                                                   │
    ├───────────────────────────────────────────────────────────────────┤
    │  ✓ Verified by Post-Evaluation                    [▾ Show Details]│
    │  [Collapsible evaluation content...]                              │
    ├───────────────────────────────────────────────────────────────────┤
    │  [📋 Copy]  [📂 Workspace]                                        │
    │  💬 Type below to continue the conversation                       │
    └───────────────────────────────────────────────────────────────────┘
    ```
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    # Debounce interval for batched updates (seconds)
    _UPDATE_DEBOUNCE_MS = 50

    def __init__(
        self,
        agent_id: str,
        model_name: str = "",
        vote_results: Optional[Dict] = None,
        context_paths: Optional[Dict] = None,
        workspace_path: Optional[str] = None,
        completion_only: bool = False,
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id or "final_presentation_card")
        self.agent_id = agent_id
        self.model_name = model_name
        self.vote_results = vote_results or {}
        self.context_paths = context_paths or {}
        self.workspace_path = workspace_path
        self._final_content: list = []
        self._post_eval_content: list = []
        self._is_streaming = not completion_only
        self._post_eval_expanded = False
        self._post_eval_status = "none"  # none, evaluating, verified
        self._text_widget: Optional[Static] = None  # Direct reference to text widget
        # Performance: track pending updates for debouncing
        self._update_pending = False
        self._update_timer = None
        self._cached_full_text: Optional[str] = None  # Cache to avoid repeated joins
        if completion_only:
            self.add_class("completion-only")
        else:
            self.add_class("streaming")

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal, ScrollableContainer
        from textual.widgets import Label

        # Header section - compact single line
        with Vertical(id="final_card_header"):
            yield Label(self._build_title(), id="final_card_title")
            yield Label(self._build_vote_summary(), id="final_card_votes")

        # Body: horizontal container for content + file explorer
        from textual.widgets import Markdown

        from massgen.frontend.displays.textual_widgets.file_explorer_panel import (
            FileExplorerPanel,
        )

        self._text_widget = Markdown("", id="final_card_text")
        with Horizontal(id="final_card_body"):
            with ScrollableContainer(id="final_card_content"):
                yield self._text_widget
            yield FileExplorerPanel(
                context_paths=self.context_paths,
                workspace_path=self.workspace_path,
                id="file_explorer_panel",
            )

        # Post-evaluation section (hidden until post-eval content arrives)
        with Vertical(id="final_card_post_eval", classes="hidden"):
            with Horizontal(id="post_eval_header"):
                yield Label("🔍 Evaluating...", id="post_eval_status", classes="evaluating")
                yield Label("", id="post_eval_toggle")
            with ScrollableContainer(id="post_eval_details", classes="collapsed"):
                yield Static("", id="post_eval_content")

        # Context paths section (hidden if no paths)
        has_paths = bool(self.context_paths.get("new") or self.context_paths.get("modified"))
        with Vertical(id="final_card_context_paths", classes="" if has_paths else "hidden"):
            new_count = len(self.context_paths.get("new", []))
            mod_count = len(self.context_paths.get("modified", []))
            total = new_count + mod_count
            yield Label(f"📂 Files Written ({total})", id="context_paths_header")
            with Vertical(id="context_paths_list"):
                for path in self.context_paths.get("new", []):
                    yield Label(f"  ✚ {path}", classes="context-path-new")
                for path in self.context_paths.get("modified", []):
                    yield Label(f"  ✎ {path}", classes="context-path-modified")

        # Footer with link-style actions and continue message (hidden until complete)
        with Vertical(id="final_card_footer", classes="hidden"):
            with Horizontal(id="final_card_buttons"):
                yield Static("📋 Copy", id="final_card_copy_btn", classes="footer-link")
                yield Static("📂 Workspace", id="final_card_workspace_btn", classes="footer-link")
                # Verified indicator - faded, shown when post-eval verified
                verified = Static("✓ Verified", id="final_card_verified", classes="verified-indicator")
                yield verified
                # Spacer to push unlock button to the right
                yield Static("", id="final_card_button_spacer")
                # Unlock button - hidden initially, shown when locked
                link = Static("↩ Previous Work", id="final_card_unlock_btn", classes="footer-link")
                link.display = False
                yield link
            yield Label("💬 Type below to continue the conversation", id="continue_message")

    def _build_title(self) -> str:
        """Build the title with trophy icon."""
        return "🏆 FINAL ANSWER"

    def _build_vote_summary(self) -> str:
        """Build the vote summary line."""
        if not self.vote_results:
            return ""

        vote_counts = self.vote_results.get("vote_counts", {})
        winner = self.vote_results.get("winner", "")
        is_tie = self.vote_results.get("is_tie", False)

        if not vote_counts:
            return ""

        # Format: "Winner: agent_a | Votes: agent_a (2), agent_b (1)"
        tie_note = " (tie-breaker)" if is_tie else ""
        counts_str = ", ".join(f"{aid} ({count})" for aid, count in vote_counts.items())

        return f"Winner: {winner}{tie_note} | Votes: {counts_str}"

    def append_chunk(self, chunk: str) -> None:
        """Append streaming content to the card.

        Args:
            chunk: Text chunk to append

        Performance: Uses debounced updates to batch multiple chunks into
        a single render cycle, avoiding O(n²) string joining and expensive
        Markdown re-renders on every chunk.
        """
        if not chunk:
            return

        # Accumulate content and invalidate cache
        self._final_content.append(chunk)
        self._cached_full_text = None  # Invalidate cache

        # Schedule debounced update if not already pending
        if not self._update_pending:
            self._update_pending = True
            try:
                self._update_timer = self.set_timer(
                    self._UPDATE_DEBOUNCE_MS / 1000.0,
                    self._flush_pending_update,
                )
            except Exception:
                # Widget not mounted yet - will flush on mount
                pass

    def _flush_pending_update(self) -> None:
        """Flush pending chunks to the text widget.

        Called by the debounce timer to batch multiple chunks into one render.
        """
        self._update_pending = False
        self._update_timer = None
        self._try_update_text()

    def _get_full_text(self) -> str:
        """Get the full accumulated text, using cache when available."""
        if self._cached_full_text is None:
            self._cached_full_text = "".join(self._final_content)
        return self._cached_full_text

    def _try_update_text(self) -> bool:
        """Try to update the text widget with accumulated content.

        Called by the debounce timer. Silently fails if widget not ready yet.

        Returns:
            True if update succeeded, False if widget not ready.
        """
        if not self._final_content:
            return True  # Nothing to update

        full_text = self._get_full_text()

        # Use direct reference if available (set in compose)
        if self._text_widget is not None:
            try:
                self._text_widget.update(full_text)
                # Note: No explicit refresh() - update() schedules its own refresh
                return True
            except Exception as e:
                tui_log(f"[ContentSections] {e}")

        # Fallback to query
        try:
            from textual.widgets import Markdown

            text_widget = self.query_one("#final_card_text", Markdown)
            text_widget.update(full_text)
            return True
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        # Last resort: manually create the text widget if compose didn't run
        try:
            from textual.widgets import Markdown

            # Check if we have any children at all
            if not list(self.children):
                self._text_widget = Markdown(full_text, id="final_card_text_manual")
                self.mount(self._text_widget)
                return True
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        return False

    def on_mount(self) -> None:
        """Flush any pending content when the widget is mounted."""
        # Cancel any pending debounce timer and flush immediately
        self._update_pending = False
        if self._update_timer:
            self._update_timer.stop()
            self._update_timer = None

        # Flush any buffered content that arrived before mount
        self._try_update_text()

        # In completion-only mode, show footer immediately and mark as completed
        # (content has already been shown through the normal pipeline)
        if self.has_class("completion-only"):
            self.complete()

        # Show file explorer if set_locked_mode was called before mount
        if getattr(self, "_pending_file_explorer", False):
            self._pending_file_explorer = False
            self._show_file_explorer(True)

    def _on_compose(self) -> None:
        """Called after compose() completes - use this to flush content."""
        # Try to update after compose completes
        if self._final_content:
            self._try_update_text()

    def complete(self) -> None:
        """Mark the presentation as complete and show action buttons."""
        from textual.widgets import Label

        self._is_streaming = False

        # Flush any pending debounced updates immediately
        self._update_pending = False
        if self._update_timer:
            self._update_timer.stop()
            self._update_timer = None
        self._try_update_text()

        # Update styling
        self.remove_class("streaming")
        # Only add completed class if not in completion-only mode
        # (completion-only mode has its own styling via the class)
        if not self.has_class("completion-only"):
            self.add_class("completed")

        # Update title to show completed
        try:
            title = self.query_one("#final_card_title", Label)
            title.update("✅ FINAL ANSWER")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

        # Show footer with buttons and continue message
        try:
            footer = self.query_one("#final_card_footer")
            footer.remove_class("hidden")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def get_content(self) -> str:
        """Get the full content for copy operation."""
        return self._get_full_text()

    def on_click(self, event) -> None:
        """Handle clicks on footer links and post-eval toggle."""
        from textual.widgets import Label

        widget_id = getattr(event.widget, "id", None) if hasattr(event, "widget") else None

        # Handle footer link clicks
        if widget_id == "final_card_unlock_btn":
            self._toggle_lock()
            event.stop()
            return
        elif widget_id == "final_card_copy_btn":
            self._copy_to_clipboard()
            event.stop()
            return
        elif widget_id == "final_card_workspace_btn":
            self._open_workspace()
            event.stop()
            return

        # Check if click was on the toggle label
        try:
            toggle = self.query_one("#post_eval_toggle", Label)
            if toggle.region.contains(event.x, event.y):
                self._toggle_post_eval_details()
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def _toggle_post_eval_details(self) -> None:
        """Toggle the post-evaluation details visibility."""
        from textual.containers import ScrollableContainer
        from textual.widgets import Label

        try:
            details = self.query_one("#post_eval_details", ScrollableContainer)
            toggle = self.query_one("#post_eval_toggle", Label)

            if self._post_eval_expanded:
                details.add_class("collapsed")
                toggle.update("▸ Show Details")
                self._post_eval_expanded = False
            else:
                details.remove_class("collapsed")
                toggle.update("▾ Hide Details")
                self._post_eval_expanded = True
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def _toggle_lock(self) -> None:
        """Toggle between locked (answer-only) and unlocked (full timeline) view."""
        # Find parent TimelineSection
        timeline = None
        parent = self.parent
        while parent:
            if isinstance(parent, TimelineSection):
                timeline = parent
                break
            parent = parent.parent

        if not timeline:
            return

        try:
            link = self.query_one("#final_card_unlock_btn", Static)
            link.display = True  # Always keep visible once shown

            if timeline.is_answer_locked:
                # Unlock: show full timeline
                timeline.unlock_final_answer()
                self.remove_class("locked-mode")
                link.update("⎯ Answer Only")
                self._show_file_explorer(False)
            else:
                # Lock: show only final answer
                timeline.lock_to_final_answer(self.id or "final_presentation_card")
                self.add_class("locked-mode")
                link.update("↩ Previous Work")
                self._show_file_explorer(True)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def set_locked_mode(self, locked: bool) -> None:
        """Set the locked mode state programmatically.

        Called by textual_terminal_display when auto-locking after final answer.

        Args:
            locked: Whether to enable locked mode
        """
        if locked:
            self.add_class("locked-mode")
            try:
                link = self.query_one("#final_card_unlock_btn", Static)
                link.display = True
                link.update("↩ Previous Work")
            except Exception as e:
                tui_log(f"[ContentSections] {e}")
            # Show file explorer directly (called after 0.1s timer, card should be mounted)
            self._show_file_explorer(True)
            # Also set flag for on_mount fallback in case we're not mounted yet
            self._pending_file_explorer = True
        else:
            self.remove_class("locked-mode")
            try:
                link = self.query_one("#final_card_unlock_btn", Static)
                link.display = False
                link.update("⎯ Answer Only")
            except Exception as e:
                tui_log(f"[ContentSections] {e}")
            self._show_file_explorer(False)

    def _show_file_explorer(self, show: bool) -> None:
        """Show or hide the file explorer side panel."""
        try:
            from massgen.frontend.displays.textual_widgets.file_explorer_panel import (
                FileExplorerPanel,
            )

            panel = self.query_one("#file_explorer_panel", FileExplorerPanel)

            if not show:
                panel.remove_class("visible")
                return

            # Lazy-resolve workspace path from log directory
            if not panel.has_files():
                self._resolve_workspace_path(panel)
                if panel.workspace_path and Path(panel.workspace_path).exists():
                    panel._scan_workspace()
                    if panel.has_files():

                        def _apply():
                            try:
                                p = self.query_one("#file_explorer_panel", FileExplorerPanel)
                                p.rebuild_tree()
                                p.add_class("visible")
                                p.auto_preview(self.get_content())
                                p.refresh(layout=True)
                            except Exception as e:
                                tui_log(f"[ContentSections] {e}")

                        self.call_later(_apply)
                        return

            if panel.has_files():
                panel.add_class("visible")
                try:
                    self.query_one("#final_card_context_paths").add_class("hidden")
                except Exception as e:
                    tui_log(f"[ContentSections] {e}")
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def _resolve_workspace_path(self, panel) -> None:
        """Resolve the workspace path from the log session directory."""
        try:
            from massgen.logger_config import get_log_session_dir

            log_dir = get_log_session_dir()
            if not log_dir:
                return

            candidate = self._find_final_workspace(log_dir, self.agent_id)
            if candidate is None:
                # log_dir may be the session root; scan turn/attempt subdirs
                for turn_dir in sorted(log_dir.glob("turn_*"), reverse=True):
                    for attempt_dir in sorted(turn_dir.glob("attempt_*"), reverse=True):
                        candidate = self._find_final_workspace(attempt_dir, self.agent_id)
                        if candidate is not None:
                            break
                    if candidate is not None:
                        break

            if candidate is not None and candidate.exists():
                panel.workspace_path = str(candidate)
        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    @staticmethod
    def _find_final_workspace(base_dir: Path, agent_id: str) -> Optional[Path]:
        """Look for final/<agent_id>/workspace under base_dir."""
        final_dir = base_dir / "final"
        if not final_dir.exists() or not final_dir.is_dir():
            return None
        ws = final_dir / agent_id / "workspace"
        if ws.exists():
            return ws
        agent_dir = final_dir / agent_id
        if agent_dir.exists():
            return agent_dir
        # Single-agent fallback
        agent_dirs = [d for d in final_dir.iterdir() if d.is_dir()]
        if len(agent_dirs) == 1:
            lone = agent_dirs[0]
            ws = lone / "workspace"
            return ws if ws.exists() else lone
        return None

    def _copy_to_clipboard(self) -> None:
        """Copy final answer to system clipboard."""
        import platform
        import subprocess

        full_content = self.get_content()
        try:
            system = platform.system()
            if system == "Darwin":
                process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                process.communicate(full_content.encode("utf-8"))
            elif system == "Windows":
                process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                process.communicate(full_content.encode("utf-8"))
            else:
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                )
                process.communicate(full_content.encode("utf-8"))
            self.app.notify(
                f"Copied {len(self._final_content)} lines to clipboard",
                severity="information",
            )
        except Exception as e:
            self.app.notify(f"Failed to copy: {e}", severity="error")

    def _open_workspace(self) -> None:
        """Open workspace browser for the winning agent."""
        try:
            app = self.app
            if hasattr(app, "_show_workspace_browser_for_agent"):
                app._show_workspace_browser_for_agent(self.agent_id)
            else:
                self.app.notify("Workspace browser not available", severity="warning")
        except Exception as e:
            self.app.notify(f"Failed to open workspace: {e}", severity="error")

    def set_post_eval_status(self, status: str, content: str = "") -> None:
        """Set the post-evaluation status and optionally add content.

        Args:
            status: One of "evaluating", "verified", "restart"
            content: Optional content to display in the details section
        """
        from textual.widgets import Label

        self._post_eval_status = status

        try:
            # Update the faded verified indicator in the footer
            try:
                verified_indicator = self.query_one("#final_card_verified", Static)
                if status == "verified":
                    verified_indicator.display = True
                else:
                    verified_indicator.display = False
            except Exception:
                pass

            # Show the post-eval section only if there's content to show
            if content and content.strip():
                post_eval_section = self.query_one("#final_card_post_eval")
                post_eval_section.remove_class("hidden")

                # Update status label in post-eval section
                status_label = self.query_one("#post_eval_status", Label)
                toggle_label = self.query_one("#post_eval_toggle", Label)

                if status == "evaluating":
                    status_label.update("🔍 Evaluating...")
                    status_label.add_class("evaluating")
                    toggle_label.update("")
                elif status == "verified":
                    status_label.update("✓ Verified")
                    status_label.remove_class("evaluating")
                    toggle_label.update("▸ Show Details")
                elif status == "restart":
                    status_label.update("🔄 Restart Requested")
                    status_label.remove_class("evaluating")
                    toggle_label.update("▸ Show Details")

                # Add content
                self._post_eval_content.append(content)
                post_eval_static = self.query_one("#post_eval_content", Static)
                full_content = "\n".join(self._post_eval_content)
                post_eval_static.update(full_content)

        except Exception as e:
            tui_log(f"[ContentSections] {e}")

    def add_post_evaluation(self, content: str) -> None:
        """Add post-evaluation content to the card (legacy method).

        Args:
            content: The post-evaluation text to display
        """
        if not content.strip():
            return

        # If status not set, set to evaluating
        if self._post_eval_status == "none":
            self.set_post_eval_status("evaluating", content)
        else:
            self.set_post_eval_status(self._post_eval_status, content)

    def get_post_evaluation_content(self) -> str:
        """Get the full post-evaluation content."""
        return "\n".join(self._post_eval_content)
