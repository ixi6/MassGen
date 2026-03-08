"""Tests for the AtPathCompleter class."""

import tempfile
from pathlib import Path

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from massgen.path_handling import AtPathCompleter


def get_completions(completer: AtPathCompleter, text: str) -> list[str]:
    """Helper to get completion texts from a completer."""
    doc = Document(text)
    event = CompleteEvent()
    return [c.text for c in completer.get_completions(doc, event)]


class TestAtPathCompleterBasics:
    """Basic tests for AtPathCompleter."""

    def test_no_at_symbol_returns_no_completions(self):
        """Test that text without @ returns no completions."""
        completer = AtPathCompleter()
        completions = get_completions(completer, "hello world")
        assert completions == []

    def test_at_symbol_triggers_completion(self):
        """Test that @ symbol triggers path completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Type @t and expect test.py completion
            completions = get_completions(completer, "@t")
            # Should have at least the test.py file
            assert any("test.py" in c for c in completions)

    def test_escaped_at_symbol_ignored(self):
        """Test that \\@ is treated as literal and not completed."""
        completer = AtPathCompleter()
        completions = get_completions(completer, "\\@test")
        # Should return no completions because @ is escaped
        assert completions == []

    def test_at_after_space_triggers_completion(self):
        """Test that @ after space triggers completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "file.txt"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "Review @f")
            assert any("file.txt" in c for c in completions)


class TestWriteModeSuffix:
    """Tests for :w suffix handling."""

    def test_write_suffix_preserved(self):
        """Test that :w suffix is preserved in completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "config.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@config:w")
            # Should have completion with :w
            assert any(":w" in c for c in completions)

    def test_write_variant_offered_for_files(self):
        """Test that :w variant is offered for files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "main.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@main")

            # Should have both read and write variants
            assert any("@main.py" in c and ":w" not in c for c in completions)
            assert any("@main.py:w" in c for c in completions)


class TestDirectoryHandling:
    """Tests for directory path handling."""

    def test_directory_gets_trailing_slash(self):
        """Test that directory paths get trailing slash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "subdir"
            test_dir.mkdir()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@sub")

            # Should have directory with trailing slash
            assert any("subdir/" in c for c in completions)


class TestEmailDetection:
    """Tests for email address detection."""

    def test_email_not_treated_as_path(self):
        """Test that email addresses don't trigger completion."""
        completer = AtPathCompleter()
        # "user@gmail.com" should not trigger completion
        completions = get_completions(completer, "Contact user@gmail")
        # The @ in email context should be ignored
        assert completions == []

    def test_at_start_is_path(self):
        """Test that @ at start of word is treated as path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "src"
            test_file.mkdir()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@s")
            # Should get src directory
            assert any("src" in c for c in completions)


class TestPathResolution:
    """Tests for path resolution."""

    def test_relative_path_resolution(self):
        """Test that relative paths are resolved correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b"
            nested.mkdir(parents=True)
            test_file = nested / "file.txt"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@a/b/f")
            assert any("file.txt" in c for c in completions)

    def test_home_directory_expansion(self):
        """Test that ~ is expanded."""
        completer = AtPathCompleter(expanduser=True)
        # Just test that it doesn't error
        completions = get_completions(completer, "@~/")
        # Should return some completions (home directory contents)
        # We can't assert specific files but shouldn't error
        assert isinstance(completions, list)


class TestFileTypeDisplay:
    """Tests for file type detection in display."""

    def test_python_file_detected(self):
        """Test that .py extension is recognized."""
        completer = AtPathCompleter()
        assert completer._get_file_type("test.py") == "python"

    def test_javascript_file_detected(self):
        """Test that .js extension is recognized."""
        completer = AtPathCompleter()
        assert completer._get_file_type("app.js") == "javascript"

    def test_unknown_extension_returns_plaintext(self):
        """Test that unknown extensions return plaintext."""
        completer = AtPathCompleter()
        assert completer._get_file_type("file.xyz") == "plaintext"

    def test_yaml_file_detected(self):
        """Test that .yaml extension is recognized."""
        completer = AtPathCompleter()
        assert completer._get_file_type("config.yaml") == "yaml"


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_input_no_completions(self):
        """Test that empty input returns no completions."""
        completer = AtPathCompleter()
        completions = get_completions(completer, "")
        assert completions == []

    def test_just_at_returns_completions(self):
        """Test that just @ returns root completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@")
            # Should have at least test.txt
            assert len(completions) > 0

    def test_multiple_at_symbols(self):
        """Test handling of multiple @ in prompt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "first.py"
            file2 = Path(tmpdir) / "second.py"
            file1.touch()
            file2.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Only the last @ should be completed
            completions = get_completions(completer, "@first.py and @sec")
            # Should complete to second.py, not first.py
            assert any("second.py" in c for c in completions)
            assert not any("first.py" in c for c in completions)

    def test_path_with_spaces_returns_no_completions(self):
        """Test that paths with spaces return no completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Space in path text should return no completions
            completions = get_completions(completer, "@path with space")
            assert completions == []

    def test_at_followed_by_space_returns_no_completions(self):
        """Test that @ followed by space returns no completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, "@ test")
            assert completions == []


class TestConstructorParameters:
    """Tests for constructor parameters."""

    def test_only_directories_parameter(self):
        """Test only_directories=True excludes files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_dir = Path(tmpdir) / "subdir"
            test_file.touch()
            test_dir.mkdir()

            completer = AtPathCompleter(base_path=Path(tmpdir), only_directories=True)
            completions = get_completions(completer, "@")

            # Should include directory but not file
            assert any("subdir" in c for c in completions)
            assert not any("test.py" in c for c in completions)

    def test_file_filter_parameter(self):
        """Test file_filter parameter filters completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "code.py"
            txt_file = Path(tmpdir) / "notes.txt"
            py_file.touch()
            txt_file.touch()

            # Filter to only show .py files
            def py_filter(filename: str) -> bool:
                return filename.endswith(".py")

            completer = AtPathCompleter(base_path=Path(tmpdir), file_filter=py_filter)
            completions = get_completions(completer, "@")

            # Should include .py file but not .txt file
            assert any("code.py" in c for c in completions)
            assert not any("notes.txt" in c for c in completions)

    def test_partial_write_suffix_typing(self):
        """Test completion while typing :w suffix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # User typing "@test:" should still complete
            completions = get_completions(completer, "@test:")
            assert any("test.py" in c for c in completions)


class TestQuotedPathCompletion:
    """Tests for quoted path completion with spaces."""

    def test_quoted_path_triggers_completion(self):
        """Test that @" triggers quoted path completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, '@"t')
            # Should have test.py completion with quotes
            assert any("test.py" in c for c in completions)

    def test_quoted_path_allows_spaces(self):
        """Test that quoted paths allow spaces in completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a directory with spaces
            spaced_dir = Path(tmpdir) / "my project"
            spaced_dir.mkdir()
            spaced_file = spaced_dir / "file.txt"
            spaced_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Type @"my pro to get completions for "my project"
            completions = get_completions(completer, '@"my ')

            # Should get completions for the spaced directory
            assert any("my project" in c for c in completions)

    def test_quoted_path_completion_includes_quotes(self):
        """Test that completions for quoted paths include closing quote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spaced_dir = Path(tmpdir) / "test dir"
            spaced_dir.mkdir()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, '@"test ')

            # Completions should have proper quote format
            assert any(c.startswith('@"') and '"' in c[2:] for c in completions)

    def test_quoted_path_with_write_suffix(self):
        """Test @"path with space":w completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spaced_dir = Path(tmpdir) / "out dir"
            spaced_dir.mkdir()
            out_file = spaced_dir / "out.txt"
            out_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, '@"out dir/out:w')

            # Should have :w suffix preserved
            assert any(":w" in c for c in completions)

    def test_space_in_unquoted_still_returns_no_completions(self):
        """Test that unquoted paths with spaces still return no completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Without quotes, space should stop completion
            completions = get_completions(completer, "@path with space")
            assert completions == []

    def test_files_with_spaces_auto_quoted(self):
        """Test that files with spaces in names get quoted in completions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with space in name
            spaced_file = Path(tmpdir) / "my file.txt"
            spaced_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Type @"my to start completing in quoted mode
            completions = get_completions(completer, '@"my')

            # Should get quoted completion for spaced file
            assert any("my file.txt" in c for c in completions)
            # All completions should have quotes
            assert all(c.startswith('@"') for c in completions if "my file" in c)

    def test_unquoted_input_auto_quotes_for_spaced_files(self):
        """Test that typing @prefix (unquoted) auto-quotes if file has spaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with space in name
            spaced_file = Path(tmpdir) / "myfile with spaces.txt"
            spaced_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            # Type @myf unquoted - completion should auto-quote since file has spaces
            completions = get_completions(completer, "@myf")

            # Should get quoted completion
            assert any("myfile with spaces" in c for c in completions)
            # Completions for spaced files should be auto-quoted
            for c in completions:
                if "myfile with spaces" in c:
                    assert c.startswith('@"'), f"Expected quoted path but got: {c}"
                    assert c.endswith('"') or c.endswith('":w'), f"Expected closing quote but got: {c}"

    def test_nested_directory_with_spaces(self):
        """Test completion for nested directories with spaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure with spaces
            parent = Path(tmpdir) / "parent dir"
            child = parent / "child dir"
            child.mkdir(parents=True)
            nested_file = child / "file.txt"
            nested_file.touch()

            completer = AtPathCompleter(base_path=Path(tmpdir))
            completions = get_completions(completer, '@"parent dir/child')

            # Should complete to child dir
            assert any("child dir" in c for c in completions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
