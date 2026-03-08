"""
Utilities for structured logging and observability.

This module provides:
- Centralized truncation constants for consistent log preview lengths
- Helper functions for truncating text with ellipsis indication
- Workspace path extraction utilities for telemetry

Usage:
    from massgen.structured_logging_utils import (
        truncate_for_log,
        extract_workspace_info,
        PreviewLengths,
        PREVIEW_TASK,
        PREVIEW_ANSWER,
    )

    # Truncate with default length (200)
    preview = truncate_for_log(long_text)

    # Truncate with specific length
    task_preview = truncate_for_log(task, PREVIEW_TASK)

    # Extract workspace name from path
    workspace = extract_workspace_info("/path/.massgen/workspaces/ws1/file.txt")
    # Returns: "ws1"
"""

from pathlib import Path, PurePath


class PreviewLengths:
    """Centralized truncation length constants for logging.

    Use these constants instead of magic numbers when truncating
    strings for log messages and telemetry.
    """

    # Short previews - for lists, summaries, quick context
    SHORT = 100

    # Medium previews - default for most content (answers, arguments, output)
    DEFAULT = 200

    # Long previews - for tasks, errors, detailed context
    LONG = 500


# Semantic aliases for clarity - use these in code for self-documenting truncation
PREVIEW_TASK = PreviewLengths.LONG  # 500 - tasks need more context
PREVIEW_ANSWER = PreviewLengths.DEFAULT  # 200 - answer previews
PREVIEW_ERROR = PreviewLengths.LONG  # 500 - errors need detail
PREVIEW_TOOL_ARGS = PreviewLengths.DEFAULT  # 200 - tool argument previews
PREVIEW_TOOL_OUTPUT = PreviewLengths.DEFAULT  # 200 - tool output previews
PREVIEW_QUESTION = PreviewLengths.SHORT  # 100 - question previews
PREVIEW_VOTE_REASON = PreviewLengths.LONG  # 500 - vote reasoning (extended for workflow analysis)
PREVIEW_FILE_PATH = PreviewLengths.LONG  # 500 - file paths (can be deep)

# Workflow analysis constants (MAS-199)
PREVIEW_ROUND_INTENT = PreviewLengths.DEFAULT  # 200 - agent round intent
PREVIEW_ANSWER_EACH = PreviewLengths.SHORT  # 100 - per-answer preview in context
PREVIEW_RESTART_REASON = PreviewLengths.DEFAULT  # 200 - restart reason
PREVIEW_SUBAGENT_TASK = PreviewLengths.LONG  # 500 - subagent task (extended)
PREVIEW_ERROR_CONTEXT = PreviewLengths.LONG  # 500 - tool error context
MAX_FILES_CREATED = 50  # Max files to log in files_created list


# Workspace path constants
MASSGEN_DIR_NAME = ".massgen"
WORKSPACES_DIR_NAME = "workspaces"


def truncate_for_log(
    text: str | None,
    max_length: int = PreviewLengths.DEFAULT,
    suffix: str = "...",
) -> str | None:
    """
    Truncate text for logging with consistent behavior.

    When text exceeds max_length, it is truncated and a suffix is appended
    to indicate truncation. The total output length (including suffix) will
    not exceed max_length.

    Args:
        text: The text to truncate. If None, returns None.
        max_length: Maximum length before truncation. Use PreviewLengths constants.
        suffix: String to append when truncating (default: "...").

    Returns:
        Truncated string with suffix if truncated, original string if short enough,
        or None for None input.

    Examples:
        >>> truncate_for_log("Hello world", 8)
        'Hello...'
        >>> truncate_for_log(None)
        None
        >>> truncate_for_log("Short", 200)
        'Short'
        >>> truncate_for_log("Long text here", 10, suffix="[...]")
        'Long [....]'
    """
    if text is None:
        return None

    if not isinstance(text, str):
        text = str(text)

    if len(text) <= max_length:
        return text

    # Account for suffix length to stay within max_length total
    truncate_at = max_length - len(suffix)
    if truncate_at < 0:
        truncate_at = 0

    return text[:truncate_at] + suffix


def extract_workspace_info(file_path: str | Path | None) -> str | None:
    """
    Extract workspace name from a MassGen workspace path.

    MassGen stores workspace files under `.massgen/workspaces/{workspace_name}/`.
    This function extracts the workspace name from such paths using pathlib
    for robust cross-platform handling.

    Args:
        file_path: A file path that may be within a MassGen workspace.
                   e.g., "/project/.massgen/workspaces/workspace1_abc123/file.txt"

    Returns:
        The workspace name (e.g., "workspace1_abc123") if the path is within
        a MassGen workspace, otherwise None.

    Examples:
        >>> extract_workspace_info("/project/.massgen/workspaces/ws1/file.txt")
        'ws1'
        >>> extract_workspace_info("/project/regular/file.txt")
        None
        >>> extract_workspace_info(Path("/home/.massgen/workspaces/ws_123/sub/file.py"))
        'ws_123'
        >>> extract_workspace_info(None)
        None
    """
    if file_path is None:
        return None

    # Convert to PurePath for reliable parsing (works on any platform)
    path = PurePath(file_path) if not isinstance(file_path, PurePath) else file_path
    parts = path.parts

    # Find the .massgen/workspaces sequence
    for i, part in enumerate(parts):
        if part == MASSGEN_DIR_NAME:
            # Check if next part is "workspaces" and there's a workspace name after
            if i + 2 < len(parts) and parts[i + 1] == WORKSPACES_DIR_NAME:
                return parts[i + 2]  # The workspace name

    return None


def is_massgen_workspace_path(file_path: str | Path | None) -> bool:
    """
    Check if a path is within a MassGen workspace.

    Args:
        file_path: Path to check.

    Returns:
        True if the path is within .massgen/workspaces/, False otherwise.

    Examples:
        >>> is_massgen_workspace_path("/project/.massgen/workspaces/ws1/file.txt")
        True
        >>> is_massgen_workspace_path("/project/regular/file.txt")
        False
    """
    return extract_workspace_info(file_path) is not None


__all__ = [
    # Constants
    "PreviewLengths",
    "PREVIEW_TASK",
    "PREVIEW_ANSWER",
    "PREVIEW_ERROR",
    "PREVIEW_TOOL_ARGS",
    "PREVIEW_TOOL_OUTPUT",
    "PREVIEW_QUESTION",
    "PREVIEW_VOTE_REASON",
    "PREVIEW_FILE_PATH",
    # Workflow analysis constants (MAS-199)
    "PREVIEW_ROUND_INTENT",
    "PREVIEW_ANSWER_EACH",
    "PREVIEW_RESTART_REASON",
    "PREVIEW_SUBAGENT_TASK",
    "PREVIEW_ERROR_CONTEXT",
    "MAX_FILES_CREATED",
    # Workspace path constants
    "MASSGEN_DIR_NAME",
    "WORKSPACES_DIR_NAME",
    # Functions
    "truncate_for_log",
    "extract_workspace_info",
    "is_massgen_workspace_path",
]
