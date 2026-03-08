"""Context management for MassGen.

This module provides utilities for loading and managing task context
that is passed to external API calls (multimodal tools, subagents).
"""

from massgen.context.task_context import (
    TaskContextError,
    TaskContextResult,
    format_prompt_with_context,
    load_task_context,
    load_task_context_with_warning,
)

__all__ = [
    "load_task_context",
    "load_task_context_with_warning",
    "format_prompt_with_context",
    "TaskContextError",
    "TaskContextResult",
]
