"""Unit tests for core Orchestrator coordination behavior."""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from massgen.backend.base import StreamChunk
from massgen.events import EventEmitter, EventType


def test_normalize_subagent_mcp_result_accepts_structured_content_payload(mock_orchestrator):
    """Claude Code style call_tool results may expose the parsed payload via structuredContent."""
    orchestrator = mock_orchestrator(num_agents=1)

    raw_result = SimpleNamespace(
        content=None,
        structuredContent={
            "success": True,
            "operation": "spawn_subagents",
            "results": [{"subagent_id": "round_eval"}],
        },
    )

    normalized = orchestrator._normalize_subagent_mcp_result(raw_result)
    assert normalized == {
        "success": True,
        "operation": "spawn_subagents",
        "results": [{"subagent_id": "round_eval"}],
    }


@pytest.mark.asyncio
async def test_call_subagent_mcp_tool_async_uses_background_client_structured_content(
    mock_orchestrator,
    monkeypatch,
):
    """The orchestrator MCP bridge should accept Claude Code background-client results that only populate structuredContent."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    backend = orchestrator.agents[agent_id].backend

    captured: dict[str, object] = {}

    class _FakeBackgroundClient:
        async def call_tool(self, name, arguments):
            captured["name"] = name
            captured["arguments"] = arguments
            return SimpleNamespace(
                content=None,
                structuredContent={
                    "success": True,
                    "operation": "spawn_subagents",
                    "results": [{"subagent_id": "round_eval"}],
                },
            )

    monkeypatch.setattr(
        backend,
        "_get_background_mcp_client",
        AsyncMock(return_value=_FakeBackgroundClient()),
        raising=False,
    )
    monkeypatch.delattr(backend, "_execute_mcp_function_with_retry", raising=False)

    result = await orchestrator._call_subagent_mcp_tool_async(
        parent_agent_id=agent_id,
        tool_name="spawn_subagents",
        params={"tasks": [{"subagent_id": "round_eval", "task": "critique"}]},
    )

    assert result == {
        "success": True,
        "operation": "spawn_subagents",
        "results": [{"subagent_id": "round_eval"}],
    }
    assert captured["name"] == "mcp__subagent_agent_a__spawn_subagents"
    assert captured["arguments"] == {"tasks": [{"subagent_id": "round_eval", "task": "critique"}]}


@pytest.mark.asyncio
async def test_phase_transitions_initial_to_enforcement(mock_orchestrator, monkeypatch):
    """Agents should move from answer submission to voting in the next iteration."""
    orchestrator = mock_orchestrator(num_agents=2)
    orchestrator.current_task = "Test task"

    # Keep this unit test purely in-memory.
    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="snapshot-ts")

    call_counts = defaultdict(int)
    agent_ids = list(orchestrator.agents.keys())
    winner_id = agent_ids[0]

    async def fake_stream_agent_execution(
        agent_id,
        task,
        answers,
        conversation_context=None,
        paraphrase=None,
    ):
        _ = (task, answers, conversation_context, paraphrase)
        call_counts[agent_id] += 1

        # First round: each agent submits an answer.
        if call_counts[agent_id] == 1:
            yield ("result", ("answer", f"{agent_id} answer"))
            yield ("done", None)
            return

        # Second round: each agent votes, completing coordination.
        yield ("result", ("vote", {"agent_id": winner_id, "reason": "Best answer"}))
        yield ("done", None)

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    votes = {}
    observed_chunks = []
    async for chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        observed_chunks.append(chunk)

    assert call_counts[agent_ids[0]] == 2
    assert call_counts[agent_ids[1]] == 2
    assert orchestrator.agent_states[agent_ids[0]].answer == f"{agent_ids[0]} answer"
    assert orchestrator.agent_states[agent_ids[1]].answer == f"{agent_ids[1]} answer"
    assert all(state.has_voted for state in orchestrator.agent_states.values())
    assert set(votes.keys()) == set(agent_ids)
    assert all(vote["agent_id"] == winner_id for vote in votes.values())
    assert observed_chunks  # coordination streamed at least one chunk


@pytest.mark.asyncio
async def test_presentation_fallback_uses_stored_answer(mock_orchestrator, monkeypatch):
    """If final presentation yields no content, fallback should use stored answer."""
    orchestrator = mock_orchestrator(num_agents=1)
    selected_agent_id = next(iter(orchestrator.agents.keys()))
    orchestrator._selected_agent = selected_agent_id
    stored_answer = "Stored answer from coordination phase."
    orchestrator.agent_states[selected_agent_id].answer = stored_answer

    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._copy_all_snapshots_to_temp_workspace = AsyncMock(return_value=None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    async def empty_presentation_chat(*args, **kwargs):
        _ = (args, kwargs)
        yield StreamChunk(type="done")

    orchestrator.agents[selected_agent_id].chat = empty_presentation_chat

    chunks = []
    async for chunk in orchestrator.get_final_presentation(
        selected_agent_id,
        {
            "vote_counts": {selected_agent_id: 1},
            "voter_details": {},
            "is_tie": False,
        },
    ):
        chunks.append(chunk)

    fallback_chunks = [c for c in chunks if getattr(c, "type", None) == "content" and "Using stored answer as final presentation" in (getattr(c, "content", "") or "")]

    assert fallback_chunks
    assert stored_answer in fallback_chunks[0].content
    assert orchestrator._final_presentation_content == stored_answer


def test_get_coordination_result_includes_timeout_metadata(mock_orchestrator):
    """Execution mode needs explicit timeout signals for chunk retry handling."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.is_orchestrator_timeout = True
    orchestrator.timeout_reason = "Time limit exceeded (120.0s/120s)"

    result = orchestrator.get_coordination_result()

    assert result["is_orchestrator_timeout"] is True
    assert result["timeout_reason"] == "Time limit exceeded (120.0s/120s)"


def test_truncate_enforcement_buffer_content_caps_to_first_segment(mock_orchestrator):
    """Large enforcement retry buffers should keep only bounded recent context."""
    orchestrator = mock_orchestrator(num_agents=1)

    oversize_chars = orchestrator._ENFORCEMENT_RETRY_BUFFER_MAX_CHARS * 2
    buffer_content = "START_SENTINEL\n" + ("A" * oversize_chars) + "\nEND_SENTINEL"
    truncated = orchestrator._truncate_enforcement_buffer_content(buffer_content)

    assert truncated is not None
    assert "START_SENTINEL" in truncated
    assert "END_SENTINEL" not in truncated
    assert "truncated" in truncated.lower()
    assert "showing first" in truncated.lower()
    assert len(truncated) <= orchestrator._ENFORCEMENT_RETRY_BUFFER_MAX_CHARS + 200


@pytest.mark.asyncio
async def test_cancel_running_background_work_for_agent_cancels_active_subagents_and_jobs(
    mock_orchestrator,
    monkeypatch,
):
    """Round-end cleanup should cancel running/pending subagents and backend jobs."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    call_log: list[tuple[str, str, dict[str, object]]] = []

    async def fake_subagent_call(parent_agent_id: str, tool_name: str, params: dict[str, object]):
        call_log.append((parent_agent_id, tool_name, dict(params)))
        assert parent_agent_id == agent_id
        if tool_name == "list_subagents":
            return {
                "success": True,
                "subagents": [
                    {"subagent_id": "subagent_running", "status": "running"},
                    {"subagent_id": "subagent_pending", "status": "pending"},
                    {"subagent_id": "subagent_done", "status": "completed"},
                ],
            }
        if tool_name == "cancel_subagent":
            return {"success": True, "status": "cancelled", "subagent_id": params.get("subagent_id")}
        raise AssertionError(f"Unexpected tool call: {tool_name}")

    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        fake_subagent_call,
    )

    cancel_background_jobs = AsyncMock()
    monkeypatch.setattr(
        orchestrator.agents[agent_id].backend,
        "_cancel_all_background_tool_jobs",
        cancel_background_jobs,
        raising=False,
    )

    await orchestrator._cancel_running_background_work_for_agent(agent_id)

    cancel_calls = [entry for entry in call_log if entry[1] == "cancel_subagent"]
    assert {entry[2]["subagent_id"] for entry in cancel_calls} == {
        "subagent_running",
        "subagent_pending",
    }
    cancel_background_jobs.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_answer_triggers_round_end_background_cleanup(mock_orchestrator, monkeypatch):
    """Submitting a new_answer should trigger immediate round-end background cleanup."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Submit an answer and clean background work."
    agent_id = "agent_a"

    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="snapshot-ts")
    cancel_background_work = AsyncMock()
    monkeypatch.setattr(
        orchestrator,
        "_cancel_running_background_work_for_agent",
        cancel_background_work,
    )

    call_count = {"count": 0}

    async def fake_stream_agent_execution(
        aid: str,
        task: str,
        answers: dict[str, str],
        conversation_context: dict[str, object] | None = None,
        paraphrase: str | None = None,
    ):
        _ = (aid, task, answers, conversation_context, paraphrase)
        call_count["count"] += 1
        if call_count["count"] == 1:
            yield ("result", ("answer", "answer v1"))
            yield ("done", None)
            return

        yield ("result", ("vote", {"agent_id": agent_id, "reason": "done"}))
        yield ("done", None)

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    votes: dict[str, dict[str, object]] = {}
    async for _chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    cancel_background_work.assert_awaited_once_with(agent_id)


@pytest.mark.asyncio
async def test_round_evaluator_launches_between_round_one_and_round_two_and_injects_packet(
    mock_orchestrator,
    monkeypatch,
):
    """Orchestrator should launch round_evaluator after round 1 and inject its packet into round 2."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Critique and refine the current draft."
    agent_id = next(iter(orchestrator.agents.keys()))
    backend = orchestrator.agents[agent_id].backend
    backend.tool_call_responses = [
        [{"name": "new_answer", "arguments": {"content": "answer v1"}}],
        [{"name": "vote", "arguments": {"agent_id": agent_id, "reason": "done"}}],
    ]
    backend.responses = ["round 1", "round 2"]

    orchestrator.config.voting_sensitivity = "checklist_gated"
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="snapshot-ts")
    orchestrator._copy_all_snapshots_to_temp_workspace = AsyncMock(
        return_value="/tmp/temp_workspaces",
    )

    recorded_user_messages: list[str] = []
    original_stream_with_tools = backend.stream_with_tools

    async def wrapped_stream_with_tools(messages, tools=None, **kwargs):
        user_parts: list[str] = []
        for message in messages:
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, str):
                user_parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        user_parts.append(str(item["text"]))
        recorded_user_messages.append("\n".join(user_parts))
        async for chunk in original_stream_with_tools(messages, tools=tools, **kwargs):
            yield chunk

    monkeypatch.setattr(backend, "stream_with_tools", wrapped_stream_with_tools)

    captured_subagent_calls: list[tuple[str, dict[str, object], int]] = []

    async def fake_subagent_call(
        parent_agent_id: str,
        tool_name: str,
        params: dict[str, object],
    ):
        assert parent_agent_id == agent_id
        captured_subagent_calls.append((tool_name, dict(params), backend._call_count))
        if tool_name == "list_subagents":
            return {"success": True, "subagents": []}
        if tool_name == "spawn_subagents":
            return {
                "success": True,
                "mode": "blocking",
                "results": [
                    {
                        "subagent_id": "round_eval",
                        "status": "completed",
                        "success": True,
                        "answer": "ROUND_EVAL_PACKET: critical improvement spec",
                        "workspace": "/tmp/round_eval",
                        "execution_time_seconds": 1.25,
                        "token_usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                ],
            }
        raise AssertionError(f"Unexpected subagent MCP call: {tool_name}")

    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        fake_subagent_call,
    )

    emitter = EventEmitter()
    emitted_events = []
    emitter.add_listener(emitted_events.append)
    monkeypatch.setattr("massgen.orchestrator.get_event_emitter", lambda: emitter)

    votes: dict[str, dict[str, object]] = {}
    async for _chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    spawn_calls = [entry for entry in captured_subagent_calls if entry[0] == "spawn_subagents"]
    assert len(spawn_calls) == 1

    _, spawn_params, backend_call_count_at_spawn = spawn_calls[0]
    assert backend_call_count_at_spawn == 1
    assert spawn_params["background"] is False
    assert spawn_params["refine"] is False
    assert isinstance(spawn_params["tasks"], list)
    assert spawn_params["tasks"][0]["subagent_type"] == "round_evaluator"
    assert "/tmp/temp_workspaces" in spawn_params["tasks"][0]["context_paths"]

    assert len(recorded_user_messages) >= 2
    assert "ROUND_EVAL_PACKET" not in recorded_user_messages[0]
    assert "ROUND_EVAL_PACKET: critical improvement spec" in recorded_user_messages[1]

    spawn_tool_events = [event for event in emitted_events if event.event_type in {EventType.TOOL_START, EventType.TOOL_COMPLETE} and event.data.get("tool_name") == "spawn_subagents"]
    assert [event.event_type for event in spawn_tool_events] == [
        EventType.TOOL_START,
        EventType.TOOL_COMPLETE,
    ]
    assert spawn_tool_events[0].round_number == 1


@pytest.mark.asyncio
async def test_round_evaluator_failure_blocks_parent_restart_until_retry_succeeds(
    mock_orchestrator,
    monkeypatch,
):
    """A failed round_evaluator launch should block the next parent round until a retry succeeds."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Hold round 2 until the evaluator succeeds."
    agent_id = next(iter(orchestrator.agents.keys()))

    orchestrator.config.voting_sensitivity = "checklist_gated"
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="snapshot-ts")
    orchestrator._copy_all_snapshots_to_temp_workspace = AsyncMock(
        return_value="/tmp/temp_workspaces",
    )

    sequence: list[tuple[str, object]] = []
    stream_call_count = {"count": 0}

    async def fake_stream_agent_execution(
        aid: str,
        task: str,
        answers: dict[str, str],
        conversation_context: dict[str, object] | None = None,
        paraphrase: str | None = None,
    ):
        _ = (aid, task, conversation_context, paraphrase)
        stream_call_count["count"] += 1
        sequence.append(("stream", dict(answers)))
        if stream_call_count["count"] == 1:
            yield ("result", ("answer", "answer v1"))
            yield ("done", None)
            return

        yield ("result", ("vote", {"agent_id": agent_id, "reason": "ready"}))
        yield ("done", None)

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    gate_results = iter(
        [
            {"success": False, "error": "temporary evaluator launch failure"},
            {
                "success": True,
                "mode": "blocking",
                "results": [
                    {
                        "subagent_id": "round_eval",
                        "status": "completed",
                        "success": True,
                        "answer": "ROUND_EVAL_PACKET: critical improvement spec",
                        "workspace": "/tmp/round_eval",
                        "execution_time_seconds": 0.75,
                    },
                ],
            },
        ],
    )

    async def fake_subagent_call(
        parent_agent_id: str,
        tool_name: str,
        params: dict[str, object],
    ):
        _ = params
        assert parent_agent_id == agent_id
        assert tool_name == "spawn_subagents"
        result = next(gate_results)
        sequence.append(("gate", bool(result.get("success"))))
        return result

    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        fake_subagent_call,
    )

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr("massgen.orchestrator.asyncio.sleep", fake_sleep)

    votes: dict[str, dict[str, object]] = {}
    async for _chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    assert sequence == [
        ("stream", {}),
        ("gate", False),
        ("gate", True),
        ("stream", {agent_id: "answer v1"}),
    ]
    assert sleep_calls


@pytest.mark.asyncio
async def test_round_evaluator_gate_runs_between_first_and_second_round(mock_orchestrator, monkeypatch):
    """The orchestrator should run the round-evaluator gate itself before round 2 starts."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Critique first draft before second round."
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True

    monkeypatch.setattr("massgen.orchestrator.get_log_session_dir", lambda: None)
    orchestrator._save_agent_snapshot = AsyncMock(return_value="snapshot-ts")

    events: list[tuple[str, dict[str, str]]] = []
    gate = AsyncMock(side_effect=lambda answers, conversation_context=None: events.append(("gate", dict(answers))))
    monkeypatch.setattr(
        orchestrator,
        "_run_round_evaluator_pre_round_if_needed",
        gate,
        raising=False,
    )

    agent_id = "agent_a"
    call_count = {"count": 0}

    async def fake_stream_agent_execution(
        aid: str,
        task: str,
        answers: dict[str, str],
        conversation_context: dict[str, object] | None = None,
        paraphrase: str | None = None,
    ):
        _ = (aid, task, conversation_context, paraphrase)
        call_count["count"] += 1
        events.append(("stream", dict(answers)))
        if call_count["count"] == 1:
            yield ("result", ("answer", "answer v1"))
            yield ("done", None)
            return

        yield ("result", ("vote", {"agent_id": agent_id, "reason": "ready"}))
        yield ("done", None)

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    votes: dict[str, dict[str, object]] = {}
    async for _chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    assert events == [
        ("gate", {}),
        ("stream", {}),
        ("gate", {agent_id: "answer v1"}),
        ("stream", {agent_id: "answer v1"}),
    ]
    assert gate.await_count == 2
