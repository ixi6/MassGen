## 1. Phase 1 — Rich Audio Understanding (MAS-334)

- [ ] 1.1 Add `gpt-4o-audio-preview` backend to `understand_audio.py`:
  - [ ] 1.1.1 Add `_understand_audio_openai_native()` function using Chat Completions with audio input
  - [ ] 1.1.2 Base64-encode audio file, send as `input_audio` content type
  - [ ] 1.1.3 Build rich analysis prompt: transcription + tone + emotion + pacing + emphasis + speaker characteristics
  - [ ] 1.1.4 Update backend selection: when OpenAI selected, use `gpt-4o-audio-preview` instead of Whisper
  - [ ] 1.1.5 Keep Whisper as explicit fallback for cheap transcription-only mode
- [ ] 1.2 Enhance Gemini audio analysis prompting:
  - [ ] 1.2.1 Update default prompt to request paralinguistic analysis (not just transcription)
  - [ ] 1.2.2 Add structured output guidance: delivery, tone, emotion, pacing sections
- [ ] 1.3 Add `analysis_mode` parameter to `understand_audio()`:
  - `"transcription"` — STT only (fast/cheap, Whisper or Gemini)
  - `"rich"` — Full prosody/tone/emotion analysis (gpt-4o-audio-preview or enhanced Gemini)
  - Default: `"rich"` (MAS-334's whole point)
- [ ] 1.4 Write tests: `test_rich_audio_understanding.py`
  - [ ] `test_openai_native_audio_sends_input_audio_content`
  - [ ] `test_openai_native_audio_uses_gpt4o_audio_preview`
  - [ ] `test_rich_analysis_includes_tone_and_emotion`
  - [ ] `test_transcription_mode_uses_whisper`
  - [ ] `test_gemini_enhanced_prompt_requests_paralinguistics`
  - [ ] `test_backend_selection_prefers_native_audio_model`
  - [ ] `test_fallback_to_whisper_when_audio_preview_fails`

## 2. Phase 2 — Audio Editing & Transformation

- [ ] 2.1 Add `input_audio_path` field to `GenerationConfig` in `_base.py`
- [ ] 2.2 Implement `_convert_voice_elevenlabs(config)` in `_audio.py`:
  - Resolve target voice UUID, open source audio, call `speech_to_speech.convert()`
  - Support `remove_background_noise` option
- [ ] 2.3 Implement `_isolate_audio_elevenlabs(config)` in `_audio.py`:
  - Open source audio, call `audio_isolation.convert()`, save cleaned output
- [ ] 2.4 Implement `_design_voice_elevenlabs(config)` in `_audio.py`:
  - Call `text_to_voice.create_previews()` with `voice_description`
  - Return preview audio + `generated_voice_id` in metadata
- [ ] 2.5 Update `generate_audio()` dispatcher:
  - [ ] Add `audio_type == "voice_conversion"` → `_convert_voice_elevenlabs()`
  - [ ] Add `audio_type == "audio_isolation"` → `_isolate_audio_elevenlabs()`
  - [ ] Add `audio_type == "voice_design"` → `_design_voice_elevenlabs()`
- [ ] 2.6 Update `generate_media()` to pass `input_audio_path` through to config
- [ ] 2.7 Write tests: `test_audio_editing.py`
  - [ ] `test_voice_conversion_calls_speech_to_speech`
  - [ ] `test_voice_conversion_resolves_voice_name`
  - [ ] `test_voice_conversion_passes_remove_noise`
  - [ ] `test_audio_isolation_calls_audio_isolation`
  - [ ] `test_audio_isolation_saves_output`
  - [ ] `test_voice_design_calls_create_previews`
  - [ ] `test_voice_design_returns_voice_id_in_metadata`
  - [ ] `test_voice_conversion_missing_key_returns_error`
  - [ ] `test_voice_conversion_missing_input_audio_returns_error`

## 3. Phase 3 — Voice Cloning

- [ ] 3.1 Add `voice_samples` field to `GenerationConfig` (list of Paths)
- [ ] 3.2 Implement `_clone_voice_elevenlabs(config)` in `_audio.py`:
  - Open sample files, call `voices.ivc.create()`, return new voice UUID
  - Support `remove_background_noise` for cleaning samples
- [ ] 3.3 Add `audio_type == "voice_clone"` to dispatcher
- [ ] 3.4 Update `generate_media()` to accept `voice_samples` parameter
- [ ] 3.5 Write tests: `test_voice_cloning.py`
  - [ ] `test_voice_clone_calls_ivc_create`
  - [ ] `test_voice_clone_passes_sample_files`
  - [ ] `test_voice_clone_returns_voice_uuid`
  - [ ] `test_voice_clone_removes_background_noise`
  - [ ] `test_voice_clone_missing_samples_errors`
  - [ ] `test_voice_clone_missing_key_errors`

## 4. Phase 4 — Audio Translation & Dubbing

- [ ] 4.1 Add `target_language` and `source_language` fields to `GenerationConfig`
- [ ] 4.2 Implement `_translate_audio_openai(config)` in `_audio.py`:
  - Call `audio.translations.create()`, return translated text
- [ ] 4.3 Implement `_dub_elevenlabs(config)` in `_audio.py`:
  - Call `dubbing.create()` with source/target languages
  - Poll for completion via `dubbing.get()`
  - Download and save dubbed output
- [ ] 4.4 Add dispatcher entries for `audio_type == "translation"` and `"dubbing"`
- [ ] 4.5 Write tests: `test_audio_translation.py`
  - [ ] `test_translation_calls_openai_translations`
  - [ ] `test_translation_returns_english_text`
  - [ ] `test_dubbing_calls_elevenlabs_dubbing`
  - [ ] `test_dubbing_polls_for_completion`
  - [ ] `test_dubbing_saves_output`
  - [ ] `test_dubbing_passes_language_params`
  - [ ] `test_translation_missing_input_errors`

## 5. Phase 5 — Advanced TTS Features

- [ ] 5.1 Add fields to `GenerationConfig`: `instructions`, `speed`, `voice_stability`, `voice_similarity`
- [ ] 5.2 Wire `instructions` param to OpenAI `gpt-4o-mini-tts` in `_generate_audio_openai()`
- [ ] 5.3 Wire `speed` param to OpenAI TTS (0.25-4.0x)
- [ ] 5.4 Wire `voice_settings` (stability + similarity) to ElevenLabs TTS
- [ ] 5.5 Wire `seed` param to ElevenLabs TTS for reproducible generation
- [ ] 5.6 Update `generate_media()` to accept and pass these parameters
- [ ] 5.7 Write tests: `test_advanced_tts.py`
  - [ ] `test_openai_tts_passes_instructions`
  - [ ] `test_openai_tts_passes_speed`
  - [ ] `test_elevenlabs_tts_passes_voice_settings`
  - [ ] `test_elevenlabs_tts_passes_seed`
  - [ ] `test_instructions_ignored_by_elevenlabs`
  - [ ] `test_speed_clamped_to_valid_range`

## 6. Phase 6 — Documentation & System Prompts

- [ ] 6.1 Add audio understanding guidance to `MultimodalToolsSection`:
  - Rich analysis mode vs transcription-only
  - When to use each backend
- [ ] 6.2 Add audio editing guidance:
  - Voice conversion workflow
  - Audio isolation for pre-processing
  - Voice design flow (preview → save)
- [ ] 6.3 Add voice cloning guidance (with consent note)
- [ ] 6.4 Add translation/dubbing guidance
- [ ] 6.5 Add advanced TTS guidance (instructions, speed, voice settings)
- [ ] 6.6 Add audio capabilities table to system prompt
- [ ] 6.7 Update `TOOL.md`:
  - [ ] New parameters in frontmatter
  - [ ] New `audio_type` values documented
  - [ ] Audio editing examples
  - [ ] Audio understanding modes documented
- [ ] 6.8 Update `generate_media.py` docstring with all new audio parameters

## 7. Future Enhancements (Deferred)

- [ ] 7.1 OpenAI Realtime API for live voice interaction (separate Linear issue)
- [ ] 7.2 ElevenLabs Professional Voice Cloning (PVC) — enterprise feature
- [ ] 7.3 ElevenLabs realtime TTS streaming via WebSocket
- [ ] 7.4 Streaming audio transcription (OpenAI + ElevenLabs)
- [ ] 7.5 Audio continuation / editing chains (like image continuation)
- [ ] 7.6 ElevenLabs voice library search / discovery
- [ ] 7.7 Multi-channel audio transcription (ElevenLabs)
- [ ] 7.8 Entity detection in audio (PII, PHI — ElevenLabs)
