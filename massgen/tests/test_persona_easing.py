#!/usr/bin/env python3
"""Unit tests for persona lifecycle behavior (drop / soften / keep)."""

import pytest

from massgen.agent_config import AgentConfig
from massgen.orchestrator import Orchestrator
from massgen.persona_generator import GeneratedPersona

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator_with_persona(after_first_answer="drop"):
    """Return an Orchestrator with a single persona configured."""
    orchestrator = Orchestrator(agents={}, config=AgentConfig())
    orchestrator.config.coordination_config.persona_generator.after_first_answer = after_first_answer
    persona = GeneratedPersona(
        agent_id="agent_a",
        persona_text="Prioritize maintainability and simplicity.",
        attributes={},
    )
    orchestrator._generated_personas = {"agent_a": persona}
    return orchestrator


# ---------------------------------------------------------------------------
# Peer detection (unchanged)
# ---------------------------------------------------------------------------


def test_has_peer_answers_excludes_own_answer():
    """Peer detection should not count the agent's own prior answer."""
    assert Orchestrator._has_peer_answers("agent_a", None) is False
    assert Orchestrator._has_peer_answers("agent_a", {}) is False
    assert Orchestrator._has_peer_answers("agent_a", {"agent_a": "my answer"}) is False
    assert Orchestrator._has_peer_answers("agent_a", {"agent_b": "peer answer"}) is True
    assert (
        Orchestrator._has_peer_answers(
            "agent_a",
            {"agent_a": "my answer", "agent_b": "peer answer"},
        )
        is True
    )


# ---------------------------------------------------------------------------
# Before peer answers: persona is always strong regardless of mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["drop", "soften", "keep"])
def test_persona_is_strong_before_peer_answers(mode):
    """Strong persona text should be used until peer answers are visible, regardless of mode."""
    orchestrator = _make_orchestrator_with_persona(after_first_answer=mode)
    result = orchestrator._get_persona_for_agent("agent_a", has_peer_answers=False)
    assert result == "Prioritize maintainability and simplicity."


# ---------------------------------------------------------------------------
# After peer answers: behaviour depends on after_first_answer mode
# ---------------------------------------------------------------------------


def test_persona_dropped_after_peer_answers_default():
    """Default after_first_answer='drop' should return None after peers visible."""
    orchestrator = _make_orchestrator_with_persona(after_first_answer="drop")
    result = orchestrator._get_persona_for_agent("agent_a", has_peer_answers=True)
    assert result is None


def test_persona_is_eased_after_peer_answers():
    """after_first_answer='soften' should return softened text emphasizing synthesis."""
    orchestrator = _make_orchestrator_with_persona(after_first_answer="soften")
    eased_text = orchestrator._get_persona_for_agent("agent_a", has_peer_answers=True)
    assert eased_text is not None
    # Template wraps across a line break; normalize whitespace for assertion
    normalized = " ".join(eased_text.split())
    assert "preference, not a position to defend" in normalized
    assert "synthesize the strongest ideas" in normalized
    assert "Prioritize maintainability and simplicity." in eased_text


def test_persona_kept_at_full_strength():
    """after_first_answer='keep' should return original persona text always."""
    orchestrator = _make_orchestrator_with_persona(after_first_answer="keep")
    result = orchestrator._get_persona_for_agent("agent_a", has_peer_answers=True)
    assert result == "Prioritize maintainability and simplicity."
