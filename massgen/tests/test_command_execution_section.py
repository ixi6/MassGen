"""Tests for CommandExecutionSection prompt guidance."""

from massgen.system_prompt_sections import CommandExecutionSection


def test_command_execution_section_includes_background_tool_guidance():
    """Prompt should teach the generic background tool lifecycle."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "Background Tool Execution" in content
    assert "custom_tool__start_background_tool" in content
    assert "custom_tool__get_background_tool_status" in content
    assert "custom_tool__get_background_tool_result" in content
    assert "custom_tool__cancel_background_tool" in content
    assert "custom_tool__list_background_tools" in content
    assert "custom_tool__wait_for_background_tool" in content


def test_command_execution_section_lists_long_running_background_candidates():
    """Prompt should suggest practical long-running work for background execution."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "execute_command" in content
    assert "read_media" in content
    assert "generate_media" in content
    assert "test suites" in content
    assert "benchmarks" in content


def test_command_execution_section_requires_media_tools_background():
    """Prompt should explicitly require media tools to run in background."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "Always run `read_media` and `generate_media` in background" in content
    assert "`background: false`" in content


def test_command_execution_section_makes_execute_command_conditional():
    """Prompt should clarify that execute_command can be foreground or background."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "For `execute_command`, choose background mode only for long-running work" in content
    assert "Use foreground when output is needed immediately" in content


def test_command_execution_section_allows_discretion_for_other_tools():
    """Prompt should leave non-media tool backgrounding up to model judgment."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "For other tools, use your judgment" in content


def test_command_execution_section_recommends_wait_tool_when_blocked():
    """Prompt should recommend blocking wait when no meaningful foreground work remains."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "If no meaningful work remains while waiting on background jobs" in content
    assert "custom_tool__wait_for_background_tool" in content


def test_command_execution_section_describes_wait_interrupt_response_shape():
    """Prompt should document early wait interruption payload keys."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "interrupted" in content
    assert "injected_content" in content


def test_command_execution_section_recommends_direct_background_for_custom_tools():
    """Prompt should recommend simpler background=true pattern before wrapper tools."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "Simplest for custom tools" in content
    assert "`background: true` directly on the tool call" in content


def test_command_execution_section_discourages_stringified_json_arguments():
    """Prompt should discourage double-encoding JSON argument payloads."""
    section = CommandExecutionSection()
    content = section.build_content()

    assert "Pass tool arguments as JSON objects" in content
    assert "not escaped or stringified JSON blobs" in content
