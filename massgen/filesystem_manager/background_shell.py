"""
Background shell execution manager for MassGen.

Provides infrastructure for running shell commands in the background with
process management, output capture, and control capabilities.

Supports both local subprocess execution and Docker container execution.

Example usage:
    >>> manager = BackgroundShellManager()
    >>> shell_id = manager.start_shell("python train.py --epochs 100")
    >>> # Later...
    >>> status = manager.get_status(shell_id)
    >>> output = manager.get_output(shell_id)
    >>> manager.kill_shell(shell_id)

Docker usage:
    >>> manager = BackgroundShellManager()
    >>> shell_id = manager.start_docker_shell(
    ...     command="python train.py",
    ...     container_name="massgen-agent_a",
    ...     docker_client=docker_client,
    ...     work_dir="/workspace"
    ... )
"""

import atexit
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from ..logger_config import logger

# Docker is optional - only needed for Docker mode
if TYPE_CHECKING:
    pass


class RingBuffer:
    """Thread-safe ring buffer for output capture with size limit."""

    def __init__(self, maxlen: int = 10000):
        """Initialize ring buffer.

        Args:
            maxlen: Maximum number of lines to store (default: 10,000)
        """
        self._buffer = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        """Append a line to the buffer (thread-safe).

        Args:
            line: Line to append
        """
        with self._lock:
            self._buffer.append(line)

    def get_all(self) -> list[str]:
        """Get all lines from the buffer (thread-safe).

        Returns:
            List of all lines in the buffer
        """
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Clear the buffer (thread-safe)."""
        with self._lock:
            self._buffer.clear()


class BackgroundShell:
    """Represents a single background shell process."""

    def __init__(
        self,
        shell_id: str,
        command: str,
        process: subprocess.Popen,
        cwd: str | None = None,
        max_output_lines: int = 10000,
    ):
        """Initialize background shell.

        Args:
            shell_id: Unique identifier for this shell
            command: Command being executed
            process: subprocess.Popen instance
            cwd: Working directory for the command
            max_output_lines: Maximum lines to buffer (default: 10,000)
        """
        self.shell_id = shell_id
        self.command = command
        self.process = process
        self.cwd = cwd
        self.start_time = datetime.now()
        self.end_time: datetime | None = None
        self.exit_code: int | None = None

        # Output buffers
        self.stdout_buffer = RingBuffer(maxlen=max_output_lines)
        self.stderr_buffer = RingBuffer(maxlen=max_output_lines)

        # Start output capture threads
        self._stop_capture = threading.Event()
        self._stdout_thread = threading.Thread(target=self._capture_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._capture_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _capture_stdout(self) -> None:
        """Capture stdout in background thread."""
        try:
            for line in iter(self.process.stdout.readline, ""):
                if self._stop_capture.is_set():
                    break
                if line:
                    self.stdout_buffer.append(line.rstrip("\n"))
        except Exception as e:
            logger.error(f"Error capturing stdout for shell {self.shell_id}: {e}")
        finally:
            if self.process.stdout:
                self.process.stdout.close()

    def _capture_stderr(self) -> None:
        """Capture stderr in background thread."""
        try:
            for line in iter(self.process.stderr.readline, ""):
                if self._stop_capture.is_set():
                    break
                if line:
                    self.stderr_buffer.append(line.rstrip("\n"))
        except Exception as e:
            logger.error(f"Error capturing stderr for shell {self.shell_id}: {e}")
        finally:
            if self.process.stderr:
                self.process.stderr.close()

    def get_status(self) -> str:
        """Get current status of the shell.

        Returns:
            Status string: 'running', 'stopped', 'failed', or 'killed'
        """
        if self.process.poll() is None:
            return "running"
        elif self.exit_code is not None and self.exit_code < 0:
            return "killed"
        elif self.exit_code is not None and self.exit_code > 0:
            return "failed"
        else:
            return "stopped"

    def update_exit_code(self) -> int | None:
        """Update and return exit code if process has finished.

        Returns:
            Exit code if process finished, None if still running
        """
        if self.exit_code is None:
            self.exit_code = self.process.poll()
            if self.exit_code is not None and self.end_time is None:
                self.end_time = datetime.now()
        return self.exit_code

    def kill(self, signal: int = subprocess.signal.SIGTERM) -> None:
        """Kill the background process.

        Args:
            signal: Signal to send (default: SIGTERM)
        """
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal)
                # Wait a bit for graceful shutdown
                time.sleep(0.5)
                if self.process.poll() is None:
                    # Force kill if still running
                    self.process.kill()
                self.update_exit_code()
            except Exception as e:
                logger.error(f"Error killing shell {self.shell_id}: {e}")

    def cleanup(self) -> None:
        """Clean up resources."""
        self._stop_capture.set()
        if self.process.poll() is None:
            self.kill()
        # Daemon threads will terminate automatically, no need to wait
        # (joining can cause hangs if threads are blocked on readline)


class DockerBackgroundShell:
    """Represents a background shell process running inside a Docker container."""

    def __init__(
        self,
        shell_id: str,
        command: str,
        container: Any,  # docker.models.containers.Container
        exec_id: str,
        cwd: str | None = None,
        max_output_lines: int = 10000,
    ):
        """Initialize Docker background shell.

        Args:
            shell_id: Unique identifier for this shell
            command: Command being executed
            container: Docker container object
            exec_id: Docker exec instance ID
            cwd: Working directory for the command
            max_output_lines: Maximum lines to buffer (default: 10,000)
        """
        self.shell_id = shell_id
        self.command = command
        self.container = container
        self.exec_id = exec_id
        self.cwd = cwd
        self.start_time = datetime.now()
        self.end_time: datetime | None = None
        self.exit_code: int | None = None
        self._is_docker = True  # Flag to identify Docker shells

        # Output buffers
        self.stdout_buffer = RingBuffer(maxlen=max_output_lines)
        self.stderr_buffer = RingBuffer(maxlen=max_output_lines)

        # Socket for reading output
        self._socket = None
        self._stop_capture = threading.Event()
        self._capture_thread: threading.Thread | None = None

    def start_capture(self, socket: Any) -> None:
        """Start capturing output from the Docker exec socket.

        Args:
            socket: Docker exec socket for reading output
        """
        self._socket = socket
        self._capture_thread = threading.Thread(target=self._capture_output, daemon=True)
        self._capture_thread.start()

    def _capture_output(self) -> None:
        """Capture output from Docker exec in background thread."""
        try:
            # Read from the socket - Docker multiplexes stdout/stderr
            while not self._stop_capture.is_set():
                try:
                    # Set a timeout so we can check _stop_capture periodically
                    self._socket._sock.settimeout(0.5)
                    chunk = self._socket.read(4096)
                    if not chunk:
                        break
                    # Docker stream format: first 8 bytes are header
                    # [stream_type (1), 0, 0, 0, size (4)]
                    # For simplicity, we'll treat all output as stdout
                    decoded = chunk.decode("utf-8", errors="replace")
                    for line in decoded.splitlines():
                        # Skip Docker stream headers (binary data)
                        if line and not line.startswith("\x01") and not line.startswith("\x02"):
                            self.stdout_buffer.append(line)
                except TimeoutError:
                    continue
                except Exception as e:
                    if not self._stop_capture.is_set():
                        logger.debug(f"Docker output capture ended: {e}")
                    break
        except Exception as e:
            logger.error(f"Error capturing Docker output for shell {self.shell_id}: {e}")
        finally:
            self._update_exit_code()

    def _update_exit_code(self) -> None:
        """Check and update exit code from Docker exec."""
        if self.exit_code is None:
            try:
                # Inspect the exec instance to get exit code
                exec_info = self.container.client.api.exec_inspect(self.exec_id)
                if exec_info.get("Running", True) is False:
                    self.exit_code = exec_info.get("ExitCode", 0)
                    if self.end_time is None:
                        self.end_time = datetime.now()
            except Exception as e:
                logger.debug(f"Could not inspect Docker exec {self.exec_id}: {e}")

    def get_status(self) -> str:
        """Get current status of the shell.

        Returns:
            Status string: 'running', 'stopped', 'failed', or 'killed'
        """
        self._update_exit_code()

        if self.exit_code is None:
            # Check if exec is still running
            try:
                exec_info = self.container.client.api.exec_inspect(self.exec_id)
                if exec_info.get("Running", False):
                    return "running"
                self.exit_code = exec_info.get("ExitCode", 0)
                if self.end_time is None:
                    self.end_time = datetime.now()
            except Exception:
                pass

        if self.exit_code is None:
            return "running"
        elif self.exit_code < 0:
            return "killed"
        elif self.exit_code > 0:
            return "failed"
        else:
            return "stopped"

    def update_exit_code(self) -> int | None:
        """Update and return exit code if process has finished.

        Returns:
            Exit code if process finished, None if still running
        """
        self._update_exit_code()
        return self.exit_code

    def kill(self, signal: int = 15) -> None:  # 15 = SIGTERM
        """Kill the background process in the container.

        Args:
            signal: Signal to send (default: SIGTERM=15)
        """
        if self.get_status() == "running":
            try:
                # Find the PID inside the container and kill it
                exec_info = self.container.client.api.exec_inspect(self.exec_id)
                pid = exec_info.get("Pid", 0)
                if pid > 0:
                    # Kill the process inside the container
                    self.container.exec_run(f"kill -{signal} {pid}", detach=True)
                    time.sleep(0.5)
                    # Force kill if still running
                    if self.get_status() == "running":
                        self.container.exec_run(f"kill -9 {pid}", detach=True)
                self.exit_code = -signal  # Negative signal indicates killed
                self.end_time = datetime.now()
            except Exception as e:
                logger.error(f"Error killing Docker shell {self.shell_id}: {e}")

    def cleanup(self) -> None:
        """Clean up resources."""
        self._stop_capture.set()
        if self.get_status() == "running":
            self.kill()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

    @property
    def process(self) -> None:
        """Compatibility property - Docker shells don't have a subprocess.

        Returns None but allows code to check `shell.process.pid` safely.
        """
        return None


class BackgroundShellManager:
    """Manager for background shell processes."""

    _instance: Optional["BackgroundShellManager"] = None
    _lock = threading.RLock()

    def __new__(cls):
        """Singleton pattern to ensure single manager instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initialize the background shell manager."""
        if self._initialized:
            return

        self._shells: dict[str, BackgroundShell] = {}
        self._shells_lock = threading.RLock()
        self._max_concurrent = 10  # Default max concurrent shells
        self._max_output_lines = 10000  # Default max output lines per shell

        # Register cleanup on exit
        atexit.register(self.cleanup_all)

        self._initialized = True
        logger.info("BackgroundShellManager initialized")

    def start_shell(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Start a command in the background.

        Args:
            command: Command to execute
            cwd: Working directory (default: current directory)
            env: Environment variables (default: inherit from parent)

        Returns:
            shell_id: Unique identifier for this shell

        Raises:
            RuntimeError: If max concurrent shells limit is reached
        """
        with self._shells_lock:
            # Check concurrent limit
            active_shells = sum(1 for s in self._shells.values() if s.get_status() == "running")
            if active_shells >= self._max_concurrent:
                raise RuntimeError(f"Maximum concurrent shells ({self._max_concurrent}) reached")

            # Generate unique shell ID
            shell_id = f"shell_{uuid.uuid4().hex[:8]}"

            # Start process
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Create background shell
            bg_shell = BackgroundShell(
                shell_id=shell_id,
                command=command,
                process=process,
                cwd=cwd,
                max_output_lines=self._max_output_lines,
            )

            self._shells[shell_id] = bg_shell

            logger.info(
                f"Started background shell {shell_id}: {command[:100]}{'...' if len(command) > 100 else ''}",
            )

            return shell_id

    def start_docker_shell(
        self,
        command: str,
        container: Any,  # docker.models.containers.Container
        cwd: str | None = None,
    ) -> str:
        """Start a command in the background inside a Docker container.

        Args:
            command: Command to execute
            container: Docker container object to execute in
            cwd: Working directory inside the container

        Returns:
            shell_id: Unique identifier for this shell

        Raises:
            RuntimeError: If max concurrent shells limit is reached or Docker exec fails
        """
        with self._shells_lock:
            # Check concurrent limit
            active_shells = sum(1 for s in self._shells.values() if s.get_status() == "running")
            if active_shells >= self._max_concurrent:
                raise RuntimeError(f"Maximum concurrent shells ({self._max_concurrent}) reached")

            # Generate unique shell ID
            shell_id = f"shell_{uuid.uuid4().hex[:8]}"

            try:
                # Create exec instance with streaming
                exec_config = {
                    "cmd": ["/bin/sh", "-c", command],
                    "stdout": True,
                    "stderr": True,
                    "stdin": False,
                    "tty": False,
                }
                if cwd:
                    exec_config["workdir"] = cwd

                # Create the exec instance
                exec_id = container.client.api.exec_create(container.id, **exec_config)["Id"]

                # Start the exec and get a socket for streaming output
                socket = container.client.api.exec_start(exec_id, socket=True, detach=False)

                # Create Docker background shell
                docker_shell = DockerBackgroundShell(
                    shell_id=shell_id,
                    command=command,
                    container=container,
                    exec_id=exec_id,
                    cwd=cwd,
                    max_output_lines=self._max_output_lines,
                )

                # Start output capture
                docker_shell.start_capture(socket)

                self._shells[shell_id] = docker_shell

                logger.info(
                    f"Started Docker background shell {shell_id} in container {container.name}: " f"{command[:100]}{'...' if len(command) > 100 else ''}",
                )

                return shell_id

            except Exception as e:
                logger.error(f"Failed to start Docker background shell: {e}")
                raise RuntimeError(f"Failed to start Docker background shell: {e}")

    def get_output(self, shell_id: str) -> dict[str, Any]:
        """Get output from a background shell.

        Args:
            shell_id: Shell identifier

        Returns:
            Dictionary with stdout, stderr, and status

        Raises:
            KeyError: If shell_id not found
        """
        with self._shells_lock:
            if shell_id not in self._shells:
                raise KeyError(f"Shell {shell_id} not found")

            bg_shell = self._shells[shell_id]
            bg_shell.update_exit_code()

            return {
                "shell_id": shell_id,
                "stdout": "\n".join(bg_shell.stdout_buffer.get_all()),
                "stderr": "\n".join(bg_shell.stderr_buffer.get_all()),
                "status": bg_shell.get_status(),
                "exit_code": bg_shell.exit_code,
            }

    def get_status(self, shell_id: str) -> dict[str, Any]:
        """Get status of a background shell.

        Args:
            shell_id: Shell identifier

        Returns:
            Dictionary with status information

        Raises:
            KeyError: If shell_id not found
        """
        with self._shells_lock:
            if shell_id not in self._shells:
                raise KeyError(f"Shell {shell_id} not found")

            bg_shell = self._shells[shell_id]
            bg_shell.update_exit_code()

            duration = None
            if bg_shell.end_time:
                duration = (bg_shell.end_time - bg_shell.start_time).total_seconds()
            else:
                duration = (datetime.now() - bg_shell.start_time).total_seconds()

            # Handle both local and Docker shells
            is_docker = getattr(bg_shell, "_is_docker", False)
            if is_docker:
                # Docker shell - get PID from exec_inspect if available
                pid = None
                try:
                    exec_info = bg_shell.container.client.api.exec_inspect(bg_shell.exec_id)
                    pid = exec_info.get("Pid", None)
                except Exception:
                    pass
            else:
                # Local shell
                pid = bg_shell.process.pid

            return {
                "shell_id": shell_id,
                "status": bg_shell.get_status(),
                "exit_code": bg_shell.exit_code,
                "pid": pid,
                "command": bg_shell.command,
                "cwd": bg_shell.cwd,
                "start_time": bg_shell.start_time.isoformat(),
                "duration_seconds": round(duration, 2),
                "is_docker": is_docker,
            }

    def kill_shell(self, shell_id: str) -> dict[str, Any]:
        """Kill a background shell.

        Args:
            shell_id: Shell identifier

        Returns:
            Dictionary with kill result

        Raises:
            KeyError: If shell_id not found
        """
        with self._shells_lock:
            if shell_id not in self._shells:
                raise KeyError(f"Shell {shell_id} not found")

            bg_shell = self._shells[shell_id]

            if bg_shell.get_status() == "running":
                bg_shell.kill()
                logger.info(f"Killed background shell {shell_id}")
                return {
                    "shell_id": shell_id,
                    "status": "killed",
                    "signal": "SIGTERM",
                }
            else:
                return {
                    "shell_id": shell_id,
                    "status": bg_shell.get_status(),
                    "signal": None,
                    "message": "Process already terminated",
                }

    def list_shells(self) -> list[dict[str, Any]]:
        """List all background shells.

        Returns:
            List of shell status dictionaries
        """
        with self._shells_lock:
            return [self.get_status(shell_id) for shell_id in self._shells.keys()]

    def cleanup_all(self) -> None:
        """Clean up all background shells (called on exit)."""
        logger.info("Cleaning up all background shells...")
        with self._shells_lock:
            for shell_id in list(self._shells.keys()):
                try:
                    bg_shell = self._shells[shell_id]
                    bg_shell.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up shell {shell_id}: {e}")
        logger.info("Background shell cleanup complete")

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset the singleton for testing purposes.

        WARNING: Only use in tests! This force-resets the singleton by
        cleaning up all shells and resetting the instance.
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.cleanup_all()
                    cls._instance._shells.clear()
                except Exception as e:
                    logger.error(f"Error during testing reset: {e}")
                # Don't reset _instance itself - just clean the state
                cls._instance._initialized = True


# Convenience functions for easy import
def start_shell(command: str, cwd: str | None = None, env: dict[str, str] | None = None) -> str:
    """Start a command in the background.

    Args:
        command: Command to execute
        cwd: Working directory (default: current directory)
        env: Environment variables (default: inherit from parent)

    Returns:
        shell_id: Unique identifier for this shell
    """
    manager = BackgroundShellManager()
    return manager.start_shell(command, cwd=cwd, env=env)


def start_docker_shell(command: str, container: Any, cwd: str | None = None) -> str:
    """Start a command in the background inside a Docker container.

    Args:
        command: Command to execute
        container: Docker container object to execute in
        cwd: Working directory inside the container

    Returns:
        shell_id: Unique identifier for this shell
    """
    manager = BackgroundShellManager()
    return manager.start_docker_shell(command, container=container, cwd=cwd)


def get_shell_output(shell_id: str) -> dict[str, Any]:
    """Get output from a background shell.

    Args:
        shell_id: Shell identifier

    Returns:
        Dictionary with stdout, stderr, and status
    """
    manager = BackgroundShellManager()
    return manager.get_output(shell_id)


def get_shell_status(shell_id: str) -> dict[str, Any]:
    """Get status of a background shell.

    Args:
        shell_id: Shell identifier

    Returns:
        Dictionary with status information
    """
    manager = BackgroundShellManager()
    return manager.get_status(shell_id)


def kill_shell(shell_id: str) -> dict[str, Any]:
    """Kill a background shell.

    Args:
        shell_id: Shell identifier

    Returns:
        Dictionary with kill result
    """
    manager = BackgroundShellManager()
    return manager.kill_shell(shell_id)


def list_shells() -> list[dict[str, Any]]:
    """List all background shells.

    Returns:
        List of shell status dictionaries
    """
    manager = BackgroundShellManager()
    return manager.list_shells()
