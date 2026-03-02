"""
Comprehensive tests for config_builder.py - Agent cloning and preset application.

These tests ensure:
1. Cross-provider cloning preserves correct settings
2. Incompatible settings are skipped with warnings
3. Workspace uniqueness across agents
4. Tool compatibility matrix is enforced

Run with: uv run pytest massgen/tests/test_config_builder.py -v
"""

import pytest

from massgen.config_builder import (
    ConfigBuilder,
    build_quickstart_config_path,
    normalize_quickstart_config_filename,
)


class TestCloneAgent:
    """Test agent cloning across providers with compatibility checks."""

    @pytest.fixture
    def builder(self):
        """Create a ConfigBuilder instance for testing."""
        return ConfigBuilder()

    def test_clone_openai_to_gemini_preserves_provider(self, builder):
        """Test cloning OpenAI to Gemini preserves Gemini provider."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_web_search": True,
                "cwd": "workspace",
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        assert cloned["id"] == "agent_b"
        assert cloned["backend"]["type"] == "gemini"
        assert cloned["backend"]["model"] == "gemini-3-flash-preview"  # Default Gemini model
        assert cloned["backend"]["enable_web_search"] is True  # Compatible, should copy
        assert cloned["backend"]["cwd"] == "workspace"  # Filesystem copied (unique suffix added at runtime by cli.py)

    def test_clone_copies_filesystem_cwd(self, builder):
        """Test that cwd (filesystem) is copied and updated for target agent."""
        source = {
            "id": "agent_a",
            "backend": {"type": "openai", "model": "gpt-5", "cwd": "workspace"},
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="claude")

        # cwd should exist (copied from source) - unique suffix added at runtime by cli.py
        assert "cwd" in cloned["backend"]
        assert cloned["backend"]["cwd"] == "workspace"

    def test_clone_updates_workspace_number(self, builder):
        """Test that workspace number updates for target agent ID."""
        source = {
            "id": "agent_a",
            "backend": {"type": "openai", "model": "gpt-5", "cwd": "workspace"},
        }

        cloned = builder.clone_agent(source, "agent_c", target_backend_type="openai")

        assert cloned["backend"]["cwd"] == "workspace"  # unique suffix added at runtime by cli.py

    def test_clone_copies_compatible_tools(self, builder):
        """Test that compatible tools are copied across providers."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_web_search": True,
                "enable_mcp_command_line": True,
                "command_line_execution_mode": "docker",
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        # Universal tools should be copied
        assert cloned["backend"]["enable_mcp_command_line"] is True
        assert cloned["backend"]["command_line_execution_mode"] == "docker"
        # Web search compatible with both OpenAI and Gemini
        assert cloned["backend"]["enable_web_search"] is True

    def test_clone_skips_incompatible_tools(self, builder):
        """Test that incompatible tools are skipped with warnings."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_code_interpreter": True,  # OpenAI-specific
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        # Incompatible setting should be skipped
        assert "enable_code_interpreter" not in cloned["backend"]
        # Should generate skipped settings list
        assert "_skipped_settings" in cloned
        assert any("enable_code_interpreter" in s for s in cloned["_skipped_settings"])

    def test_clone_skips_openai_reasoning_to_gemini(self, builder):
        """Test that OpenAI reasoning/text settings are skipped for other providers."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "text": {"verbosity": "medium"},
                "reasoning": {"effort": "high", "summary": "auto"},
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        # OpenAI-specific settings should be skipped
        assert "text" not in cloned["backend"]
        assert "reasoning" not in cloned["backend"]
        # Should be in skipped list
        assert any("text" in s for s in cloned["_skipped_settings"])
        assert any("reasoning" in s for s in cloned["_skipped_settings"])

    def test_clone_preserves_openai_reasoning_to_openai(self, builder):
        """Test that OpenAI reasoning settings are preserved when cloning to OpenAI."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "text": {"verbosity": "medium"},
                "reasoning": {"effort": "high", "summary": "auto"},
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="openai")

        # OpenAI-specific settings should be preserved
        assert cloned["backend"]["text"]["verbosity"] == "medium"
        assert cloned["backend"]["reasoning"]["effort"] == "high"

    def test_clone_skips_code_interpreter_openai_to_gemini(self, builder):
        """Test code_interpreter is skipped when cloning OpenAI to Gemini."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_code_interpreter": True,
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        assert "enable_code_interpreter" not in cloned["backend"]
        assert any("enable_code_interpreter" in s for s in cloned["_skipped_settings"])

    def test_clone_skips_code_execution_gemini_to_openai(self, builder):
        """Test code_execution is skipped when cloning Gemini to OpenAI."""
        source = {
            "id": "agent_a",
            "backend": {"type": "gemini", "model": "gemini-2.5-pro", "enable_code_execution": True},
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="openai")

        assert "enable_code_execution" not in cloned["backend"]
        assert any("enable_code_execution" in s for s in cloned["_skipped_settings"])

    def test_clone_copies_mcp_servers_when_supported(self, builder):
        """Test MCP servers are copied when target supports MCP."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "mcp_servers": [
                    {"name": "weather", "command": "npx", "args": ["-y", "@fak111/weather-mcp"]},
                ],
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="gemini")

        # Gemini supports MCP, should copy
        assert "mcp_servers" in cloned["backend"]
        assert cloned["backend"]["mcp_servers"][0]["name"] == "weather"

    def test_clone_same_provider_copies_everything(self, builder):
        """Test cloning within same provider copies all settings."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_web_search": True,
                "enable_code_interpreter": True,
                "text": {"verbosity": "high"},
                "reasoning": {"effort": "medium", "summary": "auto"},
                "cwd": "workspace",
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="openai")

        # Everything should be copied for same provider
        assert cloned["backend"]["enable_web_search"] is True
        assert cloned["backend"]["enable_code_interpreter"] is True
        assert cloned["backend"]["text"]["verbosity"] == "high"
        assert cloned["backend"]["reasoning"]["effort"] == "medium"

    def test_clone_generates_skipped_settings_list(self, builder):
        """Test that _skipped_settings list is generated for incompatible settings."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_code_interpreter": True,
                "text": {"verbosity": "high"},
                "reasoning": {"effort": "medium", "summary": "auto"},
            },
        }

        cloned = builder.clone_agent(source, "agent_b", target_backend_type="claude")

        # Should have skipped settings
        assert "_skipped_settings" in cloned
        skipped = cloned["_skipped_settings"]
        assert len(skipped) > 0
        # All three should be skipped
        assert any("enable_code_interpreter" in s for s in skipped)
        assert any("text" in s for s in skipped)
        assert any("reasoning" in s for s in skipped)


class TestApplyPresetToAgent:
    """Test preset application generates unique workspaces."""

    @pytest.fixture
    def builder(self):
        """Create a ConfigBuilder instance for testing."""
        return ConfigBuilder()

    def test_apply_preset_generates_unique_workspace(self, builder):
        """Test that preset application generates workspace based on agent index."""
        agent = {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5"}}

        updated = builder.apply_preset_to_agent(agent, "coding", agent_index=1)

        assert updated["backend"]["cwd"] == "workspace"  # unique suffix added at runtime by cli.py

    def test_apply_preset_multiple_agents_unique_workspaces(self, builder):
        """Test that multiple agents get unique workspace numbers."""
        agents = [
            {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5"}},
            {"id": "agent_b", "backend": {"type": "gemini", "model": "gemini-2.5-pro"}},
            {"id": "agent_c", "backend": {"type": "claude", "model": "claude-3-5-sonnet-20241022"}},
        ]

        for i, agent in enumerate(agents):
            updated = builder.apply_preset_to_agent(agent, "coding", agent_index=i + 1)
            agents[i] = updated

        # Check all have workspace base name (unique suffixes added at runtime by cli.py)
        assert agents[0]["backend"]["cwd"] == "workspace"
        assert agents[1]["backend"]["cwd"] == "workspace"
        assert agents[2]["backend"]["cwd"] == "workspace"

    def test_apply_preset_filesystem_enabled_for_preset(self, builder):
        """Test that filesystem is enabled for presets that require it."""
        agent = {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5"}}

        updated = builder.apply_preset_to_agent(agent, "coding", agent_index=1)

        # Coding preset requires filesystem
        assert "cwd" in updated["backend"]

    def test_apply_preset_respects_agent_index(self, builder):
        """Test that agent_index correctly determines workspace number."""
        agent = {"id": "agent_c", "backend": {"type": "openai", "model": "gpt-5"}}

        updated = builder.apply_preset_to_agent(agent, "coding", agent_index=3)

        assert updated["backend"]["cwd"] == "workspace"  # unique suffix added at runtime by cli.py


class TestCrossProviderCompatibility:
    """Test tool compatibility matrix across providers."""

    @pytest.fixture
    def builder(self):
        """Create a ConfigBuilder instance for testing."""
        return ConfigBuilder()

    def test_web_search_compatible_providers(self, builder):
        """Test web_search is compatible with OpenAI, Gemini, Claude, Grok."""
        source = {
            "id": "agent_a",
            "backend": {"type": "openai", "model": "gpt-5", "enable_web_search": True},
        }

        for target_type in ["gemini", "claude", "grok"]:
            cloned = builder.clone_agent(source, "agent_b", target_backend_type=target_type)
            assert cloned["backend"]["enable_web_search"] is True, f"web_search should work on {target_type}"

    def test_code_interpreter_only_openai_azure(self, builder):
        """Test code_interpreter only works on OpenAI and Azure OpenAI."""
        source = {
            "id": "agent_a",
            "backend": {"type": "openai", "model": "gpt-5", "enable_code_interpreter": True},
        }

        # Should be skipped for non-OpenAI providers
        for target_type in ["gemini", "claude", "grok"]:
            cloned = builder.clone_agent(source, "agent_b", target_backend_type=target_type)
            assert "enable_code_interpreter" not in cloned["backend"], f"code_interpreter shouldn't work on {target_type}"
            assert any("enable_code_interpreter" in s for s in cloned["_skipped_settings"])

    def test_code_execution_only_claude_gemini(self, builder):
        """Test code_execution only works on Claude and Gemini."""
        source = {
            "id": "agent_a",
            "backend": {"type": "gemini", "model": "gemini-2.5-pro", "enable_code_execution": True},
        }

        # Should work on Claude
        cloned_claude = builder.clone_agent(source, "agent_b", target_backend_type="claude")
        assert cloned_claude["backend"]["enable_code_execution"] is True

        # Should be skipped for OpenAI
        cloned_openai = builder.clone_agent(source, "agent_c", target_backend_type="openai")
        assert "enable_code_execution" not in cloned_openai["backend"]
        assert any("enable_code_execution" in s for s in cloned_openai["_skipped_settings"])

    def test_filesystem_copied_across_all_providers(self, builder):
        """Test filesystem (cwd) is copied across all providers and updated to target agent number."""
        source = {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5", "cwd": "workspace"}}

        for target_type in ["gemini", "claude", "grok", "claude_code", "lmstudio"]:
            cloned = builder.clone_agent(source, "agent_b", target_backend_type=target_type)
            # cwd should exist - unique suffix added at runtime by cli.py
            assert "cwd" in cloned["backend"], f"cwd should be copied to {target_type}"
            assert cloned["backend"]["cwd"] == "workspace", f"cwd should be workspace for {target_type}"

    def test_command_line_execution_mode_universal(self, builder):
        """Test command_line_execution_mode is universal across providers."""
        source = {
            "id": "agent_a",
            "backend": {
                "type": "openai",
                "model": "gpt-5",
                "enable_mcp_command_line": True,
                "command_line_execution_mode": "docker",
            },
        }

        for target_type in ["gemini", "claude", "grok"]:
            cloned = builder.clone_agent(source, "agent_b", target_backend_type=target_type)
            assert cloned["backend"]["enable_mcp_command_line"] is True
            assert cloned["backend"]["command_line_execution_mode"] == "docker"


class TestWorkspaceUniqueness:
    """Test workspace uniqueness across different scenarios."""

    @pytest.fixture
    def builder(self):
        """Create a ConfigBuilder instance for testing."""
        return ConfigBuilder()

    def test_three_agents_get_workspace_base_name(self, builder):
        """Test that all agents get 'workspace' base name (unique suffix added at runtime by cli.py)."""
        agents = [
            {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5"}},
            {"id": "agent_b", "backend": {"type": "gemini", "model": "gemini-2.5-pro"}},
            {"id": "agent_c", "backend": {"type": "claude", "model": "claude-3-5-sonnet-20241022"}},
        ]

        for i, agent in enumerate(agents):
            agents[i] = builder.apply_preset_to_agent(agent, "coding", agent_index=i + 1)

        # All agents get "workspace" base name - unique suffixes added at runtime by cli.py
        assert agents[0]["backend"]["cwd"] == "workspace"
        assert agents[1]["backend"]["cwd"] == "workspace"
        assert agents[2]["backend"]["cwd"] == "workspace"

    def test_clone_updates_workspace_for_target_agent(self, builder):
        """Test that cloning updates workspace to match target agent ID."""
        source = {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5", "cwd": "workspace"}}

        # Clone gets "workspace" base name - unique suffix added at runtime by cli.py
        cloned = builder.clone_agent(source, "agent_d", target_backend_type="openai")

        assert cloned["backend"]["cwd"] == "workspace"

    def test_mixed_providers_all_unique_workspaces(self, builder):
        """Test mixed preset + clone scenario maintains unique workspaces."""
        # Agent A from preset
        agent_a = {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-5"}}
        agent_a = builder.apply_preset_to_agent(agent_a, "coding", agent_index=1)

        # Agent B cloned from A
        agent_b = builder.clone_agent(agent_a, "agent_b", target_backend_type="gemini")

        # Agent C from preset
        agent_c = {"id": "agent_c", "backend": {"type": "claude", "model": "claude-3-5-sonnet-20241022"}}
        agent_c = builder.apply_preset_to_agent(agent_c, "coding", agent_index=3)

        # All get "workspace" base name - unique suffixes added at runtime by cli.py
        assert agent_a["backend"]["cwd"] == "workspace"
        assert agent_b["backend"]["cwd"] == "workspace"
        assert agent_c["backend"]["cwd"] == "workspace"


class TestQuickstartDecompositionSettings:
    """Test quickstart config generation for decomposition settings and defaults."""

    @pytest.fixture
    def builder(self):
        """Create a ConfigBuilder instance for testing."""
        return ConfigBuilder()

    @staticmethod
    def _agents():
        return [
            {"id": "agent_a", "type": "openai", "model": "gpt-5"},
            {"id": "agent_b", "type": "openai", "model": "gpt-5"},
            {"id": "agent_c", "type": "openai", "model": "gpt-5"},
        ]

    def test_decomposition_defaults_applied(self, builder):
        """Decomposition mode gets recommended quickstart defaults when unset."""
        config = builder._generate_quickstart_config(
            agents_config=self._agents(),
            use_docker=False,
            coordination_settings={"coordination_mode": "decomposition"},
        )

        orch = config["orchestrator"]
        assert orch["coordination_mode"] == "decomposition"
        assert orch["presenter_agent"] == "agent_c"
        assert orch["max_new_answers_per_agent"] == 2
        assert orch["max_new_answers_global"] == 9
        assert orch["answer_novelty_requirement"] == "balanced"
        assert orch["fairness_enabled"] is True
        assert orch["fairness_lead_cap_answers"] == 2
        assert orch["max_midstream_injections_per_round"] == 2

    def test_decomposition_overrides_respected(self, builder):
        """Explicit decomposition settings should override defaults."""
        config = builder._generate_quickstart_config(
            agents_config=self._agents(),
            use_docker=False,
            coordination_settings={
                "coordination_mode": "decomposition",
                "presenter_agent": "agent_a",
                "max_new_answers_per_agent": 3,
                "max_new_answers_global": 12,
                "answer_novelty_requirement": "strict",
            },
        )

        orch = config["orchestrator"]
        assert orch["coordination_mode"] == "decomposition"
        assert orch["presenter_agent"] == "agent_a"
        assert orch["max_new_answers_per_agent"] == 3
        assert orch["max_new_answers_global"] == 12
        assert orch["answer_novelty_requirement"] == "strict"

    def test_parallel_defaults_include_fairness(self, builder):
        """Parallel/voting quickstart defaults include fairness controls."""
        config = builder._generate_quickstart_config(
            agents_config=self._agents(),
            use_docker=False,
        )

        orch = config["orchestrator"]
        assert orch["max_new_answers_per_agent"] == 5
        assert orch["fairness_enabled"] is True
        assert orch["fairness_lead_cap_answers"] == 2
        assert orch["max_midstream_injections_per_round"] == 2
        assert "coordination_mode" not in orch
        assert "presenter_agent" not in orch
        assert "max_new_answers_global" not in orch

    def test_global_cap_pass_through_in_parallel(self, builder):
        """Global cap can still be set explicitly outside decomposition mode."""
        config = builder._generate_quickstart_config(
            agents_config=self._agents(),
            use_docker=False,
            coordination_settings={"max_new_answers_global": 7},
        )

        assert config["orchestrator"]["max_new_answers_global"] == 7


class TestQuickstartReasoningSettings:
    """Test quickstart reasoning selector behavior and config output."""

    @pytest.fixture
    def builder(self):
        return ConfigBuilder()

    def test_reasoning_profile_for_openai_gpt5(self):
        profile = ConfigBuilder.get_quickstart_reasoning_profile("openai", "gpt-5.2")
        assert profile is not None
        assert profile["default_effort"] == "medium"
        efforts = [value for _, value in profile["choices"]]
        assert efforts == ["low", "medium", "high"]

    def test_reasoning_profile_for_codex_includes_xhigh(self):
        profile = ConfigBuilder.get_quickstart_reasoning_profile("codex", "gpt-5.3-codex")
        assert profile is not None
        efforts = [value for _, value in profile["choices"]]
        assert efforts == ["low", "medium", "high", "xhigh"]

    def test_reasoning_profile_ignored_for_non_gpt5_models(self):
        profile = ConfigBuilder.get_quickstart_reasoning_profile("openai", "gpt-4o")
        assert profile is None

    def test_quickstart_reasoning_effort_written_to_backend(self, builder):
        config = builder._generate_quickstart_config(
            agents_config=[
                {
                    "id": "agent_a",
                    "type": "openai",
                    "model": "gpt-5.2",
                    "reasoning_effort": "high",
                },
                {
                    "id": "agent_b",
                    "type": "codex",
                    "model": "gpt-5.3-codex",
                    "reasoning_effort": "xhigh",
                },
            ],
            use_docker=False,
        )

        assert config["agents"][0]["backend"]["reasoning"] == {
            "effort": "high",
            "summary": "auto",
        }
        assert config["agents"][1]["backend"]["reasoning"] == {
            "effort": "xhigh",
            "summary": "auto",
        }


class TestQuickstartConfigPathHelpers:
    """Test quickstart output filename/path helper behavior."""

    def test_normalize_quickstart_filename_adds_yaml_extension(self):
        assert normalize_quickstart_config_filename("team-config") == "team-config.yaml"

    def test_normalize_quickstart_filename_uses_basename_only(self):
        assert normalize_quickstart_config_filename(".massgen/nested/custom.yml") == "custom.yml"

    def test_build_quickstart_project_path_uses_dot_massgen(self, tmp_path):
        path = build_quickstart_config_path(
            location="project",
            filename="my-team",
            cwd=tmp_path,
        )
        assert path == tmp_path / ".massgen" / "my-team.yaml"

    def test_build_quickstart_global_path_uses_home_config_dir(self, tmp_path):
        fake_home = tmp_path / "home"
        path = build_quickstart_config_path(
            location="global",
            filename="global-name",
            home_dir=fake_home,
        )
        assert path == fake_home / ".config" / "massgen" / "global-name.yaml"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
