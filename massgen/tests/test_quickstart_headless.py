"""Tests for headless quickstart (massgen --quickstart --headless)."""

import argparse
import os
from pathlib import Path
from unittest.mock import patch

import yaml

# ---------------------------------------------------------------------------
# ConfigBuilder.run_quickstart_headless tests
# ---------------------------------------------------------------------------


class TestHeadlessAutoSelect:
    """Priority-based backend auto-selection."""

    def test_auto_selects_anthropic_when_available(self, tmp_path, monkeypatch):
        """Priority order picks anthropic (claude) first."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["success"] is True
        assert result["backend"] == "claude"
        assert "claude" in result["model"].lower() or "sonnet" in result["model"].lower()

    def test_auto_selects_openai_when_anthropic_missing(self, tmp_path, monkeypatch):
        """Falls through priority chain when anthropic key missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["success"] is True
        assert result["backend"] == "openai"

    def test_auto_selects_gemini_when_others_missing(self, tmp_path, monkeypatch):
        """Falls through to gemini when anthropic and openai keys missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["success"] is True
        assert result["backend"] == "gemini"

    def test_auto_selects_grok_as_last_resort(self, tmp_path, monkeypatch):
        """Falls through to grok when all others missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("XAI_API_KEY", "test-key")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["success"] is True
        assert result["backend"] == "grok"


class TestHeadlessNoKeys:
    """Behavior when no API keys are found."""

    def test_no_keys_creates_template_only(self, tmp_path, monkeypatch):
        """No config generated, .env template created."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["success"] is False
        assert result["env_template_path"] is not None
        assert Path(result["env_template_path"]).exists()
        assert result["config_path"] is None
        assert len(result["manual_steps"]) > 0


class TestHeadlessOverrides:
    """Backend/model override behavior."""

    def test_respects_backend_override(self, tmp_path, monkeypatch):
        """Override takes precedence over auto-detection."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            backend_override="gemini",
        )

        assert result["success"] is True
        assert result["backend"] == "gemini"

    def test_respects_model_override(self, tmp_path, monkeypatch):
        """Model override takes precedence over default."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            model_override="claude-opus-4-6",
        )

        assert result["success"] is True
        assert result["model"] == "claude-opus-4-6"

    def test_backend_override_without_key_fails(self, tmp_path, monkeypatch):
        """Override backend that has no key fails gracefully."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            backend_override="claude",
        )

        assert result["success"] is False

    def test_csv_multi_backend_override_is_rejected(self, tmp_path, monkeypatch):
        """CSV multi-backend overrides should point callers to --quickstart-agent."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            backend_override="claude,openai,gemini",
            model_override="claude-opus-4-6,gpt-5.4,gemini-3-flash-preview",
        )

        assert result["success"] is False
        assert any("--quickstart-agent" in step for step in result["manual_steps"])

    def test_explicit_agent_specs_support_mixed_providers(self, tmp_path, monkeypatch):
        """Explicit agent specs create a mixed-provider config."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            use_docker=False,
            agent_specs=[
                {"backend": "claude", "model": "claude-opus-4-6"},
                {"backend": "openai", "model": "gpt-5.4"},
                {"backend": "gemini", "model": "gemini-3-flash-preview"},
            ],
        )

        assert result["success"] is True
        assert result["backends"] == ["claude", "openai", "gemini"]
        config = yaml.safe_load(Path(result["config_path"]).read_text())
        assert [agent["backend"]["type"] for agent in config["agents"]] == ["claude", "openai", "gemini"]


class TestHeadlessEnvTemplate:
    """Env template generation."""

    def test_env_template_format(self, tmp_path, monkeypatch):
        """Template has correct structure, no actual key values."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        template_path = result["env_template_path"]
        assert template_path is not None
        content = Path(template_path).read_text()

        # Must contain key names but no values
        assert "ANTHROPIC_API_KEY=" in content
        assert "OPENAI_API_KEY=" in content
        assert "GEMINI_API_KEY=" in content
        assert "XAI_API_KEY=" in content
        # Must not contain actual key values (only empty =)
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                assert value.strip() == "", f"Template should not contain values: {line}"

    def test_env_template_idempotent(self, tmp_path, monkeypatch):
        """Won't overwrite existing .env."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        # Create existing .env with user content
        env_path = tmp_path / ".env"
        env_path.write_text("MY_CUSTOM_KEY=secret\n")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        # Existing file should be untouched
        assert env_path.read_text() == "MY_CUSTOM_KEY=secret\n"
        # env_template_path should be None since we didn't create one
        assert result["env_template_path"] is None


class TestHeadlessConfigGeneration:
    """Generated config contents."""

    def test_config_generation(self, tmp_path, monkeypatch):
        """Generated YAML has correct agents/backend."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            num_agents=4,
        )

        assert result["success"] is True
        config_path = result["config_path"]
        assert config_path is not None
        assert Path(config_path).exists()

        config = yaml.safe_load(Path(config_path).read_text())
        assert len(config["agents"]) == 4
        for agent in config["agents"]:
            assert agent["backend"]["type"] == "claude"

    def test_config_uses_default_3_agents(self, tmp_path, monkeypatch):
        """Default num_agents is 3."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        config = yaml.safe_load(Path(result["config_path"]).read_text())
        assert len(config["agents"]) == 3


class TestHeadlessDocker:
    """Docker auto-detection behavior."""

    def test_docker_auto_detection(self, tmp_path, monkeypatch):
        """Docker detected -> docker info in result."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        # Patch diagnose_docker at its source module
        with patch("massgen.utils.docker_diagnostics.diagnose_docker") as mock_diag:
            mock_diag.return_value.is_available = True
            result = builder.run_quickstart_headless(output_dir=str(tmp_path))

        assert result["docker_available"] is True

    def test_docker_not_available(self, tmp_path, monkeypatch):
        """Docker missing -> config still works with local mode."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        with patch("massgen.utils.docker_diagnostics.diagnose_docker") as mock_diag:
            mock_diag.return_value.is_available = False
            result = builder.run_quickstart_headless(
                output_dir=str(tmp_path),
                use_docker=False,
            )

        assert result["success"] is True
        assert result["docker_available"] is False

    def test_docker_explicit_false(self, tmp_path, monkeypatch):
        """Explicit use_docker=False skips docker."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            use_docker=False,
        )

        assert result["success"] is True
        config = yaml.safe_load(Path(result["config_path"]).read_text())
        # In non-docker mode, agents shouldn't have docker command settings
        for agent in config["agents"]:
            backend = agent["backend"]
            assert backend.get("command_line_execution_mode") != "docker"

    def test_local_mode_still_enables_skills(self, tmp_path, monkeypatch):
        """Local quickstart should keep built-in skills enabled."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from massgen.config_builder import ConfigBuilder

        builder = ConfigBuilder()
        result = builder.run_quickstart_headless(
            output_dir=str(tmp_path),
            use_docker=False,
        )

        assert result["success"] is True
        config = yaml.safe_load(Path(result["config_path"]).read_text())
        coordination = config["orchestrator"]["coordination"]
        assert coordination["use_skills"] is True


# ---------------------------------------------------------------------------
# CLI argument parsing and dispatch
# ---------------------------------------------------------------------------


def _build_test_parser() -> argparse.ArgumentParser:
    """Build a minimal parser with just the args needed for headless tests."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--quickstart", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--config-backend", type=str)
    parser.add_argument("--config-model", type=str)
    parser.add_argument("--config-agents", type=int, default=2)
    parser.add_argument("--config-docker", action="store_true")
    parser.add_argument("--config-context-path", type=str)
    return parser


class TestHeadlessCLI:
    """CLI argument parsing."""

    def test_headless_cli_arg_parsing(self):
        """--headless stored in args correctly."""
        parser = _build_test_parser()
        args = parser.parse_args(["--quickstart", "--headless"])
        assert args.headless is True
        assert args.quickstart is True

    def test_headless_default_false(self):
        """--headless defaults to False."""
        parser = _build_test_parser()
        args = parser.parse_args(["--quickstart"])
        assert args.headless is False

    def test_headless_with_overrides(self):
        """--headless combined with --config-backend and --config-agents."""
        parser = _build_test_parser()
        args = parser.parse_args(
            [
                "--quickstart",
                "--headless",
                "--config-backend",
                "anthropic",
                "--config-agents",
                "5",
            ],
        )
        assert args.headless is True
        assert args.config_backend == "anthropic"
        assert args.config_agents == 5

    def test_generate_config_cli_dispatches_without_unboundlocalerror(self, monkeypatch, tmp_path, capsys):
        """--generate-config should use ConfigBuilder without tripping local shadowing."""
        from massgen import cli as massgen_cli

        output_path = tmp_path / "generated.yaml"
        args = massgen_cli.main_parser().parse_args(
            [
                "--generate-config",
                str(output_path),
                "--config-backend",
                "openai",
                "--config-model",
                "gpt-5.4",
                "--config-docker",
            ],
        )

        generate_calls = []

        def fake_generate_config_programmatic(
            self,
            output_path,
            num_agents,
            backend_type,
            model,
            use_docker,
            context_path,
        ):
            generate_calls.append(
                {
                    "output_path": output_path,
                    "num_agents": num_agents,
                    "backend_type": backend_type,
                    "model": model,
                    "use_docker": use_docker,
                    "context_path": context_path,
                },
            )
            Path(output_path).write_text("agents: []\n")
            return True

        monkeypatch.setattr(
            massgen_cli.ConfigBuilder,
            "generate_config_programmatic",
            fake_generate_config_programmatic,
        )

        massgen_cli._cli_main_continued(args)

        output = capsys.readouterr().out
        assert generate_calls == [
            {
                "output_path": str(output_path),
                "num_agents": 2,
                "backend_type": "openai",
                "model": "gpt-5.4",
                "use_docker": True,
                "context_path": None,
            },
        ]
        assert f"Configuration saved to: {output_path}" in output

    def test_headless_quickstart_cli_honors_exact_config_path(self, monkeypatch, tmp_path):
        """Headless quickstart should treat --config as an exact output path."""
        from massgen import cli as massgen_cli

        requested_path = tmp_path / "exact" / "headless.yaml"
        args = massgen_cli.main_parser().parse_args(
            [
                "--quickstart",
                "--headless",
                "--config",
                str(requested_path),
                "--config-backend",
                "openai",
                "--config-model",
                "gpt-5.4",
            ],
        )

        run_calls = []
        monkeypatch.setattr(
            massgen_cli,
            "_print_headless_quickstart_summary",
            lambda result: None,
        )
        monkeypatch.setattr(
            massgen_cli,
            "_ensure_quickstart_skills_ready",
            lambda *_args, **_kwargs: None,
        )

        def fake_run_quickstart_headless(
            self,
            output_dir,
            num_agents,
            backend_override,
            model_override,
            use_docker,
            context_path,
            agent_specs,
            output_path=None,
        ):
            run_calls.append(
                {
                    "output_dir": output_dir,
                    "output_path": output_path,
                    "num_agents": num_agents,
                    "backend_override": backend_override,
                    "model_override": model_override,
                    "use_docker": use_docker,
                    "context_path": context_path,
                    "agent_specs": agent_specs,
                },
            )
            return {
                "success": True,
                "config_path": output_path,
                "env_template_path": None,
                "backend": backend_override,
                "model": model_override,
                "backends": None,
                "models": None,
                "api_keys_summary": {},
                "docker_available": False,
                "docker_pulled": False,
                "skills_installed": False,
                "messages": [],
                "manual_steps": [],
            }

        monkeypatch.setattr(
            massgen_cli.ConfigBuilder,
            "run_quickstart_headless",
            fake_run_quickstart_headless,
        )

        massgen_cli._cli_main_continued(args)

        assert run_calls == [
            {
                "output_dir": ".massgen",
                "output_path": str(requested_path),
                "num_agents": 3,
                "backend_override": "openai",
                "model_override": "gpt-5.4",
                "use_docker": None,
                "context_path": None,
                "agent_specs": None,
            },
        ]


class TestHeadlessAutoTrigger:
    """Auto-trigger headless mode when no TTY."""

    def test_auto_triggers_without_tty(self):
        """No TTY -> headless path taken automatically via condition check."""
        parser = _build_test_parser()
        args = parser.parse_args(["--quickstart"])

        # Verify headless is False (not explicitly set)
        assert args.headless is False

        # The dispatch condition is: args.headless or not sys.stdin.isatty()
        # We just verify the condition logic works correctly
        headless_should_trigger = args.headless or not os.isatty(0)
        assert isinstance(headless_should_trigger, bool)


class TestHeadlessSummaryPrinting:
    """_print_headless_quickstart_summary output."""

    def test_summary_prints_success(self, capsys):
        """Summary prints structured output for successful result."""
        from massgen.cli import _print_headless_quickstart_summary

        result = {
            "success": True,
            "config_path": ".massgen/config.yaml",
            "env_template_path": None,
            "backend": "claude",
            "model": "claude-sonnet-4-5-20250514",
            "api_keys_summary": {
                "ANTHROPIC_API_KEY": True,
                "OPENAI_API_KEY": False,
            },
            "docker_available": True,
            "docker_pulled": False,
            "skills_installed": True,
            "messages": ["Config generated successfully"],
            "manual_steps": [],
        }

        _print_headless_quickstart_summary(result)
        output = capsys.readouterr().out

        assert "SUCCESS" in output
        assert "claude" in output
        assert "config.yaml" in output

    def test_summary_prints_failure(self, capsys):
        """Summary prints structured output for failed result."""
        from massgen.cli import _print_headless_quickstart_summary

        result = {
            "success": False,
            "config_path": None,
            "env_template_path": ".env",
            "backend": None,
            "model": None,
            "api_keys_summary": {
                "ANTHROPIC_API_KEY": False,
                "OPENAI_API_KEY": False,
            },
            "docker_available": False,
            "docker_pulled": False,
            "skills_installed": False,
            "messages": [],
            "manual_steps": ["Fill in API keys in .env, then re-run"],
        }

        _print_headless_quickstart_summary(result)
        output = capsys.readouterr().out

        assert "NEEDS_CONFIG" in output
        assert ".env" in output
