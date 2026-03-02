"""Tests for image generation backend selection, Gemini dispatch, and editing support."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.tool._multimodal_tools.generation import _image as image_generation
from massgen.tool._multimodal_tools.generation._base import (
    BACKEND_PRIORITY,
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_default_model,
)
from massgen.tool._multimodal_tools.generation._selector import select_backend_and_model

# ---------------------------------------------------------------------------
# Backend auto-selection priority tests
# ---------------------------------------------------------------------------


def test_image_auto_selection_prefers_google(monkeypatch: pytest.MonkeyPatch):
    """Image auto-selection should prefer Google when both Google + OpenAI keys present."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.IMAGE,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "google"
    assert model == "gemini-3.1-flash-image-preview"


def test_image_auto_selection_openai_only(monkeypatch: pytest.MonkeyPatch):
    """Image auto-selection should pick OpenAI when only OpenAI key is present."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.IMAGE,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "openai"
    assert model == "gpt-5.2"


def test_image_auto_selection_openrouter_only(monkeypatch: pytest.MonkeyPatch):
    """Image auto-selection should pick OpenRouter when only OpenRouter key is present."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    backend, model = select_backend_and_model(
        media_type=MediaType.IMAGE,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "openrouter"
    assert model == "google/gemini-3.1-flash-image-preview"


def test_image_auto_selection_none_without_keys(monkeypatch: pytest.MonkeyPatch):
    """Image auto-selection should return None when no API keys are available."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.IMAGE,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend is None
    assert model is None


# ---------------------------------------------------------------------------
# Default model tests
# ---------------------------------------------------------------------------


def test_google_default_model_is_nano_banana_2():
    """Google default image model should be Nano Banana 2."""
    assert get_default_model("google", MediaType.IMAGE) == "gemini-3.1-flash-image-preview"


def test_openrouter_default_model_is_nano_banana_2():
    """OpenRouter default image model should be Nano Banana 2 (via OpenRouter)."""
    assert get_default_model("openrouter", MediaType.IMAGE) == "google/gemini-3.1-flash-image-preview"


def test_openai_default_model_is_gpt_5_2():
    """OpenAI default image model should be GPT-5.2."""
    assert get_default_model("openai", MediaType.IMAGE) == "gpt-5.2"


def test_image_backend_priority_google_first():
    """IMAGE backend priority should list Google first."""
    assert BACKEND_PRIORITY[MediaType.IMAGE] == ["google", "openai", "grok", "openrouter"]


# ---------------------------------------------------------------------------
# Gemini vs Imagen dispatch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_gemini_model_uses_generate_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A gemini-* model should route to _generate_image_google_gemini()."""
    config = GenerationConfig(
        prompt="a cat in space",
        output_path=tmp_path / "cat.png",
        media_type=MediaType.IMAGE,
        backend="google",
        model="gemini-3.1-flash-image-preview",
    )

    gemini_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.IMAGE,
        backend_name="google",
        model_used="gemini-3.1-flash-image-preview",
        file_size_bytes=1234,
    )
    mock_gemini = AsyncMock(return_value=gemini_result)
    monkeypatch.setattr(image_generation, "_generate_image_google_gemini", mock_gemini)

    result = await image_generation._generate_image_google(config)

    assert result.success is True
    assert result.model_used == "gemini-3.1-flash-image-preview"
    mock_gemini.assert_awaited_once_with(config, "gemini-3.1-flash-image-preview")


@pytest.mark.asyncio
async def test_google_imagen_model_uses_generate_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """An imagen-* model should route to _generate_image_google_imagen()."""
    config = GenerationConfig(
        prompt="a cat in space",
        output_path=tmp_path / "cat.png",
        media_type=MediaType.IMAGE,
        backend="google",
        model="imagen-4.0-fast-generate-001",
    )

    imagen_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.IMAGE,
        backend_name="google",
        model_used="imagen-4.0-fast-generate-001",
        file_size_bytes=5678,
    )
    mock_imagen = AsyncMock(return_value=imagen_result)
    monkeypatch.setattr(image_generation, "_generate_image_google_imagen", mock_imagen)

    result = await image_generation._generate_image_google(config)

    assert result.success is True
    assert result.model_used == "imagen-4.0-fast-generate-001"
    mock_imagen.assert_awaited_once_with(config, "imagen-4.0-fast-generate-001")


@pytest.mark.asyncio
async def test_google_gemini_pro_model_uses_generate_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """gemini-3-pro-image-preview should route to _generate_image_google_gemini() (same path as flash)."""
    config = GenerationConfig(
        prompt="a detailed landscape",
        output_path=tmp_path / "landscape.png",
        media_type=MediaType.IMAGE,
        backend="google",
        model="gemini-3-pro-image-preview",
    )

    gemini_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.IMAGE,
        backend_name="google",
        model_used="gemini-3-pro-image-preview",
        file_size_bytes=9000,
    )
    mock_gemini = AsyncMock(return_value=gemini_result)
    monkeypatch.setattr(image_generation, "_generate_image_google_gemini", mock_gemini)

    result = await image_generation._generate_image_google(config)

    assert result.success is True
    mock_gemini.assert_awaited_once_with(config, "gemini-3-pro-image-preview")


@pytest.mark.asyncio
async def test_google_default_model_routes_to_gemini(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When no model is specified, the default (gemini-3.1-flash-image-preview) should route to Gemini path."""
    config = GenerationConfig(
        prompt="a sunset",
        output_path=tmp_path / "sunset.png",
        media_type=MediaType.IMAGE,
        backend="google",
        model=None,  # Will use default
    )

    gemini_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.IMAGE,
        backend_name="google",
        model_used="gemini-3.1-flash-image-preview",
        file_size_bytes=2000,
    )
    mock_gemini = AsyncMock(return_value=gemini_result)
    monkeypatch.setattr(image_generation, "_generate_image_google_gemini", mock_gemini)

    result = await image_generation._generate_image_google(config)

    assert result.success is True
    mock_gemini.assert_awaited_once_with(config, "gemini-3.1-flash-image-preview")


# ---------------------------------------------------------------------------
# Gemini image editing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_image_editing_passes_input_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Config with input_images + Gemini model should include image parts in chat.send_message() call."""
    # Create a fake input image content block (already base64-encoded by _prepare_input_images)
    input_image_block = {
        "type": "input_image",
        "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    }

    output_path = tmp_path / "edited.png"
    config = GenerationConfig(
        prompt="Make it look like a watercolor painting",
        output_path=output_path,
        media_type=MediaType.IMAGE,
        backend="google",
        model="gemini-3.1-flash-image-preview",
        input_images=[input_image_block],
    )

    # Mock the image save to create the file so stat() works
    def _fake_save(path):
        Path(path).write_bytes(b"fake-image-bytes")

    mock_image = MagicMock()
    mock_image.save = MagicMock(side_effect=_fake_save)

    mock_part = MagicMock()
    mock_part.inline_data = True
    mock_part.as_image.return_value = mock_image

    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]

    mock_send_response = MagicMock()
    mock_send_response.candidates = [mock_candidate]

    mock_chat = MagicMock()
    mock_chat.send_message = MagicMock(return_value=mock_send_response)

    mock_client = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    # Patch the module-level genai reference
    mock_genai = MagicMock()
    mock_genai.Client.return_value = mock_client
    monkeypatch.setattr(image_generation, "genai", mock_genai)

    # Keep real genai_types.Part.from_bytes working — it just creates a Part object
    # but patch GenerateContentConfig and ImageConfig to avoid SDK validation
    mock_types = MagicMock()
    mock_types.Part.from_bytes = MagicMock(return_value=MagicMock(spec=[]))
    mock_types.GenerateContentConfig = MagicMock()
    mock_types.ImageConfig = MagicMock()
    monkeypatch.setattr(image_generation, "genai_types", mock_types)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

    assert result.success is True
    assert result.backend_name == "google"
    assert result.metadata.get("api_path") == "gemini_generate_content"

    # Verify chat.send_message was called with contents that include image data
    call_args = mock_chat.send_message.call_args
    contents = call_args[0][0]  # First positional arg = msg_contents
    # Contents should be a list (not just a string) because input_images are present
    assert isinstance(contents, list)
    assert len(contents) > 1  # At least one image part + the text prompt

    # Verify Part.from_bytes was called with the decoded image data
    mock_types.Part.from_bytes.assert_called_once()
    call_kw = mock_types.Part.from_bytes.call_args
    assert call_kw.kwargs["mime_type"] == "image/png"


# ---------------------------------------------------------------------------
# GenerationConfig field tests
# ---------------------------------------------------------------------------


class TestGenerationConfigFields:
    """Tests for GenerationConfig field additions."""

    def test_generation_config_has_continue_from_field(self):
        """continue_from field should exist and default to None."""
        config = GenerationConfig(
            prompt="test",
            output_path=Path("/tmp/test.png"),
            media_type=MediaType.IMAGE,
        )
        assert config.continue_from is None

    def test_generation_config_has_size_field(self):
        """size field should exist and default to None."""
        config = GenerationConfig(
            prompt="test",
            output_path=Path("/tmp/test.png"),
            media_type=MediaType.IMAGE,
        )
        assert config.size is None

    def test_generation_config_continue_from_set(self):
        """continue_from should accept a string value."""
        config = GenerationConfig(
            prompt="test",
            output_path=Path("/tmp/test.png"),
            media_type=MediaType.IMAGE,
            continue_from="resp_abc123",
        )
        assert config.continue_from == "resp_abc123"

    def test_generation_config_size_set(self):
        """size should accept a string value."""
        config = GenerationConfig(
            prompt="test",
            output_path=Path("/tmp/test.png"),
            media_type=MediaType.IMAGE,
            size="1024x1536",
        )
        assert config.size == "1024x1536"


# ---------------------------------------------------------------------------
# OpenAI continuation tests
# ---------------------------------------------------------------------------


class TestOpenAIContinuation:
    """Tests for OpenAI image generation continuation (previous_response_id)."""

    @pytest.mark.asyncio
    async def test_openai_passes_previous_response_id_when_continue_from_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """When continue_from is set, previous_response_id should be passed to responses.create()."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_new123"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)

        mock_client = AsyncMock()
        mock_client.responses = mock_responses

        mock_openai_cls = MagicMock(return_value=mock_client)
        monkeypatch.setattr(image_generation, "AsyncOpenAI", mock_openai_cls)

        config = GenerationConfig(
            prompt="Make the text larger",
            output_path=tmp_path / "continued.png",
            media_type=MediaType.IMAGE,
            backend="openai",
            continue_from="resp_abc",
        )

        result = await image_generation._generate_image_openai(config)

        assert result.success is True
        call_kwargs = mock_responses.create.call_args.kwargs
        assert call_kwargs["previous_response_id"] == "resp_abc"

    @pytest.mark.asyncio
    async def test_openai_returns_continuation_id_in_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Response ID should be stored as continuation_id in metadata."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_xyz789"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)

        mock_client = AsyncMock()
        mock_client.responses = mock_responses

        mock_openai_cls = MagicMock(return_value=mock_client)
        monkeypatch.setattr(image_generation, "AsyncOpenAI", mock_openai_cls)

        config = GenerationConfig(
            prompt="A logo",
            output_path=tmp_path / "logo.png",
            media_type=MediaType.IMAGE,
            backend="openai",
        )

        result = await image_generation._generate_image_openai(config)

        assert result.success is True
        assert result.metadata["continuation_id"] == "resp_xyz789"

    @pytest.mark.asyncio
    async def test_openai_first_call_also_returns_continuation_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Even without continue_from, response.id should be returned as continuation_id."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_first_call"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)

        mock_client = AsyncMock()
        mock_client.responses = mock_responses

        mock_openai_cls = MagicMock(return_value=mock_client)
        monkeypatch.setattr(image_generation, "AsyncOpenAI", mock_openai_cls)

        config = GenerationConfig(
            prompt="A cat",
            output_path=tmp_path / "cat.png",
            media_type=MediaType.IMAGE,
            backend="openai",
            continue_from=None,  # explicitly no continuation
        )

        result = await image_generation._generate_image_openai(config)

        assert result.success is True
        assert result.metadata["continuation_id"] == "resp_first_call"
        # Should NOT pass previous_response_id when continue_from is None
        call_kwargs = mock_responses.create.call_args.kwargs
        assert "previous_response_id" not in call_kwargs


# ---------------------------------------------------------------------------
# OpenAI quality + size wiring tests
# ---------------------------------------------------------------------------


class TestOpenAIQualityAndSize:
    """Tests for quality and size parameter wiring to OpenAI."""

    @pytest.mark.asyncio
    async def test_openai_quality_passed_to_image_tool_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """quality='hd' should appear in the image_generation tool config."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_q"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)
        mock_client = AsyncMock()
        mock_client.responses = mock_responses
        monkeypatch.setattr(image_generation, "AsyncOpenAI", MagicMock(return_value=mock_client))

        config = GenerationConfig(
            prompt="A logo",
            output_path=tmp_path / "logo.png",
            media_type=MediaType.IMAGE,
            backend="openai",
            quality="hd",
        )

        await image_generation._generate_image_openai(config)

        call_kwargs = mock_responses.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "image_generation"
        assert tools[0]["quality"] == "hd"

    @pytest.mark.asyncio
    async def test_openai_quality_omitted_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """No quality key in tool config when quality is None."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_nq"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)
        mock_client = AsyncMock()
        mock_client.responses = mock_responses
        monkeypatch.setattr(image_generation, "AsyncOpenAI", MagicMock(return_value=mock_client))

        config = GenerationConfig(
            prompt="A logo",
            output_path=tmp_path / "logo.png",
            media_type=MediaType.IMAGE,
            backend="openai",
            quality=None,
        )

        await image_generation._generate_image_openai(config)

        call_kwargs = mock_responses.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert "quality" not in tools[0]

    @pytest.mark.asyncio
    async def test_openai_size_passed_to_image_tool_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """size='1024x1536' should appear in the image_generation tool config."""
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_response = MagicMock()
        mock_response.id = "resp_s"
        mock_output = MagicMock()
        mock_output.type = "image_generation_call"
        mock_output.result = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        mock_response.output = [mock_output]

        mock_responses = AsyncMock()
        mock_responses.create = AsyncMock(return_value=mock_response)
        mock_client = AsyncMock()
        mock_client.responses = mock_responses
        monkeypatch.setattr(image_generation, "AsyncOpenAI", MagicMock(return_value=mock_client))

        config = GenerationConfig(
            prompt="A logo",
            output_path=tmp_path / "logo.png",
            media_type=MediaType.IMAGE,
            backend="openai",
            size="1024x1536",
        )

        await image_generation._generate_image_openai(config)

        call_kwargs = mock_responses.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert tools[0]["size"] == "1024x1536"


# ---------------------------------------------------------------------------
# Gemini continuation tests
# ---------------------------------------------------------------------------


class TestGeminiContinuation:
    """Tests for Gemini image generation continuation via chat."""

    @pytest.mark.asyncio
    async def test_gemini_continue_uses_chat_send_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """When continue_from is set, should use chat.send_message() instead of generate_content()."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        # Set up a mock chat in the store
        from massgen.tool._multimodal_tools.generation._image import _gemini_chat_store

        mock_chat = MagicMock()

        # Mock the send_message response
        def _fake_save(path):
            Path(path).write_bytes(b"fake-image-bytes")

        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=_fake_save)

        mock_part = MagicMock()
        mock_part.inline_data = True
        mock_part.as_image.return_value = mock_image

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_send_response = MagicMock()
        mock_send_response.candidates = [mock_candidate]
        mock_chat.send_message = MagicMock(return_value=mock_send_response)

        # Store the chat with a known ID (save requires client + chat)
        mock_client = MagicMock()
        chat_id = _gemini_chat_store.save(mock_client, mock_chat)

        # Patch genai and genai_types
        mock_genai = MagicMock()
        monkeypatch.setattr(image_generation, "genai", mock_genai)

        mock_types = MagicMock()
        mock_types.ImageConfig = MagicMock()
        mock_types.GenerateContentConfig = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="Make the text bigger",
            output_path=tmp_path / "edited.png",
            media_type=MediaType.IMAGE,
            backend="google",
            continue_from=chat_id,
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is True
        mock_chat.send_message.assert_called_once()
        # generate_content should NOT have been called
        mock_genai.Client.return_value.models.generate_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_gemini_first_call_stores_chat_and_returns_continuation_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """First call should create a chat and return a continuation_id."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        def _fake_save(path):
            Path(path).write_bytes(b"fake-image-bytes")

        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=_fake_save)

        mock_part = MagicMock()
        mock_part.inline_data = True
        mock_part.as_image.return_value = mock_image

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_send_response = MagicMock()
        mock_send_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_send_response)

        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        monkeypatch.setattr(image_generation, "genai", mock_genai)

        mock_types = MagicMock()
        mock_types.ImageConfig = MagicMock()
        mock_types.GenerateContentConfig = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="A logo for a coffee shop",
            output_path=tmp_path / "logo.png",
            media_type=MediaType.IMAGE,
            backend="google",
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is True
        assert "continuation_id" in result.metadata
        assert result.metadata["continuation_id"].startswith("gemini_chat_")
        mock_client.chats.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_gemini_continuation_not_found_returns_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """continue_from with invalid chat ID should return an error."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        mock_genai = MagicMock()
        monkeypatch.setattr(image_generation, "genai", mock_genai)
        mock_types = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="Edit this",
            output_path=tmp_path / "edit.png",
            media_type=MediaType.IMAGE,
            backend="google",
            continue_from="gemini_chat_nonexistent",
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is False
        assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# Gemini aspect_ratio + size wiring tests
# ---------------------------------------------------------------------------


class TestGeminiAspectRatioAndSize:
    """Tests for aspect_ratio and size wiring to Gemini generate_content path."""

    @pytest.mark.asyncio
    async def test_gemini_aspect_ratio_in_generate_content_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """aspect_ratio should be passed via ImageConfig to generate_content()."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        def _fake_save(path):
            Path(path).write_bytes(b"fake-image-bytes")

        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=_fake_save)

        mock_part = MagicMock()
        mock_part.inline_data = True
        mock_part.as_image.return_value = mock_image

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_send_response = MagicMock()
        mock_send_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_send_response)

        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        monkeypatch.setattr(image_generation, "genai", mock_genai)

        # Track what ImageConfig is called with
        image_config_calls = []
        original_image_config = MagicMock()

        def track_image_config(**kwargs):
            image_config_calls.append(kwargs)
            return original_image_config

        mock_types = MagicMock()
        mock_types.ImageConfig = track_image_config
        mock_types.GenerateContentConfig = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="A landscape",
            output_path=tmp_path / "landscape.png",
            media_type=MediaType.IMAGE,
            backend="google",
            aspect_ratio="16:9",
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is True
        assert len(image_config_calls) == 1
        assert image_config_calls[0]["aspect_ratio"] == "16:9"

    @pytest.mark.asyncio
    async def test_gemini_aspect_ratio_omitted_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """No ImageConfig when aspect_ratio and size are None."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        def _fake_save(path):
            Path(path).write_bytes(b"fake-image-bytes")

        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=_fake_save)

        mock_part = MagicMock()
        mock_part.inline_data = True
        mock_part.as_image.return_value = mock_image

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_send_response = MagicMock()
        mock_send_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_send_response)

        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        monkeypatch.setattr(image_generation, "genai", mock_genai)

        image_config_calls = []

        def track_image_config(**kwargs):
            image_config_calls.append(kwargs)
            return MagicMock()

        mock_types = MagicMock()
        mock_types.ImageConfig = track_image_config
        mock_types.GenerateContentConfig = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="A sunset",
            output_path=tmp_path / "sunset.png",
            media_type=MediaType.IMAGE,
            backend="google",
            aspect_ratio=None,
            size=None,
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is True
        # ImageConfig should NOT be called when no image params set
        assert len(image_config_calls) == 0

    @pytest.mark.asyncio
    async def test_gemini_size_mapped_to_image_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """size='2K' should map to ImageConfig(image_size='2K')."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        def _fake_save(path):
            Path(path).write_bytes(b"fake-image-bytes")

        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=_fake_save)

        mock_part = MagicMock()
        mock_part.inline_data = True
        mock_part.as_image.return_value = mock_image

        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_send_response = MagicMock()
        mock_send_response.candidates = [mock_candidate]

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_send_response)

        mock_client = MagicMock()
        mock_client.chats.create.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        monkeypatch.setattr(image_generation, "genai", mock_genai)

        image_config_calls = []

        def track_image_config(**kwargs):
            image_config_calls.append(kwargs)
            return MagicMock()

        mock_types = MagicMock()
        mock_types.ImageConfig = track_image_config
        mock_types.GenerateContentConfig = MagicMock()
        monkeypatch.setattr(image_generation, "genai_types", mock_types)

        config = GenerationConfig(
            prompt="A portrait",
            output_path=tmp_path / "portrait.png",
            media_type=MediaType.IMAGE,
            backend="google",
            size="2K",
        )

        result = await image_generation._generate_image_google_gemini(config, "gemini-3.1-flash-image-preview")

        assert result.success is True
        assert len(image_config_calls) == 1
        assert image_config_calls[0]["image_size"] == "2K"


# ---------------------------------------------------------------------------
# generate_media() entry point tests
# ---------------------------------------------------------------------------


class TestGenerateMediaEntryPoint:
    """Tests for generate_media() signature and continuation wiring."""

    def test_generate_media_accepts_continue_from_param(self):
        """generate_media should accept continue_from parameter."""
        import inspect

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        sig = inspect.signature(generate_media)
        assert "continue_from" in sig.parameters

    def test_generate_media_accepts_size_param(self):
        """generate_media should accept size parameter."""
        import inspect

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        sig = inspect.signature(generate_media)
        assert "size" in sig.parameters

    @pytest.mark.asyncio
    async def test_continue_from_only_valid_for_single_image(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Batch + continue_from should return an error."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        result = await generate_media(
            prompts=["A cat", "A dog"],
            mode="image",
            continue_from="resp_abc",
            agent_cwd=str(tmp_path),
            task_context="Test context",
        )

        # Should be an error
        import json

        data = json.loads(result.output_blocks[0].data)
        assert data["success"] is False
        assert "continue_from" in data["error"].lower()
