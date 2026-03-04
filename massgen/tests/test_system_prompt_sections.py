"""Tests for agent identity isolation in system prompt sections."""

from massgen.system_prompt_sections import (
    _CHECKLIST_ITEMS,
    FilesystemBestPracticesSection,
    FilesystemOperationsSection,
    MemorySection,
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


def test_checklist_gated_decision_requires_blocking_evaluator_execution():
    """Checklist gated flow should require blocking evaluator execution before scoring."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    lower = content.lower()
    assert "background=false, refine=false" in lower
    assert "required before scoring" in lower


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


def test_task_planning_section_no_subagents_omits_classification_step():
    """Without subagents, STEP 2 classification block should be absent."""
    content = TaskPlanningSection().build_content()
    assert "Classify Every Task for Delegation" not in content
    assert "Available subagent types" not in content
    # Step numbering should not reference STEP 3/4 when subagents are absent
    assert "STEP 2 — Execute Every Task" in content
    assert "STEP 3 — Include Task Summary" in content


def test_task_planning_section_with_subagents_includes_classification_step():
    """With subagents present, STEP 2 classification block should appear with type names."""
    from types import SimpleNamespace

    fake_types = [
        SimpleNamespace(name="builder"),
        SimpleNamespace(name="evaluator"),
    ]
    content = TaskPlanningSection(specialized_subagents=fake_types).build_content()
    assert "Classify Every Task for Delegation" in content
    assert "Available subagent types" in content
    assert '"builder"' in content
    assert '"evaluator"' in content
    # subagent_name and subagent_id should appear in the classification step
    assert "subagent_name" in content
    assert "subagent_id" in content
    # novelty guidance should appear in the classification step
    assert "novelty" in content.lower()
    # Step numbering should use STEP 3/4 when subagents are present
    assert "STEP 3 — Execute Every Task" in content
    assert "STEP 4 — Include Task Summary" in content


def test_task_planning_section_is_mandatory_for_complex_tasks():
    """Task planning section must state planning is required, not optional."""
    content = TaskPlanningSection().build_content()
    assert "REQUIRED" in content
    assert "propose_improvements" in content


def test_checklist_gated_decision_requires_verification_replay_memory_capture():
    """Phase 5 guidance should require writing a verification replay memo before submit."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "memory/short_term/verification_latest.md" in content
    assert "verification replay" in content.lower()
    assert "**Environment**" in content
    assert "**Pipeline**" in content
    assert "**Artifacts**" in content
    assert "**Freshness**" in content
    assert "Key assertions" not in content
    assert "concrete value extracted" not in content.lower()


def test_memory_section_verification_replay_requirements_drop_output_assertion_rule():
    """Saving Memories guidance should not require concrete output assertions."""
    section = MemorySection(
        memory_config={
            "short_term": {"content": ""},
            "long_term": [],
            "temp_workspace_memories": [],
            "archived_memories": {"short_term": {}, "long_term": {}},
        },
    )

    content = section.build_content()
    assert "memory/short_term/verification_latest.md" in content
    assert "exact commands/script paths" in content
    assert "artifact paths" in content
    assert "freshness status" in content
    assert "concrete assertion" not in content.lower()


def test_memory_section_renders_dedicated_verification_replay_block():
    """Verification replay memories should appear in a dedicated auto-injected section."""
    section = MemorySection(
        memory_config={
            "short_term": {"content": ""},
            "long_term": [],
            "temp_workspace_memories": [
                {
                    "agent_label": "agent1",
                    "memories": {
                        "short_term": {
                            "verification_latest": {
                                "name": "verification_latest",
                                "content": "## Verify\n- uv run pytest massgen/tests/test_planning_tools.py -q",
                            },
                        },
                        "long_term": {},
                    },
                },
            ],
            "archived_memories": {"short_term": {}, "long_term": {}},
        },
    )
    content = section.build_content()
    assert "Verification Replay Memories (Auto-Injected)" in content
    assert "verification_latest.md" in content
    assert "uv run pytest" in content
