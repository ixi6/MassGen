"""
Result Renderer for MassGen TUI.

Smart formatting of tool results with content type detection,
syntax highlighting, and truncation.
"""

import json
import re

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text


class ResultRenderer:
    """Smart renderer for tool results with content type detection and formatting."""

    # Maximum lines before truncation
    MAX_LINES = 50
    # Maximum characters before truncation
    MAX_CHARS = 5000

    # Content type detection patterns
    JSON_PATTERN = re.compile(r"^\s*[\[{]")
    PYTHON_PATTERN = re.compile(r"^(def |class |import |from |if __name__|@)")
    MARKDOWN_PATTERN = re.compile(r"^(#{1,6} |```|\*\*|__|\[.*\]\()")
    XML_PATTERN = re.compile(r"^\s*<\?xml|^\s*<[a-zA-Z]")
    YAML_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:\s*")
    SHELL_PATTERN = re.compile(r"^\s*(#!|export |echo |cd |ls |grep |find |sudo )")

    @classmethod
    def render(
        cls,
        content: str | None,
        force_type: str | None = None,
        max_lines: int | None = None,
        max_chars: int | None = None,
    ) -> tuple[RenderableType, bool]:
        """Render content with appropriate formatting.

        Args:
            content: The content to render
            force_type: Force a specific content type (json, python, etc.)
            max_lines: Override default max lines
            max_chars: Override default max chars

        Returns:
            Tuple of (rendered content, was_truncated)
        """
        if not content:
            return Text("(no content)", style="dim italic"), False

        max_lines = max_lines or cls.MAX_LINES
        max_chars = max_chars or cls.MAX_CHARS

        # Detect content type
        content_type = force_type or cls.detect_type(content)

        # Pre-process content based on type
        processed_content, was_truncated = cls._truncate(content, max_lines, max_chars)

        # Format based on type
        if content_type == "json":
            rendered = cls._render_json(processed_content)
        elif content_type in ("python", "py"):
            rendered = cls._render_syntax(processed_content, "python")
        elif content_type in ("javascript", "js"):
            rendered = cls._render_syntax(processed_content, "javascript")
        elif content_type in ("typescript", "ts"):
            rendered = cls._render_syntax(processed_content, "typescript")
        elif content_type == "markdown":
            rendered = cls._render_syntax(processed_content, "markdown")
        elif content_type == "yaml":
            rendered = cls._render_syntax(processed_content, "yaml")
        elif content_type == "xml":
            rendered = cls._render_syntax(processed_content, "xml")
        elif content_type == "shell":
            rendered = cls._render_syntax(processed_content, "bash")
        else:
            rendered = cls._render_plain(processed_content)

        # Add truncation indicator if needed
        if was_truncated:
            lines = content.count("\n") + 1
            chars = len(content)
            truncation_note = Text(
                f"\n... truncated ({lines} lines, {chars} chars total)",
                style="dim italic",
            )
            rendered = Group(rendered, truncation_note)

        return rendered, was_truncated

    @classmethod
    def detect_type(cls, content: str) -> str:
        """Detect the content type from the content.

        Args:
            content: Content to analyze

        Returns:
            Detected type string
        """
        content_stripped = content.strip()

        # Check for JSON
        if cls.JSON_PATTERN.match(content_stripped):
            try:
                json.loads(content_stripped)
                return "json"
            except json.JSONDecodeError:
                pass

        # Check first few lines for patterns
        first_lines = "\n".join(content_stripped.split("\n")[:5])

        if cls.PYTHON_PATTERN.search(first_lines):
            return "python"
        if cls.XML_PATTERN.match(content_stripped):
            return "xml"
        if cls.YAML_PATTERN.match(content_stripped):
            return "yaml"
        if cls.SHELL_PATTERN.search(first_lines):
            return "shell"
        if cls.MARKDOWN_PATTERN.search(first_lines):
            return "markdown"

        return "text"

    @classmethod
    def _truncate(
        cls,
        content: str,
        max_lines: int,
        max_chars: int,
    ) -> tuple[str, bool]:
        """Truncate content if needed.

        Args:
            content: Content to truncate
            max_lines: Maximum number of lines
            max_chars: Maximum number of characters

        Returns:
            Tuple of (truncated content, was_truncated)
        """
        was_truncated = False

        # Truncate by characters first
        if len(content) > max_chars:
            content = content[:max_chars]
            was_truncated = True

        # Truncate by lines
        lines = content.split("\n")
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines])
            was_truncated = True

        return content, was_truncated

    @classmethod
    def _render_json(cls, content: str) -> RenderableType:
        """Render JSON content with pretty-printing and syntax highlighting.

        Args:
            content: JSON content

        Returns:
            Rendered JSON
        """
        try:
            # Parse and pretty-print
            parsed = json.loads(content)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            return Syntax(
                formatted,
                "json",
                theme="monokai",
                line_numbers=False,
                word_wrap=True,
            )
        except json.JSONDecodeError:
            # Fall back to plain rendering if JSON is invalid
            return cls._render_syntax(content, "json")

    @classmethod
    def _render_syntax(cls, content: str, language: str) -> Syntax:
        """Render content with syntax highlighting.

        Args:
            content: Content to render
            language: Language for syntax highlighting

        Returns:
            Syntax object
        """
        return Syntax(
            content,
            language,
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        )

    @classmethod
    def _render_plain(cls, content: str) -> Text:
        """Render content as plain text.

        Args:
            content: Content to render

        Returns:
            Text object
        """
        return Text(content)

    @classmethod
    def format_preview(
        cls,
        content: str | None,
        max_length: int = 100,
    ) -> str:
        """Format a short preview of content for inline display.

        Args:
            content: Content to preview
            max_length: Maximum length of preview

        Returns:
            Preview string
        """
        if not content:
            return "(no content)"

        # Collapse whitespace and newlines
        preview = " ".join(content.split())

        if len(preview) > max_length:
            return preview[: max_length - 3] + "..."

        return preview

    @classmethod
    def get_content_summary(cls, content: str | None) -> str:
        """Get a summary of content (type, lines, chars).

        Args:
            content: Content to summarize

        Returns:
            Summary string
        """
        if not content:
            return "empty"

        content_type = cls.detect_type(content)
        lines = content.count("\n") + 1
        chars = len(content)

        return f"{content_type} ({lines} lines, {chars} chars)"
