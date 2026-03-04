"""
Token and Cost Management Module
Provides unified token estimation and cost calculation for all backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logger_config import logger


@dataclass
class TokenUsage:
    """Token usage and cost tracking with full visibility.

    Tracks basic token counts plus detailed breakdown for:
    - Reasoning tokens (OpenAI o1/o3 models)
    - Cached tokens (Anthropic/OpenAI prompt caching)
    - Cache creation tokens (Anthropic cache writes)
    """

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0

    # Detailed token breakdown for visibility
    reasoning_tokens: int = 0  # OpenAI o1/o3 reasoning tokens
    cached_input_tokens: int = 0  # Prompt cache hits (Anthropic/OpenAI)
    cache_creation_tokens: int = 0  # Cache write tokens (Anthropic)

    def add(self, other: TokenUsage):
        """Add another TokenUsage to this one."""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.estimated_cost += other.estimated_cost
        self.reasoning_tokens += other.reasoning_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_creation_tokens += other.cache_creation_tokens

    def reset(self):
        """Reset all counters to zero."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.estimated_cost = 0.0
        self.reasoning_tokens = 0
        self.cached_input_tokens = 0
        self.cache_creation_tokens = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


@dataclass
class ToolExecutionMetric:
    """Metrics for a single tool execution.

    Tracks timing, success/failure, and character counts for token estimation.
    Uses character-based estimation (~4 chars per token) for low overhead.
    """

    tool_name: str
    tool_type: str  # "mcp", "custom", "provider"
    call_id: str
    agent_id: str
    round_number: int
    start_time: float
    end_time: float = 0.0
    success: bool = True
    error_message: str | None = None
    input_chars: int = 0  # Character count in arguments
    output_chars: int = 0  # Character count in result

    @property
    def execution_time_ms(self) -> float:
        """Execution time in milliseconds."""
        return (self.end_time - self.start_time) * 1000 if self.end_time else 0

    @property
    def input_tokens_est(self) -> int:
        """Estimated input tokens (~4 chars per token)."""
        return self.input_chars // 4

    @property
    def output_tokens_est(self) -> int:
        """Estimated output tokens (~4 chars per token)."""
        return self.output_chars // 4

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tool_name": self.tool_name,
            "tool_type": self.tool_type,
            "call_id": self.call_id,
            "agent_id": self.agent_id,
            "round_number": self.round_number,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "success": self.success,
            "error_message": self.error_message,
            "input_chars": self.input_chars,
            "output_chars": self.output_chars,
            "input_tokens_est": self.input_tokens_est,
            "output_tokens_est": self.output_tokens_est,
        }


@dataclass
class APICallMetric:
    """Metrics for a single LLM API call.

    Tracks timing for the actual API request/response cycle,
    separate from tool execution time.
    """

    agent_id: str
    round_number: int
    call_index: int  # Which API call in this round (0-indexed)
    backend_name: str  # "OpenAI", "Anthropic", "Google", etc.
    model: str
    start_time: float
    end_time: float = 0.0
    time_to_first_token_ms: float = 0.0  # TTFT for streaming
    success: bool = True
    error_message: str | None = None

    @property
    def duration_ms(self) -> float:
        """Total API call duration in milliseconds."""
        return (self.end_time - self.start_time) * 1000 if self.end_time else 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "round_number": self.round_number,
            "call_index": self.call_index,
            "backend_name": self.backend_name,
            "model": self.model,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "time_to_first_token_ms": round(self.time_to_first_token_ms, 2),
            "success": self.success,
            "error_message": self.error_message,
        }


@dataclass
class RoundTokenUsage:
    """Token usage for a single coordination round.

    Tracks token delta (consumption) within a round that ends with
    an answer, vote, restart, or timeout.
    """

    round_number: int
    agent_id: str
    round_type: str  # "initial_answer", "enforcement", "presentation"
    outcome: str = ""  # "answer", "vote", "restarted", "timeout", "error"

    # Token breakdown (delta from previous round)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost: float = 0.0

    # Context window usage
    context_window_size: int = 0  # Model's max context
    context_usage_pct: float = 0.0  # input_tokens / context_window_size * 100

    # Tool usage in this round
    tool_calls_count: int = 0

    # Token tracking source ("api" = from API response, "estimated" = fallback estimation)
    token_source: str = "api"

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0

    # API call timing (pure LLM time, excluding tool execution)
    api_calls_count: int = 0
    api_time_ms: float = 0.0
    avg_ttft_ms: float = 0.0  # Average time to first token

    @property
    def duration_ms(self) -> float:
        """Round duration in milliseconds."""
        return (self.end_time - self.start_time) * 1000 if self.end_time else 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "round_number": self.round_number,
            "agent_id": self.agent_id,
            "round_type": self.round_type,
            "outcome": self.outcome,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "estimated_cost": round(self.estimated_cost, 6),
            "context_window_size": self.context_window_size,
            "context_usage_pct": round(self.context_usage_pct, 2),
            "tool_calls_count": self.tool_calls_count,
            "token_source": self.token_source,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "api_calls_count": self.api_calls_count,
            "api_time_ms": round(self.api_time_ms, 2),
            "avg_ttft_ms": round(self.avg_ttft_ms, 2),
        }


@dataclass
class ModelPricing:
    """Pricing information for a model."""

    input_cost_per_1k: float  # Cost per 1000 input tokens
    output_cost_per_1k: float  # Cost per 1000 output tokens
    context_window: int | None = None
    max_output_tokens: int | None = None
    source: str = "unknown"  # Where pricing came from: "litellm", "hardcoded", "api"


class TokenCostCalculator:
    """Unified token estimation and cost calculation."""

    # Default pricing data for various providers and models
    PROVIDER_PRICING: dict[str, dict[str, ModelPricing]] = {
        "OpenAI": {
            # GPT-5 models (400K context window)
            "gpt-5.2": ModelPricing(0.00175, 0.014, 400000, 128000),
            "gpt-5": ModelPricing(0.00125, 0.01, 400000, 128000),
            "gpt-5-mini": ModelPricing(0.00025, 0.002, 400000, 128000),
            "gpt-5-nano": ModelPricing(0.00005, 0.0004, 400000, 128000),
            # GPT-4 series
            "gpt-4o": ModelPricing(0.0025, 0.01, 128000, 16384),
            "gpt-4o-mini": ModelPricing(0.00015, 0.0006, 128000, 16384),
            "gpt-4-turbo": ModelPricing(0.01, 0.03, 128000, 4096),
            "gpt-4": ModelPricing(0.03, 0.06, 8192, 8192),
            "gpt-3.5-turbo": ModelPricing(0.0005, 0.0015, 16385, 4096),
            # O-series models
            "o1-preview": ModelPricing(0.015, 0.06, 128000, 32768),
            "o1-mini": ModelPricing(0.003, 0.012, 128000, 65536),
            "o3-mini": ModelPricing(0.0011, 0.0044, 200000, 100000),
        },
        "Anthropic": {
            # Claude 4.5 models (October 2024+)
            "claude-haiku-4-5": ModelPricing(0.001, 0.005, 200000, 65536),  # $1/MTok input, $5/MTok output, 64K max output
            "claude-sonnet-4-5": ModelPricing(0.003, 0.015, 200000, 65536),  # $3/MTok input, $15/MTok output, 64K max output
            # Claude 4 models
            "claude-opus-4.1": ModelPricing(0.015, 0.075, 200000, 32768),  # $15/MTok input, $75/MTok output, 32K max output
            "claude-opus-4": ModelPricing(0.015, 0.075, 200000, 32768),  # $15/MTok input, $75/MTok output, 32K max output
            "claude-sonnet-4": ModelPricing(0.003, 0.015, 200000, 8192),  # $3/MTok input, $15/MTok output
            # Claude 3.5 models
            "claude-3-5-sonnet": ModelPricing(0.003, 0.015, 200000, 8192),  # $3/MTok input, $15/MTok output
            "claude-3-5-haiku": ModelPricing(0.0008, 0.004, 200000, 8192),  # $0.80/MTok input, $4/MTok output
            # Claude 3 models (deprecated)
            "claude-3-opus": ModelPricing(0.015, 0.075, 200000, 4096),  # Deprecated
            "claude-3-sonnet": ModelPricing(0.003, 0.015, 200000, 4096),  # Deprecated
            "claude-3-haiku": ModelPricing(0.00025, 0.00125, 200000, 4096),
        },
        "Google": {
            "gemini-3.1-pro-preview": ModelPricing(0.002, 0.012, 1048576, 65536),  # $2/MTok input, $12/MTok output, 1M context, 64K output
            "gemini-2.0-flash-exp": ModelPricing(0.0, 0.0, 1048576, 8192),  # Free during experimental
            "gemini-2.0-flash-thinking-exp": ModelPricing(0.0, 0.0, 32767, 8192),
            "gemini-1.5-pro": ModelPricing(0.00125, 0.005, 2097152, 8192),
            "gemini-1.5-flash": ModelPricing(0.000075, 0.0003, 1048576, 8192),
            "gemini-1.5-flash-8b": ModelPricing(0.0000375, 0.00015, 1048576, 8192),
            "gemini-1.0-pro": ModelPricing(0.00025, 0.00125, 32760, 8192),
        },
        "Cerebras": {
            "llama3.3-70b": ModelPricing(0.00035, 0.00035, 128000, 8192),
            "llama3.1-70b": ModelPricing(0.00035, 0.00035, 128000, 8192),
            "llama3.1-8b": ModelPricing(0.00001, 0.00001, 128000, 8192),
        },
        "Together": {
            "meta-llama/Llama-3.3-70B-Instruct-Turbo": ModelPricing(0.00059, 0.00079, 128000, 32768),
            "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo": ModelPricing(0.00059, 0.00079, 128000, 32768),
            "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": ModelPricing(0.00088, 0.00088, 130000, 4096),
            "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": ModelPricing(0.00018, 0.00018, 131072, 65536),
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": ModelPricing(0.00006, 0.00006, 131072, 16384),
            "Qwen/QwQ-32B-Preview": ModelPricing(0.00015, 0.00015, 32768, 32768),
            "Qwen/Qwen2.5-72B-Instruct-Turbo": ModelPricing(0.00012, 0.00012, 32768, 8192),
            "mistralai/Mixtral-8x22B-Instruct-v0.1": ModelPricing(0.0009, 0.0009, 65536, 65536),
            "deepseek-ai/deepseek-r1-distill-llama-70b": ModelPricing(0.00015, 0.00015, 65536, 8192),
        },
        "Fireworks": {
            "llama-3.3-70b": ModelPricing(0.0002, 0.0002, 128000, 16384),
            "llama-3.1-405b": ModelPricing(0.0009, 0.0009, 131072, 16384),
            "llama-3.1-70b": ModelPricing(0.0002, 0.0002, 131072, 16384),
            "llama-3.1-8b": ModelPricing(0.00002, 0.00002, 131072, 16384),
            "qwen2.5-72b": ModelPricing(0.0002, 0.0002, 32768, 16384),
        },
        "Groq": {
            "llama-3.3-70b-versatile": ModelPricing(0.00059, 0.00079, 128000, 32768),
            "llama-3.1-70b-versatile": ModelPricing(0.00059, 0.00079, 131072, 8000),
            "llama-3.1-8b-instant": ModelPricing(0.00005, 0.00008, 131072, 8000),
            "mixtral-8x7b-32768": ModelPricing(0.00024, 0.00024, 32768, 32768),
        },
        "xAI": {
            # Grok 4.1 family (Nov 2025)
            "grok-4-1-fast-reasoning": ModelPricing(0.0002, 0.0005, 2000000, 131072),  # 2M context, $0.20/M input (cached: $0.05/M)
            "grok-4-1-fast-non-reasoning": ModelPricing(0.0002, 0.0005, 2000000, 131072),  # 2M context
            # Grok 4 family (Jul-Sep 2025)
            "grok-code-fast-1": ModelPricing(0.0002, 0.0015, 256000, 131072),  # 256K context, $0.20/M input, $1.50/M output
            "grok-4": ModelPricing(0.003, 0.015, 131072, 131072),  # $3/M input, $15/M output
            "grok-4-fast": ModelPricing(0.003, 0.015, 131072, 131072),
            # Grok 3 family (Feb-May 2025)
            "grok-3": ModelPricing(0.003, 0.015, 131072, 131072),
            "grok-3-mini": ModelPricing(0.001, 0.003, 131072, 65536),
            # Grok 2 family (legacy)
            "grok-2-latest": ModelPricing(0.005, 0.015, 131072, 131072),
            "grok-2": ModelPricing(0.005, 0.015, 131072, 131072),
            "grok-2-mini": ModelPricing(0.001, 0.003, 131072, 65536),
        },
        "DeepSeek": {
            "deepseek-reasoner": ModelPricing(0.00014, 0.0028, 163840, 8192),
            "deepseek-chat": ModelPricing(0.00014, 0.00028, 64000, 8192),
        },
    }

    def __init__(self):
        """Initialize the calculator with optional tiktoken for accurate estimation."""
        self.tiktoken_encoder = None
        self._try_init_tiktoken()
        self._litellm_cache = None  # Cache for LiteLLM pricing database
        self._litellm_cache_time = None  # When cache was last refreshed

    def _try_init_tiktoken(self):
        """Try to initialize tiktoken encoder for more accurate token counting."""
        try:
            import tiktoken

            # Use cl100k_base encoder (GPT-4/GPT-3.5-turbo tokenizer)
            self.tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
            logger.debug("Tiktoken encoder initialized for accurate token counting")
        except ImportError:
            logger.debug("Tiktoken not available, using simple estimation")
        except Exception as e:
            logger.warning(f"Failed to initialize tiktoken: {e}")

    def _fetch_litellm_pricing(self) -> dict | None:
        """Fetch pricing database from LiteLLM (cached for 1 hour).

        Returns:
            Dictionary of model pricing data or None if fetch fails
        """
        import time

        # Check cache (1 hour expiry)
        if self._litellm_cache is not None and self._litellm_cache_time is not None:
            if time.time() - self._litellm_cache_time < 3600:
                return self._litellm_cache

        try:
            import requests

            url = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            self._litellm_cache = response.json()
            self._litellm_cache_time = time.time()
            logger.debug("Fetched LiteLLM pricing database (500+ models)")
            return self._litellm_cache

        except Exception as e:
            logger.debug(f"Failed to fetch LiteLLM pricing database: {e}")
            return None

    def estimate_tokens(self, text: str | list[dict[str, Any]], method: str = "auto") -> int:
        """
        Estimate token count for text or messages.

        Args:
            text: Text string or list of message dictionaries
            method: Estimation method ("tiktoken", "simple", "auto")

        Returns:
            Estimated token count
        """
        # Convert messages to text if needed
        if isinstance(text, list):
            text = self._messages_to_text(text)

        if method == "auto":
            # Use tiktoken if available, otherwise simple
            if self.tiktoken_encoder:
                return self.estimate_tokens_tiktoken(text)
            else:
                return self.estimate_tokens_simple(text)
        elif method == "tiktoken":
            return self.estimate_tokens_tiktoken(text)
        else:
            return self.estimate_tokens_simple(text)

    def estimate_tokens_tiktoken(self, text: str) -> int:
        """
        Estimate tokens using tiktoken (OpenAI's tokenizer).
        Most accurate for OpenAI models.

        Args:
            text: Text to estimate

        Returns:
            Token count
        """
        if not self.tiktoken_encoder:
            logger.warning("Tiktoken not available, falling back to simple estimation")
            return self.estimate_tokens_simple(text)

        try:
            tokens = self.tiktoken_encoder.encode(text)
            return len(tokens)
        except Exception as e:
            logger.warning(f"Tiktoken encoding failed: {e}, using simple estimation")
            return self.estimate_tokens_simple(text)

    def estimate_tokens_simple(self, text: str) -> int:
        """
        Simple token estimation based on character/word count.
        Roughly 1 token ≈ 4 characters or 0.75 words.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        # Method 1: Character-based (1 token ≈ 4 characters)
        char_estimate = len(text) / 4

        # Method 2: Word-based (1 token ≈ 0.75 words)
        words = text.split()
        word_estimate = len(words) / 0.75

        # Take average of both methods for better accuracy
        estimate = (char_estimate + word_estimate) / 2

        return int(estimate)

    def _messages_to_text(self, messages: list[dict[str, Any]]) -> str:
        """Convert message list to text for token estimation."""
        text_parts = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Handle different content types
            if isinstance(content, str):
                text_parts.append(f"{role}: {content}")
            elif isinstance(content, list):
                # Handle structured content (like Claude's format)
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(f"{role}: {item.get('text', '')}")
                        elif item.get("type") == "tool_result":
                            text_parts.append(f"tool_result: {item.get('content', '')}")
                    else:
                        text_parts.append(f"{role}: {str(item)}")
            else:
                text_parts.append(f"{role}: {str(content)}")

            # Add tool calls if present
            if "tool_calls" in msg:
                tool_calls = msg["tool_calls"]
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        text_parts.append(f"tool_call: {str(call)}")

        return "\n".join(text_parts)

    def _dict_to_namespace(self, d: Any) -> Any:
        """Recursively convert dict to SimpleNamespace for litellm compatibility."""
        from types import SimpleNamespace

        if not isinstance(d, dict):
            return d
        result = {}
        for k, v in d.items():
            result[k] = self._dict_to_namespace(v) if isinstance(v, dict) else v
        return SimpleNamespace(**result)

    def _map_provider_to_litellm(self, provider: str | None) -> str | None:
        """Map MassGen provider names to litellm provider identifiers."""
        if not provider:
            return None
        mapping = {
            "openai": "openai",
            "anthropic": "anthropic",
            "claude": "anthropic",
            "claude_code": "anthropic",
            "google": "vertex_ai",
            "gemini": "gemini",
            "xai": "xai",
            "grok": "xai",
            "groq": "groq",
            "together": "together_ai",
            "fireworks": "fireworks_ai",
            "deepseek": "deepseek",
            "cerebras": "cerebras",
            "azure": "azure",
            "azure openai": "azure",
        }
        return mapping.get(provider.lower())

    def extract_token_breakdown(self, usage: dict[str, Any] | Any) -> dict[str, int]:
        """Extract detailed token counts from usage object.

        Handles provider-specific formats:
        - OpenAI: prompt_tokens, completion_tokens, completion_tokens_details.reasoning_tokens
        - Anthropic: input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens
        - SGLang: reasoning_tokens at top level
        - Gemini: prompt_token_count, candidates_token_count, thoughts_token_count, cached_content_token_count

        Args:
            usage: Usage object or dict from API response

        Returns:
            Dictionary with token counts for visibility tracking
        """
        if not usage:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cached_input_tokens": 0,
                "cache_creation_tokens": 0,
            }

        # Normalize to dict
        if isinstance(usage, dict):
            u = usage
        elif hasattr(usage, "__dict__"):
            u = vars(usage)
        else:
            # Try to access as object attributes
            u = {}
            for attr in [
                "prompt_tokens",
                "input_tokens",
                "completion_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cached_input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "prompt_token_count",
                "candidates_token_count",
                "thoughts_token_count",
                "cached_content_token_count",
            ]:
                if hasattr(usage, attr):
                    u[attr] = getattr(usage, attr, 0)

        breakdown = {
            "input_tokens": u.get("prompt_tokens") or u.get("input_tokens") or u.get("prompt_token_count") or 0,
            "output_tokens": u.get("completion_tokens") or u.get("output_tokens") or u.get("candidates_token_count") or 0,
            "reasoning_tokens": 0,
            "cached_input_tokens": 0,
            "cache_creation_tokens": 0,
        }

        # Extract reasoning tokens (OpenAI o1/o3, SGLang, Gemini 2.5 thinking)
        if u.get("reasoning_tokens"):
            breakdown["reasoning_tokens"] = u["reasoning_tokens"]
        elif u.get("thoughts_token_count"):
            # Gemini 2.5 thinking models use thoughts_token_count
            breakdown["reasoning_tokens"] = u["thoughts_token_count"]
        else:
            # Check nested details (OpenAI/Grok format)
            completion_details = u.get("completion_tokens_details") or u.get("output_tokens_details")
            if completion_details:
                if isinstance(completion_details, dict):
                    breakdown["reasoning_tokens"] = completion_details.get("reasoning_tokens", 0) or 0
                elif hasattr(completion_details, "reasoning_tokens"):
                    breakdown["reasoning_tokens"] = getattr(completion_details, "reasoning_tokens", 0) or 0

        # Extract cached tokens (Anthropic format - separate from input_tokens)
        breakdown["cached_input_tokens"] = u.get("cache_read_input_tokens", 0) or 0
        breakdown["cache_creation_tokens"] = u.get("cache_creation_input_tokens", 0) or 0

        # Extract cached tokens (Codex/OpenAI top-level field)
        if not breakdown["cached_input_tokens"]:
            breakdown["cached_input_tokens"] = u.get("cached_input_tokens", 0) or 0

        # Extract cached tokens (OpenAI format - nested in prompt_tokens_details)
        if not breakdown["cached_input_tokens"]:
            prompt_details = u.get("prompt_tokens_details") or u.get("input_tokens_details")
            if prompt_details:
                if isinstance(prompt_details, dict):
                    breakdown["cached_input_tokens"] = prompt_details.get("cached_tokens", 0) or 0
                elif hasattr(prompt_details, "cached_tokens"):
                    breakdown["cached_input_tokens"] = getattr(prompt_details, "cached_tokens", 0) or 0

        # Extract cached tokens (Gemini format - cached_content_token_count)
        if not breakdown["cached_input_tokens"]:
            breakdown["cached_input_tokens"] = u.get("cached_content_token_count", 0) or 0

        return breakdown

    def calculate_cost_with_usage_object(
        self,
        model: str,
        usage: dict[str, Any] | Any,
        provider: str | None = None,
    ) -> float:
        """
        Calculate cost from API usage object using litellm.completion_cost() directly.

        Automatically handles:
        - Reasoning tokens (o1/o3 models)
        - Cached tokens (prompt caching)
        - Cache creation vs cache read pricing
        - Provider-specific token structures

        Args:
            model: Model identifier (e.g., "gpt-4o", "claude-sonnet-4-5-20250929")
            usage: Usage object/dict from API response
            provider: Optional provider name for model lookup

        Returns:
            Cost in USD
        """
        if not usage:
            return 0.0

        # Try litellm.completion_cost() first (most accurate, auto-updated)
        try:
            from litellm import completion_cost

            # Convert usage to dict if needed (litellm prefers dict format)
            if isinstance(usage, dict):
                usage_dict = usage.copy()
            elif hasattr(usage, "__dict__"):
                usage_dict = self._namespace_to_dict(usage)
            else:
                # Try to build dict from known attributes
                usage_dict = {}
                for attr in [
                    "prompt_tokens",
                    "completion_tokens",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cached_input_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                    "completion_tokens_details",
                    "prompt_tokens_details",
                    "prompt_token_count",
                    "candidates_token_count",
                    "thoughts_token_count",
                    "cached_content_token_count",
                ]:
                    if hasattr(usage, attr):
                        val = getattr(usage, attr, None)
                        if val is not None:
                            usage_dict[attr] = val

            # Normalize Gemini field names to litellm format
            # Gemini uses: prompt_token_count, candidates_token_count, thoughts_token_count
            # Litellm expects: prompt_tokens, completion_tokens
            if "prompt_token_count" in usage_dict and "prompt_tokens" not in usage_dict:
                usage_dict["prompt_tokens"] = usage_dict["prompt_token_count"]
            if "candidates_token_count" in usage_dict and "completion_tokens" not in usage_dict:
                usage_dict["completion_tokens"] = usage_dict["candidates_token_count"]

            # Normalize Codex/OpenAI top-level cached_input_tokens to prompt_tokens_details.
            # This matches the canonical OpenAI usage shape litellm expects for cache discounts.
            if usage_dict.get("cached_input_tokens", 0) and "prompt_tokens_details" not in usage_dict:
                usage_dict["prompt_tokens_details"] = {
                    "cached_tokens": usage_dict["cached_input_tokens"],
                }

            # Create mock response as dict (litellm prefers this format)
            mock_response = {
                "model": model,
                "usage": usage_dict,
                "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            }

            # Map provider to litellm format
            custom_provider = self._map_provider_to_litellm(provider)

            # Calculate cost using litellm directly
            cost = completion_cost(
                completion_response=mock_response,
                model=model,
                custom_llm_provider=custom_provider,
            )

            logger.debug(f"litellm.completion_cost: {model} = ${cost:.6f}")
            return float(cost)

        except ImportError:
            logger.debug("litellm not available, using fallback pricing database")
        except Exception as e:
            logger.debug(f"litellm.completion_cost failed ({type(e).__name__}: {e}), using fallback")

        # Fallback: Use litellm pricing database with manual calculation
        return self._calculate_cost_from_pricing_db(model, usage, provider)

    def _namespace_to_dict(self, obj: Any) -> dict[str, Any]:
        """Recursively convert object with __dict__ to dict for litellm."""
        if not hasattr(obj, "__dict__"):
            return obj

        result = {}
        for k, v in vars(obj).items():
            if hasattr(v, "__dict__"):
                result[k] = self._namespace_to_dict(v)
            else:
                result[k] = v
        return result

    def _calculate_cost_from_pricing_db(
        self,
        model: str,
        usage: dict[str, Any] | Any,
        provider: str | None = None,
    ) -> float:
        """Fallback cost calculation using litellm pricing database.

        Used when litellm.completion_cost() is not available or fails.
        """
        # Extract token breakdown
        breakdown = self.extract_token_breakdown(usage)
        input_tokens = breakdown["input_tokens"]
        output_tokens = breakdown["output_tokens"]
        reasoning_tokens = breakdown["reasoning_tokens"]
        cached_read_tokens = breakdown["cached_input_tokens"]
        cached_write_tokens = breakdown["cache_creation_tokens"]

        # Normalize usage to dict for checking format
        usage_dict = usage if isinstance(usage, dict) else vars(usage) if hasattr(usage, "__dict__") else {}

        # Try to get pricing from litellm database
        litellm_db = self._fetch_litellm_pricing()
        if litellm_db and model in litellm_db:
            model_pricing = litellm_db[model]

            # For Anthropic: cache_read_input_tokens and cache_creation_input_tokens are SEPARATE from input_tokens
            # For OpenAI: cached_tokens in prompt_tokens_details are PART OF prompt_tokens (subtract them)
            non_cached_input = input_tokens
            if cached_read_tokens > 0 and "cache_read_input_tokens" not in usage_dict:
                # OpenAI format: cached tokens are included in prompt_tokens
                non_cached_input = max(0, input_tokens - cached_read_tokens)

            # Calculate costs using litellm pricing
            input_cost = (non_cached_input / 1_000_000) * model_pricing.get("input_cost_per_token", 0) * 1_000_000
            output_cost = (output_tokens / 1_000_000) * model_pricing.get("output_cost_per_token", 0) * 1_000_000
            reasoning_cost = (reasoning_tokens / 1_000_000) * model_pricing.get("output_cost_per_token", 0) * 1_000_000

            # Cached token costs
            cache_read_cost = (
                (cached_read_tokens / 1_000_000)
                * model_pricing.get(
                    "cache_read_input_token_cost",
                    model_pricing.get("input_cost_per_token", 0) * 0.1,
                )
                * 1_000_000
            )
            cache_write_cost = (
                (cached_write_tokens / 1_000_000)
                * model_pricing.get(
                    "cache_creation_input_token_cost",
                    model_pricing.get("input_cost_per_token", 0) * 1.25,
                )
                * 1_000_000
            )

            total_cost = input_cost + output_cost + reasoning_cost + cache_read_cost + cache_write_cost

            logger.debug(
                f"litellm pricing db: {model} = ${total_cost:.6f} " f"(input=${input_cost:.6f}, output=${output_cost:.6f}, " f"reasoning=${reasoning_cost:.6f}, cache_read=${cache_read_cost:.6f})",
            )
            return total_cost

        # Final fallback to basic calculation
        logger.debug(f"Model {model} not in litellm database, using basic fallback")
        return self._extract_and_calculate_basic_cost(usage, provider, model)

    def _extract_and_calculate_basic_cost(
        self,
        usage: dict | Any,
        provider: str,
        model: str,
    ) -> float:
        """Extract basic token counts and calculate cost (fallback)."""
        # Extract basic token counts (provider-agnostic)
        # OpenAI format: prompt_tokens, completion_tokens
        # Anthropic format: input_tokens, output_tokens

        if isinstance(usage, dict):
            input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens", 0)
            output_tokens = usage.get("completion_tokens") or usage.get("output_tokens", 0)
        elif hasattr(usage, "prompt_tokens") or hasattr(usage, "input_tokens"):
            input_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0)
        else:
            logger.warning(f"Could not extract token counts from usage object: {usage}")
            return 0.0

        return self.calculate_cost(input_tokens, output_tokens, provider, model)

    def get_model_pricing(self, provider: str, model: str) -> ModelPricing | None:
        """
        Get pricing information for a specific model.

        Tries in order:
        1. LiteLLM pricing database (500+ models, auto-updated)
        2. Hardcoded PROVIDER_PRICING (fallback)
        3. Pattern matching heuristics

        Args:
            provider: Provider name (e.g., "OpenAI", "Anthropic")
            model: Model name or identifier

        Returns:
            ModelPricing object or None if not found
        """
        # Normalize provider name
        provider = self._normalize_provider(provider)

        # Build list of model name variations to try in LiteLLM
        # OpenRouter models come as "x-ai/grok-4.1-fast" but LiteLLM uses "openrouter/x-ai/grok-4.1-fast"
        model_variations = [model]  # Original first

        # If model has provider prefix (e.g., "x-ai/grok-4.1-fast"), try with openrouter/ prefix
        if "/" in model:
            model_variations.append(f"openrouter/{model}")
            # Also try just the model name without prefix
            _, model_name_only = model.split("/", 1)
            model_variations.append(model_name_only)
            # Try with dots converted to dashes (e.g., "grok-4.1-fast" -> "grok-4-1-fast")
            model_variations.append(model_name_only.replace(".", "-"))

        # Also try converting version dashes to dots (e.g., "claude-3-5-sonnet" -> "claude-3.5-sonnet")
        # LiteLLM uses dots for version numbers: "openrouter/anthropic/claude-3.5-sonnet"
        import re

        model_with_dots = re.sub(r"-(\d+)-(\d+)-", r"-\1.\2-", model)  # "3-5" -> "3.5"
        if model_with_dots != model:
            model_variations.append(model_with_dots)
            model_variations.append(f"openrouter/{model_with_dots}")

        # Try LiteLLM database with all variations
        litellm_db = self._fetch_litellm_pricing()
        if litellm_db:
            for model_variant in model_variations:
                if model_variant in litellm_db:
                    model_data = litellm_db[model_variant]
                    try:
                        # Convert LiteLLM format to ModelPricing
                        # LiteLLM uses per-token, we use per-1K
                        input_per_1k = model_data.get("input_cost_per_token", 0) * 1000
                        output_per_1k = model_data.get("output_cost_per_token", 0) * 1000
                        context = model_data.get("max_input_tokens")
                        max_output = model_data.get("max_output_tokens")

                        logger.info(f"[TokenCostCalculator] Pricing for '{model}' from LiteLLM (variant: {model_variant})")
                        return ModelPricing(
                            input_cost_per_1k=input_per_1k,
                            output_cost_per_1k=output_per_1k,
                            context_window=context,
                            max_output_tokens=max_output,
                            source="litellm",
                        )
                    except Exception as e:
                        logger.debug(f"Error parsing LiteLLM data for {model_variant}: {e}")

        # Fallback to hardcoded PROVIDER_PRICING
        # For OpenRouter models, extract actual provider from prefix (e.g., "x-ai/grok-4.1-fast")
        actual_provider = provider
        actual_model = model
        if "/" in model:
            prefix, model_name = model.split("/", 1)
            prefix_to_provider = {
                "x-ai": "xAI",
                "openai": "OpenAI",
                "anthropic": "Anthropic",
                "google": "Google",
                "meta-llama": "Meta",
                "mistralai": "Mistral",
                "deepseek": "DeepSeek",
                "qwen": "Qwen",
            }
            if prefix.lower() in prefix_to_provider:
                actual_provider = prefix_to_provider[prefix.lower()]
                actual_model = model_name
                logger.debug(f"Extracted provider={actual_provider}, model={actual_model} from OpenRouter format")

        # Normalize model name: convert dots to dashes (e.g., "grok-4.1-fast" -> "grok-4-1-fast")
        model_normalized = actual_model.replace(".", "-")

        provider_models = self.PROVIDER_PRICING.get(actual_provider, {})

        # Try exact match first (with original model name)
        if actual_model in provider_models:
            pricing = provider_models[actual_model]
            logger.info(f"[TokenCostCalculator] Pricing for '{model}' from hardcoded (exact: {actual_model})")
            return ModelPricing(
                pricing.input_cost_per_1k,
                pricing.output_cost_per_1k,
                pricing.context_window,
                pricing.max_output_tokens,
                source="hardcoded",
            )

        # Try with normalized model name (dots to dashes)
        if model_normalized in provider_models:
            pricing = provider_models[model_normalized]
            logger.info(f"[TokenCostCalculator] Pricing for '{model}' from hardcoded (normalized: {model_normalized})")
            return ModelPricing(
                pricing.input_cost_per_1k,
                pricing.output_cost_per_1k,
                pricing.context_window,
                pricing.max_output_tokens,
                source="hardcoded",
            )

        # Try to find by partial match
        for model_key, pricing in provider_models.items():
            if model_key.lower() in model_normalized.lower() or model_normalized.lower() in model_key.lower():
                logger.info(f"[TokenCostCalculator] Pricing for '{model}' from hardcoded (partial: {model_key})")
                return ModelPricing(
                    pricing.input_cost_per_1k,
                    pricing.output_cost_per_1k,
                    pricing.context_window,
                    pricing.max_output_tokens,
                    source="hardcoded",
                )

        # Try to infer from model name patterns
        model_lower = model_normalized.lower()

        def _with_source(pricing: ModelPricing | None, matched_key: str) -> ModelPricing | None:
            """Helper to add source and logging to pattern-matched pricing."""
            if pricing:
                logger.info(f"[TokenCostCalculator] Pricing for '{model}' from hardcoded (pattern: {matched_key})")
                return ModelPricing(
                    pricing.input_cost_per_1k,
                    pricing.output_cost_per_1k,
                    pricing.context_window,
                    pricing.max_output_tokens,
                    source="hardcoded",
                )
            return None

        # Grok variants (xAI)
        if "grok" in model_lower:
            xai_models = self.PROVIDER_PRICING.get("xAI", {})
            if "grok-4-1-fast" in model_lower or "grok-4.1-fast" in model_lower:
                return _with_source(xai_models.get("grok-4-1-fast-reasoning"), "grok-4-1-fast-reasoning")
            elif "grok-4-fast" in model_lower:
                return _with_source(xai_models.get("grok-4-fast"), "grok-4-fast")
            elif "grok-4" in model_lower:
                return _with_source(xai_models.get("grok-4"), "grok-4")
            elif "grok-3-mini" in model_lower:
                return _with_source(xai_models.get("grok-3-mini"), "grok-3-mini")
            elif "grok-3" in model_lower:
                return _with_source(xai_models.get("grok-3"), "grok-3")
            elif "grok-2-mini" in model_lower:
                return _with_source(xai_models.get("grok-2-mini"), "grok-2-mini")
            elif "grok-2" in model_lower:
                return _with_source(xai_models.get("grok-2"), "grok-2")

        # GPT-4 variants
        elif "gpt-4o" in model_lower and "mini" in model_lower:
            return _with_source(provider_models.get("gpt-4o-mini"), "gpt-4o-mini")
        elif "gpt-4o" in model_lower:
            return _with_source(provider_models.get("gpt-4o"), "gpt-4o")
        elif "gpt-4" in model_lower and "turbo" in model_lower:
            return _with_source(provider_models.get("gpt-4-turbo"), "gpt-4-turbo")
        elif "gpt-4" in model_lower:
            return _with_source(provider_models.get("gpt-4"), "gpt-4")
        elif "gpt-3.5" in model_lower:
            return _with_source(provider_models.get("gpt-3.5-turbo"), "gpt-3.5-turbo")

        # Claude variants
        elif "claude-3-5-sonnet" in model_lower or "claude-3.5-sonnet" in model_lower:
            return _with_source(provider_models.get("claude-3-5-sonnet"), "claude-3-5-sonnet")
        elif "claude-3-5-haiku" in model_lower or "claude-3.5-haiku" in model_lower:
            return _with_source(provider_models.get("claude-3-5-haiku"), "claude-3-5-haiku")
        elif "claude-3-opus" in model_lower:
            return _with_source(provider_models.get("claude-3-opus"), "claude-3-opus")
        elif "claude-3-sonnet" in model_lower:
            return _with_source(provider_models.get("claude-3-sonnet"), "claude-3-sonnet")
        elif "claude-3-haiku" in model_lower:
            return _with_source(provider_models.get("claude-3-haiku"), "claude-3-haiku")

        # Gemini variants
        elif "gemini-3.1-pro" in model_lower:
            return _with_source(provider_models.get("gemini-3.1-pro-preview"), "gemini-3.1-pro-preview")
        elif "gemini-2" in model_lower and "flash" in model_lower:
            return _with_source(provider_models.get("gemini-2.0-flash-exp"), "gemini-2.0-flash-exp")
        elif "gemini-1.5-pro" in model_lower:
            return _with_source(provider_models.get("gemini-1.5-pro"), "gemini-1.5-pro")
        elif "gemini-1.5-flash" in model_lower:
            return _with_source(provider_models.get("gemini-1.5-flash"), "gemini-1.5-flash")

        logger.info(f"[TokenCostCalculator] No pricing found for {provider}/{model}")
        return None

    def _normalize_provider(self, provider: str) -> str:
        """Normalize provider name for lookup."""
        provider_map = {
            "openai": "OpenAI",
            "azure": "OpenAI",
            "azure openai": "OpenAI",
            "anthropic": "Anthropic",
            "claude": "Anthropic",
            "google": "Google",
            "gemini": "Google",
            "vertex": "Google",
            "cerebras": "Cerebras",
            "cerebras ai": "Cerebras",
            "together": "Together",
            "together ai": "Together",
            "fireworks": "Fireworks",
            "fireworks ai": "Fireworks",
            "groq": "Groq",
            "xai": "xAI",
            "x.ai": "xAI",
            "grok": "xAI",
            "deepseek": "DeepSeek",
        }

        provider_lower = provider.lower()
        return provider_map.get(provider_lower, provider)

    def calculate_cost(self, input_tokens: int, output_tokens: int, provider: str, model: str) -> float:
        """
        Calculate cost for token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            provider: Provider name
            model: Model name

        Returns:
            Estimated cost in USD
        """
        pricing = self.get_model_pricing(provider, model)

        if not pricing:
            logger.debug(f"No pricing for {provider}/{model}, returning 0")
            return 0.0

        # Calculate costs (prices are per 1000 tokens)
        input_cost = (input_tokens / 1000) * pricing.input_cost_per_1k
        output_cost = (output_tokens / 1000) * pricing.output_cost_per_1k

        total_cost = input_cost + output_cost

        logger.debug(
            f"Cost calculation for {provider}/{model}: "
            f"{input_tokens} input @ ${pricing.input_cost_per_1k}/1k = ${input_cost:.4f}, "
            f"{output_tokens} output @ ${pricing.output_cost_per_1k}/1k = ${output_cost:.4f}, "
            f"total = ${total_cost:.4f}",
        )

        return total_cost

    def update_token_usage(self, usage: TokenUsage, messages: list[dict[str, Any]], response_content: str, provider: str, model: str) -> TokenUsage:
        """
        Update token usage with new conversation turn.

        Args:
            usage: Existing TokenUsage to update
            messages: Input messages
            response_content: Response content
            provider: Provider name
            model: Model name

        Returns:
            Updated TokenUsage object
        """
        # Estimate tokens
        input_tokens = self.estimate_tokens(messages)
        output_tokens = self.estimate_tokens(response_content)

        # Calculate cost
        cost = self.calculate_cost(input_tokens, output_tokens, provider, model)

        # Update usage
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.estimated_cost += cost

        return usage

    def format_cost(self, cost: float) -> str:
        """Format cost for display."""
        if cost < 0.01:
            return f"${cost:.4f}"
        elif cost < 1.0:
            return f"${cost:.3f}"
        else:
            return f"${cost:.2f}"

    def format_usage_summary(self, usage: TokenUsage) -> str:
        """Format token usage summary for display."""
        return f"Tokens: {usage.input_tokens:,} input, " f"{usage.output_tokens:,} output, " f"Cost: {self.format_cost(usage.estimated_cost)}"
