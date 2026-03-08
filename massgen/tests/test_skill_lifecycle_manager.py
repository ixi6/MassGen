"""Tests for analysis skill lifecycle create/update behaviors."""

from pathlib import Path

from massgen.filesystem_manager.skills_manager import (
    apply_analysis_skill_lifecycle,
    parse_frontmatter,
)


def _write_skill(
    skill_dir: Path,
    *,
    name: str,
    description: str,
    body: str,
    extra_meta: dict | None = None,
) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "name": name,
        "description": description,
    }
    if extra_meta:
        metadata.update(extra_meta)

    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", body])
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_create_or_update_merges_same_directory(tmp_path: Path) -> None:
    """create_or_update should merge when the same directory name already exists."""
    project_skills = tmp_path / ".agent" / "skills"
    existing = project_skills / "poem-workflow"
    source = tmp_path / "source" / "poem-workflow"

    _write_skill(
        existing,
        name="poem-writing",
        description="Write poems with constraints and rhyme",
        body="# Poem Writing\nUse iterative drafting.",
    )
    _write_skill(
        source,
        name="poem-writer",
        description="Workflow for writing constrained poems",
        body="# Poem Writer\nDraft then refine with meter checks.",
        extra_meta={"massgen_origin": "log_1::turn_1", "evolving": True},
    )

    result = apply_analysis_skill_lifecycle(
        source,
        project_skills,
        lifecycle_mode="create_or_update",
    )

    assert result["action"] == "updated"
    assert result["target"] == str(existing)

    updated_content = (existing / "SKILL.md").read_text(encoding="utf-8")
    updated_meta = parse_frontmatter(updated_content)
    assert "Evolving Updates" in updated_content
    assert updated_meta.get("evolving") is True


def test_create_or_update_without_similarity_matching(tmp_path: Path) -> None:
    """create_or_update should NOT match by similarity — only by directory name.

    When the source directory name differs from all existing project skill
    directories, a new skill should be created even if names are very similar.
    """
    project_skills = tmp_path / ".agent" / "skills"
    existing = project_skills / "poem-writing"
    source = tmp_path / "source" / "poem-workflow"

    _write_skill(
        existing,
        name="poem-writing",
        description="Write poems with constraints and rhyme",
        body="# Poem Writing\nUse iterative drafting.",
    )
    _write_skill(
        source,
        name="poem-writer",
        description="Workflow for writing constrained poems",
        body="# Poem Writer\nDraft then refine with meter checks.",
        extra_meta={"massgen_origin": "log_1::turn_1", "evolving": True},
    )

    result = apply_analysis_skill_lifecycle(
        source,
        project_skills,
        lifecycle_mode="create_or_update",
    )

    # Should create new since directory names differ — no similarity matching
    assert result["action"] == "created"
    assert (project_skills / "poem-workflow" / "SKILL.md").exists()

    # Original should remain unchanged
    existing_content = (existing / "SKILL.md").read_text(encoding="utf-8")
    assert "Evolving Updates" not in existing_content


def test_create_new_keeps_existing_skill_and_creates_new_dir(tmp_path: Path) -> None:
    """create_new should always create a new project skill directory when possible."""
    project_skills = tmp_path / ".agent" / "skills"
    existing = project_skills / "poem-writing"
    source = tmp_path / "source" / "poem-workflow"

    _write_skill(
        existing,
        name="poem-writing",
        description="Write poems with constraints and rhyme",
        body="# Poem Writing\nUse iterative drafting.",
    )
    _write_skill(
        source,
        name="poem-writer",
        description="Workflow for writing constrained poems",
        body="# Poem Writer\nDraft then refine with meter checks.",
    )

    result = apply_analysis_skill_lifecycle(
        source,
        project_skills,
        lifecycle_mode="create_new",
    )

    assert result["action"] == "created"
    assert (project_skills / "poem-workflow" / "SKILL.md").exists()
    existing_content = (existing / "SKILL.md").read_text(encoding="utf-8")
    assert "Evolving Updates" not in existing_content


def test_consolidate_mode_normalizes_to_create_or_update(tmp_path: Path) -> None:
    """Removed 'consolidate' mode should fall back to 'create_or_update'."""
    from massgen.filesystem_manager.skills_manager import normalize_skill_lifecycle_mode

    assert normalize_skill_lifecycle_mode("consolidate") == "create_or_update"
