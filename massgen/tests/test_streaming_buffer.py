"""
Tests for StreamingBufferMixin and its integration with all backends.

Test Categories:
1. Unit tests for StreamingBufferMixin class
2. MRO verification for all backends
3. Buffer behavior tests (clearing, appending, compression retry)
4. Integration tests with mock streaming
"""

from unittest.mock import patch

import pytest

from massgen.backend._streaming_buffer_mixin import StreamingBufferMixin

# =============================================================================
# Unit Tests for StreamingBufferMixin
# =============================================================================


class TestStreamingBufferMixinUnit:
    """Unit tests for StreamingBufferMixin in isolation."""

    def test_mixin_init_creates_empty_buffer(self):
        """Test that mixin initializes with empty buffer."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        assert obj._streaming_buffer == ""
        assert obj._get_streaming_buffer() is None

    def test_clear_streaming_buffer_clears_content(self):
        """Test _clear_streaming_buffer clears the buffer."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._streaming_buffer = "some content"
        obj._clear_streaming_buffer()
        assert obj._streaming_buffer == ""

    def test_clear_streaming_buffer_preserves_on_compression_retry(self):
        """Test buffer is preserved when _compression_retry=True."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._streaming_buffer = "important content for compression"
        obj._clear_streaming_buffer(_compression_retry=True)
        assert obj._streaming_buffer == "important content for compression"

    def test_clear_streaming_buffer_clears_when_retry_false(self):
        """Test buffer clears when _compression_retry=False."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._streaming_buffer = "content"
        obj._clear_streaming_buffer(_compression_retry=False)
        assert obj._streaming_buffer == ""

    def test_append_to_streaming_buffer_adds_content(self):
        """Test _append_to_streaming_buffer appends text."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_to_streaming_buffer("Hello")
        obj._append_to_streaming_buffer(" ")
        obj._append_to_streaming_buffer("World")
        assert obj._streaming_buffer == "Hello World"

    def test_append_to_streaming_buffer_ignores_empty(self):
        """Test empty strings are ignored."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_to_streaming_buffer("content")
        obj._append_to_streaming_buffer("")
        obj._append_to_streaming_buffer(None)  # Should be handled gracefully
        assert obj._streaming_buffer == "content"

    def test_append_tool_to_buffer_formats_result(self):
        """Test tool results are formatted correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_to_buffer("read_file", "file contents here")
        assert "[Tool: read_file]" in obj._streaming_buffer
        assert "file contents here" in obj._streaming_buffer

    def test_append_tool_to_buffer_formats_error(self):
        """Test tool errors are formatted with error prefix."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_to_buffer("write_file", "Permission denied", is_error=True)
        assert "[Tool Error: write_file]" in obj._streaming_buffer
        assert "Permission denied" in obj._streaming_buffer

    def test_append_tool_to_buffer_multiple_tools(self):
        """Test multiple tool results accumulate correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_to_buffer("tool1", "result1")
        obj._append_tool_to_buffer("tool2", "result2", is_error=True)
        obj._append_tool_to_buffer("tool3", "result3")

        buffer = obj._streaming_buffer
        assert "[Tool: tool1]" in buffer
        assert "result1" in buffer
        assert "[Tool Error: tool2]" in buffer
        assert "result2" in buffer
        assert "[Tool: tool3]" in buffer
        assert "result3" in buffer

    def test_append_tool_call_to_buffer_single_call(self):
        """Test tool call request is formatted correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        tool_calls = [{"name": "read_file", "arguments": {"path": "/tmp/test.txt"}}]
        obj._append_tool_call_to_buffer(tool_calls)
        assert "[Tool Call: read_file(" in obj._streaming_buffer
        assert "/tmp/test.txt" in obj._streaming_buffer

    def test_append_tool_call_to_buffer_multiple_calls(self):
        """Test multiple tool calls accumulate correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        tool_calls = [
            {"name": "read_file", "arguments": {"path": "/a.txt"}},
            {"name": "write_file", "arguments": {"path": "/b.txt", "content": "hello"}},
        ]
        obj._append_tool_call_to_buffer(tool_calls)
        buffer = obj._streaming_buffer
        assert "[Tool Call: read_file(" in buffer
        assert "[Tool Call: write_file(" in buffer
        assert "/a.txt" in buffer
        assert "/b.txt" in buffer

    def test_append_tool_call_to_buffer_string_arguments(self):
        """Test tool call with string arguments (JSON string)."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        tool_calls = [{"name": "search", "arguments": '{"query": "test"}'}]
        obj._append_tool_call_to_buffer(tool_calls)
        assert "[Tool Call: search(" in obj._streaming_buffer
        assert "query" in obj._streaming_buffer

    def test_append_tool_call_to_buffer_empty_list(self):
        """Test empty tool call list is ignored."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_call_to_buffer([])
        assert obj._streaming_buffer == ""

    def test_append_reasoning_to_buffer_single(self):
        """Test reasoning content is formatted correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_reasoning_to_buffer("Let me think about this...")
        assert "[Reasoning]" in obj._streaming_buffer
        assert "Let me think about this..." in obj._streaming_buffer

    def test_append_reasoning_to_buffer_streaming(self):
        """Test reasoning content accumulates during streaming."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_reasoning_to_buffer("First ")
        obj._append_reasoning_to_buffer("I need ")
        obj._append_reasoning_to_buffer("to analyze.")
        buffer = obj._streaming_buffer
        # Should have one [Reasoning] header
        assert buffer.count("[Reasoning]") == 1
        assert "First I need to analyze." in buffer

    def test_append_reasoning_to_buffer_empty_ignored(self):
        """Test empty reasoning is ignored."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_reasoning_to_buffer("")
        assert obj._streaming_buffer == ""

    def test_mixed_buffer_content(self):
        """Test buffer with all content types mixed."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        # Simulate a realistic streaming sequence
        obj._append_reasoning_to_buffer("Analyzing the request...")
        obj._append_to_streaming_buffer("I'll help you with that. ")
        obj._append_tool_call_to_buffer([{"name": "read_file", "arguments": {"path": "/test.py"}}])
        obj._append_tool_to_buffer("read_file", "def main(): pass")
        obj._append_to_streaming_buffer("The file contains a main function.")

        buffer = obj._streaming_buffer
        assert "[Reasoning]" in buffer
        assert "Analyzing the request" in buffer
        assert "I'll help you with that" in buffer
        assert "[Tool Call: read_file(" in buffer
        assert "[Tool: read_file]" in buffer
        assert "def main(): pass" in buffer
        assert "main function" in buffer

    def test_get_streaming_buffer_returns_content(self):
        """Test _get_streaming_buffer returns content when present."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._streaming_buffer = "buffer content"
        assert obj._get_streaming_buffer() == "buffer content"

    def test_get_streaming_buffer_returns_none_when_empty(self):
        """Test _get_streaming_buffer returns None when empty."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        assert obj._get_streaming_buffer() is None


# =============================================================================
# MRO and Integration Tests for All Backends
# =============================================================================


class TestBackendMROIntegration:
    """Test that all backends correctly inherit StreamingBufferMixin."""

    def test_response_backend_mro(self):
        """Test ResponseBackend has correct MRO."""
        from massgen.backend.response import ResponseBackend

        mro_names = [c.__name__ for c in ResponseBackend.__mro__]
        # StreamingBufferMixin should come before CustomToolAndMCPBackend
        mixin_idx = mro_names.index("StreamingBufferMixin")
        base_idx = mro_names.index("CustomToolAndMCPBackend")
        assert mixin_idx < base_idx, "StreamingBufferMixin must come before CustomToolAndMCPBackend in MRO"

    def test_chat_completions_backend_mro(self):
        """Test ChatCompletionsBackend has correct MRO."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        mro_names = [c.__name__ for c in ChatCompletionsBackend.__mro__]
        mixin_idx = mro_names.index("StreamingBufferMixin")
        base_idx = mro_names.index("CustomToolAndMCPBackend")
        assert mixin_idx < base_idx, "StreamingBufferMixin must come before CustomToolAndMCPBackend in MRO"

    def test_claude_backend_mro(self):
        """Test ClaudeBackend has correct MRO."""
        from massgen.backend.claude import ClaudeBackend

        mro_names = [c.__name__ for c in ClaudeBackend.__mro__]
        mixin_idx = mro_names.index("StreamingBufferMixin")
        base_idx = mro_names.index("CustomToolAndMCPBackend")
        assert mixin_idx < base_idx, "StreamingBufferMixin must come before CustomToolAndMCPBackend in MRO"

    def test_gemini_backend_mro(self):
        """Test GeminiBackend has correct MRO."""
        from massgen.backend.gemini import GeminiBackend

        mro_names = [c.__name__ for c in GeminiBackend.__mro__]
        mixin_idx = mro_names.index("StreamingBufferMixin")
        base_idx = mro_names.index("CustomToolAndMCPBackend")
        assert mixin_idx < base_idx, "StreamingBufferMixin must come before CustomToolAndMCPBackend in MRO"


class TestBackendBufferMethods:
    """Test that all backends have buffer methods available."""

    @pytest.fixture
    def backend_classes(self):
        """Get all backend classes that should have streaming buffer."""
        from massgen.backend.chat_completions import ChatCompletionsBackend
        from massgen.backend.claude import ClaudeBackend
        from massgen.backend.gemini import GeminiBackend
        from massgen.backend.response import ResponseBackend

        return [
            ("ResponseBackend", ResponseBackend),
            ("ChatCompletionsBackend", ChatCompletionsBackend),
            ("ClaudeBackend", ClaudeBackend),
            ("GeminiBackend", GeminiBackend),
        ]

    def test_all_backends_have_clear_method(self, backend_classes):
        """Test all backends have _clear_streaming_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_clear_streaming_buffer"), f"{name} missing _clear_streaming_buffer"

    def test_all_backends_have_append_content_method(self, backend_classes):
        """Test all backends have _append_to_streaming_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_append_to_streaming_buffer"), f"{name} missing _append_to_streaming_buffer"

    def test_all_backends_have_append_tool_method(self, backend_classes):
        """Test all backends have _append_tool_to_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_append_tool_to_buffer"), f"{name} missing _append_tool_to_buffer"

    def test_all_backends_have_append_tool_call_method(self, backend_classes):
        """Test all backends have _append_tool_call_to_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_append_tool_call_to_buffer"), f"{name} missing _append_tool_call_to_buffer"

    def test_all_backends_have_append_reasoning_method(self, backend_classes):
        """Test all backends have _append_reasoning_to_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_append_reasoning_to_buffer"), f"{name} missing _append_reasoning_to_buffer"

    def test_all_backends_have_get_buffer_method(self, backend_classes):
        """Test all backends have _get_streaming_buffer method."""
        for name, cls in backend_classes:
            assert hasattr(cls, "_get_streaming_buffer"), f"{name} missing _get_streaming_buffer"


# =============================================================================
# Behavioral Tests with Mocked Backends
# =============================================================================


class TestBufferBehaviorWithMockedBackend:
    """Test buffer behavior using a mock backend subclass."""

    @pytest.fixture
    def mock_backend_class(self):
        """Create a testable backend class with mixin."""

        class MockBackend(StreamingBufferMixin):
            """Mock backend for testing buffer behavior."""

            def __init__(self):
                super().__init__()
                self.stream_calls = []

            async def stream_with_tools(self, messages, tools, **kwargs):
                """Mock stream that tracks buffer behavior."""
                self._clear_streaming_buffer(**kwargs)
                self.stream_calls.append({"messages": messages, "kwargs": kwargs})

                # Simulate streaming content
                for text in ["Hello", " ", "World"]:
                    self._append_to_streaming_buffer(text)
                    yield {"type": "content", "content": text}

                # Simulate tool result
                self._append_tool_to_buffer("test_tool", "tool output")
                yield {"type": "tool_result", "name": "test_tool", "result": "tool output"}

                yield {"type": "done"}

        return MockBackend

    @pytest.mark.asyncio
    async def test_buffer_cleared_at_stream_start(self, mock_backend_class):
        """Test buffer is cleared at start of stream_with_tools."""
        backend = mock_backend_class()
        backend._streaming_buffer = "old content"

        chunks = []
        async for chunk in backend.stream_with_tools([], []):
            chunks.append(chunk)

        # Old content should be gone
        assert "old content" not in backend._streaming_buffer

    @pytest.mark.asyncio
    async def test_buffer_accumulates_content(self, mock_backend_class):
        """Test buffer accumulates streaming content."""
        backend = mock_backend_class()

        async for chunk in backend.stream_with_tools([], []):
            pass

        buffer = backend._get_streaming_buffer()
        assert "Hello World" in buffer

    @pytest.mark.asyncio
    async def test_buffer_accumulates_tool_results(self, mock_backend_class):
        """Test buffer accumulates tool results."""
        backend = mock_backend_class()

        async for chunk in backend.stream_with_tools([], []):
            pass

        buffer = backend._get_streaming_buffer()
        assert "[Tool: test_tool]" in buffer
        assert "tool output" in buffer

    @pytest.mark.asyncio
    async def test_buffer_preserved_on_compression_retry(self, mock_backend_class):
        """Test buffer preserved when _compression_retry=True."""
        backend = mock_backend_class()

        # First stream
        async for chunk in backend.stream_with_tools([], []):
            pass

        first_buffer = backend._get_streaming_buffer()
        assert first_buffer is not None

        # Second stream with compression retry - buffer should be preserved
        async for chunk in backend.stream_with_tools([], [], _compression_retry=True):
            pass

        # Buffer should still contain first stream's content plus new content
        final_buffer = backend._get_streaming_buffer()
        assert len(final_buffer) > len(first_buffer)


# =============================================================================
# Integration Tests with Real Backend Classes (No API Calls)
# =============================================================================


class TestRealBackendBufferInitialization:
    """Test buffer initialization in real backend classes."""

    def test_response_backend_buffer_init(self):
        """Test ResponseBackend initializes buffer correctly."""
        from massgen.backend.response import ResponseBackend

        # Mock the API key requirement
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            backend = ResponseBackend(api_key="test-key")
            assert backend._streaming_buffer == ""
            assert backend._get_streaming_buffer() is None

    def test_chat_completions_backend_buffer_init(self):
        """Test ChatCompletionsBackend initializes buffer correctly."""
        from massgen.backend.chat_completions import ChatCompletionsBackend

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            backend = ChatCompletionsBackend(api_key="test-key")
            assert backend._streaming_buffer == ""
            assert backend._get_streaming_buffer() is None

    def test_claude_backend_buffer_init(self):
        """Test ClaudeBackend initializes buffer correctly."""
        from massgen.backend.claude import ClaudeBackend

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            backend = ClaudeBackend(api_key="test-key")
            assert backend._streaming_buffer == ""
            assert backend._get_streaming_buffer() is None

    def test_gemini_backend_buffer_init(self):
        """Test GeminiBackend initializes buffer correctly."""
        from massgen.backend.gemini import GeminiBackend

        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
            backend = GeminiBackend(api_key="test-key")
            assert backend._streaming_buffer == ""
            assert backend._get_streaming_buffer() is None


class TestBufferMethodsWorkCorrectly:
    """Test buffer methods work correctly on real backend instances."""

    @pytest.fixture
    def backend_instances(self):
        """Create instances of all backends for testing."""
        from massgen.backend.chat_completions import ChatCompletionsBackend
        from massgen.backend.claude import ClaudeBackend
        from massgen.backend.gemini import GeminiBackend
        from massgen.backend.response import ResponseBackend

        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "ANTHROPIC_API_KEY": "test-key",
                "GOOGLE_API_KEY": "test-key",
            },
        ):
            return [
                ("ResponseBackend", ResponseBackend(api_key="test-key")),
                ("ChatCompletionsBackend", ChatCompletionsBackend(api_key="test-key")),
                ("ClaudeBackend", ClaudeBackend(api_key="test-key")),
                ("GeminiBackend", GeminiBackend(api_key="test-key")),
            ]

    def test_append_content_works(self, backend_instances):
        """Test _append_to_streaming_buffer works on all backends."""
        for name, backend in backend_instances:
            backend._append_to_streaming_buffer("test content")
            assert "test content" in backend._streaming_buffer, f"{name} failed to append content"

    def test_append_tool_works(self, backend_instances):
        """Test _append_tool_to_buffer works on all backends."""
        for name, backend in backend_instances:
            backend._append_tool_to_buffer("my_tool", "tool result")
            assert "[Tool: my_tool]" in backend._streaming_buffer, f"{name} failed to append tool"

    def test_clear_buffer_works(self, backend_instances):
        """Test _clear_streaming_buffer works on all backends."""
        for name, backend in backend_instances:
            backend._streaming_buffer = "content to clear"
            backend._clear_streaming_buffer()
            assert backend._streaming_buffer == "", f"{name} failed to clear buffer"

    def test_get_buffer_works(self, backend_instances):
        """Test _get_streaming_buffer works on all backends."""
        for name, backend in backend_instances:
            backend._streaming_buffer = "buffer content"
            result = backend._get_streaming_buffer()
            assert result == "buffer content", f"{name} failed to get buffer"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestBufferEdgeCases:
    """Test edge cases and error handling."""

    def test_buffer_handles_unicode(self):
        """Test buffer handles unicode content correctly."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_to_streaming_buffer("Hello ")
        obj._append_to_streaming_buffer("")
        obj._append_to_streaming_buffer(" World")

        assert obj._streaming_buffer == "Hello  World"

    def test_buffer_handles_special_characters(self):
        """Test buffer handles special characters."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        special_content = "Content with\nnewlines\tand\ttabs and 'quotes' and \"double quotes\""
        obj._append_to_streaming_buffer(special_content)
        assert obj._streaming_buffer == special_content

    def test_buffer_handles_large_content(self):
        """Test buffer handles large content."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        large_content = "x" * 100000  # 100KB of content
        obj._append_to_streaming_buffer(large_content)
        assert len(obj._streaming_buffer) == 100000

    def test_tool_buffer_with_empty_tool_name(self):
        """Test tool buffer handles empty tool name."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_to_buffer("", "result")
        assert "[Tool: ]" in obj._streaming_buffer

    def test_tool_buffer_with_empty_result(self):
        """Test tool buffer handles empty result."""

        class TestClass(StreamingBufferMixin):
            def __init__(self):
                super().__init__()

        obj = TestClass()
        obj._append_tool_to_buffer("my_tool", "")
        assert "[Tool: my_tool]" in obj._streaming_buffer


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
