# -*- coding: utf-8 -*-
"""
GitHub Copilot backend implementation using github-copilot-sdk.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    from copilot import CopilotClient
    from copilot.types import Tool

    COPILOT_SDK_AVAILABLE = True
except ImportError:
    COPILOT_SDK_AVAILABLE = False
    CopilotClient = object

from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, StreamChunk
from .base_with_custom_tool_and_mcp import CustomToolAndMCPBackend

logger = logging.getLogger(__name__)


class CopilotBackend(StreamingBufferMixin, CustomToolAndMCPBackend):
    """GitHub Copilot backend integration."""

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize Copilot backend."""
        if not COPILOT_SDK_AVAILABLE:
            raise ImportError(
                "github-copilot-sdk is required for CopilotBackend. " "Install it with: pip install github-copilot-sdk",
            )

        super().__init__(api_key, **kwargs)
        self.client = CopilotClient()
        self.sessions: Dict[str, Any] = {}
        self._started = False

    def get_provider_name(self) -> str:
        return "copilot"

    def get_filesystem_support(self) -> FilesystemSupport:
        return FilesystemSupport.MCP

    def _create_client(self, **kwargs):
        return self.client

    async def _ensure_started(self):
        if not self._started:
            try:
                await self.client.start()
                self._started = True
            except Exception as e:
                # Ignore if already running or check state
                if "already running" not in str(e):
                    logger.warning(f"Client start warning: {e}")
                self._started = True

    async def _process_stream(
        self,
        stream,
        all_params,
        agent_id: Optional[str] = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        # Not used — Copilot handles streaming via session events, not a raw stream.
        raise NotImplementedError("CopilotBackend uses session-based streaming, not _process_stream")
        yield  # pragma: no cover — makes this a generator for type checking

    async def _stream_without_custom_and_mcp_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        client,
        **kwargs,
    ) -> AsyncGenerator[StreamChunk, None]:
        # Copilot always uses session-based execution, delegate to the session handler
        async for chunk in self._stream_with_custom_and_mcp_tools(messages, tools, client, **kwargs):
            yield chunk

    async def _stream_with_custom_and_mcp_tools(
        self,
        current_messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        client,
        **kwargs,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Stream with tool support using Copilot Sessions."""
        await self._ensure_started()

        agent_id = kwargs.get("agent_id", self.agent_id or "default")

        # Create a queue for events (mixed SessionEvent and StreamChunk)
        queue = asyncio.Queue()

        # Convert tools
        copilot_tools = []
        for t in tools:
            # Handle OpenAI tool format {"type": "function", "function": {...}}
            tool_def = t
            if "function" in t:
                tool_def = t["function"]

            t_name = tool_def.get("name")
            if not t_name:
                logger.warning(f"Skipping tool without name: {t}")
                continue

            def make_handler(t_name):
                async def handler(params, invocation):
                    # 1. Emit tool call event
                    call_id = getattr(invocation, "id", "unknown")

                    # Convert params to dict if string
                    args_dict = params
                    if isinstance(params, str):
                        try:
                            args_dict = json.loads(params)
                        except (json.JSONDecodeError, ValueError):
                            args_dict = {"raw": params}

                    # Notify Orchestrator of tool call
                    queue.put_nowait(
                        StreamChunk(
                            type="tool_calls",
                            tool_calls=[{"name": t_name, "arguments": args_dict, "id": call_id}],
                            source=agent_id,
                        ),
                    )

                    # 2. Execute Tool

                    # Special handling for workflow tools which shouldn't be executed by generic runner
                    if t_name in ["vote", "new_answer"]:
                        result = "Action accepted."
                        # We don't yield result chunks for these, Orchestrator handles them via tool_calls
                        return result

                    # For standard tools, execute and stream output
                    call_dict = {
                        "name": t_name,
                        "arguments": params,
                        "id": call_id,
                    }

                    result_text = ""
                    try:
                        async for chunk in self.stream_custom_tool_execution(call_dict, agent_id_override=agent_id):
                            queue.put_nowait(chunk)
                            if chunk.completed:
                                result_text = chunk.accumulated_result
                    except Exception as e:
                        result_text = f"Error: {e}"
                        queue.put_nowait(StreamChunk(type="error", error=str(e), source=agent_id))

                    return result_text

                return handler

            copilot_tools.append(
                Tool(
                    name=t_name,
                    description=tool_def.get("description", "") or "",
                    parameters=tool_def.get("parameters"),
                    handler=make_handler(t_name),
                ),
            )

        # Get or Update session
        session = self.sessions.get(agent_id)

        # Extract system message from messages for the session config (Bug 1 fix)
        system_message = None
        for msg in current_messages:
            if msg["role"] == "system":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle structured content blocks
                    content = "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
                if content:
                    system_message = content
                break

        # Prepare session config
        session_config = {
            "model": kwargs.get("model", "gpt-4"),
            "streaming": True,
            "tools": copilot_tools,
        }
        if system_message:
            # SDK expects SystemMessageAppendConfig, not a plain string
            session_config["system_message"] = {"mode": "append", "content": system_message}

        try:
            if session:
                # Reuse/Update session
                session_id = session.session_id
                # resume_session takes session_id and config
                session = await self.client.resume_session(session_id, session_config)
                self.sessions[agent_id] = session
            else:
                session = await self.client.create_session(session_config)
                self.sessions[agent_id] = session
        except Exception as e:
            yield StreamChunk(type="error", error=f"Session creation failed: {e}", source=agent_id)
            return

        # Build prompt from full conversation history (Bug 2 fix)
        # Include all non-system messages so the model sees conversation context,
        # assistant history, and orchestrator enforcement/retry messages.
        prompt_parts = []
        for msg in current_messages:
            if msg["role"] == "system":
                continue
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
            if content:
                prompt_parts.append(f"[{role}]: {content}")

        prompt = "\n\n".join(prompt_parts) if prompt_parts else "Please continue."

        def on_event(event):
            queue.put_nowait(event)

        unsubscribe = session.on(on_event)

        # Track seen event IDs to avoid processing replayed history (Bug 3 fix)
        seen_event_ids = set()
        # Track accumulated content and whether workflow tools were called
        accumulated_content = []
        workflow_tool_called = False

        try:
            # Send message
            await session.send({"prompt": prompt})

            # Event processing loop
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    yield StreamChunk(type="error", error="Response timeout", source=agent_id)
                    break

                # Handle StreamChunk (from our tool handler)
                if isinstance(event, StreamChunk):
                    if event.type == "tool_calls" and event.tool_calls:
                        for tc in event.tool_calls:
                            if tc.get("name") in ("vote", "new_answer"):
                                workflow_tool_called = True
                    yield event
                    continue

                # Handle SessionEvent (from Copilot SDK)
                # Skip replayed/duplicate events (Bug 3 fix)
                event_id = getattr(event, "id", None)
                if event_id is not None:
                    if event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event_id)

                event_type = event.type
                if hasattr(event_type, "value"):
                    event_type = event_type.value

                # Streaming content
                if event_type == "assistant.message_delta":
                    if hasattr(event, "data") and hasattr(event.data, "delta_content"):
                        content = event.data.delta_content
                        if content:
                            accumulated_content.append(content)
                            yield StreamChunk(type="content", content=content, source=agent_id)

                # Streaming reasoning
                elif event_type == "assistant.reasoning_delta":
                    if hasattr(event, "data") and hasattr(event.data, "delta_content"):
                        content = event.data.delta_content
                        if content:
                            yield StreamChunk(type="content", content=content, source=agent_id)

                # Handle termination
                elif event_type == "session.idle":
                    break

                # Handle errors
                elif "error" in str(event_type).lower():
                    pass

        except Exception as e:
            yield StreamChunk(type="error", error=str(e), source=agent_id)
        finally:
            unsubscribe()

        # Fallback: if the model responded with content but never called workflow
        # tools (vote/new_answer), synthesize a new_answer call so the orchestrator
        # can accept the response instead of retrying.
        if not workflow_tool_called and accumulated_content:
            full_answer = "".join(accumulated_content)
            logger.info(f"Copilot agent {agent_id} did not call workflow tools; synthesizing new_answer")
            yield StreamChunk(
                type="tool_calls",
                tool_calls=[
                    {
                        "name": "new_answer",
                        "arguments": {"content": full_answer},
                        "id": f"synth-{agent_id}",
                    },
                ],
                source=agent_id,
            )

    def _append_tool_result_message(self, updated_messages, call, result, tool_type):
        # No-op: Copilot SDK handles tool results internally via session callbacks.
        # The handler function returns the result directly to the SDK, which feeds
        # it back to the model automatically — no manual message appending needed.
        pass

    def _append_tool_error_message(self, updated_messages, call, error_msg, tool_type):
        # No-op: Same as _append_tool_result_message — tool errors are returned
        # directly from the handler to the SDK.
        pass
