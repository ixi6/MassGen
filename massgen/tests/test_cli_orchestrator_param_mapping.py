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
