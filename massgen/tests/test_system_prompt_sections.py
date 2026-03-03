"""Tests for agent identity isolation in system prompt sections."""

from massgen.system_prompt_sections import (
    _CHECKLIST_ITEMS,
    FilesystemBestPracticesSection,
    FilesystemOperationsSection,
    TaskPlanningSection,
    _build_checklist_analysis,
    _build_checklist_gated_decision,
)


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


def test_checklist_analysis_includes_visual_comparison_guidance():
    """Cross-answer synthesis should instruct agents to compare visual outputs
    with read_media using named multi-image inputs rather than text summaries."""
    content = _build_checklist_analysis()
    assert "read_media" in content
    assert "visual" in content.lower()
    # Must reference the multi-image files dict pattern
    assert '"files"' in content


def test_checklist_gated_decision_evaluator_guidance_includes_visual_comparison():
    """Evaluator spawn guidance in gated checklist should instruct passing all
    agents' images in one read_media call for grounded cross-agent comparison."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "read_media" in content
    assert "visual" in content.lower()


def test_checklist_gated_decision_includes_peer_build_copy_guidance():
    """Checklist workflow should explain how to evaluate peer build outputs
    without mutating read-only shared snapshots."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "temp_workspaces" in content
    assert ".massgen_scratch/peer_eval/" in content
    assert "npm install" in content


def test_filesystem_best_practices_includes_visual_comparison_guidance():
    """Evaluation bullet in FilesystemBestPracticesSection should guide agents
    to compare peer visual outputs directly rather than from text descriptions."""
    section = FilesystemBestPracticesSection()
    content = section.build_content()
    assert "read_media" in content
    assert "visual" in content.lower()


def test_filesystem_operations_includes_peer_build_copy_guidance():
    """Filesystem operations guidance should instruct copying peer artifacts into
    local scratch before running mutable install/build commands."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/abc",
        temp_workspace="/tmp/abc",
        agent_answers={"agent_a": "x"},
        agent_mapping={"agent_a": "agent1"},
    )
    content = section.build_content()
    assert ".massgen_scratch/peer_eval/" in content
    assert "read-only snapshots" in content
    assert "build in your own workspace copy" in content


def test_task_planning_section_includes_subagent_and_novelty_guidance():
    """Task planning instructions should document delegation metadata and novelty tasks."""
    content = TaskPlanningSection().build_content().lower()
    assert "subagent_name" in content
    assert "subagent_id" in content
    assert "novelty" in content
