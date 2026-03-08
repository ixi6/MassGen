"""
Quickstart Wizard for MassGen TUI.

Provides an interactive wizard for creating a MassGen configuration.
This replaces the questionary-based CLI quickstart with a Textual TUI experience.
"""

import asyncio
import contextlib
import io
import string
from pathlib import Path
from typing import Any

import yaml
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    OptionList,
    Select,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.option_list import Option

from massgen.config_builder import (
    DEFAULT_QUICKSTART_CONFIG_FILENAME,
    build_quickstart_config_path,
    normalize_quickstart_config_filename,
    sort_quickstart_provider_ids,
)

from .setup_wizard import DockerSetupStep
from .wizard_base import StepComponent, WizardModal, WizardState, WizardStep
from .wizard_steps import LaunchOptionsStep, WelcomeStep


def _agent_letter(index: int) -> str:
    """Convert 0-based index to letter (0='a', 1='b', etc.)."""
    return string.ascii_lowercase[index]


def _quickstart_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[QUICKSTART] {msg}")


class QuickstartWelcomeStep(WelcomeStep):
    """Welcome step customized for quickstart wizard."""

    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(
            wizard_state,
            title="MassGen Quickstart",
            subtitle="Create a configuration in minutes",
            features=[
                "Select number of agents",
                "Choose AI providers and models",
                "Configure tools and execution mode",
                "Generate ready-to-use YAML config",
            ],
            **kwargs,
        )


class AgentCountStep(StepComponent):
    """Step for selecting number of agents using native OptionList."""

    COUNTS = [
        ("1", "1 Agent", "Single agent mode"),
        ("2", "2 Agents", "Two agents collaborating"),
        ("3", "3 Agents (Recommended)", "Three agents for robust consensus"),
        ("4", "4 Agents", "Four agents for complex tasks"),
        ("5", "5 Agents", "Maximum agents for diverse perspectives"),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_count: str = "3"
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        yield Label("How many agents should work on your tasks?", classes="text-input-label")

        # Build native options
        textual_options = []
        for value, label, description in self.COUNTS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="count_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection (3 agents - index 2)
        if self._option_list:
            self._option_list.highlighted = 2

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler for option selection."""
        if event.option and event.option.id:
            self._selected_count = str(event.option.id)
            _quickstart_log(f"AgentCountStep: Selected {self._selected_count}")

    def get_value(self) -> int:
        return int(self._selected_count)

    def set_value(self, value: Any) -> None:
        if isinstance(value, int):
            self._selected_count = str(value)
            # Highlight option in OptionList
            idx = next(
                (i for i, (v, _, _) in enumerate(self.COUNTS) if v == str(value)),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx


class SetupModeStep(StepComponent):
    """Step for choosing same or different backends per agent using native OptionList."""

    OPTIONS = [
        ("same", "Same Backend for All", "Use the same provider and model for all agents"),
        ("different", "Different Backends", "Configure each agent separately"),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_mode: str = "different"
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        yield Label("How do you want to configure your agents?", classes="text-input-label")

        # Build native options
        textual_options = []
        for value, label, description in self.OPTIONS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="mode_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection (different - second item)
        if self._option_list:
            self._option_list.highlighted = 1

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler for option selection."""
        if event.option and event.option.id:
            self._selected_mode = str(event.option.id)
            _quickstart_log(f"SetupModeStep: Selected {self._selected_mode}")

    def get_value(self) -> str:
        return self._selected_mode

    def set_value(self, value: Any) -> None:
        if isinstance(value, str):
            self._selected_mode = value
            # Highlight option in OptionList
            idx = next(
                (i for i, (v, _, _) in enumerate(self.OPTIONS) if v == value),
                None,
            )
            if idx is not None and self._option_list:
                self._option_list.highlighted = idx


class ProviderModelStep(StepComponent):
    """Combined step for selecting provider and model.

    Shows provider selection first, then model selection for that provider.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        agent_label: str = "all agents",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._agent_label = agent_label
        self._provider_select: Select | None = None
        self._model_select: Select | None = None
        self._key_input: Input | None = None
        self._key_label: Label | None = None
        self._providers: list[tuple[str, str]] = []  # (provider_id, display_name)
        self._models_by_provider: dict[str, list[str]] = {}
        self._provider_has_key: dict[str, bool] = {}
        self._provider_env_var: dict[str, str] = {}
        self._current_provider: str | None = None
        self._current_model: str | None = None
        self._current_reasoning_effort: str | None = None
        self._reasoning_hint: Label | None = None
        self._reasoning_label: Label | None = None
        self._reasoning_select: Select | None = None

    def _load_providers(self) -> None:
        """Load all providers from ConfigBuilder, tracking which have keys."""
        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()
            api_keys = builder.detect_api_keys()
            ordered_provider_ids = sort_quickstart_provider_ids(list(builder.PROVIDERS.keys()))

            for provider_id in ordered_provider_ids:
                provider_info = builder.PROVIDERS.get(provider_id, {})
                name = provider_info.get("name", provider_id)
                models = provider_info.get("models", [])
                has_key = api_keys.get(provider_id, False)
                env_var = provider_info.get("env_var", "")

                self._providers.append((provider_id, name))
                self._models_by_provider[provider_id] = models
                self._provider_has_key[provider_id] = has_key
                self._provider_env_var[provider_id] = env_var

            # Default to first provider that has a key, else first overall
            configured = [pid for pid, _ in self._providers if self._provider_has_key.get(pid)]
            first = configured[0] if configured else (self._providers[0][0] if self._providers else None)
            if first:
                self._current_provider = first
                if self._models_by_provider.get(first):
                    self._current_model = self._models_by_provider[first][0]

        except Exception as e:
            _quickstart_log(f"ProviderModelStep._load_providers error: {e}")

    def _provider_options(self) -> list:
        """Build provider select options, marking unconfigured ones."""
        options = []
        for pid, name in self._providers:
            if self._provider_has_key.get(pid):
                options.append((name, pid))
            else:
                options.append((f"{name} (no API key)", pid))
        return options

    def _update_key_input(self) -> None:
        """Show/hide API key input based on current provider."""
        if not self._key_input or not self._key_label:
            return
        pid = self._current_provider
        if pid and not self._provider_has_key.get(pid):
            env_var = self._provider_env_var.get(pid, "")
            self._key_label.update(f"Enter API key ({env_var}):")
            self._key_label.display = True
            self._key_input.display = True
            self._key_input.placeholder = f"Paste your {env_var} here..."
            self._key_input.value = ""
        else:
            self._key_label.display = False
            self._key_input.display = False

    @staticmethod
    def _get_reasoning_profile(provider_id: str | None, model: str | None) -> dict[str, Any] | None:
        """Return quickstart reasoning options for the current provider/model."""
        if not provider_id or not model:
            return None
        try:
            from massgen.config_builder import ConfigBuilder

            return ConfigBuilder.get_quickstart_reasoning_profile(provider_id, model)
        except Exception:
            return None

    def _set_reasoning_visibility(self, visible: bool) -> None:
        for widget in [self._reasoning_hint, self._reasoning_label, self._reasoning_select]:
            if widget is not None:
                widget.display = visible

    def _update_reasoning_input(self) -> None:
        """Show/hide and populate reasoning selector based on provider/model."""
        if not self._reasoning_select:
            return

        profile = self._get_reasoning_profile(self._current_provider, self._current_model)
        if not profile:
            self._current_reasoning_effort = None
            self._set_reasoning_visibility(False)
            return

        choices = profile.get("choices", [])
        default_effort = profile.get("default_effort", "medium")
        selected_effort = default_effort

        self._current_reasoning_effort = selected_effort
        if not self.is_mounted:
            return

        try:
            self._reasoning_select.set_options(choices)
            self._reasoning_select.value = selected_effort
        except Exception as e:
            _quickstart_log(f"ProviderModelStep._update_reasoning_input error: {e}")
            return

        if self._reasoning_hint:
            self._reasoning_hint.update(profile.get("description", ""))
        self._set_reasoning_visibility(True)

    @staticmethod
    def _save_api_key(env_var: str, key: str) -> None:
        """Save API key to .env file."""
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()
        # Replace or append
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={key}"
                found = True
                break
        if not found:
            lines.append(f"{env_var}={key}")
        env_path.write_text("\n".join(lines) + "\n")

    def compose(self) -> ComposeResult:
        self._load_providers()

        yield Label(f"Select provider and model for {self._agent_label}:", classes="text-input-label")

        # Provider selection
        yield Label("Provider:", classes="text-input-label")
        provider_options = self._provider_options()
        self._provider_select = Select(
            provider_options,
            value=self._current_provider,
            id="provider_select",
        )
        yield self._provider_select

        # Inline API key input (hidden by default)
        self._key_label = Label("", classes="text-input-label")
        self._key_label.display = False
        yield self._key_label
        self._key_input = Input(
            placeholder="",
            password=True,
            classes="text-input",
            id="api_key_input",
        )
        self._key_input.display = False
        yield self._key_input

        # Model selection
        yield Label("Model:", classes="text-input-label")
        models = self._models_by_provider.get(self._current_provider, [])
        model_options = [(m, m) for m in models] if models else [("", "No models available")]
        self._model_select = Select(
            model_options,
            value=self._current_model,
            id="model_select",
        )
        yield self._model_select

        self._reasoning_hint = Label("", classes="password-hint")
        self._reasoning_hint.display = False
        yield self._reasoning_hint

        self._reasoning_label = Label("Reasoning effort:", classes="text-input-label")
        self._reasoning_label.display = False
        yield self._reasoning_label

        self._reasoning_select = Select(
            [("Select reasoning effort", "__placeholder__")],
            value="__placeholder__",
            id="reasoning_select",
        )
        self._reasoning_select.display = False
        yield self._reasoning_select

        self._update_key_input()
        self._update_reasoning_input()

    async def on_mount(self) -> None:
        self._update_key_input()
        self._update_reasoning_input()

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle provider selection change to update model list."""
        if event.select.id == "provider_select" and event.value != Select.BLANK:
            self._current_provider = str(event.value)
            _quickstart_log(f"ProviderModelStep: Provider changed to {self._current_provider}")

            self._update_key_input()

            # Update model select
            if self._model_select:
                models = self._models_by_provider.get(self._current_provider, [])
                model_options = [(m, m) for m in models] if models else [("", "No models available")]
                self._model_select.set_options(model_options)
                if models:
                    self._model_select.value = models[0]
                    self._current_model = models[0]
                else:
                    self._current_model = None
            self._update_reasoning_input()

        elif event.select.id == "model_select" and event.value != Select.BLANK:
            self._current_model = str(event.value)
            self._update_reasoning_input()
        elif event.select.id == "reasoning_select" and event.value != Select.BLANK:
            if str(event.value) == "__placeholder__":
                return
            self._current_reasoning_effort = str(event.value)

    def get_value(self) -> dict[str, str]:
        value = {
            "provider": self._current_provider or "",
            "model": self._current_model or "",
        }
        if self._current_reasoning_effort:
            value["reasoning_effort"] = self._current_reasoning_effort
        return value

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict):
            saved_reasoning_effort = value.get("reasoning_effort")
            if "provider" in value and self._provider_select:
                self._current_provider = value["provider"]
                self._provider_select.value = value["provider"]
            if "model" in value and self._model_select:
                self._current_model = value["model"]
                self._model_select.value = value["model"]
            self._update_reasoning_input()
            if saved_reasoning_effort and self._reasoning_select:
                try:
                    self._reasoning_select.value = saved_reasoning_effort
                    self._current_reasoning_effort = saved_reasoning_effort
                except Exception:
                    pass

    def validate(self) -> str | None:
        if not self._current_provider:
            return "Please select a provider"
        pid = self._current_provider
        if not self._provider_has_key.get(pid):
            # Check if user entered a key
            if self._key_input and self._key_input.value.strip():
                env_var = self._provider_env_var.get(pid, "")
                if env_var:
                    self._save_api_key(env_var, self._key_input.value.strip())
                    self._provider_has_key[pid] = True
            else:
                env_var = self._provider_env_var.get(pid, "")
                return f"Please enter your API key for {pid} ({env_var})"
        if not self._current_model:
            return "Please select a model"
        return None


class TabbedProviderModelStep(StepComponent):
    """Single tabbed step for configuring provider/model per agent."""

    def __init__(
        self,
        wizard_state: WizardState,
        agent_count: int = 3,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._agent_count = agent_count
        self._providers: list[tuple[str, str]] = []
        self._models_by_provider: dict[str, list[str]] = {}
        self._provider_has_key: dict[str, bool] = {}
        self._provider_env_var: dict[str, str] = {}
        # Keyed by agent letter ('a', 'b', 'c', ...)
        self._tab_selections: dict[str, dict[str, str | None]] = {}
        self._provider_selects: dict[str, Select] = {}
        self._model_selects: dict[str, Select] = {}
        self._key_inputs: dict[str, Input] = {}
        self._key_labels: dict[str, Label] = {}
        self._reasoning_hints: dict[str, Label] = {}
        self._reasoning_labels: dict[str, Label] = {}
        self._reasoning_selects: dict[str, Select] = {}

    def _load_providers(self) -> None:
        """Load all providers from ConfigBuilder, tracking which have keys."""
        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()
            api_keys = builder.detect_api_keys()
            ordered_provider_ids = sort_quickstart_provider_ids(list(builder.PROVIDERS.keys()))

            for provider_id in ordered_provider_ids:
                provider_info = builder.PROVIDERS.get(provider_id, {})
                name = provider_info.get("name", provider_id)
                models = provider_info.get("models", [])
                has_key = api_keys.get(provider_id, False)
                env_var = provider_info.get("env_var", "")

                self._providers.append((provider_id, name))
                self._models_by_provider[provider_id] = models
                self._provider_has_key[provider_id] = has_key
                self._provider_env_var[provider_id] = env_var

        except Exception as e:
            _quickstart_log(f"TabbedProviderModelStep._load_providers error: {e}")

    def _provider_options(self) -> list:
        options = []
        for pid, name in self._providers:
            if self._provider_has_key.get(pid):
                options.append((name, pid))
            else:
                options.append((f"{name} (no API key)", pid))
        return options

    def _update_key_input(self, agent_key: str, provider_id: str) -> None:
        key_label = self._key_labels.get(agent_key)
        key_input = self._key_inputs.get(agent_key)
        if not key_label or not key_input:
            return
        if not self._provider_has_key.get(provider_id):
            env_var = self._provider_env_var.get(provider_id, "")
            key_label.update(f"Enter API key ({env_var}):")
            key_label.display = True
            key_input.display = True
            key_input.placeholder = f"Paste your {env_var} here..."
            key_input.value = ""
        else:
            key_label.display = False
            key_input.display = False

    @staticmethod
    def _get_reasoning_profile(provider_id: str | None, model: str | None) -> dict[str, Any] | None:
        if not provider_id or not model:
            return None
        try:
            from massgen.config_builder import ConfigBuilder

            return ConfigBuilder.get_quickstart_reasoning_profile(provider_id, model)
        except Exception:
            return None

    def _set_reasoning_visibility(self, agent_key: str, visible: bool) -> None:
        for widget in [
            self._reasoning_hints.get(agent_key),
            self._reasoning_labels.get(agent_key),
            self._reasoning_selects.get(agent_key),
        ]:
            if widget is not None:
                widget.display = visible

    def _update_reasoning_input(self, agent_key: str, provider_id: str | None, model: str | None) -> None:
        """Show/hide and populate reasoning selector for one agent tab."""
        reasoning_select = self._reasoning_selects.get(agent_key)
        if reasoning_select is None:
            return

        profile = self._get_reasoning_profile(provider_id, model)
        if not profile:
            self._tab_selections.setdefault(agent_key, {})["reasoning_effort"] = None
            self._set_reasoning_visibility(agent_key, False)
            return

        choices = profile.get("choices", [])
        default_effort = profile.get("default_effort", "medium")
        selected_effort = default_effort

        self._tab_selections.setdefault(agent_key, {})["reasoning_effort"] = selected_effort
        if not self.is_mounted:
            return

        try:
            reasoning_select.set_options(choices)
            reasoning_select.value = selected_effort
        except Exception as e:
            _quickstart_log(f"TabbedProviderModelStep._update_reasoning_input error: {e}")
            return

        hint = self._reasoning_hints.get(agent_key)
        if hint:
            hint.update(profile.get("description", ""))
        self._set_reasoning_visibility(agent_key, True)

    def compose(self) -> ComposeResult:
        self._load_providers()

        # Default to first configured provider
        configured = [pid for pid, _ in self._providers if self._provider_has_key.get(pid)]
        default_provider = configured[0] if configured else (self._providers[0][0] if self._providers else None)
        default_model = self._models_by_provider.get(default_provider, [""])[0] if default_provider else None

        yield Label("Configure provider and model for each agent:", classes="text-input-label")

        provider_options = self._provider_options()

        with TabbedContent():
            for i in range(self._agent_count):
                letter = _agent_letter(i)
                self._tab_selections[letter] = {
                    "provider": default_provider,
                    "model": default_model,
                    "reasoning_effort": None,
                }

                with TabPane(f"Agent {letter.upper()}", id=f"tab_agent_{letter}"):
                    with VerticalScroll():
                        yield Label("Provider:", classes="text-input-label")
                        p_select = Select(
                            provider_options,
                            value=default_provider,
                            id=f"provider_{letter}",
                        )
                        self._provider_selects[letter] = p_select
                        yield p_select

                        # Inline API key input (hidden by default)
                        k_label = Label("", classes="text-input-label")
                        k_label.display = False
                        self._key_labels[letter] = k_label
                        yield k_label
                        k_input = Input(
                            placeholder="",
                            password=True,
                            classes="text-input",
                            id=f"apikey_{letter}",
                        )
                        k_input.display = False
                        self._key_inputs[letter] = k_input
                        yield k_input

                        yield Label("Model:", classes="text-input-label")
                        models = self._models_by_provider.get(default_provider, [])
                        model_options = [(m, m) for m in models] if models else [("", "No models")]
                        m_select = Select(
                            model_options,
                            value=default_model,
                            id=f"model_{letter}",
                        )
                        self._model_selects[letter] = m_select
                        yield m_select

                        reasoning_hint = Label("", classes="password-hint")
                        reasoning_hint.display = False
                        self._reasoning_hints[letter] = reasoning_hint
                        yield reasoning_hint

                        reasoning_label = Label("Reasoning effort:", classes="text-input-label")
                        reasoning_label.display = False
                        self._reasoning_labels[letter] = reasoning_label
                        yield reasoning_label

                        reasoning_select = Select(
                            [("Select reasoning effort", "__placeholder__")],
                            value="__placeholder__",
                            id=f"reasoning_{letter}",
                        )
                        reasoning_select.display = False
                        self._reasoning_selects[letter] = reasoning_select
                        yield reasoning_select

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Handle provider/model changes per tab."""
        sel_id = event.select.id or ""
        if not sel_id or event.value == Select.BLANK:
            return

        # Parse agent key from id like "provider_a" or "model_b"
        parts = sel_id.rsplit("_", 1)
        if len(parts) != 2 or len(parts[1]) != 1 or parts[1] not in string.ascii_lowercase:
            return
        kind, agent_key = parts[0], parts[1]

        if kind == "provider":
            provider = str(event.value)
            self._tab_selections[agent_key]["provider"] = provider
            self._update_key_input(agent_key, provider)
            # Update model select for this agent
            m_select = self._model_selects.get(agent_key)
            if m_select:
                models = self._models_by_provider.get(provider, [])
                model_options = [(m, m) for m in models] if models else [("", "No models")]
                m_select.set_options(model_options)
                if models:
                    m_select.value = models[0]
                    self._tab_selections[agent_key]["model"] = models[0]
                else:
                    self._tab_selections[agent_key]["model"] = None
            self._update_reasoning_input(
                agent_key,
                self._tab_selections[agent_key].get("provider"),
                self._tab_selections[agent_key].get("model"),
            )
        elif kind == "model":
            self._tab_selections[agent_key]["model"] = str(event.value)
            self._update_reasoning_input(
                agent_key,
                self._tab_selections[agent_key].get("provider"),
                self._tab_selections[agent_key].get("model"),
            )
        elif kind == "reasoning":
            if str(event.value) == "__placeholder__":
                return
            self._tab_selections[agent_key]["reasoning_effort"] = str(event.value)

    def get_value(self) -> dict[str, Any]:
        # Store per-agent configs in wizard state
        for agent_key, sel in self._tab_selections.items():
            agent_config = {
                "provider": sel.get("provider", ""),
                "model": sel.get("model", ""),
            }
            if sel.get("reasoning_effort"):
                agent_config["reasoning_effort"] = sel.get("reasoning_effort")
            self.wizard_state.set(
                f"agent_{agent_key}_config",
                agent_config,
            )
        return {"agent_configs": dict(self._tab_selections)}

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict) and "agent_configs" in value:
            for agent_key, sel in value["agent_configs"].items():
                self._tab_selections[agent_key] = sel
                p_select = self._provider_selects.get(agent_key)
                m_select = self._model_selects.get(agent_key)
                if p_select and sel.get("provider"):
                    p_select.value = sel["provider"]
                if m_select and sel.get("model"):
                    m_select.value = sel["model"]
                self._update_reasoning_input(
                    agent_key,
                    sel.get("provider"),
                    sel.get("model"),
                )
                reasoning_select = self._reasoning_selects.get(agent_key)
                reasoning_effort = sel.get("reasoning_effort")
                if reasoning_select and reasoning_effort:
                    try:
                        reasoning_select.value = reasoning_effort
                        self._tab_selections[agent_key]["reasoning_effort"] = reasoning_effort
                    except Exception:
                        pass

    async def on_mount(self) -> None:
        for i in range(self._agent_count):
            letter = _agent_letter(i)
            sel = self._tab_selections.get(letter, {})
            provider = sel.get("provider")
            if provider:
                self._update_key_input(letter, provider)
            self._update_reasoning_input(
                letter,
                provider,
                sel.get("model"),
            )

    def _get_active_tab_index(self) -> int:
        """Return the 0-based index of the currently active tab."""
        try:
            tc = self.query_one(TabbedContent)
            active_id = tc.active  # e.g. "tab_agent_b"
            if active_id and active_id.startswith("tab_agent_"):
                letter = active_id.split("_")[-1]
                return string.ascii_lowercase.index(letter)
        except Exception:
            pass
        return 0

    def try_retreat_tab(self) -> bool:
        """Try to move to the previous agent tab. Returns True if moved, False if on first."""
        current = self._get_active_tab_index()
        if current > 0:
            try:
                tc = self.query_one(TabbedContent)
                tc.active = f"tab_agent_{_agent_letter(current - 1)}"
                return True
            except Exception:
                pass
        return False

    def try_advance_tab(self) -> bool:
        """Try to move to the next agent tab. Returns True if moved, False if all done."""
        current = self._get_active_tab_index()
        if current + 1 < self._agent_count:
            try:
                tc = self.query_one(TabbedContent)
                tc.active = f"tab_agent_{_agent_letter(current + 1)}"
                return True
            except Exception:
                pass
        return False

    def validate(self) -> str | None:
        for i in range(self._agent_count):
            letter = _agent_letter(i)
            label = letter.upper()
            sel = self._tab_selections.get(letter, {})
            pid = sel.get("provider")
            if not pid:
                return f"Please select a provider for Agent {label}"
            if not self._provider_has_key.get(pid):
                key_input = self._key_inputs.get(letter)
                if key_input and key_input.value.strip():
                    env_var = self._provider_env_var.get(pid, "")
                    if env_var:
                        ProviderModelStep._save_api_key(env_var, key_input.value.strip())
                        self._provider_has_key[pid] = True
                else:
                    env_var = self._provider_env_var.get(pid, "")
                    return f"Please enter your API key for Agent {label} ({env_var})"
            if not sel.get("model"):
                return f"Please select a model for Agent {label}"
        return None


class ExecutionModeStep(StepComponent):
    """Step for selecting Docker or local execution mode using native OptionList."""

    OPTIONS = [
        ("docker", "Docker Mode (Recommended)", "Full code execution in isolated containers - most powerful"),
        ("local", "Local Mode", "File operations only, no code execution - simpler setup"),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_mode: str = "docker"
        self._option_list: OptionList | None = None

    def compose(self) -> ComposeResult:
        yield Label("Select execution mode:", classes="text-input-label")

        # Build native options
        textual_options = []
        for value, label, description in self.OPTIONS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="exec_list",
            classes="step-option-list",
        )
        yield self._option_list

        # Set default selection (docker - first item)
        if self._option_list:
            self._option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Native event handler for option selection."""
        if event.option and event.option.id:
            self._selected_mode = str(event.option.id)
            _quickstart_log(f"ExecutionModeStep: Selected {self._selected_mode}")

    def get_value(self) -> bool:
        return self._selected_mode == "docker"

    def set_value(self, value: Any) -> None:
        if isinstance(value, bool):
            self._selected_mode = "docker" if value else "local"
            # Highlight option in OptionList
            idx = 0 if self._selected_mode == "docker" else 1
            if self._option_list:
                self._option_list.highlighted = idx


class SkillsInstallStep(StepComponent):
    """Step for selecting and installing quickstart skill packages."""

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._packages_status: dict[str, dict[str, Any]] | None = None
        self._checkboxes: dict[str, Checkbox] = {}
        self._selected_packages: list[str] = []
        self._available_package_ids: list[str] = []
        self._install_button: Button | None = None
        self._status_label: Label | None = None
        self._status_message: str = ""
        self._installing: bool = False
        self._install_attempted: bool = False
        self._installed_packages: list[str] = []
        self._failed_packages: list[str] = []

    def _load_packages_status(self) -> None:
        """Load current skill package installation status."""
        try:
            from massgen.utils.skills_installer import check_skill_packages_installed

            self._packages_status = check_skill_packages_installed()
        except Exception as e:
            _quickstart_log(f"SkillsInstallStep: Failed to load packages status: {e}")
            self._packages_status = None

    def compose(self) -> ComposeResult:
        self._load_packages_status()
        self._checkboxes = {}
        self._available_package_ids = []

        yield Label("Skill Packages", classes="text-input-label")
        yield Label(
            "Select which quickstart packages to install now, then press Install Selected Packages.",
            classes="password-hint",
        )

        if self._packages_status is None:
            yield Label("Could not check skill package status.", classes="password-hint")
            return

        missing_packages: list[tuple[str, dict[str, Any]]] = []
        for pkg_id, pkg in self._packages_status.items():
            installed = bool(pkg.get("installed"))
            status_text = "installed" if installed else "not installed"
            yield Label(f"{pkg.get('name', pkg_id)} [{status_text}]", classes="password-hint")
            yield Label(f"  {pkg.get('description', '')}", classes="password-hint")
            if not installed:
                missing_packages.append((pkg_id, pkg))

        if not missing_packages:
            yield Label("All quickstart skill packages are already installed.", classes="password-hint")
            self._install_attempted = True
            return

        self._available_package_ids = [pkg_id for pkg_id, _ in missing_packages]

        if not self._selected_packages:
            self._selected_packages = list(self._available_package_ids)
        else:
            self._selected_packages = [pkg_id for pkg_id in self._selected_packages if pkg_id in self._available_package_ids]

        yield Label("Select packages to install:", classes="text-input-label")
        for pkg_id, pkg in missing_packages:
            cb = Checkbox(
                f"{pkg.get('name', pkg_id)}",
                value=pkg_id in self._selected_packages,
                id=f"skills_pkg_{pkg_id}",
            )
            cb.disabled = self._installing
            self._checkboxes[pkg_id] = cb
            yield cb

        self._install_button = Button(
            "Install Selected Packages",
            id="install_selected_skill_packages",
            variant="default",
        )
        if self._installing:
            self._install_button.disabled = True
            self._install_button.label = "Installing..."
        yield self._install_button

        self._status_label = Label(self._status_message, classes="password-hint")
        self._status_label.display = bool(self._status_message)
        yield self._status_label

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle package selection toggles."""
        for pkg_id, cb in self._checkboxes.items():
            if cb.id != event.checkbox.id:
                continue
            if event.value and pkg_id not in self._selected_packages:
                self._selected_packages.append(pkg_id)
            elif not event.value and pkg_id in self._selected_packages:
                self._selected_packages.remove(pkg_id)
            break

    @staticmethod
    def _run_installer_quiet(installer) -> tuple[bool, str]:
        """Run installer while capturing stdout/stderr to avoid TUI corruption."""
        output_buffer = io.StringIO()
        error_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(error_buffer):
            ok = bool(installer())
        combined = "\n".join([output_buffer.getvalue(), error_buffer.getvalue()]).strip()
        return ok, combined

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Install selected skill packages with progress updates."""
        if event.button.id != "install_selected_skill_packages" or self._installing:
            return

        if not self._selected_packages:
            self._install_attempted = True
            self._status_message = "No packages selected. You can continue."
            if self._status_label:
                self._status_label.update(self._status_message)
                self._status_label.display = True
            return

        self._installing = True
        if self._install_button:
            self._install_button.disabled = True
            self._install_button.label = "Installing..."
        for cb in self._checkboxes.values():
            cb.disabled = True

        def _status(message: str) -> None:
            self._status_message = message
            if self._status_label:
                self._status_label.update(message)
                self._status_label.display = True

        _status("Preparing skill package installation...")
        self._installed_packages = []
        self._failed_packages = []

        try:
            from massgen.utils.skills_installer import (
                install_agent_browser_skill,
                install_anthropic_skills,
                install_crawl4ai_skill,
                install_openai_skills,
                install_openskills_cli,
                install_remotion_skill,
                install_vercel_skills,
            )

            openskills_installers = {
                "anthropic": install_anthropic_skills,
                "openai": install_openai_skills,
                "vercel": install_vercel_skills,
                "agent_browser": install_agent_browser_skill,
                "remotion": install_remotion_skill,
            }

            selected = list(self._selected_packages)
            needs_openskills = any(pkg_id in openskills_installers for pkg_id in selected)
            openskills_ready = True

            if needs_openskills:
                _status("Installing openskills CLI...")
                openskills_ready, cli_logs = await asyncio.to_thread(
                    self._run_installer_quiet,
                    install_openskills_cli,
                )
                if cli_logs:
                    _quickstart_log(f"SkillsInstallStep: openskills logs:\n{cli_logs}")
                if not openskills_ready:
                    self._failed_packages.extend([pkg_id for pkg_id in selected if pkg_id in openskills_installers])

            for pkg_id in selected:
                if pkg_id in openskills_installers:
                    if not openskills_ready:
                        continue
                    _status(f"Installing {pkg_id}...")
                    ok, pkg_logs = await asyncio.to_thread(
                        self._run_installer_quiet,
                        openskills_installers[pkg_id],
                    )
                elif pkg_id == "crawl4ai":
                    _status("Installing crawl4ai...")
                    ok, pkg_logs = await asyncio.to_thread(
                        self._run_installer_quiet,
                        install_crawl4ai_skill,
                    )
                else:
                    _quickstart_log(f"SkillsInstallStep: Unknown package id '{pkg_id}'")
                    pkg_logs = ""
                    ok = False

                if pkg_logs:
                    _quickstart_log(f"SkillsInstallStep: {pkg_id} logs:\n{pkg_logs}")

                if ok:
                    self._installed_packages.append(pkg_id)
                else:
                    self._failed_packages.append(pkg_id)

            self._install_attempted = True
            if self._failed_packages:
                _status(
                    f"Installed {len(self._installed_packages)} package(s), " f"{len(self._failed_packages)} failed. Retry or adjust selection.",
                )
            else:
                _status(f"Installed {len(self._installed_packages)} package(s) successfully.")

        except Exception as e:
            self._install_attempted = True
            self._failed_packages = list(self._selected_packages)
            _quickstart_log(f"SkillsInstallStep: Installation error: {e}")
            _status(f"Skills installation failed: {e}")

        self._installing = False
        if self._install_button:
            self._install_button.disabled = False
            self._install_button.label = "Install Selected Packages"
        for cb in self._checkboxes.values():
            cb.disabled = False

        # Recompose so package status reflects newly installed items.
        self.refresh(recompose=True)

    def validate(self) -> str | None:
        if self._installing:
            return "Please wait for skill installation to finish"

        if not self._available_package_ids:
            return None

        if self._selected_packages and not self._install_attempted:
            return "Click 'Install Selected Packages' before continuing, or deselect all packages"

        return None

    def get_value(self) -> dict[str, Any]:
        return {
            "packages_to_install": list(self._selected_packages),
            "install_attempted": self._install_attempted,
            "installed_packages": list(self._installed_packages),
            "failed_packages": list(self._failed_packages),
        }

    def set_value(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        self._selected_packages = list(value.get("packages_to_install", []))
        self._install_attempted = bool(value.get("install_attempted", False))
        self._installed_packages = list(value.get("installed_packages", []))
        self._failed_packages = list(value.get("failed_packages", []))


class ContextPathStep(StepComponent):
    """Step for entering optional context/workspace path."""

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        yield Label("Context Path (optional):", classes="text-input-label")
        yield Label(
            "Enter a directory path the agents can access. Leave empty to skip.",
            classes="password-hint",
        )

        self._input = Input(
            placeholder="e.g., /path/to/project or . for current directory",
            classes="text-input",
            id="context_path_input",
        )
        yield self._input

        yield Label(
            "This grants agents read/write access to the specified directory.",
            classes="password-hint",
        )

    def get_value(self) -> str | None:
        if self._input and self._input.value.strip():
            return self._input.value.strip()
        return None

    def set_value(self, value: Any) -> None:
        if self._input and isinstance(value, str):
            self._input.value = value


class CoordinationModeStep(StepComponent):
    """Step for choosing coordination mode and decomposition answer controls."""

    OPTIONS = [
        (
            "voting",
            "Parallel Voting (Default)",
            "Traditional multi-agent voting with standard defaults",
        ),
        (
            "decomposition",
            "Decomposition",
            "Subtask ownership + presenter with lower per-agent answer caps",
        ),
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected_mode: str = "voting"
        self._option_list: OptionList | None = None
        self._presenter_label: Label | None = None
        self._presenter_select: Select | None = None
        self._per_agent_label: Label | None = None
        self._per_agent_input: Input | None = None
        self._global_label: Label | None = None
        self._global_input: Input | None = None
        self._novelty_label: Label | None = None
        self._novelty_select: Select | None = None

    def _agent_ids(self) -> list[str]:
        agent_count = self.wizard_state.get("agent_count", 3)
        return [f"agent_{_agent_letter(i)}" for i in range(agent_count)]

    def _recommended_global_cap(self) -> int:
        return max(3, len(self._agent_ids()) * 3)

    def _set_decomposition_visibility(self, visible: bool) -> None:
        for widget in [
            self._presenter_label,
            self._presenter_select,
            self._per_agent_label,
            self._per_agent_input,
            self._global_label,
            self._global_input,
            self._novelty_label,
            self._novelty_select,
        ]:
            if widget is not None:
                widget.display = visible

    def compose(self) -> ComposeResult:
        yield Label("Select coordination mode:", classes="text-input-label")

        textual_options = []
        for value, label, description in self.OPTIONS:
            option_text = f"[bold]{label}[/bold]\n[dim]{description}[/dim]"
            textual_options.append(Option(option_text, id=value))

        self._option_list = OptionList(
            *textual_options,
            id="coordination_mode_list",
            classes="step-option-list",
        )
        yield self._option_list

        if self._option_list:
            self._option_list.highlighted = 0

        yield Label(
            "Decomposition recommended defaults: per-agent 2 (recommended range 2-3), " "global cap = 3 x agents, novelty = balanced.",
            classes="password-hint",
        )

        presenter_options = [(agent_id, agent_id) for agent_id in self._agent_ids()]
        default_presenter = presenter_options[-1][1] if presenter_options else "agent_a"

        self._presenter_label = Label("Presenter agent:", classes="text-input-label")
        yield self._presenter_label
        self._presenter_select = Select(
            presenter_options if presenter_options else [("agent_a", "agent_a")],
            value=default_presenter,
            id="presenter_agent_select",
        )
        yield self._presenter_select

        self._per_agent_label = Label(
            "Max new answers per agent (recommended 2-3):",
            classes="text-input-label",
        )
        yield self._per_agent_label
        self._per_agent_input = Input(
            value="2",
            placeholder="2",
            classes="text-input",
            id="decomp_per_agent_input",
        )
        yield self._per_agent_input

        self._global_label = Label(
            "Max new answers globally (all agents combined):",
            classes="text-input-label",
        )
        yield self._global_label
        self._global_input = Input(
            value=str(self._recommended_global_cap()),
            placeholder=str(self._recommended_global_cap()),
            classes="text-input",
            id="decomp_global_input",
        )
        yield self._global_input

        self._novelty_label = Label(
            "Answer novelty requirement:",
            classes="text-input-label",
        )
        yield self._novelty_label
        self._novelty_select = Select(
            [
                ("Lenient", "lenient"),
                ("Balanced", "balanced"),
                ("Strict", "strict"),
            ],
            value="balanced",
            id="decomp_novelty_select",
        )
        yield self._novelty_select

        self._set_decomposition_visibility(False)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id:
            self._selected_mode = str(event.option.id)
            self._set_decomposition_visibility(self._selected_mode == "decomposition")

    def get_value(self) -> dict[str, Any]:
        if self._selected_mode != "decomposition":
            return {"coordination_mode": "voting"}

        presenter_value: str | None = None
        if self._presenter_select and self._presenter_select.value != Select.BLANK:
            presenter_value = str(self._presenter_select.value)

        max_per_agent = 2
        if self._per_agent_input and self._per_agent_input.value.strip():
            try:
                parsed = int(self._per_agent_input.value.strip())
                if parsed > 0:
                    max_per_agent = parsed
            except ValueError:
                pass

        max_global = self._recommended_global_cap()
        if self._global_input and self._global_input.value.strip():
            try:
                parsed = int(self._global_input.value.strip())
                if parsed > 0:
                    max_global = parsed
            except ValueError:
                pass

        novelty = "balanced"
        if self._novelty_select and self._novelty_select.value != Select.BLANK:
            novelty = str(self._novelty_select.value)

        return {
            "coordination_mode": "decomposition",
            "presenter_agent": presenter_value,
            "max_new_answers_per_agent": max_per_agent,
            "max_new_answers_global": max_global,
            "answer_novelty_requirement": novelty,
        }

    def set_value(self, value: Any) -> None:
        if not isinstance(value, dict):
            return

        mode = value.get("coordination_mode", "voting")
        self._selected_mode = "decomposition" if mode == "decomposition" else "voting"
        if self._option_list:
            self._option_list.highlighted = 1 if self._selected_mode == "decomposition" else 0

        if self._selected_mode == "decomposition":
            presenter_agent = value.get("presenter_agent")
            if presenter_agent and self._presenter_select:
                self._presenter_select.value = presenter_agent

            per_agent = value.get("max_new_answers_per_agent")
            if per_agent and self._per_agent_input:
                self._per_agent_input.value = str(per_agent)

            max_global = value.get("max_new_answers_global")
            if max_global and self._global_input:
                self._global_input.value = str(max_global)

            novelty = value.get("answer_novelty_requirement")
            if novelty and self._novelty_select:
                self._novelty_select.value = novelty

        self._set_decomposition_visibility(self._selected_mode == "decomposition")

    def validate(self) -> str | None:
        if self._selected_mode != "decomposition":
            return None

        if not self._presenter_select or self._presenter_select.value == Select.BLANK:
            return "Please select a presenter agent for decomposition mode"

        if self._per_agent_input:
            try:
                value = int(self._per_agent_input.value.strip())
                if value <= 0:
                    return "Max answers per agent must be a positive integer"
            except ValueError:
                return "Max answers per agent must be a positive integer"

        if self._global_input:
            try:
                value = int(self._global_input.value.strip())
                if value <= 0:
                    return "Max global answers must be a positive integer"
            except ValueError:
                return "Max global answers must be a positive integer"

        return None


class ConfigLocationStep(StepComponent):
    """Step for choosing where to save the generated config."""

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._selected: str = "project"
        self._filename: str = DEFAULT_QUICKSTART_CONFIG_FILENAME
        self._option_list: OptionList | None = None
        self._filename_input: Input | None = None
        self._warning_label: Label | None = None
        saved_value = self.wizard_state.get("config_location")
        if isinstance(saved_value, dict):
            self._selected = str(saved_value.get("location", "project"))
            self._filename = normalize_quickstart_config_filename(
                str(saved_value.get("filename", DEFAULT_QUICKSTART_CONFIG_FILENAME)),
            )
        elif isinstance(saved_value, str):
            self._selected = saved_value

    def _path_for(self, location: str, filename: str | None = None) -> Path:
        return build_quickstart_config_path(
            location=location,
            filename=filename or self._filename,
        )

    def _build_options(self) -> list:
        options = []
        for value, label, desc, path in [
            (
                "project",
                "This Project (Recommended)",
                ".massgen/ in current directory",
                self._path_for("project"),
            ),
            (
                "global",
                "Global",
                "~/.config/massgen/ — available from any directory",
                self._path_for("global"),
            ),
        ]:
            exists_tag = "  [yellow]⚠ exists[/yellow]" if path.exists() else ""
            option_text = f"[bold]{label}{exists_tag}[/bold]\n[dim]{desc}[/dim]"
            options.append(Option(option_text, id=value))
        return options

    def _current_filename(self) -> str:
        if self._filename_input:
            return self._filename_input.value.strip()
        return self._filename

    def _update_warning(self) -> None:
        if self._warning_label:
            filename = normalize_quickstart_config_filename(self._current_filename())
            path = self._path_for(self._selected, filename)
            if path.exists():
                self._warning_label.update(
                    f"[yellow]A config already exists at {path}. It will be overwritten.[/yellow]",
                )
                self._warning_label.display = True
            else:
                self._warning_label.display = False

    def compose(self) -> ComposeResult:
        yield Label("Where should the config be saved?", classes="text-input-label")

        self._option_list = OptionList(
            *self._build_options(),
            id="config_location_list",
            classes="step-option-list",
        )
        yield self._option_list

        if self._option_list:
            self._option_list.highlighted = 1 if self._selected == "global" else 0

        yield Label("Config filename:", classes="text-input-label")
        self._filename_input = Input(
            value=self._filename,
            placeholder=DEFAULT_QUICKSTART_CONFIG_FILENAME,
            classes="text-input",
            id="config_filename_input",
        )
        yield self._filename_input
        yield Label(
            "Only a filename is needed. Quickstart chooses the directory for you.",
            classes="password-hint",
        )

        self._warning_label = Label("", classes="password-hint")
        self._warning_label.display = False
        yield self._warning_label

        self._update_warning()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id:
            self._selected = str(event.option.id)
            self._update_warning()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "config_filename_input":
            self._filename = event.value.strip() or self._filename
            self._update_warning()

    def validate(self) -> str | None:
        raw_filename = self._current_filename()
        if not raw_filename:
            return "Please enter a config filename"

        if Path(raw_filename).name != raw_filename or raw_filename in {".", ".."}:
            return "Enter a filename only (no directory path)"

        return None

    def get_value(self) -> dict[str, str]:
        return {
            "location": self._selected,
            "filename": normalize_quickstart_config_filename(self._current_filename()),
        }

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict):
            location = str(value.get("location", "project"))
            filename = str(value.get("filename", DEFAULT_QUICKSTART_CONFIG_FILENAME))
        elif isinstance(value, str):
            location = value
            filename = self._filename
        else:
            return

        self._selected = location
        self._filename = normalize_quickstart_config_filename(filename)

        options = [("project", 0), ("global", 1)]
        idx = next((i for v, i in options if v == self._selected), None)
        if idx is not None and self._option_list:
            self._option_list.highlighted = idx
        if self._filename_input:
            self._filename_input.value = self._filename
        self._update_warning()


class ConfigPreviewStep(StepComponent):
    """Step for previewing the generated YAML configuration."""

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._textarea: TextArea | None = None

    def _generate_preview(self) -> str:
        """Generate YAML config from wizard state."""
        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()

            # Get agent count
            agent_count = self.wizard_state.get("agent_count", 3)
            setup_mode = self.wizard_state.get("setup_mode", "same")
            use_docker = self.wizard_state.get("execution_mode", True)
            context_path = self.wizard_state.get("context_path")

            # Build agents config
            agents_config = []

            if setup_mode == "same" or agent_count == 1:
                # Same provider/model for all agents
                provider_model = self.wizard_state.get("provider_model", {})
                provider = provider_model.get("provider", "openai")
                model = provider_model.get("model", "gpt-4o-mini")
                reasoning_effort = provider_model.get("reasoning_effort")

                for i in range(agent_count):
                    agent_spec = {
                        "id": f"agent_{_agent_letter(i)}",
                        "type": provider,
                        "model": model,
                    }
                    if reasoning_effort:
                        agent_spec["reasoning_effort"] = reasoning_effort
                    agents_config.append(agent_spec)
            else:
                # Different provider/model per agent
                for i in range(agent_count):
                    letter = _agent_letter(i)
                    agent_config = self.wizard_state.get(f"agent_{letter}_config", {})
                    agent_spec = {
                        "id": f"agent_{letter}",
                        "type": agent_config.get("provider", "openai"),
                        "model": agent_config.get("model", "gpt-4o-mini"),
                    }
                    if agent_config.get("reasoning_effort"):
                        agent_spec["reasoning_effort"] = agent_config.get("reasoning_effort")
                    agents_config.append(agent_spec)

            # Build context paths
            context_paths = None
            if context_path:
                context_paths = [{"path": context_path, "permission": "write"}]

            coordination_settings = self.wizard_state.get("coordination_mode_settings", {})
            if not isinstance(coordination_settings, dict):
                coordination_settings = {}

            # Generate config
            config = builder._generate_quickstart_config(
                agents_config=agents_config,
                context_paths=context_paths,
                use_docker=use_docker,
                coordination_settings=coordination_settings,
            )

            return yaml.dump(config, default_flow_style=False, sort_keys=False)

        except Exception as e:
            _quickstart_log(f"ConfigPreviewStep._generate_preview error: {e}")
            return f"# Error generating preview: {e}"

    def compose(self) -> ComposeResult:
        yield Label("Preview Configuration:", classes="preview-header")

        content = self._generate_preview()
        self._textarea = TextArea(
            content,
            classes="preview-content",
            id="config_preview",
            read_only=True,
        )
        yield self._textarea

    async def on_mount(self) -> None:
        """Refresh preview on mount."""
        if self._textarea:
            content = self._generate_preview()
            self._textarea.text = content

    def get_value(self) -> str:
        return self._textarea.text if self._textarea else ""


class QuickstartCompleteStep(StepComponent):
    """Final step showing completion and launch options."""

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)

    def compose(self) -> ComposeResult:
        with Container(classes="complete-container"):
            yield Label("OK", classes="complete-icon")
            yield Label("Configuration Ready!", classes="complete-title")

            location_data = self.wizard_state.get("config_location", "project")
            if isinstance(location_data, dict):
                location = str(location_data.get("location", "project"))
                filename = str(location_data.get("filename", DEFAULT_QUICKSTART_CONFIG_FILENAME))
            else:
                location = str(location_data or "project")
                filename = DEFAULT_QUICKSTART_CONFIG_FILENAME

            default = str(
                build_quickstart_config_path(
                    location=location,
                    filename=filename,
                ),
            )
            config_path = self.wizard_state.get("config_path", default)
            yield Label(f"Saved to: {config_path}", classes="complete-message")

            skills_data = self.wizard_state.get("install_skills_now", {})
            if isinstance(skills_data, dict):
                installed = skills_data.get("installed_packages", [])
                failed = skills_data.get("failed_packages", [])
                if installed:
                    yield Label(
                        f"Installed {len(installed)} skill package(s)",
                        classes="complete-next-steps",
                    )
                if failed:
                    yield Label(
                        f"{len(failed)} skill package(s) failed to install",
                        classes="complete-next-steps",
                    )

            launch_option = self.wizard_state.get("launch_option", "terminal")
            if launch_option == "terminal":
                yield Label("Launching MassGen Terminal TUI...", classes="complete-next-steps")
            elif launch_option == "web":
                yield Label("Launching MassGen Web UI...", classes="complete-next-steps")
            else:
                yield Label("Configuration saved. Run with:", classes="complete-next-steps")
                yield Label(f"  massgen --config {config_path}", classes="complete-next-steps")

    def get_value(self) -> bool:
        return True


class QuickstartWizard(WizardModal):
    """Quickstart wizard for creating MassGen configurations.

    Flow:
    1. Welcome
    2. Agent count
    3. Setup mode (same/different) - skipped if 1 agent
    4. Provider/model selection
    5. Execution mode
    6. Docker setup - skipped if local mode selected
    7. Skills setup - select packages and install in-step (skipped if local mode selected)
    8. Context path
    9. Coordination mode (multi-agent only)
    10. Preview
    11. Launch options
    12. Complete
    """

    def __init__(
        self,
        config_filename: str | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._dynamic_steps_added = False
        self._config_path: str | None = None
        if config_filename:
            self.state.set(
                "config_location",
                {
                    "location": "project",
                    "filename": normalize_quickstart_config_filename(config_filename),
                },
            )

    def get_steps(self) -> list[WizardStep]:
        """Return the wizard steps."""
        return [
            WizardStep(
                id="welcome",
                title="MassGen Quickstart",
                description="Create a configuration in minutes",
                component_class=QuickstartWelcomeStep,
            ),
            WizardStep(
                id="agent_count",
                title="Agent Count",
                description="How many agents should collaborate?",
                component_class=AgentCountStep,
            ),
            WizardStep(
                id="setup_mode",
                title="Setup Mode",
                description="Same or different backends per agent?",
                component_class=SetupModeStep,
                skip_condition=lambda state: state.get("agent_count", 3) == 1,
            ),
            WizardStep(
                id="provider_model",
                title="Provider & Model",
                description="Choose your AI provider and model",
                component_class=ProviderModelStep,
                skip_condition=lambda state: state.get("agent_count", 3) > 1 and state.get("setup_mode") == "different",
            ),
            # Dynamic per-agent steps are inserted here when setup_mode == "different"
            WizardStep(
                id="execution_mode",
                title="Execution Mode",
                description="Docker or local execution?",
                component_class=ExecutionModeStep,
            ),
            WizardStep(
                id="docker_setup",
                title="Docker Setup",
                description="Check Docker status and pull images",
                component_class=DockerSetupStep,
                skip_condition=lambda state: not state.get("execution_mode", True),
            ),
            WizardStep(
                id="install_skills_now",
                title="Skills",
                description="Install quickstart skill packages now?",
                component_class=SkillsInstallStep,
                skip_condition=lambda state: not state.get("execution_mode", True),
            ),
            WizardStep(
                id="context_path",
                title="Context Path",
                description="Optional workspace directory",
                component_class=ContextPathStep,
            ),
            WizardStep(
                id="coordination_mode_settings",
                title="Coordination",
                description="Parallel voting or decomposition presenter mode",
                component_class=CoordinationModeStep,
                skip_condition=lambda state: state.get("agent_count", 3) == 1,
            ),
            WizardStep(
                id="config_location",
                title="Save Location",
                description="Where to save the config",
                component_class=ConfigLocationStep,
            ),
            WizardStep(
                id="preview",
                title="Preview",
                description="Review your configuration",
                component_class=ConfigPreviewStep,
            ),
            WizardStep(
                id="launch_options",
                title="Launch Options",
                description="How do you want to proceed?",
                component_class=LaunchOptionsStep,
            ),
        ]

    async def action_next_step(self) -> None:
        """Override to insert per-agent model steps when setup_mode is 'different'."""
        if not self._current_component:
            return

        step = self._steps[self.state.current_step_idx]

        # Validate current step
        error = self._current_component.validate()
        if error:
            self._show_error(error)
            self.state.set_error(step.id, error)
            return

        # Save current step data
        value = self._current_component.get_value()
        self.state.step_data[step.id] = value
        self.state.clear_error(step.id)

        # After setup_mode selection, insert per-agent steps if "different"
        if step.id == "setup_mode" and not self._dynamic_steps_added:
            setup_mode = value if isinstance(value, str) else "same"
            agent_count = self.state.get("agent_count", 3)

            if setup_mode == "different" and agent_count > 1:
                # Find insertion point (after provider_model step)
                insert_idx = next(
                    (i for i, s in enumerate(self._steps) if s.id == "provider_model"),
                    None,
                )
                if insert_idx is not None:
                    # Insert a single tabbed step after the (skipped) provider_model step
                    count = agent_count

                    def make_tabbed_step(n):
                        class _TabbedStep(TabbedProviderModelStep):
                            def __init__(self, wizard_state, **kwargs):
                                super().__init__(wizard_state, agent_count=n, **kwargs)

                        return _TabbedStep

                    self._steps.insert(
                        insert_idx + 1,
                        WizardStep(
                            id="tabbed_agent_models",
                            title="Agent Models",
                            description="Configure provider and model for each agent",
                            component_class=make_tabbed_step(count),
                        ),
                    )

            self._dynamic_steps_added = True

        # If on tabbed step, advance to next tab before leaving the step
        if isinstance(self._current_component, TabbedProviderModelStep):
            if self._current_component.try_advance_tab():
                return

        # Find next step
        next_idx = self._find_next_step(self.state.current_step_idx + 1)
        if next_idx >= len(self._steps):
            await self._complete_wizard()
        else:
            await self._show_step(next_idx)

    async def action_previous_step(self) -> None:
        """Override to navigate between tabs before leaving the tabbed step."""
        if self._current_component and isinstance(self._current_component, TabbedProviderModelStep):
            if self._current_component.try_retreat_tab():
                return
        await super().action_previous_step()

    async def on_wizard_complete(self) -> Any:
        """Save the configuration and return launch options."""
        _quickstart_log("QuickstartWizard.on_wizard_complete: Saving configuration")

        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()

            # Get wizard state values
            agent_count = self.state.get("agent_count", 3)
            setup_mode = self.state.get("setup_mode", "same")
            use_docker = self.state.get("execution_mode", True)
            skills_step_data = self.state.get("install_skills_now", {})
            install_skills_now = False
            installed_skill_packages: list[str] = []
            failed_skill_packages: list[str] = []
            if isinstance(skills_step_data, dict):
                installed_skill_packages = list(skills_step_data.get("installed_packages", []))
                failed_skill_packages = list(skills_step_data.get("failed_packages", []))
            elif isinstance(skills_step_data, bool):
                # Backward compatibility: older bool step data means defer to CLI installer.
                install_skills_now = skills_step_data
            context_path = self.state.get("context_path")
            launch_option = self.state.get("launch_options", "terminal")

            # Build agents config
            agents_config = []

            if setup_mode == "same" or agent_count == 1:
                provider_model = self.state.get("provider_model", {})
                provider = provider_model.get("provider", "openai")
                model = provider_model.get("model", "gpt-4o-mini")
                reasoning_effort = provider_model.get("reasoning_effort")

                for i in range(agent_count):
                    agent_spec = {
                        "id": f"agent_{_agent_letter(i)}",
                        "type": provider,
                        "model": model,
                    }
                    if reasoning_effort:
                        agent_spec["reasoning_effort"] = reasoning_effort
                    agents_config.append(agent_spec)
            else:
                for i in range(agent_count):
                    letter = _agent_letter(i)
                    agent_config = self.state.get(f"agent_{letter}_config", {})
                    if not agent_config:
                        # Fallback to shared config
                        provider_model = self.state.get("provider_model", {})
                        agent_config = {
                            "provider": provider_model.get("provider", "openai"),
                            "model": provider_model.get("model", "gpt-4o-mini"),
                            "reasoning_effort": provider_model.get("reasoning_effort"),
                        }
                    agent_spec = {
                        "id": f"agent_{letter}",
                        "type": agent_config.get("provider", "openai"),
                        "model": agent_config.get("model", "gpt-4o-mini"),
                    }
                    if agent_config.get("reasoning_effort"):
                        agent_spec["reasoning_effort"] = agent_config.get("reasoning_effort")
                    agents_config.append(agent_spec)

            # Build context paths
            context_paths = None
            if context_path:
                context_paths = [{"path": context_path, "permission": "write"}]

            coordination_settings = self.state.get("coordination_mode_settings", {})
            if not isinstance(coordination_settings, dict):
                coordination_settings = {}

            # Generate config
            config = builder._generate_quickstart_config(
                agents_config=agents_config,
                context_paths=context_paths,
                use_docker=use_docker,
                coordination_settings=coordination_settings,
            )

            # Save config to chosen location + filename
            config_location_data = self.state.get("config_location", "project")
            if isinstance(config_location_data, dict):
                config_location = str(config_location_data.get("location", "project"))
                config_filename = str(config_location_data.get("filename", DEFAULT_QUICKSTART_CONFIG_FILENAME))
            else:
                config_location = str(config_location_data or "project")
                config_filename = DEFAULT_QUICKSTART_CONFIG_FILENAME

            normalized_filename = normalize_quickstart_config_filename(config_filename)
            self.state.set(
                "config_location",
                {
                    "location": config_location,
                    "filename": normalized_filename,
                },
            )
            config_path = build_quickstart_config_path(
                location=config_location,
                filename=normalized_filename,
            )
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            self._config_path = str(config_path.absolute())
            self.state.set("config_path", self._config_path)

            _quickstart_log(f"QuickstartWizard: Config saved to {self._config_path}")

            return {
                "success": True,
                "config_path": self._config_path,
                "launch_option": launch_option,
                "install_skills_now": bool(install_skills_now),
                "skills_installed": installed_skill_packages,
                "skills_failed": failed_skill_packages,
            }

        except Exception as e:
            _quickstart_log(f"QuickstartWizard: Failed to save config: {e}")
            return {
                "success": False,
                "error": str(e),
            }
