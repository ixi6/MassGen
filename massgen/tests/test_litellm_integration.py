#!/usr/bin/env python3
"""
Tests for litellm cost tracking integration.

Verifies that:
- litellm.completion_cost() is used for accurate pricing
- Reasoning tokens are properly tracked (o1/o3 models)
- Cached tokens are properly tracked (Claude caching)
- Fallback works when litellm unavailable or model unknown
"""

from types import SimpleNamespace

import pytest

from massgen.token_manager.token_manager import TokenCostCalculator


class TestLiteLLMIntegration:
    """Test suite for litellm cost calculation integration."""

    def test_calculate_cost_with_usage_dict(self):
        """Test cost calculation with usage dictionary."""
        calc = TokenCostCalculator()

        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        cost = calc.calculate_cost_with_usage_object("gpt-4o", usage, "openai")

        # Should return a positive cost
        assert cost > 0
        assert isinstance(cost, float)

    def test_calculate_cost_with_usage_object(self):
        """Test cost calculation with usage object (SimpleNamespace)."""
        calc = TokenCostCalculator()

        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
        )

        cost = calc.calculate_cost_with_usage_object("gpt-4o", usage, "openai")

        assert cost > 0

    def test_reasoning_tokens_handled(self):
        """Test that reasoning tokens are properly handled (o3-mini)."""
        calc = TokenCostCalculator()

        # Usage with reasoning tokens
        usage_with_reasoning = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {
                "reasoning_tokens": 30,
            },
        }

        cost_with_reasoning = calc.calculate_cost_with_usage_object(
            "o3-mini",
            usage_with_reasoning,
            "openai",
        )

        # Usage without reasoning tokens (for comparison)
        usage_basic = {
            "prompt_tokens": 100,
            "completion_tokens": 20,  # Only non-reasoning tokens
        }

        cost_basic = calc.calculate_cost_with_usage_object(
            "o3-mini",
            usage_basic,
            "openai",
        )

        # Cost with reasoning should be higher (30 extra reasoning tokens)
        assert cost_with_reasoning > cost_basic

    def test_cached_tokens_discount(self):
        """Test that cached tokens get discount pricing (Claude)."""
        calc = TokenCostCalculator()

        # Anthropic format: cache_read_input_tokens is SEPARATE from input_tokens
        # Usage with cache hits (200 new + 800 cached = 1000 total input)
        usage_with_cache = {
            "input_tokens": 200,  # New input tokens (not cached)
            "output_tokens": 200,
            "cache_read_input_tokens": 800,  # Cached tokens (separate field)
            "cache_creation_input_tokens": 0,
        }

        cost_with_cache = calc.calculate_cost_with_usage_object(
            "claude-sonnet-4-5-20250929",
            usage_with_cache,
            "anthropic",
        )

        # Usage without caching (same total tokens: 1000 input, but all non-cached)
        usage_no_cache = {
            "input_tokens": 1000,
            "output_tokens": 200,
        }

        cost_no_cache = calc.calculate_cost_with_usage_object(
            "claude-sonnet-4-5-20250929",
            usage_no_cache,
            "anthropic",
        )

        # Cached cost should be significantly cheaper
        # 800 cached @ 10% vs 1000 full price = savings
        assert cost_with_cache < cost_no_cache
        # Should save at least 30% overall
        assert cost_with_cache < cost_no_cache * 0.7

    def test_fallback_on_unknown_model(self):
        """Test fallback when model not in litellm database."""
        calc = TokenCostCalculator()

        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

        # Custom model unlikely to be in litellm
        cost = calc.calculate_cost_with_usage_object(
            "my-custom-model-xyz",
            usage,
            "custom-provider",
        )

        # Should gracefully return 0 or estimate
        assert cost >= 0

    def test_fallback_extraction_openai_format(self):
        """Test _extract_and_calculate_basic_cost with OpenAI format."""
        calc = TokenCostCalculator()

        usage = {"prompt_tokens": 100, "completion_tokens": 50}

        cost = calc._extract_and_calculate_basic_cost(usage, "openai", "gpt-4o")

        assert cost > 0

    def test_fallback_extraction_anthropic_format(self):
        """Test _extract_and_calculate_basic_cost with Anthropic format."""
        calc = TokenCostCalculator()

        usage = {"input_tokens": 100, "output_tokens": 50}

        cost = calc._extract_and_calculate_basic_cost(usage, "anthropic", "claude-sonnet-4-5")

        assert cost > 0

    def test_empty_usage_returns_zero(self):
        """Test that empty usage returns 0 cost."""
        calc = TokenCostCalculator()

        cost = calc.calculate_cost_with_usage_object("gpt-4o", {}, "openai")

        assert cost == 0.0

    def test_none_usage_returns_zero(self):
        """Test that None usage returns 0 cost."""
        calc = TokenCostCalculator()

        cost = calc._extract_and_calculate_basic_cost(None, "openai", "gpt-4o")

        assert cost == 0.0


class TestLiteLLMCaching:
    """Test litellm pricing database caching."""

    def test_cache_is_populated(self):
        """Test that litellm database is fetched and cached."""
        calc = TokenCostCalculator()

        # First call should fetch
        db1 = calc._fetch_litellm_pricing()

        # Second call should use cache
        db2 = calc._fetch_litellm_pricing()

        # Should return same object (cached)
        assert db1 is db2

    def test_cache_has_models(self):
        """Test that cached database has model data."""
        calc = TokenCostCalculator()

        db = calc._fetch_litellm_pricing()

        if db:  # May fail if network unavailable
            # Should have major models
            assert "gpt-4o" in db or "gpt-4" in db
            assert len(db) > 100  # Should have 100+ models


class TestProviderFormats:
    """Test handling of different provider usage formats."""

    def test_sglang_top_level_reasoning_tokens(self):
        """Test SGLang format with top-level reasoning_tokens field."""
        calc = TokenCostCalculator()

        # SGLang puts reasoning_tokens at top level
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "reasoning_tokens": 30,  # Top-level (SGLang format)
        }

        cost = calc.calculate_cost_with_usage_object("o3-mini", usage, "openai")

        # Should handle reasoning tokens from top-level
        assert cost > 0

        # Compare with nested format (should be equivalent)
        usage_nested = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 30},
        }
        cost_nested = calc.calculate_cost_with_usage_object("o3-mini", usage_nested, "openai")

        # Costs should be very close (within rounding)
        assert abs(cost - cost_nested) < 0.0001

    def test_grok_reasoning_format(self):
        """Test Grok format with output_tokens_details."""
        calc = TokenCostCalculator()

        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "output_tokens_details": {  # Grok uses this name
                "reasoning_tokens": 30,
            },
        }

        cost = calc.calculate_cost_with_usage_object("grok-4-1-fast-reasoning", usage, "xai")

        assert cost > 0

    def test_openai_cached_tokens_format(self):
        """Test OpenAI cached tokens (different from Anthropic)."""
        calc = TokenCostCalculator()

        # OpenAI: cached_tokens are PART OF prompt_tokens (subtract them)
        usage_with_cache = {
            "prompt_tokens": 1000,  # Includes 800 cached
            "completion_tokens": 200,
            "prompt_tokens_details": {
                "cached_tokens": 800,  # These are included in prompt_tokens
            },
        }

        cost_with_cache = calc.calculate_cost_with_usage_object("gpt-4o", usage_with_cache, "openai")

        # Compare with no caching (same total tokens)
        usage_no_cache = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
        }

        cost_no_cache = calc.calculate_cost_with_usage_object("gpt-4o", usage_no_cache, "openai")

        # Cached should be cheaper (800 tokens at discount)
        assert cost_with_cache < cost_no_cache

    def test_openai_top_level_cached_input_tokens_format(self):
        """Test Codex/OpenAI usage format with top-level cached_input_tokens."""
        calc = TokenCostCalculator()

        usage_with_cache = {
            "prompt_tokens": 1000,  # Includes 800 cached
            "completion_tokens": 200,
            "cached_input_tokens": 800,
        }

        breakdown = calc.extract_token_breakdown(usage_with_cache)
        assert breakdown["cached_input_tokens"] == 800

        cost_with_cache = calc.calculate_cost_with_usage_object("gpt-4o", usage_with_cache, "openai")

        usage_no_cache = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
        }
        cost_no_cache = calc.calculate_cost_with_usage_object("gpt-4o", usage_no_cache, "openai")

        assert cost_with_cache < cost_no_cache

    def test_groq_usage_format(self):
        """Test Groq-specific usage format."""
        calc = TokenCostCalculator()

        # Groq uses input_tokens/output_tokens like Anthropic
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0, "reasoning_tokens": 0},
            "output_tokens_details": {"cached_tokens": 0, "reasoning_tokens": 0},
        }

        cost = calc.calculate_cost_with_usage_object("llama-3.3-70b-versatile", usage, "groq")
        assert cost >= 0  # May be 0 if not in litellm, but should not error


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_malformed_usage_objects(self):
        """Test error handling for malformed usage data."""
        calc = TokenCostCalculator()

        # Empty usage
        assert calc.calculate_cost_with_usage_object("gpt-4o", {}, "openai") == 0.0

        # None usage
        cost = calc._extract_and_calculate_basic_cost(None, "openai", "gpt-4o")
        assert cost == 0.0

        # Invalid structure
        usage = {"invalid_field": 123}
        cost = calc.calculate_cost_with_usage_object("gpt-4o", usage, "openai")
        assert cost == 0.0

    def test_missing_nested_details(self):
        """Test handling of None values in details objects."""
        calc = TokenCostCalculator()

        # completion_tokens_details is None (SGLang may do this)
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": None,
        }

        # Should not crash
        cost = calc.calculate_cost_with_usage_object("gpt-4o", usage, "openai")
        assert cost >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
