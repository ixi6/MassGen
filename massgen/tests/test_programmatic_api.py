#!/usr/bin/env python3
"""
Tests for MassGen programmatic API and LiteLLM integration.

Tests:
- build_config() function with various parameter combinations
- LiteLLM provider registration and model string parsing
- MassGenLLM class methods

Note: Actual run() tests are marked as 'expensive' since they make API calls.
"""

import pytest

import massgen
from massgen import LITELLM_AVAILABLE, build_config


class TestBuildConfig:
    """Test suite for massgen.build_config() function."""

    def test_build_config_default(self):
        """Test default config generation (no parameters)."""
        config = build_config()

        assert "agents" in config
        assert len(config["agents"]) == 2  # Default is 2 agents
        assert "orchestrator" in config

        # Check default model is gpt-5.4 (current default in ConfigBuilder)
        for agent in config["agents"]:
            assert agent["backend"]["model"] == "gpt-5.4"

    def test_build_config_with_num_agents(self):
        """Test config with specified number of agents."""
        config = build_config(num_agents=4)

        assert len(config["agents"]) == 4

    def test_build_config_with_single_model(self):
        """Test config with single model for all agents."""
        config = build_config(model="gpt-4o-mini", num_agents=3)

        assert len(config["agents"]) == 3
        for agent in config["agents"]:
            assert agent["backend"]["model"] == "gpt-4o-mini"

    def test_build_config_with_multiple_models(self):
        """Test config with different models per agent."""
        models = ["gpt-5", "claude-sonnet-4-5-20250929", "gemini-2.5-flash"]
        config = build_config(models=models)

        assert len(config["agents"]) == 3

        # Each agent should have the corresponding model
        for i, agent in enumerate(config["agents"]):
            assert agent["backend"]["model"] == models[i]

    def test_build_config_with_explicit_backends(self):
        """Test config with explicit backend types."""
        config = build_config(
            backends=["openai", "claude"],
            models=["gpt-5", "claude-sonnet-4-5-20250929"],
        )

        assert len(config["agents"]) == 2
        assert config["agents"][0]["backend"]["type"] == "openai"
        assert config["agents"][1]["backend"]["type"] == "claude"

    def test_build_config_with_docker(self):
        """Test config with Docker execution enabled."""
        config = build_config(model="gpt-5", num_agents=2, use_docker=True)

        # Docker execution is configured in agent backend
        assert "agents" in config
        backend = config["agents"][0]["backend"]
        assert backend.get("command_line_execution_mode") == "docker"

    def test_build_config_without_docker(self):
        """Test config with local execution (no Docker)."""
        config = build_config(model="gpt-5", num_agents=2, use_docker=False)

        # Local execution mode
        assert "agents" in config
        backend = config["agents"][0]["backend"]
        assert backend.get("command_line_execution_mode") in ["local", None] or "command_line_execution_mode" not in backend

    def test_build_config_with_context_paths(self):
        """Test config with context paths for file operations."""
        config = build_config(
            model="gpt-5",
            num_agents=2,
            context_paths=["/tmp/test_project"],
        )

        # Should have context path in orchestrator
        assert "orchestrator" in config
        # Context path should be set somewhere in the config
        assert config is not None  # Basic validation

    def test_build_config_auto_detects_backend(self):
        """Test that backend is auto-detected from model name."""
        # OpenAI model
        config = build_config(models=["gpt-5"])
        assert config["agents"][0]["backend"]["type"] == "openai"

        # Claude model
        config = build_config(models=["claude-sonnet-4-5-20250929"])
        assert config["agents"][0]["backend"]["type"] == "claude"

        # Gemini model
        config = build_config(models=["gemini-2.5-flash"])
        assert config["agents"][0]["backend"]["type"] == "gemini"

        # Grok model
        config = build_config(models=["grok-4"])
        assert config["agents"][0]["backend"]["type"] == "grok"

        # New Grok default model
        config = build_config(models=["grok-4.20-0309-reasoning"])
        assert config["agents"][0]["backend"]["type"] == "grok"

    def test_build_config_slash_format(self):
        """Test slash format for explicit backend specification."""
        config = build_config(models=["openai/gpt-5", "groq/llama-3.3-70b"])

        assert len(config["agents"]) == 2
        assert config["agents"][0]["backend"]["type"] == "openai"
        assert config["agents"][0]["backend"]["model"] == "gpt-5"
        assert config["agents"][1]["backend"]["type"] == "groq"
        assert config["agents"][1]["backend"]["model"] == "llama-3.3-70b"

    def test_build_config_slash_format_mixed(self):
        """Test mixed slash format and auto-detect."""
        config = build_config(models=["gpt-5", "groq/llama-3.3-70b-versatile"])

        assert len(config["agents"]) == 2
        # First agent: auto-detected
        assert config["agents"][0]["backend"]["type"] == "openai"
        assert config["agents"][0]["backend"]["model"] == "gpt-5"
        # Second agent: explicit slash format
        assert config["agents"][1]["backend"]["type"] == "groq"
        assert config["agents"][1]["backend"]["model"] == "llama-3.3-70b-versatile"

    def test_build_config_slash_format_single_model(self):
        """Test slash format for single model with multiple agents."""
        config = build_config(model="groq/llama-3.3-70b", num_agents=3)

        assert len(config["agents"]) == 3
        for agent in config["agents"]:
            assert agent["backend"]["type"] == "groq"
            assert agent["backend"]["model"] == "llama-3.3-70b"

    def test_build_config_slash_format_cerebras(self):
        """Test slash format with Cerebras provider."""
        config = build_config(models=["cerebras/llama-3.3-70b"])

        assert len(config["agents"]) == 1
        assert config["agents"][0]["backend"]["type"] == "cerebras"
        assert config["agents"][0]["backend"]["model"] == "llama-3.3-70b"

    def test_build_config_base_url_auto_fill(self):
        """Test that base_url is auto-filled for OpenAI-compatible providers."""
        # Groq should have base_url auto-filled
        config = build_config(models=["groq/llama-3.3-70b"])
        assert config["agents"][0]["backend"]["base_url"] == "https://api.groq.com/openai/v1"

        # Cerebras should have base_url auto-filled
        config = build_config(models=["cerebras/llama-3.3-70b"])
        assert config["agents"][0]["backend"]["base_url"] == "https://api.cerebras.ai/v1"

        # Together should have base_url auto-filled
        config = build_config(models=["together/llama-3.3-70b"])
        assert config["agents"][0]["backend"]["base_url"] == "https://api.together.xyz/v1"

        # OpenAI should NOT have base_url (uses native client)
        config = build_config(models=["openai/gpt-5"])
        assert "base_url" not in config["agents"][0]["backend"]

    def test_build_config_base_url_qwen(self):
        """Test that Qwen provider gets correct base_url."""
        config = build_config(models=["qwen/qwen-max"])

        assert config["agents"][0]["backend"]["type"] == "qwen"
        assert config["agents"][0]["backend"]["model"] == "qwen-max"
        assert config["agents"][0]["backend"]["base_url"] == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


@pytest.mark.skipif(not LITELLM_AVAILABLE, reason="LiteLLM not installed")
class TestLiteLLMProvider:
    """Test suite for LiteLLM provider integration."""

    def test_litellm_available(self):
        """Test that LiteLLM is available."""
        assert LITELLM_AVAILABLE is True

    def test_register_with_litellm(self):
        """Test registering MassGen as a LiteLLM provider."""
        import litellm

        from massgen import register_with_litellm

        # Register
        register_with_litellm()

        # Check it's registered
        assert hasattr(litellm, "custom_provider_map")
        assert litellm.custom_provider_map is not None

        # Find massgen in providers
        provider_names = [p.get("provider") for p in litellm.custom_provider_map]
        assert "massgen" in provider_names

    def test_register_idempotent(self):
        """Test that registering multiple times doesn't duplicate."""
        import litellm

        from massgen import register_with_litellm

        # Register twice
        register_with_litellm()
        register_with_litellm()

        # Should only have one massgen provider
        massgen_count = sum(1 for p in litellm.custom_provider_map if p.get("provider") == "massgen")
        assert massgen_count == 1

    def test_massgen_llm_class_exists(self):
        """Test that MassGenLLM class is importable."""
        from massgen import MassGenLLM

        assert MassGenLLM is not None

    def test_massgen_llm_instantiation(self):
        """Test MassGenLLM can be instantiated."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        assert llm is not None


@pytest.mark.skipif(not LITELLM_AVAILABLE, reason="LiteLLM not installed")
class TestModelStringParsing:
    """Test suite for model string parsing in LiteLLM provider."""

    def test_parse_model_build(self):
        """Test parsing massgen/build model string."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        config, model, is_build = llm._parse_model("massgen/build")

        assert config is None
        assert model is None
        assert is_build is True

    def test_parse_model_single_agent(self):
        """Test parsing massgen/model:X model string."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        config, model, is_build = llm._parse_model("massgen/model:gpt-5")

        assert config is None
        assert model == "gpt-5"
        assert is_build is False

    def test_parse_model_config_path(self):
        """Test parsing massgen/path:X model string."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        config, model, is_build = llm._parse_model("massgen/path:/tmp/config.yaml")

        assert config == "/tmp/config.yaml"
        assert model is None
        assert is_build is False

    def test_parse_model_example_config(self):
        """Test parsing massgen/example_name model string."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        config, model, is_build = llm._parse_model("massgen/basic_multi")

        assert config == "@examples/basic_multi"
        assert model is None
        assert is_build is False

    def test_parse_model_various_examples(self):
        """Test parsing various example config names."""
        from massgen import MassGenLLM

        llm = MassGenLLM()

        test_cases = [
            ("massgen/three_agents_default", "@examples/three_agents_default"),
            ("massgen/tools/mcp/weather", "@examples/tools/mcp/weather"),
            ("massgen/providers/gemini/gemini_flash", "@examples/providers/gemini/gemini_flash"),
        ]

        for model_str, expected_config in test_cases:
            config, model, is_build = llm._parse_model(model_str)
            assert config == expected_config, f"Failed for {model_str}"
            assert model is None
            assert is_build is False


@pytest.mark.skipif(not LITELLM_AVAILABLE, reason="LiteLLM not installed")
class TestQueryExtraction:
    """Test suite for query extraction from messages."""

    def test_extract_query_simple(self):
        """Test extracting query from simple messages."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        messages = [{"role": "user", "content": "What is AI?"}]

        query = llm._extract_query(messages)
        assert query == "What is AI?"

    def test_extract_query_last_user_message(self):
        """Test that last user message is extracted."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]

        query = llm._extract_query(messages)
        assert query == "Second question"

    def test_extract_query_multimodal_content(self):
        """Test extracting text from multimodal content."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
                ],
            },
        ]

        query = llm._extract_query(messages)
        assert query == "Describe this image"

    def test_extract_query_empty_messages(self):
        """Test extracting from empty messages list."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        query = llm._extract_query([])
        assert query == ""

    def test_extract_query_no_user_message(self):
        """Test extracting when no user message exists."""
        from massgen import MassGenLLM

        llm = MassGenLLM()
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "Hello!"},
        ]

        query = llm._extract_query(messages)
        assert query == ""


class TestRunFunctionSignature:
    """Test suite for massgen.run() function signature and validation."""

    def test_run_function_exists(self):
        """Test that run() function is exported."""
        assert hasattr(massgen, "run")
        assert callable(massgen.run)

    def test_run_is_async(self):
        """Test that run() is an async function."""
        import inspect

        assert inspect.iscoroutinefunction(massgen.run)


@pytest.mark.expensive
class TestRunFunctionIntegration:
    """Integration tests for massgen.run() - these make actual API calls.

    Run with: pytest -m expensive
    """

    @pytest.mark.asyncio
    async def test_run_with_single_model(self):
        """Test run() with single model."""
        result = await massgen.run(
            query="What is 2+2? Answer with just the number.",
            model="gpt-5-nano",  # Use cheapest model
        )

        assert "final_answer" in result
        assert "4" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_run_with_models_list(self):
        """Test run() with multiple models."""
        result = await massgen.run(
            query="What is 2+2? Answer with just the number.",
            models=["gpt-5-nano", "gpt-5-nano"],  # Two cheap agents
        )

        assert "final_answer" in result
        assert "4" in result["final_answer"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not expensive"])
