---
name: multimodal-tools
description: Analyze visual, audio, and video evidence — screenshots, recordings, charts, transcriptions, PDFs
category: multimodal
requires_api_keys: [OPENAI_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY, ELEVENLABS_API_KEY]
tasks:
  - "Analyze and understand images with vision models"
  - "Understand and transcribe audio files"
  - "Analyze video recordings and video content"
  - "Process and understand various file formats (PDF, DOCX, etc.)"
  - "Generate images from text descriptions (OpenAI, Google Imagen, OpenRouter)"
  - "Generate videos from text prompts (OpenAI Sora, Google Veo)"
  - "Convert text to speech with natural voices (ElevenLabs, OpenAI TTS)"
  - "Generate music from text prompts (ElevenLabs)"
  - "Generate sound effects from text descriptions (ElevenLabs)"
  - "Transform images to new variations"
keywords: [vision, audio, video, multimodal, image-analysis, speech, transcription, generation, pdf, file-processing, imagen, veo, sora, tts, elevenlabs, music, sfx, sound-effects]
---

# Multimodal Tools

Comprehensive suite of tools for processing and understanding vision, audio, video, and file content using OpenAI's multimodal APIs.

## Purpose

Enable agents to work with media beyond text:
- **Vision**: Analyze images, screenshots, recordings, charts, diagrams
- **Audio**: Transcribe speech, understand audio content
- **Video**: Process and analyze video frames
- **File Processing**: Extract content from PDFs, documents, etc.
- **Generation**: Create images, videos, and speech from text

## When to Use This Tool

**Use multimodal tools when:**
- Verifying artifacts with appropriate evidence (screenshots for layout, video for behavior, audio for sound)
- Extracting information from images or videos
- Transcribing audio recordings or understanding speech
- Processing document files (PDF, DOCX, XLSX)
- Generating visual or audio content
- Working with multi-format media files

**Do NOT use for:**
- Simple text processing (use text tools instead)
- Real-time video streaming analysis
- High-volume batch processing (consider costs)
- Tasks not requiring multimodal understanding

## Available Functions

### Understanding Tools

#### `understand_image(image_path: str, prompt: str, ...) -> ExecutionResult`
Analyze images using vision models (GPT-4.1 or similar).

**Example:**
```python
result = await understand_image(
    "screenshot.png",
    "What buttons are visible in this UI?"
)
# Returns: Detailed description of UI elements
```

**Use cases:**
- Screenshot analysis
- Chart/graph interpretation
- Visual content extraction
- UI testing verification

#### `understand_audio(audio_path: str, prompt: str, ...) -> ExecutionResult`
Transcribe and understand audio files.

**Example:**
```python
result = await understand_audio(
    "recording.mp3",
    "Transcribe this audio and summarize key points"
)
# Returns: Transcription and summary
```

**Supported formats:** MP3, WAV, M4A, etc.

#### `understand_video(video_path: str, prompt: str, ...) -> ExecutionResult`
Analyze video content by processing frames.

**Example:**
```python
result = await understand_video(
    "demo.mp4",
    "Describe what happens in this video"
)
# Returns: Frame-by-frame analysis
```

**Note:** Processes video by extracting and analyzing key frames.

#### `understand_file(file_path: str, prompt: str, ...) -> ExecutionResult`
Extract and understand content from various file formats.

**Example:**
```python
result = await understand_file(
    "report.pdf",
    "Summarize the main findings"
)
# Returns: Extracted content and analysis
```

**Supported formats:** PDF, DOCX, XLSX, TXT, CSV, etc.

### Generation Tools

#### `generate_media(prompt: str, mode: str, backend_type: str = "auto", ...) -> ExecutionResult`
**Unified media generation tool** - Generate images, videos, or audio with automatic backend selection.

This is the recommended tool for all media generation. It automatically selects the best available backend based on:
1. Explicit `backend_type` parameter
2. Available API keys
3. Modality-specific priority order

**Parameters:**
- `prompt`: Text description of what to generate. For audio/speech, this is the
  **literal text to speak** — do NOT include speaking instructions here.
- `mode`: Type of media - `"image"`, `"video"`, or `"audio"`
- `backend_type`: Preferred backend - `"auto"`, `"openai"`, `"google"`, `"openrouter"`, or `"elevenlabs"`
- `model`: Override default model
- `duration`: For video/audio, length in seconds
- `voice`: For audio, voice name or ID (e.g., `"Rachel"`, `"alloy"`, `"nova"`).
  ElevenLabs names are auto-resolved to UUIDs.
- `instructions`: For audio, speaking style/tone guidance (e.g., `"warm, reflective tone"`).
  Only supported by OpenAI gpt-4o-mini-tts. Do NOT put style instructions in `prompt`.
- `aspect_ratio`: For image/video (e.g., `"16:9"`, `"1:1"`). Works for both Gemini and Imagen paths.
- `size`: Image dimensions. OpenAI: `"1024x1024"`, `"1024x1536"`, `"1536x1024"`.
  Gemini: `"512px"`, `"1K"`, `"2K"`, `"4K"`.
- `quality`: Image quality. OpenAI: `"low"`, `"medium"`, `"high"`, `"auto"`.
- `continue_from`: Continuation ID from a previous `generate_media` result for multi-turn
  image editing. Pass `result["continuation_id"]` from the previous call. Only valid for
  single image generation (not batch, not video/audio).
- `storage_path`: Directory to save generated media

**Supported Backends:**
| Mode | Backends | Default Models |
|------|----------|----------------|
| image | google, openai, openrouter | Nano Banana 2 (`gemini-3.1-flash-image-preview`), GPT-5.2, Nano Banana 2 (via OR) |
| video | google, openai | Veo 3.1, Sora-2 |
| audio (speech) | elevenlabs, openai | eleven_multilingual_v2, gpt-4o-mini-tts |
| audio (music) | elevenlabs | elevenlabs-music |
| audio (sfx) | elevenlabs | elevenlabs-sfx |

Google image generation supports two API paths:
- **Gemini models** (`gemini-*`): Uses `generate_content()` — supports text-to-image and image editing via `input_images`
- **Imagen models** (`imagen-*`): Uses `generate_images()` — text-to-image only

For studio-quality precision and text rendering, set `model: "gemini-3-pro-image-preview"` (Pro-tier, same Gemini API path).

**Audio note:** Prefer `generate_media` with `mode="audio"` over installing packages like `edge-tts`. Backend selection is automatic based on available API keys. If no keys are available, falling back to free packages is fine.

**Examples:**
```python
# Generate speech (ElevenLabs preferred when key available)
result = await generate_media(
    "Hello world!",
    mode="audio",
    voice="Rachel"
)

# Generate music (ElevenLabs only)
result = await generate_media(
    "Upbeat jazz piano with soft drums",
    mode="audio",
    audio_type="music",
    duration=30
)

# Generate sound effects (ElevenLabs only)
result = await generate_media(
    "Thunder rolling across a mountain valley",
    mode="audio",
    audio_type="sound_effect",
    duration=5
)

# Generate an image with auto-selection
result = await generate_media(
    "A cat in space",
    mode="image"
)

# Iterative image editing (multi-turn continuation)
result = await generate_media(
    "A logo for a coffee shop",
    mode="image"
)
# Refine using continuation_id from previous result
result2 = await generate_media(
    "Make the text larger and add a cup icon",
    mode="image",
    continue_from=result["continuation_id"]
)

# Generate video with Google Veo
result = await generate_media(
    "A robot walking through a city",
    mode="video",
    backend_type="google",
    duration=8
)
```

#### `image_to_image_generation(image_path: str, prompt: str, output_path: str, ...) -> ExecutionResult`
Transform existing images based on prompts.

**Example:**
```python
result = await image_to_image_generation(
    "photo.jpg",
    "Make it look like a watercolor painting",
    "watercolor.png"
)
# Saves: watercolor.png
```

#### `text_to_speech_continue_generation(text: str, previous_audio: str, output_path: str, ...) -> ExecutionResult`
Continue speech generation with context from previous audio.

**Example:**
```python
result = await text_to_speech_continue_generation(
    "And here's the next sentence.",
    "speech.mp3",
    "speech_continued.mp3"
)
# Saves: speech_continued.mp3 with matching voice/style
```

#### `text_to_file_generation(content: str, output_path: str, file_format: str, ...) -> ExecutionResult`
Generate structured files from text (PDF, DOCX, etc.).

**Example:**
```python
result = await text_to_file_generation(
    "# Report\n\nThis is the content...",
    "report.pdf",
    "pdf"
)
# Saves: report.pdf
```

**Supported formats:** PDF, DOCX, TXT, MD, HTML.

## Configuration

### Prerequisites

**Environment variables:**
```bash
# Required for OpenAI backends (image, video, audio)
export OPENAI_API_KEY="your-api-key"

# Optional - for Google backends (Imagen, Veo)
export GOOGLE_API_KEY="your-api-key"
# or
export GEMINI_API_KEY="your-api-key"

# Optional - for OpenRouter image generation
export OPENROUTER_API_KEY="your-api-key"

# Optional - for ElevenLabs audio (TTS, music, sound effects)
export ELEVENLABS_API_KEY="your-api-key"
```

**Optional dependencies:**
```bash
pip install pillow  # For image processing
pip install ffmpeg-python  # For video processing
pip install google-genai  # For Google Imagen/Veo (already in requirements)
```

### YAML Config

Enable multimodal tools in your config:

```yaml
custom_tools_path: "massgen/tool/_multimodal_tools"
```

Or include specific tools in your tools list.

### Generation Backend/Model Configuration

You can configure default backends and models at the **orchestrator level** (applies to all agents) or per-agent:

**Orchestrator-level defaults (recommended):**
```yaml
orchestrator:
  # Enable multimodal tools for all agents
  enable_multimodal_tools: true

  # Set default backends for all agents
  image_generation_backend: "openai"
  video_generation_backend: "openai"
  audio_generation_backend: "elevenlabs"

  # Optionally set default models
  image_generation_model: "imagen-3.0-generate-002"
  video_generation_model: "veo-2.0-generate-001"
  audio_generation_model: "gpt-4o-mini-tts"

agents:
  - id: "agent1"
    backend:
      type: "openai"
      model: "gpt-4o"
      cwd: "workspace1"
      # Inherits orchestrator defaults automatically
```

**Per-agent override:**
```yaml
orchestrator:
  enable_multimodal_tools: true
  image_generation_backend: "google"

agents:
  - id: "agent1"
    backend:
      type: "openai"
      model: "gpt-4o"
      # Override orchestrator default for this agent only
      image_generation_backend: "openai"
```

**Priority Order:**
1. Explicit parameter in tool call (e.g., `generate_media(..., backend="google")`)
2. Per-agent config setting (e.g., `image_generation_backend: "openai"`)
3. Orchestrator-level config setting
4. Auto-selection based on available API keys

**Available Backends:**
| Mode  | Backends                        | Default Models |
|-------|--------------------------------|----------------|
| image | google, openai, openrouter     | gemini-3.1-flash-image-preview (Nano Banana 2), gpt-5.2, google/gemini-3.1-flash-image-preview |
| video | google, openai                 | veo-3.1-generate-preview, sora-2 |
| audio (speech) | elevenlabs, openai     | eleven_multilingual_v2, gpt-4o-mini-tts |
| audio (music) | elevenlabs              | elevenlabs-music |
| audio (sfx) | elevenlabs                | elevenlabs-sfx |

## Path Handling

All tools support flexible path handling:
- **Relative paths**: Resolved relative to agent workspace
- **Absolute paths**: Must be within allowed directories
- **Output paths**: Saved to workspace by default

**Validation:** Path access is validated for security.

## Cost Considerations

**Be mindful of API costs:**
- Image analysis: ~$0.01-0.05 per image
- Video analysis: Cost scales with duration/frames
- Image generation: ~$0.02-0.08 per image
- Video generation: Significantly higher costs
- Audio transcription: ~$0.006 per minute

Always consider cost when processing large batches.

## Limitations

- **API dependencies**: Requires OpenAI API access and credits
- **File size limits**: Large files may exceed API limits
- **Processing time**: Video/audio processing can be slow
- **Quality variability**: Generated content quality depends on prompts
- **Format support**: Not all file formats supported for all operations
- **Network required**: All operations require internet access

## Common Use Cases

1. **Evidence analysis**: Verify artifacts with screenshots, video recordings, or audio captures
2. **Document processing**: Extract information from PDFs, reports
3. **Media transcription**: Convert audio/video to text
4. **Visual content creation**: Generate images for presentations, reports
5. **Accessibility**: Convert text to speech, extract text from images
6. **Video analysis**: Understand video content without watching
7. **Chart/graph interpretation**: Extract data from visual charts
8. **Interaction/behavior verification**: Record and analyze dynamic behavior with video
