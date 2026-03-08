"""
Stop toolkit for MassGen decomposition mode coordination.

In decomposition mode, agents call `stop` instead of `vote` to signal
that their assigned subtask is complete.
"""

from typing import Any

from .base import BaseToolkit, ToolType

_STOP_DESCRIPTION = (
    "Signal that you have reviewed the current state and are satisfied with your deliverables as-is."
    " Only call this if you made no improvements to your work this round."
    " If you changed or improved your deliverables, use new_answer instead to share them."
)


class StopToolkit(BaseToolkit):
    """Stop toolkit for decomposition mode agent coordination."""

    def __init__(
        self,
        template_overrides: dict[str, Any] | None = None,
    ):
        self._template_overrides = template_overrides or {}

    @property
    def toolkit_id(self) -> str:
        return "stop"

    @property
    def toolkit_type(self) -> ToolType:
        return ToolType.WORKFLOW

    def is_enabled(self, config: dict[str, Any]) -> bool:
        return config.get("enable_workflow_tools", True)

    def get_tools(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Get stop tool definition based on API format."""
        if "stop_tool" in self._template_overrides:
            override = self._template_overrides["stop_tool"]
            if callable(override):
                return [override()]
            return [override]

        api_format = config.get("api_format", "chat_completions")

        if api_format == "claude":
            return [
                {
                    "name": "stop",
                    "description": _STOP_DESCRIPTION,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "What you accomplished and how it connects to other agents' work",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["complete", "blocked"],
                                "description": "Whether your subtask is complete or blocked on something",
                            },
                        },
                        "required": ["summary", "status"],
                    },
                },
            ]

        else:
            # Response API and Chat Completions share the same format
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "stop",
                        "description": _STOP_DESCRIPTION,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "summary": {
                                    "type": "string",
                                    "description": "What you accomplished and how it connects to other agents' work",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["complete", "blocked"],
                                    "description": "Whether your subtask is complete or blocked on something",
                                },
                            },
                            "required": ["summary", "status"],
                        },
                    },
                },
            ]
