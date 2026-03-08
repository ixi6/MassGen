"""
Example custom tools for code-based tools demo.

These are full Python implementations (not MCP wrappers) that demonstrate
how custom tools work alongside MCP tools in the code-based paradigm.

NOTE: Custom tools MUST return ExecutionResult (not plain str/int/dict).
"""

from massgen.tool._result import ExecutionResult, TextContent


def reverse_string(text: str) -> ExecutionResult:
    """Reverse a string.

    Args:
        text: The string to reverse

    Returns:
        ExecutionResult containing the reversed string

    Example:
        >>> result = reverse_string("hello")
        >>> result.output_blocks[0].data
        'olleh'
    """
    reversed_text = text[::-1]
    return ExecutionResult(
        output_blocks=[TextContent(data=reversed_text)],
    )


def count_words(text: str) -> ExecutionResult:
    """Count words in a string.

    Args:
        text: The text to count words in

    Returns:
        ExecutionResult containing the word count

    Example:
        >>> result = count_words("hello world")
        >>> result.output_blocks[0].data
        '2'
    """
    word_count = len(text.split())
    return ExecutionResult(
        output_blocks=[TextContent(data=str(word_count))],
    )


def uppercase(text: str) -> ExecutionResult:
    """Convert text to uppercase.

    Args:
        text: The text to convert

    Returns:
        ExecutionResult containing the uppercase text

    Example:
        >>> result = uppercase("hello")
        >>> result.output_blocks[0].data
        'HELLO'
    """
    uppercased = text.upper()
    return ExecutionResult(
        output_blocks=[TextContent(data=uppercased)],
    )
