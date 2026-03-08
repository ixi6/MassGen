"""
Generate a video from a text prompt using OpenAI's Sora-2 API.

This module is an alias for the unified generate_media tool.
For new code, prefer using generate_media(prompt, mode="video") directly.
"""

from massgen.tool._result import ExecutionResult

from .generation import generate_media


async def text_to_video_generation(
    prompt: str,
    model: str = "sora-2",
    seconds: int = 4,
    storage_path: str | None = None,
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
) -> ExecutionResult:
    """
    Generate a video from a text prompt using OpenAI's Sora-2 API.

    This is an alias for generate_media(mode="video", backend="openai").
    For new code, prefer using generate_media directly.

    Args:
        prompt: Text description for the video to generate
        model: Model to use (default: "sora-2")
        seconds: Video duration in seconds (default: 4)
        storage_path: Directory path where to save the video (optional)
                     - **IMPORTANT**: Must be a DIRECTORY path only, NOT a file path (e.g., "videos/generated" NOT "videos/output.mp4")
                     - The filename is automatically generated from the prompt and timestamp
                     - Relative path: Resolved relative to agent's workspace (e.g., "videos/generated")
                     - Absolute path: Must be within allowed directories
                     - None/empty: Saves to agent's workspace root
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Agent's current working directory (automatically injected)

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "generate_media"
        - mode: "video"
        - file_path: Path to the saved video file
        - backend: "openai"
        - model: Model used for generation
        - duration_seconds: Duration of the video

    Examples:
        text_to_video_generation("A cool cat on a motorcycle in the night")
        → Generates a video and saves to workspace root

        text_to_video_generation("Dancing robot", storage_path="videos/")
        → Generates a video and saves to videos/ directory

    Security:
        - Requires valid OpenAI API key with Sora-2 access
        - Files are saved to specified path within workspace

    Note:
        This function is an alias for the unified generate_media tool.
        For new implementations, prefer using:
            generate_media(prompt, mode="video", backend="openai", duration=4)
    """
    return await generate_media(
        prompt=prompt,
        mode="video",
        storage_path=storage_path,
        backend="openai",
        model=model,
        duration=seconds,
        allowed_paths=allowed_paths,
        agent_cwd=agent_cwd,
    )
