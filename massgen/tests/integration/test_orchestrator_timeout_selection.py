"""Deterministic non-API integration tests for timeout and selection behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from massgen.backend.base import StreamChunk


async def _collect_chunks(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_timeout_with_no_answers_emits_fallback_and_done(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.timeout_reason = "Time limit exceeded"

    chunks = await _collect_chunks(orchestrator._handle_orchestrator_timeout())

    messages = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]
    assert any("Orchestrator Timeout" in m for m in messages)
    assert any("No answers available from any agents due to timeout" in m for m in messages)
    assert chunks[-1].type == "done"
    assert orchestrator.workflow_phase == "presenting"


@pytest.mark.asyncio
async def test_timeout_with_votes_selects_most_voted_agent(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.timeout_reason = "Time limit exceeded"
    orchestrator.agent_states["agent_a"].answer = "Answer A"
    orchestrator.agent_states["agent_b"].answer = "Answer B"
    orchestrator.agent_states["agent_a"].votes = {"agent_id": "agent_b", "reason": "better"}
    orchestrator.agent_states["agent_b"].votes = {"agent_id": "agent_b", "reason": "self"}
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    async def show_modal():
        return None

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("get_final_presentation should be skipped after timeout salvage")

    monkeypatch.setattr(orchestrator, "_show_workspace_modal_if_needed", show_modal)
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)
    monkeypatch.setattr(orchestrator, "get_final_presentation", should_not_be_called)

    chunks = await _collect_chunks(orchestrator._handle_orchestrator_timeout())
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert orchestrator._selected_agent == "agent_b"
    assert any("Orchestrator Timeout" in c for c in contents)
    assert any("Answer B" in c for c in contents)
    assert not any("Jumping to final presentation" in c for c in contents)
    assert chunks[-1].type == "done"
    orchestrator._save_agent_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_with_answers_but_no_votes_uses_latest_answer_without_presentation(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.timeout_reason = "Time limit exceeded"
    orchestrator.agent_states["agent_a"].answer = "First answer"
    orchestrator.agent_states["agent_b"].answer = "Second answer"
    orchestrator.coordination_tracker.add_agent_answer("agent_a", "First answer")
    orchestrator.coordination_tracker.add_agent_answer("agent_b", "Second answer")
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    async def show_modal():
        return None

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("get_final_presentation should be skipped after timeout salvage")

    monkeypatch.setattr(orchestrator, "_show_workspace_modal_if_needed", show_modal)
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)
    monkeypatch.setattr(orchestrator, "get_final_presentation", should_not_be_called)

    chunks = await _collect_chunks(orchestrator._handle_orchestrator_timeout())
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert orchestrator._selected_agent == "agent_b"
    assert any("Second answer" in c for c in contents)
    assert not any("Jumping to final presentation" in c for c in contents)
    assert chunks[-1].type == "done"
    orchestrator._save_agent_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_ignores_killed_agents(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.timeout_reason = "Time limit exceeded"
    orchestrator.agent_states["agent_a"].answer = "Killed answer"
    orchestrator.agent_states["agent_a"].is_killed = True
    orchestrator.agent_states["agent_b"].answer = "Live answer"
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    async def show_modal():
        return None

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("get_final_presentation should be skipped after timeout salvage")

    monkeypatch.setattr(orchestrator, "_show_workspace_modal_if_needed", show_modal)
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)
    monkeypatch.setattr(orchestrator, "get_final_presentation", should_not_be_called)

    chunks = await _collect_chunks(orchestrator._handle_orchestrator_timeout())
    assert orchestrator._selected_agent == "agent_b"
    assert chunks[-1].type == "done"


def test_determine_final_agent_from_votes_returns_none_without_answers(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    selected = orchestrator._determine_final_agent_from_votes(votes={}, agent_answers={})
    assert selected is None


def test_get_vote_results_reports_tie_and_counts(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.agent_states["agent_a"].answer = "A"
    orchestrator.agent_states["agent_b"].answer = "B"
    orchestrator.agent_states["agent_a"].votes = {"agent_id": "agent_a", "reason": "self"}
    orchestrator.agent_states["agent_b"].votes = {"agent_id": "agent_b", "reason": "self"}

    results = orchestrator._get_vote_results()
    assert results["is_tie"] is True
    assert results["total_votes"] == 2
    assert results["agents_with_answers"] == 2
    assert results["vote_counts"]["agent_a"] == 1
    assert results["vote_counts"]["agent_b"] == 1
    # Tie breaks by registration order.
    assert results["winner"] == "agent_a"


@pytest.mark.asyncio
async def test_coordinate_agents_skip_rounds_shortcuts_to_final_presentation(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Debug mode path."
    orchestrator.config.skip_coordination_rounds = True

    async def fake_generate_personas():
        return None

    async def fake_present_final_answer():
        yield StreamChunk(type="content", content="final directly")
        yield StreamChunk(type="done")

    monkeypatch.setattr(orchestrator, "_generate_and_inject_personas", fake_generate_personas)
    monkeypatch.setattr(orchestrator, "_present_final_answer", fake_present_final_answer)

    chunks = await _collect_chunks(orchestrator._coordinate_agents({}))
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert orchestrator._selected_agent == "agent_a"
    assert any("Skipping coordination rounds" in c for c in contents)
    assert any("final directly" in c for c in contents)
