"""Tests for CLI mode flags: --single-agent, --coordination-mode, --quick, --personas.

These flags mirror the TUI mode bar toggles, allowing users to control
execution modes from the command line.
"""

import argparse

import pytest


def _make_parser_with_mode_flags():
    """Create a minimal argparse parser with mode flags for testing.

    Imports the real add_mode_flags_to_parser helper from cli.py.
    """
    from massgen.cli import add_mode_flags_to_parser

    parser = argparse.ArgumentParser()
    # Add the positional question arg to match real CLI behavior
    parser.add_argument("question", nargs="?", default=None)
    add_mode_flags_to_parser(parser)
    return parser


class TestModeFlargParsing:
    """Test that mode flags are accepted and parsed correctly."""

    def test_quick_flag_parsed(self):
        """--quick sets quick=True in parsed args."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--quick", "my question"])
        assert args.quick is True

    def test_quick_flag_default(self):
        """--quick defaults to False when not provided."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["my question"])
        assert args.quick is False

    def test_single_agent_no_id(self):
        """--single-agent without ID sets single_agent=True."""
        parser = _make_parser_with_mode_flags()
        # Put question before flag to avoid nargs='?' consuming it
        args = parser.parse_args(["my question", "--single-agent"])
        assert args.single_agent is True

    def test_single_agent_with_id(self):
        """--single-agent agent_b sets single_agent='agent_b'."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--single-agent", "agent_b", "my question"])
        assert args.single_agent == "agent_b"

    def test_single_agent_default(self):
        """--single-agent defaults to None when not provided."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["my question"])
        assert args.single_agent is None

    def test_coordination_mode_parallel(self):
        """--coordination-mode parallel is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--coordination-mode", "parallel", "my question"])
        assert args.coordination_mode == "parallel"

    def test_coordination_mode_decomposition(self):
        """--coordination-mode decomposition is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--coordination-mode", "decomposition", "my question"])
        assert args.coordination_mode == "decomposition"

    def test_coordination_mode_invalid_rejected(self):
        """--coordination-mode with invalid value is rejected."""
        parser = _make_parser_with_mode_flags()
        with pytest.raises(SystemExit):
            parser.parse_args(["--coordination-mode", "invalid"])

    def test_coordination_mode_default(self):
        """--coordination-mode defaults to None when not provided."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["my question"])
        assert args.coordination_mode is None

    def test_personas_perspective(self):
        """--personas perspective is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--personas", "perspective", "my question"])
        assert args.personas == "perspective"

    def test_personas_implementation(self):
        """--personas implementation is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--personas", "implementation", "my question"])
        assert args.personas == "implementation"

    def test_personas_methodology(self):
        """--personas methodology is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--personas", "methodology", "my question"])
        assert args.personas == "methodology"

    def test_personas_off(self):
        """--personas off is accepted."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["--personas", "off", "my question"])
        assert args.personas == "off"

    def test_personas_invalid_rejected(self):
        """--personas with invalid value is rejected."""
        parser = _make_parser_with_mode_flags()
        with pytest.raises(SystemExit):
            parser.parse_args(["--personas", "invalid"])

    def test_personas_default(self):
        """--personas defaults to None when not provided."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(["my question"])
        assert args.personas is None

    def test_multiple_flags_combined(self):
        """Multiple mode flags can be combined."""
        parser = _make_parser_with_mode_flags()
        args = parser.parse_args(
            [
                "--quick",
                "--single-agent",
                "--personas",
                "off",
                "my question",
            ],
        )
        assert args.quick is True
        assert args.single_agent is True
        assert args.personas == "off"


class TestModeFlargValidation:
    """Test validation of incompatible flag combinations."""

    def test_single_agent_with_decomposition_rejected(self):
        """--single-agent + --coordination-mode decomposition should fail."""
        from massgen.cli import validate_mode_flag_combinations

        args = argparse.Namespace(
            single_agent=True,
            coordination_mode="decomposition",
            personas=None,
            quick=False,
        )
        errors = validate_mode_flag_combinations(args)
        assert len(errors) > 0
        assert any("decomposition" in e.lower() for e in errors)

    def test_personas_with_decomposition_rejected(self):
        """--personas perspective + --coordination-mode decomposition should fail."""
        from massgen.cli import validate_mode_flag_combinations

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="decomposition",
            personas="perspective",
            quick=False,
        )
        errors = validate_mode_flag_combinations(args)
        assert len(errors) > 0
        assert any("persona" in e.lower() for e in errors)

    def test_valid_combination_no_errors(self):
        """Valid flag combinations produce no errors."""
        from massgen.cli import validate_mode_flag_combinations

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="parallel",
            personas="perspective",
            quick=False,
        )
        errors = validate_mode_flag_combinations(args)
        assert len(errors) == 0

    def test_quick_with_single_agent_valid(self):
        """--quick + --single-agent is a valid combination."""
        from massgen.cli import validate_mode_flag_combinations

        args = argparse.Namespace(
            single_agent=True,
            coordination_mode=None,
            personas=None,
            quick=True,
        )
        errors = validate_mode_flag_combinations(args)
        assert len(errors) == 0

    def test_personas_off_with_decomposition_valid(self):
        """--personas off + --coordination-mode decomposition is valid."""
        from massgen.cli import validate_mode_flag_combinations

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="decomposition",
            personas="off",
            quick=False,
        )
        errors = validate_mode_flag_combinations(args)
        assert len(errors) == 0


class TestModeConfigOverrides:
    """Test that CLI mode flags correctly modify orchestrator config."""

    def test_quick_applies_refinement_off_overrides(self):
        """--quick sets max_new_answers_per_agent=1, skip_final_presentation=True."""
        from massgen.cli import apply_mode_flags_to_config

        config = {"orchestrator": {}}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=True,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"]["max_new_answers_per_agent"] == 1
        assert config["orchestrator"]["skip_final_presentation"] is True

    def test_quick_single_agent_skips_voting(self):
        """--quick + --single-agent sets skip_voting=True."""
        from massgen.cli import apply_mode_flags_to_config

        config = {"orchestrator": {}}
        args = argparse.Namespace(
            single_agent=True,
            coordination_mode=None,
            personas=None,
            quick=True,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"]["skip_voting"] is True
        # Should NOT have multi-agent-specific overrides
        assert config["orchestrator"].get("disable_injection") is None

    def test_quick_multi_agent_disables_injection(self):
        """--quick (multi-agent) sets disable_injection=True, defer_voting_until_all_answered=True."""
        from massgen.cli import apply_mode_flags_to_config

        config = {"orchestrator": {}}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=True,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"]["disable_injection"] is True
        assert config["orchestrator"]["defer_voting_until_all_answered"] is True
        # Should NOT have single-agent-specific overrides
        assert config["orchestrator"].get("skip_voting") is None

    def test_coordination_mode_parallel_maps_to_voting(self):
        """--coordination-mode parallel maps to coordination_mode='voting'."""
        from massgen.cli import apply_mode_flags_to_config

        config = {}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="parallel",
            personas=None,
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"]["coordination_mode"] == "voting"

    def test_coordination_mode_decomposition(self):
        """--coordination-mode decomposition maps correctly."""
        from massgen.cli import apply_mode_flags_to_config

        config = {}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="decomposition",
            personas=None,
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"]["coordination_mode"] == "decomposition"

    def test_personas_enables_persona_generator(self):
        """--personas perspective enables persona_generator with diversity_mode."""
        from massgen.cli import apply_mode_flags_to_config

        config = {}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas="perspective",
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        pg = config["orchestrator"]["coordination"]["persona_generator"]
        assert pg["enabled"] is True
        assert pg["diversity_mode"] == "perspective"

    def test_personas_methodology(self):
        """--personas methodology sets correct diversity_mode."""
        from massgen.cli import apply_mode_flags_to_config

        config = {}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas="methodology",
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        pg = config["orchestrator"]["coordination"]["persona_generator"]
        assert pg["enabled"] is True
        assert pg["diversity_mode"] == "methodology"

    def test_personas_off_disables_persona_generator(self):
        """--personas off disables persona generation even if config had it enabled."""
        from massgen.cli import apply_mode_flags_to_config

        config = {
            "orchestrator": {
                "coordination": {
                    "persona_generator": {
                        "enabled": True,
                        "diversity_mode": "perspective",
                    },
                },
            },
        }
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas="off",
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        pg = config["orchestrator"]["coordination"]["persona_generator"]
        assert pg["enabled"] is False

    def test_no_flags_no_changes(self):
        """No mode flags = no changes to config."""
        from massgen.cli import apply_mode_flags_to_config

        config = {"orchestrator": {"coordination_mode": "voting"}}
        original = dict(config["orchestrator"])
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        assert config["orchestrator"] == original

    def test_config_without_orchestrator_section_created(self):
        """Config without orchestrator section gets one created when needed."""
        from massgen.cli import apply_mode_flags_to_config

        config = {}
        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="parallel",
            personas=None,
            quick=False,
        )
        apply_mode_flags_to_config(config, args)
        assert "orchestrator" in config
        assert config["orchestrator"]["coordination_mode"] == "voting"


class TestSingleAgentFiltering:
    """Test --single-agent agent filtering."""

    def test_filter_picks_first_agent(self):
        """--single-agent (no ID) picks first agent."""
        from massgen.cli import filter_agents_for_single_mode

        agents = {"agent_a": "mock_a", "agent_b": "mock_b", "agent_c": "mock_c"}
        result = filter_agents_for_single_mode(agents, single_agent_arg=True)
        assert len(result) == 1
        assert "agent_a" in result

    def test_filter_picks_specified_agent(self):
        """--single-agent agent_b picks the named agent."""
        from massgen.cli import filter_agents_for_single_mode

        agents = {"agent_a": "mock_a", "agent_b": "mock_b", "agent_c": "mock_c"}
        result = filter_agents_for_single_mode(agents, single_agent_arg="agent_b")
        assert len(result) == 1
        assert "agent_b" in result
        assert result["agent_b"] == "mock_b"

    def test_filter_invalid_id_raises(self):
        """--single-agent nonexistent raises ValueError with available agents."""
        from massgen.cli import filter_agents_for_single_mode

        agents = {"agent_a": "mock_a", "agent_b": "mock_b"}
        with pytest.raises(ValueError, match="agent_a"):
            filter_agents_for_single_mode(agents, single_agent_arg="nonexistent")

    def test_filter_none_returns_unchanged(self):
        """No --single-agent returns agents unchanged."""
        from massgen.cli import filter_agents_for_single_mode

        agents = {"agent_a": "mock_a", "agent_b": "mock_b"}
        result = filter_agents_for_single_mode(agents, single_agent_arg=None)
        assert result == agents


class TestCliModeDefaults:
    """Test that CLI mode flags are correctly packaged for TUI defaults."""

    def test_build_cli_mode_defaults_quick(self):
        """--quick produces refinement_enabled=False in defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=True,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["refinement_enabled"] is False

    def test_build_cli_mode_defaults_single_agent(self):
        """--single-agent produces agent_mode='single' in defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=True,
            coordination_mode=None,
            personas=None,
            quick=False,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["agent_mode"] == "single"

    def test_build_cli_mode_defaults_single_agent_with_id(self):
        """--single-agent agent_b includes selected_agent in defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent="agent_b",
            coordination_mode=None,
            personas=None,
            quick=False,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["agent_mode"] == "single"
        assert defaults["selected_agent"] == "agent_b"

    def test_build_cli_mode_defaults_coordination_mode(self):
        """--coordination-mode decomposition included in defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode="decomposition",
            personas=None,
            quick=False,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["coordination_mode"] == "decomposition"

    def test_build_cli_mode_defaults_personas(self):
        """--personas perspective included in defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas="perspective",
            quick=False,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["personas"] == "perspective"

    def test_build_cli_mode_defaults_plan(self):
        """--plan seeds textual defaults with initial plan mode."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=False,
            plan=True,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["plan_mode"] == "plan"

    def test_build_cli_mode_defaults_empty_when_no_flags(self):
        """No mode flags produces empty defaults dict."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent=None,
            coordination_mode=None,
            personas=None,
            quick=False,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults == {}

    def test_build_cli_mode_defaults_all_flags(self):
        """All mode flags combined produces complete defaults."""
        from massgen.cli import build_cli_mode_defaults

        args = argparse.Namespace(
            single_agent="agent_x",
            coordination_mode="parallel",
            personas="implementation",
            quick=True,
        )
        defaults = build_cli_mode_defaults(args)
        assert defaults["agent_mode"] == "single"
        assert defaults["selected_agent"] == "agent_x"
        assert defaults["coordination_mode"] == "parallel"
        assert defaults["personas"] == "implementation"
        assert defaults["refinement_enabled"] is False
