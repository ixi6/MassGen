"""
Azure OpenAI backend implementation.
Uses the official Azure OpenAI client for proper Azure integration.
"""

# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger

from ..logger_config import (
    log_backend_activity,
    log_backend_agent_message,
    log_stream_chunk,
)
from .base import FilesystemSupport, LLMBackend, StreamChunk


class AzureOpenAIBackend(LLMBackend):
    """Azure OpenAI backend using the official Azure OpenAI client.

    Supports Azure OpenAI deployments with proper Azure authentication and configuration.

    Environment Variables:
        AZURE_OPENAI_API_KEY: Azure OpenAI API key
        AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint URL
        AZURE_OPENAI_API_VERSION: Azure OpenAI API version (optional, defaults to 2024-12-01-preview)
    """

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)

        # Get Azure configuration from parameters or environment variables
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "Azure OpenAI API key is required. Set AZURE_OPENAI_API_KEY environment variable or pass api_key parameter.",
            )

        # Persist normalized Azure settings for introspection/tests and sensible defaults.
        self.azure_endpoint = kwargs.get("azure_endpoint") or kwargs.get("base_url") or os.getenv("AZURE_OPENAI_ENDPOINT")
        if self.azure_endpoint and self.azure_endpoint.endswith("/"):
            self.azure_endpoint = self.azure_endpoint[:-1]
        self.api_version = kwargs.get("api_version") or os.getenv(
            "AZURE_OPENAI_API_VERSION",
            "2024-12-01-preview",
        )

    def get_provider_name(self) -> str:
        """Get the name of this provider."""
        return "Azure OpenAI"

    async def stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs,
    ) -> AsyncGenerator[StreamChunk]:
        """
        Stream a response with tool calling support using Azure OpenAI.

        Args:
            messages: Conversation messages
            tools: Available tools schema
            **kwargs: Additional parameters including model (deployment name)
        """
        # Extract agent_id for logging
        agent_id = kwargs.get("agent_id", None)

        log_backend_activity(
            self.get_provider_name(),
            "Starting stream_with_tools",
            {"num_messages": len(messages), "num_tools": len(tools) if tools else 0},
            agent_id=agent_id,
        )

        try:
            # Merge constructor config with stream kwargs (stream kwargs take priority)
            all_params = {**self.config, **kwargs}

            # Import Azure OpenAI client
            from openai import AsyncAzureOpenAI, AsyncOpenAI

            azure_endpoint = all_params.get("azure_endpoint") or all_params.get("base_url") or self.azure_endpoint
            api_version = all_params.get("api_version") or self.api_version

            # Validate required configuration
            if not azure_endpoint:
                raise ValueError(
                    "Azure OpenAI endpoint URL is required. Set AZURE_OPENAI_ENDPOINT environment variable or pass azure_endpoint/base_url parameter.",
                )

            # Clean up endpoint URL
            if azure_endpoint.endswith("/"):
                azure_endpoint = azure_endpoint[:-1]

            # Detect if this is an OpenAI-compatible endpoint (v1 format) or Azure-specific
            # OpenAI-compatible endpoints contain "/openai/v1" in the path
            is_openai_compatible = "/openai/v1" in azure_endpoint

            if is_openai_compatible:
                # Use standard OpenAI client for OpenAI-compatible Azure endpoints
                log_backend_activity(
                    self.get_provider_name(),
                    "Using OpenAI-compatible endpoint",
                    {"endpoint": azure_endpoint},
                    agent_id=agent_id,
                )
                self.client = AsyncOpenAI(
                    base_url=azure_endpoint,
                    api_key=self.api_key,
                )
            else:
                # Use Azure-specific client for traditional Azure OpenAI endpoints
                if not api_version:
                    raise ValueError(
                        "Azure OpenAI API version is required for Azure-specific endpoints. Set AZURE_OPENAI_API_VERSION environment variable or pass api_version parameter.",
                    )

                log_backend_activity(
                    self.get_provider_name(),
                    "Using Azure-specific endpoint",
                    {"endpoint": azure_endpoint, "api_version": api_version},
                    agent_id=agent_id,
                )
                self.client = AsyncAzureOpenAI(
                    api_version=api_version,
                    azure_endpoint=azure_endpoint,
                    api_key=self.api_key,
                )

            # Get deployment name from model parameter
            deployment_name = all_params.get("model")
            if not deployment_name:
                raise ValueError(
                    "Azure OpenAI requires a deployment name. Pass it as the 'model' parameter.",
                )

            # Check if workflow tools are present
            workflow_tools = [t for t in tools if t.get("function", {}).get("name") in ["new_answer", "vote", "stop", "submit", "restart_orchestration"]] if tools else []
            has_workflow_tools = len(workflow_tools) > 0

            # CRITICAL DEBUG: Log tool detection (using logger.info to ensure it appears)
            tool_names = [t.get("function", {}).get("name") for t in tools] if tools else []
            logger.info(
                f"[Azure OpenAI] Agent {agent_id}: Tool detection - "
                f"total_tools={len(tools) if tools else 0}, "
                f"all_tool_names={tool_names}, "
                f"workflow_tools_detected={len(workflow_tools)}, "
                f"workflow_tool_names={[t.get('function', {}).get('name') for t in workflow_tools]}, "
                f"has_workflow_tools={has_workflow_tools}",
            )

            # Use messages as-is - tools are passed to API natively
            modified_messages = messages

            # Filter out problematic tool messages for Azure OpenAI
            modified_messages = self._filter_tool_messages_for_azure(modified_messages)

            # Debug: Log workflow tools detection and system prompt
            if has_workflow_tools:
                log_backend_activity(
                    self.get_provider_name(),
                    "Workflow tools detected",
                    {
                        "workflow_tools_count": len(workflow_tools),
                        "workflow_tool_names": [t.get("function", {}).get("name") for t in workflow_tools],
                        "system_message_length": (len(modified_messages[0]["content"]) if modified_messages and modified_messages[0]["role"] == "system" else 0),
                    },
                    agent_id=agent_id,
                )

            # Log messages being sent
            log_backend_agent_message(
                agent_id or "default",
                "SEND",
                {"messages": modified_messages, "tools": len(tools) if tools else 0},
                backend_name=self.get_provider_name(),
            )

            # Prepare API parameters
            api_params = {
                "messages": modified_messages,
                "model": deployment_name,  # Use deployment name directly
                "stream": True,
            }

            # Only add stream_options for models that support it
            # Ministral and some other models don't support stream_options
            models_without_stream_options = ["ministral", "mistral"]
            if not any(model_name.lower() in deployment_name.lower() for model_name in models_without_stream_options):
                api_params["stream_options"] = {
                    "include_usage": True,
                }  # Enable usage tracking in stream

            # Only add tools if explicitly provided and not empty
            if tools and len(tools) > 0:
                # Convert tools to Azure OpenAI format if needed
                converted_tools = self._convert_tools_format(tools)
                api_params["tools"] = converted_tools
            # Note: Don't set tool_choice when no tools are provided - Azure OpenAI doesn't allow it

            # Add other parameters (excluding model since we already set it)
            # Filter out unsupported Azure OpenAI parameters
            excluded_params = self.get_base_excluded_config_params() | {
                # Azure OpenAI specific exclusions
                "model",
                "messages",
                "stream",
                "tools",
                "api_version",
                "azure_endpoint",
                "base_url",
                "enable_web_search",
                "enable_rate_limit",  # Not supported by Azure OpenAI
                "instance_id",  # Not supported by Azure OpenAI
                "api_key",
            }
            for key, value in kwargs.items():
                if key not in excluded_params and value is not None:
                    api_params[key] = value

            # Create streaming response (now properly async)
            stream = await self.client.chat.completions.create(**api_params)

            # Process streaming response with content and tool call accumulation
            accumulated_content = ""
            accumulated_tool_calls = {}  # Track tool calls by index
            complete_response = ""  # Keep track of the complete response
            last_yield_type = None

            async for chunk in stream:
                # Track usage data from chunk (typically in final chunk)
                if hasattr(chunk, "usage") and chunk.usage:
                    self._update_token_usage_from_api_response(
                        chunk.usage,
                        deployment_name,
                    )

                converted = self._convert_chunk_to_stream_chunk(chunk)

                # Accumulate content chunks
                if converted.type == "content" and converted.content:
                    accumulated_content += converted.content
                    complete_response += converted.content  # Add to complete response
                    # Only yield content when we have meaningful chunks (words, not single characters)
                    if len(accumulated_content) >= 10 or " " in accumulated_content:
                        log_backend_agent_message(
                            agent_id or "default",
                            "RECV",
                            {"content": accumulated_content},
                            backend_name=self.get_provider_name(),
                        )
                        log_stream_chunk(
                            "backend.azure_openai",
                            "content",
                            accumulated_content,
                            agent_id,
                        )
                        yield StreamChunk(type="content", content=accumulated_content)
                        accumulated_content = ""
                elif converted.type == "tool_calls":
                    # Accumulate tool call deltas
                    for tc_delta in converted.tool_calls:
                        index = getattr(tc_delta, "index", 0)
                        if index not in accumulated_tool_calls:
                            accumulated_tool_calls[index] = {
                                "id": getattr(tc_delta, "id", None),
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }

                        # Accumulate function name and arguments
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            if hasattr(tc_delta.function, "name") and tc_delta.function.name:
                                accumulated_tool_calls[index]["function"]["name"] = tc_delta.function.name
                            if hasattr(tc_delta.function, "arguments") and tc_delta.function.arguments:
                                accumulated_tool_calls[index]["function"]["arguments"] += tc_delta.function.arguments
                elif converted.type != "content":
                    # Log non-content chunks
                    if converted.type == "error":
                        log_stream_chunk(
                            "backend.azure_openai",
                            "error",
                            converted.error,
                            agent_id,
                        )
                    elif converted.type == "done":
                        log_stream_chunk("backend.azure_openai", "done", None, agent_id)
                    # Yield non-content chunks immediately
                    last_yield_type = converted.type
                    yield converted

            # Yield any remaining accumulated content
            if accumulated_content:
                log_backend_agent_message(
                    agent_id or "default",
                    "RECV",
                    {"content": accumulated_content},
                    backend_name=self.get_provider_name(),
                )
                log_stream_chunk(
                    "backend.azure_openai",
                    "content",
                    accumulated_content,
                    agent_id,
                )
                yield StreamChunk(type="content", content=accumulated_content)

            # Yield any accumulated tool calls
            if accumulated_tool_calls:
                tool_calls_list = [accumulated_tool_calls[i] for i in sorted(accumulated_tool_calls.keys())]
                log_stream_chunk(
                    "backend.azure_openai",
                    "tool_calls",
                    tool_calls_list,
                    agent_id,
                )
                yield StreamChunk(type="tool_calls", tool_calls=tool_calls_list)
                last_yield_type = "tool_calls"

            # Ensure stream termination is signaled
            if last_yield_type != "done":
                log_stream_chunk("backend.azure_openai", "done", None, agent_id)
                yield StreamChunk(type="done")

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            error_msg = f"Azure OpenAI API error: {str(e)}"
            log_backend_activity(
                self.get_provider_name(),
                "Error occurred",
                {
                    "error": str(e),
                    "traceback": error_details,
                    "endpoint": (azure_endpoint if "azure_endpoint" in locals() else "unknown"),
                },
                agent_id=agent_id,
            )
            log_stream_chunk("backend.azure_openai", "error", error_msg, agent_id)
            yield StreamChunk(type="error", error=error_msg)

    def _prepare_messages_with_workflow_tools(
        self,
        messages: list[dict[str, Any]],
        workflow_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prepare messages with workflow tool instructions."""
        if not workflow_tools:
            return messages

        # Find the system message
        system_message = None
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg
                break

        # Create enhanced system message with workflow tool instructions
        enhanced_system = self._build_workflow_tools_system_prompt(
            system_message.get("content", "") if system_message else "",
            workflow_tools,
        )

        # Create new messages list with enhanced system message
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                new_messages.append({"role": "system", "content": enhanced_system})
            else:
                new_messages.append(msg)

        return new_messages

    def _build_workflow_tools_system_prompt(
        self,
        base_system: str,
        workflow_tools: list[dict[str, Any]],
    ) -> str:
        """Build system prompt with workflow tool instructions."""
        system_parts = []

        if base_system:
            system_parts.append(base_system)

        # Add workflow tools information
        if workflow_tools:
            system_parts.append("\n--- Available Tools ---")
            for tool in workflow_tools:
                name = tool.get("function", {}).get("name", "unknown")
                description = tool.get("function", {}).get(
                    "description",
                    "No description",
                )
                system_parts.append(f"- {name}: {description}")

                # Add usage examples for workflow tools
                if name == "new_answer":
                    system_parts.append(
                        '    Usage: {"tool_name": "new_answer", ' '"arguments": {"content": "your answer"}}',
                    )
                elif name == "vote":
                    # Extract valid agent IDs from enum if available
                    agent_id_enum = None
                    for t in workflow_tools:
                        if t.get("function", {}).get("name") == "vote":
                            agent_id_param = t.get("function", {}).get("parameters", {}).get("properties", {}).get("agent_id", {})
                            if "enum" in agent_id_param:
                                agent_id_enum = agent_id_param["enum"]
                            break

                    if agent_id_enum:
                        agent_list = ", ".join(agent_id_enum)
                        system_parts.append(
                            f'    Usage: {{"tool_name": "vote", ' f'"arguments": {{"agent_id": "agent1", ' f'"reason": "explanation"}}}} // Choose agent_id from: {agent_list}',
                        )
                    else:
                        system_parts.append(
                            '    Usage: {"tool_name": "vote", ' '"arguments": {"agent_id": "agent1", ' '"reason": "explanation"}}',
                        )
                elif name == "stop":
                    system_parts.append(
                        '    Usage: {"tool_name": "stop", "arguments": {"summary": "Brief summary of completed work", ' '"status": "complete"}}  // status: "complete" or "blocked"',
                    )
                elif name == "submit":
                    system_parts.append(
                        '    Usage: {"tool_name": "submit", ' '"arguments": {"confirmed": true}}',
                    )
                elif name == "restart_orchestration":
                    system_parts.append(
                        '    Usage: {"tool_name": "restart_orchestration", ' '"arguments": {"reason": "The answer is incomplete because...", ' '"instructions": "In the next attempt, please..."}}',
                    )

            system_parts.append("\n--- MassGen Workflow Instructions ---")
            system_parts.append(
                "CRITICAL REQUIREMENT: You MUST end your response with a JSON tool call.",
            )
            system_parts.append(
                "This is MANDATORY - responses without a tool call will be rejected.",
            )
            system_parts.append("")
            system_parts.append(
                "Step 1: Provide your analysis and reasoning (optional)",
            )
            system_parts.append("Step 2: End with EXACTLY this format:")
            system_parts.append("")
            system_parts.append("```json")
            system_parts.append(
                '{"tool_name": "TOOL_NAME", "arguments": {YOUR_ARGUMENTS}}',
            )
            system_parts.append("```")
            system_parts.append("")
            system_parts.append("IMPORTANT FORMATTING RULES:")
            system_parts.append("- The JSON MUST be wrapped in ```json and ``` markers")
            system_parts.append("- Use double quotes for all strings")
            system_parts.append(
                "- The field name MUST be 'tool_name' (not 'name' or 'function')",
            )
            system_parts.append("- The arguments MUST be in an 'arguments' object")
            system_parts.append("")
            system_parts.append("Complete Examples:")
            system_parts.append("")
            system_parts.append("Example 1 - Providing a new answer:")
            system_parts.append("```json")
            system_parts.append(
                '{"tool_name": "new_answer", "arguments": {"content": "My answer here"}}',
            )
            system_parts.append("```")
            system_parts.append("")
            system_parts.append("Example 2 - Voting for another agent:")
            system_parts.append("```json")
            system_parts.append(
                '{"tool_name": "vote", "arguments": {"agent_id": "agent1", "reason": "Their answer is better"}}',
            )
            system_parts.append("```")
            system_parts.append("")
            system_parts.append(
                "REMEMBER: Every response MUST end with one of these tool calls!",
            )

        return "\n".join(system_parts)

    def _filter_tool_messages_for_azure(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter out tool messages that don't follow Azure OpenAI requirements."""
        filtered_messages = []
        last_message_had_tool_calls = False

        for message in messages:
            role = message.get("role")

            if role == "tool":
                # Only include tool messages if the previous message had tool_calls
                if last_message_had_tool_calls:
                    filtered_messages.append(message)
                # Otherwise skip this tool message
            else:
                filtered_messages.append(message)
                # Check if this assistant message has tool_calls
                last_message_had_tool_calls = role == "assistant" and "tool_calls" in message and message["tool_calls"]

        return filtered_messages

    def _extract_workflow_tool_calls(self, content: str) -> list[dict[str, Any]]:
        """Extract workflow tool calls from content.

        Tries multiple extraction strategies in order:
        1. Markdown JSON blocks with tool_name
        2. Plain JSON objects with proper nested structure support
        3. Fallback pattern for simple {"content": "..."} format
        4. Loose text patterns for common tool usage phrases
        """
        try:
            import json
            import re

            # Enhanced debug logging to see what we're trying to extract
            logger.info(
                f"[AzureOpenAI] Attempting to extract workflow tools from content (length={len(content)})",
            )
            logger.debug(f"[AzureOpenAI] Full content: {content}")

            # Strategy 1: Look for JSON inside markdown code blocks first
            markdown_json_pattern = r"```json\s*(\{.*?\})\s*```"
            markdown_matches = re.findall(markdown_json_pattern, content, re.DOTALL)

            if markdown_matches:
                logger.info(
                    f"[AzureOpenAI] Found {len(markdown_matches)} markdown JSON blocks",
                )

            for match in reversed(markdown_matches):
                try:
                    parsed = json.loads(match.strip())
                    if isinstance(parsed, dict) and "tool_name" in parsed:
                        logger.info(
                            f"[AzureOpenAI] Successfully extracted tool from markdown: {parsed.get('tool_name')}",
                        )
                        # Convert to MassGen tool call format
                        tool_call = {
                            "id": f"call_{hash(match) % 10000}",  # Generate a unique ID
                            "type": "function",
                            "function": {
                                "name": parsed["tool_name"],
                                "arguments": json.dumps(parsed.get("arguments", {})),
                            },
                        }
                        return [tool_call]
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[AzureOpenAI] Markdown JSON parse failed: {str(e)}",
                    )
                    log_backend_activity(
                        self.get_provider_name(),
                        "Markdown JSON parse failed",
                        {"error": str(e), "json_sample": match[:100]},
                    )
                    continue

            # Strategy 2: Extract all potential JSON blocks and try parsing each
            # This handles nested structures properly by finding balanced braces
            # Pattern matches: { ... } blocks that may contain nested objects
            potential_json_blocks = []
            brace_count = 0
            current_block_start = -1

            for i, char in enumerate(content):
                if char == "{":
                    if brace_count == 0:
                        current_block_start = i
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0 and current_block_start != -1:
                        potential_json_blocks.append(
                            content[current_block_start : i + 1],
                        )
                        current_block_start = -1

            if potential_json_blocks:
                logger.info(
                    f"[AzureOpenAI] Found {len(potential_json_blocks)} potential JSON blocks",
                )

            # Try to parse each potential JSON block
            for block in reversed(
                potential_json_blocks,
            ):  # Process from end to get latest
                if '"tool_name"' not in block:
                    continue

                try:
                    parsed = json.loads(block.strip())
                    if isinstance(parsed, dict) and "tool_name" in parsed:
                        logger.info(
                            f"[AzureOpenAI] Successfully extracted tool from JSON block: {parsed.get('tool_name')}",
                        )
                        # Convert to MassGen tool call format
                        tool_call = {
                            "id": f"call_{hash(block) % 10000}",
                            "type": "function",
                            "function": {
                                "name": parsed["tool_name"],
                                "arguments": json.dumps(parsed.get("arguments", {})),
                            },
                        }
                        return [tool_call]
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[AzureOpenAI] JSON block parse failed: {str(e)}, block: {block[:100]}",
                    )
                    log_backend_activity(
                        self.get_provider_name(),
                        "JSON block parse failed",
                        {"error": str(e), "json_sample": block[:100]},
                    )
                    continue

            # Strategy 3: AZURE OPENAI FALLBACK
            # Handle {"content": "..."} format with flexible whitespace and escaped characters
            # Pattern allows: whitespace, escaped quotes, newlines
            azure_content_pattern = r'\{\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
            azure_matches = re.findall(azure_content_pattern, content, re.DOTALL)

            if azure_matches:
                logger.info(
                    f"[AzureOpenAI] Found {len(azure_matches)} Azure-style content blocks",
                )
                # Take the last content match and convert to new_answer tool call
                answer_content = azure_matches[-1]
                tool_call = {
                    "id": f"call_{hash(answer_content) % 10000}",
                    "type": "function",
                    "function": {
                        "name": "new_answer",
                        "arguments": json.dumps({"content": answer_content}),
                    },
                }
                return [tool_call]

            # Strategy 4: DIRECT ARGUMENTS WITHOUT TOOL_NAME WRAPPER
            # Some models output just the arguments: {"agent_id":"agent1","reason":"..."}
            # or {"content":"..."} without the tool_name wrapper
            for block in reversed(potential_json_blocks):
                try:
                    parsed = json.loads(block.strip())
                    if isinstance(parsed, dict):
                        # Check if it's a vote (has agent_id and reason)
                        if "agent_id" in parsed and "reason" in parsed:
                            logger.info(
                                "[AzureOpenAI] Found vote arguments without tool_name wrapper",
                            )
                            tool_call = {
                                "id": f"call_{hash(block) % 10000}",
                                "type": "function",
                                "function": {
                                    "name": "vote",
                                    "arguments": json.dumps(parsed),
                                },
                            }
                            return [tool_call]
                        # Check if it's a new_answer (has content but not agent_id)
                        elif "content" in parsed and "agent_id" not in parsed:
                            logger.info(
                                "[AzureOpenAI] Found new_answer arguments without tool_name wrapper",
                            )
                            tool_call = {
                                "id": f"call_{hash(block) % 10000}",
                                "type": "function",
                                "function": {
                                    "name": "new_answer",
                                    "arguments": json.dumps(parsed),
                                },
                            }
                            return [tool_call]
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Strategy 5: LOOSE TEXT PATTERN MATCHING
            # Look for common phrases that indicate tool usage even without proper JSON
            # This is a last resort for models that struggle with JSON formatting

            # Pattern 1: Look for "new_answer" with quoted content
            new_answer_pattern = r'new_answer.*?["\'](.+?)["\']'
            new_answer_matches = re.findall(
                new_answer_pattern,
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if new_answer_matches:
                logger.info(
                    "[AzureOpenAI] Found new_answer via loose pattern matching",
                )
                answer_content = new_answer_matches[-1].strip()
                tool_call = {
                    "id": f"call_{hash(answer_content) % 10000}",
                    "type": "function",
                    "function": {
                        "name": "new_answer",
                        "arguments": json.dumps({"content": answer_content}),
                    },
                }
                return [tool_call]

            # Pattern 2: Look for "vote" with agent_id
            vote_pattern = r'vote.*?agent[_\s]*id["\'\s:]*(["\']?agent\d+["\']?)'
            vote_matches = re.findall(vote_pattern, content, re.IGNORECASE)
            if vote_matches:
                logger.info("[AzureOpenAI] Found vote via loose pattern matching")
                agent_id = vote_matches[-1].strip("\"' ")
                # Try to extract reason
                reason_pattern = r'reason["\'\s:]*(["\'](.+?)["\']|([^\n,}]+))'
                reason_matches = re.findall(
                    reason_pattern,
                    content,
                    re.DOTALL | re.IGNORECASE,
                )
                reason = ""
                if reason_matches:
                    # Take the first non-empty group
                    for match in reason_matches:
                        reason = match[1] if match[1] else match[2]
                        if reason:
                            break
                tool_call = {
                    "id": f"call_{hash(content) % 10000}",
                    "type": "function",
                    "function": {
                        "name": "vote",
                        "arguments": json.dumps(
                            {"agent_id": agent_id, "reason": reason.strip()},
                        ),
                    },
                }
                return [tool_call]

            # No tool calls found
            logger.warning(
                f"[AzureOpenAI] No workflow tool calls extracted from content (length={len(content)})",
            )
            logger.warning(f"[AzureOpenAI] Content sample: {content[:500]}")
            log_backend_activity(
                self.get_provider_name(),
                "No workflow tool calls extracted",
                {"content_length": len(content), "content_sample": content[:200]},
            )
            return []

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            logger.error(
                f"[AzureOpenAI] Tool extraction failed with exception: {str(e)}",
            )
            log_backend_activity(
                self.get_provider_name(),
                "Tool extraction failed with exception",
                {
                    "error": str(e),
                    "traceback": error_details,
                    "content_sample": content[:200],
                },
            )
            return []

    def _convert_tools_format(
        self,
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert tools to Azure OpenAI format if needed."""
        # Azure OpenAI uses the same tool format as OpenAI
        return tools

    def _convert_chunk_to_stream_chunk(self, chunk) -> StreamChunk:
        """Convert Azure OpenAI chunk to MassGen StreamChunk format."""
        try:
            if hasattr(chunk, "choices") and chunk.choices:
                choice = chunk.choices[0]

                if hasattr(choice, "delta") and choice.delta:
                    delta = choice.delta

                    # Handle content - this should be the main response
                    if hasattr(delta, "content") and delta.content:
                        return StreamChunk(type="content", content=delta.content)

                    # Handle tool calls - yield them as proper tool_calls chunks
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        # Return tool_calls chunk - will be accumulated in stream_with_tools()
                        return StreamChunk(
                            type="tool_calls",
                            tool_calls=delta.tool_calls,
                        )

                    # Handle finish reason
                    if hasattr(choice, "finish_reason") and choice.finish_reason:
                        if choice.finish_reason == "stop":
                            return StreamChunk(type="done")
                        elif choice.finish_reason == "tool_calls":
                            return StreamChunk(type="done")  # Treat as done

            # Default chunk - this should not happen for valid responses
            return StreamChunk(type="content", content="")

        except Exception as e:
            return StreamChunk(type="error", error=f"Error processing chunk: {str(e)}")

    def extract_tool_call_id(self, tool_call: dict[str, Any]) -> str:
        """Extract tool call id from Chat Completions-style tool call."""
        return tool_call.get("id", "")

    def get_filesystem_support(self) -> FilesystemSupport:
        """OpenAI supports filesystem through MCP servers."""
        return FilesystemSupport.MCP

    def get_supported_builtin_tools(self) -> list[str]:
        """Get list of builtin tools supported by OpenAI."""
        return ["web_search", "code_interpreter"]
