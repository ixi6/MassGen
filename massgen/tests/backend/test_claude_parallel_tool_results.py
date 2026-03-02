"""Tests for Claude backend parallel tool result consolidation.

Claude API has two strict requirements when using tool_use blocks:
  1. All tool_result blocks for a given assistant turn MUST be in ONE user message.
  2. That user message MUST immediately follow the assistant message — no intervening
     messages of any kind are allowed between them.

Without consolidation, parallel execution would produce:
  [..., assistant(tool_uses), user(tool_result_1), user(tool_result_2)]

Post-tool hook reminders (strategy='user_message') make it worse:
  [..., assistant(tool_uses), user(tr_1), user(reminder), user(tr_2)]

Both patterns cause the Anthropic API to reject with:
  "messages.N: tool_use ids were found without tool_result blocks immediately after"

ClaudeBackend._merge_parallel_tool_results fixes both:
  1. Consolidates all tool_result blocks into a single user message.
  2. Appends non-tool-result messages (hook reminders) AFTER the consolidated message.
  Result: [..., assistant(tool_uses), user(tr_1, tr_2), user(reminder)]
"""

from __future__ import annotations

import pytest

from massgen.backend.claude import ClaudeBackend


@pytest.fixture()
def backend():
    return ClaudeBackend(api_key="test-key")


class TestMergeParallelToolResults:
    """Unit tests for ClaudeBackend._merge_parallel_tool_results."""

    def _make_tr_msg(self, tool_use_id: str, content: str, is_error: bool = False) -> dict:
        block: dict = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
        if is_error:
            block["is_error"] = True
        return {"role": "user", "content": [block]}

    def test_two_parallel_results_consolidated_into_one_message(self, backend):
        """Two separate tool_result user messages are merged into one."""
        updated_messages = [
            {"role": "user", "content": "Do something."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "tool_b", "input": {}},
                ],
            },
        ]

        per_call_1 = [self._make_tr_msg("toolu_1", "result A")]
        per_call_2 = [self._make_tr_msg("toolu_2", "result B")]

        backend._merge_parallel_tool_results(updated_messages, [per_call_1, per_call_2])

        # Should have exactly one user message with tool_results after the assistant
        assert len(updated_messages) == 3
        last = updated_messages[-1]
        assert last["role"] == "user"
        content = last["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        ids = {block["tool_use_id"] for block in content}
        assert ids == {"toolu_1", "toolu_2"}

    def test_single_tool_unchanged(self, backend):
        """A single per-call message is passed through correctly."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}}],
            },
        ]
        per_call_1 = [self._make_tr_msg("toolu_1", "result")]

        backend._merge_parallel_tool_results(updated_messages, [per_call_1])

        assert len(updated_messages) == 3
        last = updated_messages[-1]
        assert last["role"] == "user"
        assert len(last["content"]) == 1
        assert last["content"][0]["tool_use_id"] == "toolu_1"

    def test_error_results_also_consolidated(self, backend):
        """Error tool_result blocks are consolidated too."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "tool_b", "input": {}},
                ],
            },
        ]
        per_call_1 = [self._make_tr_msg("toolu_1", "result A")]
        per_call_2 = [self._make_tr_msg("toolu_2", "ERROR: boom", is_error=True)]

        backend._merge_parallel_tool_results(updated_messages, [per_call_1, per_call_2])

        assert len(updated_messages) == 3
        last = updated_messages[-1]
        assert len(last["content"]) == 2

    def test_empty_per_call_list_is_noop(self, backend):
        """Empty per-call list leaves updated_messages unchanged."""
        updated_messages = [{"role": "user", "content": "task"}]
        backend._merge_parallel_tool_results(updated_messages, [])
        assert len(updated_messages) == 1

    def test_per_call_messages_with_no_blocks_unchanged(self, backend):
        """Per-call messages that are not tool_result user messages pass through directly."""
        updated_messages: list = []
        # Non-tool-result message (e.g. some other type the backend might emit)
        non_tr_msg = {"role": "user", "content": "plain text, not a tool result"}
        backend._merge_parallel_tool_results(updated_messages, [[non_tr_msg]])
        assert len(updated_messages) == 1
        assert updated_messages[0] is non_tr_msg

    def test_consolidation_order_matches_tool_call_order(self, backend):
        """Tool result blocks appear in the order tools were declared in all_calls."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "tool_b", "input": {}},
                    {"type": "tool_use", "id": "toolu_3", "name": "tool_c", "input": {}},
                ],
            },
        ]
        per_call_1 = [self._make_tr_msg("toolu_1", "first")]
        per_call_2 = [self._make_tr_msg("toolu_2", "second")]
        per_call_3 = [self._make_tr_msg("toolu_3", "third")]

        backend._merge_parallel_tool_results(
            updated_messages,
            [per_call_1, per_call_2, per_call_3],
        )

        content = updated_messages[-1]["content"]
        assert [b["tool_use_id"] for b in content] == ["toolu_1", "toolu_2", "toolu_3"]

    def test_merges_into_existing_tool_result_message(self, backend):
        """If a tool_result user message already exists after the last assistant,
        the new blocks are appended to it (sequential + parallel mixed scenario)."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "tool_b", "input": {}},
                ],
            },
            # Existing tool_result message from a prior sequential call
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "r1"}],
            },
        ]
        per_call_2 = [self._make_tr_msg("toolu_2", "r2")]

        backend._merge_parallel_tool_results(updated_messages, [per_call_2])

        # Still 3 messages total — merged into the existing tool_result message
        assert len(updated_messages) == 3
        last = updated_messages[-1]
        assert len(last["content"]) == 2
        ids = {b["tool_use_id"] for b in last["content"]}
        assert ids == {"toolu_1", "toolu_2"}


class TestHookReminderOrdering:
    """Hook reminders must come AFTER the consolidated tool_result message, never before."""

    def _make_tr_msg(self, tool_use_id: str, content: str) -> dict:
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
        }

    def _make_reminder_msg(self, text: str) -> dict:
        # Hook reminders have string content (not a list), role=user.
        return {"role": "user", "content": text}

    def test_reminder_from_one_tool_placed_after_all_results(self, backend):
        """When one parallel tool fires a hook reminder, tool_results come first."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "tool_b", "input": {}},
                ],
            },
        ]
        # Tool 1 produced a result AND a reminder (from high_priority_task_reminder hook)
        per_call_1 = [
            self._make_tr_msg("toolu_1", "result A"),
            self._make_reminder_msg("⚠️ SYSTEM REMINDER: document decisions"),
        ]
        # Tool 2 produced only a result
        per_call_2 = [self._make_tr_msg("toolu_2", "result B")]

        backend._merge_parallel_tool_results(updated_messages, [per_call_1, per_call_2])

        # 4 messages: system, user, assistant, consolidated_tr, reminder
        assert len(updated_messages) == 4

        tr_msg = updated_messages[2]
        reminder_msg = updated_messages[3]

        # Consolidated tool_result user message is immediately after assistant
        assert tr_msg["role"] == "user"
        assert isinstance(tr_msg["content"], list)
        ids = {b["tool_use_id"] for b in tr_msg["content"]}
        assert ids == {"toolu_1", "toolu_2"}

        # Reminder comes AFTER the tool_result message
        assert reminder_msg["role"] == "user"
        assert isinstance(reminder_msg["content"], str)
        assert "REMINDER" in reminder_msg["content"]

    def test_reminder_not_injected_between_tool_results(self, backend):
        """The reminder cannot end up between the assistant and the tool_result message."""
        updated_messages = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "tool_a", "input": {}},
                ],
            },
        ]
        per_call_1 = [
            self._make_tr_msg("toolu_1", "result"),
            self._make_reminder_msg("DO NOT PUT ME BEFORE TOOL RESULTS"),
        ]

        backend._merge_parallel_tool_results(updated_messages, [per_call_1])

        # Order must be: user[0], assistant[1], user(tool_result)[2], user(reminder)[3]
        assert len(updated_messages) == 4
        assert updated_messages[1]["role"] == "assistant"
        assert updated_messages[2]["content"][0]["type"] == "tool_result"
        assert isinstance(updated_messages[3]["content"], str)


class TestBaseClassDefaultMerge:
    """The base class default should still extend directly (non-Claude backends)."""

    def test_base_extends_directly(self):
        """Default _merge_parallel_tool_results extends without consolidation."""
        from massgen.backend.base_with_custom_tool_and_mcp import (
            CustomToolAndMCPBackend,
        )

        # Use ClaudeBackend to call the BASE method explicitly (to test default behavior)
        # We cannot instantiate the abstract base directly, but we can invoke the
        # default implementation through super().
        class _TestBackend(ClaudeBackend):
            def _merge_parallel_tool_results(self, updated_messages, all_per_call_messages):
                # Call base class implementation
                CustomToolAndMCPBackend._merge_parallel_tool_results(
                    self,
                    updated_messages,
                    all_per_call_messages,
                )

        backend = _TestBackend(api_key="test-key")
        updated_messages: list = []
        msg1 = {"role": "tool", "tool_call_id": "c1", "content": "r1"}
        msg2 = {"role": "tool", "tool_call_id": "c2", "content": "r2"}
        backend._merge_parallel_tool_results(updated_messages, [[msg1], [msg2]])
        # Default: two separate messages preserved (correct for OpenAI)
        assert len(updated_messages) == 2
