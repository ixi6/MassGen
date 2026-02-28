"""Audio generation backends: ElevenLabs (TTS, music, SFX) and OpenAI TTS."""

from dataclasses import replace

from elevenlabs import AsyncElevenLabs
from openai import AsyncOpenAI

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_api_key,
    get_default_model,
    has_api_key,
)

# Available voices for OpenAI TTS
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "sage"]

# Supported audio formats
AUDIO_FORMATS = ["mp3", "opus", "aac", "flac", "wav", "pcm"]

# Default ElevenLabs voice ID — "Rachel" pre-made voice.
# ElevenLabs requires the UUID, not the display name.
ELEVENLABS_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Map of well-known ElevenLabs pre-made voice names to their UUIDs.
# Models often pass display names; the API requires UUIDs.
# Verified against the ElevenLabs TTS API 2026-02-28.
ELEVENLABS_VOICE_MAP: dict[str, str] = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "drew": "29vD33N1CtxCmqQRPOHJ",
    "clyde": "2EiwWnXFnvU5JabPnv8n",
    "paul": "5Q0t7uMcjvnagumLfvZi",
    "domi": "AZnzlk1XvdvUeBnXmlld",
    "dave": "CYw3kZ02Hs0563khs1Fj",
    "fin": "D38z5RcWu1voky8WS1ja",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "thomas": "GBv7mTt0atIp3Br8iCZE",
    "charlie": "IKne3meq5aSn9XLyUdCD",
    "george": "JBFqnCBsd6RMkjVDRZzb",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "patrick": "ODq5zmih8GrVes37Dizd",
    "harry": "SOYHLrjzK2X1ezoPC6cr",
    "liam": "TX3LPaxmHKxFdv7VOQHJ",
    "dorothy": "ThT5KcBeYPX3keUQqHPh",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "charlotte": "XB0fDUnXU5powFXDhCwa",
    "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "james": "ZQe5CZNOzWyzPSCn5a3c",
    "michael": "flq6f7yk4E4fJM5XTYuZ",
    "ethan": "g5CIjZEefAph4nQFvHAz",
    "chris": "iP95p4xoKVk53GoZ742B",
    "mimi": "zrHiDhphv9ZnVXBqCLjz",
    "brian": "nPczCjzI2devNBz1zQrb",
    "sam": "yoZ06aMxZJJ28mfd3POQ",
    "lily": "pFZP5JQG7iQjIQuC4Bku",
    "bill": "pqHfZKP75CvOlQylNhV4",
    "nicole": "piTKgcLEGmPE4e6mEKli",
    "daniel": "onwK4e9ZLuTAKqWW03F9",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "glinda": "z9fAnlkpzviPz146aGWa",
}

# ElevenLabs UUIDs are 20-char alphanumeric strings.
_ELEVENLABS_UUID_LEN = 20


def resolve_elevenlabs_voice(voice: str | None) -> str:
    """Resolve a voice name or UUID to an ElevenLabs voice UUID.

    - None → default voice UUID (Rachel)
    - 20-char alphanumeric string → assumed UUID, pass through
    - Known display name (case-insensitive) → mapped UUID
    - Unknown name → default voice UUID with log warning
    """
    if voice is None:
        return ELEVENLABS_DEFAULT_VOICE_ID

    # If it looks like an ElevenLabs UUID (20 chars, alphanumeric), pass through.
    if len(voice) == _ELEVENLABS_UUID_LEN and voice.isalnum():
        return voice

    # Try case-insensitive name lookup.
    resolved = ELEVENLABS_VOICE_MAP.get(voice.lower())
    if resolved:
        return resolved

    logger.warning(
        "Unknown ElevenLabs voice '%s'; using default (Rachel). " "Pass a voice UUID or a known name: %s",
        voice,
        ", ".join(sorted(ELEVENLABS_VOICE_MAP)),
    )
    return ELEVENLABS_DEFAULT_VOICE_ID


async def generate_audio(config: GenerationConfig) -> GenerationResult:
    """Generate audio using the selected backend.

    Dispatches based on ``audio_type`` in ``config.extra_params``:
    - ``"speech"`` (default): Text-to-speech via ElevenLabs or OpenAI.
    - ``"music"``: Music generation via ElevenLabs only.
    - ``"sound_effect"``: Sound effect generation via ElevenLabs only.

    Args:
        config: GenerationConfig with prompt (text), output_path, voice, etc.

    Returns:
        GenerationResult with success status and file info
    """
    audio_type = config.extra_params.get("audio_type", "speech")
    backend = (config.backend or "openai").lower()

    # Music and sound effects are ElevenLabs-only.
    if audio_type in {"music", "sound_effect"}:
        if backend not in {"elevenlabs", "eleven_labs"} and has_api_key("elevenlabs"):
            backend = "elevenlabs"
        if not has_api_key("elevenlabs"):
            return GenerationResult(
                success=False,
                backend_name=backend,
                error=(f"{audio_type} generation is only supported via " "ElevenLabs. Set ELEVENLABS_API_KEY."),
            )
        if audio_type == "music":
            return await _generate_music_elevenlabs(config)
        return await _generate_sfx_elevenlabs(config)

    # Speech: ElevenLabs preferred with OpenAI fallback.
    if backend in {"elevenlabs", "eleven_labs"}:
        elevenlabs_result = await _generate_speech_elevenlabs(config)
        if elevenlabs_result.success:
            return elevenlabs_result

        if get_api_key("openai"):
            logger.warning(
                "ElevenLabs TTS failed (%s). Falling back to OpenAI.",
                elevenlabs_result.error,
            )
            # Clear the model so OpenAI uses its own default instead of
            # the ElevenLabs model name that was selected upstream.
            openai_config = replace(config, model=None)
            return await _generate_audio_openai(openai_config)

        return elevenlabs_result

    if backend != "openai":
        logger.warning(
            "Unknown audio backend '%s'; falling back to OpenAI TTS.",
            backend,
        )

    return await _generate_audio_openai(config)


# ---------------------------------------------------------------------------
# ElevenLabs backends (SDK)
# ---------------------------------------------------------------------------


async def _generate_speech_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Generate speech using the ElevenLabs Text-to-Speech API."""
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY environment variable.",
        )

    model = config.model or get_default_model("elevenlabs", MediaType.AUDIO) or "eleven_multilingual_v2"
    voice_id = resolve_elevenlabs_voice(config.voice)

    try:
        client = AsyncElevenLabs(api_key=api_key)
        # SDK v2.x: convert() returns an async generator, not a coroutine.
        audio_iterator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=config.prompt,
            model_id=model,
        )

        chunks: list[bytes] = []
        async for chunk in audio_iterator:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        config.output_path.write_bytes(audio_bytes)
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "audio_type": "speech",
                "voice": config.voice,
                "resolved_voice_id": voice_id,
                "format": "mp3",
                "text_length": len(config.prompt),
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs TTS generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            model_used=model,
            error=f"ElevenLabs TTS error: {e}",
        )


async def _generate_music_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Generate music using the ElevenLabs Music API."""
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY environment variable.",
        )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        duration_ms = (config.duration or 30) * 1000
        force_instrumental = config.extra_params.get("force_instrumental", True)

        audio_iterator = client.music.compose(
            prompt=config.prompt,
            music_length_ms=duration_ms,
            force_instrumental=force_instrumental,
        )

        chunks: list[bytes] = []
        async for chunk in audio_iterator:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        config.output_path.write_bytes(audio_bytes)
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used="elevenlabs-music",
            file_size_bytes=file_size,
            metadata={
                "audio_type": "music",
                "duration_ms": duration_ms,
                "force_instrumental": force_instrumental,
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs music generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs music error: {e}",
        )


async def _generate_sfx_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Generate sound effects using the ElevenLabs Sound Effects API."""
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY environment variable.",
        )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        prompt_influence = config.extra_params.get("prompt_influence", 0.3)
        kwargs: dict = {
            "text": config.prompt,
            "prompt_influence": prompt_influence,
        }
        if config.duration is not None:
            kwargs["duration_seconds"] = max(0.5, min(float(config.duration), 30.0))

        audio_iterator = client.text_to_sound_effects.convert(**kwargs)

        chunks: list[bytes] = []
        async for chunk in audio_iterator:
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)

        config.output_path.write_bytes(audio_bytes)
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used="elevenlabs-sfx",
            file_size_bytes=file_size,
            metadata={
                "audio_type": "sound_effect",
                "duration_seconds": kwargs.get("duration_seconds"),
                "prompt_influence": prompt_influence,
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs SFX generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs SFX error: {e}",
        )


# ---------------------------------------------------------------------------
# OpenAI backend (speech only)
# ---------------------------------------------------------------------------


async def _generate_audio_openai(config: GenerationConfig) -> GenerationResult:
    """Generate audio using OpenAI's TTS API.

    Uses streaming response for efficient file handling.

    Args:
        config: GenerationConfig with prompt (text to speak), output path, voice, etc.

    Returns:
        GenerationResult with generated audio info
    """
    api_key = get_api_key("openai")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error="OpenAI API key not found. Set OPENAI_API_KEY environment variable.",
        )

    try:
        client = AsyncOpenAI(api_key=api_key)
        model = config.model or get_default_model("openai", MediaType.AUDIO)
        voice = config.voice or "alloy"

        # Validate voice
        if voice not in OPENAI_VOICES:
            logger.warning(
                "Unknown voice '%s', using 'alloy'. Available: %s",
                voice,
                ", ".join(OPENAI_VOICES),
            )
            voice = "alloy"

        # Determine format from output path extension
        ext = config.output_path.suffix.lstrip(".").lower()
        if ext not in AUDIO_FORMATS:
            ext = "mp3"  # Default format

        # Prepare request parameters
        request_params = {
            "model": model,
            "voice": voice,
            "input": config.prompt,
        }

        # Add instructions if provided (only for gpt-4o-mini-tts)
        instructions = config.extra_params.get("instructions")
        if instructions and model == "gpt-4o-mini-tts":
            request_params["instructions"] = instructions

        # Use streaming response for efficient file handling
        async with client.audio.speech.with_streaming_response.create(**request_params) as response:
            await response.stream_to_file(config.output_path)

        # Get file info
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="openai",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "voice": voice,
                "format": ext,
                "text_length": len(config.prompt),
                "instructions": instructions,
            },
        )

    except Exception as e:
        logger.exception(f"OpenAI TTS generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI TTS error: {e}",
        )
