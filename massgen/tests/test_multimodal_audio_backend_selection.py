"""Tests for audio generation backend selection without ElevenLabs support."""

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


def test_audio_auto_selection_uses_openai(monkeypatch: pytest.MonkeyPatch):
    """Audio auto-selection should choose OpenAI when API key is present."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    backend, model = select_backend_and_model(
        media_type=MediaType.AUDIO,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "openai"
    assert model == "gpt-4o-mini-tts"


def test_audio_auto_selection_returns_none_without_openai(monkeypatch: pytest.MonkeyPatch):
    """Audio auto-selection should fail when OpenAI API key is unavailable."""
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


def test_audio_preferred_elevenlabs_falls_back_to_openai(monkeypatch: pytest.MonkeyPatch):
    """A preferred ElevenLabs backend should gracefully fall back to OpenAI."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-elevenlabs-key")

    backend, model = select_backend_and_model(
        media_type=MediaType.AUDIO,
        preferred_backend="elevenlabs",
        preferred_model=None,
        config=None,
    )

    assert backend == "openai"
    assert model == "gpt-4o-mini-tts"


@pytest.mark.asyncio
async def test_generate_audio_routes_to_openai_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """generate_audio should route speech generation to OpenAI backend."""
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
async def test_generate_audio_rejects_elevenlabs_backend(tmp_path: Path):
    """ElevenLabs backend should be explicitly rejected in this release."""
    config = GenerationConfig(
        prompt="hello world",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="elevenlabs",
    )

    result = await audio_generation.generate_audio(config)

    assert result.success is False
    assert result.backend_name == "elevenlabs"
    assert "not supported" in (result.error or "").lower()
    assert "openai" in (result.error or "").lower()


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
