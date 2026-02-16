# -*- coding: utf-8 -*-
"""Deterministic non-API integration tests for final presentation decision paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from git import Repo

from massgen.backend.base import StreamChunk
from massgen.filesystem_manager import IsolationContextManager, ReviewResult


async def _collect_chunks(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return chunks


def _init_git_repo(path: Path, files: dict[str, str]) -> Repo:
    repo = Repo.init(path)
    with repo.config_writer() as config:
        config.set_value("user", "email", "test@test.com")
        config.set_value("user", "name", "Test")
    for rel_path, content in files.items():
        file_path = path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    repo.index.add(list(files.keys()))
    repo.index.commit("init")
    return repo


@pytest.mark.asyncio
async def test_skip_final_presentation_single_agent_with_write_paths_uses_existing_answer(
    mock_orchestrator,
    monkeypatch,
):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    orchestrator.current_task = "Finalize single-agent answer"
    orchestrator._selected_agent = agent_id
    orchestrator.agent_states[agent_id].answer = "Single-agent final answer"
    orchestrator.config.skip_voting = True
    orchestrator.config.skip_final_presentation = True
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    monkeypatch.setattr(orchestrator, "_has_write_context_paths", lambda _agent: True)
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("get_final_presentation should not run in single-agent skip path")

    monkeypatch.setattr(orchestrator, "get_final_presentation", should_not_be_called)

    chunks = await _collect_chunks(orchestrator._present_final_answer())
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert any("Single-agent final answer" in content for content in contents)
    assert chunks[-1].type == "done"
    orchestrator._save_agent_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_skip_final_presentation_multi_agent_with_write_paths_falls_through_to_presentation(
    mock_orchestrator,
    monkeypatch,
):
    orchestrator = mock_orchestrator(num_agents=2)
    agent_id = "agent_a"
    orchestrator.current_task = "Finalize multi-agent answer"
    orchestrator._selected_agent = agent_id
    orchestrator.agent_states[agent_id].answer = "Winning answer content"
    orchestrator.config.skip_voting = False
    orchestrator.config.skip_final_presentation = True

    monkeypatch.setattr(orchestrator, "_has_write_context_paths", lambda _agent: True)

    called = {"selected": None}

    async def fake_final_presentation(selected_agent_id, vote_results):
        called["selected"] = selected_agent_id
        _ = vote_results
        yield StreamChunk(type="content", content="Presented via final presentation")
        yield StreamChunk(type="done")

    monkeypatch.setattr(orchestrator, "get_final_presentation", fake_final_presentation)

    chunks = await _collect_chunks(orchestrator._present_final_answer())
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert called["selected"] == agent_id
    assert any("Presented via final presentation" in content for content in contents)


@pytest.mark.asyncio
async def test_skip_final_presentation_multi_agent_without_write_paths_uses_existing_answer(
    mock_orchestrator,
    monkeypatch,
):
    orchestrator = mock_orchestrator(num_agents=2)
    agent_id = "agent_a"
    orchestrator.current_task = "Skip final presentation in multi-agent no-write mode"
    orchestrator._selected_agent = agent_id
    orchestrator.agent_states[agent_id].answer = "Existing winning answer"
    orchestrator.config.skip_voting = False
    orchestrator.config.skip_final_presentation = True
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")

    monkeypatch.setattr(orchestrator, "_has_write_context_paths", lambda _agent: False)
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)

    async def should_not_be_called(*_args, **_kwargs):
        raise AssertionError("get_final_presentation should be skipped when no write paths exist")

    monkeypatch.setattr(orchestrator, "get_final_presentation", should_not_be_called)

    chunks = await _collect_chunks(orchestrator._present_final_answer())
    contents = [getattr(c, "content", "") for c in chunks if getattr(c, "type", None) == "content"]

    assert any("Existing winning answer" in content for content in contents)
    assert chunks[-1].type == "done"
    orchestrator._save_agent_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_final_presentation_enables_context_write_access(mock_orchestrator, monkeypatch):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]
    orchestrator.current_task = "Final presentation write enablement"
    orchestrator._selected_agent = agent_id
    orchestrator.agent_states[agent_id].answer = "Stored answer for final presentation"

    class DummyPathPermissionManager:
        def __init__(self):
            self.snapshot_calls = 0
            self.write_enabled = []
            self.compute_calls = 0

        def snapshot_writable_context_paths(self):
            self.snapshot_calls += 1

        def set_context_write_access_enabled(self, enabled):
            self.write_enabled.append(enabled)

        def compute_context_path_writes(self):
            self.compute_calls += 1
            return []

        def get_context_paths(self):
            return [{"permission": "write"}]

    class DummyFilesystemManager:
        def __init__(self, ppm):
            self.path_permission_manager = ppm
            self.docker_manager = None
            self.agent_temporary_workspace = "/tmp/agent-temp"

        def get_current_workspace(self):
            return "/tmp/agent-workspace"

    ppm = DummyPathPermissionManager()
    agent.backend.filesystem_manager = DummyFilesystemManager(ppm)
    agent.backend._planning_mode = True

    orchestrator._copy_all_snapshots_to_temp_workspace = AsyncMock(return_value="/tmp/final-snapshots")
    orchestrator._save_agent_snapshot = AsyncMock(return_value="final")
    monkeypatch.setattr(orchestrator, "save_coordination_logs", lambda: None)
    monkeypatch.setattr(
        orchestrator,
        "_get_system_message_builder",
        lambda: type(
            "DummyBuilder",
            (),
            {"build_presentation_message": lambda self, **_kwargs: "presentation system"},
        )(),
    )

    async def fake_chat(*_args, **_kwargs):
        yield StreamChunk(type="done")

    agent.chat = fake_chat

    chunks = await _collect_chunks(
        orchestrator.get_final_presentation(
            agent_id,
            {"vote_counts": {agent_id: 1}, "voter_details": {}, "is_tie": False},
        ),
    )

    assert ppm.snapshot_calls == 1
    assert ppm.write_enabled == [True]
    assert ppm.compute_calls >= 1
    assert agent.backend._planning_mode is False
    assert any(chunk.type == "status" for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_applies_uncommitted_presenter_changes(mock_orchestrator, tmp_path):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('v1')\n"})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-uncommitted",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('v2-uncommitted')\n")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (repo_path / "app.py").read_text() == "print('v2-uncommitted')\n"
    assert any("Applied 1 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_applies_committed_presenter_changes(mock_orchestrator, tmp_path):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('v1')\n"})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-committed",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('v2-committed')\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("presenter commit")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (repo_path / "app.py").read_text() == "print('v2-committed')\n"
    assert any("Applied 1 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_applies_committed_and_uncommitted_changes(mock_orchestrator, tmp_path):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(
        repo_path,
        {
            "committed.py": "print('base-committed')\n",
            "uncommitted.py": "print('base-uncommitted')\n",
        },
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-mixed",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    wt_repo = Repo(isolated_path)

    (Path(isolated_path) / "committed.py").write_text("print('committed-new')\n")
    wt_repo.git.add("-A")
    wt_repo.index.commit("manual committed change")

    (Path(isolated_path) / "uncommitted.py").write_text("print('uncommitted-new')\n")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (repo_path / "committed.py").read_text() == "print('committed-new')\n"
    assert (repo_path / "uncommitted.py").read_text() == "print('uncommitted-new')\n"
    assert any("Applied 2 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_respects_prefix_for_committed_changes(mock_orchestrator, tmp_path):
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(
        repo_path,
        {
            "root.txt": "root-base\n",
            "inside/dir/allowed.txt": "allowed-base\n",
        },
    )
    context_path = repo_path / "inside" / "dir"

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-prefix-committed",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(context_path), agent_id=agent_id)
    (Path(isolated_path) / "inside" / "dir" / "allowed.txt").write_text("allowed-updated\n")
    (Path(isolated_path) / "root.txt").write_text("root-updated\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("commit both files")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (context_path / "allowed.txt").read_text() == "allowed-updated\n"
    assert (repo_path / "root.txt").read_text() == "root-base\n"
    assert any("Applied 1 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_applies_selected_hunks_only(mock_orchestrator, tmp_path):
    """Review metadata with approved_hunks_by_context should apply only selected hunks."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    original_lines = [f"line {i}\n" for i in range(1, 13)]
    _init_git_repo(repo_path, {"app.py": "".join(original_lines)})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-hunk-apply",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    updated_lines = original_lines.copy()
    updated_lines[1] = "line two changed\n"
    updated_lines[10] = "line eleven changed\n"
    (Path(isolated_path) / "app.py").write_text("".join(updated_lines))

    context_path = str(repo_path.resolve())

    class _DisplayStub:
        async def show_change_review_modal(self, _changes):
            return ReviewResult(
                approved=True,
                metadata={
                    "selection_mode": "selected",
                    "approved_files_by_context": {context_path: ["app.py"]},
                    "approved_hunks_by_context": {context_path: {"app.py": [0]}},
                },
            )

    orchestrator.coordination_ui = SimpleNamespace(display=_DisplayStub())

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    final_lines = (repo_path / "app.py").read_text().splitlines(keepends=True)
    assert final_lines[1] == "line two changed\n"
    assert final_lines[10] == "line 11\n"
    assert any("Applied 1 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_builds_on_dirty_source_baseline(mock_orchestrator, tmp_path):
    """Presenter edits should build on source dirty state, not clean HEAD snapshot."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('base')\n"})

    # Simulate user launching MassGen with unstaged local edits
    (repo_path / "app.py").write_text("print('local-dirty')\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-dirty-baseline",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)

    # Presenter modifies on top of dirty baseline and commits
    app_path = Path(isolated_path) / "app.py"
    app_path.write_text(app_path.read_text().rstrip("\n") + " + presenter\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("presenter commit on dirty baseline")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (repo_path / "app.py").read_text() == "print('local-dirty') + presenter\n"
    assert any("Applied 1 file change(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_skips_drifted_target_files(mock_orchestrator, tmp_path):
    """If source changed after baseline capture, drifted files are skipped (not overwritten)."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(
        repo_path,
        {
            "app.py": "print('base-app')\n",
            "safe.py": "print('base-safe')\n",
        },
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-drift",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)

    # Presenter changes two files.
    (Path(isolated_path) / "app.py").write_text("print('presenter-app')\n")
    (Path(isolated_path) / "safe.py").write_text("print('presenter-safe')\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("presenter updates app + safe")

    # Source drifts after baseline: app.py changed independently.
    (repo_path / "app.py").write_text("print('source-drifted-app')\n")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    # Drifted file should be preserved; safe file should still apply.
    assert (repo_path / "app.py").read_text() == "print('source-drifted-app')\n"
    assert (repo_path / "safe.py").read_text() == "print('presenter-safe')\n"
    assert any("Skipped 1 drifted file(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)
    assert any("app.py" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_prefer_presenter_policy_applies_drifted_files(mock_orchestrator, tmp_path):
    """prefer_presenter policy should apply presenter version even when target drift exists."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.config.coordination_config.drift_conflict_policy = "prefer_presenter"
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('base-app')\n"})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-drift-prefer-presenter",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('presenter-app')\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("presenter update")

    # Target drifts after baseline.
    (repo_path / "app.py").write_text("print('source-drifted-app')\n")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    assert (repo_path / "app.py").read_text() == "print('presenter-app')\n"
    assert any("Detected 1 drifted file(s)" in (getattr(chunk, "content", "") or "") for chunk in chunks)
    assert any("prefer_presenter" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_review_isolated_changes_fail_policy_blocks_apply_on_drift(mock_orchestrator, tmp_path):
    """fail policy should block apply when any drift is detected."""
    orchestrator = mock_orchestrator(num_agents=1)
    orchestrator.config.coordination_config.drift_conflict_policy = "fail"
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(
        repo_path,
        {
            "app.py": "print('base-app')\n",
            "safe.py": "print('base-safe')\n",
        },
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-review-drift-fail",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('presenter-app')\n")
    (Path(isolated_path) / "safe.py").write_text("print('presenter-safe')\n")
    wt_repo = Repo(isolated_path)
    wt_repo.git.add("-A")
    wt_repo.index.commit("presenter updates")

    # Drift one target file after baseline.
    (repo_path / "app.py").write_text("print('source-drifted-app')\n")

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    # No files should apply under fail policy.
    assert (repo_path / "app.py").read_text() == "print('source-drifted-app')\n"
    assert (repo_path / "safe.py").read_text() == "print('base-safe')\n"
    assert any("Drift conflict policy is 'fail'" in ((getattr(chunk, "error", "") or "") + (getattr(chunk, "content", "") or "")) for chunk in chunks)
    assert any("app.py" in (getattr(chunk, "content", "") or "") for chunk in chunks)


@pytest.mark.asyncio
async def test_show_workspace_modal_if_needed_opens_modal_without_workspace_path(
    mock_orchestrator,
    monkeypatch,
):
    """No-git final answer modal should still open even when workspace path is unavailable."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    orchestrator._selected_agent = agent_id
    orchestrator._final_presentation_content = "Final answer content"
    orchestrator._isolation_manager = None

    display = SimpleNamespace(
        show_final_answer_modal=AsyncMock(return_value=ReviewResult(approved=True)),
    )
    orchestrator.coordination_ui = SimpleNamespace(display=display)

    monkeypatch.setattr(orchestrator, "_resolve_final_workspace_path", lambda _agent_id: None)
    orchestrator.agents[agent_id].backend.filesystem_manager = None

    await orchestrator._show_workspace_modal_if_needed()

    display.show_final_answer_modal.assert_awaited_once()
    kwargs = display.show_final_answer_modal.await_args.kwargs
    assert kwargs["changes"] == []
    assert kwargs["answer_content"] == "Final answer content"
    assert kwargs["agent_id"] == agent_id
    assert kwargs["workspace_path"] is None


@pytest.mark.asyncio
async def test_show_workspace_modal_if_needed_opens_modal_with_empty_isolation_contexts(
    mock_orchestrator,
    monkeypatch,
):
    """Final modal should auto-open when write_mode created an isolation manager with no contexts."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    orchestrator._selected_agent = agent_id
    orchestrator._final_presentation_content = "Final answer content"
    orchestrator._isolation_manager = SimpleNamespace(list_contexts=lambda: [])

    display = SimpleNamespace(
        show_final_answer_modal=AsyncMock(return_value=ReviewResult(approved=True)),
    )
    orchestrator.coordination_ui = SimpleNamespace(display=display)

    monkeypatch.setattr(orchestrator, "_resolve_final_workspace_path", lambda _agent_id: None)
    orchestrator.agents[agent_id].backend.filesystem_manager = None

    await orchestrator._show_workspace_modal_if_needed()

    display.show_final_answer_modal.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_isolated_changes_rework_preserves_isolation(mock_orchestrator, tmp_path):
    """Rework ReviewResult preserves isolation and sets _pending_review_rework signal."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('v1')\n"})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-rework",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('v2-reworked')\n")

    # Wire up a display that returns a rework ReviewResult
    rework_result = ReviewResult(
        approved=False,
        action="rework",
        feedback="fix the import order",
    )
    display = SimpleNamespace(
        show_final_answer_modal=AsyncMock(return_value=rework_result),
    )
    orchestrator.coordination_ui = SimpleNamespace(display=display)

    chunks = await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    # Rework signal should be set on orchestrator
    assert orchestrator._pending_review_rework is not None
    assert orchestrator._pending_review_rework["action"] == "rework"
    assert orchestrator._pending_review_rework["feedback"] == "fix the import order"
    assert orchestrator._pending_review_rework["agent_id"] == agent_id

    # Status chunk should be yielded
    assert any("Rework requested" in (getattr(chunk, "content", "") or "") for chunk in chunks)

    # Source file should NOT be modified (changes not applied)
    assert (repo_path / "app.py").read_text() == "print('v1')\n"

    # Isolation worktree should still exist (preserved, not cleaned up)
    assert Path(isolated_path).exists()


@pytest.mark.asyncio
async def test_review_isolated_changes_quick_fix_preserves_isolation(mock_orchestrator, tmp_path):
    """quick_fix ReviewResult also preserves isolation."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    agent = orchestrator.agents[agent_id]

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path, {"app.py": "print('v1')\n"})

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    isolation_manager = IsolationContextManager(
        session_id="test-quickfix",
        write_mode="worktree",
        workspace_path=str(workspace),
    )
    isolated_path = isolation_manager.initialize_context(str(repo_path), agent_id=agent_id)
    (Path(isolated_path) / "app.py").write_text("print('v2-quickfix')\n")

    quick_fix_result = ReviewResult(
        approved=False,
        action="quick_fix",
        feedback="add error handling",
    )
    display = SimpleNamespace(
        show_final_answer_modal=AsyncMock(return_value=quick_fix_result),
    )
    orchestrator.coordination_ui = SimpleNamespace(display=display)

    await _collect_chunks(
        orchestrator._review_isolated_changes(
            agent=agent,
            isolation_manager=isolation_manager,
            selected_agent_id=agent_id,
        ),
    )

    # Rework signal populated with quick_fix action
    assert orchestrator._pending_review_rework is not None
    assert orchestrator._pending_review_rework["action"] == "quick_fix"
    assert orchestrator._pending_review_rework["feedback"] == "add error handling"

    # Source NOT modified
    assert (repo_path / "app.py").read_text() == "print('v1')\n"

    # Isolation preserved
    assert Path(isolated_path).exists()


@pytest.mark.asyncio
async def test_show_workspace_modal_if_needed_skips_with_active_contexts(
    mock_orchestrator,
    monkeypatch,
):
    """Modal should NOT open when isolation manager has active contexts."""
    orchestrator = mock_orchestrator(num_agents=1)
    agent_id = "agent_a"
    orchestrator._selected_agent = agent_id
    orchestrator._final_presentation_content = "Final answer content"
    orchestrator._isolation_manager = SimpleNamespace(
        list_contexts=lambda: ["some-active-context"],
    )

    display = SimpleNamespace(
        show_final_answer_modal=AsyncMock(return_value=ReviewResult(approved=True)),
    )
    orchestrator.coordination_ui = SimpleNamespace(display=display)

    await orchestrator._show_workspace_modal_if_needed()

    # Modal should NOT have been called
    display.show_final_answer_modal.assert_not_awaited()
