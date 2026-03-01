# Video Backends: Detailed Reference

## Grok (xAI)

**Model:** `grok-imagine-video` (default)

**Duration**: 1-15 seconds (continuous range, clamped to bounds).

**Resolution** (via `size` param):
- `"720p"` - Standard (default)
- `"480p"` - Lower resolution

**Aspect ratio**: Supported via `aspect_ratio` param.

**Image-to-video**: Supported. Pass image path in `input_images`. The first image is base64-encoded and sent as `image_url` data URI.

**Polling**: SDK handles polling internally with a 10-minute timeout (`timedelta(minutes=10)`).

**Response**: Returns a URL to the generated video, which is downloaded and saved locally.

**API path**: `client.video.generate()`.

```python
# Standard resolution, 10 seconds
generate_media(prompt="A bird flying over a lake", mode="video",
               backend_type="grok", duration=10, size="720p")

# Image-to-video
generate_media(prompt="Animate this scene", mode="video",
               backend_type="grok", input_images=["scene.jpg"])
```

## Google Veo

**Model:** `veo-3.1-generate-preview` (default)

**Duration**: 4-8 seconds (clamped to range).

**Aspect ratio**: Defaults to `"16:9"` if not specified. Supported values vary by model.

**Polling**: Custom polling every 20 seconds, max 10 minutes. Uses `client.operations.get()` to check status.

**API path**: `client.models.generate_videos()` with `GenerateVideosConfig`.

```python
# Default 16:9, 8 seconds
generate_media(prompt="A sunset over the ocean", mode="video",
               backend_type="google", duration=8)

# Custom aspect ratio
generate_media(prompt="A vertical video of rain", mode="video",
               backend_type="google", aspect_ratio="9:16", duration=6)
```

## OpenAI Sora

**Model:** `sora-2` (default)

**Duration**: Discrete values only: 4, 8, or 12 seconds. Requested duration is snapped to the nearest valid value.

**Polling**: Custom polling every 2 seconds. Uses `client.videos.retrieve()` to check status.

**Video download**: Uses `client.videos.download_content()` with `variant="video"`.

**API path**: `client.videos.create()`.

```python
# Will snap to 4 seconds (nearest valid)
generate_media(prompt="A quick intro animation", mode="video",
               backend_type="openai", duration=5)

# 12 second video
generate_media(prompt="A detailed product showcase", mode="video",
               backend_type="openai", duration=12)
```

## Backend Selection Priority

When `backend_type` is not specified (or `"auto"`):

1. **Grok** (if `XAI_API_KEY` set)
2. **Google** (if `GOOGLE_API_KEY` or `GEMINI_API_KEY` set)
3. **OpenAI** (if `OPENAI_API_KEY` set)

Override via YAML config:

```yaml
orchestrator:
  video_generation_backend: "google"
```

## Cost Considerations

Video generation is significantly more expensive than image generation. Consider:
- Using shorter durations for drafts
- Testing with Grok (generally faster) before switching to Veo/Sora for final quality
- Batch video generation is not supported (generate one at a time)
