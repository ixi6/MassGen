"""Tests for local skills pipeline wiring and previous-session support."""

from pathlib import Path

from massgen.filesystem_manager._filesystem_manager import FilesystemManager


def _build_manager(tmp_path: Path) -> FilesystemManager:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    temp_parent = tmp_path / "temp_workspaces"
    temp_parent.mkdir(parents=True, exist_ok=True)

    return FilesystemManager(
        cwd=str(workspace),
        agent_temporary_workspace_parent=str(temp_parent),
        enable_mcp_command_line=True,
        command_line_execution_mode="local",
    )


def _write_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_setup_orchestration_paths_passes_load_previous_flag(monkeypatch, tmp_path: Path) -> None:
    """setup_orchestration_paths should forward load_previous_session_skills to local setup."""
    manager = _build_manager(tmp_path)
    project_skills = tmp_path / ".agent" / "skills"
    project_skills.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _fake_setup_local_skills(
        skills_directory=None,
        massgen_skills=None,
        load_previous_session_skills=False,
    ):
        captured["skills_directory"] = skills_directory
        captured["massgen_skills"] = massgen_skills
        captured["load_previous_session_skills"] = load_previous_session_skills

    monkeypatch.setattr(manager, "setup_local_skills", _fake_setup_local_skills)

    manager.setup_orchestration_paths(
        agent_id="agent_a",
        skills_directory=str(project_skills),
        load_previous_session_skills=True,
    )

    assert captured["skills_directory"] == str(project_skills)
    assert captured["load_previous_session_skills"] is True


def test_setup_local_skills_copies_previous_session_skills(monkeypatch, tmp_path: Path) -> None:
    """Local merged skills directory should include previous-session skills when enabled."""
    project_skills = tmp_path / ".agent" / "skills"
    project_skills.mkdir(parents=True, exist_ok=True)
    _write_skill(project_skills / "project-skill", "project-skill")

    previous_skill_dir = tmp_path / ".massgen" / "massgen_logs" / "log_20260209_130000_demo" / "turn_1" / "attempt_1" / "final" / "agent_a" / "workspace" / "tasks" / "evolving_skill"
    _write_skill(previous_skill_dir, "evolving-local-skill")

    monkeypatch.chdir(tmp_path)
    manager = _build_manager(tmp_path)
    manager.setup_local_skills(
        skills_directory=str(project_skills),
        load_previous_session_skills=True,
    )

    merged = manager.local_skills_directory
    assert merged is not None
    assert (merged / "project-skill" / "SKILL.md").exists()
    assert (merged / "evolving-local-skill" / "SKILL.md").exists()
