"""Session registry for tracking and managing memory sessions.

This module provides functionality to:
- Log session IDs when sessions start/end
- Store session metadata (timestamp, config, model info)
- List available sessions
- Retrieve session details
"""

import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@contextmanager
def _registry_lock(lock_path: Path, exclusive: bool):
    """Cross-process file lock using fcntl (POSIX) or a no-op on Windows.

    Args:
        lock_path: Path to the lock sidecar file.
        exclusive: If True, acquire an exclusive write lock; otherwise shared read lock.
    """
    if sys.platform == "win32":
        # Windows: no fcntl; accept the risk of concurrent corruption for now.
        yield
        return

    import fcntl

    lock_file = open(lock_path, "w")
    try:
        flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), flag)
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


class SessionRegistry:
    """Registry for tracking memory sessions across MassGen runs.

    Sessions are stored in ~/.massgen/sessions.json with metadata including:
    - session_id: Unique identifier for the session
    - start_time: ISO timestamp when session started
    - end_time: ISO timestamp when session ended (if completed)
    - config_path: Path to YAML config used
    - model: Primary model used (if available)
    - status: "active" or "completed"
    - description: Optional user-provided description
    """

    def __init__(self, registry_path: str | None = None):
        """Initialize session registry.

        Args:
            registry_path: Path to registry file. Defaults to ~/.massgen/sessions.json
        """
        if registry_path:
            self.registry_path = Path(registry_path)
        else:
            massgen_dir = Path.home() / ".massgen"
            massgen_dir.mkdir(exist_ok=True)
            self.registry_path = massgen_dir / "sessions.json"

        self._ensure_registry_exists()

    def _ensure_registry_exists(self) -> None:
        """Create registry file if it doesn't exist."""
        if not self.registry_path.exists():
            self.registry_path.write_text(json.dumps({"sessions": []}, indent=2))
            logger.debug(f"Created session registry at {self.registry_path}")

    @property
    def _lock_path(self) -> Path:
        return self.registry_path.with_suffix(".lock")

    def _load_registry(self, _already_locked: bool = False) -> dict[str, list[dict[str, Any]]]:
        """Load registry from disk.

        When called from within ``_update_registry`` the caller already holds
        the exclusive lock; pass ``_already_locked=True`` to skip re-locking.
        For standalone read-only access a shared lock is acquired automatically.
        """

        def _read() -> dict:
            try:
                with open(self.registry_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load session registry: {e}. Creating new registry.")
                return {"sessions": []}

        if _already_locked:
            return _read()

        try:
            with _registry_lock(self._lock_path, exclusive=False):
                return _read()
        except OSError:
            return _read()  # Fallback if lock unavailable

    def _save_registry(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """Save registry to disk (no lock — callers must hold a lock themselves)."""
        try:
            with open(self.registry_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to save session registry: {e}")

    def _update_registry(self, update_fn):
        """Atomically read-modify-write the registry under an exclusive lock.

        Args:
            update_fn: Callable that takes the loaded registry dict and returns
                the modified dict to persist.  It must not perform I/O itself.
        """
        try:
            with _registry_lock(self._lock_path, exclusive=True):
                data = self._load_registry(_already_locked=True)
                updated = update_fn(data)
                self._save_registry(updated)
        except OSError as e:
            logger.error(f"Failed to update session registry: {e}")

    def register_session(
        self,
        session_id: str,
        config_path: str | None = None,
        model: str | None = None,
        description: str | None = None,
        subagent: bool = False,
        parent_session_id: str | None = None,
        **metadata: Any,
    ) -> None:
        """Register a new session or update existing session.

        Args:
            session_id: Unique session identifier
            config_path: Path to configuration file used
            model: Model name/ID used for the session
            description: Optional description of the session
            subagent: Whether this session belongs to a subagent
            parent_session_id: Parent session ID if this is a subagent session
            **metadata: Additional metadata to store
        """

        def _do_register(registry: dict) -> dict:
            # Check if session already exists
            existing_session = None
            for s in registry["sessions"]:
                if s["session_id"] == session_id:
                    existing_session = s
                    break

            if existing_session:
                existing_session.update(
                    {
                        "config_path": config_path,
                        "model": model,
                        "description": description,
                        "subagent": subagent,
                        "parent_session_id": parent_session_id,
                        **metadata,
                    },
                )
                logger.debug(f"Updated existing session: {session_id}")
            else:
                new_session = {
                    "session_id": session_id,
                    "start_time": datetime.now().isoformat(),
                    "end_time": None,
                    "status": "active",
                    "config_path": config_path,
                    "model": model,
                    "description": description,
                    "subagent": subagent,
                    "parent_session_id": parent_session_id,
                    **metadata,
                }
                registry["sessions"].append(new_session)
                logger.info(f"Registered new session: {session_id}")

            return registry

        self._update_registry(_do_register)

    def complete_session(self, session_id: str) -> None:
        """Mark a session as completed.

        Args:
            session_id: Session to mark as completed
        """

        def _do_complete(registry: dict) -> dict:
            for s in registry["sessions"]:
                if s["session_id"] == session_id:
                    s["end_time"] = datetime.now().isoformat()
                    s["status"] = "completed"
                    logger.info(f"Marked session as completed: {session_id}")
                    break
            return registry

        self._update_registry(_do_complete)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific session.

        Args:
            session_id: Session to retrieve

        Returns:
            Session metadata dict or None if not found
        """
        registry = self._load_registry()

        for session in registry["sessions"]:
            if session["session_id"] == session_id:
                return session

        return None

    def list_sessions(
        self,
        limit: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all registered sessions.

        Args:
            limit: Maximum number of sessions to return (most recent first)
            status: Filter by status ("active" or "completed")

        Returns:
            List of session metadata dicts
        """
        registry = self._load_registry()
        sessions = registry["sessions"]

        # Filter by status if specified
        if status:
            sessions = [s for s in sessions if s.get("status") == status]

        # Sort by start_time (most recent first)
        sessions.sort(key=lambda s: s.get("start_time", ""), reverse=True)

        # Apply limit if specified
        if limit:
            sessions = sessions[:limit]

        return sessions

    def get_most_recent_session(self) -> dict[str, Any] | None:
        """Get the most recently started session.

        Returns:
            Session metadata dict for most recent session, or None if no sessions
        """
        sessions = self.list_sessions(limit=1)
        return sessions[0] if sessions else None

    def get_most_recent_continuable_session(self) -> dict[str, Any] | None:
        """Get the most recent session that can be continued (has saved turns).

        Skips empty sessions that have no turns saved yet.
        Also skips subagent sessions (which have subagent=True flag).

        Returns:
            Session metadata dict for most recent non-empty session, or None if none found
        """
        sessions = self.list_sessions()  # Get all sessions, sorted by start_time desc

        # Filter out subagent sessions (only return user-facing sessions)
        user_sessions = [s for s in sessions if not s.get("subagent", False)]

        for session in user_sessions:
            session_id = session.get("session_id")
            if session_id and self.session_has_turns(session_id):
                return session
        return None

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists in the registry.

        Args:
            session_id: Session ID to check

        Returns:
            True if session exists, False otherwise
        """
        return self.get_session(session_id) is not None

    def session_has_turns(self, session_id: str) -> bool:
        """Check if a session has any saved turns (is non-empty).

        Args:
            session_id: Session ID to check

        Returns:
            True if session has at least one turn, False otherwise
        """
        from pathlib import Path

        # Check standard session storage location
        session_dir = Path(".massgen/sessions") / session_id
        if session_dir.exists():
            # Look for turn_N directories
            for item in session_dir.iterdir():
                if item.is_dir() and item.name.startswith("turn_"):
                    return True
        return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from the registry.

        Note: This only removes the session from the registry, not from
        the vector database. Memory data remains in Qdrant.

        Args:
            session_id: Session to delete

        Returns:
            True if session was deleted, False if not found
        """
        registry = self._load_registry()

        initial_count = len(registry["sessions"])
        registry["sessions"] = [s for s in registry["sessions"] if s["session_id"] != session_id]

        if len(registry["sessions"]) < initial_count:
            self._save_registry(registry)
            logger.info(f"Deleted session from registry: {session_id}")
            return True

        return False


def format_session_list(sessions: list[dict[str, Any]], show_all: bool = False) -> str:
    """Format session list for display in CLI.

    Args:
        sessions: List of session metadata dicts
        show_all: If True, show full details. If False, show compact format

    Returns:
        Formatted string for display
    """
    if not sessions:
        return "No sessions found."

    output = []
    output.append(f"\n{'Recent' if not show_all else 'All'} Memory Sessions:")
    output.append("=" * 100)

    if show_all:
        # Detailed format
        for session in sessions:
            session_id = session.get("session_id", "unknown")
            start_time = session.get("start_time", "unknown")
            status = session.get("status", "unknown")
            model = session.get("model", "N/A")
            config = session.get("config_path", "N/A")
            description = session.get("description", "")

            # Parse and format start time
            try:
                dt = datetime.fromisoformat(start_time)
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                time_str = start_time

            output.append(f"\nSession ID: {session_id}")
            output.append(f"  Status:  {status}")
            output.append(f"  Started: {time_str}")
            output.append(f"  Model:   {model}")
            if description:
                output.append(f"  Description: {description}")
            if config != "N/A":
                # Show just filename for brevity
                config_name = Path(config).name if config else "N/A"
                output.append(f"  Config:  {config_name}")
    else:
        # Compact format - table view
        output.append(f"\n{'Session ID':<30} {'Started':<20} {'Status':<12} {'Model':<20}")
        output.append("-" * 100)

        for session in sessions:
            session_id = session.get("session_id", "unknown")
            start_time = session.get("start_time", "unknown")
            status = session.get("status", "unknown")
            model = session.get("model", "N/A")

            # Parse and format start time
            try:
                dt = datetime.fromisoformat(start_time)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                time_str = start_time[:16] if len(start_time) > 16 else start_time

            # Truncate model name if too long
            model_display = model[:18] + ".." if model and len(model) > 20 else (model or "N/A")

            # Status indicator
            status_icon = "✓" if status == "completed" else "○"
            status_display = f"{status_icon} {status}"

            output.append(f"{session_id:<30} {time_str:<20} {status_display:<12} {model_display:<20}")

    output.append("\n" + "=" * 100)
    if not show_all and len(sessions) >= 10:
        output.append(f"\nShowing {len(sessions)} most recent sessions. Use --list-sessions --all to see all sessions.")
    output.append('\nTo load a session: massgen --session-id <SESSION_ID> "Your question"')
    output.append("To continue most recent: massgen --continue")

    return "\n".join(output)
