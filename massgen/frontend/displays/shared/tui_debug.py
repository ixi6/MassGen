"""TUI debug logging utilities.

Single source of truth for TUI debug logging. Previously located in:
- base_tui_layout.py:63-69

This module provides utilities for debug logging to a separate file,
useful for debugging TUI issues without affecting the main display.
"""

import logging
import os
import tempfile

_DEBUG_ENV = "MASSGEN_TUI_DEBUG"


def tui_debug_enabled() -> bool:
    """Return True when TUI debug logging is enabled via env."""
    return os.environ.get(_DEBUG_ENV, "").lower() in ("1", "true", "yes", "on")


def get_tui_debug_logger() -> logging.Logger:
    """Get or create TUI debug logger.

    Returns:
        Logger instance configured for TUI debugging.
    """
    logger = logging.getLogger("tui_debug")

    if not tui_debug_enabled():
        # Disable logging entirely when not enabled.
        logger.disabled = True
        return logger

    if logger.disabled:
        logger.disabled = False

    if not logger.handlers:
        # Create file handler
        handler = logging.FileHandler(os.path.join(tempfile.gettempdir(), "tui_debug.log"), mode="a")
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger


def tui_log(msg: str, level: str = "debug") -> None:
    """Log to TUI debug file.

    Args:
        msg: Message to log.
        level: Log level (debug, info, warning, error). Default is debug.
    """
    if not tui_debug_enabled():
        return
    try:
        logger = get_tui_debug_logger()
        level_method = getattr(logger, level.lower(), logger.debug)
        level_method(msg)
    except Exception:
        # Silent failure - don't break TUI if logging fails
        pass
