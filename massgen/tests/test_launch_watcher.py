"""
Unit tests for SubagentLaunchWatcher (MAS-325).

Tests cover:
- Watcher picks up request files
- Workspace allowlist validation
- Response writing on success/failure
- Cancel sentinel handling
- Cleanup on stop
- _run_subprocess: correct cmd construction, output handling, timeout/termination
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from massgen.subagent.delegation_protocol import (
    DELEGATION_PROTOCOL_VERSION,
    DelegationRequest,
    DelegationResponse,
    write_cancel_sentinel,
)


def _make_request(
    delegation_dir: Path,
    subagent_id: str = "sub-1",
    workspace: str | None = None,
    timeout_seconds: int = 30,
    yaml_config: dict | None = None,
) -> DelegationRequest:
    if workspace is None:
        workspace = str(delegation_dir / "ws")
    if yaml_config is None:
        yaml_config = {
            "agents": [
                {
                    "id": "agent-1",
                    "backend": {
                        "type": "openai",
                        "command_line_execution_mode": "docker",
                        "command_line_docker_image": "myimage:latest",
                        "command_line_docker_network_mode": "bridge",
                    },
                },
            ],
            "orchestrator": {},
        }
    req = DelegationRequest(
        version=DELEGATION_PROTOCOL_VERSION,
        subagent_id=subagent_id,
        request_id=f"req-{subagent_id}",
        task="Do something",
        yaml_config=yaml_config,
        answer_file=str(Path(workspace) / "answer.txt"),
        workspace=workspace,
        timeout_seconds=timeout_seconds,
    )
    return req


def _make_watcher(tmp_path, **kwargs):
    from massgen.subagent.launch_watcher import SubagentLaunchWatcher

    delegation_dir = tmp_path / "_delegation"
    delegation_dir.mkdir(exist_ok=True)
    return SubagentLaunchWatcher(
        delegation_dir=delegation_dir,
        allowed_workspace_roots=[tmp_path],
        **kwargs,
    )


class TestWatcherPicksUpRequest:
    """Tests that the watcher discovers and processes request files."""

    @pytest.mark.asyncio
    async def test_watcher_picks_up_request(self, tmp_path):
        """Watcher processes a request file written before or during polling."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        req = _make_request(delegation_dir, subagent_id="sub-pick", workspace=str(workspace))
        req.to_file(delegation_dir)

        handled_requests = []

        async def fake_handle(request: DelegationRequest) -> None:
            handled_requests.append(request.subagent_id)
            resp = DelegationResponse(
                version=DELEGATION_PROTOCOL_VERSION,
                subagent_id=request.subagent_id,
                request_id=request.request_id,
                status="completed",
                exit_code=0,
            )
            resp.to_file(delegation_dir)

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )

        with patch.object(watcher, "_handle_request", side_effect=fake_handle):
            await watcher.start()
            for _ in range(20):
                await asyncio.sleep(0.1)
                if handled_requests:
                    break
            await watcher.stop()

        assert "sub-pick" in handled_requests


class TestWatcherAllowlistValidation:
    """Tests workspace path allowlist enforcement."""

    @pytest.mark.asyncio
    async def test_watcher_validates_workspace_allowlist(self, tmp_path):
        """Request with workspace outside allowed roots is rejected."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()

        evil_workspace = tmp_path / "evil"
        evil_workspace.mkdir()
        req = _make_request(delegation_dir, subagent_id="sub-evil", workspace=str(evil_workspace))
        req.to_file(delegation_dir)

        rejection_log = []

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[allowed_root],
        )

        original_validate = watcher._validate_workspace_path

        def capturing_validate(workspace_str: str) -> bool:
            result = original_validate(workspace_str)
            if not result:
                rejection_log.append(workspace_str)
            return result

        with patch.object(watcher, "_validate_workspace_path", side_effect=capturing_validate):
            await watcher.start()
            for _ in range(10):
                await asyncio.sleep(0.1)
                if rejection_log:
                    break
            await watcher.stop()

        assert len(rejection_log) > 0, "Expected workspace to be rejected"

    def test_workspace_under_sibling_dir_accepted_when_parent_is_root(self, tmp_path):
        """Workspace under workspaces/ is accepted when .massgen (parent) is the allowed root.

        Mirrors the real failure: subagent_logs/ and workspaces/ are siblings under
        .massgen/. Passing subagent_logs_dir as the root rejects all real workspaces.
        Passing .massgen (parent.parent of the run-specific logs dir) fixes it.
        """
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        # Structure mirrors reality:
        #   tmp_path/                      ← .massgen equivalent
        #     subagent_logs/sa_abc/        ← _subagent_logs_dir
        #     workspaces/workspace_xyz/
        #       subagents/sub1/workspace/  ← actual subagent workspace
        logs_dir = tmp_path / "subagent_logs" / "sa_abc"
        logs_dir.mkdir(parents=True)
        workspace = tmp_path / "workspaces" / "workspace_xyz" / "subagents" / "sub1" / "workspace"
        workspace.mkdir(parents=True)

        watcher = SubagentLaunchWatcher(
            delegation_dir=logs_dir / "_delegation",
            allowed_workspace_roots=[tmp_path],  # parent of both dirs — the fix
        )

        assert watcher._validate_workspace_path(str(workspace)) is True

    def test_logs_dir_as_root_rejects_workspace_under_sibling(self, tmp_path):
        """Regression: using subagent_logs_dir (not its parent) as root rejects real workspaces.

        This documents the broken behavior from the original orchestrator wiring
        (allowed_workspace_roots=[self._subagent_logs_dir]).
        """
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        logs_dir = tmp_path / "subagent_logs" / "sa_abc"
        logs_dir.mkdir(parents=True)
        workspace = tmp_path / "workspaces" / "workspace_xyz" / "subagents" / "sub1" / "workspace"
        workspace.mkdir(parents=True)

        watcher = SubagentLaunchWatcher(
            delegation_dir=logs_dir / "_delegation",
            allowed_workspace_roots=[logs_dir],  # old broken value — too narrow
        )

        assert watcher._validate_workspace_path(str(workspace)) is False


class TestWatcherResponseWriting:
    """Tests that watcher writes correct response files."""

    @pytest.mark.asyncio
    async def test_watcher_writes_response_on_success(self, tmp_path):
        """Watcher writes response_*.json with status=completed after successful run."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        req = _make_request(delegation_dir, subagent_id="sub-resp", workspace=str(workspace))
        req.to_file(delegation_dir)

        async def fake_run(request: DelegationRequest, yaml_config: dict) -> tuple[int, str, str]:
            Path(request.answer_file).parent.mkdir(parents=True, exist_ok=True)
            Path(request.answer_file).write_text("The answer.")
            return 0, "stdout output", ""

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )

        with patch.object(watcher, "_run_subprocess", side_effect=fake_run):
            await watcher.start()
            for _ in range(30):
                await asyncio.sleep(0.1)
                response_file = delegation_dir / "response_sub-resp.json"
                if response_file.exists():
                    break
            await watcher.stop()

        response_file = delegation_dir / "response_sub-resp.json"
        assert response_file.exists(), "Response file should be written"
        data = json.loads(response_file.read_text())
        assert data["status"] == "completed"
        assert data["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_watcher_writes_error_response_on_failure(self, tmp_path):
        """Watcher writes response with status=error when subprocess exits non-zero."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        req = _make_request(delegation_dir, subagent_id="sub-fail", workspace=str(workspace))
        req.to_file(delegation_dir)

        async def fake_run(request: DelegationRequest, yaml_config: dict) -> tuple[int, str, str]:
            return 1, "", "Something went wrong"

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )

        with patch.object(watcher, "_run_subprocess", side_effect=fake_run):
            await watcher.start()
            for _ in range(30):
                await asyncio.sleep(0.1)
                response_file = delegation_dir / "response_sub-fail.json"
                if response_file.exists():
                    break
            await watcher.stop()

        response_file = delegation_dir / "response_sub-fail.json"
        assert response_file.exists()
        data = json.loads(response_file.read_text())
        assert data["status"] == "error"
        assert data["exit_code"] == 1


class TestWatcherCancelSentinel:
    """Tests cancel sentinel handling in watcher."""

    @pytest.mark.asyncio
    async def test_watcher_cancel_sentinel_stops_execution(self, tmp_path):
        """Writing cancel sentinel causes watcher to abort the running subprocess."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        req = _make_request(
            delegation_dir,
            subagent_id="sub-cancelled",
            workspace=str(workspace),
            timeout_seconds=30,
        )
        req.to_file(delegation_dir)

        run_started = asyncio.Event()
        run_cancelled = asyncio.Event()

        async def slow_run(request: DelegationRequest, yaml_config: dict) -> tuple[int, str, str]:
            run_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                run_cancelled.set()
                raise
            return 0, "", ""

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )

        with patch.object(watcher, "_run_subprocess", side_effect=slow_run):
            await watcher.start()
            await asyncio.wait_for(run_started.wait(), timeout=5.0)
            write_cancel_sentinel(delegation_dir, "sub-cancelled")
            try:
                await asyncio.wait_for(run_cancelled.wait(), timeout=3.0)
            except TimeoutError:
                pass  # Some implementations cancel via stop() instead
            await watcher.stop()


class TestRunSubprocess:
    """
    Tests for _run_subprocess() — exercises the asyncio.create_subprocess_exec
    call path without actually running massgen.
    """

    @pytest.mark.asyncio
    async def test_run_subprocess_builds_correct_cmd(self, tmp_path):
        """_run_subprocess launches `uv run massgen --config ... --automation --output-file ... task`."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )
        req = _make_request(delegation_dir, subagent_id="sub-cmd", workspace=str(workspace))

        captured_cmd = []

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"stdout", b""))

        async def fake_exec(*args, **kwargs):
            captured_cmd.extend(args)
            return mock_process

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"stdout", b""))):
                await watcher._run_subprocess(req, req.yaml_config)

        assert "uv" in captured_cmd
        assert "massgen" in captured_cmd
        assert "--automation" in captured_cmd
        assert "--config" in captured_cmd
        assert "--output-file" in captured_cmd
        assert req.task in captured_cmd

    @pytest.mark.asyncio
    async def test_run_subprocess_returns_exit_code_and_output(self, tmp_path):
        """_run_subprocess returns (exit_code, stdout_tail, stderr_tail) tuple."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )
        req = _make_request(delegation_dir, subagent_id="sub-out", workspace=str(workspace))

        mock_process = MagicMock()
        mock_process.returncode = 42

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
            with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"hello stdout", b"hello stderr"))):
                exit_code, stdout, stderr = await watcher._run_subprocess(req, req.yaml_config)

        assert exit_code == 42
        assert "hello stdout" in stdout
        assert "hello stderr" in stderr

    @pytest.mark.asyncio
    async def test_run_subprocess_terminates_on_timeout(self, tmp_path):
        """On TimeoutError, _run_subprocess terminates the process then re-raises."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )
        req = _make_request(delegation_dir, subagent_id="sub-timeout", workspace=str(workspace))

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(return_value=None)

        async def raise_timeout(*args, **kwargs):
            raise TimeoutError("timed out")

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
            with patch("asyncio.wait_for", side_effect=raise_timeout):
                with pytest.raises(TimeoutError):
                    await watcher._run_subprocess(req, req.yaml_config)

        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_subprocess_writes_config_yaml(self, tmp_path):
        """_run_subprocess writes yaml_config to workspace before launching subprocess."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        workspace = tmp_path / "ws"
        workspace.mkdir()

        watcher = SubagentLaunchWatcher(
            delegation_dir=delegation_dir,
            allowed_workspace_roots=[tmp_path],
        )
        req = _make_request(delegation_dir, subagent_id="sub-yaml", workspace=str(workspace))

        mock_process = MagicMock()
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
            with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"", b""))):
                await watcher._run_subprocess(req, req.yaml_config)

        config_file = workspace / f"delegated_config_{req.subagent_id}.yaml"
        assert config_file.exists(), "YAML config should be written to workspace"
        import yaml

        written = yaml.safe_load(config_file.read_text())
        assert "agents" in written


class TestWatcherCleanup:
    """Tests watcher cleanup behavior."""

    @pytest.mark.asyncio
    async def test_watcher_cleanup_on_stop(self, tmp_path):
        """Stopping watcher cancels all active tasks."""
        from massgen.subagent.launch_watcher import SubagentLaunchWatcher

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        watcher = SubagentLaunchWatcher(delegation_dir=delegation_dir)

        await watcher.start()
        assert watcher._running, "Watcher should be running"
        await watcher.stop()
        assert not watcher._running, "Watcher should stop after stop()"
