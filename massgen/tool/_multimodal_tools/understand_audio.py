"""
Transcribe audio file(s) to text using OpenAI's Transcription API or Gemini.

Supports multiple backends with automatic selection:
- Gemini: Uses native audio understanding with inline_data (preferred)
- OpenAI: Uses Whisper transcription API

Backend Selection Priority:
1. Same backend as the calling agent (if specified and has API key)
2. Default priority list: Gemini → OpenAI (first with available API key)

This can be configured via the multimodal settings in agent config.
"""

import json
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.backend_selector import get_backend
from massgen.tool._result import ExecutionResult, TextContent


def _validate_path_access(path: Path, allowed_paths: list[Path] | None = None) -> None:
    """
    Validate that a path is within allowed directories.

    Args:
        path: Path to validate
        allowed_paths: List of allowed base paths (optional)

    Raises:
        ValueError: If path is not within allowed directories
    """
    if not allowed_paths:
        return  # No restrictions

    for allowed_path in allowed_paths:
        try:
            path.relative_to(allowed_path)
            return  # Path is within this allowed directory
        except ValueError:
            continue

    raise ValueError(f"Path not in allowed directories: {path}")


def _get_mime_type(file_path: Path) -> str:
    """Get MIME type for an audio file."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        return mime_type
    # Fallback
    ext = file_path.suffix.lower()
    fallbacks = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    return fallbacks.get(ext, "audio/mpeg")


async def _process_with_gemini(
    audio_path: Path,
    prompt: str,
    model: str = "gemini-3-flash-preview",
) -> str:
    """
    Process audio using Gemini's native audio understanding.

    Args:
        audio_path: Path to the audio file
        prompt: Prompt for analysis (string or dict with 'question' key)
        model: Gemini model to use

    Returns:
        Text transcription/analysis from Gemini
    """
    from google import genai
    from google.genai import types

    # Handle dict prompt (model sometimes outputs {"question": "..."})
    if isinstance(prompt, dict):
        prompt = prompt.get("question", str(prompt))

    # Read audio data
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    mime_type = _get_mime_type(audio_path)

    # Create Gemini client
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    logger.info(f"[understand_audio] Using Gemini {model} for audio: {audio_path.name}")

    # Use types.Part for proper SDK format
    contents = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=audio_data, mime_type=mime_type),
    ]

    # Make API call
    response = client.models.generate_content(
        model=model,
        contents=contents,
    )

    return response.text


async def _process_with_openai(
    audio_path: Path,
    prompt: str | None = None,
    model: str = "gpt-4o-transcribe",
) -> str:
    """
    Process audio using OpenAI's Whisper transcription API.

    Args:
        audio_path: Path to the audio file
        prompt: Optional prompt (not used for Whisper, but included for API consistency)
        model: OpenAI model to use

    Returns:
        Text transcription from OpenAI
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key)

    logger.info(f"[understand_audio] Using OpenAI {model} for audio: {audio_path.name}")

    with open(audio_path, "rb") as audio_file:
        transcription = await client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
        )

    return transcription


async def _process_with_openai_native(
    audio_path: Path,
    prompt: str | None = None,
    model: str = "gpt-4o-audio-preview",
) -> str:
    """Process audio using OpenAI's native audio understanding via Chat Completions.

    Unlike Whisper (transcription-only), this sends audio as input_audio content
    to a chat model that natively understands audio, preserving tone, emotion,
    pacing, emphasis, and speaker characteristics.

    Args:
        audio_path: Path to the audio file
        prompt: Analysis prompt (what to extract from the audio)
        model: OpenAI model with native audio support

    Returns:
        Rich analysis text from the model
    """
    import base64

    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key)

    logger.info(
        f"[understand_audio] Using OpenAI native audio {model} for: {audio_path.name}",
    )

    # Read and base64-encode the audio
    with open(audio_path, "rb") as f:
        audio_data = base64.b64encode(f.read()).decode("utf-8")

    # Determine format from extension
    ext = audio_path.suffix.lstrip(".").lower()
    format_map = {
        "mp3": "mp3",
        "wav": "wav",
        "m4a": "mp4",
        "ogg": "ogg",
        "flac": "flac",
        "aac": "aac",
        "opus": "opus",
    }
    audio_format = format_map.get(ext, "mp3")

    analysis_prompt = prompt or (
        "Analyze this audio comprehensively. Include: "
        "1) Full transcription of speech, "
        "2) Speaker characteristics (tone, emotion, energy, pacing), "
        "3) Notable emphasis or inflection patterns, "
        "4) Background sounds or music if present, "
        "5) Overall mood and atmosphere."
    )

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": analysis_prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_data,
                            "format": audio_format,
                        },
                    },
                ],
            },
        ],
    )

    return response.choices[0].message.content or ""


async def understand_audio(
    audio_paths: list[str],
    prompt: str | None = None,
    model: str | None = None,
    backend_type: str | None = None,
    analysis_mode: str = "rich",
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
    task_context: str | None = None,
) -> ExecutionResult:
    """
    Transcribe/analyze audio file(s) using the best available backend.

    Backend Selection Priority:
    1. Same backend as the calling agent (if backend_type specified and has API key)
    2. Default priority list: Gemini → OpenAI (first with available API key)

    Supports multiple backends and analysis modes:
    - Gemini: Uses native audio understanding with inline_data (preferred)
    - OpenAI (rich mode): Uses gpt-4o-audio-preview for full audio understanding
      including tone, emotion, pacing, and speaker characteristics
    - OpenAI (transcription mode): Uses Whisper for fast, cheap transcription

    Args:
        audio_paths: List of paths to input audio files (WAV, MP3, M4A, etc.)
                    - Relative path: Resolved relative to workspace
                    - Absolute path: Must be within allowed directories
        prompt: Optional prompt for audio analysis. For rich mode, guides what
                aspects to analyze. For transcription mode, used as context hint.
        model: Model to use. If not specified, uses default from backend selector:
               - Gemini: "gemini-3-flash-preview"
               - OpenAI (rich): "gpt-4o-audio-preview"
               - OpenAI (transcription): "gpt-4o-transcribe"
        backend_type: Preferred backend ("gemini" or "openai"). If specified and
                      has API key, this backend is used. Otherwise falls through
                      to priority list.
        analysis_mode: Analysis depth - "rich" (default) for full audio
                       understanding with tone/emotion/pacing, or "transcription"
                       for fast text-only transcription.
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Current working directory of the agent (optional)

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "understand_audio"
        - transcriptions: List of transcription/analysis results for each file
        - audio_files: List of paths to the input audio files
        - model: Model used
        - backend: Backend used ("gemini" or "openai")
        - analysis_mode: The analysis mode used

    Examples:
        understand_audio(["recording.wav"])
        → Rich analysis with tone, emotion, pacing (default)

        understand_audio(["recording.wav"], analysis_mode="transcription")
        → Fast text-only transcription via Whisper

        understand_audio(["interview.mp3"], prompt="Summarize the key points")
        → Rich analysis focused on key points

    Security:
        - Requires valid API key for the chosen backend
        - All input audio files must exist and be readable
    """
    try:
        # Convert allowed_paths from strings to Path objects
        allowed_paths_list = [Path(p) for p in allowed_paths] if allowed_paths else None

        # Load environment variables
        script_dir = Path(__file__).parent.parent.parent.parent
        env_path = script_dir / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()

        # Use backend selector to choose the best available backend
        # This prioritizes the caller's backend if specified, then falls through priority list
        backend_config = get_backend(
            media_type="audio",
            preferred_backend=backend_type,
            preferred_model=model,
        )

        if not backend_config:
            result = {
                "success": False,
                "operation": "understand_audio",
                "error": "No audio backend available. Please set GOOGLE_API_KEY/GEMINI_API_KEY or OPENAI_API_KEY.",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        selected_backend = backend_config.name
        selected_model = backend_config.model

        logger.info(
            f"[understand_audio] Selected backend: {selected_backend}/{selected_model} " f"(preferred: {backend_type})",
        )

        # Validate and process input audio files
        validated_audio_paths = []
        audio_extensions = [".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac", ".aac", ".wma", ".opus"]

        for audio_path_str in audio_paths:
            # Resolve audio path
            base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()

            if Path(audio_path_str).is_absolute():
                audio_path = Path(audio_path_str).resolve()
            else:
                audio_path = (base_dir / audio_path_str).resolve()

            # Validate audio path
            _validate_path_access(audio_path, allowed_paths_list)

            if not audio_path.exists():
                result = {
                    "success": False,
                    "operation": "understand_audio",
                    "error": f"Audio file does not exist: {audio_path}",
                }
                return ExecutionResult(
                    output_blocks=[TextContent(data=json.dumps(result, indent=2))],
                )

            # Check if file is an audio file
            if audio_path.suffix.lower() not in audio_extensions:
                result = {
                    "success": False,
                    "operation": "understand_audio",
                    "error": f"File does not appear to be an audio file: {audio_path}",
                }
                return ExecutionResult(
                    output_blocks=[TextContent(data=json.dumps(result, indent=2))],
                )

            # Check file size (25MB limit for most APIs)
            file_size = audio_path.stat().st_size
            max_size = 25 * 1024 * 1024  # 25MB
            if file_size > max_size:
                result = {
                    "success": False,
                    "operation": "understand_audio",
                    "error": (f"Audio file too large: {audio_path} ({file_size/1024/1024:.1f}MB > 25MB). " "Please use a smaller file or compress the audio."),
                }
                return ExecutionResult(
                    output_blocks=[TextContent(data=json.dumps(result, indent=2))],
                )

            validated_audio_paths.append(audio_path)

        # Determine effective analysis mode and model
        use_rich = analysis_mode == "rich"

        # For OpenAI rich mode, override to native audio model unless user
        # specified a model explicitly.
        if selected_backend == "openai" and use_rich and not model:
            selected_model = "gpt-4o-audio-preview"

        # Process each audio file with the selected backend
        transcriptions = []

        if use_rich:
            default_prompt = prompt or (
                "Analyze this audio comprehensively. Include: "
                "1) Full transcription of speech, "
                "2) Speaker characteristics (tone, emotion, energy, pacing), "
                "3) Notable emphasis or inflection patterns, "
                "4) Background sounds or music if present, "
                "5) Overall mood and atmosphere."
            )
        else:
            default_prompt = prompt or ("Transcribe this audio file. Include speaker " "identification if multiple speakers are present.")

        # Inject task context into prompt if available
        from massgen.context.task_context import format_prompt_with_context

        augmented_prompt = format_prompt_with_context(default_prompt, task_context)

        for audio_path in validated_audio_paths:
            try:
                if selected_backend == "gemini":
                    transcription = await _process_with_gemini(
                        audio_path=audio_path,
                        prompt=augmented_prompt,
                        model=selected_model,
                    )
                elif selected_backend == "openai" and use_rich:
                    transcription = await _process_with_openai_native(
                        audio_path=audio_path,
                        prompt=augmented_prompt,
                        model=selected_model,
                    )
                else:  # openai transcription mode
                    transcription = await _process_with_openai(
                        audio_path=audio_path,
                        prompt=augmented_prompt,
                        model=selected_model,
                    )

                transcriptions.append(
                    {
                        "file": str(audio_path),
                        "transcription": transcription,
                    },
                )

            except Exception as api_error:
                # If rich mode fails, try falling back to transcription
                if use_rich and selected_backend == "openai":
                    logger.warning(
                        "Native audio analysis failed (%s), " "falling back to Whisper transcription.",
                        api_error,
                    )
                    try:
                        transcription = await _process_with_openai(
                            audio_path=audio_path,
                            prompt=augmented_prompt,
                            model="gpt-4o-transcribe",
                        )
                        transcriptions.append(
                            {
                                "file": str(audio_path),
                                "transcription": transcription,
                                "fallback": True,
                            },
                        )
                        continue
                    except Exception:
                        pass  # Fall through to error below

                result = {
                    "success": False,
                    "operation": "understand_audio",
                    "error": f"Audio processing error for {audio_path}: {str(api_error)}",
                }
                return ExecutionResult(
                    output_blocks=[TextContent(data=json.dumps(result, indent=2))],
                )

        result = {
            "success": True,
            "operation": "understand_audio",
            "transcriptions": transcriptions,
            "audio_files": [str(p) for p in validated_audio_paths],
            "model": selected_model,
            "backend": selected_backend,
            "analysis_mode": analysis_mode,
        }
        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(result, indent=2))],
        )

    except Exception as e:
        result = {
            "success": False,
            "operation": "understand_audio",
            "error": f"Failed to process audio: {str(e)}",
        }
        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(result, indent=2))],
        )
