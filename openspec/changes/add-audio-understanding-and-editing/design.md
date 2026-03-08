## Context

MassGen's audio capabilities are fragmented across three disconnected modules and underutilize the installed SDKs. The core problem (MAS-334) is that audio understanding via STT loses tone, emotion, pacing, and other paralinguistic cues that are essential for iterative refinement of audio outputs.

**Current audio modules:**
- `understand_audio.py` — STT via Gemini `generate_content()` or OpenAI Whisper transcription
- `_audio.py` — TTS via ElevenLabs/OpenAI, music via ElevenLabs, SFX via ElevenLabs
- `text_to_speech_continue_generation.py` — Experimental `gpt-4o-audio-preview` for continued speech

**What agents lose with STT-only understanding:**
- Tone and emotional delivery (sarcasm, warmth, urgency)
- Pacing and timing (pauses, rhythm, speed variations)
- Emphasis patterns (stressed words, inflection)
- Background audio context (ambient sounds, music underneath)
- Speaker characteristics (age, accent, vocal quality)

**Stakeholders:** MassGen agents generating/refining audio, users who need high-quality voice output.

**Constraints:**
- OpenAI Realtime API requires WebSocket connection (not simple HTTP)
- ElevenLabs voice cloning has legal/ethical considerations (consent required)
- Audio files can be large; processing must handle streaming
- All new features must be optional with backward-compatible defaults

## Goals / Non-Goals

**Goals:**
1. Enable rich audio understanding that preserves prosody, tone, and emotion (MAS-334)
2. Expose audio editing capabilities (voice conversion, noise removal)
3. Enable custom voice creation (cloning from samples, design from descriptions)
4. Add audio/video translation and dubbing
5. Wire advanced TTS parameters (instructions, speed, voice settings)
6. Consolidate fragmented audio tooling into coherent interfaces

**Non-Goals:**
- Real-time live conversation agents (Realtime API streaming for live use)
- Audio mixing or DAW-like editing
- SSML/phoneme-level pronunciation control
- Video generation from audio (audio-to-video)

## Research Findings — SDK Capability Matrix

### Audio Understanding

| Feature | OpenAI `gpt-4o-audio-preview` (Chat) | OpenAI Realtime API | Gemini (current) | OpenAI Whisper (current) |
|---------|---------------------------------------|---------------------|-------------------|-------------------------|
| Transcription | Yes | Yes | Yes | Yes |
| Tone/emotion understanding | **Yes** (native audio input) | **Yes** | **Yes** (multimodal) | No (text only) |
| Speaker diarization | No | No | Yes | No |
| Background sound detection | **Yes** | **Yes** | **Yes** | No |
| Streaming input | No | **Yes** (WebSocket) | No | No |
| Audio output | **Yes** (can respond with audio) | **Yes** | No | No |
| Cost | Chat token rates | $32/$64 per 1M audio tokens | Standard Gemini rates | Whisper rates |

**Key insight:** `gpt-4o-audio-preview` via Chat Completions API is the simplest path to rich audio understanding — it accepts raw audio as input content and can analyze prosody/tone/emotion without transcription loss. No WebSocket required.

### Audio Editing & Transformation

| Feature | ElevenLabs | OpenAI | Google | Grok |
|---------|------------|--------|--------|------|
| Text-to-Speech | `text_to_speech.convert()` | `audio.speech.create()` | N/A | N/A |
| Voice conversion (speech-to-speech) | `speech_to_speech.convert()` + `.stream()` | N/A | N/A | N/A |
| Audio isolation (noise removal) | `audio_isolation.convert()` + `.stream()` | N/A | N/A | N/A |
| Voice design (create from description) | `text_to_voice.create_previews()` + `.create()` | N/A | N/A | N/A |
| Instant voice cloning | `voices.ivc.create()` | N/A | N/A | N/A |
| Audio translation | N/A | `audio.translations.create()` | N/A | N/A |
| Dubbing/localization | `dubbing.create()` | N/A | N/A | N/A |
| Music generation | `music.compose()` | N/A | N/A | N/A |
| Sound effects | `text_to_sound_effects.convert()` | N/A | N/A | N/A |
| TTS voice instructions | N/A | `instructions` param (gpt-4o-mini-tts) | N/A | N/A |
| Speed control | N/A | `speed` (0.25-4.0x) | N/A | N/A |
| Voice settings | `stability`, `similarity_boost` | N/A | N/A | N/A |
| Seed/reproducibility | `seed` param | N/A | N/A | N/A |

### Verified SDK Signatures

```python
# --- AUDIO UNDERSTANDING ---

# OpenAI gpt-4o-audio-preview — Rich audio understanding via Chat API
# Send audio as input content, get analysis of tone/emotion/pacing
await client.chat.completions.create(
    model="gpt-4o-audio-preview",
    modalities=["text"],              # text output (analysis)
    messages=[{
        "role": "user",
        "content": [
            {"type": "input_audio", "input_audio": {
                "data": base64_audio,      # base64-encoded audio
                "format": "wav",           # wav, mp3, etc.
            }},
            {"type": "text", "text": "Analyze the tone, emotion, pacing..."},
        ],
    }],
)

# OpenAI Realtime API — WebSocket-based audio understanding
async with client.realtime.connect(model="gpt-realtime") as conn:
    await conn.session.update(session={
        "type": "realtime",
        "modalities": ["text"],           # text-only output for analysis
        "input_audio_format": "pcm16",    # pcm16, g711_ulaw, g711_alaw
        "instructions": "Analyze the audio for tone, emotion, delivery...",
    })
    await conn.input_audio_buffer.append(audio=base64_pcm_bytes)
    await conn.input_audio_buffer.commit()
    await conn.response.create()
    async for event in conn:
        if event.type == "response.output_text.delta":
            # Rich audio analysis text
            ...

# --- AUDIO EDITING ---

# ElevenLabs speech-to-speech (voice conversion)
result = await client.speech_to_speech.convert(
    voice_id="target_voice_uuid",
    audio=open("input.wav", "rb"),
    model_id="eleven_english_sts_v2",
    remove_background_noise=True,          # Optional: isolate voice first
    output_format="mp3_44100_128",
    seed=42,                               # Reproducible output
)

# ElevenLabs audio isolation (noise removal)
result = await client.audio_isolation.convert(
    audio=open("noisy.wav", "rb"),
)
# Returns: clean audio bytes (streaming also available)

# ElevenLabs voice design (create voice from description)
previews = await client.text_to_voice.create_previews(
    voice_description="A warm, authoritative male voice with a slight British accent",
    text="Sample text to preview the voice",
)
# Then save: await client.text_to_voice.create(generated_voice_id=previews[0].id, name="Custom Voice")

# ElevenLabs instant voice cloning
voice = await client.voices.ivc.create(
    name="Cloned Voice",
    files=[open("sample1.mp3", "rb"), open("sample2.mp3", "rb")],
    remove_background_noise=True,
    description="Voice cloned from speaker samples",
)

# ElevenLabs dubbing
job = await client.dubbing.create(
    file=open("video.mp4", "rb"),
    source_lang="en",
    target_lang="es",
    num_speakers=2,
    highest_resolution=True,
)

# OpenAI audio translation (any language → English)
translation = await client.audio.translations.create(
    file=open("spanish_audio.mp3", "rb"),
    model="whisper-1",
    response_format="text",
)

# --- ADVANCED TTS ---

# OpenAI TTS with instructions
response = await client.audio.speech.create(
    model="gpt-4o-mini-tts",
    voice="coral",
    input="Hello, welcome to our presentation.",
    instructions="Speak in a warm, professional tone with slight excitement",
    speed=1.1,                             # 0.25-4.0x
    response_format="mp3",
)

# ElevenLabs TTS with voice settings + seed
result = await client.text_to_speech.convert(
    voice_id="21m00Tcm4TlvDq8ikWAM",
    text="Hello world",
    model_id="eleven_multilingual_v2",
    voice_settings='{"stability": 0.7, "similarity_boost": 0.8}',
    seed=42,
    output_format="mp3_44100_128",
)
```

## Decisions

### Decision 1: Use `gpt-4o-audio-preview` via Chat API as the primary rich audio understanding path (not Realtime API)

**Rationale:** The Chat Completions API with `gpt-4o-audio-preview` accepts raw audio as input content and can analyze prosody, tone, and emotion — exactly what MAS-334 needs. It's a standard HTTP request (no WebSocket), works with existing `AsyncOpenAI` client, and fits the existing `understand_audio()` architecture.

The Realtime API is designed for low-latency bidirectional streaming — overkill for analyzing pre-recorded audio files. It adds WebSocket complexity and costs more per token.

**Alternatives considered:**
- Realtime API for all audio understanding → rejected (WebSocket complexity, higher cost, designed for live conversation not file analysis)
- Gemini-only enhancement → rejected (OpenAI audio model provides complementary capabilities)
- Both Realtime + Chat → deferred (Realtime useful for future live audio features, not for MAS-334's core need)

### Decision 2: Add audio editing as new `audio_type` values in `generate_media()`

**Rationale:** The existing `audio_type` dispatch pattern (`"speech"`, `"music"`, `"sound_effect"`) extends naturally. New types: `"voice_conversion"`, `"audio_isolation"`, `"voice_design"`, `"dubbing"`, `"translation"`.

**Alternatives considered:**
- Separate `edit_audio()` tool → rejected (fragmenting the surface area further contradicts consolidation goal)
- All via `extra_params` → rejected (no discoverability, poor ergonomics)

### Decision 3: Voice cloning requires explicit `audio_type="voice_clone"` with sample files

**Rationale:** Voice cloning has ethical/legal implications (consent required). Making it an explicit action (not automatic) with a distinct `audio_type` ensures agents make a deliberate choice.

**Alternatives considered:**
- Auto-clone when voice sample provided → rejected (too implicit for an ethically sensitive operation)
- Separate tool → workable but adds fragmentation

### Decision 4: Upgrade `understand_audio()` rather than creating a new tool

**Rationale:** The existing `understand_audio()` function already handles backend selection and multi-file processing. Adding `gpt-4o-audio-preview` as a backend and upgrading the Gemini prompt for richer analysis is less disruptive than a new tool.

**Alternatives considered:**
- New `analyze_audio()` tool → rejected (duplicates routing/selection logic)
- Replace `understand_audio()` entirely → rejected (Gemini's speaker diarization is still valuable)

### Decision 5: Phase the work with audio understanding first (MAS-334 priority)

**Rationale:** MAS-334 specifically asks for better audio understanding. Phases 2-5 are valuable but secondary. Delivering Phase 1 first addresses the stated need.

### Decision 6: OpenAI Realtime API deferred to future work

**Rationale:** The Realtime API's strengths (low-latency bidirectional streaming) are best suited for live audio interaction features, not the current file-based audio analysis workflow. It adds significant complexity (WebSocket connection management, event loop handling, PCM format requirements) for MAS-334's use case, which `gpt-4o-audio-preview` via Chat API handles more simply. The Realtime API should be revisited when MassGen adds live voice agent capabilities.

**What the Realtime API would enable (future):**
- Live voice conversation agents
- Real-time voice-to-voice with function calling
- Streaming audio input/output during agent execution
- VAD (voice activity detection) for turn-taking

## Architecture

### Rich Audio Understanding Flow

```
Agent calls read_media(file_paths=["speech.wav"], prompt="How is the delivery?")
    │
    ▼
understand_audio()
    ├─ Backend selection (same priority: Gemini → OpenAI)
    │
    ├─ Gemini path (existing, enhanced):
    │    └─ generate_content() with audio inline_data
    │       Enhanced prompt: "Analyze transcription AND tone, emotion, pacing..."
    │
    └─ OpenAI path (NEW — replaces Whisper for rich analysis):
         ├─ Read audio file, base64-encode
         ├─ chat.completions.create(
         │     model="gpt-4o-audio-preview",
         │     messages=[{
         │       "content": [
         │         {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
         │         {"type": "text", "text": analysis_prompt},
         │       ]
         │     }],
         │     modalities=["text"],
         │  )
         └─ Return rich analysis (transcription + tone + emotion + pacing)
```

### Audio Editing Flow

```
Agent calls generate_media(mode="audio", audio_type="voice_conversion",
                           input_audio_path="/path/to/source.wav",
                           voice="target_voice_name")
    │
    ▼
generate_media.py
    ├─ Route to generate_audio(config)
    │
    ▼
_audio.py generate_audio()
    ├─ audio_type == "voice_conversion"
    │    └─ _convert_voice_elevenlabs(config)
    │          ├─ Resolve target voice UUID
    │          ├─ Open source audio
    │          ├─ client.speech_to_speech.convert(voice_id=..., audio=...)
    │          └─ Write result to output_path
    │
    ├─ audio_type == "audio_isolation"
    │    └─ _isolate_audio_elevenlabs(config)
    │          ├─ Open source audio
    │          ├─ client.audio_isolation.convert(audio=...)
    │          └─ Write cleaned result to output_path
    │
    ├─ audio_type == "voice_design"
    │    └─ _design_voice_elevenlabs(config)
    │          ├─ client.text_to_voice.create_previews(voice_description=config.prompt)
    │          └─ Return preview audio + generated_voice_id for saving
    │
    ├─ audio_type == "voice_clone"
    │    └─ _clone_voice_elevenlabs(config)
    │          ├─ client.voices.ivc.create(name=..., files=[...])
    │          └─ Return new voice UUID for future TTS use
    │
    ├─ audio_type == "dubbing"
    │    └─ _dub_elevenlabs(config)
    │          ├─ client.dubbing.create(file=..., source_lang=..., target_lang=...)
    │          ├─ Poll for completion
    │          └─ Download and save dubbed audio/video
    │
    └─ audio_type == "translation"
         └─ _translate_audio_openai(config)
               ├─ client.audio.translations.create(file=..., model="whisper-1")
               └─ Return translated text (English)
```

### GenerationConfig Audio Extensions

```python
# New fields for audio editing
input_audio_path: Path | None = None       # Source audio for editing/conversion
target_language: str | None = None         # For translation/dubbing
source_language: str | None = None         # For dubbing
voice_description: str | None = None       # For voice design
voice_samples: list[Path] | None = None    # For voice cloning
instructions: str | None = None            # TTS delivery instructions (OpenAI)
speed: float | None = None                 # TTS speed (0.25-4.0x)
voice_stability: float | None = None       # ElevenLabs voice stability
voice_similarity: float | None = None      # ElevenLabs similarity boost
```

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| `gpt-4o-audio-preview` costs more than Whisper | Higher per-file analysis cost | Make it opt-in via backend preference; keep Whisper as cheap fallback |
| Voice cloning ethical/legal concerns | Potential misuse | Require explicit `audio_type="voice_clone"`; log usage; add consent guidance in docs |
| ElevenLabs API rate limits on voice operations | Voice cloning/dubbing may be slow | Queue operations; clear progress feedback |
| Audio files can be very large | Memory pressure with base64 encoding | Stream where possible; validate file size before processing |
| `gpt-4o-audio-preview` is marked "preview" | API may change | Abstract behind `understand_audio()` interface; easy to swap models |
| Dubbing is expensive and slow | Users may not expect the cost/time | Clear documentation; log estimated costs before proceeding |

## Migration Plan

No migration needed — all changes are additive. Existing `understand_audio()` calls continue to work identically (Gemini/Whisper backends still available). New capabilities are opt-in via new `audio_type` values and upgraded backend selection.

## Open Questions

1. **`gpt-4o-audio-preview` vs `gpt-4o-mini-audio-preview`**: Should we default to mini for cost savings, or full for quality? Decision: default to mini, allow override.
2. **Voice cloning consent**: Should MassGen require explicit user consent before voice cloning? Decision: yes, via `audio_type="voice_clone"` requiring deliberate invocation.
3. **Dubbing output format**: ElevenLabs dubbing can return video (with dubbed audio) or audio-only. Which should be default? Decision: match input format.
4. **Realtime API future scope**: When should we add live voice interaction? Decision: deferred until MassGen adds interactive agent mode (separate Linear issue).
