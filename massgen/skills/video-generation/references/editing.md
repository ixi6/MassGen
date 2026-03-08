# Video Editing: Advanced Operations

## Video Continuation / Remix

Generate a video, then use its `continuation_id` to create follow-up or remixed versions. Each backend stores the video reference in-memory (LRU, 50 items max) and returns a `continuation_id` in the result metadata.

### Workflow

```python
# Step 1: Generate initial video
result = generate_media(
    prompt="A cat sitting on a windowsill watching rain",
    mode="video",
    backend_type="google",
    duration=8
)
# result includes continuation_id, e.g. "veo_vid_a1b2c3d4e5f6"

# Step 2: Continue/extend with the continuation_id
result2 = generate_media(
    prompt="The cat jumps down and walks across the room",
    mode="video",
    continue_from="veo_vid_a1b2c3d4e5f6"
)
```

The `continue_from` prefix determines which backend handles the continuation:
- `sora_vid_*` -> OpenAI Sora remix
- `grok_vid_*` -> Grok video editing (re-render with new prompt, same duration)
- `veo_vid_*` -> Google Veo extension (append to timeline)

### OpenAI Sora Remix

Uses `videos.remix()` to re-edit an existing video with a new prompt. This creates
a new clip inspired by the source — it does **not** append time or extend the video.
Duration and model are inherited from the source video.
```python
generate_media(
    prompt="Same scene but in anime style",
    mode="video",
    continue_from="sora_vid_abc123def456"
)
```

### Grok Video Editing

Re-renders the video with a new prompt. The output retains the original duration,
aspect ratio, and resolution (capped at 720p). Only `prompt` is used — `duration`,
`aspect_ratio`, and `size` are ignored for editing.
```python
generate_media(
    prompt="Give the character a red hat",
    mode="video",
    continue_from="grok_vid_abc123def456"
)
```

### Google Veo Extension

Appends a new segment to a previously generated Veo video:
```python
generate_media(
    prompt="Extend with a dramatic camera pan",
    mode="video",
    continue_from="veo_vid_abc123def456"
)
```
Duration is always 8 seconds per extension (API requirement). Source video must
be 720p and 16:9 or 9:16.

**Extension constraints:**
- Resolution is forced to **720p** (API requirement)
- Only **16:9** and **9:16** aspect ratios are supported
- Each extension appends up to 7 seconds to the timeline
- Maximum 20 extensions (~141 seconds cumulative)
- Generated videos are retained for 2 days before expiry

### Notes

- Continuation IDs are stored in-memory and are lost on process restart.
- Each store has a max capacity of 50 items (LRU eviction).
- Each continuation produces a new `continuation_id` for further chaining.
- The `continue_from` parameter is not supported in batch mode.

## Image-to-Video (All Backends)

Animate a static image into video. Supported by all three video backends:

```python
# Grok — passes image_url to video.generate()
generate_media(
    prompt="Animate this scene with gentle camera movement",
    mode="video",
    backend_type="grok",
    input_images=["starting_frame.jpg"],
    duration=5
)

# OpenAI Sora — passes image as input_reference to videos.create()
generate_media(
    prompt="Bring this photo to life with subtle motion",
    mode="video",
    backend_type="openai",
    input_images=["photo.png"],
    duration=8
)

# Google Veo — passes image as Image object to generate_videos()
generate_media(
    prompt="Animate this illustration with a slow zoom",
    mode="video",
    backend_type="google",
    input_images=["illustration.png"]
)
```

### Backend Differences

| Backend | How Image Is Passed | Duration Range |
|---------|-------------------|----------------|
| Grok | `image_url` data URI | 1-15s |
| OpenAI Sora | `input_reference` (decoded bytes) | 4, 8, or 12s |
| Google Veo | `image=types.Image(...)` | 4-8s |

- The first image in `input_images` is used; additional images are ignored.
- Images must be PNG or JPEG, under 4MB.
- Input images are base64-encoded before being sent to the API.

## Reference Images (Google Veo)

Use `video_reference_images` to provide up to 3 images for style and content guidance. These are distinct from `input_images` (which sets the first frame for image-to-video).

```python
# Generate a video guided by reference images
generate_media(
    prompt="A cinematic scene of a forest at dawn",
    mode="video",
    backend_type="google",
    video_reference_images=["mood_board.png", "color_palette.jpg"],
    duration=8
)
```

- Up to 3 images accepted; excess images are silently trimmed.
- Images must be PNG or JPEG, under 4MB each.
- Reference images guide style/content but do not set the first frame.

## Advanced Veo Parameters

Google Veo also supports `negative_prompt` and resolution control:

```python
generate_media(
    prompt="A serene mountain landscape",
    mode="video",
    backend_type="google",
    negative_prompt="blurry, low quality, text",
    size="1080p",
    duration=8
)
```

| Parameter | Description |
|-----------|-------------|
| `negative_prompt` | What to exclude from generation |
| `size` | Resolution: `"720p"`, `"1080p"`, `"4k"` (1080p/4k require 8s duration; extensions are 720p only) |
