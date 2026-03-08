import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from massgen.message_templates import MessageTemplates
from massgen.system_message_builder import SystemMessageBuilder

LEGACY_WRAPPERS = (
    "text_to_image_generation",
    "text_to_video_generation",
    "text_to_speech_transcription_generation",
)

LEGACY_MEDIA_ANALYSIS_TOOLS = (
    "understand_image",
    "understand_audio",
    "understand_video",
)

REMOVED_MODALITY_PROMPT_SECTIONS = (
    "For image generation tasks:",
    "For audio generation tasks:",
    "For video generation tasks:",
)


def test_final_presentation_omits_modality_specific_media_workflows():
    templates = MessageTemplates()

    message = templates.final_presentation_system_message()

    for section in REMOVED_MODALITY_PROMPT_SECTIONS:
        assert section not in message


def test_final_presentation_omits_media_analysis_workflow_sections():
    templates = MessageTemplates()

    message = templates.final_presentation_system_message()

    for section in REMOVED_MODALITY_PROMPT_SECTIONS:
        assert section not in message
    for legacy in LEGACY_MEDIA_ANALYSIS_TOOLS:
        assert legacy not in message


def test_multimodal_yaml_examples_do_not_register_legacy_generation_wrappers():
    configs_dir = Path("massgen/configs/tools/custom_tools/multimodal_tools")
    generation_examples = [
        configs_dir / "text_to_image_generation_single.yaml",
        configs_dir / "text_to_image_generation_multi.yaml",
        configs_dir / "text_to_video_generation_single.yaml",
        configs_dir / "text_to_video_generation_multi.yaml",
        configs_dir / "text_to_speech_generation_single.yaml",
        configs_dir / "text_to_speech_generation_multi.yaml",
    ]

    for config_path in generation_examples:
        config = yaml.safe_load(config_path.read_text())
        agents = config.get("agents", [])

        found_generate_media = False
        for agent in agents:
            custom_tools = agent.get("backend", {}).get("custom_tools", [])
            for tool in custom_tools:
                names = tool.get("name", [])
                function_names = tool.get("function", [])
                path = tool.get("path", "")

                if "generate_media" in names:
                    found_generate_media = True
                    assert path == "massgen/tool/_multimodal_tools/generation/generate_media.py"
                    assert function_names == ["generate_media"]

                for legacy in LEGACY_WRAPPERS:
                    assert legacy not in names
                    assert legacy not in function_names
                    assert f"/{legacy}.py" not in path

        assert found_generate_media


def test_multimodal_tool_docs_promote_direct_generate_media_calls_only():
    tool_md = Path("massgen/tool/_multimodal_tools/TOOL.md").read_text()

    assert "generate_media" in tool_md
    for legacy in LEGACY_WRAPPERS:
        assert legacy not in tool_md


def test_config_builder_multimodal_picker_uses_generate_media():
    config_builder_source = Path("massgen/config_builder.py").read_text()

    assert 'value="generate_media"' in config_builder_source
    assert "generation/generate_media.py" in config_builder_source
    for legacy in LEGACY_WRAPPERS:
        assert legacy not in config_builder_source


def test_final_presentation_signature_does_not_include_unused_modality_flags():
    signature = inspect.signature(MessageTemplates.final_presentation_system_message)

    assert "enable_image_generation" not in signature.parameters
    assert "enable_audio_generation" not in signature.parameters
    assert "enable_video_generation" not in signature.parameters


def test_system_message_builder_presentation_signature_does_not_include_unused_modality_flags():
    signature = inspect.signature(SystemMessageBuilder.build_presentation_message)

    assert "enable_image_generation" not in signature.parameters
    assert "enable_audio_generation" not in signature.parameters
    assert "enable_video_generation" not in signature.parameters


def _build_presentation_builder() -> SystemMessageBuilder:
    config = SimpleNamespace(coordination_config=SimpleNamespace(enable_changedoc=False))
    return SystemMessageBuilder(
        config=config,
        message_templates=MessageTemplates(),
        agents={},
    )


def _build_agent_for_presentation(
    *,
    enable_multimodal_tools: bool = False,
    custom_tools: list[dict] | None = None,
):
    backend = MagicMock()
    backend.config = {
        "model": "gpt-4o-mini",
        "enable_multimodal_tools": enable_multimodal_tools,
    }
    if custom_tools is not None:
        backend.config["custom_tools"] = custom_tools
    backend.filesystem_manager = None
    backend.backend_params = {}

    agent = MagicMock()
    agent.get_configurable_system_message.return_value = "You are Agent A."
    agent.backend = backend
    agent.config = None
    return agent


def test_presentation_message_omits_modality_specific_media_workflows_when_multimodal_enabled():
    builder = _build_presentation_builder()
    agent = _build_agent_for_presentation(enable_multimodal_tools=True)

    message = builder.build_presentation_message(
        agent=agent,
        all_answers={"agent_a": "Answer A"},
        previous_turns=[],
    )

    for section in REMOVED_MODALITY_PROMPT_SECTIONS:
        assert section not in message


def test_presentation_message_omits_modality_specific_media_workflows_when_tool_explicitly_configured():
    builder = _build_presentation_builder()
    agent = _build_agent_for_presentation(
        enable_multimodal_tools=False,
        custom_tools=[
            {
                "name": ["generate_media"],
                "path": "massgen/tool/_multimodal_tools/generation/generate_media.py",
                "function": ["generate_media"],
            },
        ],
    )

    message = builder.build_presentation_message(
        agent=agent,
        all_answers={"agent_a": "Answer A"},
        previous_turns=[],
    )

    for section in REMOVED_MODALITY_PROMPT_SECTIONS:
        assert section not in message
