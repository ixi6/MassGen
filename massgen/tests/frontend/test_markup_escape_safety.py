"""Tests that user/agent content with bracket metacharacters does not crash the TUI.

Textual interprets [text] as markup tags when markup=True on Static widgets.
User content containing LaTeX, JSON, markdown links, or other bracket-heavy text
must not cause MarkupError.

Key findings from investigation:
- Textual's Static widget has a STRICT markup parser that raises MarkupError
- Rich's RichLog.write() is lenient and does NOT raise (safe by default)
- The fix for Static widgets: escape user content with rich.markup.escape()
  before interpolating into markup strings, OR use Text objects directly
"""

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.markup import MarkupError
from textual.widgets import RichLog, Static

# --- Test data: strings that trigger MarkupError in Textual's markup parser ---

LATEX_CONTENT = r"\begin{mdframed}[backgroundcolor=Salmon!15]" r"\textcolor{orange}{\textbf{Agent:}} I have NOT completed the shutdown." r"\end{mdframed}"

JSON_ARRAY_CONTENT = '{"items": ["key1", "key2"], "nested": [1, [2, 3]]}'

MARKDOWN_LINK_CONTENT = "See [the documentation](https://example.com) and " "[this issue](https://github.com/org/repo/issues/123)"

# Looks like valid Rich markup — would silently style text instead of displaying literally
ACCIDENTAL_RICH_MARKUP = "Use [red]caution[/red] when editing [bold]production[/bold] configs."

# Brackets with invalid markup syntax
INVALID_BRACKET_CONTENT = "Array access: items[0] and matrix[i][j] = values[key!special]"

MIXED_LATEX_AND_JSON = r"\begin{mdframed}[backgroundcolor=Salmon!15]" r' {"data": ["a", "b"]} ' r"\end{mdframed}"

# Content that crashes Textual's Static(markup=True)
CRASHING_CONTENT = [
    LATEX_CONTENT,
    MIXED_LATEX_AND_JSON,
]

# Content that doesn't crash but is silently misinterpreted (swallowed brackets)
MISINTERPRETED_CONTENT = [
    ACCIDENTAL_RICH_MARKUP,
]

ALL_DANGEROUS_CONTENT = [
    LATEX_CONTENT,
    JSON_ARRAY_CONTENT,
    MARKDOWN_LINK_CONTENT,
    ACCIDENTAL_RICH_MARKUP,
    INVALID_BRACKET_CONTENT,
    MIXED_LATEX_AND_JSON,
]


# --- Proof that Textual's markup parser crashes on bracket content ---


class TestTextualMarkupParserCrashes:
    """Demonstrate that Textual's markup parser raises on certain bracket patterns.

    These tests document the ROOT CAUSE: Textual's markup module is stricter
    than Rich's. This is why Static(markup=True) crashes but RichLog doesn't.
    """

    @pytest.mark.parametrize("content", CRASHING_CONTENT, ids=["latex", "mixed"])
    def test_textual_markup_raises_on_invalid_brackets(self, content):
        """Textual's markup parser raises MarkupError for LaTeX-style brackets."""
        from textual.markup import to_content

        with pytest.raises(MarkupError):
            to_content(f"[dim]Previous: {content}[/]")


# --- Widget-level tests: Static with interpolated user content ---


class _StaticMarkupTestApp(App):
    """Minimal app with a Static widget using markup=True."""

    def __init__(self, content: str):
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        yield Static(self._content, id="test_static", markup=True)


class TestStaticMarkupSafety:
    """Test that Static widgets with markup=True handle user content safely.

    This tests the pattern used in textual_terminal_display.py:7397:
        Static(f"[dim]Previous: {summary}[/]", markup=True)

    When summary contains LaTeX brackets, this crashes. The fix is to escape
    the user content before interpolation.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        ALL_DANGEROUS_CONTENT,
        ids=[
            "latex",
            "json_array",
            "markdown_link",
            "accidental_rich",
            "invalid_bracket",
            "mixed",
        ],
    )
    async def test_static_with_interpolated_user_content(self, content):
        """Static(f"[dim]Previous: {user_content}[/]", markup=True) must not crash."""
        from rich.markup import escape

        escaped = escape(content)
        formatted = f"[dim]Previous: {escaped}[/]"
        app = _StaticMarkupTestApp(formatted)
        async with app.run_test() as pilot:
            await pilot.pause()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        ALL_DANGEROUS_CONTENT,
        ids=[
            "latex",
            "json_array",
            "markdown_link",
            "accidental_rich",
            "invalid_bracket",
            "mixed",
        ],
    )
    async def test_static_with_raw_user_content_uses_text_object(self, content):
        """When displaying pure user content, use Text objects to bypass markup."""

        class _TextStaticApp(App):
            def compose(self_app) -> ComposeResult:
                widget = Static(id="test_static")
                yield widget

        app = _TextStaticApp()
        async with app.run_test() as pilot:
            static = app.query_one("#test_static", Static)
            # Using Text objects is always safe — no markup parsing
            static.update(Text(content))
            await pilot.pause()


# --- Widget-level tests: RichLog is safe (documenting this for confidence) ---


class _RichLogTestApp(App):
    """Minimal app with a RichLog widget."""

    def __init__(self, markup: bool = True):
        super().__init__()
        self._markup = markup

    def compose(self) -> ComposeResult:
        yield RichLog(id="test_log", markup=self._markup, highlight=False)


class TestRichLogIsAlreadySafe:
    """Verify RichLog.write() does NOT crash on bracket content.

    RichLog uses Rich's lenient parser, not Textual's strict one.
    This means our RichLog widgets (thinking_log, log-stream, content_log)
    are NOT vulnerable to the MarkupError crash. However, content with
    brackets matching valid Rich markup names (e.g., [red], [bold]) will
    still be silently interpreted as styles rather than displayed literally.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        ALL_DANGEROUS_CONTENT,
        ids=[
            "latex",
            "json_array",
            "markdown_link",
            "accidental_rich",
            "invalid_bracket",
            "mixed",
        ],
    )
    async def test_richlog_write_string_does_not_crash(self, content):
        """RichLog.write(str) with markup=True does not crash."""
        app = _RichLogTestApp(markup=True)
        async with app.run_test() as pilot:
            log = app.query_one("#test_log", RichLog)
            log.write(content)
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_richlog_markup_false_preserves_literal_brackets(self):
        """With markup=False, RichLog displays brackets literally."""
        app = _RichLogTestApp(markup=False)
        async with app.run_test() as pilot:
            log = app.query_one("#test_log", RichLog)
            log.write(ACCIDENTAL_RICH_MARKUP)
            await pilot.pause()
            # No crash — markup=False means no parsing at all


# --- ThinkingSection widget test ---


class TestThinkingSectionMarkupSafety:
    """Test that ThinkingSection.append() handles dangerous content safely.

    ThinkingSection uses a RichLog internally, so it's safe from MarkupError
    crashes. But verify the full widget integration path works.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        ALL_DANGEROUS_CONTENT,
        ids=[
            "latex",
            "json_array",
            "markdown_link",
            "accidental_rich",
            "invalid_bracket",
            "mixed",
        ],
    )
    async def test_thinking_section_append_with_dangerous_content(self, content):
        """ThinkingSection.append() must not crash on bracket-heavy content."""
        from massgen.frontend.displays.textual_widgets.content_sections import (
            ThinkingSection,
        )

        class _ThinkingApp(App):
            def compose(self) -> ComposeResult:
                yield ThinkingSection(id="thinking")

        app = _ThinkingApp()
        async with app.run_test() as pilot:
            section = app.query_one("#thinking", ThinkingSection)
            section.append(content)
            await pilot.pause()


# --- Escape utility tests ---


class TestEscapePreservesDisplay:
    """Verify that escaping brackets preserves the literal text for display."""

    def test_escape_produces_identical_plain_text(self):
        """rich.markup.escape() should make text display literally, not as markup."""
        from rich.markup import escape

        for content in ALL_DANGEROUS_CONTENT:
            escaped = escape(content)
            text = Text.from_markup(escaped)
            assert text.plain == content, f"Escaped content didn't round-trip:\n" f"  original: {content!r}\n" f"  escaped:  {escaped!r}\n" f"  rendered: {text.plain!r}"

    def test_escape_allows_mixing_with_rich_markup(self):
        """Escaped user content can be safely interpolated into Rich markup strings."""
        from rich.markup import escape

        user_input = LATEX_CONTENT
        escaped = escape(user_input)
        safe_markup = f"[dim]Previous: {escaped}[/]"

        # Should not raise
        text = Text.from_markup(safe_markup)
        # The user content should appear literally in the output
        assert user_input in text.plain
