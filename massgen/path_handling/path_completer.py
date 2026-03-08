"""Path completer for @filename syntax in MassGen prompts.

This module provides a custom prompt_toolkit Completer that triggers
path completion when the user types @ followed by a path.

Example:
    >>> from massgen.path_handling import AtPathCompleter
    >>> from prompt_toolkit import prompt
    >>> completer = AtPathCompleter()
    >>> user_input = prompt("User: ", completer=completer)
"""

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    PathCompleter,
)
from prompt_toolkit.document import Document

from massgen.filesystem_manager._constants import get_language_for_extension


class AtPathCompleter(Completer):
    """Completer for @path syntax in prompts.

    Triggers path completion when user types @ followed by partial path.
    Supports:
        - @path/to/file - read-only context
        - @path/to/file:w - write context
        - @~/path - home directory expansion
        - Directories with trailing slash

    Attributes:
        path_completer: Underlying PathCompleter for file suggestions.
        base_path: Base path for resolving relative paths.
    """

    def __init__(
        self,
        base_path: Path | None = None,
        only_directories: bool = False,
        expanduser: bool = True,
        file_filter: Callable | None = None,
    ):
        """Initialize AtPathCompleter.

        Args:
            base_path: Base path for relative path resolution. Defaults to cwd.
            only_directories: If True, only show directories in completion.
            expanduser: If True, expand ~ to home directory.
            file_filter: Optional callable to filter files (return True to include).
        """
        try:
            self.base_path = base_path or Path.cwd()
        except OSError:
            # Fallback if cwd is unavailable (deleted directory, etc.)
            self.base_path = Path.home()
        self.only_directories = only_directories
        self.expanduser = expanduser
        self.file_filter = file_filter

        # Create underlying path completer with get_paths callback
        # to use our base_path instead of cwd
        def get_paths() -> list[str]:
            return [str(self.base_path)]

        self.path_completer = PathCompleter(
            only_directories=only_directories,
            expanduser=expanduser,
            file_filter=file_filter,
            get_paths=get_paths,
        )

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterable[Completion]:
        """Get completions for the current input.

        Args:
            document: The document containing the current input.
            complete_event: The completion event.

        Yields:
            Completion objects for matching paths.
        """
        text = document.text_before_cursor

        # Find the last @ that's not escaped and not part of an email
        at_result = self._find_at_position(text)

        if at_result is None:
            # No @ found or it's part of an email
            return

        at_pos, is_quoted = at_result

        # Extract the partial path after @ (and opening quote if quoted)
        if is_quoted:
            # Skip the opening quote
            path_text = text[at_pos + 2 :]
        else:
            path_text = text[at_pos + 1 :]

        # Check if there's a :w suffix being typed
        has_write_suffix = False
        if path_text.endswith(":w"):
            path_text = path_text[:-2]
            has_write_suffix = True
        elif path_text.endswith(":"):
            # User is typing :w, show completion without the :
            path_text = path_text[:-1]

        # For unquoted paths, skip if the path contains spaces (likely not a path)
        if not is_quoted and " " in path_text:
            return

        # Create a document for just the path portion
        path_document = Document(path_text)

        # Get completions from PathCompleter
        for completion in self.path_completer.get_completions(
            path_document,
            complete_event,
        ):
            # Calculate the start position relative to the full text
            # We need to replace from the @ symbol onwards
            # +1 for @, +1 for opening quote if quoted
            start_position = -(len(path_text) + 1 + (1 if is_quoted else 0))

            # Build the completion text
            completed_path = path_text + completion.text

            # Check if this is a directory (with error handling for filesystem issues)
            try:
                full_path = self._resolve_path(completed_path)
                is_dir = full_path.is_dir() if full_path.exists() else False
            except (OSError, PermissionError, ValueError, RuntimeError):
                # Skip completions we can't resolve (permission denied, invalid path, etc.)
                continue

            # Add trailing slash for directories
            if is_dir and not completed_path.endswith("/"):
                completed_path += "/"

            # Preserve :w suffix if user had it
            suffix = ":w" if has_write_suffix else ""

            # Create display text with file type indicator
            if is_dir:
                display_meta = "dir"
            else:
                display_meta = self._get_file_type(completed_path)

            # Format path with quotes if needed (for paths with spaces or if already quoted)
            needs_quotes = is_quoted or " " in completed_path
            if needs_quotes:
                formatted_path = f'@"{completed_path}"{suffix}'
            else:
                formatted_path = f"@{completed_path}{suffix}"

            yield Completion(
                text=formatted_path,
                start_position=start_position,
                display=formatted_path,
                display_meta=display_meta,
            )

            # Also offer :w variant for files (not directories already covered)
            if not is_dir and not has_write_suffix:
                if needs_quotes:
                    formatted_path_w = f'@"{completed_path}":w'
                else:
                    formatted_path_w = f"@{completed_path}:w"

                yield Completion(
                    text=formatted_path_w,
                    start_position=start_position,
                    display=formatted_path_w,
                    display_meta=f"{display_meta} (write)",
                )

    def _find_at_position(self, text: str) -> tuple[int, bool] | None:
        """Find the position of the last @ that starts a path reference.

        Args:
            text: The text to search.

        Returns:
            Tuple of (position of @, is_quoted) or None if not found/not valid.
            is_quoted is True if the path starts with @" (quoted path syntax).
        """
        # Search backwards for @
        pos = len(text) - 1
        while pos >= 0:
            if text[pos] == "@":
                # Check if escaped
                if pos > 0 and text[pos - 1] == "\\":
                    pos -= 1
                    continue

                # Check if it's likely part of an email
                # (has word chars before and after with a dot after)
                if self._is_email_context(text, pos):
                    pos -= 1
                    continue

                # Check if this is a quoted path (@ followed by ")
                is_quoted = pos + 1 < len(text) and text[pos + 1] == '"'

                # Valid @ for path
                return (pos, is_quoted)

            # For quoted paths, we need to track if we're inside quotes
            # If we find a quote, check if there's @" before it
            if text[pos] == '"':
                # Look for @" pattern
                if pos > 0 and text[pos - 1] == "@":
                    # Check if the @ is escaped
                    if pos > 1 and text[pos - 2] == "\\":
                        pos -= 2
                        continue
                    # Found @" - this is a quoted path
                    return (pos - 1, True)

            # Stop if we hit whitespace (@ must be at word boundary or start)
            # But don't stop for quoted paths - spaces are allowed inside quotes
            if text[pos] == " ":
                # Check if we might be inside a quoted path by looking for @" before this space
                at_quote_pos = text.rfind('@"', 0, pos)
                if at_quote_pos != -1:
                    # Check if there's a closing quote after @" but before this space
                    quote_after = text.find('"', at_quote_pos + 2, pos + 1)
                    if quote_after == -1:
                        # No closing quote yet, we're inside a quoted path
                        return (at_quote_pos, True)
                break

            pos -= 1

        return None

    def _is_email_context(self, text: str, at_pos: int) -> bool:
        """Check if the @ at the given position is likely part of an email.

        Args:
            text: The full text.
            at_pos: Position of the @ symbol.

        Returns:
            True if this looks like an email address.
        """
        # Check for word chars before @
        if at_pos == 0:
            return False

        before = text[at_pos - 1]
        if not (before.isalnum() or before in "._-"):
            return False

        # Check for domain-like pattern after @
        after = text[at_pos + 1 :] if at_pos + 1 < len(text) else ""
        if not after:
            return False

        # If there's a dot and it looks like a TLD, it's probably an email
        if "." in after:
            parts = after.split(".")
            if len(parts) >= 2:
                # Check if first part is alphanumeric (domain)
                # and there are no path separators before the first dot
                first_part = parts[0]
                if "/" not in first_part and first_part.replace("-", "").isalnum():
                    return True

        return False

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path string to an absolute Path.

        Args:
            path_str: The path string to resolve.

        Returns:
            Resolved absolute Path.

        Raises:
            OSError: If path resolution fails (e.g., permission denied).
            RuntimeError: If path has circular symlinks.
            ValueError: If path contains invalid characters.
        """
        # Handle ~ expansion
        if path_str.startswith("~") and self.expanduser:
            path_str = os.path.expanduser(path_str)

        path = Path(path_str)

        # Resolve relative paths against base_path
        if not path.is_absolute():
            path = self.base_path / path

        # resolve() can raise OSError or RuntimeError (circular symlinks)
        return path.resolve()

    def _get_file_type(self, path_str: str) -> str:
        """Get a short description of the file type.

        Args:
            path_str: The path string.

        Returns:
            Short file type description.
        """
        ext = Path(path_str).suffix.lower()
        return get_language_for_extension(ext)
