"""Audio generation backend: OpenAI TTS only."""

from openai import AsyncOpenAI

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_api_key,
    get_default_model,
)

# Available voices for OpenAI TTS
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "sage"]

# Supported audio formats
AUDIO_FORMATS = ["mp3", "opus", "aac", "flac", "wav", "pcm"]


async def generate_audio(config: GenerationConfig) -> GenerationResult:
    """Generate audio using OpenAI speech synthesis.

    Notes:
    - Only ``audio_type="speech"`` is supported in this release.
    - ElevenLabs backend support is intentionally disabled for now.
    """
    audio_type = str(config.extra_params.get("audio_type", "speech"))
    backend = (config.backend or "openai").lower()

    if audio_type != "speech":
        return GenerationResult(
            success=False,
            backend_name=backend,
            error=(f"Audio type '{audio_type}' is not supported in this release. " "Supported audio_type: 'speech'."),
        )

    if backend in {"elevenlabs", "eleven_labs"}:
        return GenerationResult(
            success=False,
            backend_name=backend,
            error=("Audio backend 'elevenlabs' is not supported in this release. " "Use backend='openai'."),
        )

    if backend != "openai":
        logger.warning(
            "Unknown audio backend '%s'; falling back to OpenAI TTS.",
            backend,
        )

    return await _generate_audio_openai(config)


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
