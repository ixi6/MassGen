"""Integration tests for plan-and-execute workflow."""

import json

import pytest

from massgen.plan_storage import PlanStorage


class TestWorkspaceCopying:
    """Tests for workspace copying behavior in plan-and-execute."""

    @pytest.fixture
    def temp_plans_dir(self, monkeypatch, tmp_path):
        """Create temporary plans directory for testing."""
        temp_path = tmp_path / ".massgen" / "plans"
        temp_path.mkdir(parents=True)
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_path)
        return temp_path

    def test_copies_only_workspace_not_agent_metadata(self, temp_plans_dir, tmp_path):
        """Test that only workspace content is copied, not answer.txt, context.txt, etc."""
        assert temp_plans_dir.exists()

        # Create a fake final/ directory with full agent structure
        final_dir = tmp_path / "final"
        agent_dir = final_dir / "agent_a"
        workspace_dir = agent_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Create workspace content (should be copied) - project_plan.json in root
        plan_data = {"tasks": [{"id": "T001", "description": "Test task", "status": "pending"}]}
        (workspace_dir / "project_plan.json").write_text(json.dumps(plan_data, indent=2))
        (workspace_dir / "user_stories.md").write_text("# User Stories\n- Story 1")
        (workspace_dir / "CONTEXT.md").write_text("# Context\nTest context")

        # Create agent metadata files (should NOT be copied)
        (agent_dir / "answer.txt").write_text("Agent's final answer")
        (agent_dir / "context.txt").write_text("Agent's context history")
        (agent_dir / "execution_trace.md").write_text("# Execution Trace\nStep by step...")

        # Now use PlanStorage with the workspace_dir (simulating what run_plan_and_execute does)
        storage = PlanStorage()
        session = storage.create_plan("test_session", str(tmp_path))
        storage.finalize_planning_phase(session, workspace_dir)  # Pass workspace_dir, not final_dir

        # Verify workspace content WAS copied (project_plan.json renamed to plan.json)
        assert (session.workspace_dir / "plan.json").exists()  # Renamed from project_plan.json
        assert (session.workspace_dir / "user_stories.md").exists()
        assert (session.workspace_dir / "CONTEXT.md").exists()

        # Verify agent metadata was NOT copied
        assert not (session.workspace_dir / "answer.txt").exists()
        assert not (session.workspace_dir / "context.txt").exists()
        assert not (session.workspace_dir / "execution_trace.md").exists()

    def test_copies_only_deliverable_when_two_tier_enabled(self, temp_plans_dir, tmp_path):
        """Test that only deliverable/ content is copied when two-tier workspace is used."""
        assert temp_plans_dir.exists()

        # Create a fake workspace with two-tier structure
        workspace_dir = tmp_path / "workspace"
        scratch_dir = workspace_dir / "scratch"
        deliverable_dir = workspace_dir / "deliverable"
        scratch_dir.mkdir(parents=True)
        deliverable_dir.mkdir(parents=True)

        # Create scratch content (should NOT be copied when using deliverable/)
        (scratch_dir / "draft.md").write_text("# Draft notes")
        (scratch_dir / "temp_file.txt").write_text("Temporary content")

        # Create deliverable content (should be copied) - project_plan.json in root
        plan_data = {"tasks": [{"id": "T001", "description": "Test task", "status": "pending"}]}
        (deliverable_dir / "project_plan.json").write_text(json.dumps(plan_data, indent=2))
        (deliverable_dir / "USER_STORIES.md").write_text("# User Stories\n- Final story")

        # When two-tier is enabled, we pass deliverable_dir
        storage = PlanStorage()
        session = storage.create_plan("test_session", str(tmp_path))
        storage.finalize_planning_phase(session, deliverable_dir)

        # Verify deliverable content WAS copied (project_plan.json renamed to plan.json)
        assert (session.workspace_dir / "plan.json").exists()  # Renamed from project_plan.json
        assert (session.workspace_dir / "USER_STORIES.md").exists()

        # Verify scratch content was NOT copied
        assert not (session.workspace_dir / "draft.md").exists()
        assert not (session.workspace_dir / "temp_file.txt").exists()
        assert not (session.workspace_dir / "scratch").exists()

    def test_handles_missing_deliverable_dir_gracefully(self, temp_plans_dir, tmp_path):
        """Test that workspace without deliverable/ still works (non-two-tier)."""
        assert temp_plans_dir.exists()

        # Create a simple workspace without two-tier structure - project_plan.json in root
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir(parents=True)

        plan_data = {"tasks": [{"id": "T001", "description": "Test task", "status": "pending"}]}
        (workspace_dir / "project_plan.json").write_text(json.dumps(plan_data, indent=2))
        (workspace_dir / "design.md").write_text("# Design Doc")

        # Copy the whole workspace (no deliverable/ exists)
        storage = PlanStorage()
        session = storage.create_plan("test_session", str(tmp_path))
        storage.finalize_planning_phase(session, workspace_dir)

        # Verify content was copied (project_plan.json renamed to plan.json)
        assert (session.workspace_dir / "plan.json").exists()  # Renamed from project_plan.json
        assert (session.workspace_dir / "design.md").exists()


class TestPlanAndExecuteWorkflow:
    """Integration tests for plan-and-execute workflow."""

    @pytest.fixture
    def temp_plans_dir(self, monkeypatch, tmp_path):
        """Create temporary plans directory for testing."""
        temp_path = tmp_path / ".massgen" / "plans"
        temp_path.mkdir(parents=True)
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_path)
        return temp_path

    @pytest.fixture
    def mock_config(self):
        """Create a mock config for testing."""
        return {
            "agents": [{"type": "claude", "model": "claude-haiku-4-5-20251001"}],
            "orchestrator": {
                "snapshot_storage": "/tmp/test_snapshots",
                "agent_temporary_workspace": "/tmp/test_temp",
            },
        }

    def test_plan_session_lifecycle(self, temp_plans_dir, tmp_path):
        """Test complete plan session lifecycle."""
        assert temp_plans_dir.exists()

        storage = PlanStorage()

        # Create a plan session
        session = storage.create_plan("test_session_id", str(tmp_path / "test_logs"))

        # Verify session created correctly
        assert session.plan_dir.exists()
        assert session.workspace_dir.exists()
        assert session.frozen_dir.exists()

        # Check metadata
        metadata = session.load_metadata()
        assert metadata.status == "planning"
        assert metadata.planning_session_id == "test_session_id"

        # Simulate planning artifacts - use plan.json (as it would be after finalize rename)
        # In real flow: agent creates project_plan.json, finalize_planning_phase renames to plan.json
        plan_data = {
            "tasks": [
                {"id": "T001", "description": "Task 1", "status": "pending"},
                {"id": "T002", "description": "Task 2", "status": "pending"},
            ],
        }
        (session.workspace_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))

        # Add some planning docs
        (session.workspace_dir / "user_stories.md").write_text("# User Stories\n- Story 1")

        # Finalize planning (creates frozen copy)
        session.copy_workspace_to_frozen()

        # Verify frozen copy
        assert (session.frozen_dir / "plan.json").exists()
        assert (session.frozen_dir / "user_stories.md").exists()

        # Update metadata to ready
        metadata.status = "ready"
        session.save_metadata(metadata)

        # Simulate execution modifying the plan
        workspace_plan = json.loads((session.workspace_dir / "plan.json").read_text())
        workspace_plan["tasks"][0]["status"] = "completed"
        workspace_plan["tasks"].append(
            {"id": "T003", "description": "New task added during execution", "status": "pending"},
        )
        (session.workspace_dir / "plan.json").write_text(
            json.dumps(workspace_plan, indent=2),
        )

        # Compute diff
        diff = session.compute_plan_diff()

        assert len(diff["tasks_added"]) == 1
        assert "T003" in diff["tasks_added"]
        assert len(diff["tasks_modified"]) == 1
        assert diff["divergence_score"] > 0

        # Save diff
        session.diff_file.write_text(json.dumps(diff, indent=2))

    def test_get_latest_plan(self, temp_plans_dir, tmp_path):
        """Test getting the latest plan session."""
        assert temp_plans_dir.exists()

        storage = PlanStorage()

        # Create multiple plans
        storage.create_plan("sess_1", str(tmp_path / "logs1"))
        storage.create_plan("sess_2", str(tmp_path / "logs2"))
        session3 = storage.create_plan("sess_3", str(tmp_path / "logs3"))

        # Get latest should return most recent
        latest = storage.get_latest_plan()
        assert latest is not None
        assert latest.plan_id == session3.plan_id

    def test_plan_diff_no_changes(self, temp_plans_dir, tmp_path):
        """Test diff computation with no changes."""
        assert temp_plans_dir.exists()

        storage = PlanStorage()
        session = storage.create_plan("test_sess", str(tmp_path / "logs"))

        # Create identical plans in workspace and frozen (plan.json after rename)
        plan_data = {"tasks": [{"id": "T001", "description": "Test", "status": "pending"}]}

        (session.workspace_dir / "plan.json").write_text(json.dumps(plan_data))
        (session.frozen_dir / "plan.json").write_text(json.dumps(plan_data))

        diff = session.compute_plan_diff()

        assert len(diff["tasks_added"]) == 0
        assert len(diff["tasks_removed"]) == 0
        assert len(diff["tasks_modified"]) == 0
        assert diff["divergence_score"] == 0.0

    def test_event_logging(self, temp_plans_dir, tmp_path):
        """Test event logging functionality."""
        assert temp_plans_dir.exists()

        storage = PlanStorage()
        session = storage.create_plan("test_sess", str(tmp_path))

        # Log some events
        session.log_event("planning_started", {"user": "test"})
        session.log_event("task_created", {"task_id": "T001"})
        session.log_event("execution_completed", {"success": True})

        # Read and verify events
        assert session.execution_log_file.exists()
        lines = session.execution_log_file.read_text().strip().split("\n")

        # First event is plan_created (from create_plan), then our 3 events
        assert len(lines) == 4

        # Verify structure
        for line in lines:
            event = json.loads(line)
            assert "timestamp" in event
            assert "event_type" in event
            assert "data" in event

    def test_execution_prompt_generation(self):
        """Test that execution prompt is generated correctly.

        Verifies key sections are present in the generated prompt including
        plan execution mode markers, task references, and planning doc paths.
        """
        from massgen.plan_execution import build_execution_prompt

        prompt = build_execution_prompt("Build a REST API")

        # Verify key sections are present (simplified prompt, details in system message)
        assert "PLAN EXECUTION MODE" in prompt
        assert "Build a REST API" in prompt
        assert "tasks/plan.json" in prompt  # References task plan location
        assert "AUTO-LOADED" in prompt  # Plan is auto-loaded
        assert "planning_docs" in prompt  # References supporting docs


@pytest.mark.asyncio
@pytest.mark.expensive
class TestPlanAndExecuteEndToEnd:
    """End-to-end tests for plan-and-execute (requires API keys)."""

    async def test_full_workflow_mock(self, tmp_path, monkeypatch):
        """Test full workflow with mocked subprocess."""
        # This test mocks the subprocess to avoid actual API calls
        # For real integration testing, use the CLI tests in the plan

        # Setup temp plans directory
        temp_plans = tmp_path / ".massgen" / "plans"
        temp_plans.mkdir(parents=True)
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_plans)

        # Create a fake planning output directory (simulating workspace structure)
        fake_log_dir = tmp_path / "logs" / "session_123"
        fake_workspace_dir = fake_log_dir / "final" / "agent_a" / "workspace"
        fake_workspace_dir.mkdir(parents=True)

        # Create fake planning artifacts - project_plan.json in workspace root
        plan_data = {
            "tasks": [
                {"id": "T001", "description": "Implement calculator add function", "status": "pending"},
                {"id": "T002", "description": "Implement calculator subtract function", "status": "pending"},
            ],
        }
        (fake_workspace_dir / "project_plan.json").write_text(json.dumps(plan_data, indent=2))
        (fake_workspace_dir / "user_stories.md").write_text("# User Stories\n- Basic calculator")

        # Test that storage can capture these artifacts
        storage = PlanStorage()
        session = storage.create_plan("session_123", str(fake_log_dir))
        storage.finalize_planning_phase(session, fake_workspace_dir)

        # Verify plan was captured (project_plan.json renamed to plan.json)
        assert (session.workspace_dir / "plan.json").exists()  # Renamed from project_plan.json
        assert (session.frozen_dir / "plan.json").exists()
        assert (session.workspace_dir / "user_stories.md").exists()

        # Verify metadata
        metadata = session.load_metadata()
        assert metadata.status == "ready"
