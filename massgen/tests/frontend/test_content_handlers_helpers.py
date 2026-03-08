"""Unit tests for content_handlers helper functions."""

from massgen.frontend.displays.content_handlers import (
    get_mcp_server_name,
    get_mcp_tool_name,
    get_tool_category,
    summarize_args,
    summarize_result,
)


def test_get_mcp_server_name_extracts_server():
    assert get_mcp_server_name("mcp__filesystem__write_file") == "filesystem"


def test_get_mcp_server_name_returns_none_for_non_mcp():
    assert get_mcp_server_name("web_search") is None


def test_get_mcp_tool_name_extracts_standard_tool():
    assert get_mcp_tool_name("mcp__filesystem__write_file") == "write_file"


def test_get_mcp_tool_name_extracts_custom_tool_suffix():
    tool_name = "mcp__linear__custom_tool__triage__issue"
    assert get_mcp_tool_name(tool_name) == "triage__issue"


def test_get_mcp_tool_name_returns_none_for_non_mcp():
    assert get_mcp_tool_name("execute_command") is None


def test_get_tool_category_includes_wrapper_icon_for_known_category():
    category = get_tool_category("mcp__filesystem__read_text_file")
    assert category["category"] == "filesystem"
    assert category["icon"] == "\U0001f4c1"


def test_get_tool_category_includes_default_icon_for_unknown_category():
    category = get_tool_category("unknown_tool_name")
    assert category["category"] == "tool"
    assert category["icon"] == "\U0001f527"


def test_summarize_args_formats_supported_types_and_truncates_strings():
    summary = summarize_args(
        {
            "path": "a" * 40,
            "limit": 10,
            "enabled": True,
            "items": [1, 2, 3],
            "config": {"mode": "fast"},
        },
        max_len=400,
    )

    assert f"path: {'a' * 27}..." in summary
    assert "limit: 10" in summary
    assert "enabled: True" in summary
    assert "items: [list]" in summary
    assert "config: [dict]" in summary


def test_summarize_args_returns_empty_for_empty_args():
    assert summarize_args({}) == ""


def test_summarize_args_respects_max_len():
    summary = summarize_args({"a": "x" * 200, "b": "y" * 200}, max_len=20)
    assert len(summary) <= 20
    assert summary.endswith("...")


def test_summarize_result_strips_markers_and_adds_line_count():
    result = summarize_result("[INJECTION] first line\nsecond line")
    assert result == "first line [2 lines]"


def test_summarize_result_skips_json_like_leading_lines():
    result = summarize_result("{\n[1, 2]\nfinal answer")
    assert result == "final answer [3 lines]"


def test_summarize_result_truncates_first_line():
    assert summarize_result("x" * 20, max_len=10) == "xxxxxxx..."


def test_summarize_result_returns_empty_for_empty_input():
    assert summarize_result("") == ""
