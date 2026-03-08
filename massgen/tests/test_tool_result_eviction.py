#!/usr/bin/env python3
"""
Unit tests for tool result eviction feature.

Tests the automatic eviction of large tool results to files when they exceed
the token threshold, preventing context window saturation.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from massgen.filesystem_manager._constants import (
    EVICTED_RESULTS_DIR,
    TOOL_RESULT_EVICTION_PREVIEW_TOKENS,
    TOOL_RESULT_EVICTION_THRESHOLD_TOKENS,
)


class TestToolResultEvictionConstants:
    """Test that eviction constants are properly defined."""

    def test_threshold_is_reasonable(self):
        """Threshold should be a reasonable value (e.g., 20000 tokens)."""
        assert TOOL_RESULT_EVICTION_THRESHOLD_TOKENS == 20_000

    def test_preview_tokens_less_than_threshold(self):
        """Preview should be smaller than threshold."""
        assert TOOL_RESULT_EVICTION_PREVIEW_TOKENS < TOOL_RESULT_EVICTION_THRESHOLD_TOKENS

    def test_evicted_results_dir_is_hidden(self):
        """Evicted results directory should be hidden (starts with .)."""
        assert EVICTED_RESULTS_DIR.startswith(".")


class TestTruncateToTokenLimit:
    """Test the _truncate_to_token_limit helper method."""

    @pytest.fixture
    def mock_backend(self):
        """Create a mock backend with token calculator."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        # Create backend with mocked token calculator
        with patch.object(ChatCompletionsBackend, "__init__", lambda self: None):
            backend = ChatCompletionsBackend()
            backend.token_calculator = MagicMock()
            backend.filesystem_manager = None
            return backend

    def test_text_under_limit_returned_unchanged(self, mock_backend):
        """Text under token limit should be returned as-is."""
        text = "Short text"
        mock_backend.token_calculator.estimate_tokens.return_value = 5

        result = mock_backend._truncate_to_token_limit(text, max_tokens=100)

        assert result == text

    def test_text_over_limit_truncated(self, mock_backend):
        """Text over token limit should be truncated."""
        text = "A" * 1000  # Long text

        # Simulate token counting: returns len/4 (approx 4 chars per token)
        def mock_token_count(t):
            return len(t) // 4

        mock_backend.token_calculator.estimate_tokens.side_effect = mock_token_count

        result = mock_backend._truncate_to_token_limit(text, max_tokens=50)

        # Should be truncated to approximately 50 tokens (~200 chars)
        assert len(result) < len(text)
        assert mock_backend.token_calculator.estimate_tokens(result) <= 50

    def test_empty_text_returns_empty(self, mock_backend):
        """Empty text should return empty."""
        mock_backend.token_calculator.estimate_tokens.return_value = 0

        result = mock_backend._truncate_to_token_limit("", max_tokens=100)

        assert result == ""


class TestMaybeEvictLargeToolResult:
    """Test the _maybe_evict_large_tool_result method."""

    @pytest.fixture
    def mock_backend_with_workspace(self):
        """Create a mock backend with workspace directory."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        with patch.object(ChatCompletionsBackend, "__init__", lambda self: None):
            backend = ChatCompletionsBackend()
            backend.token_calculator = MagicMock()

            # Create temporary workspace
            temp_dir = tempfile.mkdtemp()
            backend.filesystem_manager = MagicMock()
            backend.filesystem_manager.cwd = Path(temp_dir)

            yield backend

            # Cleanup
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_small_result_not_evicted(self, mock_backend_with_workspace):
        """Results under threshold should not be evicted."""
        result_text = "Small result"
        mock_backend_with_workspace.token_calculator.estimate_tokens.return_value = 100

        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call123",
        )

        assert was_evicted is False
        assert result == result_text

    def test_large_result_evicted_to_file(self, mock_backend_with_workspace):
        """Results over threshold should be evicted to file."""
        # Create a large result (simulate >20k tokens)
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4  # ~25k tokens for 100k chars

        mock_backend_with_workspace.token_calculator.estimate_tokens.side_effect = mock_token_count

        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call12345678",
        )

        assert was_evicted is True
        assert "[Tool Result Evicted" in result
        assert "test_tool" in result
        assert EVICTED_RESULTS_DIR in result

    def test_evicted_file_created(self, mock_backend_with_workspace):
        """Evicted file should be created in workspace."""
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4

        mock_backend_with_workspace.token_calculator.estimate_tokens.side_effect = mock_token_count

        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call12345678",
        )

        # Check file was created
        eviction_dir = mock_backend_with_workspace.filesystem_manager.cwd / EVICTED_RESULTS_DIR
        assert eviction_dir.exists()

        files = list(eviction_dir.glob("*.txt"))
        assert len(files) == 1

        # Verify file contents
        file_content = files[0].read_text()
        assert file_content == result_text

    def test_reference_contains_char_info(self, mock_backend_with_workspace):
        """Reference message should contain character position info."""
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4

        mock_backend_with_workspace.token_calculator.estimate_tokens.side_effect = mock_token_count

        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call12345678",
        )

        # Should contain character info for chunked reading
        assert "chars" in result.lower()
        assert "100,000" in result  # Total chars
        assert "Preview (chars 0-" in result

    def test_reference_contains_token_info(self, mock_backend_with_workspace):
        """Reference message should contain token count info."""
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4

        mock_backend_with_workspace.token_calculator.estimate_tokens.side_effect = mock_token_count

        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call12345678",
        )

        # Should contain token info
        assert "tokens" in result.lower()
        assert f"{TOOL_RESULT_EVICTION_THRESHOLD_TOKENS:,}" in result

    def test_no_workspace_returns_original(self):
        """Without workspace, should return original result."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        with patch.object(ChatCompletionsBackend, "__init__", lambda self: None):
            backend = ChatCompletionsBackend()
            backend.token_calculator = MagicMock()
            backend.token_calculator.estimate_tokens.return_value = 50_000
            backend.filesystem_manager = None  # No workspace

            result_text = "Large result"
            result, was_evicted = backend._maybe_evict_large_tool_result(
                result_text,
                "test_tool",
                "call123",
            )

            assert was_evicted is False
            assert result == result_text

    def test_filename_sanitization(self, mock_backend_with_workspace):
        """Tool names with special chars should be sanitized in filename."""
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4

        mock_backend_with_workspace.token_calculator.estimate_tokens.side_effect = mock_token_count

        # Use tool name with special characters
        result, was_evicted = mock_backend_with_workspace._maybe_evict_large_tool_result(
            result_text,
            "mcp::filesystem::read_file",
            "call12345678",
        )

        # Check file was created with sanitized name
        eviction_dir = mock_backend_with_workspace.filesystem_manager.cwd / EVICTED_RESULTS_DIR
        files = list(eviction_dir.glob("*.txt"))
        assert len(files) == 1

        # Filename should not contain colons
        assert "::" not in files[0].name
        assert "mcp__filesystem__read_file" in files[0].name


class TestEvictionIntegration:
    """Integration tests for eviction in tool execution flow."""

    @pytest.fixture
    def mock_backend_full(self):
        """Create a more complete mock backend."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        with patch.object(ChatCompletionsBackend, "__init__", lambda self: None):
            backend = ChatCompletionsBackend()

            # Token calculator
            backend.token_calculator = MagicMock()

            # Filesystem manager with temp directory
            temp_dir = tempfile.mkdtemp()
            backend.filesystem_manager = MagicMock()
            backend.filesystem_manager.cwd = Path(temp_dir)

            # Other required attributes
            backend.agent_id = "test_agent"
            backend._current_round_number = 1
            backend._tool_execution_metrics = []

            yield backend

            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_preview_respects_token_limit(self, mock_backend_full):
        """Preview should respect TOOL_RESULT_EVICTION_PREVIEW_TOKENS."""
        result_text = "A" * 100_000

        def mock_token_count(t):
            return len(t) // 4

        mock_backend_full.token_calculator.estimate_tokens.side_effect = mock_token_count

        result, was_evicted = mock_backend_full._maybe_evict_large_tool_result(
            result_text,
            "test_tool",
            "call12345678",
        )

        # Extract preview from result
        preview_start = result.find("Preview (chars")
        assert preview_start > 0

        # The preview should be approximately TOOL_RESULT_EVICTION_PREVIEW_TOKENS tokens
        # which is ~8000 chars with our mock (4 chars per token)
        # Binary search may not hit exactly, so check it's in a reasonable range
        import re

        # Match comma-formatted numbers like "8,000"
        match = re.search(r"chars 0-([\d,]+)", result)
        assert match, "Preview should contain character range"
        preview_end = int(match.group(1).replace(",", ""))

        expected_preview_chars = TOOL_RESULT_EVICTION_PREVIEW_TOKENS * 4  # 8000
        # Allow some tolerance due to binary search granularity
        assert preview_end >= expected_preview_chars - 100, f"Preview too short: {preview_end}"
        assert preview_end <= expected_preview_chars + 100, f"Preview too long: {preview_end}"
