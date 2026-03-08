"""
End-to-end tests for SubagentLaunchWatcher subprocess execution.

These tests run a real subprocess (a tiny Python script) to verify the full
delegation flow without requiring Docker or a running massgen instance:
  DelegationRequest -> SubagentLaunchWatcher -> subprocess -> DelegationResponse

Run with:
    uv run pytest massgen/tests/test_launch_watcher_e2e.py -v
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from massgen.subagent.delegation_protocol import (
    DELEGATION_PROTOCOL_VERSION,
    DelegationRequest,
    response_path,
)


def _make_e2e_request(
    delegation_dir: Path,
    workspace: Path,
    subagent_id: str = "e2e-sub",
    task: str = "echo hello from subagent",
    timeout_seconds: int = 30,
    yaml_config: dict | None = None,
) -> DelegationRequest:
    """Build a minimal DelegationRequest for E2E testing."""
    if yaml_config is None:
        yaml_config = {
            "agents": [{"id": "agent_a", "backend": {"type": "openai"}}],
            "orchestrator": {},
        }
    return DelegationRequest(
        version=DELEGATION_PROTOCOL_VERSION,
        subagent_id=subagent_id,
        request_id=f"req-{subagent_id}",
        task=task,
        yaml_config=yaml_config,
        answer_file=str(workspace / "answer.txt"),
        workspace=str(workspace),
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.asyncio
async def test_e2e_watcher_runs_subprocess_and_writes_response(tmp_path):
    """
    Full E2E: watcher picks up a DelegationRequest, runs a subprocess that
    writes the answer file, and writes a DelegationResponse with status=completed.

    Uses a real subprocess (python3 -c "...") so no Docker or massgen needed.
    """
    from massgen.subagent.launch_watcher import SubagentLaunchWatcher

    delegation_dir = tmp_path / "_delegation"
    delegation_dir.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    req = _make_e2e_request(delegation_dir, workspace, subagent_id="e2e-basic")
    req.to_file(delegation_dir)

    watcher = SubagentLaunchWatcher(
        delegation_dir=delegation_dir,
        allowed_workspace_roots=[tmp_path],
    )

    # Override _run_subprocess to run a trivial real subprocess instead of massgen
    answer_file = req.answer_file

    async def real_subprocess(request: DelegationRequest, yaml_config: dict) -> tuple[int, str, str]:
        cmd = [
            sys.executable,
            "-c",
            f"open({answer_file!r}, 'w').write('e2e ok')",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        return process.returncode or 0, stdout_b.decode(), stderr_b.decode()

    watcher._run_subprocess = real_subprocess

    await watcher.start()

    # Wait up to 10s for the response file
    resp_path = response_path(delegation_dir, "e2e-basic")
    for _ in range(100):
        await asyncio.sleep(0.1)
        if resp_path.exists():
            break

    await watcher.stop()

    assert resp_path.exists(), "Response file was not written"
    data = json.loads(resp_path.read_text())
    assert data["status"] == "completed", f"Expected completed, got: {data}"
    assert data["exit_code"] == 0

    answer = Path(req.answer_file)
    assert answer.exists(), "Answer file was not written by subprocess"
    assert answer.read_text() == "e2e ok"


@pytest.mark.asyncio
async def test_e2e_watcher_subprocess_nonzero_exit_writes_error_response(tmp_path):
    """
    E2E: watcher writes status=error response when subprocess exits non-zero.
    """
    from massgen.subagent.launch_watcher import SubagentLaunchWatcher

    delegation_dir = tmp_path / "_delegation"
    delegation_dir.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    req = _make_e2e_request(delegation_dir, workspace, subagent_id="e2e-fail")
    req.to_file(delegation_dir)

    watcher = SubagentLaunchWatcher(
        delegation_dir=delegation_dir,
        allowed_workspace_roots=[tmp_path],
    )

    async def failing_subprocess(request: DelegationRequest, yaml_config: dict) -> tuple[int, str, str]:
        cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        return process.returncode, stdout_b.decode(), stderr_b.decode()

    watcher._run_subprocess = failing_subprocess

    await watcher.start()

    resp_path = response_path(delegation_dir, "e2e-fail")
    for _ in range(100):
        await asyncio.sleep(0.1)
        if resp_path.exists():
            break

    await watcher.stop()

    assert resp_path.exists(), "Response file was not written"
    data = json.loads(resp_path.read_text())
    assert data["status"] == "error", f"Expected error, got: {data}"
    assert data["exit_code"] == 42


@pytest.mark.asyncio
async def test_e2e_watcher_rejected_workspace_writes_error_response(tmp_path):
    """
    E2E: request with workspace outside allowed roots gets an error response.
    """
    from massgen.subagent.launch_watcher import SubagentLaunchWatcher

    delegation_dir = tmp_path / "_delegation"
    delegation_dir.mkdir()
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    evil_workspace = tmp_path / "evil"
    evil_workspace.mkdir()

    req = _make_e2e_request(
        delegation_dir,
        evil_workspace,
        subagent_id="e2e-rejected",
    )
    req.to_file(delegation_dir)

    watcher = SubagentLaunchWatcher(
        delegation_dir=delegation_dir,
        allowed_workspace_roots=[allowed_root],
    )

    await watcher.start()

    resp_path = response_path(delegation_dir, "e2e-rejected")
    for _ in range(50):
        await asyncio.sleep(0.1)
        if resp_path.exists():
            break

    await watcher.stop()

    assert resp_path.exists(), "Error response should be written for rejected workspace"
    data = json.loads(resp_path.read_text())
    assert data["status"] == "error"
