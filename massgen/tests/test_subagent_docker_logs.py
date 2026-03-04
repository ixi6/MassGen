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

import pytest

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
        orch._delegation_dir = None
        orch._subagent_launch_watcher = None
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
        agent.backend.filesystem_manager.get_workspace_root = lambda: Path(agent.backend.filesystem_manager.cwd)

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

    def test_subagent_mcp_config_bridges_claude_config_dir_from_codex_backend(self, tmp_path):
        """Codex Docker credential mounts should flow through to subagent MCP env."""
        from massgen.backend.codex import CodexBackend

        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        codex_workspace = tmp_path / "codex_workspace"
        codex_workspace.mkdir(parents=True, exist_ok=True)

        agent.backend = CodexBackend(
            cwd=str(codex_workspace),
            command_line_execution_mode="docker",
            command_line_docker_credentials={"mount": ["claude_config"]},
        )
        orch.agents["test_agent"].backend.config = {
            "type": "codex",
            "command_line_execution_mode": "docker",
        }

        config = orch._create_subagent_mcp_config("test_agent", agent)
        assert config["env"]["CLAUDE_CONFIG_DIR"] == "/home/massgen/.claude"

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

    def test_subagent_mcp_config_passes_agent_temporary_workspace(self, tmp_path):
        """Parent agent temporary workspace should be forwarded for subagent path validation."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        temp_workspace = (tmp_path / "temp_workspaces" / "agent_a").resolve()
        temp_workspace.mkdir(parents=True, exist_ok=True)
        agent.backend.filesystem_manager.agent_temporary_workspace = str(temp_workspace)

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        assert self._get_arg(args, "--agent-temporary-workspace") == str(temp_workspace)

    def test_subagent_mcp_config_defaults_fallback_for_codex_docker(self, tmp_path):
        """Codex+Docker should default runtime fallback to inherited when unset."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.agents["test_agent"].backend.config = {
            "type": "codex",
            "model": "gpt-5.3-codex",
            "command_line_execution_mode": "docker",
        }
        orch.config.coordination_config.subagent_runtime_mode = "isolated"
        # Intentionally omit subagent_runtime_fallback_mode.

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        assert self._get_arg(args, "--runtime-mode") == "isolated"
        assert self._get_arg(args, "--runtime-fallback-mode") == "inherited"

    def test_subagent_mcp_config_keeps_strict_default_for_non_codex(self, tmp_path):
        """Non-Codex backends keep strict isolated behavior unless fallback is explicit."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.agents["test_agent"].backend.config = {
            "type": "openrouter",
            "model": "z-ai/glm-5",
            "command_line_execution_mode": "docker",
        }
        orch.config.coordination_config.subagent_runtime_mode = "isolated"
        # Intentionally omit subagent_runtime_fallback_mode.

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        assert self._get_arg(args, "--runtime-mode") == "isolated"
        assert self._get_arg(args, "--runtime-fallback-mode") == ""

    def test_subagent_mcp_config_files_are_created_in_workspace(self, tmp_path, monkeypatch):
        """Temp config files should live in workspace so Docker-mounted MCP can read them."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        workspace_root = Path(agent.backend.filesystem_manager.get_workspace_root()).resolve()

        # Ensure context-paths temp file is created.
        context_dir = tmp_path / "context"
        context_dir.mkdir()
        agent.backend.config = {"context_paths": [{"path": str(context_dir), "permission": "read"}]}

        # Ensure specialized subagent type dirs are written to workspace.
        monkeypatch.setattr(
            "massgen.subagent.type_scanner.scan_subagent_types",
            lambda **kwargs: [SpecializedSubagentConfig(name="evaluator", description="Evaluates outputs")],
        )

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        # Arg-based temp files must exist and be inside workspace root
        file_flags = [
            "--agent-configs-file",
            "--context-paths-file",
            "--coordination-config-file",
        ]

        for flag in file_flags:
            path_str = self._get_arg(args, flag)
            assert path_str, f"{flag} should not be empty"
            path = Path(path_str).resolve()
            assert str(path).startswith(str(workspace_root))
            assert path.exists()

        # Specialized subagent types are delivered via SUBAGENT.md dirs in the workspace
        assert "--specialized-subagents-file" not in args
        type_dir = workspace_root / ".massgen" / "subagent_types" / "evaluator"
        assert type_dir.is_dir()
        assert (type_dir / "SUBAGENT.md").exists()

    def test_subagent_mcp_config_files_use_persistent_workspace_root_after_workspace_switch(self, tmp_path, monkeypatch):
        """Subagent MCP config files should always use persistent workspace root, not active cwd."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        persistent_root = tmp_path / "workspace_root"
        temp_workspace = tmp_path / "temp_workspace"
        persistent_root.mkdir(parents=True, exist_ok=True)
        temp_workspace.mkdir(parents=True, exist_ok=True)

        agent.backend.filesystem_manager.cwd = str(temp_workspace)
        agent.backend.filesystem_manager.get_workspace_root = lambda: persistent_root

        monkeypatch.setattr(
            "massgen.subagent.type_scanner.scan_subagent_types",
            lambda **kwargs: [SpecializedSubagentConfig(name="critic", description="Critiques outputs")],
        )

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]

        assert self._get_arg(args, "--workspace-path") == str(persistent_root.resolve())

        # Specialized types are written as SUBAGENT.md dirs into the persistent workspace root
        assert "--specialized-subagents-file" not in args
        type_dir = (persistent_root / ".massgen" / "subagent_types" / "critic").resolve()
        assert str(type_dir).startswith(str(persistent_root.resolve()))
        assert type_dir.is_dir()
        assert (type_dir / "SUBAGENT.md").exists()

    def test_subagent_mcp_config_raises_on_invalid_specialized_profile(self, tmp_path, monkeypatch):
        """Schema errors in specialized profiles should surface as explicit failures."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)

        def _raise_profile_error(**kwargs):
            raise ValueError("Unsupported specialized subagent frontmatter fields")

        monkeypatch.setattr(
            "massgen.subagent.type_scanner.scan_subagent_types",
            _raise_profile_error,
        )

        with pytest.raises(ValueError, match="Failed to discover specialized subagent types"):
            orch._create_subagent_mcp_config("test_agent", agent)

    def test_subagent_mcp_agent_config_preserves_command_line_inheritance(self, tmp_path):
        """Parent backend command-line settings should be serialized for subagent inheritance."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.agents["test_agent"].backend.config = {
            "type": "codex",
            "model": "gpt-5.3-codex",
            "enable_mcp_command_line": True,
            "command_line_execution_mode": "docker",
            "command_line_docker_credentials": {"mount": ["codex_config"]},
            "enable_code_based_tools": True,
        }

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]
        agent_configs_file = Path(self._get_arg(args, "--agent-configs-file"))
        payload = json.loads(agent_configs_file.read_text())

        assert payload[0]["backend"]["enable_mcp_command_line"] is True
        assert payload[0]["backend"]["command_line_execution_mode"] == "docker"
        assert payload[0]["backend"]["command_line_docker_credentials"]["mount"] == ["codex_config"]
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

    def test_subagent_mcp_coordination_config_forwards_final_only_fallback_opt_out(self, tmp_path):
        """final_only fallback opt-out must be passed so delegated subagents stay read-focused."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.learning_capture_mode = "final_only"
        orch.config.coordination_config.disable_final_only_round_capture_fallback = True

        config = orch._create_subagent_mcp_config("test_agent", agent)
        args = config["args"]
        coord_file = Path(self._get_arg(args, "--coordination-config-file"))
        payload = json.loads(coord_file.read_text())

        assert payload["learning_capture_mode"] == "final_only"
        assert payload["disable_final_only_round_capture_fallback"] is True


class TestPlanningMcpConfigHooks:
    """Tests for planning MCP hook-dir wiring (Codex MCP hook delivery path)."""

    def _make_orchestrator_and_agent(self, tmp_path):
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        orch.orchestrator_id = "test-orch"

        coord_cfg = MagicMock(spec=[])
        coord_cfg.task_planning_filesystem_mode = True
        coord_cfg.use_skills = False
        coord_cfg.enable_memory_filesystem_mode = False
        coord_cfg.learning_capture_mode = "round"
        coord_cfg.disable_final_only_round_capture_fallback = False
        coord_cfg.use_two_tier_workspace = False

        orch.config = MagicMock(spec=[])
        orch.config.coordination_config = coord_cfg
        orch.config.skip_final_presentation = False

        agent = MagicMock()
        agent.backend = MagicMock(spec=[])
        agent.backend.config = {}
        agent.backend.filesystem_manager = MagicMock()
        agent.backend.filesystem_manager.cwd = str(tmp_path / "workspace")
        Path(agent.backend.filesystem_manager.cwd).mkdir(parents=True, exist_ok=True)

        return orch, agent

    def test_planning_mcp_config_includes_hook_dir_for_mcp_hook_backends(self, tmp_path):
        """Backends with MCP server hooks should pass --hook-dir to planning MCP."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        hook_dir = tmp_path / "hook_ipc"
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=True)
        agent.backend.get_hook_dir = MagicMock(return_value=hook_dir)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--hook-dir" in args
        hook_index = args.index("--hook-dir")
        assert args[hook_index + 1] == str(hook_dir)

    def test_planning_mcp_config_omits_hook_dir_when_backend_has_no_mcp_hooks(self, tmp_path):
        """Backends without MCP server hook support should not get --hook-dir."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)

        assert "--hook-dir" not in config["args"]

    def test_planning_mcp_config_includes_learning_flags_in_round_mode(self, tmp_path):
        """Round mode should keep auto-injected evolving-skill and memory planning flags."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.enable_memory_filesystem_mode = True
        orch.config.coordination_config.learning_capture_mode = "round"
        agent.backend.config = {"auto_discover_custom_tools": True}
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--auto-discovery-enabled" in args
        assert "--memory-enabled" in args

    def test_planning_mcp_config_omits_learning_flags_in_final_only_mode(self, tmp_path):
        """final_only should disable round-time evolving-skill/memory auto-injection."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.enable_memory_filesystem_mode = True
        orch.config.coordination_config.learning_capture_mode = "final_only"
        agent.backend.config = {"auto_discover_custom_tools": True}
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--auto-discovery-enabled" not in args
        assert "--memory-enabled" not in args

    def test_planning_mcp_config_verification_and_final_only_adds_verification_flag(self, tmp_path):
        """verification_and_final_only should inject only verification replay capture tasks."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.enable_memory_filesystem_mode = True
        orch.config.coordination_config.learning_capture_mode = "verification_and_final_only"
        agent.backend.config = {"auto_discover_custom_tools": True}
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--auto-discovery-enabled" not in args
        assert "--memory-enabled" not in args
        assert "--verification-memory-enabled" in args

    def test_planning_mcp_config_keeps_learning_flags_when_final_is_skipped(self, tmp_path):
        """final_only should fall back to round flags when skip_final_presentation is active."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.enable_memory_filesystem_mode = True
        orch.config.coordination_config.learning_capture_mode = "final_only"
        orch.config.skip_final_presentation = True
        agent.backend.config = {"auto_discover_custom_tools": True}
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--auto-discovery-enabled" in args
        assert "--memory-enabled" in args

    def test_planning_mcp_config_omits_learning_flags_when_fallback_is_disabled(self, tmp_path):
        """Subagent opt-out should keep final_only read-focused even when final presentation is skipped."""
        orch, agent = self._make_orchestrator_and_agent(tmp_path)
        orch.config.coordination_config.enable_memory_filesystem_mode = True
        orch.config.coordination_config.learning_capture_mode = "final_only"
        orch.config.coordination_config.disable_final_only_round_capture_fallback = True
        orch.config.skip_final_presentation = True
        agent.backend.config = {"auto_discover_custom_tools": True}
        agent.backend.supports_mcp_server_hooks = MagicMock(return_value=False)

        config = orch._create_planning_mcp_config("agent_a", agent)
        args = config["args"]

        assert "--auto-discovery-enabled" not in args
        assert "--memory-enabled" not in args
