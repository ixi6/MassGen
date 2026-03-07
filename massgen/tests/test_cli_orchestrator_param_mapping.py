"""Tests for shared orchestrator param mapping in CLI setup paths."""

from __future__ import annotations

from massgen.agent_config import AgentConfig
from massgen.cli import _apply_orchestrator_runtime_params


def test_apply_orchestrator_runtime_params_maps_new_defer_flags():
    config = AgentConfig()

    _apply_orchestrator_runtime_params(
        config,
        {
            "defer_peer_updates_until_restart": True,
            "allow_midstream_peer_updates_before_checklist_submit": False,
        },
    )

    assert config.defer_peer_updates_until_restart is True
    assert config.allow_midstream_peer_updates_before_checklist_submit is False


def test_apply_orchestrator_runtime_params_keeps_optional_override_unset_when_missing():
    config = AgentConfig()
    assert config.allow_midstream_peer_updates_before_checklist_submit is None

    _apply_orchestrator_runtime_params(
        config,
        {
            "defer_peer_updates_until_restart": True,
        },
    )

    assert config.defer_peer_updates_until_restart is True
    assert config.allow_midstream_peer_updates_before_checklist_submit is None


def test_final_answer_strategy_mapped_from_yaml():
    """final_answer_strategy: synthesize in orchestrator config must land on AgentConfig."""
    config = AgentConfig()
    assert config.final_answer_strategy is None

    _apply_orchestrator_runtime_params(
        config,
        {"final_answer_strategy": "synthesize"},
    )

    assert config.final_answer_strategy == "synthesize"


def test_skip_final_presentation_explicit_false():
    """Explicit False in YAML must override a previously-True default."""
    config = AgentConfig()
    config.skip_final_presentation = True

    _apply_orchestrator_runtime_params(
        config,
        {"skip_final_presentation": False},
    )

    assert config.skip_final_presentation is False


def test_disable_injection_explicit_true():
    """disable_injection: true must be applied."""
    config = AgentConfig()
    assert getattr(config, "disable_injection", False) is False

    _apply_orchestrator_runtime_params(
        config,
        {"disable_injection": True},
    )

    assert config.disable_injection is True


def test_skip_voting_explicit_false():
    """Explicit skip_voting: false must override a previously-True value."""
    config = AgentConfig()
    config.skip_voting = True

    _apply_orchestrator_runtime_params(
        config,
        {"skip_voting": False},
    )

    assert config.skip_voting is False
