## Context

MassGen's `generate_media` tool orchestrates image, video, and audio generation across multiple backends (OpenAI, Google, Grok, OpenRouter). It currently supports iterative editing only for images via `continue_from`, and blocks video continuation and image-to-video at the entry point. Meanwhile, all three video backends support continuation, all three support image-to-video, and OpenAI + Google offer advanced image editing features (inpainting, style transfer, subject consistency) that are completely unexposed.

This design covers 7 implementation phases to comprehensively wire multimedia editing capabilities through MassGen's generation pipeline.

**Stakeholders:** MassGen agents using `generate_media` tool, users who depend on iterative multimedia refinement.

**Constraints:**
- All new parameters must be optional with backward-compatible defaults
- Must follow existing continuation store pattern (in-memory `OrderedDict`, LRU eviction)
- Backend-specific features must degrade gracefully (ignored or clear error) on unsupported backends
- TDD required for all phases

## Goals / Non-Goals

**Goals:**
- Enable video continuation (edit/extend) through `continue_from` for Sora, Veo, and Grok
- Enable image-to-video animation across all video backends
- Add mask-based image inpainting via OpenAI `images.edit()`
- Expose Google Imagen's `edit_image()` reference-based editing (style, control, subject, mask)
- Wire advanced generation parameters (negative prompt, seed, output format, background) to supporting backends
- Provide comprehensive system prompt guidance for agents

**Non-Goals:**
- Audio editing/continuation (no backend supports this)
- Streaming/progressive image loading
- Video storyboard or multi-scene composition
- Custom model fine-tuning integration
- Video batch mode

## Research Findings — SDK Capability Matrix

### Image Backends

| Feature | OpenAI `images.edit()` (gpt-image-1) | OpenAI (dall-e-2) | Google `edit_image()` (Imagen) | Google (Gemini) | Grok |
|---------|---------------------------------------|-------------------|-------------------------------|-----------------|------|
| Text-to-image | `generate()` | `generate()` | `generate_images()` | `generate_content()` | `sample()` |
| Multi-turn continuation | `previous_response_id` | N/A | N/A | Chat-based | `image_url` (base64) |
| Inpainting (mask) | PNG transparent areas | PNG transparent areas | `MaskReferenceImage` | N/A | N/A |
| Style transfer | N/A | N/A | `StyleReferenceImage` | N/A | N/A |
| Control images | N/A | N/A | `ControlReferenceImage` | N/A | N/A |
| Subject consistency | N/A | N/A | `SubjectReferenceImage` | N/A | N/A |
| Background control | transparent/opaque/auto | N/A | N/A | N/A | N/A |
| Negative prompt | N/A | N/A | `negative_prompt` | N/A | N/A |
| Seed | N/A | N/A | `seed` | N/A | N/A |
| Output format | png/jpeg/webp | url/b64_json | `output_mime_type` | N/A | N/A |

### Video Backends

| Feature | OpenAI Sora | Google Veo | Grok |
|---------|-------------|------------|------|
| Text-to-video | `create(prompt)` | `generate_videos(prompt)` | `generate(prompt)` |
| Video continuation | `remix(video_id, prompt)` | `generate_videos(video=...)` | `generate(video_url=...)` |
| Image-to-video | `create(input_reference=...)` | `generate_videos(image=...)` | `generate(image_url=...)` |
| Frame interpolation | N/A | `config.last_frame` | N/A |
| Duration | 4/8/12s fixed | 4-8s | 1-15s |
| Continuable? | **Yes** (remix) | **Yes** (extend) | **Yes** (extend) |

### Verified SDK Signatures

```python
# OpenAI images.edit()
await client.images.edit(
    image: FileTypes, prompt: str, mask: FileTypes | None,
    model="gpt-image-1", background: str | None,
    output_format: str | None, quality: str | None,
    size: str | None, n: int | None,
) -> ImagesResponse

# Google edit_image()
client.models.edit_image(
    model: str, prompt: str,
    reference_images: list[ReferenceImage],  # Mask|Style|Control|Subject
    config: EditImageConfig(negative_prompt, guidance_scale, seed, edit_mode, ...),
)

# OpenAI Sora remix (no seconds/size — inherits from original)
await client.videos.remix(video_id: str, *, prompt: str) -> Video

# OpenAI Sora image-to-video
await client.videos.create(prompt: str, *, input_reference: FileTypes) -> Video

# Google Veo
client.models.generate_videos(
    model: str, prompt: str | None,
    image: ImageOrDict | None,   # image-to-video
    video: VideoOrDict | None,   # video extension
    config: GenerateVideosConfig(duration_seconds, aspect_ratio, last_frame),
)

# Grok video
await client.video.generate(
    prompt: str, model: str, *,
    image_url: str | None,   # image-to-video
    video_url: str | None,   # video extension
    duration: int, aspect_ratio: str | None,
    resolution: str, timeout: timedelta,
)
```

## Decisions

### Decision 1: Phase the work into 7 incremental phases

Each phase delivers independently testable value. Phases 1-3 (gates + video + image-to-video) are highest impact. Phases 4-6 add progressive sophistication. Phase 7 documents everything.

**Alternatives considered:**
- Big-bang implementation → rejected (too large for single review, harder to test)
- Backend-first (complete one backend before next) → rejected (cross-cutting gates need lifting first)

### Decision 2: Extend `GenerationConfig` with optional fields

The existing single-dataclass pattern works well. New fields are optional with `None` defaults. Backends ignore unsupported fields.

**Alternatives considered:**
- Separate `EditConfig` class → rejected (adds routing complexity)
- `extra_params` dict for everything → rejected (no type safety, poor discoverability)

### Decision 3: Video stores follow `_GrokImageStore` / `_GeminiChatStore` pattern

In-memory `OrderedDict` with LRU eviction at 50 items. Stores IDs/URLs, not bytes.

**Alternatives considered:**
- Disk-based → rejected (overengineered; we store IDs/URLs not video bytes)
- Global registry → rejected (module-level singletons match existing pattern)

### Decision 4: Gate change: `media_type != IMAGE` → `media_type == AUDIO`

Minimal change that unblocks video while keeping audio gated. New media types are allowed by default (safer — gate exceptions, not allowlist).

**Alternatives considered:**
- Allowlist `in (IMAGE, VIDEO)` → workable but breaks if new types added
- Remove gate entirely → too permissive for audio

### Decision 5: OpenAI inpainting via `images.edit()` as separate code path

The `edit()` endpoint has fundamentally different params (image + mask). Routing via `config.mask_path` is the clearest signal.

**Alternatives considered:**
- Always use `edit()` with no mask → rejected (different quotas, models)
- Add to continuation flow → rejected (inpainting is distinct from continuation)

### Decision 6: Google `edit_image()` is Phase 5 (separate from OpenAI inpainting)

Google's editing API uses 4 reference image types with their own config classes. Significant design work that shouldn't block simpler features.

**Alternatives considered:**
- Combine with Phase 4 → rejected (Google editing is much more complex)
- Defer indefinitely → rejected (style transfer + subject consistency are high-value)

### Decision 7: Recommended PR grouping

- **PR 1**: Phases 1-3 (tightly coupled — gate lifting enables both video continuation and image-to-video)
- **PR 2**: Phase 4 (self-contained OpenAI inpainting)
- **PR 3**: Phase 5 (complex Google editing, benefits from standalone review)
- **PR 4**: Phases 6+7 (polish + documentation)

## Architecture

### Data Flow — Video Continuation

```
Agent calls generate_media(continue_from="sora_vid_abc123", mode="video", prompt="Make it slow motion")
    │
    ▼
generate_media.py
    ├─ Gate check: media_type == AUDIO? No → proceed (was: media_type != IMAGE → block)
    ├─ Route to generate_video(config)
    │
    ▼
_video.py generate_video()
    ├─ config.continue_from is set
    ├─ backend == "openai" → _remix_video_openai(config)
    │      ├─ _sora_video_store.get("sora_vid_abc123") → "vid_original_id"
    │      ├─ client.videos.remix("vid_original_id", prompt="Make it slow motion")
    │      ├─ Poll for completion
    │      ├─ Download + save to output_path
    │      ├─ _sora_video_store.save(new_video.id) → "sora_vid_def456"
    │      └─ Return GenerationResult(continuation_id="sora_vid_def456")
    │
    ├─ backend == "grok" → _generate_video_grok(config)
    │      ├─ _grok_video_store.get(continue_from) → "https://..."
    │      ├─ generate(video_url="https://...", prompt=...)
    │      └─ Store new URL, return continuation_id
    │
    └─ backend == "google" → _generate_video_google(config)
           ├─ _veo_video_store.get(continue_from) → video_ref
           ├─ generate_videos(video=video_ref, prompt=...)
           └─ Store new ref, return continuation_id
```

### Data Flow — Image Inpainting

```
Agent calls generate_media(mode="image", mask_path="/path/to/mask.png", input_images=[...], prompt="Replace sky")
    │
    ▼
generate_media.py
    ├─ mask_path is set → route to image generation with mask
    │
    ▼
_image.py generate_image()
    ├─ config.mask_path is set, backend == "openai"
    │      └─ _inpaint_image_openai(config)
    │             ├─ Open source image from input_images[0]
    │             ├─ Open mask from config.mask_path
    │             ├─ client.images.edit(image=..., mask=..., prompt=..., background=..., output_format=...)
    │             ├─ Decode response, save to output_path
    │             └─ Return GenerationResult
    │
    └─ config.mask_path is set, backend == "google"
           └─ (Phase 5) _edit_image_google(config) with MaskReferenceImage
```

### Store Architecture

```
_video.py module-level stores:
    _sora_video_store = _SoraVideoStore(max_items=50)   # video_id strings
    _grok_video_store = _GrokVideoStore(max_items=50)   # video URL strings
    _veo_video_store  = _VeoVideoStore(max_items=50)    # video references

_image.py module-level stores (existing):
    _grok_image_store  = _GrokImageStore(max_items=50)  # base64 strings
    _gemini_chat_store = _GeminiChatStore(max_items=50) # chat objects

All stores: OrderedDict, LRU eviction, key format: "{prefix}_{uuid12}"
```

### `GenerationConfig` Extension

```python
@dataclass
class GenerationConfig:
    # Existing fields (unchanged)
    prompt: str
    output_path: Path
    media_type: MediaType
    backend: str | None = None
    model: str | None = None
    quality: str | None = None
    duration: int | None = None
    voice: str | None = None
    aspect_ratio: str | None = None
    size: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    input_images: list[dict[str, str]] = field(default_factory=list)
    input_image_paths: list[str] = field(default_factory=list)
    continue_from: str | None = None

    # Phase 1 — Core editing fields
    mask_path: Path | None = None              # Inpainting mask (PNG)
    edit_mode: str | None = None               # "inpaint" | "outpaint"
    output_format: str | None = None           # "png" | "jpeg" | "webp"
    background: str | None = None              # "transparent" | "opaque" | "auto"
    negative_prompt: str | None = None         # What to avoid
    seed: int | None = None                    # Reproducibility
    guidance_scale: float | None = None        # Prompt adherence

    # Phase 5 — Google advanced editing fields
    style_image_path: Path | None = None       # Style reference image
    style_description: str | None = None       # Style description text
    control_image_path: Path | None = None     # Structural control reference
    control_type: str | None = None            # Control guidance type
    subject_image_path: Path | None = None     # Subject reference image
    subject_type: str | None = None            # Subject type
    subject_description: str | None = None     # Subject description
    mask_mode: str | None = None               # "AUTO" | "FOREGROUND" | "BACKGROUND" | "USER_PROVIDED"
    segmentation_classes: list[int] | None = None  # Semantic mask classes
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Grok video SDK may not have `video_url` in installed version | Grok video continuation fails at runtime | Verify with live test; graceful error if param not accepted |
| Google Veo video extension poorly documented | May not work as expected | Test with live API; fall back to clear error message |
| In-memory stores lose state on process restart | Continuation chains broken between runs | Same limitation as existing image stores; acceptable for single-process model |
| OpenAI `images.edit()` has different rate limits | Agents may hit limits faster | Log rate limit errors clearly; agents can retry or switch backends |
| Google `edit_image()` reference types are complex | Hard for agents to construct correctly | System prompt guidance with clear examples (Phase 7) |
| `GenerationConfig` growing large with Phase 5 fields | Dataclass bloat | All fields optional; backends ignore irrelevant ones; Phase 5 fields only matter for Google |

## Migration Plan

No migration needed — all changes are additive with optional parameters. Existing `generate_media` calls continue to work identically. No schema changes, no config file changes.

## Open Questions

1. **Grok `video_url` param**: Does the installed xai-sdk version support this? Need live API test to confirm.
2. **Google Veo video extension**: Is the `video` param fully functional, or is it still experimental? Documentation is sparse.
3. **Phase 5 field explosion**: Should Google-specific fields (style_image_path, control_image_path, etc.) live in `GenerationConfig` or in `extra_params`? Current decision: typed fields for discoverability, but could revisit if dataclass becomes unwieldy.
4. **OpenAI `images.edit()` vs Response API continuation**: When both `mask_path` and `continue_from` are set, should inpainting take precedence? Current decision: yes — mask_path is a more explicit instruction.
