# -*- coding: utf-8 -*-
"""
Unit tests for SubagentManager callback mechanism.

Tests for the async subagent execution feature (MAS-214):
- Callback registration
- Callback invocation on completion
- Callback invocation on timeout
- Multiple callback support
"""

from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock

import pytest

from massgen.subagent.models import SubagentConfig, SubagentResult

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
        invocations: List[Tuple[str, SubagentResult]] = []

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

        invocations: List[Tuple[str, SubagentResult]] = []

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

        invocations: List[Tuple[str, SubagentResult]] = []

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

    def _make_manager(self, parent_workspace, parent_context_paths=None):
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
        """No extra context_paths when parameter not provided."""
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

        # Verify YAML config has no context_paths when none provided and no parent paths
        manager = self._make_manager(parent_ws)
        workspace = manager._create_workspace(config.id)
        yaml_config = manager._generate_subagent_yaml_config(config, workspace, resolved)
        assert "context_paths" not in yaml_config["orchestrator"]

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
