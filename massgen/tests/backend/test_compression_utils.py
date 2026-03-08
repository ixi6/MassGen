"""Unit tests for compression utilities.

Tests the core compression recovery logic in _compression_utils.py.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from massgen.backend._compression_utils import (
    _ensure_fits_context,
    _format_messages_for_summary,
    _get_context_window_for_backend,
    _truncate_to_token_budget,
    compress_messages_for_recovery,
)
from massgen.backend.base import StreamChunk

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_backend():
    """Create a mock backend for testing."""
    backend = MagicMock()
    backend.get_provider_name.return_value = "test_provider"
    backend.config = {"model": "test-model"}
    return backend


@pytest.fixture
def sample_messages():
    """Sample conversation messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you for asking!"},
        {"role": "user", "content": "Can you help me write some code?"},
        {"role": "assistant", "content": "Of course! What would you like me to help you with?"},
        {"role": "user", "content": "Write a Python function to calculate fibonacci."},
    ]


@pytest.fixture
def large_message():
    """Create a large message for truncation testing."""
    # ~50k characters, roughly 12k tokens
    return "x" * 50000


# =============================================================================
# Tests for _truncate_to_token_budget
# =============================================================================


class TestTruncateToTokenBudget:
    """Tests for _truncate_to_token_budget function."""

    def test_text_under_limit_unchanged(self):
        """Text under the token limit should not be modified."""
        text = "This is a short text."
        result = _truncate_to_token_budget(text, max_tokens=1000)
        assert result == text

    def test_text_over_limit_truncated(self):
        """Text over the token limit should be truncated."""
        # Create text that's definitely over 100 tokens
        text = "word " * 500  # ~500 tokens
        result = _truncate_to_token_budget(text, max_tokens=100)

        # Should be shorter than original
        assert len(result) < len(text)
        # Should have truncation marker
        assert "[... truncated to fit context ...]" in result

    def test_truncation_respects_limit(self):
        """Truncated text should be within the token budget."""
        from massgen.token_manager import TokenCostCalculator

        calc = TokenCostCalculator()
        text = "word " * 1000
        max_tokens = 200

        result = _truncate_to_token_budget(text, max_tokens)
        result_tokens = calc.estimate_tokens(result)

        # Should be at or under the limit (with some tolerance for the marker)
        assert result_tokens <= max_tokens + 20  # Allow small margin for marker

    def test_empty_text(self):
        """Empty text should return empty."""
        result = _truncate_to_token_budget("", max_tokens=100)
        assert result == ""

    def test_single_token_limit(self):
        """Should handle very small token limits."""
        text = "This is a test sentence with several words. " * 10
        result = _truncate_to_token_budget(text, max_tokens=5)

        # Should be truncated (result may include marker, so check content is shorter)
        assert "[... truncated to fit context ...]" in result
        # The actual content before marker should be much shorter
        content_before_marker = result.split("[... truncated")[0]
        assert len(content_before_marker) < len(text)


# =============================================================================
# Tests for _format_messages_for_summary
# =============================================================================


class TestFormatMessagesForSummary:
    """Tests for _format_messages_for_summary function."""

    def test_basic_message_formatting(self):
        """Basic messages should be formatted with role labels."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = _format_messages_for_summary(messages)

        assert "[user]" in result
        assert "Hello" in result
        assert "[assistant]" in result
        assert "Hi there!" in result
        assert "---" in result  # Separator

    def test_tool_call_formatting(self):
        """Tool calls should be formatted specially."""
        messages = [
            {
                "type": "function_call",
                "name": "read_file",
                "arguments": '{"path": "/test.txt"}',
            },
        ]
        result = _format_messages_for_summary(messages)

        assert "[Tool Call: read_file]" in result
        assert "Arguments:" in result
        assert "/test.txt" in result

    def test_tool_result_formatting(self):
        """Tool results should be formatted specially."""
        messages = [
            {"type": "function_call_output", "output": "File contents here"},
        ]
        result = _format_messages_for_summary(messages)

        assert "[Tool Result]" in result
        assert "File contents here" in result

    def test_multimodal_content(self):
        """Multimodal content (list format) should extract text."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What's in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/..."}},
                ],
            },
        ]
        result = _format_messages_for_summary(messages)

        assert "[user]" in result
        assert "What's in this image?" in result

    def test_empty_messages(self):
        """Empty message list should return empty string."""
        result = _format_messages_for_summary([])
        assert result == ""

    def test_message_with_missing_content(self):
        """Messages with missing content should be handled gracefully."""
        messages = [{"role": "user"}]  # No content
        result = _format_messages_for_summary(messages)

        assert "[user]" in result


# =============================================================================
# Tests for _ensure_fits_context
# =============================================================================


class TestEnsureFitsContext:
    """Tests for _ensure_fits_context function."""

    def test_messages_under_limit_unchanged(self, mock_backend):
        """Messages under the context limit should pass through unchanged."""
        messages = [
            {"role": "system", "content": "Short system prompt."},
            {"role": "user", "content": "Short message."},
        ]
        result = _ensure_fits_context(messages, mock_backend)

        assert result == messages

    def test_messages_over_limit_truncated(self, mock_backend):
        """Messages over the context limit should be truncated."""
        # Create messages that exceed the limit
        large_content = "x" * 50000  # Very large
        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "assistant", "content": large_content},
        ]

        # Patch to use a small context window for testing
        with patch(
            "massgen.backend._compression_utils._get_context_window_for_backend",
            return_value=(1000, "test"),
        ):
            result = _ensure_fits_context(messages, mock_backend)

        # The large message should be truncated
        assert len(result[1]["content"]) < len(large_content)
        assert "[... truncated to fit context ...]" in result[1]["content"]

    def test_truncates_largest_message(self, mock_backend):
        """Should truncate the largest message, not others."""
        small_content = "small message"
        large_content = "x" * 50000

        messages = [
            {"role": "user", "content": small_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": small_content},
        ]

        # Patch to use a small context window for testing
        with patch(
            "massgen.backend._compression_utils._get_context_window_for_backend",
            return_value=(2000, "test"),
        ):
            result = _ensure_fits_context(messages, mock_backend)

        # Small messages should be unchanged
        assert result[0]["content"] == small_content
        assert result[2]["content"] == small_content
        # Large message should be truncated
        assert len(result[1]["content"]) < len(large_content)

    def test_no_truncatable_content(self, mock_backend):
        """Should handle messages with no truncatable string content."""

        # Multimodal content (list, not string) - can't truncate
        messages = [
            {
                "role": "user",
                "content": [{"type": "image", "data": "..."}],
            },
        ]

        result = _ensure_fits_context(messages, mock_backend)
        # Should return unchanged (can't truncate list content)
        assert result == messages


# =============================================================================
# Tests for _get_context_window_for_backend
# =============================================================================


class TestGetContextWindowForBackend:
    """Tests for _get_context_window_for_backend function."""

    def test_uses_token_calculator(self):
        """Should use TokenCostCalculator to get context window."""
        backend = MagicMock()
        backend.get_provider_name.return_value = "openai"
        backend.config = {"model": "gpt-4o"}

        window, source = _get_context_window_for_backend(backend)

        # Should get a reasonable value from the calculator or fallback
        assert window > 0
        assert "TokenCostCalculator" in source or "fallback" in source

    def test_falls_back_to_default(self):
        """Should fall back to 128k default if nothing else works."""
        backend = MagicMock()
        backend.get_provider_name.return_value = "unknown_provider"
        backend.config = {"model": "unknown-model"}

        window, source = _get_context_window_for_backend(backend)

        assert window == 128000
        assert "fallback" in source


# =============================================================================
# Tests for compress_messages_for_recovery
# =============================================================================


class TestCompressMessagesForRecovery:
    """Tests for compress_messages_for_recovery function."""

    @pytest.fixture
    def mock_streaming_backend(self):
        """Create a mock backend that streams summary responses."""

        async def mock_stream(*args, **kwargs):
            yield StreamChunk(type="content", content="Summary: ")
            yield StreamChunk(type="content", content="User asked for help. ")
            yield StreamChunk(type="content", content="Work was completed.")

        backend = MagicMock()
        backend.get_provider_name.return_value = "test"
        backend.config = {"model": "test-model"}
        backend.stream_with_tools = mock_stream
        return backend

    @pytest.mark.asyncio
    async def test_preserves_system_message(self, mock_streaming_backend, sample_messages):
        """System message should NEVER be compressed."""
        result = await compress_messages_for_recovery(
            sample_messages,
            mock_streaming_backend,
            target_ratio=0.2,
        )

        # System message should be first and unchanged
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."

    @pytest.mark.asyncio
    async def test_returns_original_when_only_system_message(self, mock_streaming_backend):
        """Should return original if only system message exists."""
        messages = [{"role": "system", "content": "System prompt only."}]

        result = await compress_messages_for_recovery(
            messages,
            mock_streaming_backend,
        )

        assert result == messages

    @pytest.mark.asyncio
    async def test_returns_original_when_nothing_to_compress(self, mock_streaming_backend):
        """Should return original if there's nothing to compress."""
        # Only 2 messages - with 0.2 ratio, we'd keep 1 and compress 1
        # But if preserve_count >= total, we keep all
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Hello"},
        ]

        result = await compress_messages_for_recovery(
            messages,
            mock_streaming_backend,
            target_ratio=0.9,  # High ratio means keep more
        )

        # With only 1 conversation message and high ratio, should return original
        assert result == messages

    @pytest.mark.asyncio
    async def test_compresses_older_messages(self, mock_streaming_backend, sample_messages):
        """Older messages should be compressed into a summary."""
        result = await compress_messages_for_recovery(
            sample_messages,
            mock_streaming_backend,
            target_ratio=0.2,
        )

        # Should have fewer messages than original
        assert len(result) < len(sample_messages)

        # Last message should be the assistant summary
        assert result[-1]["role"] == "assistant"
        assert "[CONTEXT RECOVERY" in result[-1]["content"]

    @pytest.mark.asyncio
    async def test_includes_buffer_content_in_summary(self, mock_streaming_backend, sample_messages):
        """Buffer content should be included in the summarization."""
        buffer_content = "Tool result: File read successfully with 1000 lines."

        # We need to verify the buffer is passed to summarization
        # The mock will generate a summary regardless, but we can check the flow
        result = await compress_messages_for_recovery(
            sample_messages,
            mock_streaming_backend,
            target_ratio=0.2,
            buffer_content=buffer_content,
        )

        # Should complete without error and produce compressed result
        assert len(result) < len(sample_messages)
        assert result[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_buffer_only_compression(self, mock_streaming_backend):
        """Should handle case where only buffer content needs summarization."""
        # Few messages but large buffer
        messages = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Read the file."},
        ]
        buffer_content = "Massive tool output: " + "data " * 1000

        result = await compress_messages_for_recovery(
            messages,
            mock_streaming_backend,
            target_ratio=0.5,
            buffer_content=buffer_content,
        )

        # Should produce a result with summary
        assert any("[CONTEXT RECOVERY" in str(msg.get("content", "")) for msg in result)

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, mock_backend, sample_messages):
        """Should fall back to truncation message on API errors."""

        async def mock_stream_error(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "Rate limit exceeded",
                request=MagicMock(),
                response=MagicMock(status_code=429),
            )
            yield  # Make it a generator

        with patch("massgen.cli.create_backend") as mock_create:
            mock_compression_backend = MagicMock()
            mock_compression_backend.stream_with_tools = mock_stream_error
            mock_create.return_value = mock_compression_backend

            result = await compress_messages_for_recovery(
                sample_messages,
                mock_backend,
                target_ratio=0.2,
            )

        # Should still produce a result
        assert len(result) > 0
        # Summary should indicate API error
        assert any("API error" in str(msg.get("content", "")) for msg in result)

    @pytest.mark.asyncio
    async def test_handles_timeout_error_gracefully(self, mock_backend, sample_messages):
        """Should fall back to truncation message on timeout."""

        async def mock_stream_timeout(*args, **kwargs):
            raise TimeoutError("Request timed out")
            yield  # Make it a generator

        with patch("massgen.cli.create_backend") as mock_create:
            mock_compression_backend = MagicMock()
            mock_compression_backend.stream_with_tools = mock_stream_timeout
            mock_create.return_value = mock_compression_backend

            result = await compress_messages_for_recovery(
                sample_messages,
                mock_backend,
                target_ratio=0.2,
            )

        # Should still produce a result
        assert len(result) > 0
        # Summary should indicate API error (timeout is treated as API error)
        assert any("API error" in str(msg.get("content", "")) for msg in result)

    @pytest.mark.asyncio
    async def test_handles_unexpected_error_gracefully(self, mock_backend, sample_messages):
        """Should fall back to truncation message on unexpected errors."""

        async def mock_stream_error(*args, **kwargs):
            raise ValueError("Unexpected error in summarization")
            yield  # Make it a generator

        mock_backend.stream_with_tools = mock_stream_error

        result = await compress_messages_for_recovery(
            sample_messages,
            mock_backend,
            target_ratio=0.2,
        )

        # Should still produce a result
        assert len(result) > 0
        # Summary should indicate fallback guidance (tells agent how to recover)
        assert any("summarization failed" in str(msg.get("content", "")).lower() for msg in result)

    @pytest.mark.asyncio
    async def test_result_has_valid_message_structure(self, mock_streaming_backend, sample_messages):
        """Compressed result should have valid message structure for API calls."""
        result = await compress_messages_for_recovery(
            sample_messages,
            mock_streaming_backend,
            target_ratio=0.2,
        )

        for msg in result:
            # Each message should have role and content
            assert "role" in msg
            assert "content" in msg
            assert msg["role"] in ["system", "user", "assistant"]
            assert isinstance(msg["content"], str)

    @pytest.mark.asyncio
    async def test_strips_trailing_whitespace(self, mock_streaming_backend, sample_messages):
        """Summary should have trailing whitespace stripped (Claude API requirement)."""

        async def mock_stream_with_whitespace(*args, **kwargs):
            yield StreamChunk(type="content", content="Summary with trailing space   \n\n")

        mock_streaming_backend.stream_with_tools = mock_stream_with_whitespace

        result = await compress_messages_for_recovery(
            sample_messages,
            mock_streaming_backend,
            target_ratio=0.2,
        )

        # The assistant message content should not have trailing whitespace
        assistant_msg = result[-1]
        assert assistant_msg["role"] == "assistant"
        assert not assistant_msg["content"].endswith(" ")
        assert not assistant_msg["content"].endswith("\n")

    @pytest.mark.asyncio
    async def test_filters_mcp_status_chunks(self, sample_messages):
        """Should filter out mcp_status chunks from summary."""

        async def mock_stream_with_mcp(*args, **kwargs):
            yield StreamChunk(type="mcp_status", content="Connecting to MCP server...")
            yield StreamChunk(type="content", content="Actual summary content")
            yield StreamChunk(type="mcp_status", content="Tool registered")

        backend = MagicMock()
        backend.get_provider_name.return_value = "test"
        backend.config = {"model": "test-model"}
        backend.api_key = "test-key"

        with patch("massgen.cli.create_backend") as mock_create:
            mock_compression_backend = MagicMock()
            mock_compression_backend.stream_with_tools = mock_stream_with_mcp
            mock_create.return_value = mock_compression_backend

            result = await compress_messages_for_recovery(
                sample_messages,
                backend,
                target_ratio=0.2,
            )

        # Summary should only contain actual content, not MCP status
        summary_content = result[-1]["content"]
        assert "Connecting to MCP" not in summary_content
        assert "Tool registered" not in summary_content
        assert "Actual summary content" in summary_content

    @pytest.mark.asyncio
    async def test_compression_uses_cloned_backend(self, sample_messages):
        """Verify compression creates a cloned backend instead of reusing original.

        Regression test for bug where using the same backend for compression
        triggered __aexit__ cleanup which cleared _mcp_functions.
        """
        backend = MagicMock()
        backend.config = {"model": "gpt-4", "mcp_servers": ["server1"], "custom_tools": ["tool1"]}
        backend.get_provider_name.return_value = "OpenAI"
        backend.api_key = "test-key"

        with patch("massgen.cli.create_backend") as mock_create:
            # Create mock compression backend
            mock_compression_backend = MagicMock()

            async def mock_stream(*args, **kwargs):
                yield StreamChunk(type="content", content="Summary of conversation")

            mock_compression_backend.stream_with_tools = mock_stream
            mock_create.return_value = mock_compression_backend

            await compress_messages_for_recovery(
                sample_messages,
                backend,
                target_ratio=0.2,
            )

            # create_backend should be called to clone the backend
            mock_create.assert_called_once()

            # Verify stripped config - no MCP, no custom tools
            call_kwargs = mock_create.call_args[1]
            assert "mcp_servers" not in call_kwargs
            assert "custom_tools" not in call_kwargs

            # Original backend's stream_with_tools should NOT be called
            backend.stream_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_tools_preserved_after_compression(self, sample_messages):
        """Regression test: MCP tools must not be cleared during compression.

        This tests the fix for the bug where compression recovery would clear
        _mcp_functions on the original backend, causing the retry to lose MCP tools.
        """
        backend = MagicMock()
        backend.config = {"model": "gpt-4"}
        backend.get_provider_name.return_value = "OpenAI"
        backend.api_key = "test-key"
        backend._mcp_functions = {"mcp__filesystem__write_file": MagicMock()}

        with patch("massgen.cli.create_backend") as mock_create:
            mock_compression_backend = MagicMock()

            async def mock_stream(*args, **kwargs):
                yield StreamChunk(type="content", content="Summary")

            mock_compression_backend.stream_with_tools = mock_stream
            mock_create.return_value = mock_compression_backend

            await compress_messages_for_recovery(
                sample_messages,
                backend,
                target_ratio=0.2,
            )

            # MCP tools should still be present on original backend
            assert len(backend._mcp_functions) == 1
            assert "mcp__filesystem__write_file" in backend._mcp_functions
