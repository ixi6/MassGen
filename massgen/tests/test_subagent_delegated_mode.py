"""
Unit tests for delegated subagent runtime mode (MAS-325).

Tests cover:
- Runtime mode resolution for "delegated"
- Validation of delegated mode configuration
- DelegationRequest/DelegationResponse schema and atomic write
- _execute_delegated success/error/timeout/cancel paths
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from massgen.subagent.delegation_protocol import (
    DELEGATION_PROTOCOL_VERSION,
    DelegationRequest,
    DelegationResponse,
    cancel_sentinel_path,
    write_cancel_sentinel,
)

# =============================================================================
# Helper to create a SubagentManager
# =============================================================================


def _make_manager(
    tmp_path: Path,
    runtime_mode: str = "isolated",
    delegation_directory: str | None = None,
    running_inside_container: bool = False,
    fallback_mode: str | None = None,
    host_launch_prefix: list[str] | None = None,
):
    from massgen.subagent.manager import SubagentManager

    with patch("massgen.subagent.manager.os.path.exists", return_value=running_inside_container):
        mgr = SubagentManager(
            parent_workspace=str(tmp_path),
            parent_agent_id="parent-agent",
            orchestrator_id="orch-1",
            parent_agent_configs=[],
            subagent_runtime_mode=runtime_mode,
            subagent_runtime_fallback_mode=fallback_mode,
            subagent_host_launch_prefix=host_launch_prefix,
            delegation_directory=delegation_directory,
        )
    return mgr


# =============================================================================
# Step 1: Runtime mode resolution for "delegated"
# =============================================================================


class TestResolveRuntimeModeDelegated:
    """Tests for _resolve_effective_runtime_mode when mode is 'delegated'."""

    def test_resolve_runtime_mode_delegated_inside_container(self, tmp_path):
        """Delegated mode resolves to 'delegated' when inside container with delegation_dir."""
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        mgr = _make_manager(
            tmp_path,
            runtime_mode="delegated",
            delegation_directory=str(delegation_dir),
            running_inside_container=True,
        )
        mode, warning = mgr._resolve_effective_runtime_mode()
        assert mode == "delegated"
        assert warning is None

    def test_resolve_delegated_rejects_outside_container(self, tmp_path):
        """Delegated mode requires running inside a container."""
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        mgr = _make_manager(
            tmp_path,
            runtime_mode="delegated",
            delegation_directory=str(delegation_dir),
            running_inside_container=False,
        )
        with pytest.raises(RuntimeError, match="container"):
            mgr._resolve_effective_runtime_mode()

    def test_resolve_delegated_rejects_no_delegation_dir(self, tmp_path):
        """Delegated mode requires delegation_directory to be set."""
        mgr = _make_manager(
            tmp_path,
            runtime_mode="delegated",
            delegation_directory=None,
            running_inside_container=True,
        )
        with pytest.raises(RuntimeError, match="delegation_directory"):
            mgr._resolve_effective_runtime_mode()

    def test_validate_runtime_config_accepts_delegated(self, tmp_path):
        """SubagentManager init should not raise when mode is 'delegated'."""
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        # Should not raise
        mgr = _make_manager(
            tmp_path,
            runtime_mode="delegated",
            delegation_directory=str(delegation_dir),
            running_inside_container=True,
        )
        assert mgr._subagent_runtime_mode == "delegated"


# =============================================================================
# CoordinationConfig validation
# =============================================================================


class TestCoordinationConfigValidation:
    """Tests for CoordinationConfig._validate_subagent_runtime_config."""

    def test_coordination_config_accepts_delegated(self):
        """CoordinationConfig should accept 'delegated' as subagent_runtime_mode."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(subagent_runtime_mode="delegated")
        assert config.subagent_runtime_mode == "delegated"

    def test_coordination_config_rejects_invalid_mode(self):
        """CoordinationConfig should reject unknown runtime modes."""
        from massgen.agent_config import CoordinationConfig

        with pytest.raises(ValueError, match="subagent_runtime_mode"):
            CoordinationConfig(subagent_runtime_mode="unknown_mode")


# =============================================================================
# Step 2: DelegationRequest schema
# =============================================================================


class TestDelegationRequestSchema:
    """Tests for DelegationRequest dataclass."""

    def _make_request(self, **overrides) -> DelegationRequest:
        defaults = dict(
            version=DELEGATION_PROTOCOL_VERSION,
            subagent_id="sub-1",
            request_id="req-abc",
            task="Do something",
            yaml_config={"agents": [], "orchestrator": {}},
            answer_file="/workspace/answer.txt",
            workspace="/workspace",
            timeout_seconds=300,
        )
        defaults.update(overrides)
        return DelegationRequest(**defaults)

    def test_delegation_request_schema(self):
        """Request dict has all required keys."""
        req = self._make_request()
        d = req.to_dict()
        assert d["version"] == DELEGATION_PROTOCOL_VERSION
        assert d["subagent_id"] == "sub-1"
        assert d["request_id"] == "req-abc"
        assert d["task"] == "Do something"
        assert "yaml_config" in d
        assert "answer_file" in d
        assert "workspace" in d
        assert "timeout_seconds" in d
        assert "created_at" in d

    def test_delegation_request_roundtrip(self):
        """from_dict(to_dict()) is a lossless roundtrip."""
        req = self._make_request()
        req2 = DelegationRequest.from_dict(req.to_dict())
        assert req2.subagent_id == req.subagent_id
        assert req2.request_id == req.request_id
        assert req2.task == req.task
        assert req2.timeout_seconds == req.timeout_seconds

    def test_delegation_request_from_dict_ignores_unknown_fields(self):
        """Unknown fields in the dict are silently ignored."""
        req = self._make_request()
        d = req.to_dict()
        d["future_field"] = "some_value"
        # Should not raise
        req2 = DelegationRequest.from_dict(d)
        assert req2.subagent_id == req.subagent_id

    def test_delegation_request_validation_passes(self):
        """Valid request should pass validate() without exception."""
        req = self._make_request()
        req.validate()  # Should not raise

    def test_delegation_request_validation_rejects_wrong_version(self):
        """Request with wrong version fails validate()."""
        req = self._make_request(version=999)
        with pytest.raises(ValueError, match="version"):
            req.validate()

    def test_delegation_request_validation_rejects_empty_task(self):
        """Request with empty task fails validate()."""
        req = self._make_request(task="")
        with pytest.raises(ValueError, match="task"):
            req.validate()

    def test_delegation_request_validation_rejects_negative_timeout(self):
        """Request with non-positive timeout fails validate()."""
        req = self._make_request(timeout_seconds=0)
        with pytest.raises(ValueError, match="timeout_seconds"):
            req.validate()


# =============================================================================
# Step 2: Atomic write for DelegationRequest
# =============================================================================


class TestDelegationRequestAtomicWrite:
    """Tests for atomic write behavior of DelegationRequest.to_file()."""

    def test_delegation_request_atomic_write(self, tmp_path):
        """to_file() produces final JSON without leaving .tmp files."""
        req = DelegationRequest(
            version=DELEGATION_PROTOCOL_VERSION,
            subagent_id="sub-atomic",
            request_id="req-1",
            task="Test atomic write",
            yaml_config={},
            answer_file="/workspace/answer.txt",
            workspace="/workspace",
            timeout_seconds=120,
        )
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        result_path = req.to_file(delegation_dir)

        # Final file exists
        assert result_path.exists()
        assert result_path.name == "request_sub-atomic.json"

        # No leftover .tmp file
        tmp_files = list(delegation_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        # File content is valid JSON with correct data
        data = json.loads(result_path.read_text())
        assert data["subagent_id"] == "sub-atomic"
        assert data["task"] == "Test atomic write"

    def test_delegation_request_from_file(self, tmp_path):
        """from_file() correctly deserializes a written request."""
        req = DelegationRequest(
            version=DELEGATION_PROTOCOL_VERSION,
            subagent_id="sub-file-read",
            request_id="req-2",
            task="Test file read",
            yaml_config={"agents": [{"id": "agent-1"}]},
            answer_file="/workspace/answer.txt",
            workspace="/workspace",
            timeout_seconds=300,
        )
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()
        path = req.to_file(delegation_dir)

        req2 = DelegationRequest.from_file(path)
        assert req2.subagent_id == "sub-file-read"
        assert req2.request_id == "req-2"
        assert req2.task == "Test file read"
        assert req2.yaml_config == {"agents": [{"id": "agent-1"}]}


# =============================================================================
# Step 2: DelegationResponse schema and atomic write
# =============================================================================


class TestDelegationResponseSchema:
    """Tests for DelegationResponse dataclass."""

    def _make_response(self, **overrides) -> DelegationResponse:
        defaults = dict(
            version=DELEGATION_PROTOCOL_VERSION,
            subagent_id="sub-1",
            request_id="req-abc",
            status="completed",
            exit_code=0,
            stdout_tail="Final answer: Done!",
            stderr_tail="",
        )
        defaults.update(overrides)
        return DelegationResponse(**defaults)

    def test_delegation_response_roundtrip(self):
        """from_dict(to_dict()) is lossless."""
        resp = self._make_response()
        resp2 = DelegationResponse.from_dict(resp.to_dict())
        assert resp2.status == "completed"
        assert resp2.exit_code == 0
        assert resp2.stdout_tail == "Final answer: Done!"

    def test_delegation_response_error_path(self, tmp_path):
        """Error response has status='error' and non-zero exit_code."""
        resp = self._make_response(status="error", exit_code=1, stderr_tail="Something failed")
        d = resp.to_dict()
        assert d["status"] == "error"
        assert d["exit_code"] == 1
        assert d["stderr_tail"] == "Something failed"

    def test_delegation_response_validation_rejects_invalid_status(self):
        """Response with invalid status fails validate()."""
        resp = self._make_response(status="flying")
        with pytest.raises(ValueError, match="status"):
            resp.validate()

    def test_delegation_response_atomic_write(self, tmp_path):
        """to_file() produces final file without .tmp residuals."""
        resp = self._make_response(subagent_id="sub-resp-atomic")
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        path = resp.to_file(delegation_dir)

        assert path.exists()
        assert path.name == "response_sub-resp-atomic.json"
        tmp_files = list(delegation_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        data = json.loads(path.read_text())
        assert data["status"] == "completed"


# =============================================================================
# Step 2: Cancel sentinel
# =============================================================================


class TestCancelSentinel:
    """Tests for cancel sentinel file operations."""

    def test_write_cancel_sentinel(self, tmp_path):
        """write_cancel_sentinel creates an empty file."""
        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        sentinel = write_cancel_sentinel(delegation_dir, "sub-sentinel")

        assert sentinel.exists()
        assert sentinel.name == "cancel_sub-sentinel"
        assert sentinel.read_text() == ""

    def test_cancel_sentinel_path(self, tmp_path):
        """cancel_sentinel_path returns the expected path."""
        delegation_dir = tmp_path / "_delegation"
        path = cancel_sentinel_path(delegation_dir, "sub-xyz")
        assert path.name == "cancel_sub-xyz"
        assert path.parent == delegation_dir


# =============================================================================
# Step 4: _execute_delegated success path
# =============================================================================


class TestExecuteDelegatedSuccess:
    """Tests for SubagentManager._execute_delegated() success path."""

    @pytest.mark.asyncio
    async def test_delegation_response_success_path(self, tmp_path):
        """_execute_delegated reads answer.txt and returns success result."""
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentConfig

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        with patch("massgen.subagent.manager.os.path.exists", return_value=True):
            mgr = SubagentManager(
                parent_workspace=str(tmp_path),
                parent_agent_id="parent",
                orchestrator_id="orch",
                parent_agent_configs=[],
                subagent_runtime_mode="delegated",
                delegation_directory=str(delegation_dir),
            )

        config = SubagentConfig(id="sub-success", task="Write a poem", parent_agent_id="parent")

        # Simulate a watcher that writes a response + answer
        async def fake_delegate(cfg, workspace, start_time, context_warning):
            # Write answer file to subagent workspace
            answer_file = workspace / "answer.txt"
            answer_file.write_text("A beautiful poem here.")

            # Write response to delegation_dir
            resp = DelegationResponse(
                version=DELEGATION_PROTOCOL_VERSION,
                subagent_id=cfg.id,
                request_id="req-1",
                status="completed",
                exit_code=0,
                stdout_tail="",
                stderr_tail="",
            )
            delegation_dir = Path(mgr._delegation_directory)
            resp.to_file(delegation_dir)

            from massgen.subagent.models import SubagentResult

            return SubagentResult(
                subagent_id=cfg.id,
                status="completed",
                success=True,
                answer="A beautiful poem here.",
                workspace_path=str(workspace),
                execution_time_seconds=1.0,
            )

        with patch.object(mgr, "_execute_delegated", side_effect=fake_delegate):
            workspace = mgr._create_workspace(config.id)
            result = await mgr._execute_delegated(config, workspace, time.time(), None)

        assert result.status == "completed"
        assert result.answer == "A beautiful poem here."

    @pytest.mark.asyncio
    async def test_delegated_round_evaluator_request_synthesizes_by_default(self, tmp_path):
        """Delegated round_evaluator runs use synthesis by default (no skip_synthesis flag)."""
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentConfig, SubagentOrchestratorConfig

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        with patch("massgen.subagent.manager.os.path.exists", return_value=True):
            mgr = SubagentManager(
                parent_workspace=str(tmp_path),
                parent_agent_id="parent",
                orchestrator_id="orch",
                parent_agent_configs=[{"id": "parent", "backend": {"type": "codex", "model": "gpt-5.4"}}],
                subagent_runtime_mode="delegated",
                delegation_directory=str(delegation_dir),
                subagent_orchestrator_config=SubagentOrchestratorConfig(
                    enabled=True,
                    agents=[
                        {"id": "eval_codex", "backend": {"type": "codex", "model": "gpt-5.4"}},
                        {"id": "eval_claude", "backend": {"type": "claude_code", "model": "claude-sonnet-4-6"}},
                        {"id": "eval_gemini", "backend": {"type": "gemini", "model": "gemini-3.1-pro-preview"}},
                    ],
                ),
            )

        config = SubagentConfig.create(
            task="Produce one critique packet.",
            parent_agent_id="parent",
            subagent_id="round-eval",
            metadata={"refine": False, "subagent_type": "round_evaluator"},
        )
        workspace = mgr._create_workspace(config.id)
        (workspace / "CONTEXT.md").write_text("Round evaluator integration context.")

        captured_request: dict[str, object] = {}
        original_to_file = DelegationRequest.to_file

        def tracking_to_file(self_req, target_dir):
            captured_request["yaml_config"] = self_req.yaml_config
            return original_to_file(self_req, target_dir)

        async def respond_quickly():
            await asyncio.sleep(0.2)
            (workspace / "answer.txt").write_text("Synthesized critique packet")
            DelegationResponse(
                version=DELEGATION_PROTOCOL_VERSION,
                subagent_id=config.id,
                request_id=f"req-{config.id}",
                status="completed",
                exit_code=0,
            ).to_file(delegation_dir)

        with (
            patch.object(DelegationRequest, "to_file", tracking_to_file),
            patch.object(mgr, "_build_subagent_system_prompt", return_value=("Round evaluator prompt", None)),
        ):
            responder = asyncio.create_task(respond_quickly())
            result = await mgr._execute_subagent(config, workspace)
            await responder

        assert result.status == "completed"
        assert result.answer == "Synthesized critique packet"
        yaml_config = captured_request["yaml_config"]
        assert isinstance(yaml_config, dict)
        orchestrator_cfg = yaml_config["orchestrator"]
        assert orchestrator_cfg["final_answer_strategy"] == "synthesize"
        assert orchestrator_cfg["skip_final_presentation"] is False


class TestExecuteDelegatedTimeout:
    """Tests for _execute_delegated timeout handling."""

    @pytest.mark.asyncio
    async def test_delegation_timeout_writes_cancel_sentinel(self, tmp_path):
        """On timeout, _execute_delegated writes a cancel sentinel file."""
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentConfig

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        with patch("massgen.subagent.manager.os.path.exists", return_value=True):
            mgr = SubagentManager(
                parent_workspace=str(tmp_path),
                parent_agent_id="parent",
                orchestrator_id="orch",
                parent_agent_configs=[],
                subagent_runtime_mode="delegated",
                delegation_directory=str(delegation_dir),
                default_timeout=1,  # very short
                min_timeout=1,
                max_timeout=5,
            )

        config = SubagentConfig(id="sub-timeout", task="Do something slow", parent_agent_id="parent")

        # Never write a response — simulate a slow watcher
        workspace = mgr._create_workspace(config.id)
        result = await mgr._execute_delegated(config, workspace, time.time(), None)

        # Cancel sentinel should be written
        sentinel = delegation_dir / f"cancel_{config.id}"
        assert sentinel.exists(), "Cancel sentinel should be created on timeout"
        assert result.status in ("timeout", "completed_but_timeout", "partial")

    @pytest.mark.asyncio
    async def test_delegation_cancel_writes_sentinel(self, tmp_path):
        """On asyncio.CancelledError, _execute_delegated writes a cancel sentinel."""
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentConfig

        delegation_dir = tmp_path / "_delegation"
        delegation_dir.mkdir()

        with patch("massgen.subagent.manager.os.path.exists", return_value=True):
            mgr = SubagentManager(
                parent_workspace=str(tmp_path),
                parent_agent_id="parent",
                orchestrator_id="orch",
                parent_agent_configs=[],
                subagent_runtime_mode="delegated",
                delegation_directory=str(delegation_dir),
                default_timeout=60,
            )

        config = SubagentConfig(id="sub-cancel", task="Do something", parent_agent_id="parent")
        workspace = mgr._create_workspace(config.id)

        async def cancel_after_start():
            task = asyncio.create_task(mgr._execute_delegated(config, workspace, time.time(), None))
            # Let it start polling
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await cancel_after_start()

        sentinel = delegation_dir / f"cancel_{config.id}"
        assert sentinel.exists(), "Cancel sentinel should be created on CancelledError"
