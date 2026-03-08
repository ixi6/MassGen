"""Tests for workspace token isolation in FilesystemManager."""

from massgen.filesystem_manager._filesystem_manager import FilesystemManager


def test_temp_workspace_uses_workspace_token(tmp_path):
    """When workspace_token is provided, the temp workspace path should use it, not agent_id."""
    ws = tmp_path / "ws"
    ws.mkdir()
    parent = tmp_path / "temps"
    parent.mkdir()

    fm = FilesystemManager(cwd=str(ws), agent_temporary_workspace_parent=str(parent))
    fm.setup_orchestration_paths(
        agent_id="agent_a",
        workspace_token="a3f9b2c1",
        agent_temporary_workspace=str(parent),
    )

    assert fm.agent_temporary_workspace is not None
    temp_str = str(fm.agent_temporary_workspace)
    assert "agent_a" not in temp_str
    assert "a3f9b2c1" in temp_str


def test_temp_workspace_falls_back_to_agent_id_when_no_token(tmp_path):
    """When workspace_token is not provided, the temp workspace path should use agent_id (backward compat)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    parent = tmp_path / "temps"
    parent.mkdir()

    fm = FilesystemManager(cwd=str(ws), agent_temporary_workspace_parent=str(parent))
    fm.setup_orchestration_paths(
        agent_id="agent_a",
        agent_temporary_workspace=str(parent),
    )

    assert fm.agent_temporary_workspace is not None
    assert "agent_a" in str(fm.agent_temporary_workspace)
