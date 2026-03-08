"""Graceful cancellation handling for MassGen sessions.

This module provides the CancellationManager class that enables graceful
handling of Ctrl+C interrupts, saving partial progress when a session
is cancelled mid-coordination.
"""

import signal
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from .logger_config import logger

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


class CancellationRequested(Exception):
    """Exception raised when user requests cancellation via Ctrl+C.

    This exception allows the caller to handle cancellation gracefully
    without immediately exiting the process. Useful for multi-turn sessions
    where we want to return to the prompt instead of exiting.

    Attributes:
        partial_saved: Whether partial progress was successfully saved
    """

    def __init__(self, partial_saved: bool = False):
        """Initialize the cancellation exception.

        Args:
            partial_saved: Whether partial progress was saved before cancellation
        """
        self.partial_saved = partial_saved
        super().__init__("Cancellation requested by user")


class CancellationManager:
    """Manages graceful cancellation of MassGen sessions.

    When a user presses Ctrl+C during coordination, this manager:
    1. Captures the partial state from the orchestrator
    2. Calls a save callback to persist the partial progress
    3. Raises CancellationRequested (soft) or KeyboardInterrupt (hard) based on mode

    A second Ctrl+C will always force immediate exit without saving.

    Example:
        >>> manager = CancellationManager()
        >>> # For multi-turn (returns to prompt after cancellation)
        >>> manager.register(orchestrator, save_callback, multi_turn=True)
        >>> try:
        ...     # Run coordination
        ...     pass
        ... except CancellationRequested:
        ...     print("Cancelled, returning to prompt")
        ... finally:
        ...     manager.unregister()
    """

    def __init__(self):
        """Initialize the cancellation manager."""
        self._cancelled = False
        self._orchestrator: Optional["Orchestrator"] = None
        self._original_handler = None
        self._save_callback: Callable[[dict[str, Any]], None] | None = None
        self._multi_turn = False
        self._partial_saved = False

    def register(
        self,
        orchestrator: "Orchestrator",
        save_callback: Callable[[dict[str, Any]], None],
        multi_turn: bool = False,
    ) -> None:
        """Register orchestrator for graceful cancellation.

        Args:
            orchestrator: The orchestrator to capture partial state from
            save_callback: Function to call with partial result to save it
            multi_turn: If True, raise CancellationRequested instead of
                KeyboardInterrupt, allowing the caller to return to prompt
                instead of exiting the process.

        Note:
            The save_callback should handle any errors internally.
            If it raises, the error will be logged but cancellation continues.
        """
        self._orchestrator = orchestrator
        self._save_callback = save_callback
        self._cancelled = False
        self._partial_saved = False
        self._multi_turn = multi_turn
        self._original_handler = signal.signal(signal.SIGINT, self._handle_signal)
        # Set reference on orchestrator so coordination UI can check cancellation status
        if orchestrator is not None:
            orchestrator.cancellation_manager = self
        logger.debug(
            f"CancellationManager registered (multi_turn={multi_turn})",
        )

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle SIGINT signal (Ctrl+C).

        First Ctrl+C: Save partial progress and either:
            - In multi-turn mode: Raise CancellationRequested (soft, return to prompt)
            - In single-turn mode: Raise KeyboardInterrupt (hard, exit process)
        Second Ctrl+C: Always force immediate exit with KeyboardInterrupt.

        Args:
            signum: Signal number (always SIGINT)
            frame: Current stack frame
        """
        if self._cancelled:
            # Second Ctrl+C - restore original handler and force exit
            logger.info("Second Ctrl+C received - forcing immediate exit")
            if self._original_handler:
                signal.signal(signal.SIGINT, self._original_handler)
            raise KeyboardInterrupt

        self._cancelled = True
        logger.info("Cancellation requested - attempting to save partial progress")

        # In multi-turn mode, DON'T print here - the Rich Live display is still running
        # and would overwrite our messages. The coordination loop will handle messaging
        # AFTER stopping the display.
        if not self._multi_turn:
            print("\n⚠️  Cancellation requested - saving partial progress...", flush=True)

        self._partial_saved = False
        if self._orchestrator and self._save_callback:
            try:
                partial_result = self._orchestrator.get_partial_result()
                if partial_result:
                    self._save_callback(partial_result)
                    self._partial_saved = True
                    logger.info("Partial progress saved successfully")
                else:
                    logger.info("No partial progress to save")
            except Exception as e:
                if not self._multi_turn:
                    print(f"⚠️  Could not save partial progress: {e}", flush=True)
                logger.warning(f"Failed to save partial progress: {e}")

        # In multi-turn mode, DON'T raise or print - just set flag and let coordination loop detect it
        # This avoids raising exceptions from signal handlers in async code, which can
        # interrupt the event loop at arbitrary points and bypass all exception handlers.
        # The coordination loop will stop the display first, then print messages.
        # In single-turn mode, raise KeyboardInterrupt to exit the process
        if self._multi_turn:
            # DON'T RAISE OR PRINT HERE - the coordination loop will check is_cancelled flag,
            # stop the Rich display, then print the cancellation message
            logger.info("Cancellation flag set - coordination loop will handle it")
        else:
            # Single-turn mode - exit the process
            if self._partial_saved:
                print(
                    "✅ Partial progress saved. Session can be resumed with --continue",
                    flush=True,
                )
            else:
                print(
                    "ℹ️  No partial progress to save (no answers generated yet)",
                    flush=True,
                )
            raise KeyboardInterrupt

    def unregister(self) -> None:
        """Restore original signal handler.

        Should be called in a finally block to ensure cleanup.
        """
        if self._original_handler is not None:
            signal.signal(signal.SIGINT, self._original_handler)
            logger.debug("CancellationManager unregistered, original handler restored")
        self._orchestrator = None
        self._save_callback = None
        self._original_handler = None

    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested.

        Returns:
            True if Ctrl+C has been pressed, False otherwise
        """
        return self._cancelled

    def reset(self) -> None:
        """Reset the cancelled state.

        Useful for multi-turn sessions where you want to allow
        cancellation for each turn independently.
        """
        self._cancelled = False
