"""Tests for GEPA-inspired evaluation criteria generation.

Tests cover:
- Default criteria fallback (when generation is disabled or fails)
- Changedoc mode adds traceability criterion
- Criteria count validation
- Config parsing
- E-prefix on all criteria
- Dynamic core/stretch categories
"""

import json

from massgen.evaluation_criteria_generator import (
    EvaluationCriteriaGeneratorConfig,
    get_default_criteria,
)


class TestDefaultCriteria:
    """Tests for static default criteria."""

    def test_default_criteria_use_e_prefix(self):
        """All default criteria must use E-prefix IDs."""
        criteria = get_default_criteria(has_changedoc=False)
        for c in criteria:
            assert c.id.startswith("E"), f"Expected E-prefix, got {c.id}"

    def test_default_criteria_count(self):
        """Default criteria should have exactly 5 items (4 base + quality/craft)."""
        criteria = get_default_criteria(has_changedoc=False)
        assert len(criteria) == 5

    def test_default_criteria_have_must_should_could(self):
        """Default criteria should have 2 must + 2 should + 1 could."""
        criteria = get_default_criteria(has_changedoc=False)
        must_count = sum(1 for c in criteria if c.category == "must")
        should_count = sum(1 for c in criteria if c.category == "should")
        could_count = sum(1 for c in criteria if c.category == "could")
        assert must_count == 2
        assert should_count == 2
        assert could_count == 1

    def test_default_criteria_includes_quality_craft(self):
        """Default criteria must include the quality/craft criterion."""
        criteria = get_default_criteria(has_changedoc=False)
        craft_criteria = [c for c in criteria if "craft" in c.text or "intentional" in c.text]
        assert len(craft_criteria) == 1
        assert craft_criteria[0].category == "should"

    def test_default_criteria_sequential_ids(self):
        """Default criteria should have sequential E1-E5 IDs."""
        criteria = get_default_criteria(has_changedoc=False)
        ids = [c.id for c in criteria]
        assert ids == ["E1", "E2", "E3", "E4", "E5"]


class TestChangedocDefaults:
    """Tests for changedoc mode defaults."""

    def test_changedoc_adds_traceability_criterion(self):
        """Changedoc mode should add traceability after quality/craft."""
        criteria = get_default_criteria(has_changedoc=True)
        assert len(criteria) == 6

    def test_changedoc_traceability_is_must(self):
        """The changedoc traceability criterion should be tagged must."""
        criteria = get_default_criteria(has_changedoc=True)
        traceability = criteria[5]  # 6th item (after quality/craft at E5)
        assert traceability.category == "must"
        assert traceability.id == "E6"

    def test_changedoc_traceability_mentions_changedoc(self):
        """Changedoc traceability criterion text should mention changedoc."""
        criteria = get_default_criteria(has_changedoc=True)
        traceability = criteria[5]
        assert "changedoc" in traceability.text.lower() or "decision" in traceability.text.lower()

    def test_changedoc_preserves_base_criteria(self):
        """Changedoc mode should preserve all 5 base criteria (4 + quality/craft)."""
        base = get_default_criteria(has_changedoc=False)
        changedoc = get_default_criteria(has_changedoc=True)
        for i in range(5):
            assert base[i].text == changedoc[i].text


class TestConfig:
    """Tests for EvaluationCriteriaGeneratorConfig."""

    def test_default_config_disabled(self):
        """Config should be disabled by default."""
        config = EvaluationCriteriaGeneratorConfig()
        assert config.enabled is False

    def test_default_min_max_criteria(self):
        """Config should have default min=4 and max=7."""
        config = EvaluationCriteriaGeneratorConfig()
        assert config.min_criteria == 4
        assert config.max_criteria == 7

    def test_persist_across_turns_default(self):
        """Config should not persist across turns by default."""
        config = EvaluationCriteriaGeneratorConfig()
        assert config.persist_across_turns is False

    def test_custom_config(self):
        """Config should accept custom values."""
        config = EvaluationCriteriaGeneratorConfig(
            enabled=True,
            min_criteria=3,
            max_criteria=8,
            persist_across_turns=True,
        )
        assert config.enabled is True
        assert config.min_criteria == 3
        assert config.max_criteria == 8
        assert config.persist_across_turns is True


class TestCriteriaValidation:
    """Tests for criteria parsing and validation."""

    def test_parse_valid_criteria_json(self):
        """Valid JSON with criteria should parse correctly."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [
                    {"text": "Goal alignment check", "category": "core"},
                    {"text": "No broken functionality", "category": "core"},
                    {"text": "Output is thorough", "category": "core"},
                    {"text": "Shows creative craft", "category": "stretch"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 4
        assert result[0].id == "E1"
        assert result[0].text == "Goal alignment check"
        assert result[0].category == "must"
        assert result[3].category == "could"

    def test_parse_invalid_json_returns_none(self):
        """Invalid JSON should return None (triggering fallback)."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        result = _parse_criteria_response("not json at all", min_criteria=4, max_criteria=10)
        assert result is None

    def test_parse_too_few_criteria_returns_none(self):
        """Fewer criteria than min should return None."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [
                    {"text": "Only one", "category": "core"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is None

    def test_parse_too_many_criteria_returns_none(self):
        """More criteria than max should return None."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"Criterion {i}", "category": "core"} for i in range(15)],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is None

    def test_parse_missing_core_criteria_returns_none(self):
        """Must have at least min_criteria - 1 core items."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [
                    {"text": "Stretch 1", "category": "stretch"},
                    {"text": "Stretch 2", "category": "stretch"},
                    {"text": "Core 1", "category": "core"},
                    {"text": "Stretch 3", "category": "stretch"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is None

    def test_parse_criteria_from_markdown_code_block(self):
        """Should extract JSON from markdown code blocks."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = """Here are the criteria:

```json
{
    "criteria": [
        {"text": "Goal alignment", "category": "core"},
        {"text": "No defects", "category": "core"},
        {"text": "Thorough output", "category": "core"},
        {"text": "Polish and craft", "category": "stretch"}
    ]
}
```
"""
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 4

    def test_variable_item_count_6(self):
        """6 criteria with 5 core + 1 stretch should work."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"Core criterion {i}", "category": "core"} for i in range(5)]
                + [
                    {"text": "Stretch criterion", "category": "stretch"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 6
        assert result[5].id == "E6"

    def test_variable_item_count_8(self):
        """8 criteria with 6 core + 2 stretch should work."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"Core criterion {i}", "category": "core"} for i in range(6)] + [{"text": f"Stretch criterion {i}", "category": "stretch"} for i in range(2)],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 8
        must_count = sum(1 for c in result if c.category == "must")
        could_count = sum(1 for c in result if c.category == "could")
        assert must_count == 6
        assert could_count == 2


class TestGenerationPrompt:
    """Tests for generation prompt construction."""

    def test_prompt_includes_task(self):
        """Generation prompt must include the user's task."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt(
            task="Build a snake game with mobile support",
            has_changedoc=False,
            min_criteria=4,
            max_criteria=10,
        )
        assert "snake game" in prompt

    def test_prompt_changedoc_adds_traceability(self):
        """When changedoc is enabled, prompt should mention traceability."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt(
            task="Build a website",
            has_changedoc=True,
            min_criteria=4,
            max_criteria=10,
        )
        assert "changedoc" in prompt.lower() or "traceability" in prompt.lower()

    def test_prompt_specifies_criteria_range(self):
        """Generation prompt should specify the min-max range."""
        from massgen.evaluation_criteria_generator import EvaluationCriteriaGenerator

        gen = EvaluationCriteriaGenerator()
        prompt = gen._build_generation_prompt(
            task="Build a website",
            has_changedoc=False,
            min_criteria=4,
            max_criteria=10,
        )
        assert "4" in prompt and "10" in prompt
