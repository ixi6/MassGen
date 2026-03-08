"""Share MassGen sessions via GitHub Gist.

This module provides functionality to upload MassGen session logs to GitHub Gist
for easy sharing. Viewers can access shared sessions without authentication.

Enhanced to support:
- Multi-turn session sharing (all turns in chronological order)
- Error state sharing (incomplete/failed sessions)
- Workspace artifact inclusion with size limits and interactive prompts
"""

import base64
import fnmatch
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console

from .filesystem_manager._constants import MAX_FILE_SIZE_FOR_SHARING as MAX_FILE_SIZE
from .filesystem_manager._constants import MAX_FILES_FOR_SHARING as MAX_FILES
from .filesystem_manager._constants import (
    MAX_PREVIEWABLE_FILE_SIZE_FOR_SHARING as MAX_PREVIEWABLE_FILE_SIZE,
)
from .filesystem_manager._constants import MAX_TOTAL_SIZE_FOR_SHARING as MAX_TOTAL_SIZE
from .filesystem_manager._constants import (
    OFFICE_DOCUMENT_EXTENSIONS,
    PREVIEWABLE_EXTENSIONS,
)
from .filesystem_manager._constants import SHARE_EXCLUDE_DIRS as EXCLUDE_PATTERNS
from .filesystem_manager._constants import (
    SHARE_EXCLUDE_EXTENSIONS as EXCLUDE_EXTENSIONS,
)
from .filesystem_manager._constants import (
    WORKSPACE_INCLUDE_EXTENSIONS,
)

# =============================================================================
# Office Document PDF Conversion
# =============================================================================

# Docker images for LibreOffice conversion (in order of preference)
# Sudo image is recommended and pre-selected in `massgen --setup-docker`
MASSGEN_DOCKER_IMAGES = [
    "ghcr.io/massgen/mcp-runtime-sudo:latest",  # Preferred - has sudo access
    "ghcr.io/massgen/mcp-runtime:latest",  # Fallback - standard image
]


def _get_available_docker_image(client) -> str | None:
    """Find the first available MassGen Docker image.

    Args:
        client: Docker client instance

    Returns:
        Image name if found, None otherwise
    """
    for image in MASSGEN_DOCKER_IMAGES:
        try:
            client.images.get(image)
            return image
        except Exception:
            continue
    return None


def convert_office_to_pdf(file_path: Path, console: Console | None = None) -> bytes | None:
    """Convert DOCX/PPTX/XLSX to PDF using Docker + LibreOffice.

    Uses the same approach as the webui /api/convert/document endpoint.
    Tries the sudo image first (recommended), falls back to standard image.

    Args:
        file_path: Path to the Office document
        console: Optional Rich console for logging warnings

    Returns:
        PDF bytes if successful, None if conversion failed or Docker unavailable
    """
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except ImportError:
        if console:
            console.print("[yellow]Docker Python package not installed - skipping Office document conversion[/yellow]")
        return None
    except Exception:
        if console:
            console.print("[yellow]Docker not available - skipping Office document conversion[/yellow]")
        return None

    # Find an available MassGen image (tries sudo first, then standard)
    docker_image = _get_available_docker_image(client)
    if docker_image is None:
        if console:
            console.print("[yellow]MassGen Docker image not found. Run: massgen --setup-docker[/yellow]")
        return None

    # Create temp directory for output
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # Run LibreOffice conversion in container
        # Docker requires absolute paths for volume mounts
        input_dir = file_path.parent.resolve()
        input_filename = file_path.name
        output_filename = file_path.stem + ".pdf"

        try:
            # Run soffice in container
            client.containers.run(
                docker_image,
                command=[
                    "/bin/sh",
                    "-c",
                    f"soffice --headless --convert-to pdf --outdir /output '/input/{input_filename}'",
                ],
                volumes={
                    str(input_dir): {"bind": "/input", "mode": "ro"},
                    str(temp_dir_path): {"bind": "/output", "mode": "rw"},
                },
                remove=True,
                user="root",  # LibreOffice needs write access to home dir
                stderr=True,
                stdout=True,
            )

            # Check if PDF was created
            output_pdf = temp_dir_path / output_filename
            if not output_pdf.exists():
                # Try alternate output name (sometimes LibreOffice changes case)
                for f in temp_dir_path.iterdir():
                    if f.suffix.lower() == ".pdf":
                        output_pdf = f
                        break

            if not output_pdf.exists():
                if console:
                    console.print(f"[yellow]PDF conversion failed for {file_path.name}[/yellow]")
                return None

            # Read and return the PDF bytes
            return output_pdf.read_bytes()

        except Exception as e:
            if console:
                console.print(f"[yellow]PDF conversion error for {file_path.name}: {e}[/yellow]")
            return None


# =============================================================================
# Data Classes for Multi-Turn Sharing
# =============================================================================


@dataclass
class TurnInfo:
    """Metadata for a single turn in a session.

    Attributes:
        turn_number: 1-indexed turn number
        attempt_number: Attempt within turn (e.g., 2 if this is the second attempt)
        total_attempts: Total number of attempts for this turn (e.g., 2 if there are 2 attempts)
        attempt_path: Absolute path to the attempt directory
        status: Turn status - "complete", "error", or "timeout"
        question: The question/prompt for this turn (if available)
        winner: The winning agent ID (if applicable)
    """

    turn_number: int
    attempt_number: int
    total_attempts: int
    attempt_path: Path
    status: str = "complete"
    question: str | None = None
    winner: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "turn_number": self.turn_number,
            "attempt_number": self.attempt_number,
            "total_attempts": self.total_attempts,
            "status": self.status,
            "question": self.question,
            "winner": self.winner,
        }


@dataclass
class WorkspaceWarning:
    """Warning about workspace size limit exceedance.

    Attributes:
        agent_id: The agent whose workspace exceeded the limit
        turn_number: Turn number where this workspace exists
        actual_size: Actual workspace size in bytes
        limit: The configured limit in bytes
        file_count: Number of files in the workspace
        files: List of (path, size) tuples for files in the workspace
    """

    agent_id: str
    turn_number: int
    actual_size: int
    limit: int
    file_count: int
    files: list[tuple[str, int]] = field(default_factory=list)


class WorkspaceAction(Enum):
    """Actions user can take when workspace limit is exceeded."""

    INCREASE_LIMIT = "increase_limit"
    EXCLUDE_WORKSPACE = "exclude_workspace"
    SELECT_FILES = "select_files"
    CANCEL = "cancel"


@dataclass
class WorkspaceDecision:
    """User's decision about how to handle workspace limit exceedance.

    Attributes:
        action: The action to take
        new_limit: New limit in bytes (if action is INCREASE_LIMIT)
        selected_files: List of file paths to include (if action is SELECT_FILES)
    """

    action: WorkspaceAction
    new_limit: int | None = None
    selected_files: list[str] | None = None


# Priority files to always include (most important first)
PRIORITY_FILES = [
    "answer.txt",  # Always include answer files
    "metrics_summary.json",
    "status.json",
    "coordination_events.json",
    "snapshot_mappings.json",
    "coordination_table.txt",
    "execution_metadata.yaml",
]


def is_previewable_file(file_path: Path) -> bool:
    """Check if a file is a previewable binary (pptx, pdf, images).

    These files get higher size limits and priority since they're often
    the main deliverable from agent work.
    """
    return file_path.suffix.lower() in PREVIEWABLE_EXTENSIONS


def is_answer_file(rel_path: str) -> bool:
    """Check if a file is an answer file that should always be included."""
    return rel_path.endswith("answer.txt") or "/answer.txt" in rel_path


# Pattern to match redundant final presentation files in agent_outputs
EXCLUDE_FILE_PATTERN = "final_presentation_*_latest.txt"

# Viewer URL base (hosted on MassGen org GitHub Pages)
VIEWER_URL_BASE = "https://massgen.github.io/MassGen-Viewer/"


class ShareError(Exception):
    """Error during share operation."""


def should_exclude(path: Path, rel_path: str) -> bool:
    """Check if file should be excluded from upload.

    Args:
        path: Absolute path to the file
        rel_path: Relative path from log directory

    Returns:
        True if file should be excluded
    """
    # Exclude hidden/system files by name
    excluded_filenames = {".DS_Store", "Thumbs.db", ".gitignore", ".gitkeep"}
    if path.name in excluded_filenames:
        return True

    # Check excluded files by pattern
    if fnmatch.fnmatch(path.name, EXCLUDE_FILE_PATTERN):
        return True

    # Check directory patterns (but allow workspace files with allowed extensions)
    for pattern in EXCLUDE_PATTERNS:
        if pattern in rel_path:
            # Allow workspace files with allowed extensions
            # Paths like: agent_a/20251218_170133/workspace/file.txt
            #         or: final/agent_a/workspace/file.txt
            if pattern == "workspace":
                suffix = path.suffix.lower()
                if suffix in WORKSPACE_INCLUDE_EXTENSIONS:
                    return False  # Include this workspace file
            return True

    # Check extensions
    for ext in EXCLUDE_EXTENSIONS:
        if path.name.endswith(ext):
            return True

    # Exclude massgen.log (usually large)
    if path.name == "massgen.log":
        return True

    # Exclude MCP stderr logs (debug noise)
    if path.name.startswith("mcp_") and path.name.endswith("_stderr.log"):
        return True

    return False


def collect_files(log_dir: Path) -> tuple[dict[str, str], list[tuple[str, int]]]:
    """Collect and flatten files for gist upload.

    Args:
        log_dir: Path to the log attempt directory

    Returns:
        Tuple of (files dict, skipped list)
        - files: Dict mapping flattened filenames to content
        - skipped: List of (rel_path, size) tuples for skipped files
    """
    files: dict[str, str] = {}
    skipped: list[tuple[str, int]] = []
    total_size = 0

    # First pass: collect all eligible files with sizes
    candidates = []
    for file_path in log_dir.rglob("*"):
        if not file_path.is_file():
            continue

        rel_path = str(file_path.relative_to(log_dir))

        # Check exclusion patterns
        if should_exclude(file_path, rel_path):
            continue

        try:
            size = file_path.stat().st_size
            # Skip empty files (gist doesn't allow blank files)
            if size == 0:
                continue
            # Skip files over size limit
            if size > MAX_FILE_SIZE:
                skipped.append((rel_path, size))
                continue
            candidates.append((rel_path, file_path, size))
        except OSError:
            continue

    # Sort: priority files first, then by size (smaller first)
    def sort_key(item: tuple[str, Path, int]) -> tuple[int, int, int]:
        rel_path, _, size = item
        filename = Path(rel_path).name
        if filename in PRIORITY_FILES:
            return (0, PRIORITY_FILES.index(filename), size)
        return (1, 0, size)

    candidates.sort(key=sort_key)

    # Second pass: add files within limits
    for rel_path, file_path, size in candidates:
        if len(files) >= MAX_FILES:
            skipped.append((rel_path, size))
            continue
        if total_size + size > MAX_TOTAL_SIZE:
            skipped.append((rel_path, size))
            continue

        try:
            content = file_path.read_text(errors="replace")
            # Skip files that are effectively empty (only whitespace)
            if not content.strip():
                continue
            # Flatten path: agent_a/timestamp/answer.txt → agent_a__timestamp__answer.txt
            flat_name = rel_path.replace("/", "__").replace("\\", "__")
            files[flat_name] = content
            total_size += size
        except (OSError, UnicodeDecodeError):
            skipped.append((rel_path, size))
            continue

    return files, skipped


# =============================================================================
# Multi-Turn Session Sharing Functions
# =============================================================================


def collect_files_multi_turn(
    session_root: Path,
    turns: list["TurnInfo"],
    include_workspace: bool = True,
    workspace_limit: int = 500_000,
    console: Console | None = None,
) -> tuple[dict[str, str], list[tuple[str, int]], list[WorkspaceWarning]]:
    """Collect files from all turns in a multi-turn session.

    Unlike collect_files() which only collects from a single attempt directory,
    this function iterates over all turns and prefixes files with turn/attempt info.

    For Office documents (.docx, .pptx, .xlsx):
    - Includes the original file as base64 (for download)
    - Also converts to PDF and includes that (for preview)

    Args:
        session_root: Path to the session root directory
        turns: List of TurnInfo objects for turns to include
        include_workspace: Whether to include workspace artifacts
        workspace_limit: Maximum workspace size per agent in bytes
        console: Optional Rich console for logging

    Returns:
        Tuple of (files dict, skipped list, workspace warnings)
        - files: Dict mapping flattened filenames to content
        - skipped: List of (rel_path, size) tuples for skipped files
        - warnings: List of WorkspaceWarning for limit exceedances
    """
    files: dict[str, str] = {}
    skipped: list[tuple[str, int]] = []
    warnings: list[WorkspaceWarning] = []
    total_size = 0
    # Track if we've already shown Docker warning (avoid duplicates)
    _docker_warning_shown = False
    # Track if we've found execution_metadata.yaml (only exists in attempt_1)
    _found_execution_metadata = False
    # Track if we've found agent_outputs (only exists in attempt_1)
    _found_agent_outputs = False

    for turn in turns:
        turn_prefix = f"turn_{turn.turn_number}__attempt_{turn.attempt_number}__"
        attempt_dir = turn.attempt_path

        # Collect files from this turn's attempt directory
        candidates = []
        for file_path in attempt_dir.rglob("*"):
            if not file_path.is_file():
                continue

            rel_path = str(file_path.relative_to(attempt_dir))

            # Skip nested subagent log directories (creates very long paths)
            if ".massgen" in rel_path or "massgen_logs" in rel_path:
                continue
            # Skip subagent workspaces entirely - these are nested MassGen sessions
            if "/subagents/" in rel_path or "subagents/" in rel_path:
                continue

            # Check exclusion patterns
            if should_exclude(file_path, rel_path):
                continue

            try:
                size = file_path.stat().st_size
                if size == 0:
                    continue
                # Use higher limit for previewable binary files (pptx, pdf, images)
                # and answer files (must always be included)
                is_previewable = is_previewable_file(file_path)
                is_answer = is_answer_file(rel_path)
                max_size = MAX_PREVIEWABLE_FILE_SIZE if (is_previewable or is_answer) else MAX_FILE_SIZE
                if size > max_size:
                    skipped.append((f"{turn_prefix}{rel_path}", size))
                    continue
                candidates.append((rel_path, file_path, size, is_previewable, is_answer))
            except OSError:
                continue

        # Sort: priority order (balanced across agents)
        # 1. Answer files (must include)
        # 2. FINAL workspace previewable files (the actual deliverable)
        # 3. Priority metadata files
        # 4. Latest timestamp workspace per agent (balanced - one per agent first)
        # 5. Older timestamp workspaces
        # 6. Other files by size

        # First, identify the latest timestamp per agent for workspace files
        agent_timestamps: dict[str, list[str]] = {}
        for rel_path, _, _, _, _ in candidates:
            if "workspace" in rel_path and "/final/" not in rel_path:
                import re

                # Extract agent_id and timestamp from path like: agent_a/20251231_093357/workspace/file
                agent_match = re.match(r"^([^/]+)/(\d{8}_\d+)/", rel_path)
                if agent_match:
                    agent_id = agent_match.group(1)
                    timestamp = agent_match.group(2)
                    if agent_id not in agent_timestamps:
                        agent_timestamps[agent_id] = []
                    if timestamp not in agent_timestamps[agent_id]:
                        agent_timestamps[agent_id].append(timestamp)

        # Sort timestamps descending (newest first) for each agent
        for agent_id in agent_timestamps:
            agent_timestamps[agent_id].sort(reverse=True)

        def sort_key(item: tuple[str, Path, int, bool, bool]) -> tuple[int, int, int, str, int]:
            rel_path, file_path, size, is_previewable, is_answer = item
            filename = Path(rel_path).name

            # Priority 0: Answer files (must include)
            if is_answer:
                return (0, 0, 0, "", size)

            # Check if this is a workspace file
            is_workspace = "workspace" in rel_path
            is_final_workspace = is_workspace and "/final/" in rel_path

            # Priority 1: FINAL workspace previewable files (the main deliverable)
            if is_final_workspace and is_previewable:
                return (1, 0, 0, "", size)

            # Priority 2: Named priority files (metadata)
            if filename in PRIORITY_FILES:
                return (2, PRIORITY_FILES.index(filename), 0, "", size)

            # Priority 3: FINAL workspace non-previewable files
            if is_final_workspace:
                return (3, 0, 0, "", size)

            # For timestamped workspaces, get agent and timestamp rank
            if is_workspace and not is_final_workspace:
                import re

                agent_match = re.match(r"^([^/]+)/(\d{8}_\d+)/", rel_path)
                if agent_match:
                    agent_id = agent_match.group(1)
                    timestamp = agent_match.group(2)
                    ts_list = agent_timestamps.get(agent_id, [])
                    # Rank is position in sorted list (0 = newest)
                    ts_rank = ts_list.index(timestamp) if timestamp in ts_list else 999

                    # Priority 4: Previewable workspace files, sorted by timestamp rank (balanced across agents)
                    # ts_rank ensures we get newest from each agent first
                    if is_previewable:
                        return (4, ts_rank, 0, agent_id, size)

                    # Priority 6: Non-previewable workspace files
                    return (6, ts_rank, 0, agent_id, size)

            # Priority 5: Other previewable files
            if is_previewable:
                return (5, 0, 0, "", size)

            # Priority 7: Everything else by size
            return (7, 0, 0, "", size)

        candidates.sort(key=sort_key)

        # Add files within limits
        for rel_path, file_path, size, is_previewable, is_answer in candidates:
            if len(files) >= MAX_FILES:
                skipped.append((f"{turn_prefix}{rel_path}", size))
                continue

            # Calculate estimated final size including base64 overhead (~1.37x) and PDF conversion
            suffix = file_path.suffix.lower()
            is_binary = suffix in OFFICE_DOCUMENT_EXTENSIONS or suffix == ".pdf" or suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            # Base64 encoding adds ~37% overhead
            estimated_size = int(size * 1.37) if is_binary else size
            # Office docs also get PDF conversion - estimate PDF is similar size to original
            if suffix in OFFICE_DOCUMENT_EXTENSIONS:
                estimated_size += int(size * 1.37)  # Add estimated PDF size

            if total_size + estimated_size > MAX_TOTAL_SIZE:
                skipped.append((f"{turn_prefix}{rel_path}", size))
                continue

            try:
                # Flatten path with turn prefix
                flat_name = turn_prefix + rel_path.replace("/", "__").replace("\\", "__")

                # Handle Office documents specially (binary files)
                if suffix in OFFICE_DOCUMENT_EXTENSIONS:
                    # Read as binary and encode as base64
                    binary_content = file_path.read_bytes()
                    content = base64.b64encode(binary_content).decode("utf-8")
                    files[flat_name] = content
                    total_size += len(content)  # Use actual encoded size

                    # Also convert to PDF for preview
                    pdf_bytes = convert_office_to_pdf(
                        file_path,
                        console if not _docker_warning_shown else None,
                    )
                    if pdf_bytes:
                        pdf_content = base64.b64encode(pdf_bytes).decode("utf-8")
                        pdf_flat_name = flat_name + ".pdf"
                        files[pdf_flat_name] = pdf_content
                        total_size += len(pdf_content)  # Use actual encoded size
                        if console:
                            console.print(f"  [dim]Converted {file_path.name} → PDF for preview[/dim]")
                    else:
                        _docker_warning_shown = True
                elif suffix == ".pdf":
                    # PDF files - read as binary and encode as base64
                    binary_content = file_path.read_bytes()
                    content = base64.b64encode(binary_content).decode("utf-8")
                    files[flat_name] = content
                    total_size += len(content)  # Use actual encoded size
                elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    # Image files - read as binary and encode as base64
                    binary_content = file_path.read_bytes()
                    content = base64.b64encode(binary_content).decode("utf-8")
                    files[flat_name] = content
                    total_size += len(content)  # Use actual encoded size
                else:
                    # Text files - read as text
                    content = file_path.read_text(errors="replace")
                    if not content.strip():
                        continue
                    files[flat_name] = content
                    total_size += len(content)  # Use actual content size

                    # Track if we found key session files
                    if rel_path == "execution_metadata.yaml":
                        _found_execution_metadata = True
                    elif rel_path.startswith("agent_outputs/"):
                        _found_agent_outputs = True
            except (OSError, UnicodeDecodeError):
                skipped.append((f"{turn_prefix}{rel_path}", size))
                continue

    # Fallback: if execution_metadata.yaml or agent_outputs not found in exported turns,
    # try to get them from turn_1/attempt_1 (where they are created)
    if not _found_execution_metadata or not _found_agent_outputs:
        fallback_attempt = session_root / "turn_1" / "attempt_1"
        if fallback_attempt.exists():
            # Use first turn's prefix for fallback files
            fallback_prefix = "turn_1__attempt_1__"

            # Fallback for execution_metadata.yaml
            if not _found_execution_metadata:
                exec_meta_path = fallback_attempt / "execution_metadata.yaml"
                if exec_meta_path.exists():
                    try:
                        content = exec_meta_path.read_text(errors="replace")
                        if content.strip():
                            flat_name = fallback_prefix + "execution_metadata.yaml"
                            files[flat_name] = content
                            total_size += len(content)
                    except (OSError, UnicodeDecodeError):
                        pass

            # Fallback for agent_outputs directory
            if not _found_agent_outputs:
                agent_outputs_dir = fallback_attempt / "agent_outputs"
                if agent_outputs_dir.exists():
                    for output_file in agent_outputs_dir.glob("*.txt"):
                        # Skip _latest files, system_status, and Unknown agent files
                        if "_latest" in output_file.name or output_file.name == "system_status.txt":
                            continue
                        if "Unknown" in output_file.name:
                            continue
                        try:
                            content = output_file.read_text(errors="replace")
                            if content.strip():
                                rel_path = f"agent_outputs/{output_file.name}"
                                flat_name = fallback_prefix + rel_path.replace("/", "__")
                                files[flat_name] = content
                                total_size += len(content)
                        except (OSError, UnicodeDecodeError):
                            pass

    return files, skipped, warnings


def collect_workspace_files(
    session_root: Path,
    turns: list["TurnInfo"],
    limit_per_agent: int = 500_000,
    console: Console | None = None,
) -> dict[str, tuple[str, int]]:
    """Collect workspace files from all turns with size tracking.

    Workspace files are found in patterns like:
    - turn_N/attempt_N/agent_id/timestamp/workspace/*
    - turn_N/attempt_N/final/agent_id/workspace/*

    For Office documents (.docx, .pptx, .xlsx):
    - Includes the original file as base64 (for download)
    - Also converts to PDF and includes that (for preview)

    Args:
        session_root: Path to the session root directory
        turns: List of TurnInfo objects
        limit_per_agent: Maximum workspace size per agent in bytes
        console: Optional Rich console for logging

    Returns:
        Dict mapping flattened file paths to (content, size) tuples
    """
    workspace_files: dict[str, tuple[str, int]] = {}
    # Track which Office files we've already warned about (avoid duplicate warnings)
    _docker_warning_shown = False

    for turn in turns:
        attempt_dir = turn.attempt_path

        # Find workspace directories
        for workspace_dir in attempt_dir.rglob("workspace"):
            if not workspace_dir.is_dir():
                continue

            # Get agent ID from path (workspace is under agent_id/timestamp/workspace or final/agent_id/workspace)
            rel_to_attempt = workspace_dir.relative_to(attempt_dir)
            parts = rel_to_attempt.parts
            if len(parts) >= 2:
                _agent_id = parts[1] if parts[0] == "final" else parts[0]  # noqa: F841 - reserved for future per-agent tracking
            else:
                pass

            # Track size per agent for this turn
            agent_size = 0

            for file_path in workspace_dir.rglob("*"):
                if not file_path.is_file():
                    continue

                # Skip nested subagent directories and their log directories (very long paths)
                rel_to_workspace = str(file_path.relative_to(workspace_dir))
                if ".massgen" in rel_to_workspace or "massgen_logs" in rel_to_workspace:
                    continue
                # Skip subagent workspaces entirely - these are nested MassGen sessions
                if "subagents/" in rel_to_workspace or "/subagents/" in rel_to_workspace:
                    continue

                # Skip non-allowed extensions
                suffix = file_path.suffix.lower()
                if suffix not in WORKSPACE_INCLUDE_EXTENSIONS:
                    continue

                try:
                    size = file_path.stat().st_size
                    if size == 0:
                        continue

                    # Check per-agent limit
                    if agent_size + size > limit_per_agent:
                        continue

                    # Create flattened path
                    rel_path = file_path.relative_to(attempt_dir)
                    turn_prefix = f"turn_{turn.turn_number}__attempt_{turn.attempt_number}__"
                    flat_name = turn_prefix + str(rel_path).replace("/", "__").replace("\\", "__")

                    # Handle Office documents specially (binary files)
                    if suffix in OFFICE_DOCUMENT_EXTENSIONS:
                        # Read as binary and encode as base64
                        binary_content = file_path.read_bytes()
                        content = base64.b64encode(binary_content).decode("utf-8")
                        workspace_files[flat_name] = (content, size)
                        agent_size += size

                        # Also convert to PDF for preview
                        pdf_bytes = convert_office_to_pdf(file_path, console if not _docker_warning_shown else None)
                        if pdf_bytes:
                            pdf_content = base64.b64encode(pdf_bytes).decode("utf-8")
                            pdf_flat_name = flat_name + ".pdf"
                            pdf_size = len(pdf_bytes)
                            workspace_files[pdf_flat_name] = (pdf_content, pdf_size)
                            agent_size += pdf_size
                            if console:
                                console.print(f"  [dim]Converted {file_path.name} → PDF for preview[/dim]")
                        else:
                            _docker_warning_shown = True
                    elif suffix == ".pdf":
                        # PDF files - read as binary and encode as base64
                        binary_content = file_path.read_bytes()
                        content = base64.b64encode(binary_content).decode("utf-8")
                        workspace_files[flat_name] = (content, size)
                        agent_size += size
                    else:
                        # Text files - read as text
                        content = file_path.read_text(errors="replace")
                        if not content.strip():
                            continue
                        workspace_files[flat_name] = (content, size)
                        agent_size += size

                except (OSError, UnicodeDecodeError):
                    continue

    return workspace_files


def detect_sensitive_patterns(workspace_dir: Path) -> list[str]:
    """Detect files that may contain sensitive data.

    Checks for:
    - .env files
    - Files containing patterns like api_key, secret, password
    - Credential files (credentials.json, etc.)

    Args:
        workspace_dir: Path to workspace directory to scan

    Returns:
        List of relative file paths that may contain sensitive data
    """
    sensitive_files: list[str] = []

    # Sensitive filename patterns
    sensitive_names = {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "secrets.json",
        "secrets.yaml",
        ".npmrc",
        ".pypirc",
    }

    # Patterns to search in file content
    sensitive_patterns = [
        re.compile(r'["\']?api[_-]?key["\']?\s*[:=]', re.IGNORECASE),
        re.compile(r'["\']?secret["\']?\s*[:=]', re.IGNORECASE),
        re.compile(r'["\']?password["\']?\s*[:=]', re.IGNORECASE),
        re.compile(r'["\']?token["\']?\s*[:=]', re.IGNORECASE),
        re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style API keys
        re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key IDs
    ]

    if not workspace_dir.exists():
        return sensitive_files

    for file_path in workspace_dir.rglob("*"):
        if not file_path.is_file():
            continue

        rel_path = str(file_path.relative_to(workspace_dir))

        # Check filename
        if file_path.name.lower() in sensitive_names:
            sensitive_files.append(rel_path)
            continue

        # Check content of text files
        suffix = file_path.suffix.lower()
        if suffix in {".json", ".yaml", ".yml", ".txt", ".env", ".ini", ".conf", ".config"}:
            try:
                content = file_path.read_text(errors="ignore")
                for pattern in sensitive_patterns:
                    if pattern.search(content):
                        sensitive_files.append(rel_path)
                        break
            except (OSError, UnicodeDecodeError):
                continue

    return sensitive_files


def prompt_workspace_limit_exceeded(
    agent_id: str,
    actual_size: int,
    limit: int,
    files: list[tuple[str, int]],
) -> WorkspaceDecision:
    """Prompt user when workspace exceeds size limit.

    Args:
        agent_id: The agent whose workspace exceeded the limit
        actual_size: Actual workspace size in bytes
        limit: The configured limit in bytes
        files: List of (filename, size) tuples

    Returns:
        WorkspaceDecision with the user's choice
    """
    import questionary

    def format_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f}KB"
        return f"{size_bytes}B"

    print(f"\n⚠️  Workspace for '{agent_id}' exceeds limit:")
    print(f"   Size: {format_size(actual_size)} (limit: {format_size(limit)})")
    print(f"   Files: {len(files)}")

    choices = [
        questionary.Choice("Increase limit to include all files", value="increase"),
        questionary.Choice("Exclude this workspace from share", value="exclude"),
        questionary.Choice("Select specific files to include", value="select"),
        questionary.Choice("Cancel export", value="cancel"),
    ]

    answer = questionary.select(
        "What would you like to do?",
        choices=choices,
    ).ask()

    if answer == "increase":
        new_limit = questionary.text(
            "Enter new limit (e.g., '1MB', '2MB'):",
            default=f"{int(actual_size * 1.1 / 1024)}KB",
        ).ask()
        try:
            new_limit_bytes = parse_size(new_limit) if new_limit else actual_size * 2
            return WorkspaceDecision(action=WorkspaceAction.INCREASE_LIMIT, new_limit=new_limit_bytes)
        except ValueError:
            return WorkspaceDecision(action=WorkspaceAction.INCREASE_LIMIT, new_limit=actual_size * 2)
    elif answer == "exclude":
        return WorkspaceDecision(action=WorkspaceAction.EXCLUDE_WORKSPACE)
    elif answer == "select":
        selected = prompt_file_selection(files, limit)
        return WorkspaceDecision(action=WorkspaceAction.SELECT_FILES, selected_files=selected)
    else:
        return WorkspaceDecision(action=WorkspaceAction.CANCEL)


def prompt_sensitive_data_warning(sensitive_files: list[str]) -> bool:
    """Prompt user about detected sensitive data.

    Args:
        sensitive_files: List of file paths that may contain sensitive data

    Returns:
        True to proceed with sharing, False to cancel
    """
    import questionary

    print("\n⚠️  Potentially sensitive files detected:")
    for f in sensitive_files[:5]:
        print(f"   - {f}")
    if len(sensitive_files) > 5:
        print(f"   ... and {len(sensitive_files) - 5} more")

    answer = questionary.confirm(
        "These files may contain API keys, passwords, or other secrets. Continue sharing?",
        default=False,
    ).ask()

    return answer if answer is not None else False


def prompt_large_session_warning(file_count: int, total_size: int) -> bool:
    """Prompt user about sharing a large session.

    Args:
        file_count: Number of files to share
        total_size: Total size in bytes

    Returns:
        True to proceed with sharing, False to cancel
    """
    import questionary

    def format_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f}KB"
        return f"{size_bytes}B"

    print(f"\n📦 Large session detected: {file_count} files ({format_size(total_size)})")

    answer = questionary.confirm(
        "This session is quite large. Continue sharing?",
        default=True,
    ).ask()

    return answer if answer is not None else True


def prompt_file_selection(files: list[tuple[str, int]], limit: int) -> list[str]:
    """Prompt user to select specific files to include.

    Args:
        files: List of (filename, size) tuples
        limit: Size limit in bytes

    Returns:
        List of selected file paths
    """
    import questionary

    def format_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f}KB"
        return f"{size_bytes}B"

    # Sort by size descending
    sorted_files = sorted(files, key=lambda x: x[1], reverse=True)

    choices = [
        questionary.Choice(
            f"{name} ({format_size(size)})",
            value=name,
            checked=size <= limit // len(files) if files else False,
        )
        for name, size in sorted_files[:20]  # Limit to 20 files for readability
    ]

    if len(sorted_files) > 20:
        print(f"(Showing top 20 of {len(sorted_files)} files by size)")

    selected = questionary.checkbox(
        "Select files to include:",
        choices=choices,
    ).ask()

    return selected if selected else []


def determine_session_status(turns: list["TurnInfo"]) -> str:
    """Determine overall session status from turns.

    Args:
        turns: List of TurnInfo objects

    Returns:
        Session status: "complete", "error", or "interrupted"
    """
    if not turns:
        return "interrupted"

    # Check the last turn's status
    last_turn = turns[-1]
    if last_turn.status == "error":
        return "error"
    if last_turn.status == "timeout":
        return "error"
    if last_turn.status == "interrupted":
        return "interrupted"

    # Check if any turn had errors
    for turn in turns:
        if turn.status == "error" or turn.status == "timeout":
            return "error"

    return "complete"


def extract_error_info(turn_path: Path) -> dict[str, Any] | None:
    """Extract error details from a turn's status.json.

    Args:
        turn_path: Path to the turn's attempt directory

    Returns:
        Error info dict with type, message, agent_id, or None if no error
    """
    status_file = turn_path / "status.json"
    if not status_file.exists():
        return None

    try:
        status_data = json.loads(status_file.read_text())

        # Check rounds for errors
        rounds = status_data.get("rounds", {}).get("by_outcome", {})
        if rounds.get("error", 0) == 0 and rounds.get("timeout", 0) == 0:
            return None

        # Look for agent-specific errors
        agents = status_data.get("agents", {})
        for agent_id, agent_data in agents.items():
            if "error" in agent_data:
                error = agent_data["error"]
                return {
                    "type": error.get("type", "unknown"),
                    "message": error.get("message", "Unknown error"),
                    "timestamp": error.get("timestamp"),
                    "agent_id": agent_id,
                }

        # Generic error if no agent-specific error found
        if rounds.get("timeout", 0) > 0:
            return {"type": "timeout", "message": "Session timed out", "agent_id": None}

        return {"type": "unknown", "message": "Session ended with error", "agent_id": None}

    except (json.JSONDecodeError, KeyError):
        return None


def create_session_manifest(
    session_root: Path,
    turns: list["TurnInfo"],
    error_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create _session_manifest.json content for multi-turn sessions.

    Args:
        session_root: Path to the session root directory
        turns: List of TurnInfo objects
        error_info: Optional error details if session failed

    Returns:
        Manifest dict to be serialized as JSON
    """
    status = determine_session_status(turns)

    # Aggregate metrics from all turns
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    question = None
    winner = None

    for turn in turns:
        # Get first turn's question as session question
        if question is None and turn.question:
            question = turn.question

        # Get last successful turn's winner
        if turn.winner:
            winner = turn.winner

        # Try to load metrics from each turn
        metrics_file = turn.attempt_path / "metrics_summary.json"
        if metrics_file.exists():
            try:
                metrics = json.loads(metrics_file.read_text())
                costs = metrics.get("costs", {})
                total_cost += costs.get("total_estimated_cost", 0.0)
                total_input_tokens += costs.get("total_input_tokens", 0)
                total_output_tokens += costs.get("total_output_tokens", 0)
            except (json.JSONDecodeError, KeyError):
                pass

    # Count unique turns (not attempts)
    unique_turn_numbers = {turn.turn_number for turn in turns}
    # Count total attempts across all turns
    total_attempts = len(turns)

    manifest = {
        "version": "2.0",
        "session_id": session_root.name,
        "turn_count": len(unique_turn_numbers),
        "attempt_count": total_attempts,
        "status": status,
        "question": question,
        "winner": winner,
        "total_cost": total_cost,
        "total_tokens": {
            "input": total_input_tokens,
            "output": total_output_tokens,
        },
        "turns": [turn.to_dict() for turn in turns],
    }

    if error_info:
        manifest["error"] = error_info

    return manifest


def parse_size(size_str: str) -> int:
    """Parse a size string like '500KB' or '1MB' into bytes.

    Args:
        size_str: Size string (e.g., "500KB", "1MB", "1000")

    Returns:
        Size in bytes

    Raises:
        ValueError: If the size string is invalid
    """
    size_str = size_str.strip().upper()

    # Try plain number first
    if size_str.isdigit():
        return int(size_str)

    # Try KB/MB suffixes
    match = re.match(r"^(\d+)\s*(KB|MB|GB)$", size_str)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "KB":
            return value * 1024
        elif unit == "MB":
            return value * 1024 * 1024
        elif unit == "GB":
            return value * 1024 * 1024 * 1024

    raise ValueError(f'Invalid size string: "{size_str}". Use format like "500KB" or "1MB".')


def create_gist(files: dict[str, str], description: str, console: Console | None = None) -> str:
    """Create a secret gist and return the gist ID.

    Uses a two-step process for large files:
    1. Create an empty gist via `gh gist create`
    2. Clone, add files, and push via git (allows up to 100MB per file)

    Args:
        files: Dict mapping filenames to content
        description: Gist description
        console: Optional console for status messages

    Returns:
        Gist ID

    Raises:
        ShareError: If gist creation fails
    """
    # Calculate total size to decide which method to use
    total_size = sum(len(content) for content in files.values())
    # Use git push for large uploads (>10MB) to avoid API limits
    use_git_push = total_size > 10_000_000

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        if use_git_push:
            # Method 2: Create empty gist, then git push (supports large files)
            return _create_gist_via_git(files, description, tmpdir_path, console)
        else:
            # Method 1: Direct API upload (faster for small files)
            return _create_gist_via_api(files, description, tmpdir_path)


def _create_gist_via_api(files: dict[str, str], description: str, tmpdir_path: Path) -> str:
    """Create gist using gh CLI API (limited to ~1MB per file)."""
    # Write files to temp directory
    for name, content in files.items():
        (tmpdir_path / name).write_text(content, encoding="utf-8")

    file_args = [str(tmpdir_path / name) for name in files.keys()]

    try:
        result = subprocess.run(
            ["gh", "gist", "create", "-d", description] + file_args,
            capture_output=True,
            text=True,
            check=True,
        )
        gist_url = result.stdout.strip()
        gist_id = gist_url.split("/")[-1]
        return gist_id

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "gh auth login" in stderr or "not logged in" in stderr.lower():
            raise ShareError(
                "Not authenticated with GitHub.\n" "Run 'gh auth login' to enable sharing.",
            )
        raise ShareError(f"Failed to create gist: {stderr}")
    except FileNotFoundError:
        raise ShareError(
            "GitHub CLI (gh) not found.\n" "Install it from https://cli.github.com/",
        )


def _create_gist_via_git(
    files: dict[str, str],
    description: str,
    tmpdir_path: Path,
    console: Console | None = None,
) -> str:
    """Create gist using git push (supports up to 100MB per file).

    Process:
    1. Create a minimal gist with a placeholder file via API
    2. Clone the gist repo
    3. Add all files and commit
    4. Push to origin
    """
    try:
        # Step 1: Create minimal gist with placeholder
        placeholder_file = tmpdir_path / ".massgen_placeholder"
        placeholder_file.write_text("# MassGen Session\nUploading files...")

        result = subprocess.run(
            ["gh", "gist", "create", "-d", description, str(placeholder_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        gist_url = result.stdout.strip()
        gist_id = gist_url.split("/")[-1]

        if console:
            console.print(f"  [dim]Created gist {gist_id}, pushing files via git...[/dim]")

        # Step 2: Clone the gist using gh CLI's git credential helper
        clone_dir = tmpdir_path / "gist_repo"

        # Use HTTPS URL - gh CLI will handle auth via credential helper
        gist_git_url = f"https://gist.github.com/{gist_id}.git"

        # Set up environment to use gh as git credential helper
        git_env = os.environ.copy()
        git_env["GIT_ASKPASS"] = ""  # Disable interactive prompts
        git_env["GIT_TERMINAL_PROMPT"] = "0"

        # Configure git to use gh for gist.github.com credentials
        subprocess.run(
            ["git", "config", "--global", "credential.https://gist.github.com.helper", "!gh auth git-credential"],
            capture_output=True,
            text=True,
            check=False,  # Don't fail if already set
        )

        subprocess.run(
            ["git", "clone", gist_git_url, str(clone_dir)],
            capture_output=True,
            text=True,
            check=True,
            cwd=tmpdir_path,
            env=git_env,
        )

        # Step 3: Remove placeholder and add all files
        placeholder_in_repo = clone_dir / ".massgen_placeholder"
        if placeholder_in_repo.exists():
            placeholder_in_repo.unlink()

        for name, content in files.items():
            file_path = clone_dir / name
            file_path.write_text(content, encoding="utf-8")

        # Step 4: Git add, commit, push
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            text=True,
            check=True,
            cwd=clone_dir,
        )

        subprocess.run(
            ["git", "commit", "-m", "Add MassGen session files"],
            capture_output=True,
            text=True,
            check=True,
            cwd=clone_dir,
        )

        subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True,
            text=True,
            check=True,
            cwd=clone_dir,
        )

        return gist_id

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "gh auth login" in stderr or "not logged in" in stderr.lower():
            raise ShareError(
                "Not authenticated with GitHub.\n" "Run 'gh auth login' to enable sharing.",
            )
        if "Permission denied" in stderr or "publickey" in stderr:
            raise ShareError(
                "Git SSH authentication failed.\n" "Ensure your SSH key is added to GitHub: https://github.com/settings/keys",
            )
        raise ShareError(f"Failed to create gist: {stderr}")
    except FileNotFoundError as e:
        if "gh" in str(e):
            raise ShareError(
                "GitHub CLI (gh) not found.\n" "Install it from https://cli.github.com/",
            )
        if "git" in str(e):
            raise ShareError("Git not found. Please install git.")
        raise ShareError(f"Command not found: {e}")


def share_session_multi_turn(
    session_root: Path,
    turns: list["TurnInfo"],
    console: Console | None = None,
    include_workspace: bool = True,
    workspace_limit: int = 500_000,
    dry_run: bool = False,
    verbose: bool = False,
) -> str:
    """Upload multi-turn session to GitHub Gist and return viewer URL.

    Args:
        session_root: Path to the session root directory
        turns: List of TurnInfo objects for turns to include
        console: Optional console for status messages
        include_workspace: Whether to include workspace artifacts
        workspace_limit: Maximum workspace size per agent in bytes
        dry_run: If True, show what would be shared without creating gist
        verbose: If True, show detailed file listing

    Returns:
        Viewer URL (or "DRY_RUN" if dry_run=True)

    Raises:
        ShareError: If sharing fails
    """
    if console:
        console.print(f"[bold]Session:[/bold] {session_root.name}")
        console.print(f"[bold]Turns:[/bold] {len(turns)}")
        if dry_run:
            console.print("[yellow][DRY RUN][/yellow]")
        console.print()

    # Show turn-by-turn progress
    if console:
        for turn in turns:
            # Status icons and colors
            if turn.status == "complete":
                status_icon = "✓"
                status_color = "green"
            elif turn.status == "restarted":
                status_icon = "↻"
                status_color = "yellow"
            elif turn.status == "error":
                status_icon = "✗"
                status_color = "red"
            else:
                status_icon = "○"
                status_color = "yellow"

            # Build label with attempt info if there are multiple attempts
            attempt_label = ""
            if turn.total_attempts > 1:
                attempt_label = f" (attempt {turn.attempt_number}/{turn.total_attempts})"

            question_preview = ""
            if turn.question:
                q = turn.question.replace("\n", " ").strip()
                question_preview = f" - {q[:40]}..." if len(q) > 40 else f" - {q}"
            console.print(
                f"  [{status_color}]{status_icon}[/{status_color}] " f"Turn {turn.turn_number}{attempt_label}{question_preview}",
            )
        console.print()

    if console:
        console.print("[dim]Collecting files...[/dim]")

    files, skipped, warnings = collect_files_multi_turn(
        session_root,
        turns,
        include_workspace=include_workspace,
        workspace_limit=workspace_limit,
        console=console,
    )

    if not files:
        raise ShareError("No files to upload")

    # Add session manifest
    status = determine_session_status(turns)
    error_info = None
    if status == "error" and turns:
        error_info = extract_error_info(turns[-1].attempt_path)

    manifest = create_session_manifest(session_root, turns, error_info)
    files["_session_manifest.json"] = json.dumps(manifest, indent=2)

    total_size = sum(len(c) for c in files.values())

    # Verbose mode: show all files
    if verbose and console:
        console.print()
        console.print("[bold]Files to share:[/bold]")
        sorted_files = sorted(files.items(), key=lambda x: x[0])
        for filename, content in sorted_files:
            size = len(content)
            console.print(f"  [dim]{filename}[/dim] ({size:,} bytes)")
        console.print()

    # Warn if files were skipped
    if skipped and console:
        console.print(f"[yellow]Skipped {len(skipped)} files (too large or over limit):[/yellow]")
        skipped_sorted = sorted(skipped, key=lambda x: x[1], reverse=True)
        for path, size in skipped_sorted[:5]:
            console.print(f"  [dim]- {path} ({size:,} bytes)[/dim]")
        if len(skipped_sorted) > 5:
            console.print(f"  [dim]... and {len(skipped_sorted) - 5} more[/dim]")
        console.print()

    if console:
        if dry_run:
            console.print(f"[dim]Would upload {len(files)} files ({total_size:,} bytes)[/dim]")
        else:
            console.print(f"[dim]Uploading {len(files)} files ({total_size:,} bytes)...[/dim]")

    # Create description from manifest
    description = "MassGen Session"
    if manifest.get("question"):
        q = manifest["question"].replace("\n", " ").strip()
        if len(q) > 50:
            q = q[:47] + "..."
        description = f"MassGen: {q}"
    if status == "error":
        description = f"[ERROR] {description}"
    if len(turns) > 1:
        description = f"{description} ({len(turns)} turns)"

    # Dry run: don't actually create the gist
    if dry_run:
        if console:
            console.print()
            console.print(f"[dim]Description: {description}[/dim]")
        return "DRY_RUN"

    gist_id = create_gist(files, description, console)

    return f"{VIEWER_URL_BASE}?gist={gist_id}"


def share_session(log_dir: Path | str, console: Console | None = None) -> str:
    """Upload session to GitHub Gist and return viewer URL.

    Args:
        log_dir: Path to log attempt directory
        console: Optional console for status messages

    Returns:
        Viewer URL

    Raises:
        ShareError: If sharing fails
    """
    # Ensure log_dir is a Path object
    if isinstance(log_dir, str):
        log_dir = Path(log_dir)

    if console:
        console.print("[dim]Collecting files...[/dim]")

    files, skipped = collect_files(log_dir)

    if not files:
        raise ShareError("No files to upload")

    total_size = sum(len(c) for c in files.values())

    # Warn if files were skipped
    if skipped and console:
        console.print(f"[yellow]Skipped {len(skipped)} files (too large or over limit):[/yellow]")
        # Sort by size descending to show biggest first
        skipped_sorted = sorted(skipped, key=lambda x: x[1], reverse=True)
        for path, size in skipped_sorted[:5]:
            console.print(f"  [dim]- {path} ({size:,} bytes)[/dim]")
        if len(skipped_sorted) > 5:
            console.print(f"  [dim]... and {len(skipped_sorted) - 5} more[/dim]")
        console.print()

    if console:
        console.print(f"[dim]Uploading {len(files)} files ({total_size:,} bytes)...[/dim]")

    # Get session info for description
    description = "MassGen Session"
    if "metrics_summary.json" in files:
        try:
            metrics = json.loads(files["metrics_summary.json"])
            question = metrics.get("meta", {}).get("question", "")
            if question:
                # Truncate and clean up question for description
                question_clean = question.replace("\n", " ").strip()
                if len(question_clean) > 50:
                    question_clean = question_clean[:47] + "..."
                description = f"MassGen: {question_clean}"
        except (json.JSONDecodeError, KeyError):
            pass

    gist_id = create_gist(files, description, console)

    return f"{VIEWER_URL_BASE}?gist={gist_id}"


def list_shares(console: Console) -> int:
    """List all MassGen gists for current user.

    Args:
        console: Rich console for output

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        result = subprocess.run(
            ["gh", "gist", "list", "--limit", "50"],
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            console.print("[dim]No gists found.[/dim]")
            return 0

        # Filter for MassGen gists
        lines = result.stdout.strip().split("\n")
        massgen_gists = [line for line in lines if "MassGen" in line]

        if not massgen_gists:
            console.print("[dim]No shared MassGen sessions found.[/dim]")
            console.print("[dim]Share a session with: massgen export --share[/dim]")
            return 0

        console.print("[bold]Shared Sessions:[/bold]\n")
        for line in massgen_gists:
            parts = line.split("\t")
            gist_id = parts[0] if parts else ""
            desc = parts[1] if len(parts) > 1 else ""
            files_info = parts[2] if len(parts) > 2 else ""
            visibility = parts[3] if len(parts) > 3 else ""
            updated = parts[4] if len(parts) > 4 else ""

            console.print(f"  [cyan]{gist_id}[/cyan]")
            console.print(f"    {desc}")
            console.print(f"    [dim]{files_info} files • {visibility} • {updated}[/dim]")
            console.print(f"    [dim]View: {VIEWER_URL_BASE}?gist={gist_id}[/dim]")
            console.print()

        return 0

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "gh auth login" in stderr or "not logged in" in stderr.lower():
            console.print("[red]Not authenticated with GitHub.[/red]")
            console.print("Run 'gh auth login' to enable sharing.")
            return 1
        console.print(f"[red]Error listing gists:[/red] {stderr}")
        return 1
    except FileNotFoundError:
        console.print("[red]GitHub CLI (gh) not found.[/red]")
        console.print("Install it from https://cli.github.com/")
        return 1


def delete_share(gist_id: str, console: Console) -> int:
    """Delete a shared session gist.

    Args:
        gist_id: Gist ID to delete
        console: Rich console for output

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        subprocess.run(
            ["gh", "gist", "delete", gist_id, "--yes"],
            capture_output=True,
            text=True,
            check=True,
        )
        console.print(f"[green]Deleted gist {gist_id}[/green]")
        return 0

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "gh auth login" in stderr or "not logged in" in stderr.lower():
            console.print("[red]Not authenticated with GitHub.[/red]")
            console.print("Run 'gh auth login' to enable sharing.")
            return 1
        if "not found" in stderr.lower() or "404" in stderr:
            console.print(f"[red]Gist not found:[/red] {gist_id}")
            return 1
        console.print(f"[red]Error deleting gist:[/red] {stderr}")
        return 1
    except FileNotFoundError:
        console.print("[red]GitHub CLI (gh) not found.[/red]")
        console.print("Install it from https://cli.github.com/")
        return 1
