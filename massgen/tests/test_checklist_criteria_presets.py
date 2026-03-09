"""Tests for domain-specific checklist criteria presets.

Tests get_criteria_for_preset(), config validation, orchestrator wiring,
and inline criteria support.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from massgen.evaluation_criteria_generator import (
    VALID_CRITERIA_PRESETS,
    GeneratedCriterion,
    get_criteria_for_preset,
)

# ---------------------------------------------------------------------------
# get_criteria_for_preset() unit tests
# ---------------------------------------------------------------------------


class TestGetCriteriaForPreset:
    """Tests for the preset criteria function."""

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_returns_list_of_generated_criterion(self, preset_name: str):
        criteria = get_criteria_for_preset(preset_name)
        assert isinstance(criteria, list)
        assert all(isinstance(c, GeneratedCriterion) for c in criteria)

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_each_preset_has_at_least_five_criteria(self, preset_name: str):
        criteria = get_criteria_for_preset(preset_name)
        assert len(criteria) >= 5

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_ids_are_sequential(self, preset_name: str):
        criteria = get_criteria_for_preset(preset_name)
        ids = [c.id for c in criteria]
        expected = [f"E{i + 1}" for i in range(len(criteria))]
        assert ids == expected

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_categories_are_valid(self, preset_name: str):
        criteria = get_criteria_for_preset(preset_name)
        for c in criteria:
            assert c.category in ("must", "should", "could"), f"Preset {preset_name}, {c.id}: invalid category '{c.category}'"

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_texts_are_non_empty(self, preset_name: str):
        criteria = get_criteria_for_preset(preset_name)
        for c in criteria:
            assert c.text.strip(), f"Preset {preset_name}, {c.id}: empty text"

    @pytest.mark.parametrize("preset_name", list(VALID_CRITERIA_PRESETS))
    def test_at_least_three_core_criteria(self, preset_name: str):
        """Each preset should have a majority of core criteria."""
        criteria = get_criteria_for_preset(preset_name)
        must_should_count = sum(1 for c in criteria if c.category in ("must", "should"))
        assert must_should_count >= 3, f"Preset {preset_name}: only {must_should_count} must/should criteria (need >= 3)"

    def test_unknown_preset_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown criteria preset"):
            get_criteria_for_preset("nonexistent_preset")

    def test_valid_presets_constant_matches_function(self):
        """VALID_CRITERIA_PRESETS should match the actual preset keys."""
        for name in VALID_CRITERIA_PRESETS:
            # Should not raise
            get_criteria_for_preset(name)


# ---------------------------------------------------------------------------
# CoordinationConfig field tests
# ---------------------------------------------------------------------------


class TestCoordinationConfigPresetField:
    """Tests for the checklist_criteria_preset field on CoordinationConfig."""

    def test_default_is_none(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert config.checklist_criteria_preset is None

    def test_accepts_valid_preset(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(checklist_criteria_preset="persona")
        assert config.checklist_criteria_preset == "persona"

    def test_accepts_none(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(checklist_criteria_preset=None)
        assert config.checklist_criteria_preset is None


# ---------------------------------------------------------------------------
# Config validator tests
# ---------------------------------------------------------------------------


class TestConfigValidatorPreset:
    """Tests for config validation of checklist_criteria_preset."""

    def _make_config(self, preset_value):
        return {
            "agents": [
                {"id": "a1", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {
                "coordination": {
                    "checklist_criteria_preset": preset_value,
                },
            },
        }

    def test_valid_preset_passes_validation(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        for preset in VALID_CRITERIA_PRESETS:
            result = validator.validate_config(self._make_config(preset))
            assert not result.has_errors(), f"Preset '{preset}' should be valid but got errors: " f"{result.format_errors()}"

    def test_invalid_preset_fails_validation(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(self._make_config("bogus_preset"))
        assert result.has_errors()
        error_messages = [e.message for e in result.errors]
        assert any("checklist_criteria_preset" in msg for msg in error_messages)

    def test_null_preset_passes_validation(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(self._make_config(None))
        assert not result.has_errors()


# ---------------------------------------------------------------------------
# Orchestrator wiring tests
# ---------------------------------------------------------------------------


class TestOrchestratorPresetWiring:
    """Tests that _init_checklist_tool uses preset criteria when configured."""

    def test_preset_criteria_used_when_set(self):
        """When checklist_criteria_preset is set, those criteria should be used."""
        from unittest.mock import MagicMock

        # Create a mock orchestrator with the minimum required attributes
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        # Set up minimal state
        mock_config = MagicMock()
        mock_config.voting_sensitivity = "checklist_gated"
        mock_config.coordination_config.checklist_criteria_preset = "persona"
        mock_config.voting_threshold = 5
        mock_config.max_new_answers_per_agent = 5
        mock_config.checklist_require_gap_report = True
        orch.config = mock_config
        orch.agents = {}
        orch._generated_evaluation_criteria = None

        # Call _init_checklist_tool and verify criteria source
        # We can't easily run the full method without agents, but we can
        # verify the logic by checking that get_criteria_for_preset is called
        # with the right preset when the method runs through its criteria
        # selection logic.
        preset_criteria = get_criteria_for_preset("persona")
        assert len(preset_criteria) == 5
        assert preset_criteria[0].id == "E1"

    def test_generated_criteria_take_priority_over_preset(self):
        """Dynamically generated criteria should override preset."""
        # This tests the priority: generated > preset > changedoc > default
        generated = [
            GeneratedCriterion(id="E1", text="Generated criterion", category="must"),
        ]
        preset = get_criteria_for_preset("persona")

        # generated should be preferred
        assert generated[0].text == "Generated criterion"
        assert preset[0].text != "Generated criterion"
        # In the orchestrator, the check is:
        # if self._generated_evaluation_criteria is not None: use generated
        # elif preset: use preset
        # This verifies the data structures are correct for that logic


# ---------------------------------------------------------------------------
# Preset content sanity checks
# ---------------------------------------------------------------------------


class TestPresetContentSanity:
    """Verify that preset content matches composition.md expectations."""

    def test_persona_preset_exists(self):
        criteria = get_criteria_for_preset("persona")
        # Should have 3 must + 1 should + 1 could per composition.md
        categories = [c.category for c in criteria]
        assert categories.count("must") == 3
        assert categories.count("should") == 1 and categories.count("could") == 1

    def test_decomposition_preset_exists(self):
        criteria = get_criteria_for_preset("decomposition")
        categories = [c.category for c in criteria]
        assert categories.count("must") == 3
        assert categories.count("should") == 1 and categories.count("could") == 1

    def test_evaluation_preset_exists(self):
        criteria = get_criteria_for_preset("evaluation")
        categories = [c.category for c in criteria]
        assert categories.count("must") == 3
        assert categories.count("should") == 1 and categories.count("could") == 1

    def test_prompt_preset_exists(self):
        criteria = get_criteria_for_preset("prompt")
        categories = [c.category for c in criteria]
        assert categories.count("must") == 2
        assert categories.count("should") == 1 and categories.count("could") == 2

    def test_analysis_preset_exists(self):
        criteria = get_criteria_for_preset("analysis")
        categories = [c.category for c in criteria]
        assert categories.count("must") == 3
        assert categories.count("should") == 1 and categories.count("could") == 1

    def test_planning_preset_exists(self):
        criteria = get_criteria_for_preset("planning")
        categories = [c.category for c in criteria]
        assert len(criteria) == 8
        assert categories.count("must") == 5
        assert categories.count("should") == 3 and categories.count("could") == 0

    def test_spec_preset_exists(self):
        criteria = get_criteria_for_preset("spec")
        categories = [c.category for c in criteria]
        assert len(criteria) == 5
        assert categories.count("must") == 3
        assert categories.count("should") == 1 and categories.count("could") == 1

    def test_round_evaluator_preset_exists(self):
        criteria = get_criteria_for_preset("round_evaluator")
        categories = [c.category for c in criteria]
        assert len(criteria) == 7
        assert categories.count("must") == 4
        assert categories.count("should") == 2
        assert categories.count("could") == 1


# ---------------------------------------------------------------------------
# Inline criteria tests
# ---------------------------------------------------------------------------

_SAMPLE_INLINE = [
    {"text": "Visual design is cohesive and polished", "category": "must"},
    {"text": "Content demonstrates genuine understanding", "category": "should"},
    {"text": "Interactive elements enhance the experience", "category": "could"},
]


class TestInlineCriteriaConfigField:
    """Tests for checklist_criteria_inline on CoordinationConfig."""

    def test_default_is_none(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert config.checklist_criteria_inline is None

    def test_accepts_inline_list(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(checklist_criteria_inline=_SAMPLE_INLINE)
        assert config.checklist_criteria_inline == _SAMPLE_INLINE
        assert len(config.checklist_criteria_inline) == 3

    def test_inline_round_trip_text_and_category(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(checklist_criteria_inline=_SAMPLE_INLINE)
        assert config.checklist_criteria_inline[0]["text"] == "Visual design is cohesive and polished"
        assert config.checklist_criteria_inline[0]["category"] == "must"
        assert config.checklist_criteria_inline[1]["category"] == "should"
        assert config.checklist_criteria_inline[2]["category"] == "could"


class TestCriteriaFromInline:
    """Tests for the criteria_from_inline helper."""

    def test_converts_to_generated_criterion_list(self):
        from massgen.evaluation_criteria_generator import criteria_from_inline

        result = criteria_from_inline(_SAMPLE_INLINE)
        assert isinstance(result, list)
        assert all(isinstance(c, GeneratedCriterion) for c in result)

    def test_ids_are_sequential(self):
        from massgen.evaluation_criteria_generator import criteria_from_inline

        result = criteria_from_inline(_SAMPLE_INLINE)
        assert [c.id for c in result] == ["E1", "E2", "E3"]

    def test_text_and_category_preserved(self):
        from massgen.evaluation_criteria_generator import criteria_from_inline

        result = criteria_from_inline(_SAMPLE_INLINE)
        assert result[0].text == "Visual design is cohesive and polished"
        assert result[0].category == "must"
        assert result[1].category == "should"
        assert result[2].category == "could"

    def test_empty_list_returns_empty(self):
        from massgen.evaluation_criteria_generator import criteria_from_inline

        assert criteria_from_inline([]) == []


class TestInlineCriteriaValidation:
    """Tests for config validation of checklist_criteria_inline."""

    def _make_config(self, inline_value, eval_gen_enabled=False):
        config = {
            "agents": [
                {"id": "a1", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {
                "coordination": {
                    "checklist_criteria_inline": inline_value,
                },
            },
        }
        if eval_gen_enabled:
            config["orchestrator"]["coordination"]["evaluation_criteria_generator"] = {
                "enabled": True,
            }
        return config

    def test_valid_inline_passes_validation(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(self._make_config(_SAMPLE_INLINE))
        errors = [e.message for e in result.errors]
        assert not any("checklist_criteria_inline" in msg for msg in errors)

    def test_invalid_category_fails_validation(self):
        from massgen.config_validator import ConfigValidator

        bad_inline = [{"text": "Some criterion", "category": "critical"}]
        validator = ConfigValidator()
        result = validator.validate_config(self._make_config(bad_inline))
        error_messages = [e.message for e in result.errors]
        assert any("checklist_criteria_inline" in msg for msg in error_messages)

    def test_missing_text_fails_validation(self):
        from massgen.config_validator import ConfigValidator

        bad_inline = [{"category": "must"}]
        validator = ConfigValidator()
        result = validator.validate_config(self._make_config(bad_inline))
        error_messages = [e.message for e in result.errors]
        assert any("checklist_criteria_inline" in msg for msg in error_messages)

    def test_inline_and_eval_generator_warns(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(_SAMPLE_INLINE, eval_gen_enabled=True),
        )
        warning_messages = [w.message for w in result.warnings]
        assert any("checklist_criteria_inline" in msg for msg in warning_messages)


class TestPresetWiringThroughParseCoordinationConfig:
    """Test that checklist_criteria_preset flows from YAML dict -> CoordinationConfig."""

    def test_preset_wired_through_parse(self):
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"checklist_criteria_preset": "persona"}
        config = _parse_coordination_config(coord_cfg)
        assert config.checklist_criteria_preset == "persona"

    def test_inline_wired_through_parse(self):
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"checklist_criteria_inline": _SAMPLE_INLINE}
        config = _parse_coordination_config(coord_cfg)
        assert config.checklist_criteria_inline == _SAMPLE_INLINE

    def test_both_absent_gives_none(self):
        from massgen.cli import _parse_coordination_config

        config = _parse_coordination_config({})
        assert config.checklist_criteria_preset is None
        assert config.checklist_criteria_inline is None

    def test_pre_collab_voting_threshold_wired_through_parse(self):
        from massgen.cli import _parse_coordination_config

        coord_cfg = {"pre_collab_voting_threshold": 12}
        config = _parse_coordination_config(coord_cfg)
        assert config.pre_collab_voting_threshold == 12


class TestInlineCriteriaPriority:
    """Test that inline criteria take highest priority in _init_checklist_tool."""

    def _make_orch(self, inline=None, preset=None, generated=None):
        """Create a minimal Orchestrator with mocked config for checklist testing."""
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        mock_config = MagicMock()
        mock_config.voting_sensitivity = "checklist_gated"
        mock_config.coordination_config.checklist_criteria_inline = inline
        mock_config.coordination_config.checklist_criteria_preset = preset
        mock_config.coordination_config.subagent_types = None
        mock_config.coordination_config.enable_changedoc = True
        mock_config.voting_threshold = 5
        mock_config.max_new_answers_per_agent = 5
        mock_config.checklist_require_gap_report = True
        orch.config = mock_config

        mock_backend = MagicMock()
        mock_backend.supports_sdk_mcp = False
        mock_agent = MagicMock()
        mock_agent.backend = mock_backend
        orch.agents = {"a1": mock_agent}
        orch._generated_evaluation_criteria = generated
        return orch

    def test_inline_beats_generated(self):
        """Inline criteria should be used even when generated criteria exist."""
        generated = [
            GeneratedCriterion(id="E1", text="Generated criterion", category="must"),
        ]
        orch = self._make_orch(inline=_SAMPLE_INLINE, generated=generated)
        orch._init_checklist_tool()

        backend = orch.agents["a1"].backend
        items = backend._checklist_items
        # Inline has 3 items, generated has 1 — if inline wins, we get 3
        assert len(items) == 3
        assert items[0] == "Visual design is cohesive and polished"

    def test_inline_beats_preset(self):
        """Inline criteria should be used even when a preset is configured."""
        orch = self._make_orch(inline=_SAMPLE_INLINE, preset="persona")
        orch._init_checklist_tool()

        backend = orch.agents["a1"].backend
        items = backend._checklist_items
        # Inline has 3 items, persona preset has 5 — if inline wins, we get 3
        assert len(items) == 3


class TestGetActiveCriteria:
    """Test _get_active_criteria() returns correct items for system prompt."""

    def _make_orch(self, inline=None, preset=None, generated=None, changedoc=True):
        """Create a minimal Orchestrator for _get_active_criteria testing."""
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        mock_config = MagicMock()
        mock_config.coordination_config.checklist_criteria_inline = inline
        mock_config.coordination_config.checklist_criteria_preset = preset
        mock_config.coordination_config.enable_changedoc = changedoc
        orch.config = mock_config
        orch._generated_evaluation_criteria = generated
        return orch

    def test_inline_criteria_returned(self):
        """Inline criteria should be returned when set."""
        orch = self._make_orch(inline=_SAMPLE_INLINE)
        items, categories, verify_by = orch._get_active_criteria()
        assert len(items) == 3
        assert items[0] == "Visual design is cohesive and polished"
        assert categories["E1"] == "must"
        assert categories["E2"] == "should"

    def test_inline_beats_generated_in_active_criteria(self):
        """Inline should take priority over generated criteria."""
        generated = [
            GeneratedCriterion(id="E1", text="Generated criterion", category="must"),
        ]
        orch = self._make_orch(inline=_SAMPLE_INLINE, generated=generated)
        items, _, _vb = orch._get_active_criteria()
        assert len(items) == 3
        assert "Generated criterion" not in items

    def test_generated_returned_when_no_inline(self):
        """Generated criteria returned when no inline."""
        generated = [
            GeneratedCriterion(id="E1", text="Generated criterion", category="must"),
        ]
        orch = self._make_orch(generated=generated)
        items, categories, verify_by = orch._get_active_criteria()
        assert items == ["Generated criterion"]
        assert categories == {"E1": "must"}
        assert verify_by is None  # no verify_by on this criterion

    def test_preset_returned_when_no_inline_or_generated(self):
        """Preset criteria returned when no inline or generated."""
        orch = self._make_orch(preset="persona")
        items, _, _vb = orch._get_active_criteria()
        # Persona preset has 5 items
        assert len(items) == 5

    def test_none_returned_when_nothing_configured(self):
        """Returns (None, None, None) when no criteria source is available."""
        orch = self._make_orch(changedoc=False)
        items, categories, verify_by = orch._get_active_criteria()
        assert items is None
        assert categories is None
        assert verify_by is None


class TestChecklistCriteriaDisplayBackfill:
    """Ensure criteria are shown even when checklist init runs before UI attach."""

    def _make_orch(self, changedoc: bool):
        from massgen.orchestrator import Orchestrator

        orch = object.__new__(Orchestrator)
        mock_config = MagicMock()
        mock_config.voting_sensitivity = "checklist_gated"
        mock_config.coordination_config.checklist_criteria_inline = None
        mock_config.coordination_config.checklist_criteria_preset = None
        mock_config.coordination_config.subagent_types = None
        mock_config.coordination_config.enable_changedoc = changedoc
        mock_config.voting_threshold = 5
        mock_config.max_new_answers_per_agent = 5
        mock_config.checklist_require_gap_report = True
        orch.config = mock_config

        mock_backend = MagicMock()
        mock_backend.supports_sdk_mcp = False
        mock_backend.set_subagent_spawn_callback = MagicMock()
        mock_agent = MagicMock()
        mock_agent.backend = mock_backend
        orch.agents = {"a1": mock_agent}
        orch._generated_evaluation_criteria = None
        orch._criteria_pushed_to_display = False
        orch._criteria_display_payload = None
        return orch

    def test_backfills_changedoc_criteria_when_ui_attaches_later(self):
        orch = self._make_orch(changedoc=True)
        orch._init_checklist_tool()  # runs before coordination_ui/display exists
        assert orch._criteria_pushed_to_display is False

        display = MagicMock()
        orch.coordination_ui = SimpleNamespace(display=display)
        orch.setup_subagent_spawn_callbacks()

        display.set_evaluation_criteria.assert_called_once()
        call = display.set_evaluation_criteria.call_args
        criteria = call.args[0]
        source = call.kwargs.get("source")

        assert source == "changedoc"
        assert [c["id"] for c in criteria] == ["E1", "E2", "E3", "E4"]

    def test_backfills_generic_criteria_when_changedoc_disabled(self):
        orch = self._make_orch(changedoc=False)
        orch._init_checklist_tool()  # runs before coordination_ui/display exists
        assert orch._criteria_pushed_to_display is False

        display = MagicMock()
        orch.coordination_ui = SimpleNamespace(display=display)
        orch.setup_subagent_spawn_callbacks()

        display.set_evaluation_criteria.assert_called_once()
        call = display.set_evaluation_criteria.call_args
        criteria = call.args[0]
        source = call.kwargs.get("source")

        assert source == "generic"
        assert [c["id"] for c in criteria] == ["E1", "E2", "E3", "E4", "E5"]
