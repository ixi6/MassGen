"""
Image generation backends: OpenAI, Google (Gemini + Imagen), OpenRouter, Grok (xAI).

This module contains all image generation implementations that are
routed through by generate_media when mode="image".

Google backend supports two API paths:
- **Gemini** (``gemini-*`` models): Uses ``generate_content()`` with
  ``response_modalities=['IMAGE']``. Supports text-to-image and image editing.
- **Imagen** (``imagen-*`` models): Uses ``generate_images()``. Text-to-image only.

Grok backend uses the xAI SDK:
- ``client.image.sample()`` returns base64 data.
- Continuation via ``image_url`` data URI with stored base64.
"""

import base64
import uuid
from collections import OrderedDict
from typing import Any

import requests
import xai_sdk
from google import genai
from google.genai import types as genai_types
from openai import AsyncOpenAI

from massgen.logger_config import logger
from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    GenerationResult,
    MediaType,
    get_api_key,
    get_default_model,
)


class _GeminiChatStore:
    """In-memory store for Gemini chat objects used in multi-turn image editing.

    Stores ``(client, chat)`` tuples so the ``genai.Client`` stays alive
    across continuation calls — preventing the underlying HTTP connection
    from being garbage-collected.
    """

    def __init__(self, max_chats: int = 50):
        self._store: OrderedDict[str, tuple[Any, Any]] = OrderedDict()
        self._max = max_chats

    def save(self, client: Any, chat_obj: Any) -> str:
        chat_id = f"gemini_chat_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[chat_id] = (client, chat_obj)
        return chat_id

    def get(self, chat_id: str) -> tuple[Any, Any]:
        entry = self._store.get(chat_id)
        if entry is None:
            return None, None
        return entry


_gemini_chat_store = _GeminiChatStore()


class _GrokImageStore:
    """In-memory store for Grok image base64 data used in continuation editing."""

    def __init__(self, max_items: int = 50):
        self._store: OrderedDict[str, str] = OrderedDict()
        self._max = max_items

    def save(self, base64_data: str) -> str:
        store_id = f"grok_img_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[store_id] = base64_data
        return store_id

    def get(self, store_id: str) -> str | None:
        return self._store.get(store_id)


_grok_image_store = _GrokImageStore()


def _map_size_to_grok_resolution(size: str | None) -> str:
    """Map a size string to Grok resolution parameter.

    The xAI SDK only supports ``"1k"`` as a valid resolution value.

    Args:
        size: Size string from config (ignored — only "1k" is valid)

    Returns:
        Always "1k" (the only supported Grok image resolution)
    """
    return "1k"


async def generate_image(config: GenerationConfig) -> GenerationResult:
    """Generate an image using the selected backend.

    Routes to the appropriate backend based on config.backend.

    Args:
        config: GenerationConfig with prompt, output_path, backend, etc.

    Returns:
        GenerationResult with success status and file info
    """
    backend = config.backend or "openai"  # Default if not specified

    # Route inpainting when mask_path is provided
    if config.mask_path:
        if backend == "google":
            return await _edit_image_google(config)
        if backend != "openai":
            return GenerationResult(
                success=False,
                backend_name=backend,
                error=("Inpainting (mask_path) is supported by " "the OpenAI and Google backends."),
            )
        return await _inpaint_image_openai(config)

    # Route Google advanced editing when reference images are provided
    if _has_google_edit_params(config):
        if backend != "google":
            return GenerationResult(
                success=False,
                backend_name=backend,
                error=("Style transfer, control, and subject editing are only " "supported by the Google (Imagen) backend."),
            )
        return await _edit_image_google(config)

    if backend == "google":
        return await _generate_image_google(config)
    elif backend == "openrouter":
        return await _generate_image_openrouter(config)
    elif backend == "grok":
        return await _generate_image_grok(config)
    else:  # openai (default)
        return await _generate_image_openai(config)


async def _generate_image_openai(config: GenerationConfig) -> GenerationResult:
    """Generate image using OpenAI's Responses API.

    Uses the image_generation tool via the responses endpoint.
    This approach supports multi-turn conversations and is the recommended
    method for agentic image generation workflows.

    Args:
        config: GenerationConfig with prompt and output path

    Returns:
        GenerationResult with generated image info
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
        model = config.model or get_default_model("openai", MediaType.IMAGE)

        # Build input content (supports optional input_images for image-to-image)
        if config.input_images:
            input_content = [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": config.prompt}, *config.input_images],
                },
            ]
        else:
            input_content = config.prompt

        # Build image tool config with optional quality, size, format, background
        image_tool: dict[str, Any] = {"type": "image_generation"}
        if config.quality:
            image_tool["quality"] = config.quality
        if config.size:
            image_tool["size"] = config.size
        if config.output_format:
            image_tool["output_format"] = config.output_format
        if config.background:
            image_tool["background"] = config.background

        # Build create kwargs with optional continuation
        create_kwargs: dict[str, Any] = {
            "model": model,
            "input": input_content,
            "tools": [image_tool],
        }
        if config.continue_from:
            create_kwargs["previous_response_id"] = config.continue_from

        # Generate image using OpenAI Responses API (async)
        response = await client.responses.create(**create_kwargs)

        # Extract image data from response
        image_data = [output.result for output in response.output if output.type == "image_generation_call"]

        if not image_data:
            return GenerationResult(
                success=False,
                backend_name="openai",
                model_used=model,
                error="No image data in response",
            )

        # Save the first image
        image_bytes = base64.b64decode(image_data[0])
        config.output_path.write_bytes(image_bytes)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="openai",
            model_used=model,
            file_size_bytes=len(image_bytes),
            metadata={
                "total_images": len(image_data),
                "continuation_id": response.id,
            },
        )

    except Exception as e:
        logger.exception(f"OpenAI image generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI API error: {str(e)}",
        )


async def _generate_image_google(config: GenerationConfig) -> GenerationResult:
    """Route Google image generation to Gemini or Imagen based on model name.

    - ``gemini-*`` models use ``generate_content()`` (Gemini API).
    - ``imagen-*`` models use ``generate_images()`` (Imagen API).

    Args:
        config: GenerationConfig with prompt and output path

    Returns:
        GenerationResult with generated image info
    """
    api_key = get_api_key("google")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="google",
            error="Google API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.",
        )

    model = config.model or get_default_model("google", MediaType.IMAGE)

    if model.startswith("gemini-"):
        return await _generate_image_google_gemini(config, model)
    return await _generate_image_google_imagen(config, model)


def _build_gemini_contents(config: GenerationConfig) -> str | list:
    """Build contents list from config (input_images + prompt text).

    Args:
        config: GenerationConfig with prompt and optional input_images

    Returns:
        A string (prompt only) or list of Parts + prompt text
    """
    if config.input_images:
        contents: list = []
        for img_block in config.input_images:
            image_url = img_block.get("image_url", "")
            if image_url.startswith("data:"):
                header, b64_data = image_url.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
                img_bytes = base64.b64decode(b64_data)
                contents.append(
                    genai_types.Part.from_bytes(data=img_bytes, mime_type=mime),
                )
        contents.append(config.prompt)
        return contents
    return config.prompt


async def _generate_image_google_gemini(
    config: GenerationConfig,
    model: str,
) -> GenerationResult:
    """Generate image using Gemini with chat-based multi-turn support.

    Uses ``client.chats.create()`` + ``chat.send_message()`` for all calls,
    enabling multi-turn editing via ``config.continue_from``.

    Supports both text-to-image and image editing (when ``config.input_images``
    contains base64-encoded image blocks).

    Args:
        config: GenerationConfig with prompt and output path
        model: Gemini model name (e.g. ``gemini-3.1-flash-image-preview``)

    Returns:
        GenerationResult with generated image info
    """
    api_key = get_api_key("google")

    try:
        client = genai.Client(api_key=api_key)

        # Build GenerateContentConfig with optional ImageConfig
        image_config_kwargs: dict[str, Any] = {}
        if config.aspect_ratio:
            image_config_kwargs["aspect_ratio"] = config.aspect_ratio
        if config.size:
            image_config_kwargs["image_size"] = config.size

        gen_config_kwargs: dict[str, Any] = {"response_modalities": ["IMAGE"]}
        if image_config_kwargs:
            gen_config_kwargs["image_config"] = genai_types.ImageConfig(
                **image_config_kwargs,
            )

        gen_config = genai_types.GenerateContentConfig(**gen_config_kwargs)

        # Build message contents
        msg_contents = _build_gemini_contents(config)

        if config.continue_from:
            # Retrieve existing (client, chat) from store — the stored
            # client keeps the HTTP connection alive.
            stored_client, chat = _gemini_chat_store.get(config.continue_from)
            if not chat:
                return GenerationResult(
                    success=False,
                    backend_name="google",
                    model_used=model,
                    error=("Continuation chat not found. The continuation_id " f"'{config.continue_from}' may have expired or is invalid."),
                )
            response = chat.send_message(msg_contents, config=gen_config)
            # Keep the original client alive for further continuations
            client = stored_client
        else:
            # First call — create chat and send initial message
            chat = client.chats.create(model=model, config=gen_config)
            response = chat.send_message(msg_contents, config=gen_config)

        # Store (client, chat) for future continuation
        chat_id = _gemini_chat_store.save(client, chat)

        # Extract image from response parts
        candidates = getattr(response, "candidates", None)
        if not candidates or not candidates[0].content or not candidates[0].content.parts:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="Google Gemini returned no image content. The model may have refused the request.",
            )
        for part in candidates[0].content.parts:
            if part.inline_data is not None:
                image = part.as_image()
                image.save(str(config.output_path))

                file_size = config.output_path.stat().st_size
                return GenerationResult(
                    success=True,
                    output_path=config.output_path,
                    media_type=MediaType.IMAGE,
                    backend_name="google",
                    model_used=model,
                    file_size_bytes=file_size,
                    metadata={
                        "api_path": "gemini_generate_content",
                        "continuation_id": chat_id,
                    },
                )

        return GenerationResult(
            success=False,
            backend_name="google",
            model_used=model,
            error="No image data in Gemini response",
        )

    except Exception as e:
        logger.exception(f"Google Gemini image generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="google",
            model_used=model,
            error=f"Google Gemini error: {str(e)}",
        )


async def _generate_image_google_imagen(
    config: GenerationConfig,
    model: str,
) -> GenerationResult:
    """Generate image using Google Imagen ``generate_images()`` API.

    Args:
        config: GenerationConfig with prompt and output path
        model: Imagen model name (e.g. ``imagen-4.0-fast-generate-001``)

    Returns:
        GenerationResult with generated image info
    """
    api_key = get_api_key("google")

    try:
        client = genai.Client(api_key=api_key)

        # Determine output MIME type
        output_mime = "image/png"
        if config.output_format:
            fmt_map = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
            output_mime = fmt_map.get(config.output_format.lower(), "image/png")

        # Prepare config
        gen_config_kwargs: dict[str, Any] = {
            "number_of_images": 1,
            "output_mime_type": output_mime,
        }
        if config.negative_prompt:
            gen_config_kwargs["negative_prompt"] = config.negative_prompt
        if config.seed is not None:
            gen_config_kwargs["seed"] = config.seed
        if config.guidance_scale is not None:
            gen_config_kwargs["guidance_scale"] = config.guidance_scale

        gen_config = genai_types.GenerateImagesConfig(**gen_config_kwargs)

        # Add aspect ratio if specified
        if config.aspect_ratio:
            gen_config.aspect_ratio = config.aspect_ratio

        # Generate image
        response = client.models.generate_images(
            model=model,
            prompt=config.prompt,
            config=gen_config,
        )

        if not response.generated_images:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="No images generated",
            )

        # Save the first image
        generated_image = response.generated_images[0]
        generated_image.image.save(str(config.output_path))

        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="google",
            model_used=model,
            file_size_bytes=file_size,
            metadata={"total_images": len(response.generated_images)},
        )

    except Exception as e:
        logger.exception(f"Google Imagen generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="google",
            error=f"Google Imagen error: {str(e)}",
        )


async def _generate_image_grok(config: GenerationConfig) -> GenerationResult:
    """Generate image using xAI Grok's image API.

    Uses ``client.image.sample()`` which returns base64 data directly.
    Supports continuation via stored base64 passed as ``image_url`` data URI.

    Args:
        config: GenerationConfig with prompt and output path

    Returns:
        GenerationResult with generated image info
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
        model = config.model or get_default_model("grok", MediaType.IMAGE)

        sample_kwargs: dict[str, Any] = {
            "prompt": config.prompt,
            "model": model,
            "image_format": "base64",
        }

        if config.aspect_ratio:
            sample_kwargs["aspect_ratio"] = config.aspect_ratio

        sample_kwargs["resolution"] = _map_size_to_grok_resolution(config.size)

        # Handle continuation — retrieve stored data URI and pass directly
        if config.continue_from:
            stored_data_uri = _grok_image_store.get(config.continue_from)
            if not stored_data_uri:
                return GenerationResult(
                    success=False,
                    backend_name="grok",
                    model_used=model,
                    error=("Continuation image not found. The continuation_id " f"'{config.continue_from}' may have expired or is invalid."),
                )
            sample_kwargs["image_url"] = stored_data_uri
        elif config.input_images:
            # Image-to-image editing: pass first input image as image_url
            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url:
                sample_kwargs["image_url"] = image_url

        response = await client.image.sample(**sample_kwargs)

        # response.base64 is a data URI ("data:image/...;base64,<data>").
        # Strip the prefix to get raw base64, then decode.
        data_uri = response.base64
        if "base64," in data_uri:
            raw_b64 = data_uri.split("base64,", 1)[1]
        else:
            raw_b64 = data_uri
        image_bytes = base64.b64decode(raw_b64)
        config.output_path.write_bytes(image_bytes)

        # Store the full data URI for continuation (image_url expects it)
        continuation_id = _grok_image_store.save(data_uri)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="grok",
            model_used=model,
            file_size_bytes=len(image_bytes),
            metadata={
                "continuation_id": continuation_id,
            },
        )

    except Exception as e:
        logger.exception(f"Grok image generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="grok",
            error=f"Grok API error: {str(e)}",
        )


async def _generate_image_openrouter(config: GenerationConfig) -> GenerationResult:
    """Generate image using OpenRouter API.

    Uses the chat completions endpoint with modalities=["image", "text"].

    Args:
        config: GenerationConfig with prompt and output path

    Returns:
        GenerationResult with generated image info
    """
    api_key = get_api_key("openrouter")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="openrouter",
            error="OpenRouter API key not found. Set OPENROUTER_API_KEY environment variable.",
        )

    try:
        model = config.model or get_default_model("openrouter", MediaType.IMAGE)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://massgen.dev",
        }

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": config.prompt}],
            "modalities": ["image", "text"],
        }

        # Add aspect ratio if specified
        if config.aspect_ratio:
            payload["image_config"] = {"aspect_ratio": config.aspect_ratio}

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()

        # Extract image from response
        if not result.get("choices"):
            return GenerationResult(
                success=False,
                backend_name="openrouter",
                model_used=model,
                error="No choices in response",
            )

        message = result["choices"][0].get("message", {})
        images = message.get("images", [])

        if not images:
            # Check if content contains base64 image
            content = message.get("content", "")
            if "data:image" in content:
                # Extract base64 from data URL
                import re

                match = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
                if match:
                    image_bytes = base64.b64decode(match.group(1))
                    config.output_path.write_bytes(image_bytes)

                    return GenerationResult(
                        success=True,
                        output_path=config.output_path,
                        media_type=MediaType.IMAGE,
                        backend_name="openrouter",
                        model_used=model,
                        file_size_bytes=len(image_bytes),
                    )

            return GenerationResult(
                success=False,
                backend_name="openrouter",
                model_used=model,
                error="No image in response",
            )

        # Process first image
        image_url = images[0].get("image_url", {}).get("url", "")
        if not image_url:
            return GenerationResult(
                success=False,
                backend_name="openrouter",
                model_used=model,
                error="No image URL in response",
            )

        # Extract base64 data from data URL
        if image_url.startswith("data:"):
            base64_data = image_url.split(",")[1]
            image_bytes = base64.b64decode(base64_data)
        else:
            # Fetch from URL
            img_response = requests.get(image_url, timeout=60)
            img_response.raise_for_status()
            image_bytes = img_response.content

        # Save image
        config.output_path.write_bytes(image_bytes)

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="openrouter",
            model_used=model,
            file_size_bytes=len(image_bytes),
            metadata={"total_images": len(images)},
        )

    except requests.exceptions.RequestException as e:
        logger.exception(f"OpenRouter image generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openrouter",
            error=f"OpenRouter API error: {str(e)}",
        )
    except Exception as e:
        logger.exception(f"OpenRouter image generation failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openrouter",
            error=f"OpenRouter error: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Inpainting (MAS-333 Phase 4)
# ---------------------------------------------------------------------------


async def _inpaint_image_openai(config: GenerationConfig) -> GenerationResult:
    """Inpaint an image using OpenAI's images.edit() API.

    Requires a mask image (PNG with transparent regions indicating where
    to generate new content) and optionally a source image.

    Args:
        config: GenerationConfig with mask_path, prompt, and optionally
                input_images (source image) or continue_from (previous result)

    Returns:
        GenerationResult with inpainted image info
    """
    api_key = get_api_key("openai")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error="OpenAI API key not found. Set OPENAI_API_KEY environment variable.",
        )

    if not config.mask_path or not config.mask_path.exists():
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"Mask file not found: {config.mask_path}",
        )

    # Must have a source image (via input_images or continue_from)
    if not config.input_images and not config.continue_from:
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=("Inpainting requires a source image. Provide input_images " "with the image to edit, or continue_from with a previous " "generation's continuation_id."),
        )

    try:
        client = AsyncOpenAI(api_key=api_key)
        model = config.model or "gpt-5.2"

        # Build edit kwargs
        edit_kwargs: dict[str, Any] = {
            "model": model,
            "prompt": config.prompt,
        }

        # Load mask file
        mask_file = open(config.mask_path, "rb")  # noqa: SIM115
        edit_kwargs["mask"] = mask_file

        # Load source image
        source_file = None
        if config.input_images:
            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url.startswith("data:"):
                b64_data = image_url.split(",", 1)[1]
                import io

                source_bytes = base64.b64decode(b64_data)
                source_file = io.BytesIO(source_bytes)
                source_file.name = "source.png"
                edit_kwargs["image"] = source_file

        # Optional parameters
        if config.output_format:
            edit_kwargs["output_format"] = config.output_format
        if config.background:
            edit_kwargs["background"] = config.background
        if config.size:
            edit_kwargs["size"] = config.size

        try:
            response = await client.images.edit(**edit_kwargs)
        finally:
            mask_file.close()
            if source_file:
                source_file.close()

        if not response.data:
            return GenerationResult(
                success=False,
                backend_name="openai",
                model_used=model,
                error="No image data in inpainting response",
            )

        # Save the result
        image_data = response.data[0]
        if image_data.b64_json:
            image_bytes = base64.b64decode(image_data.b64_json)
            config.output_path.write_bytes(image_bytes)
        elif image_data.url:
            img_response = requests.get(image_data.url, timeout=60)
            img_response.raise_for_status()
            image_bytes = img_response.content
            config.output_path.write_bytes(image_bytes)
        else:
            return GenerationResult(
                success=False,
                backend_name="openai",
                model_used=model,
                error="No image data or URL in inpainting response",
            )

        file_size = config.output_path.stat().st_size

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="openai",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "edit_mode": "inpaint",
                "mask_path": str(config.mask_path),
                "output_format": config.output_format,
                "background": config.background,
            },
        )

    except Exception as e:
        logger.exception(f"OpenAI inpainting failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="openai",
            error=f"OpenAI inpainting error: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Google Advanced Image Editing (MAS-333 Phase 5)
# ---------------------------------------------------------------------------


def _has_google_edit_params(config: GenerationConfig) -> bool:
    """Check if config has any Google advanced editing parameters set."""
    return any(
        [
            config.style_image_path,
            config.control_image_path,
            config.subject_image_path,
            config.mask_mode,
        ],
    )


def _build_google_reference_images(
    config: GenerationConfig,
) -> list[Any]:
    """Build reference image list for Google Imagen edit_image API.

    Constructs the appropriate ReferenceImage objects based on which
    editing parameters are set in the config.

    Args:
        config: GenerationConfig with editing parameters

    Returns:
        List of ReferenceImage objects for the edit_image API
    """
    from google.genai import types

    reference_images = []

    # Style transfer reference
    if config.style_image_path and config.style_image_path.exists():
        style_bytes = config.style_image_path.read_bytes()
        style_config_kwargs: dict[str, Any] = {}
        if config.style_description:
            style_config_kwargs["style_description"] = config.style_description
        reference_images.append(
            types.StyleReferenceImage(
                reference_image=types.RawReferenceImage(
                    reference_id=1,
                    reference_image=types.Image(image_bytes=style_bytes),
                ),
                config=types.StyleReferenceConfig(**style_config_kwargs) if style_config_kwargs else None,
            ),
        )

    # Control (structural) reference
    if config.control_image_path and config.control_image_path.exists():
        control_bytes = config.control_image_path.read_bytes()
        control_config_kwargs: dict[str, Any] = {}
        if config.control_type:
            control_config_kwargs["control_type"] = config.control_type
        reference_images.append(
            types.ControlReferenceImage(
                reference_image=types.RawReferenceImage(
                    reference_id=2,
                    reference_image=types.Image(image_bytes=control_bytes),
                ),
                config=types.ControlReferenceConfig(**control_config_kwargs) if control_config_kwargs else None,
            ),
        )

    # Subject consistency reference
    if config.subject_image_path and config.subject_image_path.exists():
        subject_bytes = config.subject_image_path.read_bytes()
        subject_config_kwargs: dict[str, Any] = {}
        if config.subject_type:
            subject_config_kwargs["subject_type"] = config.subject_type
        if config.subject_description:
            subject_config_kwargs["subject_description"] = config.subject_description
        reference_images.append(
            types.SubjectReferenceImage(
                reference_image=types.RawReferenceImage(
                    reference_id=3,
                    reference_image=types.Image(image_bytes=subject_bytes),
                ),
                config=types.SubjectReferenceConfig(**subject_config_kwargs) if subject_config_kwargs else None,
            ),
        )

    # Mask reference (for Google-side inpainting)
    if config.mask_path and config.mask_path.exists():
        mask_bytes = config.mask_path.read_bytes()
        mask_config_kwargs: dict[str, Any] = {}
        if config.mask_mode:
            mask_config_kwargs["mask_mode"] = config.mask_mode
        if config.segmentation_classes:
            mask_config_kwargs["segmentation_classes"] = config.segmentation_classes
        # For mask + input_images, use the first input image as the source
        source_image = None
        if config.input_images:
            first_image = config.input_images[0]
            image_url = first_image.get("image_url", "")
            if image_url.startswith("data:"):
                b64_data = image_url.split(",", 1)[1]
                source_bytes = base64.b64decode(b64_data)
                source_image = types.Image(image_bytes=source_bytes)
        reference_images.append(
            types.MaskReferenceImage(
                reference_image=types.RawReferenceImage(
                    reference_id=4,
                    reference_image=source_image
                    or types.Image(
                        image_bytes=mask_bytes,
                    ),
                ),
                config=types.MaskReferenceConfig(**mask_config_kwargs) if mask_config_kwargs else None,
                mask_image=types.Image(image_bytes=mask_bytes),
            ),
        )

    return reference_images


async def _edit_image_google(config: GenerationConfig) -> GenerationResult:
    """Edit an image using Google Imagen's edit_image API.

    Supports style transfer, structural control, subject consistency,
    and mask-based inpainting via reference images.

    Args:
        config: GenerationConfig with editing parameters (style_image_path,
                control_image_path, subject_image_path, mask_path, etc.)

    Returns:
        GenerationResult with edited image info
    """
    api_key = get_api_key("google")
    if not api_key:
        return GenerationResult(
            success=False,
            backend_name="google",
            error="Google API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY.",
        )

    try:
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model = config.model or "imagen-3.0-capability-001"

        # Build reference images
        reference_images = _build_google_reference_images(config)
        if not reference_images:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="No valid reference images for editing operation.",
            )

        # Build edit config
        edit_config_kwargs: dict[str, Any] = {
            "number_of_images": 1,
            "output_mime_type": "image/png",
        }
        if config.negative_prompt:
            edit_config_kwargs["negative_prompt"] = config.negative_prompt
        if config.seed is not None:
            edit_config_kwargs["seed"] = config.seed
        if config.guidance_scale is not None:
            edit_config_kwargs["guidance_scale"] = config.guidance_scale

        edit_config = types.EditImageConfig(**edit_config_kwargs)

        # Call edit_image API
        response = client.models.edit_image(
            model=model,
            prompt=config.prompt,
            reference_images=reference_images,
            config=edit_config,
        )

        if not response.generated_images:
            return GenerationResult(
                success=False,
                backend_name="google",
                model_used=model,
                error="No images generated from editing operation.",
            )

        # Save first result
        generated_image = response.generated_images[0]
        generated_image.image.save(str(config.output_path))

        file_size = config.output_path.stat().st_size

        # Determine edit type for metadata
        edit_types = []
        if config.style_image_path:
            edit_types.append("style_transfer")
        if config.control_image_path:
            edit_types.append("control")
        if config.subject_image_path:
            edit_types.append("subject")
        if config.mask_path:
            edit_types.append("inpaint")

        return GenerationResult(
            success=True,
            output_path=config.output_path,
            media_type=MediaType.IMAGE,
            backend_name="google",
            model_used=model,
            file_size_bytes=file_size,
            metadata={
                "edit_types": edit_types,
                "reference_count": len(reference_images),
                "total_images": len(response.generated_images),
            },
        )

    except Exception as e:
        logger.exception(f"Google Imagen editing failed: {e}")
        return GenerationResult(
            success=False,
            backend_name="google",
            error=f"Google Imagen editing error: {str(e)}",
        )
