# Image Editing: Advanced Operations

## Image-to-Image (`input_images`)

Transform existing images by providing source images:
```python
generate_media(
    prompt="Convert to watercolor style",
    mode="image",
    input_images=["original.jpg"]
)
```
Supported by: Google Gemini, OpenAI, Grok.

## Multi-Turn Continuation (`continue_from`)

Iteratively refine images:
```python
result = generate_media(prompt="A logo", mode="image")
result2 = generate_media(
    prompt="Add a coffee cup icon",
    mode="image",
    continue_from=result["continuation_id"]
)
```
Supported by: Google Gemini (chat store), OpenAI (response ID), Grok (data URI store).

## Inpainting (Implemented — OpenAI, Google Imagen)

Edit specific regions of an image using a mask PNG. Transparent regions in the mask indicate where to generate new content.

```python
# OpenAI inpainting
generate_media(
    prompt="Replace the sky with a dramatic sunset",
    mode="image",
    backend_type="openai",
    input_images=["photo.jpg"],
    mask_path="sky_mask.png"
)

# Google Imagen inpainting
generate_media(
    prompt="Fill the masked area with flowers",
    mode="image",
    backend_type="google",
    input_images=["photo.jpg"],
    mask_path="mask.png"
)
```

### Parameters
- `mask_path`: Path to a PNG mask image with transparent regions marking edit areas
- `input_images`: Source image to edit (required)
- `size`: Output dimensions (e.g., "1024x1024")
- `output_format`: Output format override ("png", "jpeg", "webp")
- `background`: Background handling ("transparent", "opaque", "auto") — OpenAI only

### How to Create a Mask
1. Start with a fully opaque PNG matching the source image dimensions
2. Make regions transparent where you want new content generated
3. The model will fill transparent regions based on the prompt

### Backend Support
OpenAI (`images.edit()` API) and Google Imagen (`edit_image()` API with mask reference).

## Style Transfer (Implemented — Google Imagen)

Apply the style of a reference image. Uses `imagen-3.0-capability-001` (the only editing model; no Imagen 4 equivalent exists yet). The model is auto-selected when `style_image` is provided.

```python
generate_media(
    prompt="Apply this art style to my photo",
    mode="image",
    backend_type="google",
    style_image="style_ref.jpg"
)
```

Optional: Add `style_description` via `extra_params` to describe the desired style in text.

## Control-Based Editing (Implemented — Google Imagen)

Use structural references (edge maps, depth maps):
```python
generate_media(
    prompt="A house following this floor plan",
    mode="image",
    backend_type="google",
    control_image="edges.png"
)
```

Optional: Set `control_type` via `extra_params` to specify guidance type.

## Subject Consistency (Implemented — Google Imagen)

Maintain subject identity across generations:
```python
generate_media(
    prompt="The same character in a beach scene",
    mode="image",
    backend_type="google",
    subject_image="character.png"
)
```

Optional: Set `subject_type` and `subject_description` via `extra_params`.

## Combining Multiple References

Multiple reference types can be combined in a single call:
```python
generate_media(
    prompt="The character in watercolor style",
    mode="image",
    backend_type="google",
    subject_image="character.png",
    style_image="watercolor_ref.jpg"
)
```
