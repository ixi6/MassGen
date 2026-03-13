"""Tests for quickstart wizard config filename wiring."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

from massgen.frontend.displays.textual_widgets.quickstart_wizard import (
    CoordinationModeStep,
    ProviderModelStep,
    QuickstartWizard,
    TabbedProviderModelStep,
)
from massgen.frontend.displays.textual_widgets.wizard_base import WizardState


def _seed_minimal_state(wizard: QuickstartWizard) -> None:
    wizard.state.set("agent_count", 1)
    wizard.state.set("setup_mode", "same")
    wizard.state.set(
        "provider_model",
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
    )
    wizard.state.set("execution_mode", False)
    wizard.state.set("install_skills_now", {})
    wizard.state.set("launch_options", "save_only")
    wizard.state.set("coordination_mode_settings", {})


def test_quickstart_wizard_saves_custom_project_filename(monkeypatch, tmp_path):
    """Wizard should save to .massgen/<custom>.yaml when a filename is provided."""
    monkeypatch.chdir(tmp_path)
    wizard = QuickstartWizard(config_filename="my-team-setup")
    _seed_minimal_state(wizard)

    result = asyncio.run(wizard.on_wizard_complete())

    expected = (tmp_path / ".massgen" / "my-team-setup.yaml").resolve()
    assert Path(result["config_path"]) == expected
    assert expected.exists()


def test_provider_model_step_not_skipped_for_single_agent_even_with_different_setup_mode():
    """Single-agent quickstart should always show provider/model selection."""
    wizard = QuickstartWizard()
    provider_step = next(step for step in wizard.get_steps() if step.id == "provider_model")

    assert provider_step.skip_condition is not None
    should_skip = provider_step.skip_condition({"agent_count": 1, "setup_mode": "different"})
    assert should_skip is False


def test_provider_model_step_still_skipped_for_multi_agent_different_mode():
    """Multi-agent 'different' mode should keep using the tabbed per-agent step."""
    wizard = QuickstartWizard()
    provider_step = next(step for step in wizard.get_steps() if step.id == "provider_model")

    assert provider_step.skip_condition is not None
    should_skip = provider_step.skip_condition({"agent_count": 3, "setup_mode": "different"})
    assert should_skip is True


def test_quickstart_wizard_no_longer_includes_context_path_step():
    """Quickstart should not reserve a dedicated context-path step."""
    wizard = QuickstartWizard()

    step_ids = [step.id for step in wizard.get_steps()]

    assert "context_path" not in step_ids


def test_coordination_mode_step_decomposition_uses_hidden_checklist_defaults():
    """Decomposition UI should return presenter/caps only and let builder defaults handle novelty/checklist tuning."""
    step = CoordinationModeStep(WizardState())
    step._selected_mode = "decomposition"
    step._presenter_select = SimpleNamespace(value="agent_b")
    step._per_agent_input = SimpleNamespace(value="3")
    step._global_input = SimpleNamespace(value="9")
    step._novelty_select = SimpleNamespace(value="strict")

    value = step.get_value()

    assert value == {
        "coordination_mode": "decomposition",
        "presenter_agent": "agent_b",
        "max_new_answers_per_agent": 3,
        "max_new_answers_global": 9,
    }
    assert "answer_novelty_requirement" not in value


def test_quickstart_wizard_ignores_stale_context_path_state(monkeypatch, tmp_path):
    """Quickstart output should not wire a saved context path into the generated config anymore."""
    monkeypatch.chdir(tmp_path)
    wizard = QuickstartWizard(config_filename="contextless")
    _seed_minimal_state(wizard)
    wizard.state.set("context_path", str(tmp_path / "legacy_context"))

    result = asyncio.run(wizard.on_wizard_complete())

    saved_config = Path(result["config_path"])
    payload = yaml.safe_load(saved_config.read_text(encoding="utf-8"))
    assert payload["orchestrator"]["context_paths"] == []


def test_provider_model_reasoning_defaults_to_opus_high_even_if_stale_medium():
    """Opus 4.6 should force high default in quickstart model step."""
    step = ProviderModelStep(WizardState())
    step._reasoning_select = object()
    step._current_provider = "claude_code"
    step._current_model = "claude-opus-4-6"
    step._current_reasoning_effort = "medium"

    step._update_reasoning_input()

    assert step._current_reasoning_effort == "high"


def test_provider_model_reasoning_defaults_from_copilot_metadata(monkeypatch):
    """Copilot quickstart reasoning should use runtime metadata defaults in the TUI step."""
    monkeypatch.setattr(
        "massgen.config_builder.get_model_metadata_for_provider_sync",
        lambda provider, use_cache=True: [
            {
                "id": "gpt-5.4",
                "name": "GPT-5.4",
                "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
                "default_reasoning_effort": "high",
            },
        ],
    )

    step = ProviderModelStep(WizardState())
    step._reasoning_select = object()
    step._current_provider = "copilot"
    step._current_model = "gpt-5.4"
    step._current_reasoning_effort = "medium"

    step._update_reasoning_input()

    assert step._current_reasoning_effort == "high"


def test_tabbed_reasoning_defaults_to_codex_high_even_if_stale_medium():
    """Codex GPT-5.4 should force high default in tabbed quickstart step."""
    step = TabbedProviderModelStep(WizardState(), agent_count=1)
    step._reasoning_selects["a"] = object()
    step._tab_selections["a"] = {
        "provider": "codex",
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
    }

    step._update_reasoning_input("a", "codex", "gpt-5.4")

    assert step._tab_selections["a"]["reasoning_effort"] == "high"


def test_provider_model_step_loads_runtime_copilot_models(monkeypatch):
    """Textual quickstart should replace static Copilot models with runtime discovery."""
    import massgen.config_builder as config_builder_module

    class FakeBuilder:
        PROVIDERS = {
            "copilot": {
                "name": "GitHub Copilot",
                "type": "copilot",
                "env_var": None,
                "models": ["gpt-4.1", "gpt-5-mini"],
                "default_model": "gpt-5-mini",
                "supports": ["mcp", "web_search"],
            },
        }

        def detect_api_keys(self):
            return {"copilot": True}

    monkeypatch.setattr(config_builder_module, "ConfigBuilder", FakeBuilder)
    monkeypatch.setattr(
        "massgen.frontend.displays.textual_widgets.quickstart_wizard._resolve_quickstart_provider_models",
        lambda provider_id, static_models: ["gpt-5-mini", "claude-opus-4.6"],
    )

    step = ProviderModelStep(WizardState())
    step._load_providers()

    assert step._models_by_provider["copilot"] == ["gpt-5-mini", "claude-opus-4.6"]
    assert step._current_model == "gpt-5-mini"


def test_provider_model_step_marks_agent_frameworks_in_labels(monkeypatch):
    """Textual quickstart should visually distinguish agent-framework backends."""
    import massgen.config_builder as config_builder_module

    class FakeBuilder:
        PROVIDERS = {
            "claude_code": {
                "name": "Claude Code",
                "type": "claude_code",
                "env_var": "ANTHROPIC_API_KEY",
                "models": ["claude-opus-4-6"],
                "default_model": "claude-opus-4-6",
                "supports": ["filesystem", "mcp"],
            },
            "openai": {
                "name": "OpenAI",
                "type": "openai",
                "env_var": "OPENAI_API_KEY",
                "models": ["gpt-5.4"],
                "default_model": "gpt-5.4",
                "supports": ["mcp"],
            },
        }

        def detect_api_keys(self):
            return {"claude_code": True, "openai": True}

    monkeypatch.setattr(config_builder_module, "ConfigBuilder", FakeBuilder)

    step = ProviderModelStep(WizardState())
    step._load_providers()

    assert step._provider_options() == [
        ("Claude Code (agent)", "claude_code"),
        ("OpenAI", "openai"),
    ]


def test_tabbed_provider_model_step_loads_runtime_copilot_models(monkeypatch):
    """Tabbed Textual quickstart should use the same runtime Copilot model source."""
    import massgen.config_builder as config_builder_module

    class FakeBuilder:
        PROVIDERS = {
            "copilot": {
                "name": "GitHub Copilot",
                "type": "copilot",
                "env_var": None,
                "models": ["gpt-4.1", "gpt-5-mini"],
                "default_model": "gpt-5-mini",
                "supports": ["mcp", "web_search"],
            },
        }

        def detect_api_keys(self):
            return {"copilot": True}

    monkeypatch.setattr(config_builder_module, "ConfigBuilder", FakeBuilder)
    monkeypatch.setattr(
        "massgen.frontend.displays.textual_widgets.quickstart_wizard._resolve_quickstart_provider_models",
        lambda provider_id, static_models: ["gpt-5-mini", "claude-opus-4.6"],
    )

    step = TabbedProviderModelStep(WizardState(), agent_count=1)
    step._load_providers()

    assert step._models_by_provider["copilot"] == ["gpt-5-mini", "claude-opus-4.6"]
