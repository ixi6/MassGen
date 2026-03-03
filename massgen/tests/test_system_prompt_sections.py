"""Tests for agent identity isolation in system prompt sections."""

from massgen.system_prompt_sections import FilesystemOperationsSection


def test_workspace_tree_hides_real_agent_id():
    """Shared reference path should not contain real agent_id."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/token_abc123",
        temp_workspace="/tmp/token_abc123",
        agent_answers={"agent_a": "answer"},
        agent_mapping={"agent_a": "agent1"},
    )
    content = section.build_content()
    assert "agent_a" not in content


def test_hardcoded_examples_do_not_reference_workspace_agent_labels():
    """Example text about 'building on others work' should not say agent1's/agent2's."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/abc",
        temp_workspace="/tmp/abc",
        agent_answers={"agent_a": "x", "agent_b": "y"},
        agent_mapping={"agent_a": "agent1", "agent_b": "agent2"},
    )
    content = section.build_content()
    # Should not have "agent1's" or "agent2's" in the building-on-others section
    assert "agent1's" not in content
    assert "agent2's" not in content
