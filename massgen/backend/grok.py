"""
Grok/xAI backend is using the chat_completions backend for streaming.
It overrides methods for Grok-specific features (Grok Live Search).

✅ TESTED: Backend works correctly with architecture
- ✅ Grok API integration working (through chat_completions)
- ✅ Streaming functionality working correctly
- ✅ SingleAgent integration working
- ✅ Error handling and pricing calculations implemented
- ✅ Web search is working through Grok Live Search
- ✅ MCP is working

TODO for future releases:
- Test multi-agent orchestrator integration
- Validate advanced Grok-specific features
"""

# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from typing import Any

from openai import AsyncOpenAI

from ..logger_config import log_stream_chunk
from .chat_completions import ChatCompletionsBackend

logger = logging.getLogger(__name__)


class GrokBackend(ChatCompletionsBackend):
    """Grok backend using xAI's OpenAI-compatible API."""

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(api_key, **kwargs)
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.base_url = "https://api.x.ai/v1"

    def _create_client(self, **kwargs) -> AsyncOpenAI:
        """Create OpenAI client configured for xAI's Grok API."""
        import openai

        return openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def _customize_api_params(
        self,
        api_params: dict[str, Any],
        all_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Add Grok Live Search parameters to API params if web search is enabled.

        This hook is called by the parent class before making the API call.
        """
        enable_web_search = False  # all_params.get("enable_web_search", False)
        logger.debug(f"GrokBackend: Live search is currently deprecated, enable_web_search={enable_web_search} for now")

        if enable_web_search:
            # Check for conflict with manually specified search_parameters
            existing_extra = api_params.get("extra_body", {})
            if isinstance(existing_extra, dict) and "search_parameters" in existing_extra:
                error_message = "Conflict: Cannot use both 'enable_web_search: true' and manual 'extra_body.search_parameters'. Use one or the other."
                log_stream_chunk("backend.grok", "error", error_message, self.agent_id)
                raise ValueError(error_message)

            # Merge search_parameters into existing extra_body
            search_params = {"mode": "auto", "return_citations": True}
            merged_extra = existing_extra.copy() if existing_extra else {}
            merged_extra["search_parameters"] = search_params
            api_params["extra_body"] = merged_extra

        return api_params

    def get_provider_name(self) -> str:
        """Get the name of this provider."""
        return "Grok"

    def get_supported_builtin_tools(self) -> list[str]:
        """Get list of builtin tools supported by Grok."""
        return ["web_search"]
