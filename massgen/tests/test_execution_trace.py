"""Tests for ExecutionTraceWriter.

TDD tests based on OpenSpec scenarios in:
openspec/changes/add-execution-traces/specs/execution-traces/spec.md
"""

import tempfile
from pathlib import Path

from massgen.execution_trace import ExecutionTraceWriter


class TestExecutionTraceWriter:
    """Tests for ExecutionTraceWriter class."""

    def test_basic_structure(self):
        """Trace file contains metadata header with agent_id, model, and timestamp."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")

        markdown = writer.to_markdown()

        assert "# Execution Trace: agent_a" in markdown
        assert "claude-3-5-sonnet" in markdown
        assert "Started" in markdown  # Format: **Started**: timestamp

    def test_round_section_created(self):
        """Round sections are labeled by answer number."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")

        markdown = writer.to_markdown()

        assert "## Round 1 (Answer 1.1)" in markdown

    def test_tool_call_formatting(self):
        """Tool calls show name and full JSON arguments, searchable format."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/main.py"})

        markdown = writer.to_markdown()

        # Tool name is searchable
        assert "### Tool Call: Read" in markdown
        # Full arguments preserved
        assert '{"file_path": "/workspace/main.py"}' in markdown or '"file_path": "/workspace/main.py"' in markdown

    def test_tool_result_formatting(self):
        """Tool results are preserved in full without truncation."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/main.py"})

        # Simulate a large result that should NOT be truncated
        large_result = "def main():\n" + "    print('line')\n" * 1000
        writer.add_tool_result(name="Read", result=large_result)

        markdown = writer.to_markdown()

        # Full content preserved (check it's not truncated)
        assert "### Tool Result: Read" in markdown
        assert large_result in markdown

    def test_error_tracking(self):
        """Errors are marked and message preserved in full."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Write", args={"file_path": "/etc/config"})
        writer.add_tool_result(
            name="Write",
            result="Permission denied: cannot write to /etc/config",
            is_error=True,
        )

        markdown = writer.to_markdown()

        # Error is clearly marked
        assert "Tool Error" in markdown or "Error" in markdown
        # Full error message preserved
        assert "Permission denied: cannot write to /etc/config" in markdown

    def test_reasoning_content(self):
        """Reasoning appears in dedicated section, full content preserved."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")

        reasoning = "I need to understand the existing code structure before making changes. " * 50
        writer.add_reasoning(reasoning)

        markdown = writer.to_markdown()

        assert "### Reasoning" in markdown
        # Full reasoning preserved (not truncated). Trailing whitespace is
        # normalized by writer formatting, so compare without right padding.
        assert reasoning.rstrip() in markdown

    def test_answer_submission(self):
        """Answer submissions are recorded."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_answer(answer_label="1.1", content="Created output.py with requested functionality")

        markdown = writer.to_markdown()

        assert "Answer Submitted" in markdown
        assert "1.1" in markdown

    def test_vote_submission(self):
        """Vote submissions are recorded with context."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_vote(
            voted_for_agent="agent_b",
            voted_for_label="agent2.1",
            reason="Best implementation approach with thorough testing",
            available_options=["agent1.1", "agent2.1", "agent3.1"],
        )

        markdown = writer.to_markdown()

        # Vote section header
        assert "### Vote Cast: agent2.1" in markdown
        # Available options listed
        assert "agent1.1, agent2.1, agent3.1" in markdown
        # Vote target shown
        assert "**Voted for**: agent2.1" in markdown
        # Reason preserved
        assert "Best implementation approach" in markdown

    def test_vote_without_label(self):
        """Vote with only agent_id (no label) falls back to agent_id."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_vote(
            voted_for_agent="agent_b",
            voted_for_label=None,  # No label available
            reason="Clear and concise solution",
        )

        markdown = writer.to_markdown()

        # Falls back to agent_id when no label
        assert "### Vote Cast: agent_b" in markdown
        assert "**Voted for**: agent_b" in markdown

    def test_multiple_rounds(self):
        """Multiple rounds are tracked separately."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")

        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/a.py"})
        writer.add_tool_result(name="Read", result="content of a")

        writer.start_round(round_num=2, answer_label="1.2")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/b.py"})
        writer.add_tool_result(name="Read", result="content of b")

        markdown = writer.to_markdown()

        assert "## Round 1 (Answer 1.1)" in markdown
        assert "## Round 2 (Answer 1.2)" in markdown
        assert "content of a" in markdown
        assert "content of b" in markdown

    def test_save_to_file(self):
        """Trace can be saved to a file."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Read", args={"file_path": "/workspace/main.py"})
        writer.add_tool_result(name="Read", result="file content")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "execution_trace.md"
            writer.save(path)

            assert path.exists()
            content = path.read_text()
            assert "# Execution Trace: agent_a" in content
            assert "file content" in content

    def test_errors_section_aggregated(self):
        """Errors are aggregated in a dedicated section at the end."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="Write", args={"file_path": "/etc/a"})
        writer.add_tool_result(name="Write", result="Permission denied", is_error=True)
        writer.add_tool_call(name="Write", args={"file_path": "/etc/b"})
        writer.add_tool_result(name="Write", result="Read-only filesystem", is_error=True)

        markdown = writer.to_markdown()

        # Should have an errors section
        assert "## Errors" in markdown
        assert "Permission denied" in markdown
        assert "Read-only filesystem" in markdown

    def test_searchable_format(self):
        """Format is grep-friendly - can search for tool names."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_tool_call(name="mcp__filesystem__read", args={"path": "/test"})
        writer.add_tool_result(name="mcp__filesystem__read", result="test content")

        markdown = writer.to_markdown()

        # Searching for "mcp__filesystem__read" should find the entries
        assert markdown.count("mcp__filesystem__read") >= 2  # Call + Result


class TestReasoningAccumulation:
    """Tests for streaming token accumulation in reasoning."""

    def test_streaming_tokens_accumulated(self):
        """Multiple add_reasoning calls accumulate into single entry."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")

        # Simulate streaming tokens
        writer.add_reasoning("The ")
        writer.add_reasoning("answer ")
        writer.add_reasoning("is ")
        writer.add_reasoning("42.")

        markdown = writer.to_markdown()

        # Should have only ONE reasoning section
        assert markdown.count("### Reasoning") == 1
        # Should have accumulated content
        assert "The answer is 42." in markdown

    def test_tool_call_closes_reasoning_block(self):
        """Tool call after reasoning starts new reasoning block."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")

        # First reasoning block
        writer.add_reasoning("First ")
        writer.add_reasoning("reasoning.")

        # Tool call closes the block
        writer.add_tool_call(name="Read", args={"path": "/test"})
        writer.add_tool_result(name="Read", result="content")

        # Second reasoning block
        writer.add_reasoning("Second ")
        writer.add_reasoning("reasoning.")

        markdown = writer.to_markdown()

        # Should have TWO reasoning sections
        assert markdown.count("### Reasoning") == 2
        assert "First reasoning." in markdown
        assert "Second reasoning." in markdown

    def test_answer_closes_reasoning_block(self):
        """Answer submission closes reasoning block."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")
        writer.start_round(round_num=1, answer_label="1.1")

        writer.add_reasoning("Thinking...")
        writer.add_answer(answer_label="1.1", content="Done")

        # New reasoning should start fresh
        writer.add_reasoning("More thinking")

        markdown = writer.to_markdown()

        assert markdown.count("### Reasoning") == 2

    def test_round_start_closes_reasoning_block(self):
        """Starting a new round closes reasoning block."""
        writer = ExecutionTraceWriter(agent_id="agent_a", model="claude-3-5-sonnet")

        writer.start_round(round_num=1, answer_label="1.1")
        writer.add_reasoning("Round 1 thinking")

        writer.start_round(round_num=2, answer_label="1.2")
        writer.add_reasoning("Round 2 thinking")

        markdown = writer.to_markdown()

        assert markdown.count("### Reasoning") == 2
        assert "Round 1 thinking" in markdown
        assert "Round 2 thinking" in markdown


class TestExecutionTraceIntegration:
    """Integration-style tests for trace with realistic data."""

    def test_realistic_execution_sequence(self):
        """Test a realistic execution sequence similar to actual agent behavior."""
        writer = ExecutionTraceWriter(agent_id="claude_agent_1", model="claude-3-5-sonnet")

        # Round 1: Agent reads files and writes output
        writer.start_round(round_num=1, answer_label="1.1")

        writer.add_reasoning("I'll start by reading the existing code to understand the structure.")

        writer.add_tool_call(name="Read", args={"file_path": "/workspace/src/main.py"})
        writer.add_tool_result(
            name="Read",
            result="""def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
""",
        )

        writer.add_tool_call(
            name="Write",
            args={
                "file_path": "/workspace/src/utils.py",
                "content": "def helper():\n    return 42\n",
            },
        )
        writer.add_tool_result(name="Write", result="Successfully wrote 2 lines to /workspace/src/utils.py")

        writer.add_answer(answer_label="1.1", content="Created utils.py with helper function")

        # Round 2: Agent improves based on feedback
        writer.start_round(round_num=2, answer_label="1.2")

        writer.add_reasoning("Based on the other agent's approach, I should add error handling.")

        writer.add_tool_call(name="Read", args={"file_path": "/workspace/src/utils.py"})
        writer.add_tool_result(name="Read", result="def helper():\n    return 42\n")

        writer.add_tool_call(
            name="Write",
            args={
                "file_path": "/workspace/src/utils.py",
                "content": "def helper():\n    try:\n        return 42\n    except Exception as e:\n        return None\n",
            },
        )
        writer.add_tool_result(name="Write", result="Successfully wrote 5 lines to /workspace/src/utils.py")

        writer.add_answer(answer_label="1.2", content="Updated utils.py with error handling")

        markdown = writer.to_markdown()

        # Verify structure
        assert "# Execution Trace: claude_agent_1" in markdown
        assert "## Round 1 (Answer 1.1)" in markdown
        assert "## Round 2 (Answer 1.2)" in markdown

        # Verify content preservation
        assert 'print("Hello, World!")' in markdown
        assert "def helper():" in markdown
        assert "error handling" in markdown.lower() or "Error" in markdown
