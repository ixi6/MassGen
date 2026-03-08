"""Integration tests for changedoc flow through coordination.

Tests cover:
- AgentAnswer storing changedoc field
- Changedoc appearing in observation context
"""

from massgen.coordination_tracker import AgentAnswer
from massgen.message_templates import MessageTemplates


class TestAgentAnswerChangedoc:
    """Tests for AgentAnswer changedoc field."""

    def test_changedoc_defaults_to_none(self):
        """AgentAnswer.changedoc is None by default."""
        answer = AgentAnswer(agent_id="agent_a", content="My answer", timestamp=1.0)
        assert answer.changedoc is None

    def test_changedoc_can_be_set(self):
        """AgentAnswer.changedoc can be assigned."""
        answer = AgentAnswer(agent_id="agent_a", content="My answer", timestamp=1.0)
        answer.changedoc = "# Change Document\n## Summary\nUsed caching."
        assert answer.changedoc == "# Change Document\n## Summary\nUsed caching."

    def test_changedoc_via_constructor(self):
        """AgentAnswer.changedoc can be set via constructor."""
        answer = AgentAnswer(
            agent_id="agent_a",
            content="My answer",
            timestamp=1.0,
            changedoc="# Change Document",
        )
        assert answer.changedoc == "# Change Document"


class TestChangedocInObservationContext:
    """Tests for changedoc appearing in format_current_answers_with_summaries."""

    def test_changedoc_included_when_provided(self):
        """Changedoc content appears within agent block when agent_changedocs is passed."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer about caching."}
        mapping = {"agent_a": "agent1"}
        changedocs = {"agent_a": "# Change Document\n## Summary\nChose caching."}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            agent_changedocs=changedocs,
        )

        assert "<changedoc>" in result
        assert "Chose caching." in result
        assert "</changedoc>" in result
        assert "<agent1>" in result
        assert "<end of agent1>" in result

    def test_no_changedoc_when_not_provided(self):
        """No changedoc tags appear when agent_changedocs is None."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer about caching."}
        mapping = {"agent_a": "agent1"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
        )

        assert "<changedoc>" not in result
        assert "</changedoc>" not in result

    def test_changedoc_for_some_agents_only(self):
        """Changedoc only appears for agents that have one."""
        mt = MessageTemplates()
        summaries = {
            "agent_a": "Answer A",
            "agent_b": "Answer B",
        }
        mapping = {"agent_a": "agent1", "agent_b": "agent2"}
        changedocs = {"agent_a": "# Changedoc for A"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            agent_changedocs=changedocs,
        )

        # Agent A has changedoc
        assert "# Changedoc for A" in result
        # Agent B block has no changedoc
        lines = result.split("\n")
        agent2_lines = [line for line in lines if "agent2" in line]
        for line in agent2_lines:
            assert "<changedoc>" not in line

    def test_empty_changedocs_dict(self):
        """Empty changedocs dict behaves like None."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer."}
        mapping = {"agent_a": "agent1"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            agent_changedocs={},
        )

        assert "<changedoc>" not in result


class TestVersionedAnswerLabels:
    """Tests for versioned answer labels (agent1.2) in CURRENT ANSWERS."""

    def test_format_answers_with_versioned_labels(self):
        """When answer_label_mapping is provided, headers use versioned labels."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer.", "agent_b": "Their answer."}
        mapping = {"agent_a": "agent1", "agent_b": "agent2"}
        label_mapping = {"agent_a": "agent1.2", "agent_b": "agent2.1"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            answer_label_mapping=label_mapping,
        )

        assert "<agent1.2>" in result
        assert "<end of agent1.2>" in result
        assert "<agent2.1>" in result
        assert "<end of agent2.1>" in result
        # Base labels should NOT appear as headers
        assert "<agent1>" not in result
        assert "<agent2>" not in result

    def test_format_answers_without_label_mapping_uses_base(self):
        """When no answer_label_mapping, falls back to base agent1 behavior."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer."}
        mapping = {"agent_a": "agent1"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
        )

        assert "<agent1>" in result
        assert "<end of agent1>" in result

    def test_format_answers_with_changedoc_and_versioned_labels(self):
        """Versioned labels work alongside changedoc injection."""
        mt = MessageTemplates()
        summaries = {"agent_a": "My answer."}
        mapping = {"agent_a": "agent1"}
        label_mapping = {"agent_a": "agent1.3"}
        changedocs = {"agent_a": "# Change Document\n## Summary\nApproach."}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            agent_changedocs=changedocs,
            answer_label_mapping=label_mapping,
        )

        assert "<agent1.3>" in result
        assert "<end of agent1.3>" in result
        assert "<changedoc>" in result
        assert "# Change Document" in result

    def test_partial_label_mapping_falls_back(self):
        """Agents without a versioned label fall back to base anonymous ID."""
        mt = MessageTemplates()
        summaries = {"agent_a": "Answer A.", "agent_b": "Answer B."}
        mapping = {"agent_a": "agent1", "agent_b": "agent2"}
        # Only agent_a has a versioned label
        label_mapping = {"agent_a": "agent1.2"}

        result = mt.format_current_answers_with_summaries(
            summaries,
            agent_mapping=mapping,
            answer_label_mapping=label_mapping,
        )

        assert "<agent1.2>" in result
        assert "<agent2>" in result  # Falls back to base


class TestSelfPlaceholderReplacement:
    """Tests for [SELF] placeholder replacement in changedoc content."""

    def test_self_placeholder_replaced_in_changedoc(self):
        """[SELF] in changedoc content is replaced with the real answer label."""
        answer = AgentAnswer(agent_id="agent_a", content="My answer", timestamp=1.0)
        answer.label = "agent1.2"
        answer.changedoc = "**Origin:** [SELF] — NEW\n### [SELF] (based on agent2.1):"

        # Simulate the replacement the orchestrator performs
        answer.changedoc = answer.changedoc.replace("[SELF]", answer.label)

        assert "[SELF]" not in answer.changedoc
        assert "agent1.2" in answer.changedoc
        assert "**Origin:** agent1.2 — NEW" in answer.changedoc
        assert "### agent1.2 (based on agent2.1):" in answer.changedoc

    def test_self_placeholder_not_replaced_when_absent(self):
        """Changedoc without [SELF] passes through unchanged."""
        answer = AgentAnswer(agent_id="agent_a", content="My answer", timestamp=1.0)
        answer.label = "agent1.1"
        original = "**Origin:** agent1.1 — NEW\nNo placeholders here."
        answer.changedoc = original

        # Replacement is a no-op when [SELF] is absent
        answer.changedoc = answer.changedoc.replace("[SELF]", answer.label)

        assert answer.changedoc == original

    def test_self_placeholder_multiple_occurrences(self):
        """All instances of [SELF] are replaced, not just the first."""
        answer = AgentAnswer(agent_id="agent_b", content="Answer", timestamp=2.0)
        answer.label = "agent2.3"
        answer.changedoc = "**Origin:** [SELF] — NEW\n" "modified by [SELF]\n" "### [SELF] (based on agent1.2):\n" "- DEC-001: [SELF] introduced caching"

        answer.changedoc = answer.changedoc.replace("[SELF]", answer.label)

        assert answer.changedoc.count("agent2.3") == 4
        assert "[SELF]" not in answer.changedoc
