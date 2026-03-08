"""
Subagent Module for MassGen

Provides the ability for agents to spawn subagents - independent agent instances
that execute tasks with fresh context and isolated workspaces.
"""

from massgen.subagent.models import (
    SpecializedSubagentConfig,
    SubagentConfig,
    SubagentPointer,
    SubagentResult,
)

__all__ = [
    "SpecializedSubagentConfig",
    "SubagentConfig",
    "SubagentResult",
    "SubagentPointer",
]
