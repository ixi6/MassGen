"""
Setup Wizard for MassGen TUI.

Provides an interactive wizard for configuring API keys and initial setup.
This replaces the questionary-based CLI setup with a Textual TUI experience.
"""

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static

from .wizard_base import StepComponent, WizardModal, WizardState, WizardStep
from .wizard_steps import SaveLocationStep, WelcomeStep


class StatusIndicator(Static):
    """Simple status indicator widget showing icon + text.

    Temporary replacement until wizard_components is properly implemented.
    """

    STATUS_ICONS = {
        "success": "✓",
        "error": "✗",
        "warning": "⚠",
        "pending": "○",
        "loading": "◌",
    }

    def __init__(self, text: str, status: str = "pending", **kwargs):
        icon = self.STATUS_ICONS.get(status, "○")
        super().__init__(f"{icon} {text}", **kwargs)


def _setup_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[SETUP] {msg}")


class SetupWelcomeStep(WelcomeStep):
    """Welcome step customized for setup wizard."""

    def __init__(self, wizard_state: WizardState, **kwargs):
        super().__init__(
            wizard_state,
            title="Welcome to MassGen Setup",
            subtitle="Configure MassGen for first use",
            features=[
                "Detect and configure API keys",
                "Set up Docker for code execution",
                "Install additional skills",
            ],
            **kwargs,
        )


class ProviderSelectionStep(StepComponent):
    """Step for selecting which providers to configure.

    Shows all providers with their current configuration status.
    Users can select multiple unconfigured providers to set up.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._checkboxes: dict[str, Checkbox] = {}
        self._providers: list[tuple] = []  # (provider_id, name, is_configured, env_var)

    def _load_providers(self) -> None:
        """Load provider information from ConfigBuilder."""
        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()
            api_keys = builder.detect_api_keys()

            for provider_id, provider_info in builder.PROVIDERS.items():
                # Skip local models and Claude Code
                if provider_id in ("ollama", "llamacpp", "claude_code"):
                    continue

                name = provider_info.get("name", provider_id)
                env_var = provider_info.get("env_var", "")
                is_configured = api_keys.get(provider_id, False)

                self._providers.append((provider_id, name, is_configured, env_var))

        except Exception as e:
            _setup_log(f"ProviderSelectionStep._load_providers error: {e}")

    def compose(self) -> ComposeResult:
        self._load_providers()

        yield Label("Select providers to configure:", classes="text-input-label")
        yield Label("(Already configured providers are shown below)", classes="password-hint")

        with Vertical(classes="provider-list"):
            for provider_id, name, is_configured, env_var in self._providers:
                if not is_configured:
                    # Only show checkboxes for unconfigured providers
                    checkbox = Checkbox(
                        f"{name} (needs setup)",
                        value=False,  # Start unchecked, user selects what to configure
                        id=f"provider_cb_{provider_id}",
                    )
                    self._checkboxes[provider_id] = checkbox
                    yield checkbox
                else:
                    # Show status label for configured providers
                    yield Label(f"✓ {name} (configured)", classes="configured-label")

    def get_value(self) -> list[str]:
        """Return list of selected provider IDs."""
        return [pid for pid, cb in self._checkboxes.items() if cb.value]

    def set_value(self, value: Any) -> None:
        if isinstance(value, list):
            for pid, cb in self._checkboxes.items():
                cb.value = pid in value

    def validate(self) -> str | None:
        # Allow proceeding with no selection (user may already have all keys configured)
        return None


class DynamicApiKeyStep(StepComponent):
    """Dynamic step for entering an API key for a specific provider.

    This step is created dynamically for each selected provider.
    """

    def __init__(
        self,
        wizard_state: WizardState,
        provider_id: str,
        provider_name: str,
        env_var: str,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.env_var = env_var
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="password-container"):
            yield Label(f"Enter API Key for {self.provider_name}", classes="password-label")
            yield Label(f"Environment variable: {self.env_var}", classes="password-hint")

            self._input = Input(
                placeholder=f"Enter your {self.provider_name} API key...",
                password=True,
                classes="password-input",
                id=f"api_key_input_{self.provider_id}",
            )
            yield self._input

            yield Label(
                "Your API key will be saved securely in your .env file",
                classes="password-hint",
            )

    def get_value(self) -> dict[str, str]:
        """Return dict with env_var: api_key."""
        if self._input and self._input.value:
            return {self.env_var: self._input.value}
        return {}

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict) and self.env_var in value:
            if self._input:
                self._input.value = value[self.env_var]

    def validate(self) -> str | None:
        if not self._input or not self._input.value.strip():
            return f"Please enter your {self.provider_name} API key"
        return None


class DockerSetupStep(StepComponent):
    """Step for setting up Docker for code execution.

    Shows Docker diagnostics and allows selecting which images to pull.
    Uses modern StatusIndicator widgets for professional appearance.
    """

    DEFAULT_CSS = """
    DockerSetupStep {
        width: 100%;
        height: auto;
        padding: 0;
    }

    DockerSetupStep .docker-container {
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    DockerSetupStep .section-title {
        color: $primary;
        text-style: bold;
        width: 100%;
        margin: 1 0 0 0;
    }

    DockerSetupStep .status-group {
        width: 100%;
        padding: 0 1;
        margin: 0;
    }

    DockerSetupStep .resolution-list {
        width: 100%;
        padding: 0 2;
        color: $text-muted;
    }

    DockerSetupStep .image-select {
        width: 100%;
        padding: 0 1;
        margin: 0;
    }

    DockerSetupStep .image-checkbox {
        margin: 0 0 0 1;
    }

    DockerSetupStep .pull-button {
        margin: 1 0 0 2;
        min-width: 24;
        max-width: 30;
    }

    DockerSetupStep .pull-status {
        padding: 0 2;
        margin: 0;
        color: $text-muted;
    }

    DockerSetupStep .success-message {
        color: $success;
        padding: 0 1;
    }

    DockerSetupStep .error-message {
        color: $error;
        padding: 1;
    }
    """

    AVAILABLE_IMAGES = [
        {
            "name": "ghcr.io/massgen/mcp-runtime-sudo:latest",
            "short_name": "Sudo Runtime",
            "description": "Recommended - allows package installation",
            "default": True,
        },
        {
            "name": "ghcr.io/massgen/mcp-runtime:latest",
            "short_name": "Standard Runtime",
            "description": "Basic runtime without sudo access",
            "default": False,
        },
    ]

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._diagnostics = None
        self._checkboxes: dict[str, Checkbox] = {}
        self._selected_images: list[str] = []
        self._pull_button: Button | None = None
        self._pull_status: Label | None = None
        self._pulling = False
        self._spinner_timer = None
        self._spinner_frame = 0
        self._spinner_message = ""
        self._SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def _load_diagnostics(self) -> None:
        """Load Docker diagnostics."""
        try:
            from massgen.utils.docker_diagnostics import diagnose_docker

            self._diagnostics = diagnose_docker(check_images=True)
        except Exception as e:
            _setup_log(f"DockerSetupStep: Failed to load diagnostics: {e}")
            self._diagnostics = None

    def compose(self) -> ComposeResult:
        self._load_diagnostics()

        with Vertical(classes="docker-container"):
            # Status section with StatusIndicator widgets
            yield Label("System Status", classes="section-title")

            if self._diagnostics is None:
                yield StatusIndicator("Could not check Docker status", "error")
                return

            with Vertical(classes="status-group"):
                # Docker binary
                version_info = f" ({self._diagnostics.docker_version})" if self._diagnostics.docker_version else ""
                binary_status = "success" if self._diagnostics.binary_installed else "error"
                yield StatusIndicator(f"Docker binary{version_info}", binary_status)

                # Python library
                lib_status = "success" if self._diagnostics.pip_library_installed else "error"
                yield StatusIndicator("Docker Python library", lib_status)

                # Daemon
                daemon_status = "success" if self._diagnostics.daemon_running else "error"
                yield StatusIndicator("Docker daemon", daemon_status)

                # Permissions
                perm_status = "success" if self._diagnostics.has_permissions else "error"
                yield StatusIndicator("Permissions", perm_status)

            # If Docker not available, show resolution steps
            if not self._diagnostics.is_available:
                yield Label(self._diagnostics.error_message, classes="error-message")

                yield Label("Resolution Steps:", classes="section-title")
                with Vertical(classes="resolution-list"):
                    for step in self._diagnostics.resolution_steps:
                        yield Label(f"  {step}")
                return

            # Images section

            yield Label("Docker Images", classes="section-title")

            missing_images = []
            with Vertical(classes="status-group"):
                for img in self.AVAILABLE_IMAGES:
                    img_name = img["name"]
                    is_installed = self._diagnostics.images_available.get(img_name, False)
                    status = "success" if is_installed else "error"
                    yield StatusIndicator(img.get("short_name", img_name), status)
                    if not is_installed:
                        missing_images.append(img)

            # If all images installed, show success
            if not missing_images:
                yield Label("All Docker images are ready!", classes="success-message")
                return

            # Offer to pull missing images

            yield Label("Select images to pull:", classes="section-title")

            with Vertical(classes="image-select"):
                for img in missing_images:
                    img_name = img["name"]
                    cb = Checkbox(
                        f"{img.get('short_name', img_name)} - {img['description']}",
                        value=img.get("default", False),
                        id=f"docker_img_{img_name.replace('/', '_').replace(':', '_').replace('.', '_')}",
                        classes="image-checkbox",
                    )
                    self._checkboxes[img_name] = cb
                    if img.get("default", False):
                        self._selected_images.append(img_name)
                    yield cb

            self._pull_button = Button(
                "Pull Selected Images",
                id="pull_docker_images",
                variant="default",
                classes="pull-button",
            )
            yield self._pull_button

            self._pull_status = Label("", classes="pull-status")
            self._pull_status.display = False
            yield self._pull_status

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle."""
        for img_name, cb in self._checkboxes.items():
            if cb.id == event.checkbox.id:
                if event.value and img_name not in self._selected_images:
                    self._selected_images.append(img_name)
                elif not event.value and img_name in self._selected_images:
                    self._selected_images.remove(img_name)
                break

    def _animate_spinner(self) -> None:
        """Tick the spinner animation on the status label."""
        if self._pull_status and self._pulling:
            frame = self._SPINNER_FRAMES[self._spinner_frame % len(self._SPINNER_FRAMES)]
            self._pull_status.update(f"{frame} {self._spinner_message}")
            self._spinner_frame += 1

    def _start_spinner(self, message: str) -> None:
        """Start the animated spinner with a message."""
        self._spinner_message = message
        self._spinner_frame = 0
        if self._pull_status:
            self._pull_status.display = True
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._animate_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle pull button press."""
        if event.button.id != "pull_docker_images" or self._pulling:
            return

        if not self._selected_images:
            if self._pull_status:
                self._pull_status.update("No images selected.")
                self._pull_status.display = True
            return

        self._pulling = True
        if self._pull_button:
            self._pull_button.disabled = True
            self._pull_button.label = "Pulling..."
        # Disable checkboxes during pull
        for cb in self._checkboxes.values():
            cb.disabled = True

        import asyncio

        pulled = []
        failed = []
        for image in list(self._selected_images):
            self._start_spinner(f"Pulling {image}")

            _setup_log(f"DockerSetupStep: Pulling {image}")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "pull",
                    image,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # Stream stdout line-by-line to show layer progress
                if proc.stdout:
                    async for raw_line in proc.stdout:
                        line = raw_line.decode(errors="replace").strip()
                        if line:
                            self._spinner_message = line
                stderr = await proc.stderr.read() if proc.stderr else b""
                await proc.wait()
                if proc.returncode == 0:
                    pulled.append(image)
                    _setup_log(f"DockerSetupStep: Successfully pulled {image}")
                else:
                    failed.append(image)
                    err = stderr.decode().strip() if stderr else "unknown error"
                    _setup_log(f"DockerSetupStep: Failed to pull {image}: {err}")
            except Exception as e:
                failed.append(image)
                _setup_log(f"DockerSetupStep: Failed to pull {image}: {e}")

        self._stop_spinner()
        self._pulling = False

        # Update final status
        parts = []
        if pulled:
            parts.append(f"✓ Pulled {len(pulled)} image(s)")
            self._selected_images = [img for img in self._selected_images if img not in pulled]
        if failed:
            parts.append(f"✗ {len(failed)} failed: {', '.join(failed)}")

        if self._pull_status:
            self._pull_status.update(" | ".join(parts) if parts else "✓ Done")
            self._pull_status.display = True

        if self._pull_button:
            if failed:
                self._pull_button.label = "Retry Failed"
                self._pull_button.disabled = False
            else:
                self._pull_button.label = "All images pulled ✓"
                self._pull_button.disabled = True

        # Re-enable remaining checkboxes
        for cb in self._checkboxes.values():
            cb.disabled = False

    def validate(self) -> str | None:
        if self._pulling:
            return "Please wait for Docker image pull to finish"
        return None

    def get_value(self) -> dict[str, Any]:
        return {
            "available": self._diagnostics.is_available if self._diagnostics else False,
            "images_to_pull": self._selected_images,
        }

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict):
            self._selected_images = value.get("images_to_pull", [])
            for img_name, cb in self._checkboxes.items():
                cb.value = img_name in self._selected_images


class SkillsSetupStep(StepComponent):
    """Step for installing additional skills.

    Shows current skills status and allows selecting packages to install.
    Uses modern StatusIndicator widgets for professional appearance.
    """

    DEFAULT_CSS = """
    SkillsSetupStep {
        width: 100%;
        height: auto;
        padding: 0;
    }

    SkillsSetupStep .skills-container {
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    SkillsSetupStep .section-title {
        color: $primary;
        text-style: bold;
        width: 100%;
        margin-top: 0;
        margin-bottom: 0;
    }

    SkillsSetupStep .summary-box {
        width: 100%;
        padding: 0 1;
        margin-bottom: 0;
        background: transparent;
    }

    SkillsSetupStep .summary-stat {
        color: $text;
    }

    SkillsSetupStep .summary-detail {
        color: $text-muted;
        padding-left: 2;
    }

    SkillsSetupStep .package-list {
        width: 100%;
        padding: 0 1;
    }

    SkillsSetupStep .package-item {
        margin-bottom: 0;
    }

    SkillsSetupStep .package-desc {
        color: $text-muted;
        padding-left: 3;
    }

    SkillsSetupStep .package-select {
        width: 100%;
        padding: 1;
        margin-top: 1;
    }

    SkillsSetupStep .success-message {
        color: $success;
        text-align: center;
        padding: 1;
    }
    """

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)
        self._packages_status = None
        self._skills_info = None
        self._checkboxes: dict[str, Checkbox] = {}
        self._selected_packages: list[str] = []

    def _load_skills_status(self) -> None:
        """Load skills status."""
        try:
            from massgen.utils.skills_installer import (
                check_skill_packages_installed,
                list_available_skills,
            )

            self._skills_info = list_available_skills()
            self._packages_status = check_skill_packages_installed()
        except Exception as e:
            _setup_log(f"SkillsSetupStep: Failed to load skills status: {e}")
            self._skills_info = None
            self._packages_status = None

    def compose(self) -> ComposeResult:
        self._load_skills_status()

        with Vertical(classes="skills-container"):
            # Summary section
            yield Label("Skills Overview", classes="section-title")

            if self._skills_info is None:
                yield StatusIndicator("Could not check skills status", "error")
                return

            builtin = self._skills_info.get("builtin", [])
            user = self._skills_info.get("user", [])
            project = self._skills_info.get("project", [])
            installed_count = len(user) + len(project)
            total = len(builtin) + installed_count

            yield Label(f"  {total} skills available ({len(builtin)} built-in, {installed_count} user-installed)", classes="summary-detail")

            # Packages section

            yield Label("Skill Packages", classes="section-title")

            if self._packages_status is None:
                yield StatusIndicator("Could not check package status", "error")
                return

            packages_to_install = []
            with Vertical(classes="package-list"):
                for pkg_id, pkg in self._packages_status.items():
                    status = "success" if pkg["installed"] else "error"
                    status_text = "installed" if pkg["installed"] else "not installed"
                    skill_count = pkg.get("skill_count", 0)
                    count_info = f" ({skill_count} skills)" if skill_count and pkg["installed"] else ""

                    with Vertical(classes="package-item"):
                        yield StatusIndicator(f"{pkg['name']} [{status_text}{count_info}]", status)
                        yield Label(pkg["description"], classes="package-desc")

                    if not pkg["installed"]:
                        packages_to_install.append((pkg_id, pkg))

            # If all packages installed, show success
            if not packages_to_install:
                yield Label("All skill packages are ready!", classes="success-message")
                return

            # Offer to install missing packages

            yield Label("Select packages to install:", classes="section-title")

            with Vertical(classes="package-select"):
                for pkg_id, pkg in packages_to_install:
                    cb = Checkbox(
                        f"{pkg['name']} - {pkg['description']}",
                        value=True,  # Default to install
                        id=f"skills_pkg_{pkg_id}",
                    )
                    self._checkboxes[pkg_id] = cb
                    self._selected_packages.append(pkg_id)
                    yield cb

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox toggle."""
        for pkg_id, cb in self._checkboxes.items():
            if cb.id == event.checkbox.id:
                if event.value and pkg_id not in self._selected_packages:
                    self._selected_packages.append(pkg_id)
                elif not event.value and pkg_id in self._selected_packages:
                    self._selected_packages.remove(pkg_id)
                break

    def get_value(self) -> dict[str, Any]:
        return {
            "packages_to_install": self._selected_packages,
        }

    def set_value(self, value: Any) -> None:
        if isinstance(value, dict):
            self._selected_packages = value.get("packages_to_install", [])
            for pkg_id, cb in self._checkboxes.items():
                cb.value = pkg_id in self._selected_packages


class SetupCompleteStep(StepComponent):
    """Final step showing setup completion and next actions."""

    DEFAULT_CSS = """
    SetupCompleteStep {
        align: center middle;
        width: 100%;
        height: 100%;
    }

    SetupCompleteStep .complete-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 2;
    }

    SetupCompleteStep .complete-icon {
        text-align: center;
        width: 100%;
        color: $success;
        text-style: bold;
        content-align: center middle;
    }

    SetupCompleteStep .complete-title {
        text-align: center;
        width: 100%;
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }

    SetupCompleteStep .summary-list {
        width: 100%;
        padding: 0 2;
    }

    SetupCompleteStep .next-steps-title {
        text-align: center;
        width: 100%;
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 0;
    }

    SetupCompleteStep .next-step-item {
        width: 100%;
        color: $text-muted;
        text-align: center;
    }

    SetupCompleteStep #launch_quickstart {
        margin-top: 1;
        width: auto;
        min-width: 30;
    }
    """

    SUCCESS_ICON = "[bold green]✓[/bold green]"

    def __init__(
        self,
        wizard_state: WizardState,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(wizard_state, id=id, classes=classes)

    def compose(self) -> ComposeResult:
        with Vertical(classes="complete-container"):
            yield Static(self.SUCCESS_ICON, classes="complete-icon")

            # Show what was configured using StatusIndicator
            configured = self.wizard_state.get("configured_providers", [])
            save_location = self.wizard_state.get("save_location", ".env")
            docker_images = self.wizard_state.get("docker_images_pulled", [])
            skills_installed = self.wizard_state.get("skills_installed", [])

            with Vertical(classes="summary-list"):
                if configured:
                    yield StatusIndicator(f"Configured {len(configured)} provider(s)", "success")

                if save_location:
                    yield StatusIndicator(f"API keys saved to: {save_location}", "success")

                if docker_images:
                    yield StatusIndicator(f"Pulled {len(docker_images)} Docker image(s)", "success")

                if skills_installed:
                    yield StatusIndicator(f"Installed {len(skills_installed)} skill package(s)", "success")

            yield Label("What's Next?", classes="next-steps-title")
            yield Button("Launch Quickstart →", id="launch_quickstart", variant="success")
            yield Label("Or 'massgen --config your_config.yaml' to start", classes="next-step-item")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch_quickstart":
            self.wizard_state.set("launch_quickstart", True)
            # Trigger wizard finish by posting action to the parent wizard
            await self.screen.action_next_step()

    def get_value(self) -> bool:
        return True


class SetupWizard(WizardModal):
    """Setup wizard for configuring API keys, Docker, and skills.

    Flow:
    1. Welcome
    2. Provider selection
    3. API key input for each selected provider (dynamic)
    4. Save location selection
    5. Docker setup (optional)
    6. Skills installation (optional)
    7. Complete
    """

    # Short labels for breadcrumb stepper
    STEP_LABELS = ["Welcome", "Providers", "Save", "Docker", "Skills", "Done"]

    def __init__(
        self,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._dynamic_steps_added = False
        self._providers_info: dict[str, tuple] = {}  # provider_id -> (name, env_var)

    def get_step_labels(self) -> list[str]:
        """Return short labels for the breadcrumb stepper."""
        return self.STEP_LABELS

    def get_wizard_subtitle(self) -> str:
        """Return subtitle for the banner."""
        return "Configure your multi-agent AI environment"

    def _load_providers_info(self) -> None:
        """Load provider information for dynamic step creation."""
        try:
            from massgen.config_builder import ConfigBuilder

            builder = ConfigBuilder()
            for provider_id, provider_info in builder.PROVIDERS.items():
                if provider_id in ("ollama", "llamacpp", "claude_code"):
                    continue
                name = provider_info.get("name", provider_id)
                env_var = provider_info.get("env_var", "")
                self._providers_info[provider_id] = (name, env_var)
        except Exception as e:
            _setup_log(f"SetupWizard._load_providers_info error: {e}")

    def get_steps(self) -> list[WizardStep]:
        """Return the initial steps. Dynamic steps are added after provider selection."""
        self._load_providers_info()

        return [
            WizardStep(
                id="welcome",
                title="Welcome to MassGen Setup",
                description="Configure API keys for AI providers",
                component_class=SetupWelcomeStep,
            ),
            WizardStep(
                id="select_providers",
                title="Select Providers",
                description="Choose which providers to configure",
                component_class=ProviderSelectionStep,
            ),
            # Dynamic API key steps will be inserted here
            WizardStep(
                id="save_location",
                title="Save Location",
                description="Choose where to save your API keys",
                component_class=SaveLocationStep,
            ),
            WizardStep(
                id="docker_setup",
                title="Docker Setup",
                description="Configure Docker for code execution",
                component_class=DockerSetupStep,
            ),
            WizardStep(
                id="skills_setup",
                title="Skills Installation",
                description="Install additional MassGen skills",
                component_class=SkillsSetupStep,
            ),
            WizardStep(
                id="complete",
                title="Setup Complete",
                description="Your setup has been configured",
                component_class=SetupCompleteStep,
            ),
        ]

    async def action_next_step(self) -> None:
        """Override to handle dynamic step generation after provider selection."""
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

        # If we just completed provider selection, create dynamic API key steps
        if step.id == "select_providers" and not self._dynamic_steps_added:
            selected_providers = value if isinstance(value, list) else []
            _setup_log(f"SetupWizard: Selected providers: {selected_providers}")

            if selected_providers:
                # Insert dynamic steps before save_location
                insert_idx = self.state.current_step_idx + 1

                for provider_id in selected_providers:
                    if provider_id in self._providers_info:
                        name, env_var = self._providers_info[provider_id]

                        # Create a custom component class for this provider
                        def make_component_class(pid, pname, penv):
                            class DynamicStep(DynamicApiKeyStep):
                                def __init__(self, wizard_state, **kwargs):
                                    super().__init__(wizard_state, pid, pname, penv, **kwargs)

                            return DynamicStep

                        new_step = WizardStep(
                            id=f"api_key_{provider_id}",
                            title=f"Configure {name}",
                            description=f"Enter your {name} API key",
                            component_class=make_component_class(provider_id, name, env_var),
                        )
                        self._steps.insert(insert_idx, new_step)
                        insert_idx += 1

            self._dynamic_steps_added = True

        # Find next step
        next_idx = self._find_next_step(self.state.current_step_idx + 1)
        if next_idx >= len(self._steps):
            await self._complete_wizard()
        else:
            await self._show_step(next_idx)

    async def on_wizard_complete(self) -> Any:
        """Save the API keys to the selected location."""
        _setup_log("SetupWizard.on_wizard_complete: Saving API keys")

        # Collect all API keys from dynamic steps
        collected_keys: dict[str, str] = {}
        configured_providers: list[str] = []

        for step_id, step_data in self.state.step_data.items():
            if step_id.startswith("api_key_") and isinstance(step_data, dict):
                collected_keys.update(step_data)
                provider_id = step_id.replace("api_key_", "")
                configured_providers.append(provider_id)

        # Get save location
        save_location = self.state.get("save_location", ".env")
        _setup_log(f"SetupWizard: Saving to {save_location}, keys: {list(collected_keys.keys())}")

        # Determine target path
        if save_location == "~/.massgen/.env":
            env_dir = Path.home() / ".massgen"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_path = env_dir / ".env"
        elif save_location == "~/.config/massgen/.env":
            env_dir = Path.home() / ".config" / "massgen"
            env_dir.mkdir(parents=True, exist_ok=True)
            env_path = env_dir / ".env"
        elif save_location == "configs/.env":
            env_dir = Path("configs")
            env_dir.mkdir(parents=True, exist_ok=True)
            env_path = env_dir / ".env"
        else:
            env_path = Path(".env")

        # Merge with existing .env if present
        existing_content = {}
        if env_path.exists():
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            existing_content[key.strip()] = value.strip()
            except Exception as e:
                _setup_log(f"SetupWizard: Could not read existing .env: {e}")

        # Merge: existing + new (new overwrites)
        existing_content.update(collected_keys)
        final_keys = existing_content

        # Write .env file
        try:
            with open(env_path, "w") as f:
                f.write("# MassGen API Keys\n")
                f.write("# Generated by MassGen TUI Setup Wizard\n\n")

                for env_var, api_key in sorted(final_keys.items()):
                    f.write(f"{env_var}={api_key}\n")

            _setup_log(f"SetupWizard: Saved API keys to {env_path.absolute()}")

            # Reload environment variables
            load_dotenv(env_path, override=True)

        except Exception as e:
            _setup_log(f"SetupWizard: Failed to save .env: {e}")
            return {"success": False, "error": str(e)}

        # Store info for complete step
        self.state.set("configured_providers", configured_providers)
        self.state.set("save_location", str(env_path.absolute()))

        # Handle Docker image pulls if requested
        docker_data = self.state.get("docker_setup", {})
        images_to_pull = docker_data.get("images_to_pull", []) if isinstance(docker_data, dict) else []
        pulled_images = []

        if images_to_pull:
            _setup_log(f"SetupWizard: Pulling Docker images: {images_to_pull}")
            try:
                import subprocess

                for image in images_to_pull:
                    _setup_log(f"SetupWizard: Pulling {image}")
                    result = subprocess.run(
                        ["docker", "pull", image],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode == 0:
                        pulled_images.append(image)
                        _setup_log(f"SetupWizard: Successfully pulled {image}")
                    else:
                        _setup_log(f"SetupWizard: Failed to pull {image}: {result.stderr}")
            except Exception as e:
                _setup_log(f"SetupWizard: Docker pull failed: {e}")

        self.state.set("docker_images_pulled", pulled_images)

        # Handle skills installation if requested
        skills_data = self.state.get("skills_setup", {})
        packages_to_install = skills_data.get("packages_to_install", []) if isinstance(skills_data, dict) else []
        installed_packages = []

        if packages_to_install:
            _setup_log(f"SetupWizard: Installing skill packages: {packages_to_install}")
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

                requested_openskills_packages = [pkg for pkg in packages_to_install if pkg in openskills_installers]
                if requested_openskills_packages:
                    _setup_log("SetupWizard: Installing openskills CLI")
                    openskills_ready = install_openskills_cli()
                else:
                    openskills_ready = True

                for package_id in packages_to_install:
                    if package_id == "crawl4ai":
                        _setup_log("SetupWizard: Installing Crawl4AI")
                        if install_crawl4ai_skill():
                            installed_packages.append("crawl4ai")
                        continue

                    installer = openskills_installers.get(package_id)
                    if installer is None:
                        _setup_log(f"SetupWizard: Unknown package '{package_id}', skipping")
                        continue

                    if not openskills_ready:
                        _setup_log(f"SetupWizard: Skipping '{package_id}' because openskills CLI install failed")
                        continue

                    _setup_log(f"SetupWizard: Installing '{package_id}'")
                    if installer():
                        installed_packages.append(package_id)

            except Exception as e:
                _setup_log(f"SetupWizard: Skills installation failed: {e}")

        self.state.set("skills_installed", installed_packages)

        return {
            "success": True,
            "configured_providers": configured_providers,
            "save_location": str(env_path.absolute()),
            "docker_images_pulled": pulled_images,
            "skills_installed": installed_packages,
            "launch_quickstart": self.state.get("launch_quickstart", False),
        }
