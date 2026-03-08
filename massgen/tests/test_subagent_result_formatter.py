"""
Unit tests for subagent result formatter.

Tests for the async subagent execution feature (MAS-214):
- XML format generation
- Single result formatting
- Batch formatting for multiple results
- Metadata inclusion
"""

from massgen.subagent.models import SubagentResult

# =============================================================================
# Single Result Formatting Tests
# =============================================================================


class TestFormatSingleResult:
    """Tests for formatting a single subagent result."""

    def test_single_result_xml_format(self):
        """Test that single result is formatted in XML structure."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="test-sub-1",
            answer="This is the answer from the subagent.",
            workspace_path="/workspace/test-sub-1",
            execution_time_seconds=25.5,
        )

        formatted = format_single_result("test-sub-1", result)

        # Check XML structure elements
        assert "<subagent_result" in formatted
        assert 'id="test-sub-1"' in formatted
        assert 'status="completed"' in formatted
        assert "</subagent_result>" in formatted

    def test_single_result_includes_answer(self):
        """Test that result includes the subagent answer."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="answer-test",
            answer="Here is my detailed response with multiple lines.\nSecond line here.",
            workspace_path="/workspace/answer-test",
            execution_time_seconds=10.0,
        )

        formatted = format_single_result("answer-test", result)

        assert "Here is my detailed response" in formatted
        assert "Second line here" in formatted

    def test_single_result_includes_execution_time(self):
        """Test that result includes execution time."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="time-test",
            answer="Test answer",
            workspace_path="/workspace/time-test",
            execution_time_seconds=42.5,
        )

        formatted = format_single_result("time-test", result)

        assert "42.5" in formatted or "42" in formatted

    def test_single_result_includes_workspace(self):
        """Test that result includes workspace path."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="workspace-test",
            answer="Test answer",
            workspace_path="/specific/path/to/workspace",
            execution_time_seconds=5.0,
        )

        formatted = format_single_result("workspace-test", result)

        assert "/specific/path/to/workspace" in formatted

    def test_single_result_includes_token_usage(self):
        """Test that result includes token usage when available."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="token-test",
            answer="Test answer",
            workspace_path="/workspace/token-test",
            execution_time_seconds=10.0,
            token_usage={"input_tokens": 1500, "output_tokens": 750},
        )

        formatted = format_single_result("token-test", result)

        # Token usage should be included in some form
        assert "1500" in formatted or "input" in formatted.lower()

    def test_single_result_error_status(self):
        """Test formatting of error result."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_error(
            subagent_id="error-test",
            error="Something went wrong during execution",
            workspace_path="/workspace/error-test",
        )

        formatted = format_single_result("error-test", result)

        assert 'status="error"' in formatted
        assert "Something went wrong" in formatted

    def test_single_result_timeout_status(self):
        """Test formatting of timeout result."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_timeout(
            subagent_id="timeout-test",
            workspace_path="/workspace/timeout-test",
            timeout_seconds=300.0,
        )

        formatted = format_single_result("timeout-test", result)

        assert 'status="timeout"' in formatted

    def test_single_result_completed_but_timeout_status(self):
        """Test formatting of completed_but_timeout result."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="recovery-test",
            workspace_path="/workspace/recovery-test",
            timeout_seconds=300.0,
            recovered_answer="Recovered answer from timeout",
            completion_percentage=85,
        )

        formatted = format_single_result("recovery-test", result)

        assert 'status="completed_but_timeout"' in formatted
        assert "Recovered answer from timeout" in formatted

    def test_single_result_partial_status(self):
        """Test formatting of partial result."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_timeout_with_recovery(
            subagent_id="partial-test",
            workspace_path="/workspace/partial-test",
            timeout_seconds=300.0,
            recovered_answer="Partial work completed",
            completion_percentage=60,
            is_partial=True,
        )

        formatted = format_single_result("partial-test", result)

        assert 'status="partial"' in formatted


# =============================================================================
# Batch Formatting Tests
# =============================================================================


class TestFormatBatchResults:
    """Tests for formatting multiple subagent results."""

    def test_batch_format_multiple_results(self):
        """Test that multiple results are batched together."""
        from massgen.subagent.result_formatter import format_batch_results

        result1 = SubagentResult.create_success(
            subagent_id="batch-1",
            answer="First result",
            workspace_path="/workspace/batch-1",
            execution_time_seconds=10.0,
        )
        result2 = SubagentResult.create_success(
            subagent_id="batch-2",
            answer="Second result",
            workspace_path="/workspace/batch-2",
            execution_time_seconds=15.0,
        )
        result3 = SubagentResult.create_success(
            subagent_id="batch-3",
            answer="Third result",
            workspace_path="/workspace/batch-3",
            execution_time_seconds=20.0,
        )

        results = [
            ("batch-1", result1),
            ("batch-2", result2),
            ("batch-3", result3),
        ]

        formatted = format_batch_results(results)

        # All results should be present
        assert "batch-1" in formatted
        assert "batch-2" in formatted
        assert "batch-3" in formatted
        assert "First result" in formatted
        assert "Second result" in formatted
        assert "Third result" in formatted

    def test_batch_format_includes_count(self):
        """Test that batch format includes count of results."""
        from massgen.subagent.result_formatter import format_batch_results

        result1 = SubagentResult.create_success(
            subagent_id="count-1",
            answer="Result 1",
            workspace_path="/workspace/count-1",
            execution_time_seconds=5.0,
        )
        result2 = SubagentResult.create_success(
            subagent_id="count-2",
            answer="Result 2",
            workspace_path="/workspace/count-2",
            execution_time_seconds=5.0,
        )

        results = [("count-1", result1), ("count-2", result2)]

        formatted = format_batch_results(results)

        # Should indicate count somewhere
        assert "2" in formatted

    def test_batch_format_single_result(self):
        """Test batch formatting with single result still works."""
        from massgen.subagent.result_formatter import format_batch_results

        result = SubagentResult.create_success(
            subagent_id="single",
            answer="Only result",
            workspace_path="/workspace/single",
            execution_time_seconds=5.0,
        )

        results = [("single", result)]

        formatted = format_batch_results(results)

        assert "single" in formatted
        assert "Only result" in formatted

    def test_batch_format_empty_list(self):
        """Test batch formatting with empty list."""
        from massgen.subagent.result_formatter import format_batch_results

        formatted = format_batch_results([])

        # Should return empty or minimal content
        assert formatted == "" or "0" in formatted

    def test_batch_format_mixed_statuses(self):
        """Test batch formatting with mixed status results."""
        from massgen.subagent.result_formatter import format_batch_results

        success_result = SubagentResult.create_success(
            subagent_id="mixed-success",
            answer="Success!",
            workspace_path="/workspace/mixed-success",
            execution_time_seconds=10.0,
        )
        error_result = SubagentResult.create_error(
            subagent_id="mixed-error",
            error="Failed",
            workspace_path="/workspace/mixed-error",
        )
        timeout_result = SubagentResult.create_timeout_with_recovery(
            subagent_id="mixed-timeout",
            workspace_path="/workspace/mixed-timeout",
            timeout_seconds=300.0,
            recovered_answer="Recovered",
            completion_percentage=80,
        )

        results = [
            ("mixed-success", success_result),
            ("mixed-error", error_result),
            ("mixed-timeout", timeout_result),
        ]

        formatted = format_batch_results(results)

        # All statuses should be present
        assert "completed" in formatted
        assert "error" in formatted
        assert "completed_but_timeout" in formatted

    def test_batch_format_preserves_order(self):
        """Test that batch formatting preserves the order of results."""
        from massgen.subagent.result_formatter import format_batch_results

        results = []
        for i in range(5):
            result = SubagentResult.create_success(
                subagent_id=f"order-{i}",
                answer=f"Result {i}",
                workspace_path=f"/workspace/order-{i}",
                execution_time_seconds=float(i),
            )
            results.append((f"order-{i}", result))

        formatted = format_batch_results(results)

        # Check that results appear in order
        pos_0 = formatted.find("order-0")
        pos_1 = formatted.find("order-1")
        pos_2 = formatted.find("order-2")
        pos_3 = formatted.find("order-3")
        pos_4 = formatted.find("order-4")

        assert pos_0 < pos_1 < pos_2 < pos_3 < pos_4


# =============================================================================
# Metadata Formatting Tests
# =============================================================================


class TestResultMetadataFormatting:
    """Tests for metadata inclusion in formatted results."""

    def test_result_includes_all_metadata(self):
        """Test that all relevant metadata is included."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="meta-full",
            answer="Complete answer",
            workspace_path="/full/workspace/path",
            execution_time_seconds=123.45,
            token_usage={"input_tokens": 5000, "output_tokens": 2500},
            log_path="/logs/meta-full",
        )

        formatted = format_single_result("meta-full", result)

        # Check various metadata elements
        assert "meta-full" in formatted
        assert "/full/workspace/path" in formatted
        assert "123" in formatted  # execution time

    def test_result_handles_missing_token_usage(self):
        """Test that result handles missing token usage gracefully."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="no-tokens",
            answer="Answer without token info",
            workspace_path="/workspace/no-tokens",
            execution_time_seconds=10.0,
            # No token_usage provided
        )

        formatted = format_single_result("no-tokens", result)

        # Should format without error
        assert "no-tokens" in formatted
        assert "Answer without token info" in formatted

    def test_result_handles_empty_answer(self):
        """Test that result handles empty/None answer."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult(
            subagent_id="no-answer",
            status="error",
            success=False,
            answer=None,
            workspace_path="/workspace/no-answer",
            error="Failed before generating answer",
        )

        formatted = format_single_result("no-answer", result)

        # Should format without error
        assert "no-answer" in formatted
        assert "error" in formatted.lower()


# =============================================================================
# Edge Cases
# =============================================================================


class TestFormatterEdgeCases:
    """Tests for edge cases in result formatting."""

    def test_special_characters_in_answer(self):
        """Test that special characters in answer are handled."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="special-chars",
            answer='Answer with <xml> tags and &ampersands& and "quotes"',
            workspace_path="/workspace/special-chars",
            execution_time_seconds=5.0,
        )

        formatted = format_single_result("special-chars", result)

        # Should contain the answer (escaping is implementation detail)
        assert "special-chars" in formatted
        # The answer content should be present in some form
        assert "Answer with" in formatted

    def test_very_long_answer(self):
        """Test handling of very long answers."""
        from massgen.subagent.result_formatter import format_single_result

        long_answer = "A" * 10000  # 10k character answer

        result = SubagentResult.create_success(
            subagent_id="long-answer",
            answer=long_answer,
            workspace_path="/workspace/long-answer",
            execution_time_seconds=100.0,
        )

        formatted = format_single_result("long-answer", result)

        # Should format without error
        assert "long-answer" in formatted
        # Answer should be present (full or truncated)
        assert "A" in formatted

    def test_unicode_in_answer(self):
        """Test that unicode characters are handled."""
        from massgen.subagent.result_formatter import format_single_result

        result = SubagentResult.create_success(
            subagent_id="unicode-test",
            answer="Answer with unicode: \u4e2d\u6587 \u65e5\u672c\u8a9e \ud83d\ude00",
            workspace_path="/workspace/unicode-test",
            execution_time_seconds=5.0,
        )

        formatted = format_single_result("unicode-test", result)

        # Should format without error
        assert "unicode-test" in formatted
