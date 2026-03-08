"""
Model routing for the MassGen HTTP server.

Supports:
- massgen/path:<path> - Use a specific config file
- massgen/<example> - Use a built-in example config (e.g., massgen/basic_multi)
- massgen - Use the default config
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedModel:
    """Resolved model routing result."""

    raw_model: str
    config_path: str | None = None


def resolve_model(raw_model: str, *, default_config: str | None) -> ResolvedModel:
    """
    Route model string to config path.

    Model string formats:
    - "massgen/path:<path>" -> Use explicit config file path
    - "massgen/<example>" -> Use built-in example (e.g., "massgen/basic_multi" -> "@examples/basic_multi")
    - "massgen" or other -> Use default_config

    Args:
        raw_model: The model string from the request
        default_config: Default config path from server settings

    Returns:
        ResolvedModel with config_path set
    """
    # Explicit config path: massgen/path:/some/config.yaml
    if raw_model.startswith("massgen/path:"):
        path = raw_model[len("massgen/path:") :].strip()
        return ResolvedModel(raw_model=raw_model, config_path=path or default_config)

    # Built-in example: massgen/basic_multi -> @examples/basic_multi
    if raw_model.startswith("massgen/") and raw_model != "massgen/":
        example_name = raw_model[len("massgen/") :]
        # Don't treat "massgen/path:" as an example (already handled above)
        if example_name and not example_name.startswith("path:"):
            return ResolvedModel(raw_model=raw_model, config_path=f"@examples/{example_name}")

    # Default: use the server's default config
    return ResolvedModel(raw_model=raw_model, config_path=default_config)
