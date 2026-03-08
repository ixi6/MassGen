---
name: audio-generation
description: Guide to audio generation and understanding in MassGen. Covers text-to-speech, music, sound effects, and audio understanding across ElevenLabs and OpenAI backends.
---

# Audio Generation

Generate audio using `generate_media` with `mode="audio"`. Supports speech (TTS), music, and sound effects. ElevenLabs is preferred when available, with OpenAI as fallback.

## Quick Start

```python
# Text-to-speech (auto-selects ElevenLabs if key available)
generate_media(prompt="Hello, welcome to our presentation!", mode="audio")

# With specific voice
generate_media(prompt="Hello!", mode="audio", voice="Rachel")

# Music generation (ElevenLabs only)
generate_media(prompt="Upbeat jazz piano with soft drums", mode="audio",
               audio_type="music", duration=30)

# Sound effects (ElevenLabs only)
generate_media(prompt="Thunder rolling across a mountain valley", mode="audio",
               audio_type="sound_effect", duration=5)
```

## Audio Types

| Type | Backends | Description |
|------|----------|-------------|
| `"speech"` (default) | ElevenLabs, OpenAI | Text-to-speech with voice selection |
| `"music"` | ElevenLabs only | Music generation from text prompt |
| `"sound_effect"` | ElevenLabs only | Sound effect generation |
| `"voice_conversion"` | ElevenLabs only | Change voice of existing audio (speech-to-speech) |
| `"audio_isolation"` | ElevenLabs only | Remove background noise, isolate vocals |
| `"voice_design"` | ElevenLabs only | Create a new synthetic voice from text description |
| `"voice_clone"` | ElevenLabs only | Clone a voice from audio samples |
| `"dubbing"` | ElevenLabs only | Translate and dub audio to another language |

## Backend Comparison

| Backend | Default Model | Supports | API Key |
|---------|--------------|----------|---------|
| **ElevenLabs** (priority 1) | `eleven_multilingual_v2` | Speech, music, SFX | `ELEVENLABS_API_KEY` |
| **OpenAI** (priority 2) | `gpt-4o-mini-tts` | Speech only | `OPENAI_API_KEY` |

If ElevenLabs TTS fails, the system automatically falls back to OpenAI TTS.

## Key Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `prompt` | Text to speak (speech) or description (music/SFX) | `"Hello world!"` |
| `voice` | Voice name or ID | `"Rachel"`, `"nova"`, `"alloy"` |
| `audio_type` | Type of audio | `"speech"`, `"music"`, `"sound_effect"` |
| `duration` | Length in seconds (music/SFX only) | `30` |
| `instructions` | Speaking style (OpenAI `gpt-4o-mini-tts` only) | `"warm, reflective tone"` |
| `audio_format` | Output format | `"mp3"`, `"wav"`, `"opus"` |

## Voice Quick Reference

**ElevenLabs** (top voices):
| Voice | Character |
|-------|-----------|
| Rachel | Warm, conversational female |
| Sarah | Clear, professional female |
| Josh | Friendly male |
| Adam | Deep, authoritative male |
| Emily | Bright, energetic female |

**OpenAI** voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`, `coral`, `sage`

## Important: prompt vs instructions

For speech, `prompt` is the **literal text to speak**. Style guidance goes in `instructions`:

```python
# CORRECT: prompt = text to speak, instructions = how to speak it
generate_media(
    prompt="Welcome to the annual report presentation.",
    mode="audio",
    voice="alloy",
    instructions="warm, reflective tone with measured pacing",
    backend_type="openai"
)

# WRONG: Don't put style instructions in prompt
generate_media(prompt="Say this warmly: Welcome...", mode="audio")  # Bad!
```

`instructions` only works with OpenAI `gpt-4o-mini-tts`. ElevenLabs uses voice selection for tone.

## Audio Understanding

Use `read_media` (not `generate_media`) to analyze existing audio:

```python
read_media(path="recording.mp3", prompt="Transcribe and summarize this audio")
```

## Need More Control?

- **Full ElevenLabs voice catalog (28+ voices)**: See [references/voices.md](references/voices.md)
- **Music and sound effects details**: See [references/music_and_sfx.md](references/music_and_sfx.md)
- **Advanced audio capabilities (voice conversion, cloning, isolation, dubbing)**: See [references/advanced.md](references/advanced.md)
