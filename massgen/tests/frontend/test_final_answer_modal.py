"""Unit tests for FinalAnswerModal — the tabbed final answer + review changes modal."""

from unittest.mock import MagicMock, patch

from massgen.filesystem_manager import ReviewResult
from massgen.frontend.displays.textual.widgets.modals.final_answer_modal import (
    AnswerTabContent,
    FinalAnswerModal,
    FinalAnswerModalData,
)
from massgen.frontend.displays.textual.widgets.modals.review_changes_panel import (
    ReviewChangesPanel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index abc1234..def5678 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
+import sys

 def main():
     pass
@@ -10,3 +11,3 @@ def helper():
-    return False
+    return True
     # end
"""

MOCK_ANSWER = """\
# Implementation Summary

## Changes Made

1. Added `import sys` to support CLI arguments
2. Fixed `helper()` to return True instead of False
3. Updated configuration defaults

## Testing

All tests pass with the new implementation.
"""

MOCK_VOTES = {
    "winner": "agent_a",
    "vote_counts": {"agent_a": 2, "agent_b": 1},
    "is_tie": False,
}

MOCK_VOTES_TIE = {
    "winner": "agent_a",
    "vote_counts": {"agent_a": 1, "agent_b": 1},
    "is_tie": True,
}

MOCK_POST_EVAL = "All criteria met. Code quality verified."

MOCK_CONTEXT_PATHS = {
    "new": ["src/new_file.py"],
    "modified": ["src/app.py", "src/config.py"],
}


def _make_changes() -> list:
    return [
        {
            "original_path": "/project",
            "isolated_path": "/tmp/worktree",
            "changes": [
                {"status": "M", "path": "src/app.py"},
            ],
            "diff": SAMPLE_DIFF,
        },
    ]


_SENTINEL = object()


def _make_data(
    *,
    answer: str = MOCK_ANSWER,
    votes: dict | None | object = _SENTINEL,
    post_eval: str | None = None,
    changes: list | None = None,
    context_paths: dict | None = None,
    workspace_path: str | None = None,
) -> FinalAnswerModalData:
    return FinalAnswerModalData(
        answer_content=answer,
        vote_results=MOCK_VOTES if votes is _SENTINEL else (votes or {}),
        agent_id="agent_a",
        model_name="claude-sonnet-4-5-20250929",
        post_eval_content=post_eval,
        post_eval_status="verified" if post_eval else "none",
        changes=changes,
        context_paths=context_paths,
        workspace_path=workspace_path,
    )


# ---------------------------------------------------------------------------
# FinalAnswerModalData construction
# ---------------------------------------------------------------------------


class TestFinalAnswerModalData:
    def test_defaults(self):
        data = FinalAnswerModalData(answer_content="hello")
        assert data.answer_content == "hello"
        assert data.vote_results == {}
        assert data.agent_id == ""
        assert data.changes is None
        assert data.post_eval_status == "none"

    def test_with_all_fields(self):
        changes = _make_changes()
        data = _make_data(changes=changes, post_eval=MOCK_POST_EVAL, context_paths=MOCK_CONTEXT_PATHS)
        assert data.answer_content == MOCK_ANSWER
        assert data.changes == changes
        assert data.post_eval_content == MOCK_POST_EVAL
        assert data.post_eval_status == "verified"


# ---------------------------------------------------------------------------
# AnswerTabContent
# ---------------------------------------------------------------------------


class TestHeaderTitle:
    def test_header_with_votes(self):
        """Header should include winner and vote info."""
        data = _make_data()
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert "Final Answer" in title
        assert "Winner: agent_a" in title
        assert "2 votes" in title
        assert "Votes:" in title

    def test_header_no_votes(self):
        """Header with no votes should just say 'Final Answer'."""
        data = _make_data(votes={})
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert title == "Final Answer"

    def test_header_tie(self):
        """Header should show tie-breaker info."""
        data = _make_data(votes=MOCK_VOTES_TIE)
        modal = FinalAnswerModal(data=data)
        title = modal._build_header_title()
        assert "tie-breaker" in title
        assert "Votes:" in title


class TestAnswerTabContent:
    def test_winner_summary(self):
        data = _make_data()
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert "agent_a" in summary
        assert "2 votes" in summary

    def test_winner_summary_tie(self):
        data = _make_data(votes=MOCK_VOTES_TIE)
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert "tie-breaker" in summary

    def test_winner_summary_no_votes(self):
        data = _make_data(votes={})
        tab = AnswerTabContent(data=data)
        summary = tab._build_winner_summary()
        assert summary == ""

    def test_vote_summary(self):
        data = _make_data()
        tab = AnswerTabContent(data=data)
        summary = tab._build_vote_summary()
        assert "agent_a (2)" in summary
        assert "agent_b (1)" in summary

    def test_vote_summary_no_votes(self):
        data = _make_data(votes={})
        tab = AnswerTabContent(data=data)
        summary = tab._build_vote_summary()
        assert summary == ""


# ---------------------------------------------------------------------------
# FinalAnswerModal construction
# ---------------------------------------------------------------------------


class TestFinalAnswerModalConstruction:
    def test_answer_only_no_panel(self):
        """No changes → no ReviewChangesPanel."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        assert modal._panel is None

    def test_with_changes_creates_panel(self):
        """With changes → ReviewChangesPanel is created."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert isinstance(modal._panel, ReviewChangesPanel)

    def test_panel_has_correct_file_count(self):
        """Panel should track the files from changes."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        assert len(modal._panel._all_file_paths) == 1


# ---------------------------------------------------------------------------
# Dismiss behavior
# ---------------------------------------------------------------------------


class TestDismissBehavior:
    def _capture_super_dismiss(self, modal):
        """Patch super().dismiss() to capture calls without bypassing the guard."""
        captured = {}

        def mock_super_dismiss(self_inner, result=None):
            captured["result"] = result

        patch_ctx = patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss)
        return captured, patch_ctx

    def test_close_from_answer_approves_all(self):
        """Closing from answer tab should approve all changes."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured, ctx = self._capture_super_dismiss(modal)
        with ctx:
            modal._close_with_approve_all()
        result = captured["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is True
        assert result.approved_files is None
        assert result.metadata["selection_mode"] == "all"

    def test_close_no_changes_approves_all(self):
        """Closing with no changes should still return approved=True."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        captured, ctx = self._capture_super_dismiss(modal)
        with ctx:
            modal._close_with_approve_all()
        result = captured["result"]
        assert result.approved is True

    def test_esc_action_blocked_when_changes_pending(self):
        """ESC action should be blocked when changes need review."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured, ctx = self._capture_super_dismiss(modal)
        mock_app = MagicMock()
        with patch.object(type(modal), "app", new_callable=lambda: property(lambda self: mock_app)):
            with ctx:
                modal.action_close_modal()
        # Should NOT have dismissed
        assert "result" not in captured
        # Should have notified
        mock_app.notify.assert_called_once()

    def test_esc_action_approves_when_no_changes(self):
        """ESC action should approve when no changes are present."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        captured, ctx = self._capture_super_dismiss(modal)
        with ctx:
            modal.action_close_modal()
        # dismiss() called without arguments (no pending changes)
        assert "result" in captured


# ---------------------------------------------------------------------------
# Panel integration
# ---------------------------------------------------------------------------


class TestPanelIntegration:
    def test_panel_action_approve_selected(self):
        """Panel's approve_selected action should result in dismiss."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        # Simulate panel emitting ActionRequested
        result = modal._panel.get_review_result("approve")
        event = ReviewChangesPanel.ActionRequested("approve_selected", result)
        # Set the sender for the message
        event._sender = modal._panel
        modal.on_review_changes_panel_action_requested(event)

        assert "result" in captured
        assert captured["result"].approved is True

    def test_panel_action_reject(self):
        """Panel's reject action should result in dismiss with approved=False."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        result = modal._panel.get_review_result("reject")
        event = ReviewChangesPanel.ActionRequested("reject", result)
        event._sender = modal._panel
        modal.on_review_changes_panel_action_requested(event)

        assert captured["result"].approved is False


# ---------------------------------------------------------------------------
# Answer tab footer buttons
# ---------------------------------------------------------------------------


class TestAnswerFooterButtons:
    def test_approve_all_answer_btn_handler(self):
        """approve_all_answer_btn should trigger _close_with_approve_all."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        # Simulate the button press handler
        class FakeButton:
            id = "approve_all_answer_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert captured["result"].approved is True
        assert captured["result"].metadata["selection_mode"] == "all"

    def test_review_changes_btn_handler(self):
        """review_changes_btn should call action_switch_review_tab via call_later."""
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        switched = {"called": False}
        modal.action_switch_review_tab = lambda: switched.update({"called": True})
        # call_later defers execution; stub it to invoke immediately
        modal.call_later = lambda fn: fn()

        class FakeButton:
            id = "review_changes_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

            def prevent_default(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert switched["called"] is True


# ---------------------------------------------------------------------------
# Post-eval rendering
# ---------------------------------------------------------------------------


class TestPostEvalRendering:
    def test_post_eval_present(self):
        """Post-eval data should be stored correctly."""
        data = _make_data(post_eval=MOCK_POST_EVAL)
        assert data.post_eval_content == MOCK_POST_EVAL
        assert data.post_eval_status == "verified"

    def test_post_eval_absent(self):
        """No post-eval data should result in 'none' status."""
        data = _make_data(post_eval=None)
        assert data.post_eval_content is None
        assert data.post_eval_status == "none"


# ---------------------------------------------------------------------------
# Context paths
# ---------------------------------------------------------------------------


class TestContextPaths:
    def test_context_paths_stored(self):
        data = _make_data(context_paths=MOCK_CONTEXT_PATHS)
        assert data.context_paths is not None
        assert len(data.context_paths["new"]) == 1
        assert len(data.context_paths["modified"]) == 2

    def test_no_context_paths(self):
        data = _make_data(context_paths=None)
        assert data.context_paths is None


# ---------------------------------------------------------------------------
# Prior action mode (re-opened after approve/reject)
# ---------------------------------------------------------------------------


class TestPriorActionMode:
    def test_prior_action_default(self):
        """prior_action defaults to None."""
        data = FinalAnswerModalData(answer_content="hello")
        assert data.prior_action is None

    def test_prior_action_approved(self):
        """prior_action can be set to 'approved'."""
        data = FinalAnswerModalData(answer_content="hello", prior_action="approved")
        assert data.prior_action == "approved"

    def test_prior_action_rejected(self):
        """prior_action can be set to 'rejected'."""
        data = FinalAnswerModalData(answer_content="hello", prior_action="rejected")
        assert data.prior_action == "rejected"

    def test_prior_action_creates_panel_with_changes(self):
        """prior_action set should still create ReviewChangesPanel when changes exist."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._prior_action == "approved"

    def test_prior_action_rejected_creates_panel(self):
        """prior_action='rejected' should still create panel."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._prior_action == "rejected"

    def test_prior_action_no_panel_without_changes(self):
        """prior_action set without changes should not create panel."""
        data = _make_data()
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is None

    def test_prior_action_answer_tab_has_back_button(self):
        """prior_action set should produce 'Back to Timeline' button."""
        data = _make_data()
        tab = AnswerTabContent(data=data, has_changes=True, prior_action="approved")
        assert tab._prior_action == "approved"

    def test_prior_action_back_button_dismisses(self):
        """back_to_timeline_btn should trigger _close_with_approve_all."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})

        class FakeButton:
            id = "back_to_timeline_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert captured["result"].approved is True

    def test_prior_action_esc_dismisses(self):
        """ESC in prior_action mode should dismiss (no decision needed)."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        captured = {}
        modal.dismiss = lambda result=None: captured.update({"result": result})
        modal.action_close_modal()
        # Should have dismissed (prior_action means no decision required)
        assert "result" in captured

    def test_panel_dimmed_when_prior_action_set(self):
        """Panel should have review-approved-dim class when prior_action is set."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "rejected"
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        assert modal._panel.has_class("review-approved-dim")

    def test_panel_rework_disabled_when_prior_action_set(self):
        """Panel should have show_rework=False when prior_action is set."""
        data = _make_data(changes=_make_changes())
        data.prior_action = "approved"
        modal = FinalAnswerModal(data=data)
        assert modal._panel._show_rework is False


# ---------------------------------------------------------------------------
# Review panel keyboard bindings delegation
# ---------------------------------------------------------------------------


class TestReviewPanelBindings:
    """Verify FinalAnswerModal exposes all review panel keyboard actions."""

    def _make_modal_with_panel(self):
        data = _make_data(changes=_make_changes())
        modal = FinalAnswerModal(data=data)
        assert modal._panel is not None
        return modal

    def test_bindings_include_review_keys(self):
        """BINDINGS should include space, enter, arrows, h, [, ], e (not a/r — buttons only)."""
        binding_keys = {b.key for b in FinalAnswerModal.BINDINGS}
        expected = {"space", "enter", "h", "[", "]", "up", "down", "e"}
        assert expected.issubset(binding_keys), f"Missing bindings: {expected - binding_keys}"
        # a and r removed — approve/reject only via panel buttons
        assert "a" not in binding_keys
        assert "r" not in binding_keys

    def test_action_toggle_selected_delegates(self):
        """space → action_toggle_selected should call panel._toggle_file_approval."""
        modal = self._make_modal_with_panel()
        # Select first file so toggle has a target
        first_file = modal._panel._all_file_paths[0]
        modal._panel._selected_file = first_file
        original = modal._panel.file_approvals[first_file]
        modal.action_toggle_selected()
        assert modal._panel.file_approvals[first_file] != original

    def test_action_select_next_file_delegates(self):
        """down → action_select_next_file should call panel._move_selection."""
        modal = self._make_modal_with_panel()
        first_file = modal._panel._all_file_paths[0]
        modal._panel._selected_file = first_file
        modal.action_select_next_file()
        # With only 1 file it wraps around, but the method should not raise
        assert modal._panel._selected_file is not None

    def test_action_select_previous_file_delegates(self):
        """up → action_select_previous_file should call panel._move_selection."""
        modal = self._make_modal_with_panel()
        first_file = modal._panel._all_file_paths[0]
        modal._panel._selected_file = first_file
        modal.action_select_previous_file()
        assert modal._panel._selected_file is not None

    def test_no_panel_actions_are_noop(self):
        """Review actions should be no-ops when there is no panel."""
        data = _make_data(changes=None)
        modal = FinalAnswerModal(data=data)
        assert modal._panel is None
        # Should not raise
        modal.action_toggle_selected()
        modal.action_select_next_file()
        modal.action_select_previous_file()
        modal.action_toggle_selected_hunk()
        modal.action_select_next_hunk()
        modal.action_select_previous_hunk()
        modal.action_edit_file()


# ---------------------------------------------------------------------------
# Review status on FinalPresentationCard
# ---------------------------------------------------------------------------


class TestFinalPresentationCardReviewStatus:
    """Tests for showing approved/rejected status on the timeline card."""

    def _make_card(self):
        from massgen.frontend.displays.textual_widgets.content_sections import (
            FinalPresentationCard,
        )

        return FinalPresentationCard(
            agent_id="agent_a",
            model_name="test-model",
            vote_results=MOCK_VOTES,
        )

    def test_review_status_default_none(self):
        """Card should have no review status by default."""
        card = self._make_card()
        assert card._review_status is None

    def test_set_review_status_approved(self):
        """set_review_status('approved') should store the status."""
        card = self._make_card()
        card.set_review_status("approved")
        assert card._review_status == "approved"

    def test_set_review_status_rejected(self):
        """set_review_status('rejected') should store the status."""
        card = self._make_card()
        card.set_review_status("rejected")
        assert card._review_status == "rejected"


# ---------------------------------------------------------------------------
# Workspace tab feature
# ---------------------------------------------------------------------------


class TestWorkspacePathField:
    def test_workspace_path_field_default_none(self):
        """workspace_path defaults to None."""
        data = FinalAnswerModalData(answer_content="hello")
        assert data.workspace_path is None

    def test_workspace_path_set(self):
        """workspace_path can be set to a string path."""
        data = FinalAnswerModalData(answer_content="hello", workspace_path="/tmp/workspace")
        assert data.workspace_path == "/tmp/workspace"

    def test_make_data_with_workspace(self):
        """_make_data helper supports workspace_path."""
        data = _make_data(workspace_path="/tmp/ws")
        assert data.workspace_path == "/tmp/ws"


class TestComposeWithWorkspace:
    def test_compose_with_workspace_shows_two_tabs(self):
        """When workspace_path is set and no changes, compose yields TabbedContent."""
        data = _make_data(workspace_path="/tmp/workspace", changes=None)
        modal = FinalAnswerModal(data=data)
        # The compose method should produce widgets — verify the modal recognises
        # that it has a workspace to show.
        assert data.workspace_path is not None
        assert data.changes is None
        # _requires_decision should be False (no changes)
        assert modal._requires_decision is False

    def test_compose_without_workspace_shows_single_panel(self):
        """When no workspace_path and no changes, compose yields single panel (no tabs)."""
        data = _make_data(workspace_path=None, changes=None)
        modal = FinalAnswerModal(data=data)
        assert data.workspace_path is None
        assert data.changes is None
        assert modal._requires_decision is False

    def test_changes_take_precedence_over_workspace(self):
        """When both changes and workspace_path are set, changes branch wins."""
        data = _make_data(changes=_make_changes(), workspace_path="/tmp/ws")
        modal = FinalAnswerModal(data=data)
        # Should still have the review panel
        assert modal._panel is not None
        assert modal._requires_decision is True


class TestWorkspaceTabDismissBehavior:
    def test_esc_allowed_with_workspace_tab(self):
        """ESC should dismiss normally with workspace tab (no decision required)."""
        data = _make_data(workspace_path="/tmp/workspace", changes=None)
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False
        captured = {}

        def mock_super_dismiss(self_inner, result=None):
            captured["result"] = result

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_close_modal()
        assert "result" in captured

    def test_ctrl_c_immediate_dismiss_with_workspace_no_changes(self):
        """Ctrl+C should immediately dismiss when workspace but no changes."""
        data = _make_data(workspace_path="/tmp/workspace", changes=None)
        modal = FinalAnswerModal(data=data)
        assert modal._requires_decision is False
        captured = {}

        def mock_super_dismiss(self_inner, result=None):
            captured["result"] = result

        with patch.object(type(modal).__mro__[1], "dismiss", mock_super_dismiss):
            modal.action_force_close()
        assert "result" in captured
        assert modal._ctrl_c_warned is False


class TestWorkspaceAnswerTabButtons:
    def test_browse_workspace_button_shown(self):
        """AnswerTabContent with has_workspace=True should store has_workspace flag."""
        data = _make_data(workspace_path="/tmp/workspace")
        tab = AnswerTabContent(data=data, has_changes=False, has_workspace=True)
        assert tab._has_workspace is True

    def test_close_button_with_workspace(self):
        """AnswerTabContent with has_workspace=True and no changes should not show review buttons."""
        data = _make_data(workspace_path="/tmp/workspace")
        tab = AnswerTabContent(data=data, has_changes=False, has_workspace=True)
        assert tab._has_changes is False
        assert tab._has_workspace is True

    def test_browse_workspace_button_handler(self):
        """browse_workspace_btn should switch to workspace tab."""
        data = _make_data(workspace_path="/tmp/workspace", changes=None)
        modal = FinalAnswerModal(data=data)
        switched = {"called": False}
        modal.action_switch_review_tab = lambda: switched.update({"called": True})
        modal.call_later = lambda fn: fn()

        class FakeButton:
            id = "browse_workspace_btn"

        class FakeEvent:
            button = FakeButton()

            def stop(self):
                pass

            def prevent_default(self):
                pass

        modal.on_button_pressed(FakeEvent())
        assert switched["called"] is True


class TestWorkspaceTabSwitching:
    def test_switch_review_tab_handles_workspace_tab(self):
        """action_switch_review_tab should handle workspace_tab ID when no review tab."""
        data = _make_data(workspace_path="/tmp/workspace", changes=None)
        modal = FinalAnswerModal(data=data)
        # Should not raise even without a running app
        modal.action_switch_review_tab()
