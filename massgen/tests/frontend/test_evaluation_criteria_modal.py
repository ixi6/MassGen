"""Unit tests for EvaluationCriteriaModal and set_evaluation_criteria() wiring."""

from massgen.frontend.displays.textual.widgets.modals.content_modals import (
    EvaluationCriteriaModal,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_CRITERIA = [
    {
        "id": "E1",
        "text": "The output must clearly state the main conclusion.",
        "category": "must",
        "verify_by": "Check the opening paragraph for a clear thesis.",
    },
    {
        "id": "E2",
        "text": "The response should include at least two examples.",
        "category": "should",
        "verify_by": None,
    },
    {
        "id": "E3",
        "text": "Bonus: include a summary table.",
        "category": "could",
        "verify_by": None,
    },
]

SINGLE_MUST_CRITERIA = [
    {
        "id": "E1",
        "text": "The answer must be correct.",
        "category": "must",
        "verify_by": None,
    },
]


# ---------------------------------------------------------------------------
# EvaluationCriteriaModal construction
# ---------------------------------------------------------------------------


class TestEvaluationCriteriaModalConstruction:
    def test_stores_criteria(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        assert modal._criteria == SAMPLE_CRITERIA

    def test_default_source(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        assert modal._source == "default"

    def test_custom_source(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA, source="generated")
        assert modal._source == "generated"

    def test_empty_criteria(self):
        modal = EvaluationCriteriaModal(criteria=[])
        assert modal._criteria == []

    def test_none_criteria_normalized(self):
        modal = EvaluationCriteriaModal(criteria=None)
        assert modal._criteria == []


# ---------------------------------------------------------------------------
# Badge label rendering
# ---------------------------------------------------------------------------


class TestBadgeLabel:
    def test_must_badge(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        badge = modal._category_badge("must")
        assert "MUST" in badge

    def test_should_badge(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        badge = modal._category_badge("should")
        assert "SHOULD" in badge

    def test_could_badge(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        badge = modal._category_badge("could")
        assert "COULD" in badge

    def test_unknown_category_defaults(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        badge = modal._category_badge("unknown_category")
        # Should not raise; should return something
        assert isinstance(badge, str)
        assert len(badge) > 0


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


class TestSummaryLine:
    def test_count_appears(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        summary = modal._build_summary_line()
        assert "3" in summary

    def test_source_appears(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA, source="generated")
        summary = modal._build_summary_line()
        assert "generated" in summary

    def test_category_counts_in_summary(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        summary = modal._build_summary_line()
        # 1 must, 1 should, 1 could
        assert "1" in summary

    def test_empty_criteria_summary(self):
        modal = EvaluationCriteriaModal(criteria=[])
        summary = modal._build_summary_line()
        assert "0" in summary or "no" in summary.lower()


# ---------------------------------------------------------------------------
# Criterion text rendering
# ---------------------------------------------------------------------------


class TestCriterionText:
    def test_criterion_text_included(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[0])
        assert "The output must clearly state" in rendered

    def test_criterion_id_included(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[0])
        assert "E1" in rendered

    def test_verify_by_included_when_present(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[0])
        assert "Check the opening paragraph" in rendered

    def test_verify_by_absent_when_none(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[1])
        # verify_by is None — should not show "Verify:" label
        assert "Verify:" not in rendered

    def test_badge_in_rendered_criterion(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[0])
        assert "MUST" in rendered

    def test_should_badge_in_should_criterion(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[1])
        assert "SHOULD" in rendered

    def test_could_badge_in_could_criterion(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        rendered = modal._render_criterion(SAMPLE_CRITERIA[2])
        assert "COULD" in rendered


# ---------------------------------------------------------------------------
# Content text (full rendered body)
# ---------------------------------------------------------------------------


class TestBuildContent:
    def test_all_ids_in_content(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        content = modal._build_content()
        assert "E1" in content
        assert "E2" in content
        assert "E3" in content

    def test_all_categories_in_content(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        content = modal._build_content()
        assert "MUST" in content
        assert "SHOULD" in content
        assert "COULD" in content

    def test_all_texts_in_content(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        content = modal._build_content()
        assert "clearly state the main conclusion" in content
        assert "at least two examples" in content
        assert "summary table" in content

    def test_verify_by_in_content_when_present(self):
        modal = EvaluationCriteriaModal(criteria=SAMPLE_CRITERIA)
        content = modal._build_content()
        assert "Check the opening paragraph" in content

    def test_empty_criteria_content(self):
        modal = EvaluationCriteriaModal(criteria=[])
        content = modal._build_content()
        # Should not crash; should return something indicating no criteria
        assert isinstance(content, str)


# ---------------------------------------------------------------------------
# set_evaluation_criteria on TextualApp (lightweight stub test)
# ---------------------------------------------------------------------------


class TestSetEvaluationCriteriaMethod:
    """Test set_evaluation_criteria() on the inner TextualApp class (where storage lives)."""

    @staticmethod
    def _make_app_stub():
        """Create a bare TextualApp instance without running Textual."""
        import massgen.frontend.displays.textual_terminal_display as _mod

        app = _mod.TextualApp.__new__(_mod.TextualApp)
        app._runtime_evaluation_criteria = None
        app._runtime_evaluation_criteria_source = "default"
        return app

    def test_method_stores_criteria(self):
        """set_evaluation_criteria() should store criteria on the app instance."""
        app = self._make_app_stub()
        app.set_evaluation_criteria(SAMPLE_CRITERIA, source="generated")
        assert app._runtime_evaluation_criteria == SAMPLE_CRITERIA
        assert app._runtime_evaluation_criteria_source == "generated"

    def test_method_default_source(self):
        """set_evaluation_criteria() defaults source to 'default'."""
        app = self._make_app_stub()
        app.set_evaluation_criteria(SAMPLE_CRITERIA)
        assert app._runtime_evaluation_criteria_source == "default"

    def test_method_overwrites_previous(self):
        """set_evaluation_criteria() replaces any previously stored criteria."""
        app = self._make_app_stub()
        app._runtime_evaluation_criteria = SAMPLE_CRITERIA
        app._runtime_evaluation_criteria_source = "generated"

        app.set_evaluation_criteria(SINGLE_MUST_CRITERIA, source="inline")

        assert app._runtime_evaluation_criteria == SINGLE_MUST_CRITERIA
        assert app._runtime_evaluation_criteria_source == "inline"

    def test_none_criteria_stored_as_empty_list(self):
        """set_evaluation_criteria(None) should store []."""
        app = self._make_app_stub()
        app.set_evaluation_criteria(None)
        assert app._runtime_evaluation_criteria == []
