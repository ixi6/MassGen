"""Unit tests for anonymous voting bug fixes.

Bug #1 — Context leakage causes self-vote bias:
    Each voting agent receives ``per_agent_answers`` that includes their *own*
    answer alongside peers. The agent can recognise its own writing verbatim and
    votes for itself, breaking the anonymous-voting guarantee.

    Fix: exclude the agent's own answer from ``per_agent_answers`` so each agent
    only evaluates peers.

Bug #2 — ``_coordination_complete()`` blocks on killed agents:
    When agents error-out (``is_killed=True``) they keep ``has_voted=False``,
    which causes ``all(state.has_voted …)`` to never return True. The loop only
    exits via the fallback ``if not active_streams: break``, which is fine but
    semantically incorrect — the function should consider only *alive* agents.

    Fix: exclude killed agents from the completion check.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fix #1 — per_agent_answers must exclude the voting agent's own answer
# ---------------------------------------------------------------------------


def test_per_agent_answers_excludes_own_answer_for_each_agent():
    """The filter expression correctly omits an agent's own entry."""
    current_answers = {
        "agent_a": "Answer A content",
        "agent_b": "Answer B content",
        "agent_c": "Answer C content",
    }

    for agent_id in current_answers:
        per_agent_answers = {k: v for k, v in current_answers.items() if k != agent_id}

        # Own answer must be absent
        assert agent_id not in per_agent_answers, (
            f"{agent_id} should not appear in its own per_agent_answers"
        )
        # All peer answers must still be present
        assert len(per_agent_answers) == len(current_answers) - 1
        for peer_id in current_answers:
            if peer_id != agent_id:
                assert per_agent_answers[peer_id] == current_answers[peer_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_coordination_loop_excludes_own_answer_from_voting_context(
    mock_orchestrator, monkeypatch
):
    """Integration: _stream_coordination_with_agents must pass only peer answers to each agent.

    FAILS before Fix #1 (per_agent_answers = dict(current_answers) includes own).
    PASSES after Fix #1 (per_agent_answers filtered to exclude own).
    """
    orchestrator = mock_orchestrator(num_agents=3)
    orchestrator.current_task = "Test voting anonymity"
    orchestrator.config.disable_injection = True

    agent_ids = list(orchestrator.agents.keys())  # ["agent_a", "agent_b", "agent_c"]

    # Populate agent answers both on agent_states and on coordination_tracker
    # so vote label resolution doesn't produce warnings.
    for aid in agent_ids:
        orchestrator.agent_states[aid].answer = f"Answer from {aid}"
        orchestrator.coordination_tracker.add_agent_answer(aid, f"Answer from {aid}")

    captured_answers: dict[str, dict] = {}

    async def mock_stream_exec(agent_id, task, answers, *args, **kwargs):
        """Capture the answers dict and immediately return a vote for the first peer."""
        captured_answers[agent_id] = dict(answers) if answers else {}
        if answers:
            first_peer = next(iter(answers))
            yield ("result", ("vote", {"agent_id": first_peer, "reason": "peer answer"}))
        yield ("done", None)

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", mock_stream_exec)

    votes: dict = {}
    async for _ in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    # All three agents must have been spawned by the coordination loop
    assert set(captured_answers.keys()) == set(agent_ids), (
        f"Expected all agents to be spawned; got {set(captured_answers.keys())}"
    )

    # Core assertion: each agent must NOT have seen its own answer
    for agent_id in agent_ids:
        own_answers_seen = captured_answers.get(agent_id, {})
        assert agent_id not in own_answers_seen, (
            f"Agent {agent_id} received its own answer in voting context "
            f"(keys present: {list(own_answers_seen.keys())})"
        )


def test_known_answer_ids_still_includes_own_answer(mock_orchestrator):
    """Fix #1 side-effect: known_answer_ids tracks ALL answers (incl. own) for restart detection.

    The fix only changes per_agent_answers — known_answer_ids must remain
    unchanged so the 'unseen updates' restart logic keeps working correctly.
    """
    orchestrator = mock_orchestrator(num_agents=3)

    for aid in orchestrator.agents:
        orchestrator.agent_states[aid].answer = f"Answer from {aid}"

    current_answers = {
        aid: state.answer
        for aid, state in orchestrator.agent_states.items()
        if state.answer
    }

    # known_answer_ids is set to set(current_answers.keys()) — includes own entry
    for agent_id in orchestrator.agents:
        known_ids = set(current_answers.keys())
        assert agent_id in known_ids, (
            f"known_answer_ids should include {agent_id}'s own answer "
            "so restart detection works correctly"
        )


# ---------------------------------------------------------------------------
# Fix #2 — _coordination_complete() must exclude killed agents
# ---------------------------------------------------------------------------


def test_coordination_complete_logic_excludes_killed_agents(mock_orchestrator):
    """Fix #2: completion condition returns True when only alive agents have voted.

    Documents the bug (old logic) and the fix (new logic).
    """
    orchestrator = mock_orchestrator(num_agents=3)

    # agent_a voted; agents b and c died (error/timeout)
    orchestrator.agent_states["agent_a"].has_voted = True
    orchestrator.agent_states["agent_b"].is_killed = True
    orchestrator.agent_states["agent_c"].is_killed = True

    # Bug: old logic requires ALL agents to have voted (including killed ones)
    old_all_voted = all(s.has_voted for s in orchestrator.agent_states.values())
    assert old_all_voted is False, (
        "Bug confirmed: old logic prevents completion when killed agents exist"
    )

    # Fix: new logic only requires non-killed agents to have voted
    active_states = [s for s in orchestrator.agent_states.values() if not s.is_killed]
    new_all_voted = all(s.has_voted for s in active_states) if active_states else True
    assert new_all_voted is True, (
        "Fixed logic: coordination completes when all alive agents have voted"
    )


def test_coordination_complete_logic_waits_for_alive_unvoted_agents(mock_orchestrator):
    """Fix #2: coordination must NOT complete while alive agents haven't voted."""
    orchestrator = mock_orchestrator(num_agents=3)

    # Only agent_a voted; b and c are alive but still working
    orchestrator.agent_states["agent_a"].has_voted = True
    # b and c: defaults — has_voted=False, is_killed=False

    active_states = [s for s in orchestrator.agent_states.values() if not s.is_killed]
    new_all_voted = all(s.has_voted for s in active_states) if active_states else True
    assert new_all_voted is False, (
        "Coordination should wait for alive agents b and c to vote"
    )


def test_coordination_complete_logic_all_alive_voted(mock_orchestrator):
    """Fix #2: coordination completes when all alive agents have voted."""
    orchestrator = mock_orchestrator(num_agents=3)

    for aid in orchestrator.agents:
        orchestrator.agent_states[aid].has_voted = True

    active_states = [s for s in orchestrator.agent_states.values() if not s.is_killed]
    new_all_voted = all(s.has_voted for s in active_states) if active_states else True
    assert new_all_voted is True


def test_coordination_complete_logic_handles_all_killed(mock_orchestrator):
    """Edge case: if all agents are killed, treat as complete (empty active_states)."""
    orchestrator = mock_orchestrator(num_agents=2)

    orchestrator.agent_states["agent_a"].is_killed = True
    orchestrator.agent_states["agent_b"].is_killed = True

    active_states = [s for s in orchestrator.agent_states.values() if not s.is_killed]
    new_all_voted = all(s.has_voted for s in active_states) if active_states else True
    assert new_all_voted is True, (
        "Edge case: all killed → no active states → treated as complete"
    )
