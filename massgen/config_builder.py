#!/usr/bin/env python3
"""
MassGen Interactive Configuration Builder

A user-friendly CLI tool to create MassGen configuration files without
manually writing YAML. Guides users through agent selection, tool configuration,
and workspace setup.

Usage:
    python -m massgen.config_builder
    python -m massgen.cli --build-config
"""

import os
from pathlib import Path
from typing import Any

import questionary
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.theme import Theme

from massgen.backend.capabilities import (
    BACKEND_CAPABILITIES,
    get_capabilities,
    has_capability,
)
from massgen.utils.model_matcher import get_all_models_for_provider


def _get_provider_capabilities(provider_id: str) -> dict[str, bool]:
    """Get capability flags for a provider for quickstart UI.

    Args:
        provider_id: The provider/backend type (e.g., "openai", "claude")

    Returns:
        Dict with boolean flags for supported capabilities
    """
    caps = get_capabilities(provider_id)
    if not caps:
        return {"web_search": False, "code_execution": False}
    return {
        "web_search": "web_search" in caps.supported_capabilities,
        "code_execution": "code_execution" in caps.supported_capabilities,
    }


DEFAULT_QUICKSTART_CONFIG_FILENAME = "config.yaml"
QUICKSTART_PROVIDER_PRIORITY = (
    "claude_code",
    "codex",
    "gemini",
)


def sort_quickstart_provider_ids(provider_ids: list[str]) -> list[str]:
    """Return provider IDs with quickstart defaults prioritized.

    Priority order is:
    1. claude_code
    2. codex
    3. gemini

    Any remaining providers keep their original relative order.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for provider_id in QUICKSTART_PROVIDER_PRIORITY:
        if provider_id in provider_ids and provider_id not in seen:
            ordered.append(provider_id)
            seen.add(provider_id)

    for provider_id in provider_ids:
        if provider_id not in seen:
            ordered.append(provider_id)
            seen.add(provider_id)

    return ordered


def normalize_quickstart_config_filename(
    filename: str | None,
    default: str = DEFAULT_QUICKSTART_CONFIG_FILENAME,
) -> str:
    """Normalize a quickstart config filename.

    - Keeps only the basename so quickstart controls the target directory.
    - Falls back to ``default`` when value is empty/invalid.
    - Appends ``.yaml`` when no extension is provided.
    """
    fallback = Path((default or DEFAULT_QUICKSTART_CONFIG_FILENAME).strip() or DEFAULT_QUICKSTART_CONFIG_FILENAME).name
    if fallback in {"", ".", ".."}:
        fallback = DEFAULT_QUICKSTART_CONFIG_FILENAME

    candidate = Path((filename or "").strip()).name
    if candidate in {"", ".", ".."}:
        candidate = fallback

    if not Path(candidate).suffix:
        candidate = f"{candidate}.yaml"

    return candidate


def build_quickstart_config_path(
    *,
    location: str = "project",
    filename: str | None = None,
    cwd: Path | None = None,
    home_dir: Path | None = None,
) -> Path:
    """Build a quickstart config output path from location + filename."""
    normalized_filename = normalize_quickstart_config_filename(filename)

    if location == "global":
        base_dir = (home_dir or Path.home()) / ".config" / "massgen"
    else:
        base_dir = (cwd or Path.cwd()) / ".massgen"

    return base_dir / normalized_filename


# Load environment variables
load_dotenv()

# Custom theme for the CLI - using colors that work on both light and dark backgrounds
custom_theme = Theme(
    {
        "info": "#4A90E2",  # Medium blue - matches system status colors
        "warning": "#CC6600",  # Orange-brown - works on both light and dark
        "error": "#CC0000 bold",  # Deep red - strong contrast
        "success": "#00AA44 bold",  # Deep green - visible on both
        "prompt": "#6633CC bold",  # Purple - good on both backgrounds
    },
)

console = Console(theme=custom_theme)


class ConfigBuilder:
    """Interactive configuration builder for MassGen."""

    @staticmethod
    def get_quickstart_reasoning_profile(
        backend_type: str | None,
        model: str | None,
    ) -> dict[str, Any] | None:
        """Return quickstart reasoning options for supported models.

        Returns None when no quickstart reasoning selector should be shown.
        """
        normalized_backend = (backend_type or "").strip().lower()
        normalized_model = (model or "").strip().lower()

        def mark_recommended(label: str, effort: str, default_effort: str) -> str:
            if effort != default_effort:
                return label
            if "(" in label and label.endswith(")"):
                return f"{label[:-1]}, recommended)"
            return f"{label} (recommended)"

        def with_recommended(
            base_choices: list[tuple[str, str]],
            default_effort: str,
        ) -> list[tuple[str, str]]:
            return [(mark_recommended(label, effort, default_effort), effort) for label, effort in base_choices]

        if not normalized_model:
            return None

        # Claude Code supports effort controls for Opus/Sonnet 4.6.
        # "max" is only supported on Opus 4.6.
        if normalized_backend == "claude_code":
            supports_max = normalized_model.startswith("claude-opus-4-6")
            supports_standard = supports_max or normalized_model.startswith("claude-sonnet-4-6")
            if not supports_standard:
                return None

            default_effort = "high" if supports_max else "medium"
            choices = [
                ("Low (faster)", "low"),
                ("Medium", "medium"),
                ("High (deeper reasoning)", "high"),
            ]
            if supports_max:
                choices.append(("Max (deepest reasoning)", "max"))
            choices = with_recommended(choices, default_effort)

            return {
                "choices": choices,
                "default_effort": default_effort,
                "description": "This Claude Code model supports configurable reasoning effort.",
            }

        if "gpt-5" not in normalized_model:
            return None

        supports_xhigh = normalized_backend == "codex" or "codex" in normalized_model

        if normalized_backend not in {"openai", "azure_openai", "codex"}:
            return None

        default_effort = "low" if "nano" in normalized_model else "medium"
        if supports_xhigh and "gpt-5.3" in normalized_model:
            default_effort = "xhigh"
        if supports_xhigh:
            choices = with_recommended(
                [
                    ("Low (faster)", "low"),
                    ("Medium", "medium"),
                    ("High (deeper reasoning)", "high"),
                    ("XHigh (maximum depth)", "xhigh"),
                ],
                default_effort,
            )
            return {
                "choices": choices,
                "default_effort": default_effort,
                "description": "This GPT-5 Codex model supports extended reasoning.",
            }

        choices = with_recommended(
            [
                ("Low (faster)", "low"),
                ("Medium", "medium"),
                ("High (deeper reasoning)", "high"),
            ],
            default_effort,
        )
        return {
            "choices": choices,
            "default_effort": default_effort,
            "description": "This GPT-5 model supports extended reasoning.",
        }

    @property
    def PROVIDERS(self) -> dict[str, dict]:
        """Generate provider configurations from the capabilities registry (single source of truth).

        This dynamically builds the PROVIDERS dict from massgen/backend/capabilities.py,
        ensuring consistency between config builder, documentation, and backend implementations.
        """
        providers = {}

        for backend_type, caps in BACKEND_CAPABILITIES.items():
            # Build supports list, handling filesystem specially
            supports = list(caps.supported_capabilities)

            # Add "filesystem" to supports for ANY backend that supports it (native or MCP)
            if caps.filesystem_support in ["native", "mcp"]:
                supports = [s if s != "filesystem_native" else "filesystem" for s in supports]
                if "filesystem" not in supports:
                    supports.append("filesystem")

            providers[backend_type] = {
                "name": caps.provider_name,
                "type": caps.backend_type,
                "env_var": caps.env_var,
                "models": caps.models,
                "default_model": caps.default_model,
                "supports": supports,
            }

        return providers

    # Use case templates - all use cases support all agent types
    USE_CASES = {
        "custom": {
            "name": "Custom Configuration",
            "description": "Full flexibility - choose any agents, tools, and settings",
            "recommended_agents": 1,
            "recommended_tools": [],
            "agent_types": "all",
            "notes": "Choose any combination of agents and tools",
            "info": None,  # No auto-configuration - skip preset panel
        },
        "coding": {
            "name": "Filesystem + Code Execution",
            "description": "Generate, test, and modify code with file operations",
            "recommended_agents": 2,
            "recommended_tools": ["code_execution", "filesystem"],
            "agent_types": "all",
            "notes": "Claude Code recommended for best filesystem support",
            "info": """[bold cyan]Features auto-configured for this preset:[/bold cyan]

  [green]✓[/green] [bold]Filesystem Access[/bold]
    • File read/write operations in isolated workspace
    • Native filesystem (Claude Code) or MCP filesystem (other backends)

  [green]✓[/green] [bold]Code Execution[/bold]
    • OpenAI: Code Interpreter
    • Claude/Gemini: Native code execution
    • Isolated execution environment

[dim]Use this for:[/dim] Code generation, refactoring, testing, or any task requiring file operations.""",
        },
        "coding_docker": {
            "name": "Filesystem + Code Execution (Docker)",
            "description": "Secure isolated code execution in Docker containers (requires setup)",
            "recommended_agents": 2,
            "recommended_tools": ["code_execution", "filesystem"],
            "agent_types": "all",
            "notes": "⚠️ SETUP REQUIRED: Docker Engine 28+, Python docker library, and image build (see massgen/docker/README.md)",
            "info": """[bold cyan]Features auto-configured for this preset:[/bold cyan]

  [green]✓[/green] [bold]Filesystem Access[/bold]
    • File read/write operations

  [green]✓[/green] [bold]Code Execution[/bold]
    • OpenAI: Code Interpreter
    • Claude/Gemini: Native code execution

  [green]✓[/green] [bold]Docker Isolation[/bold]
    • Fully isolated container execution via MCP
    • Persistent package installations across turns
    • Network and resource controls

[yellow]⚠️  Requires Docker setup:[/yellow] Docker Engine 28.0.0+, docker Python library, and massgen-executor image
[dim]Use this for:[/dim] Secure code execution when you need full isolation and persistent dependencies.""",
        },
        "qa": {
            "name": "Simple Q&A",
            "description": "Basic question answering with multiple perspectives",
            "recommended_agents": 3,
            "recommended_tools": [],
            "agent_types": "all",
            "notes": "Multiple agents provide diverse perspectives and cross-verification",
            "info": None,  # No special features - skip preset panel
        },
        "research": {
            "name": "Research & Analysis",
            "description": "Multi-agent research with web search",
            "recommended_agents": 3,
            "recommended_tools": ["web_search"],
            "agent_types": "all",
            "notes": "Works best with web search enabled for current information",
            "info": """[bold cyan]Features auto-configured for this preset:[/bold cyan]

  [green]✓[/green] [bold]Web Search[/bold]
    • Real-time internet search for current information
    • Fact-checking and source verification
    • Available for: OpenAI, Claude, Gemini, Grok

  [green]✓[/green] [bold]Multi-Agent Collaboration[/bold]
    • 3 agents recommended for diverse perspectives
    • Cross-verification of facts and sources

[dim]Use this for:[/dim] Research queries, current events, fact-checking, comparative analysis.""",
        },
        "data_analysis": {
            "name": "Data Analysis",
            "description": "Analyze data with code execution and visualizations",
            "recommended_agents": 2,
            "recommended_tools": [
                "code_execution",
                "filesystem",
                "image_understanding",
            ],
            "agent_types": "all",
            "notes": "Code execution helps with data processing and visualization",
            "info": """[bold cyan]Features auto-configured for this preset:[/bold cyan]

  [green]✓[/green] [bold]Filesystem Access[/bold]
    • Read/write data files (CSV, JSON, etc.)
    • Save visualizations and reports

  [green]✓[/green] [bold]Code Execution[/bold]
    • Data processing and transformation
    • Statistical analysis
    • Visualization generation (matplotlib, seaborn, etc.)

  [green]✓[/green] [bold]Image Understanding[/bold]
    • Analyze charts, graphs, and visualizations
    • Extract data from images and screenshots
    • Available for: OpenAI, Claude Code, Gemini, Azure OpenAI

[dim]Use this for:[/dim] Data analysis, chart interpretation, statistical processing, visualization.""",
        },
        "multimodal": {
            "name": "Multimodal Analysis",
            "description": "Analyze images, audio, video, and documents",
            "recommended_agents": 2,
            "recommended_tools": [
                "image_understanding",
                "audio_understanding",
                "video_understanding",
            ],
            "agent_types": "all",
            "notes": "Combines custom tools + built-in backend capabilities",
            "info": """[bold cyan]Features auto-configured for this preset:[/bold cyan]

  [green]✓[/green] [bold]Custom Multimodal Tools (New v0.1.3+)[/bold]
    • understand_image - Analyze workspace images with gpt-4.1
    • understand_audio - Transcribe and analyze audio files
    • understand_video - Extract frames and analyze videos
    • understand_file - Process documents (PDF, DOCX, XLSX, PPTX)
    • Works with any backend, processes workspace files

  [green]✓[/green] [bold]Built-in Backend Capabilities[/bold] [dim](passive)[/dim]
    • Image understanding via upload_files (OpenAI, Claude, Gemini, Azure)
    • Audio understanding via upload_files (Claude, ChatCompletion)
    • Video understanding via upload_files (Claude, ChatCompletion, OpenAI)
    • Image/audio/video generation (where supported)

[dim]Use this for:[/dim] Image analysis, audio transcription, video analysis, document processing.""",
        },
    }

    def __init__(self, default_mode: bool = False) -> None:
        """Initialize the configuration builder with default config.

        Args:
            default_mode: If True, save config to ~/.config/massgen/config.yaml by default
        """
        self.config = {
            "agents": [],
            "ui": {
                "display_type": "textual_terminal",
                "logging_enabled": True,
            },
        }
        self.orchestrator_config = {}
        self.default_mode = default_mode

    def select_model_smart(
        self,
        backend_type: str,
        models: list[str],
        current_model: str | None = None,
        prompt: str = "Select model:",
    ) -> str | None:
        """Smart model selection with autocomplete for providers with many models.

        For providers with custom/many models (OpenRouter, Nebius, POE), offers text input with fuzzy matching.
        For providers with specific model lists, uses traditional select UI.

        Args:
            backend_type: The backend type (e.g., "openrouter", "openai")
            models: List of available models from capabilities
            current_model: Currently selected model
            prompt: Prompt text to display

        Returns:
            Selected model name, or None if cancelled
        """
        # Get expanded model list for fuzzy matching if provider has curated common models
        try:
            fuzzy_match_models = get_all_models_for_provider(backend_type)
        except Exception:
            # If API fails, fall back to models from capabilities
            fuzzy_match_models = models

        # All chatcompletion providers should use autocomplete search
        chatcompletion_providers = [
            "openrouter",
            "poe",
            "groq",
            "cerebras",
            "together",
            "nebius",
            "fireworks",
            "moonshot",
            "nvidia_nim",
            "qwen",
        ]

        # Providers that should use text input/autocomplete instead of select
        use_text_input = (
            "custom" in models  # Provider with custom models
            or len(models) > 20  # Too many models for select UI
            or backend_type in chatcompletion_providers  # All chatcompletion providers use autocomplete
            or len(fuzzy_match_models) > 20  # API returned many models
        )

        if use_text_input:
            console.print(
                "\n[dim]Type to search models (e.g., 'gpt-5.2', 'gpt-5-mini', 'gpt-5-nano')[/dim]",
            )
            console.print(
                f"[dim]Searching through {len(fuzzy_match_models)} models...[/dim]",
            )
            if current_model and current_model != "custom":
                console.print(f"[dim]Current: {current_model}[/dim]")
            console.print()

            try:
                model_input = questionary.autocomplete(
                    prompt,
                    choices=fuzzy_match_models,
                    default="" if current_model == "custom" else (current_model or ""),
                    meta_information={},  # Can add model descriptions here later
                    match_middle=True,  # Match anywhere in string
                    ignore_case=True,  # Case insensitive
                    style=questionary.Style(
                        [
                            ("question", "fg:cyan bold"),
                            ("answer", "fg:cyan"),
                            ("pointer", "fg:cyan bold"),
                        ],
                    ),
                    validate=lambda text: len(text.strip()) > 0 or "Model name cannot be empty",
                ).ask()

                if model_input is None:  # User cancelled
                    return None

                return model_input.strip()

            except ImportError:
                # Fallback to simple text input if autocomplete not available
                console.print(
                    "[warning]⚠️  Autocomplete not available, using text input[/warning]",
                )
                model_input = questionary.text(
                    prompt,
                    default="" if current_model == "custom" else (current_model or ""),
                    style=questionary.Style(
                        [
                            ("question", "fg:cyan bold"),
                            ("answer", "fg:cyan"),
                        ],
                    ),
                    validate=lambda text: len(text.strip()) > 0 or "Model name cannot be empty",
                ).ask()

                if model_input is None:
                    return None

                return model_input.strip()

        else:
            # Traditional select UI for providers with specific models
            model_choices = [
                questionary.Choice(
                    f"{model}" + (" (current)" if model == current_model else ""),
                    value=model,
                )
                for model in models
            ]

            selected_model = questionary.select(
                prompt,
                choices=model_choices,
                default=current_model,
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan bold"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            return selected_model

    def show_banner(self) -> None:
        """Display welcome banner using Rich Panel."""
        # Clear screen
        console.clear()

        # ASCII art for multi-agent coordination
        ascii_art = """[bold cyan]
     ███╗   ███╗ █████╗ ███████╗███████╗ ██████╗ ███████╗███╗   ██╗
     ████╗ ████║██╔══██╗██╔════╝██╔════╝██╔════╝ ██╔════╝████╗  ██║
     ██╔████╔██║███████║███████╗███████╗██║  ███╗█████╗  ██╔██╗ ██║
     ██║╚██╔╝██║██╔══██║╚════██║╚════██║██║   ██║██╔══╝  ██║╚██╗██║
     ██║ ╚═╝ ██║██║  ██║███████║███████║╚██████╔╝███████╗██║ ╚████║
     ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝[/bold cyan]

     [dim]     🤖 🤖 🤖  →  💬 collaborate  →  🎯 winner  →  📢 final[/dim]
"""

        banner_content = f"""{ascii_art}
[bold bright_cyan]Interactive Configuration Builder[/bold bright_cyan]
[dim]Create custom multi-agent configurations in minutes![/dim]"""

        banner_panel = Panel(
            banner_content,
            border_style="bold cyan",
            padding=(0, 2),
            width=80,
        )

        console.print(banner_panel)
        console.print()

    def _calculate_visible_length(self, text: str) -> int:
        """Calculate visible length of text, excluding Rich markup tags."""
        import re

        # Remove all Rich markup tags like [bold], [/bold], [dim cyan], etc.
        visible_text = re.sub(r"\[/?[^\]]+\]", "", text)
        return len(visible_text)

    def _pad_with_markup(self, text: str, target_width: int) -> str:
        """Pad text to target width, accounting for Rich markup."""
        visible_len = self._calculate_visible_length(text)
        padding_needed = target_width - visible_len
        return text + (" " * padding_needed if padding_needed > 0 else "")

    def _safe_prompt(self, prompt_func, error_msg: str = "Selection cancelled"):
        """Wrapper for questionary prompts with graceful exit handling.

        Args:
            prompt_func: The questionary prompt function to call
            error_msg: Error message to show if cancelled

        Returns:
            The result from the prompt, or raises KeyboardInterrupt if cancelled

        Raises:
            KeyboardInterrupt: If user cancels (Ctrl+C or returns None)
        """
        try:
            result = prompt_func()
            if result is None:
                # User pressed Ctrl+C or Esc - treat as cancellation
                raise KeyboardInterrupt
            return result
        except (KeyboardInterrupt, EOFError):
            # Re-raise to be handled by caller
            raise

    def detect_api_keys(self) -> dict[str, bool]:
        """Detect available API keys from environment with error handling."""
        api_keys = {}
        try:
            for provider_id, provider_info in self.PROVIDERS.items():
                try:
                    # Claude Code and Codex are always available (work with CLI login/OAuth or API key)
                    if provider_id in ("claude_code", "codex"):
                        api_keys[provider_id] = True
                        continue

                    env_var = provider_info.get("env_var")
                    if env_var:
                        api_keys[provider_id] = bool(os.getenv(env_var))
                    else:
                        api_keys[provider_id] = True  # Local models don't need keys
                except Exception as e:
                    console.print(
                        f"[warning]⚠️  Could not check {provider_id}: {e}[/warning]",
                    )
                    api_keys[provider_id] = False
            return api_keys
        except Exception as e:
            console.print(f"[error]❌ Error detecting API keys: {e}[/error]")
            # Return empty dict to allow continue with manual input
            return {provider_id: False for provider_id in self.PROVIDERS.keys()}

    def interactive_api_key_setup(self) -> dict[str, bool]:
        """Interactive API key setup wizard.

        Prompts user to enter API keys for providers and saves them to .env file.
        Follows CLI tool patterns (AWS CLI, Stripe CLI) for API key management.

        Returns:
            Updated api_keys dict after setup
        """
        try:
            console.print("\n[bold cyan]API Key Setup[/bold cyan]\n")
            console.print("[dim]Configure API keys for cloud AI providers.[/dim]")
            console.print(
                "[dim](Alternatively, you can use local models like vLLM/Ollama - no keys needed)[/dim]\n",
            )

            # First, detect and show currently configured keys
            current_api_keys = self.detect_api_keys()

            # Complete list of all API key providers (includes main backends + chatcompletion variants)
            # This is the complete set from cli.py create_backend()
            all_providers = [
                # Main backends (high priority)
                ("openai", "OpenAI", "OPENAI_API_KEY"),
                ("anthropic", "Anthropic (Claude)", "ANTHROPIC_API_KEY"),
                ("claude_code", "Claude Code (optional)", "CLAUDE_CODE_API_KEY"),
                ("codex", "OpenAI Codex (optional)", "OPENAI_API_KEY"),
                ("gemini", "Google Gemini", "GOOGLE_API_KEY"),
                ("grok", "xAI (Grok)", "XAI_API_KEY"),
                # Azure
                ("azure_openai", "Azure OpenAI", "AZURE_OPENAI_API_KEY"),
                # ChatCompletion providers
                ("cerebras", "Cerebras AI", "CEREBRAS_API_KEY"),
                ("together", "Together AI", "TOGETHER_API_KEY"),
                ("fireworks", "Fireworks AI", "FIREWORKS_API_KEY"),
                ("groq", "Groq", "GROQ_API_KEY"),
                ("nebius", "Nebius AI Studio", "NEBIUS_API_KEY"),
                ("openrouter", "OpenRouter", "OPENROUTER_API_KEY"),
                ("zai", "ZAI (Zhipu.ai)", "ZAI_API_KEY"),
                ("moonshot", "Kimi/Moonshot AI", "MOONSHOT_API_KEY"),
                ("nvidia_nim", "Nvidia NIM", "NGC_API_KEY"),
                ("poe", "POE", "POE_API_KEY"),
                ("qwen", "Qwen (Alibaba)", "QWEN_API_KEY"),
            ]

            # Show configured keys summary FIRST
            configured_providers = [(pid, name, env_var) for pid, name, env_var in all_providers if current_api_keys.get(pid, False)]
            unconfigured_providers = [(pid, name, env_var) for pid, name, env_var in all_providers if not current_api_keys.get(pid, False)]

            if configured_providers:
                console.print(
                    f"[green]✓ {len(configured_providers)} API Key(s) Configured:[/green]",
                )
                for _, name, _ in configured_providers:
                    console.print(f"  [green]✓[/green] {name}")
                console.print()

            if not unconfigured_providers:
                console.print("[green]All providers are configured![/green]")
                return current_api_keys

            # Sort unconfigured providers: popular first, then alphabetically
            popular_provider_ids = ["openai", "anthropic", "gemini", "grok"]

            def sort_key(provider):
                pid = provider[0]
                if pid in popular_provider_ids:
                    return (0, popular_provider_ids.index(pid))
                return (1, provider[1])  # sort by name

            unconfigured_providers.sort(key=sort_key)

            # Collect API keys from user
            collected_keys = {}

            # Create checkbox choices for unconfigured providers only
            provider_choices = []
            for provider_id, name, env_var in unconfigured_providers:
                provider_choices.append(
                    questionary.Choice(
                        f"{name:<25} [{env_var}]",
                        value=(provider_id, name, env_var),
                        checked=False,
                    ),
                )

            console.print(
                "[dim]Select which providers you want to configure (Space to toggle, Enter to confirm):[/dim]",
            )
            console.print(
                "[dim]Or skip all to use local models (vLLM, Ollama, etc.)[/dim]\n",
            )

            selected_providers = questionary.checkbox(
                "Select cloud providers to configure:",
                choices=provider_choices,
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if selected_providers is None:
                raise KeyboardInterrupt

            if not selected_providers:
                console.print("\n[yellow]⚠️  No providers selected[/yellow]")
                console.print(
                    "[dim]Skipping API key setup. You can use local models (vLLM, Ollama) without API keys.[/dim]\n",
                )
                return {}

            # Now prompt for API keys only for selected providers
            console.print(
                f"\n[cyan]Configuring {len(selected_providers)} provider(s)[/cyan]\n",
            )

            for provider_id, name, env_var in selected_providers:
                # Prompt for API key (with password-style input)
                console.print(f"[bold cyan]{name}[/bold cyan]")
                console.print(f"[dim]Environment variable: {env_var}[/dim]")

                # Add context for Claude Code
                if provider_id == "claude_code":
                    console.print(
                        "[dim]Note: Only needed if you want a separate key for claude_code backend.[/dim]",
                    )
                    console.print(
                        "[dim]      Leave empty to use ANTHROPIC_API_KEY or Claude subscription.[/dim]",
                    )

                api_key = Prompt.ask(
                    f"Enter your {name} API key",
                    password=True,  # Hide input
                )

                if api_key is None:
                    raise KeyboardInterrupt

                if api_key and api_key.strip():
                    collected_keys[env_var] = api_key.strip()
                    console.print(f"✅ {name} API key saved")
                else:
                    console.print(f"[yellow]⚠️  Skipped {name} (empty input)[/yellow]")
                console.print()

            if not collected_keys:
                console.print("[error]❌ No API keys were configured.[/error]")
                console.print(
                    "[info]At least one API key is required to use MassGen.[/info]",
                )
                return {}

            # Ask where to save
            console.print("\n[bold cyan]Where to Save API Keys[/bold cyan]\n")
            console.print("[dim]Choose where to save your API keys:[/dim]\n")
            console.print("  [1] ~/.massgen/.env (recommended - available globally)")
            console.print("  [2] ./.env (current directory only)")
            console.print()

            save_location = Prompt.ask(
                "[prompt]Choose location[/prompt]",
                choices=["1", "2"],
                default="1",
            )

            if save_location is None:
                raise KeyboardInterrupt

            # Determine target path
            if save_location == "1":
                env_dir = Path.home() / ".massgen"
                env_dir.mkdir(parents=True, exist_ok=True)
                env_path = env_dir / ".env"
            else:
                env_path = Path(".env")

            # Check if .env already exists
            existing_content = {}
            if env_path.exists():
                console.print(f"\n[yellow]⚠️  {env_path} already exists[/yellow]")

                # Parse existing .env file
                try:
                    with open(env_path) as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key, value = line.split("=", 1)
                                existing_content[key.strip()] = value.strip()
                except Exception as e:
                    console.print(
                        f"[warning]⚠️  Could not read existing .env: {e}[/warning]",
                    )

                merge = Confirm.ask(
                    "Merge with existing keys (recommended)?",
                    default=True,
                )
                if merge is None:
                    raise KeyboardInterrupt

                if merge:
                    # Merge: existing keys + new keys (new keys overwrite)
                    existing_content.update(collected_keys)
                    collected_keys = existing_content
                else:
                    # User chose to overwrite completely
                    pass

            # Write .env file
            try:
                with open(env_path, "w") as f:
                    f.write("# MassGen API Keys\n")
                    f.write("# Generated by MassGen Interactive Setup\n\n")

                    for env_var, api_key in sorted(collected_keys.items()):
                        f.write(f"{env_var}={api_key}\n")

                console.print(
                    f"\n✅ [success]API keys saved to: {env_path.absolute()}[/success]",
                )

                # Security reminder
                if env_path == Path(".env"):
                    console.print("\n[yellow]⚠️  Security reminder:[/yellow]")
                    console.print(
                        "[yellow]   Add .env to your .gitignore to avoid committing API keys![/yellow]",
                    )

            except Exception as e:
                console.print(f"\n[error]❌ Failed to save .env file: {e}[/error]")
                return {}

            # Reload environment variables
            console.print("\n[dim]Reloading environment variables...[/dim]")
            load_dotenv(env_path, override=True)

            # Re-detect API keys
            console.print("[dim]Verifying API keys...[/dim]\n")
            updated_api_keys = self.detect_api_keys()

            # Show what was detected
            available_count = sum(1 for has_key in updated_api_keys.values() if has_key)
            console.print(
                f"[success]✅ {available_count} provider(s) available[/success]\n",
            )

            return updated_api_keys

        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[yellow]API key setup cancelled[/yellow]\n")
            return {}
        except Exception as e:
            console.print(f"\n[error]❌ Error during API key setup: {e}[/error]")
            return {}

    def show_available_providers(
        self,
        api_keys: dict[str, bool],
    ) -> None:
        """Display providers in a clean Rich table."""
        try:
            # Create Rich table
            table = Table(
                title="[bold cyan]Available Providers[/bold cyan]",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
                title_style="bold cyan",
                expand=False,  # Don't expand to full width
                padding=(0, 1),  # Padding around cells
            )

            # Add columns
            table.add_column("", justify="center", width=3, no_wrap=True)  # Status icon
            table.add_column("Provider", style="bold", min_width=20)
            table.add_column("Models", style="dim", min_width=25)
            table.add_column("Capabilities", style="dim cyan", min_width=20)

            # Exclude generic backends from display (superseded by specific providers)
            excluded_generic_backends = ["chatcompletion", "inference"]

            # Add rows for each provider
            for provider_id, provider_info in self.PROVIDERS.items():
                # Skip generic backends
                if provider_id in excluded_generic_backends:
                    continue

                try:
                    has_key = api_keys.get(provider_id, False)
                    status = "✅" if has_key else "❌"
                    name = provider_info.get("name", "Unknown")

                    # Models (first 2)
                    models = provider_info.get("models", [])
                    models_display = ", ".join(models[:2])
                    if len(models) > 2:
                        models_display += f" +{len(models) - 2}"

                    # Capabilities (abbreviated, first 3)
                    caps = provider_info.get("supports", [])
                    cap_abbrev = {
                        "web_search": "web",
                        "code_execution": "code",
                        "filesystem": "files",
                        "image_understanding": "img",
                        "reasoning": "reason",
                        "mcp": "mcp",
                        "audio_understanding": "audio",
                        "video_understanding": "video",
                    }
                    caps_display = ", ".join(
                        [cap_abbrev.get(c, c[:4]) for c in caps[:3]],
                    )
                    if len(caps) > 3:
                        caps_display += f" +{len(caps) - 3}"

                    # Add row
                    # Special handling for Claude Code - always available but show hint if no API key
                    if provider_id == "claude_code":
                        env_var = provider_info.get("env_var", "")
                        api_key_set = bool(os.getenv(env_var)) if env_var else False
                        if api_key_set:
                            table.add_row(
                                "✅",
                                name,
                                models_display,
                                caps_display or "basic",
                            )
                        else:
                            name_with_hint = f"{name}\n[dim cyan]⚠️ Requires `claude login` (no API key found)[/dim cyan]"
                            table.add_row(
                                "✅",
                                name_with_hint,
                                models_display,
                                caps_display or "basic",
                            )
                    elif has_key:
                        table.add_row(
                            status,
                            name,
                            models_display,
                            caps_display or "basic",
                        )
                    else:
                        # For missing keys, add env var hint
                        env_var = provider_info.get("env_var", "")
                        name_with_hint = f"{name}\n[yellow]Need: {env_var}[/yellow]"
                        table.add_row(
                            status,
                            name_with_hint,
                            models_display,
                            caps_display or "basic",
                        )

                except Exception as e:
                    console.print(
                        f"[warning]⚠️ Could not display {provider_id}: {e}[/warning]",
                    )

            # Display the table
            console.print(table)
            console.print(
                "\n💡 [dim]Tip: Set API keys in ~/.config/massgen/.env or ~/.massgen/.env[/dim]\n",
            )

        except Exception as e:
            console.print(f"[error]❌ Error displaying providers: {e}[/error]")
            console.print("[info]Continuing with setup...[/info]\n")

    def select_use_case(self) -> str:
        """Let user select a use case template with error handling."""
        try:
            # Step header
            step_panel = Panel(
                "[bold cyan]Step 1 of 4: Select Your Use Case[/bold cyan]\n\n[italic dim]All agent types are supported for every use case[/italic dim]",
                border_style="cyan",
                padding=(0, 2),
                width=80,
            )
            console.print(step_panel)
            console.print()

            # Build choices for questionary - organized with tool hints
            choices = []

            # Add spacing before first option (using spaces to avoid line)
            choices.append(questionary.Separator(" "))

            # First option: Browse existing configs (most common for new users)
            choices.append(
                questionary.Choice(
                    title="📦  Browse ready-to-use configs / examples",
                    value="__browse_existing__",
                ),
            )
            choices.append(questionary.Separator(" "))
            choices.append(questionary.Separator("┄┄ or build from template ┄┄"))
            choices.append(questionary.Separator(" "))

            # Define display with brief tool descriptions
            display_info = [
                ("custom", "⚙️", "Custom Configuration", "Choose your own tools"),
                ("qa", "💬", "Simple Q&A", "Basic chat (no special tools)"),
                ("research", "🔍", "Research & Analysis", "Web search enabled"),
                ("coding", "💻", "Code & Files", "File ops + code execution"),
                (
                    "coding_docker",
                    "🐳",
                    "Code & Files (Docker)",
                    "File ops + isolated Docker execution",
                ),
                (
                    "data_analysis",
                    "📊",
                    "Data Analysis",
                    "Files + code + image analysis",
                ),
                (
                    "multimodal",
                    "🎨",
                    "Multimodal Analysis",
                    "Images, audio, video understanding",
                ),
            ]

            for use_case_id, emoji, name, tools_hint in display_info:
                try:
                    use_case_info = self.USE_CASES.get(use_case_id)
                    if not use_case_info:
                        continue

                    # Show name with tools hint
                    display = f"{emoji}  {name:<30} [{tools_hint}]"

                    choices.append(
                        questionary.Choice(
                            title=display,
                            value=use_case_id,
                        ),
                    )

                except Exception as e:
                    console.print(
                        f"[warning]⚠️  Could not display use case: {e}[/warning]",
                    )

            # Add helpful context before the prompt
            console.print(
                "[dim]Browse ready-to-use configs, or pick a template to build your own.[/dim]\n",
            )

            use_case_id = questionary.select(
                "Select your use case:",
                choices=choices,
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan bold"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if use_case_id is None:
                raise KeyboardInterrupt  # User cancelled, exit immediately

            # Handle special value for browsing existing configs
            if use_case_id == "__browse_existing__":
                return "__browse_existing__"

            # Show selection with description
            selected_info = self.USE_CASES[use_case_id]
            console.print(
                f"\n✅ Selected: [green]{selected_info.get('name', use_case_id)}[/green]",
            )
            console.print(f"   [dim]{selected_info.get('description', '')}[/dim]")
            console.print(
                f"   [dim cyan]→ Recommended: {selected_info.get('recommended_agents', 1)} agent(s)[/dim cyan]\n",
            )

            # Show preset information (only if there are special features)
            use_case_details = self.USE_CASES[use_case_id]
            if use_case_details.get("info"):
                preset_panel = Panel(
                    use_case_details["info"],
                    border_style="cyan",
                    title="[bold]Preset Configuration[/bold]",
                    width=80,
                    padding=(1, 2),
                )
                console.print(preset_panel)
                console.print()

            return use_case_id
        except (KeyboardInterrupt, EOFError):
            raise  # Re-raise to be handled by run()
        except Exception as e:
            console.print(f"[error]❌ Error selecting use case: {e}[/error]")
            console.print("[info]Defaulting to 'qa' use case[/info]\n")
            return "qa"  # Safe default

    def add_custom_mcp_server(self) -> dict | None:
        """Interactive flow to configure a custom MCP server.

        Returns:
            MCP server configuration dict, or None if cancelled
        """
        try:
            console.print("\n[bold cyan]Configure Custom MCP Server[/bold cyan]\n")

            # Name
            name = questionary.text(
                "Server name (identifier):",
                validate=lambda x: len(x) > 0,
            ).ask()

            if not name:
                return None

            # Type
            server_type = questionary.select(
                "Server type:",
                choices=[
                    questionary.Choice("stdio (standard input/output)", value="stdio"),
                    questionary.Choice("sse (server-sent events)", value="sse"),
                    questionary.Choice("Custom type", value="custom"),
                ],
                default="stdio",
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan bold"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if server_type == "custom":
                server_type = questionary.text("Enter custom type:").ask()

            if not server_type:
                server_type = "stdio"

            # Command
            command = questionary.text(
                "Command:",
                default="npx",
            ).ask()

            if not command:
                command = "npx"

            # Args
            args_str = questionary.text(
                "Arguments (space-separated, or empty for none):",
                default="",
            ).ask()

            args = args_str.split() if args_str else []

            # Environment variables
            env_vars = {}
            if questionary.confirm("Add environment variables?", default=False).ask():
                console.print(
                    "\n[dim]Tip: Use ${VAR_NAME} to reference from .env file[/dim]\n",
                )
                while True:
                    var_name = questionary.text(
                        "Environment variable name (or press Enter to finish):",
                    ).ask()

                    if not var_name:
                        break

                    var_value = questionary.text(
                        f"Value for {var_name}:",
                        default=f"${{{var_name}}}",
                    ).ask()

                    if var_value:
                        env_vars[var_name] = var_value

            # Build server config
            mcp_server = {
                "name": name,
                "type": server_type,
                "command": command,
                "args": args,
            }

            if env_vars:
                mcp_server["env"] = env_vars

            console.print(f"\n✅ Custom MCP server configured: {name}\n")
            return mcp_server

        except (KeyboardInterrupt, EOFError):
            console.print("\n[info]Cancelled custom MCP configuration[/info]")
            return None
        except Exception as e:
            console.print(f"[error]❌ Error configuring custom MCP: {e}[/error]")
            return None

    def batch_create_agents(
        self,
        count: int,
        provider_id: str,
        start_index: int = 0,
    ) -> list[dict]:
        """Create multiple agents with the same provider.

        Args:
            count: Number of agents to create
            provider_id: Provider ID (e.g., 'openai', 'claude')
            start_index: Starting index for agent naming (default: 0)

        Returns:
            List of agent configurations with default models
        """
        agents = []
        provider_info = self.PROVIDERS.get(provider_id, {})

        # Generate agent IDs like agent_a, agent_b, agent_c...
        for i in range(count):
            # Convert index to letter (0->a, 1->b, 2->c, etc.)
            agent_letter = chr(ord("a") + start_index + i)

            agent = {
                "id": f"agent_{agent_letter}",
                "backend": {
                    "type": provider_info.get("type", provider_id),
                    "model": provider_info.get(
                        "default_model",
                        provider_info.get("models", ["default"])[0],
                    ),
                },
            }

            # Add workspace for Claude Code (unique suffix added at runtime in cli.py)
            if provider_info.get("type") == "claude_code":
                agent["backend"]["cwd"] = "workspace"

            agents.append(agent)

        return agents

    def clone_agent(
        self,
        source_agent: dict,
        new_id: str,
        target_backend_type: str = None,
    ) -> dict:
        """Clone an agent's configuration with a new ID, optionally preserving target backend.

        Args:
            source_agent: Agent to clone
            new_id: New agent ID
            target_backend_type: If provided, preserve this backend type instead of copying source's

        Returns:
            Cloned agent with updated ID and workspace (if applicable)
        """
        import copy

        cloned = copy.deepcopy(source_agent)
        cloned["id"] = new_id

        # If target backend type is different, preserve it and update model
        if target_backend_type and target_backend_type != source_agent.get(
            "backend",
            {},
        ).get("type"):
            # Find target provider info to get default model
            target_provider_info = None
            for pid, pinfo in self.PROVIDERS.items():
                if pinfo.get("type") == target_backend_type:
                    target_provider_info = pinfo
                    break

            if target_provider_info:
                # Preserve tool enablement flags (provider-agnostic)
                preserved_settings = {}
                skipped_settings = []
                source_backend = source_agent.get("backend", {})
                source_backend_type = source_backend.get("type")

                # Copy filesystem settings (provider-agnostic)
                if "cwd" in source_backend:
                    preserved_settings["cwd"] = source_backend["cwd"]

                # Copy MCP servers (provider-agnostic, but check if target supports MCP)
                if "mcp_servers" in source_backend:
                    # Check if target provider supports MCP
                    target_supports_mcp = "mcp" in target_provider_info.get(
                        "supports",
                        [],
                    )
                    if target_supports_mcp:
                        preserved_settings["mcp_servers"] = copy.deepcopy(
                            source_backend["mcp_servers"],
                        )
                    else:
                        skipped_settings.append(
                            "mcp_servers (not supported by target provider)",
                        )

                # Copy tool flags if they exist and are supported by target
                target_caps = get_capabilities(target_backend_type)

                for key in [
                    "enable_web_search",
                    "enable_code_execution",
                    "enable_code_interpreter",
                    "enable_mcp_command_line",
                    "command_line_execution_mode",
                ]:
                    if key in source_backend:
                        # Check if target supports this specific tool
                        if key == "enable_web_search":
                            if has_capability(target_backend_type, "web_search"):
                                preserved_settings[key] = source_backend[key]
                            else:
                                skipped_settings.append(
                                    f"{key} (not supported by {target_backend_type})",
                                )
                        elif key == "enable_code_interpreter":
                            # code_interpreter is OpenAI/Azure-specific
                            if target_caps and "code_interpreter" in target_caps.builtin_tools:
                                preserved_settings[key] = source_backend[key]
                            else:
                                skipped_settings.append(
                                    f"{key} (not supported by {target_backend_type})",
                                )
                        elif key == "enable_code_execution":
                            # code_execution is Claude/Gemini-specific
                            if target_caps and "code_execution" in target_caps.builtin_tools:
                                preserved_settings[key] = source_backend[key]
                            else:
                                skipped_settings.append(
                                    f"{key} (not supported by {target_backend_type})",
                                )
                        else:
                            # MCP command line and execution mode are universal
                            preserved_settings[key] = source_backend[key]

                # Copy reasoning/text settings if target is OpenAI
                if target_backend_type == "openai":
                    for key in ["text", "reasoning"]:
                        if key in source_backend:
                            preserved_settings[key] = copy.deepcopy(source_backend[key])
                elif source_backend_type == "openai":
                    # Source was OpenAI but target is not - these settings can't be copied
                    for key in ["text", "reasoning"]:
                        if key in source_backend:
                            skipped_settings.append(f"{key} (OpenAI-specific)")

                # Replace backend with target provider's default model + preserved settings
                cloned["backend"] = {
                    "type": target_backend_type,
                    "model": target_provider_info.get(
                        "default_model",
                        target_provider_info.get("models", ["default"])[0],
                    ),
                    **preserved_settings,
                }

                # Store skipped settings for later warning
                cloned["_skipped_settings"] = skipped_settings

        # Update workspace for filesystem-enabled agents (unique suffix added at runtime in cli.py)
        if "cwd" in cloned.get("backend", {}):
            cloned["backend"]["cwd"] = "workspace"

        return cloned

    def modify_cloned_agent(self, agent: dict, agent_num: int) -> dict:
        """Allow selective modification of a cloned agent.

        Args:
            agent: Cloned agent to modify
            agent_num: Agent number (1-indexed)

        Returns:
            Modified agent configuration
        """
        try:
            console.print(
                f"\n[bold cyan]Selective Modification: {agent['id']}[/bold cyan]",
            )
            console.print(
                "[dim]Choose which settings to modify (or press Enter to keep all)[/dim]\n",
            )

            backend_type = agent.get("backend", {}).get("type")

            # Find provider info
            provider_info = None
            for pid, pinfo in self.PROVIDERS.items():
                if pinfo.get("type") == backend_type:
                    provider_info = pinfo
                    break

            if not provider_info:
                console.print("[warning]⚠️  Could not find provider info[/warning]")
                return agent

            # Ask what to modify
            modify_choices = questionary.checkbox(
                "What would you like to modify? (Space to select, Enter to confirm)",
                choices=[
                    questionary.Choice("Model", value="model"),
                    questionary.Choice(
                        "Tools (web search, code execution)",
                        value="tools",
                    ),
                    questionary.Choice("Filesystem settings", value="filesystem"),
                    questionary.Choice("MCP servers", value="mcp"),
                ],
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if not modify_choices:
                console.print("✅ Keeping all cloned settings")
                return agent

            # Modify selected aspects
            if "model" in modify_choices:
                models = provider_info.get("models", [])
                if models:
                    current_model = agent["backend"].get("model")
                    selected_model = self.select_model_smart(
                        backend_type=backend_type,
                        models=models,
                        current_model=current_model,
                        prompt=f"Select model for {agent['id']}:",
                    )

                    if selected_model:
                        agent["backend"]["model"] = selected_model
                        console.print(f"✅ Model changed to: {selected_model}")

            if "tools" in modify_choices:
                supports = provider_info.get("supports", [])
                builtin_tools = [s for s in supports if s in ["web_search", "code_execution", "bash"]]

                if builtin_tools:
                    # Show current tools
                    current_tools = []
                    if agent["backend"].get("enable_web_search"):
                        current_tools.append("web_search")
                    if agent["backend"].get("enable_code_interpreter") or agent["backend"].get("enable_code_execution"):
                        current_tools.append("code_execution")

                    tool_choices = []
                    if "web_search" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Web Search",
                                value="web_search",
                                checked="web_search" in current_tools,
                            ),
                        )
                    if "code_execution" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Code Execution",
                                value="code_execution",
                                checked="code_execution" in current_tools,
                            ),
                        )
                    if "bash" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Bash/Shell",
                                value="bash",
                                checked="bash" in current_tools,
                            ),
                        )

                    if tool_choices:
                        selected_tools = questionary.checkbox(
                            "Enable built-in tools:",
                            choices=tool_choices,
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()

                        # Clear existing tools
                        agent["backend"].pop("enable_web_search", None)
                        agent["backend"].pop("enable_code_interpreter", None)
                        agent["backend"].pop("enable_code_execution", None)

                        # Apply selected tools
                        if selected_tools:
                            if "web_search" in selected_tools:
                                if backend_type in [
                                    "openai",
                                    "claude",
                                    "claude_code",
                                    "gemini",
                                    "grok",
                                    "azure_openai",
                                    "openrouter",  # Supports web search via plugins array
                                ]:
                                    agent["backend"]["enable_web_search"] = True

                            if "code_execution" in selected_tools:
                                if backend_type == "openai" or backend_type == "azure_openai":
                                    agent["backend"]["enable_code_interpreter"] = True
                                elif backend_type in ["claude", "gemini"]:
                                    agent["backend"]["enable_code_execution"] = True

                        console.print("✅ Tools updated")

            if "filesystem" in modify_choices and "filesystem" in provider_info.get(
                "supports",
                [],
            ):
                enable_fs = questionary.confirm(
                    "Enable filesystem access?",
                    default=bool(agent["backend"].get("cwd")),
                ).ask()

                if enable_fs:
                    if backend_type == "claude_code":
                        current_cwd = agent["backend"].get(
                            "cwd",
                            "workspace",
                        )
                        custom_cwd = questionary.text(
                            "Workspace directory:",
                            default=current_cwd,
                        ).ask()
                        if custom_cwd:
                            agent["backend"]["cwd"] = custom_cwd
                    else:
                        agent["backend"]["cwd"] = "workspace"
                    console.print(f"✅ Filesystem enabled: {agent['backend']['cwd']}")
                else:
                    agent["backend"].pop("cwd", None)
                    console.print("✅ Filesystem disabled")

            if "mcp" in modify_choices and "mcp" in provider_info.get("supports", []):
                if questionary.confirm("Modify MCP servers?", default=False).ask():
                    # Show current MCP servers
                    current_mcps = agent["backend"].get("mcp_servers", [])
                    if current_mcps:
                        console.print(
                            f"\n[dim]Current MCP servers: {len(current_mcps)}[/dim]",
                        )
                        for mcp in current_mcps:
                            console.print(f"  • {mcp.get('name', 'unnamed')}")

                    if questionary.confirm(
                        "Replace with new MCP servers?",
                        default=False,
                    ).ask():
                        mcp_servers = []
                        while True:
                            custom_server = self.add_custom_mcp_server()
                            if custom_server:
                                mcp_servers.append(custom_server)
                                if not questionary.confirm(
                                    "Add another MCP server?",
                                    default=False,
                                ).ask():
                                    break
                            else:
                                break

                        if mcp_servers:
                            agent["backend"]["mcp_servers"] = mcp_servers
                            console.print(
                                f"✅ MCP servers updated: {len(mcp_servers)} server(s)",
                            )
                        else:
                            agent["backend"].pop("mcp_servers", None)
                            console.print("✅ MCP servers removed")

            console.print(f"\n✅ [green]Agent {agent['id']} modified[/green]\n")
            return agent

        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as e:
            console.print(f"[error]❌ Error modifying agent: {e}[/error]")
            return agent

    def apply_preset_to_agent(
        self,
        agent: dict,
        use_case: str,
        agent_index: int = 1,
    ) -> dict:
        """Auto-apply preset configuration to an agent.

        Args:
            agent: Agent configuration dict
            use_case: Use case ID for preset configuration
            agent_index: Agent index for unique workspace naming (1-based)

        Returns:
            Updated agent configuration with preset applied
        """
        if use_case == "custom":
            return agent

        use_case_info = self.USE_CASES.get(use_case, {})
        recommended_tools = use_case_info.get("recommended_tools", [])

        backend_type = agent.get("backend", {}).get("type")
        provider_info = None

        # Find provider info
        for pid, pinfo in self.PROVIDERS.items():
            if pinfo.get("type") == backend_type:
                provider_info = pinfo
                break

        if not provider_info:
            return agent

        # Auto-enable filesystem if recommended
        if "filesystem" in recommended_tools and "filesystem" in provider_info.get(
            "supports",
            [],
        ):
            if not agent["backend"].get("cwd"):
                # Set base workspace name (unique suffix added at runtime in cli.py)
                agent["backend"]["cwd"] = "workspace"

        # Auto-enable web search if recommended
        if "web_search" in recommended_tools:
            if backend_type in [
                "openai",
                "claude",
                "claude_code",
                "gemini",
                "grok",
                "azure_openai",
                "openrouter",  # Supports web search via plugins array
            ]:
                agent["backend"]["enable_web_search"] = True

        # Auto-enable code execution if recommended
        if "code_execution" in recommended_tools:
            if backend_type == "openai" or backend_type == "azure_openai":
                agent["backend"]["enable_code_interpreter"] = True
            elif backend_type in ["claude", "gemini"]:
                agent["backend"]["enable_code_execution"] = True

        # Auto-enable Docker for Docker preset
        if use_case == "coding_docker" and agent["backend"].get("cwd"):
            agent["backend"]["enable_mcp_command_line"] = True
            agent["backend"]["command_line_execution_mode"] = "docker"

        # Note: image_understanding, audio_understanding, video_understanding, and reasoning
        # are passive capabilities - they work automatically when the backend supports them
        # and when appropriate content (images/audio/video) is provided in messages.
        # No explicit backend configuration flags needed.

        return agent

    def customize_agent(
        self,
        agent: dict,
        agent_num: int,
        total_agents: int,
        use_case: str | None = None,
    ) -> dict:
        """Customize a single agent with Panel UI.

        Args:
            agent: Agent configuration dict
            agent_num: Agent number (1-indexed)
            total_agents: Total number of agents
            use_case: Use case ID for preset recommendations

        Returns:
            Updated agent configuration
        """
        try:
            backend_type = agent.get("backend", {}).get("type")
            provider_info = None

            # Find provider info
            for pid, pinfo in self.PROVIDERS.items():
                if pinfo.get("type") == backend_type:
                    provider_info = pinfo
                    break

            if not provider_info:
                console.print(
                    f"[warning]⚠️  Could not find provider for {backend_type}[/warning]",
                )
                return agent

            # Create Panel for this agent
            panel_content = []
            panel_content.append(
                f"[bold]Agent {agent_num} of {total_agents}: {agent['id']}[/bold]\n",
            )

            # Model selection
            models = provider_info.get("models", [])
            if models:
                current_model = agent["backend"].get("model")
                panel_content.append(f"[cyan]Current model:[/cyan] {current_model}")

                console.print(
                    Panel("\n".join(panel_content), border_style="cyan", width=80),
                )
                console.print()

                selected_model = self.select_model_smart(
                    backend_type=backend_type,
                    models=models,
                    current_model=current_model,
                    prompt=f"Select model for {agent['id']}:",
                )

                if selected_model:
                    agent["backend"]["model"] = selected_model
                    console.print(f"\n✓ Model set to {selected_model}")

                    # Configure text verbosity for OpenAI models only
                    if backend_type in ["openai", "azure_openai"]:
                        console.print("\n[dim]Configure text verbosity:[/dim]")
                        console.print("[dim]  • low: Concise responses[/dim]")
                        console.print(
                            "[dim]  • medium: Balanced detail (recommended)[/dim]",
                        )
                        console.print(
                            "[dim]  • high: Detailed, verbose responses[/dim]\n",
                        )

                        verbosity_choice = questionary.select(
                            "Text verbosity level:",
                            choices=[
                                questionary.Choice("Low (concise)", value="low"),
                                questionary.Choice(
                                    "Medium (recommended)",
                                    value="medium",
                                ),
                                questionary.Choice("High (detailed)", value="high"),
                            ],
                            default="medium",
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan bold"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()

                        agent["backend"]["text"] = {
                            "verbosity": verbosity_choice if verbosity_choice else "medium",
                        }
                        console.print(
                            f"✓ Text verbosity set to: {verbosity_choice if verbosity_choice else 'medium'}\n",
                        )

                    # Auto-add reasoning params for GPT-5 and o-series models
                    if selected_model in [
                        "gpt-5",
                        "gpt-5-mini",
                        "gpt-5-nano",
                        "o4",
                        "o4-mini",
                    ]:
                        console.print(
                            "[dim]This model supports extended reasoning. Configure reasoning effort:[/dim]",
                        )
                        console.print(
                            "[dim]  • high: Maximum reasoning depth (slower, more thorough)[/dim]",
                        )
                        console.print(
                            "[dim]  • medium: Balanced reasoning (recommended)[/dim]",
                        )
                        console.print(
                            "[dim]  • low: Faster responses with basic reasoning[/dim]\n",
                        )

                        # Determine default based on model
                        if selected_model in ["gpt-5", "o4"]:
                            default_effort = "medium"  # Changed from high to medium
                        elif selected_model in ["gpt-5-mini", "o4-mini"]:
                            default_effort = "medium"
                        else:  # gpt-5-nano
                            default_effort = "low"

                        effort_choice = questionary.select(
                            "Reasoning effort level:",
                            choices=[
                                questionary.Choice(
                                    "High (maximum depth)",
                                    value="high",
                                ),
                                questionary.Choice(
                                    "Medium (balanced - recommended)",
                                    value="medium",
                                ),
                                questionary.Choice("Low (faster)", value="low"),
                            ],
                            default=default_effort,
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan bold"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()

                        agent["backend"]["reasoning"] = {
                            "effort": effort_choice if effort_choice else default_effort,
                            "summary": "auto",
                        }
                        console.print(
                            f"✓ Reasoning effort set to: {effort_choice if effort_choice else default_effort}\n",
                        )
            else:
                console.print(
                    Panel("\n".join(panel_content), border_style="cyan", width=80),
                )

            # Filesystem access (native or via MCP)
            if "filesystem" in provider_info.get("supports", []):
                console.print()

                # Get filesystem support type from capabilities
                caps = get_capabilities(backend_type)
                fs_type = caps.filesystem_support if caps else "mcp"

                # Claude Code ALWAYS has filesystem access (that's what makes it special!)
                if backend_type == "claude_code":
                    # Filesystem is always enabled for Claude Code
                    current_cwd = agent["backend"].get("cwd", "workspace")
                    console.print(
                        "[dim]Claude Code has native filesystem access (always enabled)[/dim]",
                    )
                    console.print(f"[dim]Current workspace: {current_cwd}[/dim]")

                    if questionary.confirm(
                        "Customize workspace directory?",
                        default=False,
                    ).ask():
                        custom_cwd = questionary.text(
                            "Enter workspace directory:",
                            default=current_cwd,
                        ).ask()
                        if custom_cwd:
                            agent["backend"]["cwd"] = custom_cwd

                    console.print(
                        f"✅ Filesystem access: {agent['backend']['cwd']} (native)",
                    )

                    # Ask about Docker bash execution for Claude Code
                    console.print()
                    console.print("[dim]Claude Code bash execution mode:[/dim]")
                    console.print(
                        "[dim]  • local: Run bash commands directly on your machine (default)[/dim]",
                    )
                    console.print(
                        "[dim]  • docker: Run bash in isolated Docker container (requires Docker setup)[/dim]",
                    )

                    enable_docker = questionary.confirm(
                        "Enable Docker bash execution? (requires Docker setup)",
                        default=(use_case == "coding_docker"),
                    ).ask()

                    if enable_docker:
                        agent["backend"]["enable_mcp_command_line"] = True
                        agent["backend"]["command_line_execution_mode"] = "docker"
                        console.print("🐳 Docker bash execution enabled")
                    else:
                        console.print("💻 Local bash execution enabled (default)")
                else:
                    # For non-Claude Code backends
                    # Check if filesystem is recommended in the preset
                    filesystem_recommended = False
                    if use_case and use_case != "custom":
                        use_case_info = self.USE_CASES.get(use_case, {})
                        filesystem_recommended = "filesystem" in use_case_info.get(
                            "recommended_tools",
                            [],
                        )

                    if fs_type == "native":
                        console.print(
                            "[dim]This backend has native filesystem support[/dim]",
                        )
                    else:
                        console.print(
                            "[dim]This backend supports filesystem operations via MCP[/dim]",
                        )

                    if filesystem_recommended:
                        console.print(
                            "[dim]💡 Filesystem access recommended for this preset[/dim]",
                        )

                    # Auto-enable for Docker preset
                    enable_filesystem = filesystem_recommended
                    if not filesystem_recommended:
                        enable_filesystem = questionary.confirm(
                            "Enable filesystem access for this agent?",
                            default=True,
                        ).ask()

                    if enable_filesystem:
                        # For MCP-based filesystem, set cwd parameter
                        if not agent["backend"].get("cwd"):
                            # Set base workspace name (unique suffix added at runtime in cli.py)
                            agent["backend"]["cwd"] = "workspace"

                        console.print(
                            f"✅ Filesystem access enabled (via MCP): {agent['backend']['cwd']}",
                        )

                        # Enable Docker execution mode for Docker preset
                        if use_case == "coding_docker":
                            agent["backend"]["enable_mcp_command_line"] = True
                            agent["backend"]["command_line_execution_mode"] = "docker"
                            console.print(
                                "🐳 Docker execution mode enabled for isolated code execution",
                            )

            # Built-in tools (backend-specific capabilities)
            # Skip for Claude Code - bash is always available, already configured above
            if backend_type != "claude_code":
                supports = provider_info.get("supports", [])
                builtin_tools = [s for s in supports if s in ["web_search", "code_execution", "bash"]]

                # Get recommended tools from use case
                recommended_tools = []
                if use_case:
                    use_case_info = self.USE_CASES.get(use_case, {})
                    recommended_tools = use_case_info.get("recommended_tools", [])

                if builtin_tools:
                    console.print()

                    # Show preset info if this is a preset use case
                    if recommended_tools and use_case != "custom":
                        console.print(
                            f"[dim]💡 Preset recommendation: {', '.join(recommended_tools)}[/dim]",
                        )

                    tool_choices = []

                    if "web_search" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Web Search",
                                value="web_search",
                                checked="web_search" in recommended_tools,
                            ),
                        )
                    if "code_execution" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Code Execution",
                                value="code_execution",
                                checked="code_execution" in recommended_tools,
                            ),
                        )
                    if "bash" in builtin_tools:
                        tool_choices.append(
                            questionary.Choice(
                                "Bash/Shell",
                                value="bash",
                                checked="bash" in recommended_tools,
                            ),
                        )

                    if tool_choices:
                        selected_tools = questionary.checkbox(
                            "Enable built-in tools for this agent (Space to select, Enter to confirm):",
                            choices=tool_choices,
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()

                        if selected_tools:
                            # Apply backend-specific configuration
                            if "web_search" in selected_tools:
                                if backend_type in [
                                    "openai",
                                    "claude",
                                    "claude_code",
                                    "gemini",
                                    "grok",
                                    "azure_openai",
                                    "openrouter",  # Supports web search via plugins array
                                ]:
                                    agent["backend"]["enable_web_search"] = True

                            if "code_execution" in selected_tools:
                                if backend_type == "openai" or backend_type == "azure_openai":
                                    agent["backend"]["enable_code_interpreter"] = True
                                elif backend_type in ["claude", "gemini"]:
                                    agent["backend"]["enable_code_execution"] = True

                            console.print(
                                f"✅ Enabled {len(selected_tools)} built-in tool(s)",
                            )

            # Multimodal capabilities (passive - no config needed)
            supports = provider_info.get("supports", [])
            multimodal_caps = [
                s
                for s in supports
                if s
                in [
                    "image_understanding",
                    "audio_understanding",
                    "video_understanding",
                    "reasoning",
                ]
            ]

            # Show multimodal capabilities info (passive - no config needed)
            if multimodal_caps:
                console.print()
                console.print(
                    "[dim]📷 This backend also supports (no configuration needed):[/dim]",
                )
                if "image_understanding" in multimodal_caps:
                    console.print(
                        "[dim]  • Image understanding (analyze images, charts, screenshots)[/dim]",
                    )
                if "audio_understanding" in multimodal_caps:
                    console.print(
                        "[dim]  • Audio understanding (transcribe and analyze audio)[/dim]",
                    )
                if "video_understanding" in multimodal_caps:
                    console.print(
                        "[dim]  • Video understanding (analyze video content)[/dim]",
                    )
                if "reasoning" in multimodal_caps:
                    console.print(
                        "[dim]  • Extended reasoning (deep thinking for complex problems)[/dim]",
                    )

            # Custom multimodal tools (unified understanding and generation)
            # Available for ALL use cases - these are active tools using OpenAI's gpt-4.1 API
            console.print()
            console.print("[cyan]Custom Multimodal Tools (New in v0.1.3+):[/cyan]")
            console.print(
                "[dim]These tools let agents process multimodal content using OpenAI's gpt-4.1 API:[/dim]",
            )
            console.print(
                "[dim]  • Works with any backend (uses OpenAI for processing)[/dim]",
            )
            console.print(
                "[dim]  • Processes files agents generate or discover during execution[/dim]",
            )
            console.print(
                "[dim]  • Returns structured JSON with detailed metadata[/dim]",
            )
            console.print("[dim]  • Requires OPENAI_API_KEY in your .env file[/dim]")

            # Default to True for multimodal use case, False for others
            default_add_mm = use_case == "multimodal"

            if questionary.confirm(
                "Add custom multimodal tools?",
                default=default_add_mm,
            ).ask():
                # Determine default selections based on use case
                if use_case == "multimodal":
                    # For multimodal preset, select all by default
                    multimodal_tool_choices = [
                        questionary.Choice(
                            "understand_image - Analyze images (PNG, JPEG, JPG)",
                            value="understand_image",
                            checked=True,
                        ),
                        questionary.Choice(
                            "understand_audio - Transcribe and analyze audio",
                            value="understand_audio",
                            checked=True,
                        ),
                        questionary.Choice(
                            "understand_video - Extract frames and analyze video",
                            value="understand_video",
                            checked=True,
                        ),
                        questionary.Choice(
                            "understand_file - Process documents (PDF, DOCX, XLSX, PPTX)",
                            value="understand_file",
                            checked=True,
                        ),
                        questionary.Choice(
                            "generate_media - Unified image/video/audio generation",
                            value="generate_media",
                            checked=True,
                        ),
                        questionary.Choice(
                            "image_to_image_generation - Transform existing images",
                            value="image_to_image_generation",
                            checked=True,
                        ),
                        questionary.Choice(
                            "text_to_file_generation - Generate documents (PDF, DOCX, etc.)",
                            value="text_to_file_generation",
                            checked=True,
                        ),
                    ]
                elif use_case == "data_analysis":
                    # For data analysis, suggest image and file tools
                    multimodal_tool_choices = [
                        questionary.Choice(
                            "understand_image - Analyze images (PNG, JPEG, JPG)",
                            value="understand_image",
                            checked=True,
                        ),
                        questionary.Choice(
                            "understand_audio - Transcribe and analyze audio",
                            value="understand_audio",
                            checked=False,
                        ),
                        questionary.Choice(
                            "understand_video - Extract frames and analyze video",
                            value="understand_video",
                            checked=False,
                        ),
                        questionary.Choice(
                            "understand_file - Process documents (PDF, DOCX, XLSX, PPTX)",
                            value="understand_file",
                            checked=True,
                        ),
                        questionary.Choice(
                            "generate_media - Unified image/video/audio generation",
                            value="generate_media",
                            checked=False,
                        ),
                        questionary.Choice(
                            "image_to_image_generation - Transform existing images",
                            value="image_to_image_generation",
                            checked=False,
                        ),
                        questionary.Choice(
                            "text_to_file_generation - Generate documents (PDF, DOCX, etc.)",
                            value="text_to_file_generation",
                            checked=True,
                        ),
                    ]
                else:
                    # For other use cases, none selected by default (let user choose)
                    multimodal_tool_choices = [
                        questionary.Choice(
                            "understand_image - Analyze images (PNG, JPEG, JPG)",
                            value="understand_image",
                            checked=False,
                        ),
                        questionary.Choice(
                            "understand_audio - Transcribe and analyze audio",
                            value="understand_audio",
                            checked=False,
                        ),
                        questionary.Choice(
                            "understand_video - Extract frames and analyze video",
                            value="understand_video",
                            checked=False,
                        ),
                        questionary.Choice(
                            "understand_file - Process documents (PDF, DOCX, XLSX, PPTX)",
                            value="understand_file",
                            checked=False,
                        ),
                        questionary.Choice(
                            "generate_media - Unified image/video/audio generation",
                            value="generate_media",
                            checked=False,
                        ),
                        questionary.Choice(
                            "image_to_image_generation - Transform existing images",
                            value="image_to_image_generation",
                            checked=False,
                        ),
                        questionary.Choice(
                            "text_to_file_generation - Generate documents (PDF, DOCX, etc.)",
                            value="text_to_file_generation",
                            checked=False,
                        ),
                    ]

                selected_mm_tools = questionary.checkbox(
                    "Select custom multimodal tools (Space to select, Enter to confirm):",
                    choices=multimodal_tool_choices,
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if selected_mm_tools:
                    # Initialize custom_tools list if not exists
                    if "custom_tools" not in agent["backend"]:
                        agent["backend"]["custom_tools"] = []

                    # Tools not located directly under massgen/tool/_multimodal_tools/
                    # need explicit entry-point mapping.
                    multimodal_tool_entry_points = {
                        "generate_media": {
                            "path": "massgen/tool/_multimodal_tools/generation/generate_media.py",
                            "function": "generate_media",
                        },
                    }

                    # Add selected tools
                    for tool_name in selected_mm_tools:
                        entry_point = multimodal_tool_entry_points.get(
                            tool_name,
                            {
                                "path": f"massgen/tool/_multimodal_tools/{tool_name}.py",
                                "function": tool_name,
                            },
                        )
                        tool_config = {
                            "name": [tool_name],
                            "category": "multimodal",
                            "path": entry_point["path"],
                            "function": [entry_point["function"]],
                        }
                        agent["backend"]["custom_tools"].append(tool_config)

                    console.print(
                        f"✅ Added {len(selected_mm_tools)} custom multimodal tool(s)",
                    )

            # MCP servers (custom only)
            # Note: Filesystem is handled internally above, NOT as external MCP
            if "mcp" in provider_info.get("supports", []):
                console.print()
                console.print(
                    "[dim]MCP servers are external integrations. Filesystem is handled internally (configured above).[/dim]",
                )

                if questionary.confirm("Add custom MCP servers?", default=False).ask():
                    mcp_servers = []
                    while True:
                        custom_server = self.add_custom_mcp_server()
                        if custom_server:
                            mcp_servers.append(custom_server)

                            # Ask if they want to add another
                            if not questionary.confirm(
                                "Add another custom MCP server?",
                                default=False,
                            ).ask():
                                break
                        else:
                            break

                    # Add to agent config if any MCPs were configured
                    if mcp_servers:
                        agent["backend"]["mcp_servers"] = mcp_servers
                        console.print(
                            f"\n✅ Total: {len(mcp_servers)} MCP server(s) configured for this agent\n",
                        )

            console.print(f"✅ [green]Agent {agent_num} configured[/green]\n")
            return agent

        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as e:
            console.print(f"[error]❌ Error customizing agent: {e}[/error]")
            return agent

    def configure_agents(self, use_case: str, api_keys: dict[str, bool]) -> list[dict]:
        """Configure agents with batch creation and individual customization."""
        try:
            # Step header
            step_panel = Panel(
                "[bold cyan]Step 2 of 4: Agent Setup[/bold cyan]\n\n[italic dim]Choose any provider(s) - all types work for your selected use case[/italic dim]",
                border_style="cyan",
                padding=(0, 2),
                width=80,
            )
            console.print(step_panel)
            console.print()

            # Show available providers now (right when users need to select them)
            self.show_available_providers(api_keys)

            use_case_info = self.USE_CASES.get(use_case, {})
            recommended = use_case_info.get("recommended_agents", 1)

            # Step 2a: How many agents?
            console.print(
                f"  💡 [dim]Recommended for this use case: {recommended} agent(s)[/dim]",
            )
            console.print()

            # Build choices with proper default handling
            num_choices = [
                questionary.Choice("1 agent", value=1),
                questionary.Choice("2 agents", value=2),
                questionary.Choice(
                    "3 agents (recommended for diverse perspectives)",
                    value=3,
                ),
                questionary.Choice("4 agents", value=4),
                questionary.Choice("5 agents", value=5),
                questionary.Choice("Custom number", value="custom"),
            ]

            # Find the default choice by value
            default_choice = None
            for choice in num_choices:
                if choice.value == recommended:
                    default_choice = choice.value
                    break

            try:
                num_agents_choice = questionary.select(
                    "How many agents?",
                    choices=num_choices,
                    default=default_choice,
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if num_agents_choice is None:
                    raise KeyboardInterrupt  # User cancelled

                if num_agents_choice == "custom":
                    num_agents_text = questionary.text(
                        "Enter number of agents:",
                        validate=lambda x: x.isdigit() and int(x) > 0,
                    ).ask()
                    if num_agents_text is None:
                        raise KeyboardInterrupt  # User cancelled
                    num_agents = int(num_agents_text) if num_agents_text else recommended
                else:
                    num_agents = num_agents_choice
            except Exception as e:
                console.print(f"[warning]⚠️  Error with selection: {e}[/warning]")
                console.print(f"[info]Using recommended: {recommended} agents[/info]")
                num_agents = recommended

            if num_agents < 1:
                console.print(
                    "[warning]⚠️  Number of agents must be at least 1. Setting to 1.[/warning]",
                )
                num_agents = 1

            # Filter providers: only those with API keys, excluding generic backends
            excluded_generic_backends = [
                "chatcompletion",
                "inference",
            ]  # Now superseded by specific providers

            available_providers = [p for p, has_key in api_keys.items() if has_key and p not in excluded_generic_backends]  # Only show providers with keys, exclude generic

            if not available_providers:
                console.print(
                    "[error]❌ No providers with API keys found. Please set at least one API key.[/error]",
                )
                raise ValueError("No providers available")

            # Step 2b: Same provider or mix?
            agents = []
            if num_agents == 1:
                # Single agent - just pick provider directly
                console.print()

                provider_choices = [
                    questionary.Choice(
                        self.PROVIDERS.get(pid, {}).get("name", pid),
                        value=pid,
                    )
                    for pid in available_providers
                ]

                provider_id = questionary.select(
                    "Select provider:",
                    choices=provider_choices,
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if provider_id is None:
                    raise KeyboardInterrupt  # User cancelled

                agents = self.batch_create_agents(1, provider_id)
                provider_name = self.PROVIDERS.get(provider_id, {}).get(
                    "name",
                    provider_id,
                )
                console.print()
                console.print(f"  ✅ Created 1 {provider_name} agent")
                console.print()

            else:
                # Multiple agents - ask if same or different providers
                console.print()

                setup_mode = questionary.select(
                    "Setup mode:",
                    choices=[
                        questionary.Choice(
                            "Same provider for all agents (quick setup)",
                            value="same",
                        ),
                        questionary.Choice(
                            "Mix different providers (advanced)",
                            value="mix",
                        ),
                    ],
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if setup_mode is None:
                    raise KeyboardInterrupt  # User cancelled

                if setup_mode == "same":
                    # Batch creation with same provider
                    console.print()

                    provider_choices = [
                        questionary.Choice(
                            self.PROVIDERS.get(pid, {}).get("name", pid),
                            value=pid,
                        )
                        for pid in available_providers
                    ]

                    provider_id = questionary.select(
                        "Select provider:",
                        choices=provider_choices,
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()

                    if provider_id is None:
                        raise KeyboardInterrupt  # User cancelled

                    agents = self.batch_create_agents(num_agents, provider_id)
                    provider_name = self.PROVIDERS.get(provider_id, {}).get(
                        "name",
                        provider_id,
                    )
                    console.print()
                    console.print(f"  ✅ Created {num_agents} {provider_name} agents")
                    console.print()

                else:
                    # Advanced: mix providers
                    console.print()
                    console.print(
                        "[yellow]  💡 Advanced mode: Configure each agent individually[/yellow]",
                    )
                    console.print()
                    for i in range(num_agents):
                        try:
                            console.print(
                                f"[bold cyan]Agent {i + 1} of {num_agents}:[/bold cyan]",
                            )

                            provider_choices = [
                                questionary.Choice(
                                    self.PROVIDERS.get(pid, {}).get("name", pid),
                                    value=pid,
                                )
                                for pid in available_providers
                            ]

                            provider_id = questionary.select(
                                f"Select provider for agent {i + 1}:",
                                choices=provider_choices,
                                style=questionary.Style(
                                    [
                                        ("selected", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                    ],
                                ),
                                use_arrow_keys=True,
                            ).ask()

                            if not provider_id:
                                provider_id = available_providers[0]

                            agent_batch = self.batch_create_agents(
                                1,
                                provider_id,
                                len(agents),
                            )
                            agents.extend(agent_batch)

                            provider_name = self.PROVIDERS.get(provider_id, {}).get(
                                "name",
                                provider_id,
                            )
                            console.print(
                                f"✅ Agent {i + 1} created: {provider_name}\n",
                            )

                        except (KeyboardInterrupt, EOFError):
                            raise
                        except Exception as e:
                            console.print(
                                f"[error]❌ Error configuring agent {i + 1}: {e}[/error]",
                            )
                            console.print("[info]Skipping this agent...[/info]")

            if not agents:
                console.print(
                    "[error]❌ No agents were successfully configured.[/error]",
                )
                raise ValueError("Failed to configure any agents")

            # Step 2c: Model selection and preset application
            # Step header
            step_panel = Panel(
                "[bold cyan]Step 3 of 4: Agent Configuration[/bold cyan]",
                border_style="cyan",
                padding=(0, 2),
                width=80,
            )
            console.print(step_panel)
            console.print()

            # For non-custom presets, show info and configure models
            if use_case != "custom":
                use_case_info = self.USE_CASES.get(use_case, {})
                recommended_tools = use_case_info.get("recommended_tools", [])

                console.print(
                    f"  [bold green]✓ Preset Selected:[/bold green] {use_case_info.get('name', use_case)}",
                )
                console.print(f"  [dim]{use_case_info.get('description', '')}[/dim]")
                console.print()

                if recommended_tools:
                    console.print("  [cyan]This preset will auto-configure:[/cyan]")
                    for tool in recommended_tools:
                        tool_display = {
                            "filesystem": "📁 Filesystem access",
                            "code_execution": "💻 Code execution",
                            "web_search": "🔍 Web search",
                            "mcp": "🔌 MCP servers",
                            "image_understanding": "📷 Image understanding (backend capability)",
                            "audio_understanding": "🎵 Audio understanding (backend capability)",
                            "video_understanding": "🎬 Video understanding (backend capability)",
                        }.get(tool, tool)
                        console.print(f"    • {tool_display}")

                    if use_case == "coding_docker":
                        console.print("    • 🐳 Docker isolated execution")

                    if use_case == "multimodal":
                        console.print(
                            "    • 🎨 Custom multimodal tools (understand_image, understand_audio, understand_video, understand_file)",
                        )

                    console.print()

                # Let users select models for each agent
                console.print("  [cyan]Select models for your agents:[/cyan]")
                console.print()
                for i, agent in enumerate(agents, 1):
                    backend_type = agent.get("backend", {}).get("type")
                    provider_info = None

                    # Find provider info
                    for pid, pinfo in self.PROVIDERS.items():
                        if pinfo.get("type") == backend_type:
                            provider_info = pinfo
                            break

                    if provider_info:
                        models = provider_info.get("models", [])
                        if models and len(models) > 1:
                            current_model = agent["backend"].get("model")
                            console.print(
                                f"[bold]Agent {i} ({agent['id']}) - {provider_info.get('name')}:[/bold]",
                            )

                            selected_model = self.select_model_smart(
                                backend_type=backend_type,
                                models=models,
                                current_model=current_model,
                                prompt="Select model:",
                            )

                            if selected_model:
                                agent["backend"]["model"] = selected_model
                                console.print(f"  ✓ {selected_model}")

                                # Configure text verbosity for OpenAI models only
                                if backend_type in ["openai", "azure_openai"]:
                                    console.print(
                                        "\n  [dim]Configure text verbosity:[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• low: Concise responses[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• medium: Balanced detail (recommended)[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• high: Detailed, verbose responses[/dim]\n",
                                    )

                                    verbosity_choice = questionary.select(
                                        "  Text verbosity:",
                                        choices=[
                                            questionary.Choice(
                                                "Low (concise)",
                                                value="low",
                                            ),
                                            questionary.Choice(
                                                "Medium (recommended)",
                                                value="medium",
                                            ),
                                            questionary.Choice(
                                                "High (detailed)",
                                                value="high",
                                            ),
                                        ],
                                        default="medium",
                                        style=questionary.Style(
                                            [
                                                ("selected", "fg:cyan bold"),
                                                ("pointer", "fg:cyan bold"),
                                                ("highlighted", "fg:cyan"),
                                            ],
                                        ),
                                        use_arrow_keys=True,
                                    ).ask()

                                    agent["backend"]["text"] = {
                                        "verbosity": verbosity_choice if verbosity_choice else "medium",
                                    }
                                    console.print(
                                        f"  ✓ Text verbosity: {verbosity_choice if verbosity_choice else 'medium'}\n",
                                    )

                                # Auto-add reasoning params for GPT-5 and o-series models
                                if selected_model in [
                                    "gpt-5",
                                    "gpt-5-mini",
                                    "gpt-5-nano",
                                    "o4",
                                    "o4-mini",
                                ]:
                                    console.print(
                                        "  [dim]Configure reasoning effort:[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• high: Maximum depth (slower)[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• medium: Balanced (recommended)[/dim]",
                                    )
                                    console.print(
                                        "  [dim]• low: Faster responses[/dim]\n",
                                    )

                                    # Determine default based on model
                                    if selected_model in ["gpt-5", "o4"]:
                                        default_effort = "medium"  # Changed from high to medium
                                    elif selected_model in ["gpt-5-mini", "o4-mini"]:
                                        default_effort = "medium"
                                    else:  # gpt-5-nano
                                        default_effort = "low"

                                    effort_choice = questionary.select(
                                        "  Reasoning effort:",
                                        choices=[
                                            questionary.Choice("High", value="high"),
                                            questionary.Choice(
                                                "Medium (recommended)",
                                                value="medium",
                                            ),
                                            questionary.Choice("Low", value="low"),
                                        ],
                                        default=default_effort,
                                        style=questionary.Style(
                                            [
                                                ("selected", "fg:cyan bold"),
                                                ("pointer", "fg:cyan bold"),
                                                ("highlighted", "fg:cyan"),
                                            ],
                                        ),
                                        use_arrow_keys=True,
                                    ).ask()

                                    agent["backend"]["reasoning"] = {
                                        "effort": effort_choice if effort_choice else default_effort,
                                        "summary": "auto",
                                    }
                                    console.print(
                                        f"  ✓ Reasoning effort: {effort_choice if effort_choice else default_effort}\n",
                                    )

                # Auto-apply preset to all agents
                console.print()
                console.print(
                    "  [cyan]Applying preset configuration to all agents...[/cyan]",
                )
                for i, agent in enumerate(agents):
                    agents[i] = self.apply_preset_to_agent(
                        agent,
                        use_case,
                        agent_index=i + 1,
                    )

                console.print(
                    f"  [green]✅ {len(agents)} agent(s) configured with preset[/green]",
                )
                console.print()

                # Ask if user wants additional customization
                customize_choice = Confirm.ask(
                    "\n  [prompt]Further customize agent settings (advanced)?[/prompt]",
                    default=False,
                )
                if customize_choice is None:
                    raise KeyboardInterrupt  # User cancelled
                if customize_choice:
                    console.print()
                    console.print("  [cyan]Entering advanced customization...[/cyan]")
                    console.print()
                    for i, agent in enumerate(agents, 1):
                        # For agents after the first, offer clone option
                        if i > 1:
                            console.print(
                                f"\n[bold cyan]Agent {i} of {len(agents)}: {agent['id']}[/bold cyan]",
                            )
                            clone_choice = questionary.select(
                                "How would you like to configure this agent?",
                                choices=[
                                    questionary.Choice(
                                        f"📋 Copy agent_{chr(ord('a') + i - 2)}'s configuration",
                                        value="clone",
                                    ),
                                    questionary.Choice(
                                        f"✏️  Copy agent_{chr(ord('a') + i - 2)} and modify specific settings",
                                        value="clone_modify",
                                    ),
                                    questionary.Choice(
                                        "⚙️  Configure from scratch",
                                        value="scratch",
                                    ),
                                ],
                                style=questionary.Style(
                                    [
                                        ("selected", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                    ],
                                ),
                                use_arrow_keys=True,
                            ).ask()

                            if clone_choice == "clone":
                                # Clone the previous agent, preserving current agent's backend type
                                source_agent = agents[i - 2]
                                target_backend_type = agent.get("backend", {}).get(
                                    "type",
                                )
                                source_backend_type = source_agent.get(
                                    "backend",
                                    {},
                                ).get("type")

                                agent = self.clone_agent(
                                    source_agent,
                                    agent["id"],
                                    target_backend_type,
                                )

                                # If cross-provider cloning, prompt for model selection
                                if target_backend_type != source_backend_type:
                                    console.print(
                                        f"✅ Cloned settings from agent_{chr(ord('a') + i - 2)} ({source_backend_type})",
                                    )
                                    console.print(
                                        f"   [dim]Note: Model must be selected for {target_backend_type}[/dim]",
                                    )

                                    # Show skipped settings warning if any
                                    skipped = agent.get("_skipped_settings", [])
                                    if skipped:
                                        console.print(
                                            "   [yellow]⚠️  Skipped incompatible settings:[/yellow]",
                                        )
                                        for setting in skipped:
                                            console.print(f"      • {setting}")
                                    console.print()

                                    # Prompt for model selection
                                    target_provider_info = None
                                    for _, pinfo in self.PROVIDERS.items():
                                        if pinfo.get("type") == target_backend_type:
                                            target_provider_info = pinfo
                                            break

                                    if target_provider_info and target_provider_info.get("models"):
                                        model_choice = questionary.select(
                                            f"Select {target_backend_type} model:",
                                            choices=target_provider_info["models"],
                                            style=questionary.Style(
                                                [
                                                    ("selected", "fg:cyan bold"),
                                                    ("pointer", "fg:cyan bold"),
                                                ],
                                            ),
                                        ).ask()

                                        if model_choice:
                                            agent["backend"]["model"] = model_choice
                                            console.print(
                                                f"   ✅ Model: {model_choice}",
                                            )

                                    # Clean up temporary skipped settings marker
                                    agent.pop("_skipped_settings", None)
                                else:
                                    console.print(
                                        f"✅ Cloned configuration from agent_{chr(ord('a') + i - 2)}",
                                    )
                                    # Clean up temporary skipped settings marker
                                    agent.pop("_skipped_settings", None)

                                agents[i - 1] = agent
                                console.print()
                                continue
                            elif clone_choice == "clone_modify":
                                # Clone and selectively modify, preserving current agent's backend type
                                source_agent = agents[i - 2]
                                target_backend_type = agent.get("backend", {}).get(
                                    "type",
                                )
                                source_backend_type = source_agent.get(
                                    "backend",
                                    {},
                                ).get("type")

                                agent = self.clone_agent(
                                    source_agent,
                                    agent["id"],
                                    target_backend_type,
                                )

                                # If cross-provider cloning, prompt for model selection before modification
                                if target_backend_type != source_backend_type:
                                    console.print(
                                        f"✅ Cloned settings from agent_{chr(ord('a') + i - 2)} ({source_backend_type})",
                                    )
                                    console.print(
                                        f"   [dim]Note: Model must be selected for {target_backend_type}[/dim]",
                                    )

                                    # Show skipped settings warning if any
                                    skipped = agent.get("_skipped_settings", [])
                                    if skipped:
                                        console.print(
                                            "   [yellow]⚠️  Skipped incompatible settings:[/yellow]",
                                        )
                                        for setting in skipped:
                                            console.print(f"      • {setting}")
                                    console.print()

                                    # Prompt for model selection
                                    target_provider_info = None
                                    for _, pinfo in self.PROVIDERS.items():
                                        if pinfo.get("type") == target_backend_type:
                                            target_provider_info = pinfo
                                            break

                                    if target_provider_info and target_provider_info.get("models"):
                                        model_choice = questionary.select(
                                            f"Select {target_backend_type} model:",
                                            choices=target_provider_info["models"],
                                            style=questionary.Style(
                                                [
                                                    ("selected", "fg:cyan bold"),
                                                    ("pointer", "fg:cyan bold"),
                                                ],
                                            ),
                                        ).ask()

                                        if model_choice:
                                            agent["backend"]["model"] = model_choice
                                            console.print(
                                                f"   ✅ Model: {model_choice}",
                                            )
                                            console.print()

                                    # Clean up temporary skipped settings marker before modification
                                    agent.pop("_skipped_settings", None)

                                agent = self.modify_cloned_agent(agent, i)
                                agents[i - 1] = agent
                                continue

                        # Configure from scratch or first agent
                        agent = self.customize_agent(
                            agent,
                            i,
                            len(agents),
                            use_case=use_case,
                        )
                        agents[i - 1] = agent
            else:
                # Custom configuration - always customize
                console.print(
                    "  [cyan]Custom configuration - configuring each agent...[/cyan]",
                )
                console.print()
                for i, agent in enumerate(agents, 1):
                    # For agents after the first, offer clone option
                    if i > 1:
                        console.print(
                            f"\n[bold cyan]Agent {i} of {len(agents)}: {agent['id']}[/bold cyan]",
                        )
                        clone_choice = questionary.select(
                            "How would you like to configure this agent?",
                            choices=[
                                questionary.Choice(
                                    f"📋 Copy agent_{chr(ord('a') + i - 2)}'s configuration",
                                    value="clone",
                                ),
                                questionary.Choice(
                                    f"✏️  Copy agent_{chr(ord('a') + i - 2)} and modify specific settings",
                                    value="clone_modify",
                                ),
                                questionary.Choice(
                                    "⚙️  Configure from scratch",
                                    value="scratch",
                                ),
                            ],
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan bold"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()

                        if clone_choice == "clone":
                            # Clone the previous agent, preserving current agent's backend type
                            source_agent = agents[i - 2]
                            target_backend_type = agent.get("backend", {}).get("type")
                            source_backend_type = source_agent.get("backend", {}).get(
                                "type",
                            )

                            agent = self.clone_agent(
                                source_agent,
                                agent["id"],
                                target_backend_type,
                            )

                            # If cross-provider cloning, prompt for model selection
                            if target_backend_type != source_backend_type:
                                console.print(
                                    f"✅ Cloned settings from agent_{chr(ord('a') + i - 2)} ({source_backend_type})",
                                )
                                console.print(
                                    f"   [dim]Note: Model must be selected for {target_backend_type}[/dim]",
                                )

                                # Show skipped settings warning if any
                                skipped = agent.get("_skipped_settings", [])
                                if skipped:
                                    console.print(
                                        "   [yellow]⚠️  Skipped incompatible settings:[/yellow]",
                                    )
                                    for setting in skipped:
                                        console.print(f"      • {setting}")
                                console.print()

                                # Prompt for model selection
                                target_provider_info = None
                                for _, pinfo in self.PROVIDERS.items():
                                    if pinfo.get("type") == target_backend_type:
                                        target_provider_info = pinfo
                                        break

                                if target_provider_info and target_provider_info.get(
                                    "models",
                                ):
                                    model_choice = questionary.select(
                                        f"Select {target_backend_type} model:",
                                        choices=target_provider_info["models"],
                                        style=questionary.Style(
                                            [
                                                ("selected", "fg:cyan bold"),
                                                ("pointer", "fg:cyan bold"),
                                            ],
                                        ),
                                    ).ask()

                                    if model_choice:
                                        agent["backend"]["model"] = model_choice
                                        console.print(f"   ✅ Model: {model_choice}")

                                # Clean up temporary skipped settings marker
                                agent.pop("_skipped_settings", None)
                            else:
                                console.print(
                                    f"✅ Cloned configuration from agent_{chr(ord('a') + i - 2)}",
                                )
                                # Clean up temporary skipped settings marker
                                agent.pop("_skipped_settings", None)

                            agents[i - 1] = agent
                            console.print()
                            continue
                        elif clone_choice == "clone_modify":
                            # Clone and selectively modify, preserving current agent's backend type
                            source_agent = agents[i - 2]
                            target_backend_type = agent.get("backend", {}).get("type")
                            source_backend_type = source_agent.get("backend", {}).get(
                                "type",
                            )

                            agent = self.clone_agent(
                                source_agent,
                                agent["id"],
                                target_backend_type,
                            )

                            # If cross-provider cloning, prompt for model selection before modification
                            if target_backend_type != source_backend_type:
                                console.print(
                                    f"✅ Cloned settings from agent_{chr(ord('a') + i - 2)} ({source_backend_type})",
                                )
                                console.print(
                                    f"   [dim]Note: Model must be selected for {target_backend_type}[/dim]",
                                )

                                # Show skipped settings warning if any
                                skipped = agent.get("_skipped_settings", [])
                                if skipped:
                                    console.print(
                                        "   [yellow]⚠️  Skipped incompatible settings:[/yellow]",
                                    )
                                    for setting in skipped:
                                        console.print(f"      • {setting}")
                                console.print()

                                # Prompt for model selection
                                target_provider_info = None
                                for _, pinfo in self.PROVIDERS.items():
                                    if pinfo.get("type") == target_backend_type:
                                        target_provider_info = pinfo
                                        break

                                if target_provider_info and target_provider_info.get(
                                    "models",
                                ):
                                    model_choice = questionary.select(
                                        f"Select {target_backend_type} model:",
                                        choices=target_provider_info["models"],
                                        style=questionary.Style(
                                            [
                                                ("selected", "fg:cyan bold"),
                                                ("pointer", "fg:cyan bold"),
                                            ],
                                        ),
                                    ).ask()

                                    if model_choice:
                                        agent["backend"]["model"] = model_choice
                                        console.print(f"   ✅ Model: {model_choice}")
                                        console.print()

                                # Clean up temporary skipped settings marker before modification
                                agent.pop("_skipped_settings", None)

                            agent = self.modify_cloned_agent(agent, i)
                            agents[i - 1] = agent
                            continue

                    # Configure from scratch or first agent
                    agent = self.customize_agent(
                        agent,
                        i,
                        len(agents),
                        use_case=use_case,
                    )
                    agents[i - 1] = agent

            return agents

        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as e:
            console.print(f"[error]❌ Fatal error in agent configuration: {e}[/error]")
            raise

    def configure_tools(
        self,
        use_case: str,
        agents: list[dict],
    ) -> tuple[list[dict], dict]:
        """Configure orchestrator-level settings (tools are configured per-agent)."""
        try:
            # Step header
            step_panel = Panel(
                "[bold cyan]Step 4 of 4: Orchestrator Configuration[/bold cyan]\n\n[dim]Note: Tools and capabilities were configured per-agent in the previous step.[/dim]",
                border_style="cyan",
                padding=(0, 2),
                width=80,
            )
            console.print(step_panel)
            console.print()

            orchestrator_config = {}

            # Check if any agents have filesystem enabled (Claude Code with cwd)
            has_filesystem = any(a.get("backend", {}).get("cwd") or a.get("backend", {}).get("type") == "claude_code" for a in agents)

            if has_filesystem:
                console.print("  [cyan]Filesystem-enabled agents detected[/cyan]")
                console.print()
                orchestrator_config["snapshot_storage"] = "snapshots"
                orchestrator_config["agent_temporary_workspace"] = "temp_workspaces"

                # Context paths
                console.print(
                    "  [dim]Context paths give agents access to your project files.[/dim]",
                )
                console.print(
                    "  [dim]Paths can be absolute or relative (resolved against current directory).[/dim]",
                )
                console.print(
                    "  [dim]Note: During coordination, all context paths are read-only.[/dim]",
                )
                console.print(
                    "  [dim]      Write permission applies only to the final agent.[/dim]",
                )
                console.print()

                add_paths = Confirm.ask(
                    "[prompt]Add context paths?[/prompt]",
                    default=False,
                )
                if add_paths is None:
                    raise KeyboardInterrupt  # User cancelled
                if add_paths:
                    context_paths = []
                    while True:
                        path = Prompt.ask(
                            "[prompt]Enter directory or file path (or press Enter to finish)[/prompt]",
                        )
                        if path is None:
                            raise KeyboardInterrupt  # User cancelled
                        if not path:
                            break

                        permission = Prompt.ask(
                            "[prompt]Permission (write means final agent can modify)[/prompt]",
                            choices=["read", "write"],
                            default="write",
                        )
                        if permission is None:
                            raise KeyboardInterrupt  # User cancelled

                        context_path_entry = {
                            "path": path,
                            "permission": permission,
                        }

                        # If write permission, offer to add protected paths
                        if permission == "write":
                            console.print(
                                "[dim]Protected paths are files/directories immune from modification[/dim]",
                            )
                            if Confirm.ask(
                                "[prompt]Add protected paths (e.g., .env, config.json)?[/prompt]",
                                default=False,
                            ):
                                protected_paths = []
                                console.print(
                                    "[dim]Enter paths relative to the context path (or press Enter to finish)[/dim]",
                                )
                                while True:
                                    protected_path = Prompt.ask(
                                        "[prompt]Protected path[/prompt]",
                                    )
                                    if not protected_path:
                                        break
                                    protected_paths.append(protected_path)
                                    console.print(f"🔒 Protected: {protected_path}")

                                if protected_paths:
                                    context_path_entry["protected_paths"] = protected_paths

                        context_paths.append(context_path_entry)
                        console.print(f"✅ Added: {path} ({permission})")

                    if context_paths:
                        orchestrator_config["context_paths"] = context_paths

            # Multi-turn sessions (always enabled)
            if not orchestrator_config:
                orchestrator_config = {}
            orchestrator_config["session_storage"] = "sessions"
            console.print()
            console.print(
                "  ✅ Multi-turn sessions enabled (supports persistent conversations)",
            )

            # Planning Mode (for MCP irreversible actions) - only ask if MCPs are configured
            has_mcp = any(a.get("backend", {}).get("mcp_servers") for a in agents)
            if has_mcp:
                console.print()
                console.print(
                    "  [dim]Planning Mode: Prevents MCP tool execution during coordination[/dim]",
                )
                console.print(
                    "  [dim](for irreversible actions like Discord/Twitter posts)[/dim]",
                )
                console.print()
                planning_choice = Confirm.ask(
                    "  [prompt]Enable planning mode for MCP tools?[/prompt]",
                    default=False,
                )
                if planning_choice is None:
                    raise KeyboardInterrupt  # User cancelled
                if planning_choice:
                    orchestrator_config["coordination"] = {
                        "enable_planning_mode": True,
                    }
                    console.print()
                    console.print(
                        "  ✅ Planning mode enabled - MCP tools will plan without executing during coordination",
                    )

            # Agent Task Planning
            console.print()
            console.print(
                "  [dim]Agent Task Planning: Agents can organize work with task lists and dependencies[/dim]",
            )
            console.print(
                "  [dim]• Agents can create task plans to break down complex work[/dim]",
            )
            console.print(
                "  [dim]• Track progress and manage dependencies between tasks[/dim]",
            )
            console.print(
                "  [dim]• Useful for multi-step projects and coordination[/dim]",
            )
            console.print()

            task_planning_choice = Confirm.ask(
                "  [prompt]Enable agent task planning?[/prompt]",
                default=False,
            )
            if task_planning_choice is None:
                raise KeyboardInterrupt  # User cancelled
            if task_planning_choice:
                if "coordination" not in orchestrator_config:
                    orchestrator_config["coordination"] = {}
                orchestrator_config["coordination"]["enable_agent_task_planning"] = True
                console.print()
                console.print(
                    "  ✅ Agent task planning enabled - agents can create and manage task plans",
                )

            # Agent Communication / Broadcasts
            console.print()
            console.print(
                "  [dim]Agent Communication: Agents can ask questions to each other and optionally humans[/dim]",
            )
            console.print(
                "  [dim]• Agents can use ask_others() tool to request help or coordinate[/dim]",
            )
            console.print(
                "  [dim]• Enables collaborative problem-solving during coordination[/dim]",
            )
            console.print(
                "  [dim]• Human can optionally participate in agent discussions[/dim]",
            )
            console.print()

            broadcast_input = Prompt.ask(
                "  [prompt]Enable agent communication?[/prompt]",
                choices=["n", "a", "h"],
                default="n",
                show_choices=False,
            )

            console.print(
                "  [dim]Choices: (n) No / (a) Agent-to-agent only / (h) Include human prompts[/dim]",
            )

            if broadcast_input == "a":
                if "coordination" not in orchestrator_config:
                    orchestrator_config["coordination"] = {}
                orchestrator_config["coordination"]["broadcast"] = "agents"
                console.print()
                console.print(
                    "  ✅ Agent-to-agent communication enabled - agents can coordinate with each other",
                )
            elif broadcast_input == "h":
                if "coordination" not in orchestrator_config:
                    orchestrator_config["coordination"] = {}
                orchestrator_config["coordination"]["broadcast"] = "human"
                console.print()
                console.print(
                    "  ✅ Agent and human communication enabled - you'll be prompted when agents ask questions",
                )

            # Broadcast Sensitivity (if broadcasts enabled)
            if broadcast_input in ["a", "h"]:
                console.print()
                console.print(
                    "  [dim]Broadcast Sensitivity: How frequently agents use ask_others()[/dim]",
                )
                console.print(
                    "  [dim]• Low: Only for critical decisions or when blocked[/dim]",
                )
                console.print(
                    "  [dim]• Medium: For significant decisions and design choices (recommended)[/dim]",
                )
                console.print(
                    "  [dim]• High: Frequently - whenever considering options or proposing approaches[/dim]",
                )
                console.print()

                sensitivity_input = Prompt.ask(
                    "  [prompt]Broadcast sensitivity level?[/prompt]",
                    choices=["l", "m", "h"],
                    default="m",
                    show_choices=False,
                )

                console.print("  [dim]Choices: (l) Low / (m) Medium / (h) High[/dim]")

                sensitivity_map = {"l": "low", "m": "medium", "h": "high"}
                orchestrator_config["coordination"]["broadcast_sensitivity"] = sensitivity_map[sensitivity_input]
                console.print()
                console.print(
                    f"  ✅ Broadcast sensitivity set to: {sensitivity_map[sensitivity_input]}",
                )

            # Orchestration Restart Feature
            console.print()
            console.print(
                "  [dim]Orchestration Restart: Automatic quality checks with self-correction[/dim]",
            )
            console.print(
                "  [dim]• Agent evaluates its own answer after coordination[/dim]",
            )
            console.print(
                "  [dim]• Can restart with specific improvement instructions if incomplete[/dim]",
            )
            console.print(
                "  [dim]• Each attempt gets isolated logs in attempt_1/, attempt_2/, etc.[/dim]",
            )
            console.print(
                "  [dim]• Works with all backends (OpenAI, Claude, Gemini, Grok, etc.)[/dim]",
            )
            console.print(
                "  [dim]• 0 = no restarts (default), 1-2 = recommended, 3 = maximum[/dim]",
            )
            console.print()

            restart_input = Prompt.ask(
                "  [prompt]Max orchestration restarts (0-3)[/prompt]",
                choices=["0", "1", "2", "3"],
                default="0",
            )

            max_restarts = int(restart_input)
            if max_restarts > 0:
                if "coordination" not in orchestrator_config:
                    orchestrator_config["coordination"] = {}
                orchestrator_config["coordination"]["max_orchestration_restarts"] = max_restarts
                console.print()
                console.print(
                    f"  ✅ Orchestration restart enabled: up to {max_restarts} restart(s) allowed",
                )

            # Voting Sensitivity - only ask for multi-agent setups
            if len(agents) > 1:
                console.print()
                console.print(
                    "  [dim]Voting Sensitivity: Controls how agents reach consensus[/dim]",
                )
                console.print(
                    "  [dim]• L: Lenient - Lower threshold for faster decisions (default)[/dim]",
                )
                console.print(
                    "  [dim]• B: Balanced - Often requires more answers for consensus[/dim]",
                )
                console.print(
                    "  [dim]• S: Strict - High standards, maximum quality (slowest)[/dim]",
                )
                console.print()

                voting_input = Prompt.ask(
                    "  [prompt]Voting sensitivity[/prompt]",
                    choices=["l", "b", "s"],
                    default="l",
                )

                # Map input to full value
                voting_map = {"l": "lenient", "b": "balanced", "s": "strict"}
                voting_choice = voting_map[voting_input]

                orchestrator_config["voting_sensitivity"] = voting_choice
                console.print()
                console.print(f"  ✅ Voting sensitivity set to: {voting_choice}")

                # Answer Count Limit
                console.print()
                console.print(
                    "  [dim]Answer Count Limit: Controls maximum new answers per agent[/dim]",
                )
                console.print("  [dim]• Prevents endless coordination rounds[/dim]")
                console.print(
                    "  [dim]• After limit, agents can only vote (not provide new answers)[/dim]",
                )
                console.print()

                limit_input = Prompt.ask(
                    "  [prompt]Max new answers per agent (leave empty for unlimited)[/prompt]",
                    default="",
                )

                if limit_input.strip():
                    try:
                        answer_limit = int(limit_input)
                        if answer_limit > 0:
                            orchestrator_config["max_new_answers_per_agent"] = answer_limit
                            console.print()
                            console.print(
                                f"  ✅ Answer limit set to: {answer_limit} per agent",
                            )
                        else:
                            console.print()
                            console.print("  ⚠️  Invalid limit - using unlimited")
                    except ValueError:
                        console.print()
                        console.print("  ⚠️  Invalid number - using unlimited")
                else:
                    console.print()
                    console.print("  ✅ Answer limit: unlimited")

                # Minimum Answers Before Voting
                console.print()
                console.print(
                    "  [dim]Min Answers Before Voting: Require answers before allowing votes[/dim]",
                )
                console.print(
                    "  [dim]• Forces agents to deliberate before converging[/dim]",
                )
                console.print(
                    "  [dim]• Useful with 'strict' voting to ensure quality answers[/dim]",
                )
                console.print()

                # Answer Novelty Requirement
                console.print()
                console.print(
                    "  [dim]Answer Novelty: Controls how different new answers must be[/dim]",
                )
                console.print(
                    "  [dim]• L: Lenient - No similarity checks (default, fastest)[/dim]",
                )
                console.print(
                    "  [dim]• B: Balanced - Reject if >70% overlap (prevents rephrasing)[/dim]",
                )
                console.print(
                    "  [dim]• S: Strict - Reject if >50% overlap (requires new approaches)[/dim]",
                )
                console.print()

                novelty_input = Prompt.ask(
                    "  [prompt]Answer novelty requirement[/prompt]",
                    choices=["l", "b", "s"],
                    default="l",
                )

                # Map input to full value
                novelty_map = {"l": "lenient", "b": "balanced", "s": "strict"}
                novelty_choice = novelty_map[novelty_input]

                orchestrator_config["answer_novelty_requirement"] = novelty_choice
                console.print()
                console.print(
                    f"  ✅ Answer novelty requirement set to: {novelty_choice}",
                )

            return agents, orchestrator_config

        except (KeyboardInterrupt, EOFError):
            raise
        except Exception as e:
            console.print(f"[error]❌ Error configuring orchestrator: {e}[/error]")
            console.print("[info]Returning agents with basic configuration...[/info]")
            return agents, {}

    def review_and_save(
        self,
        agents: list[dict],
        orchestrator_config: dict,
    ) -> str | None:
        """Review configuration and save to file with error handling."""
        try:
            # Review header
            review_panel = Panel(
                "[bold green]✅  Review & Save Configuration[/bold green]",
                border_style="green",
                padding=(0, 2),
                width=80,
            )
            console.print(review_panel)
            console.print()

            # Build final config
            self.config["agents"] = agents
            if orchestrator_config:
                self.config["orchestrator"] = orchestrator_config

            # Display configuration
            try:
                yaml_content = yaml.dump(
                    self.config,
                    default_flow_style=False,
                    sort_keys=False,
                )
                config_panel = Panel(
                    yaml_content,
                    title="[bold cyan]Generated Configuration[/bold cyan]",
                    border_style="green",
                    padding=(1, 2),
                    width=min(console.width - 4, 100),  # Adaptive width, max 100
                )
                console.print(config_panel)
            except Exception as e:
                console.print(f"[warning]⚠️  Could not preview YAML: {e}[/warning]")
                console.print("[info]Proceeding with save...[/info]")

            save_choice = Confirm.ask(
                "\n[prompt]Save this configuration?[/prompt]",
                default=True,
            )
            if save_choice is None:
                raise KeyboardInterrupt  # User cancelled
            if not save_choice:
                console.print("[info]Configuration not saved.[/info]")
                return None

            # Determine save location
            if self.default_mode:
                # First-run mode: save to ~/.config/massgen/config.yaml
                config_dir = Path.home() / ".config/massgen"
                config_dir.mkdir(parents=True, exist_ok=True)
                filepath = config_dir / "config.yaml"

                # If file exists, ask to overwrite
                if filepath.exists():
                    if not Confirm.ask(
                        "\n[yellow]⚠️  Default config already exists. Overwrite?[/yellow]",
                        default=True,
                    ):
                        console.print("[info]Configuration not saved.[/info]")
                        return None

                # Save the file
                with open(filepath, "w") as f:
                    yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)

                console.print(
                    f"\n✅ [success]Configuration saved to: {filepath}[/success]",
                )
                return str(filepath)

            # File saving loop with rename option (standard mode)
            default_name = "my_massgen_config.yaml"
            filename = None

            # Ask where to save
            console.print("\nWhere would you like to save the config?")
            console.print("  [1] Current directory (default)")
            console.print("  [2] MassGen config directory (~/.config/massgen/agents/)")

            save_location = Prompt.ask(
                "[prompt]Choose location[/prompt]",
                choices=["1", "2"],
                default="1",
            )

            # Determine save directory
            save_dir = None
            if save_location == "2":
                # Save to ~/.config/massgen/agents/
                save_dir = Path.home() / ".config/massgen/agents"
                save_dir.mkdir(parents=True, exist_ok=True)
                default_name = str(save_dir / "my_massgen_config.yaml")

            while True:
                try:
                    # Get filename with validation
                    if filename is None:
                        filename = Prompt.ask(
                            "[prompt]Config filename[/prompt]",
                            default=default_name,
                        )

                    if not filename:
                        console.print(
                            "[warning]⚠️  Empty filename, using default.[/warning]",
                        )
                        filename = default_name

                    if not filename.endswith(".yaml"):
                        filename += ".yaml"

                    # Create filepath - if save_dir is set and filename is not absolute, join them
                    filepath = Path(filename)
                    if save_dir and not filepath.is_absolute():
                        filepath = save_dir / filepath

                    # Check if file exists
                    if filepath.exists():
                        console.print(
                            f"\n[yellow]⚠️  File '{filename}' already exists![/yellow]",
                        )
                        console.print("\nWhat would you like to do?")
                        console.print("  1. Rename (enter a new filename)")
                        console.print("  2. Overwrite (replace existing file)")
                        console.print("  3. Cancel (don't save)")

                        choice = Prompt.ask(
                            "\n[prompt]Choose an option[/prompt]",
                            choices=["1", "2", "3"],
                            default="1",
                        )

                        if choice == "1":
                            # Ask for new filename
                            filename = Prompt.ask(
                                "[prompt]Enter new filename[/prompt]",
                                default=f"config_{Path(filename).stem}.yaml",
                            )
                            continue  # Loop back to check new filename
                        elif choice == "2":
                            # User chose to overwrite
                            pass  # Continue to save
                        else:  # choice == "3"
                            console.print("[info]Save cancelled.[/info]")
                            return None

                    # Save the file
                    with open(filepath, "w") as f:
                        yaml.dump(
                            self.config,
                            f,
                            default_flow_style=False,
                            sort_keys=False,
                        )

                    console.print(
                        f"\n✅ [success]Configuration saved to: {filepath.absolute()}[/success]",
                    )
                    return str(filepath)

                except PermissionError:
                    console.print(
                        f"[error]❌ Permission denied: Cannot write to {filename}[/error]",
                    )
                    console.print(
                        "[info]Would you like to try a different filename?[/info]",
                    )
                    if Confirm.ask("[prompt]Try again?[/prompt]", default=True):
                        filename = None  # Reset to ask again
                        continue
                    else:
                        return None
                except OSError as e:
                    console.print(f"[error]❌ OS error saving file: {e}[/error]")
                    console.print(
                        "[info]Would you like to try a different filename?[/info]",
                    )
                    if Confirm.ask("[prompt]Try again?[/prompt]", default=True):
                        filename = None  # Reset to ask again
                        continue
                    else:
                        return None
                except Exception as e:
                    console.print(
                        f"[error]❌ Unexpected error saving file: {e}[/error]",
                    )
                    return None

        except (KeyboardInterrupt, EOFError):
            console.print("\n[info]Save cancelled by user.[/info]")
            return None
        except Exception as e:
            console.print(f"[error]❌ Error in review and save: {e}[/error]")
            return None

    def run(self) -> tuple | None:
        """Run the interactive configuration builder with comprehensive error handling."""
        try:
            self.show_banner()

            # Detect API keys with error handling
            try:
                api_keys = self.detect_api_keys()
            except Exception as e:
                console.print(f"[error]❌ Failed to detect API keys: {e}[/error]")
                api_keys = {}

            # Check if any API keys are available
            # Note: api_keys includes local models (vLLM, etc.) which are always True
            if not any(api_keys.values()):
                # No providers available at all (no API keys, no local models, no Claude Code)
                console.print(
                    "[yellow]⚠️  No API keys or local models detected[/yellow]\n",
                )
                console.print("[dim]MassGen needs at least one of:[/dim]")
                console.print(
                    "[dim]  • API keys for cloud providers (OpenAI, Anthropic, Google, etc.)[/dim]",
                )
                console.print("[dim]  • Local models (vLLM, Ollama, etc.)[/dim]")
                console.print("[dim]  • Claude Code with 'claude login'[/dim]\n")

                setup_choice = Confirm.ask(
                    "[prompt]Would you like to set up API keys now (interactive)?[/prompt]",
                    default=True,
                )

                if setup_choice is None:
                    raise KeyboardInterrupt

                if setup_choice:
                    # Run interactive setup
                    api_keys = self.interactive_api_key_setup()

                    # Check if setup was successful
                    if not any(api_keys.values()):
                        console.print(
                            "\n[error]❌ No API keys were configured.[/error]",
                        )
                        console.print("\n[dim]Alternatives to API keys:[/dim]")
                        console.print(
                            "[dim]  • Set up local models (vLLM, Ollama)[/dim]",
                        )
                        console.print(
                            "[dim]  • Use Claude Code with 'claude login'[/dim]",
                        )
                        console.print(
                            "[dim]  • Manually create .env file: ~/.massgen/.env or ./.env[/dim]\n",
                        )
                        return None
                else:
                    # User declined interactive setup
                    console.print(
                        "\n[info]To use MassGen, you need at least one provider.[/info]",
                    )
                    console.print("\n[cyan]Option 1: API Keys[/cyan]")
                    console.print("  Create .env file with one or more:")
                    for provider_id, provider_info in self.PROVIDERS.items():
                        if provider_info.get("env_var"):
                            console.print(f"    • {provider_info['env_var']}")
                    console.print("\n[cyan]Option 2: Local Models[/cyan]")
                    console.print("  • Set up vLLM, Ollama, or other local inference")
                    console.print("\n[cyan]Option 3: Claude Code[/cyan]")
                    console.print("  • Run 'claude login' in your terminal")
                    console.print(
                        "\n[dim]Run 'massgen --init' anytime to restart this wizard[/dim]\n",
                    )
                    return None

            try:
                # Step 1: Select use case
                use_case = self.select_use_case()
                if not use_case:
                    console.print("[warning]⚠️  No use case selected.[/warning]")
                    return None

                # Handle special case: user wants to browse existing configs
                if use_case == "__browse_existing__":
                    console.print("\n[cyan]Opening config selector...[/cyan]\n")
                    # Import here to avoid circular dependency
                    from .cli import interactive_config_selector

                    selected_config = interactive_config_selector()
                    if selected_config:
                        console.print(
                            f"\n[green]✓ Selected config: {selected_config}[/green]\n",
                        )
                        # Return the selected config as if it was created
                        return (selected_config, None)
                    else:
                        console.print("\n[yellow]⚠️  No config selected[/yellow]\n")
                        return None

                # Step 2: Configure agents
                agents = self.configure_agents(use_case, api_keys)
                if not agents:
                    console.print("[error]❌ No agents configured.[/error]")
                    return None

                # Step 3: Configure tools
                try:
                    agents, orchestrator_config = self.configure_tools(use_case, agents)
                except Exception as e:
                    console.print(f"[warning]⚠️  Error configuring tools: {e}[/warning]")
                    console.print("[info]Continuing with basic configuration...[/info]")
                    orchestrator_config = {}

                # Step 4: Review and save
                filepath = self.review_and_save(agents, orchestrator_config)

                if filepath:
                    # In default_mode (first-run), skip "Run now?" and go straight to interactive mode
                    if self.default_mode:
                        # Config already saved by review_and_save(), just return to launch interactive mode
                        return (filepath, None)

                    # In regular --init mode, ask if user wants to run now
                    run_choice = Confirm.ask(
                        "\n[prompt]Run MassGen with this configuration now?[/prompt]",
                        default=True,
                    )
                    if run_choice is None:
                        raise KeyboardInterrupt  # User cancelled
                    if run_choice:
                        question = Prompt.ask("\n[prompt]Enter your question[/prompt]")
                        if question is None:
                            raise KeyboardInterrupt  # User cancelled
                        if question:
                            console.print(
                                f'\n[info]Running: massgen --config {filepath} "{question}"[/info]\n',
                            )
                            return (filepath, question)
                        else:
                            console.print("[warning]⚠️  No question provided.[/warning]")
                            return (filepath, None)

                return (filepath, None) if filepath else None

            except (KeyboardInterrupt, EOFError):
                console.print(
                    "\n\n[bold yellow]Configuration cancelled by user[/bold yellow]",
                )
                console.print(
                    "\n[dim]You can run [bold]massgen --init[/bold] anytime to restart.[/dim]\n",
                )
                return None
            except ValueError as e:
                console.print(f"\n[error]❌ Configuration error: {str(e)}[/error]")
                console.print("[info]Please check your inputs and try again.[/info]")
                return None
            except Exception as e:
                console.print(
                    f"\n[error]❌ Unexpected error during configuration: {str(e)}[/error]",
                )
                console.print(f"[info]Error type: {type(e).__name__}[/info]")
                return None

        except KeyboardInterrupt:
            console.print(
                "\n\n[bold yellow]Configuration cancelled by user[/bold yellow]",
            )
            console.print(
                "\n[dim]You can run [bold]massgen --init[/bold] anytime to restart the configuration wizard.[/dim]\n",
            )
            return None
        except EOFError:
            console.print("\n\n[bold yellow]Configuration cancelled[/bold yellow]")
            console.print(
                "\n[dim]You can run [bold]massgen --init[/bold] anytime to restart the configuration wizard.[/dim]\n",
            )
            return None
        except Exception as e:
            console.print(f"\n[error]❌ Fatal error: {str(e)}[/error]")
            console.print("[info]Please report this issue if it persists.[/info]")
            return None

    def generate_config_programmatic(
        self,
        output_path: str,
        num_agents: int = 2,
        backend_type: str = None,
        model: str = None,
        use_docker: bool = False,
        context_path: str | None = None,
    ) -> bool:
        """Generate config file programmatically without user interaction.

        Args:
            output_path: Where to save the config file
            num_agents: Number of agents (1-10)
            backend_type: Backend provider (must have API key)
            model: Model name
            use_docker: Whether to enable Docker execution
            context_path: Optional path to add as context

        Returns:
            True if successful

        Raises:
            ValueError: If backend_type/model missing or API key unavailable
        """
        if not backend_type or not model:
            raise ValueError("backend_type and model are required")

        # Validate num_agents
        if num_agents < 1 or num_agents > 10:
            raise ValueError("Number of agents must be between 1 and 10")

        # Check API key availability
        api_keys = self.detect_api_keys()
        if not api_keys.get(backend_type, False):
            available = [p for p, has_key in api_keys.items() if has_key]
            raise ValueError(
                f"Backend '{backend_type}' not available (no API key found). " f"Available backends: {', '.join(available) if available else 'none'}",
            )

        # Build agents config
        provider_info = self.PROVIDERS.get(backend_type, {})
        agents_config = []
        for i in range(num_agents):
            chr(ord("a") + i) if i < 26 else str(i)
            agents_config.append(
                {
                    "id": f"{backend_type.split('.')[-1]}-{model.split('-')[-1]}{i + 1}",
                    "type": provider_info.get("type", backend_type),
                    "model": model,
                },
            )

        # Generate full config using existing quickstart logic
        config = self._generate_quickstart_config(
            agents_config,
            context_path=context_path,
            use_docker=use_docker,
        )

        # Save to file
        from pathlib import Path

        import yaml

        output_file = Path(output_path).expanduser().resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            yaml.dump(
                config,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        return True

    def run_quickstart(self, quickstart_config_filename: str | None = None) -> tuple | None:
        """Run simplified quickstart flow - just agents count and backend/model for each.

        This creates a full-featured config with code-based tools, Docker execution,
        orchestration, skills, etc. - all the good defaults. User only needs to specify
        their models.

        Returns:
            Tuple of (filepath, question, interface_choice, install_skills_now) or None if cancelled
        """
        try:
            # Simple banner
            console.clear()
            banner = """[bold cyan]
     ███╗   ███╗ █████╗ ███████╗███████╗ ██████╗ ███████╗███╗   ██╗
     ████╗ ████║██╔══██╗██╔════╝██╔════╝██╔════╝ ██╔════╝████╗  ██║
     ██╔████╔██║███████║███████╗███████╗██║  ███╗█████╗  ██╔██╗ ██║
     ██║╚██╔╝██║██╔══██║╚════██║╚════██║██║   ██║██╔══╝  ██║╚██╗██║
     ██║ ╚═╝ ██║██║  ██║███████║███████║╚██████╔╝███████╗██║ ╚████║
     ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝[/bold cyan]
"""
            console.print(banner)
            console.print(
                "[bold cyan]Quickstart[/bold cyan] - Get running in 30 seconds\n",
            )
            console.print(
                "[dim]Creates a full-featured config with code-based tools, Docker, skills, etc.[/dim]",
            )
            console.print("[dim]You just need to specify your models.[/dim]\n")

            # Initialize tracking for per-agent settings
            agent_tools: dict[str, dict] = {}
            agent_system_messages: dict[str, str] = {}
            coordination_settings: dict[str, Any] = {}

            # Step 1: How many agents?
            num_choices = [
                questionary.Choice("1 agent", value=1),
                questionary.Choice("2 agents", value=2),
                questionary.Choice("3 agents (recommended)", value=3),
                questionary.Choice("4 agents", value=4),
                questionary.Choice("5 agents", value=5),
            ]

            num_agents = questionary.select(
                "How many agents?",
                choices=num_choices,
                default=3,
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan bold"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if num_agents is None:
                raise KeyboardInterrupt

            # Step 2: Configure each agent's backend and model
            agents_config = []

            # Get available providers (exclude generic backends)
            api_keys = self.detect_api_keys()
            excluded_generic_backends = ["chatcompletion", "inference"]
            available_providers = sort_quickstart_provider_ids(
                [p for p, has_key in api_keys.items() if has_key and p not in excluded_generic_backends],
            )

            if not available_providers:
                console.print("\n[error]❌ No providers with API keys found.[/error]")
                console.print(
                    "[dim]Set API keys in ~/.massgen/.env or run 'massgen --setup'[/dim]\n",
                )
                return None

            # For multiple agents, ask if same or different providers
            use_same_provider = False
            if num_agents > 1:
                setup_mode = questionary.select(
                    "Setup mode:",
                    choices=[
                        questionary.Choice(
                            "Same backend/model for all agents",
                            value="same",
                        ),
                        questionary.Choice(
                            "Different backends per agent",
                            value="different",
                        ),
                    ],
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if setup_mode is None:
                    raise KeyboardInterrupt

                use_same_provider = setup_mode == "same"

            if use_same_provider:
                # Configure once, apply to all agents
                console.print(f"\n[bold cyan]All {num_agents} agents[/bold cyan]")

                # Select provider
                provider_choices = [
                    questionary.Choice(
                        self.PROVIDERS.get(pid, {}).get("name", pid),
                        value=pid,
                    )
                    for pid in available_providers
                ]

                provider_id = questionary.select(
                    "  Backend:",
                    choices=provider_choices,
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if provider_id is None:
                    raise KeyboardInterrupt

                # Select model
                provider_info = self.PROVIDERS.get(provider_id, {})
                models = provider_info.get("models", ["default"])
                default_model = provider_info.get(
                    "default_model",
                    models[0] if models else None,
                )

                model = self.select_model_smart(
                    provider_id,
                    models,
                    current_model=default_model,
                    prompt="  Model:",
                )

                if model is None:
                    raise KeyboardInterrupt

                reasoning_effort = None
                reasoning_profile = self.get_quickstart_reasoning_profile(
                    provider_info.get("type", provider_id),
                    model,
                )
                if reasoning_profile:
                    console.print(f"\n[dim]  {reasoning_profile['description']}[/dim]")
                    reasoning_effort = questionary.select(
                        "  Reasoning effort:",
                        choices=[questionary.Choice(label, value=value) for label, value in reasoning_profile["choices"]],
                        default=reasoning_profile["default_effort"],
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()
                    if reasoning_effort is None:
                        raise KeyboardInterrupt

                # Per-agent options (applied to all agents in same-provider mode)
                provider_caps = _get_provider_capabilities(provider_id)

                # Web search toggle (if provider supports it)
                enable_web_search = False
                if provider_caps["web_search"]:
                    enable_web_search = questionary.confirm(
                        "  Enable web search for all agents?",
                        default=False,
                        style=questionary.Style([("question", "fg:cyan bold")]),
                    ).ask()
                    if enable_web_search is None:
                        raise KeyboardInterrupt

                # System message (optional)
                console.print(
                    "\n[dim]  System message (optional) - custom instructions for agents[/dim]",
                )
                sys_msg_mode = questionary.select(
                    "  System messages:",
                    choices=[
                        questionary.Choice("Skip (no custom instructions)", value="skip"),
                        questionary.Choice("Same message for all agents", value="same"),
                        questionary.Choice("Different message per agent", value="different"),
                    ],
                    default="skip",
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if sys_msg_mode is None:
                    raise KeyboardInterrupt

                # Collect system messages based on mode
                per_agent_system_msgs: dict[str, str] = {}

                if sys_msg_mode == "same":
                    system_msg = questionary.text(
                        "  System message for all agents:",
                        default="",
                    ).ask()
                    if system_msg is None:
                        raise KeyboardInterrupt
                    if system_msg.strip():
                        for i in range(num_agents):
                            agent_letter = chr(ord("a") + i)
                            per_agent_system_msgs[f"agent_{agent_letter}"] = system_msg.strip()

                elif sys_msg_mode == "different":
                    for i in range(num_agents):
                        agent_letter = chr(ord("a") + i)
                        agent_id = f"agent_{agent_letter}"
                        console.print(f"\n[dim]  Agent {i + 1} ({agent_letter}):[/dim]")
                        system_msg = questionary.text(
                            "    System message (Enter to skip):",
                            default="",
                        ).ask()
                        if system_msg is None:
                            raise KeyboardInterrupt
                        if system_msg.strip():
                            per_agent_system_msgs[agent_id] = system_msg.strip()

                # Create all agents with same config
                for i in range(num_agents):
                    agent_letter = chr(ord("a") + i)
                    agent_id = f"agent_{agent_letter}"
                    agent_spec = {
                        "id": agent_id,
                        "type": provider_info.get("type", provider_id),
                        "model": model,
                    }
                    if reasoning_effort:
                        agent_spec["reasoning_effort"] = reasoning_effort
                    agents_config.append(agent_spec)
                    # Track per-agent settings
                    if enable_web_search:
                        agent_tools[agent_id] = {"enable_web_search": True}
                    if agent_id in per_agent_system_msgs:
                        agent_system_messages[agent_id] = per_agent_system_msgs[agent_id]

            else:
                # Configure each agent individually
                for i in range(num_agents):
                    agent_letter = chr(ord("a") + i)
                    console.print(
                        f"\n[bold cyan]Agent {i + 1} ({agent_letter})[/bold cyan]",
                    )

                    # Select provider
                    provider_choices = [
                        questionary.Choice(
                            self.PROVIDERS.get(pid, {}).get("name", pid),
                            value=pid,
                        )
                        for pid in available_providers
                    ]

                    provider_id = questionary.select(
                        "  Backend:",
                        choices=provider_choices,
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()

                    if provider_id is None:
                        raise KeyboardInterrupt

                    # Select model
                    provider_info = self.PROVIDERS.get(provider_id, {})
                    models = provider_info.get("models", ["default"])
                    default_model = provider_info.get(
                        "default_model",
                        models[0] if models else None,
                    )

                    model = self.select_model_smart(
                        provider_id,
                        models,
                        current_model=default_model,
                        prompt="  Model:",
                    )

                    if model is None:
                        raise KeyboardInterrupt

                    agent_id = f"agent_{agent_letter}"

                    reasoning_effort = None
                    reasoning_profile = self.get_quickstart_reasoning_profile(
                        provider_info.get("type", provider_id),
                        model,
                    )
                    if reasoning_profile:
                        console.print(f"\n[dim]    {reasoning_profile['description']}[/dim]")
                        reasoning_effort = questionary.select(
                            "    Reasoning effort:",
                            choices=[questionary.Choice(label, value=value) for label, value in reasoning_profile["choices"]],
                            default=reasoning_profile["default_effort"],
                            style=questionary.Style(
                                [
                                    ("selected", "fg:cyan bold"),
                                    ("pointer", "fg:cyan bold"),
                                    ("highlighted", "fg:cyan"),
                                ],
                            ),
                            use_arrow_keys=True,
                        ).ask()
                        if reasoning_effort is None:
                            raise KeyboardInterrupt

                    # Per-agent options
                    provider_caps = _get_provider_capabilities(provider_id)

                    # Web search toggle (if provider supports it)
                    enable_web_search = False
                    if provider_caps["web_search"]:
                        enable_web_search = questionary.confirm(
                            "    Enable web search?",
                            default=False,
                            style=questionary.Style([("question", "fg:cyan bold")]),
                        ).ask()
                        if enable_web_search is None:
                            raise KeyboardInterrupt

                    # System message (optional)
                    console.print(
                        "[dim]    System message (optional) - custom instructions for this agent[/dim]",
                    )
                    system_msg = questionary.text(
                        "    System message (press Enter to skip):",
                        default="",
                    ).ask()
                    if system_msg is None:
                        raise KeyboardInterrupt

                    agent_spec = {
                        "id": agent_id,
                        "type": provider_info.get("type", provider_id),
                        "model": model,
                    }
                    if reasoning_effort:
                        agent_spec["reasoning_effort"] = reasoning_effort
                    agents_config.append(agent_spec)

                    # Track per-agent settings
                    if enable_web_search:
                        agent_tools[agent_id] = {"enable_web_search": True}
                    if system_msg and system_msg.strip():
                        agent_system_messages[agent_id] = system_msg.strip()

            # Step 3: Check Docker availability and ask about execution mode
            # Import check function from cli
            from .cli import check_docker_available

            docker_available = check_docker_available()

            if docker_available:
                console.print("\n[bold cyan]Execution Mode[/bold cyan]")
                console.print(
                    "[dim]Docker (recommended): Full 'code mode' with command-line tools, skills, package installation,[/dim]",
                )
                console.print(
                    "[dim]  and isolated execution. Agents can run any code safely in containers.[/dim]",
                )
                console.print(
                    "[dim]Local: More restricted - agents can create/edit files but no command execution.[/dim]\n",
                )

                use_docker = questionary.confirm(
                    "Use Docker for code execution?",
                    default=True,
                    style=questionary.Style(
                        [
                            ("question", "fg:cyan bold"),
                        ],
                    ),
                ).ask()

                if use_docker is None:
                    raise KeyboardInterrupt
            else:
                console.print("\n[bold cyan]Execution Mode[/bold cyan]")
                console.print(
                    "[yellow]⚠️  Docker images not found. Using local mode.[/yellow]",
                )
                console.print(
                    "[dim]Local mode: Agents can create/edit files but no command execution.[/dim]",
                )
                console.print(
                    "[dim]To enable Docker mode, run: massgen --setup-docker[/dim]\n",
                )
                use_docker = False

            install_skills_now = False
            if use_docker:
                console.print("\n[bold cyan]Skills Setup[/bold cyan]")
                console.print(
                    "[dim]Install quickstart skill packages now?[/dim]",
                )
                console.print(
                    "[dim]Includes openskills + Anthropic/OpenAI/Vercel collections, Agent Browser skill, Remotion, and Crawl4AI.[/dim]\n",
                )
                install_skills_now = questionary.confirm(
                    "Install missing quickstart skill packages now?",
                    default=True,
                    style=questionary.Style([("question", "fg:cyan bold")]),
                ).ask()

                if install_skills_now is None:
                    raise KeyboardInterrupt

            # Step 3b: Code Execution toggle (only when Docker is NOT enabled)
            # Providers like OpenAI/Claude have cloud-based code execution sandboxes
            if not use_docker:
                # Check if any agent's provider supports code execution
                agents_with_code_exec = []
                for agent in agents_config:
                    caps = _get_provider_capabilities(agent["type"])
                    if caps["code_execution"]:
                        agents_with_code_exec.append(agent)

                if agents_with_code_exec:
                    console.print("\n[bold cyan]Provider Code Execution[/bold cyan]")
                    console.print(
                        "[dim]Some providers offer cloud-based code execution sandboxes.[/dim]",
                    )
                    console.print(
                        "[dim]This runs code in the provider's cloud, not locally.[/dim]\n",
                    )

                    enable_code_exec = questionary.confirm(
                        "Enable provider code execution for supported agents?",
                        default=False,
                        style=questionary.Style([("question", "fg:cyan bold")]),
                    ).ask()

                    if enable_code_exec is None:
                        raise KeyboardInterrupt

                    if enable_code_exec:
                        for agent in agents_with_code_exec:
                            agent_id = agent["id"]
                            if agent_id not in agent_tools:
                                agent_tools[agent_id] = {}
                            agent_tools[agent_id]["enable_code_execution"] = True

            # Step 4: Ask about context path (to avoid runtime prompt)
            console.print("\n[bold cyan]Context Path[/bold cyan]")
            console.print(
                "[dim]Context paths give agents read/write access to your project files.[/dim]",
            )
            console.print(
                "[dim]Without one, agents can only work in their isolated workspaces.[/dim]\n",
            )
            cwd = str(Path.cwd())
            console.print(f"[dim]Current directory: {cwd}[/dim]")

            add_context = questionary.confirm(
                "Add current directory as context path?",
                default=True,
                style=questionary.Style(
                    [
                        ("question", "fg:cyan bold"),
                    ],
                ),
            ).ask()

            if add_context is None:
                raise KeyboardInterrupt

            context_path = cwd if add_context else None

            # Step 5: Coordination settings (only for multi-agent)
            if num_agents > 1:
                console.print("\n[bold cyan]Coordination Mode[/bold cyan]")
                console.print(
                    "[dim]Parallel voting is the default. Decomposition assigns subtasks and a presenter.[/dim]",
                )

                coordination_mode = questionary.select(
                    "Coordination mode:",
                    choices=[
                        questionary.Choice(
                            "Parallel voting (default)",
                            value="voting",
                        ),
                        questionary.Choice(
                            "Decomposition (subtasks + presenter)",
                            value="decomposition",
                        ),
                    ],
                    default="voting",
                    style=questionary.Style(
                        [
                            ("selected", "fg:cyan bold"),
                            ("pointer", "fg:cyan bold"),
                            ("highlighted", "fg:cyan"),
                        ],
                    ),
                    use_arrow_keys=True,
                ).ask()

                if coordination_mode is None:
                    raise KeyboardInterrupt

                if coordination_mode == "decomposition":
                    coordination_settings["coordination_mode"] = "decomposition"

                    presenter_choices = [questionary.Choice(agent["id"], value=agent["id"]) for agent in agents_config]
                    default_presenter = agents_config[-1]["id"]

                    presenter_agent = questionary.select(
                        "Presenter agent (final synthesis):",
                        choices=presenter_choices,
                        default=default_presenter,
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()

                    if presenter_agent is None:
                        raise KeyboardInterrupt

                    coordination_settings["presenter_agent"] = presenter_agent

                    # Recommended decomposition defaults:
                    # - lower per-agent consecutive cap (2-3)
                    # - cumulative global cap for deterministic team budget
                    coordination_settings["max_new_answers_per_agent"] = 2
                    coordination_settings["max_new_answers_global"] = max(3, num_agents * 3)
                    coordination_settings["answer_novelty_requirement"] = "balanced"

                    console.print(
                        "\n[dim]Using recommended decomposition defaults:[/dim]",
                    )
                    console.print(
                        f"[dim]- max_new_answers_per_agent: {coordination_settings['max_new_answers_per_agent']} (recommended 2-3)[/dim]",
                    )
                    console.print(
                        f"[dim]- max_new_answers_global: {coordination_settings['max_new_answers_global']} (team-wide cumulative)[/dim]",
                    )
                    console.print(
                        f"[dim]- answer_novelty_requirement: {coordination_settings['answer_novelty_requirement']}[/dim]",
                    )

                # Subagents section (separate from coordination tuning)
                console.print("\n[bold cyan]Subagents[/bold cyan]")
                console.print(
                    "[dim]Subagents allow agents to spawn parallel child processes for independent tasks.[/dim]",
                )
                enable_subagents = questionary.confirm(
                    "Enable subagents?",
                    default=False,
                    style=questionary.Style([("question", "fg:cyan bold")]),
                ).ask()

                if enable_subagents is None:
                    raise KeyboardInterrupt

                if enable_subagents:
                    coordination_settings["enable_subagents"] = True

                    # Ask for subagent model configuration
                    console.print(
                        "\n[dim]Subagents can use the same model as parent agents or different ones.[/dim]",
                    )
                    subagent_model_choice = questionary.select(
                        "Subagent model:",
                        choices=[
                            questionary.Choice("Same as parent agents", value="inherit"),
                            questionary.Choice("Choose different model(s)", value="custom"),
                        ],
                        style=questionary.Style([("question", "fg:cyan bold")]),
                    ).ask()

                    if subagent_model_choice is None:
                        raise KeyboardInterrupt

                    if subagent_model_choice == "custom":
                        # Support multiple subagent backends
                        subagent_agents = []

                        while True:
                            agent_num = len(subagent_agents) + 1
                            console.print(f"\n[bold cyan]Subagent Backend {agent_num}[/bold cyan]")

                            # Only show providers with API keys
                            provider_choices = [
                                questionary.Choice(
                                    self.PROVIDERS.get(pid, {}).get("name", pid),
                                    value=pid,
                                )
                                for pid in available_providers
                            ]

                            subagent_provider = questionary.select(
                                "  Backend:",
                                choices=provider_choices,
                                style=questionary.Style(
                                    [
                                        ("selected", "fg:cyan bold"),
                                        ("pointer", "fg:cyan bold"),
                                        ("highlighted", "fg:cyan"),
                                    ],
                                ),
                                use_arrow_keys=True,
                            ).ask()

                            if subagent_provider is None:
                                raise KeyboardInterrupt

                            # Select model for subagents
                            subagent_provider_info = self.PROVIDERS.get(subagent_provider, {})
                            subagent_models = subagent_provider_info.get("models", ["default"])
                            subagent_default_model = subagent_provider_info.get(
                                "default_model",
                                subagent_models[0] if subagent_models else None,
                            )

                            subagent_model = self.select_model_smart(
                                subagent_provider,
                                subagent_models,
                                current_model=subagent_default_model,
                                prompt="  Model:",
                            )

                            if subagent_model is None:
                                raise KeyboardInterrupt

                            # Build this subagent config
                            subagent_config = {
                                "backend": {
                                    "type": subagent_provider_info.get("type", subagent_provider),
                                    "model": subagent_model,
                                },
                            }

                            # Add base_url for providers that need it
                            if subagent_provider_info.get("base_url"):
                                subagent_config["backend"]["base_url"] = subagent_provider_info["base_url"]

                            subagent_agents.append(subagent_config)
                            console.print(f"  [green]✓ Added: {subagent_model}[/green]")

                            # Ask if they want to add another
                            add_another = questionary.confirm(
                                "Add another subagent backend?",
                                default=False,
                                style=questionary.Style([("question", "fg:cyan bold")]),
                            ).ask()

                            if add_another is None:
                                raise KeyboardInterrupt

                            if not add_another:
                                break

                        # Store all subagent configs
                        coordination_settings["subagent_orchestrator"] = {
                            "enabled": True,
                            "agents": subagent_agents,
                        }

                        if len(subagent_agents) > 1:
                            console.print(f"\n  [dim]Configured {len(subagent_agents)} subagent backends[/dim]")

                # Coordination tuning section (optional, hidden by default)
                console.print("\n[bold cyan]Coordination Tuning[/bold cyan]")
                if coordination_mode == "decomposition":
                    console.print(
                        "[dim]Fine-tune decomposition defaults (presenter mode, novelty, and answer caps).[/dim]",
                    )
                    console.print(
                        "[dim]Recommended decomposition defaults are already set and usually need no changes.[/dim]",
                    )
                else:
                    console.print(
                        "[dim]Fine-tune voting sensitivity, answer novelty, and limits.[/dim]",
                    )
                    console.print("[dim]Default settings (lenient) work well for most tasks.[/dim]")

                customize_coordination = questionary.confirm(
                    "Customize coordination settings?",
                    default=False,
                    style=questionary.Style([("question", "fg:cyan bold")]),
                ).ask()

                if customize_coordination is None:
                    raise KeyboardInterrupt

                if customize_coordination:
                    # Voting sensitivity (still relevant for voting-style coordination phases)
                    voting_choices = [
                        questionary.Choice(
                            "Lenient - Agents accept answers more easily",
                            value="lenient",
                        ),
                        questionary.Choice(
                            "Balanced - Moderate scrutiny of answers",
                            value="balanced",
                        ),
                        questionary.Choice(
                            "Strict - Agents are highly critical",
                            value="strict",
                        ),
                    ]

                    voting_default = "lenient"
                    voting_sensitivity = questionary.select(
                        "Voting Sensitivity:",
                        choices=voting_choices,
                        default=voting_default,
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()

                    if voting_sensitivity is None:
                        raise KeyboardInterrupt

                    coordination_settings["voting_sensitivity"] = voting_sensitivity

                    # Answer novelty requirement
                    novelty_choices = [
                        questionary.Choice(
                            "Lenient - Similar answers are accepted",
                            value="lenient",
                        ),
                        questionary.Choice(
                            "Balanced - Some differentiation required",
                            value="balanced",
                        ),
                        questionary.Choice(
                            "Strict - Answers must be substantially different",
                            value="strict",
                        ),
                    ]

                    novelty_default = coordination_settings.get("answer_novelty_requirement", "lenient")
                    answer_novelty = questionary.select(
                        "Answer Novelty Requirement:",
                        choices=novelty_choices,
                        default=novelty_default,
                        style=questionary.Style(
                            [
                                ("selected", "fg:cyan bold"),
                                ("pointer", "fg:cyan bold"),
                                ("highlighted", "fg:cyan"),
                            ],
                        ),
                        use_arrow_keys=True,
                    ).ask()

                    if answer_novelty is None:
                        raise KeyboardInterrupt

                    coordination_settings["answer_novelty_requirement"] = answer_novelty

                    # Max answers per agent
                    max_answers_default = coordination_settings.get("max_new_answers_per_agent")
                    max_answers_input = questionary.text(
                        "Max answers per agent (leave empty for unlimited):",
                        default=str(max_answers_default) if max_answers_default else "",
                        style=questionary.Style(
                            [
                                ("question", "fg:cyan bold"),
                            ],
                        ),
                    ).ask()

                    if max_answers_input is None:
                        raise KeyboardInterrupt

                    if max_answers_input.strip():
                        try:
                            max_answers = int(max_answers_input)
                            if max_answers > 0:
                                coordination_settings["max_new_answers_per_agent"] = max_answers
                        except ValueError:
                            pass  # Ignore invalid input, use unlimited

                    if coordination_mode == "decomposition":
                        # Team-wide cumulative cap gives deterministic upper bound
                        max_global_default = coordination_settings.get(
                            "max_new_answers_global",
                            max(3, num_agents * 3),
                        )
                        max_global_input = questionary.text(
                            "Max answers globally across all agents (leave empty for unlimited):",
                            default=str(max_global_default) if max_global_default else "",
                            style=questionary.Style(
                                [
                                    ("question", "fg:cyan bold"),
                                ],
                            ),
                        ).ask()

                        if max_global_input is None:
                            raise KeyboardInterrupt

                        if max_global_input.strip():
                            try:
                                max_global = int(max_global_input)
                                if max_global > 0:
                                    coordination_settings["max_new_answers_global"] = max_global
                            except ValueError:
                                pass  # Ignore invalid input, keep prior/default value

                # Persona Generation (multi-agent only)
                console.print("\n[bold cyan]Persona Generation[/bold cyan]")
                console.print(
                    "[dim]Auto-generate diverse approaches for each agent to explore " "different regions of the solution space.[/dim]\n",
                )

                enable_personas = questionary.confirm(
                    "Enable automatic persona generation?",
                    default=True,
                    style=questionary.Style(
                        [
                            ("question", "fg:cyan bold"),
                        ],
                    ),
                ).ask()

                if enable_personas is None:
                    raise KeyboardInterrupt

                if enable_personas:
                    # Ask for diversity mode
                    diversity_mode = questionary.select(
                        "Diversity mode:",
                        choices=[
                            questionary.Choice(
                                "Perspective - Different values/priorities (e.g., simplicity vs robustness)",
                                value="perspective",
                            ),
                            questionary.Choice(
                                "Implementation - Different solution types (e.g., minimal vs feature-rich)",
                                value="implementation",
                            ),
                        ],
                        default="perspective",
                    ).ask()

                    if diversity_mode is None:
                        raise KeyboardInterrupt

                    coordination_settings["persona_generator"] = {
                        "enabled": True,
                        "diversity_mode": diversity_mode,
                    }

            # Step 6: Generate the full config
            console.print("\n[dim]Generating configuration...[/dim]")

            config = self._generate_quickstart_config(
                agents_config,
                context_path=context_path,
                use_docker=use_docker,
                agent_tools=agent_tools,
                agent_system_messages=agent_system_messages,
                coordination_settings=coordination_settings,
            )

            # Step 4: Save the config
            # When a quickstart filename is provided via CLI, save under .massgen/.
            if quickstart_config_filename:
                filepath = build_quickstart_config_path(
                    location="project",
                    filename=quickstart_config_filename,
                )
            else:
                filepath = build_quickstart_config_path(
                    location="global",
                    filename=DEFAULT_QUICKSTART_CONFIG_FILENAME,
                )
            filepath.parent.mkdir(parents=True, exist_ok=True)

            with open(filepath, "w") as f:
                yaml.dump(
                    config,
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )

            console.print(f"\n[bold green]✅ Config saved to: {filepath}[/bold green]")

            # Step 6: Ask about interface preference
            console.print("\n[bold cyan]Interface[/bold cyan]")
            console.print("[dim]Terminal: Rich text-based UI in your terminal[/dim]")
            console.print(
                "[dim]Web: Browser-based UI with visual coordination timeline[/dim]\n",
            )

            interface_choice = questionary.select(
                "Launch MassGen with:",
                choices=[
                    questionary.Choice("Terminal (rich display)", value="terminal"),
                    questionary.Choice("Web UI (browser)", value="web"),
                ],
                default="terminal",
                style=questionary.Style(
                    [
                        ("selected", "fg:cyan bold"),
                        ("pointer", "fg:cyan bold"),
                        ("highlighted", "fg:cyan"),
                    ],
                ),
                use_arrow_keys=True,
            ).ask()

            if interface_choice is None:
                raise KeyboardInterrupt

            console.print("[dim]Launching MassGen...[/dim]\n")

            # Offer example prompts to help users get started
            from .cli import show_example_prompts

            example_prompt = show_example_prompts()

            if example_prompt:
                # Return with the selected example prompt as initial question
                return (str(filepath), example_prompt, interface_choice, bool(install_skills_now))
            else:
                # Auto-launch into interactive mode (return empty string to signal interactive mode)
                return (str(filepath), "", interface_choice, bool(install_skills_now))

        except (KeyboardInterrupt, EOFError):
            console.print("\n\n[yellow]Quickstart cancelled[/yellow]\n")
            return None
        except Exception as e:
            console.print(f"\n[error]❌ Error: {e}[/error]")
            return None

    def _generate_quickstart_config(
        self,
        agents_config: list[dict],
        context_path: str | None = None,
        context_paths: list[dict] | None = None,
        use_docker: bool = True,
        agent_tools: dict[str, dict] | None = None,
        agent_system_messages: dict[str, str] | None = None,
        coordination_settings: dict | None = None,
    ) -> dict:
        """Generate a full-featured config from the quickstart agent specifications.

        Args:
            agents_config: List of dicts with 'id', 'type', 'model' for each agent.
                          Optional key: 'reasoning_effort' for GPT-5x reasoning selection.
            context_path: Deprecated. Optional path to add as context path (avoids runtime prompt)
            context_paths: List of context path dicts with 'path' and 'permission' keys.
                          Each entry: {"path": "/path", "permission": "read" or "write"}
            use_docker: Whether to use Docker for code execution (True) or local mode (False)
            agent_tools: Per-agent tool settings dict. Keys are agent IDs, values are dicts
                        with tool settings like {"enable_web_search": True, "enable_code_execution": True}
            agent_system_messages: Per-agent system messages dict. Keys are agent IDs, values are
                                  the custom system message strings
            coordination_settings: Shared coordination settings dict with keys like
                                  'coordination_mode', 'presenter_agent',
                                  'voting_sensitivity', 'answer_novelty_requirement',
                                  'max_new_answers_per_agent', 'max_new_answers_global',
                                  and fairness controls

        Returns:
            Complete configuration dict
        """
        agent_tools = agent_tools or {}
        agent_system_messages = agent_system_messages or {}
        coordination_settings = coordination_settings or {}

        # Base agent template with all the good defaults
        def create_agent_backend(
            agent_type: str,
            model: str,
            reasoning_effort: str | None = None,
            tools: dict | None = None,
        ) -> dict:
            tools = tools or {}
            if use_docker:
                # Full Docker mode with code-based tools, command execution, skills
                backend = {
                    "type": agent_type,
                    "model": model,
                    "cwd": "workspace",
                    # Code-based tools (CodeAct paradigm)
                    "enable_code_based_tools": True,
                    "exclude_file_operation_mcps": True,
                    "enable_mcp_command_line": True,
                    # Docker execution
                    "command_line_execution_mode": "docker",
                    "command_line_docker_image": "ghcr.io/massgen/mcp-runtime-sudo:latest",
                    "command_line_docker_network_mode": "bridge",
                    "command_line_docker_enable_sudo": True,
                    # Docker credentials for API keys
                    "command_line_docker_credentials": {
                        "env_file": ".env",
                        "env_vars_from_file": [
                            "OPENAI_API_KEY",
                            "ANTHROPIC_API_KEY",
                            "GOOGLE_API_KEY",
                            "GEMINI_API_KEY",
                        ],
                    },
                    # Shared tools directory
                    "shared_tools_directory": "shared_tools",
                    # Auto-discover custom tools
                    "auto_discover_custom_tools": True,
                    # Exclude heavy/problematic tools
                    "exclude_custom_tools": [
                        "_computer_use",
                        "_claude_computer_use",
                        "_gemini_computer_use",
                        "_browser_automation",
                    ],
                    # Note: enable_multimodal_tools is set at orchestrator level
                }
            else:
                # Local mode - file operations only, no command execution
                backend = {
                    "type": agent_type,
                    "model": model,
                    "cwd": "workspace",
                    # File operations via MCP (no code execution)
                    "exclude_file_operation_mcps": False,  # Keep file MCPs
                    # Note: enable_multimodal_tools is set at orchestrator level
                }

            # Add base_url for OpenAI-compatible providers (Groq, Cerebras, Together, etc.)
            caps = get_capabilities(agent_type)
            if caps and caps.base_url:
                backend["base_url"] = caps.base_url

            # Add per-agent tool settings (e.g., enable_web_search, enable_code_execution)
            # Only add if the backend supports the capability
            if tools.get("enable_web_search") is not None:
                if caps and "web_search" in caps.supported_capabilities:
                    backend["enable_web_search"] = tools["enable_web_search"]

            if tools.get("enable_code_execution") is not None:
                if caps and "code_execution" in caps.supported_capabilities:
                    # Different backends use different parameter names
                    # OpenAI uses enable_code_interpreter, Claude uses enable_code_execution
                    if agent_type == "openai":
                        backend["enable_code_interpreter"] = tools["enable_code_execution"]
                    else:
                        backend["enable_code_execution"] = tools["enable_code_execution"]

            if reasoning_effort:
                backend["reasoning"] = {
                    "effort": reasoning_effort,
                    "summary": "auto",
                }

            return backend

        # Build agents list
        agents = []
        for i, agent_spec in enumerate(agents_config):
            agent_id = agent_spec["id"]
            agent = {
                "id": agent_id,
                "backend": create_agent_backend(
                    agent_spec["type"],
                    agent_spec["model"],
                    reasoning_effort=agent_spec.get("reasoning_effort"),
                    tools=agent_tools.get(agent_id, {}),
                ),
            }
            # Add system_message if provided (at agent level, not backend level)
            if agent_id in agent_system_messages:
                agent["system_message"] = agent_system_messages[agent_id]
            agents.append(agent)

        # Build orchestrator config
        if use_docker:
            # Full orchestrator config with skills and task planning
            orchestrator_config = {
                "snapshot_storage": "snapshots",
                "agent_temporary_workspace": "temp_workspaces",
                "voting_sensitivity": "checklist_gated",
                "voting_threshold": 3,
                "max_new_answers_per_agent": 5,
                # Fairness defaults (enabled across all coordination modes)
                "fairness_enabled": True,
                "fairness_lead_cap_answers": 2,
                "max_midstream_injections_per_round": 2,
                # Multimodal tools enabled for all agents
                "enable_multimodal_tools": True,
                # Default generation backends (agents can override)
                "image_generation_backend": "openai",  # OpenAI responses image gen
                "video_generation_backend": "openai",  # OpenAI Sora2
                "audio_generation_backend": "openai",  # OpenAI TTS
                "coordination": {
                    "max_orchestration_restarts": 0,  # Disabled pending MAS-268 fix
                    "learning_capture_mode": "verification_and_final_only",
                    "use_skills": True,
                    "skills_directory": ".agent/skills",
                    "enable_agent_task_planning": True,
                    "task_planning_filesystem_mode": True,
                    "enable_memory_filesystem_mode": True,
                    "write_mode": "auto",
                },
            }
        else:
            # Simplified orchestrator config for local mode (no skills)
            orchestrator_config = {
                "snapshot_storage": "snapshots",
                "agent_temporary_workspace": "temp_workspaces",
                "voting_sensitivity": "checklist_gated",
                "voting_threshold": 3,
                "max_new_answers_per_agent": 5,
                # Fairness defaults (enabled across all coordination modes)
                "fairness_enabled": True,
                "fairness_lead_cap_answers": 2,
                "max_midstream_injections_per_round": 2,
                # Multimodal tools enabled for all agents
                "enable_multimodal_tools": True,
                # Default generation backends (agents can override)
                "image_generation_backend": "openai",  # OpenAI image generation
                "video_generation_backend": "openai",  # OpenAI video generation
                "audio_generation_backend": "openai",  # OpenAI TTS
                "coordination": {
                    "max_orchestration_restarts": 0,  # Disabled pending MAS-268 fix
                    "learning_capture_mode": "verification_and_final_only",
                    "enable_agent_task_planning": True,
                    "task_planning_filesystem_mode": True,
                    "enable_memory_filesystem_mode": True,
                    "write_mode": "auto",
                },
            }

        # Always set context_paths to avoid runtime prompt
        # Priority: context_paths (new) > context_path (deprecated) > empty list
        if context_paths:
            # Use the provided context_paths list directly (already normalized)
            orchestrator_config["context_paths"] = context_paths
        elif context_path:
            # Backward compatibility: single context_path with write permission
            orchestrator_config["context_paths"] = [
                {"path": context_path, "permission": "write"},
            ]
        else:
            orchestrator_config["context_paths"] = []

        # Add coordination settings if provided
        coordination_mode = coordination_settings.get("coordination_mode")
        if coordination_mode:
            orchestrator_config["coordination_mode"] = coordination_mode

        if coordination_settings.get("presenter_agent"):
            orchestrator_config["presenter_agent"] = coordination_settings["presenter_agent"]

        if coordination_mode == "decomposition":
            if "presenter_agent" not in orchestrator_config and agents:
                orchestrator_config["presenter_agent"] = agents[-1]["id"]
            if coordination_settings.get("answer_novelty_requirement") is None:
                orchestrator_config["answer_novelty_requirement"] = "balanced"
            if coordination_settings.get("max_new_answers_per_agent") is None:
                orchestrator_config["max_new_answers_per_agent"] = 2
            if coordination_settings.get("max_new_answers_global") is None:
                orchestrator_config["max_new_answers_global"] = max(3, len(agents) * 3)

        if coordination_settings.get("voting_sensitivity"):
            orchestrator_config["voting_sensitivity"] = coordination_settings["voting_sensitivity"]
        if coordination_settings.get("voting_threshold") is not None:
            orchestrator_config["voting_threshold"] = coordination_settings["voting_threshold"]
        if coordination_settings.get("answer_novelty_requirement"):
            orchestrator_config["answer_novelty_requirement"] = coordination_settings["answer_novelty_requirement"]
        if coordination_settings.get("max_new_answers_per_agent"):
            orchestrator_config["max_new_answers_per_agent"] = coordination_settings["max_new_answers_per_agent"]
        if coordination_settings.get("max_new_answers_global"):
            orchestrator_config["max_new_answers_global"] = coordination_settings["max_new_answers_global"]
        if "fairness_enabled" in coordination_settings:
            orchestrator_config["fairness_enabled"] = coordination_settings["fairness_enabled"]
        if coordination_settings.get("fairness_lead_cap_answers") is not None:
            orchestrator_config["fairness_lead_cap_answers"] = coordination_settings["fairness_lead_cap_answers"]
        if coordination_settings.get("max_midstream_injections_per_round") is not None:
            orchestrator_config["max_midstream_injections_per_round"] = coordination_settings["max_midstream_injections_per_round"]
        if coordination_settings.get("learning_capture_mode"):
            orchestrator_config["coordination"]["learning_capture_mode"] = coordination_settings["learning_capture_mode"]
        if coordination_settings.get("enable_subagents"):
            orchestrator_config["coordination"]["enable_subagents"] = True
            orchestrator_config["coordination"]["subagent_default_timeout"] = 300  # 5 minutes
            orchestrator_config["coordination"]["subagent_max_concurrent"] = 3

            # Add subagent orchestrator config if custom model was selected
            if coordination_settings.get("subagent_orchestrator"):
                orchestrator_config["coordination"]["subagent_orchestrator"] = coordination_settings["subagent_orchestrator"]

        # Add persona generator config if enabled
        if coordination_settings.get("persona_generator"):
            orchestrator_config["coordination"]["persona_generator"] = coordination_settings["persona_generator"]

        # Build full config
        config = {
            "agents": agents,
            "orchestrator": orchestrator_config,
            "timeout_settings": {
                "orchestrator_timeout_seconds": 3600,
                "initial_round_timeout_seconds": 1200,  # 20 min for first answer
                "subsequent_round_timeout_seconds": 900,  # 15 min for rounds with input answers
                "round_timeout_grace_seconds": 300,  # 5 min grace before hard block
            },
            "ui": {
                "display_type": "textual_terminal",
                "logging_enabled": True,
            },
        }

        return config


def main() -> None:
    """Main entry point for the config builder."""
    try:
        builder = ConfigBuilder()
        result = builder.run()

        if result and len(result) == 2:
            filepath, question = result
            if question:
                # Run MassGen with the created config
                console.print(
                    "\n[bold green]✅ Configuration created successfully![/bold green]",
                )
                console.print("\n[bold cyan]Running MassGen...[/bold cyan]\n")

                import asyncio
                import sys

                # Simulate CLI call with the config
                original_argv = sys.argv.copy()
                sys.argv = ["massgen", "--config", filepath, question]

                try:
                    from .cli import main as cli_main

                    asyncio.run(cli_main())
                finally:
                    sys.argv = original_argv
            else:
                console.print(
                    "\n[bold green]✅ Configuration saved![/bold green]",
                )
                console.print("\n[bold cyan]To use it, run:[/bold cyan]")
                console.print(
                    f'  [yellow]massgen --config {filepath} "Your question"[/yellow]\n',
                )
        else:
            console.print("[yellow]Configuration builder exited.[/yellow]")
    except KeyboardInterrupt:
        console.print(
            "\n\n[bold yellow]Configuration cancelled by user[/bold yellow]\n",
        )
    except Exception as e:
        console.print(f"\n[error]❌ Unexpected error in main: {str(e)}[/error]")
        console.print("[info]Please report this issue if it persists.[/info]\n")


if __name__ == "__main__":
    main()
