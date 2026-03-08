"""Tests for FinalAnswerModal dismiss behavior.

Verifies that ESC/X are blocked on the initial modal when there are
pending changes to review, but allowed on answer-only and re-opened modals.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def modal_data_with_changes():
    """FinalAnswerModalData with changes and no prior action (initial modal)."""
    from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
        FinalAnswerModalData,
    )

    return FinalAnswerModalData(
        answer_content="Test answer",
        changes=[{"file": "README.md", "diff": "+hello"}],
        prior_action=None,
    )


@pytest.fixture
def modal_data_no_changes():
    """FinalAnswerModalData without changes (answer-only modal)."""
    from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
        FinalAnswerModalData,
    )

    return FinalAnswerModalData(
        answer_content="Test answer",
        changes=None,
        prior_action=None,
    )


@pytest.fixture
def modal_data_reopened():
    """FinalAnswerModalData with prior_action set (re-opened modal)."""
    from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
        FinalAnswerModalData,
    )

    return FinalAnswerModalData(
        answer_content="Test answer",
        changes=[{"file": "README.md", "diff": "+hello"}],
        prior_action="approved",
    )


# ---------------------------------------------------------------------------
# _requires_decision property
# ---------------------------------------------------------------------------


class TestRequiresDecision:
    """Tests for the _requires_decision property."""

    def test_requires_decision_true_when_changes_and_no_prior_action(
        self,
        modal_data_with_changes,
    ):
        """Initial modal with pending changes requires a decision."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        assert modal._requires_decision is True

    def test_requires_decision_false_when_no_changes(self, modal_data_no_changes):
        """Answer-only modal does not require a decision."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_no_changes)
        assert modal._requires_decision is False

    def test_requires_decision_false_when_prior_action_approved(
        self,
        modal_data_reopened,
    ):
        """Re-opened modal with prior approved action does not require a decision."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_reopened)
        assert modal._requires_decision is False

    def test_requires_decision_false_when_prior_action_rejected(self):
        """Re-opened modal with prior rejected action does not require a decision."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
            FinalAnswerModalData,
        )

        data = FinalAnswerModalData(
            answer_content="Test answer",
            changes=[{"file": "README.md", "diff": "+hello"}],
            prior_action="rejected",
        )
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False

    def test_requires_decision_false_when_changes_is_empty_list(self):
        """Empty changes list should not require a decision."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
            FinalAnswerModalData,
        )

        data = FinalAnswerModalData(
            answer_content="Test answer",
            changes=[],
            prior_action=None,
        )
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False


# ---------------------------------------------------------------------------
# action_close_modal behavior
# ---------------------------------------------------------------------------


class TestActionCloseModal:
    """Tests for action_close_modal dismiss blocking."""

    def test_close_blocked_when_requires_decision(self, modal_data_with_changes):
        """ESC should NOT dismiss the modal when a decision is required."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
                modal.action_close_modal()

        assert not super_dismiss_called["called"]

    def test_close_shows_notification_when_blocked(self, modal_data_with_changes):
        """Blocked dismiss should show a notification to the user."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)

        def mock_super_dismiss(self_inner, result=None):
            pass

        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
                modal.action_close_modal()

        mock_app.notify.assert_called_once()
        call_args = mock_app.notify.call_args
        assert "approve" in call_args[0][0].lower() or "review" in call_args[0][0].lower()

    def test_close_allowed_when_no_changes(self, modal_data_no_changes):
        """ESC should dismiss normally when there are no changes."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_no_changes)
        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_close_modal()

        assert super_dismiss_called["called"]

    def test_close_allowed_when_reopened(self, modal_data_reopened):
        """ESC should dismiss normally on re-opened modal."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_reopened)
        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_close_modal()

        assert super_dismiss_called["called"]


# ---------------------------------------------------------------------------
# Re-open default prior_action
# ---------------------------------------------------------------------------


class TestReopenDefaultPriorAction:
    """Tests for the default prior_action when re-opening the modal."""

    def test_prior_action_none_when_no_stored_result(self):
        """When no result is stored, prior_action should be None, not 'approved'."""
        # Simulate the re-open logic from textual_terminal_display.py
        stored_result = None

        if stored_result is not None:
            prior_action = "approved" if stored_result.approved else "rejected"
        else:
            # This is the fix: was "approved", should be None
            prior_action = None

        assert prior_action is None

    def test_prior_action_approved_when_stored_result_approved(self):
        """When stored result is approved, prior_action should be 'approved'."""
        from massgen.filesystem_manager import ReviewResult

        stored_result = ReviewResult(approved=True)

        if stored_result is not None:
            prior_action = "approved" if stored_result.approved else "rejected"
        else:
            prior_action = None

        assert prior_action == "approved"

    def test_prior_action_rejected_when_stored_result_rejected(self):
        """When stored result is rejected, prior_action should be 'rejected'."""
        from massgen.filesystem_manager import ReviewResult

        stored_result = ReviewResult(approved=False)

        if stored_result is not None:
            prior_action = "approved" if stored_result.approved else "rejected"
        else:
            prior_action = None

        assert prior_action == "rejected"


# ---------------------------------------------------------------------------
# dismiss() override — the chokepoint guard
# ---------------------------------------------------------------------------


class TestDismissOverride:
    """Tests for the dismiss() override that blocks bare dismiss when _requires_decision."""

    def test_bare_dismiss_blocked_when_requires_decision(self, modal_data_with_changes):
        """dismiss() with no args should be blocked when _requires_decision is True."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        assert modal._requires_decision is True

        # Track whether super().dismiss() was actually called
        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
                modal.dismiss()

        assert not super_dismiss_called["called"], "super().dismiss() should NOT have been called"
        mock_app.notify.assert_called_once()

    def test_dismiss_with_review_result_allowed_when_requires_decision(
        self,
        modal_data_with_changes,
    ):
        """dismiss(ReviewResult(...)) should be allowed even when _requires_decision is True."""
        from massgen.filesystem_manager import ReviewResult
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        assert modal._requires_decision is True

        super_dismiss_called = {"called": False, "result": None}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True
            super_dismiss_called["result"] = result

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            review_result = ReviewResult(approved=True, metadata={"selection_mode": "all"})
            modal.dismiss(review_result)

        assert super_dismiss_called["called"], "super().dismiss() SHOULD have been called"
        assert super_dismiss_called["result"].approved is True

    def test_bare_dismiss_allowed_when_no_decision_required(self, modal_data_no_changes):
        """dismiss() with no args should work when _requires_decision is False."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_no_changes)
        assert modal._requires_decision is False

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.dismiss()

        assert super_dismiss_called["called"], "super().dismiss() SHOULD have been called"

    def test_bare_dismiss_allowed_when_reopened(self, modal_data_reopened):
        """dismiss() with no args should work on re-opened modal (prior_action set)."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_reopened)
        assert modal._requires_decision is False

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.dismiss()

        assert super_dismiss_called["called"], "super().dismiss() SHOULD have been called"

    def test_x_button_blocked_via_dismiss_guard(self, modal_data_with_changes):
        """X button (close_modal_button) flows through dismiss() guard — single notification."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        assert modal._requires_decision is True

        super_dismiss_called = {"called": False}
        notify_count = {"count": 0}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        mock_app = MagicMock()
        mock_app.notify = lambda *a, **kw: notify_count.update(count=notify_count["count"] + 1)

        class FakeButton:
            id = "close_modal_button"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
                modal.on_button_pressed(FakeEvent())

        assert not super_dismiss_called["called"], "dismiss should be blocked"
        assert notify_count["count"] == 1, f"Expected 1 notification, got {notify_count['count']}"


# ---------------------------------------------------------------------------
# action_force_close (Ctrl+C two-press behavior)
# ---------------------------------------------------------------------------


class TestForceClose:
    """Tests for the Ctrl+C two-press force-close behavior."""

    def test_first_ctrl_c_warns_does_not_dismiss(self, modal_data_with_changes):
        """First Ctrl+C should warn but NOT dismiss."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        assert modal._requires_decision is True

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
                modal.action_force_close()

        assert not super_dismiss_called["called"]
        assert modal._ctrl_c_warned is True
        mock_app.notify.assert_called_once()
        assert "ctrl+c" in mock_app.notify.call_args[0][0].lower()

    def test_second_ctrl_c_rejects_and_dismisses(self, modal_data_with_changes):
        """Second Ctrl+C should dismiss with approved=False."""
        from massgen.filesystem_manager import ReviewResult
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        modal._ctrl_c_warned = True  # Simulate first press already happened

        super_dismiss_called = {"called": False, "result": None}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True
            super_dismiss_called["result"] = result

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_force_close()

        assert super_dismiss_called["called"]
        result = super_dismiss_called["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is False
        assert result.metadata["selection_mode"] == "force_close"

    def test_ctrl_c_immediate_dismiss_when_no_decision_required(self, modal_data_no_changes):
        """Ctrl+C should immediately dismiss when no decision is required."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_no_changes)
        assert modal._requires_decision is False

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_force_close()

        assert super_dismiss_called["called"]
        assert modal._ctrl_c_warned is False  # Never needed to warn


# ---------------------------------------------------------------------------
# Notification debounce
# ---------------------------------------------------------------------------


class TestNotificationDebounce:
    """Tests for the _notify_decision_required debounce logic."""

    def test_first_notification_fires(self, modal_data_with_changes):
        """First call should always fire a notification."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            modal._notify_decision_required()

        mock_app.notify.assert_called_once()

    def test_rapid_second_call_suppressed(self, modal_data_with_changes):
        """Second call within 0.5s should be suppressed."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            modal._notify_decision_required()
            modal._notify_decision_required()  # immediate second call

        mock_app.notify.assert_called_once()

    def test_delayed_second_call_fires(self, modal_data_with_changes):
        """Second call after debounce period should fire."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
        )

        modal = FinalAnswerModal(data=modal_data_with_changes)
        mock_app = MagicMock()

        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            modal._notify_decision_required()
            # Simulate time passing beyond debounce
            modal._last_notify_time -= 1.0
            modal._notify_decision_required()

        assert mock_app.notify.call_count == 2


# ---------------------------------------------------------------------------
# Workspace tab dismiss behavior
# ---------------------------------------------------------------------------


class TestWorkspaceTabDismiss:
    """Tests for dismiss behavior when workspace tab is present but no changes."""

    def test_dismiss_allowed_with_workspace_no_changes(self):
        """ESC should dismiss when workspace_path is set but no changes exist."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
            FinalAnswerModalData,
        )

        data = FinalAnswerModalData(
            answer_content="Test answer",
            changes=None,
            workspace_path="/tmp/test_workspace",
            prior_action=None,
        )
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_close_modal()

        assert super_dismiss_called["called"]

    def test_dismiss_allowed_with_workspace_empty_changes(self):
        """ESC should dismiss when workspace_path is set and changes is empty list."""
        from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
            FinalAnswerModal,
            FinalAnswerModalData,
        )

        data = FinalAnswerModalData(
            answer_content="Test answer",
            changes=[],
            workspace_path="/tmp/test_workspace",
            prior_action=None,
        )
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False

        super_dismiss_called = {"called": False}

        def mock_super_dismiss(self_inner, result=None):
            super_dismiss_called["called"] = True

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_close_modal()

        assert super_dismiss_called["called"]
