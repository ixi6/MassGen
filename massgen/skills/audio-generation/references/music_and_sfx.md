# Music & Sound Effects Generation

Both music and sound effects are ElevenLabs-only features. They require `ELEVENLABS_API_KEY`.

## Music Generation

Generate music from text descriptions:

```python
generate_media(
    prompt="Upbeat jazz piano with soft drums and walking bass",
    mode="audio",
    audio_type="music",
    duration=30
)
```

### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prompt` | Music description | Required |
| `duration` | Length in seconds (converted to ms internally) | 30s |
| `extra_params.force_instrumental` | Force instrumental only (no vocals) | `True` |

### Duration Handling

Duration is converted to milliseconds for the ElevenLabs API: `duration_ms = duration * 1000`.

### Examples

```python
# Instrumental background music
generate_media(
    prompt="Calm ambient electronic with soft pads",
    mode="audio",
    audio_type="music",
    duration=60
)

# Allow vocals
generate_media(
    prompt="Pop song about summer",
    mode="audio",
    audio_type="music",
    duration=45,
    extra_params={"force_instrumental": False}
)
```

### API

Uses `client.music.compose(prompt, music_length_ms, force_instrumental)`.

## Sound Effects Generation

Generate sound effects from text descriptions:

```python
generate_media(
    prompt="Thunder rolling across a mountain valley",
    mode="audio",
    audio_type="sound_effect",
    duration=5
)
```

### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prompt` | Sound effect description | Required |
| `duration` | Length in seconds (clamped to 0.5-30s) | None (API decides) |
| `extra_params.prompt_influence` | How closely to follow the prompt (0.0-1.0) | `0.3` |

### Duration Clamping

SFX duration is clamped: `max(0.5, min(duration, 30.0))` seconds.

### Prompt Influence

Controls how literally the API interprets the prompt:
- `0.0` - More creative, may deviate from description
- `0.3` - Default balance
- `1.0` - Very literal interpretation

### Examples

```python
# Short, precise sound effect
generate_media(
    prompt="A single doorbell ring",
    mode="audio",
    audio_type="sound_effect",
    duration=2,
    extra_params={"prompt_influence": 0.8}
)

# Longer ambient sound
generate_media(
    prompt="Rain on a tin roof with occasional thunder",
    mode="audio",
    audio_type="sound_effect",
    duration=20,
    extra_params={"prompt_influence": 0.3}
)
```

### API

Uses `client.text_to_sound_effects.convert(text, prompt_influence, duration_seconds)`.

## Backend Selection

Music and SFX automatically route to ElevenLabs regardless of the `backend_type` setting (if `ELEVENLABS_API_KEY` is available). If the key is missing, generation fails with a clear error.

## Output Format

Both music and SFX default to MP3 output. Use `audio_format` to change:

```python
generate_media(
    prompt="A gentle chime",
    mode="audio",
    audio_type="sound_effect",
    audio_format="wav"
)
```
