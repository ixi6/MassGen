"""
Shadow Agent Implementation for Broadcast Responses.

Shadow agents are lightweight clones of parent agents that respond to broadcast
questions without interrupting the parent's work. They:
- Share the parent's backend (stateless, safe to share)
- Copy the parent's conversation history (full context)
- Include the parent's current turn context:
  - Text content (what's been generated so far)
  - Tool calls (native tools invoked)
  - MCP tool calls (with arguments and results)
  - Reasoning/thinking (for models that support it)
- Use a simplified system prompt (identity preserved, no vote/new_answer)
- Generate tool-free text responses

Debug Mode:
    Use --debug flag when running MassGen to save shadow agent context to files.
    Files are saved to: .massgen/massgen_logs/<session>/turn_<N>/shadow_agents/
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .broadcast.broadcast_dataclasses import BroadcastRequest
    from .chat_agent import SingleAgent

logger = logging.getLogger(__name__)


class ShadowAgentSpawner:
    """Spawns lightweight shadow agents for broadcast responses.

    Shadow agents inherit the parent agent's context and identity but operate
    with a simplified system prompt focused solely on responding to questions.
    They do NOT have access to tools - only text responses.
    """

    def __init__(self, orchestrator):
        """Initialize the spawner with orchestrator reference.

        Args:
            orchestrator: The MassGen orchestrator managing agents
        """
        self.orchestrator = orchestrator

    async def spawn_and_respond(
        self,
        parent_agent: "SingleAgent",
        broadcast_request: "BroadcastRequest",
    ) -> str:
        """
        Spawn a shadow agent with parent's context and generate response.

        The shadow agent:
        1. Shares the parent's backend (stateless)
        2. Copies the parent's full conversation history
        3. Includes parent's current turn context (if any):
           - Text content, tool calls, MCP calls, reasoning
        4. Uses simplified system prompt (preserves identity, no workflow tools)
        5. Generates a single-turn text response

        Args:
            parent_agent: The agent whose context to clone
            broadcast_request: The broadcast request to respond to

        Returns:
            The shadow agent's text response
        """
        shadow_id = f"shadow_{parent_agent.agent_id}_{uuid.uuid4().hex[:4]}"
        logger.info(
            f"[{shadow_id}] Spawning shadow agent for {parent_agent.agent_id} " f"to respond to broadcast from {broadcast_request.sender_agent_id}",
        )

        # 1. Build simplified system prompt (preserves identity, no vote/new_answer)
        shadow_system_prompt = self._build_shadow_system_prompt(
            parent_agent,
            broadcast_request,
        )

        # 2. Get current turn context (if any)
        # This captures everything the parent agent has generated so far in the current turn
        # Including: text content, tool calls, reasoning, MCP tool calls
        current_turn_context = self._build_current_turn_context(parent_agent, shadow_id)

        # 3. Check if backend requires special handling (e.g., Claude Code can't accept assistant messages)
        backend = parent_agent.backend
        is_claude_code = hasattr(backend, "get_provider_name") and backend.get_provider_name() == "claude_code"

        if is_claude_code:
            # Claude Code maintains its own conversation history and can't accept assistant messages
            # Instead, inject context as text within the user message
            shadow_history = self._build_claude_code_compatible_history(
                shadow_system_prompt,
                parent_agent,
                broadcast_request,
                current_turn_context,
                shadow_id,
            )
        else:
            # Standard flow: copy parent history and inject context as messages
            shadow_history = parent_agent.conversation_history.copy()

            # Replace/add system message with shadow prompt
            # Remove existing system messages and add shadow prompt
            shadow_history = [msg for msg in shadow_history if msg.get("role") != "system"]
            shadow_history.insert(0, {"role": "system", "content": shadow_system_prompt})

            # Include current turn context as assistant message
            if current_turn_context:
                shadow_history.append(
                    {
                        "role": "assistant",
                        "content": current_turn_context,
                    },
                )

            # Add broadcast question as user message
            shadow_history.append(
                {
                    "role": "user",
                    "content": self._format_broadcast_question(broadcast_request),
                },
            )

        # 6. Save debug context if --debug flag is enabled
        from .logger_config import get_log_session_dir, is_debug_mode

        _log_session_dir = get_log_session_dir() if is_debug_mode() else None
        debug_file_path = None
        if _log_session_dir:
            debug_file_path = self._save_debug_context(
                shadow_id=shadow_id,
                parent_agent_id=parent_agent.agent_id,
                broadcast_request=broadcast_request,
                shadow_system_prompt=shadow_system_prompt,
                shadow_history=shadow_history,
                current_turn_context=current_turn_context,
                parent_agent=parent_agent,
                log_session_dir=Path(_log_session_dir),
            )

        # 7. Generate single-turn response (no tools)
        response = await self._generate_response(
            parent_agent,
            shadow_history,
            shadow_id,
        )
        # 8. Save response to debug file if --debug flag is enabled
        if is_debug_mode() and debug_file_path:
            self._append_response_to_debug(debug_file_path, response)

        logger.info(
            f"[{shadow_id}] Generated response ({len(response)} chars): " f"{response[:100]}...",
        )

        return response

    def _build_shadow_system_prompt(
        self,
        parent_agent: "SingleAgent",
        broadcast_request: "BroadcastRequest",
    ) -> str:
        """Build simplified system prompt for shadow agent.

        Preserves the parent agent's identity/persona but removes workflow
        tools and focuses on responding to the broadcast question.

        Args:
            parent_agent: The parent agent whose identity to preserve
            broadcast_request: The broadcast to respond to

        Returns:
            Simplified system prompt string
        """
        # Get parent's identity/persona (user-configured system message)
        parent_identity = parent_agent.get_configurable_system_message() or ""

        # Get response_depth from orchestrator config (controls test-time compute scaling)
        response_depth = "medium"
        if hasattr(self.orchestrator, "config") and hasattr(self.orchestrator.config, "coordination_config"):
            response_depth = getattr(self.orchestrator.config.coordination_config, "response_depth", "medium")

        # Build depth-specific instructions for test-time compute scaling
        depth_instruction = self._get_depth_instruction(response_depth)

        # Build shadow prompt with identity but no workflow tools
        prompt_parts = []

        if parent_identity:
            prompt_parts.append(parent_identity)
            prompt_parts.append("\n---\n")

        prompt_parts.append(
            f"""## BROADCAST RESPONSE MODE

You are responding to a question from another agent in your team.

**Response Depth: {response_depth.upper()}**
{depth_instruction}

**What You Know:**
- Your own work context and conversation history (what YOU have been doing)
- Your general knowledge and expertise
- The question text from the asking agent

**Context Layers (IMPORTANT):**
- **Completed Previous Work**: Your conversation history contains solutions and work you have already **finalized and submitted** in past turns. When asked about previous solution, refer to this.
- **Current In-Progress Work**: Any section labeled `[Current work in progress - not yet complete]` is a **PARTIAL DRAFT** from your current active turn — you haven't finished or submitted it yet.
Do NOT treat this as your "previous solution."
- Rule: "previous/last solution" → look in conversation history. "what are you currently working on?" → you may reference the in-progress section.

**What You Do NOT Know:**
- The asking agent's workspace, files, or current work
- What the asking agent has discovered or built
- You do NOT have access to any tools in this mode

**Your Task:**
1. Read the question carefully - the question text is your ONLY window into their work
2. Draw on your own context and expertise to provide helpful guidance
3. If the question lacks necessary context, provide general guidance and note what additional info would help
4. Do NOT assume details about their project unless explicitly stated in the question

**Format:**
- Simply provide your answer as text
- Your response will be sent back to the asking agent
- After responding, this session ends (single-turn)""",
        )

        return "\n".join(prompt_parts)

    def _get_depth_instruction(self, response_depth: str) -> str:
        """Get depth-specific instruction for test-time compute scaling.

        This controls how thorough/complex shadow agent responses should be,
        implementing test-time compute scaling for multi-agent systems.

        Args:
            response_depth: "low", "medium", or "high"

        Returns:
            Depth-specific instruction string
        """
        if response_depth == "low":
            return """Suggest SIMPLE, MINIMAL solutions:
- Prefer basic technologies (vanilla HTML/CSS/JS, simple libraries)
- Avoid complex frameworks or architectures
- Focus on getting the job done with minimal dependencies
- Keep responses brief and to the point"""
        elif response_depth == "high":
            return """Suggest SOPHISTICATED, COMPREHENSIVE solutions:
- Recommend modern frameworks and best practices (React, Next.js, TypeScript, etc.)
- Include architecture considerations (SSR, component libraries, testing, CI/CD)
- Suggest professional-grade tooling and patterns
- Provide thorough, detailed responses with examples"""
        else:  # medium (default)
            return """Suggest BALANCED solutions:
- Use appropriate technology for the task complexity
- Include standard best practices without over-engineering
- Balance simplicity with maintainability
- Be concise but thorough"""

    def _build_current_turn_context(
        self,
        parent_agent: "SingleAgent",
        shadow_id: str,
    ) -> str | None:
        """Build a formatted string of the parent's current turn context.

        Combines text content, tool calls, reasoning, and MCP tool calls
        into a single context string for the shadow agent.

        Args:
            parent_agent: The parent agent with current turn tracking
            shadow_id: ID of the shadow agent for logging

        Returns:
            Formatted context string, or None if no context available
        """
        parts = []

        # Get all tracked context from current turn
        content = getattr(parent_agent, "_current_turn_content", "")
        tool_calls = getattr(parent_agent, "_current_turn_tool_calls", [])
        reasoning = getattr(parent_agent, "_current_turn_reasoning", [])
        mcp_calls = getattr(parent_agent, "_current_turn_mcp_calls", [])

        # Check if we have any context
        has_context = (content and content.strip()) or tool_calls or reasoning or mcp_calls

        if not has_context:
            return None

        parts.append("[Current work in progress - not yet complete]")

        # Add reasoning/thinking if present
        if reasoning:
            parts.append("\n**Reasoning/Thinking:**")
            for r in reasoning:
                if r.get("type") == "summary":
                    parts.append(f"[Summary] {r.get('content', '')}")
                else:
                    parts.append(r.get("content", ""))

        # Add tool calls if present
        if tool_calls:
            parts.append("\n**Tool Calls Made:**")
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name", tc.get("function", {}).get("name", "unknown"))
                    args = tc.get("arguments", tc.get("function", {}).get("arguments", ""))
                    parts.append(f"- {name}({args})")
                else:
                    parts.append(f"- {tc}")

        # Add MCP tool calls if present
        if mcp_calls:
            parts.append("\n**MCP Tool Calls:**")
            for mc in mcp_calls:
                name = mc.get("name", "unknown")
                args = mc.get("arguments", "")
                result = mc.get("result", "")
                parts.append(f"- {name}")
                if args:
                    parts.append(f"  Args: {args}")
                if result:
                    parts.append(f"  Result: {result}")

        # Add text content if present
        if content and content.strip():
            parts.append("\n**Generated Content:**")
            parts.append(content)

        context = "\n".join(parts)

        # Log what we're including
        logger.info(
            f"[{shadow_id}] Including current turn context: " f"content={len(content)} chars, tool_calls={len(tool_calls)}, " f"reasoning={len(reasoning)}, mcp_calls={len(mcp_calls)}",
        )

        return context

    def _build_claude_code_compatible_history(
        self,
        shadow_system_prompt: str,
        parent_agent: "SingleAgent",
        broadcast_request: "BroadcastRequest",
        current_turn_context: str | None,
        shadow_id: str,
    ) -> list:
        """Build a conversation history compatible with Claude Code backend.

        Claude Code maintains its own conversation history and cannot accept
        pre-existing assistant messages. This method injects context as text
        within a single user message instead.

        Args:
            shadow_system_prompt: The shadow agent's system prompt
            parent_agent: The parent agent with conversation history
            broadcast_request: The broadcast request to respond to
            current_turn_context: Optional current turn context string
            shadow_id: ID of the shadow agent for logging

        Returns:
            List of messages compatible with Claude Code (system + user only)
        """
        # Build context summary from parent's conversation history
        context_parts = []

        # Extract relevant context from parent's history (skip system messages)
        parent_history = [msg for msg in parent_agent.conversation_history if msg.get("role") != "system"]

        if parent_history:
            context_parts.append("**Your Previous Work Context:**")
            for msg in parent_history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if content:
                    context_parts.append(f"[{role.upper()}]: {content}")
            context_parts.append("")

        # Add current turn context if available
        if current_turn_context:
            context_parts.append("**Current Work In Progress:**")
            context_parts.append(current_turn_context)
            context_parts.append("")

        # Build the combined user message
        context_text = "\n".join(context_parts) if context_parts else ""
        broadcast_question = self._format_broadcast_question(broadcast_request)

        if context_text:
            user_content = f"{context_text}\n{broadcast_question}"
        else:
            user_content = broadcast_question

        logger.info(
            f"[{shadow_id}] Built Claude Code compatible history: " f"context_parts={len(context_parts)}, user_content={len(user_content)} chars",
        )

        return [
            {"role": "system", "content": shadow_system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _format_broadcast_question(self, broadcast_request: "BroadcastRequest") -> str:
        """Format the broadcast question as a user message.

        Args:
            broadcast_request: The broadcast request containing the question

        Returns:
            Formatted question string
        """
        return f"""**BROADCAST QUESTION FROM {broadcast_request.sender_agent_id.upper()}:**

{broadcast_request.question}

Please provide your response:"""

    async def _generate_response(
        self,
        parent_agent: "SingleAgent",
        messages: list,
        shadow_id: str,
    ) -> str:
        """Generate a text response using the parent's backend.

        Uses the shared backend with no tools to generate a pure text response.

        Args:
            parent_agent: The parent agent (for backend access)
            messages: The shadow agent's conversation history
            shadow_id: ID of the shadow agent for logging

        Returns:
            The generated text response
        """
        # Import ChunkType for proper type comparison
        from .stream_chunk import ChunkType

        # Use parent's backend with empty tools (text-only response)
        backend = parent_agent.backend
        accumulated_content = ""

        try:
            async for chunk in backend.stream_with_tools(
                messages=messages,
                tools=[],  # No tools - text only
                agent_id=shadow_id,
            ):
                # Get chunk type - handle both enum and string types
                chunk_type = chunk.type
                if isinstance(chunk_type, ChunkType):
                    chunk_type_value = chunk_type.value
                else:
                    chunk_type_value = chunk_type

                # Only collect content chunks
                if chunk_type_value == "content" and chunk.content:
                    accumulated_content += chunk.content
                elif chunk_type_value == "complete_message":
                    # Some backends use complete_message for full response
                    if hasattr(chunk, "complete_message") and chunk.complete_message:
                        msg = chunk.complete_message
                        if isinstance(msg, dict) and "content" in msg:
                            # If we haven't accumulated content, use complete message
                            if not accumulated_content:
                                accumulated_content = msg["content"]
                elif chunk_type_value == "error":
                    error_msg = getattr(chunk, "error", "Unknown error")
                    logger.error(f"[{shadow_id}] Backend error: {error_msg}")
                    return f"[Error generating response: {error_msg}]"
                elif chunk_type_value == "done":
                    break

        except Exception as e:
            logger.error(f"[{shadow_id}] Error generating shadow response: {e}")
            return f"[Error: Failed to generate response - {str(e)}]"

        return accumulated_content.strip() or "[No response generated]"

    def _save_debug_context(
        self,
        shadow_id: str,
        parent_agent_id: str,
        broadcast_request: "BroadcastRequest",
        shadow_system_prompt: str,
        shadow_history: list,
        current_turn_context: str | None,
        parent_agent: "SingleAgent",
        log_session_dir: Path,
    ) -> Path | None:
        """Save shadow agent context to a debug file.

        Creates a JSON file with the full context sent to the shadow agent,
        useful for debugging and verifying the shadow agent behavior.

        Args:
            shadow_id: Unique ID for this shadow agent
            parent_agent_id: ID of the parent agent
            broadcast_request: The broadcast being responded to
            shadow_system_prompt: The simplified system prompt
            shadow_history: Full conversation history sent to the shadow
            current_turn_context: Formatted current turn context string
            parent_agent: The parent agent (for raw context data)
            log_session_dir: The current log session directory

        Returns:
            Path to the debug file, or None if saving failed
        """
        try:
            # Save to shadow_agents subdirectory within the current turn's log dir
            shadow_debug_dir = log_session_dir / "shadow_agents"
            shadow_debug_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{timestamp}_{shadow_id}.json"
            filepath = shadow_debug_dir / filename

            # Get raw current turn data for detailed debugging
            raw_content = getattr(parent_agent, "_current_turn_content", "")
            raw_tool_calls = getattr(parent_agent, "_current_turn_tool_calls", [])
            raw_reasoning = getattr(parent_agent, "_current_turn_reasoning", [])
            raw_mcp_calls = getattr(parent_agent, "_current_turn_mcp_calls", [])

            debug_data = {
                "shadow_id": shadow_id,
                "parent_agent_id": parent_agent_id,
                "timestamp": datetime.now().isoformat(),
                "broadcast": {
                    "sender_agent_id": broadcast_request.sender_agent_id,
                    "question": broadcast_request.question,
                    "request_id": broadcast_request.id,
                },
                "shadow_system_prompt": shadow_system_prompt,
                "current_turn_context": {
                    "formatted": current_turn_context,
                    "raw": {
                        "content": raw_content,
                        "content_length": len(raw_content),
                        "tool_calls": raw_tool_calls,
                        "tool_calls_count": len(raw_tool_calls),
                        "reasoning": raw_reasoning,
                        "reasoning_count": len(raw_reasoning),
                        "mcp_calls": raw_mcp_calls,
                        "mcp_calls_count": len(raw_mcp_calls),
                    },
                },
                "conversation_history": shadow_history,
                "conversation_history_length": len(shadow_history),
                "response": None,  # Will be appended later
            }

            with open(filepath, "w") as f:
                json.dump(debug_data, f, indent=2, default=str)

            logger.info(f"[{shadow_id}] Debug context saved to: {filepath}")
            return filepath

        except Exception as e:
            logger.warning(f"[{shadow_id}] Failed to save debug context: {e}")
            return None

    def _append_response_to_debug(self, filepath: Path, response: str) -> None:
        """Append the response to the debug file.

        Args:
            filepath: Path to the debug file
            response: The generated response
        """
        try:
            with open(filepath) as f:
                debug_data = json.load(f)

            debug_data["response"] = response
            debug_data["response_length"] = len(response)

            with open(filepath, "w") as f:
                json.dump(debug_data, f, indent=2, default=str)

            logger.info(f"[Shadow] Response appended to debug file: {filepath}")

        except Exception as e:
            logger.warning(f"[Shadow] Failed to append response to debug: {e}")


async def inject_informational_to_parent(
    parent_agent: "SingleAgent",
    broadcast_request: "BroadcastRequest",
    shadow_response: str,
) -> None:
    """
    Inject informational message into parent agent's history.

    This lets the parent know what 'it' said (via shadow) so it maintains
    awareness of interactions made on its behalf.

    Args:
        parent_agent: The original agent whose shadow responded
        broadcast_request: The broadcast that was answered
        shadow_response: The response the shadow agent gave
    """
    # Truncate long responses for the info message
    response_preview = shadow_response[:500]
    if len(shadow_response) > 500:
        response_preview += "..."

    info_message = {
        "role": "user",  # Inject as user message for visibility
        "content": (
            f"\n[INFO] While you were working, {broadcast_request.sender_agent_id} "
            f'asked: "{broadcast_request.question}"\n'
            f'Your shadow agent responded: "{response_preview}"\n'
            f"(This is just for your awareness - you may continue your work.)\n"
        ),
    }

    parent_agent.conversation_history.append(info_message)
    logger.info(
        f"[{parent_agent.agent_id}] Injected informational message about " f"shadow response to {broadcast_request.sender_agent_id}",
    )
