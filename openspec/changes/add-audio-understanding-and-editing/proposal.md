# Change: Comprehensive Audio Understanding & Editing Capabilities

## Why

MAS-334: MassGen currently uses speech-to-text (Whisper/Gemini transcription) for audio understanding. This loses critical information about *how* something was said — tone, emotion, pacing, emphasis, background sounds — which is essential for quality refinement of audio outputs. An agent can't improve a voiceover's delivery if it only sees the transcript.

Additionally, the audio tooling is fragmented across multiple disconnected modules (`understand_audio.py`, `_audio.py`, `text_to_speech_continue_generation.py`) and the rich capabilities in our installed SDKs (ElevenLabs voice cloning, audio isolation, dubbing, speech-to-speech; OpenAI Realtime API, audio translations) are completely unused.

## What Changes

- **Phase 1 — Rich Audio Understanding**: Replace STT-only audio analysis with `gpt-4o-audio-preview` via Chat Completions (accepts raw audio, understands prosody/tone/emotion) and upgrade Gemini audio analysis prompting. Add OpenAI Realtime API as an alternative for streaming audio understanding.
- **Phase 2 — Audio Editing & Transformation**: Wire ElevenLabs speech-to-speech (voice conversion), audio isolation (noise removal), and voice design (create voices from descriptions).
- **Phase 3 — Voice Cloning**: Expose ElevenLabs instant voice cloning (IVC) — create custom voices from 1-3 minute audio samples.
- **Phase 4 — Audio Translation & Dubbing**: Wire OpenAI audio translation (any language → English) and ElevenLabs dubbing (full video/audio localization with speaker voice preservation).
- **Phase 5 — Advanced TTS Features**: Wire OpenAI `instructions` parameter for `gpt-4o-mini-tts`, voice speed control, ElevenLabs voice settings (stability, similarity_boost), seed for reproducible generation.
- **Phase 6 — Documentation & System Prompts**: Update system prompt guidance, TOOL.md, and consolidate the fragmented audio tool surface.

## Impact

- Affected specs: `multimedia-generation`
- Affected code:
  - `massgen/tool/_multimodal_tools/understand_audio.py` — Rich audio understanding via audio-capable models
  - `massgen/tool/_multimodal_tools/generation/_audio.py` — Voice conversion, audio isolation, voice cloning, advanced TTS
  - `massgen/tool/_multimodal_tools/generation/_base.py` — New audio config fields
  - `massgen/tool/_multimodal_tools/generation/generate_media.py` — New audio modes routing
  - `massgen/system_prompt_sections.py` — Audio guidance
  - `massgen/tool/_multimodal_tools/TOOL.md` — Audio documentation
- No breaking changes — all additive with optional parameters
