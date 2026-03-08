"""Unit tests for plan storage module."""

import json
import tempfile
from pathlib import Path

import pytest

from massgen.plan_storage import PlanMetadata, PlanSession, PlanStorage


@pytest.fixture
def temp_plans_dir(monkeypatch):
    """Create temporary plans directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / ".massgen" / "plans"
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_path)
        yield temp_path


@pytest.fixture
def temp_workspace():
    """Create temporary workspace with test plan files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # Create test plan file in workspace root
        plan_data = {
            "tasks": [
                {"id": "T001", "description": "Test task 1", "status": "pending"},
                {"id": "T002", "description": "Test task 2", "status": "pending"},
            ],
        }
        (workspace / "project_plan.json").write_text(json.dumps(plan_data, indent=2))

        # Create test markdown files
        (workspace / "user_stories.md").write_text("# User Stories\nTest content")
        (workspace / "technical_design.md").write_text("# Technical Design\nTest content")

        yield workspace


class TestPlanStorage:
    """Test plan storage operations."""

    def test_create_plan_session(self, temp_plans_dir):
        """Test creating new plan storage."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess_123", "/tmp/logs/test")

        assert session.plan_dir.exists()
        assert session.workspace_dir.exists()
        assert session.frozen_dir.exists()
        assert session.metadata_file.exists()

        # Verify metadata
        metadata = session.load_metadata()
        assert metadata.plan_id == session.plan_id
        assert metadata.planning_session_id == "test_sess_123"
        assert metadata.planning_log_dir == "/tmp/logs/test"
        assert metadata.status == "planning"

    def test_finalize_planning_phase(self, temp_plans_dir, temp_workspace):
        """Test copying workspace and freezing."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        # Finalize with test workspace (contains project_plan.json)
        storage.finalize_planning_phase(session, temp_workspace)

        # Verify workspace files copied and project_plan.json renamed to plan.json
        assert (session.workspace_dir / "plan.json").exists()  # Renamed from project_plan.json
        assert not (session.workspace_dir / "project_plan.json").exists()  # Should be renamed
        assert (session.workspace_dir / "user_stories.md").exists()
        assert (session.workspace_dir / "technical_design.md").exists()

        # Verify frozen directory created with renamed file
        assert (session.frozen_dir / "plan.json").exists()
        assert (session.frozen_dir / "user_stories.md").exists()

        # Verify metadata updated
        metadata = session.load_metadata()
        assert metadata.status == "ready"

    def test_compute_plan_diff_no_changes(self, temp_plans_dir, temp_workspace):
        """Test plan diff with no changes."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")
        storage.finalize_planning_phase(session, temp_workspace)

        # No changes made, diff should be empty
        diff = session.compute_plan_diff()

        assert len(diff["tasks_added"]) == 0
        assert len(diff["tasks_removed"]) == 0
        assert len(diff["tasks_modified"]) == 0
        assert diff["divergence_score"] == 0.0

    def test_compute_plan_diff_with_modifications(self, temp_plans_dir, temp_workspace):
        """Test plan diff computation with modifications."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")
        storage.finalize_planning_phase(session, temp_workspace)

        # Modify the workspace plan (now plan.json after rename)
        workspace_plan_file = session.workspace_dir / "plan.json"
        workspace_plan = json.loads(workspace_plan_file.read_text())

        # Modify existing task
        workspace_plan["tasks"][0]["description"] = "Modified description"

        # Add new task
        workspace_plan["tasks"].append(
            {
                "id": "T003",
                "description": "New task",
                "status": "pending",
            },
        )

        # Remove a task
        workspace_plan["tasks"] = [t for t in workspace_plan["tasks"] if t["id"] != "T002"]

        workspace_plan_file.write_text(json.dumps(workspace_plan, indent=2))

        # Compute diff
        diff = session.compute_plan_diff()

        assert len(diff["tasks_added"]) == 1
        assert "T003" in diff["tasks_added"]

        assert len(diff["tasks_removed"]) == 1
        assert "T002" in diff["tasks_removed"]

        assert len(diff["tasks_modified"]) == 1
        assert diff["tasks_modified"][0]["id"] == "T001"

        # Divergence score should be > 0
        assert diff["divergence_score"] > 0

    def test_get_latest_plan(self, temp_plans_dir):
        """Test retrieving latest plan."""
        storage = PlanStorage()

        # Create multiple plans
        storage.create_plan("sess_1", "/tmp/logs1")
        session2 = storage.create_plan("sess_2", "/tmp/logs2")

        # Get latest should return session2
        latest = storage.get_latest_plan()
        assert latest is not None
        assert latest.plan_id == session2.plan_id

    def test_get_latest_resumable_plan(self, temp_plans_dir):
        """Test retrieving the latest resumable plan session."""
        storage = PlanStorage()

        session1 = storage.create_plan("sess_1", "/tmp/logs1")
        metadata1 = session1.load_metadata()
        metadata1.status = "resumable"
        session1.save_metadata(metadata1)

        storage.create_plan("sess_2", "/tmp/logs2")

        session3 = storage.create_plan("sess_3", "/tmp/logs3")
        metadata3 = session3.load_metadata()
        metadata3.status = "resumable"
        session3.save_metadata(metadata3)

        resumable = storage.get_latest_resumable_plan()
        assert resumable is not None
        assert resumable.plan_id == session3.plan_id

    def test_log_event(self, temp_plans_dir):
        """Test event logging."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        # Log some events
        session.log_event("test_event", {"key": "value"})
        session.log_event("another_event", {"foo": "bar"})

        # Verify events logged
        assert session.execution_log_file.exists()

        lines = session.execution_log_file.read_text().strip().split("\n")
        assert len(lines) == 3  # plan_created + 2 test events

        # Parse and verify
        event = json.loads(lines[1])
        assert event["event_type"] == "test_event"
        assert event["data"]["key"] == "value"


class TestPlanSession:
    """Test plan session operations."""

    def test_session_initialization_without_create(self, temp_plans_dir):
        """Test session initialization without creating directories."""
        session = PlanSession("test_id", create=False)

        assert session.plan_id == "test_id"
        assert not session.plan_dir.exists()

    def test_session_initialization_with_create(self, temp_plans_dir):
        """Test session initialization with directory creation."""
        session = PlanSession("test_id", create=True)

        assert session.plan_dir.exists()
        assert session.workspace_dir.exists()
        assert session.frozen_dir.exists()

    def test_metadata_save_and_load(self, temp_plans_dir):
        """Test metadata persistence."""
        session = PlanSession("test_id", create=True)

        metadata = PlanMetadata(
            plan_id="test_id",
            created_at="2026-01-15T10:00:00",
            planning_session_id="sess_123",
            planning_log_dir="/tmp/logs",
            status="planning",
        )

        session.save_metadata(metadata)
        loaded = session.load_metadata()

        assert loaded.plan_id == metadata.plan_id
        assert loaded.planning_session_id == metadata.planning_session_id
        assert loaded.status == metadata.status
