"""Input-related modals: Broadcast prompts and structured questions."""

import time
from typing import TYPE_CHECKING, Any

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal, VerticalScroll
    from textual.widgets import (
        Button,
        Checkbox,
        Input,
        Label,
        RadioButton,
        RadioSet,
        Static,
        TextArea,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal

if TYPE_CHECKING:
    from massgen.frontend.displays.textual_terminal_display import TextualApp


class BroadcastPromptModal(BaseModal):
    """Modal for handling human input requests from agents during broadcast."""

    def __init__(self, sender_agent_id: str, question: str, timeout: int, app: "TextualApp"):
        super().__init__()
        self.sender_agent_id = sender_agent_id
        self.question = question
        self.timeout = timeout
        self.app_ref = app
        self.response: str | None = None
        self._start_time = time.time()

    def compose(self) -> ComposeResult:
        with Container(id="broadcast_container"):
            yield Label("⏸ ALL AGENTS PAUSED — HUMAN INPUT NEEDED ⏸", id="broadcast_banner")
            yield Label(f"From: {self.sender_agent_id}", id="broadcast_sender")
            yield Label("Question:", id="broadcast_question_label")
            yield TextArea(self.question, id="broadcast_question", read_only=True)
            yield Label(f"Timeout: {self.timeout}s", id="broadcast_timeout")
            yield Label("Your response:", id="response_label")
            yield Input(placeholder="Type your response here...", id="broadcast_input")
            with Horizontal(id="broadcast_buttons"):
                yield Button("Submit", id="submit_broadcast_button", variant="primary")
                yield Button("Skip", id="skip_broadcast_button")

    def on_mount(self) -> None:
        """Focus the input when mounted."""
        try:
            input_widget = self.query_one("#broadcast_input", Input)
            input_widget.focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "submit_broadcast_button":
            input_widget = self.query_one("#broadcast_input", Input)
            self.response = input_widget.value.strip() or None
            self.dismiss(self.response)
        elif event.button.id == "skip_broadcast_button":
            self.response = None
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        if event.input.id == "broadcast_input":
            self.response = event.value.strip() or None
            self.dismiss(self.response)


class StructuredBroadcastPromptModal(BaseModal):
    """Modal for handling structured questions with options from agents during broadcast."""

    BINDINGS = [
        ("escape", "close", "Skip"),
    ]

    def __init__(
        self,
        sender_agent_id: str,
        structured_questions: list[Any],
        timeout: int,
        app: "TextualApp",
    ):
        super().__init__()
        self.sender_agent_id = sender_agent_id
        self.structured_questions = structured_questions
        self.timeout = timeout
        self.app_ref = app
        self._start_time = time.time()
        self._current_question_idx = 0
        self._responses: list[dict[str, Any]] = []
        # Track selections per question
        self._selections: dict[int, set] = {i: set() for i in range(len(structured_questions))}
        self._other_texts: dict[int, str] = {i: "" for i in range(len(structured_questions))}

    def compose(self) -> ComposeResult:
        with Container(id="structured_broadcast_container"):
            yield Label("⏸ ALL AGENTS PAUSED — HUMAN INPUT NEEDED ⏸", id="broadcast_banner")
            yield Label(f"From: {self.sender_agent_id}", id="broadcast_sender")
            yield Label(f"Timeout: {self.timeout}s", id="broadcast_timeout")

            # Question progress indicator
            total_qs = len(self.structured_questions)
            yield Label(
                f"Question 1 of {total_qs}",
                id="question_progress",
            )

            # Question container (will be populated in on_mount)
            yield Container(id="question_container")

            # Navigation buttons
            with Horizontal(id="broadcast_buttons"):
                yield Button("Previous", id="prev_question_button", disabled=True)
                yield Button("Next", id="next_question_button", variant="primary")
                yield Button("Skip All", id="skip_broadcast_button")

    def _render_current_question(self) -> None:
        """Render the current question's UI elements."""
        q = self.structured_questions[self._current_question_idx]
        q_idx = self._current_question_idx

        # Get question attributes
        text = q.text if hasattr(q, "text") else q.get("text", "")
        options = q.options if hasattr(q, "options") else q.get("options", [])
        multi_select = q.multi_select if hasattr(q, "multi_select") else q.get("multiSelect", False)
        q.allow_other if hasattr(q, "allow_other") else q.get("allowOther", True)

        container = self.query_one("#question_container", Container)
        container.remove_children()

        # Question text - use unique ID per question to avoid duplicates
        container.mount(Label(text, id=f"question_text_{q_idx}", classes="question_text"))

        # Only show options section if there are options to display
        if options:
            if multi_select:
                container.mount(Label("Select all that apply:", classes="options_hint"))
                scroll = VerticalScroll(id=f"options_scroll_{q_idx}")
                container.mount(scroll)
                for opt in options:
                    opt_id = opt.id if hasattr(opt, "id") else opt.get("id", "")
                    opt_label = opt.label if hasattr(opt, "label") else opt.get("label", "")
                    opt_desc = opt.description if hasattr(opt, "description") else opt.get("description", "")
                    display_text = f"{opt_label}" + (f" - {opt_desc}" if opt_desc else "")
                    cb = Checkbox(
                        display_text,
                        id=f"opt_{q_idx}_{opt_id}",
                        value=opt_id in self._selections[q_idx],
                    )
                    scroll.mount(cb)
            else:
                container.mount(Label("Select one:", classes="options_hint"))
                radio_set = RadioSet(id=f"radioset_{q_idx}")
                container.mount(radio_set)
                for opt in options:
                    opt_id = opt.id if hasattr(opt, "id") else opt.get("id", "")
                    opt_label = opt.label if hasattr(opt, "label") else opt.get("label", "")
                    opt_desc = opt.description if hasattr(opt, "description") else opt.get("description", "")
                    display_text = f"{opt_label}" + (f" - {opt_desc}" if opt_desc else "")
                    rb = RadioButton(display_text, id=f"opt_{q_idx}_{opt_id}")
                    radio_set.mount(rb)

        # Always show text input for additional comments/response
        if options:
            container.mount(Label("Additional comments (optional):", classes="other_label"))
        else:
            container.mount(Label("Your response:", classes="other_label"))
        other_input = Input(
            placeholder="Type your response here...",
            id=f"other_input_{q_idx}",
            value=self._other_texts.get(q_idx, ""),
        )
        container.mount(other_input)

    def on_mount(self) -> None:
        """Initial setup when modal is mounted."""
        # Render the first question now that widgets are mounted
        self._render_current_question()
        self._update_navigation_buttons()

    def _update_navigation_buttons(self) -> None:
        """Update button states based on current question."""
        prev_btn = self.query_one("#prev_question_button", Button)
        next_btn = self.query_one("#next_question_button", Button)
        progress = self.query_one("#question_progress", Label)

        prev_btn.disabled = self._current_question_idx == 0

        is_last = self._current_question_idx == len(self.structured_questions) - 1
        next_btn.label = "Submit" if is_last else "Next"
        next_btn.variant = "success" if is_last else "primary"

        progress.update(f"Question {self._current_question_idx + 1} of {len(self.structured_questions)}")

    def _save_current_selections(self) -> None:
        """Save selections from current question before navigating."""
        q_idx = self._current_question_idx
        q = self.structured_questions[q_idx]
        multi_select = q.multi_select if hasattr(q, "multi_select") else q.get("multiSelect", False)

        # Save checkbox/radio selections
        if multi_select:
            # Get all checkboxes for this question
            try:
                scroll = self.query_one("#options_scroll", VerticalScroll)
                self._selections[q_idx] = set()
                for child in scroll.children:
                    if hasattr(child, "value") and child.value:
                        # Extract option ID from widget ID: opt_{q_idx}_{opt_id}
                        widget_id = child.id or ""
                        parts = widget_id.split("_", 2)
                        if len(parts) >= 3:
                            self._selections[q_idx].add(parts[2])
            except Exception:
                pass
        else:
            # Get selected radio button
            try:
                radio_set = self.query_one(f"#radioset_{q_idx}", RadioSet)
                self._selections[q_idx] = set()
                if radio_set.pressed_button:
                    widget_id = radio_set.pressed_button.id or ""
                    parts = widget_id.split("_", 2)
                    if len(parts) >= 3:
                        self._selections[q_idx].add(parts[2])
            except Exception:
                pass

        # Save other text
        try:
            other_input = self.query_one(f"#other_input_{q_idx}", Input)
            self._other_texts[q_idx] = other_input.value
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "prev_question_button":
            self._save_current_selections()
            if self._current_question_idx > 0:
                self._current_question_idx -= 1
                self._render_current_question()
                self._update_navigation_buttons()

        elif event.button.id == "next_question_button":
            self._save_current_selections()
            if self._current_question_idx < len(self.structured_questions) - 1:
                # Move to next question
                self._current_question_idx += 1
                self._render_current_question()
                self._update_navigation_buttons()
            else:
                # Submit all responses
                self._submit_all()

        elif event.button.id == "skip_broadcast_button":
            self.dismiss(None)

    def _submit_all(self) -> None:
        """Collect all responses and dismiss modal."""
        responses = []
        for q_idx in range(len(self.structured_questions)):
            selected = list(self._selections.get(q_idx, set()))
            other_text = self._other_texts.get(q_idx, "").strip() or None
            responses.append(
                {
                    "questionIndex": q_idx,
                    "selectedOptions": selected,
                    "otherText": other_text,
                },
            )
        self.dismiss(responses)

    def action_close(self) -> None:
        """Handle escape key."""
        self.dismiss(None)


class DecompositionSubtasksModal(BaseModal):
    """Modal for editing per-agent subtasks in decomposition mode."""

    def __init__(
        self,
        agent_ids: list[str],
        current_subtasks: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.agent_ids = agent_ids
        self.current_subtasks = current_subtasks or {}
        self._input_ids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Container(classes="modal-container modal-container-wide", id="subtasks_modal_container"):
            yield Label("🧩  Decomposition Subtasks", classes="modal-title")
            yield Label(
                "Assign an optional subtask to each agent. Leave blank to use auto-decomposition.",
                classes="modal-summary",
            )
            with VerticalScroll(id="subtasks_scroll"):
                for idx, agent_id in enumerate(self.agent_ids):
                    input_id = f"subtask_input_{idx}"
                    self._input_ids[input_id] = agent_id
                    with Horizontal(classes="subtask_row"):
                        yield Label(f"{agent_id}:", classes="subtask_agent_label")
                        yield Input(
                            value=self.current_subtasks.get(agent_id, ""),
                            placeholder="Optional subtask",
                            id=input_id,
                        )
            with Horizontal(classes="modal-footer"):
                yield Button("Clear All", id="clear_subtasks_button")
                yield Button("Cancel", id="cancel_subtasks_button")
                yield Button("Save", id="save_subtasks_button", variant="primary")

    def on_mount(self) -> None:
        """Focus the first input."""
        if not self._input_ids:
            return
        first_input_id = next(iter(self._input_ids.keys()))
        try:
            self.query_one(f"#{first_input_id}", Input).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save_subtasks_button":
            assignments: dict[str, str] = {}
            for input_id, agent_id in self._input_ids.items():
                try:
                    value = self.query_one(f"#{input_id}", Input).value.strip()
                except Exception:
                    value = ""
                if value:
                    assignments[agent_id] = value
            self.dismiss(assignments)
            return

        if event.button.id == "clear_subtasks_button":
            for input_id in self._input_ids:
                try:
                    self.query_one(f"#{input_id}", Input).value = ""
                except Exception:
                    pass
            return

        if event.button.id == "cancel_subtasks_button":
            self.dismiss(None)
            return


class DecompositionGenerationModal(BaseModal):
    """Progress modal shown while runtime decomposition subtasks are generated."""

    def __init__(self, status: str, detail: str = "") -> None:
        super().__init__()
        self._status = status
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Container(classes="modal-container modal-container-wide", id="decomposition_generation_container"):
            yield Label("🧩  Generating Decomposition Subtasks", classes="modal-title")
            yield Label(self._status, id="decomposition_generation_status")
            yield Label(self._detail, id="decomposition_generation_detail", classes="modal-summary")
            with VerticalScroll(id="decomposition_generation_results"):
                yield Static(
                    "[dim]Waiting for decomposition subagent results...[/]",
                    id="decomposition_generation_results_content",
                    markup=True,
                )
            yield Button("Close (ESC)", id="close_decomposition_generation_button")

    def update_progress(self, status: str, detail: str = "") -> None:
        """Update modal status/description text."""
        self._status = status
        self._detail = detail
        try:
            self.query_one("#decomposition_generation_status", Label).update(status)
        except Exception:
            pass
        try:
            self.query_one("#decomposition_generation_detail", Label).update(detail)
        except Exception:
            pass

    def show_subtasks(self, subtasks: dict[str, str], source: str = "subagent") -> None:
        """Render per-agent subtasks in the modal."""
        header = "[bold green]Generated by decomposition subagent:[/]\n" if source == "subagent" else "[bold yellow]Using fallback decomposition subtasks:[/]\n"
        if subtasks:
            lines = [header]
            for agent_id, subtask in subtasks.items():
                lines.append(f"- [bold]{agent_id}[/]: {subtask}")
            content = "\n".join(lines)
        else:
            content = "[dim]No subtasks were produced.[/]"

        try:
            self.query_one("#decomposition_generation_results_content", Static).update(content)
        except Exception:
            pass


class ChunkAdvanceModal(BaseModal):
    """Modal shown after chunk completion to advance/pause chunk execution."""

    BINDINGS = [
        ("enter", "continue_now", "Continue"),
        ("escape", "pause_here", "Pause"),
    ]

    def __init__(
        self,
        completed_chunk: str,
        next_chunk: str,
        *,
        auto_continue: bool = True,
        countdown_seconds: int = 2,
    ) -> None:
        super().__init__()
        self.completed_chunk = completed_chunk
        self.next_chunk = next_chunk
        self.auto_continue = auto_continue
        self.countdown_seconds = max(1, int(countdown_seconds))
        self._remaining = self.countdown_seconds
        self._countdown_timer = None

    def compose(self) -> ComposeResult:
        with Container(classes="modal-container modal-container-narrow", id="chunk_advance_container"):
            yield Label("✅ Chunk Complete", classes="modal-title")
            yield Label(
                f"Completed: {self.completed_chunk}",
                id="chunk_advance_completed",
                classes="modal-summary",
            )
            yield Label(
                f"Next chunk: {self.next_chunk}",
                id="chunk_advance_next",
                classes="modal-summary",
            )

            if self.auto_continue:
                yield Label(
                    f"Auto-continuing in {self._remaining}s. Press Pause to stop.",
                    id="chunk_advance_countdown",
                    classes="modal-summary",
                )
            else:
                yield Label(
                    "Auto-continue is off. Continue when ready.",
                    id="chunk_advance_countdown",
                    classes="modal-summary",
                )

            with Horizontal(classes="modal-footer"):
                yield Button("Continue Now (Enter)", id="continue_chunk_button", variant="primary")
                yield Button("Pause Here (Esc)", id="pause_chunk_button")

    def on_mount(self) -> None:
        """Start optional auto-continue countdown."""
        if not self.auto_continue:
            return

        def tick() -> None:
            self._remaining -= 1
            if self._remaining <= 0:
                if self._countdown_timer:
                    self._countdown_timer.stop()
                    self._countdown_timer = None
                self.dismiss(True)
                return
            try:
                label = self.query_one("#chunk_advance_countdown", Label)
                label.update(f"Auto-continuing in {self._remaining}s. Press Pause to stop.")
            except Exception:
                pass

        self._countdown_timer = self.set_interval(1.0, tick)

    def on_unmount(self) -> None:
        """Clean up countdown timer."""
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle modal button actions."""
        if event.button.id == "continue_chunk_button":
            self.dismiss(True)
        elif event.button.id == "pause_chunk_button":
            self.dismiss(False)

    def action_continue_now(self) -> None:
        self.dismiss(True)

    def action_pause_here(self) -> None:
        self.dismiss(False)
