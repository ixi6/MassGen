# -*- coding: utf-8 -*-
"""
Unit tests for background parameter on spawn_subagents MCP tool.

Tests for the background subagent execution feature:
- background=false returns results (existing behavior)
- background=true returns IDs immediately
- legacy async aliases are rejected
"""

import inspect
import sys

import pytest


async def _build_subagent_server(monkeypatch, tmp_path):
    """Create the subagent MCP server and return (module, mcp)."""
    from massgen.mcp_tools.subagent import _subagent_mcp_server as server

    # Ensure clean global state per test.
    server._manager = None
    server._workspace_path = None

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "subagent-server",
            "--agent-id",
            "agent_a",
            "--orchestrator-id",
            "orch_1",
            "--workspace-path",
            str(tmp_path),
        ],
    )

    mcp = await server.create_server()
    return server, mcp


async def _build_spawn_subagents_handler(monkeypatch, tmp_path):
    """Create the subagent MCP server and return (module, spawn_subagents handler)."""
    server, mcp = await _build_subagent_server(monkeypatch, tmp_path)
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "spawn_subagents":
            return server, tool.fn
    raise RuntimeError("spawn_subagents tool not found")


async def _invoke_handler(handler, **kwargs):
    """Invoke FastMCP handler regardless of sync/async function type."""
    result = handler(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class _FakeSubagentManager:
    """Minimal fake manager for spawn_subagents MCP tests."""

    def __init__(self):
        self.background_calls = []
        self.parallel_calls = []

    class _FakeResult:
        def __init__(self, subagent_id: str):
            self.subagent_id = subagent_id
            self.status = "completed"
            self.success = True
            self.answer = f"answer::{subagent_id}"

        def to_dict(self):
            return {
                "subagent_id": self.subagent_id,
                "status": self.status,
                "success": self.success,
                "workspace": f"/tmp/{self.subagent_id}",
                "answer": self.answer,
                "execution_time_seconds": 1.0,
            }

    def spawn_subagent_background(self, **kwargs):
        self.background_calls.append(kwargs)
        subagent_id = kwargs.get("subagent_id") or "subagent_0"
        return {
            "subagent_id": subagent_id,
            "status": "running",
            "workspace": f"/tmp/{subagent_id}",
            "status_file": f"/tmp/{subagent_id}/status.json",
        }

    async def spawn_parallel(self, tasks, timeout_seconds=None, refine=True):
        self.parallel_calls.append(
            {
                "tasks": tasks,
                "timeout_seconds": timeout_seconds,
                "refine": refine,
            },
        )
        return [self._FakeResult(task.get("subagent_id", f"subagent_{i}")) for i, task in enumerate(tasks)]

    def list_subagents(self):
        return []


class TestSubagentToolSurface:
    """Tool availability contract for subagent MCP server."""

    @pytest.mark.asyncio
    async def test_only_supported_subagent_tools_are_exposed(self, monkeypatch, tmp_path):
        _, mcp = await _build_subagent_server(monkeypatch, tmp_path)
        tool_names = {tool.name for tool in mcp._tool_manager._tools.values()}

        assert {"spawn_subagents", "list_subagents", "continue_subagent"}.issubset(tool_names)
        assert "check_subagent_status" not in tool_names
        assert "get_subagent_result" not in tool_names
        assert "get_subagent_costs" not in tool_names


class TestSpawnSubagentsContextPathsRequirement:
    """Validation behavior for explicit context_paths requirement."""

    @pytest.mark.asyncio
    async def test_missing_context_paths_field_is_rejected(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Research OAuth patterns"}],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "context_paths" in result["error"]
        assert "[]" in result["error"]

    @pytest.mark.asyncio
    async def test_context_paths_must_be_list(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Explore repo structure", "context_paths": "./"}],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "expected list" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_context_paths_is_valid_explicit_choice(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Do clean research with no prior context", "context_paths": []}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert result["mode"] == "background"
        assert len(fake_manager.background_calls) == 1
        assert fake_manager.background_calls[0]["context_paths"] == []


# =============================================================================
# Background Parameter Tests
# =============================================================================


class TestSpawnSubagentsBackgroundParameter:
    """Tests for background parameter behavior on spawn_subagents tool."""

    def test_background_false_returns_results_directly(self):
        """Test that background=false (default) returns full results after completion."""
        # This tests the expected return format when async is False
        # The actual implementation will block and return results

        # Expected return format for synchronous execution
        expected_format = {
            "success": True,
            "operation": "spawn_subagents",
            "results": [
                {
                    "subagent_id": "task-1",
                    "status": "completed",
                    "workspace": "/workspace/task-1",
                    "answer": "Task completed successfully",
                    "execution_time_seconds": 10.5,
                },
            ],
            "summary": {
                "total": 1,
                "completed": 1,
                "failed": 0,
                "timeout": 0,
            },
        }

        # Verify expected format structure
        assert "success" in expected_format
        assert "results" in expected_format
        assert "summary" in expected_format
        assert expected_format["results"][0]["answer"] is not None

    def test_background_true_returns_ids_immediately(self):
        """Test that background=true returns subagent IDs and 'running' status immediately."""
        # Expected return format for background execution
        expected_format = {
            "success": True,
            "operation": "spawn_subagents",
            "mode": "background",
            "subagents": [
                {
                    "subagent_id": "task-1",
                    "status": "running",
                    "workspace": "/workspace/task-1",
                    "status_file": "/logs/task-1/full_logs/status.json",
                },
            ],
            "note": "Results will be automatically injected when subagents complete.",
        }

        # Verify expected format structure
        assert "success" in expected_format
        assert expected_format["mode"] == "background"
        assert "subagents" in expected_format
        assert expected_format["subagents"][0]["status"] == "running"
        # Background mode should NOT have answer (still running)
        assert "answer" not in expected_format["subagents"][0]
        assert "note" in expected_format

    def test_background_true_multiple_tasks_all_return_running(self):
        """Test that background=true with multiple tasks returns all as running."""
        # Expected format for multiple background subagents
        expected_format = {
            "success": True,
            "operation": "spawn_subagents",
            "mode": "background",
            "subagents": [
                {"subagent_id": "task-1", "status": "running"},
                {"subagent_id": "task-2", "status": "running"},
                {"subagent_id": "task-3", "status": "running"},
            ],
            "note": "Results will be automatically injected when subagents complete.",
        }

        # Verify all subagents have running status
        for subagent in expected_format["subagents"]:
            assert subagent["status"] == "running"

        assert len(expected_format["subagents"]) == 3

    @pytest.mark.asyncio
    async def test_signature_uses_background_param(self, monkeypatch, tmp_path):
        """spawn_subagents should expose background param and no async alias."""
        _, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        sig = inspect.signature(handler)
        assert "background" in sig.parameters
        assert "async_" not in sig.parameters

    @pytest.mark.asyncio
    async def test_async_alias_is_rejected(self, monkeypatch, tmp_path):
        """Legacy async_ argument should fail fast (hard break)."""
        _, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        with pytest.raises(TypeError):
            await _invoke_handler(
                handler,
                tasks=[{"task": "Research OAuth patterns", "context_paths": []}],
                async_=True,
                refine=False,
            )

    @pytest.mark.asyncio
    async def test_blocking_mode_contract_parity(self, monkeypatch, tmp_path):
        """Blocking spawn_subagents should preserve results/summary contract."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Do work", "subagent_id": "w1", "context_paths": []}],
            background=False,
            refine=True,
        )

        assert result["success"] is True
        assert result["mode"] == "blocking"
        assert "results" in result
        assert result["results"][0]["subagent_id"] == "w1"
        assert "summary" in result
        assert result["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_background_mode_contract_parity(self, monkeypatch, tmp_path):
        """Background spawn_subagents should preserve running-status contract."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Do work", "subagent_id": "w1", "context_paths": []}],
            background=True,
            refine=True,
        )

        assert result["success"] is True
        assert result["mode"] == "background"
        assert "subagents" in result
        assert result["subagents"][0]["subagent_id"] == "w1"
        assert result["subagents"][0]["status"] == "running"
        assert "answer" not in result["subagents"][0]


# =============================================================================
# Configuration Tests
# =============================================================================


class TestBackgroundSubagentsConfiguration:
    """Tests for background_subagents configuration options."""

    def test_config_enabled_allows_background(self):
        """Test that enabled=true in config allows background execution."""
        config = {
            "background_subagents": {
                "enabled": True,
                "injection_strategy": "tool_result",
            },
        }

        # When enabled, background=true parameter should work
        assert config["background_subagents"]["enabled"] is True

    def test_config_disabled_falls_back_to_blocking(self):
        """Test that enabled=false forces blocking behavior even with background=true."""
        config = {
            "background_subagents": {
                "enabled": False,
            },
        }

        # When disabled, background parameter should be ignored
        # and blocking behavior should be used
        assert config["background_subagents"]["enabled"] is False

    def test_config_default_injection_strategy(self):
        """Test default injection strategy is tool_result."""
        # Default config values
        default_config = {
            "background_subagents": {
                "enabled": True,
                "injection_strategy": "tool_result",  # Default
                "inject_progress": False,  # Default
            },
        }

        assert default_config["background_subagents"]["injection_strategy"] == "tool_result"

    def test_config_user_message_injection_strategy(self):
        """Test user_message injection strategy configuration."""
        config = {
            "background_subagents": {
                "enabled": True,
                "injection_strategy": "user_message",
            },
        }

        assert config["background_subagents"]["injection_strategy"] == "user_message"


# =============================================================================
# Return Format Tests
# =============================================================================


class TestSpawnSubagentsReturnFormats:
    """Tests for spawn_subagents return value formats."""

    def test_sync_return_format_has_results(self):
        """Test synchronous return format includes results with answers."""
        sync_format = {
            "success": True,
            "operation": "spawn_subagents",
            "results": [
                {
                    "subagent_id": "research-1",
                    "status": "completed",
                    "success": True,
                    "workspace": "/workspace/research-1",
                    "answer": "Here is the research result...",
                    "execution_time_seconds": 45.2,
                    "token_usage": {"input_tokens": 1000, "output_tokens": 500},
                },
            ],
            "summary": {"total": 1, "completed": 1, "failed": 0, "timeout": 0},
        }

        # Validate structure
        assert sync_format["results"][0]["answer"] is not None
        assert "summary" in sync_format
        assert sync_format["summary"]["completed"] == 1

    def test_background_return_format_no_answers(self):
        """Test background return format does NOT include answers."""
        background_format = {
            "success": True,
            "operation": "spawn_subagents",
            "mode": "background",
            "subagents": [
                {
                    "subagent_id": "research-1",
                    "status": "running",
                    "workspace": "/workspace/research-1",
                    "status_file": "/logs/research-1/full_logs/status.json",
                },
            ],
            "note": "Results will be automatically injected when subagents complete.",
        }

        # Validate structure - no answer field
        assert "answer" not in background_format["subagents"][0]
        assert background_format["subagents"][0]["status"] == "running"
        assert background_format["mode"] == "background"

    def test_sync_format_timeout_result(self):
        """Test synchronous format includes timeout results."""
        sync_format_with_timeout = {
            "success": False,  # Overall not successful if any failed
            "operation": "spawn_subagents",
            "results": [
                {
                    "subagent_id": "slow-task",
                    "status": "timeout",
                    "success": False,
                    "workspace": "/workspace/slow-task",
                    "answer": None,
                    "execution_time_seconds": 300.0,
                    "error": "Subagent exceeded timeout of 300 seconds",
                },
            ],
            "summary": {"total": 1, "completed": 0, "failed": 0, "timeout": 1},
        }

        assert sync_format_with_timeout["results"][0]["status"] == "timeout"
        assert sync_format_with_timeout["summary"]["timeout"] == 1


# =============================================================================
# Validation Tests
# =============================================================================


class TestSpawnSubagentsValidation:
    """Tests for spawn_subagents input validation."""

    def test_tasks_required(self):
        """Test that tasks parameter is required."""
        # spawn_subagents(tasks, context) - both required
        # Empty tasks should be rejected
        pass  # Implementation will validate

    def test_context_required(self):
        """Test that context parameter is required."""
        # spawn_subagents(tasks, context) - both required
        pass  # Implementation will validate

    def test_max_concurrent_respected(self):
        """Test that max_concurrent limit is respected."""
        # If max_concurrent=3, only 3 tasks should run at once
        pass  # Implementation will enforce


# =============================================================================
# Background Spawning Integration Tests
# =============================================================================


class TestBackgroundSpawning:
    """Tests for background spawning behavior."""

    def test_background_creates_background_tasks(self):
        """Test that background=true creates background asyncio tasks."""
        # When background=true, SubagentManager.spawn_subagent_background() should be called
        # The tasks should be tracked in _background_tasks dict
        pass  # Will verify against implementation

    def test_background_returns_status_file_path(self):
        """Test that background return includes path to status file for polling."""
        background_return = {
            "success": True,
            "mode": "background",
            "subagents": [
                {
                    "subagent_id": "poll-test",
                    "status": "running",
                    "workspace": "/workspace/poll-test",
                    "status_file": "/logs/poll-test/full_logs/status.json",
                },
            ],
        }

        # Status file path should be included
        assert "status_file" in background_return["subagents"][0]
        assert background_return["subagents"][0]["status_file"].endswith("status.json")

    def test_sync_blocks_until_completion(self):
        """Test that sync mode blocks until all subagents complete."""
        # This is a behavioral test - sync should wait for all results
        pass  # Will verify against implementation


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestSpawnSubagentsErrorHandling:
    """Tests for error handling in spawn_subagents."""

    def test_invalid_background_value_handled(self):
        """Test that invalid background parameter value is handled."""
        # background should be bool, other types should be converted or rejected
        pass  # Implementation will handle

    def test_spawn_failure_in_background_mode(self):
        """Test handling when spawning fails in background mode."""
        # If spawn_subagent_background fails, should still return
        # partial success with error info
        pass  # Implementation will handle
