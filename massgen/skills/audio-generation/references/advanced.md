# Audio: Advanced Capabilities

## Rich Audio Understanding (Implemented)

Use `read_media` with audio files for full audio understanding beyond transcription. Default mode is "rich" which uses `gpt-4o-audio-preview` (OpenAI) or Gemini's native audio to capture tone, emotion, pacing, and speaker characteristics.

```python
# Rich analysis (default) — tone, emotion, pacing, not just words
read_media(path="recording.mp3", prompt="Analyze the speaker's emotional state")

# Fast transcription only
read_media(path="meeting.wav", prompt="Transcribe this", analysis_mode="transcription")
```

### Backend Fallback
- If native audio analysis (`gpt-4o-audio-preview`) fails, automatically falls back to Whisper transcription.
- Result includes `"fallback": true` when this happens.

## Voice Conversion (Implemented)

Change the voice of existing audio using ElevenLabs Speech-to-Speech:
```python
generate_media(
    prompt="placeholder",  # Not used for STS, but required
    mode="audio",
    audio_type="voice_conversion",
    input_audio="original_speech.wav",
    voice="Rachel"
)
```

- Preserves original speech content, pacing, and intonation.
- Changes only the voice timbre/characteristics.
- Uses ElevenLabs `speech_to_speech.convert()` API.
- Model: `eleven_english_sts_v2` (default).
- Voice names are auto-resolved to UUIDs (see `references/voices.md`).

## Audio Isolation (Implemented)

Remove background noise and isolate vocals/speech:
```python
generate_media(
    prompt="placeholder",
    mode="audio",
    audio_type="audio_isolation",
    input_audio="noisy_recording.wav"
)
```

- Uses ElevenLabs `audio_isolation.audio_isolation()` API.
- No voice parameter needed — it isolates whatever speech is present.
- Output is clean audio with background noise, music, and other sounds removed.

## Voice Design (Implemented)

Create a new synthetic voice from a text description:
```python
generate_media(
    prompt="A deep, warm male voice with slight British accent, aged 40-50",
    mode="audio",
    audio_type="voice_design",
    extra_params={"preview_text": "Hello, this is a test of the designed voice."}
)
```

- The `prompt` describes desired voice characteristics (age, gender, accent, tone).
- `extra_params.preview_text` is the text the preview voice will speak (optional, has default).
- Uses ElevenLabs `text_to_voice.create_previews()` API.
- Returns the first preview as the output audio.
- Result metadata includes `generated_voice_id` for further use.

## ElevenLabs -> OpenAI Fallback

If ElevenLabs TTS fails (network error, rate limit), the system automatically falls back to OpenAI TTS for speech. The model is cleared so OpenAI uses its own default instead of the ElevenLabs model name.

## Voice Cloning (Implemented)

Clone a voice from audio samples using ElevenLabs Instant Voice Cloning (IVC):
```python
generate_media(
    prompt="Hello, testing the cloned voice!",
    mode="audio",
    audio_type="voice_clone",
    voice_samples=["sample1.wav", "sample2.wav"]
)
```

- Uses ElevenLabs `voices.ivc.create()` API.
- Accepts 1+ audio sample files (1-3 minutes of clean speech recommended).
- Creates the cloned voice, then generates a TTS preview speaking the `prompt` text.
- Result metadata includes `cloned_voice_id` (UUID) for use in future TTS calls.
- Optional `extra_params`:
  - `voice_name`: Name for the cloned voice (default: "Cloned Voice")
  - `voice_description`: Description text (default: "Voice cloned from audio samples")
  - `remove_background_noise`: Clean samples before cloning (default: `true`)

### Ethical Considerations

Voice cloning requires explicit `audio_type="voice_clone"` to ensure deliberate invocation. Always obtain consent from the voice owner before cloning their voice.

## Advanced TTS Parameters (Implemented)

Fine-grained control over speech output:

### ElevenLabs Parameters
```python
generate_media(
    prompt="Hello world",
    mode="audio",
    voice="Rachel",
    voice_stability=0.7,    # 0.0 (expressive) to 1.0 (stable)
    voice_similarity=0.8,   # 0.0 (diverse) to 1.0 (faithful)
    seed=42                  # Reproducible output
)
```

- `voice_stability`: Controls voice consistency. Lower = more expressive/varied, higher = more stable.
- `voice_similarity`: Controls similarity to the original voice. Higher = more faithful reproduction.
- `seed`: Integer for reproducible output across identical calls.

### OpenAI Parameters
```python
generate_media(
    prompt="Hello world",
    mode="audio",
    voice="nova",
    speed=1.5,               # 0.25 (slow) to 4.0 (fast)
    instructions="Speak with a warm, reflective tone"
)
```

- `speed`: Playback speed multiplier (0.25-4.0, automatically clamped).
- `instructions`: Speaking style guidance (only for `gpt-4o-mini-tts` model).

## Dubbing (Implemented — ElevenLabs)

Translate and dub audio/video to another language, preserving voice characteristics:
```python
generate_media(
    prompt="placeholder",
    mode="audio",
    audio_type="dubbing",
    input_audio="english_podcast.mp3",
    target_language="es",
    source_language="en"  # optional, auto-detected
)
```

- Uses ElevenLabs `dubbing.create()` API with async polling.
- Supports both audio and video input files.
- Preserves original speaker voice characteristics in the target language.
- `source_language` is optional — auto-detected if omitted.
- Polls for completion (up to 10 minutes timeout).
- Result metadata includes `dubbing_id` for reference.

### Supported Languages
Common codes: `en` (English), `es` (Spanish), `fr` (French), `de` (German),
`it` (Italian), `pt` (Portuguese), `ja` (Japanese), `ko` (Korean), `zh` (Chinese).
See ElevenLabs docs for full list.

### Cost Warning
Dubbing is an expensive operation. Use sparingly and be aware of API costs.

## ElevenLabs Skills Repository

For advanced ElevenLabs features not yet wrapped by MassGen (voice agents, real-time streaming, advanced voice design), see the official ElevenLabs skills repository:

**https://github.com/elevenlabs/skills**

Available skills:
- Text-to-Speech
- Speech-to-Text
- Sound Effects
- Music
- Agents (conversational voice AI)
- Setup/API Key guidance
