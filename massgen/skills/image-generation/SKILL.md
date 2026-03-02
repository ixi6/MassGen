---
name: image-generation
description: Guide to image generation and editing in MassGen. Use when creating images, editing existing images, iterating on image designs, or choosing between image backends (OpenAI, Google Gemini/Imagen, Grok, OpenRouter).
---

# Image Generation

Generate images using `generate_media` with `mode="image"`. The system auto-selects the best backend based on available API keys.

## Quick Start

```python
# Simple text-to-image (auto-selects backend)
generate_media(prompt="A cat in space", mode="image")

# Specify backend and quality
generate_media(prompt="A logo for a coffee shop", mode="image",
               backend_type="openai", quality="high")

# Batch generation (parallel)
generate_media(prompts=["sunset over ocean", "mountain landscape", "city at night"],
               mode="image", max_concurrent=3)
```

## Backend Comparison

| Backend | Default Model | Strengths | API Key |
|---------|--------------|-----------|---------|
| **Google** (priority 1) | `gemini-3.1-flash-image-preview` (Nano Banana 2) | Fast, flexible sizes, image editing, multi-turn | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| **OpenAI** (priority 2) | `gpt-5.2` | High quality, transparent backgrounds, continuation via response ID | `OPENAI_API_KEY` |
| **Grok** (priority 3) | `grok-imagine-image` | 1k resolution, continuation via stored data URI | `XAI_API_KEY` |
| **OpenRouter** (priority 4) | `google/gemini-3.1-flash-image-preview` | Access to multiple models via single API | `OPENROUTER_API_KEY` |

## Key Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `prompt` | Text description of the image | `"A watercolor painting of mountains"` |
| `backend_type` | Force a specific backend | `"google"`, `"openai"`, `"grok"`, `"openrouter"` |
| `model` | Override default model | `"gemini-3-pro-image-preview"` for studio quality |
| `quality` | Image quality (OpenAI) | `"low"`, `"medium"`, `"high"`, `"auto"` |
| `size` | Image dimensions | See backends reference |
| `aspect_ratio` | Aspect ratio | `"16:9"`, `"1:1"`, `"4:5"` |
| `input_images` | Source images for image-to-image editing | `["photo.jpg"]` |
| `continue_from` | Continuation ID for multi-turn editing | `result["continuation_id"]` |

## Image-to-Image Editing

Transform existing images by providing `input_images`:

```python
generate_media(
    prompt="Make it look like a watercolor painting",
    mode="image",
    input_images=["photo.jpg"]
)
```

Supported backends for image-to-image: Google (Gemini), OpenAI, Grok. The system auto-selects if your current backend doesn't support it.

## Multi-Turn Editing (Continuation)

Iteratively refine images using `continue_from`:

```python
# First generation
result = generate_media(prompt="A logo for a coffee shop", mode="image")

# Refine using the continuation ID
result2 = generate_media(
    prompt="Make the text larger and add a cup icon",
    mode="image",
    continue_from=result["continuation_id"]
)
```

Each backend uses a different continuation mechanism:
- **OpenAI**: Passes `previous_response_id` (stateless)
- **Google Gemini**: In-memory chat store (LRU, 50 items)
- **Grok**: In-memory data URI store (LRU, 50 items)

Continuation only works for single image generation (not batch).

## Google: Gemini vs Imagen

Google supports two API paths. **Gemini (Nano Banana 2) is the default and recommended for most use cases.** Imagen is only needed for advanced reference-image editing features.

- **Gemini models** (`gemini-*`): `generate_content()` — text-to-image, image editing via `input_images`, multi-turn continuation
- **Imagen models** (`imagen-*`): `generate_images()` / `edit_image()` — text-to-image with `negative_prompt`/`seed`/`guidance_scale`, plus style transfer, control editing, and subject consistency via reference images

For studio-quality precision and text rendering, use: `model="gemini-3-pro-image-preview"` (Pro-tier).

## Need More Control?

- **Per-backend sizes, quality options, and quirks**: See [references/backends.md](references/backends.md)
- **Complete `extra_params` reference**: See [references/extra_params.md](references/extra_params.md)
- **Advanced editing (inpainting, style transfer, control, subject)**: See [references/editing.md](references/editing.md)
