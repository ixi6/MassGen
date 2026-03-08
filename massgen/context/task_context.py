"""Task context loading for external API calls.

This module provides the load_task_context function that reads CONTEXT.md
from the workspace and returns its content for injection into external API calls.

The CONTEXT.md file is created by main agents before using multimodal tools
or spawning subagents, ensuring external APIs have context about the task.
"""

from pathlib import Path

from loguru import logger


class TaskContextError(Exception):
    """Raised when CONTEXT.md is missing or cannot be read."""


# Default maximum characters to read from CONTEXT.md
DEFAULT_MAX_CHARS = 10000

# Standard filename for task context
CONTEXT_FILENAME = "CONTEXT.md"


class TaskContextResult:
    """Result of loading task context, including truncation info."""

    def __init__(
        self,
        content: str | None,
        was_truncated: bool = False,
        original_length: int = 0,
        truncated_length: int = 0,
    ):
        self.content = content
        self.was_truncated = was_truncated
        self.original_length = original_length
        self.truncated_length = truncated_length

    def get_warning(self) -> str | None:
        """Get warning message if context was truncated."""
        if self.was_truncated:
            return f"WARNING: CONTEXT.md was truncated from {self.original_length} to " f"{self.truncated_length} characters. Consider shortening it for better results."
        return None


def load_task_context(
    workspace_path: str | None,
    max_chars: int = DEFAULT_MAX_CHARS,
    required: bool = True,
    return_result: bool = False,
):
    """Load task context from CONTEXT.md in the workspace.

    This function reads the CONTEXT.md file from the workspace root and returns
    its content, truncated to max_chars if necessary.

    Args:
        workspace_path: Path to the workspace directory. If None, returns None
                       (or raises if required=True).
        max_chars: Maximum number of characters to read. Default 10000.
        required: If True, raises TaskContextError when CONTEXT.md is missing.
                 If False, returns None when missing.
        return_result: If True, returns TaskContextResult with truncation info.
                      If False, returns just the string content (default).

    Returns:
        If return_result=False: The content of CONTEXT.md (up to max_chars),
            or None if not found and required=False.
        If return_result=True: TaskContextResult with content and truncation info.

    Raises:
        TaskContextError: If CONTEXT.md is missing and required=True, or if
                         the file cannot be read.

    Example:
        >>> context = load_task_context("/path/to/workspace")
        >>> if context:
        ...     augmented_prompt = f"[Task Context]\\n{context}\\n\\n[Request]\\n{prompt}"

        >>> # With truncation info
        >>> result = load_task_context("/path/to/workspace", return_result=True)
        >>> if result.was_truncated:
        ...     print(result.get_warning())
    """

    def _return(content: str | None, was_truncated: bool = False, original_len: int = 0, truncated_len: int = 0):
        """Helper to return either string or TaskContextResult based on return_result flag."""
        if return_result:
            return TaskContextResult(content, was_truncated, original_len, truncated_len)
        return content

    if not workspace_path:
        if required:
            raise TaskContextError(
                "CONTEXT.md not found: no workspace path provided. "
                "Before using multimodal tools or spawning subagents, "
                "create a CONTEXT.md file with task context. "
                "See system prompt for instructions.",
            )
        return _return(None)

    workspace = Path(workspace_path)
    context_path = workspace / CONTEXT_FILENAME

    if not context_path.exists():
        if required:
            raise TaskContextError(
                f"CONTEXT.md not found in workspace '{workspace_path}'. "
                "Before using multimodal tools or spawning subagents, "
                "create a CONTEXT.md file with task context. "
                "See system prompt for instructions.",
            )
        logger.debug(f"[TaskContext] No CONTEXT.md found in {workspace_path}")
        return _return(None)

    if not context_path.is_file():
        if required:
            raise TaskContextError(
                f"CONTEXT.md exists but is not a file in '{workspace_path}'. " "Please create CONTEXT.md as a regular file with task context.",
            )
        return _return(None)

    try:
        content = context_path.read_text(encoding="utf-8")
        original_len = len(content)
        was_truncated = False

        # Truncate if necessary
        if len(content) > max_chars:
            was_truncated = True
            content = content[:max_chars]
            logger.warning(
                f"[TaskContext] CONTEXT.md truncated from {original_len} to {max_chars} chars",
            )

        # Strip whitespace and return None if empty
        content = content.strip()
        if not content:
            if required:
                raise TaskContextError(
                    f"CONTEXT.md is empty in '{workspace_path}'. " "Please add task context describing what you're building/doing.",
                )
            return _return(None)

        logger.debug(f"[TaskContext] Loaded {len(content)} chars from {context_path}")
        return _return(content, was_truncated, original_len, len(content))

    except TaskContextError:
        raise
    except Exception as e:
        error_msg = f"Failed to read CONTEXT.md from '{workspace_path}': {e}"
        if required:
            raise TaskContextError(error_msg) from e
        logger.error(f"[TaskContext] {error_msg}")
        return None


def load_task_context_with_warning(
    workspace_path: str | None,
    existing_context: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[str | None, str | None]:
    """Load task context, returning both content and any truncation warning.

    This is a convenience function for tools that need to:
    1. Use existing context if already loaded
    2. Otherwise load from CONTEXT.md
    3. Capture any truncation warning for inclusion in tool response

    Args:
        workspace_path: Path to the workspace directory.
        existing_context: Already-loaded context to use if available.
        max_chars: Maximum characters to read. Default 10000.

    Returns:
        Tuple of (task_context, warning_message).
        - task_context: The loaded context string, or None if not found.
        - warning_message: Warning if context was truncated, or None.

    Example:
        >>> task_context, warning = load_task_context_with_warning(
        ...     "/path/to/workspace",
        ...     existing_context=None  # Will load from CONTEXT.md
        ... )
        >>> if warning:
        ...     response["warning"] = warning
    """
    if existing_context:
        return existing_context, None

    if not workspace_path:
        return None, None

    result = load_task_context(workspace_path, max_chars=max_chars, required=False, return_result=True)
    return result.content, result.get_warning()


def format_prompt_with_context(
    prompt: str,
    task_context: str | None,
) -> str:
    """Format a prompt with task context prepended.

    Args:
        prompt: The original prompt/request.
        task_context: The task context to prepend, or None.

    Returns:
        The formatted prompt with context, or the original prompt if no context.

    Example:
        >>> formatted = format_prompt_with_context(
        ...     "Analyze this image for issues",
        ...     "Building a website for MassGen, a multi-agent AI system."
        ... )
        >>> print(formatted)
        [Task Context]
        Building a website for MassGen, a multi-agent AI system.

        [Request]
        Analyze this image for issues
    """
    if not task_context:
        return prompt

    return f"[Task Context]\n{task_context}\n\n[Request]\n{prompt}"
