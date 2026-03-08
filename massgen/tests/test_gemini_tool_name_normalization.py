"""Tests for Gemini MCP tool-name normalization and alias resolution."""

from massgen.backend.gemini import GeminiBackend


def _make_backend() -> GeminiBackend:
    backend = GeminiBackend(api_key="test-key")
    backend._mcp_functions = {
        "mcp__command_line__execute_command": object(),
        "mcp__filesystem__read_file": object(),
    }
    backend._custom_tool_names.add("custom_tool__start_background_tool")
    return backend


def test_resolves_unprefixed_registered_mcp_tool_name() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("command_line__execute_command")
    assert normalized == "mcp__command_line__execute_command"


def test_resolves_default_api_prefixed_unprefixed_mcp_tool_name() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("default_api:command_line__execute_command")
    assert normalized == "mcp__command_line__execute_command"


def test_preserves_already_prefixed_mcp_tool_name() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("mcp__command_line__execute_command")
    assert normalized == "mcp__command_line__execute_command"


def test_preserves_custom_tool_name() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("custom_tool__start_background_tool")
    assert normalized == "custom_tool__start_background_tool"


def test_leaves_unknown_unprefixed_tool_name_unchanged() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("unknown_server__unknown_tool")
    assert normalized == "unknown_server__unknown_tool"


def test_leaves_workflow_tool_name_unchanged() -> None:
    backend = _make_backend()
    normalized = backend._normalize_and_resolve_tool_name("vote")
    assert normalized == "vote"
