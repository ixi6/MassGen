"""File rendering utilities for syntax highlighting and previews.

Single source of truth for file preview rendering. Previously located in:
- textual_terminal_display.py:663-815

This module provides utilities for rendering file content with syntax
highlighting, handling binary files, and detecting file types.
"""

from pathlib import Path
from typing import Any

# Language mapping for syntax highlighting
FILE_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".xml": "xml",
    ".r": "r",
    ".lua": "lua",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
}

# Binary file extensions to reject for preview
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".mkv",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
}


def render_file_preview(
    file_path: Path,
    max_size: int = 50000,
    theme: str = "monokai",
) -> tuple[Any, bool]:
    """Render file content with syntax highlighting or markdown.

    Args:
        file_path: Path to the file to preview.
        max_size: Maximum file size in bytes to render (default 50KB).
        theme: Syntax highlighting theme (default "monokai").

    Returns:
        Tuple of (renderable, is_rich) where:
        - renderable: Rich Markdown, Syntax, or plain string
        - is_rich: True if renderable is a Rich object, False for plain text
    """
    from rich.markdown import Markdown
    from rich.syntax import Syntax

    try:
        ext = file_path.suffix.lower()

        # Handle binary files
        if ext in BINARY_EXTENSIONS:
            return f"[Binary file: {ext}]", False

        # Check file size
        if file_path.stat().st_size > max_size:
            return f"[File too large: {file_path.stat().st_size:,} bytes]", False

        # Read content
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "[Binary or non-UTF-8 file]", False

        # Empty file
        if not content.strip():
            return "[Empty file]", False

        # Markdown files - render as Markdown
        if ext in (".md", ".markdown"):
            return Markdown(content), True

        # Code files - render with syntax highlighting
        if ext in FILE_LANG_MAP:
            return (
                Syntax(
                    content,
                    FILE_LANG_MAP[ext],
                    theme=theme,
                    line_numbers=True,
                    word_wrap=True,
                ),
                True,
            )

        # Special files without extensions
        if file_path.name.lower() in ("dockerfile", "makefile", "jenkinsfile"):
            lang = file_path.name.lower()
            if lang == "makefile":
                lang = "make"
            return Syntax(content, lang, theme=theme, line_numbers=True, word_wrap=True), True

        # Default: plain text (truncate if very long)
        lines = content.split("\n")
        if len(lines) > 500:
            content = "\n".join(lines[:500]) + f"\n\n... [{len(lines) - 500} more lines]"
        return content, False

    except FileNotFoundError:
        return "[File not found]", False
    except PermissionError:
        return "[Permission denied]", False
    except Exception as e:
        return f"[Error reading file: {e}]", False
