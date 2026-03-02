"""Tests for specialized subagent types (skills-like discovery)."""

from pathlib import Path

import pytest

# ── Test 1-3: SpecializedSubagentConfig dataclass ──


def test_config_creation():
    """SpecializedSubagentConfig stores all fields correctly."""
    from massgen.subagent.models import SpecializedSubagentConfig

    config = SpecializedSubagentConfig(
        name="evaluator",
        description="Runs deliverables and checks features",
        system_prompt="You are an evaluator.",
        skills=["webapp-testing", "agent-browser"],
        expected_input=["objective", "setup", "commands"],
        source_path="/path/to/SUBAGENT.md",
    )
    assert config.name == "evaluator"
    assert config.description == "Runs deliverables and checks features"
    assert config.system_prompt == "You are an evaluator."
    assert config.skills == ["webapp-testing", "agent-browser"]
    assert config.expected_input == ["objective", "setup", "commands"]
    assert config.source_path == "/path/to/SUBAGENT.md"


def test_config_defaults():
    """SpecializedSubagentConfig has correct defaults."""
    from massgen.subagent.models import SpecializedSubagentConfig

    config = SpecializedSubagentConfig(
        name="test",
        description="test type",
    )
    assert config.system_prompt == ""
    assert config.skills == []
    assert config.expected_input == []
    assert config.source_path == ""


def test_config_roundtrip():
    """to_dict → from_dict preserves all fields including skills."""
    from massgen.subagent.models import SpecializedSubagentConfig

    original = SpecializedSubagentConfig(
        name="evaluator",
        description="Checks features",
        system_prompt="You are an evaluator.\nBe thorough.",
        skills=["webapp-testing", "agent-browser"],
        expected_input=["objective", "setup", "commands"],
        source_path="/path/to/SUBAGENT.md",
    )
    data = original.to_dict()
    restored = SpecializedSubagentConfig.from_dict(data)
    assert restored.name == original.name
    assert restored.description == original.description
    assert restored.system_prompt == original.system_prompt
    assert restored.skills == original.skills
    assert restored.expected_input == original.expected_input
    assert restored.source_path == original.source_path


# ── Test 4-8: Scanner ──


def test_scanner_finds_builtin_types():
    """Scanner discovers evaluator + explorer + researcher from massgen/subagent_types/."""
    from massgen.subagent.type_scanner import scan_subagent_types

    # Use the real built-in directory
    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    names = {t.name for t in types}
    assert "evaluator" in names
    assert "explorer" in names
    assert "researcher" in names


def test_scanner_parses_frontmatter():
    """Name, description, skills, expected_input extracted from SUBAGENT.md frontmatter."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    assert evaluator.description  # non-empty description
    assert isinstance(evaluator.skills, list)
    assert isinstance(evaluator.expected_input, list)


def test_builtin_descriptions_include_when_to_use():
    """Each built-in description should include explicit when-to-use guidance."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    for name in ("evaluator", "explorer", "researcher"):
        config = next(t for t in types if t.name == name)
        assert "when to use" in config.description.lower()


def test_builtin_profiles_define_expected_input():
    """Each built-in should define an expected_input checklist in frontmatter."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    for name in ("evaluator", "explorer", "researcher"):
        config = next(t for t in types if t.name == name)
        assert len(config.expected_input) >= 3
        assert all(isinstance(item, str) and item.strip() for item in config.expected_input)


def test_evaluator_description_targets_programmatic_execution():
    """Evaluator description should signal run-heavy procedural verification use cases."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    lower = evaluator.description.lower()
    assert "programmatic" in lower or "procedural" in lower
    assert "test" in lower or "execute" in lower or "run" in lower


def test_scanner_body_is_system_prompt():
    """Markdown body (after frontmatter) becomes system_prompt."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    # System prompt should contain meaningful content
    assert len(evaluator.system_prompt) > 50
    # Should not contain the frontmatter markers
    assert "---" not in evaluator.system_prompt[:10]


def test_evaluator_prompt_allows_optional_suggestions():
    """Evaluator prompt may include suggestions, but keeps decision ownership with main agent."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    lower = evaluator.system_prompt.lower()
    assert "may include suggestions" in lower
    assert "main agent" in lower
    assert "decid" in lower or "judg" in lower


def test_evaluator_has_skills():
    """Evaluator type includes webapp-testing + agent-browser skills."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    assert "webapp-testing" in evaluator.skills
    assert "agent-browser" in evaluator.skills


def test_explorer_has_skills():
    """Explorer type includes file-search + semtools skills."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    explorer = next(t for t in types if t.name == "explorer")
    assert "file-search" in explorer.skills
    assert "semtools" in explorer.skills


def test_researcher_description_targets_external_research():
    """Researcher description should emphasize external-source research behavior."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    researcher = next(t for t in types if t.name == "researcher")
    lower = researcher.description.lower()
    assert "research" in lower
    assert "external" in lower or "source" in lower or "web" in lower


def test_builtin_prompts_include_actionable_sections():
    """Built-in prompts should include explicit structure and usage guidance."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))

    for name in ("evaluator", "explorer", "researcher"):
        config = next(t for t in types if t.name == name)
        prompt = config.system_prompt.lower()
        assert len(prompt) > 400
        assert "when to use" in prompt
        assert "deliverable" in prompt or "output format" in prompt
        assert "do not" in prompt


def test_scanner_project_overrides_builtin(tmp_path):
    """Project type with same name replaces built-in."""
    from massgen.subagent.type_scanner import scan_subagent_types

    # Create a project-level evaluator override
    project_dir = tmp_path / "subagent_types"
    eval_dir = project_dir / "evaluator"
    eval_dir.mkdir(parents=True)
    (eval_dir / "SUBAGENT.md").write_text(
        "---\nname: evaluator\ndescription: Custom evaluator\n---\nCustom system prompt.",
    )

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=project_dir)
    evaluator = next(t for t in types if t.name == "evaluator")
    assert evaluator.description == "Custom evaluator"
    assert evaluator.system_prompt.strip() == "Custom system prompt."


def test_scanner_empty_dir(tmp_path):
    """Empty/missing dir returns empty list."""
    from massgen.subagent.type_scanner import scan_subagent_types

    types = scan_subagent_types(
        builtin_dir=tmp_path / "nonexistent",
        project_dir=tmp_path / "also_nonexistent",
    )
    assert types == []


def test_scanner_rejects_unsupported_frontmatter_fields(tmp_path):
    """Legacy fields in SUBAGENT frontmatter should fail validation."""
    from massgen.subagent.type_scanner import scan_subagent_types

    project_dir = tmp_path / "subagent_types"
    bad_dir = project_dir / "custom_eval"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SUBAGENT.md").write_text(
        "---\nname: custom_eval\ndescription: Custom evaluator\ndefault_background: true\n---\nPrompt text.",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported specialized subagent frontmatter fields"):
        scan_subagent_types(
            builtin_dir=tmp_path / "nonexistent",
            project_dir=project_dir,
        )


def test_scanner_excludes_template_directory_from_discovery(tmp_path):
    """A `_template` profile directory should be ignored by scanner discovery."""
    from massgen.subagent.type_scanner import scan_subagent_types

    project_dir = tmp_path / "subagent_types"
    template_dir = project_dir / "_template"
    template_dir.mkdir(parents=True)
    (template_dir / "SUBAGENT.md").write_text(
        "---\nname: template\ndescription: Template profile\n---\nTemplate body.",
        encoding="utf-8",
    )

    types = scan_subagent_types(
        builtin_dir=tmp_path / "nonexistent",
        project_dir=project_dir,
    )
    assert types == []


# ── Scanner: allowed_types filtering ──


def test_scanner_filter_excludes_novelty():
    """When allowed_types excludes novelty, novelty is not returned."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(
        builtin_dir=builtin_dir,
        project_dir=Path("/nonexistent"),
        allowed_types=["evaluator", "explorer", "researcher"],
    )
    names = {t.name for t in types}
    assert "novelty" not in names
    assert "evaluator" in names


def test_scanner_filter_includes_novelty_when_requested():
    """When allowed_types includes novelty, novelty is returned."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(
        builtin_dir=builtin_dir,
        project_dir=Path("/nonexistent"),
        allowed_types=["evaluator", "novelty"],
    )
    names = {t.name for t in types}
    assert "novelty" in names
    assert "evaluator" in names
    assert "researcher" not in names


def test_scanner_filter_none_returns_all():
    """When allowed_types is None, all types returned (backward compat)."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(
        builtin_dir=builtin_dir,
        project_dir=Path("/nonexistent"),
        allowed_types=None,
    )
    names = {t.name for t in types}
    assert "evaluator" in names
    assert "novelty" in names


def test_scanner_filter_unknown_type_warns(caplog):
    """Unknown type names in allowed_types produce warnings."""
    import logging

    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    with caplog.at_level(logging.WARNING):
        types = scan_subagent_types(
            builtin_dir=builtin_dir,
            project_dir=Path("/nonexistent"),
            allowed_types=["evaluator", "nonexistent_type"],
        )
    names = {t.name for t in types}
    assert "evaluator" in names
    assert "nonexistent_type" not in names
    assert "nonexistent_type" in caplog.text


def test_scanner_filter_empty_list_returns_nothing():
    """Empty allowed_types list means no types exposed."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(
        builtin_dir=builtin_dir,
        project_dir=Path("/nonexistent"),
        allowed_types=[],
    )
    assert types == []


def test_default_subagent_types_constant():
    """DEFAULT_SUBAGENT_TYPES exists and excludes novelty."""
    from massgen.subagent.type_scanner import DEFAULT_SUBAGENT_TYPES

    assert "evaluator" in DEFAULT_SUBAGENT_TYPES
    assert "explorer" in DEFAULT_SUBAGENT_TYPES
    assert "researcher" in DEFAULT_SUBAGENT_TYPES
    assert "novelty" not in DEFAULT_SUBAGENT_TYPES


# ── Test 9-12: SubagentSection with specialized types ──


def test_subagent_section_lists_attached_types():
    """Output contains 'ATTACHED' and type names when types are provided."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
        SpecializedSubagentConfig(name="explorer", description="Research agent"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content()
    assert "ATTACHED" in content.upper()
    assert "evaluator" in content
    assert "explorer" in content


def test_subagent_section_prioritizes_over_inline():
    """Output says 'instead of doing the work yourself' when types present."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content()
    assert "instead of doing the work yourself" in content.lower()


def test_subagent_section_shows_subagent_type_usage():
    """Output shows subagent_type in spawn example."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content()
    assert "subagent_type" in content
    assert "context_paths" in content


def test_subagent_section_without_types_unchanged():
    """No types → existing behavior (no ATTACHED section)."""
    from massgen.system_prompt_sections import SubagentSection

    section = SubagentSection("/workspace", max_concurrent=3)
    content = section.build_content()
    # Should still have the basic subagent delegation content
    assert "Subagent Delegation" in content
    # But not the attached types section
    assert "ATTACHED" not in content.upper()


def test_subagent_section_includes_specialized_task_brief_template():
    """Specialized section should teach parent agents how to write high-quality task briefs."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content().lower()

    assert "when writing a `task` for specialized subagents" in content
    assert "expected input for each specialized type" in content
    assert "objective" in content
    assert "setup" in content
    assert "commands to run" in content
    assert "expected output format" in content
    assert "constraints" in content


def test_subagent_section_includes_evaluator_task_brief_details():
    """Evaluator delegation guidance should require explicit procedural details in task briefs."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content().lower()

    assert "for `evaluator` tasks, explicitly include" in content
    assert "what to run" in content
    assert "how to set it up" in content
    assert "exact commands" in content
    assert "what evidence to capture" in content
    assert "pass/fail format" in content


def test_subagent_section_includes_builder_novelty_delegation_guidance():
    """Builder section must tell agents to list novelty proposals as transformative, not defer them."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="builder", description="Implements transformative changes"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content().lower()

    # Must tell agents that novelty proposals too complex for inline → list as transformative
    assert "novelty" in content
    assert "transformative" in content
    # Must steer agents away from deferring
    assert "defer" in content or "inline" in content


def test_subagent_section_builder_guidance_not_shown_without_builder():
    """Builder-specific guidance should not appear when builder is not in subagent types."""
    from massgen.subagent.models import SpecializedSubagentConfig
    from massgen.system_prompt_sections import SubagentSection

    types = [
        SpecializedSubagentConfig(name="evaluator", description="Checks features"),
    ]
    section = SubagentSection("/workspace", max_concurrent=3, specialized_subagents=types)
    content = section.build_content()

    # Builder delegation guidance should not appear when builder is absent
    assert "for `builder` tasks" not in content.lower()


# ── Test 13-15: EvaluationSection with evaluator subagent ──


def test_evaluation_no_evaluator():
    """Checklist gating should not include mandatory evaluator directives."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
    )
    content = section.build_content()
    assert "Mandatory Evaluator Check" not in content


def test_evaluation_with_evaluator():
    """Checklist gating output remains non-mandatory regardless of profile availability."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
    )
    content = section.build_content()
    assert "Mandatory Evaluator Check" not in content


def test_evaluation_evaluator_says_dont_do_yourself():
    """No mandatory evaluator directive should be injected in checklist section."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
    )
    content = section.build_content()
    assert "Mandatory Evaluator Check" not in content


def test_evaluation_evaluator_directive_keeps_main_agent_decision_authority():
    """Checklist gating instructions still remain present when evaluator exists."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
    )
    content = section.build_content().lower()
    assert "submit_checklist" in content


# ── SubagentSection timeout in system prompt ──


def test_subagent_section_includes_timeout_seconds_in_prompt():
    """SubagentSection with explicit default_timeout should mention the value in seconds."""
    from massgen.system_prompt_sections import SubagentSection

    section = SubagentSection("/workspace", max_concurrent=3, default_timeout=600)
    content = section.build_content()
    assert "600 seconds" in content or "600" in content


def test_subagent_section_includes_timeout_minutes_in_prompt():
    """SubagentSection with default_timeout=600 should mention 10 minutes."""
    from massgen.system_prompt_sections import SubagentSection

    section = SubagentSection("/workspace", max_concurrent=3, default_timeout=600)
    content = section.build_content()
    assert "10 minutes" in content


def test_subagent_section_default_timeout_is_300():
    """SubagentSection with no default_timeout arg should use 300 seconds / 5 minutes."""
    from massgen.system_prompt_sections import SubagentSection

    section = SubagentSection("/workspace", max_concurrent=3)
    content = section.build_content()
    assert "300 seconds" in content or "5 minutes" in content


def test_subagent_section_list_subagents_description_mentions_timeout_fields():
    """list_subagents() description in prompt should mention elapsed/timeout/remaining fields."""
    from massgen.system_prompt_sections import SubagentSection

    section = SubagentSection("/workspace", max_concurrent=3)
    content = section.build_content()
    assert "elapsed_seconds" in content
    assert "seconds_remaining" in content
