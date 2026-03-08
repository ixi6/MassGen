"""
Unified media generation module.

This module provides a unified interface for generating images, videos, and audio
using multiple backends (OpenAI, Google, OpenRouter).

Supports batch mode for parallel generation of multiple media items.

Usage:
    from massgen.tool._multimodal_tools.generation import generate_media

    # Generate a single image
    result = await generate_media(prompt="a cat in space", mode="image")

    # Generate multiple images in parallel (batch mode)
    result = await generate_media(
        prompts=["a cat in space", "a dog on the moon", "a bird in a forest"],
        mode="image",
        max_concurrent=3
    )

    # Generate a video with Google Veo
    result = await generate_media(prompt="robot walking", mode="video", backend_type="google")

    # Generate audio
    result = await generate_media(prompt="Hello world!", mode="audio", voice="nova")
"""

from ._base import (
    BACKEND_API_KEYS,
    BACKEND_PRIORITY,
    DEFAULT_MODELS,
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_api_key,
    get_default_model,
    has_api_key,
)
from ._selector import (
    get_available_backends,
    get_available_backends_hint,
    select_backend,
    select_backend_and_model,
)
from .generate_media import generate_media

__all__ = [
    # Main tool
    "generate_media",
    # Types
    "MediaType",
    "GenerationConfig",
    "GenerationResult",
    # Selection
    "select_backend",
    "select_backend_and_model",
    "get_available_backends",
    "get_available_backends_hint",
    # Utilities
    "has_api_key",
    "get_api_key",
    "get_default_model",
    # Constants
    "BACKEND_API_KEYS",
    "BACKEND_PRIORITY",
    "DEFAULT_MODELS",
]
