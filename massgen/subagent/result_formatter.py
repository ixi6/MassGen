"""
Subagent Result Formatter for MassGen

Formats subagent results for injection into parent agent context.
Used by SubagentCompleteHook to format background subagent completion results.
"""

from massgen.subagent.models import SubagentResult


def format_single_result(subagent_id: str, result: SubagentResult) -> str:
    """
    Format a single subagent result in XML structure.

    The format provides clear boundaries for agent parsing, includes metadata
    about execution, and contains the full answer or error information.

    Args:
        subagent_id: ID of the subagent
        result: The SubagentResult from execution

    Returns:
        XML-formatted string containing the result
    """
    # Build token usage element if available
    token_element = ""
    if result.token_usage:
        input_tokens = result.token_usage.get("input_tokens", 0)
        output_tokens = result.token_usage.get("output_tokens", 0)
        token_element = f'\n  <token_usage input="{input_tokens}" output="{output_tokens}" />'

    # Determine the content to display
    if result.answer:
        content = result.answer
    elif result.error:
        content = f"Error: {result.error}"
    else:
        content = "No output"

    # Include completion percentage if available (for timeout recovery)
    completion_info = ""
    if result.completion_percentage is not None:
        completion_info = f"\n  <completion_percentage>{result.completion_percentage}%</completion_percentage>"

    return f"""<subagent_result id="{subagent_id}" status="{result.status}">
  <execution_time>{result.execution_time_seconds:.1f}s</execution_time>
  <workspace>{result.workspace_path}</workspace>{token_element}{completion_info}
  <answer success="{str(result.success).lower()}">
{content}
  </answer>
</subagent_result>"""


def format_batch_results(results: list[tuple[str, SubagentResult]]) -> str:
    """
    Format multiple subagent results for batch injection.

    When multiple subagents complete between tool calls, their results
    are batched together in a single injection to minimize disruption.

    Args:
        results: List of (subagent_id, SubagentResult) tuples

    Returns:
        Formatted string containing all results with header
    """
    if not results:
        return ""

    count = len(results)
    separator = "=" * 60

    # Format each result
    formatted_results = []
    for subagent_id, result in results:
        formatted_results.append(format_single_result(subagent_id, result))

    # Build the batch output with header
    header = f"""
{separator}
BACKGROUND SUBAGENT RESULTS ({count} completed)
{separator}
"""

    return header + "\n".join(formatted_results) + f"\n{separator}\n"
