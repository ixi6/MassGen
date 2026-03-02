Multimodal Tools
================

Overview
--------

MassGen provides unified multimodal tools that enable AI agents to analyze and generate various media types including images, videos, and audio. These tools provide a simple, consistent interface across all supported media formats.

Quick Start
-----------

Enable multimodal tools in your configuration:

.. code-block:: yaml

   agents:
     - id: my_agent
       backend:
         type: openai
         model: gpt-5
         enable_multimodal_tools: true
         image_generation_backend: openai
         video_generation_backend: google
         audio_generation_backend: openai

This automatically registers two unified tools:

- **read_media**: Universal media reading and analysis
- **generate_media**: Universal media generation

Unified Tools
-------------

read_media
^^^^^^^^^^

**Purpose**: Analyze any media file (image, audio, or video) with a single tool.

**Auto-detection**: Automatically detects media type from file extension and routes to the appropriate analysis backend.

**Usage**:

.. code-block:: python

   # Agent can simply use read_media for any media type
   result = read_media("screenshot.png", prompt="What's in this image?")
   result = read_media("podcast.mp3", prompt="Summarize this audio")
   result = read_media("demo.mp4", prompt="What happens in this video?")

**Parameters**:

- ``media_path`` (required): Path to the media file

  - Relative paths resolved from agent workspace
  - Absolute paths must be in allowed directories
  - Auto-detects type from extension (png, jpg, mp3, wav, mp4, mov, etc.)

- ``prompt`` (optional): Question or instruction about the media

  - Default: "Please analyze this {media_type} and describe its contents."

**Returns**:

Text description of the media content via the appropriate understanding tool (``understand_image``, ``understand_audio``, or ``understand_video``).

**Supported Formats**:

- **Images**: png, jpg, jpeg, gif, webp, bmp
- **Audio**: mp3, wav, m4a, ogg, flac, aac
- **Video**: mp4, mov, avi, mkv, webm

**Configuration Overrides**:

You can specify different backends/models per media type using simple config variables:

.. code-block:: yaml

   backend:
     enable_multimodal_tools: true
     image_generation_backend: openai
     image_generation_model: gpt-5
     video_generation_backend: google
     audio_generation_backend: openai

generate_media
^^^^^^^^^^^^^^

**Purpose**: Generate images, videos, or audio from text descriptions.

**Smart Backend Selection**: Automatically chooses the best available backend based on API keys and configuration.

**Usage**:

.. code-block:: python

   # Generate an image
   result = generate_media(
       prompt="a cat in space",
       mode="image"
   )

   # Generate a video
   result = generate_media(
       prompt="neon-lit alley at night, light rain",
       mode="video",
       duration=8
   )

   # Generate audio (text-to-speech)
   result = generate_media(
       prompt="Hello, welcome to MassGen!",
       mode="audio",
       voice="nova"
   )

**Core Parameters**:

- ``prompt`` (required): Text description of what to generate. For audio speech, this is the
  **literal text to speak** — do NOT include speaking instructions here.
- ``mode`` (required): Type of media — ``"image"``, ``"video"``, or ``"audio"``
- ``backend_type`` (optional): Preferred backend — ``"auto"``, ``"openai"``, ``"google"``,
  ``"grok"``, ``"openrouter"``, or ``"elevenlabs"``
- ``model`` (optional): Override the default model for the selected backend
- ``storage_path`` (optional): Directory to save generated media (defaults to workspace root)
- ``continue_from`` (optional): Continuation ID from a previous result for multi-turn editing

**Image-specific parameters**:

- ``quality``: ``"low"``, ``"medium"``, ``"high"``, ``"auto"`` (OpenAI)
- ``size``: Image dimensions. OpenAI: ``"1024x1024"``, ``"1024x1536"``, ``"1536x1024"``.
  Gemini: ``"512px"``, ``"1K"``, ``"2K"``, ``"4K"``. Grok: ``"1k"``.
- ``aspect_ratio``: e.g., ``"16:9"``, ``"1:1"``, ``"9:16"`` (Google, Grok, OpenRouter)
- ``input_images``: List of image paths for image-to-image editing (OpenAI, Google Gemini, Grok)
- ``mask_path``: Path to mask PNG for inpainting (OpenAI, Google Imagen)
- ``output_format``: ``"png"``, ``"jpeg"``, ``"webp"`` (OpenAI, Google Imagen)
- ``background``: ``"transparent"``, ``"opaque"``, ``"auto"`` (OpenAI only)
- ``style_image``: Style reference image for Google Imagen style transfer
- ``control_image``: Structural control image for Google Imagen
- ``subject_image``: Subject reference image for Google Imagen consistency
- ``negative_prompt``: What to exclude (Google Imagen)
- ``seed``: Reproducibility seed (Google Imagen, ElevenLabs)
- ``guidance_scale``: Prompt adherence strength (Google Imagen)

**Video-specific parameters**:

- ``duration``: Length in seconds (clamped per backend)
- ``size``: Resolution — Grok: ``"480p"``, ``"720p"``; Veo: ``"720p"``, ``"1080p"``, ``"4k"``
- ``aspect_ratio``: e.g., ``"16:9"``, ``"9:16"``
- ``input_images``: Source image for image-to-video (all 3 backends)
- ``video_reference_images``: Style/content guide images for Veo (up to 3)
- ``negative_prompt``: What to exclude (Google Veo)

**Audio-specific parameters**:

- ``audio_type``: Type of audio operation — ``"speech"`` (default), ``"music"``,
  ``"sound_effect"``, ``"voice_conversion"``, ``"audio_isolation"``, ``"voice_design"``,
  ``"voice_clone"``, ``"dubbing"``
- ``voice``: Voice name or ID (e.g., ``"Rachel"``, ``"alloy"``, ``"nova"``)
- ``instructions``: Speaking style guidance (OpenAI ``gpt-4o-mini-tts`` only)
- ``speed``: Playback speed multiplier, 0.25–4.0 (OpenAI)
- ``audio_format``: Output format (``"mp3"``, ``"wav"``, ``"opus"``)
- ``input_audio``: Path to input audio for voice conversion, isolation, or dubbing
- ``voice_samples``: List of audio file paths for voice cloning
- ``target_language``: Target language code for dubbing (e.g., ``"es"``, ``"fr"``)
- ``source_language``: Source language code for dubbing (optional, auto-detected)
- ``voice_stability``: ElevenLabs voice stability (0.0–1.0)
- ``voice_similarity``: ElevenLabs similarity boost (0.0–1.0)

**Returns**:

JSON with ``success``, ``file_path``, ``file_size``, ``backend``, ``model``, ``continuation_id``,
and ``metadata`` fields.

**Supported Backends**:

.. list-table::
   :header-rows: 1

   * - Mode
     - Backends (priority order)
     - Default Models
   * - image
     - google, openai, grok, openrouter
     - Nano Banana 2 (``gemini-3.1-flash-image-preview``), ``gpt-5.2``, ``grok-imagine-image``, Nano Banana 2 (via OR)
   * - video
     - grok, google, openai
     - ``grok-imagine-video``, Veo 3.1 (``veo-3.1-generate-preview``), ``sora-2``
   * - audio (speech)
     - elevenlabs, openai
     - ``eleven_multilingual_v2``, ``gpt-4o-mini-tts``
   * - audio (music)
     - elevenlabs
     - ``elevenlabs-music``
   * - audio (sfx)
     - elevenlabs
     - ``elevenlabs-sfx``
   * - audio (editing)
     - elevenlabs
     - See ``audio_type`` values above

Backend Configuration
---------------------

Simple Configuration
^^^^^^^^^^^^^^^^^^^^

Just enable multimodal tools:

.. code-block:: yaml

   backend:
     enable_multimodal_tools: true

This uses default backends based on available API keys.

Advanced Configuration
^^^^^^^^^^^^^^^^^^^^^^

Specify backends and models per media type:

.. code-block:: yaml

   backend:
     enable_multimodal_tools: true
     image_generation_backend: openai
     image_generation_model: gpt-5
     video_generation_backend: google
     video_generation_model: veo-3.1-generate-preview
     audio_generation_backend: openai
     audio_generation_model: gpt-4o-mini-tts


Native Backend Routing (v0.1.55+)
----------------------------------

Image and video understanding now route to the **agent's own backend** when it supports the capability, instead of always using OpenAI. This preserves model diversity and per-agent consistency.

**Supported image backends**: OpenAI, Claude, Gemini, Grok, Claude Code (SDK), Codex (CLI).

If the agent's backend doesn't support image understanding, it falls back to OpenAI ``gpt-5.2``.

.. code-block:: yaml

   # A Claude agent will use Claude's vision API for image analysis
   agents:
     - id: claude_vision
       backend:
         type: claude
         model: claude-sonnet-4-5
         enable_multimodal_tools: true

Video Frame Extraction (v0.1.56+)
-----------------------------------

Video understanding (for non-Gemini backends) extracts frames from the video and sends them as images. You can configure the extraction strategy via ``multimodal_config.video``:

.. code-block:: yaml

   backend:
     enable_multimodal_tools: true
     multimodal_config:
       video:
         extraction_mode: "scene"   # "scene" (default) or "uniform"
         max_frames: 30             # Hard cap (default: 30, absolute max: 60)
         fps: 1.0                   # Frames/sec for uniform mode (default: 1.0)
         threshold: 0.3             # Scene detection sensitivity (scene mode)
         frames_per_scene: 3        # Frames per detected scene (scene mode)
         num_frames: 8              # Legacy fixed count (overrides fps if set)

**Extraction Modes:**

- **scene** (default): Uses PySceneDetect to find scene boundaries, then samples frames within each scene. Produces better coverage of meaningful content and avoids wasting tokens on static segments. Falls back to uniform if PySceneDetect is not installed.
- **uniform**: Evenly spaced frames. Uses ``fps`` (default 1.0) to compute frame count based on video duration, or ``num_frames`` for a fixed count.

**Frame Cap Behavior:**

- ``max_frames`` is configurable (default 30), but cannot exceed the absolute maximum of 60
- A 10-second video at 1 FPS produces 10 frames (good coverage)
- A 2-minute video at 1 FPS produces 30 frames (hits default cap)
- A 30-minute video at 1 FPS produces 30 frames (capped, cost-safe)
- Setting ``num_frames: 8`` explicitly gives exactly 8 frames (backward compatible)

**Installation for Scene Detection:**

.. code-block:: bash

   pip install massgen[video]

If PySceneDetect is not installed, scene mode gracefully falls back to uniform extraction.

Legacy Tools
------------

Individual Understanding Tools
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The unified ``read_media`` tool internally delegates to these specialized tools:

- ``understand_image``: Routes to agent's native backend (OpenAI, Claude, Gemini, Grok, Claude Code, Codex)
- ``understand_audio``: OpenAI Whisper transcription + gpt-4o analysis
- ``understand_video``: Routes to best available backend (Gemini native, or frame extraction via OpenAI/Claude/Grok)

These tools are **not automatically registered** when ``enable_multimodal_tools: true``. They are only used internally by ``read_media``.

**When to use them directly**: You can manually register them via ``custom_tools`` if you need:

- Fine control over frame extraction (videos)
- Custom audio transcription settings
- Specific vision model configurations

Individual Generation Tools
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Legacy generation tools have been superseded by ``generate_media``:

- ❌ ``text_to_image_generation`` → Use ``generate_media(mode="image")``
- ❌ ``text_to_video_generation`` → Use ``generate_media(mode="video")``
- ❌ ``text_to_speech_transcription_generation`` → Use ``generate_media(mode="audio")``

These tools are **not automatically registered** when ``enable_multimodal_tools: true``.

**Migration**: Update your configs to use the unified ``generate_media`` tool.

Manual Tool Registration
^^^^^^^^^^^^^^^^^^^^^^^^

If you need specific legacy tools, manually register them:

.. code-block:: yaml

   agents:
     - id: my_agent
       backend:
         custom_tools:
           - name: ["understand_video"]
             category: "multimodal"
             path: "massgen/tool/_multimodal_tools/understand_video.py"
             function: ["understand_video"]
             config:
               num_frames: 16  # More detailed analysis

Examples
--------

Complete Multimodal Workflow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: yaml

   # config.yaml
   agents:
     - id: multimodal_agent
       backend:
         type: openai
         model: gpt-4o
         enable_multimodal_tools: true
         multimodal_config:
           image:
             backend: openai
             model: gpt-5.2
           video:
             backend: google
             model: veo-3.1-generate-preview

   task: |
     1. Generate an image of a futuristic city
     2. Analyze the generated image
     3. Generate a 4-second video panning across the city

Agent interaction:

.. code-block:: python

   # Agent automatically uses the right tools
   result1 = generate_media("futuristic city with flying cars", mode="image")
   # -> Saves to: workspace/generated_image_20250122_123456.png

   result2 = read_media("generated_image_20250122_123456.png",
                        prompt="Describe this cityscape")
   # -> "The image shows a sprawling metropolis with towering skyscrapers..."

   result3 = generate_media(
       prompt="slow pan across futuristic city with neon lights",
       mode="video",
       duration=4
   )
   # -> Saves to: workspace/generated_video_20250122_123500.mp4

Multi-Agent with Specialized Backends
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: yaml

   agents:
     - id: image_specialist
       backend:
         type: openai
         model: gpt-4o
         enable_multimodal_tools: true
         multimodal_config:
           image:
             backend: openai
             model: gpt-5.2  # Best for images

     - id: video_specialist
       backend:
         type: gemini
         model: gemini-2.5-pro
         enable_multimodal_tools: true
         multimodal_config:
           video:
             backend: google
             model: veo-3.1-generate-preview  # Best for videos

Troubleshooting
---------------

API Key Issues
^^^^^^^^^^^^^^

Ensure required API keys are set:

.. code-block:: bash

   # For OpenAI (images, video, audio)
   export OPENAI_API_KEY="sk-..."

   # For Google/Gemini (images, video)
   export GEMINI_API_KEY="..."

   # For Grok/xAI (images, video)
   export XAI_API_KEY="..."

   # For ElevenLabs (audio: speech, music, SFX, voice editing)
   export ELEVENLABS_API_KEY="..."

   # For OpenRouter (images)
   export OPENROUTER_API_KEY="..."

No Backend Available
^^^^^^^^^^^^^^^^^^^^

If you see "No backend available for {mode} generation":

1. Check API keys are set
2. Verify backend supports the media type (see Supported Backends above)
3. Check ``multimodal_config`` if using custom backends

Path Access Errors
^^^^^^^^^^^^^^^^^^

If media files can't be read:

1. Use relative paths from workspace (recommended)
2. Or use absolute paths within allowed directories
3. Check file exists and has correct extension

File Size Limits
^^^^^^^^^^^^^^^^

Be aware of backend limits:

- **Input images**: 4MB per image (PNG, JPEG only)
- **Google Video**: Varies by duration and resolution
- **Audio**: Generally generous limits

See Also
--------

- :doc:`/reference/yaml_schema` - Full configuration reference
- :doc:`/reference/supported_models` - Supported models by backend
