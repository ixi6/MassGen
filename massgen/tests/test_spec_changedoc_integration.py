"""Tests for spec-changedoc integration (Fix 5)."""


class TestSpecExecutionGuidance:
    """Test that SPEC_EXECUTION_GUIDANCE includes changedoc traceability."""

    def test_guidance_includes_spec_traceability(self):
        """SPEC_EXECUTION_GUIDANCE should include spec traceability section."""
        from massgen.plan_execution import SPEC_EXECUTION_GUIDANCE

        assert "Spec Traceability" in SPEC_EXECUTION_GUIDANCE
        assert "REQ-" in SPEC_EXECUTION_GUIDANCE
        assert "Spec Coverage" in SPEC_EXECUTION_GUIDANCE

    def test_guidance_includes_diff_instruction(self):
        """SPEC_EXECUTION_GUIDANCE should instruct agents to diff regularly."""
        from massgen.plan_execution import SPEC_EXECUTION_GUIDANCE

        assert "Diff regularly" in SPEC_EXECUTION_GUIDANCE

    def test_guidance_includes_coverage_format(self):
        """SPEC_EXECUTION_GUIDANCE should show coverage format with checkboxes."""
        from massgen.plan_execution import SPEC_EXECUTION_GUIDANCE

        assert "[x]" in SPEC_EXECUTION_GUIDANCE
        assert "[ ]" in SPEC_EXECUTION_GUIDANCE


class TestSpecPresenterInstructions:
    """Test _SPEC_PRESENTER_INSTRUCTIONS constant."""

    def test_presenter_instructions_exist(self):
        """_SPEC_PRESENTER_INSTRUCTIONS should be importable."""
        from massgen.system_prompt_sections import _SPEC_PRESENTER_INSTRUCTIONS

        assert isinstance(_SPEC_PRESENTER_INSTRUCTIONS, str)
        assert len(_SPEC_PRESENTER_INSTRUCTIONS) > 0

    def test_presenter_instructions_include_compliance_report(self):
        """Presenter instructions should require compliance report."""
        from massgen.system_prompt_sections import _SPEC_PRESENTER_INSTRUCTIONS

        assert "Spec Compliance" in _SPEC_PRESENTER_INSTRUCTIONS
        assert "SATISFIED" in _SPEC_PRESENTER_INSTRUCTIONS
        assert "PARTIAL" in _SPEC_PRESENTER_INSTRUCTIONS
        assert "NOT ADDRESSED" in _SPEC_PRESENTER_INSTRUCTIONS

    def test_presenter_instructions_include_coverage_metric(self):
        """Presenter instructions should require coverage percentage."""
        from massgen.system_prompt_sections import _SPEC_PRESENTER_INSTRUCTIONS

        assert "coverage" in _SPEC_PRESENTER_INSTRUCTIONS.lower()


class TestSystemMessageBuilderSpecInjection:
    """Test that build_presentation_message injects spec instructions."""

    def test_spec_artifact_type_injects_instructions(self):
        """When artifact_type='spec', presenter should get spec compliance instructions."""
        from unittest.mock import MagicMock

        from massgen.system_message_builder import SystemMessageBuilder

        config = MagicMock()
        config.enable_changedoc = True
        config.agent_system_messages = {}

        message_templates = MagicMock()
        message_templates.final_presentation_system_message.return_value = "Base presentation"

        agent = MagicMock()
        agent.get_configurable_system_message.return_value = "Agent msg"
        agent.backend = MagicMock()
        agent.backend.filesystem_manager = None

        builder = SystemMessageBuilder(
            config=config,
            message_templates=message_templates,
            agents={"agent1": agent},
        )

        result = builder.build_presentation_message(
            agent=agent,
            all_answers={"agent1": "answer"},
            previous_turns=[],
            artifact_type="spec",
        )

        assert "Spec Compliance" in result

    def test_plan_artifact_type_no_spec_instructions(self):
        """When artifact_type='plan', presenter should NOT get spec compliance instructions."""
        from unittest.mock import MagicMock

        from massgen.system_message_builder import SystemMessageBuilder

        config = MagicMock()
        config.enable_changedoc = True
        config.agent_system_messages = {}

        message_templates = MagicMock()
        message_templates.final_presentation_system_message.return_value = "Base presentation"

        agent = MagicMock()
        agent.get_configurable_system_message.return_value = "Agent msg"
        agent.backend = MagicMock()
        agent.backend.filesystem_manager = None

        builder = SystemMessageBuilder(
            config=config,
            message_templates=message_templates,
            agents={"agent1": agent},
        )

        result = builder.build_presentation_message(
            agent=agent,
            all_answers={"agent1": "answer"},
            previous_turns=[],
            artifact_type="plan",
        )

        assert "Spec Compliance" not in result

    def test_none_artifact_type_no_spec_instructions(self):
        """When artifact_type is None, no spec compliance instructions."""
        from unittest.mock import MagicMock

        from massgen.system_message_builder import SystemMessageBuilder

        config = MagicMock()
        config.enable_changedoc = False
        config.agent_system_messages = {}

        message_templates = MagicMock()
        message_templates.final_presentation_system_message.return_value = "Base presentation"

        agent = MagicMock()
        agent.get_configurable_system_message.return_value = "Agent msg"
        agent.backend = MagicMock()
        agent.backend.filesystem_manager = None

        builder = SystemMessageBuilder(
            config=config,
            message_templates=message_templates,
            agents={"agent1": agent},
        )

        result = builder.build_presentation_message(
            agent=agent,
            all_answers={"agent1": "answer"},
            previous_turns=[],
            artifact_type=None,
        )

        assert "Spec Compliance" not in result
