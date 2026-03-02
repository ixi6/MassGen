#!/usr/bin/env python3
"""Unit tests for the persona generation engine.

Tests cover:
- PersonaGeneratorConfig validation and defaults
- GeneratedPersona.get_softened_text()
- PersonaGenerator._build_generation_prompt()
- PersonaGenerator._parse_response() with various JSON formats
- PersonaGenerator._generate_fallback_personas()
- PersonaGenerator._create_simplified_agent_configs()
- PersonaGenerator._build_subagent_personas_prompt() for both diversity modes
- DiversityMode constants
"""

import json
from types import SimpleNamespace

import pytest

from massgen.persona_generator import (
    SOFTENED_PERSPECTIVE_TEMPLATE,
    DiversityMode,
    GeneratedPersona,
    PersonaGenerator,
    PersonaGeneratorConfig,
)

# ---------------------------------------------------------------------------
# PersonaGeneratorConfig
# ---------------------------------------------------------------------------


class TestPersonaGeneratorConfig:
    """Tests for PersonaGeneratorConfig dataclass."""

    def test_default_values(self):
        config = PersonaGeneratorConfig()
        assert config.enabled is False
        assert config.diversity_mode == "perspective"
        assert config.persona_guidelines is None
        assert config.persist_across_turns is False
        assert config.after_first_answer == "drop"

    def test_invalid_diversity_mode_falls_back(self):
        config = PersonaGeneratorConfig(diversity_mode="invalid")
        assert config.diversity_mode == DiversityMode.PERSPECTIVE

    def test_valid_implementation_mode(self):
        config = PersonaGeneratorConfig(diversity_mode="implementation")
        assert config.diversity_mode == DiversityMode.IMPLEMENTATION

    def test_valid_methodology_mode(self):
        config = PersonaGeneratorConfig(diversity_mode="methodology")
        assert config.diversity_mode == DiversityMode.METHODOLOGY

    def test_after_first_answer_valid_values(self):
        for value in ("drop", "soften", "keep"):
            config = PersonaGeneratorConfig(after_first_answer=value)
            assert config.after_first_answer == value

    def test_after_first_answer_invalid_falls_back_to_drop(self):
        config = PersonaGeneratorConfig(after_first_answer="invalid")
        assert config.after_first_answer == "drop"


# ---------------------------------------------------------------------------
# GeneratedPersona
# ---------------------------------------------------------------------------


class TestGeneratedPersona:
    """Tests for the GeneratedPersona dataclass."""

    def test_get_softened_text_wraps_original(self):
        persona = GeneratedPersona(
            agent_id="agent_a",
            persona_text="Focus on performance.",
            attributes={},
        )
        softened = persona.get_softened_text()
        assert "Focus on performance." in softened
        # Template splits across line break; normalize whitespace for assertion
        normalized = " ".join(softened.split())
        assert "preference, not a position to defend" in normalized
        assert "synthesize the strongest ideas" in normalized

    def test_softened_template_format(self):
        """Template should have exactly one format placeholder for persona_text."""
        assert "{persona_text}" in SOFTENED_PERSPECTIVE_TEMPLATE


# ---------------------------------------------------------------------------
# DiversityMode
# ---------------------------------------------------------------------------


class TestDiversityMode:
    def test_constants(self):
        assert DiversityMode.PERSPECTIVE == "perspective"
        assert DiversityMode.IMPLEMENTATION == "implementation"
        assert DiversityMode.METHODOLOGY == "methodology"


# ---------------------------------------------------------------------------
# PersonaGenerator._build_generation_prompt
# ---------------------------------------------------------------------------


class TestBuildGenerationPrompt:
    """Tests for prompt construction."""

    def _make_generator(self, **kwargs):
        gen = PersonaGenerator(**kwargs)
        # _build_generation_prompt uses self.strategy which doesn't exist on __init__
        # Set it manually to avoid AttributeError
        if not hasattr(gen, "strategy"):
            gen.strategy = "complementary"
        return gen

    def test_includes_task_and_agent_ids(self):
        gen = self._make_generator()
        prompt = gen._build_generation_prompt(
            agent_ids=["agent_a", "agent_b"],
            task="Analyze this code for bugs",
            existing_system_messages={},
        )
        assert "Analyze this code for bugs" in prompt
        assert "agent_a" in prompt
        assert "agent_b" in prompt

    def test_includes_existing_system_message(self):
        gen = self._make_generator()
        prompt = gen._build_generation_prompt(
            agent_ids=["agent_a"],
            task="Test task",
            existing_system_messages={"agent_a": "You are an expert."},
        )
        assert "You are an expert." in prompt
        assert "Has existing instruction" in prompt

    def test_no_existing_message_shows_none(self):
        gen = self._make_generator()
        prompt = gen._build_generation_prompt(
            agent_ids=["agent_a"],
            task="Test task",
            existing_system_messages={},
        )
        assert "No existing instruction" in prompt

    def test_includes_custom_guidelines(self):
        gen = self._make_generator(guidelines="Focus on security aspects")
        prompt = gen._build_generation_prompt(
            agent_ids=["agent_a"],
            task="Test task",
            existing_system_messages={},
        )
        assert "Focus on security aspects" in prompt


# ---------------------------------------------------------------------------
# PersonaGenerator._parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for LLM response parsing with multiple strategies."""

    def _make_generator(self):
        gen = PersonaGenerator()
        gen.strategy = "complementary"
        return gen

    def test_parses_direct_json(self):
        gen = self._make_generator()
        response = json.dumps(
            {
                "personas": {
                    "agent_a": {
                        "persona_text": "Be analytical.",
                        "attributes": {"thinking_style": "analytical"},
                    },
                },
            },
        )
        result = gen._parse_response(response, ["agent_a"])
        assert "agent_a" in result
        assert result["agent_a"].persona_text == "Be analytical."
        assert result["agent_a"].attributes["thinking_style"] == "analytical"

    def test_parses_json_in_markdown_code_block(self):
        gen = self._make_generator()
        response = """Here are the personas:

```json
{
    "personas": {
        "agent_a": {
            "persona_text": "Be creative.",
            "attributes": {}
        }
    }
}
```
"""
        result = gen._parse_response(response, ["agent_a"])
        assert result["agent_a"].persona_text == "Be creative."

    def test_parses_json_in_generic_code_block(self):
        gen = self._make_generator()
        response = """```
{"personas": {"agent_a": {"persona_text": "Be systematic.", "attributes": {}}}}
```"""
        result = gen._parse_response(response, ["agent_a"])
        assert result["agent_a"].persona_text == "Be systematic."

    def test_extracts_json_by_brace_matching(self):
        gen = self._make_generator()
        response = 'Some preamble text {"personas": {"agent_a": {"persona_text": "Be critical.", "attributes": {}}}} trailing text'
        result = gen._parse_response(response, ["agent_a"])
        assert result["agent_a"].persona_text == "Be critical."

    def test_missing_agent_gets_default(self):
        gen = self._make_generator()
        response = json.dumps(
            {
                "personas": {
                    "agent_a": {"persona_text": "Custom.", "attributes": {}},
                },
            },
        )
        result = gen._parse_response(response, ["agent_a", "agent_b"])
        assert result["agent_a"].persona_text == "Custom."
        assert result["agent_b"].persona_text == "Approach this task thoughtfully and thoroughly."

    def test_unparseable_response_returns_fallback(self):
        gen = self._make_generator()
        result = gen._parse_response("totally invalid content", ["agent_a"])
        assert "agent_a" in result
        # Fallback personas have specific thinking_style attributes
        assert result["agent_a"].attributes.get("thinking_style") is not None

    def test_multiple_agents(self):
        gen = self._make_generator()
        response = json.dumps(
            {
                "personas": {
                    "agent_a": {"persona_text": "Focus on details.", "attributes": {"thinking_style": "analytical"}},
                    "agent_b": {"persona_text": "Think big picture.", "attributes": {"thinking_style": "creative"}},
                    "agent_c": {"persona_text": "Be systematic.", "attributes": {"thinking_style": "systematic"}},
                },
            },
        )
        result = gen._parse_response(response, ["agent_a", "agent_b", "agent_c"])
        assert len(result) == 3
        assert result["agent_a"].persona_text == "Focus on details."
        assert result["agent_b"].persona_text == "Think big picture."


# ---------------------------------------------------------------------------
# PersonaGenerator._generate_fallback_personas
# ---------------------------------------------------------------------------


class TestFallbackPersonas:
    """Tests for fallback persona generation."""

    def _make_generator(self):
        gen = PersonaGenerator()
        gen.strategy = "complementary"
        return gen

    def test_generates_for_all_agents(self):
        gen = self._make_generator()
        result = gen._generate_fallback_personas(["a", "b", "c"])
        assert len(result) == 3
        assert all(isinstance(p, GeneratedPersona) for p in result.values())

    def test_different_styles_for_different_agents(self):
        gen = self._make_generator()
        result = gen._generate_fallback_personas(["a", "b", "c", "d", "e"])
        styles = [p.attributes["thinking_style"] for p in result.values()]
        assert len(set(styles)) == 5  # All different

    def test_cycles_after_five_agents(self):
        gen = self._make_generator()
        result = gen._generate_fallback_personas(["a", "b", "c", "d", "e", "f"])
        # 6th agent should cycle back to first style
        styles = [result[aid].attributes["thinking_style"] for aid in ["a", "f"]]
        assert styles[0] == styles[1]

    def test_empty_agents_returns_empty(self):
        gen = self._make_generator()
        result = gen._generate_fallback_personas([])
        assert result == {}

    def test_fallback_personas_have_required_attributes(self):
        gen = self._make_generator()
        result = gen._generate_fallback_personas(["agent_a"])
        persona = result["agent_a"]
        assert persona.agent_id == "agent_a"
        assert len(persona.persona_text) > 0
        assert "thinking_style" in persona.attributes
        assert "focus_area" in persona.attributes
        assert "communication" in persona.attributes

    def test_fallback_methodology_mode_prescribes_approaches(self):
        gen = PersonaGenerator(diversity_mode="methodology")
        gen.strategy = "complementary"
        result = gen._generate_fallback_personas(["a", "b", "c", "d", "e"])
        # Each agent should have a different approach
        styles = [p.attributes["thinking_style"] for p in result.values()]
        assert len(set(styles)) == 5
        # Persona text should describe a working approach, not just a thinking style
        for persona in result.values():
            assert len(persona.persona_text) > 0

    def test_fallback_methodology_mode_cycles(self):
        gen = PersonaGenerator(diversity_mode="methodology")
        gen.strategy = "complementary"
        result = gen._generate_fallback_personas(["a", "b", "c", "d", "e", "f"])
        styles = [result[aid].attributes["thinking_style"] for aid in ["a", "f"]]
        assert styles[0] == styles[1]


# ---------------------------------------------------------------------------
# PersonaGenerator._create_simplified_agent_configs
# ---------------------------------------------------------------------------


class TestCreateSimplifiedConfigs:
    """Tests for agent config simplification."""

    def _make_generator(self):
        gen = PersonaGenerator()
        gen.strategy = "complementary"
        return gen

    def test_strips_tools(self):
        gen = self._make_generator()
        parent = [
            {
                "id": "agent_a",
                "backend": {
                    "type": "openai",
                    "model": "gpt-4o-mini",
                    "enable_mcp_command_line": True,
                    "enable_code_based_tools": True,
                },
            },
        ]
        result = gen._create_simplified_agent_configs(parent)
        assert len(result) == 1
        backend = result[0]["backend"]
        assert backend["enable_mcp_command_line"] is False
        assert backend["enable_code_based_tools"] is False
        assert backend["exclude_file_operation_mcps"] is True
        assert backend["model"] == "gpt-4o-mini"

    def test_preserves_model_and_type(self):
        gen = self._make_generator()
        parent = [
            {"id": "agent_a", "backend": {"type": "claude", "model": "claude-sonnet-4-5-20250929"}},
        ]
        result = gen._create_simplified_agent_configs(parent)
        assert result[0]["backend"]["type"] == "claude"
        assert result[0]["backend"]["model"] == "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# PersonaGenerator._build_subagent_personas_prompt (both modes)
# ---------------------------------------------------------------------------


class TestBuildSubagentPrompt:
    """Tests for the subagent persona prompt builder."""

    def _make_generator(self, diversity_mode="perspective"):
        gen = PersonaGenerator(diversity_mode=diversity_mode)
        gen.strategy = "complementary"
        return gen

    def test_perspective_mode_prompt(self):
        gen = self._make_generator(diversity_mode="perspective")
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a", "agent_b"],
            task="Build a website",
            existing_system_messages={},
        )
        assert "PERSPECTIVES" in prompt
        assert "agent_a" in prompt
        assert "personas.json" in prompt

    def test_implementation_mode_prompt(self):
        gen = self._make_generator(diversity_mode="implementation")
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a"],
            task="Build a website",
            existing_system_messages={},
        )
        assert "SOLUTION APPROACHES" in prompt
        assert "personas.json" in prompt

    def test_includes_guidelines_when_provided(self):
        gen = self._make_generator()
        gen.guidelines = "Each agent should have a security focus"
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a"],
            task="Test task",
            existing_system_messages={},
        )
        assert "Each agent should have a security focus" in prompt

    def test_includes_existing_system_messages(self):
        gen = self._make_generator()
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a"],
            task="Test task",
            existing_system_messages={"agent_a": "You are a security expert"},
        )
        assert "You are a security expert" in prompt

    def test_methodology_mode_prompt(self):
        gen = self._make_generator(diversity_mode="methodology")
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a", "agent_b"],
            task="Build a portfolio website",
            existing_system_messages={},
        )
        # Should focus on working approaches / methodology
        assert "WORKING APPROACH" in prompt or "METHODOLOGY" in prompt
        assert "agent_a" in prompt
        assert "agent_b" in prompt
        assert "personas.json" in prompt
        # Should NOT be about perspectives or solution types
        assert "PERSPECTIVES" not in prompt
        assert "SOLUTION APPROACHES" not in prompt

    def test_methodology_mode_emphasizes_how_to_work(self):
        gen = self._make_generator(diversity_mode="methodology")
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a", "agent_b", "agent_c"],
            task="Create a presentation about climate change",
            existing_system_messages={},
        )
        prompt_lower = prompt.lower()
        # Should emphasize how agents approach/tackle/structure work
        assert "how" in prompt_lower
        assert any(word in prompt_lower for word in ["approach", "tackle", "structure", "process", "method"])

    def test_methodology_mode_requests_different_approaches(self):
        gen = self._make_generator(diversity_mode="methodology")
        prompt = gen._build_subagent_personas_prompt(
            agent_ids=["agent_a", "agent_b"],
            task="Refactor the authentication module",
            existing_system_messages={},
        )
        prompt_lower = prompt.lower()
        # Should request genuinely different approaches
        assert "different" in prompt_lower


# ---------------------------------------------------------------------------
# PersonaGenerator._get_strategy_instructions
# ---------------------------------------------------------------------------


class TestStrategyInstructions:
    """Tests for strategy-specific prompt instructions."""

    def _make_generator(self, strategy="complementary"):
        gen = PersonaGenerator()
        gen.strategy = strategy
        return gen

    def test_complementary_strategy(self):
        gen = self._make_generator("complementary")
        text = gen._get_strategy_instructions()
        assert "complement" in text.lower()

    def test_diverse_strategy(self):
        gen = self._make_generator("diverse")
        text = gen._get_strategy_instructions()
        assert "diversity" in text.lower() or "diverse" in text.lower()

    def test_specialized_strategy(self):
        gen = self._make_generator("specialized")
        text = gen._get_strategy_instructions()
        assert "expert" in text.lower() or "specialized" in text.lower()

    def test_adversarial_strategy(self):
        gen = self._make_generator("adversarial")
        text = gen._get_strategy_instructions()
        assert "adversarial" in text.lower() or "devil" in text.lower()

    def test_unknown_strategy_defaults_to_complementary(self):
        gen = self._make_generator("unknown_strategy")
        text = gen._get_strategy_instructions()
        assert "complement" in text.lower()


@pytest.mark.asyncio
async def test_subagent_persona_generation_passes_voting_sensitivity(monkeypatch, tmp_path):
    captured = {}

    class _FakeSubagentManager:
        def __init__(self, *args, **kwargs):
            captured["coordination"] = kwargs["subagent_orchestrator_config"].coordination

        async def spawn_subagent(self, **kwargs):
            return SimpleNamespace(
                success=True,
                answer=json.dumps(
                    {
                        "personas": {
                            "agent_a": {
                                "persona_text": "Be rigorous and practical.",
                                "attributes": {},
                            },
                        },
                    },
                ),
                error=None,
                workspace_path=None,
            )

        def get_subagent_display_data(self, _subagent_id):
            return None

    monkeypatch.setattr("massgen.subagent.manager.SubagentManager", _FakeSubagentManager)

    generator = PersonaGenerator()
    personas = await generator.generate_personas_via_subagent(
        agent_ids=["agent_a"],
        task="Test task",
        existing_system_messages={},
        parent_agent_configs=[{"id": "agent_a", "backend": {"type": "openai", "model": "gpt-4o-mini"}}],
        parent_workspace=str(tmp_path),
        orchestrator_id="orch_test",
        voting_sensitivity="checklist_gated",
    )

    assert "agent_a" in personas
    assert captured["coordination"]["voting_sensitivity"] == "checklist_gated"
