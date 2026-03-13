"""
Response API parameters handler.
Handles parameter building for OpenAI Response API format.
"""

from __future__ import annotations

from typing import Any

from ..logger_config import logger
from ._api_params_handler_base import APIParamsHandlerBase


class ResponseAPIParamsHandler(APIParamsHandlerBase):
    """Handler for Response API parameters."""

    def get_excluded_params(self) -> set[str]:
        """Get parameters to exclude from Response API calls."""
        return self.get_base_excluded_params().union(
            {
                "enable_web_search",
                "enable_code_interpreter",
                "allowed_tools",
                "exclude_tools",
                "custom_tools",  # Custom tools configuration (processed separately)
                "_has_file_search_files",  # Internal flag for file search tracking
                "enable_file_generation",  # Internal flag for file generation (used in system messages only)
                "enable_image_generation",  # Internal flag for image generation (used in system messages only)
                "enable_audio_generation",  # Internal flag for audio generation (used in system messages only)
                "enable_video_generation",  # Internal flag for video generation (used in system messages only)
                "previous_response_id",  # Handled explicitly above for reasoning continuity
                "websocket_mode",  # Transport control, not an API parameter
                "base_url",  # Client-constructor param, not a request-body param
                "organization",  # Client-constructor param, not a request-body param
            },
        )

    def get_provider_tools(self, all_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Get provider tools for Response API format."""
        provider_tools = []

        if all_params.get("enable_web_search", False):
            provider_tools.append({"type": "web_search"})

        if all_params.get("enable_code_interpreter", False):
            provider_tools.append(
                {
                    "type": "code_interpreter",
                    "container": {"type": "auto"},
                },
            )

        return provider_tools

    def _convert_mcp_tools_to_openai_format(self) -> list[dict[str, Any]]:
        """Convert MCP tools to OpenAI function format for Response API."""
        if not hasattr(self.backend, "_mcp_functions") or not self.backend._mcp_functions:
            return []

        converted_tools = []
        for function in self.backend._mcp_functions.values():
            converted_tools.append(function.to_openai_format())

        return converted_tools

    async def build_api_params(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        all_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Response API parameters."""
        # Convert messages to Response API format
        converted_messages = self.formatter.format_messages(messages)

        # Response API uses 'input' instead of 'messages'
        websocket_mode = all_params.get("websocket_mode", False)  # In WebSocket mode, stream/background are not used (transport handles streaming)
        api_params = {"input": converted_messages}
        if not websocket_mode:
            api_params["stream"] = True
        else:
            all_params.pop("background", None)

        # Set default reasoning configuration for reasoning models (GPT-5, o-series)
        # Per OpenAI docs, GPT-5.1 and GPT-5.2 default to reasoning=none, but GPT-5 defaults to medium
        # We want GPT-5.1/5.2 to behave like GPT-5 for better task completion
        # See: https://cookbook.openai.com/examples/gpt-5/gpt-5-2_prompting_guide#8-prompt-migration-guide-to-gpt-52
        model_name = all_params.get("model", "").lower()
        is_reasoning_model = model_name.startswith("gpt-5") or model_name.startswith("o3") or model_name.startswith("o4")

        if is_reasoning_model:
            # Get existing reasoning config or create default
            reasoning_config = all_params.get("reasoning", {})
            if not isinstance(reasoning_config, dict):
                reasoning_config = {}

            # Set default effort for GPT-5.x models (they default to none without this)
            if model_name.startswith("gpt-5.") and "effort" not in reasoning_config:
                reasoning_config["effort"] = "medium"
                logger.info(f"[ResponseAPIParamsHandler] Set default reasoning effort 'medium' for {model_name}")

            # Always enable reasoning summaries by default for execution trace visibility
            # Uses "auto" to get the most detailed summarizer available for each model
            # See: https://platform.openai.com/docs/guides/reasoning#reasoning-summaries
            if "summary" not in reasoning_config:
                reasoning_config["summary"] = "auto"
                logger.info(f"[ResponseAPIParamsHandler] Enabled reasoning summaries for {model_name}")

            all_params["reasoning"] = reasoning_config

        # Pass previous_response_id for reasoning model continuity (e.g., GPT-5)
        # This ensures reasoning items from previous responses are available
        previous_response_id = all_params.get("previous_response_id")
        if previous_response_id:
            api_params["previous_response_id"] = previous_response_id
            logger.debug(f"Using previous_response_id for reasoning continuity: {previous_response_id}")

        # Handle parallel_tool_calls with built-in tools constraint
        builtin_flags = ("enable_web_search", "enable_code_interpreter", "_has_file_search_files")
        if any(all_params.get(f, False) for f in builtin_flags):
            # Built-in tools present - MUST disable parallel calling
            if all_params.get("parallel_tool_calls") is True:
                logger.warning(
                    "parallel_tool_calls=true is not supported with built-in tools " "(web_search, code_interpreter, file_search). " "Setting parallel_tool_calls=false.",
                )
            api_params["parallel_tool_calls"] = False
        elif "parallel_tool_calls" in all_params:
            # User explicitly set it
            api_params["parallel_tool_calls"] = all_params["parallel_tool_calls"]
        # else: Don't send - Response API defaults to true

        # Add filtered parameters with parameter mapping
        excluded = self.get_excluded_params()
        for key, value in all_params.items():
            # Skip parallel_tool_calls - already handled above
            if key == "parallel_tool_calls":
                continue
            if key not in excluded and value is not None:
                # Handle Response API parameter name differences
                if key == "max_tokens":
                    api_params["max_output_tokens"] = value
                else:
                    api_params[key] = value

        # Combine all tools
        combined_tools = api_params.setdefault("tools", [])

        # Add provider tools first
        provider_tools = self.get_provider_tools(all_params)
        if provider_tools:
            combined_tools.extend(provider_tools)

        # Add workflow tools
        if tools:
            converted_tools = self.formatter.format_tools(tools)
            combined_tools.extend(converted_tools)

        # Add custom tools (includes internal background lifecycle helpers when available)
        custom_tools = self.get_custom_tools()
        if custom_tools:
            combined_tools.extend(custom_tools)

        # Add MCP tools (use OpenAI format)
        mcp_tools = self._convert_mcp_tools_to_openai_format()
        if mcp_tools:
            combined_tools.extend(mcp_tools)

        if combined_tools:
            api_params["tools"] = combined_tools
        # File Search integration
        vector_store_ids = all_params.get("_file_search_vector_store_ids")
        if vector_store_ids:
            # Ensure vector_store_ids is a list
            if not isinstance(vector_store_ids, list):
                vector_store_ids = [vector_store_ids]

            # Check if file_search tool already exists
            file_search_tool_index = None
            for i, tool in enumerate(combined_tools):
                if tool.get("type") == "file_search":
                    file_search_tool_index = i
                    break

            # Add or update file_search tool with embedded vector_store_ids
            if file_search_tool_index is not None:
                # Update existing file_search tool
                combined_tools[file_search_tool_index]["vector_store_ids"] = vector_store_ids
            else:
                # Add new file_search tool with vector_store_ids
                combined_tools.append(
                    {
                        "type": "file_search",
                        "vector_store_ids": vector_store_ids,
                    },
                )

        return api_params
