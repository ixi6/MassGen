"""Tests for audio_type behavior after ElevenLabs removal."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from massgen.tool._multimodal_tools.generation import _audio as audio_module
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
)


def _make_config(tmp_path: Path, audio_type: str = "speech", **kwargs) -> GenerationConfig:
    """Helper to build a GenerationConfig for audio tests."""
    defaults = {
        "prompt": "test prompt",
        "output_path": tmp_path / "out.mp3",
        "media_type": MediaType.AUDIO,
        "backend": "openai",
        "extra_params": {"audio_type": audio_type},
    }
    defaults.update(kwargs)
    return GenerationConfig(**defaults)


def _ok_result(**kwargs) -> GenerationResult:
    return GenerationResult(
        success=True,
        media_type=MediaType.AUDIO,
        backend_name="openai",
        file_size_bytes=1234,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_audio_type_defaults_to_speech(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When audio_type is absent from extra_params, generate_audio routes to speech."""
    config = GenerationConfig(
        prompt="hello",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="openai",
        extra_params={},  # no audio_type
    )
    mock_openai = AsyncMock(return_value=_ok_result())
    monkeypatch.setattr(audio_module, "_generate_audio_openai", mock_openai)

    result = await audio_module.generate_audio(config)

    assert result.success is True
    mock_openai.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_music_audio_type_returns_unsupported_error(tmp_path: Path):
    """Music generation is currently disabled in this release."""
    config = _make_config(tmp_path, audio_type="music")

    result = await audio_module.generate_audio(config)

    assert result.success is False
    assert "music" in (result.error or "").lower()
    assert "not supported" in (result.error or "").lower()
    assert "speech" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_sfx_audio_type_returns_unsupported_error(tmp_path: Path):
    """Sound effect generation is currently disabled in this release."""
    config = _make_config(tmp_path, audio_type="sound_effect")

    result = await audio_module.generate_audio(config)

    assert result.success is False
    assert "sound_effect" in (result.error or "").lower()
    assert "not supported" in (result.error or "").lower()
    assert "speech" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_generate_media_threads_audio_type(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """audio_type parameter from generate_media arrives in config.extra_params."""
    captured_configs: list[GenerationConfig] = []

    async def _capture_generate_audio(config: GenerationConfig) -> GenerationResult:
        captured_configs.append(config)
        config.output_path.write_bytes(b"fake-audio")
        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="openai",
            model_used="gpt-4o-mini-tts",
            file_size_bytes=10,
        )

    with (
        patch(
            "massgen.context.task_context.load_task_context_with_warning",
            return_value=(None, None),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-4o-mini-tts"),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_audio",
            new=_capture_generate_audio,
        ),
    ):
        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        result = await generate_media(
            prompt="concise narration",
            mode="audio",
            audio_type="speech",
            agent_cwd=str(tmp_path),
            allowed_paths=[str(tmp_path)],
        )

    payload = json.loads(result.output_blocks[0].data)
    assert payload["success"] is True
    assert len(captured_configs) == 1
    assert captured_configs[0].extra_params.get("audio_type") == "speech"


@pytest.mark.asyncio
async def test_generate_media_music_returns_error(tmp_path: Path):
    """generate_media surfaces unsupported audio_type errors from generate_audio."""
    with (
        patch(
            "massgen.context.task_context.load_task_context_with_warning",
            return_value=(None, None),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-4o-mini-tts"),
        ),
    ):
        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        result = await generate_media(
            prompt="epic cinematic soundtrack",
            mode="audio",
            audio_type="music",
            agent_cwd=str(tmp_path),
            allowed_paths=[str(tmp_path)],
        )

    payload = json.loads(result.output_blocks[0].data)
    assert payload["success"] is False
    assert "music" in payload["error"].lower()
