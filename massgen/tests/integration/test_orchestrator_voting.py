"""Deterministic non-API integration tests for orchestrator voting flow."""

from __future__ import annotations

import pytest


def _configure_agent_script(agent, scripted_tool_calls, responses=None):
    """Attach deterministic per-call tool scripts to a mock-backed agent."""
    agent.backend.tool_call_responses = scripted_tool_calls
    agent.backend.responses = responses or ["ok"] * len(scripted_tool_calls)


@pytest.mark.asyncio
async def test_three_agent_voting_flow(mock_orchestrator):
    """Three agents submit answers, then vote, and a winner is selected."""
    orchestrator = mock_orchestrator(num_agents=3)
    orchestrator.current_task = "Build a concise release summary."
    orchestrator.config.disable_injection = True

    agent_ids = list(orchestrator.agents.keys())
    winner_id = agent_ids[0]

    for agent_id in agent_ids:
        _configure_agent_script(
            orchestrator.agents[agent_id],
            scripted_tool_calls=[
                [{"name": "new_answer", "arguments": {"content": f"{agent_id} answer"}}],
                [{"name": "vote", "arguments": {"agent_id": winner_id, "reason": "Most complete"}}],
            ],
            responses=[f"{agent_id} drafted answer", f"{agent_id} cast vote"],
        )

    votes = {}
    emitted_chunks = []
    async for chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        emitted_chunks.append(chunk)

    # Integration assertions across orchestrator + tracker + mock backend behavior.
    assert all(orchestrator.agent_states[aid].answer for aid in agent_ids)
    assert all(orchestrator.agent_states[aid].has_voted for aid in agent_ids)
    assert set(votes.keys()) == set(agent_ids)
    assert all(v["agent_id"] == winner_id for v in votes.values())
    assert len(orchestrator.coordination_tracker.votes) == 3
    assert all(len(orchestrator.coordination_tracker.answers_by_agent[aid]) == 1 for aid in agent_ids)

    selected = orchestrator._determine_final_agent_from_votes(
        votes,
        {aid: orchestrator.agent_states[aid].answer for aid in agent_ids},
    )
    assert selected == winner_id
    assert emitted_chunks


@pytest.mark.asyncio
async def test_tie_breaker_uses_agent_registration_order(mock_orchestrator):
    """When votes tie, winner should resolve by agent registration order."""
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Choose best patch."
    orchestrator.config.disable_injection = True

    agent_ids = list(orchestrator.agents.keys())  # ordered from fixture creation
    first_agent, second_agent = agent_ids[0], agent_ids[1]

    _configure_agent_script(
        orchestrator.agents[first_agent],
        scripted_tool_calls=[
            [{"name": "new_answer", "arguments": {"content": "answer A"}}],
            [{"name": "vote", "arguments": {"agent_id": first_agent, "reason": "self"}}],
        ],
    )
    _configure_agent_script(
        orchestrator.agents[second_agent],
        scripted_tool_calls=[
            [{"name": "new_answer", "arguments": {"content": "answer B"}}],
            [{"name": "vote", "arguments": {"agent_id": second_agent, "reason": "self"}}],
        ],
    )

    votes = {}
    async for _ in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    selected = orchestrator._determine_final_agent_from_votes(
        votes,
        {aid: orchestrator.agent_states[aid].answer for aid in agent_ids},
    )
    assert selected == first_agent
