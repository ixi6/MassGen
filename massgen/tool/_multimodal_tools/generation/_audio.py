"""Audio generation backends: ElevenLabs (TTS, music, SFX) and OpenAI TTS."""

from dataclasses import replace
from typing import Any

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

    # Audio editing operations require ElevenLabs and input audio.
    if audio_type in {
        "voice_conversion",
        "audio_isolation",
        "voice_design",
        "voice_clone",
        "dubbing",
    }:
        if audio_type == "voice_design":
            # Voice design doesn't need input audio — it creates from scratch.
            return await _design_voice_elevenlabs(config)
        if audio_type == "voice_clone":
            # Voice cloning uses voice_samples, not input_audio_path.
            if not config.voice_samples:
                return GenerationResult(
                    success=False,
                    backend_name="elevenlabs",
                    error=("voice_clone requires voice_samples. " "Provide a list of audio file paths for cloning."),
                )
            if not has_api_key("elevenlabs"):
                return GenerationResult(
                    success=False,
                    backend_name="elevenlabs",
                    error=("voice_clone is only supported via ElevenLabs. " "Set ELEVENLABS_API_KEY."),
                )
            return await _clone_voice_elevenlabs(config)
        if audio_type == "dubbing":
            if not config.input_audio_path:
                return GenerationResult(
                    success=False,
                    backend_name="elevenlabs",
                    error=("dubbing requires input_audio_path. " "Provide a path to the audio/video file to dub."),
                )
            if not has_api_key("elevenlabs"):
                return GenerationResult(
                    success=False,
                    backend_name="elevenlabs",
                    error=("dubbing is only supported via ElevenLabs. " "Set ELEVENLABS_API_KEY."),
                )
            return await _dub_elevenlabs(config)
        if not config.input_audio_path:
            return GenerationResult(
                success=False,
                backend_name="elevenlabs",
                error=(f"{audio_type} requires input_audio_path. " "Provide a path to the source audio file."),
            )
        if not has_api_key("elevenlabs"):
            return GenerationResult(
                success=False,
                backend_name="elevenlabs",
                error=(f"{audio_type} is only supported via ElevenLabs. " "Set ELEVENLABS_API_KEY."),
            )
        if audio_type == "voice_conversion":
            return await _convert_voice_elevenlabs(config)
        return await _isolate_audio_elevenlabs(config)

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

        # Build TTS kwargs with optional advanced parameters
        tts_kwargs: dict[str, Any] = {
            "voice_id": voice_id,
            "text": config.prompt,
            "model_id": model,
        }

        # Voice settings (stability + similarity)
        if config.voice_stability is not None or config.voice_similarity is not None:
            from elevenlabs import VoiceSettings

            settings_kwargs: dict[str, float] = {}
            if config.voice_stability is not None:
                settings_kwargs["stability"] = config.voice_stability
            if config.voice_similarity is not None:
                settings_kwargs["similarity_boost"] = config.voice_similarity
            tts_kwargs["voice_settings"] = VoiceSettings(**settings_kwargs)

        # Seed for reproducibility
        if config.seed is not None:
            tts_kwargs["seed"] = config.seed

        # SDK v2.x: convert() returns an async generator, not a coroutine.
        audio_iterator = client.text_to_speech.convert(**tts_kwargs)

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
                "voice_stability": config.voice_stability,
                "voice_similarity": config.voice_similarity,
                "seed": config.seed,
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

        # Add speed if provided (0.25 to 4.0)
        if config.speed is not None:
            clamped_speed = max(0.25, min(4.0, config.speed))
            if config.speed != clamped_speed:
                logger.warning(
                    "OpenAI TTS speed clamped from %.2f to %.2f " "(valid range: 0.25-4.0)",
                    config.speed,
                    clamped_speed,
                )
            request_params["speed"] = clamped_speed

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


# ---------------------------------------------------------------------------
# ElevenLabs audio editing (MAS-334)
# ---------------------------------------------------------------------------


async def _convert_voice_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Convert voice in audio using ElevenLabs Speech-to-Speech API.

    Takes input audio and converts the voice to a target voice while
    preserving the original speech content, pacing, and intonation.

    Args:
        config: GenerationConfig with input_audio_path and voice (target)

    Returns:
        GenerationResult with converted audio info
    """
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY.",
        )

    if not config.input_audio_path or not config.input_audio_path.exists():
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"Input audio file not found: {config.input_audio_path}",
        )

    voice_id = resolve_elevenlabs_voice(config.voice)
    # STS requires a speech-to-speech model. The general ElevenLabs default
    # (eleven_multilingual_v2) doesn't support STS, so override it.
    _STS_DEFAULT = "eleven_english_sts_v2"
    model = config.model if config.model and "sts" in config.model else _STS_DEFAULT

    try:
        client = AsyncElevenLabs(api_key=api_key)

        audio_bytes_in = config.input_audio_path.read_bytes()
        audio_iterator = client.speech_to_speech.convert(
            voice_id=voice_id,
            audio=audio_bytes_in,
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
                "audio_type": "voice_conversion",
                "source_audio": str(config.input_audio_path),
                "target_voice": config.voice,
                "resolved_voice_id": voice_id,
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs voice conversion failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            model_used=model,
            error=f"ElevenLabs voice conversion error: {e}",
        )


async def _isolate_audio_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Isolate vocals/speech from background noise using ElevenLabs.

    Takes input audio and returns clean, isolated audio with background
    noise, music, and other non-speech sounds removed.

    Args:
        config: GenerationConfig with input_audio_path

    Returns:
        GenerationResult with isolated audio info
    """
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY.",
        )

    if not config.input_audio_path or not config.input_audio_path.exists():
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"Input audio file not found: {config.input_audio_path}",
        )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        audio_bytes_in = config.input_audio_path.read_bytes()
        audio_iterator = client.audio_isolation.convert(
            audio=audio_bytes_in,
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
            model_used="elevenlabs-audio-isolation",
            file_size_bytes=file_size,
            metadata={
                "audio_type": "audio_isolation",
                "source_audio": str(config.input_audio_path),
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs audio isolation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs audio isolation error: {e}",
        )


async def _design_voice_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Design a new synthetic voice using ElevenLabs Voice Design API.

    Creates voice previews from a text description. The prompt describes
    desired voice characteristics (age, gender, accent, tone, etc.).
    Returns the first preview as the output audio.

    Args:
        config: GenerationConfig with prompt (voice description)

    Returns:
        GenerationResult with voice preview audio info
    """
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY.",
        )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        # The prompt describes desired voice characteristics.
        # preview_text is what the voice will say in the preview.
        preview_text = config.extra_params.get(
            "preview_text",
            "Hello! This is a preview of the designed voice. " "I can speak clearly and naturally, adjusting my tone " "and pacing to suit different kinds of content.",
        )

        response = await client.text_to_voice.create_previews(
            voice_description=config.prompt,
            text=preview_text,
        )

        if not response.previews:
            return GenerationResult(
                success=False,
                backend_name="elevenlabs",
                error="No voice previews generated from description.",
            )

        # Use the first preview
        preview = response.previews[0]
        audio_bytes = preview.audio_base_64

        import base64

        decoded = base64.b64decode(audio_bytes)
        config.output_path.write_bytes(decoded)
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used="elevenlabs-voice-design",
            file_size_bytes=file_size,
            metadata={
                "audio_type": "voice_design",
                "voice_description": config.prompt,
                "preview_text": preview_text,
                "generated_voice_id": getattr(preview, "generated_voice_id", None),
                "total_previews": len(response.previews),
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs voice design failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs voice design error: {e}",
        )


async def _clone_voice_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Clone a voice from audio samples using ElevenLabs IVC.

    Creates an instant voice clone from 1+ audio sample files, then
    generates a TTS preview using the cloned voice.

    Args:
        config: GenerationConfig with voice_samples (paths to audio samples)
               and prompt (text to speak with the cloned voice)

    Returns:
        GenerationResult with cloned voice preview and voice UUID in metadata
    """
    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY.",
        )

    # Validate sample files exist
    for sample_path in config.voice_samples:
        if not sample_path.exists():
            return GenerationResult(
                success=False,
                backend_name="elevenlabs",
                error=f"Voice sample file not found: {sample_path}",
            )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        voice_name = config.extra_params.get("voice_name", "Cloned Voice")
        voice_description = config.extra_params.get(
            "voice_description",
            "Voice cloned from audio samples",
        )
        remove_noise = config.extra_params.get("remove_background_noise", True)

        # Open all sample files for the API call
        sample_files = [open(p, "rb") for p in config.voice_samples]
        try:
            voice = await client.voices.ivc.create(
                name=voice_name,
                files=sample_files,
                remove_background_noise=remove_noise,
                description=voice_description,
            )
        finally:
            for f in sample_files:
                f.close()

        # Generate a preview with the cloned voice
        preview_text = config.prompt or "Hello, this is a test of the cloned voice."
        model = config.model or get_default_model("elevenlabs", MediaType.AUDIO) or "eleven_multilingual_v2"

        audio_iterator = client.text_to_speech.convert(
            voice_id=voice.voice_id,
            text=preview_text,
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
                "audio_type": "voice_clone",
                "cloned_voice_id": voice.voice_id,
                "voice_name": voice_name,
                "sample_count": len(config.voice_samples),
                "sample_paths": [str(p) for p in config.voice_samples],
                "remove_background_noise": remove_noise,
                "format": "mp3",
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs voice cloning failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs voice cloning error: {e}",
        )


# ---------------------------------------------------------------------------
# Audio translation & dubbing (MAS-334 Phase 4)
# ---------------------------------------------------------------------------


async def _translate_audio_openai(config: GenerationConfig) -> GenerationResult:
    """Translate audio to English using OpenAI's Whisper translations API.

    Takes audio in any language and translates it to English text.
    The translated text is written to the output file.

    Args:
        config: GenerationConfig with input_audio_path

    Returns:
        GenerationResult with translated text saved to output_path
    """
    api_key = get_api_key("openai")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error="OpenAI API key not found. Set OPENAI_API_KEY.",
        )

    if not config.input_audio_path or not config.input_audio_path.exists():
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"Input audio file not found: {config.input_audio_path}",
        )

    try:
        client = AsyncOpenAI(api_key=api_key)
        model = config.model or "whisper-1"

        with open(config.input_audio_path, "rb") as audio_file:
            translation = await client.audio.translations.create(
                model=model,
                file=audio_file,
                response_format="text",
            )

        # Write translated text to output
        output_path = config.output_path.with_suffix(".txt")
        output_path.write_text(translation, encoding="utf-8")
        file_size = output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=output_path,
            media_type=MediaType.AUDIO,
            backend_name="openai",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "audio_type": "translation",
                "source_audio": str(config.input_audio_path),
                "target_language": "en",
                "format": "txt",
            },
        )
    except Exception as e:
        logger.exception(f"OpenAI audio translation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI translation error: {e}",
        )


async def _dub_elevenlabs(config: GenerationConfig) -> GenerationResult:
    """Dub audio/video to another language using ElevenLabs Dubbing API.

    Creates an asynchronous dubbing job and polls for completion.
    Supports both audio and video input files.

    Args:
        config: GenerationConfig with input_audio_path, target_language,
                and optionally source_language

    Returns:
        GenerationResult with dubbed audio/video info
    """
    import asyncio

    api_key = get_api_key("elevenlabs")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error="ElevenLabs API key not found. Set ELEVENLABS_API_KEY.",
        )

    if not config.input_audio_path or not config.input_audio_path.exists():
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"Input file not found: {config.input_audio_path}",
        )

    if not config.target_language:
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=("dubbing requires target_language. " "Provide the target language code (e.g., 'es', 'fr', 'de')."),
        )

    try:
        client = AsyncElevenLabs(api_key=api_key)

        # Create dubbing job
        dub_kwargs: dict[str, Any] = {
            "target_lang": config.target_language,
        }
        if config.source_language:
            dub_kwargs["source_lang"] = config.source_language

        with open(config.input_audio_path, "rb") as audio_file:
            dub_response = await client.dubbing.create(
                file=audio_file,
                **dub_kwargs,
            )

        dubbing_id = dub_response.dubbing_id

        # Poll for completion
        max_wait = 600  # 10 minutes
        poll_interval = 10
        elapsed = 0

        while elapsed < max_wait:
            status = await client.dubbing.get(dubbing_id)
            if status.status == "dubbed":
                break
            if status.status == "failed":
                return GenerationResult(
                    success=False,
                    backend_name="elevenlabs",
                    error=f"Dubbing failed: {getattr(status, 'error', 'Unknown error')}",
                )
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if elapsed >= max_wait:
            return GenerationResult(
                success=False,
                backend_name="elevenlabs",
                error="Dubbing timed out after 10 minutes",
            )

        # Download dubbed output
        dubbed_content = await client.dubbing.audio.get(
            dubbing_id=dubbing_id,
            language_code=config.target_language,
        )

        # Collect streamed content
        chunks: list[bytes] = []
        async for chunk in dubbed_content:
            chunks.append(chunk)
        dubbed_bytes = b"".join(chunks)

        config.output_path.write_bytes(dubbed_bytes)
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.AUDIO,
            backend_name="elevenlabs",
            model_used="elevenlabs-dubbing",
            file_size_bytes=file_size,
            metadata={
                "audio_type": "dubbing",
                "dubbing_id": dubbing_id,
                "source_audio": str(config.input_audio_path),
                "source_language": config.source_language,
                "target_language": config.target_language,
            },
        )
    except Exception as e:
        logger.exception(f"ElevenLabs dubbing failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="elevenlabs",
            error=f"ElevenLabs dubbing error: {e}",
        )
