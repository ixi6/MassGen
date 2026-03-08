"""
Collapsible Text Card Widget for MassGen TUI.

Provides a clickable collapsible card for displaying long reasoning or content text.
Shows the last N chunks when collapsed with "(+N chunks above)" indicator at top,
matching the streaming UX where newest content is visible.
"""

import re

from rich.text import Text
from textual.events import Click
from textual.widgets import Static

# Patterns to filter out from content
FILTER_PATTERNS = [
    r"🧠\s*\[Reasoning Started\]",
    r"🧠\s*\[Reasoning Complete\]",
    r"\[Reasoning Started\]",
    r"\[Reasoning Complete\]",
    r"🔄\s*Vote for \[.*?\] ignored.*",  # Internal vote status messages
]
FILTER_REGEX = re.compile("|".join(FILTER_PATTERNS), re.IGNORECASE)


class CollapsibleTextCard(Static):
    """Collapsible card for reasoning or content text.

    Shows last N chunks when collapsed with "(+N chunks above)" indicator at top.
    Click to expand/collapse. Pattern matches ToolBatchCard's "show newest" UX.

    Uses border-left styling matching ToolCallCard. All indentation is handled
    via CSS padding-left so wrapped lines align correctly.

    Attributes:
        content: The full text content.
        label: Label shown in header ("Thinking" or "Content").
    """

    # Separator between chunks for visual clarity
    CHUNK_SEPARATOR = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

    # Three-level expansion: MINIMAL (0) -> PREVIEW (1) -> FULL (2)
    # Level 0 - Minimal: Very compact, quick glance
    MINIMAL_CHUNK_COUNT = 1
    MINIMAL_MAX_LINES = 3

    # Level 1 - Preview: More context, still manageable
    PREVIEW_CHUNK_COUNT = 2
    PREVIEW_MAX_LINES = 8

    # Level 2 - Full: Everything (no limits)

    # Max characters per line in minimal/preview modes (prevents long line wrapping)
    TRUNCATE_LINE_CHARS = 120

    # Expansion level indicators: ▸ (minimal) → ▹ (preview) → ▾ (full)
    LEVEL_INDICATORS = ("▸", "▹", "▾")

    can_focus = True

    @staticmethod
    def _clean_content(content: str) -> str:
        """Remove reasoning markers from content, preserve spacing."""
        return FILTER_REGEX.sub("", content)

    # Debounce interval for batched refresh (seconds)
    _REFRESH_DEBOUNCE_MS = 50

    def __init__(
        self,
        content: str,
        label: str = "Thinking",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the collapsible text card.

        Args:
            content: The full text content to display.
            label: Label for the card ("Thinking" or "Content").
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._content = self._clean_content(content)
        self._label = label
        # Three-level expansion: 0=minimal, 1=preview, 2=full
        self._expansion_level = 0
        self._chunks: list[str] = [self._content] if self._content else []
        # Add label-based class for CSS targeting (e.g., label-thinking, label-content)
        self.add_class(f"label-{label.lower()}")
        # Appearance animation state
        self.add_class("appearing")
        # Performance: debounced refresh tracking
        self._refresh_pending = False
        self._refresh_timer = None

    def on_mount(self) -> None:
        """Complete appearance animation after mounting."""
        self.set_timer(0.3, self._complete_appearance)

    def _complete_appearance(self) -> None:
        """Complete the appearance animation by transitioning to appeared state."""
        self.remove_class("appearing")
        self.add_class("appeared")

    def render(self) -> Text:
        """Render the card content."""
        return self._build_content()

    def _render_chunk(self, text: Text, chunk: str, truncate_lines: bool = False) -> None:
        """Render a single chunk of content.

        No manual indentation - CSS padding-left handles alignment for all lines
        including wrapped ones.

        Args:
            text: Rich Text object to append to.
            chunk: The chunk content to render.
            truncate_lines: If True, truncate long lines at TRUNCATE_LINE_CHARS.
        """
        for line in chunk.split("\n"):
            if line:  # Skip completely empty lines
                if truncate_lines and len(line) > self.TRUNCATE_LINE_CHARS:
                    line = line[: self.TRUNCATE_LINE_CHARS] + "..."
                text.append(f"\n{line}", style="dim #9ca3af")

    def _render_chunk_truncated(
        self,
        text: Text,
        chunk: str,
        max_lines: int,
        truncate_lines: bool = True,
    ) -> None:
        """Render a chunk, truncating to last max_lines lines if too long.

        Args:
            text: Rich Text object to append to.
            chunk: The chunk content to render.
            max_lines: Maximum number of lines to show (shows tail).
            truncate_lines: If True, truncate long lines at TRUNCATE_LINE_CHARS.
        """
        lines = [line for line in chunk.split("\n") if line]
        if len(lines) > max_lines:
            hidden = len(lines) - max_lines
            text.append(f"\n(+{hidden} lines above)", style="dim italic #6e7681")
            for line in lines[-max_lines:]:
                if truncate_lines and len(line) > self.TRUNCATE_LINE_CHARS:
                    line = line[: self.TRUNCATE_LINE_CHARS] + "..."
                text.append(f"\n{line}", style="dim #9ca3af")
        else:
            self._render_chunk(text, chunk, truncate_lines=truncate_lines)

    def _build_content(self) -> Text:
        """Build the Rich Text content for display."""
        text = Text()

        # Expand indicator and label (on first line)
        indicator = self.LEVEL_INDICATORS[self._expansion_level]
        text.append(f"{indicator} ", style="dim")
        text.append(f"[{self._label}]", style="dim italic #8b949e")

        total_chunks = len(self._chunks)

        if total_chunks == 0:
            return text

        # Only show separators for Thinking/Reasoning, not Content
        show_separators = self._label.lower() in ("thinking", "reasoning")

        if self._expansion_level == 2:
            # FULL: Show all chunks, no truncation
            for i, chunk in enumerate(self._chunks):
                self._render_chunk(text, chunk, truncate_lines=False)
                # Add separator or blank line between chunks (not after last)
                if i < total_chunks - 1:
                    if show_separators:
                        text.append(f"\n{self.CHUNK_SEPARATOR}", style="dim #484f58")
                    else:
                        # Blank line between content chunks for readability
                        text.append("\n")
        else:
            # MINIMAL (0) or PREVIEW (1): Show limited chunks
            if self._expansion_level == 0:
                chunk_count = self.MINIMAL_CHUNK_COUNT
                max_lines = self.MINIMAL_MAX_LINES
                truncate_lines = True  # Minimal: truncate long lines at 120 chars
            else:
                chunk_count = self.PREVIEW_CHUNK_COUNT
                max_lines = self.PREVIEW_MAX_LINES
                truncate_lines = False  # Preview: show full line length

            # Show "(+N chunks above)" at TOP if truncated
            if total_chunks > chunk_count:
                hidden = total_chunks - chunk_count
                text.append(f"\n(+{hidden} chunks above)", style="dim italic #6e7681")

            # Show LAST N chunks (tail) - newest content visible
            visible_chunks = self._chunks[-chunk_count:]
            for i, chunk in enumerate(visible_chunks):
                # Add separator or blank line before chunk (except first visible)
                if i > 0:
                    if show_separators:
                        text.append(f"\n{self.CHUNK_SEPARATOR}", style="dim #484f58")
                    else:
                        # Blank line between content chunks for readability
                        text.append("\n")
                self._render_chunk_truncated(text, chunk, max_lines, truncate_lines=truncate_lines)

        return text

    def on_click(self, event: Click) -> None:
        """Handle click - cycle through expansion levels (0 -> 1 -> 2 -> 0)."""
        # Remove old level class
        self.remove_class(f"expansion-{self._expansion_level}")

        # Cycle to next level
        self._expansion_level = (self._expansion_level + 1) % 3

        # Add new level class
        self.add_class(f"expansion-{self._expansion_level}")

        # Update legacy expanded class for CSS compatibility
        if self._expansion_level == 2:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")

        self.refresh()

    @property
    def is_expanded(self) -> bool:
        """Check if the card is fully expanded (level 2)."""
        return self._expansion_level == 2

    @property
    def expansion_level(self) -> int:
        """Get the current expansion level (0=minimal, 1=preview, 2=full)."""
        return self._expansion_level

    @property
    def label(self) -> str:
        """Get the card label."""
        return self._label

    @property
    def content(self) -> str:
        """Get the full content."""
        return self._content

    @property
    def chunk_count(self) -> int:
        """Get the total number of chunks."""
        return len(self._chunks)

    def _flush_pending_refresh(self) -> None:
        """Flush pending refresh after debounce interval."""
        self._refresh_pending = False
        self._refresh_timer = None
        self.refresh()

    def _schedule_refresh(self) -> None:
        """Schedule a debounced refresh to batch multiple updates."""
        if not self._refresh_pending:
            self._refresh_pending = True
            try:
                self._refresh_timer = self.set_timer(
                    self._REFRESH_DEBOUNCE_MS / 1000.0,
                    self._flush_pending_refresh,
                )
            except Exception:
                # Widget not mounted yet or timer failed - reset state and refresh directly
                self._refresh_pending = False
                self._refresh_timer = None
                self.refresh()

    def append_content(self, new_content: str, streaming: bool = False) -> None:
        """Append additional content to the card.

        Args:
            new_content: Text to append.
            streaming: If True, concatenate directly to the last chunk (for
                token-by-token streaming). If False, add as a new visually
                separated chunk.

        Performance: Uses debounced refresh to batch multiple streaming chunks
        into a single render cycle.
        """
        # Clean and validate content
        cleaned = self._clean_content(new_content)
        if not cleaned:
            return

        if streaming and self._chunks:
            # Concatenate to last chunk (streaming tokens)
            self._chunks[-1] += cleaned
            self._content += cleaned
        else:
            # Add as new separated chunk
            self._chunks.append(cleaned)
            self._content += "\n" + self.CHUNK_SEPARATOR + "\n" + cleaned

        # Schedule debounced refresh
        self._schedule_refresh()
