"""Regression tests for checklist state label refresh ordering after injection.

The bug: when a peer agent submits a new answer (e.g. agent1.2 replacing
agent1.1), the mid-stream injection calls update_agent_context_with_new_answers
to update the coordination tracker, then must call _refresh_checklist_state_for_agent
AFTER (so it reads the new labels). If refresh happens before the tracker update,
available_agent_labels in the checklist state still has agent1.1, causing the
validation to demand scores for agent1.1 even though the agent only sees agent1.2
in its CURRENT ANSWERS.

Also covers the no-hook fallback path, which previously had no refresh call at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from massgen.coordination_tracker import AgentAnswer, CoordinationTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_answer(agent_id: str, label: str, content: str = "some answer") -> AgentAnswer:
    ans = AgentAnswer.__new__(AgentAnswer)
    ans.agent_id = agent_id
    ans.content = content
    ans.timestamp = 0.0
    ans.changedoc = None
    ans.label = label
    return ans


def _make_tracker_with_multi_round_answers() -> CoordinationTracker:
    """Return a tracker simulating a realistic multi-round scenario.

    agent_a is currently working on its next answer. It already has both
    agent1.4 (its own previous answer, shown via context) and agent2.2 in
    its context. agent_b just submitted agent2.3, which will be injected
    into agent_a mid-stream.
    """
    tracker = CoordinationTracker()
    tracker.agent_ids = ["agent_a", "agent_b"]
    tracker.agent_context_labels = {
        # agent_a currently sees agent1.4 (own prior round) and agent2.2
        "agent_a": ["agent1.4", "agent2.2"],
        "agent_b": ["agent1.4"],
    }
    tracker.answers_by_agent = {
        "agent_a": [
            _make_answer("agent_a", "agent1.1"),
            _make_answer("agent_a", "agent1.2"),
            _make_answer("agent_a", "agent1.3"),
            _make_answer("agent_a", "agent1.4"),
        ],
        "agent_b": [
            _make_answer("agent_b", "agent2.1"),
            _make_answer("agent_b", "agent2.2"),
            _make_answer("agent_b", "agent2.3"),  # just submitted, not yet in agent_a's context
        ],
    }
    return tracker


def _make_orchestrator_with_checklist(tracker: CoordinationTracker):
    """Build a minimal Orchestrator stub with a real tracker and checklist state."""
    from massgen.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.coordination_tracker = tracker
    orch.config = MagicMock()
    orch.config.max_new_answers_per_agent = 5
    orch.config.checklist_require_gap_report = False

    # Backend stub with a _checklist_state dict — reflects what agent_a currently
    # sees: agent1.4 and agent2.2 (agent2.3 not yet injected)
    backend = MagicMock()
    backend._checklist_state = {
        "threshold": 5,
        "total": 5,
        "available_agent_labels": ["agent1.4", "agent2.2"],  # stale, pre-injection
    }
    backend._checklist_items = ["item1", "item2"]
    del backend._checklist_specs_path  # no specs file

    agent = MagicMock()
    agent.backend = backend
    orch.agents = {"agent_a": agent}
    orch.agent_states = {"agent_a": MagicMock(answer_count=4)}

    # Minimal method stubs needed by _refresh_checklist_state_for_agent
    orch._get_agent_answer_count_for_limit = MagicMock(return_value=4)
    orch._is_changedoc_enabled = MagicMock(return_value=False)

    return orch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChecklistLabelRefreshOrdering:
    """available_agent_labels in checklist state must reflect post-injection labels.

    Scenario: agent_a is mid-stream, has seen agent1.4 (own prior) and agent2.2.
    agent_b just submitted agent2.3. The injection delivers agent2.3 to agent_a.
    After injection, agent_a's checklist state must require scores for agent2.3,
    not the stale agent2.2.
    """

    def test_refresh_after_update_sees_new_label(self):
        """Correct order: update tracker first, then refresh checklist state.

        agent2.3 replaces agent2.2 in agent_a's available_agent_labels.
        agent1.4 (own prior answer, also in context) is preserved.
        """
        tracker = _make_tracker_with_multi_round_answers()
        orch = _make_orchestrator_with_checklist(tracker)

        # Correct order (the fix):
        tracker.update_agent_context_with_new_answers("agent_a", ["agent_b"])
        orch._refresh_checklist_state_for_agent("agent_a")

        labels = orch.agents["agent_a"].backend._checklist_state["available_agent_labels"]
        assert "agent2.3" in labels, f"Expected agent2.3 in labels, got: {labels}"
        assert "agent2.2" not in labels, f"Stale agent2.2 should be replaced, got: {labels}"
        assert "agent1.4" in labels, f"agent1.4 (own prior) should still be present, got: {labels}"

    def test_refresh_before_update_produces_stale_labels(self):
        """Regression: wrong order leaves stale labels — documents the original bug.

        If this test ever starts failing (stale agent2.2 is gone even with wrong
        order), something else has changed and this test needs re-evaluation.
        """
        tracker = _make_tracker_with_multi_round_answers()
        orch = _make_orchestrator_with_checklist(tracker)

        # Wrong order (the bug): refresh reads OLD tracker state, then tracker updates
        orch._refresh_checklist_state_for_agent("agent_a")
        tracker.update_agent_context_with_new_answers("agent_a", ["agent_b"])

        labels = orch.agents["agent_a"].backend._checklist_state["available_agent_labels"]
        assert "agent2.2" in labels, f"Wrong-order refresh should leave stale agent2.2 in labels (original bug). Got: {labels}"
        assert "agent2.3" not in labels, f"agent2.3 should not appear with wrong order. Got: {labels}"

    def test_no_hook_fallback_refresh_sees_new_label(self):
        """No-hook fallback must also refresh after updating tracker context.

        Previously the no-hook path called update_agent_context_with_new_answers
        but never called _refresh_checklist_state_for_agent at all, leaving
        available_agent_labels permanently stale for that injection.
        """
        tracker = _make_tracker_with_multi_round_answers()
        orch = _make_orchestrator_with_checklist(tracker)

        # Simulate the no-hook fallback path (fix adds the refresh):
        tracker.update_agent_context_with_new_answers("agent_a", ["agent_b"])
        orch._refresh_checklist_state_for_agent("agent_a")

        labels = orch.agents["agent_a"].backend._checklist_state["available_agent_labels"]
        assert "agent2.3" in labels, f"Expected agent2.3 in labels, got: {labels}"
        assert "agent2.2" not in labels, f"Stale agent2.2 should be replaced, got: {labels}"
        assert "agent1.4" in labels, f"agent1.4 (own prior) should still be present, got: {labels}"
