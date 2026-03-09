"""Unit tests for core Orchestrator coordination behavior."""

from __future__ import annotations

import json
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from massgen.backend.base import StreamChunk
from massgen.coordination_tracker import AgentAnswer
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
        async def call_tool(self, tool_name, arguments):
            captured["tool_name"] = tool_name
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
    assert captured["tool_name"] == "mcp__subagent_agent_a__spawn_subagents"
    assert captured["arguments"] == {"tasks": [{"subagent_id": "round_eval", "task": "critique"}]}


@pytest.mark.asyncio
async def test_call_subagent_mcp_tool_async_returns_structured_failure_when_all_paths_fail(
    mock_orchestrator,
    monkeypatch,
):
    """Programmatic MCP bridge failures should surface a structured error payload."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    backend = orchestrator.agents[agent_id].backend

    monkeypatch.setattr(
        backend,
        "_execute_mcp_function_with_retry",
        AsyncMock(side_effect=RuntimeError("executor path failed")),
        raising=False,
    )
    monkeypatch.setattr(
        backend,
        "_get_background_mcp_client",
        AsyncMock(side_effect=RuntimeError("background client init failed")),
        raising=False,
    )
    monkeypatch.setattr(orchestrator.agents[agent_id], "mcp_client", None, raising=False)

    result = await orchestrator._call_subagent_mcp_tool_async(
        parent_agent_id=agent_id,
        tool_name="spawn_subagents",
        params={"tasks": [{"subagent_id": "round_eval", "task": "critique"}]},
    )

    assert result == {
        "success": False,
        "operation": "spawn_subagents",
        "error": "executor path failed; background client init failed",
    }


@pytest.mark.asyncio
async def test_background_client_call_tool_uses_correct_keyword_arg(
    mock_orchestrator,
    monkeypatch,
):
    """Regression: call_tool must use tool_name= matching MCPClient.call_tool signature, not name=."""
    import inspect

    from massgen.mcp_tools.client import MCPClient

    sig = inspect.signature(MCPClient.call_tool)
    params = [p for p in sig.parameters.keys() if p != "self"]
    # First param after self should be 'tool_name', not 'name'
    assert params[0] == "tool_name", f"MCPClient.call_tool first param is '{params[0]}', " f"orchestrator uses tool_name= — keep them in sync"

    # Also verify the orchestrator call site actually uses the right keyword
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    backend = orchestrator.agents[agent_id].backend

    received_kwargs: dict[str, object] = {}

    class _StrictClient:
        async def call_tool(self, **kwargs):
            received_kwargs.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text='{"success": true, "operation": "spawn_subagents", "results": []}')],
                structuredContent=None,
            )

    monkeypatch.setattr(
        backend,
        "_get_background_mcp_client",
        AsyncMock(return_value=_StrictClient()),
        raising=False,
    )
    monkeypatch.delattr(backend, "_execute_mcp_function_with_retry", raising=False)

    await orchestrator._call_subagent_mcp_tool_async(
        parent_agent_id=agent_id,
        tool_name="spawn_subagents",
        params={"tasks": []},
    )

    assert "tool_name" in received_kwargs, f"Expected tool_name= keyword, got: {list(received_kwargs.keys())}"
    assert "name" not in received_kwargs, "Must use tool_name=, not name="


def test_round_evaluator_context_paths_are_always_absolute(mock_orchestrator):
    """Regression: relative context_paths fail validation in the subagent MCP server."""
    from pathlib import Path

    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"

    # Set a relative _agent_temporary_workspace (the bug scenario)
    orchestrator._agent_temporary_workspace = ".massgen/temp_workspaces/some_session"

    paths = orchestrator._get_round_evaluator_context_paths(
        parent_agent_id=agent_id,
        temp_workspace_path="/tmp/some_absolute_path",
    )

    for p in paths:
        assert Path(p).is_absolute(), f"Context path '{p}' is relative — subagent MCP server will reject it"


@pytest.mark.asyncio
async def test_round_evaluator_rewrites_subagent_types_before_spawn(mock_orchestrator, monkeypatch):
    """Regression: workspace may be cleared between rounds, so subagent type dirs
    must be re-written before the evaluator spawn call."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"

    # Enable the round evaluator gate
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    # Set up a fake filesystem_manager with a workspace root
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = Path(tmpdir)
        fs_mgr = SimpleNamespace(
            get_workspace_root=lambda: str(ws_root),
            get_current_workspace=lambda: str(ws_root),
            agent_temporary_workspace=str(ws_root / "temp"),
            cwd=str(ws_root),
        )
        orchestrator.agents[agent_id].backend.filesystem_manager = fs_mgr

        # Give the agent a completed answer so the gate triggers
        orchestrator.agent_states[agent_id].answer = "draft answer v1"
        # Register an answer label in the coordination tracker
        orchestrator.coordination_tracker.add_agent_answer(
            agent_id=agent_id,
            answer="draft answer v1",
        )

        # Track calls to _write_subagent_type_dirs and _call_subagent_mcp_tool_async
        call_order: list[str] = []

        def tracking_write(workspace_root):
            call_order.append("write_types")
            # Don't actually scan — just verify it's called
            return None

        monkeypatch.setattr(orchestrator, "_write_subagent_type_dirs", tracking_write)
        monkeypatch.setattr(
            orchestrator,
            "_copy_all_snapshots_to_temp_workspace",
            AsyncMock(return_value="/tmp/temp_ws"),
        )
        monkeypatch.setattr(
            orchestrator,
            "_call_subagent_mcp_tool_async",
            AsyncMock(
                side_effect=lambda *a, **kw: (
                    call_order.append("spawn_call"),
                    {"success": True, "results": [{"subagent_id": "round_eval_r2", "answer": "critique"}]},
                )[1],
            ),
        )
        monkeypatch.setattr(orchestrator, "_emit_round_evaluator_spawn_event", lambda **kw: None)
        monkeypatch.setattr(orchestrator, "_queue_round_start_context_block", lambda *a: None)

        await orchestrator._run_round_evaluator_pre_round_if_needed(
            answers={agent_id: "draft answer v1"},
        )

        # _write_subagent_type_dirs MUST be called BEFORE _call_subagent_mcp_tool_async
        assert "write_types" in call_order, "subagent types were not re-written before spawn"
        assert "spawn_call" in call_order, "spawn_subagents was not called"
        assert call_order.index("write_types") < call_order.index("spawn_call"), f"write_types must come before spawn_call, got: {call_order}"

        # CONTEXT.md must also be written for the SubagentManager
        context_md = ws_root / "CONTEXT.md"
        assert context_md.exists(), "CONTEXT.md was not created in workspace for round evaluator"
        content = context_md.read_text()
        assert "draft answer" not in content  # Should have the task, not the answer
        assert "Task coordination" in content or (orchestrator.current_task and orchestrator.current_task in content)

        # Subagent MCP config files must be re-written (workspace clear removes them)
        mcp_dir = ws_root / ".massgen" / "subagent_mcp"
        assert (mcp_dir / f"{agent_id}_agent_configs.json").exists(), "agent_configs.json not re-written before evaluator spawn"


@pytest.mark.asyncio
async def test_round_evaluator_auto_injects_when_next_tasks_exist_without_legacy_improvements(
    mock_orchestrator,
    monkeypatch,
    tmp_path,
):
    """Valid next_tasks alone should trigger auto-injection and compact handoff."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"

    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    temp_root = workspace_root / "temp"
    temp_root.mkdir()

    fs_mgr = SimpleNamespace(
        get_workspace_root=lambda: str(workspace_root),
        get_current_workspace=lambda: str(workspace_root),
        agent_temporary_workspace=str(temp_root),
        cwd=str(workspace_root),
    )
    orchestrator.agents[agent_id].backend.filesystem_manager = fs_mgr

    orchestrator.agent_states[agent_id].answer = "draft answer v1"
    orchestrator.coordination_tracker.add_agent_answer(
        agent_id=agent_id,
        answer="draft answer v1",
    )

    eval_workspace = tmp_path / "round-eval-workspace"
    eval_workspace.mkdir()
    (eval_workspace / "critique_packet.md").write_text(
        "# Critique Packet\n\nAuthoritative evaluator packet.",
        encoding="utf-8",
    )
    (eval_workspace / "verdict.json").write_text(
        json.dumps({"schema_version": "1", "verdict": "iterate", "scores": {"E1": 4}}, indent=2),
        encoding="utf-8",
    )
    (eval_workspace / "next_tasks.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "objective": "Refocus the work",
                "primary_strategy": "angle_first",
                "why_this_strategy": "It addresses the weakest criteria directly",
                "deprioritize_or_remove": ["generic closing stanza"],
                "execution_scope": {"active_chunk": "c1"},
                "tasks": [
                    {
                        "id": "rewrite_core",
                        "description": "Rewrite the core structure around one governing angle",
                        "priority": "high",
                        "depends_on": [],
                        "chunk": "c1",
                        "verification": "The new draft has a clear governing angle",
                        "verification_method": "Read stanza 1 and confirm the angle is visible",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        orchestrator,
        "_copy_all_snapshots_to_temp_workspace",
        AsyncMock(return_value=str(tmp_path / "temp_snapshots")),
    )
    monkeypatch.setattr(orchestrator, "_emit_round_evaluator_spawn_event", lambda **_kw: None)

    injected_task_plan: list[dict] = []

    def capture_injection(agent_id_arg: str, task_plan: list[dict]) -> None:
        assert agent_id_arg == agent_id
        injected_task_plan.extend(task_plan)

    monkeypatch.setattr(orchestrator, "_write_planning_injection", capture_injection)

    queued_blocks: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "_queue_round_start_context_block",
        lambda _agent_id, block: queued_blocks.append(block),
    )
    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        AsyncMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "subagent_id": "round_eval_r2",
                        "status": "completed",
                        "success": True,
                        "answer": "Short summary only.",
                        "workspace": str(eval_workspace),
                    },
                ],
            },
        ),
    )

    result = await orchestrator._run_round_evaluator_pre_round_if_needed(
        answers={agent_id: "draft answer v1"},
    )

    assert result is True
    assert injected_task_plan and injected_task_plan[0]["id"] == "rewrite_core"
    assert queued_blocks, "expected a round-start context block to be queued"
    block = queued_blocks[0]
    assert "get_task_plan" in block
    assert "Critique Packet" in block
    assert "<evaluator_summary" in block
    assert "submit_checklist" in block and "do not call" in block.lower()
    assert "propose_improvements" in block and "do not call" in block.lower()
    assert str(eval_workspace / "critique_packet.md") in block
    assert str(eval_workspace / "verdict.json") in block
    assert str(eval_workspace / "next_tasks.json") in block


@pytest.mark.asyncio
async def test_round_evaluator_auto_injects_when_next_tasks_exist_only_in_nested_final_artifact(
    mock_orchestrator,
    monkeypatch,
    tmp_path,
):
    """Nested final presenter artifacts should still drive auto-injection."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"

    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    temp_root = workspace_root / "temp"
    temp_root.mkdir()

    fs_mgr = SimpleNamespace(
        get_workspace_root=lambda: str(workspace_root),
        get_current_workspace=lambda: str(workspace_root),
        agent_temporary_workspace=str(temp_root),
        cwd=str(workspace_root),
    )
    orchestrator.agents[agent_id].backend.filesystem_manager = fs_mgr

    orchestrator.agent_states[agent_id].answer = "draft answer v1"
    orchestrator.coordination_tracker.add_agent_answer(
        agent_id=agent_id,
        answer="draft answer v1",
    )

    eval_workspace = tmp_path / "round-eval-workspace"
    eval_workspace.mkdir()
    (eval_workspace / "critique_packet.md").write_text(
        "# Critique Packet\n\nAuthoritative evaluator packet.",
        encoding="utf-8",
    )
    (eval_workspace / "verdict.json").write_text(
        json.dumps({"schema_version": "1", "verdict": "iterate", "scores": {"E1": 4}}, indent=2),
        encoding="utf-8",
    )
    nested_final = eval_workspace / ".massgen" / "massgen_logs" / "log_123" / "turn_1" / "final" / "eval_codex" / "workspace"
    nested_final.mkdir(parents=True)
    (nested_final / "next_tasks.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "objective": "Refocus the work",
                "primary_strategy": "angle_first",
                "why_this_strategy": "It addresses the weakest criteria directly",
                "deprioritize_or_remove": ["generic closing stanza"],
                "execution_scope": {"active_chunk": "c1"},
                "tasks": [
                    {
                        "id": "rewrite_core",
                        "description": "Rewrite the core structure around one governing angle",
                        "priority": "high",
                        "depends_on": [],
                        "chunk": "c1",
                        "verification": "The new draft has a clear governing angle",
                        "verification_method": "Read stanza 1 and confirm the angle is visible",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        orchestrator,
        "_copy_all_snapshots_to_temp_workspace",
        AsyncMock(return_value=str(tmp_path / "temp_snapshots")),
    )
    monkeypatch.setattr(orchestrator, "_emit_round_evaluator_spawn_event", lambda **_kw: None)

    injected_task_plan: list[dict] = []

    def capture_injection(agent_id_arg: str, task_plan: list[dict]) -> None:
        assert agent_id_arg == agent_id
        injected_task_plan.extend(task_plan)

    monkeypatch.setattr(orchestrator, "_write_planning_injection", capture_injection)

    queued_blocks: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "_queue_round_start_context_block",
        lambda _agent_id, block: queued_blocks.append(block),
    )
    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        AsyncMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "subagent_id": "round_eval_r2",
                        "status": "completed",
                        "success": True,
                        "answer": "Short summary only.",
                        "workspace": str(eval_workspace),
                    },
                ],
            },
        ),
    )

    result = await orchestrator._run_round_evaluator_pre_round_if_needed(
        answers={agent_id: "draft answer v1"},
    )

    assert result is True
    assert injected_task_plan and injected_task_plan[0]["id"] == "rewrite_core"
    assert queued_blocks, "expected a round-start context block to be queued"
    block = queued_blocks[0]
    assert "get_task_plan" in block
    assert "Critique Packet" in block
    assert "<evaluator_summary" in block


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


def test_round_evaluator_task_brief_includes_parent_delegate_targets(mock_orchestrator):
    """The evaluator should see what the parent can delegate to next round."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Build a product website."
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = [
        "round_evaluator",
        "builder",
        "critic",
    ]

    task = orchestrator._build_round_evaluator_task(
        parent_agent_id="agent_a",
        answers={"agent_a": "answer v1"},
    )

    assert "PARENT DELEGATION OPTIONS" in task
    assert "builder" in task
    assert "critic" in task
    assert "these specialized subagents: builder, critic" in task
    assert "Do not emit `round_evaluator` as a delegate target." in task
    assert "parent can delegate" in task.lower()
    assert "not by whether you can spawn subagents inside this evaluator run" in task.lower()


def test_round_evaluator_task_brief_reports_no_parent_delegate_targets(mock_orchestrator):
    """When the parent has no usable delegate targets, the evaluator should be told explicitly."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Build a product website."
    orchestrator.config.coordination_config.enable_subagents = False
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator", "builder"]

    task = orchestrator._build_round_evaluator_task(
        parent_agent_id="agent_a",
        answers={"agent_a": "answer v1"},
    )

    assert "PARENT DELEGATION OPTIONS" in task
    assert "No parent-specialized subagents are available for delegation in the next round." in task


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
    tmp_path,
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

    # Mock backend must look like it supports programmatic MCP for the gate guard
    backend._execute_mcp_function_with_retry = AsyncMock()

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
    eval_workspace = tmp_path / "round-eval-workspace"
    eval_workspace.mkdir()
    (eval_workspace / "critique_packet.md").write_text(
        "ROUND_EVAL_PACKET: critical improvement spec",
        encoding="utf-8",
    )
    (eval_workspace / "verdict.json").write_text(
        json.dumps({"schema_version": "1", "verdict": "iterate", "scores": {"E1": 4}}, indent=2),
        encoding="utf-8",
    )

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
                        "answer": "Short summary only.",
                        "workspace": str(eval_workspace),
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
    assert any("temp_workspaces" in p for p in spawn_params["tasks"][0]["context_paths"])

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
async def test_round_evaluator_single_failure_terminates_coordination(
    mock_orchestrator,
    monkeypatch,
):
    """A single round_evaluator launch failure should immediately stop coordination (no retries)."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Terminate on first evaluator failure."
    agent_id = next(iter(orchestrator.agents.keys()))

    orchestrator.config.voting_sensitivity = "checklist_gated"
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    # Mock backend must look like it supports programmatic MCP for the gate guard
    backend = orchestrator.agents[agent_id].backend
    backend._execute_mcp_function_with_retry = AsyncMock()

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

        raise AssertionError("Round 2 should not start after evaluator failure")

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    async def fake_subagent_call(
        parent_agent_id: str,
        tool_name: str,
        params: dict[str, object],
    ):
        _ = params
        assert parent_agent_id == agent_id
        assert tool_name == "spawn_subagents"
        sequence.append(("gate", False))
        return {
            "success": False,
            "operation": "spawn_subagents",
            "error": "evaluator launch failure",
        }

    monkeypatch.setattr(
        orchestrator,
        "_call_subagent_mcp_tool_async",
        fake_subagent_call,
    )

    monkeypatch.setattr("massgen.orchestrator.asyncio.sleep", AsyncMock())

    votes: dict[str, dict[str, object]] = {}
    async for _chunk in orchestrator._stream_coordination_with_agents(votes, {}):
        pass

    # Single failure → terminal, no retry
    assert sequence == [
        ("stream", {}),
        ("gate", False),
    ]
    assert stream_call_count["count"] == 1
    assert orchestrator.agent_states[agent_id].is_killed is True


@pytest.mark.asyncio
async def test_round_evaluator_persistent_failure_stops_after_retry_limit(
    mock_orchestrator,
    monkeypatch,
):
    """Persistent evaluator launch failures should stop coordination instead of looping forever."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.current_task = "Stop after repeated evaluator launch failures."
    agent_id = next(iter(orchestrator.agents.keys()))

    orchestrator.config.voting_sensitivity = "checklist_gated"
    orchestrator.config.coordination_config.round_evaluator_before_checklist = True
    orchestrator.config.coordination_config.orchestrator_managed_round_evaluator = True
    orchestrator.config.coordination_config.enable_subagents = True
    orchestrator.config.coordination_config.subagent_types = ["round_evaluator"]

    backend = orchestrator.agents[agent_id].backend
    backend._execute_mcp_function_with_retry = AsyncMock()

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

        raise AssertionError("Round 2 should not start after repeated evaluator launch failures")

    monkeypatch.setattr(orchestrator, "_stream_agent_execution", fake_stream_agent_execution)

    async def fake_subagent_call(
        parent_agent_id: str,
        tool_name: str,
        params: dict[str, object],
    ):
        _ = params
        assert parent_agent_id == agent_id
        assert tool_name == "spawn_subagents"
        if len([entry for entry in sequence if entry[0] == "gate"]) >= 1:
            raise AssertionError("Round evaluator gate retried more than the retry limit")
        sequence.append(("gate", False))
        return {
            "success": False,
            "operation": "spawn_subagents",
            "error": "persistent evaluator launch failure",
        }

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
    ]
    assert stream_call_count["count"] == 1
    assert sleep_calls == []
    assert orchestrator.agent_states[agent_id].is_killed is True
    from massgen.coordination_tracker import EventType as TrackerEventType

    assert any(event.event_type == TrackerEventType.AGENT_ERROR for event in orchestrator.coordination_tracker.events)


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


class TestDetermineFinalAgentSelectsMostRecent:
    """Fallback agent selection should pick the agent with the latest timestamp."""

    def test_selects_agent_with_latest_timestamp(self, mock_orchestrator):
        """When no winner/votes, pick the agent whose most recent answer has the latest timestamp."""
        orchestrator = mock_orchestrator(num_agents=2)

        # Give both agents answers in agent_states
        orchestrator.agent_states["agent_a"].answer = "Answer from A"
        orchestrator.agent_states["agent_b"].answer = "Answer from B"

        # Register answers in coordination_tracker with different timestamps
        # agent_a answered first (earlier timestamp)
        answer_a = AgentAnswer(agent_id="agent_a", content="Answer from A", timestamp=1000.0)
        answer_a.label = "A1.1"
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [answer_a]

        # agent_b answered later (later timestamp) — should be selected
        answer_b = AgentAnswer(agent_id="agent_b", content="Answer from B", timestamp=2000.0)
        answer_b.label = "B1.1"
        orchestrator.coordination_tracker.answers_by_agent["agent_b"] = [answer_b]

        result = orchestrator._determine_final_agent_from_states()
        assert result == "agent_b"

    def test_selects_agent_with_latest_among_multiple_answers(self, mock_orchestrator):
        """When agents have multiple answers, compare their most recent timestamps."""
        orchestrator = mock_orchestrator(num_agents=2)

        orchestrator.agent_states["agent_a"].answer = "Answer A v2"
        orchestrator.agent_states["agent_b"].answer = "Answer B v1"

        # agent_a has two answers, latest at t=3000
        a1 = AgentAnswer(agent_id="agent_a", content="A v1", timestamp=1000.0)
        a1.label = "A1.1"
        a2 = AgentAnswer(agent_id="agent_a", content="A v2", timestamp=3000.0)
        a2.label = "A1.2"
        orchestrator.coordination_tracker.answers_by_agent["agent_a"] = [a1, a2]

        # agent_b has one answer at t=2000 — earlier than agent_a's latest
        b1 = AgentAnswer(agent_id="agent_b", content="B v1", timestamp=2000.0)
        b1.label = "B1.1"
        orchestrator.coordination_tracker.answers_by_agent["agent_b"] = [b1]

        result = orchestrator._determine_final_agent_from_states()
        assert result == "agent_a"

    def test_falls_back_when_no_tracker_answers(self, mock_orchestrator):
        """When coordination_tracker has no answers, fall back to first agent with answer."""
        orchestrator = mock_orchestrator(num_agents=2)

        orchestrator.agent_states["agent_a"].answer = "Answer from A"
        orchestrator.agent_states["agent_b"].answer = "Answer from B"
        # Don't register any answers in coordination_tracker
        orchestrator.coordination_tracker.answers_by_agent = {}

        result = orchestrator._determine_final_agent_from_states()
        # Should still return something (first agent as fallback)
        assert result is not None


class TestEnsureFinalDirectoryOnShutdown:
    """On SIGTERM/timeout, the orchestrator should create a final/ directory."""

    def test_creates_final_directory_from_snapshot_storage(self, mock_orchestrator, tmp_path):
        """When an agent has snapshot_storage with content, final/ should be created."""
        from unittest.mock import patch

        orchestrator = mock_orchestrator(num_agents=1)
        agent_id = "agent_a"

        # Set up agent state with an answer
        orchestrator.agent_states[agent_id].answer = "Test answer"
        # Also register in coordination tracker so _determine_final_agent works
        answer_a = AgentAnswer(agent_id=agent_id, content="Test answer", timestamp=1000.0)
        answer_a.label = "A1.1"
        orchestrator.coordination_tracker.answers_by_agent[agent_id] = [answer_a]

        # Set up snapshot_storage with content
        snapshot_dir = tmp_path / "snapshot_storage"
        snapshot_dir.mkdir()
        (snapshot_dir / "next_tasks.json").write_text('{"tasks": []}')
        (snapshot_dir / "critique_packet.md").write_text("# Critique")

        # Create a mock filesystem_manager with snapshot_storage
        fm = SimpleNamespace(
            snapshot_storage=snapshot_dir,
            cwd=str(tmp_path / "workspace"),
            get_current_workspace=lambda: str(tmp_path / "workspace"),
        )
        orchestrator.agents[agent_id].backend.filesystem_manager = fm

        # Set up log session dir
        log_dir = tmp_path / "logs" / "turn_1" / "attempt_1"
        log_dir.mkdir(parents=True)

        answers = {agent_id: {"answer": "Test answer"}}
        workspaces = {agent_id: str(tmp_path / "workspace")}

        with patch("massgen.orchestrator.get_log_session_dir", return_value=log_dir):
            orchestrator._ensure_final_directory_on_shutdown(answers, workspaces)

        final_workspace = log_dir / "final" / agent_id / "workspace"
        assert final_workspace.exists()
        assert (final_workspace / "next_tasks.json").exists()
        assert (final_workspace / "critique_packet.md").exists()
        assert (log_dir / "final" / agent_id / "answer.txt").read_text() == "Test answer"

    def test_skips_if_final_already_exists(self, mock_orchestrator, tmp_path):
        """Don't overwrite an existing final/ directory."""
        from unittest.mock import patch

        orchestrator = mock_orchestrator(num_agents=1)
        agent_id = "agent_a"
        orchestrator.agent_states[agent_id].answer = "Test answer"

        log_dir = tmp_path / "logs" / "turn_1" / "attempt_1"
        final_dir = log_dir / "final" / agent_id
        final_dir.mkdir(parents=True)
        (final_dir / "marker.txt").write_text("existing")

        answers = {agent_id: {"answer": "Test answer"}}
        workspaces = {agent_id: str(tmp_path / "workspace")}

        with patch("massgen.orchestrator.get_log_session_dir", return_value=log_dir):
            orchestrator._ensure_final_directory_on_shutdown(answers, workspaces)

        # Should not have created workspace/ subdir since final/ already existed
        assert not (final_dir / "workspace").exists()
        assert (final_dir / "marker.txt").read_text() == "existing"

    def test_skips_when_no_answers(self, mock_orchestrator, tmp_path):
        """No final/ created when there are no answers."""
        from unittest.mock import patch

        orchestrator = mock_orchestrator(num_agents=1)
        log_dir = tmp_path / "logs" / "turn_1" / "attempt_1"
        log_dir.mkdir(parents=True)

        with patch("massgen.orchestrator.get_log_session_dir", return_value=log_dir):
            orchestrator._ensure_final_directory_on_shutdown({}, {})

        assert not (log_dir / "final").exists()


class TestCancellationManagerSigterm:
    """CancellationManager should handle SIGTERM alongside SIGINT."""

    def test_registers_sigterm_handler(self):
        """SIGTERM handler should be registered during register()."""
        import signal

        from massgen.cancellation import CancellationManager

        mgr = CancellationManager()
        original_sigterm = signal.getsignal(signal.SIGTERM)

        mock_orch = SimpleNamespace(cancellation_manager=None)
        try:
            mgr.register(mock_orch, lambda r: None, multi_turn=False)
            current_sigterm = signal.getsignal(signal.SIGTERM)
            assert current_sigterm == mgr._handle_signal
        finally:
            mgr.unregister()

        # Verify original handler restored
        assert signal.getsignal(signal.SIGTERM) == original_sigterm

    def test_unregister_restores_sigterm(self):
        """unregister() should restore the original SIGTERM handler."""
        import signal

        from massgen.cancellation import CancellationManager

        mgr = CancellationManager()
        original_sigterm = signal.getsignal(signal.SIGTERM)

        mock_orch = SimpleNamespace(cancellation_manager=None)
        mgr.register(mock_orch, lambda r: None, multi_turn=False)
        mgr.unregister()

        assert signal.getsignal(signal.SIGTERM) == original_sigterm
