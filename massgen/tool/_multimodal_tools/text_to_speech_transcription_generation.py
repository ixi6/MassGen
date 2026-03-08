"""
Convert text (transcription) directly to speech using OpenAI's TTS API with streaming response.

This module is an alias for the unified generate_media tool.
For new code, prefer using generate_media(prompt, mode="audio") directly.
"""

from massgen.tool._result import ExecutionResult

from .generation import generate_media


async def text_to_speech_transcription_generation(
    input_text: str,
    model: str = "gpt-4o-mini-tts",
    voice: str = "alloy",
    instructions: str | None = None,
    storage_path: str | None = None,
    audio_format: str = "mp3",
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
) -> ExecutionResult:
    """
    Convert text (transcription) directly to speech using OpenAI's TTS API with streaming response.

    This is an alias for generate_media(mode="audio", backend="openai").
    For new code, prefer using generate_media directly.

    Args:
        input_text: The text content to convert to speech (e.g., transcription text)
        model: TTS model to use (default: "gpt-4o-mini-tts")
               Options: "gpt-4o-mini-tts", "tts-1", "tts-1-hd"
        voice: Voice to use for speech synthesis (default: "alloy")
               Options: "alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "sage"
        instructions: Optional speaking instructions for tone and style (e.g., "Speak in a cheerful tone")
        storage_path: Directory path where to save the audio file (optional)
                     - **IMPORTANT**: Must be a DIRECTORY path only, NOT a file path (e.g., "audio/speech" NOT "audio/speech.mp3")
                     - The filename is automatically generated from the text content and timestamp
                     - Relative path: Resolved relative to agent's workspace (e.g., "audio/speech")
                     - Absolute path: Must be within allowed directories
                     - None/empty: Saves to agent's workspace root
        audio_format: Output audio format (default: "mp3")
                     Options: "mp3", "opus", "aac", "flac", "wav", "pcm"
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Agent's current working directory (automatically injected)

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "generate_media"
        - mode: "audio"
        - file_path: Path to generated audio file
        - backend: "openai"
        - model: TTS model used
        - metadata: Contains voice, format, text_length, instructions

    Examples:
        text_to_speech_transcription_generation("Hello world, this is a test.")
        → Converts text to speech and saves as MP3

        text_to_speech_transcription_generation(
            "Today is a wonderful day to build something people love!",
            voice="coral",
            instructions="Speak in a cheerful and positive tone."
        )
        → Converts with specific voice and speaking instructions

    Security:
        - Requires valid OpenAI API key
        - Files are saved to specified path within workspace
        - Path must be within allowed directories

    Note:
        This function is an alias for the unified generate_media tool.
        For new implementations, prefer using:
            generate_media(text, mode="audio", voice="alloy", instructions="...")
    """
    return await generate_media(
        prompt=input_text,
        mode="audio",
        storage_path=storage_path,
        backend="openai",
        model=model,
        voice=voice,
        instructions=instructions,
        audio_format=audio_format,
        allowed_paths=allowed_paths,
        agent_cwd=agent_cwd,
    )
