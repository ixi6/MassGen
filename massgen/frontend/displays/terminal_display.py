"""
Terminal Display for MassGen Coordination

Rich terminal interface with live updates, agent columns, and coordination events.
"""

import os

from .base_display import BaseDisplay


class TerminalDisplay(BaseDisplay):
    """Rich terminal display with live agent columns and coordination events."""

    def __init__(self, agent_ids: list[str], **kwargs):
        """Initialize terminal display.

        Args:
            agent_ids: List of agent IDs to display
            **kwargs: Additional configuration options
                - terminal_width: Override terminal width (default: auto-detect)
                - max_events: Max coordination events to show (default: 5)
        """
        super().__init__(agent_ids, **kwargs)
        self.terminal_width = kwargs.get("terminal_width", self._get_terminal_width())
        self.max_events = kwargs.get("max_events", 5)
        self.num_agents = len(agent_ids)
        self.log_filename = None
        self._last_refresh_time = 0

        # Calculate column layout
        if self.num_agents == 1:
            self.col_width = self.terminal_width - 4
            self.separators = ""
        elif self.num_agents == 2:
            self.col_width = (self.terminal_width - 3) // 2
            self.separators = " │ "
        else:
            self.col_width = (self.terminal_width - (self.num_agents - 1) * 3) // self.num_agents
            self.separators = " │ "

    def _get_terminal_width(self) -> int:
        """Get terminal width with fallback."""
        try:
            return min(os.get_terminal_size().columns, 120)
        except (OSError, AttributeError):
            return 80

    def initialize(self, question: str, log_filename: str | None = None):
        """Initialize the display with column headers."""
        self.log_filename = log_filename

        # Clear screen and show initial layout
        import os

        try:
            os.system("clear" if os.name == "posix" else "cls")
        except Exception:
            print("\033[2J\033[H", end="")

        title = f"🚀 {'Multi' if self.num_agents > 2 else 'Two' if self.num_agents == 2 else 'Single'}-Agent Coordination Dashboard"
        print(title)

        if log_filename:
            print(f"📁 Log: {log_filename}")

        print("=" * self.terminal_width)

        # Show column headers with backend info if available
        headers = []
        for agent_id in self.agent_ids:
            header_text = self._format_agent_header(agent_id)
            headers.append(f"{header_text:^{self.col_width}}")

        if self.num_agents == 1:
            print(headers[0])
            print("─" * self.col_width)
        else:
            print(self.separators.join(headers))
            print(self.separators.join(["─" * self.col_width] * self.num_agents))

        print("=" * self.terminal_width)
        print()

    def update_agent_content(
        self,
        agent_id: str,
        content: str,
        content_type: str = "thinking",
        tool_call_id: str | None = None,
    ):
        """Update content for a specific agent."""
        if agent_id not in self.agent_ids:
            return

        # Clean content - remove any legacy agent prefixes but preserve line breaks
        clean_content = content
        if clean_content.startswith(f"[{agent_id}]"):
            clean_content = clean_content[len(f"[{agent_id}]") :]

        # Remove any legacy ** prefixes from orchestrator messages (kept for compatibility)
        if clean_content.startswith(f"🤖 **{agent_id}**"):
            clean_content = clean_content.replace(f"🤖 **{agent_id}**", "🤖")

        # Only strip if content doesn't contain line breaks (preserve formatting)
        if "\n" not in clean_content:
            clean_content = clean_content.strip()

        should_refresh = False

        if content_type == "tool":
            # Temporarily show "Tool result" messages for debugging
            # if "Tool result:" in clean_content:
            #     return  # Skip tool result messages as they're just noise
            # Tool usage - add with arrow prefix
            self.agent_outputs[agent_id].append(f"→ {clean_content}")
            should_refresh = True  # Always refresh for tool calls
        elif content_type == "status":
            # Status messages - add without prefix
            self.agent_outputs[agent_id].append(clean_content)
            should_refresh = True  # Always refresh for status changes
        elif content_type == "presentation":
            # Presentation content - always start on a new line
            self.agent_outputs[agent_id].append(f"🎤 {clean_content}")
            should_refresh = True  # Always refresh for presentations
        else:
            # Thinking content - smart formatting based on content type
            if self.agent_outputs[agent_id] and self.agent_outputs[agent_id][-1] == "⚡ Working...":
                # Replace "Working..." with actual thinking
                self.agent_outputs[agent_id][-1] = clean_content
                should_refresh = True  # Refresh when replacing "Working..."
            elif self._is_action_content(clean_content):
                # Action content (tool usage, results) - always start new line
                self.agent_outputs[agent_id].append(clean_content)
                should_refresh = True
            elif (
                self.agent_outputs[agent_id]
                and not self.agent_outputs[agent_id][-1].startswith("→")
                and not self.agent_outputs[agent_id][-1].startswith("🎤")
                and not self._is_action_content(self.agent_outputs[agent_id][-1])
            ):
                # Continue building regular thinking content
                if "\n" in clean_content:
                    # Handle explicit line breaks
                    parts = clean_content.split("\n")
                    self.agent_outputs[agent_id][-1] += parts[0]
                    for part in parts[1:]:
                        self.agent_outputs[agent_id].append(part)
                    should_refresh = True
                else:
                    # Simple concatenation for regular text with careful spacing
                    # Only add space if the new content looks like a separate word/token
                    # Avoid adding spaces within words that were split across tokens
                    current_content = self.agent_outputs[agent_id][-1]
                    if (
                        current_content
                        and clean_content
                        and not current_content[-1].isspace()
                        and not clean_content[0].isspace()
                        and current_content[-1] not in ".,!?;:-()[]{}\"'"
                        and clean_content[0] not in ".,!?;:-()[]{}\"'"
                        and not clean_content.startswith("\n")
                        and
                        # Only add space if content looks like a new word (starts with letter/digit)
                        (clean_content[0].isalpha() or clean_content[0].isdigit())
                        and
                        # And previous content ended with a letter/digit
                        (current_content[-1].isalpha() or current_content[-1].isdigit())
                        and
                        # And the new content is more than 2 characters (likely a word, not suffix)
                        len(clean_content.strip()) > 2
                    ):
                        self.agent_outputs[agent_id][-1] += " " + clean_content
                    else:
                        self.agent_outputs[agent_id][-1] += clean_content
            else:
                # New line of content
                self.agent_outputs[agent_id].append(clean_content)
                should_refresh = True

        if should_refresh:
            self._refresh_display()

    def _is_action_content(self, content: str) -> bool:
        """Check if content represents an action that should be on its own line."""
        action_indicators = [
            "💡",
            "🗳️",
            "✅",
            "🔄",
            "❌",
            "🔧",  # Tool and result emojis
            "Providing answer:",
            "Voting for",
            "Answer provided",
            "Vote recorded",
            "Vote ignored",
            "Vote invalid",
            "Using",
        ]
        return any(indicator in content for indicator in action_indicators)

    def update_agent_status(self, agent_id: str, status: str):
        """Update status for a specific agent."""
        if agent_id not in self.agent_ids:
            return

        old_status = self.agent_status.get(agent_id)
        if old_status == status:
            return  # No change, no need to refresh

        self.agent_status[agent_id] = status

        # Add working indicator if transitioning to working
        if old_status != "working" and status == "working":
            if not self.agent_outputs[agent_id] or not self.agent_outputs[agent_id][-1].startswith("⚡"):
                self.agent_outputs[agent_id].append("⚡  Working...")

        # Show status update in footer
        self._refresh_display()

    def add_orchestrator_event(self, event: str):
        """Add an orchestrator coordination event."""
        self.orchestrator_events.append(event)
        self._refresh_display()

    def show_final_answer(self, answer: str, vote_results=None, selected_agent=None):
        """Display the final coordinated answer prominently."""
        print("\n🎯 FINAL COORDINATED ANSWER:")
        print("=" * 60)
        print(f"📋 {answer}")
        if selected_agent:
            print(f"✅ Selected by: {selected_agent}")
        if vote_results:
            vote_summary = ", ".join([f"{agent}: {votes}" for agent, votes in vote_results.items()])
            print(f"🗳️ Vote results: {vote_summary}")
        print("=" * 60)

    def show_post_evaluation_content(self, content: str, agent_id: str):
        """Display post-evaluation streaming content."""
        print(f"🔍 Post-Evaluation [{agent_id}]: {content}", end="", flush=True)

    def show_restart_banner(self, reason: str, instructions: str, attempt: int, max_attempts: int):
        """Display restart decision banner."""
        print("\n" + "=" * 80)
        print(f"🔄 ORCHESTRATION RESTART (Attempt {attempt}/{max_attempts})")
        print("=" * 80)
        print(f"\nREASON:\n{reason}")
        print(f"\nINSTRUCTIONS FOR NEXT ATTEMPT:\n{instructions}")
        print("\n" + "=" * 80 + "\n")

    def show_restart_context_panel(self, reason: str, instructions: str):
        """Display restart context panel at top of UI (for attempt 2+)."""
        print("\n" + "⚠" * 40)
        print("⚠️  PREVIOUS ATTEMPT FEEDBACK")
        print("⚠" * 40)
        print(f"\nReason: {reason}")
        print(f"\nInstructions: {instructions}")
        print("\n" + "⚠" * 40 + "\n")

    def cleanup(self):
        """Clean up display resources."""
        # No special cleanup needed for terminal display

    def _refresh_display(self):
        """Refresh the entire display with proper columns."""
        import time

        current_time = time.time()
        if current_time - self._last_refresh_time < 0.005:  # 5ms between refreshes
            return
        self._last_refresh_time = current_time

        # Move to after headers and clear content area
        print("\033[7;1H\033[0J", end="")  # Move to line 7 and clear down

        # Show agent outputs in columns with word wrapping
        max_lines = max(len(self.agent_outputs[agent_id]) for agent_id in self.agent_ids) if self.agent_outputs else 0

        # For single agent, don't wrap - show full content
        if self.num_agents == 1:
            for i in range(max_lines):
                line = self.agent_outputs[self.agent_ids[0]][i] if i < len(self.agent_outputs[self.agent_ids[0]]) else ""
                print(line)
        else:
            # For multiple agents, wrap long lines to fit columns
            wrapped_outputs = {}
            for agent_id in self.agent_ids:
                wrapped_outputs[agent_id] = []
                for line in self.agent_outputs[agent_id]:
                    if len(line) > self.col_width - 2:
                        # Smart word wrap - preserve formatting and avoid breaking mid-sentence
                        words = line.split(" ")
                        current_line = ""
                        for word in words:
                            test_line = current_line + (" " if current_line else "") + word
                            if len(test_line) > self.col_width - 2:
                                if current_line:
                                    wrapped_outputs[agent_id].append(current_line)
                                    current_line = word
                                else:
                                    # Single word longer than column width - truncate gracefully
                                    wrapped_outputs[agent_id].append(word[: self.col_width - 2] + "…")
                                    current_line = ""
                            else:
                                current_line = test_line
                        if current_line:
                            wrapped_outputs[agent_id].append(current_line)
                    else:
                        wrapped_outputs[agent_id].append(line)

            # Display wrapped content
            max_wrapped_lines = max(len(wrapped_outputs[agent_id]) for agent_id in self.agent_ids) if wrapped_outputs else 0
            for i in range(max_wrapped_lines):
                output_lines = []
                for agent_id in self.agent_ids:
                    line = wrapped_outputs[agent_id][i] if i < len(wrapped_outputs[agent_id]) else ""
                    output_lines.append(f"{line:<{self.col_width}}")
                print(self.separators.join(output_lines))

        # Show status footer with proper column alignment
        print("\n" + "=" * self.terminal_width)

        # Simple status line aligned with columns, matching header format
        status_lines = []
        for agent_id in self.agent_ids:
            status_text = f"{self._format_agent_header(agent_id)}: {self.agent_status[agent_id]}"
            status_lines.append(f"{status_text:^{self.col_width}}")

        if self.num_agents == 1:
            print(status_lines[0])
        else:
            print(self.separators.join(status_lines))

        print("=" * self.terminal_width)

        # Show recent coordination events
        if self.orchestrator_events:
            print("\n📋 RECENT COORDINATION EVENTS:")
            recent_events = self.orchestrator_events[-2:]  # Show last 2 events
            for event in recent_events:
                print(f"   • {event}")
        print()

    def _get_agent_backend_name(self, agent_id: str) -> str:
        """Return provider/backend name for display purposes."""
        backend_name = "Unknown"
        orchestrator = getattr(self, "orchestrator", None)
        if orchestrator and hasattr(orchestrator, "agents"):
            agent = orchestrator.agents.get(agent_id)
            backend = getattr(agent, "backend", None) if agent else None
            provider_getter = getattr(backend, "get_provider_name", None) if backend else None
            if callable(provider_getter):
                try:
                    backend_name = provider_getter()
                except Exception:
                    backend_name = "Unknown"
        return backend_name

    def _format_agent_header(self, agent_id: str) -> str:
        """Format the agent header label with backend metadata."""
        backend_name = self._get_agent_backend_name(agent_id)
        return f"{agent_id.upper()} ({backend_name})"
