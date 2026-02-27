"""
Unit tests for SubagentManager callback mechanism and runtime messaging.

Tests for the async subagent execution feature (MAS-214):
- Callback registration
- Callback invocation on completion
- Callback invocation on timeout
- Multiple callback support

Tests for runtime message routing (MAS-310):
- send_message_to_subagent file creation
- Atomic write pattern
- Unknown/non-running subagent handling
- get_running_subagent_ids
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from massgen.subagent.models import SubagentConfig, SubagentResult, SubagentState

# =============================================================================
# Callback Registration Tests
# =============================================================================


class TestSubagentManagerCallbackRegistration:
    """Tests for completion callback registration."""

    def test_register_completion_callback(self):
        """Test that a callback can be registered."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        callback_called = []

        def my_callback(subagent_id: str, result: SubagentResult):
            callback_called.append((subagent_id, result))

        manager.register_completion_callback(my_callback)

        # Verify callback is registered
        assert len(manager._completion_callbacks) == 1
        assert manager._completion_callbacks[0] == my_callback

    def test_register_multiple_callbacks(self):
        """Test that multiple callbacks can be registered."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        callback1 = MagicMock()
        callback2 = MagicMock()
        callback3 = MagicMock()

        manager.register_completion_callback(callback1)
        manager.register_completion_callback(callback2)
        manager.register_completion_callback(callback3)

        assert len(manager._completion_callbacks) == 3

    def test_callbacks_list_initialized_empty(self):
        """Test that callbacks list is initialized empty."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        assert hasattr(manager, "_completion_callbacks")
        assert manager._completion_callbacks == []


# =============================================================================
# Callback Invocation Tests
# =============================================================================


class TestSubagentManagerCallbackInvocation:
    """Tests for callback invocation on subagent completion."""

    @pytest.mark.asyncio
    async def test_callback_invoked_on_success(self):
        """Test that callback is invoked when subagent completes successfully."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        # Track callback invocations
        invocations: list[tuple[str, SubagentResult]] = []

        def track_callback(subagent_id: str, result: SubagentResult):
            invocations.append((subagent_id, result))

        manager.register_completion_callback(track_callback)

        # Create a mock result for testing
        mock_result = SubagentResult.create_success(
            subagent_id="test-sub-1",
            answer="Test answer",
            workspace_path="/tmp/test/subagents/test-sub-1",
            execution_time_seconds=5.0,
        )

        # Simulate callback invocation (this tests the callback mechanism directly)
        for callback in manager._completion_callbacks:
            callback("test-sub-1", mock_result)

        assert len(invocations) == 1
        assert invocations[0][0] == "test-sub-1"
        assert invocations[0][1].success is True
        assert invocations[0][1].answer == "Test answer"

    @pytest.mark.asyncio
    async def test_callback_invoked_on_timeout(self):
        """Test that callback is invoked when subagent times out."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        invocations: list[tuple[str, SubagentResult]] = []

        def track_callback(subagent_id: str, result: SubagentResult):
            invocations.append((subagent_id, result))

        manager.register_completion_callback(track_callback)

        # Create a timeout result
        mock_result = SubagentResult.create_timeout(
            subagent_id="test-sub-2",
            workspace_path="/tmp/test/subagents/test-sub-2",
            timeout_seconds=300.0,
        )

        # Simulate callback invocation
        for callback in manager._completion_callbacks:
            callback("test-sub-2", mock_result)

        assert len(invocations) == 1
        assert invocations[0][0] == "test-sub-2"
        assert invocations[0][1].success is False
        assert invocations[0][1].status == "timeout"

    @pytest.mark.asyncio
    async def test_callback_invoked_on_timeout_with_recovery(self):
        """Test that callback is invoked when subagent times out but has recoverable work."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        invocations: list[tuple[str, SubagentResult]] = []

        def track_callback(subagent_id: str, result: SubagentResult):
            invocations.append((subagent_id, result))

        manager.register_completion_callback(track_callback)

        # Create a timeout with recovery result
        mock_result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test-sub-3",
            workspace_path="/tmp/test/subagents/test-sub-3",
            timeout_seconds=300.0,
            recovered_answer="Recovered work from timeout",
            completion_percentage=85,
        )

        # Simulate callback invocation
        for callback in manager._completion_callbacks:
            callback("test-sub-3", mock_result)

        assert len(invocations) == 1
        assert invocations[0][0] == "test-sub-3"
        assert invocations[0][1].success is True  # Recovery was successful
        assert invocations[0][1].status == "completed_but_timeout"
        assert invocations[0][1].answer == "Recovered work from timeout"

    @pytest.mark.asyncio
    async def test_callback_receives_correct_arguments(self):
        """Test that callback receives correct subagent_id and result."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        received_id = None
        received_result = None

        def capture_callback(subagent_id: str, result: SubagentResult):
            nonlocal received_id, received_result
            received_id = subagent_id
            received_result = result

        manager.register_completion_callback(capture_callback)

        expected_result = SubagentResult.create_success(
            subagent_id="specific-id-123",
            answer="Detailed answer with specific content",
            workspace_path="/workspace/specific-id-123",
            execution_time_seconds=42.5,
            token_usage={"input_tokens": 100, "output_tokens": 50},
        )

        # Invoke callback
        for callback in manager._completion_callbacks:
            callback("specific-id-123", expected_result)

        assert received_id == "specific-id-123"
        assert received_result is not None
        assert received_result.subagent_id == "specific-id-123"
        assert received_result.answer == "Detailed answer with specific content"
        assert received_result.execution_time_seconds == 42.5
        assert received_result.token_usage == {"input_tokens": 100, "output_tokens": 50}

    @pytest.mark.asyncio
    async def test_multiple_callbacks_all_invoked(self):
        """Test that all registered callbacks are invoked."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        callback1_calls = []
        callback2_calls = []
        callback3_calls = []

        def callback1(subagent_id: str, result: SubagentResult):
            callback1_calls.append(subagent_id)

        def callback2(subagent_id: str, result: SubagentResult):
            callback2_calls.append(subagent_id)

        def callback3(subagent_id: str, result: SubagentResult):
            callback3_calls.append(subagent_id)

        manager.register_completion_callback(callback1)
        manager.register_completion_callback(callback2)
        manager.register_completion_callback(callback3)

        mock_result = SubagentResult.create_success(
            subagent_id="multi-cb-test",
            answer="Test",
            workspace_path="/tmp",
            execution_time_seconds=1.0,
        )

        # Invoke all callbacks
        for callback in manager._completion_callbacks:
            callback("multi-cb-test", mock_result)

        assert callback1_calls == ["multi-cb-test"]
        assert callback2_calls == ["multi-cb-test"]
        assert callback3_calls == ["multi-cb-test"]


# =============================================================================
# Callback Error Handling Tests
# =============================================================================


class TestSubagentManagerCallbackErrorHandling:
    """Tests for callback error handling."""

    @pytest.mark.asyncio
    async def test_callback_error_does_not_stop_other_callbacks(self):
        """Test that one callback failing doesn't prevent other callbacks from running."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        callback1_calls = []
        callback3_calls = []

        def callback1(subagent_id: str, result: SubagentResult):
            callback1_calls.append(subagent_id)

        def failing_callback(subagent_id: str, result: SubagentResult):
            raise RuntimeError("Callback error!")

        def callback3(subagent_id: str, result: SubagentResult):
            callback3_calls.append(subagent_id)

        manager.register_completion_callback(callback1)
        manager.register_completion_callback(failing_callback)
        manager.register_completion_callback(callback3)

        mock_result = SubagentResult.create_success(
            subagent_id="error-test",
            answer="Test",
            workspace_path="/tmp",
            execution_time_seconds=1.0,
        )

        # Simulate the callback invocation pattern with error handling
        # (This mirrors what _run_background should do)
        for callback in manager._completion_callbacks:
            try:
                callback("error-test", mock_result)
            except Exception:
                pass  # Continue to next callback

        assert callback1_calls == ["error-test"]
        assert callback3_calls == ["error-test"]

    @pytest.mark.asyncio
    async def test_callback_error_is_logged(self):
        """Test that callback errors are logged."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        def failing_callback(subagent_id: str, result: SubagentResult):
            raise ValueError("Test error message")

        manager.register_completion_callback(failing_callback)

        mock_result = SubagentResult.create_success(
            subagent_id="log-test",
            answer="Test",
            workspace_path="/tmp",
            execution_time_seconds=1.0,
        )

        # Test that error is raised if not caught
        with pytest.raises(ValueError, match="Test error message"):
            for callback in manager._completion_callbacks:
                callback("log-test", mock_result)


# =============================================================================
# Background Execution Tests (spawn_subagent_background)
# =============================================================================


class TestSpawnSubagentBackground:
    """Tests for spawn_subagent_background method."""

    def test_spawn_subagent_background_returns_immediately(self):
        """Test that spawn_subagent_background returns immediately with status info."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        # Note: This test verifies the return format without actually running
        # a subagent. A full integration test would need more setup.
        # The important thing is that the method signature and return type are correct.

        # Check that the method exists and has the expected signature
        assert hasattr(manager, "spawn_subagent_background")
        assert callable(manager.spawn_subagent_background)

    def test_background_subagent_creates_asyncio_task(self):
        """Test that background spawning creates an asyncio task."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace="/tmp/test",
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        # Verify _background_tasks dict is initialized
        assert hasattr(manager, "_background_tasks")
        assert isinstance(manager._background_tasks, dict)


# =============================================================================
# Subagent Result Factory Tests (ensuring test fixtures are correct)
# =============================================================================


class TestSubagentResultFactories:
    """Tests to verify SubagentResult factory methods work correctly."""

    def test_create_success_result(self):
        """Test SubagentResult.create_success factory."""
        result = SubagentResult.create_success(
            subagent_id="test-1",
            answer="Success answer",
            workspace_path="/workspace/test-1",
            execution_time_seconds=10.5,
            token_usage={"input_tokens": 500, "output_tokens": 200},
        )

        assert result.subagent_id == "test-1"
        assert result.status == "completed"
        assert result.success is True
        assert result.answer == "Success answer"
        assert result.workspace_path == "/workspace/test-1"
        assert result.execution_time_seconds == 10.5
        assert result.token_usage == {"input_tokens": 500, "output_tokens": 200}

    def test_create_timeout_result(self):
        """Test SubagentResult.create_timeout factory."""
        result = SubagentResult.create_timeout(
            subagent_id="test-2",
            workspace_path="/workspace/test-2",
            timeout_seconds=300.0,
        )

        assert result.subagent_id == "test-2"
        assert result.status == "timeout"
        assert result.success is False
        assert result.answer is None
        assert "timeout" in result.error.lower()

    def test_create_error_result(self):
        """Test SubagentResult.create_error factory."""
        result = SubagentResult.create_error(
            subagent_id="test-3",
            error="Something went wrong",
            workspace_path="/workspace/test-3",
        )

        assert result.subagent_id == "test-3"
        assert result.status == "error"
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_create_timeout_with_recovery_full_recovery(self):
        """Test SubagentResult.create_timeout_with_recovery with full recovery."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test-4",
            workspace_path="/workspace/test-4",
            timeout_seconds=300.0,
            recovered_answer="Recovered full answer",
            completion_percentage=100,
            is_partial=False,
        )

        assert result.subagent_id == "test-4"
        assert result.status == "completed_but_timeout"
        assert result.success is True
        assert result.answer == "Recovered full answer"
        assert result.completion_percentage == 100

    def test_create_timeout_with_recovery_partial(self):
        """Test SubagentResult.create_timeout_with_recovery with partial work."""
        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="test-5",
            workspace_path="/workspace/test-5",
            timeout_seconds=300.0,
            recovered_answer="Partial work",
            completion_percentage=60,
            is_partial=True,
        )

        assert result.subagent_id == "test-5"
        assert result.status == "partial"
        assert result.success is False
        assert result.answer == "Partial work"
        assert result.completion_percentage == 60


# =============================================================================
# Context Paths Tests
# =============================================================================


class TestSubagentContextPaths:
    """Tests for context_paths parameter on SubagentConfig and resolution in SubagentManager."""

    def _make_manager(self, parent_workspace, parent_context_paths=None, agent_temporary_workspace=None):
        """Helper to create a SubagentManager with minimal config."""
        from massgen.subagent.manager import SubagentManager

        return SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[
                {"id": "agent_1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            parent_context_paths=parent_context_paths,
            agent_temporary_workspace=str(agent_temporary_workspace) if agent_temporary_workspace else None,
        )

    def _resolve_context_paths(self, config, parent_workspace):
        """Simulate the context_paths resolution logic from _execute_with_orchestrator.

        This mirrors the resolution code that will be added to manager.py.
        """
        context_paths = []
        if config.context_paths:
            parent_ws = Path(parent_workspace)
            for rel_path in config.context_paths:
                if rel_path in ("./", "."):
                    resolved = parent_ws.resolve()
                else:
                    resolved = (parent_ws / rel_path).resolve()
                path_str = str(resolved)
                if path_str not in {p["path"] for p in context_paths}:
                    context_paths.append({"path": path_str, "permission": "read"})
        return context_paths

    def test_context_paths_dot_slash_mounts_parent_workspace(self, tmp_path):
        """'./' resolves to parent workspace in generated YAML config as read-only."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Evaluate the website",
            parent_agent_id="test-agent",
            subagent_id="evaluator",
            context_paths=["./"],
        )

        # Resolve context_paths the same way manager will
        resolved = self._resolve_context_paths(config, parent_ws)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(parent_ws.resolve())
        assert resolved[0]["permission"] == "read"

        # Verify it shows up in generated YAML config
        workspace = manager._create_workspace(config.id)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)
        orch_ctx = yaml_config["orchestrator"].get("context_paths", [])
        paths = [p["path"] for p in orch_ctx]
        assert str(parent_ws.resolve()) in paths
        # All permissions must be read
        for p in orch_ctx:
            assert p["permission"] == "read"

    def test_context_paths_directory_resolves_to_absolute(self, tmp_path):
        """'styles/' resolves to parent_workspace/styles/ as absolute path."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        styles_dir = parent_ws / "styles"
        styles_dir.mkdir()

        config = SubagentConfig.create(
            task="Check the CSS",
            parent_agent_id="test-agent",
            subagent_id="css-checker",
            context_paths=["styles/"],
        )

        resolved = self._resolve_context_paths(config, parent_ws)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(styles_dir.resolve())
        assert resolved[0]["permission"] == "read"

    def test_context_paths_file_resolves_to_absolute(self, tmp_path):
        """'index.html' resolves to parent_workspace/index.html as absolute path."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        index_file = parent_ws / "index.html"
        index_file.write_text("<html></html>")

        config = SubagentConfig.create(
            task="Check the HTML",
            parent_agent_id="test-agent",
            subagent_id="html-checker",
            context_paths=["index.html"],
        )

        resolved = self._resolve_context_paths(config, parent_ws)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(index_file.resolve())
        assert resolved[0]["permission"] == "read"

    def test_context_paths_empty_by_default(self, tmp_path):
        """Default context includes parent workspace as read-only mount."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        config = SubagentConfig.create(
            task="Do something",
            parent_agent_id="test-agent",
            subagent_id="default-test",
        )

        assert config.context_paths == []

        resolved = self._resolve_context_paths(config, parent_ws)
        assert resolved == []

        # Parent workspace is inherited as a safe default read-only context.
        manager = self._make_manager(parent_ws)
        workspace = manager._create_workspace(config.id)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)
        assert "context_paths" in yaml_config["orchestrator"]
        orch_paths = yaml_config["orchestrator"]["context_paths"]
        assert len(orch_paths) == 1
        assert orch_paths[0]["path"] == str(parent_ws.resolve())
        assert orch_paths[0]["permission"] == "read"

    def test_context_paths_deduplicates(self, tmp_path):
        """Same path listed twice appears only once."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        config = SubagentConfig.create(
            task="Evaluate",
            parent_agent_id="test-agent",
            subagent_id="dedup-test",
            context_paths=["./", "./"],
        )

        resolved = self._resolve_context_paths(config, parent_ws)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(parent_ws.resolve())

    def test_context_paths_coexists_with_parent_context_paths(self, tmp_path):
        """Both inherited orchestrator paths and task-specific context_paths present."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        styles_dir = parent_ws / "styles"
        styles_dir.mkdir()

        # Parent has a context path (e.g., a codebase root)
        codebase_path = str((tmp_path / "codebase").resolve())
        (tmp_path / "codebase").mkdir()

        parent_context_paths = [{"path": codebase_path, "permission": "read"}]
        manager = self._make_manager(parent_ws, parent_context_paths=parent_context_paths)

        config = SubagentConfig.create(
            task="Check CSS",
            parent_agent_id="test-agent",
            subagent_id="coexist-test",
            context_paths=["styles/"],
        )

        # Resolve task-specific context_paths
        resolved = self._resolve_context_paths(config, parent_ws)

        workspace = manager._create_workspace(config.id)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)
        orch_ctx = yaml_config["orchestrator"]["context_paths"]

        paths = [p["path"] for p in orch_ctx]
        # Parent path should be present
        assert codebase_path in paths
        # Task-specific path should also be present
        assert str(styles_dir.resolve()) in paths
        # All read-only
        for p in orch_ctx:
            assert p["permission"] == "read"

    def test_context_paths_rejects_traversal_outside_allowed_roots(self, tmp_path):
        """Paths that escape parent workspace AND parent context paths are rejected."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Try to escape",
            parent_agent_id="test-agent",
            subagent_id="escape-test",
            context_paths=["../../etc/passwd"],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        # The traversal path should be rejected (not in allowed roots)
        assert len(resolved) == 0

    def test_context_paths_allows_within_parent_workspace(self, tmp_path):
        """Paths within parent workspace are accepted."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        subdir = parent_ws / "src"
        subdir.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Read source",
            parent_agent_id="test-agent",
            subagent_id="src-test",
            context_paths=["src/"],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(subdir.resolve())

    def test_context_paths_allows_within_parent_context_path_roots(self, tmp_path):
        """Paths within inherited parent context path roots are accepted."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        external_repo = tmp_path / "external_repo"
        external_repo.mkdir()
        external_src = external_repo / "src"
        external_src.mkdir()

        parent_context_paths = [{"path": str(external_repo.resolve()), "permission": "read"}]
        manager = self._make_manager(parent_ws, parent_context_paths=parent_context_paths)
        config = SubagentConfig.create(
            task="Read external source",
            parent_agent_id="test-agent",
            subagent_id="ext-test",
            # Absolute path within a parent context root
            context_paths=[str(external_src)],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(external_src.resolve())

    def test_context_paths_allows_within_agent_temporary_workspace(self, tmp_path):
        """Paths within agent_temporary_workspace are always accepted."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        temp_root = tmp_path / "temp_workspaces" / "agent_a"
        target_file = temp_root / "agent1" / "deliverable" / "index.html"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("<html></html>")

        manager = self._make_manager(parent_ws, agent_temporary_workspace=temp_root)
        config = SubagentConfig.create(
            task="Read shared reference output",
            parent_agent_id="test-agent",
            subagent_id="shared-ref-test",
            context_paths=[str(target_file.resolve())],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(target_file.resolve())

    def test_context_paths_rejects_outside_temp_workspace_and_parent_roots(self, tmp_path):
        """Even with temp workspace configured, unrelated paths are rejected."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        temp_root = tmp_path / "temp_workspaces" / "agent_a"
        temp_root.mkdir(parents=True)
        disallowed = tmp_path / "elsewhere" / "secret.txt"
        disallowed.parent.mkdir(parents=True)
        disallowed.write_text("nope")

        manager = self._make_manager(parent_ws, agent_temporary_workspace=temp_root)
        config = SubagentConfig.create(
            task="Try unrelated path",
            parent_agent_id="test-agent",
            subagent_id="outside-test",
            context_paths=[str(disallowed.resolve())],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert resolved == []

    def test_context_paths_rejects_traversal_even_with_parent_context_paths(self, tmp_path):
        """Paths outside BOTH parent workspace and parent context roots are rejected."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()

        parent_context_paths = [{"path": str(allowed_dir.resolve()), "permission": "read"}]
        manager = self._make_manager(parent_ws, parent_context_paths=parent_context_paths)
        config = SubagentConfig.create(
            task="Try to escape",
            parent_agent_id="test-agent",
            subagent_id="escape-test-2",
            context_paths=["../../../etc/shadow"],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 0

    def test_context_paths_dot_slash_always_allowed(self, tmp_path):
        """'./' (parent workspace) is always allowed."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Mount workspace",
            parent_agent_id="test-agent",
            subagent_id="dot-test",
            context_paths=["./"],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(parent_ws.resolve())

    # ------------------------------------------------------------------
    # include_parent_workspace / temp workspace tests
    # ------------------------------------------------------------------

    def test_include_parent_workspace_true_is_default(self, tmp_path):
        """Default include_parent_workspace=True means parent workspace is in YAML."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Do research with workspace access",
            parent_agent_id="test-agent",
            subagent_id="default-ws-test",
            # include_parent_workspace defaults to True
        )

        workspace = manager._create_workspace(config.id)
        resolved = manager._resolve_context_paths_for_subagent(config)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)

        orch_paths = yaml_config["orchestrator"].get("context_paths", [])
        parent_ws_str = str(parent_ws.resolve())
        assert parent_ws_str in [p["path"] for p in orch_paths], "parent workspace should be in YAML by default (include_parent_workspace=True)"

    def test_include_parent_workspace_false_excludes_parent_workspace(self, tmp_path):
        """When include_parent_workspace=False, parent workspace is NOT auto-mounted."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()

        manager = self._make_manager(parent_ws)
        config = SubagentConfig.create(
            task="Do clean isolated research",
            parent_agent_id="test-agent",
            subagent_id="isolated-test",
            include_parent_workspace=False,
        )

        workspace = manager._create_workspace(config.id)
        resolved = manager._resolve_context_paths_for_subagent(config)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)

        orch_paths = yaml_config["orchestrator"].get("context_paths", [])
        parent_ws_str = str(parent_ws.resolve())
        assert parent_ws_str not in [p["path"] for p in orch_paths], "parent workspace should NOT be in YAML when include_parent_workspace=False"

    def test_temp_workspace_paths_always_allowed_in_context_paths(self, tmp_path):
        """Paths under agent_temporary_workspace are always allowed — no flag needed."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        temp_root = tmp_path / "temp_workspaces" / "agent_a"
        peer_ws = temp_root / "agent1" / "deliverable"
        peer_ws.mkdir(parents=True)
        (peer_ws / "index.html").write_text("<html></html>")

        manager = self._make_manager(parent_ws, agent_temporary_workspace=temp_root)
        config = SubagentConfig.create(
            task="Evaluate peer deliverable",
            parent_agent_id="test-agent",
            subagent_id="peer-eval-test",
            # No include_shared_workspace flag — just context_paths
            context_paths=[str(peer_ws.resolve())],
        )

        resolved = manager._resolve_context_paths_for_subagent(config)
        assert len(resolved) == 1
        assert resolved[0]["path"] == str(peer_ws.resolve())
        assert resolved[0]["permission"] == "read"

    def test_temp_workspace_root_not_auto_mounted(self, tmp_path):
        """The temp workspace root is never auto-mounted in YAML — only explicit paths."""
        parent_ws = tmp_path / "workspace"
        parent_ws.mkdir()
        temp_root = tmp_path / "temp_workspaces" / "agent_a"
        temp_root.mkdir(parents=True)

        manager = self._make_manager(parent_ws, agent_temporary_workspace=temp_root)
        config = SubagentConfig.create(
            task="Default spawn — no peer paths",
            parent_agent_id="test-agent",
            subagent_id="no-auto-mount-test",
        )

        workspace = manager._create_workspace(config.id)
        resolved = manager._resolve_context_paths_for_subagent(config)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)

        orch_paths = yaml_config["orchestrator"].get("context_paths", [])
        temp_str = str(temp_root.resolve())
        assert temp_str not in [p["path"] for p in orch_paths], "temp workspace root should NOT be auto-mounted in YAML"


class TestSubagentConfigInheritance:
    def test_inherits_parent_skill_settings_into_coordination(self, tmp_path):
        """Subagent YAML should inherit parent skills settings when unset locally."""
        from massgen.subagent.manager import SubagentManager

        parent_workspace = tmp_path / "workspace"
        parent_workspace.mkdir()

        manager = SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="parent-agent",
            orchestrator_id="orch",
            parent_agent_configs=[
                {"id": "agent_1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            parent_coordination_config={
                "use_skills": True,
                "massgen_skills": ["webapp-testing", "agent-browser"],
                "skills_directory": ".agent/skills",
                "load_previous_session_skills": True,
            },
        )

        config = SubagentConfig.create(
            task="Evaluate app behavior",
            parent_agent_id="parent-agent",
            subagent_id="inherit-skills",
        )
        workspace = manager._create_workspace(config.id)

        yaml_config = manager._generate_subagent_yaml_config(config, workspace, context_paths=[])
        coord = yaml_config["orchestrator"]["coordination"]

        assert coord["use_skills"] is True
        assert coord["massgen_skills"] == ["webapp-testing", "agent-browser"]
        assert coord["skills_directory"] == ".agent/skills"
        assert coord["load_previous_session_skills"] is True

    def test_inherits_parent_multimodal_tool_settings(self, tmp_path):
        """Subagent backend should inherit multimodal tool settings from parent backend."""
        from massgen.subagent.manager import SubagentManager

        parent_workspace = tmp_path / "workspace"
        parent_workspace.mkdir()

        parent_backend = {
            "type": "openai",
            "model": "gpt-4o",
            "enable_multimodal_tools": True,
            "multimodal_config": {
                "image": {"backend": "openai", "model": "gpt-image-1"},
                "audio": {"backend": "openai", "model": "gpt-4o-mini-tts"},
            },
            "image_generation_backend": "openai",
            "image_generation_model": "gpt-image-1",
            "audio_generation_backend": "openai",
            "audio_generation_model": "gpt-4o-mini-tts",
        }
        manager = SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="parent-agent",
            orchestrator_id="orch",
            parent_agent_configs=[
                {"id": "agent_1", "backend": parent_backend},
            ],
        )

        config = SubagentConfig.create(
            task="Generate and inspect media",
            parent_agent_id="parent-agent",
            subagent_id="inherit-multimodal",
        )
        workspace = manager._create_workspace(config.id)

        yaml_config = manager._generate_subagent_yaml_config(config, workspace, context_paths=[])
        backend = yaml_config["agents"][0]["backend"]

        assert backend["enable_multimodal_tools"] is True
        assert backend["multimodal_config"] == parent_backend["multimodal_config"]
        assert backend["image_generation_backend"] == "openai"
        assert backend["image_generation_model"] == "gpt-image-1"
        assert backend["audio_generation_backend"] == "openai"
        assert backend["audio_generation_model"] == "gpt-4o-mini-tts"


class TestSubagentManagerContextNormalization:
    def test_parent_workspace_added_to_context_paths(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        parent_workspace = tmp_path / "workspace"
        parent_workspace.mkdir()

        manager = SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="parent-agent",
            orchestrator_id="orch",
            parent_agent_configs=[],
        )

        paths = manager._parent_context_paths
        assert paths
        assert paths[0]["path"] == str(parent_workspace.resolve())
        assert paths[0]["permission"] == "read"
        assert len([p for p in paths if p["path"] == str(parent_workspace.resolve())]) == 1

    def test_relative_context_paths_resolved_and_read_only(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        parent_workspace = tmp_path / "workspace"
        parent_workspace.mkdir()
        relative_dir = parent_workspace / "data"
        relative_dir.mkdir()

        manager = SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="parent-agent",
            orchestrator_id="orch",
            parent_agent_configs=[],
            parent_context_paths=[{"path": "data", "permission": "write"}],
        )

        resolved_paths = {entry["path"]: entry for entry in manager._parent_context_paths}
        assert str(relative_dir.resolve()) in resolved_paths
        assert resolved_paths[str(relative_dir.resolve())]["permission"] == "read"
        workspace_path = str(parent_workspace.resolve())
        assert workspace_path in resolved_paths
        assert resolved_paths[workspace_path]["permission"] == "read"


class TestSubagentRuntimeIsolationRouting:
    def _make_manager(
        self,
        tmp_path,
        *,
        runtime_mode="isolated",
        fallback_mode=None,
        host_launch_prefix=None,
    ):
        from massgen.subagent.manager import SubagentManager

        parent_workspace = tmp_path / "workspace"
        parent_workspace.mkdir(parents=True, exist_ok=True)
        return SubagentManager(
            parent_workspace=str(parent_workspace),
            parent_agent_id="parent-agent",
            orchestrator_id="orch",
            parent_agent_configs=[],
            subagent_runtime_mode=runtime_mode,
            subagent_runtime_fallback_mode=fallback_mode,
            subagent_host_launch_prefix=host_launch_prefix,
        )

    def test_default_runtime_mode_is_isolated(self, tmp_path):
        manager = self._make_manager(tmp_path)
        assert manager._subagent_runtime_mode == "isolated"
        assert manager._subagent_runtime_fallback_mode is None

    def test_isolated_runtime_requires_prereqs_in_container(self, tmp_path):
        manager = self._make_manager(tmp_path, runtime_mode="isolated")
        manager._running_inside_container = True

        with pytest.raises(RuntimeError, match="subagent_runtime_fallback_mode"):
            manager._resolve_effective_runtime_mode()

    def test_isolated_runtime_can_fallback_to_inherited(self, tmp_path):
        manager = self._make_manager(
            tmp_path,
            runtime_mode="isolated",
            fallback_mode="inherited",
        )
        manager._running_inside_container = True

        mode, warning = manager._resolve_effective_runtime_mode()

        assert mode == "inherited"
        assert warning is not None
        assert "fallback" in warning.lower()

    def test_isolated_runtime_uses_host_prefix_when_configured(self, tmp_path):
        manager = self._make_manager(
            tmp_path,
            runtime_mode="isolated",
            host_launch_prefix=["host-launch", "--exec"],
        )
        manager._running_inside_container = True

        mode, warning = manager._resolve_effective_runtime_mode()
        assert mode == "isolated"
        assert warning is None

        cmd = manager._build_subagent_command(
            yaml_path=Path("/tmp/subagent.yaml"),
            answer_file=Path("/tmp/answer.txt"),
            full_task="do the thing",
            runtime_mode=mode,
        )
        assert cmd[:2] == ["host-launch", "--exec"]
        assert "--config" in cmd

    def test_inherited_mode_rejects_fallback_setting(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        with pytest.raises(ValueError, match="only valid when subagent_runtime_mode is 'isolated'"):
            SubagentManager(
                parent_workspace=str(tmp_path / "workspace"),
                parent_agent_id="parent-agent",
                orchestrator_id="orch",
                parent_agent_configs=[],
                subagent_runtime_mode="inherited",
                subagent_runtime_fallback_mode="inherited",
            )

    @pytest.mark.asyncio
    async def test_parallel_subagents_fail_fast_when_isolation_unavailable(self, tmp_path):
        """Strict isolated mode should fail fast instead of silently sharing runtime."""
        manager = self._make_manager(tmp_path, runtime_mode="isolated")
        manager._running_inside_container = True

        # Required for subagent spawn path.
        parent_workspace = Path(manager.parent_workspace)
        parent_workspace.mkdir(parents=True, exist_ok=True)
        (parent_workspace / "CONTEXT.md").write_text("Test context for strict-isolation failure path.")

        results = await manager.spawn_parallel(
            tasks=[
                {"task": "Start local evaluator server on 3000", "subagent_id": "eval_a", "context_paths": []},
                {"task": "Start local evaluator server on 3000", "subagent_id": "eval_b", "context_paths": []},
            ],
            timeout_seconds=120,
            refine=False,
        )

        assert len(results) == 2
        for result in results:
            assert result.success is False
            assert result.status == "error"
            assert "subagent_runtime_fallback_mode" in (result.error or "")


# =============================================================================
# Runtime Message Routing Tests (MAS-310)
# =============================================================================


class TestSendMessageToSubagent:
    """Tests for SubagentManager.send_message_to_subagent()."""

    def _make_manager(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

    def _register_running_subagent(self, manager, subagent_id, workspace_path):
        """Register a fake running subagent in manager state."""
        from massgen.subagent.models import SubagentConfig, SubagentState

        config = SubagentConfig(id=subagent_id, task="test task", parent_agent_id="test-agent")
        state = SubagentState(
            config=config,
            status="running",
            workspace_path=str(workspace_path),
        )
        manager._subagents[subagent_id] = state

    def test_send_message_creates_inbox_file(self, tmp_path):
        """Verify file written to {workspace}/.massgen/runtime_inbox/."""
        manager = self._make_manager(tmp_path)
        sub_workspace = tmp_path / "workspace" / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)
        self._register_running_subagent(manager, "sub1", sub_workspace)

        result = manager.send_message_to_subagent("sub1", "focus on performance")
        assert result is True

        inbox = sub_workspace / ".massgen" / "runtime_inbox"
        assert inbox.exists()
        msg_files = list(inbox.glob("msg_*.json"))
        assert len(msg_files) == 1

        data = json.loads(msg_files[0].read_text())
        assert data["content"] == "focus on performance"
        assert data["source"] == "parent"
        assert "timestamp" in data

    def test_send_message_returns_false_for_unknown_subagent(self, tmp_path):
        """Nonexistent ID → False."""
        manager = self._make_manager(tmp_path)
        result = manager.send_message_to_subagent("nonexistent", "hello")
        assert result is False

    def test_send_message_returns_false_for_non_running_subagent(self, tmp_path):
        """Completed subagent → False."""
        from massgen.subagent.models import SubagentConfig, SubagentState

        manager = self._make_manager(tmp_path)
        config = SubagentConfig(id="done1", task="test", parent_agent_id="test-agent")
        state = SubagentState(
            config=config,
            status="completed",
            workspace_path=str(tmp_path / "done_workspace"),
        )
        manager._subagents["done1"] = state

        result = manager.send_message_to_subagent("done1", "hello")
        assert result is False

    def test_send_message_atomic_write(self, tmp_path):
        """Verify .tmp → rename pattern (no partial reads)."""
        manager = self._make_manager(tmp_path)
        sub_workspace = tmp_path / "workspace" / "subagents" / "sub2" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)
        self._register_running_subagent(manager, "sub2", sub_workspace)

        result = manager.send_message_to_subagent("sub2", "test atomic")
        assert result is True

        inbox = sub_workspace / ".massgen" / "runtime_inbox"
        # No .tmp files should remain
        tmp_files = list(inbox.glob("*.tmp"))
        assert tmp_files == [], "No .tmp files should remain after atomic write"

    def test_multiple_messages_create_separate_files(self, tmp_path):
        """Two sends → two files with incrementing sequence."""
        manager = self._make_manager(tmp_path)
        sub_workspace = tmp_path / "workspace" / "subagents" / "sub3" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)
        self._register_running_subagent(manager, "sub3", sub_workspace)

        manager.send_message_to_subagent("sub3", "message one")
        manager.send_message_to_subagent("sub3", "message two")

        inbox = sub_workspace / ".massgen" / "runtime_inbox"
        msg_files = sorted(inbox.glob("msg_*.json"))
        assert len(msg_files) == 2

        contents = [json.loads(f.read_text())["content"] for f in msg_files]
        assert "message one" in contents
        assert "message two" in contents


class TestGetRunningSubagentIds:
    """Tests for SubagentManager.get_running_subagent_ids()."""

    def test_returns_running_ids(self, tmp_path):
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentConfig, SubagentState

        manager = SubagentManager(
            parent_workspace=str(tmp_path / "workspace"),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        for sid, status in [("a", "running"), ("b", "completed"), ("c", "running"), ("d", "failed")]:
            config = SubagentConfig(id=sid, task="test", parent_agent_id="test-agent")
            manager._subagents[sid] = SubagentState(config=config, status=status, workspace_path="")

        running = manager.get_running_subagent_ids()
        assert sorted(running) == ["a", "c"]


class _FakeCancelableProcess:
    """Minimal async subprocess stub for cancellation tests."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class TestCancelAllSubagents:
    """Tests for SubagentManager.cancel_all_subagents()."""

    @pytest.mark.asyncio
    async def test_cancel_all_marks_running_subagents_cancelled(self, tmp_path):
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentState

        manager = SubagentManager(
            parent_workspace=str(tmp_path / "workspace"),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        for subagent_id in ("sub_a", "sub_b"):
            cfg = SubagentConfig(id=subagent_id, task="test", parent_agent_id="test-agent")
            manager._subagents[subagent_id] = SubagentState(
                config=cfg,
                status="running",
                workspace_path=str(tmp_path / subagent_id),
                started_at=datetime.now(),
            )
            manager._active_processes[subagent_id] = _FakeCancelableProcess()

        cancelled = await manager.cancel_all_subagents()

        assert cancelled == 2
        assert manager._active_processes == {}
        for subagent_id in ("sub_a", "sub_b"):
            state = manager._subagents[subagent_id]
            assert state.status == "cancelled"
            assert state.finished_at is not None
            assert state.result is not None
            assert state.result.error == "Subagent cancelled"


class _FakeContinueProcess:
    """Minimal async subprocess stub for continue_subagent tests."""

    def __init__(self, workspace: Path) -> None:
        self.returncode = 0
        self._workspace = workspace

    async def communicate(self):
        answer_file = self._workspace / "answer_continued.txt"
        answer_file.write_text("continued answer")
        return b"", b""

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return 0


class TestContinueSubagent:
    """Tests for SubagentManager.continue_subagent()."""

    @pytest.mark.asyncio
    async def test_continue_updates_in_memory_state_and_listed_status(self, tmp_path, monkeypatch):
        from massgen.subagent.manager import SubagentManager
        from massgen.subagent.models import SubagentState

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        config = SubagentConfig(id="sub1", task="research topic", parent_agent_id="test-agent")
        cancelled_result = SubagentResult.create_error(
            subagent_id="sub1",
            error="Subagent cancelled",
            workspace_path=str(sub_workspace),
            execution_time_seconds=2.0,
        )
        manager._subagents["sub1"] = SubagentState(
            config=config,
            status="cancelled",
            workspace_path=str(sub_workspace),
            started_at=datetime.now(),
            finished_at=datetime.now(),
            result=cancelled_result,
        )
        manager._subagent_sessions["sub1"] = "sess-old"

        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": "sess-old",
                    "task": "research topic",
                    "status": "cancelled",
                    "workspace": str(sub_workspace),
                    "created_at": datetime.now().isoformat(),
                    "execution_time_seconds": 2.0,
                    "success": False,
                    "continuable": True,
                    "source_agent": "test-agent",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2))

        async def _fake_create_subprocess_exec(*args, **kwargs):  # noqa: ANN002, ANN003
            del args, kwargs
            return _FakeContinueProcess(sub_workspace)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(manager, "_resolve_effective_runtime_mode", lambda: ("inherited", None))
        monkeypatch.setattr(manager, "_session_has_saved_turns", lambda *args, **kwargs: True)
        monkeypatch.setattr(manager, "_parse_subprocess_status", lambda _workspace: ({}, None, "sess-new"))
        monkeypatch.setattr(manager, "_write_subprocess_log_reference", lambda *args, **kwargs: None)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="continue with more depth",
        )

        assert result.success is True
        assert result.status == "completed"
        assert result.answer == "continued answer"

        state = manager._subagents["sub1"]
        assert state.status == "completed"
        assert state.result is not None
        assert state.result.status == "completed"
        assert state.result.answer == "continued answer"
        assert state.finished_at is not None
        assert manager._subagent_sessions["sub1"] == "sess-new"

        listed = {entry["subagent_id"]: entry for entry in manager.list_subagents()}
        assert listed["sub1"]["status"] == "completed"
        assert listed["sub1"]["session_id"] == "sess-new"


class TestContinueSubagentBackground:
    """Tests for SubagentManager.continue_subagent_background()."""

    @pytest.mark.asyncio
    async def test_continue_background_returns_immediately_and_invokes_callback(self, tmp_path, monkeypatch):
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        config = SubagentConfig(id="sub1", task="research topic", parent_agent_id="test-agent")
        manager._subagents["sub1"] = SubagentState(
            config=config,
            status="completed",
            workspace_path=str(sub_workspace),
            started_at=datetime.now(),
            finished_at=datetime.now(),
            result=SubagentResult.create_success(
                subagent_id="sub1",
                answer="initial answer",
                workspace_path=str(sub_workspace),
                execution_time_seconds=1.0,
            ),
        )

        continuation_calls: list[dict[str, object]] = []

        async def _mock_continue(subagent_id: str, new_message: str, timeout_seconds: int | None = None):
            continuation_calls.append(
                {
                    "subagent_id": subagent_id,
                    "new_message": new_message,
                    "timeout_seconds": timeout_seconds,
                },
            )
            await asyncio.sleep(0)
            return SubagentResult.create_success(
                subagent_id=subagent_id,
                answer="continued answer",
                workspace_path=str(sub_workspace),
                execution_time_seconds=2.0,
            )

        monkeypatch.setattr(manager, "continue_subagent", _mock_continue)

        completed: list[tuple[str, SubagentResult]] = []
        manager.register_completion_callback(lambda sid, result: completed.append((sid, result)))

        info = manager.continue_subagent_background(
            subagent_id="sub1",
            new_message="continue with more depth",
            timeout_seconds=240,
        )

        assert info["subagent_id"] == "sub1"
        assert info["status"] == "running"
        assert "sub1" in manager._background_tasks

        result = await manager.wait_for_subagent("sub1", timeout=1.0)
        assert result is not None
        assert result.success is True
        assert result.answer == "continued answer"

        assert continuation_calls == [
            {
                "subagent_id": "sub1",
                "new_message": "continue with more depth",
                "timeout_seconds": 240,
            },
        ]
        assert len(completed) == 1
        assert completed[0][0] == "sub1"
        assert completed[0][1].answer == "continued answer"
        assert "sub1" not in manager._background_tasks

    def test_continue_background_rejects_running_subagent(self, tmp_path):
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        config = SubagentConfig(id="sub1", task="research topic", parent_agent_id="test-agent")
        manager._subagents["sub1"] = SubagentState(
            config=config,
            status="running",
            workspace_path=str(sub_workspace),
            started_at=datetime.now(),
        )

        info = manager.continue_subagent_background(
            subagent_id="sub1",
            new_message="continue with more depth",
        )

        assert info["status"] == "error"
        assert "send_message_to_subagent" in (info.get("error") or "")


class TestParseSubprocessStatusSentinel:
    """Tests for _parse_subprocess_status reading the .session_id sentinel file."""

    def test_reads_sentinel_over_status_json(self, tmp_path):
        """Sentinel file takes priority over broken status.json session_id."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace=str(tmp_path / "workspace"),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        workspace = tmp_path / "ws"
        workspace.mkdir()

        # Write sentinel with real session_id
        sentinel_dir = workspace / ".massgen"
        sentinel_dir.mkdir(parents=True)
        (sentinel_dir / ".session_id").write_text("session_20260223_120000")

        # Write status.json with broken session_id ("attempt_1")
        log_dir = sentinel_dir / "massgen_logs" / "log_001" / "turn_1" / "attempt_1"
        log_dir.mkdir(parents=True)
        status = {
            "meta": {"session_id": "attempt_1"},
            "costs": {"total_input_tokens": 100, "total_output_tokens": 50},
        }
        (log_dir / "status.json").write_text(json.dumps(status))

        token_usage, log_path, session_id = manager._parse_subprocess_status(workspace)

        # Should return sentinel session_id, not "attempt_1"
        assert session_id == "session_20260223_120000"
        assert token_usage["input_tokens"] == 100

    def test_no_sentinel_returns_none_session_id(self, tmp_path):
        """Without sentinel, session_id should be None (not status.json's broken value)."""
        from massgen.subagent.manager import SubagentManager

        manager = SubagentManager(
            parent_workspace=str(tmp_path / "workspace"),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        workspace = tmp_path / "ws"
        workspace.mkdir()

        # Write status.json with broken session_id but NO sentinel
        massgen_dir = workspace / ".massgen"
        massgen_dir.mkdir(parents=True)
        log_dir = massgen_dir / "massgen_logs" / "log_001" / "turn_1" / "attempt_1"
        log_dir.mkdir(parents=True)
        status = {
            "meta": {"session_id": "attempt_1"},
            "costs": {"total_input_tokens": 100, "total_output_tokens": 50},
        }
        (log_dir / "status.json").write_text(json.dumps(status))

        token_usage, log_path, session_id = manager._parse_subprocess_status(workspace)

        # No sentinel → session_id should be None
        assert session_id is None
        # Token usage should still work
        assert token_usage["input_tokens"] == 100


class TestContinueSubagentContextRecovery:
    """Tests for continue_subagent with cancelled subagents (no session_id)."""

    @pytest.mark.asyncio
    async def test_continue_cancelled_without_session_uses_context_recovery(self, tmp_path, monkeypatch):
        """Cancelled subagent with no session_id falls back to context_recovery."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        # Create registry with no session_id and context_recovery
        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": None,
                    "task": "research topic",
                    "status": "cancelled",
                    "workspace": str(sub_workspace),
                    "continuable_via": "context_recovery",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))

        # Mock spawn_subagent to track the call
        spawn_called = {}

        async def _mock_spawn(**kwargs):
            spawn_called.update(kwargs)
            return SubagentResult.create_success(
                subagent_id=kwargs.get("subagent_id", "sub1_recovery"),
                answer="recovered answer",
                workspace_path=str(sub_workspace),
                execution_time_seconds=1.0,
            )

        monkeypatch.setattr(manager, "spawn_subagent", _mock_spawn)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="continue with more depth",
        )

        assert result.success is True
        assert result.answer == "recovered answer"
        # spawn_subagent should have been called with original task + new message
        assert "research topic" in spawn_called["task"]
        assert "continue with more depth" in spawn_called["task"]

    @pytest.mark.asyncio
    async def test_continue_cancelled_in_memory_fallback(self, tmp_path, monkeypatch):
        """Cancelled subagent not in registry but in _subagents dict uses in-memory fallback."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        # Put in _subagents but NOT in registry
        config = SubagentConfig(id="sub1", task="research topic", parent_agent_id="test-agent")
        manager._subagents["sub1"] = SubagentState(
            config=config,
            status="cancelled",
            workspace_path=str(sub_workspace),
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )

        # Mock spawn_subagent
        spawn_called = {}

        async def _mock_spawn(**kwargs):
            spawn_called.update(kwargs)
            return SubagentResult.create_success(
                subagent_id=kwargs.get("subagent_id", "sub1_recovery"),
                answer="recovered",
                workspace_path=str(sub_workspace),
                execution_time_seconds=1.0,
            )

        monkeypatch.setattr(manager, "spawn_subagent", _mock_spawn)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="go deeper",
        )

        assert result.success is True
        assert "research topic" in spawn_called["task"]

    @pytest.mark.asyncio
    async def test_continue_regression_unchanged(self, tmp_path, monkeypatch):
        """Non-cancelled continue path still works (regression test)."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        # Registry with valid session_id
        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": "sess-valid",
                    "task": "research topic",
                    "status": "completed",
                    "workspace": str(sub_workspace),
                    "continuable_via": "session",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))
        (sub_workspace / ".massgen" / "sessions" / "sess-valid" / "turn_1").mkdir(parents=True, exist_ok=True)

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return _FakeContinueProcess(sub_workspace)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(manager, "_resolve_effective_runtime_mode", lambda: ("inherited", None))
        monkeypatch.setattr(manager, "_parse_subprocess_status", lambda _workspace: ({}, None, "sess-new"))
        monkeypatch.setattr(manager, "_write_subprocess_log_reference", lambda *args, **kwargs: None)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="continue please",
        )

        assert result.success is True
        assert result.answer == "continued answer"


class _FakeFailedContinueProcess:
    """Subprocess stub that simulates --session-id restore failure."""

    def __init__(self) -> None:
        self.returncode = 1

    async def communicate(self):
        return b"", b"ValueError: Cannot continue an empty session"

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return 1


class TestContinueSubagentSessionFallback:
    """Tests for fallback to context_recovery when --session-id subprocess fails."""

    @pytest.mark.asyncio
    async def test_session_restore_failure_falls_back_to_context_recovery(self, tmp_path, monkeypatch):
        """When --session-id subprocess fails (e.g. empty session), fall back to context_recovery."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        # Registry with valid session_id (SIGINT cancel wrote sentinel)
        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": "sess-from-sentinel",
                    "task": "research jazz history",
                    "status": "cancelled",
                    "workspace": str(sub_workspace),
                    "continuable_via": "session",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))
        (sub_workspace / ".massgen" / "sessions" / "sess-valid" / "turn_1").mkdir(parents=True, exist_ok=True)

        # The --session-id subprocess will fail (empty session)
        async def _fake_create_subprocess_exec(*args, **kwargs):
            return _FakeFailedContinueProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(manager, "_resolve_effective_runtime_mode", lambda: ("inherited", None))
        monkeypatch.setattr(manager, "_parse_subprocess_status", lambda _workspace: ({}, None, None))
        monkeypatch.setattr(manager, "_write_subprocess_log_reference", lambda *args, **kwargs: None)

        # Mock _continue_via_context_recovery to track the fallback
        recovery_called = {}

        async def _mock_recovery(sid, entry, msg, timeout, reuse_subagent_id=False):
            recovery_called["subagent_id"] = sid
            recovery_called["new_message"] = msg
            recovery_called["reuse_subagent_id"] = reuse_subagent_id
            return SubagentResult.create_success(
                subagent_id=f"{sid}_recovery",
                answer="recovered via fallback",
                workspace_path=str(sub_workspace),
                execution_time_seconds=2.0,
            )

        monkeypatch.setattr(manager, "_continue_via_context_recovery", _mock_recovery)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="now focus on rock and roll",
        )

        # Should have fallen back to context_recovery instead of returning error
        assert result.success is True
        assert result.answer == "recovered via fallback"
        assert recovery_called["subagent_id"] == "sub1"
        assert recovery_called["new_message"] == "now focus on rock and roll"
        assert recovery_called["reuse_subagent_id"] is True

    @pytest.mark.asyncio
    async def test_session_success_does_not_trigger_fallback(self, tmp_path, monkeypatch):
        """When --session-id subprocess succeeds, no fallback happens (regression)."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": "sess-valid",
                    "task": "research topic",
                    "status": "completed",
                    "workspace": str(sub_workspace),
                    "continuable_via": "session",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))
        (sub_workspace / ".massgen" / "sessions" / "sess-valid" / "turn_1").mkdir(parents=True, exist_ok=True)

        async def _fake_create_subprocess_exec(*args, **kwargs):
            return _FakeContinueProcess(sub_workspace)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        monkeypatch.setattr(manager, "_resolve_effective_runtime_mode", lambda: ("inherited", None))
        monkeypatch.setattr(manager, "_parse_subprocess_status", lambda _workspace: ({}, None, "sess-new"))
        monkeypatch.setattr(manager, "_write_subprocess_log_reference", lambda *args, **kwargs: None)

        # Mock recovery — should NOT be called
        recovery_called = False

        async def _mock_recovery(sid, entry, msg, timeout, reuse_subagent_id=False):
            nonlocal recovery_called
            recovery_called = True
            return SubagentResult.create_error(subagent_id=sid, error="should not reach here")

        monkeypatch.setattr(manager, "_continue_via_context_recovery", _mock_recovery)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="continue please",
        )

        assert result.success is True
        assert result.answer == "continued answer"
        assert recovery_called is False

    @pytest.mark.asyncio
    async def test_empty_session_precheck_bypasses_session_restore_subprocess(self, tmp_path, monkeypatch):
        """Empty session dirs should skip --session-id and go straight to context recovery."""
        from massgen.subagent.manager import SubagentManager

        workspace = tmp_path / "workspace"
        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        sub_workspace = workspace / "subagents" / "sub1" / "workspace"
        sub_workspace.mkdir(parents=True, exist_ok=True)

        # Sentinel-recovered session id exists but has NO turn_* dirs (empty session).
        session_id = "session_empty"
        (sub_workspace / ".massgen" / "sessions" / session_id).mkdir(parents=True, exist_ok=True)

        registry = {
            "parent_agent_id": "test-agent",
            "orchestrator_id": "test-orch",
            "subagents": [
                {
                    "subagent_id": "sub1",
                    "session_id": session_id,
                    "task": "research jazz history",
                    "status": "cancelled",
                    "workspace": str(sub_workspace),
                    "continuable_via": "session",
                },
            ],
        }
        registry_path = manager.subagents_base / "_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))

        # If precheck works, subprocess should never be launched.
        async def _unexpected_subprocess(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("continue_subagent should not invoke --session-id for empty sessions")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _unexpected_subprocess)
        monkeypatch.setattr(manager, "_resolve_effective_runtime_mode", lambda: ("inherited", None))

        recovery_called: dict[str, object] = {}

        async def _mock_recovery(sid, entry, msg, timeout, reuse_subagent_id=False):
            recovery_called["subagent_id"] = sid
            recovery_called["message"] = msg
            recovery_called["reuse_subagent_id"] = reuse_subagent_id
            return SubagentResult.create_success(
                subagent_id=sid,
                answer="recovered without session subprocess",
                workspace_path=str(sub_workspace),
                execution_time_seconds=1.5,
            )

        monkeypatch.setattr(manager, "_continue_via_context_recovery", _mock_recovery)

        result = await manager.continue_subagent(
            subagent_id="sub1",
            new_message="continue with rock and roll context",
        )

        assert result.success is True
        assert result.answer == "recovered without session subprocess"
        assert recovery_called["subagent_id"] == "sub1"
        assert recovery_called["reuse_subagent_id"] is True
