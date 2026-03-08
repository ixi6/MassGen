"""Unit tests for SystemMessageBuilder core behavior."""

from __future__ import annotations

from massgen.agent_config import AgentConfig
from massgen.message_templates import MessageTemplates
from massgen.system_message_builder import SystemMessageBuilder


class _DummyBackend:
    def __init__(self):
        self.config = {"model": "gpt-4o-mini"}
        self.filesystem_manager = None


class _DummyAgent:
    def __init__(self, system_message: str):
        self.backend = _DummyBackend()
        self._system_message = system_message

    def get_configurable_system_message(self):
        return self._system_message


def _build_message_builder() -> SystemMessageBuilder:
    config = AgentConfig.create_openai_config()
    templates = MessageTemplates()
    return SystemMessageBuilder(
        config=config,
        message_templates=templates,
        agents={},
    )


def test_build_coordination_message_includes_vote_only_and_planning_sections():
    builder = _build_message_builder()
    agent = _DummyAgent("You are Agent A.")

    system_message = builder.build_coordination_message(
        agent=agent,
        agent_id="agent_a",
        answers={},
        planning_mode_enabled=True,
        use_skills=False,
        enable_memory=False,
        enable_task_planning=False,
        previous_turns=[],
        vote_only=True,
        human_qa_history=None,
        agent_mapping=None,
        voting_sensitivity_override=None,
    )

    assert "<system_prompt>" in system_message
    assert "<agent_identity" in system_message
    assert "You are Agent A." in system_message
    assert "MUST vote for the best existing answer" in system_message
    assert builder.config.coordination_config.planning_mode_instruction in system_message


def test_build_presentation_message_without_filesystem_uses_template_instructions():
    builder = _build_message_builder()
    agent = _DummyAgent("You are Agent A.")

    presentation_message = builder.build_presentation_message(
        agent=agent,
        all_answers={"agent_a": "Answer A"},
        previous_turns=[],
        enable_command_execution=True,
    )

    assert "You are Agent A." in presentation_message
    assert "selected as the winning presenter" in presentation_message
    assert "new_answer" in presentation_message
    assert "requirements.txt" in presentation_message


def test_parse_memory_file_frontmatter_and_invalid_content(tmp_path):
    valid_memory = tmp_path / "valid.md"
    valid_memory.write_text(
        """---
name: short-note
description: test memory
tier: short_term
agent_id: agent_a
created: 2026-02-07
updated: 2026-02-07
---
Remember to validate outputs first.
""",
    )
    parsed = SystemMessageBuilder._parse_memory_file(valid_memory)
    assert parsed is not None
    assert parsed["name"] == "short-note"
    assert parsed["tier"] == "short_term"
    assert parsed["content"] == "Remember to validate outputs first."

    invalid_memory = tmp_path / "invalid.md"
    invalid_memory.write_text("no frontmatter here")
    assert SystemMessageBuilder._parse_memory_file(invalid_memory) is None
