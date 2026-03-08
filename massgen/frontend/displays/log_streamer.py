"""
Log Streamer Utility for MassGen TUI.

Provides efficient log file tailing for real-time display of subagent logs.
"""

from collections import deque
from pathlib import Path


class LogStreamer:
    """Efficient log file tailing for live display.

    Tracks file position to return only new lines since last read.
    Useful for streaming subagent logs to the TUI.

    Example:
        >>> streamer = LogStreamer(Path("/path/to/massgen.log"))
        >>> while running:
        ...     for line in streamer.get_new_lines():
        ...         display(line)
        ...     time.sleep(0.5)
    """

    def __init__(self, log_path: Path):
        """Initialize the log streamer.

        Args:
            log_path: Path to the log file to stream
        """
        self._path = log_path
        self._position = 0
        self._file_size = 0

    def get_new_lines(self) -> list[str]:
        """Read new lines since last call.

        Returns:
            List of new lines (stripped of trailing whitespace).
            Empty list if file doesn't exist or no new content.
        """
        if not self._path.exists():
            return []

        try:
            current_size = self._path.stat().st_size

            # Handle file truncation/rotation
            if current_size < self._file_size:
                self._position = 0

            self._file_size = current_size

            # No new content
            if self._position >= current_size:
                return []

            with open(self._path, encoding="utf-8", errors="replace") as f:
                f.seek(self._position)
                lines = f.readlines()
                self._position = f.tell()

            return [line.rstrip() for line in lines if line.strip()]

        except OSError:
            return []

    def tail(self, n: int = 50) -> list[str]:
        """Get last N lines from the file efficiently.

        Args:
            n: Number of lines to return (default 50)

        Returns:
            List of the last N lines (or fewer if file is shorter)
        """
        if not self._path.exists():
            return []

        try:
            # Use deque for efficient tail
            result: deque[str] = deque(maxlen=n)

            with open(self._path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.rstrip()
                    if stripped:
                        result.append(stripped)

            return list(result)

        except OSError:
            return []

    def reset(self) -> None:
        """Reset the position to the beginning of the file.

        Useful if you want to re-read the entire log.
        """
        self._position = 0
        self._file_size = 0

    def skip_to_end(self) -> None:
        """Skip to the end of the file.

        Useful for starting fresh without reading existing content.
        """
        if self._path.exists():
            try:
                self._file_size = self._path.stat().st_size
                self._position = self._file_size
            except OSError:
                pass


def count_files_in_directory(directory: Path, recursive: bool = True) -> int:
    """Count the number of files in a directory.

    Args:
        directory: Path to the directory
        recursive: Whether to count files in subdirectories

    Returns:
        Number of files (not directories)
    """
    if not directory.exists() or not directory.is_dir():
        return 0

    try:
        if recursive:
            return sum(1 for p in directory.rglob("*") if p.is_file())
        else:
            return sum(1 for p in directory.iterdir() if p.is_file())
    except OSError:
        return 0


def format_log_line(line: str, max_length: int = 80) -> str:
    """Format a log line for display.

    Extracts and formats key parts of a log line:
    - Timestamp
    - Log level
    - Message

    Args:
        line: Raw log line
        max_length: Maximum length before truncation

    Returns:
        Formatted log line suitable for display
    """
    # Truncate long lines
    if len(line) > max_length:
        return line[: max_length - 3] + "..."
    return line
