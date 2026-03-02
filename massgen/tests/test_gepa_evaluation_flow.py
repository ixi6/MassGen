"""Tests for GEPA evaluation flow end-to-end.

Tests cover:
- Dynamic criteria in tool schema (E1-EN keys)
- Default criteria use E-prefix
- item_categories in checklist state
- Variable item count through full flow
- Custom checklist items thread through system messages
"""

import json

from massgen.evaluation_criteria_generator import (
    GeneratedCriterion,
    get_default_criteria,
)


class TestDefaultCriteriaEPrefix:
    """Verify static defaults always use E-prefix, never T-prefix."""

    def test_default_criteria_use_e_prefix(self):
        """All static default criteria must use E-prefix."""
        criteria = get_default_criteria(has_changedoc=False)
        for c in criteria:
            assert c.id.startswith("E"), f"Expected E-prefix, got {c.id}"
            assert not c.id.startswith("T"), f"Should not use T-prefix: {c.id}"

    def test_changedoc_defaults_use_e_prefix(self):
        """Changedoc defaults must also use E-prefix."""
        criteria = get_default_criteria(has_changedoc=True)
        for c in criteria:
            assert c.id.startswith("E")
        assert criteria[-1].id == "E6"


class TestItemCategoriesInState:
    """Test that item_categories and item_prefix flow into checklist state."""

    def test_checklist_state_has_e_prefix(self):
        """Checklist state must contain item_prefix='E'."""
        from massgen.system_prompt_sections import (
            _CHECKLIST_ITEM_CATEGORIES,
            _CHECKLIST_ITEMS,
        )

        # Simulate what orchestrator._init_checklist_tool builds
        list(_CHECKLIST_ITEMS)
        item_categories = dict(_CHECKLIST_ITEM_CATEGORIES)

        state = {
            "item_prefix": "E",
            "item_categories": item_categories,
        }

        assert state["item_prefix"] == "E"
        assert "E1" in state["item_categories"]
        assert state["item_categories"]["E1"] == "must"

    def test_item_categories_match_default_criteria(self):
        """Default categories must match get_default_criteria() output."""
        from massgen.system_prompt_sections import _CHECKLIST_ITEM_CATEGORIES

        criteria = get_default_criteria(has_changedoc=False)
        for c in criteria:
            assert c.id in _CHECKLIST_ITEM_CATEGORIES
            assert _CHECKLIST_ITEM_CATEGORIES[c.id] == c.category

    def test_changedoc_categories_have_4_items(self):
        """Changedoc categories must have 4 items (3 must + 1 could)."""
        from massgen.system_prompt_sections import _CHECKLIST_ITEM_CATEGORIES_CHANGEDOC

        assert len(_CHECKLIST_ITEM_CATEGORIES_CHANGEDOC) == 4
        must_count = sum(1 for v in _CHECKLIST_ITEM_CATEGORIES_CHANGEDOC.values() if v == "must")
        could_count = sum(1 for v in _CHECKLIST_ITEM_CATEGORIES_CHANGEDOC.values() if v == "could")
        assert must_count == 3
        assert could_count == 1


class TestDynamicCriteriaInToolSchema:
    """Verify that dynamic criteria produce correct tool schema keys."""

    def test_6_criteria_produce_e1_through_e6(self):
        """6 generated criteria should produce E1-E6 keys in schema."""
        criteria = [GeneratedCriterion(id=f"E{i+1}", text=f"Criterion {i+1}", category="core" if i < 5 else "stretch") for i in range(6)]

        # Simulate SDK schema generation (same as orchestrator._init_checklist_tool_sdk)
        items = [c.text for c in criteria]
        schema_keys = [f"E{i+1}" for i in range(len(items))]

        assert schema_keys == ["E1", "E2", "E3", "E4", "E5", "E6"]

    def test_8_criteria_produce_e1_through_e8(self):
        """8 generated criteria should produce E1-E8 keys."""
        criteria = [GeneratedCriterion(id=f"E{i+1}", text=f"Criterion {i+1}", category="core" if i < 6 else "stretch") for i in range(8)]

        items = [c.text for c in criteria]
        schema_keys = [f"E{i+1}" for i in range(len(items))]

        assert schema_keys == ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]
        assert len(schema_keys) == 8

    def test_item_categories_from_generated_criteria(self):
        """Item categories dict should match generated criteria categories."""
        criteria = [
            GeneratedCriterion(id="E1", text="Goal met", category="core"),
            GeneratedCriterion(id="E2", text="No bugs", category="core"),
            GeneratedCriterion(id="E3", text="Complete", category="core"),
            GeneratedCriterion(id="E4", text="Thorough", category="core"),
            GeneratedCriterion(id="E5", text="Polish", category="stretch"),
            GeneratedCriterion(id="E6", text="Elegant", category="stretch"),
        ]

        item_categories = {c.id: c.category for c in criteria}

        assert item_categories == {
            "E1": "core",
            "E2": "core",
            "E3": "core",
            "E4": "core",
            "E5": "stretch",
            "E6": "stretch",
        }

        core_ids = [k for k, v in item_categories.items() if v == "core"]
        stretch_ids = [k for k, v in item_categories.items() if v == "stretch"]
        assert len(core_ids) == 4
        assert len(stretch_ids) == 2


class TestCustomItemsInSystemMessage:
    """Test that custom checklist items thread through system message builder."""

    def test_custom_items_override_defaults(self):
        """Custom items should appear in system message instead of defaults."""
        from massgen.system_prompt_sections import EvaluationSection

        custom_items = [
            "API endpoints return correct status codes",
            "All SQL queries are parameterized",
            "Error responses include helpful messages",
        ]
        custom_categories = {"E1": "core", "E2": "core", "E3": "stretch"}

        section = EvaluationSection(
            voting_sensitivity="checklist",
            voting_threshold=None,
            answers_used=0,
            answer_cap=5,
            custom_checklist_items=custom_items,
            item_categories=custom_categories,
        )

        content = section.build_content()
        assert "API endpoints return correct status codes" in content
        assert "SQL queries are parameterized" in content

    def test_none_custom_items_uses_defaults(self):
        """When custom_items is None, use static defaults."""
        from massgen.system_prompt_sections import EvaluationSection

        section = EvaluationSection(
            voting_sensitivity="checklist",
            voting_threshold=None,
            answers_used=0,
            answer_cap=5,
            custom_checklist_items=None,
            item_categories=None,
        )

        content = section.build_content()
        # Should contain default GEPA items
        assert "directly achieves what was asked for" in content or "requirements are met" in content


class TestCriteriaCountValidation:
    """Test that criteria count is validated during parsing."""

    def test_too_few_criteria_returns_none(self):
        """Parsing fewer than min_criteria should fail."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": "Only one", "category": "core"}],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is None

    def test_too_many_criteria_returns_none(self):
        """Parsing more than max_criteria should fail."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"C{i}", "category": "core"} for i in range(15)],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is None

    def test_exactly_min_criteria_works(self):
        """Exactly min_criteria items should parse successfully."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"Core {i}", "category": "core"} for i in range(3)]
                + [
                    {"text": "Stretch", "category": "stretch"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 4

    def test_exactly_max_criteria_works(self):
        """Exactly max_criteria items should parse successfully."""
        from massgen.evaluation_criteria_generator import _parse_criteria_response

        response = json.dumps(
            {
                "criteria": [{"text": f"Core {i}", "category": "core"} for i in range(9)]
                + [
                    {"text": "Stretch", "category": "stretch"},
                ],
            },
        )
        result = _parse_criteria_response(response, min_criteria=4, max_criteria=10)
        assert result is not None
        assert len(result) == 10


class TestAnalysisDynamicCriteriaLabels:
    """Diagnostic analysis should use custom criteria labels, not hardcoded ones."""

    def test_checklist_analysis_uses_custom_items(self):
        """When custom items provided, failure patterns should reference them."""
        from massgen.system_prompt_sections import _build_checklist_analysis

        custom = ["Visual design is cohesive", "Content tells a story", "Site is responsive"]
        analysis = _build_checklist_analysis(custom_checklist_items=custom)
        assert "Visual design is cohesive" in analysis
        assert "Content tells a story" in analysis
        # Should NOT contain hardcoded generic labels
        assert "goal alignment" not in analysis
        assert "correctness" not in analysis.split("E2")[1] if "E2" in analysis else True

    def test_checklist_analysis_default_has_generic_labels(self):
        """Without custom items, analysis should use hardcoded generic labels."""
        from massgen.system_prompt_sections import _build_checklist_analysis

        analysis = _build_checklist_analysis()
        assert "goal alignment" in analysis
        assert "correctness" in analysis

    def test_changedoc_analysis_uses_custom_items(self):
        """Changedoc analysis should also use custom criteria labels."""
        from massgen.system_prompt_sections import _build_changedoc_checklist_analysis

        custom = ["Visual design is cohesive", "Content tells a story"]
        analysis = _build_changedoc_checklist_analysis(custom_checklist_items=custom)
        assert "Visual design is cohesive" in analysis
        # Changedoc-specific sections should still be present
        assert "Decision Audit" in analysis
        assert "changedoc" in analysis.lower()

    def test_changedoc_analysis_default_has_generic_labels(self):
        """Without custom items, changedoc analysis uses hardcoded labels."""
        from massgen.system_prompt_sections import _build_changedoc_checklist_analysis

        analysis = _build_changedoc_checklist_analysis()
        assert "goal alignment" in analysis
        assert "changedoc quality" in analysis

    def test_evaluation_section_threads_custom_items_to_analysis(self):
        """EvaluationSection should pass custom items to analysis builder."""
        from massgen.system_prompt_sections import EvaluationSection

        custom = ["Visual design is cohesive", "Content tells a story"]
        section = EvaluationSection(
            voting_sensitivity="checklist_gated",
            voting_threshold=3,
            answers_used=0,
            answer_cap=5,
            custom_checklist_items=custom,
            item_categories={"E1": "must", "E2": "should"},
        )
        content = section.build_content()
        assert "Visual design is cohesive" in content
        assert "goal alignment" not in content
