"""Tests for audio generation backend selection with ElevenLabs support."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from massgen.tool._multimodal_tools.generation import _audio as audio_generation
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
)
from massgen.tool._multimodal_tools.generation._selector import select_backend_and_model


def test_audio_auto_selection_prefers_elevenlabs(monkeypatch: pytest.MonkeyPatch):
    """Audio auto-selection should prefer ElevenLabs when both keys are present."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    backend, model = select_backend_and_model(
        media_type=MediaType.AUDIO,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "elevenlabs"
    assert model == "eleven_multilingual_v2"


def test_audio_auto_selection_falls_back_to_openai(monkeypatch: pytest.MonkeyPatch):
    """Audio auto-selection should fall back to OpenAI when no ElevenLabs key."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.AUDIO,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "openai"
    assert model == "gpt-4o-mini-tts"


def test_audio_auto_selection_returns_none_without_any_keys(monkeypatch: pytest.MonkeyPatch):
    """Audio auto-selection should fail when no API keys are available."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.AUDIO,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend is None
    assert model is None


@pytest.mark.asyncio
async def test_generate_audio_routes_to_elevenlabs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """generate_audio should route speech to ElevenLabs when backend is elevenlabs."""
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="elevenlabs",
    )

    elevenlabs_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.AUDIO,
        backend_name="elevenlabs",
        model_used="eleven_multilingual_v2",
        file_size_bytes=1234,
    )
    mock_elevenlabs = AsyncMock(return_value=elevenlabs_result)
    monkeypatch.setattr(audio_generation, "_generate_speech_elevenlabs", mock_elevenlabs)

    result = await audio_generation.generate_audio(config)

    assert result.success is True
    assert result.backend_name == "elevenlabs"
    mock_elevenlabs.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_generate_audio_routes_to_openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """generate_audio should route speech to OpenAI when backend is openai."""
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="openai",
    )

    openai_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.AUDIO,
        backend_name="openai",
        model_used="gpt-4o-mini-tts",
        file_size_bytes=1234,
    )
    mock_openai = AsyncMock(return_value=openai_result)
    monkeypatch.setattr(audio_generation, "_generate_audio_openai", mock_openai)

    result = await audio_generation.generate_audio(config)

    assert result.success is True
    assert result.backend_name == "openai"
    mock_openai.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_generate_audio_falls_back_to_openai_on_elevenlabs_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """When ElevenLabs speech fails and OpenAI key exists, fall back to OpenAI.

    The fallback must clear config.model so OpenAI uses its own default
    instead of the ElevenLabs model name selected upstream.
    """
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="elevenlabs",
        model="eleven_multilingual_v2",  # ElevenLabs model from selector
    )

    elevenlabs_fail = GenerationResult(
        success=False,
        backend_name="elevenlabs",
        error="ElevenLabs API error: rate limit exceeded",
    )
    openai_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.AUDIO,
        backend_name="openai",
        model_used="gpt-4o-mini-tts",
        file_size_bytes=1234,
    )

    captured_configs: list[GenerationConfig] = []

    async def _capture_openai(cfg: GenerationConfig) -> GenerationResult:
        captured_configs.append(cfg)
        return openai_result

    monkeypatch.setattr(audio_generation, "_generate_speech_elevenlabs", AsyncMock(return_value=elevenlabs_fail))
    monkeypatch.setattr(audio_generation, "_generate_audio_openai", _capture_openai)
    monkeypatch.setattr(audio_generation, "get_api_key", lambda name: "key" if name == "openai" else None)

    result = await audio_generation.generate_audio(config)

    assert result.success is True
    assert result.backend_name == "openai"
    # The model must be cleared so OpenAI picks its own default.
    assert len(captured_configs) == 1
    assert captured_configs[0].model is None


@pytest.mark.asyncio
async def test_generate_audio_eleven_labs_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Backend 'eleven_labs' (underscore) should be treated as 'elevenlabs'."""
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="eleven_labs",
    )

    elevenlabs_result = GenerationResult(
        success=True,
        output_path=config.output_path,
        media_type=MediaType.AUDIO,
        backend_name="elevenlabs",
        model_used="eleven_multilingual_v2",
        file_size_bytes=1234,
    )
    mock_elevenlabs = AsyncMock(return_value=elevenlabs_result)
    monkeypatch.setattr(audio_generation, "_generate_speech_elevenlabs", mock_elevenlabs)

    result = await audio_generation.generate_audio(config)

    assert result.success is True
    mock_elevenlabs.assert_awaited_once_with(config)


# ---------------------------------------------------------------------------
# ElevenLabs voice resolution
# ---------------------------------------------------------------------------


def test_resolve_voice_none_returns_default():
    """None voice should resolve to the default ElevenLabs voice UUID."""
    voice_id = audio_generation.resolve_elevenlabs_voice(None)
    assert voice_id == audio_generation.ELEVENLABS_DEFAULT_VOICE_ID


def test_resolve_voice_uuid_passthrough():
    """A value that looks like an ElevenLabs UUID should pass through unchanged."""
    uuid = "21m00Tcm4TlvDq8ikWAM"
    assert audio_generation.resolve_elevenlabs_voice(uuid) == uuid


def test_resolve_voice_known_name():
    """A known ElevenLabs voice name should resolve to its UUID."""
    voice_id = audio_generation.resolve_elevenlabs_voice("Rachel")
    assert voice_id == "21m00Tcm4TlvDq8ikWAM"


def test_resolve_voice_known_name_case_insensitive():
    """Voice name resolution should be case-insensitive."""
    voice_id = audio_generation.resolve_elevenlabs_voice("rachel")
    assert voice_id == "21m00Tcm4TlvDq8ikWAM"


def test_resolve_voice_openai_name_returns_default():
    """An OpenAI voice name (e.g., 'alloy') should fall back to default."""
    voice_id = audio_generation.resolve_elevenlabs_voice("alloy")
    assert voice_id == audio_generation.ELEVENLABS_DEFAULT_VOICE_ID


def test_resolve_voice_unknown_returns_default():
    """An unknown voice name should fall back to default."""
    voice_id = audio_generation.resolve_elevenlabs_voice("totally_unknown_voice")
    assert voice_id == audio_generation.ELEVENLABS_DEFAULT_VOICE_ID


@pytest.mark.asyncio
async def test_elevenlabs_speech_uses_resolved_voice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """_generate_speech_elevenlabs should resolve voice name to UUID before API call."""
    captured_kwargs: list[dict] = []

    async def _fake_convert(**kwargs):
        captured_kwargs.append(kwargs)
        yield b"audio-bytes"

    mock_client = SimpleNamespace(
        text_to_speech=SimpleNamespace(convert=_fake_convert),
    )
    monkeypatch.setattr(audio_generation, "AsyncElevenLabs", Mock(return_value=mock_client))
    monkeypatch.setattr(audio_generation, "get_api_key", lambda name: "test-key")

    config = GenerationConfig(
        prompt="hello",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="elevenlabs",
        voice="Rachel",  # Name, not UUID
    )

    result = await audio_generation._generate_speech_elevenlabs(config)

    assert result.success is True
    assert len(captured_kwargs) == 1
    # Must have resolved "Rachel" to the UUID
    assert captured_kwargs[0]["voice_id"] == "21m00Tcm4TlvDq8ikWAM"
    assert result.metadata["resolved_voice_id"] == "21m00Tcm4TlvDq8ikWAM"


@pytest.mark.asyncio
async def test_generate_audio_openai_awaits_stream_to_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Regression: OpenAI streaming write must be awaited so file exists before stat()."""
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "speech.mp3",
        media_type=MediaType.AUDIO,
        backend="openai",
    )

    async def _write_output(path: Path) -> None:
        Path(path).write_bytes(b"audio-bytes")

    mock_response = SimpleNamespace(stream_to_file=AsyncMock(side_effect=_write_output))

    class _FakeStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    create_mock = Mock(return_value=_FakeStreamContext())
    mock_client = SimpleNamespace(
        audio=SimpleNamespace(
            speech=SimpleNamespace(
                with_streaming_response=SimpleNamespace(create=create_mock),
            ),
        ),
    )
    mock_async_openai = Mock(return_value=mock_client)

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(audio_generation, "AsyncOpenAI", mock_async_openai)

    result = await audio_generation._generate_audio_openai(config)

    assert result.success is True
    assert result.file_size_bytes == len(b"audio-bytes")
    create_mock.assert_called_once_with(model="gpt-4o-mini-tts", voice="alloy", input=config.prompt)
    mock_response.stream_to_file.assert_awaited_once_with(config.output_path)
