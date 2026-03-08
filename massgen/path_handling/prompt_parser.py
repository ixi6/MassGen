"""Prompt parser for @filename syntax to include context paths inline.

This module provides parsing functionality to extract @path references from
MassGen prompts and convert them to context_paths format.

Syntax:
  @path/to/file      - Add file as read-only context
  @path/to/file:w    - Add file as write context
  @path/to/dir/      - Add directory as read-only context
  @path/to/dir/:w    - Add directory as write context
  \\@literal          - Escaped @ (not parsed as reference)

Example:
    >>> from massgen.path_handling import parse_prompt_for_context
    >>> result = parse_prompt_for_context("Review @src/main.py and update @src/config.py:w")
    >>> result.context_paths
    [{'path': 'src/main.py', 'permission': 'read'}, {'path': 'src/config.py', 'permission': 'write'}]
    >>> result.cleaned_prompt
    'Review and update'
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


class PromptParserError(Exception):
    """Error raised when prompt parsing fails."""


@dataclass
class ParsedPrompt:
    """Result of parsing a prompt for @references.

    Attributes:
        original_prompt: The unmodified input prompt.
        cleaned_prompt: Prompt with @references removed.
        context_paths: List of context path dicts with 'path' and 'permission' keys.
        suggestions: List of suggestions (e.g., consolidation recommendations).
    """

    original_prompt: str
    cleaned_prompt: str
    context_paths: list[dict[str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class PromptParser:
    """Parser for extracting @filename references from prompts.

    This parser extracts @path and @path:w references from prompts,
    validates that the paths exist, and returns structured context
    path information.

    Attributes:
        PATTERN: Compiled regex for matching @references.
        EMAIL_PATTERN: Compiled regex for detecting email addresses.
    """

    # Regex pattern explanation:
    # (?<!\\)       - Negative lookbehind: not preceded by backslash (escaped)
    # @             - Literal @ symbol
    # (?:           - Non-capturing group for path alternatives
    #   "([^"]+)"   - Capture group 1: quoted path (allows spaces)
    #   |           - OR
    #   ([^\s@:]+?) - Capture group 2: unquoted path (non-greedy, excludes whitespace, @, :)
    # )
    # (:w)?         - Capture group 3: optional :w suffix
    # (?=\s|$|[,;!?)}\]>:]|\.(?=\s|$))  - Lookahead for path termination
    #
    # The lookahead handles:
    #   \s           - whitespace ends path
    #   $            - end of string ends path
    #   [,;!?)}\]>:] - punctuation ends path (includes : for :w suffix boundary)
    #   \.(?=\s|$)   - period only ends path if followed by space or end (sentence end)
    #
    # Note: The path character class excludes : so that :w is captured separately.
    # File extensions like .py, .md work because only sentence-ending periods
    # (followed by space or end) terminate the path.
    # Quoted paths allow spaces: @"path with spaces/file.txt"
    PATTERN = re.compile(
        r"(?<!\\)@"  # @ not preceded by backslash
        r"(?:"
        r'"([^"]+)"'  # Capture group 1: quoted path (spaces allowed)
        r"|"
        r'([^\s@:"]+?)'  # Capture group 2: unquoted path (no spaces, no quotes)
        r")"
        r"(:w)?"  # Capture group 3: optional :w suffix
        r"(?=\s|$|[,;!?)}\]>:]|\.(?=\s|$))",  # Lookahead for termination
    )

    # Pattern to detect email-like patterns (to avoid false positives)
    # Matches: word@word.word
    EMAIL_PATTERN = re.compile(r"^[\w.-]+@[\w.-]+\.\w+$")

    # Pattern for email in context - word chars, @, domain with TLD
    EMAIL_IN_CONTEXT = re.compile(r"\b[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}\b")

    def parse(self, prompt: str) -> ParsedPrompt:
        """Parse prompt and extract @references.

        Args:
            prompt: The user's prompt potentially containing @references.

        Returns:
            ParsedPrompt with extracted context paths and cleaned prompt.

        Raises:
            PromptParserError: If any referenced path does not exist.
        """
        if not prompt:
            return ParsedPrompt(
                original_prompt=prompt,
                cleaned_prompt=prompt,
                context_paths=[],
                suggestions=[],
            )

        # Find all email addresses to exclude from matching
        email_positions = set()
        for match in self.EMAIL_IN_CONTEXT.finditer(prompt):
            email_positions.add(match.start())

        # Find all @references
        matches: list[tuple[str, str, int, int]] = []  # (path, suffix, start, end)
        for match in self.PATTERN.finditer(prompt):
            # Skip if this @ is part of an email address
            # Check if @ position corresponds to an email
            at_pos = match.start()
            is_email = False
            for email_match in self.EMAIL_IN_CONTEXT.finditer(prompt):
                if email_match.start() <= at_pos < email_match.end():
                    is_email = True
                    break

            if is_email:
                continue

            # Group 1 is quoted path, group 2 is unquoted path
            path_str = match.group(1) or match.group(2)
            suffix = match.group(3) or ""
            matches.append((path_str, suffix, match.start(), match.end()))

        if not matches:
            # Handle escaped @ -> convert \@ to @
            cleaned = prompt.replace("\\@", "@")
            return ParsedPrompt(
                original_prompt=prompt,
                cleaned_prompt=cleaned,
                context_paths=[],
                suggestions=[],
            )

        # Process matches and validate paths
        context_paths: dict[str, dict[str, str]] = {}  # path -> {path, permission}
        missing_paths: list[str] = []

        for path_str, suffix, _, _ in matches:
            try:
                expanded_path = self._expand_path(path_str)
                path_exists = expanded_path.exists()
            except (OSError, PermissionError, RuntimeError) as e:
                # Treat inaccessible paths as non-existent with helpful message
                missing_paths.append(f"{path_str} (access error: {e})")
                continue

            if not path_exists:
                missing_paths.append(path_str)
                continue

            permission = "write" if suffix == ":w" else "read"
            path_key = str(expanded_path)

            # If path already exists, write permission takes precedence
            if path_key in context_paths:
                if permission == "write":
                    context_paths[path_key]["permission"] = "write"
            else:
                context_paths[path_key] = {
                    "path": path_key,
                    "permission": permission,
                }

        # Raise error for missing paths
        if missing_paths:
            paths_list = "\n  - ".join(missing_paths)
            raise PromptParserError(
                f"Context paths not found:\n  - {paths_list}\n\n" "Please check that the paths exist and are accessible.",
            )

        # Build cleaned prompt by replacing @references with clean paths
        # Instead of removing @path:w entirely, replace with just the resolved path
        # e.g., "@src/main.py:w" becomes "/abs/path/to/src/main.py"
        cleaned_prompt = prompt
        # Process in reverse order to preserve positions
        for path_str, suffix, start, end in reversed(matches):
            # Check if this path was valid (not in missing_paths)
            try:
                expanded = self._expand_path(path_str)
                if expanded.exists():
                    # Replace @path:w with just the resolved path
                    cleaned_prompt = cleaned_prompt[:start] + str(expanded) + cleaned_prompt[end:]
            except (OSError, PermissionError, RuntimeError):
                # Skip paths that can't be resolved (already handled above)
                pass

        # Handle escaped @ -> convert \@ to @
        cleaned_prompt = cleaned_prompt.replace("\\@", "@")

        # Clean up whitespace
        cleaned_prompt = self._normalize_whitespace(cleaned_prompt)

        # Generate consolidation suggestions
        suggestions = self._generate_consolidation_suggestions(list(context_paths.values()))

        return ParsedPrompt(
            original_prompt=prompt,
            cleaned_prompt=cleaned_prompt,
            context_paths=list(context_paths.values()),
            suggestions=suggestions,
        )

    def _expand_path(self, path_str: str) -> Path:
        """Expand path with home directory and resolve relative paths.

        Args:
            path_str: The path string to expand.

        Returns:
            Expanded and resolved Path object.

        Raises:
            PromptParserError: If home directory or cwd cannot be determined.
            OSError: If path resolution fails.
            RuntimeError: If path has circular symlinks.
        """
        # Remove trailing slash for directories (we'll detect dirs by existence)
        path_str = path_str.rstrip("/")

        # Expand ~ to home directory
        if path_str.startswith("~"):
            try:
                home = Path.home()
            except RuntimeError as e:
                raise PromptParserError(
                    f"Cannot expand '~' - home directory not available: {e}. " f"Use absolute path instead of: {path_str}",
                ) from e
            path_str = str(home) + path_str[1:]

        path = Path(path_str)

        # Resolve relative paths against CWD
        if not path.is_absolute():
            try:
                path = Path.cwd() / path
            except OSError as e:
                raise PromptParserError(
                    f"Cannot resolve relative path - current directory unavailable: {e}. " f"Use absolute path instead of: {path_str}",
                ) from e

        # resolve() can raise OSError or RuntimeError
        return path.resolve()

    def _normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace in text.

        Collapses multiple spaces into one and strips leading/trailing whitespace.

        Args:
            text: Text to normalize.

        Returns:
            Normalized text.
        """
        # Replace multiple spaces with single space
        text = re.sub(r" +", " ", text)
        return text.strip()

    def _generate_consolidation_suggestions(
        self,
        paths: list[dict[str, str]],
    ) -> list[str]:
        """Generate suggestions for consolidating sibling files.

        If 3 or more files are from the same directory, suggests using
        the parent directory instead.

        Args:
            paths: List of context path dicts.

        Returns:
            List of suggestion strings.
        """
        if len(paths) < 3:
            return []

        # Count files per parent directory
        parent_counts: Counter[str] = Counter()
        for ctx in paths:
            path = Path(ctx["path"])
            try:
                if path.is_file():
                    parent_counts[str(path.parent)] += 1
            except (OSError, PermissionError):
                # Skip paths we can't check
                continue

        suggestions = []
        for parent, count in parent_counts.items():
            if count >= 3:
                suggestions.append(
                    f"Consider using @{parent}/ instead of {count} individual files",
                )

        return suggestions


def parse_prompt_for_context(prompt: str) -> ParsedPrompt:
    """Convenience function to parse a prompt for @references.

    Args:
        prompt: The user's prompt potentially containing @references.

    Returns:
        ParsedPrompt with extracted context paths and cleaned prompt.

    Raises:
        PromptParserError: If any referenced path does not exist.

    Example:
        >>> result = parse_prompt_for_context("Review @src/main.py")
        >>> result.context_paths
        [{'path': '/absolute/path/to/src/main.py', 'permission': 'read'}]
    """
    parser = PromptParser()
    return parser.parse(prompt)
