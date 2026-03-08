"""Tests for Grok (xAI) backend registration, priority, and auto-selection."""

import pytest

from massgen.tool._multimodal_tools.generation._base import (
    BACKEND_API_KEYS,
    BACKEND_PRIORITY,
    MediaType,
    get_default_model,
)
from massgen.tool._multimodal_tools.generation._selector import (
    select_backend_and_model,
)

# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


def test_grok_api_key_registered():
    """BACKEND_API_KEYS should map grok to XAI_API_KEY."""
    assert "grok" in BACKEND_API_KEYS
    assert BACKEND_API_KEYS["grok"] == ["XAI_API_KEY"]


def test_grok_default_image_model():
    """Default image model for grok should be grok-imagine-image."""
    assert get_default_model("grok", MediaType.IMAGE) == "grok-imagine-image"


def test_grok_default_video_model():
    """Default video model for grok should be grok-imagine-video."""
    assert get_default_model("grok", MediaType.VIDEO) == "grok-imagine-video"


# ---------------------------------------------------------------------------
# Priority tests
# ---------------------------------------------------------------------------


def test_image_backend_priority_includes_grok():
    """IMAGE priority should be google > openai > grok > openrouter."""
    assert BACKEND_PRIORITY[MediaType.IMAGE] == [
        "google",
        "openai",
        "grok",
        "openrouter",
    ]


def test_video_backend_priority_grok_first():
    """VIDEO priority should be grok > google > openai."""
    assert BACKEND_PRIORITY[MediaType.VIDEO] == ["grok", "google", "openai"]


# ---------------------------------------------------------------------------
# Auto-selection tests
# ---------------------------------------------------------------------------


def test_image_auto_selection_grok_when_only_xai_key(
    monkeypatch: pytest.MonkeyPatch,
):
    """With only XAI_API_KEY, image auto-selection should pick grok."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")

    backend, model = select_backend_and_model(
        media_type=MediaType.IMAGE,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "grok"
    assert model == "grok-imagine-image"


def test_video_auto_selection_prefers_grok(monkeypatch: pytest.MonkeyPatch):
    """With both XAI_API_KEY and OPENAI_API_KEY, video should prefer grok (first in priority)."""
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    backend, model = select_backend_and_model(
        media_type=MediaType.VIDEO,
        preferred_backend=None,
        preferred_model=None,
        config=None,
    )

    assert backend == "grok"
    assert model == "grok-imagine-video"
