"""
Git diff review modal for approving/rejecting changes before applying.

This modal is a thin wrapper around ReviewChangesPanel, providing the
modal screen behavior (BINDINGS, dismiss) while the panel handles all
diff parsing, rendering, file selection, and approval state.
"""

from typing import Any, Optional

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal
    from textual.screen import ModalScreen
    from textual.widgets import Button, Static, TextArea

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from massgen.filesystem_manager import ReviewResult

from ..modal_base import BaseModal
from .review_changes_panel import ReviewChangesPanel


class FileEditorModal(ModalScreen[Optional[str]]):
    """Full-screen modal for editing a file's content.

    Dismisses with the edited content string on save, or None on cancel.
    """

    BINDINGS = [
        ("escape", "cancel_edit", "Cancel"),
    ]

    DEFAULT_CSS = ""

    def __init__(
        self,
        file_path: str,
        initial_content: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._file_path = file_path
        self._initial_content = initial_content
        self._edited_content = initial_content

    def compose(self) -> ComposeResult:
        with Container(id="file_editor_container"):
            with Container(classes="modal-header"):
                with Horizontal(classes="header-row"):
                    yield Static(
                        f"Edit: {self._file_path}",
                        classes="modal-title",
                    )
                    yield Button(
                        "\u2715",
                        variant="default",
                        classes="modal-close",
                        id="editor_close_btn",
                    )
            with Container(classes="modal-body"):
                yield TextArea(
                    self._initial_content,
                    id="file_editor_textarea",
                )
            with Container(classes="modal-footer"):
                with Horizontal(classes="footer-buttons"):
                    yield Button(
                        "Save",
                        variant="primary",
                        id="editor_save_btn",
                    )
                    yield Button(
                        "Cancel (Esc)",
                        variant="default",
                        id="editor_cancel_btn",
                    )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "file_editor_textarea":
            self._edited_content = event.text_area.text

    def _save_edit(self) -> None:
        """Save the edited content and dismiss."""
        try:
            self._edited_content = self.query_one("#file_editor_textarea", TextArea).text
        except Exception:
            pass
        self.dismiss(self._edited_content)

    def _cancel_edit(self) -> None:
        """Cancel editing and dismiss with None."""
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "editor_save_btn":
            self._save_edit()
        elif event.button.id in ("editor_cancel_btn", "editor_close_btn"):
            self._cancel_edit()

    def action_cancel_edit(self) -> None:
        self._cancel_edit()


class GitDiffReviewModal(BaseModal):
    """Modal for reviewing git diffs before applying changes.

    Thin wrapper around ReviewChangesPanel that provides:
    - Modal screen behavior (push/dismiss)
    - Keyboard BINDINGS that delegate to the inner panel
    - Dismiss with ReviewResult on user action
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("a", "approve_all", "Approve All"),
        ("r", "reject_all", "Reject All"),
        ("enter", "approve_selected", "Approve Selected"),
        ("space", "toggle_selected", "Toggle File"),
        ("h", "toggle_selected_hunk", "Toggle Hunk"),
        ("[", "select_previous_hunk", "Previous Hunk"),
        ("]", "select_next_hunk", "Next Hunk"),
        ("up", "select_previous_file", "Previous File"),
        ("down", "select_next_file", "Next File"),
        ("e", "edit_file", "Edit File"),
    ]

    # Backward-compat: expose FILE_KEY_SEPARATOR at the modal level
    FILE_KEY_SEPARATOR = ReviewChangesPanel.FILE_KEY_SEPARATOR

    # Backward-compat: expose rework widget IDs at the modal level
    REWORK_FEEDBACK_INPUT_ID = ReviewChangesPanel.REWORK_FEEDBACK_INPUT_ID
    REWORK_CONTINUE_BTN_ID = ReviewChangesPanel.REWORK_CONTINUE_BTN_ID
    REWORK_QUICK_EDIT_BTN_ID = ReviewChangesPanel.REWORK_QUICK_EDIT_BTN_ID

    def __init__(self, changes: list[dict[str, Any]], **kwargs):
        super().__init__(**kwargs)
        self._changes = changes
        self._panel = ReviewChangesPanel(changes=changes, id="review_panel")

    # ------------------------------------------------------------------
    # Backward-compat: proxy panel state so tests accessing modal attrs
    # continue to work (e.g. modal.file_approvals, modal._all_file_paths)
    # ------------------------------------------------------------------

    @property
    def changes(self) -> list[dict[str, Any]]:
        return self._panel.changes

    @property
    def file_approvals(self) -> dict[str, bool]:
        return self._panel.file_approvals

    @property
    def _file_key_to_context(self) -> dict[str, str]:
        return self._panel._file_key_to_context

    @property
    def _file_key_to_path(self) -> dict[str, str]:
        return self._panel._file_key_to_path

    @property
    def _context_to_isolated(self) -> dict[str, str]:
        return self._panel._context_to_isolated

    @property
    def _all_file_paths(self) -> list[str]:
        return self._panel._all_file_paths

    @property
    def _per_file_diffs(self) -> dict[str, str]:
        return self._panel._per_file_diffs

    @property
    def _selected_file(self) -> str | None:
        return self._panel._selected_file

    @_selected_file.setter
    def _selected_file(self, value: str | None) -> None:
        self._panel._selected_file = value

    @property
    def _hunks_by_file(self) -> dict[str, list[dict[str, Any]]]:
        return self._panel._hunks_by_file

    @property
    def _hunk_approvals(self) -> dict[str, dict[int, bool]]:
        return self._panel._hunk_approvals

    @property
    def _selected_hunk_index_by_file(self) -> dict[str, int]:
        return self._panel._selected_hunk_index_by_file

    @property
    def _rework_feedback_value(self) -> str:
        return self._panel._rework_feedback_value

    @_rework_feedback_value.setter
    def _rework_feedback_value(self, value: str) -> None:
        self._panel._rework_feedback_value = value

    # ------------------------------------------------------------------
    # Compose: header + panel
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        total_files = len(self._panel._all_file_paths)
        title = f"Review Changes ({total_files} file{'s' if total_files != 1 else ''})"

        with Container(
            id="review_modal_container",
            classes="modal-container modal-container-wide review-modal",
        ):
            yield from self.make_header(title, icon="")
            yield self._panel

    # ------------------------------------------------------------------
    # Handle ActionRequested from the panel → dismiss the modal
    # ------------------------------------------------------------------

    def on_review_changes_panel_action_requested(
        self,
        event: ReviewChangesPanel.ActionRequested,
    ) -> None:
        """Translate panel action into modal dismiss."""
        event.stop()
        self.dismiss(event.review_result)

    # ------------------------------------------------------------------
    # Keyboard actions — delegate to the inner panel
    # ------------------------------------------------------------------

    def action_approve_all(self) -> None:
        self._panel._approve_all()

    def action_reject_all(self) -> None:
        self._panel._reject_all()

    def action_approve_selected(self) -> None:
        self._panel._approve_selected()

    def action_cancel(self) -> None:
        self._panel._cancel()

    def action_toggle_selected(self) -> None:
        if self._panel._selected_file:
            self._panel._toggle_file_approval(self._panel._selected_file)

    def action_toggle_selected_hunk(self) -> None:
        self._panel._toggle_selected_hunk()

    def action_select_previous_hunk(self) -> None:
        self._panel._move_selected_hunk(-1)

    def action_select_next_hunk(self) -> None:
        self._panel._move_selected_hunk(1)

    def action_select_previous_file(self) -> None:
        self._panel._move_selection(-1)

    def action_select_next_file(self) -> None:
        self._panel._move_selection(1)

    def action_edit_file(self) -> None:
        self._panel.action_edit_file()

    # ------------------------------------------------------------------
    # Backward-compat: proxy methods used by tests
    # ------------------------------------------------------------------

    def _toggle_file_approval(self, file_path: str) -> None:
        self._panel._toggle_file_approval(file_path)

    def _set_all_approvals(self, value: bool) -> None:
        self._panel._set_all_approvals(value)

    def _move_selection(self, step: int) -> None:
        self._panel._move_selection(step)

    def _move_selected_hunk(self, step: int) -> None:
        self._panel._move_selected_hunk(step)

    def _toggle_selected_hunk(self) -> None:
        self._panel._toggle_selected_hunk()

    def _approve_selected(self) -> None:
        """Approve selected — directly dismiss (bypass message for modal-only use)."""
        result = self._panel.get_review_result("approve")
        self.dismiss(result)

    def _approve_all(self) -> None:
        result = ReviewResult(
            approved=True,
            approved_files=None,
            metadata={"selection_mode": "all"},
            action="approve",
        )
        self.dismiss(result)

    def _reject_all(self) -> None:
        result = self._panel.get_review_result("reject")
        self.dismiss(result)

    def _cancel(self) -> None:
        result = self._panel.get_review_result("cancel")
        self.dismiss(result)

    def _rework(self) -> None:
        self._panel._snapshot_rework_input()
        feedback = self._panel._rework_feedback_text()
        if not feedback:
            return
        result = self._panel.get_review_result("rework")
        self.dismiss(result)

    def _quick_fix(self) -> None:
        self._panel._snapshot_rework_input()
        feedback = self._panel._rework_feedback_text()
        if not feedback:
            return
        result = self._panel.get_review_result("quick_fix")
        self.dismiss(result)

    # ------------------------------------------------------------------
    # Backward-compat: proxy static/class methods used by tests
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_markup(text: str) -> str:
        return ReviewChangesPanel._escape_markup(text)

    @classmethod
    def _make_file_key(cls, context_path: str, file_path: str) -> str:
        return ReviewChangesPanel._make_file_key(context_path, file_path)

    @staticmethod
    def _parse_hunks(file_diff: str) -> list[dict[str, Any]]:
        return ReviewChangesPanel._parse_hunks(file_diff)

    def _render_diff_markup(self, file_path: str | None) -> str:
        return self._panel._render_diff_markup(file_path)

    def _render_diff_sections(self, file_path: str | None) -> list[tuple]:
        return self._panel._render_diff_sections(file_path)

    def _get_scroll_target_id(self, file_path: str | None) -> str | None:
        return self._panel._get_scroll_target_id(file_path)

    def _get_status_badge(self, status: str) -> str:
        return self._panel._get_status_badge(status)

    def _build_summary_markup(
        self,
        parts: list[str],
        total_contexts: int,
        total_files: int,
    ) -> str:
        return self._panel._build_summary_markup(parts, total_contexts, total_files)

    def _make_diff_header_text(self) -> str:
        return self._panel._make_diff_header_text()

    def _make_checkbox_id(self, file_path: str) -> str:
        return self._panel._make_checkbox_id(file_path)


__all__ = [
    "GitDiffReviewModal",
    "FileEditorModal",
    "ReviewChangesPanel",
]
