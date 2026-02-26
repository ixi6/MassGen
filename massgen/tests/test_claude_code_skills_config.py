"""Tests for Claude Code skill discovery configuration.

The Skill tool is disabled (weaker models misuse it), but skill files are
still synced to .agent/skills/ so agents can read them directly via filesystem
tools.  A .claude/skills symlink points to .agent/skills/ for compatibility.
"""

from pathlib import Path
from types import SimpleNamespace

from massgen.backend.claude_code import ClaudeCodeBackend


def _build_filesystem_manager_stub(workspace: Path, local_skills_directory: Path) -> SimpleNamespace:
    return SimpleNamespace(
        local_skills_directory=local_skills_directory,
        docker_manager=None,
        agent_id="agent_a",
        get_current_workspace=lambda: workspace,
        get_claude_code_hooks_config=lambda: {},
        path_permission_manager=SimpleNamespace(get_writable_paths=lambda: [str(workspace)]),
    )


def test_skill_tool_is_disallowed(tmp_path: Path):
    """Skill tool should be in the disallowed list."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    assert "Skill" in backend.get_disallowed_tools({})


def test_skill_tool_not_in_builtin_tools(tmp_path: Path):
    """Skill should not appear in the supported builtin tools list."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    assert "Skill" not in backend.get_supported_builtin_tools()
    assert "Skill" not in backend.get_supported_builtin_tools(enable_web_search=True)


def test_skills_synced_to_agent_dir(tmp_path: Path):
    """Skills are copied to .agent/skills/ even with Skill tool disabled."""
    # Source skills outside the workspace
    source_skills = tmp_path / "source_skills"
    demo = source_skills / "demo-skill"
    demo.mkdir(parents=True)
    (demo / "SKILL.md").write_text("# Demo Skill\n")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    backend = ClaudeCodeBackend(cwd=str(workspace))
    backend.filesystem_manager = _build_filesystem_manager_stub(workspace, source_skills)
    options = backend._build_claude_options()

    # Skills copied to .agent/skills/
    agent_skill = workspace / ".agent" / "skills" / "demo-skill" / "SKILL.md"
    assert agent_skill.exists()
    assert agent_skill.read_text() == "# Demo Skill\n"

    # .claude/skills is a symlink to .agent/skills
    claude_skills = workspace / ".claude" / "skills"
    assert claude_skills.is_symlink()
    assert claude_skills.resolve() == (workspace / ".agent" / "skills").resolve()

    # Settings still isolated (Skill tool is off)
    assert list(options.setting_sources) == []


def test_settings_disabled_with_skill_tool_off(tmp_path: Path):
    """With Skill disabled, setting_sources should be empty (isolated mode)."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))

    project_skills = tmp_path / ".agent" / "skills"
    project_skill = project_skills / "demo-skill"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text("# Demo Skill\n")

    backend.filesystem_manager = _build_filesystem_manager_stub(tmp_path, project_skills)
    options = backend._build_claude_options()

    assert list(options.setting_sources) == []


# ── Reasoning / thinking config tests ──────────────────────────────────────


def _build_options_with_kwargs(tmp_path: Path, **kwargs):
    """Helper: build ClaudeAgentOptions with given backend kwargs."""
    backend = ClaudeCodeBackend(cwd=str(tmp_path))
    skills_dir = tmp_path / ".agent" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    backend.filesystem_manager = _build_filesystem_manager_stub(tmp_path, skills_dir)
    return backend._build_claude_options(**kwargs)


def test_reasoning_adaptive_default_sonnet(tmp_path: Path):
    """Without reasoning config, sonnet defaults to adaptive thinking + medium effort."""
    options = _build_options_with_kwargs(tmp_path, model="claude-sonnet-4-6")
    assert options.thinking == {"type": "adaptive"}
    assert options.effort == "medium"


def test_reasoning_adaptive_default_opus(tmp_path: Path):
    """Without reasoning config, opus defaults to adaptive thinking + high effort."""
    options = _build_options_with_kwargs(tmp_path, model="claude-opus-4-6")
    assert options.thinking == {"type": "adaptive"}
    assert options.effort == "high"


def test_reasoning_explicit_config(tmp_path: Path):
    """Explicit reasoning config with type=disabled overrides default."""
    options = _build_options_with_kwargs(
        tmp_path,
        reasoning={"type": "disabled"},
    )
    assert options.thinking == {"type": "disabled"}


def test_reasoning_effort_override(tmp_path: Path):
    """Reasoning config can override effort level."""
    options = _build_options_with_kwargs(
        tmp_path,
        reasoning={"type": "adaptive", "effort": "max"},
    )
    assert options.thinking == {"type": "adaptive"}
    assert options.effort == "max"


def test_max_thinking_tokens_backward_compat(tmp_path: Path):
    """Legacy max_thinking_tokens maps to thinking type=enabled."""
    options = _build_options_with_kwargs(tmp_path, max_thinking_tokens=8000)
    assert options.thinking == {"type": "enabled", "budget_tokens": 8000}


def test_no_env_var_workaround(tmp_path: Path):
    """MAX_THINKING_TOKENS should NOT appear in env dict (old workaround removed)."""
    options = _build_options_with_kwargs(tmp_path, max_thinking_tokens=10000)
    assert "MAX_THINKING_TOKENS" not in options.env
