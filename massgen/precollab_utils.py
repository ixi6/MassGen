"""Shared utilities for pre-collab phases (artifact discovery, context paths)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

# Standard search patterns for subagent output artifacts, in priority order.
_SEARCH_PATTERNS = [
    "full_logs/final/agent_*/workspace/{filename}",
    "full_logs/agent_*/*/*/{filename}",
    "workspace/snapshots/agent_*/{filename}",
    "workspace/agent_*/{filename}",
    "workspace/temp/agent_*/agent*/{filename}",
]


def find_precollab_artifact(
    log_directory: str,
    subagent_id: str,
    artifact_filename: str,
) -> Path | None:
    """Find a pre-collab artifact in subagent output using standard search patterns.

    Searches ``{log_directory}/subagents/{subagent_id}/`` with 5 patterns in
    priority order:

    1. ``full_logs/final/agent_*/workspace/{filename}``
    2. ``full_logs/agent_*/*/*/{filename}``
    3. ``workspace/snapshots/agent_*/{filename}``
    4. ``workspace/agent_*/{filename}``
    5. ``workspace/temp/agent_*/agent*/{filename}``

    Returns the most recently modified match, or ``None``.
    """
    base = Path(log_directory) / "subagents" / subagent_id
    if not base.exists():
        logger.debug(f"Subagent dir not found: {base}")
        return None

    found: list[Path] = []
    for pattern_template in _SEARCH_PATTERNS:
        pattern = pattern_template.format(filename=artifact_filename)
        found.extend(base.glob(pattern))

    if not found:
        logger.debug(f"No {artifact_filename} found in {base}")
        return None

    def _safe_mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except (FileNotFoundError, OSError):
            return 0.0

    found.sort(key=_safe_mtime, reverse=True)

    # Return the most recent match
    for candidate in found:
        if candidate.exists():
            logger.debug(f"Found {artifact_filename} at: {candidate}")
            return candidate

    return None


def build_subagent_parent_context_paths(
    parent_workspace: str,
    agent_configs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build read-only context paths for pre-collab subagents.

    Resolves the parent workspace and any ``context_paths`` entries from
    the agent backend configs into a deduplicated list of absolute
    ``{"path": ..., "permission": "read"}`` dicts.
    """
    base_workspace = Path(parent_workspace).resolve()
    context_paths: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add_path(raw_path: str | None) -> None:
        if not raw_path:
            return
        try:
            path_obj = Path(raw_path)
            resolved = path_obj.resolve() if path_obj.is_absolute() else (base_workspace / path_obj).resolve()
        except Exception:
            return
        path_str = str(resolved)
        if path_str in seen:
            return
        seen.add(path_str)
        context_paths.append({"path": path_str, "permission": "read"})

    _add_path(str(base_workspace))

    for config in agent_configs:
        if not isinstance(config, dict):
            continue
        backend = config.get("backend", {})
        if not isinstance(backend, dict):
            continue
        inherited_paths = backend.get("context_paths", [])
        if not isinstance(inherited_paths, list):
            continue
        for entry in inherited_paths:
            if isinstance(entry, str):
                _add_path(entry)
            elif isinstance(entry, dict):
                raw_path = entry.get("path")
                _add_path(str(raw_path).strip() if raw_path else None)

    return context_paths
