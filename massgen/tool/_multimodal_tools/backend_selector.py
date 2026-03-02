"""
Backend selector for multimodal tools.

Provides a clean, documented system for selecting which backend/model to use
for processing different media types (image, audio, video).

Priority Order:
1. Same backend as the calling agent (if specified and supports the media type)
2. Default priority list for each media type (first one with available API key)

This ensures we use the best available option while preferring consistency
with the agent's primary backend.
"""

import os
from dataclasses import dataclass

from massgen.logger_config import logger


@dataclass
class BackendConfig:
    """Configuration for a specific backend."""

    name: str  # e.g., "gemini", "openai", "anthropic"
    model: str  # e.g., "gemini-2.5-flash", "gpt-4o"
    api_key_env_vars: list[str]  # Environment variable names to check for API key

    def has_api_key(self) -> bool:
        """Check if any of the required API keys are available."""
        for env_var in self.api_key_env_vars:
            if os.getenv(env_var):
                return True
        return False

    def get_api_key(self) -> str | None:
        """Get the first available API key."""
        for env_var in self.api_key_env_vars:
            key = os.getenv(env_var)
            if key:
                return key
        return None


# =============================================================================
# Default Backend Configurations
# =============================================================================

# Gemini backends
# Note: These defaults can be overridden via config multimodal settings
GEMINI_AUDIO = BackendConfig(
    name="gemini",
    model="gemini-3-flash-preview",
    api_key_env_vars=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
)

GEMINI_VIDEO = BackendConfig(
    name="gemini",
    model="gemini-3.1-pro-preview",
    api_key_env_vars=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
)

GEMINI_IMAGE = BackendConfig(
    name="gemini",
    model="gemini-3-flash-preview",
    api_key_env_vars=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
)

# OpenAI backends
# Note: These defaults can be overridden via config multimodal settings
OPENAI_AUDIO = BackendConfig(
    name="openai",
    model="gpt-4o-transcribe",  # Specialized for audio transcription
    api_key_env_vars=["OPENAI_API_KEY"],
)

OPENAI_VIDEO = BackendConfig(
    name="openai",
    model="gpt-5.2",
    api_key_env_vars=["OPENAI_API_KEY"],
)

OPENAI_IMAGE = BackendConfig(
    name="openai",
    model="gpt-5.2",
    api_key_env_vars=["OPENAI_API_KEY"],
)

# Claude backends
# Note: These defaults can be overridden via config multimodal settings
CLAUDE_IMAGE = BackendConfig(
    name="claude",
    model="claude-sonnet-4-5-20250929",
    api_key_env_vars=["ANTHROPIC_API_KEY"],
)

CLAUDE_VIDEO = BackendConfig(
    name="claude",
    model="claude-sonnet-4-5-20250929",  # Has vision, uses frame extraction
    api_key_env_vars=["ANTHROPIC_API_KEY"],
)

# Grok backends (xAI) - OpenAI-compatible API
GROK_IMAGE = BackendConfig(
    name="grok",
    model="grok-4-1-fast-reasoning",
    api_key_env_vars=["XAI_API_KEY"],
)

GROK_VIDEO = BackendConfig(
    name="grok",
    model="grok-4-1-fast-reasoning",  # Has vision, uses frame extraction
    api_key_env_vars=["XAI_API_KEY"],
)

# OpenRouter backends - OpenAI-compatible API
OPENROUTER_IMAGE = BackendConfig(
    name="openrouter",
    model="openai/gpt-5.2",  # OpenAI model naming
    api_key_env_vars=["OPENROUTER_API_KEY"],
)

OPENROUTER_VIDEO = BackendConfig(
    name="openrouter",
    model="openai/gpt-5.2",  # OpenAI model naming, uses frame extraction
    api_key_env_vars=["OPENROUTER_API_KEY"],
)


# =============================================================================
# Priority Lists by Media Type
# =============================================================================
# Order matters: first available backend with API key will be used

AUDIO_BACKENDS = [
    GEMINI_AUDIO,  # Gemini has native audio understanding
    OPENAI_AUDIO,  # OpenAI Whisper for transcription
]

VIDEO_BACKENDS = [
    GEMINI_VIDEO,  # Gemini has native video understanding
    OPENAI_VIDEO,  # OpenAI with frame extraction
    CLAUDE_VIDEO,  # Claude with frame extraction
    # GROK_VIDEO,  # Grok with frame extraction
    OPENROUTER_VIDEO,  # OpenRouter with frame extraction
]

IMAGE_BACKENDS = [
    GEMINI_IMAGE,  # Gemini vision
    OPENAI_IMAGE,  # GPT-4o vision
    CLAUDE_IMAGE,  # Claude vision
    # GROK_IMAGE,  # Grok vision
    OPENROUTER_IMAGE,  # OpenRouter vision
]


# =============================================================================
# Backend Selector Class
# =============================================================================


class MultimodalBackendSelector:
    """
    Selects the best available backend for processing different media types.

    Usage:
        selector = MultimodalBackendSelector()

        # Get backend for audio, preferring the agent's backend
        config = selector.get_backend("audio", preferred_backend="gemini")

        # Get backend for video with no preference
        config = selector.get_backend("video")

        if config:
            print(f"Using {config.name} with model {config.model}")
        else:
            print("No backend available")
    """

    def __init__(self):
        self._priority_lists = {
            "audio": AUDIO_BACKENDS,
            "video": VIDEO_BACKENDS,
            "image": IMAGE_BACKENDS,
        }

    def get_backend(
        self,
        media_type: str,
        preferred_backend: str | None = None,
        preferred_model: str | None = None,
    ) -> BackendConfig | None:
        """
        Get the best available backend for a media type.

        Priority:
        1. Preferred backend (if specified and has API key)
        2. First backend in priority list with available API key

        Args:
            media_type: Type of media ("audio", "video", "image")
            preferred_backend: Backend name to prefer (e.g., "gemini", "openai")
            preferred_model: Model to use if preferred backend is selected

        Returns:
            BackendConfig if a backend is available, None otherwise
        """
        if media_type not in self._priority_lists:
            logger.warning(f"[BackendSelector] Unknown media type: {media_type}")
            return None

        priority_list = self._priority_lists[media_type]

        # First, try the preferred backend if specified
        if preferred_backend:
            for config in priority_list:
                if config.name.lower() == preferred_backend.lower():
                    if config.has_api_key():
                        # Use preferred model if specified, otherwise use default
                        if preferred_model:
                            return BackendConfig(
                                name=config.name,
                                model=preferred_model,
                                api_key_env_vars=config.api_key_env_vars,
                            )
                        logger.info(
                            f"[BackendSelector] Using preferred backend {config.name} " f"for {media_type}",
                        )
                        return config
                    else:
                        logger.info(
                            f"[BackendSelector] Preferred backend {preferred_backend} " f"has no API key, falling back to priority list",
                        )
                        break

        # Fall through priority list
        for config in priority_list:
            if config.has_api_key():
                logger.info(
                    f"[BackendSelector] Selected {config.name}/{config.model} " f"for {media_type} (first available in priority list)",
                )
                return config

        logger.warning(
            f"[BackendSelector] No backend available for {media_type}. " f"Checked: {[c.name for c in priority_list]}",
        )
        return None

    def get_priority_list(self, media_type: str) -> list[BackendConfig]:
        """Get the priority list for a media type."""
        return self._priority_lists.get(media_type, [])

    def list_available_backends(self, media_type: str) -> list[BackendConfig]:
        """List all backends with available API keys for a media type."""
        priority_list = self._priority_lists.get(media_type, [])
        return [config for config in priority_list if config.has_api_key()]


# Global instance for convenience
_selector = MultimodalBackendSelector()


def get_backend(
    media_type: str,
    preferred_backend: str | None = None,
    preferred_model: str | None = None,
) -> BackendConfig | None:
    """
    Convenience function to get the best available backend.

    Args:
        media_type: Type of media ("audio", "video", "image")
        preferred_backend: Backend name to prefer (e.g., "gemini", "openai")
        preferred_model: Model to use if preferred backend is selected

    Returns:
        BackendConfig if a backend is available, None otherwise

    Example:
        from massgen.tool._multimodal_tools.backend_selector import get_backend

        config = get_backend("audio", preferred_backend="gemini")
        if config:
            # Use config.name, config.model, config.get_api_key()
            pass
    """
    return _selector.get_backend(media_type, preferred_backend, preferred_model)
