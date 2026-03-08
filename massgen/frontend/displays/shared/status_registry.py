"""Status display utilities.

Single source of truth for status indicators, colors, and time formatting.
Previously duplicated across:
- textual_widgets/subagent_screen.py:164-171
- textual_widgets/subagent_tui_modal.py:294-300
- textual_widgets/subagent_card.py (inline formatting)

This consolidation ensures consistent status display across all subprocess views.
"""

# Status icon mapping
STATUS_ICONS = {
    "completed": "✓",
    "running": "●",
    "pending": "○",
    "error": "✗",
    "timeout": "⏱",
    "failed": "✗",
}

# Status color mapping (using theme-compatible colors)
STATUS_COLORS = {
    "completed": "#7ee787",  # Success green
    "running": "#a371f7",  # Active purple
    "pending": "#8b949e",  # Neutral gray
    "error": "#f85149",  # Error red
    "timeout": "#d29922",  # Warning gold
    "failed": "#f85149",  # Error red
}


def get_status_icon_and_color(status: str) -> tuple[str, str]:
    """Get icon and color for a status.

    Args:
        status: Status string (completed, running, pending, error, timeout, failed).

    Returns:
        Tuple of (icon, color) for the status.
    """
    status_lower = status.lower()
    icon = STATUS_ICONS.get(status_lower, "●")  # Default to running icon
    color = STATUS_COLORS.get(status_lower, "#8b949e")  # Default to gray
    return (icon, color)


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed time as human-readable string.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        Formatted time string (e.g., "45s", "2m15s", "1h5m").
    """
    seconds = int(seconds)

    if seconds <= 0:
        return ""

    # Hours, minutes, seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        if minutes > 0:
            return f"{hours}h{minutes}m"
        return f"{hours}h"
    elif minutes > 0:
        if secs > 0:
            return f"{minutes}m{secs}s"
        return f"{minutes}m"
    else:
        return f"{secs}s"
