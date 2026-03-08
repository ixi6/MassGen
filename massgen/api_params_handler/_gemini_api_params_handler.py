"""
Gemini API parameters handler building SDK config with parameter mapping and exclusions.
"""

from typing import Any

from ._api_params_handler_base import APIParamsHandlerBase


class GeminiAPIParamsHandler(APIParamsHandlerBase):
    def get_excluded_params(self) -> set[str]:
        base = self.get_base_excluded_params()
        extra = {
            "enable_web_search",
            "enable_code_execution",
            "use_multi_mcp",
            "mcp_sdk_auto",
            "allowed_tools",
            "exclude_tools",
            "custom_tools",
            "enable_file_generation",  # Internal flag for file generation (used in system messages only)
            "enable_image_generation",  # Internal flag for image generation (used in system messages only)
            "enable_audio_generation",  # Internal flag for audio generation (used in system messages only)
            "enable_video_generation",  # Internal flag for video generation (used in system messages only)
            "function_calling_mode",  # Handled separately in build_api_params
            "thinking_config",  # Handled separately in build_api_params
            "thinking",  # Alternative name for thinking_config (consistency with Claude)
            "include_thoughts",  # Convenience parameter for thinking_config
        }
        return set(base) | extra

    def get_provider_tools(self, all_params: dict[str, Any]) -> list[dict[str, Any]]:
        """
        These are SDK Tool objects (from google.genai.types), not JSON tool declarations.
        """
        tools: list[Any] = []

        if all_params.get("enable_web_search", False):
            try:
                from google.genai.types import GoogleSearch, Tool

                tools.append(Tool(google_search=GoogleSearch()))
            except Exception:
                # Gracefully ignore if SDK not available
                pass

        if all_params.get("enable_code_execution", False):
            try:
                from google.genai.types import Tool, ToolCodeExecution

                tools.append(Tool(code_execution=ToolCodeExecution()))
            except Exception:
                # Gracefully ignore if SDK not available
                pass

        return tools

    async def build_api_params(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], all_params: dict[str, Any]) -> dict[str, Any]:
        """
        Build a config dict for google-genai Client.generate_content_stream.
        - Map max_tokens -> max_output_tokens
        - Do not include 'model' here; caller extracts it
        - Do not add builtin tools; stream logic handles them
        - Do not handle MCP tools or coordination schema here
        """
        excluded = self.get_excluded_params()
        config: dict[str, Any] = {}

        for key, value in all_params.items():
            if key in excluded or value is None:
                continue
            if key == "max_tokens":
                config["max_output_tokens"] = value
            elif key == "model":
                # Caller will extract model separately
                continue
            else:
                config[key] = value

        # Handle function_calling_mode parameter
        # This controls whether Gemini API calls functions in specific modes
        function_calling_mode = all_params.get("function_calling_mode")
        if function_calling_mode:
            from ..logger_config import logger  # Import once at the start

            try:
                from google.genai.types import FunctionCallingConfig, ToolConfig

                # Validate mode
                valid_modes = {"AUTO", "ANY", "NONE"}
                mode = function_calling_mode.upper()
                if mode not in valid_modes:
                    logger.warning(
                        f"[Gemini] Invalid function_calling_mode '{function_calling_mode}'. " f"Valid modes: {valid_modes}. Ignoring.",
                    )
                else:
                    # Create ToolConfig with FunctionCallingConfig
                    config["tool_config"] = ToolConfig(
                        function_calling_config=FunctionCallingConfig(mode=mode),
                    )
            except ImportError:
                logger.warning("[Gemini] google.genai.types not available. Ignoring function_calling_mode.")

        # Handle thinking_config parameter for Gemini 2.5+ thinking models
        # This enables thought summaries in responses
        # Accepts: thinking_config dict, thinking dict (Claude-style), or include_thoughts bool
        # Default: Enable thinking for Gemini 2.5+ and 3.x models automatically
        thinking_config = all_params.get("thinking_config") or all_params.get("thinking")
        include_thoughts = all_params.get("include_thoughts")

        # Auto-enable thinking for thinking-capable models if not explicitly configured
        model = all_params.get("model", "")
        is_thinking_model = any(pattern in model.lower() for pattern in ["gemini-2.5", "gemini-3", "gemini-exp", "gemini-2.0-flash-thinking"])

        # Enable thinking by default for thinking-capable models
        if thinking_config is None and include_thoughts is None and is_thinking_model:
            include_thoughts = True

        if thinking_config or include_thoughts:
            from ..logger_config import logger

            try:
                from google.genai.types import ThinkingConfig

                if isinstance(thinking_config, dict):
                    # Direct thinking_config dict: {"include_thoughts": True, "thinking_budget": 1024}
                    config["thinking_config"] = ThinkingConfig(**thinking_config)
                    logger.debug(f"[Gemini] Set thinking_config from dict: {thinking_config}")
                elif include_thoughts:
                    # Simple include_thoughts=True convenience parameter (or auto-enabled)
                    config["thinking_config"] = ThinkingConfig(include_thoughts=True)
                    if is_thinking_model:
                        logger.debug(f"[Gemini] Auto-enabled thinking for model: {model}")
                    else:
                        logger.debug("[Gemini] Set thinking_config with include_thoughts=True")
                elif thinking_config is True:
                    # thinking=True (Claude-style shorthand)
                    config["thinking_config"] = ThinkingConfig(include_thoughts=True)
                    logger.debug("[Gemini] Set thinking_config from thinking=True")
            except ImportError:
                logger.warning("[Gemini] google.genai.types.ThinkingConfig not available. Ignoring thinking_config.")
            except Exception as e:
                logger.warning(f"[Gemini] Failed to set thinking_config: {e}")

        return config
