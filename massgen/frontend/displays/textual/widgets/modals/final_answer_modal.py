# -*- coding: utf-8 -*-
"""
Tabbed Final Answer modal combining the answer presentation with optional
Review Changes tab.

Opens after final presentation streaming completes. Uses Textual's
TabbedContent with an "Answer" tab (trophy header, vote info, markdown
answer, post-eval) and a conditional "Review Changes" tab (diff review
panel reused from ReviewChangesPanel).
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from textual.app import ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.widgets import Button, Label, Markdown, Static, TabbedContent, TabPane

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from massgen.filesystem_manager import ReviewResult

from ..modal_base import BaseModal
from .review_changes_panel import ReviewChangesPanel


@dataclass
class FinalAnswerModalData:
    """Data passed to FinalAnswerModal for rendering."""

    answer_content: str
    vote_results: Dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    model_name: str = ""
    post_eval_content: Optional[str] = None
    post_eval_status: str = "none"  # "none" | "verified"
    changes: Optional[List[Dict[str, Any]]] = None  # None = no Review tab
    context_paths: Optional[Dict] = None
    prior_action: Optional[str] = None  # "approved" | "rejected" when re-opened
    workspace_path: Optional[str] = None  # Agent workspace dir (no-git mode)


class AnswerTabContent(Vertical):
    """Answer tab: markdown answer, post-eval, bottom bar with files + buttons."""

    DEFAULT_CSS = ""

    def __init__(
        self,
        data: FinalAnswerModalData,
        has_changes: bool = False,
        has_workspace: bool = False,
        prior_action: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._data = data
        self._has_changes = has_changes
        self._has_workspace = has_workspace
        self._prior_action = prior_action

    def compose(self) -> ComposeResult:
        # Main answer content
        with VerticalScroll(id="answer_content_scroll"):
            if self._data.answer_content:
                yield Markdown(self._data.answer_content, id="answer_markdown")
            else:
                yield Static("[dim]No answer content available[/]", markup=True)

        # Post-evaluation section (if present)
        if self._data.post_eval_content:
            status_icon = "\u2713" if self._data.post_eval_status == "verified" else "\u2022"
            status_label = "Verified" if self._data.post_eval_status == "verified" else "Post-Evaluation"
            with Vertical(id="answer_post_eval", classes="answer-post-eval"):
                yield Label(
                    f"{status_icon} {status_label}",
                    id="post_eval_label",
                    classes="answer-post-eval-label",
                )
                with VerticalScroll(id="post_eval_scroll", classes="answer-post-eval-scroll"):
                    yield Markdown(self._data.post_eval_content, id="post_eval_markdown")

        # Bottom bar: context paths (left) + action buttons (right)
        with Horizontal(id="answer_bottom_bar", classes="answer-bottom-bar"):
            # Context paths (if present)
            context_paths = self._data.context_paths or {}
            new_paths = context_paths.get("new", [])
            modified_paths = context_paths.get("modified", [])
            if new_paths or modified_paths:
                total = len(new_paths) + len(modified_paths)
                with Vertical(id="answer_context_paths", classes="answer-context-paths"):
                    yield Label(f"Files Written ({total})", id="answer_paths_header")
                    with VerticalScroll(id="answer_paths_scroll", classes="answer-paths-scroll"):
                        for path in new_paths[:20]:
                            yield Label(f"  + {path}", classes="context-path-new")
                        for path in modified_paths[:20]:
                            yield Label(f"  M {path}", classes="context-path-modified")
                        remaining = total - min(len(new_paths), 20) - min(len(modified_paths), 20)
                        if remaining > 0:
                            yield Label(
                                f"  ... and {remaining} more",
                                classes="context-path-overflow",
                            )

            # Action buttons (right-aligned)
            with Horizontal(classes="answer-action-buttons"):
                yield Button(
                    "Copy",
                    variant="default",
                    id="copy_answer_btn",
                    classes="answer-action-btn",
                )
                if self._prior_action:
                    yield Button(
                        "Back to Timeline",
                        variant="primary",
                        id="back_to_timeline_btn",
                        classes="answer-action-btn",
                    )
                elif self._has_changes:
                    yield Button(
                        "Review Changes",
                        variant="default",
                        id="review_changes_btn",
                        classes="answer-action-btn",
                    )
                    yield Button(
                        "Approve All Changes",
                        variant="success",
                        id="approve_all_answer_btn",
                        classes="answer-action-btn",
                    )
                elif self._has_workspace:
                    yield Button(
                        "Browse Workspace",
                        variant="default",
                        id="browse_workspace_btn",
                        classes="answer-action-btn",
                    )
                    yield Button(
                        "Close",
                        variant="primary",
                        id="close_answer_btn",
                        classes="answer-action-btn",
                    )
                else:
                    yield Button(
                        "Close",
                        variant="primary",
                        id="close_answer_btn",
                        classes="answer-action-btn",
                    )

    def _build_winner_summary(self) -> str:
        """Build the winner summary line with vote count."""
        if not self._data.vote_results:
            return ""

        vote_counts = self._data.vote_results.get("vote_counts", {})
        winner = self._data.vote_results.get("winner", "")
        is_tie = self._data.vote_results.get("is_tie", False)

        winner_label = winner or self._data.agent_id
        if not winner_label:
            return ""

        winner_votes = vote_counts.get(winner_label)
        votes_suffix = ""
        if isinstance(winner_votes, int):
            votes_suffix = f" ({winner_votes} vote{'s' if winner_votes != 1 else ''})"

        tie_suffix = " - tie-breaker" if is_tie else ""
        return f"Winner: {winner_label}{votes_suffix}{tie_suffix}"

    def _build_vote_summary(self) -> str:
        """Build the vote summary line."""
        if not self._data.vote_results:
            return ""

        vote_counts = self._data.vote_results.get("vote_counts", {})
        if not vote_counts:
            return ""

        counts_str = " | ".join(f"{aid} ({count})" for aid, count in vote_counts.items())
        return f"Votes: {counts_str}"


class WorkspaceTabContent(Vertical):
    """Workspace browser tab: file tree + preview pane for no-git mode."""

    _MAX_SCAN_FILES = 400
    _MAX_SCAN_DEPTH = 6

    def __init__(self, workspace_path: str, **kwargs):
        super().__init__(**kwargs)
        self._workspace_path = workspace_path
        self._current_files: List[Dict[str, Any]] = []
        self._tree_lines: List[tuple] = []
        self._expanded_dirs: Set[str] = set()
        self._dir_file_counts: Dict[str, int] = {}
        self._load_counter: int = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace_tab_split"):
            with Container(id="workspace_tab_file_list_container"):
                yield Label("[bold]Files[/]", id="workspace_tab_file_list_header", markup=True)
                yield VerticalScroll(id="workspace_tab_file_list")
            with Container(id="workspace_tab_preview_container"):
                yield Label("[bold]Preview[/]", id="workspace_tab_preview_header", markup=True)
                yield VerticalScroll(id="workspace_tab_preview")
        with Horizontal(id="workspace_tab_footer"):
            yield Button("Open in Filesystem", id="open_workspace_filesystem_btn")

    def on_mount(self) -> None:
        self._refresh_file_list()

    # ------------------------------------------------------------------
    # File scanning (reuses logic from browser_modals.WorkspaceBrowserModal)
    # ------------------------------------------------------------------

    def _scan_files(self) -> tuple:
        from .browser_modals import _should_skip_dir

        files: List[Dict[str, Any]] = []
        truncated = False
        workspace = self._workspace_path
        if not workspace or not os.path.isdir(workspace):
            return files, False

        for root, dirs, filenames in os.walk(workspace, topdown=True):
            rel_root = os.path.relpath(root, workspace)
            depth = 0 if rel_root == "." else len(rel_root.split(os.sep))
            dirs[:] = [d for d in dirs if not d.startswith(".") and not _should_skip_dir(d) and depth < self._MAX_SCAN_DEPTH]
            if depth >= self._MAX_SCAN_DEPTH:
                filenames = []
            for fname in filenames:
                if fname.startswith("."):
                    continue
                if len(files) >= self._MAX_SCAN_FILES:
                    truncated = True
                    break
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, workspace)
                try:
                    stat = os.stat(full_path)
                    files.append(
                        {
                            "name": fname,
                            "rel_path": rel_path,
                            "full_path": full_path,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        },
                    )
                except OSError:
                    pass
            if truncated:
                break
        return sorted(files, key=lambda f: f["rel_path"]), truncated

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size // 1024}KB"
        else:
            return f"{size // (1024 * 1024)}MB"

    def _build_file_tree(self, files: List[Dict[str, Any]]) -> List[tuple]:
        dir_files: Dict[str, List[tuple]] = {}
        root_files: List[tuple] = []

        for idx, f in enumerate(files):
            rel_path = f["rel_path"]
            size_str = self._format_size(f["size"])
            if "/" in rel_path or "\\" in rel_path:
                parts = rel_path.replace("\\", "/").split("/")
                dir_name = parts[0]
                file_name = "/".join(parts[1:])
                if dir_name not in dir_files:
                    dir_files[dir_name] = []
                dir_files[dir_name].append((file_name, size_str, idx))
            else:
                root_files.append((rel_path, size_str, idx))

        self._dir_file_counts = {d: len(f) for d, f in dir_files.items()}
        result = []

        sorted_dirs = sorted(dir_files.keys())
        for i, dir_name in enumerate(sorted_dirs):
            is_last_dir = (i == len(sorted_dirs) - 1) and not root_files
            dir_connector = "\u2514\u2500\u2500 " if is_last_dir else "\u251c\u2500\u2500 "
            dir_file_list = dir_files[dir_name]
            file_count = len(dir_file_list)

            is_expanded = dir_name in self._expanded_dirs
            if file_count <= 3 and dir_name not in self._expanded_dirs:
                is_expanded = True
                self._expanded_dirs.add(dir_name)

            arrow = "\u25bc" if is_expanded else "\u25b6"
            count_hint = f" ({file_count})" if not is_expanded else ""
            result.append(
                (
                    f"[bold yellow]{dir_connector}{arrow} {dir_name}/{count_hint}[/]",
                    f"dir:{dir_name}",
                ),
            )

            if is_expanded:
                for j, (file_name, size_str, file_idx) in enumerate(dir_file_list):
                    is_last_file = j == len(dir_file_list) - 1
                    prefix = "    " if is_last_dir else "\u2502   "
                    file_connector = "\u2514\u2500\u2500 " if is_last_file else "\u251c\u2500\u2500 "
                    result.append(
                        (
                            f"[white]{prefix}{file_connector}[/][bold cyan]{file_name}[/] [italic]{size_str}[/]",
                            file_idx,
                        ),
                    )

        for i, (file_name, size_str, file_idx) in enumerate(root_files):
            is_last = i == len(root_files) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            result.append((f"[white]{connector}[/][bold cyan]{file_name}[/] [italic]{size_str}[/]", file_idx))

        return result

    def _preview_file(self, file_idx: int) -> None:
        from .browser_modals import render_file_preview

        try:
            preview = self.query_one("#workspace_tab_preview", VerticalScroll)
        except Exception:
            return
        preview.remove_children()

        if file_idx < 0 or file_idx >= len(self._current_files):
            preview.mount(Static("[italic]Select a file to preview[/]", markup=True))
            return

        f = self._current_files[file_idx]
        full_path = Path(f["full_path"])
        header = Static(
            f"[bold cyan]{f['rel_path']}[/]\n[white]{'─' * 40}[/]",
            markup=True,
        )
        preview.mount(header)

        renderable, is_rich = render_file_preview(full_path)
        if is_rich:
            preview.mount(Static(renderable))
        else:
            preview.mount(Static(str(renderable), markup=True))

    def _refresh_file_list(self) -> None:
        try:
            file_list = self.query_one("#workspace_tab_file_list", VerticalScroll)
        except Exception:
            return
        file_list.remove_children()
        self._load_counter += 1

        files, truncated = self._scan_files()
        self._current_files = files

        if not files:
            file_list.mount(Static("[italic]Workspace is empty[/]", markup=True))
            return

        self._tree_lines = self._build_file_tree(files)
        for idx, (display_text, _item_data) in enumerate(self._tree_lines):
            file_list.mount(
                Static(
                    display_text,
                    id=f"ws_tab_file_{self._load_counter}_{idx}",
                    classes="workspace-file-item",
                    markup=True,
                ),
            )

        if truncated:
            file_list.mount(
                Static(
                    f"[dim]... showing first {self._MAX_SCAN_FILES} files[/]",
                    markup=True,
                ),
            )

    def _toggle_directory(self, dir_name: str) -> None:
        if dir_name in self._expanded_dirs:
            self._expanded_dirs.remove(dir_name)
        else:
            self._expanded_dirs.add(dir_name)
        self._refresh_file_list()

    def on_click(self, event) -> None:
        if hasattr(event, "widget") and event.widget:
            widget_id = getattr(event.widget, "id", "")
            if widget_id and widget_id.startswith("ws_tab_file_"):
                try:
                    tree_idx = int(widget_id.split("_")[-1])
                    if self._tree_lines and 0 <= tree_idx < len(self._tree_lines):
                        item_data = self._tree_lines[tree_idx][1]
                        if isinstance(item_data, str) and item_data.startswith("dir:"):
                            self._toggle_directory(item_data[4:])
                            return
                        if item_data == -1:
                            return
                        self._preview_file(item_data)
                except (ValueError, IndexError):
                    pass

    def _open_in_filesystem(self) -> None:
        import platform
        import subprocess

        if not self._workspace_path or not os.path.isdir(self._workspace_path):
            try:
                self.app.notify("No workspace available", severity="warning", timeout=2)
            except Exception:
                pass
            return
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(self._workspace_path)])
            elif system == "Windows":
                subprocess.run(["explorer", str(self._workspace_path)])
            else:
                subprocess.run(["xdg-open", str(self._workspace_path)])
        except Exception as e:
            try:
                self.app.notify(f"Error opening workspace: {e}", severity="error", timeout=3)
            except Exception:
                pass


class FinalAnswerModal(BaseModal):
    """Tabbed modal showing Final Answer + optional Review Changes.

    The Answer tab displays the winning agent's answer with vote information.
    The Review Changes tab (only shown when changes exist) provides the full
    diff review UI from ReviewChangesPanel.

    Dismiss behavior:
    - Close/ESC when changes are pending (initial modal) -> blocked with notification
    - Close/ESC on answer-only or re-opened modal -> dismiss normally
    - Apply/Reject from Review tab -> standard ReviewResult
    """

    # All bindings use priority=True so they override app-level bindings
    # (prevents keys like 'h' from leaking to the TUI behind the modal).
    BINDINGS = [
        Binding("escape", "close_modal", "Close", priority=True),
        Binding("ctrl+c", "force_close", "Reject & Close", priority=True, show=False),
        Binding("1", "switch_answer_tab", "Answer", priority=True),
        Binding("2", "switch_review_tab", "Review", priority=True),
        # Review panel bindings (delegated to self._panel when present)
        Binding("space", "toggle_selected", "Toggle File", priority=True),
        Binding("enter", "approve_selected", "Approve Selected", priority=True),
        Binding("h", "toggle_selected_hunk", "Toggle Hunk", priority=True),
        Binding("[", "select_previous_hunk", "Prev Hunk", priority=True),
        Binding("]", "select_next_hunk", "Next Hunk", priority=True),
        Binding("up", "select_previous_file", "Prev File", priority=True),
        Binding("down", "select_next_file", "Next File", priority=True),
        Binding("e", "edit_file", "Edit", priority=True),
    ]

    # Keys with bindings — stopped in on_key to prevent app-level leaking
    _MODAL_KEYS = frozenset(
        {
            "escape",
            "ctrl+c",
            "space",
            "h",
            "e",
            "enter",
            "up",
            "down",
            "1",
            "2",
            "left_square_bracket",
            "right_square_bracket",
        },
    )

    def __init__(self, data: FinalAnswerModalData, **kwargs):
        super().__init__(**kwargs)
        self._data = data
        self._prior_action = data.prior_action  # None | "approved" | "rejected"
        self._ctrl_c_warned = False
        self._last_notify_time = 0.0
        self._panel: Optional[ReviewChangesPanel] = None
        if data.changes:
            self._panel = ReviewChangesPanel(
                changes=data.changes,
                show_footer=True,
                show_rework=not self._prior_action,
                show_all_keyboard_hints=False,
                id="final_review_panel",
            )
            if self._prior_action:
                self._panel.add_class("review-approved-dim")

    @property
    def _requires_decision(self) -> bool:
        """Whether this modal requires an explicit approve/reject decision.

        True only on the initial modal when there are pending changes
        and no prior action has been taken.
        """
        return bool(self._data.changes) and self._prior_action is None

    def _build_header_title(self) -> str:
        """Build a combined header title with winner/vote info inline."""
        parts = ["Final Answer"]

        # Use AnswerTabContent helpers to get winner/vote text
        tab = AnswerTabContent(data=self._data)
        winner_text = tab._build_winner_summary()
        vote_text = tab._build_vote_summary()

        if winner_text:
            parts.append(winner_text)
        if vote_text:
            parts.append(vote_text)

        return " \u2014 ".join(parts)

    def compose(self) -> ComposeResult:
        has_changes = bool(self._data.changes)
        has_workspace = bool(self._data.workspace_path) and not has_changes

        with Container(
            id="final_answer_modal_container",
            classes="modal-container modal-container-wide final-answer-modal",
        ):
            yield from self.make_header(self._build_header_title(), icon="\U0001f3c6")

            if has_changes:
                if self._prior_action:
                    review_tab_label = f"Review Changes ({self._prior_action}) [2]"
                else:
                    review_tab_label = "Review Changes [2]"
                with TabbedContent(id="final_answer_tabs", initial="answer_tab"):
                    with TabPane("Answer [1]", id="answer_tab"):
                        yield AnswerTabContent(
                            data=self._data,
                            has_changes=True,
                            prior_action=self._prior_action,
                            id="answer_content",
                        )
                    with TabPane(review_tab_label, id="review_tab"):
                        if self._prior_action:
                            banner_text = "Changes were rejected" if self._prior_action == "rejected" else "Changes already approved"
                            yield Label(
                                banner_text,
                                id="review_approved_banner",
                            )
                        if self._panel:
                            yield self._panel
            elif has_workspace:
                with TabbedContent(id="final_answer_tabs", initial="answer_tab"):
                    with TabPane("Answer [1]", id="answer_tab"):
                        yield AnswerTabContent(
                            data=self._data,
                            has_changes=False,
                            has_workspace=True,
                            prior_action=self._prior_action,
                            id="answer_content",
                        )
                    with TabPane("Workspace [2]", id="workspace_tab"):
                        yield WorkspaceTabContent(
                            workspace_path=self._data.workspace_path,
                            id="workspace_content",
                        )
            else:
                yield AnswerTabContent(
                    data=self._data,
                    has_changes=False,
                    prior_action=self._prior_action,
                    id="answer_content",
                )

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("close_answer_btn", "approve_all_answer_btn", "back_to_timeline_btn"):
            event.stop()
            self._close_with_approve_all()
        elif event.button.id == "copy_answer_btn":
            event.stop()
            self._copy_answer()
        elif event.button.id == "review_changes_btn":
            event.stop()
            event.prevent_default()
            self.call_later(self.action_switch_review_tab)
        elif event.button.id == "browse_workspace_btn":
            event.stop()
            event.prevent_default()
            self.call_later(self.action_switch_review_tab)
        elif event.button.id == "open_workspace_filesystem_btn":
            event.stop()
            try:
                ws = self.query_one("#workspace_content", WorkspaceTabContent)
                ws._open_in_filesystem()
            except Exception:
                pass
        elif event.button.id == "close_modal_button":
            # Handle X button explicitly and stop the event so BaseModal's
            # handler doesn't also fire (Textual dispatches to each MRO class).
            event.stop()
            self.dismiss()
        else:
            super().on_button_pressed(event)

    # ------------------------------------------------------------------
    # Panel action handler
    # ------------------------------------------------------------------

    def on_review_changes_panel_action_requested(
        self,
        event: ReviewChangesPanel.ActionRequested,
    ) -> None:
        """Translate panel action into modal dismiss."""
        event.stop()
        self.dismiss(event.review_result)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def dismiss(self, result=None) -> None:
        """Guard dismiss: block bare dismiss() when a decision is required.

        This is the single chokepoint for all dismiss pathways (ESC, X button,
        bindings, ModalScreen-level handlers). Only an explicit ReviewResult
        (from the Review tab buttons) is allowed through when changes are pending.
        """
        if self._requires_decision and not isinstance(result, ReviewResult):
            self._notify_decision_required()
            return
        super().dismiss(result)

    def on_key(self, event) -> None:
        """Consume all bound keys to prevent them leaking to the app.

        Bindings fire before on_key, so the action is already dispatched.
        We just stop propagation here to prevent app-level handlers
        (e.g. 'h' for conversation history) from also firing.
        """
        if event.key in self._MODAL_KEYS:
            event.stop()
            return
        # Don't call super — BaseModal.on_key only handles ESC which
        # we already consume above.

    def key_escape(self) -> None:
        """No-op: ESC is handled by the binding via action_close_modal."""

    def action_close_modal(self) -> None:
        """ESC key: routes through dismiss() guard."""
        self.dismiss()

    def action_force_close(self) -> None:
        """Ctrl+C: warn on first press, auto-reject on second."""
        if not self._requires_decision:
            self.dismiss()
            return
        if self._ctrl_c_warned:
            self.dismiss(
                ReviewResult(
                    approved=False,
                    metadata={"selection_mode": "force_close"},
                    action="reject",
                ),
            )
        else:
            try:
                self.app.notify(
                    "Press Ctrl+C again to reject all changes and close",
                    severity="warning",
                    timeout=3,
                )
                self._ctrl_c_warned = True
            except Exception:
                pass  # Don't enter warned state if notification failed

    def action_switch_answer_tab(self) -> None:
        """Switch to Answer tab via keyboard shortcut."""
        try:
            tabs = self.query_one("#final_answer_tabs", TabbedContent)
            self.set_focus(None)
            tabs.active = "answer_tab"
        except Exception:
            pass  # No tabs in answer-only mode

    def action_switch_review_tab(self) -> None:
        """Switch to Review Changes or Workspace tab via keyboard shortcut or button."""
        try:
            tabs = self.query_one("#final_answer_tabs", TabbedContent)
            # Clear focus first — TabbedContent auto-activates the pane
            # containing the focused widget, so leaving focus on a button
            # inside answer_tab would immediately revert the switch.
            self.set_focus(None)
            # Try review_tab first (changes mode), then workspace_tab (workspace mode)
            try:
                tabs.query_one("#review_tab", TabPane)
                tabs.active = "review_tab"
            except Exception:
                tabs.active = "workspace_tab"
        except Exception:
            pass  # No tabs in answer-only mode

    # ------------------------------------------------------------------
    # Review panel keyboard actions — delegate to self._panel
    # ------------------------------------------------------------------

    def action_toggle_selected(self) -> None:
        if self._panel and self._panel._selected_file:
            self._panel._toggle_file_approval(self._panel._selected_file)

    def action_approve_selected(self) -> None:
        if self._panel:
            self._panel._approve_selected()

    def action_toggle_selected_hunk(self) -> None:
        if self._panel:
            self._panel._toggle_selected_hunk()

    def action_select_previous_hunk(self) -> None:
        if self._panel:
            self._panel._move_selected_hunk(-1)

    def action_select_next_hunk(self) -> None:
        if self._panel:
            self._panel._move_selected_hunk(1)

    def action_select_previous_file(self) -> None:
        if self._panel:
            self._panel._move_selection(-1)

    def action_select_next_file(self) -> None:
        if self._panel:
            self._panel._move_selection(1)

    def action_edit_file(self) -> None:
        if self._panel:
            self._panel.action_edit_file()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_decision_required(self) -> None:
        """Show a notification that the user must approve or reject changes.

        Debounced: ignores calls within 0.5s of the previous notification
        to prevent double-toast when multiple dismiss pathways fire.
        """
        now = time.monotonic()
        if now - self._last_notify_time < 0.5:
            return
        self._last_notify_time = now
        try:
            self.app.notify(
                "Please approve or review changes before closing",
                severity="warning",
                timeout=3,
            )
        except Exception:
            pass  # No app context (e.g. in tests)

    def _close_with_approve_all(self) -> None:
        """Close the modal, approving all changes."""
        self.dismiss(
            ReviewResult(
                approved=True,
                approved_files=None,
                metadata={"selection_mode": "all"},
                action="approve",
            ),
        )

    def _copy_answer(self) -> None:
        """Copy answer content to clipboard."""
        try:
            import pyperclip

            pyperclip.copy(self._data.answer_content)
            self.app.notify("Answer copied to clipboard", severity="information", timeout=2)
        except Exception:
            # Fallback: try Textual's clipboard if available
            try:
                self.app.copy_to_clipboard(self._data.answer_content)
                self.app.notify("Answer copied to clipboard", severity="information", timeout=2)
            except Exception:
                self.app.notify("Could not copy to clipboard", severity="warning", timeout=2)


__all__ = [
    "FinalAnswerModal",
    "FinalAnswerModalData",
    "AnswerTabContent",
    "WorkspaceTabContent",
]
