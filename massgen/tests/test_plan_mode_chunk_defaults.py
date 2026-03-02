"""Tests for plan-mode default chunk behavior."""

import pytest

from massgen.cli import (
    get_spec_creation_prompt_prefix,
    get_task_planning_prompt_prefix,
    run_plan_and_execute,
)
from massgen.frontend.displays.tui_modes import TuiModeState


def test_task_planning_prompt_defaults_to_single_chunk_target():
    prefix = get_task_planning_prompt_prefix(plan_depth="dynamic")
    assert "- Target chunks: exactly 1" in prefix
    assert "- Target chunks: around 1" not in prefix


def test_spec_creation_prompt_defaults_to_single_chunk_target():
    prefix = get_spec_creation_prompt_prefix()
    assert "- Target chunks: exactly 1" in prefix
    assert "- Target chunks: around 1" not in prefix


def test_task_planning_prompt_defaults_to_autonomous_broadcast():
    prefix = get_task_planning_prompt_prefix(plan_depth="dynamic")
    assert "### 1. Scope Analysis (REQUIRED FIRST)" in prefix
    assert "### 1. Scope Confirmation (REQUIRED FIRST)" not in prefix


def test_tui_plan_mode_defaults_to_single_chunk_target():
    state = TuiModeState()
    state.plan_mode = "plan"

    overrides = state.get_coordination_overrides()

    assert state.plan_config.target_chunks == 1
    assert overrides["plan_target_chunks"] == 1


def test_tui_plan_mode_defaults_to_broadcast_false():
    state = TuiModeState()
    state.plan_mode = "plan"

    overrides = state.get_coordination_overrides()

    assert state.plan_config.broadcast is False
    assert overrides["broadcast"] is False


@pytest.mark.asyncio
async def test_run_plan_and_execute_passes_single_chunk_target_by_default(tmp_path, monkeypatch):
    captured: dict[str, list[str]] = {}

    class _StopPlanning(Exception):
        pass

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        raise _StopPlanning("stop after capturing planning command")

    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("agents: []\n")

    with pytest.raises(_StopPlanning):
        await run_plan_and_execute(
            config={"orchestrator": {}},
            question="Test plan mode default chunk behavior",
            config_path=str(config_path),
        )

    cmd = captured["cmd"]
    assert "--plan-chunks" in cmd
    assert cmd[cmd.index("--plan-chunks") + 1] == "1"
    assert "--broadcast" in cmd
    assert cmd[cmd.index("--broadcast") + 1] == "false"


@pytest.mark.asyncio
async def test_run_plan_and_execute_uses_interactive_textual_subprocess_when_configured(tmp_path, monkeypatch):
    captured: dict[str, list[str]] = {}

    class _StopPlanning(Exception):
        pass

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        raise _StopPlanning("stop after capturing interactive planning command")

    monkeypatch.setattr("subprocess.run", _fake_run)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("agents: []\n")

    with pytest.raises(_StopPlanning):
        await run_plan_and_execute(
            config={
                "orchestrator": {},
                "ui": {"display_type": "textual_terminal"},
            },
            question="Test textual interactive planning subprocess",
            config_path=str(config_path),
        )

    cmd = captured["cmd"]
    assert "--display" in cmd
    assert cmd[cmd.index("--display") + 1] == "textual"
    assert "--automation" not in cmd
