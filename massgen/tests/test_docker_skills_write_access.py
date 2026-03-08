"""Tests for Docker skills directory write access during final presentation.

Covers:
- create_container with skills_writable=True mounts actual project dir with rw
- create_container default behavior (skills_writable=False) unchanged: temp merge, ro
- recreate_container_for_write_access passes skills_writable=True
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client that passes init checks."""
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = {"Version": "20.10.0", "ApiVersion": "1.41"}
    client.images.get.return_value = MagicMock()  # Image exists
    container = MagicMock()
    container.short_id = "abc123"
    container.status = "running"
    client.containers.run.return_value = container
    return client


@pytest.fixture
def docker_manager(mock_docker_client):
    """Create a DockerManager with mocked Docker client."""
    with patch("massgen.filesystem_manager._docker_manager.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_docker_client
        # Also need to patch the error classes for the try/except in create_container
        from massgen.filesystem_manager._docker_manager import DockerManager

        # Patch at module level
        with patch("massgen.filesystem_manager._docker_manager.DOCKER_AVAILABLE", True):
            manager = DockerManager.__new__(DockerManager)
            manager.client = mock_docker_client
            manager.image = "ghcr.io/massgen/mcp-runtime:latest"
            manager.network_mode = "none"
            manager.memory_limit = None
            manager.cpu_limit = None
            manager.enable_sudo = False
            manager.containers = {}
            manager.temp_skills_dirs = {}
            manager.instance_id = None
            manager.mount_ssh_keys = False
            manager.mount_git_config = False
            manager.mount_gh_config = False
            manager.mount_npm_config = False
            manager.mount_pypi_config = False
            manager.mount_codex_config = False
            manager.mount_claude_config = False
            manager.additional_mounts = {}
            manager.env_file_path = None
            manager.pass_env_vars = []
            manager.env_vars_from_file = []
            manager.pass_all_env = False
            manager.preinstall_python = []
            manager.preinstall_npm = []
            manager.preinstall_system = []
            return manager


# ---------------------------------------------------------------------------
# create_container: skills_writable=True mounts actual dir with rw
# ---------------------------------------------------------------------------


def test_create_container_skills_writable_mounts_actual_dir(docker_manager, tmp_path):
    """When skills_writable=True, mount actual project skills dir at container path with rw."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-skill").mkdir()
    (skills_dir / "my-skill" / "SKILL.md").write_text("test")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    docker_manager.create_container(
        agent_id="agent_a",
        workspace_path=workspace,
        skills_directory=str(skills_dir),
        skills_writable=True,
    )

    # Extract the volumes dict from the containers.run call
    call_kwargs = docker_manager.client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes")

    # The actual project skills dir should be mounted (not a temp dir)
    container_skills_path = "/home/massgen/.agent/skills"
    skills_dir_resolved = str(skills_dir.resolve())

    assert skills_dir_resolved in volumes, f"Expected actual skills dir {skills_dir_resolved} in volumes, got: {list(volumes.keys())}"
    mount = volumes[skills_dir_resolved]
    assert mount["bind"] == container_skills_path
    assert mount["mode"] == "rw"


def test_create_container_skills_writable_no_temp_dir(docker_manager, tmp_path):
    """When skills_writable=True, no temp skills dir should be created or tracked."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    docker_manager.create_container(
        agent_id="agent_a",
        workspace_path=workspace,
        skills_directory=str(skills_dir),
        skills_writable=True,
    )

    # No temp skills dir should be tracked for this agent
    assert "agent_a" not in docker_manager.temp_skills_dirs


def test_create_container_skills_writable_creates_missing_dir(docker_manager, tmp_path):
    """When skills_writable=True and skills dir doesn't exist, create it."""
    skills_dir = tmp_path / ".agent" / "skills"
    # Not created yet

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    docker_manager.create_container(
        agent_id="agent_a",
        workspace_path=workspace,
        skills_directory=str(skills_dir),
        skills_writable=True,
    )

    # The directory should have been created
    assert skills_dir.exists()


def test_create_container_sets_node_path_for_global_npm_modules(docker_manager, tmp_path):
    """Container env should expose global npm module paths for Node require() resolution."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    docker_manager.create_container(
        agent_id="agent_env",
        workspace_path=workspace,
    )

    call_kwargs = docker_manager.client.containers.run.call_args
    environment = call_kwargs.kwargs.get("environment") or call_kwargs[1].get("environment")
    assert environment is not None
    assert environment.get("NODE_PATH") == "/usr/lib/node_modules:/usr/local/lib/node_modules"


# ---------------------------------------------------------------------------
# create_container: default (skills_writable=False) unchanged
# ---------------------------------------------------------------------------


def test_create_container_default_uses_temp_merge_ro(docker_manager, tmp_path):
    """Default behavior: temp merged dir mounted at container skills path with ro."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-skill").mkdir()
    (skills_dir / "my-skill" / "SKILL.md").write_text("test")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    docker_manager.create_container(
        agent_id="agent_a",
        workspace_path=workspace,
        skills_directory=str(skills_dir),
    )

    # Extract the volumes dict
    call_kwargs = docker_manager.client.containers.run.call_args
    volumes = call_kwargs.kwargs.get("volumes") or call_kwargs[1].get("volumes")

    container_skills_path = "/home/massgen/.agent/skills"

    # Should be a temp dir (not the actual skills dir) mounted ro
    skills_dir_resolved = str(skills_dir.resolve())
    # The actual skills dir should NOT be in volumes
    assert skills_dir_resolved not in volumes, "Default behavior should use temp dir, not actual skills dir"

    # Find the mount for container_skills_path
    skills_mount = None
    for host_path, mount_config in volumes.items():
        if mount_config.get("bind") == container_skills_path:
            skills_mount = (host_path, mount_config)
            break

    assert skills_mount is not None, "Container skills path should be mounted"
    assert skills_mount[1]["mode"] == "ro", "Default skills mount should be read-only"

    # Temp dir should be tracked
    assert "agent_a" in docker_manager.temp_skills_dirs


# ---------------------------------------------------------------------------
# recreate_container_for_write_access passes skills_writable=True
# ---------------------------------------------------------------------------


def test_recreate_for_write_access_passes_skills_writable(tmp_path):
    """recreate_container_for_write_access should pass skills_writable=True to create_container."""

    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    fm = FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(tmp_path / "temp"),
        enable_mcp_command_line=False,
    )

    # Set up a mock docker manager
    mock_dm = MagicMock()
    mock_dm.create_container.return_value = None
    mock_dm.remove_container.return_value = None
    fm.docker_manager = mock_dm
    fm.agent_id = "agent_a"

    # Call recreate_container_for_write_access
    fm.recreate_container_for_write_access(
        skills_directory=str(tmp_path / ".agent" / "skills"),
    )

    # Verify create_container was called with skills_writable=True
    mock_dm.create_container.assert_called_once()
    call_kwargs = mock_dm.create_container.call_args
    assert call_kwargs.kwargs.get("skills_writable") is True or (
        len(call_kwargs.args) > 0 and "skills_writable" in str(call_kwargs)
    ), f"Expected skills_writable=True in create_container call, got: {call_kwargs}"


def test_build_credential_mounts_supports_claude_config(docker_manager, tmp_path, monkeypatch):
    """claude_config mount should map ~/.claude into /home/massgen/.claude."""
    fake_home = tmp_path / "home"
    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    docker_manager.mount_claude_config = True

    monkeypatch.setattr("massgen.filesystem_manager._docker_manager.Path.home", lambda: fake_home)

    mounts = docker_manager._build_credential_mounts()
    host_path = str(claude_dir.resolve())

    assert host_path in mounts
    assert mounts[host_path]["bind"] == "/home/massgen/.claude"
    assert mounts[host_path]["mode"] == "ro"


def test_build_credential_mounts_supports_codex_config(docker_manager, tmp_path, monkeypatch):
    """codex_config mount should map ~/.codex into /home/massgen/.codex."""
    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    docker_manager.mount_codex_config = True

    monkeypatch.setattr("massgen.filesystem_manager._docker_manager.Path.home", lambda: fake_home)

    mounts = docker_manager._build_credential_mounts()
    host_path = str(codex_dir.resolve())

    assert host_path in mounts
    assert mounts[host_path]["bind"] == "/home/massgen/.codex"
    assert mounts[host_path]["mode"] == "ro"
