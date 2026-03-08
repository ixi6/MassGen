"""Scanner for specialized subagent types defined on disk.

Mirrors the skills discovery pattern: directories containing SUBAGENT.md
with YAML frontmatter are discovered and parsed into SpecializedSubagentConfig.
"""

import logging
import re
from pathlib import Path

from massgen.subagent.models import SpecializedSubagentConfig

logger = logging.getLogger(__name__)

DEFAULT_SUBAGENT_TYPES: list[str] = ["evaluator", "explorer", "researcher", "critic"]


def scan_subagent_types(
    builtin_dir: Path = Path("massgen/subagent_types"),
    project_dir: Path = Path(".agent/subagent_types"),
    allowed_types: list[str] | None = None,
) -> list[SpecializedSubagentConfig]:
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
    result: list[SpecializedSubagentConfig] = []
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

    if allowed_types is not None:
        allowed_lower = {t.lower() for t in allowed_types}
        found_names = {t.name.lower() for t in result}
        for requested in sorted(allowed_lower - found_names):
            logger.warning(f"Requested subagent type '{requested}' not found on disk")
        result = [t for t in result if t.name.lower() in allowed_lower]

    return result


def _scan_directory(directory: Path) -> list[SpecializedSubagentConfig]:
    """Scan a directory for subdirectories containing SUBAGENT.md."""
    types: list[SpecializedSubagentConfig] = []
    excluded_dir_names = {"_template"}

    if not directory.is_dir():
        return types

    for type_path in sorted(directory.iterdir()):
        if not type_path.is_dir():
            continue
        if type_path.name.lower() in excluded_dir_names:
            continue

        subagent_file = type_path / "SUBAGENT.md"
        if not subagent_file.exists():
            continue

        try:
            content = subagent_file.read_text(encoding="utf-8")
            config = _parse_subagent_md(content, str(subagent_file), type_path.name)
            if config:
                types.append(config)
        except ValueError:
            # Surface schema errors explicitly so users can fix invalid profiles.
            raise
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
    if not isinstance(metadata, dict):
        raise ValueError(f"Failed to parse SUBAGENT.md frontmatter at {source_path}")

    allowed_fields = {"name", "description", "skills", "expected_input"}
    unsupported_fields = sorted(set(metadata.keys()) - allowed_fields)
    if unsupported_fields:
        fields = ", ".join(unsupported_fields)
        raise ValueError(
            f"Unsupported specialized subagent frontmatter fields in {source_path}: {fields}. " "Allowed fields: name, description, skills, expected_input",
        )

    # Extract system prompt: everything after the closing ---
    system_prompt = ""
    match = re.match(r"^---\n.*?\n---\n?(.*)", content, re.DOTALL)
    if match:
        system_prompt = match.group(1).strip()

    name = str(metadata.get("name", "")).strip() or dir_name
    description = metadata.get("description", "")
    skills = metadata.get("skills", []) or []
    expected_input = metadata.get("expected_input", []) or []

    if skills and (not isinstance(skills, list) or any(not isinstance(item, str) for item in skills)):
        raise ValueError(f"Invalid 'skills' field in {source_path}: expected a list of strings")
    if expected_input and (not isinstance(expected_input, list) or any(not isinstance(item, str) for item in expected_input)):
        raise ValueError(f"Invalid 'expected_input' field in {source_path}: expected a list of strings")

    if not description:
        logger.warning(f"SUBAGENT.md at {source_path} has no description, skipping")
        return None

    return SpecializedSubagentConfig(
        name=name,
        description=description,
        system_prompt=system_prompt,
        skills=skills,
        expected_input=expected_input,
        source_path=source_path,
    )
