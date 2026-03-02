"""
Understand and analyze videos using the best available backend.

Supports multiple backends with automatic selection:
- Gemini: Uses native video understanding with inline_data (preferred)
- OpenAI: Uses key frame extraction with vision API

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

from massgen.backend.capabilities import has_capability
from massgen.context.task_context import format_prompt_with_context
from massgen.logger_config import logger
from massgen.tool._multimodal_tools.backend_selector import BackendConfig, get_backend
from massgen.tool._multimodal_tools.video_extraction import (
    VideoExtractionConfig,
    extract_frames,
)
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


def _extract_key_frames(video_path: Path, num_frames: int = 8) -> list[str]:
    """Extract key frames from a video file (deprecated, use extract_frames instead).

    Kept for backward compatibility with any external callers.
    Delegates to the new extraction module with uniform mode.
    """
    config = VideoExtractionConfig.from_video_config(
        {"extraction_mode": "uniform", "num_frames": num_frames},
    )
    return extract_frames(video_path, config)


def _get_mime_type(file_path: Path) -> str:
    """Get MIME type for a video file."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        return mime_type
    # Fallback
    ext = file_path.suffix.lower()
    fallbacks = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".m4v": "video/mp4",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
    }
    return fallbacks.get(ext, "video/mp4")


async def _process_with_gemini(
    video_path: Path,
    prompt: str,
    model: str = "gemini-3.1-pro-preview",
    system_prompt: str | None = None,
) -> str:
    """
    Process video using Gemini's native video understanding.

    Args:
        video_path: Path to the video file
        prompt: Prompt for analysis (string or dict with 'question' key)
        model: Gemini model to use
        system_prompt: Optional system instruction for critical framing

    Returns:
        Text analysis from Gemini
    """
    from google import genai
    from google.genai import types

    # Handle dict prompt (model sometimes outputs {"question": "..."})
    if isinstance(prompt, dict):
        prompt = prompt.get("question", str(prompt))

    # Read video data
    with open(video_path, "rb") as f:
        video_data = f.read()
    mime_type = _get_mime_type(video_path)

    # Create Gemini client
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    logger.info(f"[understand_video] Using Gemini {model} for video: {video_path.name}")

    # Use types.Part for proper SDK format
    contents = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=video_data, mime_type=mime_type),
    ]

    # Build config with system instruction if provided
    config = types.GenerateContentConfig(system_instruction=system_prompt) if system_prompt else None

    # Make API call
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    return response.text


async def _process_with_openai(
    prompt: str,
    frames_base64: list[str],
    model: str = "gpt-5.2",
    system_prompt: str | None = None,
) -> str:
    """
    Process video using OpenAI's vision API with pre-extracted frames.

    Args:
        prompt: Prompt for analysis
        frames_base64: Pre-extracted base64-encoded JPEG frames
        model: OpenAI model to use
        system_prompt: Optional system instruction for critical framing

    Returns:
        Text analysis from OpenAI
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key)

    logger.info(
        f"[understand_video] Using OpenAI {model} ({len(frames_base64)} frames)",
    )

    # Build content array with prompt and all frames
    content = [{"type": "input_text", "text": prompt}]

    for frame_base64 in frames_base64:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{frame_base64}",
            },
        )

    # Call OpenAI API
    kwargs: dict = {"model": model, "input": [{"role": "user", "content": content}]}
    if system_prompt:
        kwargs["instructions"] = system_prompt
    response = await client.responses.create(**kwargs)

    return response.output_text if hasattr(response, "output_text") else str(response.output)


async def _process_with_anthropic(
    prompt: str,
    frames_base64: list[str],
    model: str = "claude-sonnet-4-5",
    system_prompt: str | None = None,
) -> str:
    """
    Process video using Anthropic's Claude vision API with pre-extracted frames.

    Args:
        prompt: Prompt for analysis
        frames_base64: Pre-extracted base64-encoded JPEG frames
        model: Claude model to use
        system_prompt: Optional system instruction for critical framing

    Returns:
        Text analysis from Claude
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in environment")

    client = anthropic.Anthropic(api_key=api_key)

    logger.info(
        f"[understand_video] Using Anthropic {model} ({len(frames_base64)} frames)",
    )

    # Build content array with frames and prompt
    content = []
    for frame_base64 in frames_base64:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": frame_base64,
                },
            },
        )
    content.append({"type": "text", "text": prompt})

    # Call Claude API
    kwargs: dict = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    response = client.messages.create(**kwargs)

    return response.content[0].text


async def _process_with_grok(
    prompt: str,
    frames_base64: list[str],
    model: str = "grok-4-1-fast-reasoning",
    system_prompt: str | None = None,
) -> str:
    """
    Process video using Grok's vision API with pre-extracted frames.
    Grok uses OpenAI-compatible API.

    Args:
        prompt: Prompt for analysis
        frames_base64: Pre-extracted base64-encoded JPEG frames
        model: Grok model to use
        system_prompt: Optional system instruction for critical framing

    Returns:
        Text analysis from Grok
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    logger.info(
        f"[understand_video] Using Grok {model} ({len(frames_base64)} frames)",
    )

    # Build content array with prompt and all frames
    content = [{"type": "text", "text": prompt}]
    for frame_base64 in frames_base64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame_base64}"},
            },
        )

    # Build messages list with optional system prompt
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    # Call Grok API (OpenAI-compatible)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
    )

    return response.choices[0].message.content


async def _process_with_openrouter(
    prompt: str,
    frames_base64: list[str],
    model: str = "openai/gpt-5.2",
    system_prompt: str | None = None,
) -> str:
    """
    Process video using OpenRouter's API with pre-extracted frames.
    OpenRouter uses OpenAI-compatible API.

    Args:
        prompt: Prompt for analysis
        frames_base64: Pre-extracted base64-encoded JPEG frames
        model: Model to use (with provider prefix)
        system_prompt: Optional system instruction for critical framing

    Returns:
        Text analysis from OpenRouter
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    logger.info(
        f"[understand_video] Using OpenRouter {model} ({len(frames_base64)} frames)",
    )

    # Build content array with prompt and all frames
    content = [{"type": "text", "text": prompt}]
    for frame_base64 in frames_base64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame_base64}"},
            },
        )

    # Build messages list with optional system prompt
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    # Call OpenRouter API (OpenAI-compatible)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
    )

    return response.choices[0].message.content


async def understand_video(
    video_path: str,
    prompt: str | None = None,
    num_frames: int | None = None,
    model: str | None = None,
    backend_type: str | None = None,
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
    task_context: str | None = None,
    video_extraction_config: dict | None = None,
    system_prompt: str | None = None,
) -> ExecutionResult:
    """
    Understand and analyze a video using the best available backend.

    Backend Selection Priority:
    1. Same backend as the calling agent (if backend_type specified and has API key)
    2. Default priority list: Gemini → OpenAI (first with available API key)

    Supports multiple backends:
    - Gemini: Uses native video understanding with inline_data (preferred, no frame extraction)
    - OpenAI: Extracts key frames and uses vision API

    Args:
        video_path: Path to the video file (MP4, AVI, MOV, etc.)
                   - Relative path: Resolved relative to workspace
                   - Absolute path: Must be within allowed directories
        prompt: Question or instruction about the video (default: critical analysis prompt)
        num_frames: Number of key frames to extract (legacy, default: 8).
                   Prefer video_extraction_config for new usage.
        model: Model to use. If not specified, uses default from backend selector:
               - Gemini: "gemini-3.1-pro-preview"
               - OpenAI: "gpt-5.2"
        backend_type: Preferred backend ("gemini" or "openai"). If specified and
                      has API key, this backend is used. Otherwise falls through
                      to priority list.
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Agent's current working directory (automatically injected, optional)
        task_context: Context string or key used to augment the prompt (Optional[str])
                  - Accepts named contexts (e.g., "short_summary", "detailed_analysis")
                    or raw context text.
                  - If None (default), no context-based augmentation is applied.
        video_extraction_config: Optional dict with extraction settings from
                  multimodal_config["video"]. Keys: extraction_mode, max_frames,
                  fps, threshold, frames_per_scene, num_frames.

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "understand_video"
        - video_path: Path to the analyzed video
        - prompt: The prompt used
        - model: Model used for analysis
        - backend: Backend used ("gemini" or "openai")
        - frame_extraction_performed: Whether local frame extraction was run
        - frame_extraction_reason: Why extraction was or wasn't run
        - response: The model's understanding/description of the video

    Examples:
        understand_video("demo.mp4")
        → Returns detailed description using best available backend

        understand_video("tutorial.mp4", "What steps are shown in this tutorial?")
        → Returns analysis of tutorial steps

        understand_video("demo.mp4", backend_type="gemini")
        → Prefers Gemini if available, otherwise falls back to OpenAI

    Security:
        - Requires valid API key for the chosen backend
        - Video file must exist and be readable
        - Supports common video formats (MP4, AVI, MOV, MKV, etc.)

    Note:
        - Gemini processes the full video natively (preferred)
        - OpenAI extracts still frames; audio content is not analyzed
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

        # If agent's backend supports video and a model is specified, use it directly
        # This avoids the backend_selector fallback and keeps the agent on its own backend
        backend_config: BackendConfig | None = None
        if backend_type and model and has_capability(backend_type, "video_understanding"):
            logger.info(
                f"[understand_video] Agent backend {backend_type} has video_understanding, " f"using directly with model {model}",
            )
            selected_backend = backend_type
            selected_model = model
        else:
            # Use backend selector to choose the best available backend
            backend_config = get_backend(
                media_type="video",
                preferred_backend=backend_type,
                preferred_model=model,
            )

            if not backend_config:
                result = {
                    "success": False,
                    "operation": "understand_video",
                    "error": "No video backend available. " "Please set GOOGLE_API_KEY/GEMINI_API_KEY or OPENAI_API_KEY.",
                }
                return ExecutionResult(
                    output_blocks=[TextContent(data=json.dumps(result, indent=2))],
                )

            selected_backend = backend_config.name
            selected_model = backend_config.model

        logger.info(
            f"[understand_video] Selected backend: {selected_backend}/{selected_model} " f"(preferred: {backend_type})",
        )

        # Resolve video path
        base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()

        if Path(video_path).is_absolute():
            vid_path = Path(video_path).resolve()
        else:
            vid_path = (base_dir / video_path).resolve()

        # Validate video path
        _validate_path_access(vid_path, allowed_paths_list)

        if not vid_path.exists():
            result = {
                "success": False,
                "operation": "understand_video",
                "error": f"Video file does not exist: {vid_path}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        # Check if file is likely a video (by extension)
        video_extensions = [
            ".mp4",
            ".avi",
            ".mov",
            ".mkv",
            ".flv",
            ".wmv",
            ".webm",
            ".m4v",
            ".mpg",
            ".mpeg",
        ]
        if vid_path.suffix.lower() not in video_extensions:
            result = {
                "success": False,
                "operation": "understand_video",
                "error": f"File does not appear to be a video file: {vid_path}. " f"Supported formats: {', '.join(video_extensions)}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        # Apply default prompt if none provided
        if prompt is None:
            prompt = "What's happening in this video? Please describe the content, " "actions, and any important details you observe."

        # Inject task context into prompt if available
        augmented_prompt = format_prompt_with_context(prompt, task_context)

        # Build extraction config from video_extraction_config dict + legacy num_frames
        ext_config = VideoExtractionConfig.from_video_config(
            video_extraction_config,
            legacy_num_frames=num_frames,
        )

        # Extract frames once before backend dispatch (skip for Gemini — native video)
        frame_extraction_performed = selected_backend != "gemini"
        frames_base64: list[str] | None = None
        if frame_extraction_performed:
            frames_base64 = extract_frames(vid_path, ext_config)
            logger.info(
                f"[understand_video] Extracted {len(frames_base64)} frames " f"(mode={ext_config.extraction_mode.value}) for {vid_path.name}",
            )

        # Process video with the selected backend
        try:
            if selected_backend == "gemini":
                response_text = await _process_with_gemini(
                    video_path=vid_path,
                    prompt=augmented_prompt,
                    model=selected_model,
                    system_prompt=system_prompt,
                )
            elif selected_backend == "claude":
                response_text = await _process_with_anthropic(
                    prompt=augmented_prompt,
                    frames_base64=frames_base64,
                    model=selected_model,
                    system_prompt=system_prompt,
                )
            elif selected_backend == "grok":
                response_text = await _process_with_grok(
                    prompt=augmented_prompt,
                    frames_base64=frames_base64,
                    model=selected_model,
                    system_prompt=system_prompt,
                )
            elif selected_backend == "openrouter":
                response_text = await _process_with_openrouter(
                    prompt=augmented_prompt,
                    frames_base64=frames_base64,
                    model=selected_model,
                    system_prompt=system_prompt,
                )
            else:  # openai (default)
                response_text = await _process_with_openai(
                    prompt=augmented_prompt,
                    frames_base64=frames_base64,
                    model=selected_model,
                    system_prompt=system_prompt,
                )

            result = {
                "success": True,
                "operation": "understand_video",
                "video_path": str(vid_path),
                "prompt": prompt,
                "model": selected_model,
                "backend": selected_backend,
                "extraction_mode": ext_config.extraction_mode.value,
                "frames_extracted": len(frames_base64) if frames_base64 else 0,
                "frame_extraction_performed": frame_extraction_performed,
                "frame_extraction_reason": "frame_sampling" if frame_extraction_performed else "native_backend",
                "response": response_text,
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        except ImportError as import_error:
            result = {
                "success": False,
                "operation": "understand_video",
                "error": str(import_error),
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )
        except Exception as api_error:
            result = {
                "success": False,
                "operation": "understand_video",
                "error": f"Video processing error: {str(api_error)}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

    except Exception as e:
        result = {
            "success": False,
            "operation": "understand_video",
            "error": f"Failed to understand video: {str(e)}",
        }
        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(result, indent=2))],
        )
