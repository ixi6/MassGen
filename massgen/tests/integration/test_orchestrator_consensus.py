"""Deterministic non-API integration tests for orchestrator consensus behavior."""

from __future__ import annotations

import pytest


def _configure_agent_script(agent, scripted_tool_calls, responses=None):
    """Attach deterministic per-call tool scripts to a mock-backed agent."""
    agent.backend.tool_call_responses = scripted_tool_calls
    agent.backend.responses = responses or ["ok"] * len(scripted_tool_calls)


@pytest.mark.asyncio
async def test_unanimous_consensus_early_exit(mock_orchestrator):
    """Unanimous voting should finish after the vote round with no extra loops."""
    orchestrator = mock_orchestrator(num_agents=3)
    orchestrator.current_task = "Produce final recommendation."
    orchestrator.config.disable_injection = True

    agent_ids = list(orchestrator.agents.keys())
    winner_id = agent_ids[0]

    for agent_id in agent_ids:
        _configure_agent_script(
            orchestrator.agents[agent_id],
            scripted_tool_calls=[
                [{"name": "new_answer", "arguments": {"content": f"{agent_id} proposal"}}],
                [{"name": "vote", "arguments": {"agent_id": winner_id, "reason": "best overall"}}],
            ],
            responses=[f"{agent_id} answer", f"{agent_id} vote"],
        )

    votes = {}
    async for _ in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    # Two backend turns per agent: answer round + vote round.
    assert all(orchestrator.agents[aid].backend._call_count == 2 for aid in agent_ids)
    assert all(orchestrator.agent_states[aid].has_voted for aid in agent_ids)
    assert all(v["agent_id"] == winner_id for v in votes.values())


@pytest.mark.asyncio
async def test_skip_voting_mode_completes_when_all_agents_answer(mock_orchestrator):
    """In skip-voting mode, coordination should end once every agent answered."""
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Draft two alternatives."
    orchestrator.config.skip_voting = True
    orchestrator.config.disable_injection = True

    agent_ids = list(orchestrator.agents.keys())
    for agent_id in agent_ids:
        _configure_agent_script(
            orchestrator.agents[agent_id],
            scripted_tool_calls=[
                [{"name": "new_answer", "arguments": {"content": f"{agent_id} standalone answer"}}],
            ],
            responses=[f"{agent_id} answer"],
        )

    votes = {}
    async for _ in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    assert votes == {}
    assert all(orchestrator.agent_states[aid].answer for aid in agent_ids)
    assert all(orchestrator.agents[aid].backend._call_count == 1 for aid in agent_ids)


@pytest.mark.asyncio
async def test_quick_synthesize_mode_completes_after_first_answer_round_without_votes(mock_orchestrator):
    """Quick multi-agent synthesize runs should stop after one answer round per agent."""
    orchestrator = mock_orchestrator(num_agents=3)
    orchestrator.current_task = "Draft three alternatives, then synthesize."
    orchestrator.config.disable_injection = True
    orchestrator.config.defer_voting_until_all_answered = False
    orchestrator.config.max_new_answers_per_agent = 1
    orchestrator.config.final_answer_strategy = "synthesize"

    agent_ids = list(orchestrator.agents.keys())
    for agent_id in agent_ids:
        _configure_agent_script(
            orchestrator.agents[agent_id],
            scripted_tool_calls=[
                [{"name": "new_answer", "arguments": {"content": f"{agent_id} standalone answer"}}],
            ],
            responses=[f"{agent_id} answer"],
        )

    votes = {}
    async for _ in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    assert votes == {}
    assert all(orchestrator.agent_states[aid].answer for aid in agent_ids)
    assert all(not orchestrator.agent_states[aid].has_voted for aid in agent_ids)
    assert all(orchestrator.agents[aid].backend._call_count == 1 for aid in agent_ids)

    selected = orchestrator._determine_final_agent_from_votes(
        votes,
        {aid: orchestrator.agent_states[aid].answer for aid in agent_ids},
    )
    assert selected == agent_ids[0]
