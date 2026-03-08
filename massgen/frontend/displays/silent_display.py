"""
Silent Display for MassGen Coordination

Minimal output display designed for automation, background execution, and LLM-managed workflows.
Provides only essential information while detailed progress is available via status.json file.
"""

import time

from .base_display import BaseDisplay


class SilentDisplay(BaseDisplay):
    """Silent display for automation contexts.

    Designed for LLM agents and automation tools that need:
    - Minimal stdout output (< 15 lines)
    - No emojis or ANSI codes
    - Clear file paths for monitoring
    - Real-time progress via status.json

    Prints only:
    - Log directory path
    - Status file path
    - Question being answered
    - Final result summary
    """

    def __init__(self, agent_ids, **kwargs):
        """Initialize silent display.

        Args:
            agent_ids: List of agent IDs participating
            **kwargs: Additional configuration options
        """
        super().__init__(agent_ids, **kwargs)
        self.log_dir = None
        self.start_time = None
        self.output_dir = None
        self.agent_files = {}
        self.system_status_file = None

    def initialize(self, question: str, log_filename: str | None = None):
        """Initialize the display with essential information only.

        Prints:
        - QUESTION: The question being answered

        Note: LOG_DIR and STATUS paths are printed by cli.py for automation mode.

        Args:
            question: The user's question
            log_filename: Path to the main log file (used to determine log directory)
        """

        self.start_time = time.time()

        # Store log dir for internal use (paths already printed by cli.py)
        from massgen.logger_config import get_log_session_dir

        log_session_dir = get_log_session_dir()
        if log_session_dir:
            self.log_dir = log_session_dir
            # Setup agent output files (same as RichTerminalDisplay)
            self.output_dir = log_session_dir / "agent_outputs"
            self._setup_agent_files()

        print(f"QUESTION: {question}")
        print("[Coordination in progress - monitor status.json for real-time updates]")

    def _setup_agent_files(self):
        """Setup individual txt files for each agent and system status file."""
        from pathlib import Path

        if not self.output_dir:
            return

        # Create output directory if it doesn't exist
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        # Initialize file paths for each agent
        for agent_id in self.agent_ids:
            file_path = Path(self.output_dir) / f"{agent_id}.txt"
            self.agent_files[agent_id] = file_path
            # Clear existing file content
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"=== {agent_id.upper()} OUTPUT LOG ===\n\n")

        # Initialize system status file
        self.system_status_file = Path(self.output_dir) / "system_status.txt"
        with open(str(self.system_status_file), "w", encoding="utf-8") as f:
            f.write("=== SYSTEM STATUS LOG ===\n\n")

    def update_agent_content(
        self,
        agent_id: str,
        content: str,
        content_type: str = "thinking",
        tool_call_id: str | None = None,
    ):
        """Update content for a specific agent (silent - no output).

        Content is still stored internally and written to files but not printed to stdout.
        Monitor status.json for real-time agent activity.

        Args:
            agent_id: The agent whose content to update
            content: The content to store
            content_type: Type of content (ignored in silent mode)
            tool_call_id: Optional unique ID for tool calls (unused in silent mode)
        """
        if agent_id not in self.agent_ids:
            return

        # Store content internally for potential later use
        self.agent_outputs[agent_id].append(content)

        # Write to agent output file (for sharing/export)
        self._write_to_agent_file(agent_id, content, content_type)
        # But don't print anything to stdout

    def _write_to_agent_file(self, agent_id: str, content: str, content_type: str):
        """Write content to agent's individual txt file."""
        if agent_id not in self.agent_files:
            return

        # Skip debug content from txt files
        if content_type == "debug":
            return

        try:
            file_path = self.agent_files[agent_id]
            # Append to file
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            # Handle file write errors gracefully
            pass

    def update_agent_status(self, agent_id: str, status: str):
        """Update status for a specific agent (silent - no output).

        Status changes are tracked in status.json instead of stdout.

        Args:
            agent_id: The agent whose status to update
            status: New status string
        """
        if agent_id not in self.agent_ids:
            return

        self.agent_status[agent_id] = status
        # Silent - no output to stdout

    def add_orchestrator_event(self, event: str):
        """Add an orchestrator coordination event (silent - no output).

        Events are tracked in coordination_events.json instead of stdout.

        Args:
            event: The coordination event message
        """
        self.orchestrator_events.append(event)
        # Silent - no output to stdout

    def _print_timeline(self, vote_results):
        """Print full timeline with answers, votes, and results.

        Args:
            vote_results: Dictionary containing vote data including:
                - vote_counts: {agent_id: vote_count}
                - voter_details: {voted_for_agent_id: [{voter: voter_id, reason: str}]}
                - winner: winning agent_id
                - is_tie: boolean
        """
        if not vote_results:
            return

        print("\nTIMELINE:")

        # Show individual votes from voter_details
        voter_details = vote_results.get("voter_details", {})
        if voter_details:
            for voted_for, voters in voter_details.items():
                for voter_info in voters:
                    voter = voter_info.get("voter", "unknown")
                    reason = voter_info.get("reason", "")
                    reason_preview = reason[:50] + "..." if len(reason) > 50 else reason
                    print(f"  [VOTE] {voter} -> {voted_for}")
                    if reason_preview:
                        print(f"         Reason: {reason_preview}")

        # Show vote distribution summary
        vote_counts = vote_results.get("vote_counts", {})
        if vote_counts:
            print("  [RESULTS]")
            winner = vote_results.get("winner")
            is_tie = vote_results.get("is_tie", False)
            for agent, count in sorted(vote_counts.items(), key=lambda x: -x[1]):
                winner_mark = " (winner)" if agent == winner else ""
                tie_mark = " (tie-broken)" if is_tie and agent == winner else ""
                print(f"    {agent}: {count} vote{'s' if count != 1 else ''}{winner_mark}{tie_mark}")

    def show_final_answer(self, answer: str, vote_results=None, selected_agent=None):
        """Display the final coordinated answer with essential information.

        Prints:
        - WINNER: The winning agent ID
        - ANSWER_FILE: Path to final answer file
        - DURATION: Total coordination time
        - TIMELINE: Answer submissions, votes, and results
        - ANSWER_PREVIEW: First 200 characters of answer

        Args:
            answer: The final coordinated answer
            vote_results: Dictionary of vote results
            selected_agent: The winning agent ID
        """
        print()  # Blank line for readability

        if selected_agent:
            print(f"WINNER: {selected_agent}")

        if self.log_dir and selected_agent:
            answer_file = self.log_dir / f"final/{selected_agent}/answer.txt"
            print(f"ANSWER_FILE: {answer_file}")

        if self.start_time:
            duration = time.time() - self.start_time
            print(f"DURATION: {duration:.1f}s")

        # Print full timeline
        self._print_timeline(vote_results)

        # Show preview of answer (first 200 chars)
        if answer:
            preview_length = 200
            preview = answer[:preview_length]
            if len(answer) > preview_length:
                preview += "..."
            print(f"ANSWER_PREVIEW: {preview}")

    def show_post_evaluation_content(self, content: str, agent_id: str):
        """Display post-evaluation streaming content (silent - no output).

        Post-evaluation content is logged to files instead of stdout.

        Args:
            content: Post-evaluation content from the agent
            agent_id: The agent performing the evaluation
        """
        # Silent - no output to stdout

    def show_restart_banner(self, reason: str, instructions: str, attempt: int, max_attempts: int):
        """Display restart decision banner (minimal output).

        Prints minimal restart notification for awareness.

        Args:
            reason: Why the restart was triggered
            instructions: Instructions for the next attempt
            attempt: Next attempt number
            max_attempts: Maximum attempts allowed
        """
        print(f"RESTART: Attempt {attempt}/{max_attempts}")

    def show_restart_context_panel(self, reason: str, instructions: str):
        """Display restart context panel (silent - no output).

        Restart context is available in coordination logs.

        Args:
            reason: Why the previous attempt restarted
            instructions: Instructions for this attempt
        """
        # Silent - no output to stdout

    def cleanup(self):
        """Clean up resources and print final summary.

        Prints:
        - COMPLETED: Confirmation message
        - AGENTS: Number of agents that participated
        """
        if self.start_time:
            duration = time.time() - self.start_time
            print(f"\nCOMPLETED: {len(self.agent_ids)} agents, {duration:.1f}s total")
        else:
            print(f"\nCOMPLETED: {len(self.agent_ids)} agents")
