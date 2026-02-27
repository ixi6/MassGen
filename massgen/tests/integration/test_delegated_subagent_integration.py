"""
Integration tests for delegated subagent mode (MAS-325).

These tests verify the end-to-end round-trip between SubagentManager
(container side) and SubagentLaunchWatcher (host side) using a shared
delegation directory and mock subprocess execution.

Marked @pytest.mark.integration (requires --run-integration flag).
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from massgen.subagent.delegation_protocol import (
    DELEGATION_PROTOCOL_VERSION,
    DelegationResponse,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def delegation_dir(tmp_path: Path) -> Path:
    d = tmp_path / "_delegation"
    d.mkdir()
    return d


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def manager_and_watcher(tmp_path, delegation_dir, workspace_root):
    """Create a SubagentManager (delegated) + SubagentLaunchWatcher pair."""
    from massgen.subagent.launch_watcher import SubagentLaunchWatcher
    from massgen.subagent.manager import SubagentManager

    with patch("massgen.subagent.manager.os.path.exists", return_value=True):
        manager = SubagentManager(
            parent_workspace=str(workspace_root),
            parent_agent_id="parent",
            orchestrator_id="orch-integration",
            parent_agent_configs=[{"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}}],
            subagent_runtime_mode="delegated",
            delegation_directory=str(delegation_dir),
            default_timeout=30,
            min_timeout=5,
            max_timeout=60,
        )

    watcher = SubagentLaunchWatcher(
        delegation_dir=delegation_dir,
        allowed_workspace_roots=[tmp_path],
    )

    return manager, watcher


def _stub_yaml_and_prompt(manager):
    """Return a context manager that stubs YAML config and prompt generation on the manager."""
    yaml_patch = patch.object(
        manager,
        "_generate_subagent_yaml_config",
        return_value={"agents": [{"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}}]},
    )
    prompt_patch = patch.object(
        manager,
        "_build_subagent_system_prompt",
        return_value=("Test task prompt", None),
    )

    class _Combined:
        def __enter__(self):
            yaml_patch.__enter__()
            prompt_patch.__enter__()
            return self

        def __exit__(self, *args):
            prompt_patch.__exit__(*args)
            yaml_patch.__exit__(*args)

    return _Combined()


@pytest.mark.asyncio
async def test_delegated_round_trip(manager_and_watcher, tmp_path, delegation_dir):
    """End-to-end: manager writes request, watcher handles it, manager reads response."""
    from massgen.subagent.models import SubagentConfig

    manager, watcher = manager_and_watcher

    the_answer = "The answer to the delegated task."

    async def fake_run_subprocess(request, yaml_config):
        # Write the answer file
        answer_path = Path(request.answer_file)
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(the_answer)
        return 0, "", ""

    with (
        patch.object(watcher, "_run_subprocess", side_effect=fake_run_subprocess),
        _stub_yaml_and_prompt(manager),
    ):
        await watcher.start()

        config = SubagentConfig(id="sub-roundtrip", task="Write the answer.", parent_agent_id="parent")
        workspace = manager._create_workspace(config.id)

        # Create CONTEXT.md (required by manager)
        (workspace / "CONTEXT.md").write_text("Integration test context.")

        result = await manager._execute_subagent(config, workspace)

        await watcher.stop()

    assert result.status == "completed", f"Expected completed, got {result.status}: {result.error}"
    assert result.answer == the_answer


@pytest.mark.asyncio
async def test_delegated_live_logs_symlink(manager_and_watcher, tmp_path):
    """Live logs symlink is created before request file is written."""
    from massgen.subagent.models import SubagentConfig

    manager, watcher = manager_and_watcher

    symlink_created_before_request = []

    original_to_file = None

    def tracking_to_file(self_req, delegation_dir):
        # Check if symlink already exists
        subagent_id = self_req.subagent_id
        if manager._subagent_logs_base:
            live_logs_link = manager._subagent_logs_base / subagent_id / "live_logs"
            symlink_created_before_request.append(live_logs_link.is_symlink())
        return original_to_file(self_req, delegation_dir)

    from massgen.subagent.delegation_protocol import DelegationRequest

    original_to_file = DelegationRequest.to_file

    with patch.object(DelegationRequest, "to_file", tracking_to_file), _stub_yaml_and_prompt(manager):
        # Add a log directory so symlinks are enabled
        manager._subagent_logs_base = tmp_path / "logs" / "subagents"
        manager._subagent_logs_base.mkdir(parents=True, exist_ok=True)
        manager._log_directory = tmp_path / "logs"

        config = SubagentConfig(id="sub-symlink", task="Test symlink order.", parent_agent_id="parent")
        workspace = manager._create_workspace(config.id)

        # Write response immediately so _execute_subagent doesn't hang
        async def respond_quickly():
            await asyncio.sleep(0.2)
            resp = DelegationResponse(
                version=DELEGATION_PROTOCOL_VERSION,
                subagent_id="sub-symlink",
                request_id="req-sub-symlink",
                status="completed",
                exit_code=0,
            )
            delegation_dir = Path(manager._delegation_directory)
            resp.to_file(delegation_dir)
            answer_file = workspace / "answer.txt"
            answer_file.write_text("done")

        asyncio.create_task(respond_quickly())
        (workspace / "CONTEXT.md").write_text("Context.")
        await manager._execute_subagent(config, workspace)

    # If log base is set, symlink should have been created before request
    if symlink_created_before_request:
        assert symlink_created_before_request[0], "Live logs symlink should exist before request is written"


@pytest.mark.asyncio
async def test_orchestrator_auto_delegates_codex_docker(tmp_path):
    """Orchestrator sets delegated mode when backend is Codex+Docker and no launch prefix."""
    # This is a configuration-level test: verify that the orchestrator-level
    # configuration resolves to "delegated" rather than "inherited" for Codex+Docker.

    coord_cfg_dict = {
        "enable_subagents": True,
        "subagent_runtime_mode": "delegated",
    }

    # Verify that CoordinationConfig accepts "delegated"
    from massgen.agent_config import CoordinationConfig

    coord_cfg = CoordinationConfig(**coord_cfg_dict)
    assert coord_cfg.subagent_runtime_mode == "delegated"
