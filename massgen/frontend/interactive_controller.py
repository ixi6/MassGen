"""Unified Interactive Session Controller for MassGen."""

import asyncio
import logging
import queue
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TurnResult:
    """Result of executing a single turn.

    Attributes:
        answer_text: The final answer text (may be None if cancelled/error)
        was_cancelled: Whether the turn was cancelled by user
        updated_session_id: Session ID (may be newly created on first turn)
        updated_turn: Turn number after this turn completed
        selected_agent: ID of the winning agent (if applicable)
        vote_results: Vote results dict (if applicable)
        partial_saved: Whether partial progress was saved (on cancellation)
        error: Exception if turn failed
    """

    answer_text: str | None = None
    was_cancelled: bool = False
    updated_session_id: str | None = None
    updated_turn: int = 0
    selected_agent: str | None = None
    vote_results: dict[str, Any] | None = None
    partial_saved: bool = False
    error: Exception | None = None


@dataclass
class CommandResult:
    """Result of executing a slash command.

    Attributes:
        should_exit: Whether the session should exit
        message: Message to display (help/status output)
        reset_session_state: Whether to clear history and reset turn counter
        reset_ui_view: Whether to clear UI panels
        handled: Whether the command was recognized and handled
        ui_action: Optional UI-specific action identifier
        data: Optional additional data for the command result
    """

    should_exit: bool = False
    message: str | None = None
    reset_session_state: bool = False
    reset_ui_view: bool = False
    handled: bool = True
    ui_action: str | None = None
    data: dict[str, Any] | None = None


@dataclass
class SessionContext:
    """Context for the current interactive session.

    Attributes:
        session_id: Unique session identifier
        current_turn: Number of completed turns
        conversation_history: Full conversation history as messages
        previous_turns: Turn metadata for orchestrator
        winning_agents_history: History of winning agents per turn
        agents: Dictionary of agent instances
        config_path: Path to config file (if any)
        original_config: Original config dict (before relocation)
        orchestrator_cfg: Orchestrator configuration dict
        incomplete_turn_workspaces: Dict of agent_id -> workspace path for incomplete turns
    """

    session_id: str | None = None
    current_turn: int = 0
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    previous_turns: list[dict[str, Any]] = field(default_factory=list)
    winning_agents_history: list[dict[str, Any]] = field(default_factory=list)
    agents: dict[str, Any] = field(default_factory=dict)
    config_path: str | None = None
    original_config: dict[str, Any] | None = None
    orchestrator_cfg: dict[str, Any] | None = None
    incomplete_turn_workspaces: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Protocols / Abstract Base Classes
# =============================================================================


class QuestionSource(Protocol):
    """Protocol for input sources that provide questions to the controller.

    Implementations:
    - RichStdinQuestionSource: Reads from stdin using read_multiline_input()
    - TextualThreadQueueQuestionSource: Queue-based for Textual TUI
    """

    async def get_next(self) -> str | None:
        """Get the next question/command from the source.

        Returns:
            The input string, or None if the source is closed/exhausted.
        """
        ...

    def submit(self, text: str) -> None:
        """Submit a question/command to the source (for push-based sources).

        Args:
            text: The input text to submit.
        """
        ...

    def close(self) -> None:
        """Close the source, causing get_next() to return None."""
        ...


class UIAdapter(ABC):
    """Abstract base class for UI adapters that the controller calls.

    Implementations:
    - RichInteractiveAdapter: Prints to stdout using Rich
    - TextualInteractiveAdapter: Updates Textual widgets via call_from_thread
    """

    @abstractmethod
    def set_processing(self, is_processing: bool) -> None:
        """Set whether the controller is currently processing a turn.

        Args:
            is_processing: True when processing, False when idle.
        """

    @abstractmethod
    def on_turn_begin(self, turn: int, question: str) -> None:
        """Called when a turn begins.

        Args:
            turn: The turn number (1-indexed).
            question: The user's question for this turn.
        """

    @abstractmethod
    def on_turn_end(
        self,
        turn: int,
        result: TurnResult,
    ) -> None:
        """Called when a turn ends.

        Args:
            turn: The turn number.
            result: The turn result.
        """

    @abstractmethod
    def reset_turn_view(self) -> None:
        """Reset/clear the UI view for a new turn or after /reset."""

    @abstractmethod
    def notify(self, message: str, level: str = "info") -> None:
        """Display a notification message.

        Args:
            message: The message to display.
            level: Severity level ("info", "warning", "error").
        """

    def update_loading_status(self, message: str) -> None:
        """Update loading status text during initialization.

        Args:
            message: Status message like "Creating agents...", "Starting Docker..."
        """
        # Default: just notify. Subclasses can override for better UX.

    def show_help(self, text: str) -> None:
        """Display help text.

        Args:
            text: The help text to display.
        """
        self.notify(text, "info")

    def show_status(self, text: str) -> None:
        """Display status information.

        Args:
            text: The status text to display.
        """
        self.notify(text, "info")

    def show_inspect(self, text: str) -> None:
        """Display inspection output.

        Args:
            text: The inspection text to display.
        """
        self.notify(text, "info")

    def show_events(self, text: str) -> None:
        """Display coordination events.

        Args:
            text: The events text to display.
        """
        self.notify(text, "info")

    def show_vote(self, text: str) -> None:
        """Display vote results.

        Args:
            text: The vote results text to display.
        """
        self.notify(text, "info")

    def request_exit(self) -> None:
        """Request the UI to exit/close."""


# =============================================================================
# QuestionSource Implementations
# =============================================================================


class RichStdinQuestionSource:
    """Question source that reads from stdin using Rich's multiline input.

    This is used for the Rich terminal UI where input comes from the console.
    """

    def __init__(
        self,
        prompt: str = "\n\033[94m👤 User:\033[0m ",
        read_input_func: Callable[..., str] | None = None,
    ):
        """Initialize the stdin question source.

        Args:
            prompt: The prompt to display when reading input.
            read_input_func: Optional custom input function (for testing).
        """
        self._prompt = prompt
        self._closed = False
        self._read_input_func = read_input_func

    async def get_next(self) -> str | None:
        """Read the next question from stdin.

        Returns:
            The input string, or None if closed or EOF.
        """
        if self._closed:
            return None

        try:
            loop = asyncio.get_event_loop()
            if self._read_input_func:
                text = await loop.run_in_executor(
                    None,
                    self._read_input_func,
                    self._prompt,
                )
            else:
                # Import here to avoid circular imports
                from massgen.cli import read_multiline_input

                text = await loop.run_in_executor(
                    None,
                    read_multiline_input,
                    self._prompt,
                )
            return text
        except EOFError:
            return None
        except KeyboardInterrupt:
            return None

    def submit(self, text: str) -> None:
        """Not supported for stdin source."""
        raise NotImplementedError("RichStdinQuestionSource does not support submit()")

    def close(self) -> None:
        """Close the source."""
        self._closed = True


class TextualThreadQueueQuestionSource:
    """Question source backed by a thread-safe queue for Textual TUI.

    The UI thread calls submit() to push questions, and the orchestration
    thread calls get_next() to receive them.
    """

    _SENTINEL = object()  # Sentinel value to signal close

    def __init__(self):
        """Initialize the queue-based question source."""
        self._queue: queue.Queue = queue.Queue()
        self._closed = False

    async def get_next(self) -> str | None:
        """Get the next question from the queue.

        Returns:
            The input string, or None if closed.
        """
        if self._closed:
            return None

        try:
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(None, self._queue.get)

            if item is self._SENTINEL:
                self._closed = True
                return None

            return item
        except (EOFError, KeyboardInterrupt):
            return None

    def submit(self, text: str) -> None:
        """Submit a question to the queue.

        Args:
            text: The input text to submit.
        """
        if not self._closed:
            self._queue.put(text)

    def close(self) -> None:
        """Close the source by sending sentinel."""
        if not self._closed:
            self._closed = True
            self._queue.put(self._SENTINEL)


# =============================================================================
# UIAdapter Implementations
# =============================================================================


class RichInteractiveAdapter(UIAdapter):
    """UI adapter for Rich terminal output.

    Prints banners, help, status, and turn information to stdout using Rich.
    """

    # ANSI color codes
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_BLUE = "\033[94m"
    RESET = "\033[0m"

    def __init__(self, agents: dict[str, Any], config_path: str | None = None):
        """Initialize the Rich adapter.

        Args:
            agents: Dictionary of agent instances.
            config_path: Path to config file (if any).
        """
        self._agents = agents
        self._config_path = config_path
        self._is_processing = False

    def set_processing(self, is_processing: bool) -> None:
        """Set processing state."""
        self._is_processing = is_processing
        if is_processing:
            print(f"\n🔄 {self.BRIGHT_YELLOW}Processing...{self.RESET}", flush=True)

    def on_turn_begin(self, turn: int, question: str) -> None:
        """Called when a turn begins."""
        print(f"\n{self.BRIGHT_CYAN}{'='*60}{self.RESET}", flush=True)
        print(f"{self.BRIGHT_CYAN}   Turn {turn}{self.RESET}", flush=True)
        print(f"{self.BRIGHT_CYAN}{'='*60}{self.RESET}", flush=True)

    def on_turn_end(self, turn: int, result: TurnResult) -> None:
        """Called when a turn ends."""
        if result.was_cancelled:
            if result.partial_saved:
                print(
                    f"\n{self.BRIGHT_YELLOW}⏸️  Turn cancelled. Partial progress saved.{self.RESET}",
                    flush=True,
                )
            else:
                print(
                    f"\n{self.BRIGHT_YELLOW}⏸️  Turn cancelled.{self.RESET}",
                    flush=True,
                )
            print(
                f"{self.BRIGHT_CYAN}Enter your next question or /quit to exit.{self.RESET}",
                flush=True,
            )
        elif result.error:
            print(f"❌ Error: {result.error}", flush=True)
            print("Please try again or type /quit to exit.", flush=True)
        elif result.answer_text:
            from rich.console import Console
            from rich.panel import Panel

            console = Console()
            console.print()
            console.print(
                Panel(
                    result.answer_text,
                    title="[bold green]🤖 MassGen[/bold green]",
                    border_style="green",
                    padding=(1, 2),
                ),
            )
            console.print(
                f"\n[green]✅ Complete![/green] [cyan]💭 History: {turn} exchanges[/cyan]",
            )
            console.print("[dim]Tip: Use /inspect to view agent outputs[/dim]")
        else:
            print(f"\n{self.BRIGHT_RED}❌ No response generated{self.RESET}", flush=True)

    def reset_turn_view(self) -> None:
        """Reset the view (no-op for Rich, just print confirmation)."""
        print(
            f"{self.BRIGHT_YELLOW}🔄 Conversation history cleared!{self.RESET}",
            flush=True,
        )

    def notify(self, message: str, level: str = "info") -> None:
        """Display a notification."""
        if level == "error":
            print(f"❌ {message}", flush=True)
        elif level == "warning":
            print(f"⚠️  {message}", flush=True)
        else:
            print(message, flush=True)

    def show_help(self, text: str) -> None:
        """Display help text."""
        print(f"\n{self.BRIGHT_CYAN}📚 Available Commands:{self.RESET}", flush=True)
        print(text, flush=True)

    def show_status(self, text: str) -> None:
        """Display status information."""
        print(f"\n{self.BRIGHT_CYAN}📊 Current Status:{self.RESET}", flush=True)
        print(text, flush=True)

    def request_exit(self) -> None:
        """Request exit (no-op for Rich, handled by controller)."""
        print("👋 Goodbye!", flush=True)


class TextualInteractiveAdapter(UIAdapter):
    """UI adapter for Textual TUI.

    All widget mutations go through the display's thread-safe helpers.
    """

    def __init__(self, display: Any):
        """Initialize the Textual adapter.

        Args:
            display: The TextualTerminalDisplay instance.
        """
        self._display = display
        self._is_processing = False

    def set_processing(self, is_processing: bool) -> None:
        """Set processing state and update UI."""
        self._is_processing = is_processing
        if self._display and self._display._app:
            self._display._call_app_method("set_input_enabled", not is_processing)

    def on_turn_begin(self, turn: int, question: str) -> None:
        """Called when a turn begins."""
        if self._display:
            self._display.current_turn = turn
            if self._display._app:
                self._display._call_app_method("update_turn_header", turn, question)

    def on_turn_end(self, turn: int, result: TurnResult) -> None:
        """Called when a turn ends."""
        logger.info(f"[TextualAdapter] on_turn_end called: turn={turn}, cancelled={result.was_cancelled}, error={result.error}")
        self.set_processing(False)

        # Check if this was a planning turn completion
        # _mode_state is on the Textual App (AgentPanel), accessed via _display._app
        if self._display and self._display._app and hasattr(self._display._app, "_mode_state"):
            mode_state = self._display._app._mode_state
            logger.info(f"[TextualAdapter] plan_mode={mode_state.plan_mode}, has_answer={bool(result.answer_text)}")
            if mode_state.plan_mode in ("plan", "spec") and result.answer_text and not result.was_cancelled and not result.error:
                # Planning completed - trigger approval flow
                logger.info("[TextualAdapter] Triggering plan approval flow")
                self._trigger_plan_approval(result, mode_state)
                return
            if mode_state.plan_mode in ("plan", "spec") and getattr(mode_state, "quick_edit_restore_pending", False) and (result.was_cancelled or result.error):
                restore_mode = mode_state.quick_edit_prev_agent_mode or "multi"
                restore_selected = mode_state.quick_edit_prev_selected_agent
                mode_state.agent_mode = restore_mode
                mode_state.selected_single_agent = restore_selected
                mode_state.quick_edit_prev_agent_mode = None
                mode_state.quick_edit_prev_selected_agent = None
                mode_state.quick_edit_restore_pending = False
                if self._display:
                    self._display._call_app_method(
                        "_set_agent_mode_visual_state",
                        restore_mode,
                        restore_selected,
                    )
            if mode_state.plan_mode == "execute" and mode_state.plan_session and not result.was_cancelled and not result.error:
                self._update_execute_chunk_progress(result, mode_state)
            if mode_state.plan_mode == "analysis" and result.answer_text and not result.was_cancelled and not result.error:
                analysis_profile = getattr(mode_state.analysis_config, "profile", "dev")
                if analysis_profile == "user":
                    self._display._call_app_method(
                        "_detect_new_skills_from_analysis",
                    )

        if result.was_cancelled:
            self.notify("Turn cancelled", "warning")
        elif result.error:
            self.notify(f"Error: {result.error}", "error")

    def _trigger_plan_approval(self, result: TurnResult, mode_state: Any) -> None:
        """Show plan approval modal after planning completes.

        Args:
            result: The turn result from planning
            mode_state: TuiModeState instance
        """
        logger.info("[TextualAdapter] _trigger_plan_approval called")
        plan_result = self._find_plan_from_workspace()

        if not plan_result:
            logger.warning("[TextualAdapter] No plan found in workspace")
            self.notify("Planning completed but no plan found", "warning")
            mode_state.reset_plan_state()
            if self._display and self._display._app and hasattr(self._display._app, "_mode_bar"):
                self._display._call_app_method("_update_mode_bar_plan_mode", "normal")
            return

        plan_path, plan_data = plan_result
        # Support both plan (tasks) and spec (requirements) artifacts
        tasks = plan_data.get("tasks", [])
        requirements = plan_data.get("requirements", [])
        items = tasks or requirements
        logger.info(f"[TextualAdapter] Found artifact with {len(items)} items at {plan_path}")

        if not items:
            artifact_label = "spec" if requirements else "plan"
            self.notify(f"{artifact_label.capitalize()} has no items", "warning")
            mode_state.reset_plan_state()
            if self._display and self._display._app and hasattr(self._display._app, "_mode_bar"):
                self._display._call_app_method("_update_mode_bar_plan_mode", "normal")
            return

        # Track planning revisions/iterations for iterative review flow.
        mode_state.plan_revision = (getattr(mode_state, "plan_revision", 0) or 0) + 1
        mode_state.planning_iteration_count = (getattr(mode_state, "planning_iteration_count", 0) or 0) + 1

        # Show modal via display
        # For spec artifacts, pass requirements as tasks for the approval modal
        if self._display:
            logger.info("[TextualAdapter] Calling show_plan_approval_modal")
            self._display.show_plan_approval_modal(items, plan_path, plan_data, mode_state)

    def _find_plan_from_workspace(
        self,
        *,
        prefer_execution_scope: bool = False,
    ) -> tuple | None:
        """Find and parse plan.json or spec.json from agent workspace.

        Returns:
            Tuple of (plan_path, plan_data) if found, None otherwise.
            On JSON parse errors, logs the error and continues searching.
        """
        import json

        try:
            from massgen.logger_config import get_log_session_dir

            # Use get_log_session_dir() which includes turn/attempt subdirs
            log_dir = get_log_session_dir()
            final_dir = log_dir / "final"

            if not final_dir.exists():
                logger.debug(f"[PlanApproval] Final dir not found: {final_dir}")
                return None

            # Track JSON errors to report if no valid plan found
            json_errors = []

            # Check agent workspaces for plan or spec
            for agent_dir in final_dir.glob("agent_*/workspace"):
                if prefer_execution_scope:
                    search_order = [
                        agent_dir / "tasks" / "plan.json",
                        agent_dir / "plan.json",
                        agent_dir / "deliverable" / "project_plan.json",
                        agent_dir / "project_plan.json",
                        agent_dir / "tasks" / "spec.json",
                        agent_dir / "spec.json",
                        agent_dir / "deliverable" / "project_spec.json",
                        agent_dir / "project_spec.json",
                    ]
                else:
                    search_order = [
                        agent_dir / "deliverable" / "project_plan.json",
                        agent_dir / "project_plan.json",
                        agent_dir / "tasks" / "plan.json",
                        agent_dir / "deliverable" / "project_spec.json",
                        agent_dir / "project_spec.json",
                        agent_dir / "tasks" / "spec.json",
                    ]

                for plan_location in search_order:
                    if plan_location.exists():
                        try:
                            plan_data = json.loads(plan_location.read_text())
                            # Accept either "tasks" (plan) or "requirements" (spec)
                            if "tasks" in plan_data or "requirements" in plan_data:
                                logger.info(f"[PlanApproval] Found artifact at {plan_location}")
                                return plan_location, plan_data
                            else:
                                logger.warning(
                                    f"[PlanApproval] Artifact file missing 'tasks'/'requirements' key: {plan_location}",
                                )
                        except json.JSONDecodeError as e:
                            error_msg = f"{plan_location.name}: {e}"
                            json_errors.append(error_msg)
                            logger.warning(
                                f"[PlanApproval] Corrupted artifact file at {plan_location}: {e}",
                            )
                            continue

            # Log all JSON errors if we failed to find a valid plan
            if json_errors:
                logger.error(
                    f"[PlanApproval] Found artifact file(s) but all had JSON errors: {json_errors}",
                )

            logger.debug("[PlanApproval] No valid plan/spec found in any agent workspace")
            return None
        except Exception as e:
            logger.error(f"[PlanApproval] Error finding plan: {e}")
            return None

    def _merge_chunk_updates_into_workspace(
        self,
        plan_session: Any,
        chunk_tasks: list[dict[str, Any]],
    ) -> None:
        """Merge chunk task updates into workspace/plan.json for checkpoint persistence."""
        import json

        workspace_plan_file = plan_session.workspace_dir / "plan.json"
        if not workspace_plan_file.exists():
            return
        try:
            payload = json.loads(workspace_plan_file.read_text())
        except Exception:
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
            return

        by_id = {str(task.get("id", "")).strip(): task for task in payload.get("tasks", []) if isinstance(task, dict)}
        for task in chunk_tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", "")).strip()
            if not task_id or task_id not in by_id:
                continue
            by_id[task_id].update(task)

        workspace_plan_file.write_text(json.dumps(payload, indent=2))

    def _update_execute_chunk_progress(self, result: TurnResult, mode_state: Any) -> None:
        """Checkpoint chunk execution progress after an execute-mode turn."""
        from massgen.plan_execution import (
            evaluate_chunk_progress,
            mark_session_resumable,
            record_chunk_checkpoint,
        )

        plan_result = self._find_plan_from_workspace(prefer_execution_scope=True)
        if not plan_result:
            logger.warning("[TextualAdapter] Execute turn completed but no chunk plan found in workspace")
            return

        _plan_path, plan_data = plan_result
        chunk_tasks = plan_data.get("tasks", []) if isinstance(plan_data, dict) else []
        if not isinstance(chunk_tasks, list):
            chunk_tasks = []

        plan_session = mode_state.plan_session
        metadata = plan_session.load_metadata()
        active_chunk = metadata.current_chunk
        if not active_chunk:
            return

        progress = evaluate_chunk_progress(chunk_tasks)
        self._merge_chunk_updates_into_workspace(plan_session, chunk_tasks)

        retry_counts: dict[str, int] = {}
        if isinstance(metadata.resumable_state, dict):
            saved = metadata.resumable_state.get("retry_counts", {})
            if isinstance(saved, dict):
                for chunk_name, retry_value in saved.items():
                    try:
                        retry_counts[str(chunk_name)] = int(retry_value)
                    except Exception:
                        continue

        attempt = retry_counts.get(active_chunk, 0) + 1

        if progress["is_complete"]:
            retry_counts[active_chunk] = 0
            updated = record_chunk_checkpoint(
                plan_session,
                chunk=active_chunk,
                status="completed",
                attempt=attempt,
                progress=progress,
            )

            if updated.current_chunk:
                mark_session_resumable(
                    plan_session,
                    current_chunk=updated.current_chunk,
                    reason="awaiting_next_chunk_execution",
                    retry_counts=retry_counts,
                )
                auto_continue = True
                try:
                    auto_continue = bool(
                        getattr(mode_state.plan_config, "execute_auto_continue_chunks", True),
                    )
                except Exception:
                    auto_continue = True

                if self._display:
                    self._display._call_app_method(
                        "_show_chunk_advance_modal",
                        active_chunk,
                        updated.current_chunk,
                        auto_continue,
                    )
                else:
                    self.notify(
                        f"Chunk complete: {active_chunk}. Next: {updated.current_chunk}",
                        "info",
                    )
            else:
                self.notify("All chunks completed for this plan.", "info")
                if self._display:
                    self._display._call_app_method("_handle_plan_mode_change", "normal")
        else:
            retry_counts[active_chunk] = retry_counts.get(active_chunk, 0) + 1
            record_chunk_checkpoint(
                plan_session,
                chunk=active_chunk,
                status="incomplete",
                attempt=attempt,
                progress=progress,
            )
            mark_session_resumable(
                plan_session,
                current_chunk=active_chunk,
                reason="chunk_incomplete",
                retry_counts=retry_counts,
            )
            self.notify(
                f"Chunk incomplete: {active_chunk} ({progress['completed_count']}/{progress['total_tasks']})",
                "warning",
            )

    def reset_turn_view(self) -> None:
        """Reset agent panels."""
        if self._display and self._display._app:
            self._display._call_app_method("_reset_agent_panels")

    def notify(self, message: str, level: str = "info") -> None:
        """Display a notification via Textual."""
        if self._display and self._display._app:
            severity = "warning" if level == "warning" else "error" if level == "error" else "information"
            self._display._call_app_method("notify", message, severity=severity)

    def update_loading_status(self, message: str) -> None:
        """Update loading status text on all agent panels."""
        if self._display:
            self._display.update_loading_status(message)

    def show_help(self, text: str) -> None:
        """Show help modal."""
        if self._display and self._display._app:
            self._display._call_app_method("_show_help_modal")

    def show_status(self, text: str) -> None:
        """Show status modal."""
        if self._display and self._display._app:
            self._display._call_app_method("_show_system_status_modal")

    def show_events(self, text: str) -> None:
        """Show orchestrator events modal."""
        if self._display and self._display._app:
            self._display._call_app_method("_show_orchestrator_modal")

    def show_vote(self, text: str) -> None:
        """Show vote results modal."""
        if self._display and self._display._app:
            self._display._call_app_method("action_open_vote_results")

    def request_exit(self) -> None:
        """Request Textual app to exit."""
        if self._display and self._display._app:
            self._display._call_app_method("exit")

    def request_cancel_turn(self) -> None:
        """Request cancellation of the current turn.

        Sets the quit flag on the display which will be detected by
        CoordinationUI and raise CancellationRequested.
        """
        if self._display:
            self._display.request_cancellation()


# =============================================================================
# Slash Command Dispatcher
# =============================================================================


class SlashCommandDispatcher:
    """Centralized slash command parsing and dispatch.

    This is the single source of truth for all slash commands, eliminating
    drift between Rich and Textual implementations.
    """

    # Help text for all commands - single source of truth
    HELP_TEXT = """   /quit, /exit, /q     - Exit the program
   /reset, /clear       - Clear conversation history
   /cancel              - Cancel the current turn (saves partial progress)
   /help, /h            - Show this help message
   /status              - Show current status
   /config              - Open config file in editor
   /context             - Add/modify context paths for file access
   /inspect, /i         - View agent outputs
     /inspect           - Current turn outputs
     /inspect <N>       - View turn N outputs
     /inspect all       - List all session turns
   /output [agent]      - Show full agent output (modal view)
     /output            - Select from agent list
     /output Agent_1    - View specific agent output
   /events [N]          - Show last N coordination events (default: 5)
   /vote                - Show vote results for last turn
   /cost, /c            - Show token usage and cost breakdown
   /workspace, /w       - List workspace files
   /metrics, /m         - Show tool execution metrics
   /mcp, /p             - Show MCP server status
   /answers, /b         - Browse all answers submitted
   /timeline, /t        - Show coordination timeline
   /files, /w           - Browse workspace files from answers
   /browser, /u         - Unified browser (Answers/Votes/Workspace/Timeline tabs)
   /skills, /k          - Open skills manager (session skill toggles)
   /vim                 - Toggle vim mode (hjkl navigation, i to insert)

💡 Input:
   Enter            - Submit your question
   Shift+Enter      - New line
   Ctrl+C / Ctrl+D  - Quit"""

    @staticmethod
    def build_help_text() -> str:
        """Build canonical help text for all UIs."""
        return SlashCommandDispatcher.HELP_TEXT

    def __init__(
        self,
        context: SessionContext,
        adapter: UIAdapter,
        on_agents_reload: Callable[[], None] | None = None,
    ):
        """Initialize the command dispatcher.

        Args:
            context: The session context.
            adapter: The UI adapter for output.
            on_agents_reload: Callback when agents need to be reloaded.
        """
        self._context = context
        self._adapter = adapter
        self._on_agents_reload = on_agents_reload

    def dispatch(self, command_text: str) -> CommandResult:
        """Parse and dispatch a slash command.

        Args:
            command_text: The full command text (including leading /).

        Returns:
            CommandResult with the outcome of the command.
        """
        parts = command_text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            return self._handle_quit()
        elif cmd in ("/reset", "/clear"):
            return self._handle_reset()
        elif cmd in ("/help", "/h", "/?"):
            return self._handle_help()
        elif cmd == "/status":
            return self._handle_status()
        elif cmd == "/config":
            return self._handle_config()
        elif cmd == "/context":
            return self._handle_context()
        elif cmd in ("/inspect", "/i"):
            return self._handle_inspect(args)
        elif cmd == "/cancel":
            return self._handle_cancel()
        elif cmd in ("/events", "/o"):
            return self._handle_events(args)
        elif cmd in ("/vote", "/v"):
            return self._handle_vote(args)
        elif cmd in ("/cost", "/c"):
            return self._handle_cost()
        elif cmd in ("/workspace", "/w"):
            return self._handle_workspace()
        elif cmd in ("/metrics", "/m"):
            return self._handle_metrics()
        elif cmd in ("/mcp", "/p"):
            return self._handle_mcp()
        elif cmd in ("/answers", "/b"):
            return self._handle_answers()
        elif cmd in ("/timeline", "/t"):
            return self._handle_timeline()
        elif cmd == "/files":
            return self._handle_files()
        elif cmd in ("/browser", "/u"):
            return self._handle_browser()
        elif cmd in ("/skills", "/k"):
            return self._handle_skills()
        elif cmd == "/vim":
            return self._handle_vim()
        # TODO: Re-enable /theme command when additional themes are ready
        # elif cmd == "/theme":
        #     return self._handle_theme()
        else:
            return CommandResult(
                handled=False,
                message=f"❓ Unknown command: {cmd}\n💡 Type /help for available commands",
            )

    def _handle_quit(self) -> CommandResult:
        """Handle /quit command."""
        return CommandResult(should_exit=True, message="👋 Goodbye!")

    def _handle_cancel(self) -> CommandResult:
        """Handle /cancel command - cancel the current turn."""
        return CommandResult(
            ui_action="cancel_turn",
            message="⏸️ Cancelling current turn...",
        )

    def _handle_reset(self) -> CommandResult:
        """Handle /reset command."""
        return CommandResult(
            reset_session_state=True,
            reset_ui_view=True,
            message="🔄 Conversation history cleared!",
        )

    def _handle_help(self) -> CommandResult:
        """Handle /help command."""
        return CommandResult(
            message=self.HELP_TEXT,
            ui_action="show_help",
        )

    def _handle_status(self) -> CommandResult:
        """Handle /status command."""
        agents = self._context.agents
        config_path = self._context.config_path
        history = self._context.conversation_history

        status_lines = [
            f"   Agents: {len(agents)} ({', '.join(agents.keys())})",
        ]

        if len(agents) == 1:
            mode_display = "Single Agent (Orchestrator)"
        else:
            mode_display = "Multi-Agent"
        status_lines.append(f"   Mode: {mode_display}")
        status_lines.append(f"   History: {len(history)//2} exchanges")

        if config_path:
            status_lines.append(f"   Config: {config_path}")

        return CommandResult(
            message="\n".join(status_lines),
            ui_action="show_status",
        )

    def _handle_config(self) -> CommandResult:
        """Handle /config command."""
        config_path = self._context.config_path
        if not config_path:
            return CommandResult(
                message="❌ No config file available (using CLI arguments)",
            )

        import platform
        import subprocess

        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.run(["open", config_path])
            elif system == "Windows":
                subprocess.run(["start", config_path], shell=True)
            else:  # Linux and others
                subprocess.run(["xdg-open", config_path])
            return CommandResult(message=f"📝 Opening config file: {config_path}")
        except Exception as e:
            return CommandResult(
                message=f"❌ Error opening config file: {e}\n   Config location: {config_path}",
            )

    def _handle_context(self) -> CommandResult:
        """Handle /context command."""
        if not self._context.original_config or not self._context.orchestrator_cfg:
            return CommandResult(
                message="Context paths require a config file with orchestrator settings.",
            )

        return CommandResult(
            ui_action="prompt_context_paths",
            data={
                "original_config": self._context.original_config,
                "orchestrator_cfg": self._context.orchestrator_cfg,
            },
        )

    def _handle_inspect(self, args: str) -> CommandResult:
        """Handle /inspect command."""
        session_id = self._context.session_id
        current_turn = self._context.current_turn

        if not args:
            target_turn = current_turn
        elif args.lower() == "all":
            return CommandResult(
                ui_action="list_all_turns",
                data={"session_id": session_id, "current_turn": current_turn},
            )
        else:
            try:
                target_turn = int(args)
                if target_turn < 1 or target_turn > current_turn:
                    return CommandResult(
                        message=f"Turn {target_turn} not found. Available: 1-{current_turn}",
                    )
            except ValueError:
                return CommandResult(
                    message="Invalid turn number. Usage: /inspect [turn_number|all]",
                )

        if target_turn == 0:
            return CommandResult(
                message="No turns completed yet. Complete a turn first.",
            )

        return CommandResult(
            ui_action="show_turn_inspection",
            data={
                "session_id": session_id,
                "target_turn": target_turn,
                "agents": self._context.agents,
            },
        )

    def _handle_events(self, args: str) -> CommandResult:
        """Handle /events command - show coordination events for the session."""
        turns = self._context.previous_turns or []
        if not turns:
            return CommandResult(
                message="No coordination events recorded yet.",
                ui_action="show_status",
            )

        try:
            limit = int(args) if args.strip() else 5
        except ValueError:
            limit = 5

        recent = turns[-limit:]
        lines = ["📋 Recent coordination events:"]
        for t in recent:
            turn_no = t.get("turn", "?")
            status = t.get("status", "completed")
            winner = t.get("selected_agent") or t.get("winner") or "N/A"
            lines.append(f"  • Turn {turn_no}: status={status}, winner={winner}")

        return CommandResult(
            message="\n".join(lines),
            ui_action="show_events",
        )

    def _handle_vote(self, args: str) -> CommandResult:
        """Handle /vote command - show vote results for the last turn."""
        if not self._context.previous_turns:
            return CommandResult(
                message="No turns completed yet. Complete at least one turn to see vote results.",
                ui_action="show_status",
            )

        last_turn = self._context.previous_turns[-1]
        turn_no = last_turn.get("turn", "?")
        vote_results = last_turn.get("vote_results", {})
        winner = last_turn.get("selected_agent") or last_turn.get("winner") or "N/A"

        if not vote_results:
            return CommandResult(
                message=f"🗳️ Turn {turn_no}: No vote data available. Winner: {winner}",
                ui_action="show_vote",
            )

        lines = [f"🗳️ Vote Results for Turn {turn_no}:"]
        lines.append(f"  Winner: {winner}")
        lines.append("")

        for agent_id, votes in vote_results.items():
            if isinstance(votes, dict):
                score = votes.get("score", votes.get("votes", 0))
                lines.append(f"  • {agent_id}: {score}")
            else:
                lines.append(f"  • {agent_id}: {votes}")

        return CommandResult(
            message="\n".join(lines),
            ui_action="show_vote",
        )

    def _handle_cost(self) -> CommandResult:
        """Handle /cost command - show token usage and cost breakdown."""
        return CommandResult(
            message="Opening cost breakdown...",
            ui_action="show_cost",
        )

    def _handle_workspace(self) -> CommandResult:
        """Handle /workspace command - show workspace files."""
        return CommandResult(
            message="Opening workspace files...",
            ui_action="show_workspace",
        )

    def _handle_metrics(self) -> CommandResult:
        """Handle /metrics command - show tool execution metrics."""
        return CommandResult(
            message="Opening tool metrics...",
            ui_action="show_metrics",
        )

    def _handle_mcp(self) -> CommandResult:
        """Handle /mcp command - show MCP server status."""
        return CommandResult(
            message="Opening MCP server status...",
            ui_action="show_mcp",
        )

    def _handle_answers(self) -> CommandResult:
        """Handle /answers command - open answer browser modal."""
        return CommandResult(
            message="Opening answer browser...",
            ui_action="show_answers",
        )

    def _handle_timeline(self) -> CommandResult:
        """Handle /timeline command - show coordination timeline."""
        return CommandResult(
            message="Opening coordination timeline...",
            ui_action="show_timeline",
        )

    def _handle_files(self) -> CommandResult:
        """Handle /files command - browse workspace files from answer snapshots."""
        return CommandResult(
            message="Opening workspace file browser...",
            ui_action="show_files",
        )

    def _handle_browser(self) -> CommandResult:
        """Handle /browser command - open unified browser with all tabs."""
        return CommandResult(
            message="Opening unified browser...",
            ui_action="show_browser",
        )

    def _handle_skills(self) -> CommandResult:
        """Handle /skills command - open skills manager modal."""
        return CommandResult(
            message="Opening skills manager...",
            ui_action="show_skills",
        )

    def _handle_vim(self) -> CommandResult:
        """Handle /vim command - toggle vim mode in input."""
        return CommandResult(
            handled=True,
            ui_action="toggle_vim",
        )

    # TODO: Re-enable when additional themes are ready
    # def _handle_theme(self) -> CommandResult:
    #     """Handle /theme command - toggle light/dark theme."""
    #     return CommandResult(
    #         handled=True,
    #         ui_action="toggle_theme",
    #     )


# =============================================================================
# Interactive Session Controller
# =============================================================================


class InteractiveSessionController:
    """Unified controller for multi-turn interactive sessions.

    This controller owns the session loop and delegates to:
    - QuestionSource for input
    - UIAdapter for output
    - SlashCommandDispatcher for commands
    - Turn runner for orchestration
    """

    def __init__(
        self,
        question_source: QuestionSource,
        adapter: UIAdapter,
        context: SessionContext,
        turn_runner: Callable[..., TurnResult],
        ui_config: dict[str, Any] | None = None,
        debug: bool = False,
    ):
        """Initialize the controller.

        Args:
            question_source: Source for user input.
            adapter: UI adapter for output.
            context: Session context with state.
            turn_runner: Async function to run a single turn.
            ui_config: UI configuration dict.
            debug: Whether debug mode is enabled.
        """
        self._question_source = question_source
        self._adapter = adapter
        self._context = context
        self._turn_runner = turn_runner
        self._ui_config = ui_config or {}
        self._debug = debug

        # Create command dispatcher
        self._command_dispatcher = SlashCommandDispatcher(
            context=context,
            adapter=adapter,
        )

        # Running state
        self._running = False

    @property
    def session_id(self) -> str | None:
        """Get the current session ID."""
        return self._context.session_id

    @property
    def current_turn(self) -> int:
        """Get the current turn number."""
        return self._context.current_turn

    @property
    def conversation_history(self) -> list[dict[str, str]]:
        """Get the conversation history."""
        return self._context.conversation_history

    async def run(self) -> None:
        """Run the interactive session loop.

        This is the main entry point for the controller. It loops until
        the user exits or the question source is closed.
        """
        self._running = True

        try:
            while self._running:
                # Get next input
                text = await self._question_source.get_next()

                if text is None:
                    break

                text = text.strip()
                if not text:
                    self._adapter.notify(
                        "Please enter a question or type /help for commands.",
                    )
                    continue

                if text.startswith("/"):
                    result = self._command_dispatcher.dispatch(text)
                    await self._handle_command_result(result)
                    if result.should_exit:
                        break
                    continue

                if text.lower() in ("quit", "exit", "q"):
                    self._adapter.request_exit()
                    break

                if text.lower() in ("reset", "clear"):
                    await self._handle_reset()
                    continue

                await self._run_turn(text)

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

    async def _handle_command_result(self, result: CommandResult) -> None:
        """Handle the result of a slash command.

        Args:
            result: The command result to handle.
        """
        if result.reset_session_state:
            await self._handle_reset()

        if result.reset_ui_view:
            self._adapter.reset_turn_view()

        if result.message:
            if result.ui_action == "show_help":
                self._adapter.show_help(result.message)
            elif result.ui_action == "show_status":
                self._adapter.show_status(result.message)
            elif result.ui_action == "show_events":
                self._adapter.show_events(result.message)
            elif result.ui_action == "show_vote":
                self._adapter.show_vote(result.message)
            else:
                self._adapter.notify(result.message)

        is_textual = isinstance(self._adapter, TextualInteractiveAdapter)

        if result.ui_action == "show_turn_inspection":
            data = result.data or {}
            if is_textual:
                self._adapter.notify("Use 'i' key to open agent selector for inspection")
            else:
                session_id = data.get("session_id")
                target_turn = data.get("target_turn", 0)
                agents = data.get("agents", {})
                from massgen.cli import _show_turn_inspection

                _show_turn_inspection(session_id, target_turn, agents)

        elif result.ui_action == "list_all_turns":
            data = result.data or {}
            if is_textual:
                current_turn = data.get("current_turn", 0)
                self._adapter.notify(f"Session has {current_turn} completed turn(s). Use 'i' for inspection.")
            else:
                session_id = data.get("session_id")
                current_turn = data.get("current_turn", 0)
                from rich.console import Console

                from massgen.cli import _list_all_turns

                _list_all_turns(session_id, current_turn, Console())

        elif result.ui_action == "prompt_context_paths":
            if is_textual:
                self._adapter.notify("Context path modification not available in Textual mode. Use Rich mode or edit config file.")
            else:
                data = result.data or {}
                original_config = data.get("original_config")
                orchestrator_cfg = data.get("orchestrator_cfg")
                from massgen.cli import prompt_for_context_paths

                config_modified = prompt_for_context_paths(original_config, orchestrator_cfg)
                if config_modified:
                    self._adapter.notify("Context paths updated. Agents will be reloaded on next turn.")

        elif result.ui_action == "cancel_turn":
            if is_textual and hasattr(self._adapter, "request_cancel_turn"):
                self._adapter.request_cancel_turn()
            else:
                self._adapter.notify("Cancel is only available during an active turn in Textual mode.")
        elif result.ui_action == "show_skills":
            if is_textual and isinstance(self._adapter, TextualInteractiveAdapter):
                display = getattr(self._adapter, "_display", None)
                if display:
                    display._call_app_method("_show_skills_modal")
            else:
                self._adapter.notify("Skills manager is available in Textual mode.")

        if result.should_exit:
            self._adapter.request_exit()

    async def _handle_reset(self) -> None:
        """Handle session reset."""
        self._context.conversation_history.clear()
        self._context.current_turn = 0

        for agent in self._context.agents.values():
            if hasattr(agent, "reset"):
                agent.reset()

    async def _run_turn(self, question: str) -> None:
        """Run a single turn with the given question.

        Args:
            question: The user's question.
        """
        next_turn = self._context.current_turn + 1

        self._adapter.set_processing(True)
        self._adapter.on_turn_begin(next_turn, question)

        try:
            session_info = {
                "session_id": self._context.session_id,
                "current_turn": self._context.current_turn,
                "previous_turns": self._context.previous_turns,
                "winning_agents_history": self._context.winning_agents_history,
                "multi_turn": True,
            }

            result = await self._turn_runner(
                question=question,
                agents=self._context.agents,
                ui_config=self._ui_config,
                conversation_history=self._context.conversation_history,
                session_info=session_info,
            )

            if result.updated_session_id:
                self._context.session_id = result.updated_session_id
            if result.updated_turn > 0:
                self._context.current_turn = result.updated_turn

            if result.answer_text and not result.was_cancelled:
                self._context.conversation_history.append(
                    {"role": "user", "content": question},
                )
                self._context.conversation_history.append(
                    {"role": "assistant", "content": result.answer_text},
                )
            elif result.was_cancelled:
                # Preserve the submitted prompt so queued/fallback input survives
                # into future turns even when this turn is cancelled.
                self._context.conversation_history.append(
                    {"role": "user", "content": question},
                )

            self._adapter.on_turn_end(self._context.current_turn, result)

        except Exception as e:
            logger.exception(f"Error running turn: {e}")
            result = TurnResult(error=e)
            self._adapter.on_turn_end(next_turn, result)

        finally:
            self._adapter.set_processing(False)

    def stop(self) -> None:
        """Stop the controller loop."""
        self._running = False
        self._question_source.close()
