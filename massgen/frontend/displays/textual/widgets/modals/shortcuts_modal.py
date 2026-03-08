"""Keyboard shortcuts help modal."""

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal, VerticalScroll
    from textual.widgets import Button, Label, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal


class KeyboardShortcutsModal(BaseModal):
    """Modal showing commands available during coordination."""

    def compose(self) -> ComposeResult:
        with Container(id="shortcuts_modal_container"):
            yield Label("📖  Commands & Shortcuts", id="shortcuts_modal_header")
            yield Label("Press Esc to unfocus input, then use single keys", id="shortcuts_hint")

            with Horizontal(id="shortcuts_columns"):
                with VerticalScroll(id="shortcuts_col_left", classes="shortcuts-column"):
                    yield Static(
                        "[bold cyan]Quick Keys[/] [dim](when not typing)[/]\n"
                        "  [yellow]q[/]      Cancel/stop execution\n"
                        "  [yellow]w[/]      Workspace browser\n"
                        "  [yellow]v[/]      Vote results\n"
                        "  [yellow]a[/]      Answer browser\n"
                        "  [yellow]t[/]      Timeline\n"
                        "  [yellow]h[/]      Conversation history\n"
                        "  [yellow]c[/]      Cost breakdown\n"
                        "  [yellow]m[/]      MCP status / metrics\n"
                        "  [yellow]k[/]      Skills manager\n"
                        "  [yellow]s[/]      System status\n"
                        "  [yellow]o[/]      Agent output (full)\n"
                        "  [yellow]?[/]      This help\n"
                        "  [yellow]1-9[/]    Switch to agent N\n"
                        "\n"
                        "[bold cyan]Focus[/]\n"
                        "  [yellow]Esc[/]    Unfocus input\n"
                        "  [yellow]i[/] or [yellow]/[/]  Focus input",
                        markup=True,
                    )

                with VerticalScroll(id="shortcuts_col_right", classes="shortcuts-column"):
                    yield Static(
                        "[bold cyan]Input[/]\n"
                        "  [yellow]Enter[/]       Submit question\n"
                        "  [yellow]Shift+Enter[/] New line\n"
                        "  [yellow]Ctrl+P[/]      File access (off/read/write)\n"
                        "  [yellow]Tab[/]         Next agent\n"
                        "  [yellow]Shift+Tab[/]   Cycle mode (normal/plan/execute/analysis)\n"
                        "\n"
                        "[bold cyan]Mode Bar[/]\n"
                        "  [yellow]Plan[/]          Normal / Plan / Execute / Analysis\n"
                        "  [yellow]Multi-Agent[/]   All agents vs one\n"
                        "  [yellow]Refine[/]        Iterative refinement\n"
                        "  [yellow]Parallel[/]      Same task + voting (default)\n"
                        "  [yellow]Decomposition[/] Independent subtasks\n"
                        "  [yellow]Subtasks[/]      Edit per-agent subtasks\n"
                        "  [yellow]⋮[/]             Plan/analysis settings\n"
                        "  [yellow]?[/]             Open mode bar guide\n"
                        "  [yellow]Override[/]      Manual winner selection\n"
                        "\n"
                        "[bold cyan]Slash Commands[/]\n"
                        "  [yellow]/history[/]    Conversation history\n"
                        "  [yellow]/context[/]    Manage context paths\n"
                        "  [yellow]/skills[/]     Open skills manager\n"
                        "  [yellow]/vim[/]        Toggle vim mode\n"
                        "\n"
                        "[bold cyan]Quit[/]\n"
                        "  [yellow]Ctrl+C[/]      Exit MassGen\n"
                        "  [yellow]q[/]           Cancel current turn",
                        markup=True,
                    )

            yield Button("Close (ESC)", id="close_shortcuts_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_shortcuts_button":
            self.dismiss()
