#!/usr/bin/env python3
"""Basic integration checks for key MassGen imports and config creation."""

from importlib import import_module


def _assert_import(module_path: str, attr: str | None = None) -> None:
    module = import_module(module_path)
    assert module is not None
    if attr is not None:
        assert hasattr(module, attr), f"{module_path} is missing expected attribute: {attr}"


def test_cli_import() -> None:
    """CLI module is importable."""
    _assert_import("massgen.cli")


def test_config_creation() -> None:
    """Simple config helper produces expected backend types."""
    from massgen.cli import create_simple_config

    openai_config = create_simple_config(backend_type="openai", model="gpt-4o-mini")
    assert openai_config["agent"]["backend"]["type"] == "openai"

    azure_config = create_simple_config(backend_type="azure_openai", model="gpt-4.1")
    assert azure_config["agent"]["backend"]["type"] == "azure_openai"


def test_agent_config_import() -> None:
    """Agent config module exports AgentConfig."""
    _assert_import("massgen.agent_config", "AgentConfig")


def test_orchestrator_import() -> None:
    """Orchestrator module exports Orchestrator."""
    _assert_import("massgen.orchestrator", "Orchestrator")


def test_backend_base_import() -> None:
    """Backend base module exports LLMBackend."""
    _assert_import("massgen.backend.base", "LLMBackend")


def test_frontend_import() -> None:
    """Frontend coordination UI module exports CoordinationUI."""
    _assert_import("massgen.frontend.coordination_ui", "CoordinationUI")


def test_message_templates_import() -> None:
    """Message templates module exports MessageTemplates."""
    _assert_import("massgen.message_templates", "MessageTemplates")
