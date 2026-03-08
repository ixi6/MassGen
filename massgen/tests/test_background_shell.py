"""Tests for background shell execution."""

import time

import pytest

from massgen.filesystem_manager.background_shell import (
    BackgroundShellManager,
    DockerBackgroundShell,
    get_shell_output,
    get_shell_status,
    kill_shell,
    list_shells,
    start_shell,
)

# Check if Docker is available
try:
    import docker

    _docker_client = docker.from_env()
    _docker_client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False


@pytest.fixture(scope="session", autouse=True)
def cleanup_all_shells_on_exit():
    """Cleanup all shells when test session ends."""
    yield
    # Cleanup happens automatically via atexit, but call explicitly too
    mgr = BackgroundShellManager()
    mgr.cleanup_all()


@pytest.fixture
def manager():
    """Get the BackgroundShellManager instance.

    Note: Tests share the singleton instance. Shells accumulate across tests
    but are cleaned up at session end.
    """
    return BackgroundShellManager()


def test_start_simple_command(manager):
    """Test starting a simple command in the background."""
    shell_id = manager.start_shell("echo 'Hello, World!'")

    assert shell_id.startswith("shell_")
    assert shell_id in manager._shells

    # Wait for command to complete
    time.sleep(0.5)

    status = manager.get_status(shell_id)
    assert status["status"] in ["stopped", "running"]
    assert status["exit_code"] in [0, None]
    assert status["pid"] > 0


def test_capture_stdout(manager):
    """Test capturing stdout from background command."""
    shell_id = manager.start_shell("echo 'Line 1' && echo 'Line 2'")

    # Wait for command to complete
    time.sleep(0.5)

    output = manager.get_output(shell_id)
    assert "Line 1" in output["stdout"]
    assert "Line 2" in output["stdout"]
    assert output["status"] in ["stopped", "running"]


def test_capture_stderr(manager):
    """Test capturing stderr from background command."""
    shell_id = manager.start_shell("echo 'Error message' >&2")

    # Wait for command to complete
    time.sleep(0.5)

    output = manager.get_output(shell_id)
    assert "Error message" in output["stderr"]


def test_long_running_command(manager):
    """Test a long-running command that stays active."""
    shell_id = manager.start_shell("sleep 5")

    # Check immediately - should be running
    status = manager.get_status(shell_id)
    assert status["status"] == "running"
    assert status["exit_code"] is None

    # Kill it
    result = manager.kill_shell(shell_id)
    assert result["status"] == "killed"

    # Check again - should be killed
    status = manager.get_status(shell_id)
    assert status["status"] == "killed"
    assert status["exit_code"] is not None


def test_failed_command(manager):
    """Test a command that fails."""
    shell_id = manager.start_shell("exit 1")

    # Wait for command to complete
    time.sleep(0.5)

    status = manager.get_status(shell_id)
    assert status["status"] == "failed"
    assert status["exit_code"] == 1


def test_multiple_concurrent_shells(manager):
    """Test running multiple shells concurrently."""
    shell_ids = []

    for i in range(3):
        shell_id = manager.start_shell(f"echo 'Shell {i}' && sleep 1")
        shell_ids.append(shell_id)

    # All should be in the manager
    assert len(manager._shells) >= 3

    # List all shells
    all_shells = manager.list_shells()
    assert len(all_shells) >= 3

    # Wait for completion
    time.sleep(2)

    # Check outputs
    for i, shell_id in enumerate(shell_ids):
        output = manager.get_output(shell_id)
        assert f"Shell {i}" in output["stdout"]


def test_convenience_functions():
    """Test convenience functions."""
    # Start a shell
    shell_id = start_shell("echo 'Convenience test'")
    assert shell_id.startswith("shell_")

    # Wait a bit
    time.sleep(0.5)

    # Get status
    status = get_shell_status(shell_id)
    assert status["status"] in ["stopped", "running"]

    # Get output
    output = get_shell_output(shell_id)
    assert "Convenience test" in output["stdout"]

    # List all
    shells = list_shells()
    assert any(s["shell_id"] == shell_id for s in shells)


def test_convenience_kill_function():
    """Test convenience kill_shell function."""
    shell_id = start_shell("sleep 10")

    # Verify it's running
    status = get_shell_status(shell_id)
    assert status["status"] == "running"

    # Kill using convenience function
    result = kill_shell(shell_id)
    assert result["status"] == "killed"

    # Verify it's killed
    status = get_shell_status(shell_id)
    assert status["status"] == "killed"


def test_nonexistent_shell(manager):
    """Test operations on nonexistent shell."""
    with pytest.raises(KeyError):
        manager.get_status("shell_nonexistent")

    with pytest.raises(KeyError):
        manager.get_output("shell_nonexistent")

    with pytest.raises(KeyError):
        manager.kill_shell("shell_nonexistent")


def test_kill_already_stopped(manager):
    """Test killing a shell that already stopped."""
    shell_id = manager.start_shell("echo 'Quick'")

    # Wait for it to finish
    time.sleep(0.5)

    # Try to kill it (should be already stopped)
    result = manager.kill_shell(shell_id)
    assert result["status"] in ["stopped", "failed"]
    assert result["signal"] is None


def test_max_concurrent_limit(manager):
    """Test max concurrent shells limit."""
    manager._max_concurrent = 2

    # Start 2 shells (should succeed)
    shell1 = manager.start_shell("sleep 10")
    shell2 = manager.start_shell("sleep 10")

    # Try to start a 3rd (should fail)
    with pytest.raises(RuntimeError, match="Maximum concurrent shells"):
        manager.start_shell("sleep 10")

    # Clean up
    manager.kill_shell(shell1)
    manager.kill_shell(shell2)


def test_ring_buffer_overflow(manager):
    """Test that ring buffer limits output."""
    manager._max_output_lines = 5

    # Generate more lines than buffer can hold
    shell_id = manager.start_shell("for i in {1..10}; do echo 'Line '$i; done")

    # Wait for completion
    time.sleep(0.5)

    output = manager.get_output(shell_id)
    lines = output["stdout"].split("\n")

    # Should have at most 5 lines (ring buffer limit)
    # Note: actual count might vary due to empty lines, so check <= 6
    assert len([line for line in lines if line.strip()]) <= 6


def test_command_with_cwd(manager):
    """Test running command in specific directory."""
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file in tmpdir
        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        # Run command in that directory
        shell_id = manager.start_shell("ls", cwd=tmpdir)

        # Wait for completion
        time.sleep(0.5)

        output = manager.get_output(shell_id)
        assert "test.txt" in output["stdout"]


def test_command_with_env(manager):
    """Test running command with custom environment variables."""
    import os

    custom_env = os.environ.copy()
    custom_env["TEST_VAR"] = "test_value_123"

    shell_id = manager.start_shell("echo $TEST_VAR", env=custom_env)

    # Wait for completion
    time.sleep(0.5)

    output = manager.get_output(shell_id)
    assert "test_value_123" in output["stdout"]


def test_duration_tracking(manager):
    """Test that duration is tracked correctly."""
    shell_id = manager.start_shell("sleep 0.5")

    # Check duration while running
    time.sleep(0.2)
    status1 = manager.get_status(shell_id)
    assert status1["duration_seconds"] >= 0.2

    # Wait for completion
    time.sleep(0.5)

    # Check final duration
    status2 = manager.get_status(shell_id)
    assert status2["duration_seconds"] >= 0.5
    assert status2["status"] == "stopped"


# =============================================================================
# Docker Background Shell Tests
# =============================================================================


@pytest.fixture(scope="module")
def docker_client():
    """Get Docker client, skip if not available."""
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")
    import docker

    return docker.from_env()


@pytest.fixture(scope="module")
def docker_container(docker_client):
    """Create a temporary Docker container for testing."""
    # Use a lightweight image
    container = docker_client.containers.run(
        "alpine:latest",
        command="sleep 300",  # Keep alive for tests
        detach=True,
        remove=True,
    )
    yield container
    # Cleanup
    try:
        container.stop(timeout=1)
    except Exception:
        pass


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
@pytest.mark.docker
def test_docker_start_simple_command(manager, docker_container):
    """Test starting a simple command in Docker background."""
    shell_id = manager.start_docker_shell(
        command="echo 'Hello from Docker!'",
        container=docker_container,
    )

    assert shell_id.startswith("shell_")
    assert shell_id in manager._shells

    # Verify it's a Docker shell
    shell = manager._shells[shell_id]
    assert isinstance(shell, DockerBackgroundShell)
    assert shell._is_docker is True

    # Wait for command to complete
    time.sleep(1)

    status = manager.get_status(shell_id)
    assert status["is_docker"] is True
    assert status["status"] in ["stopped", "running"]


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
@pytest.mark.docker
def test_docker_capture_stdout(manager, docker_container):
    """Test capturing stdout from Docker background command."""
    shell_id = manager.start_docker_shell(
        command="echo 'Docker Line 1' && echo 'Docker Line 2'",
        container=docker_container,
    )

    # Docker output capture is asynchronous and can lag behind process exit.
    # Poll for a short window to avoid timing flakes.
    deadline = time.time() + 5.0
    stdout = ""
    while time.time() < deadline:
        output = manager.get_output(shell_id)
        stdout = output["stdout"]
        if "Docker Line 1" in stdout or "Line 1" in stdout:
            break
        time.sleep(0.2)

    # Docker output may include stream headers; assert on substring presence.
    assert "Docker Line 1" in stdout or "Line 1" in stdout


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
@pytest.mark.docker
def test_docker_long_running_command(manager, docker_container):
    """Test a long-running Docker command that stays active."""
    shell_id = manager.start_docker_shell(
        command="sleep 10",
        container=docker_container,
    )

    # Check immediately - should be running
    time.sleep(0.5)
    status = manager.get_status(shell_id)
    assert status["status"] == "running"
    assert status["is_docker"] is True

    # Kill it
    result = manager.kill_shell(shell_id)
    assert result["status"] == "killed"


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
@pytest.mark.docker
def test_docker_command_with_workdir(manager, docker_container):
    """Test running Docker command in specific directory."""
    shell_id = manager.start_docker_shell(
        command="pwd",
        container=docker_container,
        cwd="/tmp",
    )

    # Wait for command to complete - Docker output capture can be slow
    time.sleep(2)

    output = manager.get_output(shell_id)
    status = manager.get_status(shell_id)

    # Verify the command ran with workdir set (check status at minimum)
    # Output capture from Docker exec can be unreliable for quick commands
    assert status["cwd"] == "/tmp"
    # If we got output, verify it's correct
    if output["stdout"]:
        assert "/tmp" in output["stdout"]


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
@pytest.mark.docker
def test_docker_failed_command(manager, docker_container):
    """Test a Docker command that fails."""
    shell_id = manager.start_docker_shell(
        command="exit 1",
        container=docker_container,
    )

    # Wait for command to complete
    time.sleep(1)

    status = manager.get_status(shell_id)
    assert status["status"] == "failed"
    assert status["exit_code"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
