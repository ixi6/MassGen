"""
Path Suggestion Dropdown Widget for MassGen TUI.

Provides inline file path autocomplete when user types @ in the input.
Supports directory browsing, file selection, and :w suffix for write mode.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from massgen.filesystem_manager._constants import get_language_for_extension


@dataclass
class PathSuggestion:
    """A single path suggestion."""

    path: str  # Full path
    name: str  # Display name (filename or dirname)
    is_dir: bool  # Whether this is a directory


class SuggestionRow(Static):
    """A single row in the suggestion dropdown."""

    DEFAULT_CSS = """
    SuggestionRow {
        height: 1;
        padding: 0 1;
    }

    SuggestionRow.selected {
        background: $primary;
        color: $text;
    }

    SuggestionRow .dir-icon {
        color: $warning;
    }

    SuggestionRow .file-icon {
        color: $text-muted;
    }

    SuggestionRow .file-type {
        color: $text-muted;
    }

    SuggestionRow .write-suffix {
        color: $success;
    }
    """

    def __init__(
        self,
        suggestion: PathSuggestion,
        show_write: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.suggestion = suggestion
        self.show_write = show_write

    def render(self) -> Text:
        """Render the suggestion row."""
        text = Text()

        # Icon
        if self.suggestion.is_dir:
            text.append("📁 ", style="bold")
        else:
            text.append("📄 ", style="dim")

        # Name
        name = self.suggestion.name
        if self.suggestion.is_dir and not name.endswith("/"):
            name += "/"
        text.append(name)

        # File type or write suffix
        if not self.suggestion.is_dir:
            # Add spacing
            text.append("  ")
            if self.show_write:
                text.append(":w", style="bold green")
                text.append(" (write)", style="dim green")
            else:
                ext = Path(self.suggestion.name).suffix.lower()
                file_type = get_language_for_extension(ext)
                text.append(f"({file_type})", style="dim")

        return text


class PathSuggestionDropdown(Widget):
    """Dropdown widget showing path suggestions.

    Triggered when user types @ in the input field.
    Shows file/directory suggestions based on the path prefix.

    Design:
    ```
    ┌─────────────────────────────────────────────────────────────────┐
    │ 📁 src/components/        (dir)                                 │
    │ 📁 src/utils/             (dir)                                 │
    │ 📄 src/main.py            python                                │
    │ 📄 src/config.py          python                                │
    │ 📄 src/main.py:w          python (write)                        │
    ├─────────────────────────────────────────────────────────────────┤
    │ ↑↓ navigate • Tab select • → toggle :w • Esc dismiss            │
    └─────────────────────────────────────────────────────────────────┘
    ```
    """

    DEFAULT_CSS = """
    PathSuggestionDropdown {
        display: none;
        layer: overlay;
        width: 100%;
        height: auto;
        max-height: 14;
        background: $surface;
        border: solid $primary;
        padding: 0;
        layout: vertical;
    }

    PathSuggestionDropdown.visible {
        display: block;
    }

    PathSuggestionDropdown > #suggestions_container {
        height: auto;
        max-height: 11;
        overflow-y: auto;
    }

    PathSuggestionDropdown > .hint-bar {
        dock: bottom;
        height: 1;
        width: 100%;
        background: $surface-darken-1;
        color: $text-muted;
        text-align: center;
        padding: 0 1;
        border-top: solid $primary-darken-1;
    }
    """

    # Reactive properties
    visible = reactive(False)
    selected_index = reactive(0)
    show_write_suffix = reactive(False)

    class PathSelected(Message, bubble=True):
        """Message sent when a path is selected."""

        def __init__(self, path: str, with_write: bool = False) -> None:
            super().__init__()
            self.path = path
            self.with_write = with_write

    class Dismissed(Message, bubble=True):
        """Message sent when the dropdown is dismissed."""

    class ContinueBrowsing(Message, bubble=True):
        """Message sent when user selects a directory to continue browsing."""

        def __init__(self, prefix: str) -> None:
            super().__init__()
            self.prefix = prefix

    def __init__(
        self,
        base_path: Path | None = None,
        **kwargs,
    ) -> None:
        """Initialize the dropdown.

        Args:
            base_path: Base directory for resolving relative paths.
        """
        super().__init__(**kwargs)
        try:
            self.base_path = base_path or Path.cwd()
        except OSError:
            self.base_path = Path.home()
        self._suggestions: list[PathSuggestion] = []
        self._suggestion_widgets: list[SuggestionRow] = []

    def compose(self) -> ComposeResult:
        """Compose the dropdown layout."""
        yield Vertical(id="suggestions_container")
        yield Static("j/k or ↑↓ navigate • Tab select • → toggle :w • Esc dismiss", classes="hint-bar")

    def update_suggestions(self, prefix: str) -> None:
        """Update suggestions based on the path prefix.

        Args:
            prefix: The path prefix after @ symbol.
        """
        self._suggestions = self._get_suggestions(prefix)
        self.selected_index = 0
        self.show_write_suffix = False
        self._refresh_suggestion_widgets()

        # Show/hide based on suggestions
        self.visible = len(self._suggestions) > 0

    def _get_suggestions(self, prefix: str, max_results: int = 15) -> list[PathSuggestion]:
        """Get path suggestions for the given prefix.

        Args:
            prefix: Path prefix to complete.
            max_results: Maximum number of suggestions.

        Returns:
            List of PathSuggestion objects with relative paths matching user input style.
        """
        # Handle special shortcuts for current directory
        if prefix in (".", "cwd"):
            cwd = str(self.base_path)
            return [
                PathSuggestion(
                    path=".",
                    name=f"{cwd} (current directory)",
                    is_dir=True,
                ),
            ]

        # Store original prefix to build relative completion paths
        original_prefix = prefix

        # Handle empty prefix - show current directory contents
        if not prefix:
            original_prefix = ""
            expanded = str(self.base_path)
        elif prefix.startswith("~"):
            # Expand ~ to home directory
            expanded = os.path.expanduser(prefix)
        elif prefix.startswith("./") or prefix.startswith("../"):
            expanded = str(self.base_path / prefix)
        elif not prefix.startswith("/"):
            expanded = str(self.base_path / prefix)
        else:
            expanded = prefix

        try:
            prefix_path = Path(expanded)

            # Determine parent directory and partial name
            if prefix.endswith("/") or (prefix_path.exists() and prefix_path.is_dir()):
                parent_dir = prefix_path if prefix_path.is_dir() else prefix_path.parent
                partial_name = ""
                # The prefix to build upon includes the trailing slash
                base_prefix = original_prefix if original_prefix.endswith("/") else (original_prefix + "/" if original_prefix else "")
            else:
                parent_dir = prefix_path.parent
                partial_name = prefix_path.name.lower()
                # The prefix to build upon is up to the last /
                if "/" in original_prefix:
                    base_prefix = original_prefix.rsplit("/", 1)[0] + "/"
                else:
                    base_prefix = ""

            parent_dir = parent_dir.resolve()

            if not parent_dir.exists() or not parent_dir.is_dir():
                return []

            suggestions = []

            # Add CWD shortcut as first option when browsing from root
            if not original_prefix:
                suggestions.append(
                    PathSuggestion(
                        path=".",
                        name=". (current directory)",
                        is_dir=True,
                    ),
                )

            for entry in sorted(parent_dir.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                # Skip hidden files unless explicitly requested
                if entry.name.startswith(".") and not partial_name.startswith("."):
                    continue

                # Match partial name
                if partial_name and not entry.name.lower().startswith(partial_name):
                    continue

                # Build relative path that matches the user's input style
                relative_path = base_prefix + entry.name

                suggestions.append(
                    PathSuggestion(
                        path=relative_path,
                        name=entry.name,
                        is_dir=entry.is_dir(),
                    ),
                )

                if len(suggestions) >= max_results:
                    break

            return suggestions

        except (OSError, PermissionError, ValueError):
            return []

    def _refresh_suggestion_widgets(self) -> None:
        """Refresh the suggestion widgets."""
        container = self.query_one("#suggestions_container", Vertical)

        # Remove old widgets
        container.remove_children()

        # Add new widgets
        self._suggestion_widgets = []
        for i, suggestion in enumerate(self._suggestions):
            is_selected = i == self.selected_index
            show_write = is_selected and self.show_write_suffix and not suggestion.is_dir

            row = SuggestionRow(
                suggestion,
                show_write=show_write,
                classes="selected" if is_selected else "",
            )
            self._suggestion_widgets.append(row)
            container.mount(row)

    def watch_visible(self, visible: bool) -> None:
        """Update visibility class."""
        if visible:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def watch_selected_index(self, index: int) -> None:
        """Update selected row highlighting."""
        for i, widget in enumerate(self._suggestion_widgets):
            if i == index:
                widget.add_class("selected")
            else:
                widget.remove_class("selected")

        # Refresh to show/hide write suffix on selected
        self._refresh_write_display()

    def watch_show_write_suffix(self, show: bool) -> None:
        """Update write suffix display."""
        self._refresh_write_display()

    def _refresh_write_display(self) -> None:
        """Refresh the write suffix display for selected item."""
        for i, widget in enumerate(self._suggestion_widgets):
            is_selected = i == self.selected_index
            suggestion = self._suggestions[i] if i < len(self._suggestions) else None
            if suggestion:
                show_write = is_selected and self.show_write_suffix and not suggestion.is_dir
                widget.show_write = show_write
                widget.refresh()

    def handle_key(self, event: events.Key) -> bool:
        """Handle keyboard navigation.

        Args:
            event: The key event.

        Returns:
            True if the event was handled, False otherwise.
        """
        if not self.visible or not self._suggestions:
            return False

        key = event.key

        if key in ("down", "j"):
            self.selected_index = (self.selected_index + 1) % len(self._suggestions)
            self.show_write_suffix = False
            return True

        elif key in ("up", "k"):
            self.selected_index = (self.selected_index - 1 + len(self._suggestions)) % len(self._suggestions)
            self.show_write_suffix = False
            return True

        elif key == "right":
            # Toggle :w suffix for files
            suggestion = self._suggestions[self.selected_index]
            if not suggestion.is_dir:
                self.show_write_suffix = not self.show_write_suffix
                return True
            return False

        elif key in ("tab", "enter"):
            self._select_current()
            return True

        elif key == "escape":
            self.dismiss()
            return True

        return False

    def _select_current(self) -> None:
        """Select the currently highlighted suggestion."""
        if not self._suggestions:
            return

        suggestion = self._suggestions[self.selected_index]

        if suggestion.is_dir:
            # Continue browsing in directory
            self.post_message(self.ContinueBrowsing(suggestion.path + "/"))
        else:
            # Select file
            self.post_message(self.PathSelected(suggestion.path, self.show_write_suffix))
            self.dismiss()

    def dismiss(self) -> None:
        """Dismiss the dropdown."""
        self.visible = False
        self._suggestions = []
        self._suggestion_widgets = []
        self.post_message(self.Dismissed())

    @property
    def is_showing(self) -> bool:
        """Check if dropdown is currently visible."""
        return self.visible
