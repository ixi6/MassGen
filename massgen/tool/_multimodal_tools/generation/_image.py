"""
Image generation backends: OpenAI, Google (Gemini + Imagen), OpenRouter.

This module contains all image generation implementations that are
routed through by generate_media when mode="image".

Google backend supports two API paths:
- **Gemini** (``gemini-*`` models): Uses ``generate_content()`` with
  ``response_modalities=['IMAGE']``. Supports text-to-image and image editing.
- **Imagen** (``imagen-*`` models): Uses ``generate_images()``. Text-to-image only.
"""

import base64
import uuid
from collections import OrderedDict
from typing import Any

import requests
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
    """In-memory store for Gemini chat objects used in multi-turn image editing."""

    def __init__(self, max_chats: int = 50):
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._max = max_chats

    def save(self, chat_obj: Any) -> str:
        chat_id = f"gemini_chat_{uuid.uuid4().hex[:12]}"
        if len(self._store) >= self._max:
            self._store.popitem(last=False)
        self._store[chat_id] = chat_obj
        return chat_id

    def get(self, chat_id: str) -> Any | None:
        return self._store.get(chat_id)


_gemini_chat_store = _GeminiChatStore()


async def generate_image(config: GenerationConfig) -> GenerationResult:
    """Generate an image using the selected backend.

    Routes to the appropriate backend based on config.backend.

    Args:
        config: GenerationConfig with prompt, output_path, backend, etc.

    Returns:
        GenerationResult with success status and file info
    """
    backend = config.backend or "openai"  # Default if not specified

    if backend == "google":
        return await _generate_image_google(config)
    elif backend == "openrouter":
        return await _generate_image_openrouter(config)
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

        # Build image tool config with optional quality and size
        image_tool: dict[str, Any] = {"type": "image_generation"}
        if config.quality:
            image_tool["quality"] = config.quality
        if config.size:
            image_tool["size"] = config.size

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
            # Retrieve existing chat from store
            chat = _gemini_chat_store.get(config.continue_from)
            if not chat:
                return GenerationResult(
                    success=False,
                    backend_name="google",
                    model_used=model,
                    error=("Continuation chat not found. The continuation_id " f"'{config.continue_from}' may have expired or is invalid."),
                )
            response = chat.send_message(msg_contents, config=gen_config)
        else:
            # First call — create chat and send initial message
            chat = client.chats.create(model=model, config=gen_config)
            response = chat.send_message(msg_contents, config=gen_config)

        # Store chat for future continuation
        chat_id = _gemini_chat_store.save(chat)

        # Extract image from response parts
        for part in response.candidates[0].content.parts:
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

        # Prepare config
        gen_config = genai_types.GenerateImagesConfig(
            number_of_images=1,
            output_mime_type="image/png",
        )

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
