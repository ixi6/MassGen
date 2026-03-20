"""
Tests for backend capabilities registry.

These tests ensure the capabilities registry is consistent and valid.
Run with: uv run pytest massgen/tests/test_backend_capabilities.py -v
"""

import pytest

from massgen.backend.capabilities import (
    BACKEND_CAPABILITIES,
    get_all_backend_types,
    get_backends_with_capability,
    get_capabilities,
    has_capability,
    validate_backend_config,
)


class TestBackendCapabilitiesRegistry:
    """Test the capabilities registry structure and validity."""

    def test_all_backends_have_required_fields(self):
        """Ensure all backend entries have required fields."""
        for backend_type, caps in BACKEND_CAPABILITIES.items():
            assert caps.backend_type == backend_type, f"{backend_type}: backend_type mismatch"
            assert caps.provider_name, f"{backend_type}: provider_name is empty"
            assert caps.supported_capabilities is not None, f"{backend_type}: supported_capabilities is None"
            assert caps.builtin_tools is not None, f"{backend_type}: builtin_tools is None"
            assert caps.filesystem_support in ["none", "native", "mcp"], f"{backend_type}: invalid filesystem_support"
            assert caps.models, f"{backend_type}: models list is empty"
            assert caps.default_model, f"{backend_type}: default_model is empty"

    def test_default_model_in_models_list(self):
        """Ensure default model exists in models list."""
        for backend_type, caps in BACKEND_CAPABILITIES.items():
            assert caps.default_model in caps.models, f"{backend_type}: default_model '{caps.default_model}' not in models list"

    def test_openai_default_model_is_gpt54(self):
        """OpenAI should advertise GPT-5.4 as the default model."""
        caps = BACKEND_CAPABILITIES["openai"]
        assert caps.default_model == "gpt-5.4"
        assert caps.models[0] == "gpt-5.4"

    def test_codex_default_model_is_gpt54(self):
        """Codex should advertise GPT-5.4 as the default model."""
        caps = BACKEND_CAPABILITIES["codex"]
        assert caps.default_model == "gpt-5.4"
        assert caps.models[0] == "gpt-5.4"

    def test_grok_default_model_is_grok_420_reasoning(self):
        """Grok should advertise grok-4.20-0309-reasoning as the default model."""
        caps = BACKEND_CAPABILITIES["grok"]
        assert caps.default_model == "grok-4.20-0309-reasoning"
        assert caps.models[0] == "grok-4.20-0309-reasoning"

    def test_filesystem_support_values(self):
        """Ensure filesystem_support has valid values."""
        valid_values = {"none", "native", "mcp"}
        for backend_type, caps in BACKEND_CAPABILITIES.items():
            assert caps.filesystem_support in valid_values, f"{backend_type}: filesystem_support '{caps.filesystem_support}' " f"not in {valid_values}"

    def test_no_empty_backend_types(self):
        """Ensure no backend has an empty backend_type."""
        for backend_type, caps in BACKEND_CAPABILITIES.items():
            assert backend_type, "Found backend with empty backend_type"
            assert caps.backend_type, f"Backend {backend_type} has empty backend_type field"

    def test_capability_strings_are_valid(self):
        """Ensure capability strings follow conventions."""
        valid_capabilities = {
            "web_search",
            "code_execution",
            "bash",
            "multimodal",  # Legacy - being phased out
            "vision",  # Legacy - use image_understanding
            "mcp",
            "filesystem_native",
            "filesystem_mcp",
            "reasoning",
            "image_generation",
            "image_understanding",
            "audio_generation",
            "audio_understanding",
            "video_generation",
            "video_understanding",
            "tool_search",  # Claude-specific
            "programmatic_tool_calling",  # Claude-specific
        }

        for backend_type, caps in BACKEND_CAPABILITIES.items():
            for cap in caps.supported_capabilities:
                assert cap in valid_capabilities, f"{backend_type}: unknown capability '{cap}'. " f"Valid capabilities: {valid_capabilities}"


class TestCapabilityQueries:
    """Test capability query functions."""

    def test_get_capabilities_existing_backend(self):
        """Test getting capabilities for existing backends."""
        caps = get_capabilities("openai")
        assert caps is not None
        assert caps.backend_type == "openai"
        assert caps.provider_name == "OpenAI"

    def test_get_capabilities_nonexistent_backend(self):
        """Test getting capabilities for non-existent backend."""
        caps = get_capabilities("nonexistent_backend")
        assert caps is None

    def test_has_capability_true(self):
        """Test checking for existing capability."""
        # OpenAI has web_search
        assert has_capability("openai", "web_search") is True

    def test_has_capability_false(self):
        """Test checking for non-existent capability."""
        # LM Studio doesn't have web_search
        assert has_capability("lmstudio", "web_search") is False

    def test_has_capability_nonexistent_backend(self):
        """Test checking capability on non-existent backend."""
        assert has_capability("nonexistent", "web_search") is False

    @pytest.mark.parametrize(
        ("backend_type", "expected_backend_type"),
        [
            ("OpenAI", "openai"),
            ("Claude", "claude"),
            ("Grok", "grok"),
            ("Azure OpenAI", "azure_openai"),
            ("ChatCompletion", "chatcompletion"),
            ("Together AI", "together"),
            ("Fireworks AI", "fireworks"),
            ("OpenRouter", "openrouter"),
            ("Kimi", "moonshot"),
            ("Nvidia NIM", "nvidia_nim"),
        ],
    )
    def test_get_capabilities_normalizes_known_display_names(self, backend_type, expected_backend_type):
        """Display-name provider labels should resolve to canonical backend ids."""
        caps = get_capabilities(backend_type)
        assert caps is not None
        assert caps.backend_type == expected_backend_type

    @pytest.mark.parametrize(
        ("backend_type", "capability"),
        [
            ("OpenAI", "image_understanding"),
            ("Claude", "image_understanding"),
            ("Grok", "image_understanding"),
            ("Azure OpenAI", "image_understanding"),
        ],
    )
    def test_has_capability_accepts_display_names(self, backend_type, capability):
        """Display-name provider labels should work in capability checks."""
        assert has_capability(backend_type, capability) is True

    def test_get_all_backend_types(self):
        """Test getting all backend types."""
        backend_types = get_all_backend_types()
        assert len(backend_types) > 0
        assert "openai" in backend_types
        assert "claude" in backend_types
        assert "gemini" in backend_types

    def test_get_backends_with_capability(self):
        """Test getting backends by capability."""
        web_search_backends = get_backends_with_capability("web_search")
        assert "openai" in web_search_backends
        assert "gemini" in web_search_backends
        assert "grok" in web_search_backends
        assert "claude_code" in web_search_backends  # claude_code has WebSearch/WebFetch tools

        # Backends without web search should not be included
        assert "lmstudio" not in web_search_backends


class TestBackendValidation:
    """Test backend configuration validation."""

    def test_validate_valid_openai_config(self):
        """Test validating a valid OpenAI config."""
        config = {
            "type": "openai",
            "model": "gpt-4o",
            "enable_web_search": True,
            "enable_code_interpreter": True,
        }
        errors = validate_backend_config("openai", config)
        assert len(errors) == 0

    def test_validate_invalid_capability(self):
        """Test validation catches unsupported capability."""
        # LM Studio doesn't support web_search
        config = {
            "type": "lmstudio",
            "enable_web_search": True,
        }
        errors = validate_backend_config("lmstudio", config)
        assert len(errors) > 0
        assert any("web_search" in error for error in errors)

    def test_validate_invalid_backend_type(self):
        """Test validation catches unknown backend."""
        config = {"type": "nonexistent"}
        errors = validate_backend_config("nonexistent", config)
        assert len(errors) > 0
        assert any("Unknown backend" in error for error in errors)

    def test_validate_code_execution_variants(self):
        """Test validation handles different code execution config keys."""
        # OpenAI uses enable_code_interpreter
        config_openai = {"type": "openai", "enable_code_interpreter": True}
        errors = validate_backend_config("openai", config_openai)
        assert len(errors) == 0

        # Claude uses enable_code_execution
        config_claude = {"type": "claude", "enable_code_execution": True}
        errors = validate_backend_config("claude", config_claude)
        assert len(errors) == 0

    def test_validate_mcp_servers(self):
        """Test validation of MCP server configuration."""
        # Valid MCP config for backend that supports it
        config = {
            "type": "openai",
            "mcp_servers": [
                {
                    "name": "weather",
                    "command": "npx",
                    "args": ["-y", "@fak111/weather-mcp"],
                },
            ],
        }
        errors = validate_backend_config("openai", config)
        assert len(errors) == 0


class TestSpecificBackends:
    """Test specific backend configurations."""

    def test_openai_capabilities(self):
        """Test OpenAI backend capabilities."""
        caps = get_capabilities("openai")
        assert "web_search" in caps.supported_capabilities
        assert "code_execution" in caps.supported_capabilities
        assert "mcp" in caps.supported_capabilities
        assert "reasoning" in caps.supported_capabilities
        assert "image_generation" in caps.supported_capabilities
        assert "image_understanding" in caps.supported_capabilities
        assert "audio_generation" in caps.supported_capabilities
        assert "video_generation" in caps.supported_capabilities
        assert caps.filesystem_support == "mcp"
        assert caps.env_var == "OPENAI_API_KEY"

    def test_claude_capabilities(self):
        """Test Claude backend capabilities."""
        caps = get_capabilities("claude")
        assert "web_search" in caps.supported_capabilities
        assert "code_execution" in caps.supported_capabilities
        assert "mcp" in caps.supported_capabilities
        assert caps.filesystem_support == "mcp"
        assert caps.env_var == "ANTHROPIC_API_KEY"

    def test_claude_code_capabilities(self):
        """Test Claude Code backend capabilities."""
        caps = get_capabilities("claude_code")
        assert "bash" in caps.supported_capabilities
        assert "mcp" in caps.supported_capabilities
        assert "reasoning" in caps.supported_capabilities
        assert caps.filesystem_support == "native"
        assert caps.env_var == "ANTHROPIC_API_KEY"
        assert len(caps.builtin_tools) > 0

    def test_codex_capabilities_include_reasoning(self):
        """Codex quickstart should advertise reasoning-capable GPT-5 models."""
        caps = get_capabilities("codex")
        assert "reasoning" in caps.supported_capabilities

    def test_claude_code_models_include_sonnet_46_after_opus_46(self):
        """Claude Code quickstart models should list Sonnet 4.6 right after Opus 4.6."""
        caps = get_capabilities("claude_code")
        assert caps is not None
        assert "claude-opus-4-6" in caps.models
        assert "claude-sonnet-4-6" in caps.models
        assert caps.models.index("claude-sonnet-4-6") == caps.models.index("claude-opus-4-6") + 1

    def test_gemini_capabilities(self):
        """Test Gemini backend capabilities."""
        caps = get_capabilities("gemini")
        assert "web_search" in caps.supported_capabilities
        assert "code_execution" in caps.supported_capabilities
        assert "mcp" in caps.supported_capabilities
        assert "image_understanding" in caps.supported_capabilities
        assert caps.filesystem_support == "mcp"
        assert caps.env_var == "GEMINI_API_KEY"

    def test_gemini_cli_capabilities(self):
        """Test Gemini CLI backend capabilities."""
        caps = get_capabilities("gemini_cli")
        assert caps is not None
        assert caps.backend_type == "gemini_cli"
        assert "bash" in caps.supported_capabilities
        assert "mcp" in caps.supported_capabilities
        assert "filesystem_native" in caps.supported_capabilities
        assert caps.filesystem_support == "native"
        assert caps.env_var == "GOOGLE_API_KEY"
        assert "gemini-2.5-pro" in caps.models

    def test_gemini_cli_model_release_dates(self):
        """Test Gemini CLI has model_release_dates populated."""
        caps = get_capabilities("gemini_cli")
        assert caps.model_release_dates is not None
        assert len(caps.model_release_dates) > 0
        # Every model in the list should have a release date
        for model in caps.models:
            assert model in caps.model_release_dates, f"Model {model} missing from model_release_dates"

    def test_gemini_cli_builtin_tools_use_actual_names(self):
        """Test Gemini CLI builtin_tools use actual Gemini CLI tool names."""
        caps = get_capabilities("gemini_cli")
        assert "run_shell_command" in caps.builtin_tools
        assert "read_file" in caps.builtin_tools
        assert "write_file" in caps.builtin_tools
        assert "replace" in caps.builtin_tools
        # Old wrong names should not be present
        assert "shell" not in caps.builtin_tools
        assert "file_read" not in caps.builtin_tools
        assert "file_write" not in caps.builtin_tools
        assert "file_edit" not in caps.builtin_tools

    def test_gemini_cli_deprecated_model_removed(self):
        """gemini-3-pro-preview (deprecated March 9 2026) must not be in models."""
        caps = get_capabilities("gemini_cli")
        assert "gemini-3-pro-preview" not in caps.models
        if caps.model_release_dates:
            assert "gemini-3-pro-preview" not in caps.model_release_dates

    def test_local_backends_no_api_key(self):
        """Test local backends don't require API keys."""
        local_backends = ["lmstudio", "inference", "chatcompletion"]
        for backend_type in local_backends:
            caps = get_capabilities(backend_type)
            # These backends may or may not require API keys depending on provider
            # Just verify they're in the registry
            assert caps is not None


class TestConsistency:
    """Test consistency between related fields."""

    def test_filesystem_native_implies_capability(self):
        """Backends with native filesystem should have filesystem capability."""
        for backend_type, caps in BACKEND_CAPABILITIES.items():
            if caps.filesystem_support == "native":
                # Should have filesystem_native in capabilities
                assert "filesystem_native" in caps.supported_capabilities or len(caps.builtin_tools) > 0, f"{backend_type}: native filesystem but no capability/tools"  # Or have filesystem tools

    def test_mcp_capability_consistency(self):
        """All backends should support MCP except where explicitly excluded."""
        # Most backends support MCP
        mcp_backends = get_backends_with_capability("mcp")
        assert len(mcp_backends) > 0
        assert "openai" in mcp_backends
        assert "claude" in mcp_backends
        assert "gemini" in mcp_backends


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
