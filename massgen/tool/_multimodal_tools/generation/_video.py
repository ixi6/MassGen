"""
Video generation backends: OpenAI Sora, Google Veo, Grok (xAI).

This module contains all video generation implementations that are
routed through by generate_media when mode="video".

Supports ``continue_from`` for iterative video work:
- **Sora**: Remix via ``videos.remix()`` — re-edits with a new prompt,
  producing a new clip inspired by the source (does NOT append time).
- **Veo**: Extension via ``video`` reference — appends ~7s segments to
  an existing video (requires 720p source, 8s duration, 16:9 or 9:16).
- **Grok**: Editing via ``video_url`` — re-renders with a new prompt,
  retaining the original duration/aspect/resolution (not extension).
"""

import asyncio
import time
import uuid
from collections import OrderedDict
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

# ---------------------------------------------------------------------------
# Video continuation stores (in-memory, LRU)
# ---------------------------------------------------------------------------


class _SoraVideoStore:
    """In-memory store for Sora video IDs used in remix/continuation."""

    def __init__(self, max_items: int = 50):
        self._store: OrderedDict[str, str] = OrderedDict()
        self._max = max_items

    def save(self, video_id: str) -> str:
        store_id = f"sora_vid_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[store_id] = video_id
        return store_id

    def get(self, store_id: str) -> str | None:
        return self._store.get(store_id)


class _VeoVideoStore:
    """In-memory store for Veo video references used in continuation."""

    def __init__(self, max_items: int = 50):
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._max = max_items

    def save(self, video_ref: Any) -> str:
        store_id = f"veo_vid_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[store_id] = video_ref
        return store_id

    def get(self, store_id: str) -> Any | None:
        return self._store.get(store_id)


class _GrokVideoStore:
    """In-memory store for Grok video URLs used in editing."""

    def __init__(self, max_items: int = 50):
        self._store: OrderedDict[str, str] = OrderedDict()
        self._max = max_items

    def save(self, video_url: str) -> str:
        store_id = f"grok_vid_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[store_id] = video_url
        return store_id

    def get(self, store_id: str) -> str | None:
        return self._store.get(store_id)


_sora_video_store = _SoraVideoStore()
_veo_video_store = _VeoVideoStore()
_grok_video_store = _GrokVideoStore()


async def generate_video(config: GenerationConfig) -> GenerationResult:
    """Generate a video using the selected backend.

    Routes to the appropriate backend based on config.backend.
    Supports continuation via ``config.continue_from`` for iterative
    video refinement (remix, extend).

    Args:
        config: GenerationConfig with prompt, output_path, backend, duration, etc.

    Returns:
        GenerationResult with success status and file info
    """
    backend = config.backend or "openai"  # Default if not specified

    # Route continuation to the correct backend based on store ID prefix
    if config.continue_from:
        if config.continue_from.startswith("sora_vid_"):
            return await _remix_video_openai(config)
        elif config.continue_from.startswith("grok_vid_"):
            return await _edit_video_grok(config)
        elif config.continue_from.startswith("veo_vid_"):
            return await _continue_video_google(config)
        else:
            return GenerationResult(
                success=False,
                backend_name=backend,
                error=(f"Unknown continuation_id format: '{config.continue_from}'. " "Expected a continuation_id from a previous video generation."),
            )

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

        # Build create kwargs
        create_kwargs: dict[str, Any] = {
            "model": model,
            "prompt": config.prompt,
            "seconds": str(duration),
        }

        # Image-to-video: pass first input image as input_reference.
        # Sora requires the input image dimensions to match the video size
        # exactly, so we resize the image to the target dimensions.
        if config.input_images:
            # Determine target video size from aspect ratio
            _SORA_SIZE_MAP = {
                "16:9": "1280x720",
                "9:16": "720x1280",
            }
            if "size" not in create_kwargs:
                create_kwargs["size"] = _SORA_SIZE_MAP.get(
                    config.aspect_ratio,
                    "1280x720",
                )
            target_w, target_h = (int(d) for d in create_kwargs["size"].split("x"))

            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url:
                if image_url.startswith("data:"):
                    import base64 as b64
                    from io import BytesIO

                    from PIL import Image

                    header, b64_data = image_url.split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    image_bytes = b64.b64decode(b64_data)

                    # Resize to match video dimensions
                    img = Image.open(BytesIO(image_bytes))
                    if img.size != (target_w, target_h):
                        img = img.resize(
                            (target_w, target_h),
                            Image.LANCZOS,
                        )
                    fmt = "JPEG" if "jpeg" in mime or "jpg" in mime else "PNG"
                    buf = BytesIO()
                    img.save(buf, format=fmt)
                    image_bytes = buf.getvalue()

                    ext = "jpg" if "jpeg" in mime else "png"
                    create_kwargs["input_reference"] = (
                        f"input.{ext}",
                        image_bytes,
                        mime,
                    )
                else:
                    create_kwargs["input_reference"] = image_url

        # Start video generation
        video = await client.videos.create(**create_kwargs)

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

        # Store video ID for continuation/remix
        store_id = _sora_video_store.save(video.id)

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
                "continuation_id": store_id,
                "image_to_video": bool(config.input_images),
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

        # Map size to Veo resolution (720p, 1080p, 4k)
        if config.size and config.size.lower() in ("720p", "1080p", "4k"):
            resolution = config.size.lower()
            gen_config.resolution = resolution
            # 1080p and 4k require 8s duration
            if resolution in ("1080p", "4k") and duration < 8:
                logger.warning(
                    f"Veo resolution '{resolution}' requires 8s duration. " f"Overriding from {duration}s to 8s.",
                )
                duration = 8
                gen_config.duration_seconds = duration

        # Wire negative_prompt
        if config.negative_prompt:
            gen_config.negative_prompt = config.negative_prompt

        # Build generation kwargs
        gen_kwargs: dict[str, Any] = {
            "model": model,
            "prompt": config.prompt,
            "config": gen_config,
        }

        # Reference images (up to 3) for style/content guidance
        if config.video_reference_images:
            import base64 as b64

            ref_images = []
            for img_block in config.video_reference_images:
                image_url = img_block.get("image_url", "")
                if image_url.startswith("data:"):
                    header, b64_data = image_url.split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    image_bytes = b64.b64decode(b64_data)
                    ref_images.append(
                        types.VideoGenerationReferenceImage(
                            image=types.Image(
                                image_bytes=image_bytes,
                                mime_type=mime,
                            ),
                        ),
                    )
            if ref_images:
                gen_config.reference_images = ref_images

        # Image-to-video: pass first input image as image= parameter
        if config.input_images:
            import base64 as b64

            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url and image_url.startswith("data:"):
                # Decode base64 data URI
                header, b64_data = image_url.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
                image_bytes = b64.b64decode(b64_data)
                gen_kwargs["image"] = types.Image(
                    image_bytes=image_bytes,
                    mime_type=mime,
                )

        # Start video generation (async operation)
        operation = client.models.generate_videos(**gen_kwargs)

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

        # Capture a clean URI-only reference BEFORE download mutates
        # the object (download populates video_bytes which makes the
        # reference unsuitable for extension API calls).
        video_ref_for_store = types.Video(
            uri=generated_video.video.uri,
            mime_type=generated_video.video.mime_type,
        )

        client.files.download(file=generated_video.video)
        generated_video.video.save(str(config.output_path))

        # Get file info
        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        # Store clean video reference for extension
        store_id = _veo_video_store.save(video_ref_for_store)

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
                "continuation_id": store_id,
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

        # Store video URL for future editing via continue_from
        continuation_id = _grok_video_store.save(response.url)

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
                "continuation_id": continuation_id,
            },
        )

    except Exception as e:
        logger.exception(f"Grok video generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="grok",
            error=f"Grok API error: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Video continuation / editing functions
# ---------------------------------------------------------------------------


async def _edit_video_grok(config: GenerationConfig) -> GenerationResult:
    """Edit a previously generated Grok video with a new prompt.

    Re-renders the video with the new prompt. The output retains the
    original duration, aspect ratio, and resolution (capped at 720p).
    Only ``prompt``, ``model``, and ``video_url`` are supported for editing.

    Args:
        config: GenerationConfig with continue_from (store ID) and new prompt

    Returns:
        GenerationResult with edited video info
    """
    api_key = get_api_key("grok")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="grok",
            error="xAI API key not found. Set XAI_API_KEY environment variable.",
        )

    video_url = _grok_video_store.get(config.continue_from)
    if not video_url:
        return GenerationResult(
            success=False,
            backend_name="grok",
            error=(f"Continuation ID '{config.continue_from}' not found. " "Video URLs are stored in-memory and may have been evicted."),
        )

    try:
        client = xai_sdk.AsyncClient(api_key=api_key)
        model = config.model or get_default_model("grok", MediaType.VIDEO)

        start_time = time.time()

        response = await client.video.generate(
            prompt=config.prompt,
            model=model,
            timeout=timedelta(minutes=10),
            video_url=video_url,
        )

        # Download video from URL
        video_response = requests.get(response.url, timeout=120)
        video_response.raise_for_status()
        config.output_path.write_bytes(video_response.content)

        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        # Store new video for further editing
        new_store_id = _grok_video_store.save(response.url)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="grok",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "generation_time": generation_time,
                "continuation_id": new_store_id,
                "edited_from": config.continue_from,
            },
        )

    except Exception as e:
        logger.exception(f"Grok video editing failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="grok",
            error=f"Grok video editing error: {str(e)}",
        )


async def _remix_video_openai(config: GenerationConfig) -> GenerationResult:
    """Remix a previously generated Sora video with a new prompt.

    Uses ``client.videos.remix()`` with the stored video ID.

    Args:
        config: GenerationConfig with continue_from (store ID) and new prompt

    Returns:
        GenerationResult with remixed video info
    """
    api_key = get_api_key("openai")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error="OpenAI API key not found. Set OPENAI_API_KEY environment variable.",
        )

    video_id = _sora_video_store.get(config.continue_from)
    if not video_id:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=(f"Continuation ID '{config.continue_from}' not found. " "Video IDs are stored in-memory and may have been evicted."),
        )

    try:
        client = AsyncOpenAI(api_key=api_key)
        model = config.model or get_default_model("openai", MediaType.VIDEO)

        start_time = time.time()

        # Remix the existing video with a new prompt.
        # Note: remix() only accepts (video_id, prompt) — model and
        # duration are inherited from the source video.
        video = await client.videos.remix(
            video_id=video_id,
            prompt=config.prompt,
        )

        # Poll for completion
        while video.status in ("in_progress", "queued"):
            video = await client.videos.retrieve(video.id)
            await asyncio.sleep(2)

        if video.status == "failed":
            error_message = getattr(
                getattr(video, "error", None),
                "message",
                "Video remix failed",
            )
            return GenerationResult(
                success=False,
                backend_name="openai",
                model_used=model,
                error=error_message,
            )

        # Download remixed video
        content = await client.videos.download_content(video.id, variant="video")
        content.write_to_file(str(config.output_path))

        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        # Store new video for further remixing
        new_store_id = _sora_video_store.save(video.id)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="openai",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "generation_time": generation_time,
                "video_id": video.id,
                "continuation_id": new_store_id,
                "remixed_from": config.continue_from,
            },
        )

    except Exception as e:
        logger.exception(f"OpenAI video remix failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI remix error: {str(e)}",
        )


async def _continue_video_google(config: GenerationConfig) -> GenerationResult:
    """Continue/extend a previously generated Veo video.

    Passes the stored video reference to the generation call.

    Args:
        config: GenerationConfig with continue_from (store ID) and new prompt

    Returns:
        GenerationResult with continued video info
    """
    api_key = get_api_key("google")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="google",
            error="Google API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY.",
        )

    video_ref = _veo_video_store.get(config.continue_from)
    if not video_ref:
        return GenerationResult(
            success=False,
            backend_name="google",
            error=(f"Continuation ID '{config.continue_from}' not found. " "Video references are stored in-memory and may have been evicted."),
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model = config.model or get_default_model("google", MediaType.VIDEO)

        # Veo extension constraints (per Google API docs):
        #   - Duration must be 8s
        #   - Resolution must be 720p
        #   - Aspect ratio must be 16:9 or 9:16
        VEO_EXTENSION_DURATION = 8

        if config.duration and config.duration != VEO_EXTENSION_DURATION:
            logger.warning(
                f"Veo video extension requires {VEO_EXTENSION_DURATION}s duration. " f"Overriding requested {config.duration}s.",
            )

        start_time = time.time()

        gen_config = types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=VEO_EXTENSION_DURATION,
        )

        if config.aspect_ratio:
            gen_config.aspect_ratio = config.aspect_ratio
        else:
            gen_config.aspect_ratio = "16:9"

        if config.size and config.size.lower() != "720p":
            logger.warning(
                f"Veo video extension only supports 720p resolution. " f"Ignoring requested size '{config.size}'.",
            )
        gen_config.resolution = "720p"

        # Wire negative_prompt
        if config.negative_prompt:
            gen_config.negative_prompt = config.negative_prompt

        # Pass stored video reference for continuation
        operation = client.models.generate_videos(
            model=model,
            prompt=config.prompt,
            video=video_ref,
            config=gen_config,
        )

        # Poll for completion
        poll_interval = 20
        max_wait = 600
        elapsed = 0

        while not operation.done:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if elapsed > max_wait:
                return GenerationResult(
                    success=False,
                    backend_name="google",
                    model_used=model,
                    error="Video continuation timed out after 10 minutes",
                )
            operation = client.operations.get(operation)

        if hasattr(operation, "error") and operation.error:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error=f"Veo continuation error: {operation.error}",
            )

        if not operation.response or not operation.response.generated_videos:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="No video generated from continuation",
            )

        generated_video = operation.response.generated_videos[0]

        # Capture clean URI-only reference before download mutates it
        video_ref_for_store = types.Video(
            uri=generated_video.video.uri,
            mime_type=generated_video.video.mime_type,
        )

        client.files.download(file=generated_video.video)
        generated_video.video.save(str(config.output_path))

        generation_time = time.time() - start_time
        file_size = config.output_path.stat().st_size

        # Store clean video reference for further extension
        new_store_id = _veo_video_store.save(video_ref_for_store)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.VIDEO,
            backend_name="google",
            model_used=model,
            file_size_bytes=file_size,
            duration_seconds=VEO_EXTENSION_DURATION,
            metadata={
                "generation_time": generation_time,
                "total_videos": len(operation.response.generated_videos),
                "continuation_id": new_store_id,
                "continued_from": config.continue_from,
            },
        )

    except Exception as e:
        logger.exception(f"Google Veo continuation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="google",
            error=f"Google Veo continuation error: {str(e)}",
        )
