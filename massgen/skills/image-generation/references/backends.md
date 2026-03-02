# Image Backends: Detailed Reference

## Google Gemini

**Models:** `gemini-3.1-flash-image-preview` (default, Nano Banana 2), `gemini-3-pro-image-preview` (Pro-tier, studio quality)

**Size options** (via `size` param):
- `"512px"` - Small
- `"1K"` - Medium (1024px)
- `"2K"` - Large (2048px)
- `"4K"` - Extra large (4096px)

**Aspect ratio**: Supported via `aspect_ratio` param (e.g., `"16:9"`, `"1:1"`).

**Image editing**: Supported via `input_images`. Images are base64-encoded and sent as `Part.from_bytes()`. Combined with text prompt for editing instructions.

**Continuation**: Uses an in-memory chat store. Returns a `continuation_id` (format: `gemini_chat_<hash>`). LRU eviction at 50 stored chats.

**API path**: `client.chats.create()` + `chat.send_message()` with `response_modalities=["IMAGE"]`.

```python
# Gemini with specific size and aspect ratio
generate_media(prompt="A logo design", mode="image",
               backend_type="google", size="2K", aspect_ratio="1:1")

# Pro-tier model for text rendering
generate_media(prompt="A poster with the title 'Hello World'", mode="image",
               backend_type="google", model="gemini-3-pro-image-preview")
```

## Google Imagen

Imagen is a separate API path from Gemini, used for advanced editing features that Gemini doesn't support. You don't need to use Imagen for basic generation — Nano Banana 2 is better for that. Use Imagen only when you need reference-image editing.

**Editing model:** `imagen-3.0-capability-001` (still the only model for `edit_image()` with reference images)

**Generation models (Imagen 4):** `imagen-4.0-generate-001`, `imagen-4.0-fast-generate-001`, `imagen-4.0-ultra-generate-001`

**Imagen-exclusive features** (not available via Gemini):
- Style transfer (`style_image`)
- Control-based editing (`control_image`)
- Subject consistency (`subject_image`)
- Mask inpainting (`mask_path`)
- `negative_prompt`, `seed`, `guidance_scale`

**API path:** `client.models.generate_images()` for generation, `client.models.edit_image()` for editing.

```python
# Imagen editing (style transfer)
generate_media(prompt="A portrait in this style", mode="image",
               backend_type="google", style_image="ref.jpg")

# Imagen generation with seed
generate_media(prompt="A mountain landscape", mode="image",
               backend_type="google", model="imagen-4.0-generate-001",
               seed=42, negative_prompt="people, text")
```

## OpenAI

**Model:** `gpt-5.2` (default)

**Size options** (via `size` param):
- `"1024x1024"` - Square
- `"1024x1536"` - Portrait
- `"1536x1024"` - Landscape

**Quality options** (via `quality` param):
- `"low"` - Faster, lower detail
- `"medium"` - Balanced
- `"high"` - Maximum detail
- `"auto"` - Let the model decide

**Image editing**: Supported via `input_images`. Input images are sent as mixed content blocks (`input_text` + `input_image`).

**Continuation**: Stateless. Returns `continuation_id` which is the `response.id`. Passed as `previous_response_id` on next call.

**API path**: `client.responses.create()` with `tools=[{"type": "image_generation"}]`.

```python
# High quality with specific size
generate_media(prompt="A detailed botanical illustration", mode="image",
               backend_type="openai", quality="high", size="1024x1536")
```

## Grok (xAI)

**Model:** `grok-imagine-image` (default)

**Resolution**: The xAI SDK only supports `"1k"` resolution. The `size` parameter is accepted but always maps to `"1k"`.

**Aspect ratio**: Supported via `aspect_ratio` param.

**Image editing**: Supported via `input_images`. First input image is passed as `image_url` data URI.

**Continuation**: Uses in-memory data URI store. Returns `continuation_id` (format: `grok_img_<hash>`). Stored data URI is passed directly as `image_url`. LRU eviction at 50 items.

**API path**: `client.image.sample()` with `image_format="base64"`. Note: the SDK returns a data URI (`data:image/jpeg;base64,...`), not raw base64.

```python
# Grok image generation
generate_media(prompt="A cyberpunk cityscape", mode="image",
               backend_type="grok")
```

## OpenRouter

**Model:** `google/gemini-3.1-flash-image-preview` (default, Nano Banana 2 via OpenRouter)

**Aspect ratio**: Supported via `aspect_ratio` param (sent as `image_config.aspect_ratio`).

**Limitations**: No image editing, no continuation. Response image may be in `images` array or embedded as base64 data URI in content.

**API path**: `POST /api/v1/chat/completions` with `modalities=["image", "text"]`.

```python
generate_media(prompt="A minimalist logo", mode="image",
               backend_type="openrouter")
```

## Backend Selection Priority

When `backend_type` is not specified (or `"auto"`), backends are tried in this order:

1. **Google** (if `GOOGLE_API_KEY` or `GEMINI_API_KEY` set)
2. **OpenAI** (if `OPENAI_API_KEY` set)
3. **Grok** (if `XAI_API_KEY` set)
4. **OpenRouter** (if `OPENROUTER_API_KEY` set)

This priority can be overridden per-agent via YAML config:

```yaml
orchestrator:
  image_generation_backend: "openai"
agents:
  - id: agent1
    image_generation_backend: "grok"  # Override for this agent
```

## Input Image Constraints

For image-to-image (`input_images` param):
- Images must be under 4MB each
- Supported formats: PNG, JPEG, GIF, WEBP
- Images are base64-encoded before sending to API
- Paths are validated against allowed directories
