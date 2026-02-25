"""Plan storage and session management for plan-and-execute workflow."""

import json
import shutil
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from .logger_config import logger

PLANS_DIR = Path(".massgen/plans")


@dataclass
class PlanMetadata:
    """Metadata for a plan session."""

    plan_id: str
    created_at: str
    planning_session_id: str
    planning_log_dir: str
    planning_prompt: str | None = None  # Original user query that initiated planning
    planning_turn: int | None = None  # Turn number when planning was initiated
    execution_session_id: str | None = None
    execution_log_dir: str | None = None
    status: str = "planning"  # planning, ready, executing, resumable, completed, failed
    context_paths: list[dict[str, Any]] | None = None  # Context paths from planning phase
    # Planning review loop metadata
    plan_revision: int = 1
    planning_iteration_count: int = 1
    planning_feedback_history: list[str] | None = None
    last_planning_mode: str | None = None  # "multi" | "single"
    # Chunk execution metadata
    execution_mode: str | None = None  # "chunked_by_planner_v1"
    chunk_order: list[str] | None = None
    current_chunk: str | None = None
    completed_chunks: list[str] | None = None
    chunk_history: list[dict[str, Any]] | None = None
    resumable_state: dict[str, Any] | None = None
    # Artifact type: "plan" for task plans, "spec" for requirement specs
    artifact_type: str = "plan"  # "plan" | "spec"


class PlanSession:
    """Represents a single plan-and-execute session."""

    def __init__(self, plan_id: str, create: bool = False):
        self.plan_id = plan_id
        self.plan_dir = PLANS_DIR / f"plan_{plan_id}"
        self.workspace_dir = self.plan_dir / "workspace"
        self.frozen_dir = self.plan_dir / "frozen"
        self.metadata_file = self.plan_dir / "plan_metadata.json"
        self.execution_log_file = self.plan_dir / "execution_log.jsonl"
        self.diff_file = self.plan_dir / "plan_diff.json"

        if create:
            self.plan_dir.mkdir(parents=True, exist_ok=True)
            self.workspace_dir.mkdir(exist_ok=True)
            self.frozen_dir.mkdir(exist_ok=True)

    def load_metadata(self) -> PlanMetadata:
        """Load plan metadata from disk."""
        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Plan metadata not found: {self.metadata_file}")
        raw = json.loads(self.metadata_file.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid plan metadata format in {self.metadata_file}")
        allowed = {field.name for field in fields(PlanMetadata)}
        normalized = {k: v for k, v in raw.items() if k in allowed}
        return PlanMetadata(**normalized)

    def save_metadata(self, metadata: PlanMetadata):
        """Save plan metadata to disk."""
        self.metadata_file.write_text(json.dumps(asdict(metadata), indent=2))

    def log_event(self, event_type: str, data: dict[str, Any]):
        """Append event to execution log."""
        event = {"timestamp": datetime.now().isoformat(), "event_type": event_type, "data": data}
        with self.execution_log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def copy_workspace_to_frozen(self):
        """Copy workspace contents to frozen directory (immutable snapshot)."""
        if self.frozen_dir.exists():
            shutil.rmtree(self.frozen_dir)
        shutil.copytree(self.workspace_dir, self.frozen_dir)
        logger.info(f"[PlanStorage] Froze workspace snapshot: {self.frozen_dir}")

    def compute_plan_diff(self) -> dict[str, Any]:
        """Compare workspace/ and frozen/ to detect plan drift."""
        # Spec sessions use spec.json, not plan.json — diff not yet supported
        workspace_spec = self.workspace_dir / "spec.json"
        frozen_spec = self.frozen_dir / "spec.json"
        if workspace_spec.exists() or frozen_spec.exists():
            return {"info": "spec_session_no_diff"}

        # Plan is stored as plan.json in workspace root (renamed from project_plan.json during finalize)
        workspace_plan = self.workspace_dir / "plan.json"
        frozen_plan = self.frozen_dir / "plan.json"

        if not workspace_plan.exists() or not frozen_plan.exists():
            return {"error": "Plan files missing"}

        workspace_data = json.loads(workspace_plan.read_text())
        frozen_data = json.loads(frozen_plan.read_text())

        diff = {"tasks_added": [], "tasks_removed": [], "tasks_modified": [], "divergence_score": 0.0}

        workspace_ids = {t["id"]: t for t in workspace_data.get("tasks", [])}
        frozen_ids = {t["id"]: t for t in frozen_data.get("tasks", [])}

        # Find added tasks
        for task_id in workspace_ids:
            if task_id not in frozen_ids:
                diff["tasks_added"].append(task_id)

        # Find removed tasks
        for task_id in frozen_ids:
            if task_id not in workspace_ids:
                diff["tasks_removed"].append(task_id)

        # Find modified tasks
        for task_id in frozen_ids:
            if task_id in workspace_ids:
                if workspace_ids[task_id] != frozen_ids[task_id]:
                    diff["tasks_modified"].append({"id": task_id, "original": frozen_ids[task_id], "modified": workspace_ids[task_id]})

        # Compute divergence score (0.0 = no changes, 1.0 = complete rewrite)
        total_tasks = len(frozen_ids)
        if total_tasks > 0:
            changes = len(diff["tasks_added"]) + len(diff["tasks_removed"]) + len(diff["tasks_modified"])
            diff["divergence_score"] = min(1.0, changes / total_tasks)

        return diff


class PlanStorage:
    """Manages plan storage and retrieval."""

    def __init__(self):
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    def create_plan(
        self,
        planning_session_id: str,
        planning_log_dir: str,
        planning_prompt: str | None = None,
        planning_turn: int | None = None,
    ) -> PlanSession:
        """Create a new plan session.

        Args:
            planning_session_id: Session ID for the planning phase.
            planning_log_dir: Log directory for planning phase.
            planning_prompt: Original user query that initiated planning.
            planning_turn: Turn number when planning was initiated.

        Returns:
            New PlanSession object.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        plan_id = timestamp

        session = PlanSession(plan_id, create=True)

        metadata = PlanMetadata(
            plan_id=plan_id,
            created_at=datetime.now().isoformat(),
            planning_session_id=planning_session_id,
            planning_log_dir=planning_log_dir,
            planning_prompt=planning_prompt,
            planning_turn=planning_turn,
            status="planning",
        )
        session.save_metadata(metadata)
        session.log_event("plan_created", {"plan_id": plan_id, "prompt": planning_prompt, "turn": planning_turn})

        logger.info(f"[PlanStorage] Created plan session: {plan_id}")
        return session

    def get_latest_plan(self) -> PlanSession | None:
        """Get most recent plan session."""
        if not PLANS_DIR.exists():
            return None

        plan_dirs = sorted(PLANS_DIR.glob("plan_*"), reverse=True)
        if not plan_dirs:
            return None

        plan_id = plan_dirs[0].name.replace("plan_", "")
        return PlanSession(plan_id)

    def get_latest_resumable_plan(self) -> PlanSession | None:
        """Get the most recent resumable plan session, if any."""
        if not PLANS_DIR.exists():
            return None

        for plan_dir in sorted(PLANS_DIR.glob("plan_*"), reverse=True):
            plan_id = plan_dir.name.replace("plan_", "")
            session = PlanSession(plan_id)
            if not session.metadata_file.exists():
                continue
            try:
                metadata = session.load_metadata()
            except Exception:
                logger.exception(
                    f"[PlanStorage] Failed to load metadata for resumable check (plan_id={plan_id})",
                )
                continue
            if metadata.status == "resumable":
                return session
        return None

    def get_all_plans(self, limit: int = 10) -> list[PlanSession]:
        """Get all plan sessions sorted by creation date (newest first).

        Args:
            limit: Maximum number of plans to return. Defaults to 10.

        Returns:
            List of PlanSession objects, sorted newest first.
        """
        if not PLANS_DIR.exists():
            return []

        # Plan directories are named plan_{timestamp} where timestamp is YYYYMMDD_HHMMSS_microseconds
        # Sorting by name (reverse) gives us newest first
        plan_dirs = sorted(PLANS_DIR.glob("plan_*"), reverse=True)

        sessions = []
        for plan_dir in plan_dirs[:limit]:
            plan_id = plan_dir.name.replace("plan_", "")
            try:
                session = PlanSession(plan_id)
                # Verify the session has valid metadata
                if session.metadata_file.exists():
                    sessions.append(session)
            except Exception:
                # Log and skip invalid/corrupted plan directories
                logger.exception(
                    f"[PlanStorage] Failed to load plan directory '{plan_dir.name}' (plan_id={plan_id}). Skipping.",
                )
                continue

        return sessions

    def get_plan_by_id(self, plan_id: str) -> PlanSession | None:
        """Get a specific plan session by its ID.

        Args:
            plan_id: The plan ID to retrieve.

        Returns:
            PlanSession if found, None otherwise.
        """
        session = PlanSession(plan_id)
        if session.plan_dir.exists() and session.metadata_file.exists():
            return session
        return None

    def finalize_planning_phase(
        self,
        session: PlanSession,
        workspace_source: Path,
        context_paths: list[dict[str, Any]] | None = None,
    ):
        """Copy planning workspace to plan storage and freeze it.

        Uses atomic operations to prevent partial state on interruption:
        1. Copy to temp directory
        2. Perform transformations (rename files)
        3. Atomic rename to final location

        Args:
            session: PlanSession to finalize
            workspace_source: Path to the workspace to copy
            context_paths: Optional list of context paths used during planning
                          (will be restored during execution)
        """
        # Use a temp directory for atomic operation
        temp_workspace = session.plan_dir / ".workspace_temp"
        temp_frozen = session.plan_dir / ".frozen_temp"

        try:
            # Clean up any leftover temp directories from previous failed attempts
            if temp_workspace.exists():
                shutil.rmtree(temp_workspace)
            if temp_frozen.exists():
                shutil.rmtree(temp_frozen)

            # Early guard: bail out if workspace_source doesn't exist
            # This prevents Steps 3-4 from deleting existing snapshots when there's no source
            if not workspace_source.exists():
                logger.warning(
                    f"[PlanStorage] workspace_source does not exist: {workspace_source}. " "Skipping snapshot creation to preserve existing workspace/frozen dirs.",
                )
                return

            # Step 1: Copy source to temp workspace
            # (workspace_source guaranteed to exist due to early guard above)
            temp_workspace.mkdir(parents=True, exist_ok=True)
            for item in workspace_source.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(workspace_source)
                    dest = temp_workspace / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

            # Step 2: Rename artifact files in temp workspace
            # Planning phase outputs project_plan.json or project_spec.json
            # (to distinguish from internal tasks/ files).
            # Execution phase expects plan.json or spec.json at workspace root.
            is_spec_artifact = False
            project_plan = temp_workspace / "project_plan.json"
            project_spec = temp_workspace / "project_spec.json"
            if project_spec.exists():
                project_spec.rename(temp_workspace / "spec.json")
                logger.info("[PlanStorage] Renamed project_spec.json -> spec.json")
                is_spec_artifact = True
            if project_plan.exists():
                project_plan.rename(temp_workspace / "plan.json")
                logger.info("[PlanStorage] Renamed project_plan.json -> plan.json")

            # Step 3: Create frozen copy from temp workspace
            # (temp_workspace guaranteed to exist since we just created it in Step 1)
            shutil.copytree(temp_workspace, temp_frozen)

            # Step 4: Atomic move - remove existing and rename temp to final
            # Remove existing directories if they exist
            if session.workspace_dir.exists():
                shutil.rmtree(session.workspace_dir)
            if session.frozen_dir.exists():
                shutil.rmtree(session.frozen_dir)

            # Atomic rename to final locations
            # (temp_workspace and temp_frozen guaranteed to exist from Steps 1 & 3)
            temp_workspace.rename(session.workspace_dir)
            temp_frozen.rename(session.frozen_dir)

            logger.info(f"[PlanStorage] Froze workspace snapshot: {session.frozen_dir}")

            # Step 5: Update metadata (this is a small file, low risk of corruption)
            metadata = session.load_metadata()
            metadata.status = "ready"
            # Store context paths for use during execution
            # Empty list [] means "no new paths provided, retain existing value".
            if context_paths:
                metadata.context_paths = context_paths

            if is_spec_artifact:
                metadata.artifact_type = "spec"
                # Extract chunk order from spec requirements
                spec_file = session.workspace_dir / "spec.json"
                if spec_file.exists():
                    try:
                        spec_data = json.loads(spec_file.read_text())
                        seen: set[str] = set()
                        chunks: list[str] = []
                        for req in spec_data.get("requirements", []):
                            chunk = req.get("chunk", "")
                            if chunk and chunk not in seen:
                                seen.add(chunk)
                                chunks.append(chunk)
                        metadata.chunk_order = chunks
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(
                            f"[PlanStorage] Failed to parse chunk order from spec.json: {e}. " f"chunk_order will be empty.",
                        )
                        metadata.chunk_order = []
                else:
                    metadata.chunk_order = []
                metadata.execution_mode = metadata.execution_mode or "chunked_by_planner_v1"
            else:
                metadata.artifact_type = "plan"
                metadata.execution_mode = metadata.execution_mode or "chunked_by_planner_v1"
                metadata.chunk_order = metadata.chunk_order or []

            metadata.completed_chunks = metadata.completed_chunks or []
            metadata.chunk_history = metadata.chunk_history or []
            metadata.planning_feedback_history = metadata.planning_feedback_history or []
            session.save_metadata(metadata)
            session.log_event(
                "planning_finalized",
                {"workspace_files": [str(f) for f in session.workspace_dir.rglob("*") if f.is_file()]},
            )

            logger.info(f"[PlanStorage] Finalized planning phase for {session.plan_id}")

        except Exception as e:
            # Clean up temp directories on failure
            logger.error(f"[PlanStorage] Finalization failed, cleaning up: {e}")
            if temp_workspace.exists():
                shutil.rmtree(temp_workspace, ignore_errors=True)
            if temp_frozen.exists():
                shutil.rmtree(temp_frozen, ignore_errors=True)
            raise
