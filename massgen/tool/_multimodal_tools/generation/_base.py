"""
Base types and protocols for unified media generation.

This module provides the core abstractions for the generation system:
- MediaType: Enum for image/video/audio generation
- GenerationConfig: Configuration passed to backends
- GenerationResult: Standardized result from any backend
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MediaType(Enum):
    """Types of media that can be generated."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass
class GenerationConfig:
    """Configuration passed to generation backends.

    Attributes:
        prompt: Text description of what to generate. For audio/speech this is
            the literal text to speak (not speaking instructions).
        output_path: Where to save the generated media
        media_type: Type of media being generated
        backend: Preferred backend (None for auto-selection)
        model: Override default model for the backend
        quality: Quality setting ("standard", "hd", etc.)
        duration: For video/audio - length in seconds
        voice: For audio - voice name or UUID. ElevenLabs names are resolved
            to UUIDs automatically.
        aspect_ratio: For image/video - aspect ratio string
        size: Image dimensions (OpenAI: "1024x1024" etc; Gemini: "512px"/"1K"/"2K"/"4K")
        extra_params: Backend-specific parameters (e.g., instructions, audio_type)
        input_images: Optional input images (image-to-image)
        input_image_paths: Resolved input image paths (for metadata)
        continue_from: Continuation ID from a previous generation result for
            multi-turn editing. OpenAI: response ID; Gemini: chat store ID.
    """

    prompt: str
    output_path: Path
    media_type: MediaType
    backend: str | None = None
    model: str | None = None
    quality: str | None = None
    duration: int | None = None
    voice: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    input_images: list[dict[str, str]] = field(default_factory=list)
    input_image_paths: list[str] = field(default_factory=list)
    continue_from: str | None = None


@dataclass
class GenerationResult:
    """Standardized result from any generation backend.

    Attributes:
        success: Whether generation succeeded
        output_path: Path to the generated file (if successful)
        media_type: Type of media generated
        backend_name: Name of backend used
        model_used: Specific model used
        file_size_bytes: Size of generated file
        duration_seconds: For video/audio - actual duration
        error: Error message if failed
        metadata: Backend-specific metadata
    """

    success: bool
    output_path: Path | None = None
    media_type: MediaType | None = None
    backend_name: str = ""
    model_used: str = ""
    file_size_bytes: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# API key environment variable mappings for each backend
BACKEND_API_KEYS: dict[str, list[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "elevenlabs": ["ELEVENLABS_API_KEY"],
}

# Default models for each backend and media type
DEFAULT_MODELS: dict[str, dict[MediaType, str]] = {
    "openai": {
        MediaType.IMAGE: "gpt-5.2",
        MediaType.VIDEO: "sora-2",
        MediaType.AUDIO: "gpt-4o-mini-tts",
    },
    "google": {
        MediaType.IMAGE: "gemini-3.1-flash-image-preview",  # Nano Banana 2
        MediaType.VIDEO: "veo-3.1-generate-preview",
    },
    "openrouter": {
        MediaType.IMAGE: "google/gemini-3.1-flash-image-preview",  # Nano Banana 2
    },
    "elevenlabs": {
        MediaType.AUDIO: "eleven_multilingual_v2",
    },
}

# Priority order for auto-selection per media type
BACKEND_PRIORITY: dict[MediaType, list[str]] = {
    MediaType.IMAGE: ["google", "openai", "openrouter"],
    MediaType.VIDEO: ["openai", "google"],
    MediaType.AUDIO: ["elevenlabs", "openai"],
}


def has_api_key(backend_name: str) -> bool:
    """Check if the required API key for a backend is available.

    Args:
        backend_name: Name of the backend ("openai", "google", "openrouter")

    Returns:
        True if at least one API key env var is set
    """
    env_vars = BACKEND_API_KEYS.get(backend_name, [])
    return any(os.getenv(var) for var in env_vars)


def get_api_key(backend_name: str) -> str | None:
    """Get the API key for a backend.

    Args:
        backend_name: Name of the backend

    Returns:
        The first available API key or None
    """
    env_vars = BACKEND_API_KEYS.get(backend_name, [])
    for var in env_vars:
        if key := os.getenv(var):
            return key
    return None


def get_default_model(backend_name: str, media_type: MediaType) -> str | None:
    """Get the default model for a backend and media type.

    Args:
        backend_name: Name of the backend
        media_type: Type of media to generate

    Returns:
        Default model string or None if not supported
    """
    backend_models = DEFAULT_MODELS.get(backend_name, {})
    return backend_models.get(media_type)
