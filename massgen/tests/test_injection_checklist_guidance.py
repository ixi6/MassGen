"""Tests for injection guidance text and label transition formatting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from massgen.coordination_tracker import CoordinationTracker
from massgen.orchestrator import Orchestrator


def _build_orchestrator(
    voting_sensitivity: str,
    *,
    coordination_mode: str = "voting",
) -> Orchestrator:
    orchestrator = Orchestrator.__new__(Orchestrator)
    tracker = CoordinationTracker()
    tracker.initialize_session(["agent_a", "agent_b"], user_prompt="test")
    tracker.add_agent_answer("agent_b", "old answer")
    tracker.track_agent_context("agent_a", {"agent_b": "old answer"})
    tracker.add_agent_answer("agent_b", "new answer")

    orchestrator.coordination_tracker = tracker
    orchestrator.config = SimpleNamespace(
        coordination_mode=coordination_mode,
        voting_sensitivity=voting_sensitivity,
    )
    orchestrator._normalize_workspace_paths_in_answers = lambda answers, viewing_agent_id: answers
    orchestrator._compute_plan_progress_stats = lambda _workspace_path: None

    backend = MagicMock()
    backend.filesystem_manager = MagicMock()
    backend.filesystem_manager.agent_temporary_workspace = "/tmp/viewer"
    agent = MagicMock()
    agent.backend = backend
    orchestrator.agents = {"agent_a": agent}
    return orchestrator


def test_injection_includes_explicit_label_transition_for_updates():
    orchestrator = _build_orchestrator(voting_sensitivity="checklist_gated")

    injection = orchestrator._build_tool_result_injection(
        "agent_a",
        {"agent_b": "updated peer answer"},
        existing_answers={"agent_b": "stale peer answer"},
    )

    assert "[UPDATE: agent2 (agent2.1 -> agent2.2) updated their answer(s)]" in injection
    assert "agent2.1 -> agent2.2" in injection


def test_checklist_mode_injection_requires_submit_checklist_flow():
    orchestrator = _build_orchestrator(voting_sensitivity="checklist_gated")

    injection = orchestrator._build_tool_result_injection(
        "agent_a",
        {"agent_b": "updated peer answer"},
        existing_answers={"agent_b": "stale peer answer"},
    )

    assert "submit_checklist" in injection
    assert "validation error" in injection.lower()
    assert "propose_improvements" in injection


def test_decomposition_checklist_mode_injection_requires_recheck_before_stop():
    orchestrator = _build_orchestrator(
        voting_sensitivity="checklist_gated",
        coordination_mode="decomposition",
    )

    injection = orchestrator._build_tool_result_injection(
        "agent_a",
        {"agent_b": "updated peer answer"},
        existing_answers={"agent_b": "stale peer answer"},
    )

    assert "submit_checklist" in injection
    assert "propose_improvements" in injection
    assert "Call `stop` only" in injection


def test_non_checklist_mode_keeps_vote_or_build_guidance():
    orchestrator = _build_orchestrator(voting_sensitivity="balanced")

    injection = orchestrator._build_tool_result_injection(
        "agent_a",
        {"agent_b": "updated peer answer"},
        existing_answers={"agent_b": "stale peer answer"},
    )

    assert "THEN CHOOSE ONE" in injection
    assert "VOTE for their answer" in injection
