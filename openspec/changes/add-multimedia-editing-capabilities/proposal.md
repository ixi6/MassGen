# Change: Add Comprehensive Multimedia Editing Capabilities

## Why

MassGen's `generate_media` tool currently supports only basic text-to-image/video/audio generation and image-only continuation editing. Our backend SDKs already provide rich editing capabilities — inpainting with masks, video remixing, image-to-video animation, style transfer, subject consistency — but none of it is wired through. Two hard gates in `generate_media.py` block all video editing and image-to-video entirely.

This severely limits agents' ability to iteratively refine multimedia outputs, which is central to MassGen's quality-through-refinement philosophy. Linear issue: MAS-333.

## What Changes

- **Phase 1 — Core Infrastructure**: Extend `GenerationConfig` with new fields (`mask_path`, `edit_mode`, `output_format`, `background`, `negative_prompt`, `seed`, `guidance_scale`). Lift entry-point gates in `generate_media.py` that block video continuation and image-to-video.
- **Phase 2 — Video Continuation**: Sora remix via `videos.remix()`, Grok extension via `video_url`, Veo extension via `video` param. Add in-memory stores (`_SoraVideoStore`, `_GrokVideoStore`, `_VeoVideoStore`).
- **Phase 3 — Image-to-Video**: Sora via `input_reference`, Veo via `image` param, Grok via `image_url` (already wired internally, just needs gate lifted).
- **Phase 4 — Image Inpainting**: OpenAI `images.edit()` with mask support, background control, output format selection.
- **Phase 5 — Google Advanced Editing**: Google `edit_image()` API with `StyleReferenceImage`, `ControlReferenceImage`, `SubjectReferenceImage`, `MaskReferenceImage`.
- **Phase 6 — Advanced Parameters**: Wire negative prompt, seed, guidance scale, output format, background control, compression to supporting backends.
- **Phase 7 — Documentation**: System prompt guidance and TOOL.md updates for all new capabilities.

No breaking changes — all new parameters are optional with backward-compatible defaults.

## Impact

- Affected specs: `multimedia-generation`
- Affected code:
  - `massgen/tool/_multimodal_tools/generation/_base.py` — GenerationConfig extensions
  - `massgen/tool/_multimodal_tools/generation/_video.py` — Video continuation stores + remix/extension + image-to-video
  - `massgen/tool/_multimodal_tools/generation/_image.py` — OpenAI inpainting + Google edit_image
  - `massgen/tool/_multimodal_tools/generation/generate_media.py` — Gate lifting + new param routing
  - `massgen/system_prompt_sections.py` — Agent guidance for editing workflows
  - `massgen/tool/_multimodal_tools/TOOL.md` — User-facing documentation
