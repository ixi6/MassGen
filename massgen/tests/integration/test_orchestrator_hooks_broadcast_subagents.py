# -*- coding: utf-8 -*-
"""Deterministic non-API integration tests for hooks, broadcast, and async subagents."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from massgen.coordination_tracker import AgentAnswer
from massgen.mcp_tools.hooks import HookType
from massgen.subagent.models import SubagentResult


def _capture_general_hook_manager(agent):
    captured = {}

    def _set_manager(manager):
        captured["manager"] = manager

    agent.backend.set_general_hook_manager = _set_manager
    return captured


@pytest.mark.asyncio
async def test_mid_stream_hook_clears_stale_restart_when_no_new_answers(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.config.disable_injection = False
    agent_id = "agent_a"
    peer_id = "agent_b"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 1
    state.answer = "Agent A's existing answer"  # Has produced an answer already
    orchestrator.agent_states[peer_id].answer = "Known peer answer"

    agent = orchestrator.agents[agent_id]
    captured = _capture_general_hook_manager(agent)
    known_answers = {peer_id: "Known peer answer"}
    orchestrator._setup_hook_manager_for_agent(agent_id, agent, known_answers)
    manager = captured["manager"]

    result = await manager.execute_hooks(
        HookType.POST_TOOL_USE,
        "read_file",
        "{}",
        {"agent_id": agent_id},
        tool_output="ok",
    )

    assert result.inject is None
    assert state.restart_pending is False


@pytest.mark.asyncio
async def test_mid_stream_hook_injects_new_answers_after_first_restart(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.config.disable_injection = False
    agent_id = "agent_a"
    peer_id = "agent_b"

    state = orchestrator.agent_states[agent_id]
    state.restart_pending = True
    state.injection_count = 1
    state.answer = "Agent A's existing answer"  # Has produced an answer already
    orchestrator.agent_states[peer_id].answer = "New answer from peer"

    # Register the answer revision in coordination_tracker so
    # _get_agent_answer_revision_count returns > 0 for the peer.
    peer_answer = AgentAnswer(agent_id=peer_id, content="New answer from peer", timestamp=time.time())
    peer_answer.label = "B1.1"
    orchestrator.coordination_tracker.answers_by_agent.setdefault(peer_id, []).append(peer_answer)

    monkeypatch.setattr(
        orchestrator,
        "_copy_all_snapshots_to_temp_workspace",
        AsyncMock(return_value="/tmp/mock-snapshots"),
    )

    agent = orchestrator.agents[agent_id]
    captured = _capture_general_hook_manager(agent)
    orchestrator._setup_hook_manager_for_agent(agent_id, agent, {})
    manager = captured["manager"]

    result = await manager.execute_hooks(
        HookType.POST_TOOL_USE,
        "read_file",
        "{}",
        {"agent_id": agent_id},
        tool_output="ok",
    )

    assert result.inject is not None
    assert "NEW ANSWER RECEIVED" in result.inject["content"]
    assert state.restart_pending is False
    assert state.injection_count == 2
    assert peer_id in state.known_answer_ids


@pytest.mark.asyncio
async def test_round_timeout_hooks_integration_soft_then_hard_timeout(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    orchestrator.config.timeout_config.initial_round_timeout_seconds = 1
    orchestrator.config.timeout_config.subsequent_round_timeout_seconds = 1
    orchestrator.config.timeout_config.round_timeout_grace_seconds = 0
    orchestrator.config.coordination_config.use_two_tier_workspace = True
    orchestrator.agent_states[agent_id].round_start_time = time.time() - 5

    captured = _capture_general_hook_manager(agent)
    orchestrator._setup_hook_manager_for_agent(agent_id, agent, {})
    manager = captured["manager"]

    post_result = await manager.execute_hooks(
        HookType.POST_TOOL_USE,
        "read_file",
        "{}",
        {"agent_id": agent_id},
        tool_output="ok",
    )
    assert post_result.inject is not None
    assert "ROUND TIME LIMIT APPROACHING" in post_result.inject["content"]
    assert "deliverable/" in post_result.inject["content"]
    assert orchestrator.agent_states[agent_id].round_timeout_state is not None
    assert orchestrator.agent_states[agent_id].round_timeout_state.soft_timeout_fired_at is not None

    hard_block = await manager.execute_hooks(
        HookType.PRE_TOOL_USE,
        "read_file",
        "{}",
        {"agent_id": agent_id},
    )
    assert hard_block.decision == "deny"
    assert "HARD TIMEOUT" in (hard_block.reason or "")
    assert orchestrator.agent_states[agent_id].round_timeout_state.consecutive_hard_denials == 1

    allow_vote = await manager.execute_hooks(
        HookType.PRE_TOOL_USE,
        "vote",
        "{}",
        {"agent_id": agent_id},
    )
    assert allow_vote.allowed is True
    assert orchestrator.agent_states[agent_id].round_timeout_state.consecutive_hard_denials == 0


def test_broadcast_tool_registration_adds_custom_tool_names(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.config.coordination_config.broadcast = "agents"
    orchestrator.config.coordination_config.broadcast_sensitivity = "high"

    for agent in orchestrator.agents.values():
        agent.backend.custom_tool_manager = object()

    orchestrator._init_broadcast_tools()

    workflow_names = {(tool.get("function", {}) or {}).get("name") for tool in orchestrator.workflow_tools}
    assert "ask_others" in workflow_names

    for agent in orchestrator.agents.values():
        assert "ask_others" in agent.backend._custom_tool_names
        assert "respond_to_broadcast" in agent.backend._custom_tool_names


def test_on_subagent_complete_queues_pending_results(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    result = SubagentResult(
        subagent_id="sub-1",
        status="completed",
        success=True,
        answer="done",
        workspace_path="/tmp/sub-1",
        execution_time_seconds=1.2,
    )

    orchestrator._on_subagent_complete(agent_id, "sub-1", result)

    assert agent_id in orchestrator._pending_subagent_results
    assert orchestrator._pending_subagent_results[agent_id][0][0] == "sub-1"
    assert orchestrator._pending_subagent_results[agent_id][0][1] == result


def test_get_pending_subagent_results_polls_mcp_and_deduplicates(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    class FakeMCPClient:
        def __init__(self):
            self.calls = []

        def call_tool(self, name, args):
            self.calls.append((name, args))
            if name == f"mcp__subagent_{agent_id}__list_subagents":
                return {
                    "success": True,
                    "subagents": [
                        {"subagent_id": "sub-complete", "status": "completed"},
                        {"subagent_id": "sub-running", "status": "running"},
                    ],
                }
            if name == f"mcp__subagent_{agent_id}__get_subagent_result":
                return {
                    "success": True,
                    "result": {
                        "subagent_id": "sub-complete",
                        "success": True,
                        "status": "completed",
                        "answer": "Subagent finished",
                        "workspace_path": "/tmp/sub-complete",
                        "execution_time_seconds": 3.5,
                        "token_usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                }
            return {"success": False}

    agent.mcp_client = FakeMCPClient()

    first = orchestrator._get_pending_subagent_results(agent_id)
    second = orchestrator._get_pending_subagent_results(agent_id)

    assert len(first) == 1
    assert first[0][0] == "sub-complete"
    assert first[0][1].status == "completed"
    assert second == []


@pytest.mark.asyncio
async def test_setup_hook_manager_registers_subagent_injection_hook(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator._async_subagents_enabled = True
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    pending_result = SubagentResult(
        subagent_id="sub-done",
        status="completed",
        success=True,
        answer="Background subagent answer",
        workspace_path="/tmp/sub-done",
        execution_time_seconds=2.0,
    )
    monkeypatch.setattr(
        orchestrator,
        "_get_pending_subagent_results",
        lambda _agent_id: [("sub-done", pending_result)],
    )

    captured = _capture_general_hook_manager(agent)
    orchestrator._setup_hook_manager_for_agent(agent_id, agent, {})
    manager = captured["manager"]

    result = await manager.execute_hooks(
        HookType.POST_TOOL_USE,
        "read_file",
        "{}",
        {"agent_id": agent_id},
        tool_output="ok",
    )

    assert result.inject is not None
    assert "ASYNC SUBAGENT RESULTS" in result.inject["content"]
    assert "sub-done" in result.inject["content"]
    assert result.inject["strategy"] == orchestrator._async_subagent_injection_strategy
