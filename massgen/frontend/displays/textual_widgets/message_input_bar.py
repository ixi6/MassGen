"""Reusable message input bar widget with inject-target toggle."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Button

from .multi_line_input import MultiLineInput


class MessageInputBar(Container):
    """Compact input bar with optional inject-target toggle button.

    Emits ``Submitted`` when the user presses Enter with non-empty text.
    The ``target`` field indicates which agent(s) should receive the message:
    ``"all"`` for broadcast, or a specific agent ID.
    """

    class Submitted(Message):
        """Emitted on Enter with non-empty text."""

        def __init__(self, value: str, target: str) -> None:
            super().__init__()
            self.value = value
            self.target = target

    class TargetChanged(Message):
        """Emitted when the inject target is toggled."""

        def __init__(self, target: str) -> None:
            super().__init__()
            self.target = target

    DEFAULT_CSS = """
    MessageInputBar {
        dock: bottom;
        height: auto;
        width: 100%;
        padding: 0 1;
        background: $background;
    }
    """

    def __init__(
        self,
        placeholder: str = "",
        targets: list[str] | None = None,
        vim_mode: bool = False,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._placeholder = placeholder
        self._targets: list[str] = targets or []
        self._current_target: str = "all"
        self._vim_mode = vim_mode

    def compose(self) -> ComposeResult:
        with Container(classes="shared-question-input-row"):
            yield MultiLineInput(
                placeholder=self._placeholder,
                classes="shared-question-input",
                vim_mode=self._vim_mode,
            )
            btn = Button(
                self._format_target_label(),
                classes="shared-inject-target-button",
            )
            # Hide button until targets are set
            if not self._targets:
                btn.display = False
            yield btn

    def set_targets(self, targets: list[str]) -> None:
        """Update the list of inject targets and reset to 'all'."""
        self._targets = list(targets)
        self._current_target = "all"
        self._update_target_button()
        # Show/hide button based on whether we have targets
        try:
            btn = self.query_one(".shared-inject-target-button", Button)
            btn.display = bool(self._targets)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear the input text."""
        try:
            self.query_one(".shared-question-input", MultiLineInput).clear()
        except Exception:
            pass

    def _cycle_target(self) -> None:
        """Cycle inject target: all -> targets[0] -> ... -> all."""
        if not self._targets:
            return
        cycle = ["all"] + self._targets
        try:
            idx = cycle.index(self._current_target)
        except ValueError:
            idx = -1
        self._current_target = cycle[(idx + 1) % len(cycle)]

    def _format_target_label(self) -> str:
        if self._current_target == "all":
            return "Inject: all"
        return f"Inject: {self._current_target}"

    def _update_target_button(self) -> None:
        try:
            btn = self.query_one(".shared-inject-target-button", Button)
            btn.label = self._format_target_label()
            btn.set_class(self._current_target != "all", "mode-current")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("shared-inject-target-button"):
            event.stop()
            self._cycle_target()
            self._update_target_button()
            self.post_message(self.TargetChanged(self._current_target))

    def on_multi_line_input_submitted(self, event: Any) -> None:
        event.stop()
        text = event.value.strip() if hasattr(event, "value") else ""
        if text:
            self.post_message(self.Submitted(value=text, target=self._current_target))
            self.clear()
