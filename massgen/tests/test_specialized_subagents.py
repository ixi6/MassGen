# -*- coding: utf-8 -*-
"""Tests for specialized subagent types (skills-like discovery)."""

from pathlib import Path

# ── Test 1-3: SpecializedSubagentConfig dataclass ──


def test_config_creation():
    """SpecializedSubagentConfig stores all fields correctly."""
    from massgen.subagent.models import SpecializedSubagentConfig

    config = SpecializedSubagentConfig(
        name="evaluator",
        description="Runs deliverables and checks features",
        system_prompt="You are an evaluator.",
        default_background=True,
        default_refine=False,
        skills=["webapp-testing", "agent-browser"],
        mcp_servers=["browser"],
        source_path="/path/to/SUBAGENT.md",
    )
    assert config.name == "evaluator"
    assert config.description == "Runs deliverables and checks features"
    assert config.system_prompt == "You are an evaluator."
    assert config.default_background is True
    assert config.default_refine is False
    assert config.skills == ["webapp-testing", "agent-browser"]
    assert config.mcp_servers == ["browser"]
    assert config.source_path == "/path/to/SUBAGENT.md"


def test_config_defaults():
    """SpecializedSubagentConfig has correct defaults."""
    from massgen.subagent.models import SpecializedSubagentConfig

    config = SpecializedSubagentConfig(
        name="test",
        description="test type",
    )
    assert config.default_background is False
    assert config.default_refine is False
    assert config.system_prompt == ""
    assert config.skills == []
    assert config.mcp_servers == []
    assert config.source_path == ""


def test_config_roundtrip():
    """to_dict → from_dict preserves all fields including skills."""
    from massgen.subagent.models import SpecializedSubagentConfig

    original = SpecializedSubagentConfig(
        name="evaluator",
        description="Checks features",
        system_prompt="You are an evaluator.\nBe thorough.",
        default_background=True,
        default_refine=False,
        skills=["webapp-testing", "agent-browser"],
        mcp_servers=["browser"],
        source_path="/path/to/SUBAGENT.md",
    )
    data = original.to_dict()
    restored = SpecializedSubagentConfig.from_dict(data)
    assert restored.name == original.name
    assert restored.description == original.description
    assert restored.system_prompt == original.system_prompt
    assert restored.default_background == original.default_background
    assert restored.default_refine == original.default_refine
    assert restored.skills == original.skills
    assert restored.mcp_servers == original.mcp_servers
    assert restored.source_path == original.source_path


# ── Test 4-8: Scanner ──


def test_scanner_finds_builtin_types():
    """Scanner discovers evaluator + explorer from massgen/subagent_types/."""
    from massgen.subagent.type_scanner import scan_subagent_types

    # Use the real built-in directory
    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    names = {t.name for t in types}
    assert "evaluator" in names
    assert "explorer" in names


def test_scanner_parses_frontmatter():
    """Name, description, defaults, skills extracted from SUBAGENT.md frontmatter."""
    from massgen.subagent.type_scanner import scan_subagent_types

    builtin_dir = Path(__file__).parent.parent / "subagent_types"
    types = scan_subagent_types(builtin_dir=builtin_dir, project_dir=Path("/nonexistent"))
    evaluator = next(t for t in types if t.name == "evaluator")
    assert evaluator.description  # non-empty description
    assert isinstance(evaluator.default_background, bool)
    assert isinstance(evaluator.default_refine, bool)


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


# ── Test 13-15: EvaluationSection with evaluator subagent ──


def test_evaluation_no_evaluator():
    """Without evaluator, no mandatory directive."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
        has_evaluator_subagent=False,
    )
    content = section.build_content()
    assert "Mandatory Evaluator Check" not in content


def test_evaluation_with_evaluator():
    """With evaluator, mandatory directive is present."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
        has_evaluator_subagent=True,
    )
    content = section.build_content()
    assert "Mandatory Evaluator Check" in content


def test_evaluation_evaluator_says_dont_do_yourself():
    """Evaluator directive says NOT to serve/test yourself."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
        has_evaluator_subagent=True,
    )
    content = section.build_content()
    # Should tell agent NOT to do evaluation work inline
    assert "do not" in content.lower() or "don't" in content.lower() or "NOT" in content
    assert "evaluator" in content.lower()


def test_evaluation_evaluator_directive_keeps_main_agent_decision_authority():
    """Evaluator directive can accept suggestions but must keep final judgment with main agent."""
    from massgen.system_prompt_sections import EvaluationSection

    section = EvaluationSection(
        voting_sensitivity="checklist_gated",
        has_evaluator_subagent=True,
    )
    content = section.build_content().lower()
    assert "suggest" in content
    assert "your judgment" in content or "you decide" in content or "you remain responsible" in content
