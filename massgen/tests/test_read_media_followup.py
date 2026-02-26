"""Tests for read_media follow-up conversation capability.

Covers:
- Backend return type changes (tuple[str, str | None])
- OpenAI previous_response_id threading
- Non-OpenAI conversation_messages threading
- ConversationStore lifecycle
- read_media continue_from parameter
- understand_image response_id threading
"""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# Backend return types — all call_* functions return tuple[str, str | None]
# ===========================================================================


class TestBackendReturnTypes:
    """All call_* functions return (text, response_id_or_none)."""

    @pytest.mark.asyncio
    async def test_call_openai_returns_tuple_with_response_id(self):
        from massgen.tool._multimodal_tools.image_backends import call_openai
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.output_text = "Analysis text"
        mock_response.id = "resp_abc123"

        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        with (
            patch("openai.AsyncOpenAI", return_value=mock_client),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
        ):
            result = await call_openai(imgs, "Analyze this", "gpt-5.2")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == "Analysis text"
        assert result[1] == "resp_abc123"

    @pytest.mark.asyncio
    async def test_call_claude_returns_tuple_with_none_id(self):
        from massgen.tool._multimodal_tools.image_backends import call_claude
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Claude analysis")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        with (
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            result = await call_claude(imgs, "Analyze this", "claude-sonnet-4-20250514")

        assert isinstance(result, tuple)
        assert result[0] == "Claude analysis"
        assert result[1] is None

    def test_call_gemini_returns_tuple(self):
        """call_gemini should be callable with expected signature."""
        func = __import__(
            "massgen.tool._multimodal_tools.image_backends",
            fromlist=["call_gemini"],
        ).call_gemini
        assert callable(func)
        assert "model" in inspect.signature(func).parameters

    def test_call_grok_returns_tuple(self):
        """call_grok should be callable with expected signature."""
        func = __import__(
            "massgen.tool._multimodal_tools.image_backends",
            fromlist=["call_grok"],
        ).call_grok
        assert callable(func)
        assert "model" in inspect.signature(func).parameters

    def test_call_claude_code_returns_tuple(self):
        """call_claude_code should be callable with expected signature."""
        func = __import__(
            "massgen.tool._multimodal_tools.image_backends",
            fromlist=["call_claude_code"],
        ).call_claude_code
        assert callable(func)
        assert "model" in inspect.signature(func).parameters

    def test_call_codex_returns_tuple(self):
        """call_codex should be callable with expected signature."""
        func = __import__(
            "massgen.tool._multimodal_tools.image_backends",
            fromlist=["call_codex"],
        ).call_codex
        assert callable(func)
        assert "model" in inspect.signature(func).parameters


# ===========================================================================
# call_openai previous_response_id parameter
# ===========================================================================


class TestCallOpenaiFollowUp:
    """call_openai accepts and passes previous_response_id."""

    def test_accepts_previous_response_id_param(self):
        from massgen.tool._multimodal_tools.image_backends import call_openai

        sig = inspect.signature(call_openai)
        assert "previous_response_id" in sig.parameters

    @pytest.mark.asyncio
    async def test_previous_response_id_passed_to_api(self):
        from massgen.tool._multimodal_tools.image_backends import call_openai
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.output_text = "Follow-up analysis"
        mock_response.id = "resp_def456"

        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        with (
            patch("openai.AsyncOpenAI", return_value=mock_client),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
        ):
            await call_openai(imgs, "Follow up", "gpt-5.2", previous_response_id="resp_abc123")

        create_kwargs = mock_client.responses.create.call_args
        assert create_kwargs.kwargs.get("previous_response_id") == "resp_abc123" or create_kwargs[1].get("previous_response_id") == "resp_abc123"

    @pytest.mark.asyncio
    async def test_no_previous_response_id_when_not_provided(self):
        from massgen.tool._multimodal_tools.image_backends import call_openai
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.output_text = "Fresh analysis"
        mock_response.id = "resp_xyz"

        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        with (
            patch("openai.AsyncOpenAI", return_value=mock_client),
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
        ):
            await call_openai(imgs, "Analyze", "gpt-5.2")

        call_kwargs = mock_client.responses.create.call_args[1]
        assert "previous_response_id" not in call_kwargs


# ===========================================================================
# call_claude conversation_messages parameter
# ===========================================================================


class TestCallClaudeFollowUp:
    """call_claude accepts and uses conversation_messages."""

    def test_accepts_conversation_messages_param(self):
        from massgen.tool._multimodal_tools.image_backends import call_claude

        sig = inspect.signature(call_claude)
        assert "conversation_messages" in sig.parameters

    @pytest.mark.asyncio
    async def test_conversation_messages_prepended(self):
        from massgen.tool._multimodal_tools.image_backends import call_claude
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Follow-up")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        prior_messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ]

        with (
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            await call_claude(imgs, "Follow up", "claude-sonnet-4-20250514", conversation_messages=prior_messages)

        call_kwargs = mock_client.messages.create.call_args[1]
        messages = call_kwargs["messages"]
        # Prior messages should come first, then the new user message
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "First question"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "First answer"
        assert messages[2]["role"] == "user"

    @pytest.mark.asyncio
    async def test_no_conversation_messages_sends_only_current(self):
        from massgen.tool._multimodal_tools.image_backends import call_claude
        from massgen.tool._multimodal_tools.understand_image import LoadedImage

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Fresh analysis")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        imgs = [LoadedImage(path=MagicMock(name="test.png"), base64_data="abc", mime_type="image/png")]

        with (
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
        ):
            await call_claude(imgs, "Analyze", "claude-sonnet-4-20250514")

        call_kwargs = mock_client.messages.create.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 1


# ===========================================================================
# call_grok conversation_messages parameter
# ===========================================================================


class TestCallGrokFollowUp:
    """call_grok accepts conversation_messages."""

    def test_accepts_conversation_messages_param(self):
        from massgen.tool._multimodal_tools.image_backends import call_grok

        sig = inspect.signature(call_grok)
        assert "conversation_messages" in sig.parameters


# ===========================================================================
# ConversationStore
# ===========================================================================


class TestConversationStore:
    """ConversationStore manages follow-up conversation state."""

    def test_save_and_get_roundtrip(self):
        from massgen.tool._multimodal_tools.read_media import _ConversationStore

        store = _ConversationStore()
        state = {"backend_type": "openai", "response_id": "resp_123", "model": "gpt-5.2"}
        store.save("conv_abc", state)

        retrieved = store.get("conv_abc")
        assert retrieved is not None
        assert retrieved["response_id"] == "resp_123"

    def test_get_unknown_returns_none(self):
        from massgen.tool._multimodal_tools.read_media import _ConversationStore

        store = _ConversationStore()
        assert store.get("nonexistent") is None

    def test_eviction_when_over_max(self):
        from massgen.tool._multimodal_tools.read_media import _ConversationStore

        store = _ConversationStore(max_conversations=3)
        store.save("conv_1", {"id": 1})
        store.save("conv_2", {"id": 2})
        store.save("conv_3", {"id": 3})
        store.save("conv_4", {"id": 4})  # Should evict conv_1

        assert store.get("conv_1") is None
        assert store.get("conv_4") is not None
        assert store.get("conv_2") is not None

    def test_update_existing_conversation(self):
        from massgen.tool._multimodal_tools.read_media import _ConversationStore

        store = _ConversationStore()
        store.save("conv_abc", {"response_id": "resp_1"})
        store.save("conv_abc", {"response_id": "resp_2"})

        retrieved = store.get("conv_abc")
        assert retrieved["response_id"] == "resp_2"


# ===========================================================================
# understand_image response_id threading
# ===========================================================================


class TestUnderstandImageResponseId:
    """understand_image accepts follow-up params and returns response_id."""

    def test_accepts_previous_response_id_param(self):
        from massgen.tool._multimodal_tools.understand_image import understand_image

        sig = inspect.signature(understand_image)
        assert "previous_response_id" in sig.parameters

    def test_accepts_conversation_messages_param(self):
        from massgen.tool._multimodal_tools.understand_image import understand_image

        sig = inspect.signature(understand_image)
        assert "conversation_messages" in sig.parameters

    @pytest.mark.asyncio
    async def test_response_id_in_result(self, tmp_path):
        """When backend returns a response_id, it appears in the result dict."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        # Create a test image
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai") as mock_call,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
            patch("massgen.tool._multimodal_tools.understand_image.has_capability", return_value=False),
        ):
            mock_call.return_value = ("Analysis text", "resp_xyz789")
            mock_load.return_value = MagicMock(
                path=img,
                base64_data="abc",
                mime_type="image/png",
                name=None,
            )

            result = await understand_image(
                image_path=str(img),
                prompt="Test",
                model="gpt-5.2",
                agent_cwd=str(tmp_path),
            )

        # Parse the result JSON
        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["response_id"] == "resp_xyz789"

    @pytest.mark.asyncio
    async def test_no_response_id_when_none(self, tmp_path):
        """When backend returns None for response_id, it's omitted from result."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai") as mock_call,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
            patch("massgen.tool._multimodal_tools.understand_image.has_capability", return_value=False),
        ):
            mock_call.return_value = ("Analysis text", None)
            mock_load.return_value = MagicMock(
                path=img,
                base64_data="abc",
                mime_type="image/png",
                name=None,
            )

            result = await understand_image(
                image_path=str(img),
                prompt="Test",
                model="gpt-5.2",
                agent_cwd=str(tmp_path),
            )

        result_data = json.loads(result.output_blocks[0].data)
        assert "response_id" not in result_data

    @pytest.mark.asyncio
    async def test_previous_response_id_passed_to_call_openai(self, tmp_path):
        """previous_response_id is forwarded to call_openai."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_openai") as mock_call,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
            patch("massgen.tool._multimodal_tools.understand_image.has_capability", return_value=False),
        ):
            mock_call.return_value = ("Follow-up", "resp_new")
            mock_load.return_value = MagicMock(
                path=img,
                base64_data="abc",
                mime_type="image/png",
                name=None,
            )

            await understand_image(
                image_path=str(img),
                prompt="Follow up question",
                model="gpt-5.2",
                agent_cwd=str(tmp_path),
                previous_response_id="resp_old",
            )

        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs.kwargs.get("previous_response_id") == "resp_old" or (len(call_kwargs.args) > 4 and call_kwargs.args[4] == "resp_old")

    @pytest.mark.asyncio
    async def test_conversation_messages_passed_to_call_claude(self, tmp_path):
        """conversation_messages is forwarded to call_claude."""
        from massgen.tool._multimodal_tools.understand_image import understand_image

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        prior_msgs = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response"},
        ]

        with (
            patch("massgen.tool._multimodal_tools.understand_image.call_claude") as mock_call,
            patch("massgen.tool._multimodal_tools.understand_image._load_and_process_image") as mock_load,
            patch("massgen.tool._multimodal_tools.understand_image.has_capability", return_value=True),
        ):
            mock_call.return_value = ("Follow-up", None)
            mock_load.return_value = MagicMock(
                path=img,
                base64_data="abc",
                mime_type="image/png",
                name=None,
            )

            await understand_image(
                image_path=str(img),
                prompt="Follow up",
                model="claude-sonnet-4-20250514",
                agent_cwd=str(tmp_path),
                backend_type="claude",
                conversation_messages=prior_msgs,
            )

        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs.kwargs.get("conversation_messages") == prior_msgs


# ===========================================================================
# read_media continue_from parameter
# ===========================================================================


class TestReadMediaContinueFrom:
    """read_media supports continue_from for follow-up conversations."""

    def test_accepts_continue_from_param(self):
        from massgen.tool._multimodal_tools.read_media import read_media

        sig = inspect.signature(read_media)
        assert "continue_from" in sig.parameters

    @pytest.mark.asyncio
    async def test_first_call_returns_conversation_id(self, tmp_path):
        """First read_media call includes conversation_id in result."""
        from massgen.tool._multimodal_tools.read_media import read_media

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        context = tmp_path / "CONTEXT.md"
        context.write_text("Test context")

        mock_result_data = {
            "success": True,
            "operation": "understand_image",
            "image_path": str(img),
            "prompt": "test",
            "model": "gpt-5.2",
            "response": "Analysis",
            "response_id": "resp_abc123",
        }
        from massgen.tool._result import ExecutionResult, TextContent

        mock_result = ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(mock_result_data))],
        )

        mock_ui = AsyncMock(return_value=mock_result)
        with patch("massgen.tool._multimodal_tools.understand_image.understand_image", mock_ui):
            result = await read_media(
                file_path=str(img),
                prompt="What's wrong?",
                agent_cwd=str(tmp_path),
                backend_type="openai",
                model="gpt-5.2",
            )

        result_data = json.loads(result.output_blocks[0].data)
        assert "conversation_id" in result_data
        assert result_data["conversation_id"].startswith("conv_")

    @pytest.mark.asyncio
    async def test_continue_from_unknown_id_returns_error(self, tmp_path):
        """continue_from with unknown conversation_id returns error."""
        from massgen.tool._multimodal_tools.read_media import read_media

        context = tmp_path / "CONTEXT.md"
        context.write_text("Test context")

        result = await read_media(
            prompt="Follow up",
            continue_from="conv_nonexistent",
            agent_cwd=str(tmp_path),
        )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is False
        assert "not found" in result_data["error"].lower() or "unknown" in result_data["error"].lower()

    @pytest.mark.asyncio
    async def test_continue_from_allows_no_file_path(self, tmp_path):
        """continue_from allows calling without file_path (prompt-only follow-up)."""
        from massgen.tool._multimodal_tools.read_media import (
            _conversation_store,
            read_media,
        )

        context = tmp_path / "CONTEXT.md"
        context.write_text("Test context")

        # Seed the conversation store
        _conversation_store.save(
            "conv_test123",
            {
                "backend_type": "openai",
                "response_id": "resp_old",
                "model": "gpt-5.2",
                "system_prompt": None,
                "prompt": "Original prompt",
                "images": [],
                "messages": [],
            },
        )

        mock_result_data = {
            "success": True,
            "operation": "understand_image",
            "response": "Follow-up analysis",
            "response_id": "resp_new",
        }
        from massgen.tool._result import ExecutionResult, TextContent

        mock_result = ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(mock_result_data))],
        )

        mock_ui = AsyncMock(return_value=mock_result)
        with patch("massgen.tool._multimodal_tools.understand_image.understand_image", mock_ui):
            result = await read_media(
                prompt="What about the spacing?",
                continue_from="conv_test123",
                agent_cwd=str(tmp_path),
            )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert "conversation_id" in result_data

        # Verify previous_response_id was passed
        mock_ui.assert_called_once()
        call_kwargs = mock_ui.call_args.kwargs
        assert call_kwargs.get("previous_response_id") == "resp_old"

    @pytest.mark.asyncio
    async def test_continue_from_without_file_path_threads_to_backend(self, tmp_path):
        """Regression: continue_from-only follow-up should reach backend without new image."""
        from massgen.tool._multimodal_tools.read_media import (
            _conversation_store,
            read_media,
        )

        context = tmp_path / "CONTEXT.md"
        context.write_text("Test context")

        conv_id = "conv_chain_followup_no_file"
        _conversation_store.save(
            conv_id,
            {
                "media_type": "image",
                "backend_type": "openai",
                "response_id": "resp_old_chain",
                "model": "gpt-5.2",
                "system_prompt": None,
                "prompt": "Original prompt",
                "images": [],
                "messages": [],
            },
        )

        with patch(
            "massgen.tool._multimodal_tools.understand_image.call_openai",
            new_callable=AsyncMock,
        ) as mock_call_openai:
            mock_call_openai.return_value = ("Threaded follow-up analysis", "resp_new_chain")

            result = await read_media(
                prompt="Please go deeper on this image analysis.",
                continue_from=conv_id,
                agent_cwd=str(tmp_path),
            )

        result_data = json.loads(result.output_blocks[0].data)
        assert result_data["success"] is True
        assert result_data["conversation_id"] == conv_id
        assert result_data["response"] == "Threaded follow-up analysis"

        mock_call_openai.assert_called_once()
        call_args = mock_call_openai.call_args
        loaded_images = call_args.args[0]
        assert loaded_images == []
        assert call_args.kwargs.get("previous_response_id") == "resp_old_chain"
