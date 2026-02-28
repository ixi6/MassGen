## 1. Phase 1 — Core Infrastructure

- [ ] 1.1 Add new fields to `GenerationConfig` in `_base.py`:
  - `mask_path`, `edit_mode`, `output_format`, `background`, `negative_prompt`, `seed`, `guidance_scale`
- [ ] 1.2 Lift `continue_from` gate in `generate_media.py` (line ~423):
  - Change `media_type != MediaType.IMAGE` → `media_type == MediaType.AUDIO`
- [ ] 1.3 Lift `input_images` gate in `generate_media.py` (line ~461):
  - Change `media_type == MediaType.IMAGE` → `media_type in (MediaType.IMAGE, MediaType.VIDEO)`
- [ ] 1.4 Pass new config fields through `generate_media()` → `GenerationConfig`
- [ ] 1.5 Write tests: `test_video_editing_generate_media_e2e.py`
  - [ ] `test_video_continue_from_routes_to_backend`
  - [ ] `test_audio_continue_from_still_blocked`
  - [ ] `test_video_input_images_routes_to_backend`
  - [ ] `test_new_config_fields_passed_through`

## 2. Phase 2 — Video Continuation

- [ ] 2.1 Add `_SoraVideoStore` class to `_video.py` (key format: `sora_vid_{uuid12}`)
- [ ] 2.2 Add `_GrokVideoStore` class to `_video.py` (key format: `grok_vid_{uuid12}`)
- [ ] 2.3 Add `_VeoVideoStore` class to `_video.py` (key format: `veo_vid_{uuid12}`)
- [ ] 2.4 Implement `_remix_video_openai(config)` — retrieve video_id, call `videos.remix()`, poll, download, store new ID
- [ ] 2.5 Update `_generate_video_openai()` — store `video.id` after success, return `continuation_id` in metadata
- [ ] 2.6 Update `_generate_video_grok()` — store `response.url` after success, handle `config.continue_from` → `video_url`
- [ ] 2.7 Update `_generate_video_google()` — store video reference after success, handle `config.continue_from` → `video=` param
- [ ] 2.8 Update `generate_video()` dispatcher — route `continue_from` to backend-specific handlers
- [ ] 2.9 Write tests: `test_video_continuation.py`
  - [ ] `test_sora_remix_calls_videos_remix`
  - [ ] `test_sora_remix_polls_and_downloads`
  - [ ] `test_sora_remix_stores_new_continuation_id`
  - [ ] `test_sora_remix_not_found_returns_error`
  - [ ] `test_grok_video_continuation_passes_video_url`
  - [ ] `test_grok_video_continuation_not_found_returns_error`
  - [ ] `test_veo_video_continuation_passes_video_param`
  - [ ] `test_veo_video_continuation_stores_new_id`
  - [ ] `test_sora_generation_stores_continuation_id`
  - [ ] `test_grok_generation_stores_continuation_id`
  - [ ] `test_veo_generation_stores_continuation_id`
- [ ] 2.10 Update `test_grok_multimedia_generation.py` — add Grok video continuation store tests

## 3. Phase 3 — Image-to-Video

- [ ] 3.1 Update `_generate_video_openai()` — if `config.input_images`, pass first image as `input_reference`
- [ ] 3.2 Update `_generate_video_google()` — if `config.input_images`, pass first image as `image=` param
- [ ] 3.3 Verify Grok image-to-video already works once gate is lifted (lines 334-338)
- [ ] 3.4 Update `_generate_single_with_input_images()` in `generate_media.py` — handle video mode
- [ ] 3.5 Write tests: `test_image_to_video.py`
  - [ ] `test_sora_image_to_video_passes_input_reference`
  - [ ] `test_sora_image_to_video_reads_local_file`
  - [ ] `test_veo_image_to_video_passes_image_param`
  - [ ] `test_grok_image_to_video_already_wired`
  - [ ] `test_generate_media_routes_video_input_images`
  - [ ] `test_video_input_images_fallback_chain`

## 4. Phase 4 — Image Inpainting (OpenAI)

- [ ] 4.1 Implement `_inpaint_image_openai(config)` in `_image.py`:
  - Validate mask PNG, load source image, call `client.images.edit()` with mask + background + output_format
- [ ] 4.2 Add routing logic: `mask_path` set + backend "openai" → `_inpaint_image_openai()`
- [ ] 4.3 Pass `mask_path` through `generate_media()` kwargs → `GenerationConfig`
- [ ] 4.4 Write tests: `test_image_inpainting.py`
  - [ ] `test_openai_inpainting_calls_images_edit`
  - [ ] `test_openai_inpainting_passes_mask_file`
  - [ ] `test_openai_inpainting_passes_background_param`
  - [ ] `test_openai_inpainting_passes_output_format`
  - [ ] `test_openai_inpainting_saves_result`
  - [ ] `test_openai_inpainting_returns_continuation_id`
  - [ ] `test_openai_inpainting_source_from_continuation`
  - [ ] `test_openai_inpainting_without_source_image_errors`
  - [ ] `test_inpainting_unsupported_backend_errors`
  - [ ] `test_generate_media_routes_mask_to_inpainting`

## 5. Phase 5 — Google Advanced Image Editing

- [ ] 5.1 Add `GenerationConfig` fields: `style_image_path`, `style_description`, `control_image_path`, `control_type`, `subject_image_path`, `subject_type`, `subject_description`, `mask_mode`, `segmentation_classes`
- [ ] 5.2 Implement `_build_google_reference_images(config)` helper — construct reference image list from config fields
- [ ] 5.3 Implement `_edit_image_google(config)` in `_image.py` — call `client.models.edit_image()` with reference images and `EditImageConfig`
- [ ] 5.4 Add routing: style/control/subject fields set + backend "google" → `_edit_image_google()`
- [ ] 5.5 Write tests: `test_google_image_editing.py`
  - [ ] `test_google_style_transfer_builds_reference`
  - [ ] `test_google_control_image_builds_reference`
  - [ ] `test_google_subject_consistency_builds_reference`
  - [ ] `test_google_mask_inpainting_builds_reference`
  - [ ] `test_google_semantic_segmentation_mask`
  - [ ] `test_google_edit_config_params`
  - [ ] `test_google_multiple_references_combined`
  - [ ] `test_google_edit_saves_result`
  - [ ] `test_google_edit_unsupported_for_gemini`

## 6. Phase 6 — Advanced Parameters

- [ ] 6.1 Wire `negative_prompt` to Google Imagen backends
- [ ] 6.2 Wire `seed` to Google Imagen backends
- [ ] 6.3 Wire `guidance_scale` to Google Imagen backends
- [ ] 6.4 Wire `output_format` to OpenAI (`output_format`) and Google (`output_mime_type`)
- [ ] 6.5 Wire `background` to OpenAI gpt-image-1
- [ ] 6.6 Wire output compression to OpenAI and Google
- [ ] 6.7 Write tests: `test_advanced_generation_params.py`
  - [ ] `test_negative_prompt_passed_to_google`
  - [ ] `test_negative_prompt_ignored_by_openai`
  - [ ] `test_seed_reproducibility_google`
  - [ ] `test_output_format_openai`
  - [ ] `test_output_format_google_mime_type`
  - [ ] `test_background_transparent_openai`
  - [ ] `test_compression_openai`

## 7. Phase 7 — System Prompt & Documentation

- [ ] 7.1 Add video editing guidance to `MultimodalToolsSection` in `system_prompt_sections.py`
- [ ] 7.2 Add image-to-video guidance
- [ ] 7.3 Add image inpainting guidance
- [ ] 7.4 Add Google advanced editing guidance
- [ ] 7.5 Add backend capabilities table
- [ ] 7.6 Update `TOOL.md` — new parameters in frontmatter, capability rows, usage examples
- [ ] 7.7 Update `generate_media.py` docstring — document all new parameters

## 8. Future Enhancements (Deferred)

- [ ] 8.1 Veo frame interpolation via `config.last_frame`
- [ ] 8.2 OpenAI image streaming via `partial_images`
- [ ] 8.3 Video batch mode
- [ ] 8.4 Audio continuation (when backends support it)
- [ ] 8.5 Live API test suite for editing workflows
