"""
MassGen Display Components

Provides various display interfaces for MassGen coordination visualization.
"""

from .base_display import BaseDisplay
from .rich_terminal_display import (
    RichTerminalDisplay,
    create_rich_display,
    is_rich_available,
)
from .simple_display import SimpleDisplay
from .terminal_display import TerminalDisplay

try:
    from .textual_terminal_display import (
        TextualTerminalDisplay,
        create_textual_display,
        is_textual_available,
    )

    TEXTUAL_IMPORTS_AVAILABLE = True
except (ImportError, NameError):
    # Keep non-Textual imports usable when textual dependencies are unavailable
    # or when textual symbols fail to resolve during module initialization.
    TextualTerminalDisplay = None
    TEXTUAL_IMPORTS_AVAILABLE = False

    def is_textual_available():
        return False

    def create_textual_display(*args, **kwargs):
        return None


__all__ = [
    "BaseDisplay",
    "TerminalDisplay",
    "SimpleDisplay",
    "RichTerminalDisplay",
    "is_rich_available",
    "create_rich_display",
    "TextualTerminalDisplay",
    "is_textual_available",
    "create_textual_display",
]
