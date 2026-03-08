# Image Generation: Advanced Parameters Reference

These parameters are now available as direct `generate_media` keyword arguments (not `extra_params`).

## Available Parameters

| Parameter | Type | Description | Backends |
|-----------|------|-------------|----------|
| `mask_path` | `str` | Path to mask PNG for inpainting | OpenAI, Google Imagen |
| `negative_prompt` | `str` | What to exclude from the image | Google Imagen |
| `seed` | `int` | Reproducibility seed for deterministic output | Google Imagen, ElevenLabs |
| `guidance_scale` | `float` | Prompt adherence strength (higher = more literal) | Google Imagen |
| `output_format` | `str` | Output format override (`"png"`, `"jpeg"`, `"webp"`) | OpenAI, Google Imagen |
| `background` | `str` | Background handling: `"transparent"`, `"opaque"`, `"auto"` | OpenAI |
| `style_image` | `str` | Path to style reference image | Google Imagen |
| `control_image` | `str` | Path to structural control image (edge/depth map) | Google Imagen |
| `subject_image` | `str` | Path to subject reference for consistency | Google Imagen |

## Examples

### Transparent Background (OpenAI)
```python
generate_media(
    prompt="A logo with transparent background",
    mode="image",
    backend_type="openai",
    background="transparent",
    output_format="png"
)
```

### Reproducible Output (Google Imagen)
```python
generate_media(
    prompt="A mountain landscape at sunset",
    mode="image",
    backend_type="google",
    model="imagen-4.0-generate-001",
    seed=42,
    negative_prompt="people, buildings, text",
    guidance_scale=7.5
)
```

### Style Transfer (Google Imagen)
```python
generate_media(
    prompt="A portrait in this artistic style",
    mode="image",
    backend_type="google",
    style_image="reference_painting.jpg"
)
```

### Subject Consistency (Google Imagen)
```python
generate_media(
    prompt="The same character in a beach scene",
    mode="image",
    backend_type="google",
    subject_image="character_ref.png"
)
```

## Backend Support Matrix

| Parameter | OpenAI | Gemini | Imagen | Grok | OpenRouter |
|-----------|--------|--------|--------|------|------------|
| `quality` | Yes | - | - | - | - |
| `size` | Yes | Yes | - | Yes (1k only) | - |
| `aspect_ratio` | - | Yes | Yes | Yes | Yes |
| `output_format` | Yes | - | Yes | - | - |
| `background` | Yes | - | - | - | - |
| `negative_prompt` | - | - | Yes | - | - |
| `seed` | - | - | Yes | - | - |
| `guidance_scale` | - | - | Yes | - | - |
| `mask_path` | Yes | - | Yes | - | - |
| `style_image` | - | - | Yes | - | - |
| `control_image` | - | - | Yes | - | - |
| `subject_image` | - | - | Yes | - | - |
| `continue_from` | Yes | Yes | - | Yes | - |
| `input_images` | Yes | Yes | - | Yes | - |
