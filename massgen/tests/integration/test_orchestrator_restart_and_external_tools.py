# -*- coding: utf-8 -*-
"""Deterministic non-API integration tests for restart and external tool passthrough."""

from __future__ import annotations

import pytest


def _configure_agent_script(agent, scripted_tool_calls, responses=None):
    """Attach deterministic per-call tool scripts to a mock-backed agent."""
    agent.backend.tool_call_responses = scripted_tool_calls
    agent.backend.responses = responses or ["ok"] * len(scripted_tool_calls)


async def _collect_stream(stream):
    emitted = []
    async for item in stream:
        emitted.append(item)
    return emitted


@pytest.mark.asyncio
async def test_stream_agent_execution_vote_only_restart_short_circuits(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Vote-only restart path"
    agent_id = "agent_a"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 2
    state.answer = "existing answer"  # Must have answer for restart to proceed

    monkeypatch.setattr(orchestrator, "_is_vote_only_mode", lambda _aid: True)

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    assert emitted == [("done", None)]
    assert state.restart_pending is False
    assert orchestrator.agents[agent_id].backend._call_count == 0


@pytest.mark.asyncio
async def test_stream_agent_execution_first_restart_increments_injection_count(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "First restart path"
    agent_id = "agent_a"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 0
    state.answer = "existing answer"  # Must have answer for restart to proceed

    monkeypatch.setattr(orchestrator, "_is_vote_only_mode", lambda _aid: False)

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    assert emitted == [("done", None)]
    assert state.restart_pending is False
    assert state.injection_count == 1
    assert orchestrator.agents[agent_id].backend._call_count == 0


# --- First-answer protection tests ---


def test_should_defer_restart_true_when_no_answer(mock_orchestrator):
    """Agent with no answer should defer restart to protect first-answer production."""
    orchestrator = mock_orchestrator(num_agents=1)
    assert orchestrator._should_defer_restart_for_first_answer("agent_a") is True


def test_should_defer_restart_false_when_has_answer(mock_orchestrator):
    """Agent with an existing answer should not defer restart."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.agent_states["agent_a"].answer = "some answer"
    assert orchestrator._should_defer_restart_for_first_answer("agent_a") is False


def test_should_defer_restart_false_for_unknown_agent(mock_orchestrator):
    """Unknown agent_id should not defer (no state to protect)."""
    orchestrator = mock_orchestrator(num_agents=1)
    assert orchestrator._should_defer_restart_for_first_answer("nonexistent") is False


@pytest.mark.asyncio
async def test_first_answer_protection_skips_restart(mock_orchestrator, monkeypatch):
    """Agent with restart_pending but no answer yet should NOT restart - it should
    clear the flag and proceed with normal execution instead."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "First answer protection test"
    agent_id = "agent_a"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 0
    state.answer = None  # No answer yet - first answer protection applies

    monkeypatch.setattr(orchestrator, "_is_vote_only_mode", lambda _aid: False)

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    # Agent should NOT have immediately restarted - it should have run normally
    assert emitted != [("done", None)]
    # restart_pending should be cleared
    assert state.restart_pending is False


@pytest.mark.asyncio
async def test_first_answer_protection_allows_restart_when_has_answer(mock_orchestrator, monkeypatch):
    """Agent WITH an existing answer should restart normally when restart_pending."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Restart proceeds with answer"
    agent_id = "agent_a"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 0
    state.answer = "existing answer"  # HAS an answer

    monkeypatch.setattr(orchestrator, "_is_vote_only_mode", lambda _aid: False)

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    # Should restart normally (existing behavior)
    assert emitted == [("done", None)]


@pytest.mark.asyncio
async def test_no_hook_midstream_deferred_for_first_answer(mock_orchestrator):
    """_prepare_no_hook_midstream_enforcement should return None when agent has no answer."""
    orchestrator = mock_orchestrator(num_agents=2)
    agent_id = "agent_a"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.answer = None  # No answer yet

    # Give the other agent an answer so there's something to inject
    orchestrator.agent_states["agent_b"].answer = "agent b answer"

    result = await orchestrator._prepare_no_hook_midstream_enforcement(agent_id, {})

    assert result is None
    assert state.restart_pending is False


@pytest.mark.asyncio
async def test_stream_agent_execution_surfaces_external_tool_calls(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "External passthrough"
    orchestrator._external_tools = [
        {
            "type": "function",
            "function": {
                "name": "external_lookup",
                "description": "Caller-executed external tool",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    agent_id = "agent_a"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"id": "ext-1", "name": "external_lookup", "arguments": {"query": "latest"}}],
        ],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    external_items = [item for item in emitted if item[0] == "external_tool_calls"]
    assert len(external_items) == 1
    assert external_items[0][1][0]["name"] == "external_lookup"
    assert emitted[-1] == ("done", None)
    assert not any(item[0] == "result" for item in emitted)


@pytest.mark.asyncio
async def test_stream_coordination_surfaces_external_tool_calls_and_stops(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Coordination external passthrough"
    orchestrator._external_tools = [
        {
            "type": "function",
            "function": {
                "name": "external_lookup",
                "description": "Caller-executed external tool",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    _configure_agent_script(
        orchestrator.agents["agent_a"],
        scripted_tool_calls=[
            [{"id": "ext-2", "name": "external_lookup", "arguments": {"query": "deploy status"}}],
        ],
    )

    votes = {}
    chunks = []
    async for chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        chunks.append(chunk)

    tool_chunks = [chunk for chunk in chunks if getattr(chunk, "type", None) == "tool_calls"]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].source == "agent_a"
    assert tool_chunks[0].tool_calls[0]["name"] == "external_lookup"
    assert chunks[-1].type == "done"
    assert votes == {}
