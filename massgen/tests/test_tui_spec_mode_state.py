"""Unit tests for spec mode support in TUI mode state."""

from massgen.frontend.displays.tui_modes import SpecConfig, TuiModeState


class TestSpecConfig:
    """Test SpecConfig dataclass."""

    def test_default_broadcast_is_false(self):
        config = SpecConfig()
        assert config.broadcast is False

    def test_broadcast_can_be_set(self):
        config = SpecConfig(broadcast="agents")
        assert config.broadcast == "agents"

        config = SpecConfig(broadcast=False)
        assert config.broadcast is False


class TestTuiModeStateSpecMode:
    """Test TuiModeState with spec mode."""

    def test_spec_mode_returns_coordination_overrides(self):
        state = TuiModeState(plan_mode="spec")
        overrides = state.get_coordination_overrides()
        assert overrides != {}
        assert overrides["enable_agent_task_planning"] is True
        assert overrides["task_planning_filesystem_mode"] is True

    def test_normal_mode_returns_empty_overrides(self):
        state = TuiModeState(plan_mode="normal")
        overrides = state.get_coordination_overrides()
        assert overrides == {}

    def test_spec_mode_uses_spec_config_broadcast(self):
        state = TuiModeState(
            plan_mode="spec",
            spec_config=SpecConfig(broadcast="agents"),
        )
        overrides = state.get_coordination_overrides()
        assert overrides["broadcast"] == "agents"

    def test_reset_plan_state_clears_spec_config(self):
        state = TuiModeState(
            plan_mode="spec",
            spec_config=SpecConfig(broadcast="agents"),
        )
        state.reset_plan_state()
        assert state.spec_config.broadcast is False
        assert state.plan_mode == "normal"

    def test_spec_config_field_exists(self):
        state = TuiModeState()
        assert hasattr(state, "spec_config")
        assert isinstance(state.spec_config, SpecConfig)


class TestTuiModeStateQuickMode:
    """Test quick-mode orchestrator overrides."""

    def test_multi_agent_refinement_off_defaults_to_synthesize(self):
        state = TuiModeState(
            agent_mode="multi",
            refinement_enabled=False,
        )

        overrides = state.get_orchestrator_overrides()

        assert overrides["max_new_answers_per_agent"] == 1
        assert overrides["skip_final_presentation"] is True
        assert overrides["disable_injection"] is True
        assert overrides["defer_voting_until_all_answered"] is True
        assert overrides["final_answer_strategy"] == "synthesize"

    def test_single_agent_refinement_off_keeps_direct_answer_flow(self):
        state = TuiModeState(
            agent_mode="single",
            refinement_enabled=False,
        )

        overrides = state.get_orchestrator_overrides()

        assert overrides["skip_voting"] is True
        assert "final_answer_strategy" not in overrides
