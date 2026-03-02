"""
Live E2E tests for generate_media — calls real APIs with real keys.

These tests are EXPENSIVE. They are skipped by default and only run when
both ``--run-live-api`` and ``--run-expensive`` flags are passed (or the
corresponding env vars ``RUN_LIVE_API=1`` and ``RUN_EXPENSIVE=1`` are set).

Run examples::

    # Collect only (no API calls)
    uv run pytest massgen/tests/test_generate_media_live.py --collect-only

    # Run all (needs all API keys)
    uv run pytest massgen/tests/test_generate_media_live.py \
        --run-live-api --run-expensive -v -s --timeout=600

    # Run only audio tests (cheapest)
    uv run pytest massgen/tests/test_generate_media_live.py::TestAudioGenerationLive \
        --run-live-api --run-expensive -v -s

    # Run only tests for a specific backend
    uv run pytest massgen/tests/test_generate_media_live.py \
        --run-live-api --run-expensive -v -s -k "openai"
"""

from __future__ import annotations

import json
import math
import os
import struct
import wave
from pathlib import Path

import pytest

from massgen.tool._multimodal_tools.generation.generate_media import generate_media

# ---------------------------------------------------------------------------
# Skip markers — per API key
# ---------------------------------------------------------------------------

_skip_no_openai = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
_skip_no_google = pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"),
    reason="GOOGLE_API_KEY / GEMINI_API_KEY not set",
)
_skip_no_grok = pytest.mark.skipif(
    not os.getenv("XAI_API_KEY"),
    reason="XAI_API_KEY not set",
)
_skip_no_openrouter = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
_skip_no_elevenlabs = pytest.mark.skipif(
    not os.getenv("ELEVENLABS_API_KEY"),
    reason="ELEVENLABS_API_KEY not set",
)
_skip_vertex_only = pytest.mark.skipif(
    not os.getenv("GOOGLE_VERTEX_PROJECT"),
    reason=(
        "Vertex AI only — style_transfer, control_editing, subject_consistency, "
        "inpainting (imagen), negative_prompt/seed/guidance_scale for Imagen "
        "require the Vertex AI client (not Gemini Developer API)"
    ),
)
_skip_elevenlabs_paid = pytest.mark.skipif(
    not os.getenv("ELEVENLABS_PAID"),
    reason=("ElevenLabs paid tier only — music, voice_clone, dubbing require a " "paid subscription (set ELEVENLABS_PAID=1 to enable)"),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_result(result) -> dict:
    """Parse JSON from generate_media ExecutionResult."""
    return json.loads(result.output_blocks[0].data)


def _print_result(label: str, data: dict) -> None:
    """Print formatted debug block (visible with ``-s``)."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    for key in ("success", "error", "backend", "model", "file_path", "file_size"):
        if key in data:
            print(f"  {key}: {data[key]}")
    if "metadata" in data and isinstance(data["metadata"], dict):
        for mk, mv in data["metadata"].items():
            print(f"  metadata.{mk}: {mv}")
    if "continuation_id" in data:
        print(f"  continuation_id: {data['continuation_id']}")
    print(f"{'=' * 60}\n")


# Minimal valid 1×1 red PNG (raw bytes, no PIL dependency).
# NOTE: Only used for the Veo reference-image test fixture (which creates
# its own proper-sized images). All tests that send images to APIs use
# _REAL_IMAGE_PATH instead — most backends reject 1×1 images.
_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"  # signature
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde"  # 1×1 RGB
    b"\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Real test image that APIs will accept (1280×905 JPEG, ~170KB).
_REAL_IMAGE_PATH = Path(__file__).resolve().parent.parent / "configs" / "resources" / "v0.1.3-example" / "multimodality.jpg"


def _make_wav(path: Path, duration_s: float = 1.0, freq_hz: int = 440) -> Path:
    """Create a minimal valid WAV file (mono 16-bit 8 kHz)."""
    sample_rate = 8000
    n_samples = int(sample_rate * duration_s)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = b"".join(
            struct.pack(
                "<h",
                int(16000 * math.sin(2 * math.pi * freq_hz * i / sample_rate)),
            )
            for i in range(n_samples)
        )
        wf.writeframes(frames)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def live_workspace(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Workspace with CONTEXT.md for live tests.

    Set env var ``LIVE_TEST_OUTPUT_DIR`` to save generated media to a
    persistent local directory (e.g., ``test_media_outputs/``) instead
    of the default pytest tmp_path.
    """
    output_dir = os.getenv("LIVE_TEST_OUTPUT_DIR")
    if output_dir:
        base = Path(output_dir).resolve()
        # Create a sub-folder per test to avoid filename collisions
        test_name = request.node.name
        workspace = base / test_name
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        workspace = tmp_path
    (workspace / "CONTEXT.md").write_text(
        "# Test Context\nLive E2E test for generate_media endpoints.",
    )
    return workspace


@pytest.fixture
def fake_png(live_workspace: Path) -> Path:
    """Copy a real image into the workspace for API tests."""
    import shutil

    p = live_workspace / "test_input.jpg"
    shutil.copy2(_REAL_IMAGE_PATH, p)
    return p


@pytest.fixture
def fake_mask_png(live_workspace: Path) -> Path:
    """512×512 RGBA PNG with a transparent centre (for inpainting)."""
    from PIL import Image

    img = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
    # Make the centre 256×256 transparent
    for x in range(128, 384):
        for y in range(128, 384):
            img.putpixel((x, y), (0, 0, 0, 0))
    p = live_workspace / "test_mask.png"
    img.save(str(p))
    return p


@pytest.fixture
def fake_wav(live_workspace: Path) -> Path:
    """5-second 440 Hz sine WAV (meets ElevenLabs 4.6s minimum)."""
    return _make_wav(live_workspace / "test_input.wav", duration_s=5.0)


@pytest.fixture
def fake_wav_pair(live_workspace: Path) -> list[Path]:
    """Two short WAV files for voice cloning."""
    return [
        _make_wav(live_workspace / "sample1.wav", duration_s=1.5, freq_hz=440),
        _make_wav(live_workspace / "sample2.wav", duration_s=1.5, freq_hz=330),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# IMAGE GENERATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestImageGenerationLive:
    """E2E image generation through generate_media()."""

    # -- text-to-image (4 backends) ------------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_text_to_image_openai(self, live_workspace: Path):
        result = await generate_media(
            prompt="A simple red circle on a white background",
            mode="image",
            backend_type="openai",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE text-to-image [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 1000

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_text_to_image_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="A blue square on a white background",
            mode="image",
            backend_type="google",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE text-to-image [google]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 1000

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_text_to_image_grok(self, live_workspace: Path):
        result = await generate_media(
            prompt="A green triangle on a white background",
            mode="image",
            backend_type="grok",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE text-to-image [grok]", data)

        assert data["success"] is True
        assert data["backend"] == "grok"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 1000

    @_skip_no_openrouter
    @pytest.mark.asyncio
    async def test_text_to_image_openrouter(self, live_workspace: Path):
        result = await generate_media(
            prompt="A yellow star on a white background",
            mode="image",
            backend_type="openrouter",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE text-to-image [openrouter]", data)

        assert data["success"] is True
        assert data["backend"] == "openrouter"
        assert Path(data["file_path"]).exists()

    # -- image-to-image (3 backends) -----------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_image_to_image_openai(self, live_workspace: Path, fake_png: Path):
        result = await generate_media(
            prompt="Make the image blue-tinted",
            mode="image",
            backend_type="openai",
            input_images=["test_input.jpg"],
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE image-to-image [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_image_to_image_google(self, live_workspace: Path, fake_png: Path):
        result = await generate_media(
            prompt="Add mountains in the background",
            mode="image",
            backend_type="google",
            input_images=["test_input.jpg"],
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE image-to-image [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_image_to_image_grok(self, live_workspace: Path, fake_png: Path):
        result = await generate_media(
            prompt="Add a decorative border",
            mode="image",
            backend_type="grok",
            input_images=["test_input.jpg"],
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE image-to-image [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- continuation / multi-turn (3 backends) ------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_continuation_openai(self, live_workspace: Path):
        # Step 1 — generate
        r1 = await generate_media(
            prompt="A simple blue square on white",
            mode="image",
            backend_type="openai",
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("continuation_id") or d1.get("metadata", {}).get(
            "continuation_id",
        )
        assert cid, "No continuation_id in first result"

        # Step 2 — continue
        r2 = await generate_media(
            prompt="Add a red circle inside the square",
            mode="image",
            backend_type="openai",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("IMAGE continuation [openai]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_continuation_google(self, live_workspace: Path):
        r1 = await generate_media(
            prompt="A coffee shop logo",
            mode="image",
            backend_type="google",
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("continuation_id") or d1.get("metadata", {}).get(
            "continuation_id",
        )
        assert cid, "No continuation_id in first result"

        r2 = await generate_media(
            prompt="Change the color scheme to blue and gold",
            mode="image",
            backend_type="google",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("IMAGE continuation [google]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_continuation_grok(self, live_workspace: Path):
        r1 = await generate_media(
            prompt="A minimalist mountain logo",
            mode="image",
            backend_type="grok",
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("continuation_id") or d1.get("metadata", {}).get(
            "continuation_id",
        )
        assert cid, "No continuation_id in first result"

        r2 = await generate_media(
            prompt="Add a sunset behind the mountains",
            mode="image",
            backend_type="grok",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("IMAGE continuation [grok]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()

    # -- inpainting (OpenAI) -------------------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_inpainting_openai(
        self,
        live_workspace: Path,
        fake_mask_png: Path,
    ):
        # Generate a real source image first (API needs proper dimensions)
        src = await generate_media(
            prompt="A plain landscape photo",
            mode="image",
            backend_type="openai",
            size="1024x1024",
            agent_cwd=str(live_workspace),
        )
        src_data = _parse_result(src)
        assert src_data["success"] is True
        src_name = Path(src_data["file_path"]).name

        result = await generate_media(
            prompt="Fill the masked area with flowers",
            mode="image",
            backend_type="openai",
            input_images=[src_name],
            mask_path="test_mask.png",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE inpainting [openai]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- Google Imagen advanced editing --------------------------------

    @_skip_no_google
    @_skip_vertex_only
    @pytest.mark.asyncio
    async def test_style_transfer_google(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="A landscape in this artistic style",
            mode="image",
            backend_type="google",
            model="imagen-3.0-capability-001",
            style_image="test_input.jpg",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE style transfer [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @_skip_vertex_only
    @pytest.mark.asyncio
    async def test_control_editing_google(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="A building following this structure",
            mode="image",
            backend_type="google",
            model="imagen-3.0-capability-001",
            control_image="test_input.jpg",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE control editing [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @_skip_vertex_only
    @pytest.mark.asyncio
    async def test_subject_consistency_google(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="The same subject in a beach scene",
            mode="image",
            backend_type="google",
            model="imagen-3.0-capability-001",
            subject_image="test_input.jpg",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE subject consistency [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @_skip_vertex_only
    @pytest.mark.asyncio
    async def test_advanced_params_google_imagen(self, live_workspace: Path):
        result = await generate_media(
            prompt="A cat sitting on a windowsill",
            mode="image",
            backend_type="google",
            model="imagen-4.0-generate-001",
            negative_prompt="dog, blurry, text",
            seed=42,
            guidance_scale=7.0,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE advanced params [google/imagen]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- output format & transparent background (OpenAI) ---------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_output_format_transparent_bg_openai(self, live_workspace: Path):
        result = await generate_media(
            prompt="A simple logo icon",
            mode="image",
            backend_type="openai",
            output_format="png",
            background="transparent",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE transparent bg [openai]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()


# ═══════════════════════════════════════════════════════════════════════════
# VIDEO GENERATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestVideoGenerationLive:
    """E2E video generation through generate_media()."""

    # -- text-to-video (3 backends) ------------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_text_to_video_openai(self, live_workspace: Path):
        result = await generate_media(
            prompt="A cat slowly walking across a room",
            mode="video",
            backend_type="openai",
            duration=4,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO text-to-video [openai/sora]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 5000

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_text_to_video_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="Ocean waves gently hitting a sandy beach",
            mode="video",
            backend_type="google",
            duration=4,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO text-to-video [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 5000

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_text_to_video_grok(self, live_workspace: Path):
        result = await generate_media(
            prompt="Rain drops falling on a window",
            mode="video",
            backend_type="grok",
            duration=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO text-to-video [grok]", data)

        assert data["success"] is True
        assert data["backend"] == "grok"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 5000

    # -- image-to-video (3 backends) -----------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_image_to_video_openai(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="Animate this image with text slowly appearing",
            mode="video",
            backend_type="openai",
            input_images=["test_input.jpg"],
            duration=4,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO image-to-video [openai/sora]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_image_to_video_google(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="Bring this image to life",
            mode="video",
            backend_type="google",
            input_images=["test_input.jpg"],
            duration=4,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO image-to-video [google/veo]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_image_to_video_grok(
        self,
        live_workspace: Path,
        fake_png: Path,
    ):
        result = await generate_media(
            prompt="Make this image move gently",
            mode="video",
            backend_type="grok",
            input_images=["test_input.jpg"],
            duration=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO image-to-video [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- video remix/edit (Sora) & extension (Veo) --------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_video_remix_openai(self, live_workspace: Path):
        """Sora remix: re-edit an existing video with a new prompt.

        Note: Sora has no continuation/extension API. ``remix()`` creates
        a new clip inspired by the source — it does NOT append time.
        """
        # Step 1 — generate source video
        r1 = await generate_media(
            prompt="A ball rolling across a table",
            mode="video",
            backend_type="openai",
            duration=4,
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("metadata", {}).get("continuation_id")
        assert cid, "No continuation_id in first video result"

        # Step 2 — remix with new prompt (same duration as source)
        r2 = await generate_media(
            prompt="The same scene but filmed from a different angle",
            mode="video",
            backend_type="openai",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("VIDEO remix [openai/sora]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_extension_google(self, live_workspace: Path):
        # Extension requires 720p source video, so force it here
        r1 = await generate_media(
            prompt="A sunrise over mountains",
            mode="video",
            backend_type="google",
            duration=8,
            size="720p",
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("metadata", {}).get("continuation_id")
        assert cid, "No continuation_id in first video result"

        # Extension is always 8s at 720p per API requirement
        r2 = await generate_media(
            prompt="Birds start flying across the sky",
            mode="video",
            backend_type="google",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("VIDEO continuation [google/veo]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_video_editing_grok(self, live_workspace: Path):
        r1 = await generate_media(
            prompt="A candle flame flickering",
            mode="video",
            backend_type="grok",
            duration=2,
            agent_cwd=str(live_workspace),
        )
        d1 = _parse_result(r1)
        assert d1["success"] is True
        cid = d1.get("metadata", {}).get("continuation_id")
        assert cid, "No continuation_id in first video result"
        assert cid.startswith("grok_vid_")

        r2 = await generate_media(
            prompt="Make the flame turn blue",
            mode="video",
            continue_from=cid,
            agent_cwd=str(live_workspace),
        )
        d2 = _parse_result(r2)
        _print_result("VIDEO editing [grok]", d2)

        assert d2["success"] is True
        assert Path(d2["file_path"]).exists()


# ═══════════════════════════════════════════════════════════════════════════
# VEO 3.1 FEATURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestVeoFeaturesLive:
    """E2E tests for Veo 3.1 specific features."""

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_audio_google(self, live_workspace: Path):
        """Veo 3.1 generates audio from dialogue/SFX in prompt."""
        result = await generate_media(
            prompt=('A woman walks into a cafe. "I\'ll have a latte, please," ' "she says. The espresso machine hisses in the background."),
            mode="video",
            backend_type="google",
            duration=6,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO audio [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()
        # Audio adds to file size — expect more than a silent video
        assert data["file_size"] > 5000

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_resolution_1080p_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="A slow aerial view of a green valley",
            mode="video",
            backend_type="google",
            size="1080p",
            duration=8,  # 1080p requires 8s
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO resolution 1080p [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_resolution_4k_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="A detailed close-up of a butterfly on a flower",
            mode="video",
            backend_type="google",
            size="4k",
            duration=8,  # 4k requires 8s
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO resolution 4k [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_reference_images_google(
        self,
        live_workspace: Path,
    ):
        from PIL import Image

        # Veo needs a real image (not 1x1) for reference processing
        img = Image.new("RGB", (256, 256), (100, 150, 200))
        img.save(str(live_workspace / "ref1.png"))
        img2 = Image.new("RGB", (256, 256), (200, 100, 50))
        img2.save(str(live_workspace / "ref2.png"))

        result = await generate_media(
            prompt="A cinematic scene inspired by these reference images",
            mode="video",
            backend_type="google",
            video_reference_images=["ref1.png", "ref2.png"],
            duration=8,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO reference_images [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_video_negative_prompt_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="A clear sunny day over a calm lake",
            mode="video",
            backend_type="google",
            negative_prompt="blurry, low quality, text, watermark",
            duration=4,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO negative_prompt [google/veo]", data)

        assert data["success"] is True
        assert data["backend"] == "google"
        assert Path(data["file_path"]).exists()

    # NOTE: Veo does not support the `seed` parameter (Gemini API limitation).
    # Seed is supported for Imagen (image generation) only.


# ═══════════════════════════════════════════════════════════════════════════
# AUDIO GENERATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestAudioGenerationLive:
    """E2E audio generation through generate_media()."""

    # -- speech TTS ----------------------------------------------------

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_speech_tts_elevenlabs(self, live_workspace: Path):
        result = await generate_media(
            prompt="Hello world, this is a live test.",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="speech",
            voice="Rachel",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO speech [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 500

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_speech_tts_openai_with_speed(self, live_workspace: Path):
        result = await generate_media(
            prompt="Hello world, this is a speed test.",
            mode="audio",
            backend_type="openai",
            audio_type="speech",
            voice="alloy",
            speed=1.5,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO speech+speed [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 500

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_speech_tts_openai_with_instructions(self, live_workspace: Path):
        result = await generate_media(
            prompt="Welcome to the show, everyone.",
            mode="audio",
            backend_type="openai",
            audio_type="speech",
            voice="nova",
            instructions="Speak with a warm, reflective tone",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO speech+instructions [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()

    # -- music & SFX ---------------------------------------------------

    @_skip_no_elevenlabs
    @_skip_elevenlabs_paid
    @pytest.mark.asyncio
    async def test_music_generation_elevenlabs(self, live_workspace: Path):
        result = await generate_media(
            prompt="Upbeat jazz piano with soft drums",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="music",
            duration=5,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO music [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 1000

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_sound_effect_elevenlabs(self, live_workspace: Path):
        result = await generate_media(
            prompt="Thunder clap in a mountain valley",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="sound_effect",
            duration=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO sound_effect [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    # -- voice conversion & isolation ----------------------------------

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_voice_conversion_elevenlabs(
        self,
        live_workspace: Path,
        fake_wav: Path,
    ):
        result = await generate_media(
            prompt="convert voice",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="voice_conversion",
            input_audio="test_input.wav",
            voice="Josh",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO voice_conversion [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_audio_isolation_elevenlabs(
        self,
        live_workspace: Path,
        fake_wav: Path,
    ):
        result = await generate_media(
            prompt="isolate audio",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="audio_isolation",
            input_audio="test_input.wav",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO audio_isolation [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    # -- voice design & cloning ----------------------------------------

    @_skip_no_elevenlabs
    @_skip_elevenlabs_paid
    @pytest.mark.asyncio
    async def test_voice_design_elevenlabs(self, live_workspace: Path):
        # ElevenLabs voice design requires text ≥100 characters
        result = await generate_media(
            prompt="A warm male voice with a slight British accent, middle-aged, " "calm and reassuring tone suitable for narrating documentaries " "and audiobooks with clear enunciation",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="voice_design",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO voice_design [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    @_skip_no_elevenlabs
    @_skip_elevenlabs_paid
    @pytest.mark.asyncio
    async def test_voice_cloning_elevenlabs(
        self,
        live_workspace: Path,
        fake_wav_pair: list[Path],
    ):
        sample_names = [p.name for p in fake_wav_pair]
        result = await generate_media(
            prompt="Hello from the cloned voice",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="voice_clone",
            voice_samples=sample_names,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO voice_clone [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    # -- translation & dubbing -----------------------------------------

    @_skip_no_elevenlabs
    @_skip_elevenlabs_paid
    @pytest.mark.asyncio
    async def test_dubbing_elevenlabs(
        self,
        live_workspace: Path,
        fake_wav: Path,
    ):
        result = await generate_media(
            prompt="dub audio",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="dubbing",
            input_audio="test_input.wav",
            target_language="es",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO dubbing [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()

    # -- advanced TTS params -------------------------------------------

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_advanced_tts_params_elevenlabs(self, live_workspace: Path):
        result = await generate_media(
            prompt="Testing voice parameters carefully.",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="speech",
            voice="Sarah",
            voice_stability=0.8,
            voice_similarity=0.9,
            seed=42,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO advanced TTS params [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 500


# ═══════════════════════════════════════════════════════════════════════════
# BATCH MODE
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestBatchModeLive:
    """E2E batch generation (prompts list) through generate_media()."""

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_batch_image_google(self, live_workspace: Path):
        result = await generate_media(
            prompts=["A red apple on a table", "A blue cup on a shelf"],
            mode="image",
            backend_type="google",
            max_concurrent=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("BATCH image [google]", data)

        assert data["success"] is True
        assert data["batch"] is True
        assert data["total"] == 2
        assert data["succeeded"] == 2
        for item in data["results"]:
            assert item["success"] is True
            assert Path(item["file_path"]).exists()

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_batch_audio_openai(self, live_workspace: Path):
        result = await generate_media(
            prompts=["Hello from batch one.", "Hello from batch two."],
            mode="audio",
            backend_type="openai",
            audio_type="speech",
            voice="alloy",
            max_concurrent=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("BATCH audio [openai]", data)

        assert data["success"] is True
        assert data["batch"] is True
        assert data["total"] == 2
        assert data["succeeded"] == 2
        for item in data["results"]:
            assert item["success"] is True
            assert Path(item["file_path"]).exists()


# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER VARIATIONS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.live_api
@pytest.mark.expensive
class TestParameterVariationsLive:
    """Tests for parameter variations not covered by the main tests."""

    # -- aspect_ratio (image) ------------------------------------------

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_aspect_ratio_image_google(self, live_workspace: Path):
        result = await generate_media(
            prompt="A wide panoramic landscape",
            mode="image",
            backend_type="google",
            aspect_ratio="16:9",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE aspect_ratio 16:9 [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_aspect_ratio_image_grok(self, live_workspace: Path):
        result = await generate_media(
            prompt="A tall portrait of a tree",
            mode="image",
            backend_type="grok",
            aspect_ratio="9:16",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE aspect_ratio 9:16 [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- size (image) --------------------------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_size_image_openai(self, live_workspace: Path):
        result = await generate_media(
            prompt="A small square icon",
            mode="image",
            backend_type="openai",
            size="1024x1024",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE size 1024x1024 [openai]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_size_image_grok_1k(self, live_workspace: Path):
        """Grok only supports 1k resolution (xAI SDK Literal['1k'])."""
        result = await generate_media(
            prompt="A detailed flower close-up",
            mode="image",
            backend_type="grok",
            size="1k",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE size 1k [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- aspect_ratio (video) ------------------------------------------

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_aspect_ratio_video_grok(self, live_workspace: Path):
        result = await generate_media(
            prompt="A vertical video of rain on a window",
            mode="video",
            backend_type="grok",
            aspect_ratio="9:16",
            duration=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO aspect_ratio 9:16 [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- size/resolution (video, Grok) ---------------------------------

    @_skip_no_grok
    @pytest.mark.asyncio
    async def test_resolution_video_grok_480p(self, live_workspace: Path):
        result = await generate_media(
            prompt="A simple bouncing ball animation",
            mode="video",
            backend_type="grok",
            size="480p",
            duration=2,
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("VIDEO resolution 480p [grok]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- storage_path --------------------------------------------------

    @_skip_no_google
    @pytest.mark.asyncio
    async def test_storage_path(self, live_workspace: Path):
        output_dir = live_workspace / "media_output"
        result = await generate_media(
            prompt="A simple test pattern",
            mode="image",
            backend_type="google",
            storage_path="media_output",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE storage_path [google]", data)

        assert data["success"] is True
        file_path = Path(data["file_path"])
        assert file_path.exists()
        assert file_path.parent == output_dir

    # -- Google inpainting (mask_path) ---------------------------------

    @_skip_no_google
    @_skip_vertex_only
    @pytest.mark.asyncio
    async def test_inpainting_google(
        self,
        live_workspace: Path,
        fake_png: Path,
        fake_mask_png: Path,
    ):
        result = await generate_media(
            prompt="Fill the masked area with flowers",
            mode="image",
            backend_type="google",
            model="imagen-3.0-capability-001",
            input_images=["test_input.jpg"],
            mask_path="test_mask.png",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("IMAGE inpainting [google]", data)

        assert data["success"] is True
        assert Path(data["file_path"]).exists()

    # -- basic OpenAI speech (no extras) -------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_speech_tts_openai_basic(self, live_workspace: Path):
        result = await generate_media(
            prompt="Hello world, this is a basic test.",
            mode="audio",
            backend_type="openai",
            audio_type="speech",
            voice="alloy",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO speech basic [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        assert Path(data["file_path"]).exists()
        assert data["file_size"] > 500

    # -- audio_format (wav output) -------------------------------------

    @_skip_no_openai
    @pytest.mark.asyncio
    async def test_audio_format_wav_openai(self, live_workspace: Path):
        result = await generate_media(
            prompt="Testing wav format output.",
            mode="audio",
            backend_type="openai",
            audio_type="speech",
            voice="alloy",
            audio_format="wav",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO format=wav [openai]", data)

        assert data["success"] is True
        assert data["backend"] == "openai"
        file_path = Path(data["file_path"])
        assert file_path.exists()
        assert file_path.suffix == ".wav"
        assert data["file_size"] > 500

    @_skip_no_elevenlabs
    @pytest.mark.asyncio
    async def test_audio_format_wav_elevenlabs(self, live_workspace: Path):
        result = await generate_media(
            prompt="Testing wav format from ElevenLabs.",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="speech",
            voice="Rachel",
            audio_format="wav",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO format=wav [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        file_path = Path(data["file_path"])
        assert file_path.exists()
        assert file_path.suffix == ".wav"
        assert data["file_size"] > 500

    # -- dubbing with source_language ----------------------------------

    @_skip_no_elevenlabs
    @_skip_elevenlabs_paid
    @pytest.mark.asyncio
    async def test_dubbing_with_source_language_elevenlabs(
        self,
        live_workspace: Path,
        fake_wav: Path,
    ):
        result = await generate_media(
            prompt="dub audio",
            mode="audio",
            backend_type="elevenlabs",
            audio_type="dubbing",
            input_audio="test_input.wav",
            source_language="en",
            target_language="fr",
            agent_cwd=str(live_workspace),
        )
        data = _parse_result(result)
        _print_result("AUDIO dubbing source_language [elevenlabs]", data)

        assert data["success"] is True
        assert data["backend"] == "elevenlabs"
        assert Path(data["file_path"]).exists()
