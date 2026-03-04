"""Tests for quickstart wizard config filename wiring."""

import asyncio
from pathlib import Path

from massgen.frontend.displays.textual_widgets.quickstart_wizard import (
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


def test_provider_model_reasoning_defaults_to_opus_high_even_if_stale_medium():
    """Opus 4.6 should force high default in quickstart model step."""
    step = ProviderModelStep(WizardState())
    step._reasoning_select = object()
    step._current_provider = "claude_code"
    step._current_model = "claude-opus-4-6"
    step._current_reasoning_effort = "medium"

    step._update_reasoning_input()

    assert step._current_reasoning_effort == "high"


def test_tabbed_reasoning_defaults_to_codex_xhigh_even_if_stale_medium():
    """GPT-5.3 Codex should force xhigh default in tabbed quickstart step."""
    step = TabbedProviderModelStep(WizardState(), agent_count=1)
    step._reasoning_selects["a"] = object()
    step._tab_selections["a"] = {
        "provider": "codex",
        "model": "gpt-5.3-codex",
        "reasoning_effort": "medium",
    }

    step._update_reasoning_input("a", "codex", "gpt-5.3-codex")

    assert step._tab_selections["a"]["reasoning_effort"] == "xhigh"
