"""Regression tests for execution traces when orchestration ends early."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from massgen import logger_config
from massgen.agent_config import AgentConfig
from massgen.backend.chat_completions import ChatCompletionsBackend
from massgen.backend.claude_code import ClaudeCodeBackend
from massgen.backend.codex import CodexBackend
from massgen.orchestrator import Orchestrator


def _reset_log_dirs(monkeypatch: pytest.MonkeyPatch, log_base: Path) -> None:
    monkeypatch.setattr(logger_config, "_LOG_BASE_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_LOG_SESSION_DIR", None)
    monkeypatch.setattr(logger_config, "_CURRENT_TURN", None)
    monkeypatch.setattr(logger_config, "_CURRENT_ATTEMPT", None)
    logger_config.set_log_base_session_dir_absolute(log_base)


def _build_backend(
    backend_kind: str,
    workspace: Path,
    temp_parent: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    if backend_kind == "chat_completions":
        return ChatCompletionsBackend(
            api_key="test-key",
            model="gpt-4o-mini",
            agent_id="agent_a",
            cwd=str(workspace),
            agent_temporary_workspace=str(temp_parent),
        )
    if backend_kind == "claude_code":
        return ClaudeCodeBackend(
            agent_id="agent_a",
            cwd=str(workspace),
            agent_temporary_workspace=str(temp_parent),
        )
    if backend_kind == "codex":
        monkeypatch.setattr(CodexBackend, "_find_codex_cli", lambda self: "/usr/bin/codex")
        monkeypatch.setattr(CodexBackend, "_has_cached_credentials", lambda self: True)
        return CodexBackend(
            agent_id="agent_a",
            cwd=str(workspace),
            agent_temporary_workspace=str(temp_parent),
        )
    raise ValueError(f"Unsupported backend kind: {backend_kind}")


def _build_orchestrator(backend: Any, snapshot_storage: Path, temp_parent: Path) -> Orchestrator:
    agent = SimpleNamespace(agent_id="agent_a", backend=backend)
    return Orchestrator(
        agents={"agent_a": agent},
        config=AgentConfig(),
        snapshot_storage=str(snapshot_storage),
        agent_temporary_workspace=str(temp_parent),
    )


@pytest.mark.parametrize(
    "backend_kind",
    ["chat_completions", "claude_code", "codex"],
)
@pytest.mark.asyncio
async def test_partial_snapshot_writes_execution_trace_for_all_backend_families(
    backend_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_log_dirs(monkeypatch, tmp_path / "logs")

    workspace = tmp_path / backend_kind / "workspace"
    workspace.mkdir(parents=True)
    temp_parent = tmp_path / backend_kind / "temp_workspaces"
    temp_parent.mkdir(parents=True)
    snapshot_storage = tmp_path / backend_kind / "snapshots"

    backend = _build_backend(backend_kind, workspace, temp_parent, monkeypatch)
    backend._clear_streaming_buffer(agent_id="agent_a")
    backend._add_reasoning_to_trace("Partial reasoning before early termination.")

    orchestrator = _build_orchestrator(backend, snapshot_storage, temp_parent)
    await orchestrator._save_agent_snapshot(
        "agent_a",
        answer_content=None,
        vote_data=None,
        is_final=False,
        context_data={"ended_early": True},
    )

    trace_path = backend.filesystem_manager.snapshot_storage / "execution_trace.md"
    assert trace_path.exists()
    trace_text = trace_path.read_text()
    assert "Partial reasoning before early termination." in trace_text


@pytest.mark.parametrize(
    "backend_kind",
    ["chat_completions", "claude_code", "codex"],
)
@pytest.mark.asyncio
async def test_timeout_without_answers_still_writes_execution_trace_for_all_backend_families(
    backend_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_log_dirs(monkeypatch, tmp_path / "logs")

    workspace = tmp_path / backend_kind / "workspace"
    workspace.mkdir(parents=True)
    temp_parent = tmp_path / backend_kind / "temp_workspaces"
    temp_parent.mkdir(parents=True)
    snapshot_storage = tmp_path / backend_kind / "snapshots"

    backend = _build_backend(backend_kind, workspace, temp_parent, monkeypatch)
    backend._clear_streaming_buffer(agent_id="agent_a")
    backend._add_reasoning_to_trace("Captured before orchestrator timeout.")

    orchestrator = _build_orchestrator(backend, snapshot_storage, temp_parent)
    orchestrator.timeout_reason = "Time limit exceeded"

    chunks = []
    async for chunk in orchestrator._handle_orchestrator_timeout():
        chunks.append(chunk)

    assert chunks[-1].type == "done"
    trace_path = backend.filesystem_manager.snapshot_storage / "execution_trace.md"
    assert trace_path.exists()
    trace_text = trace_path.read_text()
    assert "Captured before orchestrator timeout." in trace_text


@pytest.mark.parametrize(
    "backend_kind",
    ["chat_completions", "claude_code", "codex"],
)
def test_interrupted_turn_partial_result_flushes_execution_trace_for_all_backend_families(
    backend_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_log_dirs(monkeypatch, tmp_path / "logs")

    workspace = tmp_path / backend_kind / "workspace"
    workspace.mkdir(parents=True)
    temp_parent = tmp_path / backend_kind / "temp_workspaces"
    temp_parent.mkdir(parents=True)
    snapshot_storage = tmp_path / backend_kind / "snapshots"

    backend = _build_backend(backend_kind, workspace, temp_parent, monkeypatch)
    workspace_file = workspace / "interrupted_workspace_file.txt"
    workspace_file.write_text("workspace snapshot content", encoding="utf-8")
    backend._clear_streaming_buffer(agent_id="agent_a")
    backend._add_reasoning_to_trace("Interrupted turn trace flush.")

    orchestrator = _build_orchestrator(backend, snapshot_storage, temp_parent)
    partial = orchestrator.get_partial_result()
    assert partial is not None

    trace_path = backend.filesystem_manager.snapshot_storage / "execution_trace.md"
    assert trace_path.exists()
    trace_text = trace_path.read_text()
    assert "Interrupted turn trace flush." in trace_text

    # Interrupted-turn partial result should persist current workspace snapshot.
    snapshot_workspace_file = backend.filesystem_manager.snapshot_storage / "interrupted_workspace_file.txt"
    assert snapshot_workspace_file.exists()
    assert snapshot_workspace_file.read_text(encoding="utf-8") == "workspace snapshot content"

    log_session_dir = logger_config.get_log_session_dir()
    log_workspace_matches = list(
        (log_session_dir / "agent_a").glob("*/workspace/interrupted_workspace_file.txt"),
    )
    assert log_workspace_matches
