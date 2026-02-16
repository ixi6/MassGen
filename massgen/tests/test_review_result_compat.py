# -*- coding: utf-8 -*-
"""Backward-compatibility tests for ReviewResult after adding action/feedback fields."""

from massgen.filesystem_manager._change_applier import ReviewResult


class TestReviewResultBackwardCompat:
    """Ensure existing code that constructs ReviewResult without new fields still works."""

    def test_minimal_construction(self):
        """Old-style construction with only approved=True should still work."""
        result = ReviewResult(approved=True)
        assert result.approved is True
        assert result.approved_files is None
        assert result.comments is None
        assert result.metadata == {}
        assert result.action == "approve"
        assert result.feedback is None

    def test_old_style_with_metadata(self):
        """Old-style construction with metadata dict should still work."""
        result = ReviewResult(
            approved=False,
            metadata={"selection_mode": "rejected"},
        )
        assert result.approved is False
        assert result.action == "approve"  # default
        assert result.feedback is None

    def test_new_style_with_action_and_feedback(self):
        """New-style construction with action and feedback."""
        result = ReviewResult(
            approved=False,
            action="rework",
            feedback="fix the imports",
        )
        assert result.approved is False
        assert result.action == "rework"
        assert result.feedback == "fix the imports"

    def test_all_action_values(self):
        """All expected action values should be settable."""
        for action in ("approve", "reject", "cancel", "rework", "quick_fix"):
            result = ReviewResult(approved=False, action=action)
            assert result.action == action

    def test_approved_files_still_works(self):
        """approved_files field should still function."""
        result = ReviewResult(
            approved=True,
            approved_files=["a.py", "b.py"],
            action="approve",
        )
        assert result.approved_files == ["a.py", "b.py"]
