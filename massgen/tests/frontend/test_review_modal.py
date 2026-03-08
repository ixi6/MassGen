"""Unit tests for GitDiffReviewModal — the change review modal for applying isolated changes."""

import pytest

from massgen.filesystem_manager import ReviewResult
from massgen.frontend.displays.textual.widgets.modals.review_modal import (
    GitDiffReviewModal,
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

MULTI_HUNK_DIFF = """\
diff --git a/utils.py b/utils.py
index 1111111..2222222 100644
--- a/utils.py
+++ b/utils.py
@@ -1,3 +1,4 @@
 # header
+import logging

 def foo():
@@ -20,3 +21,3 @@ def bar():
-    x = 1
+    x = 2
     return x
@@ -40,3 +41,4 @@ def baz():
     y = 10
+    z = 20
     return y
"""


def _make_changes(
    *,
    context_path: str = "/project",
    diff: str = SAMPLE_DIFF,
    files: list | None = None,
) -> list:
    """Build a minimal changes list for the modal constructor."""
    if files is None:
        files = [
            {"status": "M", "path": "src/app.py"},
        ]
    return [
        {
            "original_path": context_path,
            "isolated_path": "/tmp/worktree",
            "changes": files,
            "diff": diff,
        },
    ]


def _make_multi_file_changes() -> list:
    added_diff = """\
diff --git a/new_file.py b/new_file.py
new file mode 100644
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+# new file
+def hello():
+    pass
"""
    return [
        {
            "original_path": "/project",
            "isolated_path": "/tmp/worktree",
            "changes": [
                {"status": "M", "path": "src/app.py"},
                {"status": "A", "path": "new_file.py"},
                {"status": "D", "path": "old_file.py"},
            ],
            "diff": SAMPLE_DIFF + "\n" + added_diff,
        },
    ]


def _make_multi_context_changes() -> list:
    return [
        {
            "original_path": "/project_a",
            "isolated_path": "/tmp/worktree_a",
            "changes": [{"status": "M", "path": "foo.py"}],
            "diff": SAMPLE_DIFF.replace("src/app.py", "foo.py"),
        },
        {
            "original_path": "/project_b",
            "isolated_path": "/tmp/worktree_b",
            "changes": [{"status": "M", "path": "bar.py"}],
            "diff": SAMPLE_DIFF.replace("src/app.py", "bar.py"),
        },
    ]


# ---------------------------------------------------------------------------
# Construction & file tracking
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_single_file_tracked(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        assert len(modal._all_file_paths) == 1
        assert all(v is True for v in modal.file_approvals.values())

    def test_multiple_files_tracked(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        assert len(modal._all_file_paths) == 3

    def test_multi_context_files_tracked(self):
        modal = GitDiffReviewModal(changes=_make_multi_context_changes())
        assert len(modal._all_file_paths) == 2
        # Each file key includes its context path
        contexts = {modal._file_key_to_context[k] for k in modal._all_file_paths}
        assert contexts == {"/project_a", "/project_b"}

    def test_first_file_selected_by_default(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        assert modal._selected_file == modal._all_file_paths[0]

    def test_empty_changes_handled(self):
        modal = GitDiffReviewModal(changes=[])
        assert modal._all_file_paths == []
        assert modal._selected_file is None

    def test_duplicate_files_deduplicated(self):
        changes = _make_changes(
            files=[
                {"status": "M", "path": "src/app.py"},
                {"status": "M", "path": "src/app.py"},
            ],
        )
        modal = GitDiffReviewModal(changes=changes)
        assert len(modal._all_file_paths) == 1


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------


class TestDiffParsing:
    def test_per_file_diffs_extracted(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        diff_text = modal._per_file_diffs.get(file_key, "")
        assert "src/app.py" in diff_text

    def test_hunks_parsed(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        hunks = modal._hunks_by_file.get(file_key, [])
        assert len(hunks) == 2  # Two @@ sections in SAMPLE_DIFF

    def test_multi_hunk_diff_parsed(self):
        changes = _make_changes(
            diff=MULTI_HUNK_DIFF,
            files=[{"status": "M", "path": "utils.py"}],
        )
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]
        hunks = modal._hunks_by_file.get(file_key, [])
        assert len(hunks) == 3

    def test_placeholder_diff_for_missing(self):
        changes = _make_changes(diff="", files=[{"status": "A", "path": "brand_new.py"}])
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]
        diff_text = modal._per_file_diffs.get(file_key, "")
        assert "New file added" in diff_text


# ---------------------------------------------------------------------------
# File approval toggling
# ---------------------------------------------------------------------------


class TestFileApproval:
    def test_toggle_file_approval(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        file_key = modal._all_file_paths[0]
        assert modal.file_approvals[file_key] is True

        modal._toggle_file_approval(file_key)
        assert modal.file_approvals[file_key] is False

        modal._toggle_file_approval(file_key)
        assert modal.file_approvals[file_key] is True

    def test_set_all_approvals_true(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        modal.refresh = lambda *a, **kw: None
        modal._set_all_approvals(False)
        assert all(v is False for v in modal.file_approvals.values())

        modal._set_all_approvals(True)
        assert all(v is True for v in modal.file_approvals.values())

    def test_toggle_file_also_toggles_all_hunks(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        file_key = modal._all_file_paths[0]

        modal._toggle_file_approval(file_key)
        # All hunks should also be False
        hunk_approvals = modal._hunk_approvals[file_key]
        assert all(v is False for v in hunk_approvals.values())

    def test_set_all_approvals_syncs_hunks(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None

        modal._set_all_approvals(False)
        for file_key in modal._all_file_paths:
            for v in modal._hunk_approvals[file_key].values():
                assert v is False


# ---------------------------------------------------------------------------
# Hunk approval toggling
# ---------------------------------------------------------------------------


class TestHunkApproval:
    def test_all_hunks_approved_by_default(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        hunk_approvals = modal._hunk_approvals[file_key]
        assert all(v is True for v in hunk_approvals.values())

    def test_toggle_selected_hunk(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key
        modal._selected_hunk_index_by_file[file_key] = 0

        modal._toggle_selected_hunk()
        assert modal._hunk_approvals[file_key][0] is False
        assert modal._hunk_approvals[file_key][1] is True
        # File should still be approved (hunk 1 is still True)
        assert modal.file_approvals[file_key] is True

    def test_toggle_all_hunks_sets_file_unapproved(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key

        # Toggle hunk 0
        modal._selected_hunk_index_by_file[file_key] = 0
        modal._toggle_selected_hunk()
        # Toggle hunk 1
        modal._selected_hunk_index_by_file[file_key] = 1
        modal._toggle_selected_hunk()

        # All hunks rejected -> file should be unapproved
        assert modal.file_approvals[file_key] is False

    def test_hunk_navigation_wraps(self):
        changes = _make_changes(
            diff=MULTI_HUNK_DIFF,
            files=[{"status": "M", "path": "utils.py"}],
        )
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key

        assert modal._selected_hunk_index_by_file[file_key] == 0
        modal._move_selected_hunk(1)
        assert modal._selected_hunk_index_by_file[file_key] == 1
        modal._move_selected_hunk(1)
        assert modal._selected_hunk_index_by_file[file_key] == 2
        # Wrap around
        modal._move_selected_hunk(1)
        assert modal._selected_hunk_index_by_file[file_key] == 0

    def test_hunk_navigation_backward_wraps(self):
        changes = _make_changes(
            diff=MULTI_HUNK_DIFF,
            files=[{"status": "M", "path": "utils.py"}],
        )
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key

        modal._move_selected_hunk(-1)
        assert modal._selected_hunk_index_by_file[file_key] == 2  # wraps to last


# ---------------------------------------------------------------------------
# File navigation
# ---------------------------------------------------------------------------


class TestFileNavigation:
    def test_move_selection_down(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        modal.refresh = lambda *a, **kw: None
        first = modal._all_file_paths[0]
        second = modal._all_file_paths[1]
        assert modal._selected_file == first

        modal._move_selection(1)
        assert modal._selected_file == second

    def test_move_selection_wraps(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        modal.refresh = lambda *a, **kw: None
        last = modal._all_file_paths[-1]

        # Move to the end
        for _ in range(len(modal._all_file_paths) - 1):
            modal._move_selection(1)
        assert modal._selected_file == last

        # Wrap to beginning
        modal._move_selection(1)
        assert modal._selected_file == modal._all_file_paths[0]


# ---------------------------------------------------------------------------
# Dismiss results
# ---------------------------------------------------------------------------


class TestDismissResults:
    def _capture_dismiss(self, modal):
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        return captured

    def test_approve_all_returns_none_files(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        captured = self._capture_dismiss(modal)
        modal._approve_all()
        result = captured["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is True
        assert result.approved_files is None
        assert result.metadata["selection_mode"] == "all"

    def test_reject_all_returns_not_approved(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        captured = self._capture_dismiss(modal)
        modal._reject_all()
        result = captured["result"]
        assert result.approved is False
        assert result.metadata["selection_mode"] == "rejected"

    def test_cancel_returns_not_approved(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        captured = self._capture_dismiss(modal)
        modal._cancel()
        result = captured["result"]
        assert result.approved is False
        assert result.metadata["selection_mode"] == "cancelled"

    def test_approve_selected_returns_only_approved_files(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)

        # Reject the second file
        modal._toggle_file_approval(modal._all_file_paths[1])

        modal._approve_selected()
        result = captured["result"]
        assert result.approved is True
        assert result.metadata["selection_mode"] == "selected"
        # Should have 2 approved (file 0 and file 2), not 3
        assert len(result.approved_files) == 2

    def test_approve_selected_includes_hunk_approvals(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)

        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key
        modal._selected_hunk_index_by_file[file_key] = 1
        modal._toggle_selected_hunk()

        modal._approve_selected()
        result = captured["result"]
        hunks_by_context = result.metadata.get("approved_hunks_by_context", {})
        assert hunks_by_context  # Should have hunk data
        # Hunk 0 approved, hunk 1 rejected
        context_hunks = hunks_by_context.get("/project", {})
        assert context_hunks.get("src/app.py") == [0]


# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------


class TestDiffRendering:
    def test_renders_added_lines_green(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        # Added lines use green color
        assert "#56d364" in markup

    def test_renders_removed_lines_red(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        # Removed lines use red color
        assert "#f85149" in markup

    def test_renders_hunk_headers_cyan(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        assert "cyan" in markup

    def test_unapproved_hunk_renders_dim(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        file_key = modal._all_file_paths[0]
        modal._selected_file = file_key
        modal._selected_hunk_index_by_file[file_key] = 0
        modal._toggle_selected_hunk()

        markup = modal._render_diff_markup(file_key)
        # The rejected hunk's added line should be dim, not green
        lines = markup.split("\n")
        # Find the first hunk's add line (import sys)
        import_sys_lines = [line for line in lines if "import sys" in line]
        assert import_sys_lines
        assert "dim" in import_sys_lines[0]

    def test_no_file_selected_shows_prompt(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        markup = modal._render_diff_markup(None)
        assert "Select a file" in markup

    def test_line_numbers_present_in_diff(self):
        """Line numbers should appear in the rendered diff markup for added/removed/context lines."""
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        lines = markup.split("\n")

        # Find a context line (starts with space in the raw diff)
        # "import os" is the first context line after the @@ header
        import_os_lines = [line for line in lines if "import os" in line]
        assert import_os_lines, "Should find 'import os' context line"
        # Line numbers should appear as a dim prefix like "  1     1  "
        # (old line number and new line number)
        import re

        # Match a line number pattern: digits followed by space
        has_line_number = any(re.search(r"\d+\s.*import os", line) for line in import_os_lines)
        assert has_line_number, f"Expected line numbers before 'import os', got: {import_os_lines}"

    def test_added_line_shows_new_line_number_only(self):
        """Added lines should show only the new line number, not old."""
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        lines = markup.split("\n")
        # "import sys" is an added line
        import_sys_lines = [line for line in lines if "import sys" in line]
        assert import_sys_lines
        # Should have a new line number (2) but show blank for old
        # Pattern: spaces/blank for old, digit for new
        import re

        has_new_only = any(re.search(r"\s+2\s", line) for line in import_sys_lines)
        assert has_new_only, f"Expected new line number 2 for added line, got: {import_sys_lines}"

    def test_removed_line_shows_old_line_number_only(self):
        """Removed lines should show only the old line number, not new."""
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        markup = modal._render_diff_markup(file_key)
        lines = markup.split("\n")
        # "return False" is a removed line
        return_false_lines = [line for line in lines if "return False" in line]
        assert return_false_lines


# ---------------------------------------------------------------------------
# Escape markup
# ---------------------------------------------------------------------------


class TestEscapeMarkup:
    def test_escapes_square_brackets(self):
        result = GitDiffReviewModal._escape_markup("array[0] = value[1]")
        assert "\\[" in result
        assert "\\]" in result

    def test_plain_text_unchanged(self):
        result = GitDiffReviewModal._escape_markup("hello world")
        assert result == "hello world"


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------


class TestStatusBadges:
    @pytest.mark.parametrize(
        "status,expected_color",
        [
            ("M", "yellow"),
            ("A", "bright_green"),
            ("D", "bright_red"),
            ("?", "cyan"),
        ],
    )
    def test_status_badge_colors(self, status, expected_color):
        modal = GitDiffReviewModal(changes=_make_changes())
        badge = modal._get_status_badge(status)
        assert expected_color in badge


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


class TestSummaryLine:
    def test_summary_counts(self):
        modal = GitDiffReviewModal(changes=_make_multi_file_changes())
        summary = modal._build_summary_markup(
            parts=["[yellow]1 modified[/]", "[bright_green]1 added[/]", "[bright_red]1 deleted[/]"],
            total_contexts=1,
            total_files=3,
        )
        assert "3/3 selected" in summary

    def test_multi_context_mentioned(self):
        modal = GitDiffReviewModal(changes=_make_multi_context_changes())
        summary = modal._build_summary_markup(
            parts=[],
            total_contexts=2,
            total_files=2,
        )
        assert "2 contexts" in summary


# ---------------------------------------------------------------------------
# Diff header
# ---------------------------------------------------------------------------


class TestDiffHeader:
    def test_header_shows_file_path(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        header = modal._make_diff_header_text()
        assert "src/app.py" in header

    def test_header_shows_hunk_position(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        header = modal._make_diff_header_text()
        assert "hunk 1/2" in header

    def test_header_shows_context_for_multi_context(self):
        modal = GitDiffReviewModal(changes=_make_multi_context_changes())
        header = modal._make_diff_header_text()
        assert "project_a" in header


# ---------------------------------------------------------------------------
# Rework flow
# ---------------------------------------------------------------------------


class TestReworkFlow:
    """Test rework/quick_fix dismiss actions and feedback validation."""

    def _capture_dismiss(self, modal):
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        return captured

    def test_rework_returns_correct_action(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)
        modal._rework_feedback_value = "fix the imports"
        modal._rework()
        result = captured["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is False
        assert result.action == "rework"
        assert result.feedback == "fix the imports"

    def test_quick_fix_returns_correct_action(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)
        modal._rework_feedback_value = "add error handling"
        modal._quick_fix()
        result = captured["result"]
        assert isinstance(result, ReviewResult)
        assert result.approved is False
        assert result.action == "quick_fix"
        assert result.feedback == "add error handling"

    def test_rework_without_feedback_does_not_dismiss(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)
        modal._rework_feedback_value = ""
        modal._rework()
        # Should NOT have dismissed since no feedback
        assert "result" not in captured

    def test_quick_fix_without_feedback_does_not_dismiss(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)
        modal._rework_feedback_value = ""
        modal._quick_fix()
        assert "result" not in captured

    def test_rework_feedback_whitespace_only_does_not_dismiss(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = self._capture_dismiss(modal)
        modal._rework_feedback_value = "   "
        modal._rework()
        assert "result" not in captured

    def test_has_rework_mixin_ids(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        # Should have the review-specific rework widget IDs
        assert modal.REWORK_FEEDBACK_INPUT_ID == "review_rework_feedback_input"
        assert modal.REWORK_CONTINUE_BTN_ID == "review_rework_continue_btn"
        assert modal.REWORK_QUICK_EDIT_BTN_ID == "review_rework_quick_edit_btn"


# ---------------------------------------------------------------------------
# FileEditorModal
# ---------------------------------------------------------------------------


class TestFileEditorModal:
    """Test the file editor modal construction and dismiss behavior."""

    def test_construction(self):
        from massgen.frontend.displays.textual.widgets.modals.review_modal import (
            FileEditorModal,
        )

        editor = FileEditorModal(file_path="src/app.py", initial_content="hello world")
        assert editor._file_path == "src/app.py"
        assert editor._initial_content == "hello world"

    def test_dismiss_with_none_on_cancel(self):
        from massgen.frontend.displays.textual.widgets.modals.review_modal import (
            FileEditorModal,
        )

        editor = FileEditorModal(file_path="src/app.py", initial_content="original")
        captured = {}
        editor.dismiss = lambda result: captured.update({"result": result})
        editor._cancel_edit()
        assert captured["result"] is None

    def test_dismiss_with_content_on_save(self):
        from massgen.frontend.displays.textual.widgets.modals.review_modal import (
            FileEditorModal,
        )

        editor = FileEditorModal(file_path="src/app.py", initial_content="original")
        captured = {}
        editor.dismiss = lambda result: captured.update({"result": result})
        editor._edited_content = "modified content"
        editor._save_edit()
        assert captured["result"] == "modified content"


# ---------------------------------------------------------------------------
# Review modal edit file context mapping
# ---------------------------------------------------------------------------


class TestEditFileContextMapping:
    """Test that _context_to_isolated mapping is built from changes data."""

    def test_context_to_isolated_mapping_built(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        # The mapping should contain isolated_path keyed by original_path
        assert hasattr(modal, "_context_to_isolated")
        assert modal._context_to_isolated.get("/project") == "/tmp/worktree"

    def test_multi_context_mapping(self):
        modal = GitDiffReviewModal(changes=_make_multi_context_changes())
        assert modal._context_to_isolated.get("/project_a") == "/tmp/worktree_a"
        assert modal._context_to_isolated.get("/project_b") == "/tmp/worktree_b"


# ---------------------------------------------------------------------------
# Hunk scroll-to-navigation
# ---------------------------------------------------------------------------


class TestHunkScrolling:
    """Test per-hunk Static widgets and scroll target IDs."""

    def test_render_diff_sections_returns_per_hunk_ids(self):
        """_render_diff_sections should return unique IDs per hunk."""
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        sections = modal._render_diff_sections(file_key)

        # Meta section + 2 hunks = 3 sections
        assert len(sections) == 3
        ids = [s[0] for s in sections]
        # All IDs should be unique
        assert len(ids) == len(set(ids))
        # First should be meta, rest should be hunks
        assert ids[0].startswith("meta_")
        assert ids[1].startswith("hunk_")
        assert ids[2].startswith("hunk_")

    def test_render_diff_sections_multi_hunk(self):
        """Multi-hunk diffs should produce matching section count."""
        changes = _make_changes(
            diff=MULTI_HUNK_DIFF,
            files=[{"status": "M", "path": "utils.py"}],
        )
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]
        sections = modal._render_diff_sections(file_key)

        # Meta section + 3 hunks
        assert len(sections) == 4

    def test_render_diff_sections_no_file_returns_single(self):
        """When no file is selected, should return one section with prompt."""
        modal = GitDiffReviewModal(changes=_make_changes())
        sections = modal._render_diff_sections(None)
        assert len(sections) == 1
        assert "Select a file" in sections[0][1]

    def test_scroll_target_hunk_id_matches(self):
        """The scroll target for selected hunk should match section IDs."""
        changes = _make_changes(
            diff=MULTI_HUNK_DIFF,
            files=[{"status": "M", "path": "utils.py"}],
        )
        modal = GitDiffReviewModal(changes=changes)
        file_key = modal._all_file_paths[0]

        sections = modal._render_diff_sections(file_key)
        hunk_ids = [s[0] for s in sections if s[0].startswith("hunk_")]

        # Move to hunk 1
        modal._selected_hunk_index_by_file[file_key] = 1
        target_id = modal._get_scroll_target_id(file_key)
        assert target_id == hunk_ids[1]

    def test_hunk_ids_stable_across_renders(self):
        """Hunk IDs should be deterministic for the same file."""
        modal = GitDiffReviewModal(changes=_make_changes())
        file_key = modal._all_file_paths[0]
        sections1 = modal._render_diff_sections(file_key)
        sections2 = modal._render_diff_sections(file_key)
        assert [s[0] for s in sections1] == [s[0] for s in sections2]


# ---------------------------------------------------------------------------
# Rework result construction
# ---------------------------------------------------------------------------


class TestReworkResultConstruction:
    """Verify rework/quick_fix ReviewResult objects have the correct shape."""

    def test_rework_result_has_all_fields(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        modal._rework_feedback_value = "fix the order"
        modal._rework()
        result = captured["result"]
        assert result.action == "rework"
        assert result.feedback == "fix the order"
        assert result.approved is False
        assert result.metadata.get("selection_mode") == "rework"

    def test_quick_fix_result_has_all_fields(self):
        modal = GitDiffReviewModal(changes=_make_changes())
        modal.refresh = lambda *a, **kw: None
        captured = {}
        modal.dismiss = lambda result: captured.update({"result": result})
        modal._rework_feedback_value = "add tests"
        modal._quick_fix()
        result = captured["result"]
        assert result.action == "quick_fix"
        assert result.feedback == "add tests"
        assert result.approved is False
        assert result.metadata.get("selection_mode") == "quick_fix"


# ---------------------------------------------------------------------------
# Orchestrator error-handling safety (tests the orchestrator's behavior)
# ---------------------------------------------------------------------------


class TestOrchestratorSafety:
    """Tests that verify the orchestrator rejects changes on error rather than auto-approving."""

    @pytest.mark.asyncio
    async def test_show_change_review_modal_returns_false_on_no_app(self):
        """When no app is available, should return approved=False."""
        from massgen.frontend.displays.textual_terminal_display import (
            TextualTerminalDisplay,
        )

        display = TextualTerminalDisplay.__new__(TextualTerminalDisplay)
        display._app = None

        result = await display.show_change_review_modal([])
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_show_final_answer_modal_workspace_only_skips_review_status_update(self, monkeypatch):
        """Workspace-only final modal should not mark changes as approved/applied."""
        from massgen.frontend.displays.textual_terminal_display import (
            TextualTerminalDisplay,
        )

        class FakeApp:
            def call_from_thread(self, fn):
                fn()

            def push_screen(self, _modal, callback):
                callback(ReviewResult(approved=True))

        display = TextualTerminalDisplay.__new__(TextualTerminalDisplay)
        display._app = FakeApp()

        update_calls = []
        monkeypatch.setattr(display, "_update_card_review_status", lambda _result: update_calls.append(True))

        result = await display.show_final_answer_modal(
            changes=[],
            answer_content="final answer",
            vote_results={},
            agent_id="agent_a",
            workspace_path="/tmp/workspace",
        )

        assert result.approved is True
        assert update_calls == []

    @pytest.mark.asyncio
    async def test_show_final_answer_modal_with_changes_updates_review_status(self, monkeypatch):
        """Real reviewed changes should still update review status."""
        from massgen.frontend.displays.textual_terminal_display import (
            TextualTerminalDisplay,
        )

        class FakeApp:
            def call_from_thread(self, fn):
                fn()

            def push_screen(self, _modal, callback):
                callback(ReviewResult(approved=True))

        display = TextualTerminalDisplay.__new__(TextualTerminalDisplay)
        display._app = FakeApp()

        update_calls = []
        monkeypatch.setattr(display, "_update_card_review_status", lambda _result: update_calls.append(True))

        result = await display.show_final_answer_modal(
            changes=_make_changes(),
            answer_content="final answer",
            vote_results={},
            agent_id="agent_a",
        )

        assert result.approved is True
        assert update_calls == [True]
