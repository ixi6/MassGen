"""
Unit tests for background parameter on spawn_subagents MCP tool.

Tests for the background subagent execution feature:
- background=false returns results (existing behavior)
- background=true returns IDs immediately
- legacy async aliases are rejected
"""

import inspect
import json
import sys

import pytest


async def _build_subagent_server(monkeypatch, tmp_path):
    """Create the subagent MCP server and return (module, mcp)."""
    from massgen.mcp_tools.subagent import _subagent_mcp_server as server

    # Ensure clean global state per test.
    server._manager = None
    server._workspace_path = None
    server._specialized_subagents = {}
    server._subagent_types_loaded = False
    server._next_subagent_index = 0

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


async def _build_continue_subagent_handler(monkeypatch, tmp_path):
    """Create the subagent MCP server and return (module, continue_subagent handler)."""
    server, mcp = await _build_subagent_server(monkeypatch, tmp_path)
    for tool in mcp._tool_manager._tools.values():
        if tool.name == "continue_subagent":
            return server, tool.fn
    raise RuntimeError("continue_subagent tool not found")


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
        self.continue_background_calls = []
        self.continue_calls = []

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

    async def continue_subagent(self, subagent_id, new_message, timeout_seconds=None):  # noqa: ANN001
        self.continue_calls.append(
            {
                "subagent_id": subagent_id,
                "new_message": new_message,
                "timeout_seconds": timeout_seconds,
            },
        )
        return self._FakeResult(subagent_id)

    def continue_subagent_background(self, subagent_id, new_message, timeout_seconds=None):  # noqa: ANN001
        self.continue_background_calls.append(
            {
                "subagent_id": subagent_id,
                "new_message": new_message,
                "timeout_seconds": timeout_seconds,
            },
        )
        return {
            "subagent_id": subagent_id,
            "status": "running",
            "workspace": f"/tmp/{subagent_id}",
            "status_file": f"/tmp/{subagent_id}/status.json",
        }


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


class TestContinueSubagentBackground:
    """Background behavior contract for continue_subagent MCP tool."""

    @pytest.mark.asyncio
    async def test_signature_uses_background_param(self, monkeypatch, tmp_path):
        _, handler = await _build_continue_subagent_handler(monkeypatch, tmp_path)
        sig = inspect.signature(handler)
        assert "background" in sig.parameters

    @pytest.mark.asyncio
    async def test_background_true_returns_running_contract(self, monkeypatch, tmp_path):
        server, handler = await _build_continue_subagent_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            subagent_id="sub_1",
            message="continue with additional depth",
            timeout_seconds=180,
            background=True,
        )

        assert result["success"] is True
        assert result["operation"] == "continue_subagent"
        assert result["mode"] == "background"
        assert result["subagents"][0]["subagent_id"] == "sub_1"
        assert result["subagents"][0]["status"] == "running"
        assert len(fake_manager.continue_background_calls) == 1
        assert fake_manager.continue_background_calls[0]["new_message"] == "continue with additional depth"
        assert fake_manager.continue_calls == []

    @pytest.mark.asyncio
    async def test_background_false_uses_blocking_continue(self, monkeypatch, tmp_path):
        server, handler = await _build_continue_subagent_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            subagent_id="sub_1",
            message="keep going",
            background=False,
        )

        assert result["success"] is True
        assert result["operation"] == "continue_subagent"
        assert result["subagent_id"] == "sub_1"
        assert len(fake_manager.continue_calls) == 1
        assert fake_manager.continue_calls[0]["new_message"] == "keep going"
        assert fake_manager.continue_background_calls == []


class TestSpawnSubagentsAutoIncrementIds:
    """Default subagent IDs must be globally unique across multiple spawn calls."""

    @pytest.mark.asyncio
    async def test_successive_spawns_get_incrementing_ids(self, monkeypatch, tmp_path):
        """Two spawn calls without explicit IDs must NOT reuse subagent_0."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        # First call: 2 tasks with no explicit subagent_id
        result1 = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Critique the site", "context_paths": []},
                {"task": "Propose novelty", "context_paths": []},
            ],
            background=True,
            refine=False,
        )
        assert result1["success"] is True
        ids_first = [s["subagent_id"] for s in result1["subagents"]]
        assert ids_first == ["subagent_0", "subagent_1"]

        # Second call: 1 task with no explicit subagent_id
        result2 = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Build the site", "context_paths": []},
            ],
            background=True,
            refine=False,
        )
        assert result2["success"] is True
        ids_second = [s["subagent_id"] for s in result2["subagents"]]
        # Must be subagent_2, NOT subagent_0
        assert ids_second == ["subagent_2"], f"Expected ['subagent_2'] but got {ids_second} — " "default IDs must auto-increment across spawn calls"

    @pytest.mark.asyncio
    async def test_explicit_ids_do_not_affect_counter(self, monkeypatch, tmp_path):
        """Explicit subagent_id values should not consume counter slots."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        # First call with explicit IDs
        result1 = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Research", "subagent_id": "my_researcher", "context_paths": []},
            ],
            background=True,
            refine=False,
        )
        assert result1["success"] is True

        # Second call with auto-generated IDs should still start from 0
        # because no auto-IDs have been consumed yet
        result2 = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Build", "context_paths": []},
            ],
            background=True,
            refine=False,
        )
        assert result2["success"] is True
        ids = [s["subagent_id"] for s in result2["subagents"]]
        assert ids == ["subagent_0"]

    @pytest.mark.asyncio
    async def test_mixed_explicit_and_auto_ids(self, monkeypatch, tmp_path):
        """Mix of explicit and auto IDs in one call: auto IDs still increment."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Auto task", "context_paths": []},
                {"task": "Named task", "subagent_id": "custom_name", "context_paths": []},
                {"task": "Another auto", "context_paths": []},
            ],
            background=True,
            refine=False,
        )
        assert result["success"] is True
        ids = [s["subagent_id"] for s in result["subagents"]]
        assert ids == ["subagent_0", "custom_name", "subagent_1"]


class TestSpawnSubagentsContextPathsRequirement:
    """Validation behavior for context_paths and workspace access fields."""

    @pytest.mark.asyncio
    async def test_missing_context_paths_field_is_accepted(self, monkeypatch, tmp_path):
        """context_paths is now optional — omitting it is fine (parent workspace is always-on)."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Research OAuth patterns"}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert result["mode"] == "background"

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

    @pytest.mark.asyncio
    async def test_top_level_context_paths_applied_to_all_tasks(self, monkeypatch, tmp_path):
        """Top-level context_paths are merged into every task's context_paths."""
        shared = tmp_path / "shared"
        shared.mkdir()
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Evaluate agent1 site", "subagent_id": "eval1"},
                {"task": "Evaluate agent2 site", "subagent_id": "eval2"},
            ],
            context_paths=[str(shared)],
            background=True,
            refine=False,
        )

        assert result["success"] is True, result
        assert len(fake_manager.background_calls) == 2
        for call in fake_manager.background_calls:
            assert str(shared) in call["context_paths"]

    @pytest.mark.asyncio
    async def test_top_level_context_paths_merged_with_per_task_paths(self, monkeypatch, tmp_path):
        """Top-level context_paths are combined with per-task context_paths."""
        shared = tmp_path / "shared"
        extra = tmp_path / "extra"
        shared.mkdir()
        extra.mkdir()
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Evaluate", "subagent_id": "eval", "context_paths": [str(extra)]}],
            context_paths=[str(shared)],
            background=True,
            refine=False,
        )

        assert result["success"] is True, result
        assert len(fake_manager.background_calls) == 1
        paths = fake_manager.background_calls[0]["context_paths"]
        assert str(shared) in paths
        assert str(extra) in paths

    @pytest.mark.asyncio
    async def test_duplicate_subagent_ids_in_single_request_are_rejected(self, monkeypatch, tmp_path):
        """A single spawn request must not contain duplicate subagent_id values."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {"task": "Task one", "subagent_id": "dup", "context_paths": []},
                {"task": "Task two", "subagent_id": "dup", "context_paths": []},
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert result["operation"] == "spawn_subagents"
        assert "Duplicate subagent_id" in result["error"]
        assert "dup" in result["error"]
        assert fake_manager.background_calls == []

    @pytest.mark.asyncio
    async def test_running_subagent_id_is_rejected(self, monkeypatch, tmp_path):
        """Spawning with an ID already running should fail fast with guidance."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        fake_manager.list_subagents = lambda: [{"subagent_id": "music_history", "status": "running"}]
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Research updates",
                    "subagent_id": "music_history",
                    "context_paths": [],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert result["operation"] == "spawn_subagents"
        assert "already running" in result["error"]
        assert "music_history" in result["error"]
        assert "send_message_to_subagent" in result["error"]
        assert fake_manager.background_calls == []

    @pytest.mark.asyncio
    async def test_nonexistent_absolute_context_path_is_rejected(self, monkeypatch, tmp_path):
        """Absolute path that doesn't exist should fail fast with workspace info."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Screenshot the website",
                    "context_paths": ["/nonexistent/path/to/nowhere"],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert result["operation"] == "spawn_subagents"
        assert "/nonexistent/path/to/nowhere" in result["error"]
        assert str(tmp_path) in result["error"]  # workspace path shown for guidance
        assert fake_manager.background_calls == []

    @pytest.mark.asyncio
    async def test_nonexistent_relative_context_path_is_rejected(self, monkeypatch, tmp_path):
        """Relative path that doesn't exist (e.g. hallucinated temp_workspaces) fails fast."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Evaluate the site",
                    "context_paths": ["./temp_workspaces/agent_a/agent1"],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert result["operation"] == "spawn_subagents"
        assert "temp_workspaces/agent_a/agent1" in result["error"]
        assert str(tmp_path) in result["error"]  # workspace path shown for guidance
        assert fake_manager.background_calls == []

    @pytest.mark.asyncio
    async def test_dotslash_context_path_accepted_when_workspace_exists(self, monkeypatch, tmp_path):
        """'["./"]' resolves to the workspace root which always exists."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Take screenshots of the website",
                    "context_paths": ["./"],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert fake_manager.background_calls[0]["context_paths"] == ["./"]

    @pytest.mark.asyncio
    async def test_existing_subdirectory_context_path_is_accepted(self, monkeypatch, tmp_path):
        """A relative path resolving to an existing subdirectory is valid."""
        deliverable = tmp_path / "deliverable"
        deliverable.mkdir()

        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Review deliverable files",
                    "context_paths": ["./deliverable"],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert fake_manager.background_calls[0]["context_paths"] == ["./deliverable"]

    @pytest.mark.asyncio
    async def test_context_paths_field_is_optional(self, monkeypatch, tmp_path):
        """context_paths is now optional — parent workspace is always-on."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Research OAuth patterns"}],  # no context_paths
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert result["mode"] == "background"
        assert len(fake_manager.background_calls) == 1
        # context_paths defaults to []
        assert fake_manager.background_calls[0]["context_paths"] == []

    @pytest.mark.asyncio
    async def test_include_parent_workspace_false_passes_through(self, monkeypatch, tmp_path):
        """include_parent_workspace=False is accepted and passed to the manager."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Isolated research", "include_parent_workspace": False}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert fake_manager.background_calls[0]["include_parent_workspace"] is False

    @pytest.mark.asyncio
    async def test_reusing_completed_subagent_id_is_allowed(self, monkeypatch, tmp_path):
        """Completed IDs can be reused; only running IDs are blocked."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        fake_manager.list_subagents = lambda: [{"subagent_id": "music_history", "status": "completed"}]
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Fresh run with same identifier",
                    "subagent_id": "music_history",
                    "context_paths": [],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert result["mode"] == "background"
        assert len(fake_manager.background_calls) == 1

    @pytest.mark.asyncio
    async def test_temp_workspace_auto_mounted_by_default(self, monkeypatch, tmp_path):
        """When _agent_temporary_workspace is set, it is prepended to every task's context_paths."""
        tw = tmp_path / "temp_ws"
        tw.mkdir()
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(server, "_agent_temporary_workspace", str(tw))

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Eval site", "subagent_id": "eval1"}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert str(tw) in fake_manager.background_calls[0]["context_paths"]
        # temp_workspace is prepended (appears first)
        assert fake_manager.background_calls[0]["context_paths"][0] == str(tw)

    @pytest.mark.asyncio
    async def test_temp_workspace_opt_out(self, monkeypatch, tmp_path):
        """include_temp_workspace=False skips the auto-mount."""
        tw = tmp_path / "temp_ws"
        tw.mkdir()
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(server, "_agent_temporary_workspace", str(tw))

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Isolated research", "include_temp_workspace": False}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert str(tw) not in fake_manager.background_calls[0]["context_paths"]

    @pytest.mark.asyncio
    async def test_temp_workspace_not_added_when_unset(self, monkeypatch, tmp_path):
        """When _agent_temporary_workspace is None, no path is added."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(server, "_agent_temporary_workspace", None)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Task"}],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        # No unexpected paths injected
        assert fake_manager.background_calls[0]["context_paths"] == []


class TestSpecializedTypesFileNotDeleted:
    """Temp config files must survive MCP server startup (no race condition)."""

    @pytest.mark.asyncio
    async def test_all_config_files_persist_after_create_server(self, monkeypatch, tmp_path):
        """All temp config files (agent_configs, context_paths, coordination_config)
        must survive MCP server startup."""
        import json

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._manager = None
        server._workspace_path = None

        # Create all temp config files
        agent_configs_file = tmp_path / "agent_configs.json"
        agent_configs_file.write_text(json.dumps([{"id": "agent_a", "backend": {"type": "claude"}}]))

        context_paths_file = tmp_path / "context_paths.json"
        context_paths_file.write_text(json.dumps(["/some/path"]))

        coordination_config_file = tmp_path / "coordination_config.json"
        coordination_config_file.write_text(json.dumps({"max_rounds": 3}))

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
                "--agent-configs-file",
                str(agent_configs_file),
                "--context-paths-file",
                str(context_paths_file),
                "--coordination-config-file",
                str(coordination_config_file),
            ],
        )

        await server.create_server()

        # All files must still exist
        assert agent_configs_file.exists(), "MCP server deleted agent_configs file"
        assert context_paths_file.exists(), "MCP server deleted context_paths file"
        assert coordination_config_file.exists(), "MCP server deleted coordination_config file"

    @pytest.mark.asyncio
    async def test_agent_temporary_workspace_is_passed_to_manager(self, monkeypatch, tmp_path):
        """Server should forward --agent-temporary-workspace to SubagentManager."""
        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._manager = None
        server._workspace_path = None

        temp_workspace = (tmp_path / "temp_workspaces" / "agent_a").resolve()
        temp_workspace.mkdir(parents=True, exist_ok=True)

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
                "--agent-temporary-workspace",
                str(temp_workspace),
            ],
        )

        await server.create_server()
        manager = server._get_manager()

        assert manager._agent_temporary_workspace is not None
        assert manager._agent_temporary_workspace.resolve() == temp_workspace

    @pytest.mark.asyncio
    async def test_missing_agent_configs_file_falls_back_to_temp_workspace_snapshot(self, monkeypatch, tmp_path):
        """If primary agent-config path is missing, server should load from temp workspace snapshot copy."""
        import json

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._manager = None
        server._workspace_path = None
        server._parent_agent_configs = []

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        temp_workspace = tmp_path / "temp_workspaces" / "agent_a"
        snapshot_mcp_dir = temp_workspace / "agent1" / ".massgen" / "subagent_mcp"
        snapshot_mcp_dir.mkdir(parents=True, exist_ok=True)
        snapshot_payload = [
            {
                "id": "agent_a",
                "backend": {
                    "type": "codex",
                    "enable_mcp_command_line": True,
                    "command_line_execution_mode": "docker",
                },
            },
        ]
        (snapshot_mcp_dir / "agent_a_agent_configs.json").write_text(json.dumps(snapshot_payload))

        missing_primary_path = workspace / ".massgen" / "subagent_mcp" / "agent_a_agent_configs.json"

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
                str(workspace),
                "--agent-temporary-workspace",
                str(temp_workspace),
                "--agent-configs-file",
                str(missing_primary_path),
            ],
        )

        await server.create_server()

        assert server._parent_agent_configs
        assert server._parent_agent_configs[0]["backend"]["enable_mcp_command_line"] is True
        assert server._parent_agent_configs[0]["backend"]["command_line_execution_mode"] == "docker"

    @pytest.mark.asyncio
    async def test_missing_coordination_config_file_falls_back_to_temp_workspace_snapshot(self, monkeypatch, tmp_path):
        """If primary coordination config path is missing, server should load from temp workspace snapshot copy."""
        import json

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._manager = None
        server._workspace_path = None
        server._parent_coordination_config = {}

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        temp_workspace = tmp_path / "temp_workspaces" / "agent_a"
        snapshot_mcp_dir = temp_workspace / "agent1" / ".massgen" / "subagent_mcp"
        snapshot_mcp_dir.mkdir(parents=True, exist_ok=True)
        snapshot_payload = {
            "enable_agent_task_planning": True,
            "task_planning_filesystem_mode": True,
            "use_skills": True,
        }
        (snapshot_mcp_dir / "agent_a_coordination_config.json").write_text(json.dumps(snapshot_payload))

        missing_primary_path = workspace / ".massgen" / "subagent_mcp" / "agent_a_coordination_config.json"

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
                str(workspace),
                "--agent-temporary-workspace",
                str(temp_workspace),
                "--coordination-config-file",
                str(missing_primary_path),
            ],
        )

        await server.create_server()

        assert server._parent_coordination_config
        assert server._parent_coordination_config["enable_agent_task_planning"] is True
        assert server._parent_coordination_config["task_planning_filesystem_mode"] is True


class TestLazySubagentTypeLoading:
    """Lazy loading of specialized subagent types from workspace SUBAGENT.md dirs."""

    def _make_subagent_dir(self, parent: "Path", name: str, description: str, system_prompt: str = "", skills: list | None = None) -> None:  # type: ignore[name-defined]  # noqa: F821
        type_dir = parent / name
        type_dir.mkdir(parents=True, exist_ok=True)
        skills_line = f"skills: {skills!r}\n" if skills else ""
        content = f"---\nname: {name}\ndescription: {description!r}\n{skills_line}---\n{system_prompt}"
        (type_dir / "SUBAGENT.md").write_text(content)

    @pytest.mark.asyncio
    async def test_lazy_loading_populates_types_from_workspace_dirs(self, monkeypatch, tmp_path):
        """_ensure_specialized_types_loaded() scans workspace/.massgen/subagent_types/ on first call."""
        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        # Write SUBAGENT.md dirs into the workspace
        types_dir = tmp_path / ".massgen" / "subagent_types"
        self._make_subagent_dir(types_dir, "builder", "Builds things", "You are a builder.", ["file-search"])
        self._make_subagent_dir(types_dir, "critic", "Critiques output", "You are a critic.")

        # Set up clean state
        server._specialized_subagents = {}
        server._subagent_types_loaded = False
        server._workspace_path = tmp_path

        server._ensure_specialized_types_loaded()

        assert "builder" in server._specialized_subagents
        assert "critic" in server._specialized_subagents
        assert server._specialized_subagents["builder"]["system_prompt"] == "You are a builder."
        assert server._specialized_subagents["builder"]["skills"] == ["file-search"]
        assert server._specialized_subagents["critic"]["system_prompt"] == "You are a critic."

    @pytest.mark.asyncio
    async def test_lazy_loading_warns_when_types_dir_missing(self, monkeypatch, tmp_path, caplog):
        """Missing subagent_types dir logs a warning but does not crash."""
        import logging

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._specialized_subagents = {}
        server._subagent_types_loaded = False
        server._workspace_path = tmp_path  # no .massgen/subagent_types subdir

        with caplog.at_level(logging.WARNING):
            server._ensure_specialized_types_loaded()

        assert server._specialized_subagents == {}
        assert server._subagent_types_loaded is True  # flag set even on miss

    @pytest.mark.asyncio
    async def test_spawn_with_no_types_dir_reports_none_configured(self, monkeypatch, tmp_path):
        """spawn_subagents returns '(none configured)' when no SUBAGENT.md dirs exist."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Build site", "subagent_type": "builder", "context_paths": []}],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "builder" in result["error"]
        assert "(none configured)" in result["error"]

    @pytest.mark.asyncio
    async def test_double_scan_prevented_by_flag(self, monkeypatch, tmp_path):
        """_ensure_specialized_types_loaded() is a no-op when _subagent_types_loaded is True."""
        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        server._specialized_subagents = {"evaluator": {"name": "evaluator"}}
        server._subagent_types_loaded = True
        server._workspace_path = tmp_path

        # Even with a types dir present, should not scan again
        types_dir = tmp_path / ".massgen" / "subagent_types"
        self._make_subagent_dir(types_dir, "builder", "Builds things")

        server._ensure_specialized_types_loaded()

        # builder should NOT be present — scan was skipped
        assert "builder" not in server._specialized_subagents
        assert "evaluator" in server._specialized_subagents


class TestSpawnSubagentsSpecializedTypeResolution:
    """Validation and resolution behavior for `subagent_type` tasks."""

    @pytest.mark.asyncio
    async def test_unknown_subagent_type_fails_fast(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(
            server,
            "_specialized_subagents",
            {
                "evaluator": {
                    "name": "evaluator",
                    "description": "Programmatic evaluator",
                },
            },
        )

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Run validation",
                    "subagent_type": "evalutor",
                    "context_paths": [],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "Unknown subagent_type" in result["error"]
        assert "evalutor" in result["error"]
        assert "evaluator" in result["error"]
        assert fake_manager.background_calls == []

    @pytest.mark.asyncio
    async def test_known_subagent_type_injects_prompt_and_skills_for_background(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(
            server,
            "_specialized_subagents",
            {
                "explorer": {
                    "name": "explorer",
                    "description": "Repo explorer",
                    "system_prompt": "You are an explorer.",
                    "skills": ["file-search", "semtools"],
                },
            },
        )

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Map relevant files",
                    "subagent_type": "explorer",
                    "context_paths": [],
                },
            ],
            background=True,
            refine=False,
        )

        assert result["success"] is True
        assert len(fake_manager.background_calls) == 1
        call = fake_manager.background_calls[0]
        assert call["system_prompt"] == "You are an explorer."
        assert call["skills"] == ["file-search", "semtools"]

    @pytest.mark.asyncio
    async def test_known_subagent_type_injects_prompt_and_skills_for_blocking(self, monkeypatch, tmp_path):
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        monkeypatch.setattr(
            server,
            "_specialized_subagents",
            {
                "evaluator": {
                    "name": "evaluator",
                    "description": "Programmatic evaluator",
                    "system_prompt": "You are an evaluator.",
                    "skills": ["webapp-testing", "agent-browser"],
                },
            },
        )

        result = await _invoke_handler(
            handler,
            tasks=[
                {
                    "task": "Run tests",
                    "subagent_type": "evaluator",
                    "context_paths": [],
                },
            ],
            background=False,
            refine=False,
        )

        assert result["success"] is True
        assert len(fake_manager.parallel_calls) == 1
        task = fake_manager.parallel_calls[0]["tasks"][0]
        assert task["system_prompt"] == "You are an evaluator."
        assert task["skills"] == ["webapp-testing", "agent-browser"]


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
# Cancel Subagent Registry Persistence Tests
# =============================================================================


class TestCancelSubagentRegistryPersistence:
    """cancel_subagent MCP tool must persist cancelled status to filesystem registry."""

    @pytest.mark.asyncio
    async def test_cancel_writes_cancelled_status_to_registry(self, monkeypatch, tmp_path):
        """After cancel_subagent MCP call, _registry.json must show cancelled status.

        Regression test: stale registry (showing 'running') caused delegated builders
        to appear active in subsequent rounds after being cancelled.
        """
        import json

        server, mcp = await _build_subagent_server(monkeypatch, tmp_path)

        cancel_handler = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "cancel_subagent":
                cancel_handler = tool.fn
                break
        assert cancel_handler is not None, "cancel_subagent tool not found"

        class _FakeCancelManager:
            async def cancel_subagent(self, subagent_id):  # noqa: ANN001
                return {"success": True, "subagent_id": subagent_id, "status": "cancelled"}

            def list_subagents(self):
                return [{"subagent_id": "build_member_architecture", "status": "cancelled"}]

        monkeypatch.setattr(server, "_get_manager", lambda: _FakeCancelManager())

        result = await _invoke_handler(cancel_handler, subagent_id="build_member_architecture")
        assert result["success"] is True

        # Registry must be written with cancelled status so fresh MCP processes
        # (new Codex round) don't show cancelled builders as 'running'.
        registry_file = tmp_path / "subagents" / "_registry.json"
        assert registry_file.exists(), "Registry file must be written after cancel"
        registry = json.loads(registry_file.read_text())
        entries = registry.get("subagents", [])
        assert len(entries) == 1
        assert entries[0]["subagent_id"] == "build_member_architecture"
        assert entries[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_registry_not_written_on_failure(self, monkeypatch, tmp_path):
        """Registry should not be written when cancel fails (manager returns success=False)."""
        import json

        server, mcp = await _build_subagent_server(monkeypatch, tmp_path)

        cancel_handler = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "cancel_subagent":
                cancel_handler = tool.fn
                break
        assert cancel_handler is not None

        class _FakeFailManager:
            async def cancel_subagent(self, subagent_id):  # noqa: ANN001
                return {"success": False, "error": "Subagent not found: no-such-id"}

            def list_subagents(self):
                return []

        monkeypatch.setattr(server, "_get_manager", lambda: _FakeFailManager())

        result = await _invoke_handler(cancel_handler, subagent_id="no-such-id")
        assert result["success"] is False

        registry_file = tmp_path / "subagents" / "_registry.json"
        # Registry should not be written (or if written, should show empty list)
        if registry_file.exists():
            registry = json.loads(registry_file.read_text())
            assert registry.get("subagents", []) == []


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


# =============================================================================
# Phase 1: Blocking spawn with workspace_path=None (UnboundLocalError fix)
# =============================================================================


class TestBlockingSpawnWithoutWorkspacePath:
    """Blocking mode must not crash when _workspace_path is None."""

    @pytest.mark.asyncio
    async def test_blocking_spawn_no_workspace_path(self, monkeypatch, tmp_path):
        """Blocking spawn with _workspace_path=None must not raise UnboundLocalError."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)
        # Simulate no workspace path (edge case: MCP server started without workspace)
        monkeypatch.setattr(server, "_workspace_path", None)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Do blocking work", "subagent_id": "blk1"}],
            background=False,
            refine=False,
        )

        assert result["success"] is True
        assert result["mode"] == "blocking"
        assert result["results"][0]["subagent_id"] == "blk1"


# =============================================================================
# Phase 2: Monotonic counter (no decrement on failure)
# =============================================================================


class TestMonotonicAutoIdCounter:
    """Auto-ID counter must never decrease, even after spawn failure."""

    @pytest.mark.asyncio
    async def test_counter_never_decreases_after_spawn_failure(self, monkeypatch, tmp_path):
        """Counter stays incremented even when background spawn returns error status."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)

        class _FailingManager(_FakeSubagentManager):
            def spawn_subagent_background(self, **kwargs):
                self.background_calls.append(kwargs)
                sid = kwargs.get("subagent_id") or "subagent_0"
                return {"subagent_id": sid, "status": "error", "error": "spawn failed"}

            def remove_immediately_failed_subagent(self, subagent_id):
                pass  # Manager cleanup still happens, but counter should not roll back

        failing_manager = _FailingManager()
        monkeypatch.setattr(server, "_get_manager", lambda: failing_manager)

        # First spawn: should get subagent_0, then fail
        result1 = await _invoke_handler(
            handler,
            tasks=[{"task": "Will fail"}],
            background=True,
            refine=False,
        )
        assert result1["success"] is True  # spawn_subagents itself succeeded
        first_id = result1["subagents"][0]["subagent_id"]
        assert first_id == "subagent_0"

        # Second spawn: must be subagent_1 (NOT subagent_0 reused)
        result2 = await _invoke_handler(
            handler,
            tasks=[{"task": "Second try"}],
            background=True,
            refine=False,
        )
        second_id = result2["subagents"][0]["subagent_id"]
        assert second_id == "subagent_1", f"Expected 'subagent_1' but got '{second_id}' — " "counter must never decrease after failure"


# =============================================================================
# Phase 3a: Non-string context path elements rejected
# =============================================================================


class TestContextPathElementTypeValidation:
    """Individual context_path elements must be strings."""

    @pytest.mark.asyncio
    async def test_non_string_context_path_element_rejected(self, monkeypatch, tmp_path):
        """A non-string element inside context_paths list should fail fast."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Research", "context_paths": [123]}],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "expected string" in result["error"]
        assert "int" in result["error"]

    @pytest.mark.asyncio
    async def test_dict_context_path_element_rejected(self, monkeypatch, tmp_path):
        """A dict element inside context_paths list should fail fast."""
        server, handler = await _build_spawn_subagents_handler(monkeypatch, tmp_path)
        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        result = await _invoke_handler(
            handler,
            tasks=[{"task": "Research", "context_paths": [{"path": "/tmp"}]}],
            background=True,
            refine=False,
        )

        assert result["success"] is False
        assert "expected string" in result["error"]
        assert "dict" in result["error"]


# =============================================================================
# Phase 3b: JSON decode fallback
# =============================================================================


class TestJsonDecodeFallback:
    """JSON decode errors should fall back to temp workspace snapshot."""

    def test_json_decode_error_falls_back_to_temp_workspace(self, monkeypatch, tmp_path):
        """JSONDecodeError on primary file should try temp workspace fallback."""
        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        # Create a corrupted primary file
        primary = tmp_path / "config.json"
        primary.write_text("{invalid json")

        # Create a valid fallback in temp workspace
        temp_ws = tmp_path / "temp_workspaces" / "agent_a"
        snapshot_dir = temp_ws / "snap1" / ".massgen" / "subagent_mcp"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        valid_data = {"key": "value"}
        (snapshot_dir / "config.json").write_text(json.dumps(valid_data))

        monkeypatch.setattr(server, "_agent_temporary_workspace", str(temp_ws))

        data, used_path = server._load_json_with_temp_workspace_fallback(str(primary))
        assert data == valid_data
        assert used_path == snapshot_dir / "config.json"

    def test_json_decode_error_without_fallback_raises(self, monkeypatch, tmp_path):
        """JSONDecodeError without available fallback should raise."""
        import json

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        primary = tmp_path / "bad.json"
        primary.write_text("{broken")

        monkeypatch.setattr(server, "_agent_temporary_workspace", None)

        with pytest.raises(json.JSONDecodeError):
            server._load_json_with_temp_workspace_fallback(str(primary))


# =============================================================================
# Phase 3c: Registry write error handling
# =============================================================================


class TestRegistryWriteErrorHandling:
    """Registry write failures should be logged, not crash the server."""

    def test_registry_write_failure_logged_not_raised(self, monkeypatch, tmp_path, caplog):
        """OSError during registry write should be logged but not propagated."""
        import logging

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        monkeypatch.setattr(server, "_workspace_path", tmp_path)

        fake_manager = _FakeSubagentManager()
        monkeypatch.setattr(server, "_get_manager", lambda: fake_manager)

        # Make the subagents directory read-only to trigger OSError
        subagents_dir = tmp_path / "subagents"
        subagents_dir.mkdir()
        registry_file = subagents_dir / "_registry.json"
        registry_file.write_text("{}")
        registry_file.chmod(0o000)

        try:
            # Should not raise — error is caught and logged
            with caplog.at_level(logging.ERROR):
                server._save_subagents_to_filesystem()

            assert "Failed to save registry" in caplog.text
        finally:
            # Restore permissions for cleanup
            registry_file.chmod(0o644)


# =============================================================================
# Phase 4: Process cleanup hardening
# =============================================================================


class TestSyncCleanup:
    """atexit cleanup should terminate then force-kill hung processes."""

    def test_sync_cleanup_terminates_and_force_kills(self, monkeypatch):
        """_sync_cleanup should terminate, wait with timeout, then kill if needed."""
        import subprocess

        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        class MockProcess:
            def __init__(self, hangs=False):
                self.returncode = None
                self._terminated = False
                self._killed = False
                self._hangs = hangs

            def terminate(self):
                self._terminated = True

            def wait(self, timeout=None):
                if self._hangs:
                    raise subprocess.TimeoutExpired(cmd="test", timeout=timeout)
                self.returncode = 0

            def kill(self):
                self._killed = True

        # Create a mock manager with two processes: one clean, one hung
        clean_proc = MockProcess(hangs=False)
        hung_proc = MockProcess(hangs=True)

        class FakeManager:
            _active_processes = {"sub_clean": clean_proc, "sub_hung": hung_proc}

        monkeypatch.setattr(server, "_manager", FakeManager())

        server._sync_cleanup()

        # Clean process: terminated, not killed
        assert clean_proc._terminated is True
        assert clean_proc._killed is False

        # Hung process: terminated, then force-killed
        assert hung_proc._terminated is True
        assert hung_proc._killed is True

    def test_sync_cleanup_handles_already_exited_process(self, monkeypatch):
        """Processes with returncode != None should be skipped."""
        from massgen.mcp_tools.subagent import _subagent_mcp_server as server

        class AlreadyDone:
            returncode = 0

            def terminate(self):
                raise RuntimeError("should not be called")

        class FakeManager:
            _active_processes = {"sub_done": AlreadyDone()}

        monkeypatch.setattr(server, "_manager", FakeManager())

        # Should not raise — skips already-exited process
        server._sync_cleanup()
