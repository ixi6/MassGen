"""
Generate image using OpenAI's response with gpt-5.4 WITHOUT ANY INPUT IMAGES and store it in the workspace.

This module is an alias for the unified generate_media tool.
For new code, prefer using generate_media(prompt, mode="image") directly.
"""

from massgen.tool._result import ExecutionResult

from .generation import generate_media


async def text_to_image_generation(
    prompt: str,
    model: str = "gpt-5.4",
    storage_path: str | None = None,
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
) -> ExecutionResult:
    """
    Generate image using OpenAI's response with gpt-5.4 **WITHOUT ANY INPUT IMAGES** and store it in the workspace.

    This is an alias for generate_media(mode="image", backend="openai").
    For new code, prefer using generate_media directly.

    Args:
        prompt: Text description of the image to generate
        model: Model to use for generation (default: "gpt-5.4")
               Options: "gpt-5.4"
        storage_path: Directory path where to save the image (optional)
                     - **IMPORTANT**: Must be a DIRECTORY path only, NOT a file path (e.g., "images/generated" NOT "images/cat.png")
                     - The filename is automatically generated from the prompt
                     - Relative path: Resolved relative to agent's workspace (e.g., "images/generated")
                     - Absolute path: Must be within allowed directories
                     - None/empty: Saves to agent's workspace root
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Agent's current working directory (automatically injected)

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "generate_media"
        - mode: "image"
        - file_path: Path to the generated image
        - backend: "openai"
        - model: Model used for generation
        - file_size: Size of generated file

    Examples:
        text_to_image_generation("a cat in space")
        → Generates and saves to: 20240115_143022_a_cat_in_space.png

        text_to_image_generation("sunset over mountains", storage_path="art/landscapes")
        → Generates and saves to: art/landscapes/20240115_143022_sunset_over_mountains.png

    Security:
        - Requires valid OpenAI API key (automatically detected from .env or environment)
        - Files are saved to specified path within workspace
        - Path must be within allowed directories

    Note:
        This function is an alias for the unified generate_media tool.
        For new implementations, prefer using:
            generate_media(prompt, mode="image", backend="openai")
    """
    return await generate_media(
        prompt=prompt,
        mode="image",
        storage_path=storage_path,
        backend="openai",
        model=model,
        allowed_paths=allowed_paths,
        agent_cwd=agent_cwd,
    )
