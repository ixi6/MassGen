"""
Video generation backends: OpenAI Sora, Google Veo, Grok (xAI).

This module contains all video generation implementations that are
routed through by generate_media when mode="video".
"""

import asyncio
import time
from datetime import timedelta
from typing import Any

import requests
import xai_sdk
from openai import AsyncOpenAI

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_api_key,
    get_default_model,
)


async def generate_video(config: GenerationConfig) -> GenerationResult:
    """Generate a video using the selected backend.

    Routes to the appropriate backend based on config.backend.

    Args:
        config: GenerationConfig with prompt, output_path, backend, duration, etc.

    Returns:
        GenerationResult with success status and file info
    """
    backend = config.backend or "openai"  # Default if not specified

    if backend == "google":
        return await _generate_video_google(config)
    elif backend == "grok":
        return await _generate_video_grok(config)
    else:  # openai (default)
        return await _generate_video_openai(config)


async def _generate_video_openai(config: GenerationConfig) -> GenerationResult:
    """Generate video using OpenAI's Sora-2 API.

    Uses polling to wait for video generation completion.

    Args:
        config: GenerationConfig with prompt, output path, and duration

    Returns:
        GenerationResult with generated video info
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
        model = config.model or get_default_model("openai", MediaType.VIDEO)

        # OpenAI Sora API only allows 4, 8, or 12 seconds
        SORA_VALID_DURATIONS = [4, 8, 12]
        requested_duration = config.duration or 4
        # Find the closest valid duration
        duration = min(SORA_VALID_DURATIONS, key=lambda x: abs(x - requested_duration))

        if requested_duration not in SORA_VALID_DURATIONS:
            logger.warning(
                f"OpenAI Sora duration adjusted from {requested_duration}s to {duration}s " f"(valid values: {SORA_VALID_DURATIONS})",
            )

        start_time = time.time()

        # Start video generation
        video = await client.videos.create(
            model=model,
            prompt=config.prompt,
            seconds=str(duration),
        )

        # Poll for completion (silently, no stdout writes)
        while video.status in ("in_progress", "queued"):
            video = await client.videos.retrieve(video.id)
            await asyncio.sleep(2)

        if video.status == "failed":
            error_message = getattr(
                getattr(video, "error", None),
                "message",
                "Video generation failed",
            )
            return GenerationResult(
                success=False,
                backend_name="openai",
                model_used=model,
                error=error_message,
            )

        # Download video content
        content = await client.videos.download_content(video.id, variant="video")
        content.write_to_file(str(config.output_path))

        # Get file info
        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="openai",
            model_used=model,
            file_size_bytes=file_size,
            duration_seconds=duration,
            metadata={
                "generation_time": generation_time,
                "video_id": video.id,
            },
        )

    except Exception as e:
        logger.exception(f"OpenAI video generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI API error: {str(e)}",
        )


async def _generate_video_google(config: GenerationConfig) -> GenerationResult:
    """Generate video using Google Veo API.

    Uses polling to wait for video generation completion.

    Args:
        config: GenerationConfig with prompt, output path, and duration

    Returns:
        GenerationResult with generated video info
    """
    api_key = get_api_key("google")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="google",
            error="Google API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.",
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model = config.model or get_default_model("google", MediaType.VIDEO)

        # Google Veo supports 4-8 seconds duration
        VEO_MIN_DURATION = 4
        VEO_MAX_DURATION = 8
        requested_duration = config.duration or VEO_MAX_DURATION
        duration = max(VEO_MIN_DURATION, min(VEO_MAX_DURATION, requested_duration))

        if requested_duration != duration:
            logger.warning(
                f"Google Veo duration clamped from {requested_duration}s to {duration}s " f"(valid range: {VEO_MIN_DURATION}-{VEO_MAX_DURATION}s)",
            )

        start_time = time.time()

        # Prepare config
        gen_config = types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=duration,
        )

        # Add aspect ratio if specified
        if config.aspect_ratio:
            gen_config.aspect_ratio = config.aspect_ratio
        else:
            gen_config.aspect_ratio = "16:9"  # Default

        # Start video generation (async operation)
        operation = client.models.generate_videos(
            model=model,
            prompt=config.prompt,
            config=gen_config,
        )

        # Poll for completion
        poll_interval = 20  # seconds
        max_wait = 600  # 10 minutes max
        elapsed = 0

        while not operation.done:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if elapsed > max_wait:
                return GenerationResult(
                    success=False,
                    backend_name="google",
                    model_used=model,
                    error="Video generation timed out after 10 minutes",
                )
            operation = client.operations.get(operation)

        # Check for errors
        if hasattr(operation, "error") and operation.error:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error=f"Veo error: {operation.error}",
            )

        # Get generated video
        if not operation.response or not operation.response.generated_videos:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="No video generated",
            )

        # Download and save first video
        generated_video = operation.response.generated_videos[0]
        client.files.download(file=generated_video.video)
        generated_video.video.save(str(config.output_path))

        # Get file info
        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="google",
            model_used=model,
            file_size_bytes=file_size,
            duration_seconds=duration,
            metadata={
                "generation_time": generation_time,
                "total_videos": len(operation.response.generated_videos),
            },
        )

    except Exception as e:
        logger.exception(f"Google Veo generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="google",
            error=f"Google Veo error: {str(e)}",
        )


def _map_size_to_grok_video_resolution(size: str | None) -> str:
    """Map a size string to Grok video resolution parameter.

    Args:
        size: Size string from config (e.g., "480", "480p", "720p")

    Returns:
        "480p" for low-res requests, "720p" otherwise
    """
    if not size:
        return "720p"
    normalized = size.lower().strip()
    if normalized in ("480", "480p"):
        return "480p"
    return "720p"


async def _generate_video_grok(config: GenerationConfig) -> GenerationResult:
    """Generate video using xAI Grok's video API.

    Uses ``client.video.generate()`` which handles polling internally
    and returns a URL to the generated video.

    Args:
        config: GenerationConfig with prompt, output path, and duration

    Returns:
        GenerationResult with generated video info
    """
    api_key = get_api_key("grok")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="grok",
            error="xAI API key not found. Set XAI_API_KEY environment variable.",
        )

    try:
        client = xai_sdk.AsyncClient(api_key=api_key)
        model = config.model or get_default_model("grok", MediaType.VIDEO)

        # Clamp duration to 1-15 seconds
        GROK_MIN_DURATION = 1
        GROK_MAX_DURATION = 15
        requested_duration = config.duration if config.duration is not None else 5
        duration = max(GROK_MIN_DURATION, min(GROK_MAX_DURATION, requested_duration))

        if requested_duration != duration:
            logger.warning(
                f"Grok video duration clamped from {requested_duration}s to " f"{duration}s (valid range: {GROK_MIN_DURATION}-{GROK_MAX_DURATION}s)",
            )

        start_time = time.time()

        generate_kwargs: dict[str, Any] = {
            "prompt": config.prompt,
            "model": model,
            "duration": duration,
            "timeout": timedelta(minutes=10),
        }

        if config.aspect_ratio:
            generate_kwargs["aspect_ratio"] = config.aspect_ratio

        generate_kwargs["resolution"] = _map_size_to_grok_video_resolution(
            config.size,
        )

        # Handle image-to-video via input_images
        if config.input_images:
            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url:
                generate_kwargs["image_url"] = image_url

        # SDK handles polling internally
        response = await client.video.generate(**generate_kwargs)

        # Download video from URL
        video_response = requests.get(response.url, timeout=120)
        video_response.raise_for_status()
        video_bytes = video_response.content

        config.output_path.write_bytes(video_bytes)

        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="grok",
            model_used=model,
            file_size_bytes=file_size,
            duration_seconds=duration,
            metadata={
                "generation_time": generation_time,
            },
        )

    except Exception as e:
        logger.exception(f"Grok video generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="grok",
            error=f"Grok API error: {str(e)}",
        )
