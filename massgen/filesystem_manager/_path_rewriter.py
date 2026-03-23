"""Replace stale absolute paths in framework metadata files.

When workspaces are copied (step mode save, snapshot sharing), files inside
framework metadata directories may contain absolute paths pointing to the
original workspace location. This module rewrites those paths so they remain
valid in the copied workspace.

Only scans known framework subdirectories — never touches agent deliverables.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ._constants import BINARY_FILE_EXTENSIONS, SKIP_DIRS_FOR_LOGGING

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_FOR_PATH_REWRITE = 2_000_000  # 2 MB

# Framework metadata subdirs to scan recursively.
# These are written by the framework (verification, memory, tool results),
# not by agents in their deliverable output files.
_SCAN_DIRS = ("memory", ".massgen_scratch", ".tool_results")


def replace_stale_paths_in_workspace(
    workspace_root: Path,
    replacements: dict[str, str],
) -> int:
    """Replace stale absolute paths in framework metadata files.

    Only scans ``_SCAN_DIRS`` subdirectories recursively.
    Does **not** touch agent deliverables (root-level files, src/, etc.).

    Replacement keys are sorted longest-first to prevent partial matches
    (e.g. ``/tmp/workspace/subdir`` is replaced before ``/tmp/workspace``).

    Args:
        workspace_root: Root of the copied workspace.
        replacements: Mapping of old-path → new-path strings.

    Returns:
        Count of files that were modified.
    """
    if not replacements or not workspace_root.exists():
        return 0

    # Sort longest-first so longer paths are replaced before shorter prefixes
    ordered = sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True)

    # Pre-encode old paths to bytes for fast ``in`` scanning
    encoded_keys = [old.encode("utf-8") for old, _ in ordered]

    # Collect files from scan dirs
    target_files: list[Path] = []
    for scan_dir_name in _SCAN_DIRS:
        scan_dir = workspace_root / scan_dir_name
        if scan_dir.is_dir():
            target_files.extend(_walk_files(scan_dir))

    return _replace_in_files(target_files, ordered, encoded_keys)


def _walk_files(directory: Path) -> list[Path]:
    """Recursively collect files, skipping SKIP_DIRS_FOR_LOGGING."""
    files: list[Path] = []
    try:
        for entry in directory.iterdir():
            if entry.is_dir():
                if entry.name in SKIP_DIRS_FOR_LOGGING:
                    continue
                files.extend(_walk_files(entry))
            elif entry.is_file():
                files.append(entry)
    except OSError:
        pass
    return files


def _should_skip_file(file_path: Path) -> bool:
    """Return True if the file should not be scanned."""
    if file_path.suffix.lower() in BINARY_FILE_EXTENSIONS:
        return True
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_FOR_PATH_REWRITE:
            return True
    except OSError:
        return True
    return False


def _replace_in_files(
    files: list[Path],
    ordered_replacements: list[tuple[str, str]],
    encoded_keys: list[bytes],
) -> int:
    """Replace strings in a list of files. Returns count of modified files."""
    modified = 0
    for file_path in files:
        if not file_path.exists() or _should_skip_file(file_path):
            continue
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        if not any(key in raw for key in encoded_keys):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new_text = text
        for old_val, new_val in ordered_replacements:
            new_text = new_text.replace(old_val, new_val)
        if new_text != text:
            try:
                file_path.write_text(new_text, encoding="utf-8")
                modified += 1
            except OSError as exc:
                logger.debug("[PathRewriter] Failed to write %s: %s", file_path, exc)
    return modified


# ---------------------------------------------------------------------------
# Agent ID scrubbing in snapshot copies
# ---------------------------------------------------------------------------

# Framework dirs/files to scan for agent ID scrubbing.
# These are written by the orchestrator, not by agents.
_SCRUB_SCAN_DIRS = ("tasks", "memory", ".massgen_scratch", ".tool_results")

# Root-level framework files to scrub (not deliverables).
_SCRUB_ROOT_FILES = ("execution_trace.md",)


def scrub_agent_ids_in_snapshot(
    snapshot_root: Path,
    agent_id_mapping: dict[str, str],
) -> int:
    """Replace real agent IDs with anonymous IDs in a snapshot copy.

    Two passes:
    1. Rename files whose names contain real agent IDs.
    2. Replace real agent IDs in file contents.

    Only scans ``_SCRUB_SCAN_DIRS`` and ``_SCRUB_ROOT_FILES`` — never
    touches agent deliverables (root-level files other than the
    explicitly listed framework files, or arbitrary subdirectories).

    Args:
        snapshot_root: Root of the copied snapshot directory.
        agent_id_mapping: Mapping of real-agent-id → anonymous-id.

    Returns:
        Count of files renamed or content-modified.
    """
    if not agent_id_mapping or not snapshot_root.exists():
        return 0

    # Sort longest-first to prevent partial matches
    ordered = sorted(
        agent_id_mapping.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    modified = 0

    # Collect all files to process
    target_files: list[Path] = []
    for scan_dir_name in _SCRUB_SCAN_DIRS:
        scan_dir = snapshot_root / scan_dir_name
        if scan_dir.is_dir():
            target_files.extend(_walk_files(scan_dir))
    for root_file_name in _SCRUB_ROOT_FILES:
        root_file = snapshot_root / root_file_name
        if root_file.is_file():
            target_files.append(root_file)

    # Pass 1: Rename files whose names contain real agent IDs
    renamed_files: dict[Path, Path] = {}
    for file_path in target_files:
        new_name = file_path.name
        for real_id, anon_id in ordered:
            new_name = new_name.replace(real_id, anon_id)
        if new_name != file_path.name:
            new_path = file_path.parent / new_name
            try:
                file_path.rename(new_path)
                renamed_files[file_path] = new_path
                modified += 1
            except OSError as exc:
                logger.debug(
                    "[PathRewriter] Failed to rename %s -> %s: %s",
                    file_path,
                    new_path,
                    exc,
                )

    # Update target_files with renamed paths
    final_files = [renamed_files.get(fp, fp) for fp in target_files]

    # Pass 2: Replace agent IDs in file contents
    encoded_keys = [real_id.encode("utf-8") for real_id, _ in ordered]
    modified += _replace_in_files(final_files, ordered, encoded_keys)

    return modified
