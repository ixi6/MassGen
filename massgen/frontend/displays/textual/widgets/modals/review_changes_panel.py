# -*- coding: utf-8 -*-
"""
Reusable two-panel diff review widget (file list + diff viewer).

Extracted from GitDiffReviewModal so it can be composed inside both the
standalone review modal and the tabbed FinalAnswerModal.
"""

import re
from hashlib import sha1
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.message import Message
    from textual.widgets import Button, Input, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from massgen.filesystem_manager import ReviewResult

from ..rework_controls import ReworkControlsMixin


class _ApprovalToggle(Static):
    """Clickable approval indicator. Click to toggle approved/excluded."""

    class Toggled(Message):
        def __init__(self, file_path: str) -> None:
            super().__init__()
            self.file_path = file_path

    def __init__(self, file_path: str, approved: bool = True, **kwargs):
        indicator = "\u2713" if approved else "\u25cb"  # ✓ or ○
        super().__init__(indicator, **kwargs)
        self.file_path = file_path

    def on_click(self, event) -> None:
        event.stop()
        self.post_message(self.Toggled(self.file_path))


class _FileEntry(Static):
    """Clickable file name. Click to select and view diff."""

    class FileSelected(Message):
        def __init__(self, file_path: str) -> None:
            super().__init__()
            self.file_path = file_path

    def __init__(self, file_path: str, display_label: str, **kwargs):
        super().__init__(display_label, markup=True, **kwargs)
        self.file_path = file_path

    def on_click(self, event) -> None:
        event.stop()
        self.post_message(self.FileSelected(self.file_path))


class ReviewChangesPanel(ReworkControlsMixin, Vertical):
    """Reusable two-panel diff review widget (file list + diff viewer).

    Emits ActionRequested messages when the user clicks Apply/Reject/Cancel.
    The parent modal should handle these messages to dismiss with the
    appropriate ReviewResult.
    """

    # Rework control widget IDs
    REWORK_FEEDBACK_INPUT_ID = "review_rework_feedback_input"
    REWORK_CONTINUE_BTN_ID = "review_rework_continue_btn"
    REWORK_QUICK_EDIT_BTN_ID = "review_rework_quick_edit_btn"

    FILE_KEY_SEPARATOR = "::"

    class ActionRequested(Message):
        """Emitted when Apply/Reject/Cancel clicked."""

        def __init__(self, action: str, review_result: "ReviewResult") -> None:
            super().__init__()
            self.action = action
            self.review_result = review_result

    def __init__(
        self,
        changes: List[Dict[str, Any]],
        show_footer: bool = True,
        show_rework: bool = True,
        show_all_keyboard_hints: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.changes = changes
        self._show_footer = show_footer
        self._show_rework = show_rework
        self._show_all_keyboard_hints = show_all_keyboard_hints
        self.file_approvals: Dict[str, bool] = {}
        self._file_key_to_context: Dict[str, str] = {}
        self._file_key_to_path: Dict[str, str] = {}
        self._context_to_isolated: Dict[str, str] = {}
        self._checkbox_to_path: Dict[str, str] = {}
        self._file_key_to_checkbox: Dict[str, str] = {}
        self._all_file_paths: List[str] = []
        self._per_file_diffs: Dict[str, str] = {}
        self._selected_file: Optional[str] = None
        self._hunks_by_file: Dict[str, List[Dict[str, Any]]] = {}
        self._hunk_approvals: Dict[str, Dict[int, bool]] = {}
        self._selected_hunk_index_by_file: Dict[str, int] = {}

        # Build file list, approval map, and per-file diffs
        for ctx in changes:
            context_path = ctx.get("original_path", "")
            isolated_path = ctx.get("isolated_path", "")
            if context_path and isolated_path:
                self._context_to_isolated[context_path] = isolated_path
            combined_diff = ctx.get("diff", "")
            parsed_diffs = self._parse_per_file_diffs(combined_diff)

            for change in ctx.get("changes", []):
                file_path = change.get("path", "")
                if file_path:
                    file_key = self._make_file_key(context_path, file_path)
                    if file_key in self.file_approvals:
                        continue

                    self.file_approvals[file_key] = True
                    self._file_key_to_context[file_key] = context_path
                    self._file_key_to_path[file_key] = file_path
                    self._all_file_paths.append(file_key)

                    checkbox_id = self._make_checkbox_id(file_key)
                    self._checkbox_to_path[checkbox_id] = file_key
                    self._file_key_to_checkbox[file_key] = checkbox_id

                    # Try to find this file's diff from parsed output
                    if file_key not in self._per_file_diffs:
                        matched_diff = self._find_file_diff(file_path, parsed_diffs)
                        if matched_diff:
                            self._per_file_diffs[file_key] = matched_diff
                        else:
                            status = change.get("status", "?")
                            self._per_file_diffs[file_key] = self._make_placeholder_diff(file_path, status)

                    hunks = self._parse_hunks(self._per_file_diffs.get(file_key, ""))
                    self._hunks_by_file[file_key] = hunks
                    self._hunk_approvals[file_key] = {idx: True for idx in range(len(hunks))}
                    self._selected_hunk_index_by_file[file_key] = 0

        # Default to first file selected
        if self._all_file_paths:
            self._selected_file = self._all_file_paths[0]

    def compose(self) -> ComposeResult:
        total_files = len(self._all_file_paths)

        # Summary line
        total_contexts = len(self.changes)
        added = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() in ("A", "?", "+"))
        modified = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() == "M")
        deleted = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() in ("D", "-"))
        parts = []
        if modified:
            parts.append(f"[yellow]{modified} modified[/]")
        if added:
            parts.append(f"[bright_green]{added} added[/]")
        if deleted:
            parts.append(f"[bright_red]{deleted} deleted[/]")
        yield Static(
            self._build_summary_markup(parts=parts, total_contexts=total_contexts, total_files=total_files),
            id="review_summary",
            classes="modal-summary",
            markup=True,
        )
        hints = "[dim]" "[bold]\u2191\u2193[/bold] navigate  " "[bold]Space[/bold] toggle  " "[bold]h[/bold] hunk  " "[bold]\\[[/bold] [bold]\\][/bold] prev/next" "  \u2502  " "[bold]e[/bold] edit  "
        if self._show_all_keyboard_hints:
            hints += "[bold]a[/bold] all  " "[bold]r[/bold] reject  "
        hints += "[bold]Enter[/bold] apply  "
        if self._show_all_keyboard_hints:
            hints += "[bold]Esc[/bold] cancel"
        hints += "[/]"
        yield Static(hints, classes="modal-instructions", markup=True)

        # Main two-panel content area
        with Horizontal(id="review_content", classes="review-content"):
            # ---- Left panel: File list ----
            with Vertical(id="review_file_list", classes="review-file-list"):
                # File list header with select/deselect toggle
                with Horizontal(classes="review-file-list-header"):
                    yield Static(
                        "[bold]Files[/]",
                        classes="review-file-list-title",
                        markup=True,
                    )
                    yield Button(
                        "All",
                        id="select_all_btn",
                        classes="review-toggle-btn",
                    )
                    yield Button(
                        "None",
                        id="deselect_all_btn",
                        classes="review-toggle-btn",
                    )

                with VerticalScroll(id="file_list_scroll"):
                    rendered_keys = set()
                    for ctx in self.changes:
                        context_path = ctx.get("original_path", "")
                        context_name = Path(context_path).name if context_path else "Unknown"
                        if len(self.changes) > 1:
                            yield Static(
                                f"[bold dim]{context_name}[/]",
                                classes="review-context-header",
                                markup=True,
                            )

                        for change in ctx.get("changes", []):
                            status = change.get("status", "?")
                            file_path = change.get("path", "")
                            if not file_path:
                                continue

                            file_key = self._make_file_key(context_path, file_path)
                            if file_key in rendered_keys:
                                continue
                            rendered_keys.add(file_key)

                            status_badge = self._get_status_badge(status)
                            entry_id = self._file_key_to_checkbox.get(file_key, self._make_checkbox_id(file_key))
                            display_name = Path(file_path).name
                            if "/" in file_path:
                                display_name = str(Path(file_path).parent.name) + "/" + display_name

                            is_selected = file_key == self._selected_file
                            approved = self.file_approvals.get(file_key, True)

                            row_classes = "review-file-row"
                            if is_selected:
                                row_classes += " review-file-selected"

                            with Horizontal(
                                classes=row_classes,
                                id=f"row_{entry_id}",
                            ):
                                yield _ApprovalToggle(
                                    file_path=file_key,
                                    approved=approved,
                                    classes="review-toggle-indicator" + (" review-approved" if approved else ""),
                                    id=f"toggle_{entry_id}",
                                )
                                yield _FileEntry(
                                    file_path=file_key,
                                    display_label=(f"{status_badge} {display_name}"),
                                    classes="review-file-entry",
                                    id=f"entry_{entry_id}",
                                )

            # ---- Right panel: Diff viewer ----
            with Vertical(id="review_diff_panel", classes="review-diff-panel"):
                yield Static(
                    self._make_diff_header_text(),
                    id="diff_panel_header",
                    classes="review-diff-header",
                    markup=True,
                )
                with VerticalScroll(id="diff_scroll"):
                    for section_id, markup in self._render_diff_sections(self._selected_file):
                        yield Static(
                            markup,
                            id=section_id,
                            classes="review-diff-content",
                            markup=True,
                        )

        # Footer: optional rework input (inline) + action buttons on one row.
        # Edit [e] and Cancel [esc] omitted — available via keyboard shortcuts
        # shown in the instruction line above.
        if self._show_footer:
            from textual.containers import Horizontal as _Horizontal

            with _Horizontal(classes="modal-footer"):
                if self._show_rework:
                    yield Input(
                        placeholder="Describe changes for rework/quick fix...",
                        id=self.REWORK_FEEDBACK_INPUT_ID,
                        classes="rework-feedback-input-inline",
                    )
                    yield from self.compose_rework_buttons(
                        continue_label="Rework",
                        quick_edit_label="Quick Fix",
                    )
                yield Button("Apply Selected", variant="primary", id="approve_selected_btn")
                yield Button("Apply All", variant="default", id="approve_all_btn")
                yield Button("Reject", variant="error", id="reject_all_btn")

    # =========================================================================
    # Diff parsing and rendering
    # =========================================================================

    def _parse_per_file_diffs(self, combined_diff: str) -> Dict[str, str]:
        """Parse a combined diff string into per-file diff sections."""
        if not combined_diff or not combined_diff.strip():
            return {}

        result: Dict[str, str] = {}
        sections = re.split(r"(?=^diff --git )", combined_diff, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section.startswith("diff --git"):
                continue

            match = re.match(r"diff --git a/(.*?) b/(.*?)$", section, re.MULTILINE)
            if match:
                file_a = match.group(1)
                file_b = match.group(2)
                result[file_b] = section
                if file_a != file_b:
                    result[file_a] = section

        return result

    def _find_file_diff(
        self,
        file_path: str,
        parsed_diffs: Dict[str, str],
    ) -> Optional[str]:
        """Find a file's diff from parsed diffs, trying various path forms."""
        if file_path in parsed_diffs:
            return parsed_diffs[file_path]

        target_name = Path(file_path).name
        for diff_path, diff_text in parsed_diffs.items():
            if Path(diff_path).name == target_name:
                return diff_text

        for diff_path, diff_text in parsed_diffs.items():
            if diff_path.endswith(file_path) or file_path.endswith(diff_path):
                return diff_text

        return None

    @staticmethod
    def _parse_hunks(file_diff: str) -> List[Dict[str, Any]]:
        """Parse unified diff hunks for a single file."""
        if not file_diff:
            return []

        hunks: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for line in file_diff.splitlines(keepends=True):
            if line.startswith("@@"):
                if current is not None:
                    hunks.append(current)
                current = {
                    "header": line.rstrip("\n"),
                    "lines": [],
                }
                continue

            if current is None:
                continue

            if line.startswith("\\ No newline at end of file"):
                continue

            if line[:1] in {" ", "+", "-"}:
                current["lines"].append(line)

        if current is not None:
            hunks.append(current)

        return hunks

    def _make_placeholder_diff(self, file_path: str, status: str) -> str:
        """Create a placeholder diff text when no actual diff is available."""
        status_labels = {
            "?": "New untracked file",
            "A": "New file added",
            "+": "New file added",
            "M": "Modified file",
            "D": "Deleted file",
            "-": "Deleted file",
            "R": "Renamed file",
        }
        label = status_labels.get(status.upper(), f"Changed ({status})")
        return f"--- {file_path}\n+++ {file_path}\n\n  ({label} - no diff content available)"

    @staticmethod
    def _parse_hunk_start_lines(header: str) -> tuple:
        """Extract old and new start line numbers from a @@ hunk header."""
        match = re.match(r"@@\s+-(\d+)", header)
        old_start = int(match.group(1)) if match else 1
        match2 = re.match(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)", header)
        new_start = int(match2.group(1)) if match2 else 1
        return old_start, new_start

    def _render_diff_markup(self, file_path: Optional[str]) -> str:
        """Render a file's diff as Rich-markup-formatted text."""
        if not file_path:
            return "[dim]Select a file to view its diff[/]"

        raw_diff = self._per_file_diffs.get(file_path, "")
        if not raw_diff:
            return "[dim]No diff available for this file[/]"

        lines = raw_diff.split("\n")
        rendered: List[str] = []
        hunk_index = -1
        selected_hunk = self._selected_hunk_index_by_file.get(file_path, 0)
        hunk_approvals = self._hunk_approvals.get(file_path, {})
        current_hunk_approved = True
        old_line = 0
        new_line = 0

        for line in lines:
            escaped = self._escape_markup(line)

            if line.startswith("diff --git") or line.startswith("index "):
                rendered.append(f"[dim]{escaped}[/]")
            elif line.startswith("--- ") or line.startswith("+++ "):
                rendered.append(f"[bold]{escaped}[/]")
            elif line.startswith("@@"):
                hunk_index += 1
                old_line, new_line = self._parse_hunk_start_lines(line)
                current_hunk_approved = hunk_approvals.get(hunk_index, True)
                marker = "\u2713" if current_hunk_approved else "\u25cb"
                header_text = f"[{marker}] {escaped}"
                if hunk_index == selected_hunk:
                    rendered.append(f"[bold cyan reverse]{header_text}[/]")
                elif current_hunk_approved:
                    rendered.append(f"[bold cyan]{header_text}[/]")
                else:
                    rendered.append(f"[dim]{header_text}[/]")
            elif line.startswith("+"):
                gutter = f"[dim]{'':>4s} {new_line:>4d} [/]"
                new_line += 1
                if current_hunk_approved:
                    rendered.append(f"{gutter}[#56d364 on #0d2818]{escaped}[/]")
                else:
                    rendered.append(f"{gutter}[dim]{escaped}[/]")
            elif line.startswith("-"):
                gutter = f"[dim]{old_line:>4d} {'':>4s} [/]"
                old_line += 1
                if current_hunk_approved:
                    rendered.append(f"{gutter}[#f85149 on #2d1010]{escaped}[/]")
                else:
                    rendered.append(f"{gutter}[dim]{escaped}[/]")
            elif line[:1] == " ":
                gutter = f"[dim]{old_line:>4d} {new_line:>4d} [/]"
                old_line += 1
                new_line += 1
                rendered.append(f"{gutter}[dim]{escaped}[/]")
            else:
                rendered.append(f"[dim]{escaped}[/]")

        return "\n".join(rendered)

    def _render_diff_sections(self, file_path: Optional[str]) -> List[tuple]:
        """Render a file's diff as a list of (section_id, markup) tuples."""
        if not file_path:
            return [("no_file", "[dim]Select a file to view its diff[/]")]

        raw_diff = self._per_file_diffs.get(file_path, "")
        if not raw_diff:
            return [("no_diff", "[dim]No diff available for this file[/]")]

        file_hash = sha1(file_path.encode("utf-8")).hexdigest()[:8]
        lines = raw_diff.split("\n")
        selected_hunk = self._selected_hunk_index_by_file.get(file_path, 0)
        hunk_approvals = self._hunk_approvals.get(file_path, {})

        meta_lines: List[str] = []
        hunk_sections: List[tuple] = []
        current_hunk_lines: List[str] = []
        hunk_index = -1
        current_hunk_approved = True
        old_line = 0
        new_line = 0

        for line in lines:
            escaped = self._escape_markup(line)

            if line.startswith("diff --git") or line.startswith("index "):
                if hunk_index == -1:
                    meta_lines.append(f"[dim]{escaped}[/]")
                else:
                    current_hunk_lines.append(f"[dim]{escaped}[/]")
            elif line.startswith("--- ") or line.startswith("+++ "):
                if hunk_index == -1:
                    meta_lines.append(f"[bold]{escaped}[/]")
                else:
                    current_hunk_lines.append(f"[bold]{escaped}[/]")
            elif line.startswith("@@"):
                if hunk_index >= 0 and current_hunk_lines:
                    section_id = f"hunk_{file_hash}_{hunk_index}"
                    hunk_sections.append((section_id, "\n".join(current_hunk_lines)))
                    current_hunk_lines = []

                hunk_index += 1
                old_line, new_line = self._parse_hunk_start_lines(line)
                current_hunk_approved = hunk_approvals.get(hunk_index, True)
                marker = "\u2713" if current_hunk_approved else "\u25cb"
                header_text = f"[{marker}] {escaped}"
                if hunk_index == selected_hunk:
                    current_hunk_lines.append(f"[bold cyan reverse]{header_text}[/]")
                elif current_hunk_approved:
                    current_hunk_lines.append(f"[bold cyan]{header_text}[/]")
                else:
                    current_hunk_lines.append(f"[dim]{header_text}[/]")
            elif line.startswith("+"):
                gutter = f"[dim]{'':>4s} {new_line:>4d} [/]"
                new_line += 1
                if current_hunk_approved:
                    current_hunk_lines.append(f"{gutter}[#56d364 on #0d2818]{escaped}[/]")
                else:
                    current_hunk_lines.append(f"{gutter}[dim]{escaped}[/]")
            elif line.startswith("-"):
                gutter = f"[dim]{old_line:>4d} {'':>4s} [/]"
                old_line += 1
                if current_hunk_approved:
                    current_hunk_lines.append(f"{gutter}[#f85149 on #2d1010]{escaped}[/]")
                else:
                    current_hunk_lines.append(f"{gutter}[dim]{escaped}[/]")
            elif line[:1] == " ":
                gutter = f"[dim]{old_line:>4d} {new_line:>4d} [/]"
                old_line += 1
                new_line += 1
                if hunk_index >= 0:
                    current_hunk_lines.append(f"{gutter}[dim]{escaped}[/]")
                else:
                    meta_lines.append(f"{gutter}[dim]{escaped}[/]")
            else:
                if hunk_index >= 0:
                    current_hunk_lines.append(f"[dim]{escaped}[/]")
                else:
                    meta_lines.append(f"[dim]{escaped}[/]")

        if hunk_index >= 0 and current_hunk_lines:
            section_id = f"hunk_{file_hash}_{hunk_index}"
            hunk_sections.append((section_id, "\n".join(current_hunk_lines)))

        result: List[tuple] = []
        if meta_lines:
            result.append((f"meta_{file_hash}", "\n".join(meta_lines)))
        result.extend(hunk_sections)

        return result if result else [("empty", "[dim]No content[/]")]

    def _get_scroll_target_id(self, file_path: Optional[str]) -> Optional[str]:
        """Get the widget ID for the currently selected hunk in a file."""
        if not file_path:
            return None
        file_hash = sha1(file_path.encode("utf-8")).hexdigest()[:8]
        hunk_index = self._selected_hunk_index_by_file.get(file_path, 0)
        return f"hunk_{file_hash}_{hunk_index}"

    @staticmethod
    def _escape_markup(text: str) -> str:
        """Escape Rich markup special characters in text."""
        return text.replace("[", "\\[").replace("]", "\\]")

    def _make_diff_header_text(self) -> str:
        """Build the diff panel header text showing the selected file."""
        if self._selected_file:
            file_path = self._file_key_to_path.get(self._selected_file, self._selected_file)
            context_path = self._file_key_to_context.get(self._selected_file, "")
            hunk_count = len(self._hunks_by_file.get(self._selected_file, []))
            selected_hunk = self._selected_hunk_index_by_file.get(self._selected_file, 0)
            selected_hunk_label = ""
            if hunk_count:
                selected_hunk_label = f" [dim]\u2022 hunk {selected_hunk + 1}/{hunk_count}[/]"
            if len(self.changes) > 1:
                context_name = Path(context_path).name if context_path else "context"
                return f"[bold]Diff:[/] " f"[italic]{self._escape_markup(context_name)}:{self._escape_markup(file_path)}[/]" f"{selected_hunk_label}"
            return f"[bold]Diff:[/] [italic]{self._escape_markup(file_path)}[/]" f"{selected_hunk_label}"
        return "[bold]Diff Preview[/]"

    def _build_summary_markup(
        self,
        parts: List[str],
        total_contexts: int,
        total_files: int,
    ) -> str:
        """Build summary line with change totals + current selection count."""
        summary = ", ".join(parts) if parts else f"{total_files} file(s) changed"
        if total_contexts > 1:
            summary += f" across {total_contexts} contexts"

        selected_count = sum(1 for approved in self.file_approvals.values() if approved)
        summary += f" [dim]\u2022[/] [bold]{selected_count}/{total_files} selected[/]"
        return summary

    def _update_summary(self) -> None:
        """Refresh summary line after approval changes."""
        total_files = len(self._all_file_paths)
        if not total_files:
            return

        total_contexts = len(self.changes)
        added = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() in ("A", "?", "+"))
        modified = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() == "M")
        deleted = sum(1 for ctx in self.changes for c in ctx.get("changes", []) if c.get("status", "").upper() in ("D", "-"))

        parts = []
        if modified:
            parts.append(f"[yellow]{modified} modified[/]")
        if added:
            parts.append(f"[bright_green]{added} added[/]")
        if deleted:
            parts.append(f"[bright_red]{deleted} deleted[/]")

        try:
            summary = self.query_one("#review_summary", Static)
            summary.update(
                self._build_summary_markup(
                    parts=parts,
                    total_contexts=total_contexts,
                    total_files=total_files,
                ),
            )
        except Exception:
            pass

    # =========================================================================
    # Status badges
    # =========================================================================

    @staticmethod
    def _approval_indicator(approved: bool) -> str:
        """Render a compact approval indicator."""
        if approved:
            return "[bold bright_green]\u2713[/]"  # ✓
        return "[dim]\u25cb[/]"  # ○

    def _get_status_badge(self, status: str) -> str:
        """Get a colored status badge for the file change type."""
        badges = {
            "M": "[bold yellow]M[/]",
            "A": "[bold bright_green]A[/]",
            "+": "[bold bright_green]+[/]",
            "D": "[bold bright_red]D[/]",
            "-": "[bold bright_red]-[/]",
            "?": "[bold cyan]?[/]",
            "R": "[bold bright_blue]R[/]",
        }
        return badges.get(status.upper(), f"[dim]{status}[/]")

    # =========================================================================
    # Checkbox ID mapping
    # =========================================================================

    @classmethod
    def _make_file_key(cls, context_path: str, file_path: str) -> str:
        """Create a unique key for a file scoped to its context path."""
        return f"{context_path}{cls.FILE_KEY_SEPARATOR}{file_path}"

    def _make_checkbox_id(self, file_path: str) -> str:
        """Create a valid widget ID from a file path."""
        digest = sha1(file_path.encode("utf-8")).hexdigest()[:12]
        return f"file_cb_{digest}"

    def _path_from_checkbox_id(self, checkbox_id: str) -> Optional[str]:
        """Look up the original file path from a checkbox ID."""
        return self._checkbox_to_path.get(checkbox_id)

    # =========================================================================
    # Event handlers
    # =========================================================================

    def on_mount(self) -> None:
        """After mount, ensure the first file's row is visually selected."""
        if self._selected_file:
            self._highlight_selected_row(self._selected_file)
        self._update_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "approve_selected_btn":
            self._approve_selected()
        elif button_id == "approve_all_btn":
            self._approve_all()
        elif button_id == "edit_file_btn":
            self.action_edit_file()
        elif button_id == "reject_all_btn":
            self._reject_all()
        elif button_id == "cancel_btn":
            self._cancel()
        elif button_id == "select_all_btn":
            self._set_all_approvals(True)
        elif button_id == "deselect_all_btn":
            self._set_all_approvals(False)
        elif button_id == self.REWORK_CONTINUE_BTN_ID:
            self._rework()
        elif button_id == self.REWORK_QUICK_EDIT_BTN_ID:
            self._quick_fix()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Keep rework feedback state in sync."""
        if event.input.id == self.REWORK_FEEDBACK_INPUT_ID:
            self._rework_feedback_value = event.value
            self._sync_rework_button_states()

    def on__file_entry_file_selected(self, event: _FileEntry.FileSelected) -> None:
        """Handle file entry click — select file and show its diff."""
        self._select_file(event.file_path)

    def on__approval_toggle_toggled(self, event: _ApprovalToggle.Toggled) -> None:
        """Handle approval toggle click — flip approval and update indicator."""
        self._toggle_file_approval(event.file_path)
        self._select_file(event.file_path)

    # =========================================================================
    # Selection and diff update
    # =========================================================================

    def _select_file(self, file_path: str) -> None:
        """Select a file and update the diff panel to show its diff."""
        if file_path == self._selected_file:
            return

        self._selected_file = file_path
        self._update_diff_panel()
        self._highlight_selected_row(file_path)

    def _update_diff_panel(self) -> None:
        """Refresh the diff panel content for the currently selected file."""
        try:
            diff_header = self.query_one("#diff_panel_header", Static)
            diff_header.update(self._make_diff_header_text())

            diff_scroll = self.query_one("#diff_scroll", VerticalScroll)
            for child in list(diff_scroll.children):
                child.remove()
            for section_id, markup in self._render_diff_sections(self._selected_file):
                diff_scroll.mount(
                    Static(markup, id=section_id, classes="review-diff-content", markup=True),
                )

            diff_scroll.scroll_home(animate=False)
        except Exception:
            pass

    def _highlight_selected_row(self, file_path: str) -> None:
        """Update the visual highlight on the selected file row."""
        try:
            for row in self.query(".review-file-row"):
                row.remove_class("review-file-selected")

            entry_id = self._file_key_to_checkbox.get(file_path, self._make_checkbox_id(file_path))
            try:
                target = self.query_one(f"#row_{entry_id}")
                target.add_class("review-file-selected")
            except Exception:
                pass
        except Exception:
            pass

    def _toggle_file_approval(self, file_path: str) -> None:
        """Toggle a single file's approval state and update its indicator."""
        current = self.file_approvals.get(file_path, True)
        new_value = not current
        self.file_approvals[file_path] = new_value
        hunk_approvals = self._hunk_approvals.get(file_path)
        if hunk_approvals:
            for hunk_idx in list(hunk_approvals.keys()):
                hunk_approvals[hunk_idx] = new_value
        self._refresh_toggle(file_path)
        self._update_diff_panel()
        self._update_summary()

    def _set_all_approvals(self, value: bool) -> None:
        """Set all files to approved or unapproved."""
        for file_path in self._all_file_paths:
            self.file_approvals[file_path] = value
            hunk_approvals = self._hunk_approvals.get(file_path)
            if hunk_approvals:
                for hunk_idx in list(hunk_approvals.keys()):
                    hunk_approvals[hunk_idx] = value
            self._refresh_toggle(file_path)
        self._update_diff_panel()
        self._update_summary()

    def _move_selection(self, step: int) -> None:
        """Move selected file up/down in the file list."""
        if not self._all_file_paths:
            return

        if self._selected_file not in self._all_file_paths:
            self._select_file(self._all_file_paths[0])
            return

        current_index = self._all_file_paths.index(self._selected_file)
        next_index = (current_index + step) % len(self._all_file_paths)
        self._select_file(self._all_file_paths[next_index])

    def _move_selected_hunk(self, step: int) -> None:
        """Move selected hunk within the currently selected file."""
        if not self._selected_file:
            return
        hunks = self._hunks_by_file.get(self._selected_file, [])
        if not hunks:
            return

        current = self._selected_hunk_index_by_file.get(self._selected_file, 0)
        next_index = (current + step) % len(hunks)
        self._selected_hunk_index_by_file[self._selected_file] = next_index
        self._update_diff_panel()
        self._scroll_to_selected_hunk()

    def _scroll_to_selected_hunk(self) -> None:
        """Scroll the diff panel so the selected hunk is visible."""
        target_id = self._get_scroll_target_id(self._selected_file)
        if not target_id:
            return
        try:
            target = self.query_one(f"#{target_id}", Static)
            target.scroll_visible(animate=True, top=True)
        except Exception:
            pass

    def _toggle_selected_hunk(self) -> None:
        """Toggle approval for the selected hunk in the current file."""
        if not self._selected_file:
            return
        hunks = self._hunks_by_file.get(self._selected_file, [])
        if not hunks:
            self._toggle_file_approval(self._selected_file)
            return

        selected_hunk = self._selected_hunk_index_by_file.get(self._selected_file, 0)
        approvals = self._hunk_approvals.get(self._selected_file, {})
        current = approvals.get(selected_hunk, True)
        approvals[selected_hunk] = not current

        self.file_approvals[self._selected_file] = any(approvals.values())
        self._refresh_toggle(self._selected_file)
        self._update_diff_panel()
        self._update_summary()

    def _refresh_toggle(self, file_path: str) -> None:
        """Update the approval toggle indicator for a file."""
        entry_id = self._file_key_to_checkbox.get(file_path, self._make_checkbox_id(file_path))
        approved = self.file_approvals.get(file_path, True)
        try:
            toggle = self.query_one(f"#toggle_{entry_id}", _ApprovalToggle)
            toggle.update("\u2713" if approved else "\u25cb")  # ✓ or ○
            if approved:
                toggle.add_class("review-approved")
            else:
                toggle.remove_class("review-approved")
        except Exception:
            pass

    # =========================================================================
    # Build ReviewResult helpers
    # =========================================================================

    def get_review_result(self, action: str = "approve") -> ReviewResult:
        """Build a ReviewResult from current panel state.

        Args:
            action: One of "approve", "reject", "cancel", "rework", "quick_fix"
        """
        if action in ("reject", "cancel"):
            mode = "rejected" if action == "reject" else "cancelled"
            return ReviewResult(
                approved=False,
                metadata={"selection_mode": mode},
                action=action,
            )

        if action in ("rework", "quick_fix"):
            feedback = self._rework_feedback_text()
            return ReviewResult(
                approved=False,
                metadata={"selection_mode": action},
                action=action,
                feedback=feedback or "",
            )

        # "approve" — build per-context file/hunk selection
        approved_files = [path for path, approved in self.file_approvals.items() if approved]
        approved_files_by_context: Dict[str, List[str]] = {}
        approved_hunks_by_context: Dict[str, Dict[str, List[int]]] = {}
        for file_key in approved_files:
            context_path = self._file_key_to_context.get(file_key)
            file_path = self._file_key_to_path.get(file_key)
            if not context_path or not file_path:
                continue
            approved_files_by_context.setdefault(context_path, []).append(file_path)
            hunk_approvals = self._hunk_approvals.get(file_key, {})
            if hunk_approvals:
                approved_hunks = [idx for idx, is_approved in sorted(hunk_approvals.items()) if is_approved]
                approved_hunks_by_context.setdefault(context_path, {})[file_path] = approved_hunks

        return ReviewResult(
            approved=True,
            approved_files=approved_files,
            metadata={
                "selection_mode": "selected",
                "approved_files_by_context": approved_files_by_context,
                "approved_hunks_by_context": approved_hunks_by_context,
            },
            action="approve",
        )

    # =========================================================================
    # Approval / rejection actions (emit ActionRequested)
    # =========================================================================

    def _approve_selected(self) -> None:
        """Approve only selected (checked) files and emit action."""
        result = self.get_review_result("approve")
        self.post_message(self.ActionRequested("approve_selected", result))

    def _approve_all(self) -> None:
        """Approve all files and emit action."""
        result = ReviewResult(
            approved=True,
            approved_files=None,
            metadata={"selection_mode": "all"},
            action="approve",
        )
        self.post_message(self.ActionRequested("approve_all", result))

    def _reject_all(self) -> None:
        """Reject all changes and emit action."""
        result = self.get_review_result("reject")
        self.post_message(self.ActionRequested("reject", result))

    def _cancel(self) -> None:
        """Cancel the review and emit action."""
        result = self.get_review_result("cancel")
        self.post_message(self.ActionRequested("cancel", result))

    def _rework(self) -> None:
        """Request multi-agent rework and emit action."""
        self._snapshot_rework_input()
        feedback = self._rework_feedback_text()
        if not feedback:
            return
        result = self.get_review_result("rework")
        self.post_message(self.ActionRequested("rework", result))

    def _quick_fix(self) -> None:
        """Request single-agent quick fix and emit action."""
        self._snapshot_rework_input()
        feedback = self._rework_feedback_text()
        if not feedback:
            return
        result = self.get_review_result("quick_fix")
        self.post_message(self.ActionRequested("quick_fix", result))

    # =========================================================================
    # Edit file support
    # =========================================================================

    def action_edit_file(self) -> None:
        """Open the selected file in the FileEditorModal for editing."""
        if not self._selected_file:
            return

        file_path = self._file_key_to_path.get(self._selected_file, "")
        context_path = self._file_key_to_context.get(self._selected_file, "")
        isolated_path = self._context_to_isolated.get(context_path, "")

        if not isolated_path or not file_path:
            return

        full_path = Path(isolated_path) / file_path
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            try:
                self.app.notify(f"Cannot open {file_path}: {e}", severity="error", timeout=4)
            except Exception:
                pass
            return

        selected_file_key = self._selected_file

        def _on_editor_dismiss(updated_content):
            if updated_content is None:
                return
            try:
                full_path.write_text(updated_content, encoding="utf-8")
            except Exception as e:
                try:
                    self.app.notify(f"Could not save {file_path}: {e}", severity="error", timeout=4)
                except Exception:
                    pass
                return
            self._refresh_file_diff(selected_file_key, context_path, isolated_path, file_path)

        from .review_modal import FileEditorModal

        self.app.push_screen(
            FileEditorModal(file_path=file_path, initial_content=content),
            _on_editor_dismiss,
        )

    def _refresh_file_diff(
        self,
        file_key: str,
        context_path: str,
        isolated_path: str,
        file_path: str,
    ) -> None:
        """Re-run git diff for a single file and refresh the diff panel."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "diff", "--", file_path],
                cwd=isolated_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            new_diff = result.stdout.strip()
        except Exception:
            return

        if new_diff:
            self._per_file_diffs[file_key] = new_diff
        else:
            self._per_file_diffs[file_key] = self._make_placeholder_diff(file_path, "M")

        hunks = self._parse_hunks(self._per_file_diffs.get(file_key, ""))
        self._hunks_by_file[file_key] = hunks
        self._hunk_approvals[file_key] = {idx: True for idx in range(len(hunks))}
        self._selected_hunk_index_by_file[file_key] = 0

        self._update_diff_panel()
        self._update_summary()


__all__ = [
    "ReviewChangesPanel",
]
