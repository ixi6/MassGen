"""Live API tests for Grok (xAI) image and video generation.

These tests hit the real xAI API and cost money.
Run with: uv run pytest massgen/tests/test_grok_multimedia_live.py --run-live-api -v -s
"""

import os
from pathlib import Path

import pytest

from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    MediaType,
)

_skip_no_key = pytest.mark.skipif(
    not os.getenv("XAI_API_KEY"),
    reason="XAI_API_KEY not set",
)


@pytest.mark.live_api
@pytest.mark.expensive
class TestGrokImageLive:
    """Live API tests for Grok image generation."""

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_image_basic_generation(self, tmp_path: Path):
        """Generate a simple image and verify the file is valid."""
        from massgen.tool._multimodal_tools.generation._image import (
            _generate_image_grok,
        )

        output_path = tmp_path / "grok_test_image.png"
        config = GenerationConfig(
            prompt="A simple red circle on a white background",
            output_path=output_path,
            media_type=MediaType.IMAGE,
            backend="grok",
        )

        result = await _generate_image_grok(config)

        print(f"\n{'='*60}")
        print("GROK IMAGE — basic generation")
        print(f"{'='*60}")
        print(f"  success:         {result.success}")
        print(f"  model:           {result.model_used}")
        print(f"  file_size:       {result.file_size_bytes} bytes")
        print(f"  continuation_id: {result.metadata.get('continuation_id')}")
        print(f"  output_path:     {result.output_path}")
        print(f"{'='*60}\n")

        assert result.success is True
        assert result.backend_name == "grok"
        assert result.model_used == "grok-imagine-image"
        assert output_path.exists()
        assert output_path.stat().st_size > 1000  # Should be a real image
        assert "continuation_id" in result.metadata
        assert result.metadata["continuation_id"].startswith("grok_img_")

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_image_with_aspect_ratio(self, tmp_path: Path):
        """Generate a 16:9 image and verify it succeeds."""
        from massgen.tool._multimodal_tools.generation._image import (
            _generate_image_grok,
        )

        output_path = tmp_path / "grok_wide.png"
        config = GenerationConfig(
            prompt="A panoramic mountain landscape at sunset",
            output_path=output_path,
            media_type=MediaType.IMAGE,
            backend="grok",
            aspect_ratio="16:9",
        )

        result = await _generate_image_grok(config)

        print(f"\n{'='*60}")
        print("GROK IMAGE — 16:9 aspect ratio")
        print(f"{'='*60}")
        print(f"  success:    {result.success}")
        print(f"  file_size:  {result.file_size_bytes} bytes")
        print(f"  output:     {result.output_path}")
        print(f"{'='*60}\n")

        assert result.success is True
        assert output_path.exists()
        assert output_path.stat().st_size > 1000

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_image_2k_resolution(self, tmp_path: Path):
        """Generate a 2k image and verify it's larger than default."""
        from massgen.tool._multimodal_tools.generation._image import (
            _generate_image_grok,
        )

        # Generate 1k (default)
        path_1k = tmp_path / "grok_1k.png"
        config_1k = GenerationConfig(
            prompt="A detailed botanical illustration of a sunflower",
            output_path=path_1k,
            media_type=MediaType.IMAGE,
            backend="grok",
        )
        result_1k = await _generate_image_grok(config_1k)

        # Generate 2k
        path_2k = tmp_path / "grok_2k.png"
        config_2k = GenerationConfig(
            prompt="A detailed botanical illustration of a sunflower",
            output_path=path_2k,
            media_type=MediaType.IMAGE,
            backend="grok",
            size="2k",
        )
        result_2k = await _generate_image_grok(config_2k)

        print(f"\n{'='*60}")
        print("GROK IMAGE — 1k vs 2k resolution")
        print(f"{'='*60}")
        print(f"  1k: success={result_1k.success}, size={result_1k.file_size_bytes}")
        print(f"  2k: success={result_2k.success}, size={result_2k.file_size_bytes}")
        print(f"{'='*60}\n")

        assert result_1k.success is True
        assert result_2k.success is True
        # 2k should be larger than 1k
        assert result_2k.file_size_bytes > result_1k.file_size_bytes

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_image_continuation_editing(self, tmp_path: Path):
        """Generate an image then edit it via continuation."""
        from massgen.tool._multimodal_tools.generation._image import (
            _generate_image_grok,
        )

        # Step 1: Generate initial image
        path_v1 = tmp_path / "grok_v1.png"
        config_v1 = GenerationConfig(
            prompt="A logo for a coffee shop called 'Bean There'",
            output_path=path_v1,
            media_type=MediaType.IMAGE,
            backend="grok",
        )
        result_v1 = await _generate_image_grok(config_v1)
        assert result_v1.success is True
        continuation_id = result_v1.metadata["continuation_id"]

        # Step 2: Edit using continuation
        path_v2 = tmp_path / "grok_v2.png"
        config_v2 = GenerationConfig(
            prompt="Make the text larger and add steam rising from a coffee cup",
            output_path=path_v2,
            media_type=MediaType.IMAGE,
            backend="grok",
            continue_from=continuation_id,
        )
        result_v2 = await _generate_image_grok(config_v2)

        print(f"\n{'='*60}")
        print("GROK IMAGE — continuation editing")
        print(f"{'='*60}")
        print(f"  v1: success={result_v1.success}, size={result_v1.file_size_bytes}")
        print(f"  v1 continuation_id: {continuation_id}")
        print(f"  v2: success={result_v2.success}, size={result_v2.file_size_bytes}")
        print(f"  v2 continuation_id: {result_v2.metadata.get('continuation_id')}")
        print(f"{'='*60}\n")

        assert result_v2.success is True
        assert path_v2.exists()
        assert path_v2.stat().st_size > 1000
        # Should get a new continuation_id for further editing
        assert "continuation_id" in result_v2.metadata


@pytest.mark.live_api
@pytest.mark.expensive
class TestGrokVideoLive:
    """Live API tests for Grok video generation.

    Note: Video generation is slower (can take minutes) and costs more.
    """

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_video_basic_generation(self, tmp_path: Path):
        """Generate a short video and verify the file is valid."""
        from massgen.tool._multimodal_tools.generation._video import (
            _generate_video_grok,
        )

        output_path = tmp_path / "grok_test_video.mp4"
        config = GenerationConfig(
            prompt="A cat slowly walking across a sunny room",
            output_path=output_path,
            media_type=MediaType.VIDEO,
            backend="grok",
            duration=3,
        )

        result = await _generate_video_grok(config)

        print(f"\n{'='*60}")
        print("GROK VIDEO — basic generation")
        print(f"{'='*60}")
        print(f"  success:         {result.success}")
        print(f"  model:           {result.model_used}")
        print(f"  file_size:       {result.file_size_bytes} bytes")
        print(f"  duration:        {result.duration_seconds}s")
        print(f"  gen_time:        {result.metadata.get('generation_time', 0):.1f}s")
        print(f"  output_path:     {result.output_path}")
        if not result.success:
            print(f"  error:           {result.error}")
        print(f"{'='*60}\n")

        assert result.success is True
        assert result.backend_name == "grok"
        assert result.model_used == "grok-imagine-video"
        assert output_path.exists()
        assert output_path.stat().st_size > 5000  # Should be a real video

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_grok_video_with_aspect_ratio(self, tmp_path: Path):
        """Generate a 9:16 vertical video."""
        from massgen.tool._multimodal_tools.generation._video import (
            _generate_video_grok,
        )

        output_path = tmp_path / "grok_vertical.mp4"
        config = GenerationConfig(
            prompt="Rain falling on a window at night, shot vertically",
            output_path=output_path,
            media_type=MediaType.VIDEO,
            backend="grok",
            duration=2,
            aspect_ratio="9:16",
        )

        result = await _generate_video_grok(config)

        print(f"\n{'='*60}")
        print("GROK VIDEO — 9:16 vertical")
        print(f"{'='*60}")
        print(f"  success:    {result.success}")
        print(f"  file_size:  {result.file_size_bytes} bytes")
        print(f"  gen_time:   {result.metadata.get('generation_time', 0):.1f}s")
        if not result.success:
            print(f"  error:      {result.error}")
        print(f"{'='*60}\n")

        assert result.success is True
        assert output_path.exists()


@pytest.mark.live_api
@pytest.mark.expensive
class TestGrokViaGenerateMediaLive:
    """End-to-end tests through the generate_media() entry point."""

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_generate_media_image_grok_backend(self, tmp_path: Path):
        """generate_media(mode='image', backend_type='grok') end-to-end."""
        import json

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        # Create CONTEXT.md (required by generate_media)
        (tmp_path / "CONTEXT.md").write_text(
            "# Test Context\nTesting Grok image generation backend.",
        )

        result = await generate_media(
            prompt="A minimalist logo of a lightning bolt",
            mode="image",
            backend_type="grok",
            agent_cwd=str(tmp_path),
            task_context="Testing Grok image generation backend.",
        )

        data = json.loads(result.output_blocks[0].data)

        print(f"\n{'='*60}")
        print("GENERATE_MEDIA — image via grok")
        print(f"{'='*60}")
        print(json.dumps(data, indent=2))
        print(f"{'='*60}\n")

        assert data["success"] is True
        assert data["backend"] == "grok"
        assert data["model"] == "grok-imagine-image"
        assert "continuation_id" in data
        assert Path(data["file_path"]).exists()

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_generate_media_video_grok_backend(self, tmp_path: Path):
        """generate_media(mode='video', backend_type='grok') end-to-end."""
        import json

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        (tmp_path / "CONTEXT.md").write_text(
            "# Test Context\nTesting Grok video generation backend.",
        )

        result = await generate_media(
            prompt="Ocean waves gently washing onto a sandy beach",
            mode="video",
            backend_type="grok",
            duration=2,
            agent_cwd=str(tmp_path),
            task_context="Testing Grok video generation backend.",
        )

        data = json.loads(result.output_blocks[0].data)

        print(f"\n{'='*60}")
        print("GENERATE_MEDIA — video via grok")
        print(f"{'='*60}")
        print(json.dumps(data, indent=2))
        print(f"{'='*60}\n")

        assert data["success"] is True
        assert data["backend"] == "grok"
        assert data["model"] == "grok-imagine-video"
        assert Path(data["file_path"]).exists()

    @_skip_no_key
    @pytest.mark.asyncio
    async def test_generate_media_image_continuation_e2e(self, tmp_path: Path):
        """Full continuation flow through generate_media()."""
        import json

        from massgen.tool._multimodal_tools.generation.generate_media import (
            generate_media,
        )

        (tmp_path / "CONTEXT.md").write_text(
            "# Test Context\nTesting Grok continuation flow.",
        )

        # Step 1: Initial generation
        result1 = await generate_media(
            prompt="A simple blue square on white background",
            mode="image",
            backend_type="grok",
            agent_cwd=str(tmp_path),
            task_context="Testing Grok continuation flow.",
        )
        data1 = json.loads(result1.output_blocks[0].data)
        assert data1["success"] is True
        continuation_id = data1["continuation_id"]

        # Step 2: Edit via continuation
        result2 = await generate_media(
            prompt="Add a red circle inside the blue square",
            mode="image",
            backend_type="grok",
            continue_from=continuation_id,
            agent_cwd=str(tmp_path),
            task_context="Testing Grok continuation flow.",
        )
        data2 = json.loads(result2.output_blocks[0].data)

        print(f"\n{'='*60}")
        print("GENERATE_MEDIA — continuation e2e")
        print(f"{'='*60}")
        print(f"  v1: {data1['file_path']} ({data1.get('file_size')} bytes)")
        print(f"  v1 continuation_id: {continuation_id}")
        print(f"  v2: {data2.get('file_path')} ({data2.get('file_size')} bytes)")
        print(f"  v2 continuation_id: {data2.get('continuation_id')}")
        if not data2["success"]:
            print(f"  v2 error: {data2.get('error')}")
        print(f"{'='*60}\n")

        assert data2["success"] is True
        assert "continuation_id" in data2
        assert Path(data2["file_path"]).exists()
