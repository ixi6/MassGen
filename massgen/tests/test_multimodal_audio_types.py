"""Tests for audio_type routing with ElevenLabs support (speech, music, SFX)."""

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
        "backend": "elevenlabs",
        "extra_params": {"audio_type": audio_type},
    }
    defaults.update(kwargs)
    return GenerationConfig(**defaults)


def _ok_result(backend: str = "elevenlabs", **kwargs) -> GenerationResult:
    return GenerationResult(
        success=True,
        media_type=MediaType.AUDIO,
        backend_name=backend,
        file_size_bytes=1234,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Speech routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_type_defaults_to_speech(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When audio_type is absent from extra_params, generate_audio routes to speech."""
    config = GenerationConfig(
        prompt="hello",
        output_path=tmp_path / "hello.mp3",
        media_type=MediaType.AUDIO,
        backend="elevenlabs",
        extra_params={},  # no audio_type
    )
    mock_elevenlabs = AsyncMock(return_value=_ok_result())
    monkeypatch.setattr(audio_module, "_generate_speech_elevenlabs", mock_elevenlabs)

    result = await audio_module.generate_audio(config)

    assert result.success is True
    mock_elevenlabs.assert_awaited_once_with(config)


# ---------------------------------------------------------------------------
# Music routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_music_routes_to_elevenlabs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """audio_type='music' dispatches to _generate_music_elevenlabs."""
    config = _make_config(tmp_path, audio_type="music")

    mock_music = AsyncMock(return_value=_ok_result())
    monkeypatch.setattr(audio_module, "_generate_music_elevenlabs", mock_music)
    monkeypatch.setattr(audio_module, "has_api_key", lambda name: True)

    result = await audio_module.generate_audio(config)

    assert result.success is True
    mock_music.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_music_requires_elevenlabs_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Music generation should fail with clear error when no ElevenLabs key."""
    config = _make_config(tmp_path, audio_type="music")
    monkeypatch.setattr(audio_module, "has_api_key", lambda name: False)

    result = await audio_module.generate_audio(config)

    assert result.success is False
    assert "elevenlabs" in (result.error or "").lower()
    assert "ELEVENLABS_API_KEY" in (result.error or "")


@pytest.mark.asyncio
async def test_music_auto_upgrades_backend_to_elevenlabs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Music with backend='openai' should auto-upgrade to ElevenLabs when key exists."""
    config = _make_config(tmp_path, audio_type="music", backend="openai")

    mock_music = AsyncMock(return_value=_ok_result())
    monkeypatch.setattr(audio_module, "_generate_music_elevenlabs", mock_music)
    monkeypatch.setattr(audio_module, "has_api_key", lambda name: True)

    result = await audio_module.generate_audio(config)

    assert result.success is True
    mock_music.assert_awaited_once_with(config)


# ---------------------------------------------------------------------------
# Sound effect routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sfx_routes_to_elevenlabs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """audio_type='sound_effect' dispatches to _generate_sfx_elevenlabs."""
    config = _make_config(tmp_path, audio_type="sound_effect")

    mock_sfx = AsyncMock(return_value=_ok_result())
    monkeypatch.setattr(audio_module, "_generate_sfx_elevenlabs", mock_sfx)
    monkeypatch.setattr(audio_module, "has_api_key", lambda name: True)

    result = await audio_module.generate_audio(config)

    assert result.success is True
    mock_sfx.assert_awaited_once_with(config)


@pytest.mark.asyncio
async def test_sfx_requires_elevenlabs_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sound effect generation should fail with clear error when no ElevenLabs key."""
    config = _make_config(tmp_path, audio_type="sound_effect")
    monkeypatch.setattr(audio_module, "has_api_key", lambda name: False)

    result = await audio_module.generate_audio(config)

    assert result.success is False
    assert "elevenlabs" in (result.error or "").lower()
    assert "ELEVENLABS_API_KEY" in (result.error or "")


# ---------------------------------------------------------------------------
# generate_media integration
# ---------------------------------------------------------------------------


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
            backend_name="elevenlabs",
            model_used="eleven_multilingual_v2",
            file_size_bytes=10,
        )

    with (
        patch(
            "massgen.context.task_context.load_task_context_with_warning",
            return_value=(None, None),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("elevenlabs", "eleven_multilingual_v2"),
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
async def test_generate_media_music_routes_to_elevenlabs(tmp_path: Path):
    """generate_media with audio_type='music' routes through to generate_audio."""
    captured_configs: list[GenerationConfig] = []

    async def _capture_generate_audio(config: GenerationConfig) -> GenerationResult:
        captured_configs.append(config)
        config.output_path.write_bytes(b"fake-music")
        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used="elevenlabs-music",
            file_size_bytes=10,
        )

    with (
        patch(
            "massgen.context.task_context.load_task_context_with_warning",
            return_value=(None, None),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("elevenlabs", "eleven_multilingual_v2"),
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
            prompt="epic cinematic soundtrack",
            mode="audio",
            audio_type="music",
            agent_cwd=str(tmp_path),
            allowed_paths=[str(tmp_path)],
        )

    payload = json.loads(result.output_blocks[0].data)
    assert payload["success"] is True
    assert len(captured_configs) == 1
    assert captured_configs[0].extra_params.get("audio_type") == "music"
