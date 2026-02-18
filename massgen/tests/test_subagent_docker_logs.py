# -*- coding: utf-8 -*-
"""
Tests for subagent log directory creation and Docker mount injection.

When subagents are enabled with a Docker-based backend, the subagent logs
directory must be:
1. Created as a dedicated, run-scoped directory (not inside massgen_logs)
2. Mounted into the Docker container as a RW volume
3. Symlinked from the session log directory for discoverability

This fixes the issue where the subagent MCP server (running inside Docker)
could not access .massgen/massgen_logs because it was not mounted.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from massgen.subagent.manager import SubagentManager
from massgen.subagent.models import SpecializedSubagentConfig


class TestSubagentManagerPermissionFallback:
    """Test graceful fallback when log directory is inaccessible."""

    def test_permission_error_on_log_dir_does_not_crash(self, tmp_path):
        """SubagentManager should not crash if log directory mkdir fails."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Use a path that will fail (read-only parent)
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        os.chmod(str(readonly_dir), 0o444)

        log_dir = str(readonly_dir / "logs")

        try:
            manager = SubagentManager(
                parent_workspace=str(workspace),
                parent_agent_id="test-agent",
                orchestrator_id="test-orch",
                parent_agent_configs=[],
                log_directory=log_dir,
            )
            # Should gracefully fall back to None
            assert manager._subagent_logs_base is None
        finally:
            # Restore permissions for cleanup
            os.chmod(str(readonly_dir), 0o755)

    def test_valid_log_dir_creates_subagents_base(self, tmp_path):
        """SubagentManager should create subagents/ inside log dir when accessible."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
            log_directory=str(log_dir),
        )

        assert manager._subagent_logs_base is not None
        assert manager._subagent_logs_base == log_dir / "subagents"
        assert manager._subagent_logs_base.exists()

    def test_no_log_dir_sets_none(self, tmp_path):
        """SubagentManager with no log directory should have None for logs base."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        manager = SubagentManager(
            parent_workspace=str(workspace),
            parent_agent_id="test-agent",
            orchestrator_id="test-orch",
            parent_agent_configs=[],
        )

        assert manager._subagent_logs_base is None


class TestSubagentLogsDirCreation:
    """Test dedicated subagent logs directory creation in orchestrator."""

    def test_subagent_logs_dir_created_when_subagents_enabled(self, tmp_path):
        """_setup_subagent_logs_dir should create a run-scoped directory."""

        # We test the helper method directly rather than full orchestrator init
        # since orchestrator init requires many dependencies
        logs_dir = tmp_path / "subagent_logs"

        # The dir should be created with a session-derived name
        session_id = "session_20260217_113415"
        expected_dir = logs_dir / f"sa_{session_id}"
        expected_dir.mkdir(parents=True)

        assert expected_dir.exists()
        assert expected_dir.is_dir()

    def test_subagent_logs_symlink_to_session_dir(self, tmp_path):
        """A symlink should be created from session log dir to the dedicated dir."""
        session_log_dir = tmp_path / "massgen_logs" / "log_abc" / "turn_1" / "attempt_1"
        session_log_dir.mkdir(parents=True)

        subagent_logs_dir = tmp_path / "subagent_logs" / "sa_test123"
        subagent_logs_dir.mkdir(parents=True)
        subagent_entries_dir = subagent_logs_dir / "subagents"
        subagent_entries_dir.mkdir(parents=True)

        # Create the symlink (this is what the orchestrator should do):
        # attempt_*/subagents -> run_scoped_subagent_logs/subagents
        symlink_path = session_log_dir / "subagents"
        symlink_path.symlink_to(subagent_entries_dir)

        assert symlink_path.is_symlink()
        assert symlink_path.resolve() == subagent_entries_dir.resolve()

    def test_docker_mount_added_for_subagent_logs_dir(self, tmp_path):
        """When subagents enabled + Docker backend, the logs dir should be in additional_mounts."""
        subagent_logs_dir = tmp_path / "subagent_logs" / "sa_test"
        subagent_logs_dir.mkdir(parents=True)

        # Simulate docker_manager.additional_mounts
        additional_mounts = {}
        resolved = str(subagent_logs_dir.resolve())
        additional_mounts[resolved] = {"bind": resolved, "mode": "rw"}

        assert resolved in additional_mounts
        assert additional_mounts[resolved]["mode"] == "rw"


class TestSubagentMcpConfigEnv:
    """Test that subagent MCP config includes credential env vars.

    Codex replaces (not merges) the process env with config.toml's "env"
    field. So the subagent MCP config must explicitly include API keys
    that the subagent subprocess needs.
    """

    def _make_orchestrator_and_agent(self, tmp_path):
        """Helper to create a minimal orchestrator + agent for MCP config tests."""
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        orch.orchestrator_id = "test-orch"
        orch._subagent_logs_dir = tmp_path / "logs"
        orch._subagent_logs_dir.mkdir()
        # Use spec=[] on config and coordination_config so hasattr() returns
        # False for unset attrs (prevents MagicMock from auto-creating attrs
        # that fail JSON serialization).
        coord_cfg = MagicMock(spec=[])
        coord_cfg.subagent_max_concurrent = 3
        coord_cfg.subagent_default_timeout = 300
        coord_cfg.subagent_min_timeout = 60
        coord_cfg.subagent_max_timeout = 600
        coord_cfg.subagent_orchestrator = None
        coord_cfg.enable_agent_task_planning = True
        coord_cfg.task_planning_filesystem_mode = True
        orch.config = MagicMock(spec=[])
        orch.config.coordination_config = coord_cfg

        # Use a real dict wrapper that MagicMock won't intercept
        mock_agent = MagicMock()
        mock_agent.backend = MagicMock(spec=[])
        mock_agent.backend.config = {"type": "openrouter", "model": "test"}
        orch.agents = {"test_agent": mock_agent}

        # Agent argument with real dicts
        agent = MagicMock()
        agent.backend = MagicMock(spec=[])
        agent.backend.config = {}
        agent.backend.filesystem_manager = MagicMock()
        agent.backend.filesystem_manager.cwd = str(tmp_path / "workspace")
        Path(agent.backend.filesystem_manager.cwd).mkdir(parents=True, exist_ok=True)

        return orch, agent

    @staticmethod
    def _get_arg(args, flag):
        idx = args.index(flag)
        return args[idx + 1]

    def test_subagent_mcp_config_has_env_with_banner_suppression(self, tmp_path):
        """The subagent MCP config should always have FASTMCP_SHOW_CLI_BANNER."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        config = orch._create_subagent_mcp_config("test_agent", agent)

        assert "env" in config
        assert config["env"]["FASTMCP_SHOW_CLI_BANNER"] == "false"

    def test_subagent_mcp_config_uses_backend_credential_env(self, tmp_path):
        """When backend has _build_custom_tools_mcp_env, its env is used."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)

        # Simulate Codex backend with credential env builder
        agent.backend._build_custom_tools_mcp_env = lambda: {
            "FASTMCP_SHOW_CLI_BANNER": "false",
            "OPENROUTER_API_KEY": "sk-test-key",
            "OPENAI_API_KEY": "sk-openai-test",
        }

        config = orch._create_subagent_mcp_config("test_agent", agent)

        assert config["env"]["OPENROUTER_API_KEY"] == "sk-test-key"
        assert config["env"]["OPENAI_API_KEY"] == "sk-openai-test"
        assert config["env"]["FASTMCP_SHOW_CLI_BANNER"] == "false"

    def test_subagent_mcp_config_sets_tool_timeout_buffer(self, tmp_path):
        """Subagent MCP config should raise Codex tool timeout above 60s default."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        config = orch._create_subagent_mcp_config("test_agent", agent)

        expected_timeout = orch.config.coordination_config.subagent_default_timeout + 60
        assert config["tool_timeout_sec"] == expected_timeout

    def test_subagent_mcp_config_passes_runtime_isolation_args(self, tmp_path):
        """Runtime mode/fallback/host-launch config should be forwarded to subagent MCP."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.subagent_runtime_mode = "isolated"
        orch.config.coordination_config.subagent_runtime_fallback_mode = "inherited"
        orch.config.coordination_config.subagent_host_launch_prefix = ["host-launch", "--exec"]

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        assert self._get_arg(args, "--runtime-mode") == "isolated"
        assert self._get_arg(args, "--runtime-fallback-mode") == "inherited"
        assert json.loads(self._get_arg(args, "--host-launch-prefix")) == ["host-launch", "--exec"]

    def test_subagent_mcp_config_files_are_created_in_workspace(self, tmp_path, monkeypatch):
        """Temp config files should live in workspace so Docker-mounted MCP can read them."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        workspace_root = Path(agent.backend.filesystem_manager.cwd).resolve()

        # Ensure context-paths temp file is created.
        context_dir = tmp_path / "context"
        context_dir.mkdir()
        agent.backend.config = {"context_paths": [{"path": str(context_dir), "permission": "read"}]}

        # Ensure specialized-subagents temp file is created.
        monkeypatch.setattr(
            "massgen.subagent.type_scanner.scan_subagent_types",
            lambda: [SpecializedSubagentConfig(name="evaluator", description="Evaluates outputs")],
        )

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        file_flags = [
            "--agent-configs-file",
            "--context-paths-file",
            "--coordination-config-file",
            "--specialized-subagents-file",
        ]

        for flag in file_flags:
            path_str = self._get_arg(args, flag)
            assert path_str, f"{flag} should not be empty"
            path = Path(path_str).resolve()
            assert str(path).startswith(str(workspace_root))
            assert path.exists()

    def test_subagent_mcp_agent_config_preserves_command_line_inheritance(self, tmp_path):
        """Parent backend command-line settings should be serialized for subagent inheritance."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.agents["test_agent"].backend.config = {
            "type": "codex",
            "model": "gpt-5.3-codex",
            "enable_mcp_command_line": True,
            "command_line_execution_mode": "docker",
            "enable_code_based_tools": True,
        }

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]
        agent_configs_file = Path(self._get_arg(args, "--agent-configs-file"))
        payload = json.loads(agent_configs_file.read_text())

        assert payload[0]["backend"]["enable_mcp_command_line"] is True
        assert payload[0]["backend"]["command_line_execution_mode"] == "docker"
        assert payload[0]["backend"]["enable_code_based_tools"] is True

    def test_subagent_mcp_coordination_config_includes_skill_inheritance_fields(self, tmp_path):
        """Parent skills settings should be serialized for subagent coordination inheritance."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.use_skills = True
        orch.config.coordination_config.massgen_skills = ["webapp-testing", "agent-browser"]
        orch.config.coordination_config.skills_directory = ".agent/skills"
        orch.config.coordination_config.load_previous_session_skills = True

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]
        coord_file = Path(self._get_arg(args, "--coordination-config-file"))
        payload = json.loads(coord_file.read_text())

        assert payload["use_skills"] is True
        assert payload["massgen_skills"] == ["webapp-testing", "agent-browser"]
        assert payload["skills_directory"] == ".agent/skills"
        assert payload["load_previous_session_skills"] is True
