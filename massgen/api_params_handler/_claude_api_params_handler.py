"""
Claude API parameters handler.
Handles parameter building for Anthropic Claude Messages API format.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..logger_config import logger
from ._api_params_handler_base import APIParamsHandlerBase


class ClaudeAPIParamsHandler(APIParamsHandlerBase):
    """Handler for Claude API parameters."""

    # Code execution tool version
    CODE_EXECUTION_VERSION = "code_execution_20250825"

    # Structured outputs beta
    STRUCTURED_OUTPUTS_BETA = "structured-outputs-2025-11-13"

    def _apply_defer_loading(
        self,
        tools: list[dict[str, Any]],
        overrides: dict[str, Any],
        name_extractor: Callable[[str], str],
        tool_type: str,
    ) -> tuple[list[str], list[str]]:
        """Apply defer_loading settings to tools and return deferred/visible lists."""
        deferred_tools = []
        visible_tools = []
        for tool in tools:
            tool_name = tool.get("name", "")
            lookup_key = name_extractor(tool_name)
            override = overrides.get(lookup_key)
            if override is not False:
                tool["defer_loading"] = True
                deferred_tools.append(lookup_key)
            else:
                visible_tools.append(lookup_key)
        if deferred_tools:
            logger.info(f"[Tool Search] {tool_type} tools deferred: {deferred_tools}")
        if visible_tools:
            logger.info(f"[Tool Search] {tool_type} tools visible (defer_loading: false): {visible_tools}")
        return deferred_tools, visible_tools

    @staticmethod
    def _patch_additional_properties(schema: dict[str, Any]) -> None:
        """Recursively add additionalProperties: false to all object schemas."""
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        # Recurse into properties
        for prop in schema.get("properties", {}).values():
            ClaudeAPIParamsHandler._patch_additional_properties(prop)
        # Recurse into array items
        if "items" in schema:
            ClaudeAPIParamsHandler._patch_additional_properties(schema["items"])
        # Recurse into allOf/anyOf/oneOf
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in schema.get(key, []):
                ClaudeAPIParamsHandler._patch_additional_properties(sub)
        # Recurse into $defs/definitions
        for key in ("$defs", "definitions"):
            for defn in schema.get(key, {}).values():
                ClaudeAPIParamsHandler._patch_additional_properties(defn)

    def _apply_strict_to_tools(
        self,
        tools: list[dict[str, Any]],
        overrides: dict[str, Any],
        name_extractor: Callable[[str], str],
        tool_type: str,
    ) -> tuple[list[str], list[str]]:
        """Apply strict settings to tools with recursive schema patching."""
        strict_tools = []
        non_strict_tools = []
        for tool in tools:
            tool_name = tool.get("name", "")
            lookup_key = name_extractor(tool_name)
            override = overrides.get(lookup_key)
            if override is not False:
                tool["strict"] = True
                input_schema = tool.get("input_schema", {})
                if isinstance(input_schema, dict):
                    self._patch_additional_properties(input_schema)
                strict_tools.append(lookup_key)
            else:
                non_strict_tools.append(lookup_key)
        if non_strict_tools:
            logger.info(f"[Strict Tool Use] {tool_type} tools opted-out (strict: false): {non_strict_tools}")
        return strict_tools, non_strict_tools

    @staticmethod
    def _supports_structured_outputs(model: str | None) -> bool:
        """Check if model supports structured outputs (Sonnet 4.5, Opus 4.1 only)."""
        if not model:
            return False
        model_lower = model.lower()
        return "claude-sonnet-4-5" in model_lower or "claude-opus-4-1" in model_lower

    def get_excluded_params(self) -> set[str]:
        """Get parameters to exclude from Claude API calls."""
        return self.get_base_excluded_params().union(
            {
                "enable_web_search",
                "enable_code_execution",
                "enable_programmatic_flow",  # Flag to enable programmatic tool calling
                "enable_tool_search",  # Flag to enable tool search
                "tool_search_variant",  # Tool search variant (regex or bm25)
                "_programmatic_flow_logged",  # Internal flag to prevent duplicate logging
                "_tool_search_logged",  # Internal flag to prevent duplicate logging
                "allowed_tools",
                "exclude_tools",
                "custom_tools",  # Custom tools configuration (processed separately)
                "_has_files_api_files",
                "enable_file_generation",  # Internal flag for file generation (used in system messages only)
                "enable_image_generation",  # Internal flag for image generation (used in system messages only)
                "enable_audio_generation",  # Internal flag for audio generation (used in system messages only)
                "enable_video_generation",  # Internal flag for video generation (used in system messages only)
                "enable_strict_tool_use",  # Structured outputs: strict tool use
                "output_schema",  # Structured outputs: JSON outputs schema
                "_programmatic_flow_logged",  # Internal flag to prevent duplicate logging
                "_tool_search_logged",  # Internal flag to prevent duplicate logging
                "_strict_tool_use_logged",  # Internal flag to prevent duplicate logging
                "_strict_tool_use_enabled",  # Internal metadata for backend StreamChunk
                "_strict_tool_count",  # Internal metadata for backend StreamChunk
                "_strict_tool_names",  # Internal metadata for backend StreamChunk
            },
        )

    def get_provider_tools(self, all_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Get provider tools for Claude format (server-side tools)."""
        provider_tools = []

        if all_params.get("enable_web_search", False):
            provider_tools.append(
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                },
            )

        if all_params.get("enable_code_execution", False):
            provider_tools.append(
                {
                    "type": self.CODE_EXECUTION_VERSION,
                    "name": "code_execution",
                },
            )

        # Tool search tool - enables dynamic tool discovery
        if all_params.get("enable_tool_search", False):
            variant = all_params.get("tool_search_variant", "regex")
            provider_tools.append(
                {
                    "type": f"tool_search_tool_{variant}_20251119",
                    "name": f"tool_search_tool_{variant}",
                },
            )

        return provider_tools

    async def build_api_params(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        all_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Claude API parameters."""
        # Convert messages to Claude format and extract system message
        converted_messages, system_message = self.formatter.format_messages_and_system(messages)

        # Strip trailing whitespace from assistant messages (Claude API rejects trailing whitespace)
        for msg in converted_messages:
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str):
                    msg["content"] = content.rstrip()
                elif isinstance(content, list):
                    # Handle multimodal content
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            item["text"] = item.get("text", "").rstrip()

        # Build base parameters
        api_params: dict[str, Any] = {
            "messages": converted_messages,
            "stream": True,
        }

        # Add filtered parameters
        excluded = self.get_excluded_params()
        for key, value in all_params.items():
            if key not in excluded and value is not None:
                api_params[key] = value

        # Claude API requires max_tokens - add default if not provided
        if "max_tokens" not in api_params:
            api_params["max_tokens"] = 32000

        enable_programmatic = all_params.get("enable_programmatic_flow", False)
        enable_tool_search = all_params.get("enable_tool_search", False)

        if enable_programmatic and not all_params.get("enable_code_execution"):
            all_params["enable_code_execution"] = True

        betas_list = []
        if enable_programmatic or enable_tool_search:
            betas_list.append("advanced-tool-use-2025-11-20")
            if all_params.get("enable_code_execution"):
                betas_list.append("code-execution-2025-08-25")
        elif all_params.get("enable_code_execution"):
            betas_list.append("code-execution-2025-08-25")
        if all_params.get("_has_files_api_files"):
            betas_list.append("files-api-2025-04-14")
        if betas_list:
            api_params["betas"] = betas_list

        # Build defer_loading overrides for custom tools (tool search feature)
        custom_tools_defer_overrides: dict[str, Any] = {}
        if enable_tool_search:
            custom_tools_config = all_params.get("custom_tools", [])
            for tc in custom_tools_config:
                if isinstance(tc, dict):
                    func_names = tc.get("function", tc.get("func", []))
                    if isinstance(func_names, str):
                        func_names = [func_names]
                    defer_val = tc.get("defer_loading")
                    for fn in func_names:
                        custom_tools_defer_overrides[fn] = defer_val

        # Build defer_loading overrides for MCP servers (handle both list and dict formats)
        mcp_defer_overrides: dict[str, Any] = {}
        if enable_tool_search:
            mcp_servers_config = all_params.get("mcp_servers", [])
            if isinstance(mcp_servers_config, dict):
                for server_name, server_config in mcp_servers_config.items():
                    if isinstance(server_config, dict):
                        mcp_defer_overrides[server_name] = server_config.get("defer_loading")
            elif isinstance(mcp_servers_config, list):
                for server in mcp_servers_config:
                    if isinstance(server, dict):
                        server_name = server.get("name", "")
                        mcp_defer_overrides[server_name] = server.get("defer_loading")

        enable_strict = all_params.get("enable_strict_tool_use", False)
        custom_tools_strict_overrides: dict[str, Any] = {}
        if enable_strict:
            custom_tools_config = all_params.get("custom_tools", [])
            for tc in custom_tools_config:
                if isinstance(tc, dict):
                    func_names = tc.get("function", tc.get("func", []))
                    if isinstance(func_names, str):
                        func_names = [func_names]
                    strict_val = tc.get("strict")
                    for fn in func_names:
                        custom_tools_strict_overrides[fn] = strict_val

        mcp_strict_overrides: dict[str, Any] = {}
        if enable_strict:
            mcp_servers_config = all_params.get("mcp_servers", [])
            if isinstance(mcp_servers_config, dict):
                for server_name, server_config in mcp_servers_config.items():
                    if isinstance(server_config, dict):
                        mcp_strict_overrides[server_name] = server_config.get("strict")
            elif isinstance(mcp_servers_config, list):
                for server in mcp_servers_config:
                    if isinstance(server, dict):
                        server_name = server.get("name", "")
                        mcp_strict_overrides[server_name] = server.get("strict")

        # Remove internal flag so it doesn't leak
        all_params.pop("_has_files_api_files", None)

        # Add system message if present
        if system_message:
            api_params["system"] = system_message

        combined_tools = []

        # Server-side tools (provider tools) go first
        provider_tools = self.get_provider_tools(all_params)
        if provider_tools:
            combined_tools.extend(provider_tools)
            if enable_programmatic:
                provider_tool_names = [t.get("name", "unknown") for t in provider_tools]
                logger.debug(
                    f"[Programmatic Flow] Server-side builtin tools (no allowed_callers): {provider_tool_names}",
                )

        # Workflow tools
        if tools:
            converted_tools = self.formatter.format_tools(tools)
            if enable_programmatic:
                workflow_tool_names = [t.get("name", "unknown") for t in converted_tools]
                logger.debug(
                    f"[Programmatic Flow] Workflow tools (direct-call only): {workflow_tool_names}",
                )
            combined_tools.extend(converted_tools)

        # Add custom tools
        custom_tools = self.custom_tool_manager.registered_tools
        if custom_tools:
            converted_custom_tools = self.formatter.format_custom_tools(custom_tools)

            # Apply programmatic flow settings
            if enable_programmatic:
                custom_tool_names = [t.get("name", "unknown") for t in converted_custom_tools]
                logger.debug(
                    f"[Programmatic Flow] Custom tools with allowed_callers: {custom_tool_names}",
                )
                for tool in converted_custom_tools:
                    tool["allowed_callers"] = [self.CODE_EXECUTION_VERSION]

            # Apply tool search defer_loading settings
            if enable_tool_search:
                self._apply_defer_loading(
                    converted_custom_tools,
                    custom_tools_defer_overrides,
                    lambda name: name.replace("custom_tool__", ""),
                    "Custom",
                )

            combined_tools.extend(converted_custom_tools)

        # MCP tools - add allowed_callers and defer_loading
        mcp_tools = self.get_mcp_tools()
        if mcp_tools:
            # Apply programmatic flow settings
            if enable_programmatic:
                mcp_tool_names = [t.get("name", "unknown") for t in mcp_tools]
                logger.debug(
                    f"[Programmatic Flow] MCP tools with allowed_callers: {mcp_tool_names}",
                )
                for tool in mcp_tools:
                    tool["allowed_callers"] = [self.CODE_EXECUTION_VERSION]

            # Apply tool search defer_loading settings
            if enable_tool_search:
                # Extract server name from mcp__<server>__<tool>
                self._apply_defer_loading(
                    mcp_tools,
                    mcp_defer_overrides,
                    lambda name: name.split("__")[1] if len(name.split("__")) >= 2 else "",
                    "MCP",
                )

            combined_tools.extend(mcp_tools)

        # Structured outputs support (strict tools + JSON outputs)
        # Only supported on Claude Sonnet 4.5 and Opus 4.1
        # Requires beta header: structured-outputs-2025-11-13
        model = all_params.get("model")
        output_schema = all_params.get("output_schema")

        # Guard: Strict tool use is incompatible with programmatic flow
        if enable_programmatic and enable_strict:
            logger.warning(
                "[Claude] Strict tool use is not supported with programmatic tool calling. " "Skipping strict tool use.",
            )
            enable_strict = False

        if self._supports_structured_outputs(model):
            needs_structured_beta = False

            # Strict tool use: add strict: true to custom tools (with per-tool overrides)
            if enable_strict and combined_tools:
                custom_type_tools = [t for t in combined_tools if t.get("type") == "custom"]
                if custom_type_tools:
                    # Merge overrides: custom tools + MCP tools
                    all_strict_overrides = {**custom_tools_strict_overrides, **mcp_strict_overrides}

                    # Apply strict with per-tool overrides
                    strict_tools, non_strict_tools = self._apply_strict_to_tools(
                        custom_type_tools,
                        all_strict_overrides,
                        lambda name: (name.replace("custom_tool__", "") if name.startswith("custom_tool__") else (name.split("__")[1] if "__" in name else name)),
                        "User-defined",
                    )
                    if strict_tools:
                        needs_structured_beta = True
                        logger.info(f"[Claude] Strict tool use enabled for {len(strict_tools)} tools")
                        # Store metadata for backend to yield StreamChunk
                        all_params["_strict_tool_use_enabled"] = True
                        all_params["_strict_tool_count"] = len(strict_tools)
                        all_params["_strict_tool_names"] = strict_tools
                else:
                    logger.warning("[Claude] enable_strict_tool_use is true but no user-defined tools found")

            # JSON outputs: add output_format
            if output_schema:
                if isinstance(output_schema, dict) and output_schema:
                    # Patch nested objects with additionalProperties: false
                    self._patch_additional_properties(output_schema)
                    api_params["output_format"] = {
                        "type": "json_schema",
                        "schema": output_schema,
                    }
                    needs_structured_beta = True
                    logger.info("[Claude] JSON outputs enabled")
                else:
                    logger.warning("[Claude] output_schema is invalid or empty, ignoring")

            # Add beta header if either feature is used
            if needs_structured_beta and self.STRUCTURED_OUTPUTS_BETA not in betas_list:
                betas_list.append(self.STRUCTURED_OUTPUTS_BETA)
                api_params["betas"] = betas_list
        else:
            if enable_strict or output_schema:
                logger.warning(
                    f"[Claude] Structured outputs not supported for model '{model}'. " f"Requires Claude Sonnet 4.5 or Opus 4.1.",
                )

        if combined_tools:
            api_params["tools"] = combined_tools
            if enable_programmatic:
                logger.info(
                    f"[Programmatic Flow] Total {len(combined_tools)} tools configured for programmatic calling",
                )
            if enable_tool_search:
                deferred_count = sum(1 for t in combined_tools if t.get("defer_loading"))
                visible_count = len(combined_tools) - deferred_count
                variant = all_params.get("tool_search_variant", "regex")
                logger.info(
                    f"[Tool Search] Total {len(combined_tools)} tools: {visible_count} visible, {deferred_count} deferred (variant: {variant})",
                )

        # Handle disable_parallel_tool_use parameter
        # This controls whether Claude API can call multiple tools in parallel
        if all_params.get("disable_parallel_tool_use", False):
            # Get existing tool_choice or default to "auto"
            existing_tool_choice = api_params.get("tool_choice", {"type": "auto"})

            # Convert to dict format if needed
            if isinstance(existing_tool_choice, str):
                existing_tool_choice = {"type": existing_tool_choice}
            elif isinstance(existing_tool_choice, dict):
                existing_tool_choice = existing_tool_choice.copy()
            else:
                existing_tool_choice = {"type": "auto"}

            # Add disable_parallel_tool_use flag to tool_choice
            existing_tool_choice["disable_parallel_tool_use"] = True
            api_params["tool_choice"] = existing_tool_choice

        return api_params
