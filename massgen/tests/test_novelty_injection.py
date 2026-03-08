"""Tests for novelty injection feature (Change 6).

Tests cover:
- Config: novelty_injection field on CoordinationConfig
- Config validation: valid/invalid values
- Convergence detection: checklist_history tracking, _detect_convergence logic
- NoveltyPressureSection: rendering at each level
- Wiring: build_coordination_message accepts novelty_pressure_data
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from massgen.agent_config import CoordinationConfig

# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------


class TestNoveltyInjectionConfig:
    """Tests for novelty_injection field on CoordinationConfig."""

    def test_default_is_none(self):
        """Default novelty_injection should be 'none'."""
        config = CoordinationConfig()
        assert config.novelty_injection == "none"

    def test_valid_values_accepted(self):
        """All valid values should be accepted without error."""
        for value in ("none", "gentle", "moderate", "aggressive"):
            config = CoordinationConfig(novelty_injection=value)
            assert config.novelty_injection == value

    def test_invalid_value_raises(self):
        """Invalid novelty_injection value should raise ValueError."""
        with pytest.raises(ValueError, match="novelty_injection"):
            CoordinationConfig(novelty_injection="extreme")

    def test_enable_novelty_on_iteration_defaults_false(self):
        """Default should keep novelty-on-iteration auto-trigger disabled."""
        config = CoordinationConfig()
        assert config.enable_novelty_on_iteration is False

    def test_enable_novelty_on_iteration_accepts_true(self):
        """CoordinationConfig should store explicit enable_novelty_on_iteration flag."""
        config = CoordinationConfig(enable_novelty_on_iteration=True)
        assert config.enable_novelty_on_iteration is True

    def test_enable_quality_rethink_on_iteration_defaults_false(self):
        """Default should keep quality-rethink-on-iteration auto-trigger disabled."""
        config = CoordinationConfig()
        assert config.enable_quality_rethink_on_iteration is False

    def test_enable_quality_rethink_on_iteration_accepts_true(self):
        """CoordinationConfig should store explicit enable_quality_rethink_on_iteration flag."""
        config = CoordinationConfig(enable_quality_rethink_on_iteration=True)
        assert config.enable_quality_rethink_on_iteration is True

    def test_config_validator_accepts_valid(self):
        """Config validator should accept valid novelty_injection values."""
        from massgen.config_validator import ConfigValidator

        for value in ("none", "gentle", "moderate", "aggressive"):
            config = {
                "agents": [
                    {
                        "id": "agent_a",
                        "backend": {"model": "test-model", "type": "openai"},
                    },
                ],
                "orchestrator": {
                    "coordination": {"novelty_injection": value},
                },
            }
            result = ConfigValidator().validate_config(config)
            novelty_errors = [e for e in result.errors if "novelty_injection" in e.message]
            assert len(novelty_errors) == 0, f"Unexpected error for value '{value}': {novelty_errors}"

    def test_config_validator_rejects_invalid(self):
        """Config validator should reject invalid novelty_injection values."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {
                    "id": "agent_a",
                    "backend": {"model": "test-model", "type": "openai"},
                },
            ],
            "orchestrator": {
                "coordination": {"novelty_injection": "extreme"},
            },
        }
        result = ConfigValidator().validate_config(config)
        novelty_errors = [e for e in result.errors if "novelty_injection" in e.message]
        assert len(novelty_errors) > 0


# ---------------------------------------------------------------------------
# Config Parsing / Wiring Tests
# ---------------------------------------------------------------------------


class TestNoveltyInjectionConfigParsing:
    """Tests for novelty_injection wiring through _parse_coordination_config."""

    def test_parse_coordination_config_passes_novelty_injection(self):
        """_parse_coordination_config must pass novelty_injection to CoordinationConfig."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"novelty_injection": "aggressive"}
        result = _parse_coordination_config(coord_cfg)
        assert result.novelty_injection == "aggressive"

    def test_parse_coordination_config_defaults_novelty_injection_to_none(self):
        """_parse_coordination_config must default novelty_injection to 'none'."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {}
        result = _parse_coordination_config(coord_cfg)
        assert result.novelty_injection == "none"

    def test_parse_coordination_config_all_novelty_levels(self):
        """_parse_coordination_config must pass all valid novelty levels."""
        from massgen.cli import _parse_coordination_config

        for level in ("none", "gentle", "moderate", "aggressive"):
            result = _parse_coordination_config({"novelty_injection": level})
            assert result.novelty_injection == level, f"Expected {level}, got {result.novelty_injection}"

    def test_parse_coordination_config_passes_enable_novelty_on_iteration(self):
        """_parse_coordination_config should pass enable_novelty_on_iteration through."""
        from massgen.cli import _parse_coordination_config

        result = _parse_coordination_config({"enable_novelty_on_iteration": True})
        assert result.enable_novelty_on_iteration is True

    def test_parse_coordination_config_passes_enable_quality_rethink_on_iteration(self):
        """_parse_coordination_config should pass enable_quality_rethink_on_iteration through."""
        from massgen.cli import _parse_coordination_config

        result = _parse_coordination_config({"enable_quality_rethink_on_iteration": True})
        assert result.enable_quality_rethink_on_iteration is True


# ---------------------------------------------------------------------------
# Subagent Types Config Tests
# ---------------------------------------------------------------------------


class TestSubagentTypesConfig:
    """Tests for subagent_types field on CoordinationConfig."""

    def test_default_is_none(self):
        """Default subagent_types should be None."""
        config = CoordinationConfig()
        assert config.subagent_types is None

    def test_explicit_list_stored(self):
        """Explicit subagent_types list should be stored."""
        config = CoordinationConfig(subagent_types=["evaluator", "novelty"])
        assert config.subagent_types == ["evaluator", "novelty"]

    def test_config_validator_accepts_valid_list(self):
        """Config validator should accept valid subagent_types list."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "agent_a", "backend": {"model": "test-model", "type": "openai"}},
            ],
            "orchestrator": {
                "coordination": {"subagent_types": ["evaluator", "novelty"]},
            },
        }
        result = ConfigValidator().validate_config(config)
        errors = [e for e in result.errors if "subagent_types" in e.message.lower()]
        assert len(errors) == 0

    def test_config_validator_accepts_null(self):
        """Config validator should accept null subagent_types."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "agent_a", "backend": {"model": "test-model", "type": "openai"}},
            ],
            "orchestrator": {
                "coordination": {"subagent_types": None},
            },
        }
        result = ConfigValidator().validate_config(config)
        errors = [e for e in result.errors if "subagent_types" in e.message.lower()]
        assert len(errors) == 0

    def test_config_validator_rejects_string(self):
        """Config validator should reject subagent_types as a string."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "agent_a", "backend": {"model": "test-model", "type": "openai"}},
            ],
            "orchestrator": {
                "coordination": {"subagent_types": "evaluator"},
            },
        }
        result = ConfigValidator().validate_config(config)
        errors = [e for e in result.errors if "subagent_types" in e.message.lower()]
        assert len(errors) > 0

    def test_config_validator_rejects_empty_string_entry(self):
        """Config validator should reject empty string entries."""
        from massgen.config_validator import ConfigValidator

        config = {
            "agents": [
                {"id": "agent_a", "backend": {"model": "test-model", "type": "openai"}},
            ],
            "orchestrator": {
                "coordination": {"subagent_types": ["evaluator", ""]},
            },
        }
        result = ConfigValidator().validate_config(config)
        errors = [e for e in result.errors if "subagent_types" in e.message.lower()]
        assert len(errors) > 0


class TestSubagentTypesConfigParsing:
    """Tests for subagent_types wiring through _parse_coordination_config."""

    def test_parse_coordination_config_passes_subagent_types(self):
        """_parse_coordination_config must pass subagent_types to CoordinationConfig."""
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"subagent_types": ["evaluator", "novelty"]}
        result = _parse_coordination_config(coord_cfg)
        assert result.subagent_types == ["evaluator", "novelty"]

    def test_parse_coordination_config_defaults_to_none(self):
        """_parse_coordination_config must default subagent_types to None."""
        from massgen.cli import _parse_coordination_config

        result = _parse_coordination_config({})
        assert result.subagent_types is None


# ---------------------------------------------------------------------------
# Builder Subagent Discovery Tests
# ---------------------------------------------------------------------------


class TestBuilderSubagentDiscovery:
    """Tests that the builder subagent type SUBAGENT.md is discoverable."""

    def test_builder_subagent_md_exists(self):
        """massgen/subagent_types/builder/SUBAGENT.md must exist."""
        from pathlib import Path

        subagent_md = Path(__file__).parent.parent / "subagent_types" / "builder" / "SUBAGENT.md"
        assert subagent_md.exists(), f"SUBAGENT.md not found at {subagent_md}"

    def test_scan_discovers_builder_type(self):
        """scan_subagent_types() must discover the builder type when it is in allowed_types."""
        from massgen.subagent.type_scanner import scan_subagent_types

        types = scan_subagent_types(allowed_types=["builder"])
        names = [t.name.lower() for t in types]
        assert "builder" in names

    def test_builder_type_has_description(self):
        """Discovered builder type must have a non-empty description."""
        from massgen.subagent.type_scanner import scan_subagent_types

        types = scan_subagent_types(allowed_types=["builder"])
        builder = next((t for t in types if t.name.lower() == "builder"), None)
        assert builder is not None
        assert builder.description, "builder description must be non-empty"

    def test_builder_type_has_system_prompt(self):
        """Discovered builder type must have a non-empty system prompt."""
        from massgen.subagent.type_scanner import scan_subagent_types

        types = scan_subagent_types(allowed_types=["builder"])
        builder = next((t for t in types if t.name.lower() == "builder"), None)
        assert builder is not None
        assert builder.system_prompt, "builder system_prompt must be non-empty"

    def test_builder_not_in_results_when_not_allowed(self):
        """Builder is not returned when not in allowed_types."""
        from massgen.subagent.type_scanner import scan_subagent_types

        types = scan_subagent_types(allowed_types=["novelty", "critic"])
        names = [t.name.lower() for t in types]
        assert "builder" not in names


# ---------------------------------------------------------------------------
# Convergence Detection Tests
# ---------------------------------------------------------------------------


class TestConvergenceDetection:
    """Tests for convergence detection logic using checklist_history."""

    def _make_orchestrator_with_history(self, history):
        """Create a minimal mock to test _detect_convergence."""
        from massgen.orchestrator import AgentState

        # We test the detection logic directly using AgentState
        state = AgentState()
        state.checklist_history = history
        return state

    def test_agent_state_has_checklist_history(self):
        """AgentState should have a checklist_history field."""
        from massgen.orchestrator import AgentState

        state = AgentState()
        assert hasattr(state, "checklist_history")
        assert state.checklist_history == []

    def test_empty_history_no_convergence(self):
        """Empty history should not detect convergence."""

        history = []
        consecutive = _count_consecutive_incremental(history)
        assert consecutive < 2

    def test_single_incremental_no_convergence(self):
        """Single incremental entry should not trigger convergence (need 2+)."""
        history = [
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
        ]
        consecutive = _count_consecutive_incremental(history)
        assert consecutive < 2

    def test_two_consecutive_incremental_triggers(self):
        """Two consecutive incremental-only entries should trigger convergence."""
        history = [
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
        ]
        consecutive = _count_consecutive_incremental(history)
        assert consecutive >= 2

    def test_structural_round_breaks_streak(self):
        """A structural round should break the incremental streak."""
        history = [
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": False, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
        ]
        consecutive = _count_consecutive_incremental(history)
        # Only 1 trailing incremental, not 2
        assert consecutive < 2

    def test_decision_space_exhausted_counts(self):
        """decision_space_exhausted should also count toward convergence."""
        history = [
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": False, "decision_space_exhausted": True},
                "convergence_offramp": False,
            },
            {
                "verdict": "new_answer",
                "true_count": 2,
                "substantiveness": {"incremental_only": True, "decision_space_exhausted": False},
                "convergence_offramp": False,
            },
        ]
        consecutive = _count_consecutive_incremental(history)
        assert consecutive >= 2


# ---------------------------------------------------------------------------
# NoveltyPressureSection Tests
# ---------------------------------------------------------------------------


class TestNoveltyPressureSection:
    """Tests for NoveltyPressureSection rendering."""

    def test_gentle_level_content(self):
        """Gentle level should produce appropriate suggestion text."""
        from massgen.system_prompt_sections import NoveltyPressureSection

        section = NoveltyPressureSection(
            novelty_level="gentle",
            consecutive_incremental_rounds=2,
            restart_count=0,
        )
        content = section.build_content()
        assert "fundamentally different approach" in content
        assert len(content) > 0

    def test_moderate_level_content(self):
        """Moderate level should produce convergence detection text."""
        from massgen.system_prompt_sections import NoveltyPressureSection

        section = NoveltyPressureSection(
            novelty_level="moderate",
            consecutive_incremental_rounds=3,
            restart_count=0,
        )
        content = section.build_content()
        assert "CONVERGENCE DETECTED" in content
        assert "3" in content  # should include the count

    def test_aggressive_level_content(self):
        """Aggressive level should produce mandatory divergence text."""
        from massgen.system_prompt_sections import NoveltyPressureSection

        section = NoveltyPressureSection(
            novelty_level="aggressive",
            consecutive_incremental_rounds=1,
            restart_count=1,
        )
        content = section.build_content()
        assert "MANDATORY DIVERGENCE" in content

    def test_section_has_medium_priority(self):
        """NoveltyPressureSection should have Priority.MEDIUM (10)."""
        from massgen.system_prompt_sections import NoveltyPressureSection, Priority

        section = NoveltyPressureSection(
            novelty_level="gentle",
            consecutive_incremental_rounds=2,
            restart_count=0,
        )
        assert section.priority == Priority.MEDIUM

    def test_section_includes_round_count(self):
        """Section content should include the consecutive round count."""
        from massgen.system_prompt_sections import NoveltyPressureSection

        section = NoveltyPressureSection(
            novelty_level="moderate",
            consecutive_incremental_rounds=4,
            restart_count=0,
        )
        content = section.build_content()
        assert "4" in content


# ---------------------------------------------------------------------------
# Wiring Tests
# ---------------------------------------------------------------------------


class TestNoveltyPressureWiring:
    """Tests for NoveltyPressureSection wiring in system_message_builder."""

    def test_build_coordination_message_accepts_novelty_param(self):
        """build_coordination_message should accept novelty_pressure_data without error."""
        # Check that the parameter exists in the signature
        import inspect

        from massgen.system_message_builder import SystemMessageBuilder

        sig = inspect.signature(SystemMessageBuilder.build_coordination_message)
        assert "novelty_pressure_data" in sig.parameters

    def test_aggressive_novelty_renders_mandatory_divergence_in_system_message(self):
        """Integration: aggressive novelty with restart_count>0 must produce MANDATORY DIVERGENCE in rendered message."""
        from massgen.message_templates import MessageTemplates
        from massgen.system_message_builder import SystemMessageBuilder

        # Build a minimal config with novelty_injection=aggressive
        config = _make_minimal_config(novelty_level="aggressive")
        templates = MessageTemplates(
            voting_sensitivity="checklist_gated",
            answer_novelty_requirement="lenient",
        )
        builder = SystemMessageBuilder(
            config=config,
            message_templates=templates,
            agents=[],
        )

        agent = _MockAgent()
        message = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            novelty_pressure_data={"consecutive": 2, "restart_count": 3},
        )
        assert "MANDATORY DIVERGENCE" in message

    def test_no_novelty_when_data_is_none(self):
        """Integration: novelty_pressure_data=None must NOT produce novelty text."""
        from massgen.message_templates import MessageTemplates
        from massgen.system_message_builder import SystemMessageBuilder

        config = _make_minimal_config(novelty_level="aggressive")
        templates = MessageTemplates(
            voting_sensitivity="checklist_gated",
            answer_novelty_requirement="lenient",
        )
        builder = SystemMessageBuilder(
            config=config,
            message_templates=templates,
            agents=[],
        )

        agent = _MockAgent()
        message = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            novelty_pressure_data=None,
        )
        assert "MANDATORY DIVERGENCE" not in message
        assert "CONVERGENCE DETECTED" not in message

    def test_moderate_novelty_renders_convergence_detected(self):
        """Integration: moderate novelty must produce CONVERGENCE DETECTED in rendered message."""
        from massgen.message_templates import MessageTemplates
        from massgen.system_message_builder import SystemMessageBuilder

        config = _make_minimal_config(novelty_level="moderate")
        templates = MessageTemplates(
            voting_sensitivity="checklist_gated",
            answer_novelty_requirement="lenient",
        )
        builder = SystemMessageBuilder(
            config=config,
            message_templates=templates,
            agents=[],
        )

        agent = _MockAgent()
        message = builder.build_coordination_message(
            agent=agent,
            agent_id="agent_a",
            answers=None,
            planning_mode_enabled=False,
            use_skills=False,
            enable_memory=False,
            enable_task_planning=False,
            previous_turns=[],
            novelty_pressure_data={"consecutive": 3, "restart_count": 2},
        )
        assert "CONVERGENCE DETECTED" in message


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _MockAgent:
    """Minimal mock agent for system message builder tests."""

    def get_configurable_system_message(self):
        return "You are a test agent."

    @property
    def backend(self):
        return self

    @property
    def config(self):
        return {"model": "test-model"}

    def get(self, key, default=None):
        return {"model": "test-model"}.get(key, default)

    @property
    def filesystem_manager(self):
        return None


def _make_minimal_config(novelty_level="none"):
    """Create a minimal orchestrator config with novelty_injection set."""
    _level = novelty_level

    @dataclass
    class _MinimalCoordConfig:
        novelty_injection: str = _level
        enable_changedoc: bool = False

    @dataclass
    class _MinimalConfig:
        coordination_config: Any = field(default_factory=_MinimalCoordConfig)
        voting_sensitivity: str = "checklist_gated"
        answer_novelty_requirement: str = "lenient"

    return _MinimalConfig()


# ---------------------------------------------------------------------------
# Helper for convergence detection tests (mirrors orchestrator logic)
# ---------------------------------------------------------------------------


def _count_consecutive_incremental(history: list) -> int:
    """Count consecutive incremental-only entries from end of history.

    Mirrors the logic in Orchestrator._detect_convergence().
    """
    consecutive = 0
    for entry in reversed(history):
        sub = entry.get("substantiveness", {})
        if sub.get("incremental_only") or sub.get("decision_space_exhausted"):
            consecutive += 1
        else:
            break
    return consecutive
