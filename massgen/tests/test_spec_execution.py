"""Unit tests for spec execution functions in plan_execution module."""

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from massgen.plan_execution import (
    SPEC_EXECUTION_GUIDANCE,
    PlanValidationError,
    _get_artifact_items,
    build_execution_prompt,
    build_spec_execution_prompt,
    initialize_chunk_execution_state,
    load_frozen_plan,
    prepare_spec_execution_config,
    setup_agent_workspaces_for_execution,
    setup_agent_workspaces_for_spec_execution,
    validate_chunked_plan,
)


@pytest.fixture
def temp_plans_dir(monkeypatch):
    """Create temporary plans directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir) / ".massgen" / "plans"
        monkeypatch.setattr("massgen.plan_storage.PLANS_DIR", temp_path)
        yield temp_path


@pytest.fixture
def spec_session(temp_plans_dir):
    """Create a finalized spec session with frozen spec.json."""
    from massgen.plan_storage import PlanStorage

    storage = PlanStorage()
    session = storage.create_plan("test_sess", "/tmp/logs")

    spec_data = {
        "feature": "User Auth",
        "overview": "Authentication system",
        "requirements": [
            {
                "id": "REQ-001",
                "chunk": "C01_core",
                "title": "Login endpoint",
                "priority": "P0",
                "type": "functional",
                "ears": "WHEN user submits valid credentials THE SYSTEM SHALL return a JWT token",
                "rationale": "Core auth flow",
                "verification": "POST /login returns 200 + JWT",
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
                "rationale": "Self-service recovery",
                "verification": "POST /reset-password triggers email",
                "depends_on": ["REQ-001"],
            },
        ],
    }

    # Write spec to frozen dir
    session.frozen_dir.mkdir(parents=True, exist_ok=True)
    (session.frozen_dir / "spec.json").write_text(json.dumps(spec_data, indent=2))
    (session.frozen_dir / "design.md").write_text("# Design\nJWT for stateless auth")

    # Update metadata
    metadata = session.load_metadata()
    metadata.status = "ready"
    metadata.artifact_type = "spec"
    metadata.chunk_order = ["C01_core", "C02_advanced"]
    metadata.completed_chunks = []
    metadata.current_chunk = "C01_core"
    session.save_metadata(metadata)

    return session


@pytest.fixture
def base_config():
    """Base MassGen config for testing."""
    return {
        "orchestrator": {
            "context_paths": [],
            "coordination": {},
        },
        "agents": [
            {"name": "agent_1", "system_message": "You are agent 1."},
            {"name": "agent_2", "system_message": "You are agent 2."},
        ],
    }


class TestSpecExecutionGuidance:
    """Test the SPEC_EXECUTION_GUIDANCE constant."""

    def test_guidance_mentions_spec_json(self):
        assert "spec.json" in SPEC_EXECUTION_GUIDANCE

    def test_guidance_mentions_ears(self):
        assert "EARS" in SPEC_EXECUTION_GUIDANCE or "ears" in SPEC_EXECUTION_GUIDANCE

    def test_guidance_mentions_frozen_read_only(self):
        assert "FROZEN" in SPEC_EXECUTION_GUIDANCE or "read-only" in SPEC_EXECUTION_GUIDANCE


class TestPrepareSpecExecutionConfig:
    """Test prepare_spec_execution_config function."""

    def test_adds_frozen_dir_as_context_path(self, spec_session, base_config):
        result = prepare_spec_execution_config(base_config, spec_session)
        context_paths = result["orchestrator"]["context_paths"]
        frozen_path = str(spec_session.frozen_dir.resolve())
        path_strings = [ctx.get("path") if isinstance(ctx, dict) else None for ctx in context_paths]
        assert frozen_path in path_strings

    def test_injects_spec_execution_guidance(self, spec_session, base_config):
        result = prepare_spec_execution_config(base_config, spec_session)
        for agent_cfg in result["agents"]:
            assert SPEC_EXECUTION_GUIDANCE in agent_cfg["system_message"]

    def test_enables_task_planning(self, spec_session, base_config):
        result = prepare_spec_execution_config(base_config, spec_session)
        coordination = result["orchestrator"]["coordination"]
        assert coordination["enable_agent_task_planning"] is True
        assert coordination["task_planning_filesystem_mode"] is True

    def test_does_not_modify_original_config(self, spec_session, base_config):
        original = copy.deepcopy(base_config)
        prepare_spec_execution_config(base_config, spec_session)
        assert base_config == original

    def test_restores_context_paths_from_metadata(self, spec_session, base_config):
        metadata = spec_session.load_metadata()
        metadata.context_paths = [{"path": "/some/context", "permission": "read"}]
        spec_session.save_metadata(metadata)

        result = prepare_spec_execution_config(base_config, spec_session)
        context_paths = result["orchestrator"]["context_paths"]
        path_strings = [ctx.get("path") if isinstance(ctx, dict) else None for ctx in context_paths]
        assert "/some/context" in path_strings


class TestBuildSpecExecutionPrompt:
    """Test build_spec_execution_prompt function."""

    def test_includes_spec_execution_header(self, spec_session):
        prompt = build_spec_execution_prompt(
            question="Build user auth",
            plan_session=spec_session,
            active_chunk="C01_core",
        )
        assert "SPEC EXECUTION" in prompt

    def test_lists_active_chunk_requirements(self, spec_session):
        prompt = build_spec_execution_prompt(
            question="Build user auth",
            plan_session=spec_session,
            active_chunk="C01_core",
        )
        assert "REQ-001" in prompt
        assert "REQ-002" in prompt
        # REQ-003 is in C02_advanced, should NOT be in C01_core prompt
        assert "REQ-003" not in prompt

    def test_includes_ears_statements(self, spec_session):
        prompt = build_spec_execution_prompt(
            question="Build user auth",
            plan_session=spec_session,
            active_chunk="C01_core",
        )
        assert "WHEN user submits valid credentials" in prompt

    def test_includes_chunk_order(self, spec_session):
        prompt = build_spec_execution_prompt(
            question="Build user auth",
            plan_session=spec_session,
            active_chunk="C01_core",
            chunk_order=["C01_core", "C02_advanced"],
        )
        assert "C01_core" in prompt
        assert "C02_advanced" in prompt

    def test_includes_user_question(self, spec_session):
        prompt = build_spec_execution_prompt(
            question="Build user auth system",
            plan_session=spec_session,
            active_chunk="C01_core",
        )
        assert "Build user auth system" in prompt


class TestSetupAgentWorkspacesForSpecExecution:
    """Test setup_agent_workspaces_for_spec_execution function."""

    def test_writes_chunk_scoped_spec_to_tasks_dir(self, spec_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_workspace = Path(tmpdir)
            fm = MagicMock()
            fm.cwd = str(agent_workspace)
            backend = MagicMock()
            backend.filesystem_manager = fm
            agent = MagicMock()
            agent.backend = backend

            agents = {"agent_1": agent}

            task_count = setup_agent_workspaces_for_spec_execution(
                agents=agents,
                plan_session=spec_session,
                active_chunk="C01_core",
            )

            # Should write chunk-scoped spec
            spec_file = agent_workspace / "tasks" / "spec.json"
            assert spec_file.exists()
            spec_data = json.loads(spec_file.read_text())
            # Only C01_core requirements
            assert len(spec_data["requirements"]) == 2
            req_ids = [r["id"] for r in spec_data["requirements"]]
            assert "REQ-001" in req_ids
            assert "REQ-002" in req_ids
            assert "REQ-003" not in req_ids
            # Has execution_scope
            assert "execution_scope" in spec_data
            assert spec_data["execution_scope"]["active_chunk"] == "C01_core"
            assert task_count == 2

    def test_copies_planning_docs(self, spec_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_workspace = Path(tmpdir)
            fm = MagicMock()
            fm.cwd = str(agent_workspace)
            backend = MagicMock()
            backend.filesystem_manager = fm
            agent = MagicMock()
            agent.backend = backend

            agents = {"agent_1": agent}

            setup_agent_workspaces_for_spec_execution(
                agents=agents,
                plan_session=spec_session,
                active_chunk="C01_core",
            )

            # Should copy markdown docs
            planning_docs = agent_workspace / "planning_docs"
            assert planning_docs.exists()
            assert (planning_docs / "design.md").exists()

    def test_copies_full_spec_to_planning_docs(self, spec_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_workspace = Path(tmpdir)
            fm = MagicMock()
            fm.cwd = str(agent_workspace)
            backend = MagicMock()
            backend.filesystem_manager = fm
            agent = MagicMock()
            agent.backend = backend

            agents = {"agent_1": agent}

            setup_agent_workspaces_for_spec_execution(
                agents=agents,
                plan_session=spec_session,
                active_chunk="C01_core",
            )

            # Full spec in planning_docs for reference
            full_spec = agent_workspace / "planning_docs" / "full_spec.json"
            assert full_spec.exists()
            data = json.loads(full_spec.read_text())
            # Full spec has all 3 requirements
            assert len(data["requirements"]) == 3


class TestGetArtifactItems:
    """Test _get_artifact_items helper for both plan and spec data."""

    def test_extracts_tasks_from_plan_data(self):
        data = {"tasks": [{"id": "T001", "chunk": "C01"}]}
        key, items = _get_artifact_items(data)
        assert key == "tasks"
        assert len(items) == 1

    def test_extracts_requirements_from_spec_data(self):
        data = {"requirements": [{"id": "REQ-001", "chunk": "C01_core"}]}
        key, items = _get_artifact_items(data)
        assert key == "requirements"
        assert len(items) == 1

    def test_prefers_tasks_when_both_present(self):
        data = {
            "tasks": [{"id": "T001", "chunk": "C01"}],
            "requirements": [{"id": "REQ-001", "chunk": "C01_core"}],
        }
        key, items = _get_artifact_items(data)
        assert key == "tasks"

    def test_raises_when_neither_present(self):
        with pytest.raises(PlanValidationError, match="non-empty"):
            _get_artifact_items({"overview": "something"})

    def test_raises_when_both_empty(self):
        with pytest.raises(PlanValidationError, match="non-empty"):
            _get_artifact_items({"tasks": [], "requirements": []})


class TestValidateChunkedPlanWithSpecs:
    """Test that validate_chunked_plan works with spec requirements."""

    def test_validates_spec_requirements_as_chunked_items(self):
        spec_data = {
            "requirements": [
                {"id": "REQ-001", "chunk": "C01_core", "depends_on": []},
                {"id": "REQ-002", "chunk": "C01_core", "depends_on": ["REQ-001"]},
                {"id": "REQ-003", "chunk": "C02_adv", "depends_on": ["REQ-001"]},
            ],
        }
        chunk_order, items_by_chunk = validate_chunked_plan(spec_data)
        assert chunk_order == ["C01_core", "C02_adv"]
        assert len(items_by_chunk["C01_core"]) == 2
        assert len(items_by_chunk["C02_adv"]) == 1

    def test_raises_for_missing_chunk_on_requirement(self):
        spec_data = {
            "requirements": [{"id": "REQ-001"}],
        }
        with pytest.raises(PlanValidationError):
            validate_chunked_plan(spec_data)

    def test_raises_for_duplicate_requirement_ids(self):
        spec_data = {
            "requirements": [
                {"id": "REQ-001", "chunk": "C01"},
                {"id": "REQ-001", "chunk": "C01"},
            ],
        }
        with pytest.raises(PlanValidationError, match="duplicate"):
            validate_chunked_plan(spec_data)


class TestLoadFrozenPlanWithSpec:
    """Test load_frozen_plan with spec.json files."""

    def test_loads_spec_json_when_plan_json_absent(self, spec_session):
        """load_frozen_plan should find spec.json when plan.json doesn't exist."""
        data = load_frozen_plan(spec_session)
        assert "requirements" in data
        assert len(data["requirements"]) == 3

    def test_raises_when_neither_artifact_exists(self, temp_plans_dir):
        from massgen.plan_storage import PlanStorage

        storage = PlanStorage()
        session = storage.create_plan("empty_sess", "/tmp/logs")
        session.frozen_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(FileNotFoundError, match="plan.json and spec.json"):
            load_frozen_plan(session)


class TestInitializeChunkExecutionStateWithSpec:
    """Test initialize_chunk_execution_state with spec sessions."""

    def test_initializes_chunk_order_from_spec(self, spec_session):
        metadata = initialize_chunk_execution_state(spec_session)
        assert metadata.chunk_order == ["C01_core", "C02_advanced"]
        assert metadata.current_chunk == "C01_core"

    def test_sets_execution_mode(self, spec_session):
        metadata = initialize_chunk_execution_state(spec_session)
        assert metadata.execution_mode == "chunked_by_planner_v1"


class TestSetupAgentWorkspacesForExecutionWithSpec:
    """Test setup_agent_workspaces_for_execution (shared) with spec sessions."""

    def test_writes_spec_json_to_tasks_dir(self, spec_session):
        """The shared function should detect spec data and write spec.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_workspace = Path(tmpdir)
            fm = MagicMock()
            fm.cwd = str(agent_workspace)
            backend = MagicMock()
            backend.filesystem_manager = fm
            agent = MagicMock()
            agent.backend = backend

            count = setup_agent_workspaces_for_execution(
                agents={"agent_1": agent},
                plan_session=spec_session,
                active_chunk="C01_core",
            )

            spec_file = agent_workspace / "tasks" / "spec.json"
            assert spec_file.exists(), "spec.json should be written for spec sessions"
            data = json.loads(spec_file.read_text())
            assert "requirements" in data
            assert len(data["requirements"]) == 2  # Only C01_core reqs
            assert count == 2

    def test_writes_full_spec_reference(self, spec_session):
        """Full spec reference should be full_spec.json, not full_plan.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_workspace = Path(tmpdir)
            fm = MagicMock()
            fm.cwd = str(agent_workspace)
            backend = MagicMock()
            backend.filesystem_manager = fm
            agent = MagicMock()
            agent.backend = backend

            setup_agent_workspaces_for_execution(
                agents={"agent_1": agent},
                plan_session=spec_session,
                active_chunk="C01_core",
            )

            full_spec = agent_workspace / "planning_docs" / "full_spec.json"
            assert full_spec.exists(), "Full spec reference should be full_spec.json"
            data = json.loads(full_spec.read_text())
            assert len(data["requirements"]) == 3


class TestBuildExecutionPromptArtifactType:
    """Test build_execution_prompt with artifact_type parameter."""

    def test_plan_mode_default(self):
        prompt = build_execution_prompt("Build something", active_chunk="C01")
        assert "PLAN EXECUTION MODE" in prompt
        assert "plan.json" in prompt

    def test_spec_mode_uses_spec_language(self):
        prompt = build_execution_prompt(
            "Build something",
            active_chunk="C01",
            artifact_type="spec",
        )
        assert "SPEC EXECUTION MODE" in prompt
        assert "spec.json" in prompt
        assert "requirements" in prompt.lower()

    def test_spec_mode_references_full_spec(self):
        prompt = build_execution_prompt(
            "Build something",
            active_chunk="C01",
            artifact_type="spec",
        )
        assert "full_spec.json" in prompt
