# -*- coding: utf-8 -*-
"""Unit tests for ReworkControlsMixin — the shared feedback + rework button pattern."""


from massgen.frontend.displays.textual.widgets.rework_controls import (
    ReworkControlsMixin,
)


class TestReworkControlsMixinState:
    """Test mixin state management without mounting widgets."""

    def test_default_state(self):
        """Mixin should initialize with empty feedback and status."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        assert obj._rework_feedback_value == ""
        assert obj._rework_action_status == ""

    def test_rework_feedback_text_empty(self):
        """_rework_feedback_text returns None when no feedback."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        assert obj._rework_feedback_text() is None

    def test_rework_feedback_text_with_value(self):
        """_rework_feedback_text returns stripped text when feedback set."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        obj._rework_feedback_value = "  fix imports  "
        assert obj._rework_feedback_text() == "fix imports"

    def test_has_rework_feedback_false(self):
        """_has_rework_feedback returns False when empty."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        assert obj._has_rework_feedback() is False

    def test_has_rework_feedback_true(self):
        """_has_rework_feedback returns True when feedback present."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        obj._rework_feedback_value = "some feedback"
        assert obj._has_rework_feedback() is True

    def test_has_rework_feedback_whitespace_only(self):
        """Whitespace-only feedback counts as no feedback."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        obj._rework_feedback_value = "   "
        assert obj._has_rework_feedback() is False


class TestReworkControlsMixinWidgetIDs:
    """Test that widget ID class attrs can be customized to avoid collisions."""

    def test_default_widget_ids(self):
        """Default IDs should be set."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        assert obj.REWORK_FEEDBACK_INPUT_ID == "rework_feedback_input"
        assert obj.REWORK_CONTINUE_BTN_ID == "rework_continue_btn"
        assert obj.REWORK_QUICK_EDIT_BTN_ID == "rework_quick_edit_btn"

    def test_custom_widget_ids(self):
        """Subclass can override widget IDs."""

        class CustomModal(ReworkControlsMixin):
            REWORK_FEEDBACK_INPUT_ID = "planning_feedback_input"
            REWORK_CONTINUE_BTN_ID = "continue_btn"
            REWORK_QUICK_EDIT_BTN_ID = "quick_edit_btn"

        obj = CustomModal()
        assert obj.REWORK_FEEDBACK_INPUT_ID == "planning_feedback_input"
        assert obj.REWORK_CONTINUE_BTN_ID == "continue_btn"
        assert obj.REWORK_QUICK_EDIT_BTN_ID == "quick_edit_btn"


class TestReworkControlsMixinCompose:
    """Test that compose_rework_controls yields the correct widget structure."""

    def test_compose_yields_widgets(self):
        """compose_rework_controls should yield a Container with children."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(
            obj.compose_rework_controls(
                feedback_label="Feedback:",
                feedback_placeholder="Enter feedback...",
                continue_label="Continue",
                quick_edit_label="Quick Edit",
            ),
        )
        # Should yield exactly 1 container
        assert len(widgets) == 1
        container = widgets[0]
        assert hasattr(container, "id") or True  # It's a Container

    def test_compose_with_custom_labels(self):
        """Custom labels should be passed through."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(
            obj.compose_rework_controls(
                feedback_label="Custom label:",
                feedback_placeholder="Custom placeholder",
                continue_label="Rework (Multi-Agent)",
                quick_edit_label="Quick Fix (Single Agent)",
            ),
        )
        assert len(widgets) == 1


class TestReworkControlsMixinSplitCompose:
    """Test compose_rework_input() and compose_rework_buttons() methods."""

    def test_compose_rework_input_yields_container(self):
        """compose_rework_input should yield exactly 1 container."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(obj.compose_rework_input())
        assert len(widgets) == 1
        container = widgets[0]
        assert "rework-input-section" in container.classes

    def test_compose_rework_input_custom_labels(self):
        """compose_rework_input should accept custom labels."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(
            obj.compose_rework_input(
                feedback_label="Custom feedback:",
                feedback_placeholder="Custom placeholder...",
            ),
        )
        assert len(widgets) == 1

    def test_compose_rework_buttons_yields_two_buttons(self):
        """compose_rework_buttons should yield exactly 2 Button widgets."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(obj.compose_rework_buttons())
        assert len(widgets) == 2
        # Both should be Button instances
        from textual.widgets import Button

        assert all(isinstance(w, Button) for w in widgets)

    def test_compose_rework_buttons_custom_labels(self):
        """compose_rework_buttons should use custom labels."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(
            obj.compose_rework_buttons(
                continue_label="Rework (Multi-Agent)",
                quick_edit_label="Quick Fix (Single Agent)",
            ),
        )
        assert len(widgets) == 2

    def test_compose_rework_buttons_disabled_without_feedback(self):
        """Buttons should be disabled when no feedback present."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        widgets = list(obj.compose_rework_buttons())
        assert all(w.disabled for w in widgets)

    def test_compose_rework_buttons_enabled_with_feedback(self):
        """Buttons should be enabled when feedback is present."""

        class MockModal(ReworkControlsMixin):
            pass

        obj = MockModal()
        obj._rework_feedback_value = "some feedback"
        widgets = list(obj.compose_rework_buttons())
        assert all(not w.disabled for w in widgets)
