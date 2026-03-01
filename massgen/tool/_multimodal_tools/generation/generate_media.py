"""
Unified media generation tool.

This is the main entry point for all media generation in MassGen.
It automatically selects the best available backend based on:
1. Explicit `backend_type` parameter
2. `multimodal_config` overrides
3. Available API keys and priority order

Supports batch mode for parallel generation of multiple media items.
"""

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from massgen.logger_config import logger
from massgen.tool._decorators import context_params
from massgen.tool._multimodal_tools.generation._audio import generate_audio
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    MediaType,
    get_default_model,
    has_api_key,
)
from massgen.tool._multimodal_tools.generation._image import generate_image
from massgen.tool._multimodal_tools.generation._selector import (
    get_available_backends_hint,
    select_backend_and_model,
)
from massgen.tool._multimodal_tools.generation._video import generate_video
from massgen.tool._result import ExecutionResult, TextContent


def _validate_path_access(path: Path, allowed_paths: list[Path] | None = None) -> None:
    """Validate that a path is within allowed directories.

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


_ALLOWED_INPUT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_MAX_INPUT_IMAGE_SIZE_BYTES = 4 * 1024 * 1024  # 4MB limit for Requests API


def _prepare_input_images(
    image_paths: list[str],
    base_dir: Path,
    allowed_paths: list[Path] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Validate and load input images for image-to-image generation.

    Returns a tuple of (content blocks, resolved_paths).
    """

    content_blocks: list[dict[str, str]] = []
    resolved_paths: list[str] = []

    for image_path_str in image_paths:
        if Path(image_path_str).is_absolute():
            resolved_path = Path(image_path_str).resolve()
        else:
            resolved_path = (base_dir / image_path_str).resolve()

        _validate_path_access(resolved_path, allowed_paths)

        if not resolved_path.exists():
            raise ValueError(f"Input image does not exist: {resolved_path}")

        if resolved_path.suffix.lower() not in _ALLOWED_INPUT_IMAGE_SUFFIXES:
            allowed = ", ".join(sorted(_ALLOWED_INPUT_IMAGE_SUFFIXES))
            raise ValueError(f"Input image must be one of [{allowed}]: {resolved_path}")

        file_size = resolved_path.stat().st_size
        if file_size > _MAX_INPUT_IMAGE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"Input image too large ({size_mb:.2f}MB). Maximum is {_MAX_INPUT_IMAGE_SIZE_BYTES / (1024 * 1024):.0f}MB: {resolved_path}",
            )

        image_bytes = resolved_path.read_bytes()
        mime_type = "image/jpeg" if resolved_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        content_blocks.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{image_base64}",
            },
        )
        resolved_paths.append(str(resolved_path))

    return content_blocks, resolved_paths


def _clean_for_filename(text: str, max_length: int = 30) -> str:
    """Clean text for use in filename.

    Args:
        text: Text to clean
        max_length: Maximum length of cleaned text

    Returns:
        Cleaned text suitable for filenames
    """
    clean = "".join(c for c in text[:max_length] if c.isalnum() or c in (" ", "-", "_")).strip()
    return clean.replace(" ", "_")


def _get_extension(media_type: MediaType, audio_format: str | None = None) -> str:
    """Get file extension for media type.

    Args:
        media_type: Type of media
        audio_format: For audio, the specific format

    Returns:
        File extension without dot
    """
    if media_type == MediaType.IMAGE:
        return "png"
    elif media_type == MediaType.VIDEO:
        return "mp4"
    elif media_type == MediaType.AUDIO:
        return audio_format or "mp3"
    return "bin"


async def _generate_single_with_input_images(
    prompt: str,
    input_images: list[str],
    output_dir: Path,
    base_dir: Path,
    allowed_paths_list: list[Path] | None,
    selected_backend: str,
    selected_model: str | None,
    media_type: MediaType,
    mode: str,
    quality: str | None,
    duration: int | None,
    voice: str | None,
    aspect_ratio: str | None,
    size: str | None,
    continue_from: str | None,
    extra_params: dict[str, Any] | None,
    instructions: str | None,
    timestamp: str,
    ext: str,
    task_context: str | None = None,
) -> ExecutionResult:
    """Handle single image generation with input images (image-to-image).

    This is separated because image-to-image requires special handling of
    input image validation and loading, and only works with OpenAI backend.
    """
    try:
        backend_forced = False

        if selected_backend not in ("openai", "google", "grok"):
            # Try Google first (Gemini supports editing), then OpenAI, then Grok
            if has_api_key("google"):
                backend_forced = True
                selected_backend = "google"
            elif has_api_key("openai"):
                backend_forced = True
                selected_backend = "openai"
            elif has_api_key("grok"):
                backend_forced = True
                selected_backend = "grok"
            else:
                return _error_result(
                    "Image editing requires the OpenAI, Google, or Grok backend. " "Please set OPENAI_API_KEY, GOOGLE_API_KEY, or XAI_API_KEY " "to enable image-to-image generation.",
                )

        input_image_content, input_image_paths = _prepare_input_images(
            input_images,
            base_dir,
            allowed_paths_list,
        )

        if backend_forced:
            selected_model = get_default_model(selected_backend, media_type)
        elif selected_backend in ("openai", "google"):
            selected_model = selected_model or get_default_model(selected_backend, media_type)

        # Generate filename
        clean_prompt = _clean_for_filename(prompt)
        filename = f"{timestamp}_{clean_prompt}.{ext}"
        output_path = output_dir / filename

        # Inject task context into prompt for generation
        from massgen.context.task_context import format_prompt_with_context

        augmented_prompt = format_prompt_with_context(prompt, task_context)

        # Build config
        config = GenerationConfig(
            prompt=augmented_prompt,
            output_path=output_path,
            media_type=media_type,
            backend=selected_backend,
            model=selected_model,
            quality=quality,
            duration=duration,
            voice=voice,
            aspect_ratio=aspect_ratio,
            size=size,
            extra_params=extra_params or {},
            input_images=input_image_content,
            input_image_paths=input_image_paths,
            continue_from=continue_from,
        )

        # Execute generation based on media type
        if media_type == MediaType.VIDEO:
            result = await generate_video(config)
        else:
            result = await generate_image(config)

        # Return result
        if result.success:
            metadata = dict(result.metadata or {})
            if input_image_paths:
                metadata["input_image_paths"] = input_image_paths

            response_data = {
                "success": True,
                "operation": "generate_media",
                "mode": mode,
                "file_path": str(result.output_path),
                "filename": result.output_path.name if result.output_path else None,
                "backend": result.backend_name,
                "model": result.model_used,
                "file_size": result.file_size_bytes,
                "duration_seconds": result.duration_seconds,
                "metadata": metadata,
            }
            if metadata.get("continuation_id"):
                response_data["continuation_id"] = metadata["continuation_id"]

            return ExecutionResult(
                output_blocks=[
                    TextContent(
                        data=json.dumps(response_data, indent=2),
                    ),
                ],
            )
        else:
            return _error_result(result.error or "Generation failed")

    except ValueError as e:
        return _error_result(str(e))
    except Exception as e:
        logger.exception(f"generate_media with input_images failed: {e}")
        return _error_result(f"Generation error: {str(e)}")


@context_params("agent_cwd", "allowed_paths", "multimodal_config", "task_context")
async def generate_media(
    prompt: str | None = None,
    mode: Literal["image", "video", "audio"] = "image",
    prompts: list[str] | None = None,
    input_images: list[str] | None = None,
    storage_path: str | None = None,
    backend_type: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    duration: int | None = None,
    voice: str | None = None,
    aspect_ratio: str | None = None,
    size: str | None = None,
    continue_from: str | None = None,
    audio_format: str | None = None,
    audio_type: Literal["speech", "music", "sound_effect", "voice_conversion", "audio_isolation", "voice_design", "voice_clone", "dubbing"] = "speech",
    input_audio: str | None = None,
    voice_samples: list[str] | None = None,
    mask_path: str | None = None,
    target_language: str | None = None,
    source_language: str | None = None,
    speed: float | None = None,
    voice_stability: float | None = None,
    voice_similarity: float | None = None,
    style_image: str | None = None,
    control_image: str | None = None,
    subject_image: str | None = None,
    output_format: str | None = None,
    background: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
    guidance_scale: float | None = None,
    video_reference_images: list[str] | None = None,
    instructions: str | None = None,
    extra_params: dict[str, Any] | None = None,
    max_concurrent: int = 4,
    agent_cwd: str | None = None,
    allowed_paths: list[str] | None = None,
    multimodal_config: dict[str, Any] | None = None,
    task_context: str | None = None,
    use_context: bool = False,
) -> ExecutionResult:
    """
    Generate media (image, video, or audio) from text prompt(s).

    This is the unified entry point for all media generation in MassGen.
    It automatically selects the best available backend based on:
    1. Explicit `backend_type` parameter
    2. `multimodal_config` overrides
    3. Available API keys and priority order

    Supports batch mode: provide `prompts` (list) instead of `prompt` (string)
    to generate multiple media items in parallel.

    Args:
        prompt: Text description of what to generate (single item mode).
                For audio/speech: the literal text to speak (NOT instructions
                about how to speak — use `instructions` for tone/style).
        mode: Type of media to generate - "image", "video", or "audio"
        prompts: List of text descriptions for batch generation (parallel mode).
                 Use this instead of `prompt` to generate multiple items at once.
        input_images: Optional list of image paths for image-to-image (OpenAI or Google, single mode)
        storage_path: Directory to save generated media (optional)
                     - Relative paths resolved from agent workspace
                     - Absolute paths must be in allowed directories
                     - Defaults to agent workspace root
        backend_type: Preferred backend ("openai", "google", "grok", "openrouter", "elevenlabs", or "auto")
                      Falls back to others if unavailable
        model: Override the default model for the selected backend
        quality: Quality setting ("standard", "hd") - backend-specific
        duration: For video/audio: length in seconds
        voice: For audio: voice name or ID. OpenAI voices: "alloy", "echo",
                "nova", "shimmer". ElevenLabs voices: "Rachel", "Sarah",
                "Josh", etc. (names are auto-resolved to UUIDs).
        aspect_ratio: For image/video: aspect ratio (e.g., "16:9", "1:1")
        size: Image dimensions. OpenAI: "1024x1024", "1024x1536", "1536x1024".
              Gemini: "512px", "1K", "2K", "4K".
        continue_from: Continuation ID from a previous generate_media result.
                       Enables multi-turn editing. Pass the ``continuation_id``
                       from the previous result's metadata. Works for image
                       (Google Gemini, OpenAI, Grok) and video (Sora remix,
                       Veo extension, Grok re-edit). Not valid for batch mode.
        audio_format: For audio: output format (mp3, wav, opus, etc.)
        audio_type: For audio: type of audio to generate - "speech" (default),
                    "music" (ElevenLabs only), "sound_effect" (ElevenLabs only),
                    "voice_conversion" (ElevenLabs, requires input_audio),
                    "audio_isolation" (ElevenLabs, requires input_audio),
                    "voice_design" (ElevenLabs, prompt describes voice),
                    "voice_clone" (ElevenLabs, requires voice_samples),
                    or "dubbing" (ElevenLabs, requires input_audio + target_language)
        input_audio: Path to input audio file for voice conversion or audio
                     isolation. Resolved relative to agent workspace.
        voice_samples: List of audio file paths for voice cloning. Each path
                       resolved relative to agent workspace.
        mask_path: Path to mask image (PNG) for inpainting. Transparent regions
                   indicate where to generate new content. OpenAI only.
        target_language: Target language code for dubbing (e.g., "es", "fr").
        source_language: Source language code for dubbing (optional, auto-detected).
        speed: For audio: playback speed multiplier (OpenAI: 0.25-4.0).
        voice_stability: For audio: ElevenLabs voice stability (0.0-1.0).
        voice_similarity: For audio: ElevenLabs similarity boost (0.0-1.0).
        style_image: Path to style reference image for Google Imagen editing.
        control_image: Path to structural control image for Google Imagen editing.
        subject_image: Path to subject reference for Google Imagen consistency.
        output_format: Override output format ("png", "jpeg", "webp").
        background: Background handling for OpenAI ("transparent", "opaque", "auto").
        negative_prompt: What to exclude from generation (Google Imagen only).
        seed: Reproducibility seed for deterministic output (Google Imagen, ElevenLabs).
        guidance_scale: Prompt adherence strength (Google Imagen only).
        video_reference_images: List of image paths (up to 3) for style/content
                                guidance in Google Veo video generation. Distinct
                                from `input_images` (which sets the first frame).
        instructions: For audio: speaking style/tone guidance (e.g., "warm,
                      reflective tone"). Only supported by OpenAI gpt-4o-mini-tts.
                      Do NOT put style instructions in `prompt` — TTS will
                      speak the prompt text literally.
        extra_params: Backend-specific parameters
        max_concurrent: Maximum concurrent generations for batch mode (default: 4)
        agent_cwd: Agent's working directory (auto-injected)
        allowed_paths: Allowed directories for output (auto-injected)
        multimodal_config: Per-modality backend/model overrides (auto-injected)

    Returns:
        ExecutionResult with generated file info or error.
        For batch mode, returns results array with per-item status.

    Examples:
        # Generate a single image
        generate_media(prompt="a cat in space", mode="image")

        # Generate multiple images in parallel (batch mode)
        generate_media(
            prompts=["a cat in space", "a dog on the moon", "a bird in a forest"],
            mode="image",
            max_concurrent=3
        )

        # Generate video with Google Veo
        generate_media(
            prompt="A robot walking through a city",
            mode="video",
            backend_type="google",
            duration=8
        )

        # Generate audio with specific voice
        generate_media(
            prompt="Hello world!",
            mode="audio",
            voice="nova"
        )

    Supported Backends:
        Image: google (Nano Banana 2 / Gemini + Imagen), openai (GPT-5.2), grok (Grok Imagine), openrouter
        Video: grok (Grok Imagine Video), google (Veo), openai (Sora-2)
        Audio (speech): elevenlabs (eleven_multilingual_v2), openai (gpt-4o-mini-tts)
        Audio (music): elevenlabs only
        Audio (sound_effect): elevenlabs only
    """
    try:
        # Parse mode to MediaType
        try:
            media_type = MediaType(mode)
        except ValueError:
            return _error_result(
                f"Invalid mode '{mode}'. Must be 'image', 'video', or 'audio'",
            )

        # Load task_context dynamically from CONTEXT.md (it may be created during execution)
        # This allows agents to create CONTEXT.md after the backend starts streaming
        from massgen.context.task_context import load_task_context_with_warning

        context_warning = None
        if use_context:
            task_context, context_warning = load_task_context_with_warning(agent_cwd, task_context)

            # For external generation APIs, context is mandatory for image/video but optional for pure TTS.
            if not task_context and media_type != MediaType.AUDIO:
                return _error_result(
                    "CONTEXT.md not found in workspace. "
                    "Before using generate_media, create a CONTEXT.md file with task context. "
                    "This helps external APIs understand what you're working on. "
                    "See system prompt for instructions and examples.",
                )
        else:
            task_context = None

        # Validate prompt/prompts - exactly one must be provided
        if prompt and prompts:
            return _error_result("Provide either 'prompt' or 'prompts', not both")
        if not prompt and not prompts:
            return _error_result("Must provide either 'prompt' or 'prompts'")

        # Normalize to list for unified processing
        prompt_list = prompts if prompts else [prompt]
        is_batch = len(prompt_list) > 1

        # Validate continue_from constraints
        if continue_from and (is_batch or media_type == MediaType.AUDIO):
            return _error_result(
                "continue_from is only supported for single image or video generation",
            )

        base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()
        allowed_paths_list = [Path(p) for p in allowed_paths] if allowed_paths else None

        # Select backend and model (using config defaults when not specified)
        selected_backend, selected_model = select_backend_and_model(
            media_type=media_type,
            preferred_backend=backend_type,
            preferred_model=model,
            config=multimodal_config,
        )

        if not selected_backend:
            hint = get_available_backends_hint(media_type)
            return _error_result(f"No backend available for {mode} generation. {hint}")

        # Resolve output path
        if storage_path:
            if Path(storage_path).is_absolute():
                output_dir = Path(storage_path).resolve()
            else:
                output_dir = (base_dir / storage_path).resolve()
        else:
            output_dir = base_dir

        # Validate path access
        _validate_path_access(output_dir, allowed_paths_list)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Common generation parameters
        ext = _get_extension(media_type, audio_format)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # For single prompt with input_images (image-to-image), handle specially
        if not is_batch and input_images and media_type in (MediaType.IMAGE, MediaType.VIDEO):
            return await _generate_single_with_input_images(
                prompt=prompt_list[0],
                input_images=input_images,
                output_dir=output_dir,
                base_dir=base_dir,
                allowed_paths_list=allowed_paths_list,
                selected_backend=selected_backend,
                selected_model=selected_model,
                media_type=media_type,
                mode=mode,
                quality=quality,
                duration=duration,
                voice=voice,
                aspect_ratio=aspect_ratio,
                size=size,
                continue_from=continue_from,
                extra_params=extra_params,
                instructions=instructions,
                timestamp=timestamp,
                ext=ext,
                task_context=task_context,
            )

        # Import context formatting function
        from massgen.context.task_context import format_prompt_with_context

        # Define the single generation task
        async def _generate_one(idx: int, single_prompt: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
            """Generate a single media item with concurrency control."""
            async with semaphore:
                try:
                    # Generate unique filename with index for batch
                    clean_prompt = _clean_for_filename(single_prompt)
                    if is_batch:
                        filename = f"{timestamp}_{idx:02d}_{clean_prompt}.{ext}"
                    else:
                        filename = f"{timestamp}_{clean_prompt}.{ext}"
                    output_path = output_dir / filename

                    # Keep pure TTS input as spoken text; avoid prepending task context.
                    if media_type == MediaType.AUDIO:
                        augmented_prompt = single_prompt
                    else:
                        augmented_prompt = format_prompt_with_context(single_prompt, task_context)

                    # Resolve input_audio path if provided
                    resolved_input_audio = None
                    if input_audio and media_type == MediaType.AUDIO:
                        if Path(input_audio).is_absolute():
                            resolved_input_audio = Path(input_audio).resolve()
                        else:
                            resolved_input_audio = (base_dir / input_audio).resolve()
                        _validate_path_access(resolved_input_audio, allowed_paths_list)

                    # Resolve editing image paths if provided
                    def _resolve_opt_path(p: str | None) -> Path | None:
                        if not p:
                            return None
                        if Path(p).is_absolute():
                            rp = Path(p).resolve()
                        else:
                            rp = (base_dir / p).resolve()
                        _validate_path_access(rp, allowed_paths_list)
                        return rp

                    resolved_style_image = _resolve_opt_path(style_image) if media_type == MediaType.IMAGE else None
                    resolved_control_image = _resolve_opt_path(control_image) if media_type == MediaType.IMAGE else None
                    resolved_subject_image = _resolve_opt_path(subject_image) if media_type == MediaType.IMAGE else None

                    # Resolve mask_path if provided
                    resolved_mask_path = None
                    if mask_path and media_type == MediaType.IMAGE:
                        if Path(mask_path).is_absolute():
                            resolved_mask_path = Path(mask_path).resolve()
                        else:
                            resolved_mask_path = (base_dir / mask_path).resolve()
                        _validate_path_access(resolved_mask_path, allowed_paths_list)

                    # Resolve video_reference_images if provided
                    resolved_video_ref_images: list[dict[str, str]] = []
                    if video_reference_images and media_type == MediaType.VIDEO:
                        ref_content, _ = _prepare_input_images(
                            video_reference_images[:3],
                            base_dir,
                            allowed_paths_list,
                        )
                        resolved_video_ref_images = ref_content

                    # Resolve voice_samples paths if provided
                    resolved_voice_samples: list[Path] = []
                    if voice_samples and media_type == MediaType.AUDIO:
                        for vs_path in voice_samples:
                            if Path(vs_path).is_absolute():
                                resolved = Path(vs_path).resolve()
                            else:
                                resolved = (base_dir / vs_path).resolve()
                            _validate_path_access(resolved, allowed_paths_list)
                            resolved_voice_samples.append(resolved)

                    # Build config
                    config = GenerationConfig(
                        prompt=augmented_prompt,
                        output_path=output_path,
                        media_type=media_type,
                        backend=selected_backend,
                        model=selected_model,
                        quality=quality,
                        duration=duration,
                        voice=voice,
                        aspect_ratio=aspect_ratio,
                        size=size,
                        extra_params=extra_params or {},
                        input_images=[],
                        input_image_paths=[],
                        continue_from=continue_from,
                        input_audio_path=resolved_input_audio,
                        voice_samples=resolved_voice_samples,
                        mask_path=resolved_mask_path,
                        target_language=target_language,
                        source_language=source_language,
                        speed=speed,
                        voice_stability=voice_stability,
                        voice_similarity=voice_similarity,
                        style_image_path=resolved_style_image,
                        control_image_path=resolved_control_image,
                        subject_image_path=resolved_subject_image,
                        output_format=output_format,
                        background=background,
                        negative_prompt=negative_prompt,
                        seed=seed,
                        guidance_scale=guidance_scale,
                        video_reference_images=resolved_video_ref_images,
                    )

                    # Add audio-specific params to extra_params
                    if media_type == MediaType.AUDIO:
                        config.extra_params["audio_type"] = audio_type
                        if instructions:
                            config.extra_params["instructions"] = instructions

                    # Execute generation based on media type
                    if media_type == MediaType.IMAGE:
                        result = await generate_image(config)
                    elif media_type == MediaType.VIDEO:
                        result = await generate_video(config)
                    elif media_type == MediaType.AUDIO:
                        result = await generate_audio(config)
                    else:
                        return {
                            "prompt": single_prompt,
                            "success": False,
                            "error": f"Unsupported media type: {mode}",
                        }

                    if result.success:
                        return {
                            "prompt": single_prompt,
                            "success": True,
                            "file_path": str(result.output_path),
                            "filename": result.output_path.name if result.output_path else None,
                            "backend": result.backend_name,
                            "model": result.model_used,
                            "file_size": result.file_size_bytes,
                            "duration_seconds": result.duration_seconds,
                            "metadata": dict(result.metadata or {}),
                        }
                    else:
                        return {
                            "prompt": single_prompt,
                            "success": False,
                            "error": result.error or "Generation failed",
                        }

                except Exception as e:
                    logger.exception(f"Generation failed for prompt: {single_prompt[:50]}...")
                    return {
                        "prompt": single_prompt,
                        "success": False,
                        "error": str(e),
                    }

        # Execute generation(s) with concurrency control
        semaphore = asyncio.Semaphore(max_concurrent if max_concurrent is not None else 4)
        tasks = [_generate_one(i, p, semaphore) for i, p in enumerate(prompt_list)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions to error results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    {
                        "prompt": prompt_list[i],
                        "success": False,
                        "error": str(result),
                    },
                )
            else:
                final_results.append(result)

        # Calculate success/failure counts
        succeeded = sum(1 for r in final_results if r.get("success"))
        failed = len(final_results) - succeeded

        # Return appropriate format based on batch vs single
        if is_batch:
            response_data = {
                "success": succeeded > 0,
                "operation": "generate_media",
                "mode": mode,
                "batch": True,
                "total": len(final_results),
                "succeeded": succeeded,
                "failed": failed,
                "results": final_results,
            }
            if context_warning:
                response_data["warning"] = context_warning
            return ExecutionResult(
                output_blocks=[
                    TextContent(
                        data=json.dumps(response_data, indent=2),
                    ),
                ],
            )
        else:
            # Single prompt - return original format for backwards compatibility
            result = final_results[0]
            if result.get("success"):
                metadata = result.get("metadata", {})
                response_data = {
                    "success": True,
                    "operation": "generate_media",
                    "mode": mode,
                    "file_path": result.get("file_path"),
                    "filename": result.get("filename"),
                    "backend": result.get("backend"),
                    "model": result.get("model"),
                    "file_size": result.get("file_size"),
                    "duration_seconds": result.get("duration_seconds"),
                    "metadata": metadata,
                }
                if metadata.get("continuation_id"):
                    response_data["continuation_id"] = metadata["continuation_id"]
                if context_warning:
                    response_data["warning"] = context_warning
                return ExecutionResult(
                    output_blocks=[
                        TextContent(
                            data=json.dumps(response_data, indent=2),
                        ),
                    ],
                )
            else:
                return _error_result(result.get("error", "Generation failed"))

    except ValueError as e:
        return _error_result(str(e))
    except Exception as e:
        logger.exception(f"generate_media failed: {e}")
        return _error_result(f"Generation error: {str(e)}")


def _error_result(error: str) -> ExecutionResult:
    """Create an error ExecutionResult.

    Args:
        error: Error message

    Returns:
        ExecutionResult with error info
    """
    return ExecutionResult(
        output_blocks=[
            TextContent(
                data=json.dumps(
                    {
                        "success": False,
                        "operation": "generate_media",
                        "error": error,
                    },
                    indent=2,
                ),
            ),
        ],
    )
