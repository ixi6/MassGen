"""Docker diagnostics module for comprehensive error detection and reporting.

This module provides detailed diagnostics for Docker-related issues, distinguishing
between different failure modes (binary not installed, daemon not running, permission
denied, etc.) and providing platform-specific resolution steps.
"""

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DockerStatus(Enum):
    """Docker availability status codes."""

    READY = "ready"
    BINARY_NOT_INSTALLED = "binary_not_installed"
    PIP_LIBRARY_NOT_INSTALLED = "pip_library_not_installed"
    DAEMON_NOT_RUNNING = "daemon_not_running"
    PERMISSION_DENIED = "permission_denied"
    IMAGES_MISSING = "images_missing"
    CONNECTION_TIMEOUT = "connection_timeout"
    UNKNOWN_ERROR = "unknown_error"


# Platform-specific error messages and resolution steps
ERROR_MESSAGES: dict[DockerStatus, dict[str, dict[str, Any]]] = {
    DockerStatus.BINARY_NOT_INSTALLED: {
        "darwin": {
            "message": "Docker is not installed on this Mac.",
            "steps": [
                "Download Docker Desktop from: https://www.docker.com/products/docker-desktop/",
                "Open the downloaded .dmg file and drag Docker to Applications",
                "Launch Docker from Applications and complete the setup wizard",
                "Once Docker Desktop shows 'Running', try again",
            ],
        },
        "linux": {
            "message": "Docker is not installed on this system.",
            "steps": [
                "Install Docker using your package manager:",
                "  Ubuntu/Debian: sudo apt-get update && sudo apt-get install docker.io",
                "  Fedora: sudo dnf install docker",
                "  Or follow: https://docs.docker.com/engine/install/",
                "Start Docker: sudo systemctl start docker",
                "Enable on boot: sudo systemctl enable docker",
            ],
        },
        "windows": {
            "message": "Docker is not installed on Windows.",
            "steps": [
                "Download Docker Desktop from: https://www.docker.com/products/docker-desktop/",
                "Run the installer and follow the setup wizard",
                "Enable WSL 2 if prompted",
                "Restart your computer if required",
                "Launch Docker Desktop and wait for it to start",
            ],
        },
    },
    DockerStatus.PIP_LIBRARY_NOT_INSTALLED: {
        "all": {
            "message": "Docker Python library is not installed.",
            "steps": [
                "Install the Docker Python SDK:",
                "  pip install docker>=7.0.0",
                "Or if using uv:",
                "  uv pip install docker>=7.0.0",
            ],
        },
    },
    DockerStatus.DAEMON_NOT_RUNNING: {
        "darwin": {
            "message": "Docker Desktop is installed but not running.",
            "steps": [
                "Open Docker Desktop from your Applications folder",
                "Wait for Docker Desktop to show 'Running' status in the menu bar",
                "The whale icon should be steady (not animating)",
                "Try your command again once Docker is ready",
            ],
        },
        "linux": {
            "message": "Docker daemon is not running.",
            "steps": [
                "Start Docker daemon: sudo systemctl start docker",
                "Check status: sudo systemctl status docker",
                "If it fails to start, check logs: sudo journalctl -u docker",
                "Enable auto-start: sudo systemctl enable docker",
            ],
        },
        "windows": {
            "message": "Docker Desktop is installed but not running.",
            "steps": [
                "Find Docker Desktop in your Start menu and launch it",
                "Wait for the whale icon in the system tray to become steady",
                "If Docker won't start, try restarting your computer",
                "Check that WSL 2 is properly configured",
            ],
        },
    },
    DockerStatus.PERMISSION_DENIED: {
        "darwin": {
            "message": "Permission denied when accessing Docker.",
            "steps": [
                "Ensure Docker Desktop is running",
                "Try restarting Docker Desktop",
                "If issue persists, reinstall Docker Desktop",
            ],
        },
        "linux": {
            "message": "Permission denied when accessing Docker. Your user is not in the docker group.",
            "steps": [
                "Add your user to the docker group:",
                "  sudo usermod -aG docker $USER",
                "Log out and log back in (or restart your terminal)",
                "Verify with: groups | grep docker",
                "Alternative: Run commands with sudo (not recommended for regular use)",
            ],
        },
        "windows": {
            "message": "Permission denied when accessing Docker.",
            "steps": [
                "Ensure Docker Desktop is running as administrator",
                "Check that your user is in the docker-users group",
                "Try restarting Docker Desktop",
            ],
        },
    },
    DockerStatus.IMAGES_MISSING: {
        "all": {
            "message": "Required MassGen Docker images are not installed.",
            "steps": [
                "Select images below and click 'Pull Selected Images'",
            ],
        },
    },
    DockerStatus.CONNECTION_TIMEOUT: {
        "all": {
            "message": "Connection to Docker timed out.",
            "steps": [
                "Docker daemon may be slow to respond or under heavy load",
                "Wait a moment and try again",
                "If using Docker Desktop, check if it's fully started",
                "Restart Docker and try again",
            ],
        },
    },
    DockerStatus.UNKNOWN_ERROR: {
        "all": {
            "message": "An unexpected Docker error occurred.",
            "steps": [
                "Check Docker is properly installed and running",
                "Try restarting Docker",
                "Check system logs for more details",
            ],
        },
    },
}

# Default required images for MassGen
DEFAULT_REQUIRED_IMAGES = [
    "ghcr.io/massgen/mcp-runtime-sudo:latest",
    "ghcr.io/massgen/mcp-runtime:latest",
]


def _get_platform() -> str:
    """Get normalized platform name."""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "linux":
        return "linux"
    elif system == "windows":
        return "windows"
    return "linux"  # Default to Linux for unknown platforms


def _get_error_info(status: DockerStatus, plat: str) -> dict[str, Any]:
    """Get error message and steps for a status and platform."""
    status_messages = ERROR_MESSAGES.get(status, ERROR_MESSAGES[DockerStatus.UNKNOWN_ERROR])

    # Try platform-specific first, fall back to "all"
    if plat in status_messages:
        return status_messages[plat]
    elif "all" in status_messages:
        return status_messages["all"]
    else:
        # Fall back to first available
        return next(iter(status_messages.values()))


@dataclass
class DockerDiagnostics:
    """Comprehensive Docker diagnostics result."""

    status: DockerStatus
    is_available: bool
    binary_installed: bool = False
    pip_library_installed: bool = False
    daemon_running: bool = False
    has_permissions: bool = False
    images_available: dict[str, bool] = field(default_factory=dict)
    docker_version: str | None = None
    api_version: str | None = None
    platform: str = field(default_factory=_get_platform)
    error_message: str = ""
    resolution_steps: list[str] = field(default_factory=list)
    raw_error: str | None = None

    def __post_init__(self):
        """Populate error message and resolution steps if not provided."""
        if not self.error_message or not self.resolution_steps:
            info = _get_error_info(self.status, self.platform)
            if not self.error_message:
                self.error_message = info.get("message", "")
            if not self.resolution_steps:
                self.resolution_steps = info.get("steps", [])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "is_available": self.is_available,
            "binary_installed": self.binary_installed,
            "pip_library_installed": self.pip_library_installed,
            "daemon_running": self.daemon_running,
            "has_permissions": self.has_permissions,
            "images_available": self.images_available,
            "docker_version": self.docker_version,
            "api_version": self.api_version,
            "platform": self.platform,
            "error_message": self.error_message,
            "resolution_steps": self.resolution_steps,
        }

    def format_error(self, include_steps: bool = True) -> str:
        """Format error message for display.

        Args:
            include_steps: Whether to include resolution steps

        Returns:
            Formatted error string
        """
        if self.is_available:
            return ""

        lines = [f"Docker Error: {self.error_message}"]

        if include_steps and self.resolution_steps:
            lines.append("")
            lines.append("To fix this:")
            for i, step in enumerate(self.resolution_steps, 1):
                # Check if step already has numbering or is indented
                if step.startswith("  ") or step.startswith("\t"):
                    lines.append(step)
                else:
                    lines.append(f"  {i}. {step}")

        return "\n".join(lines)


def check_docker_binary() -> tuple[bool, str | None]:
    """Check if Docker binary is installed and accessible.

    Returns:
        Tuple of (is_installed, version_string)
    """
    docker_path = shutil.which("docker")
    if docker_path:
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    return False, None


def check_docker_pip_library() -> bool:
    """Check if Docker Python SDK is installed.

    Returns:
        True if docker library is importable
    """
    try:
        import docker  # noqa: F401

        return True
    except ImportError:
        return False


def check_docker_daemon() -> tuple[bool, bool, str | None]:
    """Check if Docker daemon is running and accessible.

    Returns:
        Tuple of (daemon_running, has_permissions, error_details)
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, True, None

        stderr = result.stderr.lower()
        stdout = result.stdout.lower()
        combined = stderr + stdout

        # Check for permission denied
        if "permission denied" in combined or "connect: permission denied" in combined:
            return False, False, "permission_denied"

        # Check for daemon not running
        if "cannot connect" in combined or "is the docker daemon running" in combined or "connection refused" in combined or "error during connect" in combined:
            return False, True, "daemon_not_running"

        return False, True, result.stderr or result.stdout

    except subprocess.TimeoutExpired:
        return False, True, "timeout"
    except FileNotFoundError:
        return False, True, "binary_not_found"
    except OSError as e:
        return False, True, str(e)


def check_docker_images(images: list[str]) -> dict[str, bool]:
    """Check which Docker images are available locally.

    Args:
        images: List of image names to check

    Returns:
        Dictionary mapping image names to availability
    """
    available = {}
    for image in images:
        try:
            result = subprocess.run(
                ["docker", "images", "-q", image],
                capture_output=True,
                text=True,
                timeout=10,
            )
            available[image] = bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            available[image] = False
    return available


def diagnose_docker(
    required_images: list[str] | None = None,
    check_images: bool = True,
) -> DockerDiagnostics:
    """Perform comprehensive Docker diagnostics.

    Args:
        required_images: List of image names to check. If None, uses defaults.
        check_images: Whether to check for required images

    Returns:
        DockerDiagnostics with full diagnostic information
    """
    if required_images is None:
        required_images = DEFAULT_REQUIRED_IMAGES

    current_platform = _get_platform()

    # Step 1: Check binary
    binary_installed, docker_version = check_docker_binary()
    if not binary_installed:
        return DockerDiagnostics(
            status=DockerStatus.BINARY_NOT_INSTALLED,
            is_available=False,
            binary_installed=False,
            platform=current_platform,
        )

    # Step 2: Check pip library
    pip_installed = check_docker_pip_library()
    if not pip_installed:
        return DockerDiagnostics(
            status=DockerStatus.PIP_LIBRARY_NOT_INSTALLED,
            is_available=False,
            binary_installed=True,
            pip_library_installed=False,
            docker_version=docker_version,
            platform=current_platform,
        )

    # Step 3: Check daemon
    daemon_running, has_permissions, error_detail = check_docker_daemon()

    if not has_permissions:
        return DockerDiagnostics(
            status=DockerStatus.PERMISSION_DENIED,
            is_available=False,
            binary_installed=True,
            pip_library_installed=True,
            daemon_running=False,
            has_permissions=False,
            docker_version=docker_version,
            platform=current_platform,
            raw_error=error_detail,
        )

    if not daemon_running:
        status = DockerStatus.CONNECTION_TIMEOUT if error_detail == "timeout" else DockerStatus.DAEMON_NOT_RUNNING
        return DockerDiagnostics(
            status=status,
            is_available=False,
            binary_installed=True,
            pip_library_installed=True,
            daemon_running=False,
            has_permissions=True,
            docker_version=docker_version,
            platform=current_platform,
            raw_error=error_detail,
        )

    # Step 4: Check images (optional)
    images_available: dict[str, bool] = {}
    if check_images and required_images:
        images_available = check_docker_images(required_images)
        has_required_images = any(images_available.values())

        if not has_required_images:
            return DockerDiagnostics(
                status=DockerStatus.IMAGES_MISSING,
                is_available=True,
                binary_installed=True,
                pip_library_installed=True,
                daemon_running=True,
                has_permissions=True,
                images_available=images_available,
                docker_version=docker_version,
                platform=current_platform,
            )

    # All checks passed
    return DockerDiagnostics(
        status=DockerStatus.READY,
        is_available=True,
        binary_installed=True,
        pip_library_installed=True,
        daemon_running=True,
        has_permissions=True,
        images_available=images_available,
        docker_version=docker_version,
        platform=current_platform,
    )


def get_docker_error_message(
    status: DockerStatus,
    platform_override: str | None = None,
    include_steps: bool = True,
) -> str:
    """Get a formatted error message for a Docker status.

    Args:
        status: The Docker status to get the message for
        platform_override: Override the detected platform
        include_steps: Whether to include resolution steps

    Returns:
        Formatted error message string
    """
    plat = platform_override or _get_platform()
    info = _get_error_info(status, plat)

    message = info.get("message", "An error occurred with Docker.")
    steps = info.get("steps", [])

    if not include_steps or not steps:
        return message

    lines = [message, "", "To fix this:"]
    for i, step in enumerate(steps, 1):
        if step.startswith("  ") or step.startswith("\t"):
            lines.append(step)
        else:
            lines.append(f"  {i}. {step}")

    return "\n".join(lines)
