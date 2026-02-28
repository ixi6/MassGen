## ADDED Requirements

### Requirement: Video Continuation Editing

The system SHALL support iterative video editing via the `continue_from` parameter for all video backends that support it.

When `continue_from` is provided with `mode="video"`, the system SHALL route to the appropriate backend's continuation mechanism:
- OpenAI Sora: `videos.remix(video_id, prompt)` for remixing with a new prompt
- Google Veo: `generate_videos(video=video_ref)` for video extension
- Grok: `video.generate(video_url=url)` for video extension

Each video backend SHALL maintain an in-memory continuation store that maps continuation IDs to backend-specific references (video IDs, URLs, or file references). After each successful generation, the system SHALL return a `continuation_id` in the result metadata.

#### Scenario: Sora video remix
- **WHEN** an agent calls `generate_media(mode="video", continue_from="sora_vid_abc123", prompt="Make it slow motion")`
- **THEN** the system retrieves the stored Sora video ID and calls `videos.remix()` with the new prompt
- **THEN** the result includes a new `continuation_id` for further editing

#### Scenario: Grok video extension
- **WHEN** an agent calls `generate_media(mode="video", continue_from="grok_vid_xyz789", prompt="Continue the scene")`
- **THEN** the system retrieves the stored video URL and passes it as `video_url` to `video.generate()`

#### Scenario: Veo video extension
- **WHEN** an agent calls `generate_media(mode="video", continue_from="veo_vid_def456", prompt="Extend the animation")`
- **THEN** the system retrieves the stored video reference and passes it as `video=` to `generate_videos()`

#### Scenario: Invalid continuation ID
- **WHEN** an agent provides a `continue_from` ID that does not exist in the store
- **THEN** the system returns an error result with a clear message

#### Scenario: Audio continuation blocked
- **WHEN** an agent calls `generate_media(mode="audio", continue_from="...")`
- **THEN** the system returns an error result indicating audio continuation is not supported

---

### Requirement: Image-to-Video Generation

The system SHALL support animating static images into videos by accepting `input_images` with `mode="video"`.

All video backends (OpenAI Sora, Google Veo, Grok) SHALL accept input images and use them as starting frames for video generation.

#### Scenario: Sora image-to-video
- **WHEN** an agent calls `generate_media(mode="video", input_images=[{"image_url": "..."}], prompt="Animate this")`
- **THEN** the system passes the first image as `input_reference` to `videos.create()`

#### Scenario: Veo image-to-video
- **WHEN** an agent provides an image with `mode="video"` and backend is Google
- **THEN** the system passes the image as the `image=` parameter to `generate_videos()`

#### Scenario: Grok image-to-video
- **WHEN** an agent provides an image with `mode="video"` and backend is Grok
- **THEN** the system passes the image URL as `image_url` to `video.generate()`

---

### Requirement: Image Inpainting with Masks

The system SHALL support mask-based image editing via the `mask_path` parameter, routing to OpenAI's `images.edit()` endpoint.

When `mask_path` is provided, the system SHALL:
- Open the mask file (PNG with transparent areas indicating edit regions)
- Open the source image from `input_images` or continuation store
- Call the backend's inpainting endpoint with the mask, source image, and prompt

#### Scenario: OpenAI mask-based inpainting
- **WHEN** an agent calls `generate_media(mode="image", mask_path="/path/to/mask.png", input_images=[...], prompt="Replace the sky")`
- **THEN** the system calls `client.images.edit(image=..., mask=..., prompt=...)` on the OpenAI backend

#### Scenario: Inpainting with background control
- **WHEN** an agent sets `background="transparent"` along with a mask
- **THEN** the system passes the `background` parameter to `images.edit()`

#### Scenario: Unsupported backend for inpainting
- **WHEN** an agent provides `mask_path` with a backend that does not support inpainting (e.g., Grok)
- **THEN** the system returns a clear error message indicating the backend does not support mask-based editing

---

### Requirement: Google Advanced Image Editing

The system SHALL support Google Imagen's reference-based editing via `edit_image()` for style transfer, structural control, subject consistency, and semantic inpainting.

#### Scenario: Style transfer
- **WHEN** an agent provides `style_image_path` and `style_description` with backend "google"
- **THEN** the system constructs a `StyleReferenceImage` and calls `edit_image()` with it

#### Scenario: Structural control
- **WHEN** an agent provides `control_image_path` and `control_type` with backend "google"
- **THEN** the system constructs a `ControlReferenceImage` and calls `edit_image()`

#### Scenario: Subject consistency
- **WHEN** an agent provides `subject_image_path`, `subject_type`, and `subject_description` with backend "google"
- **THEN** the system constructs a `SubjectReferenceImage` and calls `edit_image()`

#### Scenario: Semantic mask inpainting
- **WHEN** an agent provides `mask_mode="AUTO"` with backend "google"
- **THEN** the system constructs a `MaskReferenceImage` with auto mask mode

---

### Requirement: Advanced Generation Parameters

The system SHALL support advanced generation parameters that are forwarded to backends that accept them and silently ignored by backends that do not.

Supported parameters:
- `negative_prompt`: What to avoid in generation (Google Imagen)
- `seed`: Reproducible generation (Google Imagen)
- `guidance_scale`: Prompt adherence strength (Google Imagen)
- `output_format`: Output file format — "png", "jpeg", "webp" (OpenAI, Google)
- `background`: Background handling — "transparent", "opaque", "auto" (OpenAI gpt-image-1)

#### Scenario: Negative prompt forwarded to Google
- **WHEN** an agent provides `negative_prompt="blurry, low quality"` with Google backend
- **THEN** the system includes `negative_prompt` in the Google Imagen config

#### Scenario: Unsupported parameter silently ignored
- **WHEN** an agent provides `negative_prompt` with OpenAI backend (which doesn't support it)
- **THEN** the system generates the image normally without error

#### Scenario: Seed reproducibility
- **WHEN** an agent provides `seed=42` with Google backend
- **THEN** the system includes `seed=42` in the generation config for deterministic output

---

### Requirement: Multimedia Editing System Prompt Guidance

The system prompt SHALL include guidance for agents on all multimedia editing capabilities, including:
- Video editing via `continue_from` with per-backend behavior
- Image-to-video via `input_images` with `mode="video"`
- Image inpainting via `mask_path`
- Google advanced editing via reference images
- Backend capabilities reference table

#### Scenario: Agent receives editing guidance
- **WHEN** an agent is initialized with multimedia tools enabled
- **THEN** the system prompt includes a backend capabilities table showing which features each backend supports
- **THEN** the system prompt includes usage patterns for video editing, image-to-video, and inpainting
