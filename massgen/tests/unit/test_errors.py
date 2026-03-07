import pytest

from massgen.tool import ToolManager


def faulty_tool_d():
    """A tool that is designed to fail."""
    raise ValueError("This tool is designed to fail.")


@pytest.mark.asyncio
async def test_tool_error_is_handled():
    """Check that a tool's error is caught and returned in an ExecutionResult."""
    tool_manager = ToolManager()
    tool_manager.setup_category(category_name="error_test", description="Error testing tools")
    tool_manager.add_tool_function(func=faulty_tool_d, category="error_test")

    tool_request = {
        "name": "custom_tool__faulty_tool_d",
        "input": {},
    }

    results = []
    async for result in tool_manager.execute_tool(tool_request):
        results.append(result)

    assert len(results) == 1
    result = results[0]
    assert len(result.output_blocks) == 1
    output_block = result.output_blocks[0]
    assert hasattr(output_block, "data")
    assert "Error: This tool is designed to fail." in output_block.data
