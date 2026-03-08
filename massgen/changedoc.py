"""Changedoc utility for reading decision journal files from agent workspaces."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHANGEDOC_FILENAME = "tasks/changedoc.md"


def read_changedoc_from_workspace(workspace_path: Path) -> str | None:
    """Read tasks/changedoc.md from an agent's workspace directory.

    Args:
        workspace_path: Path to the agent's workspace directory.

    Returns:
        The changedoc content as a string, or None if not found/empty.
    """
    changedoc_path = workspace_path / CHANGEDOC_FILENAME
    if not changedoc_path.exists():
        return None
    try:
        content = changedoc_path.read_text().strip()
        return content if content else None
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read changedoc from %s", changedoc_path)
        return None
