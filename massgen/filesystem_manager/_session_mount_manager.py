"""Session directory mount management for Docker containers.

This module provides session-aware volume mounting for Docker containers,
enabling all turn workspaces to be automatically visible without container
recreation between turns.
"""

from pathlib import Path
from typing import Any


class SessionMountManager:
    """Manages session directory mounting for Docker containers.

    Pre-mounts the session directory so all turn workspaces are
    automatically visible without container recreation. This enables:
    - Faster turn transitions (sub-second vs 2-5 seconds)
    - Package persistence across turns
    - Automatic visibility of new turn directories

    Example:
        >>> manager = SessionMountManager(Path(".massgen/sessions"))
        >>> manager.initialize_session("session_20251208_123456")
        >>> config = manager.get_mount_config()
        >>> # config: {"/abs/path/.massgen/sessions/session_xxx": {"bind": "...", "mode": "ro"}}
    """

    def __init__(self, session_storage_base: Path):
        """Initialize the session mount manager.

        Args:
            session_storage_base: Base directory for session storage
                (e.g., Path(".massgen/sessions"))
        """
        self.session_storage_base = session_storage_base
        self.session_id: str | None = None
        self.session_dir: Path | None = None

    def initialize_session(self, session_id: str) -> Path:
        """Create session directory, ready for mounting.

        Args:
            session_id: Unique session identifier (e.g., "session_20251208_123456")

        Returns:
            Path to the created session directory
        """
        self.session_id = session_id
        self.session_dir = self.session_storage_base / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        return self.session_dir

    def get_mount_config(self) -> dict[str, Any] | None:
        """Return Docker volume mount config for session directory.

        Returns:
            Docker volumes dict entry: {host_path: {"bind": container_path, "mode": "ro"}}
            or None if session not initialized.
        """
        if not self.session_dir:
            return None
        resolved = self.session_dir.resolve()
        return {str(resolved): {"bind": str(resolved), "mode": "ro"}}

    def get_session_dir(self) -> Path | None:
        """Get the current session directory path.

        Returns:
            Path to session directory or None if not initialized.
        """
        return self.session_dir

    def get_session_id(self) -> str | None:
        """Get the current session ID.

        Returns:
            Session ID string or None if not initialized.
        """
        return self.session_id
