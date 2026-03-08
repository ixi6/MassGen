"""
Workflow toolkits for MassGen coordination.
"""

from typing import Any

from .base import BaseToolkit, ToolType
from .broadcast import BroadcastToolkit
from .new_answer import NewAnswerToolkit
from .post_evaluation import PostEvaluationToolkit
from .stop import StopToolkit
from .vote import VoteToolkit

__all__ = [
    "BaseToolkit",
    "ToolType",
    "NewAnswerToolkit",
    "VoteToolkit",
    "StopToolkit",
    "BroadcastToolkit",
    "PostEvaluationToolkit",
    "get_workflow_tools",
    "get_post_evaluation_tools",
]


def get_workflow_tools(
    valid_agent_ids: list[str] | None = None,
    template_overrides: dict | None = None,
    api_format: str = "chat_completions",
    orchestrator: Any | None = None,
    broadcast_mode: str | None = None,
    broadcast_wait_by_default: bool = True,
    vote_only: bool = False,
    anon_agent_ids: list[str] | None = None,
    decomposition_mode: bool = False,
) -> list[dict]:
    """
    Get workflow tool definitions with proper formatting.

    Args:
        valid_agent_ids: List of valid agent IDs for voting (real IDs, legacy)
        template_overrides: Optional template overrides
        api_format: API format to use (chat_completions, claude, response)
        orchestrator: Optional orchestrator instance (for broadcast tools)
        broadcast_mode: Broadcast mode ("agents", "human", or None to disable)
        broadcast_wait_by_default: Default waiting behavior for broadcasts
        vote_only: If True, only include vote tool (exclude new_answer and broadcast).
                   Used when agent has reached max_new_answers_per_agent limit.
        anon_agent_ids: Pre-computed anonymous agent IDs (e.g., ["agent1", "agent3"]).
                       If provided, these are used directly for the vote enum.
                       Pass from coordination_tracker.get_agents_with_answers_anon() for
                       global consistency with injections and vote validation.
        decomposition_mode: If True, use stop tool instead of vote tool.
                           Used when coordination_mode is "decomposition".

    Returns:
        List of tool definitions
    """
    tools = []

    # Create config for tools
    config = {
        "api_format": api_format,
        "enable_workflow_tools": True,
        "valid_agent_ids": valid_agent_ids,
        "anon_agent_ids": anon_agent_ids,
        "broadcast_enabled": bool(broadcast_mode and broadcast_mode is not False),
    }

    # Get new_answer tool (unless vote_only mode)
    if not vote_only:
        new_answer_toolkit = NewAnswerToolkit(template_overrides=template_overrides)
        tools.extend(new_answer_toolkit.get_tools(config))

    if decomposition_mode:
        # Decomposition mode: use stop tool instead of vote
        stop_toolkit = StopToolkit(template_overrides=template_overrides)
        tools.extend(stop_toolkit.get_tools(config))
    else:
        # Voting mode: use vote tool (always included)
        vote_toolkit = VoteToolkit(
            valid_agent_ids=valid_agent_ids,
            template_overrides=template_overrides,
            anon_agent_ids=anon_agent_ids,
        )
        tools.extend(vote_toolkit.get_tools(config))

    # Get broadcast tools if enabled (unless vote_only mode)
    if broadcast_mode and broadcast_mode is not False and not vote_only:
        broadcast_toolkit = BroadcastToolkit(
            orchestrator=orchestrator,
            broadcast_mode=broadcast_mode,
            wait_by_default=broadcast_wait_by_default,
        )
        tools.extend(broadcast_toolkit.get_tools(config))

    return tools


def get_post_evaluation_tools(
    template_overrides: dict | None = None,
    api_format: str = "chat_completions",
) -> list[dict]:
    """
    Get post-evaluation tool definitions (submit and restart_orchestration).

    Args:
        template_overrides: Optional template overrides
        api_format: API format to use (chat_completions, claude, response)

    Returns:
        List of tool definitions [submit, restart_orchestration]
    """
    config = {
        "api_format": api_format,
        "enable_post_evaluation_tools": True,
    }

    post_eval_toolkit = PostEvaluationToolkit(template_overrides=template_overrides)
    return post_eval_toolkit.get_tools(config)
