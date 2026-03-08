"""
Base Wizard Framework for MassGen TUI.

Provides reusable infrastructure for multi-step wizards including:
- WizardStep: Definition of a single wizard step
- WizardState: Tracks wizard progress and collected data
- WizardModal: Base modal class for step-by-step wizards with navigation

This framework is used by both the Setup Wizard and Quickstart Wizard.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar


def _wizard_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[WIZARD] {msg}")


@dataclass
class WizardStep:
    """Definition of a wizard step.

    Attributes:
        id: Unique identifier for this step.
        title: Display title shown in the wizard header.
        description: Brief description of what this step does.
        component_class: The StepComponent class to instantiate for this step.
        is_optional: If True, the step can be skipped entirely.
        skip_condition: Optional function that takes step_data and returns True if step should be skipped.
    """

    id: str
    title: str
    description: str
    component_class: type["StepComponent"]
    is_optional: bool = False
    skip_condition: Callable[[dict[str, Any]], bool] | None = None


@dataclass
class WizardState:
    """Tracks wizard progress and collected data.

    Attributes:
        current_step_idx: Index of the current step (0-based).
        step_data: Dictionary mapping step IDs to their collected values.
        visited_steps: Set of step IDs that have been visited.
        validation_errors: Dictionary mapping step IDs to error messages.
    """

    current_step_idx: int = 0
    step_data: dict[str, Any] = field(default_factory=dict)
    visited_steps: set[str] = field(default_factory=set)
    validation_errors: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from step_data with a default."""
        return self.step_data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in step_data."""
        self.step_data[key] = value

    def clear_error(self, step_id: str) -> None:
        """Clear validation error for a step."""
        self.validation_errors.pop(step_id, None)

    def set_error(self, step_id: str, message: str) -> None:
        """Set validation error for a step."""
        self.validation_errors[step_id] = message


class StepComponent(Container):
    """Base class for wizard step content.

    Subclasses must implement:
    - compose(): Yield the widgets for this step
    - get_value(): Return the collected value(s) from this step

    Optionally implement:
    - validate(): Return error message if invalid, None if valid (default: None)
    - set_value(): Restore a previously collected value (for Back navigation)
    - on_mount(): Initialize the component with wizard state
    """

    # Base component should not take focus (children manage it)
    can_focus = False

    DEFAULT_CSS = """
    StepComponent {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the step component.

        Args:
            wizard_state: The current wizard state for accessing collected data.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self.wizard_state = wizard_state

    def get_value(self) -> Any:
        """Return the collected value(s) from this step.

        Returns:
            The value to store in wizard_state.step_data for this step.
        """
        raise NotImplementedError("Subclasses must implement get_value()")

    def set_value(self, value: Any) -> None:
        """Restore a previously collected value.

        Called when navigating back to a step that was already completed.
        Override this method to restore the UI state from the saved value.

        Args:
            value: The previously collected value from this step.
        """

    def validate(self) -> str | None:
        """Validate the current step's input.

        Returns:
            Error message if validation fails, None if valid.
        """
        return None


class WizardCompleted(Message):
    """Message emitted when the wizard completes successfully."""

    def __init__(self, result: Any) -> None:
        """Initialize the message.

        Args:
            result: The wizard result data to return to the caller.
        """
        self.result = result
        super().__init__()


class WizardCancelled(Message):
    """Message emitted when the wizard is cancelled."""


class WizardModal(ModalScreen):
    """Base modal for multi-step wizards with navigation.

    Subclasses must implement:
    - get_steps(): Return list of WizardStep definitions
    - on_wizard_complete(): Called when wizard finishes successfully

    The wizard provides:
    - Progress indicator showing current step
    - Navigation buttons (Back/Next/Cancel)
    - Keyboard navigation (Esc, Left/Right arrows, Enter)
    - Automatic step skipping based on skip_condition
    - State preservation when navigating back
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "cancel", "Cancel"),
        ("left", "previous_step", "Previous"),
        ("right", "next_step", "Next"),
        ("enter", "confirm", "Confirm"),
    ]

    DEFAULT_CSS = """
    WizardModal {
        align: center middle;
    }

    #wizard_container {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        layout: vertical;
        overflow: hidden;
    }

    #wizard_header {
        height: auto;
        width: 100%;
        padding: 0;
        margin-bottom: 1;
    }

    #wizard_header > Horizontal {
        height: 1;
        width: 100%;
        align: left middle;
    }

    #wizard_content {
        height: auto;
        width: 100%;
        overflow-y: auto;
        margin: 0;
        padding: 0 1;
    }

    #wizard_error.hidden {
        display: none;
    }

    #wizard_nav {
        height: 3;
        width: 100%;
        align: center middle;
        margin-top: 1;
    }

    #wizard_nav Button {
        margin: 0 1;
        min-width: 14;
        height: 3;
    }

    #wizard_hints {
        height: 1;
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the wizard modal."""
        super().__init__(id=id, classes=classes)
        self.state = WizardState()
        self._steps: list[WizardStep] = []
        self._current_component: StepComponent | None = None
        self._initialized = False

    def get_steps(self) -> list[WizardStep]:
        """Return the list of wizard steps.

        Override this method to define the steps for your wizard.

        Returns:
            List of WizardStep objects defining the wizard flow.
        """
        raise NotImplementedError("Subclasses must implement get_steps()")

    async def on_wizard_complete(self) -> Any:
        """Called when the wizard completes successfully.

        Override this method to handle wizard completion, such as
        saving configuration or launching the next action.

        Returns:
            The result to pass to dismiss() and WizardCompleted message.
        """
        raise NotImplementedError("Subclasses must implement on_wizard_complete()")

    def compose(self) -> ComposeResult:
        """Create the wizard layout."""
        with Vertical(id="wizard_container"):
            # Header section
            with Vertical(id="wizard_header"):
                # Progress bar and step counter on same line
                with Horizontal():
                    yield ProgressBar(id="wizard_progress_bar", total=100, show_eta=False)
                    yield Label("", id="wizard_step_counter")
                yield Label("", id="wizard_title")
                yield Label("", id="wizard_description")

            # Content area for step component
            yield Vertical(id="wizard_content")

            # Error message (hidden by default)
            error_label = Label("", id="wizard_error")
            error_label.add_class("hidden")
            yield error_label

            # Navigation buttons
            with Horizontal(id="wizard_nav"):
                yield Button("Back", id="wizard_back", variant="default")
                yield Button("Next", id="wizard_next", variant="success")
                yield Button("Cancel", id="wizard_cancel", variant="error")

    async def on_mount(self) -> None:
        """Initialize the wizard when mounted."""
        if self._initialized:
            return

        _wizard_log("WizardModal.on_mount: Initializing wizard")
        self._steps = self.get_steps()
        self._initialized = True

        # Show the first step
        await self._show_step(0)

    def _should_skip_step(self, step: WizardStep) -> bool:
        """Check if a step should be skipped.

        Args:
            step: The step to check.

        Returns:
            True if the step should be skipped, False otherwise.
        """
        if step.skip_condition:
            return step.skip_condition(self.state.step_data)
        return False

    def _find_next_step(self, start_idx: int) -> int:
        """Find the next non-skipped step index.

        Args:
            start_idx: The index to start searching from.

        Returns:
            The index of the next step to show, or len(steps) if at end.
        """
        idx = start_idx
        while idx < len(self._steps):
            if not self._should_skip_step(self._steps[idx]):
                return idx
            idx += 1
        return idx

    def _find_prev_step(self, start_idx: int) -> int:
        """Find the previous non-skipped step index.

        Args:
            start_idx: The index to start searching from (exclusive).

        Returns:
            The index of the previous step, or -1 if at beginning.
        """
        idx = start_idx - 1
        while idx >= 0:
            if not self._should_skip_step(self._steps[idx]):
                return idx
            idx -= 1
        return -1

    def _count_visible_steps(self) -> tuple[int, int]:
        """Count total and current position for visible steps.

        Returns:
            Tuple of (current_position, total_visible_steps) where positions are 1-indexed.
        """
        total = 0
        current = 0
        for i, step in enumerate(self._steps):
            if not self._should_skip_step(step):
                total += 1
                if i < self.state.current_step_idx:
                    current += 1
                elif i == self.state.current_step_idx:
                    current += 1

        return (current, total)

    def _update_progress(self) -> None:
        """Update the progress bar and step counter."""
        current, total = self._count_visible_steps()

        # Update progress bar
        try:
            progress_bar = self.query_one("#wizard_progress_bar", ProgressBar)
            progress_percent = (current / total) * 100 if total > 0 else 0
            progress_bar.update(progress=progress_percent)
        except Exception:
            pass

        # Update step counter
        try:
            step_counter = self.query_one("#wizard_step_counter", Label)
            step_counter.update(f"Step {current} of {total}")
        except Exception:
            pass

    def _update_navigation(self) -> None:
        """Update navigation button states."""
        try:
            back_btn = self.query_one("#wizard_back", Button)
            next_btn = self.query_one("#wizard_next", Button)

            # Disable back on first step
            prev_idx = self._find_prev_step(self.state.current_step_idx)
            if prev_idx < 0:
                back_btn.add_class("disabled")
                back_btn.disabled = True
            else:
                back_btn.remove_class("disabled")
                back_btn.disabled = False

            # Change next to "Finish" on last step
            next_idx = self._find_next_step(self.state.current_step_idx + 1)
            if next_idx >= len(self._steps):
                next_btn.label = "Finish"
            else:
                next_btn.label = "Next"

        except Exception:
            pass

    def _focus_first_widget(self) -> None:
        """Focus the first interactive widget in current step."""
        if not self._current_component:
            return

        # Query for focusable widgets in priority order
        for widget_type in ["Input", "Select", "OptionList", "Button", "Checkbox"]:
            widgets = self._current_component.query(widget_type)
            if widgets:
                try:
                    widgets.first().focus()
                    _wizard_log(f"WizardModal._focus_first_widget: Focused {widget_type}")
                    break
                except Exception as e:
                    _wizard_log(f"WizardModal._focus_first_widget: Failed to focus {widget_type}: {e}")

    def _show_error(self, message: str) -> None:
        """Show an error message.

        Args:
            message: The error message to display.
        """
        try:
            error_label = self.query_one("#wizard_error", Label)
            error_label.update(f"Error: {message}")
            error_label.remove_class("hidden")
        except Exception:
            pass

    def _hide_error(self) -> None:
        """Hide the error message."""
        try:
            error_label = self.query_one("#wizard_error", Label)
            error_label.add_class("hidden")
        except Exception:
            pass

    async def _show_step(self, step_idx: int) -> None:
        """Show a specific step.

        Args:
            step_idx: The index of the step to show.
        """
        if step_idx < 0 or step_idx >= len(self._steps):
            return

        step = self._steps[step_idx]
        _wizard_log(f"WizardModal._show_step: Showing step {step_idx} ({step.id})")

        self.state.current_step_idx = step_idx
        self.state.visited_steps.add(step.id)
        self._hide_error()

        # Update header
        try:
            title_label = self.query_one("#wizard_title", Label)
            title_label.update(step.title)

            desc_label = self.query_one("#wizard_description", Label)
            desc_label.update(step.description)
        except Exception:
            pass

        # Clear and mount the step component
        content_container = self.query_one("#wizard_content", Vertical)
        await content_container.remove_children()

        # Create the step component
        self._current_component = step.component_class(
            wizard_state=self.state,
            id=f"step_{step.id}",
        )

        await content_container.mount(self._current_component)

        # Restore value if we've visited this step before
        if step.id in self.state.step_data:
            self._current_component.set_value(self.state.step_data[step.id])

        # Update progress and navigation
        self._update_progress()
        self._update_navigation()

        # Auto-focus first interactive widget
        self.call_after_refresh(self._focus_first_widget)

    async def action_next_step(self) -> None:
        """Move to the next step."""
        if not self._current_component:
            return

        step = self._steps[self.state.current_step_idx]
        _wizard_log(f"WizardModal.action_next_step: Current step {step.id}")

        # Validate current step
        error = self._current_component.validate()
        if error:
            _wizard_log(f"WizardModal.action_next_step: Validation failed: {error}")
            self._show_error(error)
            self.state.set_error(step.id, error)
            return

        # Save current step data
        value = self._current_component.get_value()
        self.state.step_data[step.id] = value
        self.state.clear_error(step.id)
        _wizard_log(f"WizardModal.action_next_step: Saved value for {step.id}")

        # Find next step
        next_idx = self._find_next_step(self.state.current_step_idx + 1)
        if next_idx >= len(self._steps):
            # Wizard complete
            _wizard_log("WizardModal.action_next_step: Wizard complete")
            await self._complete_wizard()
        else:
            await self._show_step(next_idx)

    async def action_previous_step(self) -> None:
        """Move to the previous step."""
        if not self._current_component:
            return

        step = self._steps[self.state.current_step_idx]
        _wizard_log(f"WizardModal.action_previous_step: Current step {step.id}")

        # Save current value (without validation)
        value = self._current_component.get_value()
        self.state.step_data[step.id] = value

        # Find previous step
        prev_idx = self._find_prev_step(self.state.current_step_idx)
        if prev_idx >= 0:
            await self._show_step(prev_idx)

    async def action_cancel(self) -> None:
        """Cancel the wizard."""
        _wizard_log("WizardModal.action_cancel: Wizard cancelled")
        self.post_message(WizardCancelled())
        self.dismiss(None)

    async def action_confirm(self) -> None:
        """Confirm current step (same as Next)."""
        await self.action_next_step()

    async def _complete_wizard(self) -> None:
        """Complete the wizard and dismiss."""
        _wizard_log("WizardModal._complete_wizard: Completing wizard")
        result = await self.on_wizard_complete()
        self.post_message(WizardCompleted(result))
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        _wizard_log(f"WizardModal.on_button_pressed: {button_id}")

        if button_id == "wizard_back":
            self.run_worker(self.action_previous_step())
        elif button_id == "wizard_next":
            self.run_worker(self.action_next_step())
        elif button_id == "wizard_cancel":
            self.run_worker(self.action_cancel())

    def on_key(self, event: events.Key) -> None:
        """Handle key presses."""
        if event.key == "escape":
            self.run_worker(self.action_cancel())
            event.stop()
