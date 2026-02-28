"""Tests for Grok (xAI) image and video generation backends."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from massgen.tool._multimodal_tools.generation._base import (
    GenerationConfig,
    MediaType,
)

# ---------------------------------------------------------------------------
# Grok image generation tests
# ---------------------------------------------------------------------------


class TestGrokImageGeneration:
    """Tests for _generate_image_grok() backend."""

    @pytest.mark.asyncio
    async def test_grok_image_returns_error_when_no_api_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Missing XAI_API_KEY should return an error result."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.tool._multimodal_tools.generation._image import (
            _generate_image_grok,
        )

        config = GenerationConfig(
            prompt="A cat in space",
            output_path=tmp_path / "cat.png",
            media_type=MediaType.IMAGE,
            backend="grok",
        )

        result = await _generate_image_grok(config)

        assert result.success is False
        assert "XAI_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_grok_image_calls_xai_sdk_image_sample(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Should call client.image.sample() with correct params."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        fake_b64 = base64.b64encode(b"fake-png-bytes").decode()
        mock_response = MagicMock()
        mock_response.base64 = fake_b64
        mock_response.model = "grok-imagine-image"
        mock_response.prompt = "A cat in space"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="A cat in space",
            output_path=tmp_path / "cat.png",
            media_type=MediaType.IMAGE,
            backend="grok",
            model="grok-imagine-image",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        mock_image_client.sample.assert_awaited_once()
        call_kwargs = mock_image_client.sample.call_args.kwargs
        assert call_kwargs["prompt"] == "A cat in space"
        assert call_kwargs["model"] == "grok-imagine-image"
        assert call_kwargs["image_format"] == "base64"

    @pytest.mark.asyncio
    async def test_grok_image_saves_base64_to_output_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Decoded base64 should be written to the output file."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        raw_bytes = b"fake-png-image-data"
        fake_b64 = base64.b64encode(raw_bytes).decode()

        mock_response = MagicMock()
        mock_response.base64 = fake_b64
        mock_response.model = "grok-imagine-image"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        output_path = tmp_path / "output.png"
        config = GenerationConfig(
            prompt="Test",
            output_path=output_path,
            media_type=MediaType.IMAGE,
            backend="grok",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        assert output_path.exists()
        assert output_path.read_bytes() == raw_bytes
        assert result.file_size_bytes == len(raw_bytes)

    @pytest.mark.asyncio
    async def test_grok_image_returns_continuation_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Result metadata should include continuation_id starting with grok_img_."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        fake_b64 = base64.b64encode(b"img").decode()
        mock_response = MagicMock()
        mock_response.base64 = fake_b64
        mock_response.model = "grok-imagine-image"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="Test",
            output_path=tmp_path / "out.png",
            media_type=MediaType.IMAGE,
            backend="grok",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        assert "continuation_id" in result.metadata
        assert result.metadata["continuation_id"].startswith("grok_img_")

    @pytest.mark.asyncio
    async def test_grok_image_continuation_passes_image_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """continue_from should retrieve stored base64 and pass as image_url data URI."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        from massgen.tool._multimodal_tools.generation import _image as image_mod
        from massgen.tool._multimodal_tools.generation._image import (
            _grok_image_store,
        )

        # Store a fake base64 image
        stored_b64 = base64.b64encode(b"original-image").decode()
        store_id = _grok_image_store.save(stored_b64)

        # Mock SDK for second call
        new_b64 = base64.b64encode(b"edited-image").decode()
        mock_response = MagicMock()
        mock_response.base64 = new_b64
        mock_response.model = "grok-imagine-image"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="Make it brighter",
            output_path=tmp_path / "edited.png",
            media_type=MediaType.IMAGE,
            backend="grok",
            continue_from=store_id,
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        call_kwargs = mock_image_client.sample.call_args.kwargs
        assert call_kwargs["image_url"] == f"data:image/png;base64,{stored_b64}"

    @pytest.mark.asyncio
    async def test_grok_image_continuation_not_found_returns_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Invalid continuation ID should return error."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="Edit this",
            output_path=tmp_path / "edit.png",
            media_type=MediaType.IMAGE,
            backend="grok",
            continue_from="grok_img_nonexistent",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_grok_image_aspect_ratio_passed_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """config.aspect_ratio should be passed through to sample()."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        fake_b64 = base64.b64encode(b"img").decode()
        mock_response = MagicMock()
        mock_response.base64 = fake_b64
        mock_response.model = "grok-imagine-image"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="A landscape",
            output_path=tmp_path / "landscape.png",
            media_type=MediaType.IMAGE,
            backend="grok",
            aspect_ratio="16:9",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        call_kwargs = mock_image_client.sample.call_args.kwargs
        assert call_kwargs["aspect_ratio"] == "16:9"

    @pytest.mark.asyncio
    async def test_grok_image_size_mapped_to_resolution(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """config.size='2k' should map to resolution='2k' in sample()."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        fake_b64 = base64.b64encode(b"img").decode()
        mock_response = MagicMock()
        mock_response.base64 = fake_b64
        mock_response.model = "grok-imagine-image"

        mock_image_client = AsyncMock()
        mock_image_client.sample = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.image = mock_image_client

        from massgen.tool._multimodal_tools.generation import _image as image_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(image_mod, "xai_sdk", mock_sdk)

        config = GenerationConfig(
            prompt="Hi-res",
            output_path=tmp_path / "hires.png",
            media_type=MediaType.IMAGE,
            backend="grok",
            size="2k",
        )

        result = await image_mod._generate_image_grok(config)

        assert result.success is True
        call_kwargs = mock_image_client.sample.call_args.kwargs
        assert call_kwargs["resolution"] == "2k"


# ---------------------------------------------------------------------------
# Grok image size mapping tests
# ---------------------------------------------------------------------------


class TestGrokImageSizeMapping:
    """Tests for _map_size_to_grok_resolution() helper."""

    def test_2k_maps_to_2k(self):
        from massgen.tool._multimodal_tools.generation._image import (
            _map_size_to_grok_resolution,
        )

        assert _map_size_to_grok_resolution("2k") == "2k"

    def test_2K_uppercase_maps_to_2k(self):
        from massgen.tool._multimodal_tools.generation._image import (
            _map_size_to_grok_resolution,
        )

        assert _map_size_to_grok_resolution("2K") == "2k"

    def test_2048x2048_maps_to_2k(self):
        from massgen.tool._multimodal_tools.generation._image import (
            _map_size_to_grok_resolution,
        )

        assert _map_size_to_grok_resolution("2048x2048") == "2k"

    def test_default_maps_to_1k(self):
        from massgen.tool._multimodal_tools.generation._image import (
            _map_size_to_grok_resolution,
        )

        assert _map_size_to_grok_resolution("1024x1024") == "1k"

    def test_none_maps_to_1k(self):
        from massgen.tool._multimodal_tools.generation._image import (
            _map_size_to_grok_resolution,
        )

        assert _map_size_to_grok_resolution(None) == "1k"


# ---------------------------------------------------------------------------
# Grok video generation tests
# ---------------------------------------------------------------------------


class TestGrokVideoGeneration:
    """Tests for _generate_video_grok() backend."""

    @pytest.mark.asyncio
    async def test_grok_video_returns_error_when_no_api_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Missing XAI_API_KEY should return an error result."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)

        from massgen.tool._multimodal_tools.generation._video import (
            _generate_video_grok,
        )

        config = GenerationConfig(
            prompt="A robot walking",
            output_path=tmp_path / "robot.mp4",
            media_type=MediaType.VIDEO,
            backend="grok",
        )

        result = await _generate_video_grok(config)

        assert result.success is False
        assert "XAI_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_grok_video_calls_xai_sdk_video_generate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Should call client.video.generate() with correct params."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        mock_response = MagicMock()
        mock_response.url = "https://example.com/video.mp4"
        mock_response.duration = 5
        mock_response.model = "grok-imagine-video"

        mock_video_client = AsyncMock()
        mock_video_client.generate = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.video = mock_video_client

        from massgen.tool._multimodal_tools.generation import _video as video_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(video_mod, "xai_sdk", mock_sdk)

        # Mock requests.get for video download
        mock_get_response = MagicMock()
        mock_get_response.content = b"fake-video-bytes"
        mock_get_response.raise_for_status = MagicMock()
        monkeypatch.setattr(video_mod.requests, "get", MagicMock(return_value=mock_get_response))

        config = GenerationConfig(
            prompt="A robot walking",
            output_path=tmp_path / "robot.mp4",
            media_type=MediaType.VIDEO,
            backend="grok",
            model="grok-imagine-video",
            duration=5,
        )

        result = await video_mod._generate_video_grok(config)

        assert result.success is True
        mock_video_client.generate.assert_awaited_once()
        call_kwargs = mock_video_client.generate.call_args.kwargs
        assert call_kwargs["prompt"] == "A robot walking"
        assert call_kwargs["model"] == "grok-imagine-video"
        assert call_kwargs["duration"] == 5

    @pytest.mark.asyncio
    async def test_grok_video_saves_downloaded_content(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Video bytes from URL should be written to output file."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        video_bytes = b"mp4-video-content-here"

        mock_response = MagicMock()
        mock_response.url = "https://example.com/video.mp4"
        mock_response.duration = 5
        mock_response.model = "grok-imagine-video"

        mock_video_client = AsyncMock()
        mock_video_client.generate = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.video = mock_video_client

        from massgen.tool._multimodal_tools.generation import _video as video_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(video_mod, "xai_sdk", mock_sdk)

        mock_get_response = MagicMock()
        mock_get_response.content = video_bytes
        mock_get_response.raise_for_status = MagicMock()
        monkeypatch.setattr(video_mod.requests, "get", MagicMock(return_value=mock_get_response))

        output_path = tmp_path / "output.mp4"
        config = GenerationConfig(
            prompt="Test video",
            output_path=output_path,
            media_type=MediaType.VIDEO,
            backend="grok",
            duration=5,
        )

        result = await video_mod._generate_video_grok(config)

        assert result.success is True
        assert output_path.exists()
        assert output_path.read_bytes() == video_bytes

    @pytest.mark.asyncio
    async def test_grok_video_duration_clamped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """Duration should be clamped to 1-15 range."""
        monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

        mock_response = MagicMock()
        mock_response.url = "https://example.com/video.mp4"
        mock_response.duration = 15
        mock_response.model = "grok-imagine-video"

        mock_video_client = AsyncMock()
        mock_video_client.generate = AsyncMock(return_value=mock_response)

        mock_client = MagicMock()
        mock_client.video = mock_video_client

        from massgen.tool._multimodal_tools.generation import _video as video_mod

        mock_sdk = MagicMock()
        mock_sdk.AsyncClient.return_value = mock_client
        monkeypatch.setattr(video_mod, "xai_sdk", mock_sdk)

        mock_get_response = MagicMock()
        mock_get_response.content = b"video"
        mock_get_response.raise_for_status = MagicMock()
        monkeypatch.setattr(video_mod.requests, "get", MagicMock(return_value=mock_get_response))

        # Test duration > 15 gets clamped to 15
        config = GenerationConfig(
            prompt="Long video",
            output_path=tmp_path / "long.mp4",
            media_type=MediaType.VIDEO,
            backend="grok",
            duration=20,
        )

        await video_mod._generate_video_grok(config)
        call_kwargs = mock_video_client.generate.call_args.kwargs
        assert call_kwargs["duration"] == 15

        # Test duration < 1 gets clamped to 1
        config2 = GenerationConfig(
            prompt="Short video",
            output_path=tmp_path / "short.mp4",
            media_type=MediaType.VIDEO,
            backend="grok",
            duration=0,
        )

        await video_mod._generate_video_grok(config2)
        call_kwargs2 = mock_video_client.generate.call_args.kwargs
        assert call_kwargs2["duration"] == 1


# ---------------------------------------------------------------------------
# Grok video size mapping tests
# ---------------------------------------------------------------------------


class TestGrokVideoSizeMapping:
    """Tests for _map_size_to_grok_video_resolution() helper."""

    def test_480_maps_to_480p(self):
        from massgen.tool._multimodal_tools.generation._video import (
            _map_size_to_grok_video_resolution,
        )

        assert _map_size_to_grok_video_resolution("480") == "480p"

    def test_480p_maps_to_480p(self):
        from massgen.tool._multimodal_tools.generation._video import (
            _map_size_to_grok_video_resolution,
        )

        assert _map_size_to_grok_video_resolution("480p") == "480p"

    def test_default_maps_to_720p(self):
        from massgen.tool._multimodal_tools.generation._video import (
            _map_size_to_grok_video_resolution,
        )

        assert _map_size_to_grok_video_resolution("1080p") == "720p"

    def test_none_maps_to_720p(self):
        from massgen.tool._multimodal_tools.generation._video import (
            _map_size_to_grok_video_resolution,
        )

        assert _map_size_to_grok_video_resolution(None) == "720p"
