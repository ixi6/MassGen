"""
MassGen HTTP Server Engine

This module provides the engine that powers the OpenAI-compatible HTTP server.
It uses massgen.run() to ensure full feature parity with CLI, WebUI, and LiteLLM modes,
including proper logging, metrics, and session management.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from .openai.model_router import ResolvedModel
from .openai.schema import ChatCompletionRequest


class Engine(Protocol):
    """Protocol for MassGen server engines."""

    async def completion(
        self,
        req: ChatCompletionRequest,
        resolved: ResolvedModel,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        """Execute a chat completion request and return OpenAI-compatible response."""
        ...


class MassGenEngine:
    """
    Default engine that uses massgen.run() for full feature parity.

    This ensures the HTTP server has the same capabilities as CLI, WebUI, and LiteLLM:
    - Proper logging to .massgen/massgen_logs/
    - Metrics collection and saving
    - Session management
    - Full orchestrator features
    """

    def __init__(
        self,
        *,
        default_config: str | None = None,
    ):
        self._default_config = default_config

    def _extract_query(self, messages: list[dict[str, Any]]) -> str:
        """Extract query from messages list (last user message)."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # Handle both string and list content (multimodal)
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
                    return ""
                return content
        return ""

    def _extract_conversation_history(self, messages: list[dict[str, Any]]) -> list[dict[str, str]] | None:
        """Extract conversation history from messages (excluding last user message)."""
        if len(messages) <= 1:
            return None

        history = []
        for msg in messages[:-1]:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Handle multimodal content
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                content = " ".join(text_parts)

            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content})

        return history if history else None

    async def completion(
        self,
        req: ChatCompletionRequest,
        resolved: ResolvedModel,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        """
        Execute a chat completion using massgen.run().

        This provides full feature parity with CLI/WebUI/LiteLLM modes.
        """
        from massgen import run

        # Extract query and conversation history
        query = self._extract_query(req.messages)
        conversation_history = self._extract_conversation_history(req.messages)

        # Determine config path
        config_path = resolved.config_path or self._default_config
        if not config_path:
            raise ValueError(
                "No config provided. Set MASSGEN_SERVER_DEFAULT_CONFIG, " "use --config flag, or specify model='massgen/path:<path>'.",
            )

        # Build run kwargs
        run_kwargs = {
            "query": query,
            "config": config_path,
            "enable_logging": True,  # Always enable logging for server requests
            "verbose": False,  # Quiet mode for server
        }

        # Add conversation history for multi-turn
        if conversation_history:
            run_kwargs["conversation_history"] = conversation_history

        # Run MassGen
        result = await run(**run_kwargs)

        # Build OpenAI-compatible response
        return self._build_openai_response(
            result=result,
            model=req.model or "massgen",
            request_id=request_id,
        )

    def _build_openai_response(
        self,
        result: dict[str, Any],
        model: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible chat completion response."""
        response_id = f"chatcmpl-{request_id}"

        # Extract usage from result (populated by orchestrator)
        usage = result.get("usage") or {}

        return {
            "id": response_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result.get("final_answer", ""),
                    },
                    "finish_reason": "stop",
                },
            ],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            # MassGen-specific metadata (same structure as massgen.run() result)
            # Note: agent_mapping is inside vote_results (vote_results.agent_mapping)
            "massgen_metadata": {
                "session_id": result.get("session_id"),
                "config_used": result.get("config_used"),
                "log_directory": result.get("log_directory"),
                "final_answer_path": result.get("final_answer_path"),
                "selected_agent": result.get("selected_agent"),
                "vote_results": result.get("vote_results"),
                "answers": result.get("answers"),
            },
        }
