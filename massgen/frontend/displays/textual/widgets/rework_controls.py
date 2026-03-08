"""
Shared rework controls mixin for MassGen TUI modals.

Provides the feedback Input + Continue/Quick Edit button pattern used by both
PlanApprovalModal and GitDiffReviewModal. Subclasses set class-level widget ID
constants to avoid CSS/test ID collisions.
"""

try:
    from textual.containers import Horizontal
    from textual.widgets import Button, Input, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False


class ReworkControlsMixin:
    """Mixin providing shared feedback + rework button controls.

    Class attributes (override in subclass for CSS/test backward compat):
        REWORK_FEEDBACK_INPUT_ID: Widget ID for the feedback Input
        REWORK_CONTINUE_BTN_ID: Widget ID for the Continue/Rework button
        REWORK_QUICK_EDIT_BTN_ID: Widget ID for the Quick Edit button
    """

    REWORK_FEEDBACK_INPUT_ID: str = "rework_feedback_input"
    REWORK_CONTINUE_BTN_ID: str = "rework_continue_btn"
    REWORK_QUICK_EDIT_BTN_ID: str = "rework_quick_edit_btn"

    def __init_rework_mixin__(self) -> None:
        """Initialize mixin state. Call from subclass __init__ if needed."""
        self._rework_feedback_value: str = ""
        self._rework_action_status: str = ""

    # Ensure state attrs exist even without explicit init call
    @property
    def _rework_feedback_value(self) -> str:  # type: ignore[override]
        return self.__dict__.get("_rework_feedback_value", "")

    @_rework_feedback_value.setter
    def _rework_feedback_value(self, value: str) -> None:
        self.__dict__["_rework_feedback_value"] = value

    @property
    def _rework_action_status(self) -> str:  # type: ignore[override]
        return self.__dict__.get("_rework_action_status", "")

    @_rework_action_status.setter
    def _rework_action_status(self, value: str) -> None:
        self.__dict__["_rework_action_status"] = value

    def compose_rework_input(
        self,
        feedback_label: str = "\u270f Feedback for rework (required):",
        feedback_placeholder: str = "e.g., fix the import order, add error handling...",
    ):
        """Yield a Container with just the feedback label + Input (no buttons).

        Use this when rework buttons will be placed in a separate footer row
        via ``compose_rework_buttons()``.
        """
        from textual.containers import Container as _Container

        feedback_input = Input(
            placeholder=feedback_placeholder,
            id=self.REWORK_FEEDBACK_INPUT_ID,
            classes="rework-feedback-input",
        )
        feedback_input.value = self._rework_feedback_value

        label_widget = Static(
            feedback_label,
            classes="rework-feedback-label",
            markup=True,
        )

        yield _Container(
            label_widget,
            feedback_input,
            classes="rework-input-section",
        )

    def compose_rework_buttons(
        self,
        continue_label: str = "Continue Planning",
        quick_edit_label: str = "Quick Edit (Single Agent)",
    ):
        """Yield just the rework Button widgets (no wrapping container).

        Use this to place the buttons inside an existing footer row.
        """
        yield Button(
            continue_label,
            variant="default",
            id=self.REWORK_CONTINUE_BTN_ID,
            classes="rework-continue-btn",
            disabled=not self._has_rework_feedback(),
        )
        yield Button(
            quick_edit_label,
            variant="default",
            id=self.REWORK_QUICK_EDIT_BTN_ID,
            classes="rework-quick-edit-btn",
            disabled=not self._has_rework_feedback(),
        )

    def compose_rework_controls(
        self,
        feedback_label: str = "\u270f Feedback for rework (required):",
        feedback_placeholder: str = "e.g., fix the import order, add error handling...",
        continue_label: str = "Continue Planning",
        quick_edit_label: str = "Quick Edit (Single Agent)",
    ):
        """Yield a Container with feedback Input and Continue/Quick Edit buttons.

        Args:
            feedback_label: Label text above the input
            feedback_placeholder: Placeholder text for the input
            continue_label: Label for the multi-agent continue button
            quick_edit_label: Label for the single-agent quick edit button

        Yields:
            A single Container widget with the rework controls inside.
        """
        from textual.containers import Container as _Container

        feedback_input = Input(
            placeholder=feedback_placeholder,
            id=self.REWORK_FEEDBACK_INPUT_ID,
            classes="rework-feedback-input",
        )
        feedback_input.value = self._rework_feedback_value

        continue_btn = Button(
            continue_label,
            variant="default",
            id=self.REWORK_CONTINUE_BTN_ID,
            classes="rework-continue-btn",
            disabled=not self._has_rework_feedback(),
        )

        quick_edit_btn = Button(
            quick_edit_label,
            variant="default",
            id=self.REWORK_QUICK_EDIT_BTN_ID,
            classes="rework-quick-edit-btn",
            disabled=not self._has_rework_feedback(),
        )

        # Build the container with children
        label_widget = Static(
            feedback_label,
            classes="rework-feedback-label",
            markup=True,
        )

        button_row = Horizontal(
            continue_btn,
            quick_edit_btn,
            classes="rework-button-row",
        )

        result = _Container(
            label_widget,
            feedback_input,
            button_row,
            classes="rework-controls",
        )

        yield result

    def _rework_feedback_text(self) -> str | None:
        """Get the current feedback text, or None if empty/whitespace.

        Tries to read from mounted widget first, falls back to cached value.
        """
        # Try reading from mounted widget
        try:
            feedback_input = self.query_one(f"#{self.REWORK_FEEDBACK_INPUT_ID}", Input)  # type: ignore[attr-defined]
            text = (feedback_input.value or "").strip()
            return text or None
        except Exception:
            text = (self._rework_feedback_value or "").strip()
            return text or None

    def _has_rework_feedback(self) -> bool:
        """Check whether feedback text is present."""
        return self._rework_feedback_text() is not None

    def _sync_rework_button_states(self) -> None:
        """Enable/disable rework buttons based on feedback presence."""
        has_feedback = self._has_rework_feedback()
        for button_id in (self.REWORK_CONTINUE_BTN_ID, self.REWORK_QUICK_EDIT_BTN_ID):
            try:
                self.query_one(f"#{button_id}", Button).disabled = not has_feedback  # type: ignore[attr-defined]
            except Exception:
                pass

    def _snapshot_rework_input(self) -> None:
        """Capture current feedback input value before recompose/dismiss."""
        try:
            self._rework_feedback_value = self.query_one(  # type: ignore[attr-defined]
                f"#{self.REWORK_FEEDBACK_INPUT_ID}",
                Input,
            ).value
        except Exception:
            pass


__all__ = ["ReworkControlsMixin"]
