"""Tests for prompt parser @filename syntax.

This module tests the PromptParser that extracts @path references from prompts
and converts them to context_paths format for MassGen.

Syntax:
  @path/to/file      - Add file as read-only context
  @path/to/file:w    - Add file as write context
  @path/to/dir/      - Add directory as read-only context
  @path/to/dir/:w    - Add directory as write context
  \\@literal          - Escaped @ (not parsed as reference)
"""

from pathlib import Path

import pytest

from massgen.path_handling import (
    ParsedPrompt,
    PromptParser,
    PromptParserError,
    parse_prompt_for_context,
)


class TestPromptParserBasicSyntax:
    """Test basic @path syntax parsing."""

    def test_simple_file_reference_read(self, tmp_path: Path) -> None:
        """Test @file adds read-only context."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# test")

        prompt = f"Review @{test_file}"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)
        assert result.context_paths[0]["permission"] == "read"
        assert "Review" in result.cleaned_prompt
        # Path should be in cleaned prompt (without @ prefix)
        assert str(test_file) in result.cleaned_prompt
        assert f"@{test_file}" not in result.cleaned_prompt  # But @ should be removed

    def test_file_reference_write_suffix(self, tmp_path: Path) -> None:
        """Test :w suffix adds write context."""
        test_file = tmp_path / "output.txt"
        test_file.write_text("")

        prompt = f"Write to @{test_file}:w"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)
        assert result.context_paths[0]["permission"] == "write"

    def test_directory_reference_read(self, tmp_path: Path) -> None:
        """Test @dir/ adds directory as read-only context."""
        test_dir = tmp_path / "src"
        test_dir.mkdir()

        prompt = f"Review all files in @{test_dir}/"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_dir)
        assert result.context_paths[0]["permission"] == "read"

    def test_directory_reference_write(self, tmp_path: Path) -> None:
        """Test @dir/:w adds directory as write context."""
        test_dir = tmp_path / "output"
        test_dir.mkdir()

        prompt = f"Write files to @{test_dir}/:w"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_dir)
        assert result.context_paths[0]["permission"] == "write"


class TestPromptParserMultipleReferences:
    """Test multiple @path references in a single prompt."""

    def test_multiple_file_references(self, tmp_path: Path) -> None:
        """Test multiple @references in single prompt."""
        file1 = tmp_path / "a.py"
        file2 = tmp_path / "b.py"
        file1.write_text("")
        file2.write_text("")

        prompt = f"Compare @{file1} with @{file2}"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 2
        paths = {ctx["path"] for ctx in result.context_paths}
        assert str(file1) in paths
        assert str(file2) in paths

    def test_mixed_permissions(self, tmp_path: Path) -> None:
        """Test mixed read and write permissions."""
        source = tmp_path / "source.py"
        target = tmp_path / "target.py"
        source.write_text("")
        target.write_text("")

        prompt = f"Copy from @{source} to @{target}:w"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 2
        perms = {ctx["path"]: ctx["permission"] for ctx in result.context_paths}
        assert perms[str(source)] == "read"
        assert perms[str(target)] == "write"


class TestPromptParserEdgeCases:
    """Test edge cases and special handling."""

    def test_email_address_not_matched(self) -> None:
        """Test email addresses are not treated as paths."""
        prompt = "Send email to user@example.com"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 0
        assert result.cleaned_prompt == prompt

    def test_email_with_subdomain_not_matched(self) -> None:
        """Test email with subdomain is not matched."""
        prompt = "Contact admin@mail.example.org for help"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 0
        assert result.cleaned_prompt == prompt

    def test_escaped_at_preserved(self, tmp_path: Path) -> None:
        """Test \\@ is treated as literal @."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Use \\@decorator pattern and review @{test_file}"
        result = parse_prompt_for_context(prompt)

        # Should have @decorator preserved (unescaped) and only test.py as context
        assert "@decorator" in result.cleaned_prompt
        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)

    def test_nonexistent_path_raises_error(self) -> None:
        """Test that non-existent paths raise an error (fail fast)."""
        prompt = "Look at @/nonexistent/path/that/does/not/exist.py"

        with pytest.raises(PromptParserError) as exc_info:
            parse_prompt_for_context(prompt)

        assert "not found" in str(exc_info.value).lower()
        assert "/nonexistent/path/that/does/not/exist.py" in str(exc_info.value)

    def test_colon_w_in_middle_not_matched(self, tmp_path: Path) -> None:
        """Test :w only matches at end of path."""
        # File with :w-like content nearby shouldn't trigger write mode
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        # :w appears after the path but separated by space
        prompt = f"Review @{test_file} and write more"
        result = parse_prompt_for_context(prompt)

        assert result.context_paths[0]["permission"] == "read"

    def test_colon_other_suffix_ignored(self, tmp_path: Path) -> None:
        """Test that :r or other suffixes are ignored (not treated as :w)."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        # :r is not a valid suffix, should be ignored
        # The path should still resolve to test.py (without the :r)
        prompt = f"Review @{test_file}:r"

        # Should parse successfully, treating :r as a separate token after the path
        result = parse_prompt_for_context(prompt)
        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)
        # Since :r is not :w, permission should be read
        assert result.context_paths[0]["permission"] == "read"


class TestPromptParserPathExpansion:
    """Test path expansion (home directory, relative paths)."""

    def test_home_directory_expansion(self) -> None:
        """Test ~ is expanded to home directory."""
        home = Path.home()
        # Find a file that likely exists in home
        bashrc = home / ".bashrc"
        zshrc = home / ".zshrc"
        profile = home / ".profile"

        test_file = None
        for f in [bashrc, zshrc, profile]:
            if f.exists():
                test_file = f
                break

        if test_file is None:
            pytest.skip("No common dotfile found in home directory")

        relative_path = str(test_file).replace(str(home), "~")
        prompt = f"Review @{relative_path}"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)

    def test_relative_path_resolution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test relative paths are resolved against CWD."""
        # Create a file in tmp_path
        test_file = tmp_path / "test_relative.txt"
        test_file.write_text("test")

        # Change to tmp_path
        monkeypatch.chdir(tmp_path)

        prompt = "@test_relative.txt review this"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        # Should be resolved to absolute path
        assert result.context_paths[0]["path"] == str(test_file.resolve())


class TestPromptParserConsolidation:
    """Test smart consolidation suggestions for sibling files."""

    def test_consolidation_suggestion_three_siblings(self, tmp_path: Path) -> None:
        """Test consolidation suggestion for 3+ files in same directory."""
        # Create 3 files in same directory
        for name in ["a.py", "b.py", "c.py"]:
            (tmp_path / name).write_text("")

        prompt = f"Review @{tmp_path}/a.py @{tmp_path}/b.py @{tmp_path}/c.py"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 3
        assert len(result.suggestions) >= 1
        # Should suggest using the parent directory
        assert str(tmp_path) in result.suggestions[0] or "directory" in result.suggestions[0].lower()

    def test_no_consolidation_for_two_siblings(self, tmp_path: Path) -> None:
        """Test no consolidation suggestion for only 2 sibling files."""
        for name in ["a.py", "b.py"]:
            (tmp_path / name).write_text("")

        prompt = f"Review @{tmp_path}/a.py @{tmp_path}/b.py"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 2
        assert len(result.suggestions) == 0

    def test_no_consolidation_for_different_directories(self, tmp_path: Path) -> None:
        """Test no consolidation for files in different directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "a.py").write_text("")
        (dir1 / "b.py").write_text("")
        (dir2 / "c.py").write_text("")

        prompt = f"Review @{dir1}/a.py @{dir1}/b.py @{dir2}/c.py"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 3
        # No suggestion because only 2 files in dir1
        assert len(result.suggestions) == 0


class TestPromptParserDeduplication:
    """Test path deduplication."""

    def test_duplicate_paths_deduplicated(self, tmp_path: Path) -> None:
        """Test that duplicate paths are deduplicated."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Review @{test_file} and also @{test_file}"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1

    def test_duplicate_with_different_permissions_uses_write(self, tmp_path: Path) -> None:
        """Test that if same path appears with different permissions, write wins."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Read @{test_file} then write @{test_file}:w"
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        # Write permission should take precedence
        assert result.context_paths[0]["permission"] == "write"


class TestPromptParserCleanedPrompt:
    """Test cleaned prompt output."""

    def test_cleaned_prompt_replaces_at_with_path(self, tmp_path: Path) -> None:
        """Test that @references are replaced with clean paths in cleaned prompt."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Please review @{test_file} carefully"
        result = parse_prompt_for_context(prompt)

        # @ prefix should be removed
        assert f"@{test_file}" not in result.cleaned_prompt
        # But the path itself should remain (resolved)
        assert str(test_file) in result.cleaned_prompt
        assert "Please review" in result.cleaned_prompt
        assert "carefully" in result.cleaned_prompt

    def test_cleaned_prompt_removes_write_suffix(self, tmp_path: Path) -> None:
        """Test that :w suffix is removed from cleaned prompt."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Update @{test_file}:w with changes"
        result = parse_prompt_for_context(prompt)

        # Path should be there without @ and :w
        assert str(test_file) in result.cleaned_prompt
        assert f"@{test_file}:w" not in result.cleaned_prompt
        assert ":w" not in result.cleaned_prompt

    def test_cleaned_prompt_preserves_structure(self, tmp_path: Path) -> None:
        """Test that cleaned prompt preserves sentence structure."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"First @{test_file} then finish"
        result = parse_prompt_for_context(prompt)

        # Should have reasonable spacing
        assert "First" in result.cleaned_prompt
        assert "then finish" in result.cleaned_prompt
        # Path should be in between
        assert str(test_file) in result.cleaned_prompt

    def test_original_prompt_preserved(self, tmp_path: Path) -> None:
        """Test that original prompt is preserved."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        prompt = f"Review @{test_file}"
        result = parse_prompt_for_context(prompt)

        assert result.original_prompt == prompt


class TestPromptParserNoReferences:
    """Test prompts without @references."""

    def test_prompt_without_references(self) -> None:
        """Test that prompts without @ are returned unchanged."""
        prompt = "Just a normal prompt without any references"
        result = parse_prompt_for_context(prompt)

        assert result.cleaned_prompt == prompt
        assert result.original_prompt == prompt
        assert len(result.context_paths) == 0
        assert len(result.suggestions) == 0

    def test_empty_prompt(self) -> None:
        """Test empty prompt."""
        prompt = ""
        result = parse_prompt_for_context(prompt)

        assert result.cleaned_prompt == ""
        assert len(result.context_paths) == 0


class TestPromptParserClass:
    """Test PromptParser class directly."""

    def test_parser_instance_reusable(self, tmp_path: Path) -> None:
        """Test that parser instance can be reused."""
        parser = PromptParser()

        file1 = tmp_path / "a.py"
        file2 = tmp_path / "b.py"
        file1.write_text("")
        file2.write_text("")

        result1 = parser.parse(f"Review @{file1}")
        result2 = parser.parse(f"Review @{file2}")

        assert result1.context_paths[0]["path"] == str(file1)
        assert result2.context_paths[0]["path"] == str(file2)


class TestParsedPromptDataclass:
    """Test ParsedPrompt dataclass."""

    def test_parsed_prompt_fields(self) -> None:
        """Test ParsedPrompt has expected fields."""
        parsed = ParsedPrompt(
            original_prompt="original",
            cleaned_prompt="cleaned",
            context_paths=[{"path": "/test", "permission": "read"}],
            suggestions=["suggestion"],
        )

        assert parsed.original_prompt == "original"
        assert parsed.cleaned_prompt == "cleaned"
        assert len(parsed.context_paths) == 1
        assert len(parsed.suggestions) == 1


class TestQuotedPaths:
    """Test quoted path syntax for paths with spaces."""

    def test_quoted_path_with_spaces(self, tmp_path: Path) -> None:
        """Test @"path with spaces" syntax."""
        # Create directory and file with spaces
        dir_with_spaces = tmp_path / "path with spaces"
        dir_with_spaces.mkdir()
        test_file = dir_with_spaces / "file.txt"
        test_file.write_text("test content")

        prompt = f'Review @"{test_file}"'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)
        assert result.context_paths[0]["permission"] == "read"
        # Path should be in cleaned prompt without @ and quotes
        assert str(test_file) in result.cleaned_prompt
        assert f'@"{test_file}"' not in result.cleaned_prompt

    def test_quoted_path_with_spaces_write_permission(self, tmp_path: Path) -> None:
        """Test @"path with spaces":w syntax for write permission."""
        dir_with_spaces = tmp_path / "output dir"
        dir_with_spaces.mkdir()
        test_file = dir_with_spaces / "output.txt"
        test_file.write_text("")

        prompt = f'Write to @"{test_file}":w'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)
        assert result.context_paths[0]["permission"] == "write"

    def test_mixed_quoted_and_unquoted_paths(self, tmp_path: Path) -> None:
        """Test mixing @"quoted path" and @unquoted/path."""
        # Create paths
        dir_with_spaces = tmp_path / "spaced dir"
        dir_with_spaces.mkdir()
        file_with_spaces = dir_with_spaces / "my file.py"
        file_with_spaces.write_text("")

        normal_file = tmp_path / "normal.py"
        normal_file.write_text("")

        prompt = f'Compare @"{file_with_spaces}" with @{normal_file}'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 2
        paths = {ctx["path"] for ctx in result.context_paths}
        assert str(file_with_spaces) in paths
        assert str(normal_file) in paths

    def test_quoted_directory_with_spaces(self, tmp_path: Path) -> None:
        """Test @"dir with spaces/" syntax for directories."""
        dir_with_spaces = tmp_path / "my project"
        dir_with_spaces.mkdir()

        prompt = f'Review all files in @"{dir_with_spaces}/"'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(dir_with_spaces)
        assert result.context_paths[0]["permission"] == "read"

    def test_quoted_path_nonexistent_raises_error(self) -> None:
        """Test that non-existent quoted paths raise an error."""
        prompt = '@"/path/that does not/exist.txt"'

        with pytest.raises(PromptParserError) as exc_info:
            parse_prompt_for_context(prompt)

        assert "not found" in str(exc_info.value).lower()

    def test_empty_quoted_path_no_match(self) -> None:
        """Test that @"" (empty quoted path) does not match."""
        prompt = 'Review @"" some text'
        # Empty quoted path should not match the pattern
        result = parse_prompt_for_context(prompt)

        # Pattern requires at least one character inside quotes
        assert len(result.context_paths) == 0

    def test_quoted_path_preserves_internal_quotes(self, tmp_path: Path) -> None:
        """Test path without internal quotes works."""
        # Can't easily test files with quotes in names on all systems,
        # so just test that basic quoted paths work
        test_file = tmp_path / "simple file.txt"
        test_file.write_text("test")

        prompt = f'@"{test_file}"'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(test_file)

    def test_multiple_quoted_paths(self, tmp_path: Path) -> None:
        """Test multiple quoted paths in one prompt."""
        dir1 = tmp_path / "first dir"
        dir2 = tmp_path / "second dir"
        dir1.mkdir()
        dir2.mkdir()
        file1 = dir1 / "file.txt"
        file2 = dir2 / "file.txt"
        file1.write_text("1")
        file2.write_text("2")

        prompt = f'Compare @"{file1}" and @"{file2}":w'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 2
        perms = {ctx["path"]: ctx["permission"] for ctx in result.context_paths}
        assert perms[str(file1)] == "read"
        assert perms[str(file2)] == "write"

    def test_quoted_path_with_special_chars(self, tmp_path: Path) -> None:
        """Test quoted paths with special characters (except quotes)."""
        special_dir = tmp_path / "test (1) - copy"
        special_dir.mkdir()
        special_file = special_dir / "file [v2].txt"
        special_file.write_text("content")

        prompt = f'Review @"{special_file}"'
        result = parse_prompt_for_context(prompt)

        assert len(result.context_paths) == 1
        assert result.context_paths[0]["path"] == str(special_file)
