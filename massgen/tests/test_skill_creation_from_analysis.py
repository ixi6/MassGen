"""Tests for the redesigned skill-creation-from-analysis workflow.

Covers:
- _load_skill_creator_reference() helper and fallback
- Prompt content for user profile
- _snapshot_skill_dirs() directory scanning
- AnalysisConfig._pre_analysis_skill_dirs default
"""

from pathlib import Path

from massgen.cli import _load_skill_creator_reference, get_log_analysis_prompt_prefix
from massgen.frontend.displays.tui_modes import AnalysisConfig

# ---------------------------------------------------------------------------
# _load_skill_creator_reference
# ---------------------------------------------------------------------------


def test_load_skill_creator_reference(tmp_path, monkeypatch):
    """When the skill-creator SKILL.md exists, its content is returned."""
    skill_dir = tmp_path / ".agent" / "skills" / "skill-creator"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    content = "---\nname: skill-creator\ndescription: Guide\n---\n# Skill Creator\n"
    skill_file.write_text(content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = _load_skill_creator_reference()
    assert "skill-creator" in result
    assert "# Skill Creator" in result


def test_load_skill_creator_reference_fallback(tmp_path, monkeypatch):
    """When the file is missing, a minimal fallback is returned."""
    monkeypatch.chdir(tmp_path)
    result = _load_skill_creator_reference()
    assert "name:" in result
    assert "description:" in result


# ---------------------------------------------------------------------------
# Prompt content checks
# ---------------------------------------------------------------------------


def test_prompt_contains_skill_format_reference(tmp_path, monkeypatch):
    """User profile prompt includes skill-creator reference content."""
    skill_dir = tmp_path / ".agent" / "skills" / "skill-creator"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-creator\ndescription: Guide\n---\n# Skill Creator\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    prompt = get_log_analysis_prompt_prefix(log_dir=None, turn=None, profile="user")
    assert "skill-creator-reference" in prompt
    assert "# Skill Creator" in prompt


def test_prompt_no_regex_instruction(tmp_path, monkeypatch):
    """User profile prompt does NOT contain the old fenced-block instruction."""
    monkeypatch.chdir(tmp_path)
    prompt = get_log_analysis_prompt_prefix(log_dir=None, turn=None, profile="user")
    assert "fenced markdown block" not in prompt


def test_prompt_mentions_default_create_or_update_lifecycle(tmp_path, monkeypatch):
    """User profile prompt should describe create_or_update lifecycle behavior."""
    monkeypatch.chdir(tmp_path)
    prompt = get_log_analysis_prompt_prefix(log_dir=None, turn=None, profile="user")
    assert "create_or_update" in prompt


def test_prompt_consolidation_mode_falls_back(tmp_path, monkeypatch):
    """Removed 'consolidate' mode should fall back to create_or_update behavior."""
    monkeypatch.chdir(tmp_path)
    prompt = get_log_analysis_prompt_prefix(
        log_dir=None,
        turn=None,
        profile="user",
        skill_lifecycle_mode="consolidate",
    )
    # consolidate is no longer a valid mode; should get create_or_update instructions
    assert "create_or_update" in prompt


# ---------------------------------------------------------------------------
# _snapshot_skill_dirs
# ---------------------------------------------------------------------------


def _snapshot_skill_dirs() -> set:
    """Standalone reimplementation matching TextualApp._snapshot_skill_dirs for testing."""
    skills_root = Path(".agent") / "skills"
    if not skills_root.is_dir():
        return set()
    return {d.name for d in skills_root.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()}


def test_snapshot_skill_dirs_empty(tmp_path, monkeypatch):
    """Returns empty set when .agent/skills/ does not exist."""
    monkeypatch.chdir(tmp_path)
    result = _snapshot_skill_dirs()
    assert result == set()


def test_snapshot_skill_dirs_with_skills(tmp_path, monkeypatch):
    """Correctly captures existing skill dirs that contain SKILL.md."""
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / ".agent" / "skills"

    # Valid skill directory with SKILL.md
    valid = skills_root / "my-skill"
    valid.mkdir(parents=True)
    (valid / "SKILL.md").write_text("---\nname: my-skill\n---\n", encoding="utf-8")

    # Another valid skill
    valid2 = skills_root / "other-skill"
    valid2.mkdir(parents=True)
    (valid2 / "SKILL.md").write_text("---\nname: other\n---\n", encoding="utf-8")

    # Directory without SKILL.md — should NOT appear
    no_skill = skills_root / "empty-dir"
    no_skill.mkdir(parents=True)

    result = _snapshot_skill_dirs()
    assert result == {"my-skill", "other-skill"}


# ---------------------------------------------------------------------------
# AnalysisConfig snapshot field default
# ---------------------------------------------------------------------------


def test_analysis_config_snapshot_field_default():
    """_pre_analysis_skill_dirs defaults to None."""
    config = AnalysisConfig()
    assert config._pre_analysis_skill_dirs is None
    assert config.include_previous_session_skills is False
    assert config.skill_lifecycle_mode == "create_or_update"
