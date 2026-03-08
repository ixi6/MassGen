"""Unit tests for spec mode support in plan storage module."""

import json
import tempfile
from pathlib import Path

import pytest

from massgen.plan_storage import PlanMetadata, PlanStorage


@pytest.fixture
def temp_plans_dir(monkeypatch):
    """Create temporary plans directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / ".massgen" / "plans"
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_path)
        yield temp_path


@pytest.fixture
def spec_workspace():
    """Create temporary workspace with a spec artifact (project_spec.json)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        spec_data = {
            "feature": "User Authentication",
            "overview": "Secure user authentication system",
            "requirements": [
                {
                    "id": "REQ-001",
                    "chunk": "C01_core",
                    "title": "Login endpoint",
                    "priority": "P0",
                    "type": "functional",
                    "ears": "WHEN user submits valid credentials THE SYSTEM SHALL return a JWT token",
                    "rationale": "Core authentication flow",
                    "verification": "POST /login with valid creds returns 200 + JWT",
                    "depends_on": [],
                },
                {
                    "id": "REQ-002",
                    "chunk": "C01_core",
                    "title": "Token validation",
                    "priority": "P0",
                    "type": "functional",
                    "ears": "WHEN request includes valid JWT THE SYSTEM SHALL allow access",
                    "rationale": "All protected endpoints need token validation",
                    "verification": "GET /protected with valid JWT returns 200",
                    "depends_on": ["REQ-001"],
                },
                {
                    "id": "REQ-003",
                    "chunk": "C02_advanced",
                    "title": "Password reset",
                    "priority": "P1",
                    "type": "functional",
                    "ears": "WHEN user requests password reset THE SYSTEM SHALL send reset email",
                    "rationale": "Users need self-service password recovery",
                    "verification": "POST /reset-password triggers email",
                    "depends_on": ["REQ-001"],
                },
            ],
        }
        (workspace / "project_spec.json").write_text(json.dumps(spec_data, indent=2))
        (workspace / "design_decisions.md").write_text("# Design Decisions\nJWT chosen for stateless auth")

        yield workspace


@pytest.fixture
def plan_workspace():
    """Create temporary workspace with a plan artifact (project_plan.json)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        plan_data = {
            "tasks": [
                {"id": "T001", "chunk": "C01_setup", "description": "Setup project", "status": "pending"},
            ],
        }
        (workspace / "project_plan.json").write_text(json.dumps(plan_data, indent=2))

        yield workspace


class TestPlanMetadataArtifactType:
    """Test artifact_type field on PlanMetadata."""

    def test_default_artifact_type_is_plan(self):
        """Existing plans without artifact_type should default to 'plan'."""
        metadata = PlanMetadata(
            plan_id="test",
            created_at="2026-01-01",
            planning_session_id="sess",
            planning_log_dir="/tmp",
        )
        assert metadata.artifact_type == "plan"

    def test_artifact_type_can_be_set_to_spec(self):
        metadata = PlanMetadata(
            plan_id="test",
            created_at="2026-01-01",
            planning_session_id="sess",
            planning_log_dir="/tmp",
            artifact_type="spec",
        )
        assert metadata.artifact_type == "spec"

    def test_backward_compat_load_without_artifact_type(self, temp_plans_dir):
        """Loading metadata JSON that lacks artifact_type should default to 'plan'."""
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        # Manually write metadata WITHOUT artifact_type (simulating old format)
        raw = json.loads(session.metadata_file.read_text())
        raw.pop("artifact_type", None)
        session.metadata_file.write_text(json.dumps(raw))

        loaded = session.load_metadata()
        assert loaded.artifact_type == "plan"


class TestFinalizeSpecSession:
    """Test finalize_planning_phase with spec artifacts."""

    def test_finalize_renames_project_spec_to_spec_json(self, temp_plans_dir, spec_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        storage.finalize_planning_phase(session, spec_workspace)

        # project_spec.json should be renamed to spec.json
        assert (session.workspace_dir / "spec.json").exists()
        assert not (session.workspace_dir / "project_spec.json").exists()
        # Frozen copy should also have spec.json
        assert (session.frozen_dir / "spec.json").exists()
        assert not (session.frozen_dir / "project_spec.json").exists()
        # Supporting docs should be copied
        assert (session.workspace_dir / "design_decisions.md").exists()

    def test_finalize_sets_artifact_type_spec(self, temp_plans_dir, spec_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        storage.finalize_planning_phase(session, spec_workspace)

        metadata = session.load_metadata()
        assert metadata.artifact_type == "spec"

    def test_finalize_extracts_chunk_order_from_spec(self, temp_plans_dir, spec_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        storage.finalize_planning_phase(session, spec_workspace)

        metadata = session.load_metadata()
        # Should extract unique chunk labels in order from requirements
        assert metadata.chunk_order == ["C01_core", "C02_advanced"]

    def test_finalize_plan_artifact_type_remains_plan(self, temp_plans_dir, plan_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        storage.finalize_planning_phase(session, plan_workspace)

        metadata = session.load_metadata()
        assert metadata.artifact_type == "plan"

    def test_finalize_sets_status_ready(self, temp_plans_dir, spec_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")

        storage.finalize_planning_phase(session, spec_workspace)

        metadata = session.load_metadata()
        assert metadata.status == "ready"


class TestComputePlanDiffForSpec:
    """Test compute_plan_diff behavior with spec sessions."""

    def test_compute_diff_returns_info_for_spec_session(self, temp_plans_dir, spec_workspace):
        storage = PlanStorage()
        session = storage.create_plan("test_sess", "/tmp/logs")
        storage.finalize_planning_phase(session, spec_workspace)

        diff = session.compute_plan_diff()
        # Spec sessions don't have plan.json, so diff must return the sentinel value
        assert diff == {"info": "spec_session_no_diff"}
