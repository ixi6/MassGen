"""
Common chat interface for MassGen agents.

Defines the standard interface that both individual agents and the orchestrator implement,
allowing seamless interaction regardless of whether you're talking to a single agent
or a coordinated multi-agent system.

# TODO: Consider how to best handle stateful vs stateless backends in this interface.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from .backend.base import LLMBackend, StreamChunk
from .logger_config import log_streaming_debug, logger
from .memory import ConversationMemory, PersistentMemoryBase
from .stream_chunk import ChunkType
from .utils import CoordinationStage

if TYPE_CHECKING:
    pass


class ChatAgent(ABC):
    """
    Abstract base class defining the common chat interface.

    This interface is implemented by both individual agents and the MassGen orchestrator,
    providing a unified way to interact with any type of agent system.
    """

    def __init__(
        self,
        session_id: str | None = None,
        conversation_memory: ConversationMemory | None = None,
        persistent_memory: PersistentMemoryBase | None = None,
    ):
        self.session_id = session_id or f"chat_session_{uuid.uuid4().hex[:8]}"
        self.conversation_history: list[dict[str, Any]] = []

        # Memory components
        self.conversation_memory = conversation_memory
        self.persistent_memory = persistent_memory

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] = None,
        reset_chat: bool = False,
        clear_history: bool = False,
        current_stage: CoordinationStage = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Enhanced chat interface supporting tool calls and responses.

        Args:
            messages: List of conversation messages including:
                - {"role": "user", "content": "..."}
                - {"role": "assistant", "content": "...", "tool_calls": [...]}
                - {"role": "tool", "tool_call_id": "...", "content": "..."}
                Or a single string for backwards compatibility
            tools: Optional tools to provide to the agent
            reset_chat: If True, reset the agent's conversation history to the provided messages
            clear_history: If True, clear history but keep system message before processing messages
            current_stage: Optional current coordination stage for orchestrator use

        Yields:
            StreamChunk: Streaming response chunks
        """

    async def chat_simple(self, user_message: str) -> AsyncGenerator[StreamChunk, None]:
        """
        Backwards compatible simple chat interface.

        Args:
            user_message: Simple string message from user

        Yields:
            StreamChunk: Streaming response chunks
        """
        messages = [{"role": "user", "content": user_message}]
        async for chunk in self.chat(messages):
            yield chunk

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Get current agent status and state."""

    @abstractmethod
    async def reset(self) -> None:
        """Reset agent state for new conversation."""

    @abstractmethod
    def get_configurable_system_message(self) -> str | None:
        """
        Get the user-configurable part of the system message.

        Returns the domain expertise, role definition, or custom instructions
        that were configured for this agent, without backend-specific details.

        Returns:
            The configurable system message if available, None otherwise
        """

    # Common conversation management
    def get_conversation_history(self) -> list[dict[str, Any]]:
        """Get full conversation history."""
        return self.conversation_history.copy()

    def add_to_history(self, role: str, content: str, **kwargs) -> None:
        """Add message to conversation history."""
        message = {"role": role, "content": content}
        message.update(kwargs)  # Support tool_calls, tool_call_id, etc.
        self.conversation_history.append(message)

    def add_tool_message(self, tool_call_id: str, result: str) -> None:
        """Add tool result to conversation history."""
        self.add_to_history("tool", result, tool_call_id=tool_call_id)

    def get_last_tool_calls(self) -> list[dict[str, Any]]:
        """Get tool calls from the last assistant message."""
        for message in reversed(self.conversation_history):
            if message.get("role") == "assistant" and "tool_calls" in message:
                return message["tool_calls"]
        return []

    def get_session_id(self) -> str:
        """Get session identifier."""
        return self.session_id


class SingleAgent(ChatAgent):
    """
    Individual agent implementation with direct backend communication.

    This class wraps a single LLM backend and provides the standard chat interface,
    making it interchangeable with the MassGen orchestrator from the user's perspective.
    """

    def __init__(
        self,
        backend: LLMBackend,
        agent_id: str | None = None,
        system_message: str | None = None,
        session_id: str | None = None,
        conversation_memory: ConversationMemory | None = None,
        persistent_memory: PersistentMemoryBase | None = None,
        context_monitor: Any | None = None,
        record_all_tool_calls: bool = False,
        record_reasoning: bool = False,
        voting_sensitivity: str | None = None,
    ):
        """
        Initialize single agent.

        Args:
            backend: LLM backend for this agent
            agent_id: Optional agent identifier
            system_message: Optional system message for the agent
            session_id: Optional session identifier
            conversation_memory: Optional conversation memory instance
            persistent_memory: Optional persistent memory instance
            context_monitor: Optional context window monitor for tracking token usage
            record_all_tool_calls: If True, record ALL tool calls to memory (including intermediate MCP tools)
            record_reasoning: If True, record reasoning/thinking chunks to memory
            voting_sensitivity: Per-agent voting sensitivity override (lenient, balanced, strict).
                               If None, uses orchestrator-level default.
        """
        super().__init__(session_id, conversation_memory, persistent_memory)
        self.backend = backend
        self.agent_id = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self.system_message = system_message
        self.context_monitor = context_monitor
        self._turn_number = 0
        self.voting_sensitivity = voting_sensitivity  # Per-agent override (None = use orchestrator default)

        # Track orchestrator turn number (for turn-aware memory)
        self._orchestrator_turn = None

        # Track if compression has occurred (for smart retrieval)
        self._compression_has_occurred = False

        # Retrieval configuration (defaults, can be overridden from config)
        self._retrieval_limit = 5  # Number of memory facts to retrieve from mem0
        # Retrieve by default so persistent memory is consulted on first turn; callers can opt out via config
        self._retrieval_exclude_recent = False

        # Track previous winning agents for shared memory retrieval
        # Format: [{"agent_id": "agent_b", "turn": 1}, {"agent_id": "agent_a", "turn": 2}]
        self._previous_winners = []

        # Memory recording configuration
        self._record_all_tool_calls = record_all_tool_calls  # Record ALL tools (not just workflow)
        self._record_reasoning = record_reasoning  # Record reasoning chunks

        # Create context compressor if monitor and conversation_memory exist
        self.context_compressor = None

        if self.context_monitor and self.conversation_memory:
            from .memory._compression import ContextCompressor
            from .token_manager.token_manager import TokenCostCalculator

            self.context_compressor = ContextCompressor(
                token_calculator=TokenCostCalculator(),
                conversation_memory=self.conversation_memory,
                persistent_memory=self.persistent_memory,
            )
            logger.info(f"🗜️  Context compressor created for {self.agent_id}")

        # Add system message to history if provided
        if self.system_message:
            self.conversation_history.append({"role": "system", "content": self.system_message})

        # Orchestrator reference (for coordination features)
        self._orchestrator = None  # Will be set by orchestrator during initialization

        # Track current turn's full context (for shadow agents to access)
        # This captures everything streamed in the current turn, not just text content
        # Cleared at the start of each turn
        self._current_turn_content = ""  # Text content
        self._current_turn_tool_calls = []  # Tool calls made
        self._current_turn_reasoning = []  # Reasoning/thinking (if enabled)
        self._current_turn_mcp_calls = []  # MCP tool calls with args/results

    @staticmethod
    def _sanitize_messages_for_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Sanitize messages to ensure they are valid for OpenAI API.

        OpenAI requires:
        - Assistant messages with tool_calls can have content=None
        - Assistant messages without tool_calls MUST have content as string (not None)
        - All other roles must have content as string

        Args:
            messages: List of message dicts (may have None content values)

        Returns:
            Sanitized list of messages safe for OpenAI API
        """
        sanitized = []
        for msg in messages:
            msg_copy = msg.copy()
            role = msg_copy.get("role", "")
            content = msg_copy.get("content")
            tool_calls = msg_copy.get("tool_calls")

            if role == "assistant":
                # Assistant with tool_calls can have None content
                if tool_calls:
                    # Keep content as-is (can be None)
                    pass
                else:
                    # No tool_calls - content must be a string
                    if content is None:
                        msg_copy["content"] = ""
            else:
                # Other roles: content should be string, not None
                if content is None:
                    msg_copy["content"] = ""

            sanitized.append(msg_copy)
        return sanitized

    @staticmethod
    def _get_chunk_type_value(chunk) -> str:
        """
        Extract chunk type as string, handling both legacy and typed chunks.

        Args:
            chunk: StreamChunk, TextStreamChunk, or MultimodalStreamChunk

        Returns:
            String representation of chunk type (e.g., "content", "tool_calls")
        """
        chunk_type = chunk.type

        if isinstance(chunk_type, ChunkType):
            return chunk_type.value

        return str(chunk_type)

    async def _process_stream(self, backend_stream, tools: list[dict[str, Any]] = None) -> AsyncGenerator[StreamChunk, None]:
        """Common streaming logic for processing backend responses."""
        assistant_response = ""
        tool_calls = []
        complete_message = None
        messages_to_record = []

        # Clear current turn context at start of stream processing (for shadow agents)
        self._current_turn_content = ""
        self._current_turn_tool_calls = []
        self._current_turn_reasoning = []
        self._current_turn_mcp_calls = []

        # Optional accumulators (based on config)
        all_tool_calls_executed = [] if self._record_all_tool_calls else None
        reasoning_chunks = [] if self._record_reasoning else None
        reasoning_summaries = [] if self._record_reasoning else None

        try:
            async for chunk in backend_stream:
                chunk_type = self._get_chunk_type_value(chunk)
                if chunk_type == "content":
                    assistant_response += chunk.content
                    # Also track for shadow agents to access
                    self._current_turn_content += chunk.content
                    yield chunk
                elif chunk_type == "tool_calls":
                    chunk_tool_calls = getattr(chunk, "tool_calls", []) or []
                    tool_calls.extend(chunk_tool_calls)

                    # Track for shadow agents (always)
                    self._current_turn_tool_calls.extend(chunk_tool_calls)

                    # Optionally accumulate ALL tool calls for memory
                    if self._record_all_tool_calls and chunk_tool_calls:
                        all_tool_calls_executed.extend(chunk_tool_calls)
                        logger.debug(f"   🔧 [ALL mode] Accumulated {len(chunk_tool_calls)} tool(s), total: {len(all_tool_calls_executed)}")

                    yield chunk
                elif chunk_type == "reasoning":
                    # Track for shadow agents (always capture reasoning)
                    if hasattr(chunk, "content") and chunk.content:
                        self._current_turn_reasoning.append({"type": "reasoning", "content": chunk.content})

                    # Optionally accumulate reasoning chunks for memory
                    if self._record_reasoning and hasattr(chunk, "content") and chunk.content:
                        reasoning_chunks.append(chunk.content)
                    yield chunk
                elif chunk_type == "reasoning_summary":
                    # Track for shadow agents
                    if hasattr(chunk, "content") and chunk.content:
                        self._current_turn_reasoning.append({"type": "summary", "content": chunk.content})

                    # Optionally accumulate reasoning summaries for memory
                    if self._record_reasoning and hasattr(chunk, "content") and chunk.content:
                        reasoning_summaries.append(chunk.content)
                    yield chunk
                elif chunk_type == "mcp_status":
                    # Extract status for broadcast checking (always needed)
                    status = getattr(chunk, "status", "")
                    content = getattr(chunk, "content", "")

                    import re

                    # Track MCP tool calls for shadow agents (always) and optionally for memory
                    # Status 1: Tool call initiated - "🔧 [MCP Tool] Calling tool_name..."
                    if status == "mcp_tool_called" and "Calling " in content:
                        match = re.search(r"Calling ([^\s\.]+)", content)
                        if match:
                            tool_name = match.group(1)
                            mcp_call = {
                                "name": tool_name,
                                "type": "mcp_tool",
                                "arguments": "",  # Will be filled in next chunk
                                "result": "",  # Will be filled in later chunk
                            }
                            # Track for shadow agents
                            self._current_turn_mcp_calls.append(mcp_call)
                            # Track for memory if enabled
                            if self._record_all_tool_calls and all_tool_calls_executed is not None:
                                all_tool_calls_executed.append(mcp_call.copy())
                            logger.debug(f"   🔧 [MCP tracking] Started tracking: {tool_name}")

                    # Status 2: Arguments - "Arguments for Calling tool_name: {...}"
                    elif status == "function_call" and "Arguments for Calling " in content:
                        match = re.search(r"Arguments for Calling ([^\s:]+): (.+)", content)
                        if match:
                            tool_name = match.group(1)
                            args = match.group(2)
                            # Update shadow agent tracking
                            for tool in reversed(self._current_turn_mcp_calls):
                                if tool.get("name") == tool_name and not tool.get("arguments"):
                                    tool["arguments"] = args
                                    break
                            # Update memory tracking if enabled
                            if self._record_all_tool_calls and all_tool_calls_executed:
                                for tool in reversed(all_tool_calls_executed):
                                    if tool.get("name") == tool_name and not tool.get("arguments"):
                                        tool["arguments"] = args
                                        logger.debug(f"   🔧 [MCP tracking] Added args for: {tool_name}")
                                        break

                    # Status 3: Results - "Results for Calling tool_name: [...]"
                    elif status == "function_call_output" and "Results for Calling " in content:
                        match = re.search(r"Results for Calling ([^\s:]+): (.+)", content, re.DOTALL)
                        if match:
                            tool_name = match.group(1)
                            result = match.group(2)
                            # Update shadow agent tracking
                            for tool in reversed(self._current_turn_mcp_calls):
                                if tool.get("name") == tool_name and not tool.get("result"):
                                    tool["result"] = result
                                    break
                            # Update memory tracking if enabled
                            if self._record_all_tool_calls and all_tool_calls_executed:
                                for tool in reversed(all_tool_calls_executed):
                                    if tool.get("name") == tool_name and not tool.get("result"):
                                        tool["result"] = result
                                        logger.debug(f"   🔧 [MCP tracking] Added result for: {tool_name}")
                                        break

                    yield chunk
                elif chunk_type == "complete_message":
                    # Backend provided the complete message structure
                    complete_message = chunk.complete_message
                    # Don't yield this - it's for internal use
                elif chunk_type == "complete_response":
                    # Backend provided the raw Responses API response
                    if chunk.response:
                        complete_message = chunk.response

                        # Extract and yield tool calls for orchestrator processing
                        if isinstance(chunk.response, dict) and "output" in chunk.response:
                            response_tool_calls = []
                            for output_item in chunk.response["output"]:
                                if output_item.get("type") == "function_call":
                                    response_tool_calls.append(output_item)
                                    tool_calls.append(output_item)  # Also store for fallback

                            # Yield tool calls so orchestrator can process them
                            if response_tool_calls:
                                yield StreamChunk(type="tool_calls", tool_calls=response_tool_calls)
                    # Complete response is for internal use - don't yield it
                elif chunk_type == "done":
                    # Debug: Log what we have before assembling
                    logger.debug(f"🔍 [done] assistant_response length: {len(assistant_response)}")

                    # Assemble messages for memory recording
                    # SIMPLIFIED: Just use accumulated assistant_response + optional reasoning + tool calls
                    # (We flatten everything to text in record() anyway, so complex parsing was unnecessary)
                    messages_to_record = []

                    # 1. Add reasoning if enabled and present
                    if self._record_reasoning and reasoning_chunks:
                        combined_reasoning = "\n".join(reasoning_chunks)
                        messages_to_record.append(
                            {
                                "role": "assistant",
                                "content": f"[Reasoning]\n{combined_reasoning}",
                            },
                        )
                        logger.debug(f"   ✅ Added reasoning ({len(combined_reasoning)} chars)")

                    # 2. Add reasoning summaries if enabled and present
                    if self._record_reasoning and reasoning_summaries:
                        combined_summary = "\n".join(reasoning_summaries)
                        messages_to_record.append(
                            {
                                "role": "assistant",
                                "content": f"[Reasoning Summary]\n{combined_summary}",
                            },
                        )
                        logger.debug(f"   ✅ Added reasoning summary ({len(combined_summary)} chars)")

                    # 3. Add main response text (accumulated from all content chunks)
                    if assistant_response.strip():
                        messages_to_record.append(
                            {
                                "role": "assistant",
                                "content": assistant_response.strip(),
                            },
                        )
                        logger.debug(f"   ✅ Added main response ({len(assistant_response)} chars)")

                    # 4. Add tool calls to memory
                    tool_calls_info = []

                    # Debug: Log which path we're taking
                    logger.debug(
                        f"🔍 [done] record_all_tool_calls={self._record_all_tool_calls}, all_tool_calls_executed={len(all_tool_calls_executed) if all_tool_calls_executed is not None else 'None'}",
                    )

                    # Option A: Record ALL tool calls (including intermediate MCP tools)
                    if self._record_all_tool_calls and all_tool_calls_executed is not None and len(all_tool_calls_executed) > 0:
                        for tool_call in all_tool_calls_executed:
                            tool_name = tool_call.get("name", "unknown")
                            tool_args = tool_call.get("arguments", {})
                            tool_result = tool_call.get("result", "")

                            tool_info = f"[Tool Call: {tool_name}]"
                            if tool_args:
                                # Arguments might be string (JSON) or dict
                                args_str = tool_args if isinstance(tool_args, str) else str(tool_args)
                                if args_str:  # Only add if not empty
                                    tool_info += f"\nArguments: {args_str}"
                            if tool_result:
                                # MCP tools captured from mcp_status chunks have results
                                tool_info += f"\nResult: {tool_result}"

                            tool_calls_info.append(tool_info)

                        logger.debug(f"   ✅ Captured {len(all_tool_calls_executed)} tool call(s) (ALL mode)")

                    # Option B: Default - only record workflow tools from complete_message
                    elif complete_message and isinstance(complete_message, dict) and "output" in complete_message:
                        # Store raw output for orchestrator (needs full format)
                        self.conversation_history.extend(complete_message["output"])

                        # Collect tool outputs by call_id
                        tool_outputs_map = {}
                        for output_item in complete_message["output"]:
                            if isinstance(output_item, dict) and output_item.get("type") == "function_call_output":
                                call_id = output_item.get("call_id")
                                output = output_item.get("output", "")
                                if call_id:
                                    tool_outputs_map[call_id] = output

                        # Extract workflow tool calls (new_answer, vote, etc.)
                        for output_item in complete_message["output"]:
                            if not isinstance(output_item, dict):
                                continue

                            if output_item.get("type") == "function_call":
                                tool_name = output_item.get("name", "unknown")
                                tool_args = output_item.get("arguments", {})
                                call_id = output_item.get("call_id", "")

                                # Get the output for this tool call
                                tool_output = tool_outputs_map.get(call_id, "")

                                # Format tool call with full data (no truncation)
                                tool_info = f"[Tool Call: {tool_name}]"
                                if tool_args:
                                    args_str = str(tool_args)
                                    tool_info += f"\nArguments: {args_str}"
                                if tool_output:
                                    output_str = str(tool_output)
                                    tool_info += f"\nResult: {output_str}"

                                tool_calls_info.append(tool_info)
                                logger.debug(f"   ✅ Captured workflow tool call: {tool_name}")

                        logger.debug(f"   ✅ Captured {len(tool_calls_info)} workflow tool call(s)")

                    elif complete_message:
                        # Fallback: add complete_message to conversation_history for orchestrator
                        self.conversation_history.append(complete_message)
                        if isinstance(complete_message, dict) and complete_message.get("content"):
                            messages_to_record.append(complete_message)

                    # Add tool calls message if any were captured (either mode)
                    if tool_calls_info:
                        tool_calls_message = "\n\n".join(tool_calls_info)
                        messages_to_record.append(
                            {
                                "role": "assistant",
                                "content": f"[Tool Usage]\n{tool_calls_message}",
                            },
                        )
                        logger.debug(f"   ✅ Added tool usage to memory ({len(tool_calls_info)} call(s))")

                    # Record to memories
                    logger.debug(f"📋 [done chunk] messages_to_record has {len(messages_to_record)} message(s)")

                    if messages_to_record:
                        logger.debug(f"✅ Will record {len(messages_to_record)} message(s) to memory")
                        # Add to conversation memory (use formatted messages, not raw output)
                        if self.conversation_memory:
                            try:
                                await self.conversation_memory.add(messages_to_record)
                                logger.debug(f"📝 Added {len(messages_to_record)} message(s) to conversation memory")
                            except Exception as e:
                                # Log but don't fail if memory add fails
                                logger.warning(f"⚠️  Failed to add response to conversation memory: {e}")
                        # Record to persistent memory with turn metadata
                        if self.persistent_memory:
                            try:
                                # Include turn number in metadata for temporal filtering
                                logger.debug(f"📝 Recording {len(messages_to_record)} messages to persistent memory (turn {self._orchestrator_turn})")
                                await self.persistent_memory.record(
                                    messages_to_record,
                                    metadata={"turn": self._orchestrator_turn} if self._orchestrator_turn else None,
                                )
                                logger.debug("✅ Successfully recorded to persistent memory")
                            except NotImplementedError:
                                # Memory backend doesn't support record
                                logger.warning("⚠️  Persistent memory doesn't support record()")
                            except Exception as e:
                                # Log but don't fail if memory record fails
                                logger.warning(f"⚠️  Failed to record to persistent memory: {e}")

                    # Log context usage after response (if monitor enabled)
                    if self.context_monitor:
                        # Use official API token counts (most accurate for cost/pricing)
                        actual_input_tokens = None
                        if hasattr(self, "backend") and hasattr(self.backend, "_last_call_input_tokens"):
                            actual_input_tokens = self.backend._last_call_input_tokens

                        if actual_input_tokens and actual_input_tokens > 0:
                            # Use official API token count (available at stream end)
                            usage_info = self.context_monitor.log_context_usage_from_tokens(
                                actual_input_tokens,
                                turn_number=self._turn_number,
                            )
                            logger.debug(
                                f"[{self.agent_id}] Using official API token count: {actual_input_tokens:,} tokens",
                            )
                        else:
                            # No API token count available - use default empty usage info
                            usage_info = {
                                "current_tokens": 0,
                                "max_tokens": self.context_monitor.context_window,
                                "usage_percent": 0,
                                "should_compress": False,
                                "target_tokens": int(self.context_monitor.context_window * self.context_monitor.target_ratio),
                            }
                            logger.debug(
                                f"[{self.agent_id}] No API token count available",
                            )

                        # Use algorithmic compression if threshold exceeded
                        if self.context_compressor and usage_info.get("should_compress"):
                            logger.info(
                                f"🔄 Attempting algorithmic compression for {self.agent_id} " f"({usage_info['current_tokens']:,} → {usage_info['target_tokens']:,} tokens)",
                            )
                            # Get messages for compression
                            compression_stats = await self.context_compressor.compress_if_needed(
                                messages=self.conversation_history,
                                current_tokens=usage_info["current_tokens"],
                                target_tokens=usage_info["target_tokens"],
                                should_compress=True,
                            )

                            # Update conversation_history if compression occurred
                            if compression_stats and self.conversation_memory:
                                # Reload from conversation memory (it was updated by compressor)
                                self.conversation_history = await self.conversation_memory.get_messages()
                                # Mark that compression has occurred
                                self._compression_has_occurred = True
                                logger.info(
                                    f"✅ Conversation history updated after compression: " f"{len(self.conversation_history)} messages",
                                )
                        elif usage_info.get("should_compress") and not self.context_compressor:
                            logger.warning(
                                f"⚠️  Should compress but compressor not available " f"(monitor={self.context_monitor is not None}, " f"conv_mem={self.conversation_memory is not None})",
                            )
                    yield chunk
                else:
                    yield chunk

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.add_to_history("assistant", error_msg)
            yield StreamChunk(type="content", content=error_msg)
            yield StreamChunk(type="error", error=str(e))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] = None,
        reset_chat: bool = False,
        clear_history: bool = False,
        current_stage: CoordinationStage = None,
        orchestrator_turn: int | None = None,
        previous_winners: list[dict[str, Any]] | None = None,
        vote_only: bool = False,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Process messages through single backend with tool support.

        Args:
            reset_chat: Reset conversation history to provided messages
            clear_history: Clear conversation history but keep system messages
            orchestrator_turn: Current orchestrator turn number (for turn-aware memory)
            previous_winners: List of previous winning agents with turns
                             Format: [{"agent_id": "agent_b", "turn": 1}, ...]
            vote_only: If True, agent is in vote-only mode (reached answer limit)
                       Backends like Gemini will use a vote-only schema
        """
        # Store vote_only for use in _get_backend_params
        self._vote_only = vote_only
        # Update orchestrator turn if provided
        if orchestrator_turn is not None:
            logger.debug(f"🔍 [chat] Setting orchestrator_turn={orchestrator_turn} for {self.agent_id}")
            self._orchestrator_turn = orchestrator_turn

        # Update previous winners if provided
        if previous_winners is not None:
            logger.debug(f"🔍 [chat] Setting previous_winners={previous_winners} for {self.agent_id}")
            self._previous_winners = previous_winners
        else:
            logger.debug(f"🔍 [chat] No previous_winners provided to {self.agent_id} (current: {self._previous_winners})")
        if clear_history:
            # Clear history but keep system message if it exists
            system_messages = [msg for msg in self.conversation_history if msg.get("role") == "system"]
            self.conversation_history = system_messages.copy()
            # Clear backend history while maintaining session
            if self.backend.is_stateful():
                await self.backend.clear_history()
            # Clear conversation memory if available
            if self.conversation_memory:
                await self.conversation_memory.clear()

        if reset_chat:
            # Reset conversation history to the provided messages
            logger.debug(f"🔄 Resetting chat for {self.agent_id}")
            self.conversation_history = messages.copy()
            # Reset backend state completely
            if self.backend.is_stateful():
                await self.backend.reset_state()
            # Reset conversation memory
            if self.conversation_memory:
                await self.conversation_memory.clear()
                await self.conversation_memory.add(messages)
            backend_messages = self.conversation_history.copy()
        else:
            # Regular conversation - append new messages to agent's history
            self.conversation_history.extend(messages)
            # Add to conversation memory
            if self.conversation_memory:
                try:
                    await self.conversation_memory.add(messages)
                except Exception as e:
                    # Log but don't fail if memory add fails
                    logger.warning(f"Failed to add messages to conversation memory: {e}")
            backend_messages = self.conversation_history.copy()

        # Retrieve relevant persistent memories if available
        # ALWAYS retrieve on reset_chat (to restore recent context after restart)
        # Otherwise, only retrieve if compression has occurred (to avoid duplicating recent context)
        memory_context = ""
        should_retrieve = self.persistent_memory and (reset_chat or self._compression_has_occurred or not self._retrieval_exclude_recent)  # Always retrieve on reset to restore context

        if should_retrieve:
            try:
                # Log retrieval reason and scope
                if reset_chat:
                    logger.info(
                        f"🔄 Retrieving memories after reset for {self.agent_id} " f"(restoring recent context + {len(self._previous_winners) if self._previous_winners else 0} winner(s))...",
                    )
                elif self._previous_winners:
                    logger.info(
                        f"🔍 Retrieving memories for {self.agent_id} + {len(self._previous_winners)} previous winner(s) " f"(limit={self._retrieval_limit}/agent)...",
                    )
                    logger.debug(f"   Previous winners: {self._previous_winners}")
                else:
                    logger.info(
                        f"🔍 Retrieving memories for {self.agent_id} " f"(limit={self._retrieval_limit}, compressed={self._compression_has_occurred})...",
                    )

                memory_context = await self.persistent_memory.retrieve(
                    messages,
                    limit=self._retrieval_limit,
                    previous_winners=self._previous_winners if self._previous_winners else None,
                )

                if memory_context:
                    memory_lines = memory_context.strip().split("\n")
                    logger.info(
                        f"💭 Retrieved {len(memory_lines)} memory fact(s) from mem0",
                    )
                    # Show preview at INFO level (truncate to first 300 chars for readability)
                    preview = memory_context[:300] + "..." if len(memory_context) > 300 else memory_context
                    logger.info(f"   📝 Preview:\n{preview}")
                else:
                    logger.info("   ℹ️  No relevant memories found")
            except NotImplementedError:
                logger.debug("   Persistent memory doesn't support retrieval")
            except Exception as e:
                logger.warning(f"⚠️  Failed to retrieve from persistent memory: {e}")
        elif self.persistent_memory and self._retrieval_exclude_recent:
            logger.debug(
                f"⏭️  Skipping retrieval for {self.agent_id} " f"(no compression yet, all context in conversation_memory)",
            )

        if current_stage:
            self.backend.set_stage(current_stage)

        # Handle stateful vs stateless backends differently
        if self.backend.is_stateful():
            # Stateful: only send new messages, backend maintains context
            backend_messages = messages.copy()
            # Inject memory context before user messages if available
            if memory_context:
                memory_msg = {
                    "role": "system",
                    "content": f"Relevant memories:\n{memory_context}",
                }
                backend_messages.insert(0, memory_msg)
        else:
            # Stateless: use conversation_history as source of truth
            backend_messages = self.conversation_history.copy()
            # Inject memory context before user messages if available
            if memory_context:
                memory_msg = {
                    "role": "system",
                    "content": f"Relevant memories:\n{memory_context}",
                }
                # Insert after any existing system message but before other messages
                insert_idx = 0
                for i, msg in enumerate(backend_messages):
                    if msg.get("role") == "system":
                        insert_idx = i + 1
                    else:
                        break
                backend_messages.insert(insert_idx, memory_msg)

        # Log context usage before processing (if monitor enabled)
        # Use litellm.token_counter for accurate count including tools
        self._turn_number += 1
        if self.context_monitor:
            try:
                import litellm

                # Get model name from backend
                model_name = getattr(self.backend, "model", None)
                if not model_name and hasattr(self.backend, "config"):
                    model_name = self.backend.config.get("model", "gpt-4")

                # Pre-flight token count with messages + tools
                tool_count = len(tools) if tools else 0
                preflight_tokens = litellm.token_counter(
                    model=model_name or "gpt-4",
                    messages=backend_messages,
                    tools=tools if tools else None,
                )
                logger.info(
                    f"🔍 Pre-flight token count for {self.agent_id}: " f"{preflight_tokens:,} tokens ({len(backend_messages)} messages, {tool_count} tools)",
                )

                # Log with actual pre-flight count
                usage_info = self.context_monitor.log_context_usage_from_tokens(
                    current_tokens=preflight_tokens,
                    turn_number=self._turn_number,
                )

                # Check if we should compress BEFORE making the API call
                if usage_info.get("should_compress") and self.context_compressor:
                    logger.warning(
                        f"⚠️ Pre-flight check: {preflight_tokens:,} tokens exceeds threshold. " f"Compressing before API call...",
                    )
                    # Compress using conversation_history
                    compression_stats = await self.context_compressor.compress_if_needed(
                        messages=self.conversation_history,
                        current_tokens=preflight_tokens,
                        target_tokens=usage_info.get("target_tokens", int(self.context_monitor.context_window * 0.5)),
                        should_compress=True,
                    )
                    if compression_stats and self.conversation_memory:
                        self.conversation_history = await self.conversation_memory.get_messages()
                        self._compression_has_occurred = True
                        # Sanitize messages for OpenAI (ensure no None content without tool_calls)
                        # This is needed because compression may produce messages with None content
                        backend_messages = self._sanitize_messages_for_openai(self.conversation_history)
                        logger.info(f"✅ Pre-flight compression complete: {len(self.conversation_history)} messages")

            except Exception as e:
                # Log error but continue
                logger.debug(f"Pre-flight token count failed: {e}")

        # Sanitize messages before sending to backend
        # This ensures no None content values for non-tool-call messages (OpenAI requirement)
        provider = self.backend.get_provider_name()
        if provider.lower() in ("openai", "azure", "azure openai"):
            backend_messages = self._sanitize_messages_for_openai(backend_messages)

        # Create backend stream and process it
        backend_stream = self.backend.stream_with_tools(
            messages=backend_messages,
            tools=tools,  # Use provided tools (for MassGen workflow)
            agent_id=self.agent_id,
            session_id=self.session_id,
            **self._get_backend_params(),
        )

        async for chunk in self._process_stream(backend_stream, tools):
            log_streaming_debug(chunk, agent_id=self.agent_id)  # Full repr goes to streaming_debug.log
            yield chunk

    def _get_backend_params(self) -> dict[str, Any]:
        """Get additional backend parameters. Override in subclasses."""
        params = {}
        # Include vote_only if set (for Gemini vote-only schema)
        if hasattr(self, "_vote_only") and self._vote_only:
            params["vote_only"] = True
        return params

    def get_status(self) -> dict[str, Any]:
        """Get current agent status."""
        return {
            "agent_type": "single",
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "system_message": self.system_message,
            "conversation_length": len(self.conversation_history),
        }

    async def reset(self) -> None:
        """Reset conversation for new chat."""
        self.conversation_history.clear()

        # Reset stateful backend if needed
        if self.backend.is_stateful():
            await self.backend.reset_state()

        # Clear conversation memory (not persistent memory)
        if self.conversation_memory:
            await self.conversation_memory.clear()

        # Re-add system message if it exists
        if self.system_message:
            self.conversation_history.append({"role": "system", "content": self.system_message})

    def get_configurable_system_message(self) -> str | None:
        """Get the user-configurable part of the system message."""
        return self.system_message

    def set_model(self, model: str) -> None:
        """Set the model for this agent."""
        self.model = model

    def set_system_message(self, system_message: str) -> None:
        """Set or update the system message."""
        self.system_message = system_message

        # Remove old system message if exists
        if self.conversation_history and self.conversation_history[0].get("role") == "system":
            self.conversation_history.pop(0)

        # Add new system message at the beginning
        self.conversation_history.insert(0, {"role": "system", "content": system_message})


class ConfigurableAgent(SingleAgent):
    """
    Single agent that uses AgentConfig for advanced configuration.

    This bridges the gap between SingleAgent and the MassGen system by supporting
    all the advanced configuration options (web search, code execution, etc.)
    while maintaining the simple chat interface.

    TODO: Consider merging with SingleAgent. The main difference is:
    - SingleAgent: backend parameters passed directly to constructor/methods
    - ConfigurableAgent: backend parameters come from AgentConfig object

    Could be unified by making SingleAgent accept an optional config parameter
    and using _get_backend_params() pattern for all parameter sources.
    """

    def __init__(
        self,
        config,  # AgentConfig - avoid circular import
        backend: LLMBackend,
        session_id: str | None = None,
        conversation_memory: ConversationMemory | None = None,
        persistent_memory: PersistentMemoryBase | None = None,
        context_monitor: Any | None = None,
        record_all_tool_calls: bool = False,
        record_reasoning: bool = False,
        voting_sensitivity: str | None = None,
    ):
        """
        Initialize configurable agent.

        Args:
            config: AgentConfig with all settings
            backend: LLM backend
            session_id: Optional session identifier
            conversation_memory: Optional conversation memory instance
            persistent_memory: Optional persistent memory instance
            context_monitor: Optional context window monitor for tracking token usage
            record_all_tool_calls: If True, record ALL tool calls to memory (including intermediate MCP tools)
            record_reasoning: If True, record reasoning/thinking chunks to memory
            voting_sensitivity: Per-agent voting sensitivity override (lenient, balanced, strict).
                               If None, uses orchestrator-level default.
        """
        # Extract system message without triggering deprecation warning
        system_message = None
        if hasattr(config, "_custom_system_instruction"):
            system_message = config._custom_system_instruction

        super().__init__(
            backend=backend,
            agent_id=config.agent_id,
            system_message=system_message,
            session_id=session_id,
            conversation_memory=conversation_memory,
            persistent_memory=persistent_memory,
            context_monitor=context_monitor,
            record_all_tool_calls=record_all_tool_calls,
            record_reasoning=record_reasoning,
            voting_sensitivity=voting_sensitivity,
        )
        self.config = config

        # ConfigurableAgent relies on backend_params for model configuration

        # Initialize NLIP router if enabled
        if hasattr(config, "enable_nlip") and config.enable_nlip:
            # Get ToolManager from backend
            tool_manager = None
            if hasattr(self.backend, "custom_tool_manager"):
                tool_manager = self.backend.custom_tool_manager
            else:
                logger.warning(
                    f"Backend {self.backend.__class__.__name__} does not have " f"custom_tool_manager. NLIP will be disabled.",
                )
                config.enable_nlip = False

            if tool_manager:
                mcp_executor = getattr(self.backend, "_execute_mcp_function_with_retry", None)
                config.init_nlip_router(
                    tool_manager=tool_manager,
                    mcp_executor=mcp_executor,
                )

                # Inject NLIP router into backend
                if hasattr(self.backend, "set_nlip_router"):
                    self.backend.set_nlip_router(
                        nlip_router=config.nlip_router,
                        enabled=True,
                    )

    def _get_backend_params(self) -> dict[str, Any]:
        """Get backend parameters from config."""
        params = self.config.get_backend_params()
        # Include vote_only if set (for Gemini vote-only schema)
        if hasattr(self, "_vote_only") and self._vote_only:
            params["vote_only"] = True
        return params

    def get_status(self) -> dict[str, Any]:
        """Get current agent status with config details."""
        status = super().get_status()
        status.update(
            {
                "agent_type": "configurable",
                "config": self.config.to_dict(),
                "capabilities": {
                    "web_search": self.config.backend_params.get("enable_web_search", False),
                    "code_execution": self.config.backend_params.get("enable_code_interpreter", False),
                },
            },
        )
        return status

    def get_configurable_system_message(self) -> str | None:
        """Get the user-configurable part of the system message for ConfigurableAgent."""
        # Try multiple sources in order of preference

        # First check if backend has system prompt configuration
        if self.config and self.config.backend_params:
            backend_params = self.config.backend_params

            # For Claude Code: prefer system_prompt (complete override)
            if "system_prompt" in backend_params:
                return backend_params["system_prompt"]

            # Then append_system_prompt (additive)
            if "append_system_prompt" in backend_params:
                return backend_params["append_system_prompt"]

        # Fall back to custom_system_instruction (deprecated but still supported)
        # Access private attribute directly to avoid deprecation warning
        if self.config and hasattr(self.config, "_custom_system_instruction") and self.config._custom_system_instruction:
            return self.config._custom_system_instruction

        # Finally fall back to parent class implementation
        return super().get_configurable_system_message()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_simple_agent(backend: LLMBackend, system_message: str = None, agent_id: str = None) -> SingleAgent:
    """Create a simple single agent."""
    # Use simple default system message if none provided
    if system_message is None:
        import time

        system_message = f"""You are a helpful AI assistant. Provide clear, accurate, and comprehensive responses.

*Note*: The CURRENT TIME is **{time.strftime("%Y-%m-%d %H:%M:%S")}**."""
    return SingleAgent(backend=backend, agent_id=agent_id, system_message=system_message)


def create_expert_agent(domain: str, backend: LLMBackend, model: str = "gpt-4o-mini") -> ConfigurableAgent:
    """Create an expert agent for a specific domain."""
    from .agent_config import AgentConfig

    config = AgentConfig.for_expert_domain(domain, model=model)
    return ConfigurableAgent(config=config, backend=backend)


def create_research_agent(backend: LLMBackend, model: str = "gpt-4o-mini") -> ConfigurableAgent:
    """Create a research agent with web search capabilities."""
    from .agent_config import AgentConfig

    config = AgentConfig.for_research_task(model=model)
    return ConfigurableAgent(config=config, backend=backend)


def create_computational_agent(backend: LLMBackend, model: str = "gpt-4o-mini") -> ConfigurableAgent:
    """Create a computational agent with code execution."""
    from .agent_config import AgentConfig

    config = AgentConfig.for_computational_task(model=model)
    return ConfigurableAgent(config=config, backend=backend)
