"""Regression tests for multimodal tool context param wiring."""

from massgen.tool._multimodal_tools.read_media import read_media


def test_read_media_declares_workspace_context_params():
    """read_media must request workspace context injection for background execution."""
    context_params = set(getattr(read_media, "__context_params__", set()))
    assert "agent_cwd" in context_params
    assert "allowed_paths" in context_params
    assert "multimodal_config" in context_params
    assert "task_context" in context_params
