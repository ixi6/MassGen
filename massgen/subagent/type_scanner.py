# -*- coding: utf-8 -*-
"""Scanner for specialized subagent types defined on disk.

Mirrors the skills discovery pattern: directories containing SUBAGENT.md
with YAML frontmatter are discovered and parsed into SpecializedSubagentConfig.
"""

import logging
import re
from pathlib import Path
from typing import List

from massgen.subagent.models import SpecializedSubagentConfig

logger = logging.getLogger(__name__)


def scan_subagent_types(
    builtin_dir: Path = Path("massgen/subagent_types"),
    project_dir: Path = Path(".agent/subagent_types"),
) -> List[SpecializedSubagentConfig]:
    """Scan directories for SUBAGENT.md files and parse into configs.

    Scans builtin_dir first, then project_dir. Project types override
    built-in types on name collision (case-insensitive).

    Args:
        builtin_dir: Path to built-in subagent types (ships with MassGen)
        project_dir: Path to project-level custom types

    Returns:
        Deduplicated list of SpecializedSubagentConfig
    """
    builtin_types = _scan_directory(builtin_dir)
    project_types = _scan_directory(project_dir)

    # Project overrides builtin on name collision (case-insensitive)
    result: List[SpecializedSubagentConfig] = []
    seen: set = set()

    # Project types first (they win on collision)
    for t in project_types:
        key = t.name.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)

    # Then builtin types (skip if name already seen)
    for t in builtin_types:
        key = t.name.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)

    return result


def _scan_directory(directory: Path) -> List[SpecializedSubagentConfig]:
    """Scan a directory for subdirectories containing SUBAGENT.md."""
    types: List[SpecializedSubagentConfig] = []

    if not directory.is_dir():
        return types

    for type_path in sorted(directory.iterdir()):
        if not type_path.is_dir():
            continue

        subagent_file = type_path / "SUBAGENT.md"
        if not subagent_file.exists():
            continue

        try:
            content = subagent_file.read_text(encoding="utf-8")
            config = _parse_subagent_md(content, str(subagent_file), type_path.name)
            if config:
                types.append(config)
        except Exception as e:
            logger.warning(f"Failed to parse {subagent_file}: {e}")
            continue

    return types


def _parse_subagent_md(
    content: str,
    source_path: str,
    dir_name: str,
) -> SpecializedSubagentConfig | None:
    """Parse a SUBAGENT.md file into a SpecializedSubagentConfig.

    Extracts YAML frontmatter for metadata and uses the body as system_prompt.
    """
    from massgen.filesystem_manager.skills_manager import parse_frontmatter

    metadata = parse_frontmatter(content)

    # Extract system prompt: everything after the closing ---
    system_prompt = ""
    match = re.match(r"^---\n.*?\n---\n?(.*)", content, re.DOTALL)
    if match:
        system_prompt = match.group(1).strip()

    name = str(metadata.get("name", "")).strip() or dir_name
    description = metadata.get("description", "")

    if not description:
        logger.warning(f"SUBAGENT.md at {source_path} has no description, skipping")
        return None

    return SpecializedSubagentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        default_background=bool(metadata.get("default_background", False)),
        default_refine=bool(metadata.get("default_refine", False)),
        skills=metadata.get("skills", []) or [],
        mcp_servers=metadata.get("mcp_servers", []) or [],
        source_path=source_path,
    )
