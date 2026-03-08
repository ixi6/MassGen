"""Provider-specific context length error detection.

This module provides utilities to detect when an LLM API returns a context
length exceeded error. Different providers return these errors in different
formats, so we need provider-specific detection logic.

Note: This is part of MassGen's reactive compression system. Since most LLM
providers only report token usage AFTER a request completes, we cannot
proactively prevent context overflow. Instead, we catch errors and compress.

Verified error patterns from official documentation (2024-2025):
- OpenAI: 400 BadRequestError, code="context_length_exceeded"
- Anthropic: 400 invalid_request_error or 413 request_too_large
- Gemini: 500 INTERNAL ("context is too long") or 504 DEADLINE_EXCEEDED
- LiteLLM: ContextWindowExceededError (subclass of BadRequestError)
- Groq: 400 BadRequestError, code="context_length_exceeded" or 413
- Mistral: 400 with "exceeds the model's maximum context length"
- OpenRouter: "endpoint's maximum context length" message
- Cohere: 400 "Too many tokens" message
"""

import re
from dataclasses import dataclass


@dataclass
class ContextErrorInfo:
    """Detailed information extracted from a context length error."""

    provider: str
    input_tokens: int | None = None
    max_tokens: int | None = None
    context_limit: int | None = None
    http_status: int | None = None
    error_code: str | None = None
    raw_message: str | None = None


class ContextLengthExceededError(Exception):
    """Unified context length exceeded error.

    Wraps provider-specific errors into a single type for easier handling.
    """

    def __init__(
        self,
        original_error: Exception,
        provider: str = "unknown",
        info: ContextErrorInfo | None = None,
    ):
        self.original_error = original_error
        self.provider = provider
        self.info = info or ContextErrorInfo(provider=provider)
        super().__init__(f"Context length exceeded ({provider}): {original_error}")


def _get_http_status(error: Exception) -> int | None:
    """Extract HTTP status code from an exception if available."""
    # Check common attribute names for status code
    for attr in ("status_code", "status", "code"):
        if hasattr(error, attr):
            val = getattr(error, attr)
            # Some SDKs use callable .code() method (e.g., gRPC)
            if callable(val):
                val = val()
            if isinstance(val, int):
                return val
    # Check nested response object
    if hasattr(error, "response"):
        resp = error.response
        if hasattr(resp, "status_code"):
            return resp.status_code
        if hasattr(resp, "status"):
            return resp.status
    return None


def _check_exception_type(error: Exception) -> str | None:
    """Check if error is a known context length exception type.

    Returns the provider name if matched, None otherwise.
    """
    error_type = type(error).__name__
    error_module = str(getattr(type(error), "__module__", "")).lower()

    # LiteLLM has a specific exception class for context window errors
    if error_type == "ContextWindowExceededError":
        return "litellm"

    # Check for provider-specific BadRequestError types
    if error_type == "BadRequestError":
        if "openai" in error_module:
            return "openai"
        if "anthropic" in error_module:
            return "anthropic"
        if "groq" in error_module:
            return "groq"

    # Google/Gemini gRPC exceptions
    # Note: We only check DeadlineExceeded here. ResourceExhausted (code 8) is
    # ambiguous - it can mean rate/quota limits OR context length. We rely on
    # message pattern matching in is_context_length_error() for context errors.
    if error_type == "DeadlineExceeded":
        return "google"

    return None


def is_context_length_error(error: Exception) -> bool:
    """Check if an exception is a context length exceeded error.

    This function checks for provider-specific error patterns that indicate
    the request failed because the context (input tokens) was too long.

    Detection methods (in order):
    1. Exception type checking (ContextWindowExceededError, BadRequestError, etc.)
    2. HTTP status code checking (400, 413, 500, 504)
    3. Error message pattern matching

    Args:
        error: The exception to check.

    Returns:
        True if this is a context length error, False otherwise.

    Examples:
        >>> # OpenAI context length error
        >>> is_context_length_error(Exception("context_length_exceeded"))
        True

        >>> # Regular error
        >>> is_context_length_error(ValueError("something else"))
        False
    """
    error_str = str(error).lower()

    # 1. Check for known exception types first (most reliable)
    provider = _check_exception_type(error)
    if provider == "litellm":
        # LiteLLM's ContextWindowExceededError is always a context error
        return True

    # Note: We intentionally do NOT check gRPC code 8 (RESOURCE_EXHAUSTED) here.
    # Code 8 is ambiguous - it can indicate rate/quota limits (not context errors).
    # Instead, we rely on message pattern matching below for Gemini context errors.

    # 2. Check HTTP status + message combination for reliability
    status = _get_http_status(error)

    # Gemini returns 500 INTERNAL for "context is too long" (not 400!)
    if status == 500 and any(p in error_str for p in ["context is too long", "input context is too long", "internal"]):
        # Only match if it looks like a context error, not other 500s
        if "context" in error_str or "token" in error_str:
            return True

    # Gemini returns 504 for "prompt too large to process in time"
    if status == 504 and any(p in error_str for p in ["too large", "deadline", "context", "prompt"]):
        return True

    # 413 Request Entity Too Large - Anthropic, Groq
    if status == 413:
        return True

    # 3. Pattern matching on error message (comprehensive list)
    context_error_patterns = [
        # === OpenAI / Azure OpenAI ===
        # Error code in response: "code": "context_length_exceeded"
        "context_length_exceeded",
        # Message: "This model's maximum context length is X tokens"
        "maximum context length",
        "context length exceeded",
        # OpenAI Responses API: "Your input exceeds the context window of this model"
        "exceeds the context window",
        "input exceeds the context",
        # === Anthropic ===
        # Message: "input length and max_tokens exceed context limit: X + Y > Z"
        "exceed context limit",
        "exceeds context limit",
        "input length and max_tokens",
        # Message: "prompt is too long"
        "prompt is too long",
        # 413 error type
        "request_too_large",
        "request too large",
        # === Google Gemini ===
        # gRPC status: RESOURCE_EXHAUSTED (but note: 500 INTERNAL for context)
        "resource_exhausted",
        "resource has been exhausted",
        # Message patterns
        "input context is too long",
        "context is too long",
        "prompt (or context) is too large",
        # === LiteLLM ===
        # Normalized patterns across providers
        "contextwindowexceedederror",
        "context_length",
        "input too long",
        "token budget",
        # === Groq ===
        # Same as OpenAI: "context_length_exceeded"
        # Message: "Please reduce the length of the messages"
        "reduce the length of the messages",
        # === Mistral ===
        # Message: "exceeds the model's maximum context length of X"
        "exceeds the model's maximum context length",
        "number of tokens in the prompt exceeds",
        # === OpenRouter ===
        # Message: "this endpoint's maximum context length is X tokens"
        "endpoint's maximum context length",
        "endpoints maximum context length",
        # Suggestion in error: "use the 'middle-out' transform"
        "middle-out",
        # === Cohere ===
        # Message: "Too many tokens: the total number of tokens..."
        "too many tokens",
        # === Generic patterns (catch-all) ===
        "maximum tokens",
        "token limit",
        "exceeds the maximum",
        "context window",
        "context limit",
        "max_tokens exceed",
    ]

    for pattern in context_error_patterns:
        if pattern in error_str:
            return True

    # 4. Check for OpenAI BadRequestError with context patterns
    try:
        from openai import BadRequestError

        if isinstance(error, BadRequestError):
            # Any BadRequestError mentioning context/tokens is likely a context error
            if any(p in error_str for p in ["context", "token", "length", "exceed", "maximum"]):
                return True
    except ImportError:
        pass

    return False


def get_provider_from_error(error: Exception) -> str | None:
    """Attempt to determine the provider from an error.

    Args:
        error: The exception to analyze.

    Returns:
        Provider name if identifiable, None otherwise.
    """
    # First try exception type detection (most reliable)
    provider = _check_exception_type(error)
    if provider:
        return provider

    error_str = str(error).lower()
    error_module = str(getattr(type(error), "__module__", "")).lower()

    # Check module names
    if "openai" in error_module:
        return "openai"
    if "anthropic" in error_module:
        return "anthropic"
    if "google" in error_module or "gemini" in error_module:
        return "google"
    if "groq" in error_module:
        return "groq"
    if "mistral" in error_module:
        return "mistral"
    if "cohere" in error_module:
        return "cohere"
    if "litellm" in error_module:
        return "litellm"

    # Check error message content for provider hints
    provider_patterns = [
        # OpenAI model names
        (["gpt-4", "gpt-3", "o1-", "o3-", "davinci", "curie"], "openai"),
        # Anthropic model names
        (["claude", "anthropic"], "anthropic"),
        # Google/Gemini
        (["gemini", "palm", "bard"], "google"),
        # Groq
        (["groq", "llama-3", "mixtral"], "groq"),
        # Mistral
        (["mistral", "codestral"], "mistral"),
        # Cohere
        (["cohere", "command-r"], "cohere"),
        # OpenRouter
        (["openrouter", "middle-out"], "openrouter"),
    ]

    for patterns, provider_name in provider_patterns:
        if any(p in error_str for p in patterns):
            return provider_name

    return None


def parse_context_error_info(error: Exception) -> ContextErrorInfo | None:
    """Extract detailed information from a context length error.

    Parses provider-specific error messages to extract token counts
    and limits, which can be useful for compression decisions.

    Args:
        error: The exception to parse.

    Returns:
        ContextErrorInfo with extracted details, or None if not a context error.

    Examples:
        >>> # Anthropic error
        >>> err = Exception("input length and max_tokens exceed context limit: 187254 + 20000 > 200000")
        >>> info = parse_context_error_info(err)
        >>> info.input_tokens
        187254
        >>> info.context_limit
        200000
    """
    if not is_context_length_error(error):
        return None

    error_str = str(error)
    provider = get_provider_from_error(error) or "unknown"
    info = ContextErrorInfo(
        provider=provider,
        http_status=_get_http_status(error),
        raw_message=error_str,
    )

    # Try to extract token counts based on provider patterns

    # Anthropic: "input length and max_tokens exceed context limit: 187254 + 20000 > 200000"
    anthropic_match = re.search(
        r"(\d+)\s*\+\s*(\d+)\s*>\s*(\d+)",
        error_str,
    )
    if anthropic_match:
        info.input_tokens = int(anthropic_match.group(1))
        info.max_tokens = int(anthropic_match.group(2))
        info.context_limit = int(anthropic_match.group(3))
        return info

    # OpenAI: "maximum context length is 128000 tokens. However, you requested 135000 tokens (130000 in the messages, 5000 in the completion)"
    openai_match = re.search(
        r"maximum context length is (\d+) tokens.*?requested (\d+) tokens.*?(\d+) in the messages.*?(\d+) in the completion",
        error_str,
        re.IGNORECASE | re.DOTALL,
    )
    if openai_match:
        info.context_limit = int(openai_match.group(1))
        info.input_tokens = int(openai_match.group(3))
        info.max_tokens = int(openai_match.group(4))
        return info

    # OpenAI simpler: "maximum context length is 4096 tokens"
    simple_limit_match = re.search(
        r"maximum context length (?:is |of )?(\d+)",
        error_str,
        re.IGNORECASE,
    )
    if simple_limit_match:
        info.context_limit = int(simple_limit_match.group(1))

    # OpenRouter: "maximum context length is 131072 tokens. however, you requested about 138956 tokens"
    openrouter_match = re.search(
        r"maximum context length is (\d+) tokens.*?requested (?:about )?(\d+) tokens",
        error_str,
        re.IGNORECASE | re.DOTALL,
    )
    if openrouter_match:
        info.context_limit = int(openrouter_match.group(1))
        info.input_tokens = int(openrouter_match.group(2))
        return info

    # Mistral: "exceeds the model's maximum context length of 32768"
    mistral_match = re.search(
        r"maximum context length of (\d+)",
        error_str,
        re.IGNORECASE,
    )
    if mistral_match:
        info.context_limit = int(mistral_match.group(1))

    # Cohere: "exceeds the limit of 4081"
    cohere_match = re.search(
        r"exceeds the limit of (\d+)",
        error_str,
        re.IGNORECASE,
    )
    if cohere_match:
        info.context_limit = int(cohere_match.group(1))

    # Generic: look for any token counts
    if info.context_limit is None:
        # Try to find "X tokens" patterns
        token_matches = re.findall(r"(\d+)\s*tokens?", error_str, re.IGNORECASE)
        if token_matches:
            # Usually the largest number is the limit
            numbers = [int(m) for m in token_matches]
            info.context_limit = max(numbers)

    return info
