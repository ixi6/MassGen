import json
from unittest.mock import AsyncMock, patch

import pytest

from massgen.tool._multimodal_tools.generation._base import (
    GenerationResult,
    MediaType,
)
from massgen.tool._multimodal_tools.generation.generate_media import generate_media


def _success_result(config_prompt: str, output_path):
    return GenerationResult(
        success=True,
        output_path=output_path,
        media_type=MediaType.AUDIO,
        backend_name="openai",
        model_used="gpt-4o-mini-tts",
        file_size_bytes=5,
        metadata={"prompt_seen": config_prompt},
    )


@pytest.mark.asyncio
async def test_generate_media_audio_does_not_require_context_md(tmp_path):
    seen_prompt: dict[str, str] = {}

    async def _fake_generate_audio(config):
        seen_prompt["value"] = config.prompt
        config.output_path.write_bytes(b"audio")
        return _success_result(config.prompt, config.output_path)

    with (
        patch("massgen.context.task_context.load_task_context_with_warning", return_value=(None, None)),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-4o-mini-tts"),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_audio",
            new=AsyncMock(side_effect=_fake_generate_audio),
        ),
    ):
        result = await generate_media(
            prompt="Say hello world",
            mode="audio",
            agent_cwd=str(tmp_path),
            allowed_paths=[str(tmp_path)],
        )

    payload = json.loads(result.output_blocks[0].data)
    assert payload["success"] is True
    assert payload["mode"] == "audio"
    assert seen_prompt["value"] == "Say hello world"


@pytest.mark.asyncio
async def test_generate_media_audio_does_not_prepend_task_context(tmp_path):
    seen_prompt: dict[str, str] = {}

    async def _fake_generate_audio(config):
        seen_prompt["value"] = config.prompt
        config.output_path.write_bytes(b"audio")
        return _success_result(config.prompt, config.output_path)

    with (
        patch(
            "massgen.context.task_context.load_task_context_with_warning",
            return_value=("Build an onboarding demo and narration style guide.", None),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.select_backend_and_model",
            return_value=("openai", "gpt-4o-mini-tts"),
        ),
        patch(
            "massgen.tool._multimodal_tools.generation.generate_media.generate_audio",
            new=AsyncMock(side_effect=_fake_generate_audio),
        ),
    ):
        result = await generate_media(
            prompt="Narrate this script",
            mode="audio",
            agent_cwd=str(tmp_path),
            allowed_paths=[str(tmp_path)],
        )

    payload = json.loads(result.output_blocks[0].data)
    assert payload["success"] is True
    assert seen_prompt["value"] == "Narrate this script"
