"""
Tests for ProjectInstructionsSection - automatic discovery of CLAUDE.md/AGENTS.md files.

Tests the hierarchical discovery algorithm that implements the agents.md standard:
- "Closest file wins" semantics
- CLAUDE.md takes precedence over AGENTS.md
- Walk up directory hierarchy to workspace root
"""

import pytest

from massgen.system_prompt_sections import ProjectInstructionsSection


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with various instruction file scenarios."""
    # Create directory structure
    (tmp_path / "src" / "subdir").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_discovers_claude_md_in_root(temp_workspace):
    """Test that CLAUDE.md in workspace root is discovered."""
    claude_md = temp_workspace / "CLAUDE.md"
    claude_md.write_text("# Project Instructions\n\nUse TDD for all code.")

    context_paths = [{"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert "CLAUDE.md" in content
    assert "Use TDD for all code" in content
    assert "may or may not be relevant" in content  # Softer framing


def test_discovers_agents_md_in_root(temp_workspace):
    """Test that AGENTS.md is discovered when no CLAUDE.md exists."""
    agents_md = temp_workspace / "AGENTS.md"
    agents_md.write_text("# Build Instructions\n\nRun `npm install` before testing.")

    context_paths = [{"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert "AGENTS.md" in content
    assert "npm install" in content


def test_claude_md_takes_precedence_over_agents_md(temp_workspace):
    """Test that CLAUDE.md is preferred when both exist at same level."""
    claude_md = temp_workspace / "CLAUDE.md"
    agents_md = temp_workspace / "AGENTS.md"

    claude_md.write_text("# Claude-specific instructions")
    agents_md.write_text("# Universal instructions")

    context_paths = [{"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Should find CLAUDE.md, not AGENTS.md
    assert "Claude-specific instructions" in content
    assert "Universal instructions" not in content
    assert "CLAUDE.md" in content


def test_closest_file_wins_nested_structure(temp_workspace):
    """Test hierarchical discovery: closest AGENTS.md to context path wins."""
    # Root level AGENTS.md
    root_agents = temp_workspace / "AGENTS.md"
    root_agents.write_text("# Root project instructions")

    # Nested AGENTS.md (closer to src/subdir)
    src_agents = temp_workspace / "src" / "AGENTS.md"
    src_agents.write_text("# Source code specific instructions")

    # Context path is src/subdir - should find src/AGENTS.md (closest)
    context_paths = [{"path": str(temp_workspace / "src" / "subdir")}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert "Source code specific instructions" in content
    assert "Root project instructions" not in content


def test_walks_up_to_find_instruction_file(temp_workspace):
    """Test that discovery walks up from nested path to root."""
    # Only root level instruction file
    root_claude = temp_workspace / "CLAUDE.md"
    root_claude.write_text("# Project-level instructions")

    # Context path is deeply nested - should walk up and find root CLAUDE.md
    context_paths = [{"path": str(temp_workspace / "src" / "subdir")}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert "Project-level instructions" in content
    assert "CLAUDE.md" in content


def test_explicit_file_reference(temp_workspace):
    """Test that explicitly referencing CLAUDE.md as context path works."""
    claude_md = temp_workspace / "docs" / "CLAUDE.md"
    claude_md.write_text("# Explicit reference test")

    # Context path IS the file itself
    context_paths = [{"path": str(claude_md)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert "Explicit reference test" in content


def test_no_instructions_returns_empty(temp_workspace):
    """Test that missing instruction files return empty string."""
    # No CLAUDE.md or AGENTS.md in workspace
    context_paths = [{"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    assert content == ""


def test_multiple_context_paths_deduplicates(temp_workspace):
    """Test that same instruction file found via multiple paths is not duplicated."""
    claude_md = temp_workspace / "CLAUDE.md"
    claude_md.write_text("# Shared instructions")

    # Multiple context paths both resolve to same root CLAUDE.md
    context_paths = [
        {"path": str(temp_workspace / "src")},
        {"path": str(temp_workspace / "tests")},
    ]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Should only include the file once
    assert content.count("Shared instructions") == 1


def test_handles_nonexistent_context_path_gracefully(temp_workspace):
    """Test that nonexistent context paths don't crash."""
    context_paths = [{"path": str(temp_workspace / "nonexistent")}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Should return empty without error
    assert content == ""


def test_handles_unreadable_file_gracefully(temp_workspace):
    """Test that unreadable files are logged and skipped."""
    import os

    claude_md = temp_workspace / "CLAUDE.md"
    claude_md.write_text("# Instructions")

    # Make file unreadable (only on Unix-like systems)
    if hasattr(os, "chmod"):
        os.chmod(claude_md, 0o000)

        try:
            context_paths = [{"path": str(temp_workspace)}]
            section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
            content = section.build_content()

            # Should handle error gracefully and return empty
            assert content == ""
        finally:
            # Restore permissions for cleanup
            os.chmod(claude_md, 0o644)


def test_empty_context_path_dict(temp_workspace):
    """Test that empty context path dicts are skipped."""
    claude_md = temp_workspace / "CLAUDE.md"
    claude_md.write_text("# Instructions")

    # Context path with missing "path" key
    context_paths = [{"permission": "read"}, {"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Should still find the valid path
    assert "Instructions" in content


def test_respects_workspace_root_boundary(tmp_path):
    """Test that discovery stops at workspace root, doesn't walk up further."""
    # Create structure: /parent/workspace/src
    parent = tmp_path / "parent"
    workspace = parent / "workspace"
    src_dir = workspace / "src"
    src_dir.mkdir(parents=True)

    # Put CLAUDE.md in parent (above workspace root)
    parent_claude = parent / "CLAUDE.md"
    parent_claude.write_text("# Parent instructions (should not be found)")

    # Put AGENTS.md in workspace (at root)
    workspace_agents = workspace / "AGENTS.md"
    workspace_agents.write_text("# Workspace instructions")

    # Context path is src, workspace root is workspace
    # Should find workspace/AGENTS.md, NOT parent/CLAUDE.md
    context_paths = [{"path": str(src_dir)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(workspace))
    content = section.build_content()

    assert "Workspace instructions" in content
    assert "Parent instructions" not in content


def test_framing_message_present(temp_workspace):
    """Test that the softer framing message is included."""
    claude_md = temp_workspace / "CLAUDE.md"
    claude_md.write_text("# Instructions")

    context_paths = [{"path": str(temp_workspace)}]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Check for key phrases from the softer framing
    assert "may or may not be relevant" in content
    assert "helpful reference material" in content
    assert "do not feel obligated" in content


def test_multiple_different_instruction_files(temp_workspace):
    """Test that different instruction files from different paths are both included."""
    # CLAUDE.md in src/
    src_claude = temp_workspace / "src" / "CLAUDE.md"
    src_claude.write_text("# Source instructions")

    # AGENTS.md in docs/ (different from src)
    docs_agents = temp_workspace / "docs" / "AGENTS.md"
    docs_agents.write_text("# Documentation instructions")

    # Two context paths pointing to different subtrees
    context_paths = [
        {"path": str(temp_workspace / "src")},
        {"path": str(temp_workspace / "docs")},
    ]
    section = ProjectInstructionsSection(context_paths, workspace_root=str(temp_workspace))
    content = section.build_content()

    # Both should be included
    assert "Source instructions" in content
    assert "Documentation instructions" in content
