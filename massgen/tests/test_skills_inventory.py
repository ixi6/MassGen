"""Tests for skill inventory scanning."""

from pathlib import Path

from massgen.filesystem_manager.skills_manager import scan_skills


def _write_skill(skill_dir: Path, name: str, description: str = "") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_scan_skills_includes_project_user_and_previous(monkeypatch, tmp_path: Path) -> None:
    """scan_skills should include project, user, and previous-session skills."""
    project_skills = tmp_path / ".agent" / "skills"
    user_home = tmp_path / "home"
    user_skills = user_home / ".agent" / "skills"
    logs_dir = tmp_path / ".massgen" / "massgen_logs"

    _write_skill(project_skills / "project-skill", "project-skill", "from project")
    _write_skill(user_skills / "user-skill", "user-skill", "from user home")

    previous_skill = logs_dir / "log_20260209_120000_demo" / "turn_1" / "attempt_1" / "final" / "agent_a" / "workspace" / "tasks" / "evolving_skill"
    _write_skill(previous_skill, "evolving-skill", "from previous session")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))

    scanned = scan_skills(project_skills, logs_dir=logs_dir)
    by_name = {str(skill.get("name")): str(skill.get("location")) for skill in scanned}

    assert by_name["project-skill"] == "project"
    assert by_name["user-skill"] == "user"
    assert by_name["evolving-skill"] == "previous_session"


def test_scan_skills_prefers_project_over_user_for_duplicate_name(monkeypatch, tmp_path: Path) -> None:
    """Duplicate names should resolve to project-first entry for stable filtering."""
    project_skills = tmp_path / ".agent" / "skills"
    user_home = tmp_path / "home"
    user_skills = user_home / ".agent" / "skills"

    _write_skill(project_skills / "shared-skill", "shared-skill", "project variant")
    _write_skill(user_skills / "shared-skill", "shared-skill", "user variant")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))

    scanned = scan_skills(project_skills, include_user_skills=True)
    shared = [skill for skill in scanned if str(skill.get("name")) == "shared-skill"]

    assert len(shared) == 1
    assert shared[0].get("location") == "project"
