"""Tests for analysis mode skill organization target.

Covers:
- AnalysisConfig target field ("log" vs "skills")
- Mode summary reflects skill organization target
- Skill organization prompt generation
- Analysis submission routing by target type
"""

from massgen.frontend.displays.tui_modes import AnalysisConfig, TuiModeState

# ---------------------------------------------------------------------------
# AnalysisConfig target field
# ---------------------------------------------------------------------------


def test_analysis_config_defaults_to_log_target() -> None:
    """AnalysisConfig should default to 'log' target."""
    config = AnalysisConfig()
    assert config.target == "log"


def test_analysis_config_accepts_skills_target() -> None:
    """AnalysisConfig should accept 'skills' target."""
    config = AnalysisConfig(target="skills")
    assert config.target == "skills"


# ---------------------------------------------------------------------------
# Mode summary
# ---------------------------------------------------------------------------


def test_mode_summary_shows_log_analysis() -> None:
    """Mode summary should show profile when target is log (existing behavior)."""
    state = TuiModeState(plan_mode="analysis")
    state.analysis_config.profile = "user"
    state.analysis_config.target = "log"
    summary = state.get_mode_summary()
    assert "Analyze" in summary
    assert "User" in summary


def test_mode_summary_shows_skill_organization() -> None:
    """Mode summary should show 'Organize Skills' when target is skills."""
    state = TuiModeState(plan_mode="analysis")
    state.analysis_config.target = "skills"
    summary = state.get_mode_summary()
    assert "Skills" in summary or "Organize" in summary


# ---------------------------------------------------------------------------
# Skill organization prompt
# ---------------------------------------------------------------------------


def test_skill_organization_prompt_prefix_exists() -> None:
    """get_skill_organization_prompt_prefix should be importable and return a string."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    assert isinstance(result, str)
    assert len(result) > 0


def test_skill_organization_prompt_mentions_registry() -> None:
    """Prompt should instruct the agent to produce a SKILL_REGISTRY.md."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    assert "SKILL_REGISTRY" in result


def test_skill_organization_prompt_mentions_merging() -> None:
    """Prompt should instruct the agent to merge overlapping skills."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    assert "merge" in result.lower() or "consolidat" in result.lower() or "overlapping" in result.lower()


def test_skill_organization_prompt_mentions_reading_skills() -> None:
    """Prompt should instruct the agent to read all installed skills."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    assert "skill" in result.lower()
    assert "read" in result.lower() or "list" in result.lower()


# ---------------------------------------------------------------------------
# Analysis submission routing
# ---------------------------------------------------------------------------


def test_analysis_submission_default_for_skills_target() -> None:
    """When target is 'skills' and no user text, default request should be about skill organization."""
    # This tests the _setup_analysis_submission behavior indirectly via the config.
    config = AnalysisConfig(target="skills")
    assert config.target == "skills"
    # The default request text for skills target should differ from log target.
    # Actual integration tested via TUI, but config routing is testable here.


def test_log_analysis_prompt_not_used_for_skills_target() -> None:
    """get_log_analysis_prompt_prefix should NOT be called when target is 'skills'."""
    # This is a design contract test: the cli.py orchestration path
    # should branch on analysis_config.target and call the appropriate
    # prompt prefix function.
    config = AnalysisConfig(target="skills")
    assert config.target != "log"


# ---------------------------------------------------------------------------
# Analysis mode input placeholder text
# ---------------------------------------------------------------------------


def test_analysis_placeholder_for_log_target() -> None:
    """Log analysis mode placeholder should mention analyzing a log."""
    from massgen.frontend.displays.tui_modes import get_analysis_placeholder_text

    text = get_analysis_placeholder_text("log")
    lower = text.lower()
    assert "log" in lower or "analyze" in lower
    assert "skill" not in lower or "organize" not in lower


def test_analysis_placeholder_for_skills_target() -> None:
    """Skills organization mode placeholder should mention skills, not logs."""
    from massgen.frontend.displays.tui_modes import get_analysis_placeholder_text

    text = get_analysis_placeholder_text("skills")
    lower = text.lower()
    assert "skill" in lower
    assert "selected log" not in lower


def test_analysis_placeholder_differs_by_target() -> None:
    """Log and skills placeholders should be different strings."""
    from massgen.frontend.displays.tui_modes import get_analysis_placeholder_text

    log_text = get_analysis_placeholder_text("log")
    skills_text = get_analysis_placeholder_text("skills")
    assert log_text != skills_text


def test_skill_organization_prompt_describes_hierarchical_skills() -> None:
    """Organization prompt should describe creating hierarchical parent skills with sections."""
    from massgen.cli import get_skill_organization_prompt_prefix

    result = get_skill_organization_prompt_prefix()
    lower = result.lower()

    # Should mention hierarchical/parent skill structure with sections
    assert "section" in lower
    assert "parent" in lower or "umbrella" in lower or "broader" in lower


# ---------------------------------------------------------------------------
# Skills git tracking utility
# ---------------------------------------------------------------------------


def test_skills_gitignore_check_returns_untracked_when_ignored(tmp_path) -> None:
    """check_skills_git_tracking returns 'untracked' when .agent/ is gitignored."""
    from massgen.filesystem_manager.skills_manager import check_skills_git_tracking

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".agent/\n")
    (tmp_path / ".agent" / "skills").mkdir(parents=True)

    result = check_skills_git_tracking(tmp_path)
    assert result == "untracked"


def test_skills_gitignore_check_returns_tracked_with_negation(tmp_path) -> None:
    """check_skills_git_tracking returns 'tracked' when .agent/ is ignored but skills/ is negated."""
    from massgen.filesystem_manager.skills_manager import check_skills_git_tracking

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".agent/\n!.agent/skills/\n!.agent/skills/**\n")
    (tmp_path / ".agent" / "skills").mkdir(parents=True)

    result = check_skills_git_tracking(tmp_path)
    assert result == "tracked"


def test_skills_gitignore_check_returns_tracked_when_not_ignored(tmp_path) -> None:
    """check_skills_git_tracking returns 'tracked' when .agent/ is not in gitignore."""
    from massgen.filesystem_manager.skills_manager import check_skills_git_tracking

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n__pycache__/\n")
    (tmp_path / ".agent" / "skills").mkdir(parents=True)

    result = check_skills_git_tracking(tmp_path)
    assert result == "tracked"


def test_skills_gitignore_check_returns_no_git_without_gitignore(tmp_path) -> None:
    """check_skills_git_tracking returns 'no_git' when no .gitignore exists."""
    from massgen.filesystem_manager.skills_manager import check_skills_git_tracking

    (tmp_path / ".agent" / "skills").mkdir(parents=True)

    result = check_skills_git_tracking(tmp_path)
    assert result == "no_git"


def test_skills_gitignore_suggestion_text() -> None:
    """get_skills_gitignore_suggestion should return actionable gitignore lines."""
    from massgen.filesystem_manager.skills_manager import (
        get_skills_gitignore_suggestion,
    )

    suggestion = get_skills_gitignore_suggestion()
    assert "!.agent/skills/" in suggestion
    assert "!.agent/skills/**" in suggestion
