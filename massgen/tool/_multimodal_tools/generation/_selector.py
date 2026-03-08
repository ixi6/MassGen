"""
Backend and model selection logic for media generation.

Selects the best available backend and model based on:
1. User-specified preference (backend/model parameter)
2. Config-specified backend/model (multimodal_config from YAML)
3. First available in priority list with valid API key / default model
"""

from typing import Any

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.generation._base import (
    BACKEND_PRIORITY,
    MediaType,
    get_default_model,
    has_api_key,
)


def select_backend_and_model(
    media_type: MediaType,
    preferred_backend: str | None = None,
    preferred_model: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Select the best available backend and model for a media type.

    Priority order for backend:
    1. User-specified backend parameter (if available)
    2. Config-specified backend from YAML (multimodal_config.{type}.backend)
    3. First available backend in priority list with valid API key

    Priority order for model:
    1. User-specified model parameter
    2. Config-specified model from YAML (multimodal_config.{type}.model)
    3. Default model for the selected backend

    Args:
        media_type: Type of media to generate (IMAGE, VIDEO, AUDIO)
        preferred_backend: User-preferred backend name (e.g., "google", "openai")
        preferred_model: User-preferred model name
        config: multimodal_config dict with per-modality overrides

    Returns:
        Tuple of (backend_name, model_name) or (None, None) if no backend available
    """
    selected_backend = None
    selected_model = None

    # Get config for this media type
    media_config = config.get(media_type.value, {}) if config else {}
    config_backend = media_config.get("backend")
    config_model = media_config.get("model")

    # 1. Check user preference first
    if preferred_backend and preferred_backend != "auto":
        if _is_backend_available(preferred_backend, media_type):
            logger.info(
                f"[GenerationSelector] Using preferred backend '{preferred_backend}' " f"for {media_type.value}",
            )
            selected_backend = preferred_backend
        else:
            logger.warning(
                f"[GenerationSelector] Preferred backend '{preferred_backend}' " f"unavailable (no API key or doesn't support {media_type.value}), " f"falling back to config/priority list",
            )

    # 2. Check config backend if user didn't specify
    if not selected_backend and config_backend:
        if _is_backend_available(config_backend, media_type):
            logger.info(
                f"[GenerationSelector] Using config backend '{config_backend}' " f"for {media_type.value}",
            )
            selected_backend = config_backend
        else:
            logger.warning(
                f"[GenerationSelector] Config backend '{config_backend}' " f"unavailable, falling back to priority list",
            )

    # 3. Fall through priority list if still no backend
    if not selected_backend:
        priority_list = BACKEND_PRIORITY.get(media_type, [])
        for backend_name in priority_list:
            if _is_backend_available(backend_name, media_type):
                logger.info(
                    f"[GenerationSelector] Auto-selected '{backend_name}' " f"for {media_type.value} (first available in priority list)",
                )
                selected_backend = backend_name
                break

    if not selected_backend:
        logger.warning(
            f"[GenerationSelector] No backend available for {media_type.value}. " f"Checked: {BACKEND_PRIORITY.get(media_type, [])}",
        )
        return None, None

    # Now select model with priority:
    # 1. User-specified model
    # 2. Config model
    # 3. Default model for backend
    if preferred_model:
        selected_model = preferred_model
        logger.debug(f"[GenerationSelector] Using user-specified model: {selected_model}")
    elif config_model:
        selected_model = config_model
        logger.info(f"[GenerationSelector] Using config model '{config_model}' for {media_type.value}")
    else:
        selected_model = get_default_model(selected_backend, media_type)
        logger.debug(f"[GenerationSelector] Using default model: {selected_model}")

    return selected_backend, selected_model


def select_backend(
    media_type: MediaType,
    preferred: str | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Select the best available backend for a media type.

    This is a convenience wrapper around select_backend_and_model that only
    returns the backend. Use select_backend_and_model when you also need
    to get the model from config.

    Args:
        media_type: Type of media to generate (IMAGE, VIDEO, AUDIO)
        preferred: User-preferred backend name (e.g., "google", "openai")
        config: multimodal_config dict with per-modality overrides

    Returns:
        Backend name string or None if no backend available
    """
    backend, _ = select_backend_and_model(media_type, preferred, None, config)
    return backend


def _is_backend_available(backend_name: str, media_type: MediaType) -> bool:
    """Check if a backend is available for a media type.

    A backend is available if:
    1. It has a valid API key
    2. It supports the requested media type (has a default model)

    Args:
        backend_name: Name of the backend
        media_type: Type of media to generate

    Returns:
        True if the backend can handle this media type
    """
    # Check API key
    if not has_api_key(backend_name):
        return False

    # Check if backend supports this media type
    default_model = get_default_model(backend_name, media_type)
    return default_model is not None


def get_available_backends(media_type: MediaType) -> list[str]:
    """Get list of all available backends for a media type.

    Args:
        media_type: Type of media to generate

    Returns:
        List of backend names that are available
    """
    priority_list = BACKEND_PRIORITY.get(media_type, [])
    return [b for b in priority_list if _is_backend_available(b, media_type)]


def get_available_backends_hint(media_type: MediaType) -> str:
    """Get a helpful message about required API keys for a media type.

    Args:
        media_type: Type of media to generate

    Returns:
        Hint string for user about which API keys to set
    """
    from ._base import BACKEND_API_KEYS

    priority_list = BACKEND_PRIORITY.get(media_type, [])
    hints = []

    for backend in priority_list:
        env_vars = BACKEND_API_KEYS.get(backend, [])
        if env_vars:
            hints.append(f"{backend}: {' or '.join(env_vars)}")

    if hints:
        return f"Set one of these API keys: {', '.join(hints)}"
    return "No backends configured for this media type."
