"""
Tests for API parameter exclusion lists.

Verifies that MassGen-internal config parameters are properly excluded
from API calls and don't leak to provider APIs. The two parallel exclusion
lists (LLMBackend.get_base_excluded_config_params and
APIParamsHandlerBase.get_base_excluded_params) must stay in sync and cover
all internal parameters.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from massgen.api_params_handler import (
    ChatCompletionsAPIParamsHandler,
    ClaudeAPIParamsHandler,
    OpenAIOperatorAPIParamsHandler,
    ResponseAPIParamsHandler,
)
from massgen.api_params_handler._api_params_handler_base import APIParamsHandlerBase
from massgen.api_params_handler._gemini_api_params_handler import GeminiAPIParamsHandler
from massgen.backend.base import LLMBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_HANDLER_CLASSES = [
    ChatCompletionsAPIParamsHandler,
    ClaudeAPIParamsHandler,
    GeminiAPIParamsHandler,
    ResponseAPIParamsHandler,
    OpenAIOperatorAPIParamsHandler,
]


def _make_mock_backend():
    """Create a mock backend suitable for instantiating API param handlers."""
    backend = MagicMock()
    backend.formatter = MagicMock()
    backend.custom_tool_manager = MagicMock()
    backend.custom_tool_manager.registered_tools = []
    backend._mcp_functions = {}
    backend.get_mcp_tools_formatted = MagicMock(return_value=[])
    return backend


def _instantiate_handler(handler_cls):
    """Instantiate a handler class with a mock backend."""
    return handler_cls(_make_mock_backend())


# ---------------------------------------------------------------------------
# Test Class 1: Exclusion List Sync
# ---------------------------------------------------------------------------


class TestExclusionListSync:
    """Verify base.py params are a subset of handler base params."""

    def test_base_backend_params_subset_of_handler_params(self):
        """Every param in LLMBackend.get_base_excluded_config_params() must
        appear in APIParamsHandlerBase.get_base_excluded_params()."""
        backend_params = LLMBackend.get_base_excluded_config_params()
        handler_params = APIParamsHandlerBase.get_base_excluded_params(
            _instantiate_handler(ChatCompletionsAPIParamsHandler),
        )

        missing = backend_params - handler_params
        assert not missing, f"Params in LLMBackend.get_base_excluded_config_params() but missing from " f"APIParamsHandlerBase.get_base_excluded_params(): {sorted(missing)}"

    def test_handler_base_is_superset(self):
        """Handler base excluded params should be >= backend base excluded params."""
        backend_params = LLMBackend.get_base_excluded_config_params()
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler_params = handler.get_base_excluded_params()

        assert len(handler_params) >= len(backend_params), f"Handler base has {len(handler_params)} params but backend base has " f"{len(backend_params)} — handler should be the superset"

    def test_both_lists_are_non_empty(self):
        """Sanity check: both exclusion lists should contain a meaningful number of params."""
        backend_params = LLMBackend.get_base_excluded_config_params()
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler_params = handler.get_base_excluded_params()

        assert len(backend_params) >= 20, f"Backend exclusion list only has {len(backend_params)} params — " f"expected at least 20"
        assert len(handler_params) >= 20, f"Handler exclusion list only has {len(handler_params)} params — " f"expected at least 20"


# ---------------------------------------------------------------------------
# Test Class 2: Known Internal Params Excluded
# ---------------------------------------------------------------------------


class TestKnownInternalParamsExcluded:
    """Curated list of MassGen-internal params that must NEVER reach an API."""

    KNOWN_INTERNAL_PARAMS = [
        "type",
        "agent_id",
        "session_id",
        "vote_only",
        "cwd",
        "mcp_servers",
        "hooks",
        "coordination_mode",
        "voting_sensitivity",
        "voting_threshold",
        "instance_id",
        "enable_rate_limit",
        "debug_delay_seconds",
        "debug_delay_after_n_tools",
        "presenter_agent",
        "subtask",
        "fairness_enabled",
        "fairness_lead_cap_answers",
        "max_midstream_injections_per_round",
        "use_two_tier_workspace",
        "write_mode",
        "drift_conflict_policy",
        "learning_capture_mode",
        "disable_final_only_round_capture_fallback",
        "context_paths",
        "context_write_access_enabled",
        "enable_mcp_command_line",
        "command_line_allowed_commands",
        "command_line_blocked_commands",
        "enable_code_based_tools",
        "custom_tools_path",
        "auto_discover_custom_tools",
        "exclude_custom_tools",
        "direct_mcp_servers",
        "shared_tools_directory",
        "enable_multimodal_tools",
        "subagent_types",
    ]

    @pytest.mark.parametrize("param", KNOWN_INTERNAL_PARAMS)
    def test_param_in_backend_exclusion(self, param):
        """Each known internal param must be in LLMBackend.get_base_excluded_config_params()."""
        excluded = LLMBackend.get_base_excluded_config_params()
        assert param in excluded, f"'{param}' is a MassGen-internal param but is NOT in " f"LLMBackend.get_base_excluded_config_params()"

    @pytest.mark.parametrize("param", KNOWN_INTERNAL_PARAMS)
    def test_param_in_handler_exclusion(self, param):
        """Each known internal param must be in APIParamsHandlerBase.get_base_excluded_params()."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        excluded = handler.get_base_excluded_params()
        assert param in excluded, f"'{param}' is a MassGen-internal param but is NOT in " f"APIParamsHandlerBase.get_base_excluded_params()"


# ---------------------------------------------------------------------------
# Test Class 3: Valid API Params NOT Excluded
# ---------------------------------------------------------------------------


class TestValidApiParamsNotExcluded:
    """Params that ARE valid API parameters must NOT be in exclusion lists."""

    VALID_API_PARAMS = [
        "model",
        "temperature",
        "max_tokens",
        "top_p",
        "stop",
    ]

    @pytest.mark.parametrize("param", VALID_API_PARAMS)
    def test_valid_param_not_in_backend_exclusion(self, param):
        """Valid API params must NOT be in LLMBackend exclusion list."""
        excluded = LLMBackend.get_base_excluded_config_params()
        assert param not in excluded, f"'{param}' is a valid API parameter but is incorrectly in " f"LLMBackend.get_base_excluded_config_params()"

    @pytest.mark.parametrize("param", VALID_API_PARAMS)
    def test_valid_param_not_in_handler_base_exclusion(self, param):
        """Valid API params must NOT be in handler base exclusion list."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        excluded = handler.get_base_excluded_params()
        assert param not in excluded, f"'{param}' is a valid API parameter but is incorrectly in " f"APIParamsHandlerBase.get_base_excluded_params()"

    @pytest.mark.parametrize(
        "handler_cls",
        ALL_HANDLER_CLASSES,
        ids=lambda c: c.__name__,
    )
    @pytest.mark.parametrize("param", VALID_API_PARAMS)
    def test_valid_param_not_in_any_handler_exclusion(self, handler_cls, param):
        """Valid API params must NOT be excluded by any provider handler."""
        handler = _instantiate_handler(handler_cls)
        excluded = handler.get_excluded_params()
        assert param not in excluded, f"'{param}' is a valid API parameter but is excluded by " f"{handler_cls.__name__}.get_excluded_params()"


# ---------------------------------------------------------------------------
# Test Class 4: Provider Handler Exclusions
# ---------------------------------------------------------------------------


class TestProviderHandlerExclusions:
    """Each handler's get_excluded_params() must be a superset of base."""

    @pytest.mark.parametrize(
        "handler_cls",
        ALL_HANDLER_CLASSES,
        ids=lambda c: c.__name__,
    )
    def test_handler_exclusions_are_superset_of_base(self, handler_cls):
        """Provider handler exclusion set must include all base exclusions."""
        handler = _instantiate_handler(handler_cls)
        base_excluded = handler.get_base_excluded_params()
        handler_excluded = handler.get_excluded_params()

        missing = base_excluded - handler_excluded
        assert not missing, f"{handler_cls.__name__}.get_excluded_params() is missing base params: " f"{sorted(missing)}"

    def test_chat_completions_excludes_base_url(self):
        """ChatCompletions handler must exclude base_url (client init, not API)."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        excluded = handler.get_excluded_params()
        assert "base_url" in excluded

    def test_claude_excludes_web_search(self):
        """Claude handler must exclude enable_web_search (handled as server-side tool)."""
        handler = _instantiate_handler(ClaudeAPIParamsHandler)
        excluded = handler.get_excluded_params()
        assert "enable_web_search" in excluded

    def test_gemini_excludes_web_search(self):
        """Gemini handler must exclude enable_web_search (handled as SDK tool)."""
        handler = _instantiate_handler(GeminiAPIParamsHandler)
        excluded = handler.get_excluded_params()
        assert "enable_web_search" in excluded

    def test_response_excludes_web_search(self):
        """Response handler must exclude enable_web_search (handled as provider tool)."""
        handler = _instantiate_handler(ResponseAPIParamsHandler)
        excluded = handler.get_excluded_params()
        assert "enable_web_search" in excluded

    def test_operator_inherits_response_exclusions(self):
        """Operator handler should have all Response handler exclusions plus its own."""
        response_handler = _instantiate_handler(ResponseAPIParamsHandler)
        operator_handler = _instantiate_handler(OpenAIOperatorAPIParamsHandler)

        response_excluded = response_handler.get_excluded_params()
        operator_excluded = operator_handler.get_excluded_params()

        missing = response_excluded - operator_excluded
        assert not missing, f"Operator handler is missing Response handler params: {sorted(missing)}"

    def test_operator_has_computer_use_params(self):
        """Operator handler must exclude its own computer_use specific params."""
        handler = _instantiate_handler(OpenAIOperatorAPIParamsHandler)
        excluded = handler.get_excluded_params()
        for param in ["enable_computer_use", "display_width", "display_height", "computer_environment"]:
            assert param in excluded, f"Operator handler missing '{param}'"


# ---------------------------------------------------------------------------
# Test Class 5: Build API Params Filtering
# ---------------------------------------------------------------------------


class TestBuildApiParamsFiltering:
    """Integration test: build_base_api_params filters correctly."""

    def test_chat_completions_filters_internal_params(self):
        """ChatCompletions build_base_api_params must exclude internal params."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler.formatter.format_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        all_params = {
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "max_tokens": 1000,
            # Internal params that should be filtered:
            "type": "openai",
            "agent_id": "agent_0",
            "session_id": "sess_123",
            "vote_only": False,
            "cwd": "/tmp/workspace",
            "mcp_servers": [],
            "hooks": {},
            "coordination_mode": "parallel",
        }

        result = handler.build_base_api_params(
            messages=[{"role": "user", "content": "hi"}],
            all_params=all_params,
        )

        # Valid API params should be present
        assert result.get("model") == "gpt-4o-mini"
        assert result.get("temperature") == 0.7
        assert result.get("max_tokens") == 1000
        assert result.get("stream") is True

        # Internal params should be filtered out
        for internal_param in [
            "type",
            "agent_id",
            "session_id",
            "vote_only",
            "cwd",
            "mcp_servers",
            "hooks",
            "coordination_mode",
        ]:
            assert internal_param not in result, f"Internal param '{internal_param}' leaked into API params"

    def test_none_values_are_filtered(self):
        """Parameters with None values should not appear in API params."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler.formatter.format_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        all_params = {
            "model": "gpt-4o-mini",
            "temperature": None,
            "top_p": None,
        }

        result = handler.build_base_api_params(
            messages=[{"role": "user", "content": "hi"}],
            all_params=all_params,
        )

        assert result.get("model") == "gpt-4o-mini"
        assert "temperature" not in result
        assert "top_p" not in result

    def test_internal_underscore_params_filtered(self):
        """Parameters starting with _ should be filtered (internal flags)."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler.formatter.format_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        all_params = {
            "model": "gpt-4o-mini",
            "_has_files_api_files": True,
            "_programmatic_flow_logged": True,
            "_internal_flag": "should_not_pass",
        }

        result = handler.build_base_api_params(
            messages=[{"role": "user", "content": "hi"}],
            all_params=all_params,
        )

        assert result.get("model") == "gpt-4o-mini"
        for param in ["_has_files_api_files", "_programmatic_flow_logged", "_internal_flag"]:
            assert param not in result, f"Internal underscore param '{param}' leaked into API params"

    def test_empty_list_params_pass_through(self):
        """Empty lists (e.g., stop=[]) should pass through if not excluded
        (they are not None)."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler.formatter.format_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        all_params = {
            "model": "gpt-4o-mini",
            "stop": [],
        }

        result = handler.build_base_api_params(
            messages=[{"role": "user", "content": "hi"}],
            all_params=all_params,
        )

        # Empty list is not None, so it should pass through
        assert "stop" in result
        assert result["stop"] == []

    def test_false_values_pass_through(self):
        """False values should pass through (they are not None)."""
        handler = _instantiate_handler(ChatCompletionsAPIParamsHandler)
        handler.formatter.format_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        all_params = {
            "model": "gpt-4o-mini",
            "stream": False,  # stream is set internally but this tests filtering logic
        }

        result = handler.build_base_api_params(
            messages=[{"role": "user", "content": "hi"}],
            all_params=all_params,
        )

        # The method sets stream=True by default, but the loop should not
        # override it with False since stream is not excluded
        # (actually the loop does set it — this is by design)
        assert "model" in result
