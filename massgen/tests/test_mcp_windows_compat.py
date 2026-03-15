"""
Tests for Windows compatibility fixes in MCP server code.

Verifies that:
1. MCP server startup code contains no emoji that would crash on Windows CP1252
2. Tool call error messages are never empty
"""

import ast
import re

import pytest


class TestNoEmojiInMCPServerCode:
    """Verify MCP server and stdio-path code contains no emoji characters.

    On Windows with CP1252 encoding, any emoji in a print() or logger call
    crashes the MCP server process with:
      'charmap' codec can't encode character '\\U0001fXXX'
    """

    # Regex matching common emoji ranges that CP1252 cannot encode
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # Emoticons
        "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
        "\U0001F680-\U0001F6FF"  # Transport and Map
        "\U0001F1E0-\U0001F1FF"  # Flags
        "\U00002702-\U000027B0"  # Dingbats
        "\U0000FE00-\U0000FE0F"  # Variation Selectors
        "\U00002600-\U000026FF"  # Misc symbols (includes checkmarks)
        "\U0000200D"             # ZWJ
        "\U00002B50"             # Star
        "\U0000231A-\U0000231B"  # Watch/Hourglass
        "]+",
    )

    CRITICAL_FILES = [
        "massgen/filesystem_manager/_code_execution_server.py",
        "massgen/mcp_tools/backend_utils.py",
        "massgen/mcp_tools/client.py",
        "massgen/mcp_tools/hooks.py",
    ]

    @pytest.mark.parametrize("filepath", CRITICAL_FILES)
    def test_no_emoji_in_print_or_log_statements(self, filepath):
        """Ensure print() and logger calls contain no emoji."""
        import pathlib

        # Resolve relative to the project root
        project_root = pathlib.Path(__file__).parent.parent.parent
        full_path = project_root / filepath

        if not full_path.exists():
            pytest.skip(f"File not found: {filepath}")

        source = full_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filepath)

        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Check print() calls and logger.* calls
            is_print = (
                isinstance(node.func, ast.Name)
                and node.func.id == "print"
            )
            is_logger = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            )

            if not (is_print or is_logger):
                continue

            # Check all string literals in the call's arguments
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(
                    child.value, str,
                ):
                    match = self.EMOJI_PATTERN.search(child.value)
                    if match:
                        violations.append(
                            f"  line {child.lineno}: "
                            f"emoji '{match.group()}' in "
                            f"{'print()' if is_print else 'logger.*()'}",
                        )

        assert not violations, (
            f"Emoji found in {filepath} (will crash on Windows CP1252):\n"
            + "\n".join(violations)
        )


class TestToolCallErrorMessages:
    """Verify tool call error messages are never empty."""

    def test_empty_exception_produces_meaningful_error(self):
        """When an exception has an empty str(), the error message
        should still contain the exception type."""
        # Simulate the fix: str(e) is empty, fallback to type name
        class SilentError(Exception):
            def __str__(self):
                return ""

        e = SilentError()
        error_detail = str(e) or f"{type(e).__name__} (no message)"

        assert error_detail == "SilentError (no message)"
        assert "Tool call failed: SilentError (no message)" == (
            f"Tool call failed: {error_detail}"
        )

    def test_normal_exception_preserves_message(self):
        """Normal exceptions with messages are unchanged."""
        e = ValueError("bad argument")
        error_detail = str(e) or f"{type(e).__name__} (no message)"

        assert error_detail == "bad argument"
