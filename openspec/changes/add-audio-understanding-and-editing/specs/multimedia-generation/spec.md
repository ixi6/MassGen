## ADDED Requirements

### Requirement: Rich Audio Understanding

The system SHALL support rich audio understanding that preserves tone, emotion, pacing, and paralinguistic cues beyond plain transcription.

When analyzing audio files, the system SHALL offer two modes:
- `"rich"` (default): Full analysis using `gpt-4o-audio-preview` (OpenAI) or enhanced Gemini prompting, covering transcription, tone, emotion, pacing, emphasis, and speaker characteristics.
- `"transcription"`: Fast/cheap STT-only via Whisper or Gemini (existing behavior).

#### Scenario: Rich audio analysis via OpenAI
- **WHEN** an agent calls `understand_audio(audio_paths=["speech.wav"], analysis_mode="rich")` with OpenAI backend
- **THEN** the system sends the raw audio to `gpt-4o-audio-preview` via Chat Completions API
- **THEN** the response includes transcription AND analysis of tone, emotion, pacing, emphasis, and delivery

#### Scenario: Rich audio analysis via Gemini
- **WHEN** an agent calls `understand_audio(audio_paths=["speech.wav"], analysis_mode="rich")` with Gemini backend
- **THEN** the system sends the audio with an enhanced prompt requesting paralinguistic analysis
- **THEN** the response includes structured analysis sections for delivery, tone, emotion, and pacing

#### Scenario: Transcription-only mode
- **WHEN** an agent calls `understand_audio(audio_paths=["speech.wav"], analysis_mode="transcription")`
- **THEN** the system uses Whisper or basic Gemini transcription (fast, cheap, text-only)

#### Scenario: Default mode is rich
- **WHEN** an agent calls `understand_audio(audio_paths=["speech.wav"])` without specifying mode
- **THEN** the system defaults to rich analysis mode

---

### Requirement: Voice Conversion

The system SHALL support voice conversion via ElevenLabs speech-to-speech, transforming the voice in an audio file to a target voice while preserving timing and emotion.

#### Scenario: Convert voice to target
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="voice_conversion", input_audio_path="source.wav", voice="target_voice")`
- **THEN** the system resolves the target voice UUID and calls ElevenLabs `speech_to_speech.convert()`
- **THEN** the output audio has the target voice with preserved timing and emotion

#### Scenario: Voice conversion with noise removal
- **WHEN** an agent provides `extra_params={"remove_background_noise": true}` with voice conversion
- **THEN** the system passes `remove_background_noise=True` to isolate the voice before conversion

#### Scenario: Missing input audio
- **WHEN** an agent requests voice conversion without `input_audio_path`
- **THEN** the system returns an error indicating source audio is required

---

### Requirement: Audio Isolation

The system SHALL support background noise removal via ElevenLabs audio isolation.

#### Scenario: Remove background noise
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="audio_isolation", input_audio_path="noisy.wav")`
- **THEN** the system calls ElevenLabs `audio_isolation.convert()` and saves the cleaned audio

---

### Requirement: Voice Design

The system SHALL support creating new voices from text descriptions via ElevenLabs voice design.

#### Scenario: Design voice from description
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="voice_design", prompt="A warm, authoritative male voice with a slight British accent")`
- **THEN** the system calls ElevenLabs `text_to_voice.create_previews()` with the description
- **THEN** the result includes preview audio and a `generated_voice_id` in metadata for saving

---

### Requirement: Voice Cloning

The system SHALL support instant voice cloning from audio samples via ElevenLabs IVC.

Voice cloning MUST be an explicit action requiring `audio_type="voice_clone"` to ensure deliberate invocation given ethical/legal considerations.

#### Scenario: Clone voice from samples
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="voice_clone", voice_samples=["/path/to/sample1.mp3", "/path/to/sample2.mp3"])`
- **THEN** the system calls ElevenLabs `voices.ivc.create()` with the sample files
- **THEN** the result includes the new voice UUID in metadata for future TTS use

#### Scenario: Missing samples
- **WHEN** an agent requests voice cloning without providing `voice_samples`
- **THEN** the system returns a clear error indicating audio samples are required

---

### Requirement: Audio Translation

The system SHALL support audio translation (any language to English) via OpenAI Whisper.

#### Scenario: Translate audio to English
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="translation", input_audio_path="spanish_speech.mp3")`
- **THEN** the system calls OpenAI `audio.translations.create()` and returns the English translation text

---

### Requirement: Audio/Video Dubbing

The system SHALL support full audio/video dubbing and localization via ElevenLabs.

#### Scenario: Dub video to target language
- **WHEN** an agent calls `generate_media(mode="audio", audio_type="dubbing", input_audio_path="video.mp4", source_language="en", target_language="es")`
- **THEN** the system calls ElevenLabs `dubbing.create()` and polls for completion
- **THEN** the dubbed output preserves original speaker voices in the target language

---

### Requirement: Advanced TTS Parameters

The system SHALL support advanced text-to-speech parameters forwarded to backends that accept them.

Supported parameters:
- `instructions`: Voice delivery guidance (OpenAI `gpt-4o-mini-tts` only)
- `speed`: Playback speed 0.25-4.0x (OpenAI only)
- `voice_stability`: Voice consistency control (ElevenLabs only)
- `voice_similarity`: Voice matching strength (ElevenLabs only)
- `seed`: Reproducible generation (ElevenLabs only)

#### Scenario: TTS with delivery instructions
- **WHEN** an agent calls `generate_media(mode="audio", instructions="Speak warmly with slight excitement")` with OpenAI backend
- **THEN** the system passes `instructions` to `gpt-4o-mini-tts` for guided delivery

#### Scenario: TTS with speed control
- **WHEN** an agent provides `speed=1.5` with OpenAI TTS
- **THEN** the system passes `speed=1.5` for 1.5x playback speed

#### Scenario: Unsupported parameter silently ignored
- **WHEN** an agent provides `instructions` with ElevenLabs backend (which doesn't support it)
- **THEN** the system generates speech normally without error

---

### Requirement: Audio Capabilities System Prompt Guidance

The system prompt SHALL include comprehensive guidance for agents on all audio capabilities.

#### Scenario: Agent receives audio guidance
- **WHEN** an agent is initialized with multimedia tools enabled
- **THEN** the system prompt includes an audio capabilities table showing which features each backend supports
- **THEN** the system prompt includes guidance on rich vs transcription-only audio analysis
- **THEN** the system prompt includes usage patterns for voice conversion, isolation, cloning, dubbing
