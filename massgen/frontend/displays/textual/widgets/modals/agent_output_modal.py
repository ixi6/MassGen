"""Agent output modal: Full agent output viewing with syntax highlighting."""

from datetime import datetime

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal
    from textual.widgets import Button, Label, TextArea

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal


class AgentOutputModal(BaseModal):
    """Modal for viewing full agent output with syntax highlighting."""

    def __init__(
        self,
        agent_id: str,
        agent_outputs: list[str],
        model_name: str | None = None,
        all_agents: dict[str, dict] | None = None,
        current_prompt: str | None = None,
    ):
        super().__init__()
        self.current_agent_id = agent_id
        self.agent_outputs = agent_outputs
        self.model_name = model_name or "Unknown"
        self.all_agents = all_agents or {}
        self.current_prompt = current_prompt or ""

    def compose(self) -> ComposeResult:
        with Container(id="agent_output_container"):
            yield Label(
                f"📄 Full Output: {self.current_agent_id} ({self.model_name})",
                id="agent_output_header",
            )
            # Show prompt preview if available
            if self.current_prompt:
                # Truncate long prompts with ellipsis
                prompt_preview = self.current_prompt[:200] + "..." if len(self.current_prompt) > 200 else self.current_prompt
                # Replace newlines for single-line display
                prompt_preview = prompt_preview.replace("\n", " ").strip()
                yield Label(
                    f"💬 Prompt: {prompt_preview}",
                    id="agent_output_prompt",
                )
            # Agent toggle buttons if multiple agents
            if len(self.all_agents) > 1:
                with Horizontal(id="agent_toggle_buttons"):
                    for aid in sorted(self.all_agents.keys()):
                        agent_model = self.all_agents[aid].get("model", "")
                        # Shorten model name for button label
                        short_model = agent_model.split("/")[-1] if agent_model else ""
                        if short_model and len(short_model) > 20:
                            short_model = short_model[:17] + "..."
                        label = f"{aid}" + (f" ({short_model})" if short_model else "")
                        btn = Button(label, id=f"agent_btn_{aid}", classes="agent-toggle-btn")
                        if aid == self.current_agent_id:
                            btn.add_class("selected")
                        yield btn
            yield Label(
                f"Total lines: {len(self.agent_outputs)}",
                id="agent_output_stats",
            )
            # Join all outputs and display in scrollable text area
            full_content = "\n".join(self.agent_outputs) if self.agent_outputs else "(No output recorded)"
            yield TextArea(full_content, id="agent_output_text", read_only=True)
            with Horizontal(id="agent_output_buttons"):
                yield Button("Copy to Clipboard", id="copy_output_button")
                yield Button("Save to File", id="save_output_button")
                yield Button("Close (ESC)", id="close_output_button")

    def on_mount(self) -> None:
        """Scroll to bottom when modal opens."""
        try:
            text_area = self.query_one("#agent_output_text", TextArea)
            # Move cursor to end of document
            text_area.move_cursor_relative(rows=999999, columns=0)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close_output_button":
            self.dismiss()
        elif event.button.id == "copy_output_button":
            self._copy_to_clipboard()
        elif event.button.id == "save_output_button":
            self._save_to_file()
        elif event.button.id and event.button.id.startswith("agent_btn_"):
            # Switch to different agent
            new_agent_id = event.button.id.replace("agent_btn_", "")
            self._switch_agent(new_agent_id)

    def _switch_agent(self, agent_id: str) -> None:
        """Switch to viewing a different agent's output."""
        if agent_id not in self.all_agents:
            return
        self.current_agent_id = agent_id
        agent_data = self.all_agents[agent_id]
        self.agent_outputs = agent_data.get("outputs", [])
        self.model_name = agent_data.get("model") or "Unknown"

        # Update header
        try:
            header = self.query_one("#agent_output_header", Label)
            header.update(f"📄 Full Output: {self.current_agent_id} ({self.model_name})")
        except Exception:
            pass

        # Update stats
        try:
            stats = self.query_one("#agent_output_stats", Label)
            stats.update(f"Total lines: {len(self.agent_outputs)}")
        except Exception:
            pass

        # Update content
        try:
            text_area = self.query_one("#agent_output_text", TextArea)
            full_content = "\n".join(self.agent_outputs) if self.agent_outputs else "(No output recorded)"
            text_area.load_text(full_content)
            # Scroll to bottom
            text_area.move_cursor_relative(rows=999999, columns=0)
        except Exception:
            pass

        # Update button selection states
        try:
            for btn in self.query(".agent-toggle-btn"):
                if btn.id == f"agent_btn_{agent_id}":
                    btn.add_class("selected")
                else:
                    btn.remove_class("selected")
        except Exception:
            pass

    def _copy_to_clipboard(self) -> None:
        """Copy output to system clipboard."""
        import platform
        import subprocess

        full_content = "\n".join(self.agent_outputs)
        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                process.communicate(full_content.encode("utf-8"))
            elif system == "Windows":
                process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                process.communicate(full_content.encode("utf-8"))
            else:  # Linux
                process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                process.communicate(full_content.encode("utf-8"))
            self.app.notify(f"Copied {len(self.agent_outputs)} lines to clipboard", severity="information")
        except Exception as e:
            self.app.notify(f"Failed to copy: {e}", severity="error")

    def _save_to_file(self) -> None:
        """Save output to a file in the log directory."""
        from massgen.logging.log_directory import get_log_session_dir

        try:
            output_dir = get_log_session_dir() / "agent_outputs"
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.current_agent_id}_{timestamp}.txt"
            output_path = output_dir / filename

            full_content = "\n".join(self.agent_outputs)
            output_path.write_text(full_content, encoding="utf-8")

            self.app.notify(f"Saved to: {output_path.name}", severity="information")
        except Exception as e:
            self.app.notify(f"Failed to save: {e}", severity="error")
