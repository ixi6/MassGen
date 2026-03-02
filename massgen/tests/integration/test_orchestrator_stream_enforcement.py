"""Deterministic non-API integration tests for orchestrator stream enforcement."""

from __future__ import annotations

import pytest


def _configure_agent_script(agent, scripted_tool_calls, responses=None):
    """Attach deterministic per-call tool scripts to a mock-backed agent."""
    agent.backend.tool_call_responses = scripted_tool_calls
    agent.backend.responses = responses or ["ok"] * len(scripted_tool_calls)


async def _collect_stream(stream):
    """Collect all tuples emitted by an orchestrator stream."""
    emitted = []
    async for item in stream:
        emitted.append(item)
    return emitted


@pytest.mark.asyncio
async def test_stream_agent_execution_emits_answer_result_for_new_answer(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Draft a release summary."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"name": "new_answer", "arguments": {"content": "Final answer from A"}}],
        ],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    assert ("result", ("answer", "Final answer from A")) in emitted
    assert emitted[-1] == ("done", None)


@pytest.mark.asyncio
async def test_stream_agent_execution_emits_vote_result_for_valid_vote(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Pick best option."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    orchestrator.agent_states["agent_b"].answer = "Candidate answer B"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"name": "vote", "arguments": {"agent_id": "agent_b", "reason": "Most complete"}}],
        ],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(
            agent_id,
            orchestrator.current_task,
            {},
        ),
    )

    result_items = [item for item in emitted if item[0] == "result"]
    assert result_items
    assert result_items[0][1][0] == "vote"
    assert result_items[0][1][1]["agent_id"] == "agent_b"
    assert emitted[-1] == ("done", None)


@pytest.mark.asyncio
async def test_stream_agent_execution_retries_invalid_vote_then_accepts_valid_vote(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Vote with retry."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    orchestrator.agent_states["agent_b"].answer = "Answer B"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"name": "vote", "arguments": {"agent_id": "not_an_agent", "reason": "mistake"}}],
            [{"name": "vote", "arguments": {"agent_id": "agent_b", "reason": "corrected"}}],
        ],
        responses=["first attempt", "second attempt"],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(
            agent_id,
            orchestrator.current_task,
            {},
        ),
    )

    retry_messages = [item for item in emitted if item[0] == "content" and "Invalid agent_id" in item[1]]
    vote_results = [item for item in emitted if item[0] == "result" and item[1][0] == "vote"]
    assert retry_messages
    assert vote_results
    assert vote_results[0][1][1]["agent_id"] == "agent_b"


@pytest.mark.asyncio
async def test_stream_agent_execution_retries_vote_without_answers_then_accepts_new_answer(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Fallback to answer."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"name": "vote", "arguments": {"agent_id": "agent_a", "reason": "premature"}}],
            [{"name": "new_answer", "arguments": {"content": "Standalone answer after retry"}}],
        ],
        responses=["vote attempt", "new answer attempt"],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    retry_messages = [item for item in emitted if item[0] == "content" and "Cannot vote when no answers exist" in item[1]]
    answer_results = [item for item in emitted if item[0] == "result" and item[1][0] == "answer"]
    assert retry_messages
    assert answer_results
    assert answer_results[0][1][1] == "Standalone answer after retry"


@pytest.mark.asyncio
async def test_stream_agent_execution_rejects_mixed_vote_and_new_answer_then_accepts_answer(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Enforce one workflow action."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    orchestrator.agent_states["agent_b"].answer = "Existing answer"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [
                {"name": "vote", "arguments": {"agent_id": "agent_b", "reason": "mixed"}},
                {"name": "new_answer", "arguments": {"content": "mixed attempt"}},
            ],
            [{"name": "new_answer", "arguments": {"content": "clean answer"}}],
        ],
        responses=["mixed attempt", "clean attempt"],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(
            agent_id,
            orchestrator.current_task,
            {},
        ),
    )

    retry_messages = [item for item in emitted if item[0] == "content" and "Cannot use both 'vote' and 'new_answer'" in item[1]]
    answer_results = [item for item in emitted if item[0] == "result" and item[1][0] == "answer"]
    assert retry_messages
    assert answer_results
    assert answer_results[0][1][1] == "clean answer"


@pytest.mark.asyncio
async def test_stream_agent_execution_errors_after_three_non_workflow_attempts(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Must call workflow tool."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    _configure_agent_script(
        orchestrator.agents[agent_id],
        scripted_tool_calls=[
            [{"name": "unknown_tool", "arguments": {}}],
            [{"name": "unknown_tool", "arguments": {}}],
            [{"name": "unknown_tool", "arguments": {}}],
        ],
        responses=["attempt1", "attempt2", "attempt3"],
    )

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    errors = [item for item in emitted if item[0] == "error"]
    assert errors
    assert "failed to use workflow tools" in errors[-1][1].lower()
    assert emitted[-1] == ("done", None)


@pytest.mark.asyncio
async def test_unknown_tool_enforcement_uses_text_not_tool_result(mock_orchestrator, monkeypatch):
    """Unknown tool calls must not trigger tool_result enforcement messages.

    The Claude API rejects tool_result blocks that reference tool_use_ids not present
    in the preceding assistant message. When an unknown tool is called, its tool_use
    block never reaches history (it's silently dropped), so creating a tool_result
    enforcement for it produces a 400. Enforcement must fall back to plain text.

    The mock backend is configured to simulate Claude's filter behavior (strip unknown
    tool calls) so the test exercises the orchestrator's fallback to text enforcement.
    """
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Submit an answer."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]
    _configure_agent_script(
        agent,
        scripted_tool_calls=[
            [{"id": "toolu_bash_1", "name": "$BASH", "arguments": {"command": "ls"}}],
            [{"name": "new_answer", "arguments": {"content": "Done after retry"}}],
        ],
        responses=["running bash", "final answer"],
    )

    # Simulate Claude's filter: strip unknown tool calls (those whose tool_use blocks
    # are never added to assistant message history).
    def claude_like_filter(tool_calls, unknown_tool_calls):
        unknown_ids = {id(tc) for tc in unknown_tool_calls}
        return [tc for tc in tool_calls if id(tc) not in unknown_ids]

    agent.backend.filter_enforcement_tool_calls = claude_like_filter

    create_error_calls: list[list] = []
    original_create_error = orchestrator._create_tool_error_messages

    def recording_create_error(agt, tool_calls, primary_error_msg, secondary_error_msg=None):
        create_error_calls.append(list(tool_calls))
        return original_create_error(agt, tool_calls, primary_error_msg, secondary_error_msg)

    monkeypatch.setattr(orchestrator, "_create_tool_error_messages", recording_create_error)

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    # Agent should recover and submit new_answer on retry
    assert ("result", ("answer", "Done after retry")) in emitted

    # _create_tool_error_messages must NOT have been called with the unknown $BASH tool call.
    # If it were, it would produce a tool_result with an orphaned tool_use_id → API 400.
    assert not any(calls for calls in create_error_calls), f"_create_tool_error_messages was called with unknown tool calls: {create_error_calls}"


@pytest.mark.asyncio
async def test_stream_agent_execution_truncates_injected_buffer_on_retry(mock_orchestrator):
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Must call workflow tool."
    orchestrator.config.disable_injection = True

    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    _configure_agent_script(
        agent,
        scripted_tool_calls=[
            [],
            [{"name": "new_answer", "arguments": {"content": "Recovered answer"}}],
        ],
        responses=["plain response without workflow tool", "retry response"],
    )

    oversize_chars = orchestrator._ENFORCEMENT_RETRY_BUFFER_MAX_CHARS * 2
    large_buffer = "START_SENTINEL\n" + ("A" * oversize_chars) + "\nEND_SENTINEL"
    agent.backend._get_streaming_buffer = lambda: large_buffer

    captured_messages = []
    original_stream_with_tools = agent.backend.stream_with_tools

    async def recording_stream_with_tools(messages, tools=None, **kwargs):
        captured_messages.append(messages)
        async for chunk in original_stream_with_tools(messages=messages, tools=tools, **kwargs):
            yield chunk

    agent.backend.stream_with_tools = recording_stream_with_tools

    emitted = await _collect_stream(
        orchestrator._stream_agent_execution(agent_id, orchestrator.current_task, {}),
    )

    assert ("result", ("answer", "Recovered answer")) in emitted
    assert len(captured_messages) >= 2

    second_call_messages = captured_messages[1]
    enforcement_messages = [msg for msg in second_call_messages if msg.get("role") == "user" and "Your previous response was incomplete." in msg.get("content", "")]

    assert enforcement_messages
    enforcement_content = enforcement_messages[-1]["content"]
    assert "START_SENTINEL" in enforcement_content
    assert "END_SENTINEL" not in enforcement_content
    assert "truncated" in enforcement_content.lower()
    assert "showing first" in enforcement_content.lower()
