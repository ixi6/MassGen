"""
Reusable Step Components for MassGen TUI Wizards.

Provides pre-built step components for common wizard interactions:
- WelcomeStep: Welcome screen with title and description
- SingleSelectStep: Radio-button style single selection
- MultiSelectStep: Checkbox-style multiple selection
- ToggleStep: Boolean toggle (on/off)
- PasswordInputStep: Masked password input
- TextInputStep: Single-line text input
- TextAreaStep: Multi-line text area
- ModelSelectStep: Model selection with filtering
- PreviewStep: Read-only preview display
- CompleteStep: Completion message with next steps
"""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Checkbox, Input, Label, OptionList, Select, Switch, TextArea
from textual.widgets.option_list import Option

from .wizard_base import StepComponent, WizardState


def _step_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[STEP] {msg}")


class WelcomeStep(StepComponent):
    """Welcome screen step with feature list.

    The title and subtitle are shown in the wizard header.
    This component displays additional features/info.

    Attributes:
        title: Ignored (shown in header).
        subtitle: Ignored (shown in header).
        features: List of features/benefits to display.
    """

    # CSS moved to base.tcss for theme support
    DEFAULT_CSS = ""

    def __init__(
        self,
        wizard_state: WizardState,
        title: str = "Welcome",
        subtitle: str = "",
        features: list[str] | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._title = title
        self._subtitle = subtitle
        self._features = features or []

    def compose(self) -> ComposeResult:
        with Vertical(classes="wizard-welcome"):
            if self._features:
                yield Label("This wizard will help you:", classes="wizard-welcome-intro")
                for feature in self._features:
                    yield Label(f"  ✓ {feature}", classes="wizard-welcome-feature")

    def get_value(self) -> Any:
        return True  # Welcome step always "completes"


class SingleSelectStep(StepComponent):
    """Single selection step using native OptionList widget.

    Displays a list of options, only one can be selected at a time.
    Uses Textual's built-in OptionList for better keyboard navigation and accessibility.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        options: list[tuple[str, str, str]],  # (value, label, description)
        default_value: str | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize single select step.

        Args:
            wizard_state: The wizard state.
            options: List of (value, label, description) tuples.
            default_value: Optional default selection.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._options = options
        self._default_value = default_value
        self._selected_value: str | None = default_value
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        # Build native options with rich text formatting
        textual_options = []
        for value, label, description in self._options:
            # Format option with bold label and dimmed description
            if description:
                option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            else:
                option_text = f"[bold]{label}[/bold]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="option_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection
        if self._default_value:
            idx = next(
                (i for i, (v, _, _) in enumerate(self._options) if v == self._default_value),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler - no DOM walking needed."""
        if event.option and event.option.id:
            self._selected_value = str(event.option.id)
            _step_log(f"SingleSelectStep: Selected {self._selected_value}")

    def get_value(self) -> Any:
        return self._selected_value

    def set_value(self, value: Any) -> None:
        if isinstance(value, str):
            self._selected_value = value
            # Highlight option in OptionList
            idx = next(
                (i for i, (v, _, _) in enumerate(self._options) if v == value),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx

    def validate(self) -> str | None:
        if not self._selected_value:
            return "Please select an option"
        return None


class MultiSelectStep(StepComponent):
    """Multi-selection step with checkbox-style options.

    Displays a list of options with checkboxes, multiple can be selected.
    Uses native Checkbox widgets for better accessibility.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        options: list[tuple[str, str, str]],  # (value, label, description)
        default_values: list[str] | None = None,
        min_selections: int = 0,
        max_selections: int | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize multi-select step.

        Args:
            wizard_state: The wizard state.
            options: List of (value, label, description) tuples.
            default_values: Optional list of default selections.
            min_selections: Minimum number of required selections.
            max_selections: Maximum number of allowed selections.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._options = options
        self._default_values = default_values or []
        self._min_selections = min_selections
        self._max_selections = max_selections
        self._checkboxes: dict[str, Checkbox] = {}

    def compose(self) -> ComposeResult:
        # Use Vertical for better layout control
        with Vertical(classes="checkbox-list"):
            for value, label, description in self._options:
                # Format checkbox label with description
                if description:
                    checkbox_label = f"{label}\n  [dim]{description}[/dim]"
                else:
                    checkbox_label = label

                checkbox = Checkbox(
                    checkbox_label,
                    value=value in self._default_values,
                    id=f"checkbox_{value}",
                    classes="multi-select-checkbox",
                )
                self._checkboxes[value] = checkbox
                yield checkbox

    def get_value(self) -> list[str]:
        return [value for value, checkbox in self._checkboxes.items() if checkbox.value]

    def set_value(self, value: Any) -> None:
        if isinstance(value, list):
            for opt_value, checkbox in self._checkboxes.items():
                checkbox.value = opt_value in value

    def validate(self) -> str | None:
        selected = self.get_value()
        if len(selected) < self._min_selections:
            return f"Please select at least {self._min_selections} option(s)"
        if self._max_selections and len(selected) > self._max_selections:
            return f"Please select at most {self._max_selections} option(s)"
        return None


class ProviderSelectStep(StepComponent):
    """Provider selection step with API key status indicators.

    Shows providers with visual indicators for configured/unconfigured status.
    Uses OptionList for single selection or Checkboxes for multiple selection.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        providers: list[tuple[str, str, bool]],  # (provider_id, display_name, is_configured)
        allow_multiple: bool = False,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize provider select step.

        Args:
            wizard_state: The wizard state.
            providers: List of (provider_id, display_name, is_configured) tuples.
            allow_multiple: If True, allow multiple selections (uses checkboxes).
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._providers = providers
        self._allow_multiple = allow_multiple
        self._selected: list[str] = []
        self._option_list: OptionList | None = None
        self._checkboxes: dict[str, Checkbox] = {}

    def compose(self) -> ComposeResult:
        if self._allow_multiple:
            # Use checkboxes for multiple selection
            with Vertical(classes="provider-checkbox-list"):
                for provider_id, display_name, is_configured in self._providers:
                    status = "✓" if is_configured else "○"
                    status_text = "configured" if is_configured else "not configured"
                    checkbox_label = f"{status} {display_name} ({status_text})"

                    checkbox = Checkbox(
                        checkbox_label,
                        value=False,
                        id=f"provider_cb_{provider_id}",
                        classes="provider-checkbox",
                    )
                    self._checkboxes[provider_id] = checkbox
                    yield checkbox
        else:
            # Use OptionList for single selection
            textual_options = []
            for provider_id, display_name, is_configured in self._providers:
                status = "✓" if is_configured else "○"
                status_text = "configured" if is_configured else "not configured"
                option_text = f"[bold]{status} {display_name}[/bold]\n[dim]({status_text})[/dim]"
                textual_options.append(Option(option_text, id=provider_id))

            self._option_list = OptionList(
                *textual_options,
                id="provider_list",
                classes="step-option-list",
            )
            yield self._option_list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle OptionList selection (single selection mode)."""
        if event.option and event.option.id:
            self._selected = [str(event.option.id)]
            _step_log(f"ProviderSelectStep: Selected {self._selected}")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle Checkbox changes (multiple selection mode)."""
        # Update selected list based on checkbox states
        self._selected = [pid for pid, checkbox in self._checkboxes.items() if checkbox.value]
        _step_log(f"ProviderSelectStep: Selected {self._selected}")

    def get_value(self) -> list[str]:
        if self._allow_multiple:
            return [pid for pid, cb in self._checkboxes.items() if cb.value]
        return self._selected.copy()

    def set_value(self, value: Any) -> None:
        if isinstance(value, list):
            self._selected = value.copy()
            if self._allow_multiple:
                # Update checkboxes
                for pid, checkbox in self._checkboxes.items():
                    checkbox.value = pid in value
            else:
                # Highlight option in OptionList
                if value and self._option_list:
                    idx = next(
                        (i for i, (pid, _, _) in enumerate(self._providers) if pid == value[0]),
                        None,
                    )
                    if idx is not None:
                        self._option_list.highlighted = idx

    def validate(self) -> str | None:
        if not self.get_value():
            return "Please select at least one provider"
        return None


class ToggleStep(StepComponent):
    """Boolean toggle step with label and description.

    Shows a toggle switch for yes/no decisions.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        label: str,
        description: str = "",
        default_value: bool = False,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize toggle step.

        Args:
            wizard_state: The wizard state.
            label: Label for the toggle.
            description: Description of what the toggle does.
            default_value: Initial toggle state.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._label = label
        self._description = description
        self._default_value = default_value
        self._switch: Switch | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="toggle-container"):
            yield Label(self._label, classes="toggle-label")
            self._switch = Switch(value=self._default_value, id="toggle_switch")
            yield self._switch
            if self._description:
                yield Label(self._description, classes="toggle-description")

    def get_value(self) -> bool:
        return self._switch.value if self._switch else self._default_value

    def set_value(self, value: Any) -> None:
        if self._switch and isinstance(value, bool):
            self._switch.value = value


class PasswordInputStep(StepComponent):
    """Password input step with masked input.

    Shows a labeled password field for entering secrets like API keys.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        label: str,
        hint: str = "",
        placeholder: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize password input step.

        Args:
            wizard_state: The wizard state.
            label: Label for the input field.
            hint: Hint text shown below the input.
            placeholder: Placeholder text in the input.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._label = label
        self._hint = hint
        self._placeholder = placeholder
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="password-container"):
            yield Label(self._label, classes="password-label")
            self._input = Input(
                placeholder=self._placeholder,
                password=True,
                classes="password-input",
                id="password_input",
            )
            yield self._input
            if self._hint:
                yield Label(self._hint, classes="password-hint")

    def get_value(self) -> str:
        return self._input.value if self._input else ""

    def set_value(self, value: Any) -> None:
        if self._input and isinstance(value, str):
            self._input.value = value

    def validate(self) -> str | None:
        value = self.get_value()
        if not value or not value.strip():
            return "Please enter a value"
        return None


class TextInputStep(StepComponent):
    """Single-line text input step.

    Shows a labeled text input field.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        label: str,
        hint: str = "",
        placeholder: str = "",
        required: bool = False,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize text input step.

        Args:
            wizard_state: The wizard state.
            label: Label for the input field.
            hint: Hint text shown below the input.
            placeholder: Placeholder text in the input.
            required: If True, value is required for validation.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._label = label
        self._hint = hint
        self._placeholder = placeholder
        self._required = required
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="text-input-container"):
            yield Label(self._label, classes="text-input-label")
            self._input = Input(
                placeholder=self._placeholder,
                classes="text-input",
                id="text_input",
            )
            yield self._input
            if self._hint:
                yield Label(self._hint, classes="password-hint")

    def get_value(self) -> str:
        return self._input.value if self._input else ""

    def set_value(self, value: Any) -> None:
        if self._input and isinstance(value, str):
            self._input.value = value

    def validate(self) -> str | None:
        if self._required:
            value = self.get_value()
            if not value or not value.strip():
                return "This field is required"
        return None


class TextAreaStep(StepComponent):
    """Multi-line text area step.

    Shows a labeled text area for longer input.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        label: str,
        hint: str = "",
        default_value: str = "",
        required: bool = False,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize text area step.

        Args:
            wizard_state: The wizard state.
            label: Label for the text area.
            hint: Hint text shown below.
            default_value: Initial text content.
            required: If True, value is required.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._label = label
        self._hint = hint
        self._default_value = default_value
        self._required = required
        self._textarea: TextArea | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="text-input-container"):
            yield Label(self._label, classes="text-input-label")
            self._textarea = TextArea(
                self._default_value,
                classes="text-area-input",
                id="text_area",
            )
            yield self._textarea
            if self._hint:
                yield Label(self._hint, classes="password-hint")

    def get_value(self) -> str:
        return self._textarea.text if self._textarea else ""

    def set_value(self, value: Any) -> None:
        if self._textarea and isinstance(value, str):
            self._textarea.text = value

    def validate(self) -> str | None:
        if self._required:
            value = self.get_value()
            if not value or not value.strip():
                return "This field is required"
        return None


class ModelSelectStep(StepComponent):
    """Model selection step with search/filter.

    Shows a searchable list of models from a provider.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        models: list[str],
        label: str = "Select Model",
        default_model: str | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize model select step.

        Args:
            wizard_state: The wizard state.
            models: List of model names/IDs.
            label: Label for the selection.
            default_model: Optional default model.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._models = models
        self._label = label
        self._default_model = default_model
        self._select: Select | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="model-select-container"):
            yield Label(self._label, classes="model-select-label")

            # Use Select widget for model selection
            options = [(model, model) for model in self._models]
            default = self._default_model if self._default_model in self._models else None
            if not default and self._models:
                default = self._models[0]

            self._select = Select(
                options,
                value=default,
                id="model_select",
            )
            yield self._select

    def get_value(self) -> str | None:
        if self._select and self._select.value != Select.BLANK:
            return str(self._select.value)
        return None

    def set_value(self, value: Any) -> None:
        if self._select and isinstance(value, str) and value in self._models:
            self._select.value = value

    def validate(self) -> str | None:
        if not self.get_value():
            return "Please select a model"
        return None


class PreviewStep(StepComponent):
    """Read-only preview step for displaying content.

    Shows generated content (like YAML config) for review.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        title: str = "Preview",
        content_callback=None,  # Callable[[WizardState], str]
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize preview step.

        Args:
            wizard_state: The wizard state.
            title: Header title for the preview.
            content_callback: Function to generate preview content from wizard state.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._title = title
        self._content_callback = content_callback
        self._textarea: TextArea | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="preview-container"):
            yield Label(self._title, classes="preview-header")
            content = ""
            if self._content_callback:
                try:
                    content = self._content_callback(self.wizard_state)
                except Exception as e:
                    content = f"Error generating preview: {e}"

            self._textarea = TextArea(
                content,
                classes="preview-content",
                id="preview_content",
                read_only=True,
            )
            yield self._textarea

    async def on_mount(self) -> None:
        """Refresh preview content on mount."""
        if self._content_callback and self._textarea:
            try:
                content = self._content_callback(self.wizard_state)
                self._textarea.text = content
            except Exception as e:
                self._textarea.text = f"Error generating preview: {e}"

    def get_value(self) -> str:
        return self._textarea.text if self._textarea else ""


class CompleteStep(StepComponent):
    """Completion step showing success and next actions.

    Shows a success message with optional next steps.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        title: str = "Complete!",
        message: str = "",
        next_steps: list[str] | None = None,
        icon: str = "OK",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize complete step.

        Args:
            wizard_state: The wizard state.
            title: Success title.
            message: Success message.
            next_steps: Optional list of suggested next actions.
            icon: Icon/emoji to display.
        """
        super().__init__(wizard_state, id=id, classes=classes)
        self._title = title
        self._message = message
        self._next_steps = next_steps or []
        self._icon = icon

    def compose(self) -> ComposeResult:
        with Container(classes="complete-container"):
            yield Label(self._icon, classes="complete-icon")
            yield Label(self._title, classes="complete-title")
            if self._message:
                yield Label(self._message, classes="complete-message")
            for step in self._next_steps:
                yield Label(f"  {step}", classes="complete-next-steps")

    def get_value(self) -> bool:
        return True  # Complete step always "completes"


class SaveLocationStep(StepComponent):
    """Step for selecting where to save configuration files.

    Shows options for .env file locations using native OptionList.
    """

    LOCATIONS = [
        (".env", ".env (current directory)", "Highest priority, project-specific"),
        ("configs/.env", "configs/.env", "Project configs directory"),
        ("~/.massgen/.env", "~/.massgen/.env", "Global user config"),
        ("~/.config/massgen/.env", "~/.config/massgen/.env", "XDG config directory"),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_location: str = ".env"
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        # Build native options
        textual_options = []
        for value, label, description in self.LOCATIONS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="location_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection (first item)
        if self._option_list:
            self._option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler for option selection."""
        if event.option and event.option.id:
            self._selected_location = str(event.option.id)
            _step_log(f"SaveLocationStep: Selected {self._selected_location}")

    def get_value(self) -> str:
        return self._selected_location or ".env"

    def set_value(self, value: Any) -> None:
        if isinstance(value, str):
            self._selected_location = value
            # Highlight option in OptionList
            idx = next(
                (i for i, (v, _, _) in enumerate(self.LOCATIONS) if v == value),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx


class LaunchOptionsStep(StepComponent):
    """Step for selecting launch options after quickstart.

    Options: Terminal TUI, Web UI, Save only.
    Uses native OptionList for better keyboard navigation.
    """

    OPTIONS = [
        ("terminal", "Launch Terminal TUI", "Start MassGen in the terminal interface"),
        ("web", "Launch Web UI", "Start MassGen with the web interface"),
        ("save", "Save Config Only", "Save the configuration file without launching"),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_option: str = "terminal"
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        # Build native options
        textual_options = []
        for value, label, description in self.OPTIONS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="launch_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection (terminal - first item)
        if self._option_list:
            self._option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler for option selection."""
        if event.option and event.option.id:
            self._selected_option = str(event.option.id)
            _step_log(f"LaunchOptionsStep: Selected {self._selected_option}")

    def get_value(self) -> str:
        return self._selected_option

    def set_value(self, value: Any) -> None:
        if isinstance(value, str) and value in [o[0] for o in self.OPTIONS]:
            self._selected_option = value
            # Highlight option in OptionList
            idx = next(
                (i for i, (v, _, _) in enumerate(self.OPTIONS) if v == value),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx
