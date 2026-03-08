"""
Base Modal class with shared styling and behavior for all MassGen TUI modals.

This module provides:
- BaseModal: Abstract base class for all modals with shared ESC/close handling
- Helper methods for building consistent modal UI components
- Shared CSS definitions for modal styling
"""

from typing import TYPE_CHECKING, Any

try:
    from textual import events
    from textual.app import ComposeResult
    from textual.containers import Horizontal, ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import Button, Label, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False
    ModalScreen = object
    ComposeResult = None


if TYPE_CHECKING:
    pass


# Shared CSS for all modals - imported into each modal's CSS
MODAL_BASE_CSS = """
/* =============================================================================
 * Base Modal Styles
 * Provides consistent structure and styling for all modals
 * ============================================================================= */

/* Modal backdrop and centering */
BaseModal, ModalScreen {
    align: center middle;
}

/* Standard modal container */
.modal-container {
    width: 80%;
    max-width: 100;
    height: auto;
    max-height: 80%;
    background: $bg-surface-2;
    border: solid $accent-primary;
    padding: 1 2;
}

/* Wide modal variant */
.modal-container-wide {
    width: 90%;
    max-width: 120;
}

/* Narrow modal variant */
.modal-container-narrow {
    width: 60%;
    max-width: 80;
}

/* Modal header */
.modal-header {
    height: auto;
    layout: horizontal;
    padding-bottom: 1;
    border-bottom: solid $border-muted;
}

.modal-title {
    width: 1fr;
    text-style: bold;
    color: $accent-primary;
}

.modal-close-btn {
    width: auto;
    min-width: 3;
}

/* Modal content area */
.modal-content {
    height: auto;
    max-height: 60vh;
    padding: 1 0;
}

.modal-content-scroll {
    height: auto;
    max-height: 50vh;
}

/* Modal footer */
.modal-footer {
    height: auto;
    layout: horizontal;
    align: right middle;
    padding-top: 1;
    border-top: solid $border-muted;
}

.modal-footer Button {
    margin-left: 1;
}

/* Summary line under header */
.modal-summary {
    color: $fg-muted;
    padding: 0 0 1 0;
}

/* Section headers within modal content */
.modal-section-header {
    text-style: bold;
    color: $accent-info;
    margin-top: 1;
    margin-bottom: 0;
}

/* List items */
.modal-list-item {
    padding: 0 0 0 2;
}

.modal-list-item-selected {
    background: $bg-surface-3;
}

/* Clickable items */
.modal-clickable {
    /* hover effect handled by Textual */
}

.modal-clickable:hover {
    background: $bg-surface-3;
}
"""


class BaseModal(ModalScreen):
    """Base modal with common dismiss behavior for ESC and close buttons.

    All modals in the TUI should inherit from this class to get:
    - ESC key to dismiss
    - Close button handling (any button with id starting with "close" or "cancel")
    - Helper methods for building consistent UI components

    Subclasses should override compose() to build their content.
    """

    # Subclasses can override these for different sizes
    MODAL_WIDTH = "80%"
    MODAL_MAX_WIDTH = 100
    MODAL_MAX_HEIGHT = "80%"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle close/cancel button presses."""
        if event.button.id and (event.button.id.startswith("close") or event.button.id == "cancel_button"):
            self.dismiss()

    def on_key(self, event: events.Key) -> None:
        """Handle ESC key to dismiss modal."""
        if event.key == "escape":
            self.dismiss()
            event.stop()

    def key_escape(self) -> None:
        """Alternative escape handler (some Textual versions)."""
        self.dismiss()

    # =========================================================================
    # Helper methods for building consistent modal UI
    # =========================================================================

    def make_header(
        self,
        title: str,
        icon: str = "",
        close_button: bool = True,
        close_button_id: str = "close_modal_button",
    ) -> ComposeResult:
        """Generate standard modal header with title and optional close button.

        Args:
            title: The modal title text
            icon: Optional emoji/icon to prepend to title
            close_button: Whether to include a close button
            close_button_id: ID for the close button

        Yields:
            Header widgets
        """
        display_title = f"{icon}  {title}" if icon else title
        with Horizontal(classes="modal-header"):
            yield Label(display_title, classes="modal-title")
            if close_button:
                yield Button("×", id=close_button_id, classes="modal-close-btn")

    def make_summary(self, text: str) -> ComposeResult:
        """Generate a summary line under the header.

        Args:
            text: Summary text to display

        Yields:
            Summary label widget
        """
        yield Label(text, classes="modal-summary")

    def make_scrollable_content(
        self,
        content_id: str = "modal_content",
    ) -> ScrollableContainer:
        """Create a standard scrollable content area.

        Args:
            content_id: ID for the scrollable container

        Returns:
            ScrollableContainer widget
        """
        return ScrollableContainer(id=content_id, classes="modal-content-scroll")

    def make_footer(
        self,
        buttons: list[tuple[str, str, str]],
        alignment: str = "right",
    ) -> ComposeResult:
        """Generate standard modal footer with buttons.

        Args:
            buttons: List of (id, label, variant) tuples
                     variant can be: "default", "primary", "success", "warning", "error"
            alignment: "left", "center", or "right"

        Yields:
            Footer widgets
        """
        align_class = f"align-{alignment}"
        with Horizontal(classes=f"modal-footer {align_class}"):
            for btn_id, label, variant in buttons:
                yield Button(label, id=btn_id, variant=variant)

    def make_close_footer(
        self,
        label: str = "Close (ESC)",
        button_id: str = "close_modal_button",
    ) -> ComposeResult:
        """Generate a simple footer with just a close button.

        Args:
            label: Button label text
            button_id: Button ID

        Yields:
            Footer widgets
        """
        with Horizontal(classes="modal-footer"):
            yield Button(label, id=button_id)

    def make_section_header(self, title: str) -> ComposeResult:
        """Generate a section header within modal content.

        Args:
            title: Section header text

        Yields:
            Section header widget
        """
        yield Static(title, classes="modal-section-header", markup=True)


class BaseDataModal(BaseModal):
    """Base modal for displaying data with optional filtering and details.

    Provides additional structure for modals that display lists of items
    with a detail panel (like AnswerBrowserModal, TimelineModal, etc.).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_index: int = 0
        self._filtered_items: list[Any] = []
        self._render_count: int = 0  # For unique widget IDs

    def _increment_render_count(self) -> int:
        """Increment and return render count for unique IDs."""
        self._render_count += 1
        return self._render_count

    def _navigate_items(self, direction: int) -> None:
        """Navigate through items list.

        Args:
            direction: 1 for next, -1 for previous
        """
        if not self._filtered_items:
            return

        new_index = self._selected_index + direction
        if 0 <= new_index < len(self._filtered_items):
            self._selected_index = new_index
            self._on_item_selected(new_index)

    def _on_item_selected(self, index: int) -> None:
        """Called when an item is selected. Override in subclass."""

    def on_key(self, event: events.Key) -> None:
        """Handle arrow key navigation."""
        if event.key == "up":
            self._navigate_items(-1)
            event.stop()
        elif event.key == "down":
            self._navigate_items(1)
            event.stop()
        else:
            super().on_key(event)


# Export for use in other modules
__all__ = [
    "BaseModal",
    "BaseDataModal",
    "MODAL_BASE_CSS",
]
