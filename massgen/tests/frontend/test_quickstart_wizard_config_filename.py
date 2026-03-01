"""Tests for quickstart wizard config filename wiring."""

import asyncio
from pathlib import Path

from massgen.frontend.displays.textual_widgets.quickstart_wizard import QuickstartWizard


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
