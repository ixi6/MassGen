"""Tests for SkillsSection registry integration and recently-added fallback.

Covers:
- Registry loading when SKILL_REGISTRY.md exists
- Recently-added skills appended when not in registry
- Fallback to per-skill XML when no registry exists
- Log analysis prompt includes registry integration instructions
"""

from pathlib import Path

from massgen.system_prompt_sections import SkillsSection

SKILLS = [
    {"name": "pdf", "location": "project", "description": "PDF toolkit"},
    {"name": "xlsx", "location": "project", "description": "Excel toolkit"},
    {"name": "brand-new", "location": "project", "description": "Just created"},
]

REGISTRY_CONTENT = """---
generated_by: skill-organizer
total_skills: 2
---

# Skill Registry

## Document Tools (2)
- **pdf**: Generate and manipulate PDF documents
- **xlsx**: Create and edit Excel spreadsheets
"""


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------


def test_skills_section_uses_registry_when_present(tmp_path: Path) -> None:
    """When a SKILL_REGISTRY.md exists, SkillsSection should include its content."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL_REGISTRY.md").write_text(REGISTRY_CONTENT, encoding="utf-8")

    section = SkillsSection(SKILLS, skills_dir=skills_dir)
    content = section.build_content()

    # Should include registry body (without frontmatter)
    assert "Skill Registry" in content
    assert "Document Tools" in content


def test_skills_section_strips_frontmatter_from_registry(tmp_path: Path) -> None:
    """Registry frontmatter should be stripped before injection."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL_REGISTRY.md").write_text(REGISTRY_CONTENT, encoding="utf-8")

    section = SkillsSection(SKILLS, skills_dir=skills_dir)
    content = section.build_content()

    assert "generated_by" not in content
    assert "total_skills: 2" not in content


# ---------------------------------------------------------------------------
# Recently-added skills
# ---------------------------------------------------------------------------


def test_recently_added_skills_appended(tmp_path: Path) -> None:
    """Skills not mentioned in the registry should appear in a 'Recently Added' section."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    # Registry only mentions pdf and xlsx, not brand-new
    (skills_dir / "SKILL_REGISTRY.md").write_text(REGISTRY_CONTENT, encoding="utf-8")

    section = SkillsSection(SKILLS, skills_dir=skills_dir)
    content = section.build_content()

    # brand-new should appear in recently added section
    assert "brand-new" in content
    assert "Just created" in content


def test_no_recently_added_when_all_in_registry(tmp_path: Path) -> None:
    """When all skills are in the registry, no recently-added section needed."""
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL_REGISTRY.md").write_text(REGISTRY_CONTENT, encoding="utf-8")

    # Only skills that are in the registry
    registered_skills = [
        {"name": "pdf", "location": "project", "description": "PDF toolkit"},
        {"name": "xlsx", "location": "project", "description": "Excel toolkit"},
    ]

    section = SkillsSection(registered_skills, skills_dir=skills_dir)
    content = section.build_content()

    assert "Recently Added" not in content


# ---------------------------------------------------------------------------
# Fallback when no registry
# ---------------------------------------------------------------------------


def test_skills_section_falls_back_without_registry() -> None:
    """Without a registry, SkillsSection should produce per-skill XML listing."""
    section = SkillsSection(SKILLS)
    content = section.build_content()

    assert "<skill>" in content
    assert "pdf" in content
    assert "xlsx" in content
    assert "brand-new" in content


def test_skills_section_falls_back_with_nonexistent_dir(tmp_path: Path) -> None:
    """With a skills_dir that doesn't contain a registry, should fall back to XML."""
    skills_dir = tmp_path / "nonexistent"

    section = SkillsSection(SKILLS, skills_dir=skills_dir)
    content = section.build_content()

    assert "<skill>" in content


# ---------------------------------------------------------------------------
# Log analysis registry integration
# ---------------------------------------------------------------------------


def test_log_analysis_user_prompt_mentions_registry() -> None:
    """User profile log analysis prompt should instruct placing skills in registry."""
    from massgen.cli import get_log_analysis_prompt_prefix

    result = get_log_analysis_prompt_prefix(
        log_dir="/tmp/test_log",
        turn=1,
        profile="user",
        skill_lifecycle_mode="create_or_update",
    )

    assert "SKILL_REGISTRY" in result or "registry" in result.lower()


# ---------------------------------------------------------------------------
# Usage instructions: hierarchical skills
# ---------------------------------------------------------------------------


def test_usage_instructions_mention_sections() -> None:
    """Usage instructions should tell agents that skills may contain sections."""
    section = SkillsSection(SKILLS)
    content = section.build_content()

    assert "section" in content.lower()


def test_usage_instructions_mention_skill_hierarchy() -> None:
    """Usage instructions should describe that skills can be hierarchical with sub-capabilities."""
    section = SkillsSection(SKILLS)
    content = section.build_content()

    # Should mention that skills can contain multiple sections or sub-capabilities
    lower = content.lower()
    assert "section" in lower or "sub-capabilit" in lower or "hierarchi" in lower


def test_usage_instructions_include_workspace_and_home_skill_paths() -> None:
    """Usage instructions should mention both workspace and home skills paths."""
    section = SkillsSection(SKILLS)
    content = section.build_content()

    assert ".agent/skills/" in content
    assert "~/.agent/skills/" in content


# ---------------------------------------------------------------------------
# Organization prompt: hierarchical merging and richer registry
# ---------------------------------------------------------------------------


def test_organization_prompt_describes_hierarchical_merging() -> None:
    """Organization prompt should describe merging into parent skills with sections."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    lower = result.lower()

    # Should mention creating parent skills with sections, not just flat merges
    assert "section" in lower
    assert "parent" in lower or "umbrella" in lower or "broader" in lower


def test_organization_prompt_registry_includes_when_to_read() -> None:
    """Registry format in organization prompt should describe when to read each skill."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    lower = result.lower()

    assert "when to" in lower or "trigger" in lower or "use when" in lower


def test_organization_prompt_registry_includes_sections_listing() -> None:
    """Registry format should describe listing what sections/sub-capabilities a skill contains."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    lower = result.lower()

    # Registry should describe listing sections within skills
    assert "section" in lower
