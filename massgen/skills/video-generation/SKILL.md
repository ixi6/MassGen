---
name: video-generation
description: Guide to video generation in MassGen. Use when creating videos from text prompts or images across Grok, Google Veo, and OpenAI Sora backends.
---

# Video Generation

Generate videos using `generate_media` with `mode="video"`. The system auto-selects the best backend based on available API keys.

## Quick Start

```python
# Simple text-to-video (auto-selects backend)
generate_media(prompt="A robot walking through a city", mode="video")

# Specify backend and duration
generate_media(prompt="Ocean waves crashing on rocks", mode="video",
               backend_type="google", duration=8)

# With aspect ratio
generate_media(prompt="A timelapse of clouds", mode="video",
               backend_type="grok", aspect_ratio="16:9", duration=10)
```

## Backend Comparison

| Backend | Default Model | Duration Range | Default Duration | Resolutions | API Key |
|---------|--------------|----------------|-----------------|-------------|---------|
| **Grok** (priority 1) | `grok-imagine-video` | 1-15s | 5s | 480p, 720p | `XAI_API_KEY` |
| **Google Veo** (priority 2) | `veo-3.1-generate-preview` | 4-8s | 8s | 720p, 1080p, 4K (use `size`); default 16:9 | `GOOGLE_API_KEY` |
| **OpenAI Sora** (priority 3) | `sora-2` | 4, 8, or 12s (discrete) | 4s | Standard | `OPENAI_API_KEY` |

## Key Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `prompt` | Text description of the video | `"A drone flying over mountains"` |
| `backend_type` | Force a specific backend | `"grok"`, `"google"`, `"openai"` |
| `model` | Override default model | `"veo-3.1-generate-preview"` |
| `duration` | Video length in seconds | `8` (clamped to backend limits) |
| `aspect_ratio` | Video aspect ratio | `"16:9"`, `"9:16"`, `"1:1"` |
| `size` | Resolution (Grok: 480p/720p; Veo: 720p/1080p/4k) | `"720p"`, `"1080p"`, `"4k"` |
| `input_images` | Source image for image-to-video | `["starting_frame.jpg"]` |
| `video_reference_images` | Style/content guide images (Veo, up to 3) | `["ref1.png", "ref2.png"]` |
| `negative_prompt` | What to exclude (Veo) | `"blurry, low quality"` |

## Duration Handling

Each backend has different duration constraints. `generate_media` automatically clamps the requested duration:

- **Grok**: Continuous range 1-15s (clamped to bounds)
- **Google Veo**: Continuous range 4-8s (clamped to bounds), defaults to 16:9 aspect ratio
- **OpenAI Sora**: Discrete values only (4, 8, or 12s) - snaps to nearest valid value

A warning is logged if duration is adjusted.

## Image-to-Video

All three video backends support starting video from an existing image via `input_images`:

```python
generate_media(
    prompt="Animate this scene with gentle movement",
    mode="video",
    input_images=["scene.jpg"],
    duration=5
)
```

The first image in `input_images` is used; additional images are ignored.

## Generation Time

Video generation is significantly slower than images. All backends use polling:
- **Grok**: SDK handles polling internally (up to 10 min timeout)
- **Google Veo**: Custom polling every 20s (up to 10 min)
- **OpenAI Sora**: Custom polling every 2s

## Veo 3.1: Native Audio

Veo 3.1 generates audio (dialogue, SFX, ambient) automatically from prompt content. No extra parameter needed — just describe the sounds:

- **Dialogue**: Use quotation marks in prompt (`"Hello," she said.`)
- **Sound effects**: Describe sounds (`tires screeching, engine roaring`)
- **Ambient**: Describe atmosphere (`eerie hum resonates through the hallway`)

## Veo 3.1: Extension Constraints

When extending videos via `continue_from` with a `veo_vid_*` ID:
- Resolution is forced to **720p** (API requirement for extensions)
- Only **16:9** and **9:16** aspect ratios are supported
- Each extension adds up to 7 seconds (API limit: 20 extensions, ~141s total)
- Generated videos are retained for 2 days before expiry

## Need More Control?

- **Per-backend resolution, duration details, and quirks**: See [references/backends.md](references/backends.md)
- **Video continuation, remix, and image-to-video**: See [references/editing.md](references/editing.md)
