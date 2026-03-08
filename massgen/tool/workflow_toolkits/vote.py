"""
Vote toolkit for MassGen workflow coordination.
"""

from typing import Any

from .base import BaseToolkit, ToolType


class VoteToolkit(BaseToolkit):
    """Vote toolkit for agent coordination workflows."""

    def __init__(
        self,
        valid_agent_ids: list[str] | None = None,
        template_overrides: dict[str, Any] | None = None,
        anon_agent_ids: list[str] | None = None,
    ):
        """
        Initialize the Vote toolkit.

        Args:
            valid_agent_ids: List of valid agent IDs for voting (real IDs, legacy)
            template_overrides: Optional template overrides for customization
            anon_agent_ids: Pre-computed anonymous agent IDs (e.g., ["agent1", "agent3"]).
                           If provided, these are used directly for the vote enum.
                           Pass from coordination_tracker.get_agents_with_answers_anon() for
                           global consistency with injections and vote validation.
        """
        self.valid_agent_ids = valid_agent_ids
        self._template_overrides = template_overrides or {}
        self.anon_agent_ids = anon_agent_ids

    @property
    def toolkit_id(self) -> str:
        """Unique identifier for vote toolkit."""
        return "vote"

    @property
    def toolkit_type(self) -> ToolType:
        """Type of this toolkit."""
        return ToolType.WORKFLOW

    def is_enabled(self, config: dict[str, Any]) -> bool:
        """
        Check if vote is enabled in configuration.

        Args:
            config: Configuration dictionary.

        Returns:
            True if workflow tools are enabled or not explicitly disabled.
        """
        # Enable by default for workflow, unless explicitly disabled
        return config.get("enable_workflow_tools", True)

    def set_valid_agent_ids(self, agent_ids: list[str]):
        """
        Update the valid agent IDs for voting.

        Args:
            agent_ids: List of valid agent IDs
        """
        self.valid_agent_ids = agent_ids

    def get_tools(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Get vote tool definition based on API format.

        Args:
            config: Configuration including api_format and potentially valid_agent_ids or anon_agent_ids.

        Returns:
            List containing the vote tool definition.
        """
        # Check for template override
        if "vote_tool" in self._template_overrides:
            override = self._template_overrides["vote_tool"]
            if callable(override):
                return [override(self.valid_agent_ids)]
            return [override]

        # Get anonymous agent IDs for the vote enum
        # Priority: 1) config anon_agent_ids, 2) instance anon_agent_ids, 3) generate from valid_ids
        anon_ids = config.get("anon_agent_ids", self.anon_agent_ids)
        if anon_ids is None:
            # Fallback: generate from valid_agent_ids count (legacy behavior)
            valid_ids = config.get("valid_agent_ids", self.valid_agent_ids)
            if valid_ids:
                anon_ids = [f"agent{i}" for i in range(1, len(valid_ids) + 1)]

        api_format = config.get("api_format", "chat_completions")

        if api_format == "claude":
            # Claude native format
            tool_def = {
                "name": "vote",
                "description": "Vote for the best agent to present final answer",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief reason why this agent has the best answer",
                        },
                    },
                    "required": ["agent_id", "reason"],
                },
            }

            # Add enum constraint for valid agent IDs
            if anon_ids:
                tool_def["input_schema"]["properties"]["agent_id"]["enum"] = anon_ids

            return [tool_def]

        elif api_format == "response":
            # Response API format
            tool_def = {
                "type": "function",
                "function": {
                    "name": "vote",
                    "description": "Vote for the best agent to present final answer",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Brief reason why this agent has the best answer",
                            },
                        },
                        "required": ["agent_id", "reason"],
                    },
                },
            }

            # Add enum constraint for valid agent IDs
            if anon_ids:
                tool_def["function"]["parameters"]["properties"]["agent_id"]["enum"] = anon_ids

            return [tool_def]

        else:
            # Default Chat Completions format
            tool_def = {
                "type": "function",
                "function": {
                    "name": "vote",
                    "description": "Vote for the best agent to present final answer",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Brief reason why this agent has the best answer",
                            },
                        },
                        "required": ["agent_id", "reason"],
                    },
                },
            }

            # Add enum constraint for valid agent IDs
            if anon_ids:
                tool_def["function"]["parameters"]["properties"]["agent_id"]["enum"] = anon_ids

            return [tool_def]
